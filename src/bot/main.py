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
        dispatch_pending_client_lead_notifications,
        dispatch_pending_contadores_messages,
        fetch_client_lead_sources,
        fetch_funnels,
        fetch_pending_client_lead_notifications,
        fetch_pending_contadores_outbound,
        process_contadores_alert_email_reply,
        process_whatsapp_inbound_event,
        process_whatsapp_message_status_event,
        register_contadores_calendly_event,
        run_client_lead_source_sync_iteration,
        run_contadores_automation_iteration,
        run_workstation_automation_iteration,
        run_contadores_sheet_sync_iteration,
        send_contadores_pending_alerts,
        wait_for_backend_ready,
    )
    from .webhook_inbox import WhatsAppInboundInbox
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
        dispatch_pending_client_lead_notifications,
        dispatch_pending_contadores_messages,
        fetch_client_lead_sources,
        fetch_funnels,
        fetch_pending_client_lead_notifications,
        fetch_pending_contadores_outbound,
        process_contadores_alert_email_reply,
        process_whatsapp_inbound_event,
        process_whatsapp_message_status_event,
        register_contadores_calendly_event,
        run_client_lead_source_sync_iteration,
        run_contadores_automation_iteration,
        run_workstation_automation_iteration,
        run_contadores_sheet_sync_iteration,
        send_contadores_pending_alerts,
        wait_for_backend_ready,
    )
    from webhook_inbox import WhatsAppInboundInbox

logger = configure_runtime_logging()
LOG_STATE = BotLogState()
CALENDLY_WEBHOOK_SIGNING_KEY = (os.getenv("CALENDLY_WEBHOOK_SIGNING_KEY", "") or "").strip()


def build_sheet_sync_log_summary(sheet_summary: dict[str, Any]) -> dict[str, Any]:
    """Return a compact sheet sync summary that is safe for routine logs."""
    log_summary = {key: value for key, value in sheet_summary.items() if key != "lead_ids"}
    lead_ids = sheet_summary.get("lead_ids")
    if isinstance(lead_ids, list):
        log_summary["lead_count"] = len(lead_ids)
    return log_summary


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
    whatsapp_inbound_inbox: WhatsAppInboundInbox,
    funnels: list[Any] | None = None,
) -> None:
    """Advance automation, send alerts, and dispatch pending WhatsApp messages."""
    replay_summary = await replay_pending_whatsapp_inbound_events(
        backend_client=backend_client,
        inbox=whatsapp_inbound_inbox,
    )
    if replay_summary["delivered"] or replay_summary["failed"]:
        logger.info("WhatsApp inbound inbox replay summary: %s", replay_summary)

    current_funnels = funnels if funnels is not None else await fetch_funnels(backend_client)

    for funnel in current_funnels:
        if not funnel.enabled:
            continue
        if funnel.kind == "inbox":
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
                "ai_replies_sent",
                "scheduling_detail_requests_sent",
                "scheduling_handoffs",
                "human_handoffs",
                "closed_by_ai",
                "page_examples_sent",
                "workstation_solo_page_started",
                "classified_wants_to_proceed",
                "video_confirmation_recaps_sent",
                "classified_needs_human",
                "calendly_sent",
                "codex_fallback_alerts",
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

    workstation_summary = await run_workstation_automation_iteration(backend_client)
    if any(
        workstation_summary.get(key)
        for key in [
            "intake_messages_sent",
            "drafts_generated",
            "revision_videos_sent",
            "approvals",
            "pings_sent",
            "human_handoffs",
            "failures",
        ]
    ):
        logger.info("Workstation automation summary: %s", workstation_summary)

    pending_contadores = await fetch_pending_contadores_outbound(backend_client, limit=200)
    contadores_dispatch_results = await dispatch_pending_contadores_messages(
        backend_client,
        pending=pending_contadores,
        whatsapp_provider=whatsapp_provider,
    )
    log_dispatch_activity(logger, contadores_dispatch_results, LOG_STATE)

    pending_client_leads = await fetch_pending_client_lead_notifications(backend_client, limit=200)
    client_lead_dispatch_results = await dispatch_pending_client_lead_notifications(
        backend_client,
        pending=pending_client_leads,
        whatsapp_provider=whatsapp_provider,
    )
    log_dispatch_activity(logger, client_lead_dispatch_results, LOG_STATE)


async def run_worker_loop(
    *,
    backend_client: httpx.AsyncClient,
    email_provider: AgentMailProvider,
    whatsapp_provider: WhatsAppProvider,
    whatsapp_inbound_inbox: WhatsAppInboundInbox,
) -> None:
    """Run the continuous Contadores worker loop."""
    last_sheet_sync_at_by_funnel: dict[str, float] = {}
    last_client_lead_sync_at_by_source: dict[str, float] = {}
    try:
        while True:
            try:
                funnels = await fetch_funnels(backend_client)
                client_lead_sources = await fetch_client_lead_sources(backend_client)
                await run_worker_iteration(
                    backend_client=backend_client,
                    email_provider=email_provider,
                    whatsapp_provider=whatsapp_provider,
                    whatsapp_inbound_inbox=whatsapp_inbound_inbox,
                    funnels=funnels,
                )
                note_backend_recovered(logger, LOG_STATE)

                now = asyncio.get_running_loop().time()
                for funnel in funnels:
                    if not funnel.enabled:
                        continue
                    if funnel.kind == "inbox":
                        continue
                    sheet_poll_seconds = max(30, int(funnel.sheet_poll_seconds or 30))
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
                            logger.info(
                                "%s sheet sync summary: %s",
                                funnel.label,
                                build_sheet_sync_log_summary(sheet_summary),
                            )

                for source in client_lead_sources:
                    if not source.enabled:
                        continue
                    sheet_poll_seconds = max(5, int(source.sheet_poll_seconds or 10))
                    last_sync_at = last_client_lead_sync_at_by_source.get(source.id, 0.0)
                    if now - last_sync_at < sheet_poll_seconds:
                        continue
                    last_client_lead_sync_at_by_source[source.id] = now
                    try:
                        delivery_summary = await run_client_lead_source_sync_iteration(
                            backend_client,
                            source=source,
                        )
                    except httpx.HTTPStatusError as exc:
                        status_code = exc.response.status_code if exc.response else "unknown"
                        detail = exc.response.text[:300] if exc.response else ""
                        logger.warning(
                            "%s Delivery sync failed with HTTP %s. %s",
                            source.label,
                            status_code,
                            detail,
                        )
                    except Exception:
                        logger.exception("%s Delivery sync iteration failed.", source.label)
                    else:
                        if delivery_summary.get("status") == "ok":
                            logger.info(
                                "%s Delivery sync summary: %s",
                                source.label,
                                build_sheet_sync_log_summary(delivery_summary),
                            )
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
    inbox: WhatsAppInboundInbox,
) -> dict[str, Any]:
    """Durably save and then process one inbound WhatsApp event."""
    event_key = inbox.save_event(event)
    try:
        result = await deliver_saved_whatsapp_inbound_event(
            backend_client=backend_client,
            inbox=inbox,
            event=event,
            event_key=event_key,
        )
    except Exception:
        logger.exception("Queued inbound WhatsApp event for retry after backend delivery failed.")
        return {"status": "queued", "event_key": event_key}
    return result or {"status": "duplicate", "event_key": event_key}


async def deliver_saved_whatsapp_inbound_event(
    *,
    backend_client: httpx.AsyncClient,
    inbox: WhatsAppInboundInbox,
    event: WhatsAppInboundEvent,
    event_key: str,
) -> dict[str, Any] | None:
    """Deliver one reserved inbox event to the backend."""
    if not inbox.reserve_event(event_key):
        return None

    try:
        result = await process_whatsapp_inbound_event(
            backend_client,
            event=event,
        )
    except Exception as exc:
        inbox.mark_failed(event_key, str(exc))
        raise

    inbox.mark_delivered(event_key)
    log_whatsapp_inbound_activity(logger, result)
    return result


async def replay_pending_whatsapp_inbound_events(
    *,
    backend_client: httpx.AsyncClient,
    inbox: WhatsAppInboundInbox,
    limit: int = 50,
) -> dict[str, int]:
    """Retry saved inbound webhooks until the backend accepts them."""
    summary = {"checked": 0, "delivered": 0, "failed": 0, "pending": inbox.pending_count()}
    for saved_event in inbox.list_retryable(limit=limit):
        summary["checked"] += 1
        try:
            delivered = await deliver_saved_whatsapp_inbound_event(
                backend_client=backend_client,
                inbox=inbox,
                event=saved_event.to_event(),
                event_key=saved_event.event_key,
            )
        except httpx.HTTPStatusError as exc:
            summary["failed"] += 1
            status_code = exc.response.status_code if exc.response else 0
            if status_code >= 500:
                break
        except httpx.RequestError:
            summary["failed"] += 1
            break
        except Exception:
            logger.exception("Failed to replay saved inbound WhatsApp event.")
            summary["failed"] += 1
        else:
            if delivered:
                summary["delivered"] += 1
    summary["pending"] = inbox.pending_count()
    return summary


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


async def handle_agentmail_webhook(
    *,
    backend_client: httpx.AsyncClient,
    email_provider: AgentMailProvider,
    raw_body: bytes,
    headers: dict[str, str],
) -> dict[str, Any]:
    """Process one AgentMail webhook update."""
    payload = email_provider.verify_webhook_payload(
        payload=raw_body.decode("utf-8"),
        headers=headers,
    )
    event_type = str(payload.get("event") or payload.get("event_type") or payload.get("type") or "").strip()
    if event_type and event_type != "message.received":
        return {"status": "ignored", "reason": "not_message_received", "event_type": event_type}

    event = email_provider.build_inbound_event(payload)
    if event is None:
        return {"status": "ignored", "reason": "no_inbound_email_event"}

    result = await process_contadores_alert_email_reply(
        backend_client,
        event=event,
    )
    if result.get("status") != "ignored":
        await email_provider.acknowledge_message(
            inbox_id=event.inbox_id,
            message_id=event.message_id,
        )
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
    try:
        await email_provider.initialize()
    except Exception:
        logger.exception("AgentMail startup failed. Email alerts are disabled; WhatsApp workers will keep running.")
        await email_provider.disable()

    whatsapp_inbound_inbox = WhatsAppInboundInbox.from_env()

    async def on_whatsapp_inbound(event: WhatsAppInboundEvent) -> None:
        try:
            await handle_whatsapp_inbound(
                backend_client=backend_client,
                event=event,
                inbox=whatsapp_inbound_inbox,
            )
        except Exception:
            logger.exception("Failed to durably save an inbound WhatsApp event.")
            raise

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
            whatsapp_inbound_inbox=whatsapp_inbound_inbox,
        )
    )

    app.state.backend_client = backend_client
    app.state.email_provider = email_provider
    app.state.whatsapp_provider = whatsapp_provider
    app.state.whatsapp_inbound_inbox = whatsapp_inbound_inbox
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


@app.post("/webhooks/agentmail")
async def agentmail_webhook(request: Request) -> dict[str, Any]:
    """Receive AgentMail replies to operator alert emails."""
    backend_client = getattr(app.state, "backend_client", None)
    email_provider = getattr(app.state, "email_provider", None)
    if backend_client is None or email_provider is None:
        raise HTTPException(status_code=503, detail="Bot runtime is not ready")
    if not email_provider.configured:
        return {"status": "ignored", "reason": "agentmail_disabled"}

    raw_body = await request.body()
    try:
        return await handle_agentmail_webhook(
            backend_client=backend_client,
            email_provider=email_provider,
            raw_body=raw_body,
            headers=dict(request.headers),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
