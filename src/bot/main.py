"""Stateless bot runtime: webhook ingress + periodic dispatch loops."""

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
    from .providers import (
        AgentMailProvider,
        GmailProvider,
        WhatsAppInboundEvent,
        WhatsAppMessageStatusEvent,
        WhatsAppProvider,
    )
    from .logging_utils import (
        BotLogState,
        configure_runtime_logging,
        log_audit_delivery_activity,
        log_dispatch_activity,
        log_email_inbound_activity,
        log_whatsapp_inbound_activity,
        log_whatsapp_status_activity,
        note_backend_issue,
        note_backend_recovered,
    )
    from .utils import (
        AUTOMATED_AUDITOR_INTAKE_ENABLED,
        AUTOMATED_AUDITOR_INTAKE_POLL_SECONDS,
        AUDIT_DELIVERY_POLL_SECONDS,
        BACKEND_BOOT_POLL_SECONDS,
        BACKEND_BOOT_TIMEOUT_SECONDS,
        BOT_TICK_SECONDS,
        build_backend_client,
        dispatch_pending_contadores_messages,
        dispatch_pending_crm_messages,
        dispatch_pending_messages,
        fetch_contadores_config,
        fetch_pending_contadores_outbound,
        fetch_tracked_email_senders,
        fetch_pending_crm_outbound,
        fetch_pending_outbound,
        process_email_inbound_events,
        process_legacy_gmail_inbound_events,
        poll_gmail_inbound_batch,
        register_contadores_calendly_event,
        send_contadores_pending_alerts,
        update_backend_message_delivery_status_by_external_id,
        process_whatsapp_message_status_event,
        process_whatsapp_inbound_event,
        run_automated_auditor_intake_iteration,
        run_audit_delivery_iteration,
        run_contadores_automation_iteration,
        run_contadores_sheet_sync_iteration,
        wait_for_backend_ready,
    )
except ImportError:
    from providers import AgentMailProvider, GmailProvider, WhatsAppInboundEvent, WhatsAppMessageStatusEvent, WhatsAppProvider
    from logging_utils import (
        BotLogState,
        configure_runtime_logging,
        log_audit_delivery_activity,
        log_dispatch_activity,
        log_email_inbound_activity,
        log_whatsapp_inbound_activity,
        log_whatsapp_status_activity,
        note_backend_issue,
        note_backend_recovered,
    )
    from utils import (
        AUTOMATED_AUDITOR_INTAKE_ENABLED,
        AUTOMATED_AUDITOR_INTAKE_POLL_SECONDS,
        AUDIT_DELIVERY_POLL_SECONDS,
        BACKEND_BOOT_POLL_SECONDS,
        BACKEND_BOOT_TIMEOUT_SECONDS,
        BOT_TICK_SECONDS,
        build_backend_client,
        dispatch_pending_contadores_messages,
        dispatch_pending_crm_messages,
        dispatch_pending_messages,
        fetch_contadores_config,
        fetch_pending_contadores_outbound,
        fetch_tracked_email_senders,
        fetch_pending_crm_outbound,
        fetch_pending_outbound,
        process_email_inbound_events,
        process_legacy_gmail_inbound_events,
        poll_gmail_inbound_batch,
        register_contadores_calendly_event,
        send_contadores_pending_alerts,
        update_backend_message_delivery_status_by_external_id,
        process_whatsapp_message_status_event,
        process_whatsapp_inbound_event,
        run_automated_auditor_intake_iteration,
        run_audit_delivery_iteration,
        run_contadores_automation_iteration,
        run_contadores_sheet_sync_iteration,
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
    backend_client,
    email_provider: AgentMailProvider,
    legacy_gmail_provider: GmailProvider,
    whatsapp_provider: WhatsAppProvider,
) -> None:
    """Run one full outbound dispatch iteration."""
    if legacy_gmail_provider.configured:
        tracked_email_senders = await fetch_tracked_email_senders(backend_client)
        legacy_events = await poll_gmail_inbound_batch(
            legacy_gmail_provider,
            max_results=50,
            tracked_senders=tracked_email_senders,
        )
        if legacy_events:
            legacy_results = await process_legacy_gmail_inbound_events(
                backend_client,
                gmail_provider=legacy_gmail_provider,
                events=legacy_events,
            )
            log_email_inbound_activity(logger, legacy_results)

    if email_provider.configured:
        polled_events = await email_provider.poll_inbound_events(limit_per_inbox=20)
        if polled_events:
            inbound_results = await process_email_inbound_events(
                backend_client,
                email_provider=email_provider,
                events=polled_events,
            )
            log_email_inbound_activity(logger, inbound_results)

    contadores_automation_summary = await run_contadores_automation_iteration(backend_client)
    if any(
        contadores_automation_summary.get(key)
        for key in [
            "opener_sent",
            "loom_sent",
            "video_checks_sent",
            "classified_wants_to_proceed",
            "classified_needs_human",
            "calendly_sent",
        ]
    ):
        logger.info("📟 Contadores automation summary: %s", contadores_automation_summary)

    contadores_alert_results = await send_contadores_pending_alerts(
        backend_client,
        email_provider=email_provider,
    )
    sent_alerts = [item for item in contadores_alert_results if item.get("status") == "sent"]
    if sent_alerts:
        logger.info("📧 Contadores alerts sent: %s", sent_alerts)

    pending = await fetch_pending_outbound(backend_client, limit=200)
    pending_contadores = await fetch_pending_contadores_outbound(backend_client, limit=200)
    pending_crm = await fetch_pending_crm_outbound(backend_client, limit=200)
    dispatch_results = await dispatch_pending_messages(
        backend_client,
        pending=pending,
        email_provider=email_provider,
        whatsapp_provider=whatsapp_provider,
    )
    contadores_dispatch_results = await dispatch_pending_contadores_messages(
        backend_client,
        pending=pending_contadores,
        whatsapp_provider=whatsapp_provider,
    )
    crm_dispatch_results = await dispatch_pending_crm_messages(
        backend_client,
        pending=pending_crm,
        email_provider=email_provider,
    )
    log_dispatch_activity(
        logger,
        dispatch_results + contadores_dispatch_results + crm_dispatch_results,
        LOG_STATE,
    )


async def run_worker_loop(
    *,
    backend_client,
    email_provider: AgentMailProvider,
    legacy_gmail_provider: GmailProvider,
    whatsapp_provider: WhatsAppProvider,
) -> None:
    """Run continuous stateless worker loop."""
    last_audit_delivery_at = 0.0
    last_contadores_sheet_sync_at = 0.0
    try:
        while True:
            try:
                await run_worker_iteration(
                    backend_client=backend_client,
                    email_provider=email_provider,
                    legacy_gmail_provider=legacy_gmail_provider,
                    whatsapp_provider=whatsapp_provider,
                )
                note_backend_recovered(logger, LOG_STATE)
                now = asyncio.get_running_loop().time()
                if now - last_audit_delivery_at >= AUDIT_DELIVERY_POLL_SECONDS:
                    last_audit_delivery_at = now
                    try:
                        audit_summary = await run_audit_delivery_iteration(
                            backend_client,
                            email_provider=email_provider,
                        )
                    except Exception:
                        logger.exception("❌ Audit delivery iteration failed.")
                    else:
                        log_audit_delivery_activity(logger, audit_summary)
                contadores_config = await fetch_contadores_config(backend_client)
                sheet_poll_seconds = max(60, int(contadores_config.sheet_poll_seconds or 300))
                if now - last_contadores_sheet_sync_at >= sheet_poll_seconds:
                    last_contadores_sheet_sync_at = now
                    try:
                        sheet_summary = await run_contadores_sheet_sync_iteration(backend_client)
                    except Exception:
                        logger.exception("❌ Contadores sheet sync iteration failed.")
                    else:
                        if sheet_summary.get("status") == "ok":
                            logger.info("📄 Contadores sheet sync summary: %s", sheet_summary)
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
                logger.exception("❌ The worker loop crashed during one cycle.")
            await asyncio.sleep(BOT_TICK_SECONDS)
    except asyncio.CancelledError:
        logger.info("🛑 Bot worker loop stopped.")


async def run_company_intake_loop(
    *,
    backend_client,
) -> None:
    """Run the daily company intake loop on its own cadence."""
    if not AUTOMATED_AUDITOR_INTAKE_ENABLED:
        logger.info("ℹ️ Automated auditor intake is disabled.")
        return

    try:
        while True:
            try:
                summary = await run_automated_auditor_intake_iteration(backend_client)
                if summary.get("status") not in {"before_window", "quota_met"}:
                    logger.info("📥 Automated auditor intake summary: %s", summary)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response else "unknown"
                request_url = str(exc.request.url) if exc.request else "unknown"
                note_backend_issue(
                    logger,
                    LOG_STATE,
                    f"Backend returned HTTP {status_code} for {request_url}. The intake loop will retry automatically.",
                )
            except httpx.RequestError as exc:
                note_backend_issue(
                    logger,
                    LOG_STATE,
                    f"Backend is unavailable for automated intake ({exc}). The intake loop will retry automatically.",
                )
            except Exception:
                logger.exception("❌ The automated intake loop crashed during one cycle.")
            await asyncio.sleep(AUTOMATED_AUDITOR_INTAKE_POLL_SECONDS)
    except asyncio.CancelledError:
        logger.info("🛑 Automated auditor intake loop stopped.")


def start_company_intake_task(*, backend_client) -> asyncio.Task[None] | None:
    """Start the automated intake loop only when the feature flag is enabled."""
    if not AUTOMATED_AUDITOR_INTAKE_ENABLED:
        logger.info("ℹ️ Automated auditor intake task is disabled and will not be scheduled.")
        return None
    return asyncio.create_task(
        run_company_intake_loop(
            backend_client=backend_client,
        )
    )


async def handle_agentmail_received(
    *,
    backend_client,
    email_provider: AgentMailProvider,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Process one inbound AgentMail webhook event."""
    event = email_provider.build_inbound_event(payload)
    if event is None:
        return {"status": "ignored", "reason": "missing_message_payload"}

    results = await process_email_inbound_events(
        backend_client,
        email_provider=email_provider,
        events=[event],
    )
    log_email_inbound_activity(logger, results)
    return {
        "status": "processed",
        "event_type": "message.received",
        "results": results,
    }


async def handle_agentmail_delivery_update(
    *,
    backend_client,
    payload: dict[str, Any],
    target_status: str,
) -> dict[str, Any]:
    """Persist one AgentMail delivery status update."""
    external_id = str(
        payload.get("message_id")
        or (payload.get("message") or {}).get("message_id")
        or ""
    ).strip()
    if not external_id:
        return {"status": "ignored", "reason": "missing_message_id"}

    try:
        result = await update_backend_message_delivery_status_by_external_id(
            backend_client,
            external_id=external_id,
            status=target_status,
        )
        result["provider_status"] = target_status
        return result
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {
                "status": "ignored",
                "reason": "external_id_not_found",
                "external_id": external_id,
                "provider_status": target_status,
            }
        raise


async def handle_whatsapp_inbound(
    *,
    backend_client,
    event: WhatsAppInboundEvent,
) -> dict[str, Any]:
    """Process one inbound WhatsApp event through backend contact pipeline."""
    result = await process_whatsapp_inbound_event(
        backend_client,
        event=event,
    )
    log_whatsapp_inbound_activity(logger, result)
    return result


async def handle_whatsapp_status(
    *,
    backend_client,
    event: WhatsAppMessageStatusEvent,
) -> dict[str, Any]:
    """Process one outbound WhatsApp status event through backend delivery pipeline."""
    result = await process_whatsapp_message_status_event(
        backend_client,
        event=event,
    )
    log_whatsapp_status_activity(logger, result)
    return result


async def handle_calendly_webhook(
    *,
    backend_client,
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
    logger.info("🚀 Bot online. Starting delivery and webhook workers.")

    backend_client = build_backend_client()
    backend_ready = await wait_for_backend_ready(
        backend_client,
        timeout_seconds=BACKEND_BOOT_TIMEOUT_SECONDS,
        poll_seconds=BACKEND_BOOT_POLL_SECONDS,
    )
    if backend_ready:
        logger.info("✅ Backend connection ready.")
    else:
        logger.warning(
            "⚠️ Backend was not reachable after %ss. The bot will keep retrying.",
            BACKEND_BOOT_TIMEOUT_SECONDS,
        )
    email_provider = AgentMailProvider()
    await email_provider.initialize()
    legacy_gmail_provider = GmailProvider()

    async def on_whatsapp_inbound(event: WhatsAppInboundEvent) -> None:
        try:
            await handle_whatsapp_inbound(
                backend_client=backend_client,
                event=event,
            )
        except Exception:
            logger.exception("❌ Failed to process an inbound WhatsApp event.")

    async def on_whatsapp_status(event: WhatsAppMessageStatusEvent) -> None:
        try:
            await handle_whatsapp_status(
                backend_client=backend_client,
                event=event,
            )
        except Exception:
            logger.exception("❌ Failed to process a WhatsApp delivery update.")

    whatsapp_provider = WhatsAppProvider(app, on_whatsapp_inbound, on_whatsapp_status)
    worker_task = asyncio.create_task(
        run_worker_loop(
            backend_client=backend_client,
            email_provider=email_provider,
            legacy_gmail_provider=legacy_gmail_provider,
            whatsapp_provider=whatsapp_provider,
        )
    )
    company_intake_task = start_company_intake_task(
        backend_client=backend_client,
    )

    app.state.backend_client = backend_client
    app.state.email_provider = email_provider
    app.state.legacy_gmail_provider = legacy_gmail_provider
    app.state.whatsapp_provider = whatsapp_provider
    app.state.worker_task = worker_task
    app.state.company_intake_task = company_intake_task

    try:
        yield
    finally:
        logger.info("🛑 Shutting down the bot.")
        worker_task.cancel()
        if company_intake_task is not None:
            company_intake_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        if company_intake_task is not None:
            try:
                await company_intake_task
            except asyncio.CancelledError:
                pass
        await email_provider.close()
        await whatsapp_provider.close()
        await backend_client.aclose()


app = FastAPI(
    title="Konecta Auditor Stateless Bot",
    description="FastAPI webhook runtime + periodic stateless backend-driven worker",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/webhooks/agentmail")
async def agentmail_webhook(request: Request) -> dict[str, Any]:
    """Receive verified AgentMail webhook events."""
    email_provider = getattr(app.state, "email_provider", None)
    backend_client = getattr(app.state, "backend_client", None)
    if not isinstance(email_provider, AgentMailProvider) or backend_client is None:
        raise HTTPException(status_code=503, detail="AgentMail runtime is not ready")

    raw_body = await request.body()
    payload_text = raw_body.decode("utf-8")
    try:
        payload = email_provider.verify_webhook_payload(
            payload=payload_text,
            headers=dict(request.headers),
        )
    except Exception as exc:
        logger.warning("⚠️ Rejected invalid AgentMail webhook: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid AgentMail webhook signature") from exc

    event_type = str(payload.get("type") or payload.get("event_type") or "").strip()
    if event_type == "message.received":
        return await handle_agentmail_received(
            backend_client=backend_client,
            email_provider=email_provider,
            payload=payload,
        )
    if event_type == "message.delivered":
        return await handle_agentmail_delivery_update(
            backend_client=backend_client,
            payload=payload,
            target_status="delivered",
        )
    if event_type in {"message.bounced", "message.rejected"}:
        return await handle_agentmail_delivery_update(
            backend_client=backend_client,
            payload=payload,
            target_status="failed",
        )
    return {
        "status": "ignored",
        "reason": "unsupported_event_type",
        "event_type": event_type or None,
    }


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
