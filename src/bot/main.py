"""Stateless bot runtime for Contadores webhooks and dispatch loops."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

try:
    from .logging_utils import (
        BotLogState,
        configure_runtime_logging,
        log_dispatch_activity,
        log_whatsapp_inbound_activity,
        log_whatsapp_status_activity,
        note_backend_issue,
        note_backend_recovered,
    )
    from .providers import AgentMailProvider, WhatsAppInboundEvent, WhatsAppMessageStatusEvent, WhatsAppProvider
    from .utils import (
        BACKEND_BOOT_POLL_SECONDS,
        BACKEND_BOOT_TIMEOUT_SECONDS,
        BOT_TICK_SECONDS,
        build_backend_client,
        dispatch_pending_contadores_messages,
        fetch_funnels,
        fetch_pending_contadores_outbound,
        process_whatsapp_inbound_event,
        process_whatsapp_message_status_event,
        register_contadores_calendly_event,
        run_contadores_automation_iteration,
        run_contadores_sheet_sync_iteration,
        send_contadores_pending_alerts,
        wait_for_backend_ready,
    )
except ImportError:
    from logging_utils import (
        BotLogState,
        configure_runtime_logging,
        log_dispatch_activity,
        log_whatsapp_inbound_activity,
        log_whatsapp_status_activity,
        note_backend_issue,
        note_backend_recovered,
    )
    from providers import AgentMailProvider, WhatsAppInboundEvent, WhatsAppMessageStatusEvent, WhatsAppProvider
    from utils import (
        BACKEND_BOOT_POLL_SECONDS,
        BACKEND_BOOT_TIMEOUT_SECONDS,
        BOT_TICK_SECONDS,
        build_backend_client,
        dispatch_pending_contadores_messages,
        fetch_funnels,
        fetch_pending_contadores_outbound,
        process_whatsapp_inbound_event,
        process_whatsapp_message_status_event,
        register_contadores_calendly_event,
        run_contadores_automation_iteration,
        run_contadores_sheet_sync_iteration,
        send_contadores_pending_alerts,
        wait_for_backend_ready,
    )

logger = configure_runtime_logging()
LOG_STATE = BotLogState()
CALENDLY_WEBHOOK_SIGNING_KEY = (os.getenv("CALENDLY_WEBHOOK_SIGNING_KEY", "") or "").strip()


def verify_calendly_signature(*, payload: bytes, signature_header: str | None) -> bool:
    """Best-effort Calendly webhook signature verification."""
    if not CALENDLY_WEBHOOK_SIGNING_KEY:
        return True
    header_value = (signature_header or "").strip()
    if not header_value:
        return False
    parts: dict[str, str] = {}
    for piece in header_value.split(","):
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        parts[key.strip()] = value.strip()
    provided_signature = parts.get("v1") or parts.get("signature") or header_value
    expected_signature = hmac.new(
        CALENDLY_WEBHOOK_SIGNING_KEY.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided_signature, expected_signature)


def extract_nested_utm_content(payload: Any) -> str | None:
    """Recursively search a Calendly webhook payload for utm_content."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).strip().lower() == "utm_content":
                clean_value = str(value or "").strip()
                if clean_value:
                    return clean_value
            nested = extract_nested_utm_content(value)
            if nested:
                return nested
    if isinstance(payload, list):
        for item in payload:
            nested = extract_nested_utm_content(item)
            if nested:
                return nested
    return None


async def run_worker_iteration(
    *,
    backend_client: httpx.AsyncClient,
    email_provider: AgentMailProvider,
    whatsapp_provider: WhatsAppProvider,
) -> None:
    """Advance automation, send alerts, and dispatch pending WhatsApp messages."""
    funnels = await fetch_funnels(backend_client)
    if not funnels:
        return

    for funnel in funnels:
        if not funnel.enabled:
            continue
        automation_summary = await run_contadores_automation_iteration(
            backend_client,
            funnel_id=funnel.id,
        )
        if any(
            automation_summary.get(key)
            for key in [
                "opener_sent",
                "loom_sent",
                "video_checks_sent",
                "classified_wants_to_proceed",
                "classified_needs_human",
                "calendly_sent",
            ]
        ):
            logger.info("%s automation summary: %s", funnel.label, automation_summary)

        alert_results = await send_contadores_pending_alerts(
            backend_client,
            email_provider=email_provider,
            funnel_id=funnel.id,
            funnel_label=funnel.label,
        )
        sent_alerts = [item for item in alert_results if item.get("status") == "sent"]
        if sent_alerts:
            logger.info("%s alerts sent: %s", funnel.label, sent_alerts)

    pending_contadores = await fetch_pending_contadores_outbound(backend_client, limit=200)
    contadores_dispatch_results = await dispatch_pending_contadores_messages(
        backend_client,
        pending=pending_contadores,
        whatsapp_provider=whatsapp_provider,
    )
    log_dispatch_activity(logger, contadores_dispatch_results, LOG_STATE)


async def run_worker_loop(
    *,
    backend_client: httpx.AsyncClient,
    email_provider: AgentMailProvider,
    whatsapp_provider: WhatsAppProvider,
) -> None:
    """Run the continuous Contadores worker loop."""
    last_sheet_sync_at_by_funnel: dict[str, float] = {}
    try:
        while True:
            try:
                await run_worker_iteration(
                    backend_client=backend_client,
                    email_provider=email_provider,
                    whatsapp_provider=whatsapp_provider,
                )
                note_backend_recovered(logger, LOG_STATE)

                now = asyncio.get_running_loop().time()
                for funnel in await fetch_funnels(backend_client):
                    if not funnel.enabled:
                        continue
                    sheet_poll_seconds = max(60, int(funnel.sheet_poll_seconds or 300))
                    last_sync_at = last_sheet_sync_at_by_funnel.get(funnel.id, 0.0)
                    if now - last_sync_at < sheet_poll_seconds:
                        continue
                    last_sheet_sync_at_by_funnel[funnel.id] = now
                    try:
                        sheet_summary = await run_contadores_sheet_sync_iteration(
                            backend_client,
                            funnel_id=funnel.id,
                            funnel=funnel,
                        )
                    except Exception:
                        logger.exception("%s sheet sync iteration failed.", funnel.label)
                    else:
                        if sheet_summary.get("status") == "ok":
                            logger.info("%s sheet sync summary: %s", funnel.label, sheet_summary)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response else "unknown"
                request_url = str(exc.request.url) if exc.request else "unknown"
                note_backend_issue(
                    logger,
                    LOG_STATE,
                    f"Backend returned HTTP {status_code} for {request_url}. The bot will retry automatically.",
                )
            except httpx.RequestError as exc:
                note_backend_issue(
                    logger,
                    LOG_STATE,
                    f"Backend is unavailable ({exc}). The bot will retry automatically.",
                )
            except Exception:
                logger.exception("The worker loop crashed during one cycle.")
            await asyncio.sleep(BOT_TICK_SECONDS)
    except asyncio.CancelledError:
        logger.info("Bot worker loop stopped.")


async def handle_whatsapp_inbound(
    *,
    backend_client: httpx.AsyncClient,
    event: WhatsAppInboundEvent,
) -> dict[str, Any]:
    """Process one inbound WhatsApp event through the Contadores backend."""
    result = await process_whatsapp_inbound_event(
        backend_client,
        event=event,
    )
    log_whatsapp_inbound_activity(logger, result)
    return result


async def handle_whatsapp_status(
    *,
    backend_client: httpx.AsyncClient,
    event: WhatsAppMessageStatusEvent,
) -> dict[str, Any]:
    """Persist one outbound WhatsApp status update."""
    result = await process_whatsapp_message_status_event(
        backend_client,
        event=event,
    )
    log_whatsapp_status_activity(logger, result)
    return result


async def handle_calendly_webhook(
    *,
    backend_client: httpx.AsyncClient,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile Calendly bookings back into the Contadores lead state."""
    event_type = str(payload.get("event") or payload.get("event_type") or "").strip() or "unknown"
    token = extract_nested_utm_content(payload)
    if not token:
        return {"status": "ignored", "reason": "missing_utm_content", "event_type": event_type}
    result = await register_contadores_calendly_event(
        backend_client,
        token=token,
        event_type=event_type,
        occurred_at=None,
    )
    result["event_type"] = event_type
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize providers, backend client, and worker loop."""
    logger.info("Bot online. Starting Contadores delivery and webhook workers.")

    backend_client = build_backend_client()
    backend_ready = await wait_for_backend_ready(
        backend_client,
        timeout_seconds=BACKEND_BOOT_TIMEOUT_SECONDS,
        poll_seconds=BACKEND_BOOT_POLL_SECONDS,
    )
    if backend_ready:
        logger.info("Backend connection ready.")
    else:
        logger.warning(
            "Backend was not reachable after %ss. The bot will keep retrying.",
            BACKEND_BOOT_TIMEOUT_SECONDS,
        )

    email_provider = AgentMailProvider()
    await email_provider.initialize()

    async def on_whatsapp_inbound(event: WhatsAppInboundEvent) -> None:
        try:
            await handle_whatsapp_inbound(
                backend_client=backend_client,
                event=event,
            )
        except Exception:
            logger.exception("Failed to process an inbound WhatsApp event.")

    async def on_whatsapp_status(event: WhatsAppMessageStatusEvent) -> None:
        try:
            await handle_whatsapp_status(
                backend_client=backend_client,
                event=event,
            )
        except Exception:
            logger.exception("Failed to process a WhatsApp delivery update.")

    whatsapp_provider = WhatsAppProvider(app, on_whatsapp_inbound, on_whatsapp_status)
    worker_task = asyncio.create_task(
        run_worker_loop(
            backend_client=backend_client,
            email_provider=email_provider,
            whatsapp_provider=whatsapp_provider,
        )
    )

    app.state.backend_client = backend_client
    app.state.email_provider = email_provider
    app.state.whatsapp_provider = whatsapp_provider
    app.state.worker_task = worker_task

    try:
        yield
    finally:
        logger.info("Shutting down the bot.")
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        await email_provider.close()
        await whatsapp_provider.close()
        await backend_client.aclose()


app = FastAPI(
    title="Contadores Bot",
    description="FastAPI webhook runtime plus backend-driven Contadores worker",
    version="0.2.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/webhook/calendly")
async def calendly_webhook(request: Request) -> dict[str, Any]:
    """Receive Calendly webhook events and reconcile bookings into Contadores."""
    backend_client = getattr(app.state, "backend_client", None)
    if backend_client is None:
        raise HTTPException(status_code=503, detail="Backend runtime is not ready")

    raw_body = await request.body()
    if not verify_calendly_signature(
        payload=raw_body,
        signature_header=request.headers.get("Calendly-Webhook-Signature"),
    ):
        raise HTTPException(status_code=401, detail="Invalid Calendly webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    return await handle_calendly_webhook(
        backend_client=backend_client,
        payload=payload if isinstance(payload, dict) else {"payload": payload},
    )
