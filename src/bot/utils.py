"""Backend orchestration helpers for the Contadores bot runtime."""

from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import datetime, timezone
from io import BytesIO, StringIO
from time import monotonic
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, Field

try:
    from .providers import (
        AgentMailProvider,
        DeliveryReceipt,
        WhatsAppInboundEvent,
        WhatsAppMessageStatusEvent,
        WhatsAppProvider,
    )
except ImportError:
    from providers import (
        AgentMailProvider,
        DeliveryReceipt,
        WhatsAppInboundEvent,
        WhatsAppMessageStatusEvent,
        WhatsAppProvider,
    )

logger = logging.getLogger(__name__)

SourceMode = Literal["testing", "live"]
SHEET_IMPORT_HEADERS = {"id", "phone_number"}

BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://backend:8000").strip().rstrip("/")
CONTADORES_REVIEW_BASE_URL = (
    os.getenv("CONTADORES_REVIEW_BASE_URL", "https://chatterface.fgoiriz.com").strip().rstrip("/")
)
INTERNAL_API_TOKEN_HEADER = "X-Internal-Token"
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "").strip()
BOT_TICK_SECONDS = max(5, int(os.getenv("BOT_TICK_SECONDS", "5")))
BACKEND_BOOT_TIMEOUT_SECONDS = max(5, int(os.getenv("BACKEND_BOOT_TIMEOUT_SECONDS", "120")))
BACKEND_BOOT_POLL_SECONDS = max(1, int(os.getenv("BACKEND_BOOT_POLL_SECONDS", "2")))
CONTADORES_SOURCE_MODE: SourceMode = "live" if os.getenv("CONTADORES_SOURCE_MODE", "").strip().lower() == "live" else "testing"
CONTADORES_TEST_PHONE = os.getenv("CONTADORES_TEST_PHONE", "").strip()
CONTADORES_TEST_NAME = os.getenv("CONTADORES_TEST_NAME", "Test Contador").strip() or "Test Contador"


class ContadoresConfigPayload(BaseModel):
    """Backend Contadores config payload."""

    enabled: bool
    sheet_url: str | None = None
    sheet_gid: str | None = None
    sheet_poll_seconds: int
    loom_url: str
    calendly_base_url: str
    alert_emails: list[str] = Field(default_factory=list)
    initial_reply_quiet_seconds: int
    post_loom_min_seconds: int
    post_loom_quiet_seconds: int
    last_sheet_sync_at: str | None = None
    last_sheet_sync_status: str | None = None
    last_sheet_sync_note: str | None = None
    last_alert_at: str | None = None
    calendly_webhook_configured: bool = False


class FunnelConfigPayload(BaseModel):
    """One configured niche funnel from the backend."""

    id: str
    label: str
    kind: str = "campaign"
    enabled: bool
    source_mode: SourceMode = "testing"
    test_phone: str = ""
    test_name: str = ""
    sheet_url: str | None = None
    sheet_gid: str | None = None
    sheet_poll_seconds: int = 30


class FunnelListPayload(BaseModel):
    """Configured funnels payload."""

    funnels: list[FunnelConfigPayload] = Field(default_factory=list)


class PendingContadoresDeliveryMessage(BaseModel):
    """One Contadores outbound message awaiting WhatsApp dispatch."""

    message_id: int
    lead_id: str
    external_lead_id: str
    phone: str
    normalized_phone: str
    full_name: str | None = None
    text: str
    dispatch_after: str
    created_at: str
    sequence_step: str | None = None
    strategy_assignment_id: int | None = None
    strategy_step: str | None = None
    strategy_id: str | None = None
    strategy_label: str | None = None
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None
    contact_has_inbound: bool = False
    whatsapp_template_name: str | None = None
    whatsapp_template_language: str | None = None
    whatsapp_template_body_params: list[str] = Field(default_factory=list)


class PendingContadoresDeliveryResponse(BaseModel):
    """Pending Contadores delivery payload."""

    messages: list[PendingContadoresDeliveryMessage] = Field(default_factory=list)


class PendingContadoresAlertItem(BaseModel):
    """One Contadores lead waiting for human notification."""

    lead_id: str
    full_name: str | None = None
    phone: str
    email: str | None = None
    stage: str
    latest_inbound_text: str | None = None
    reason: str | None = None
    alert_emails: list[str] = Field(default_factory=list)


class PendingContadoresAlertsResponse(BaseModel):
    """Pending Contadores human alerts."""

    items: list[PendingContadoresAlertItem] = Field(default_factory=list)


class ContadoresWhatsAppInboundResponse(BaseModel):
    """WhatsApp inbound routing result."""

    status: str
    route: str | None = None
    lead_id: str | None = None
    reason: str | None = None


class ContadoresAutomationTickResponse(BaseModel):
    """Automation tick summary for Contadores."""

    status: str
    opener_sent: int = 0
    loom_sent: int = 0
    video_checks_sent: int = 0
    classified_wants_to_proceed: int = 0
    classified_needs_human: int = 0
    calendly_sent: int = 0


class DispatchResult(BaseModel):
    """One outbound dispatch result for operator logging."""

    message_id: int
    contact_id: str
    channel: str
    status: str
    contact_value: str | None = None
    error: str | None = None
    wait_seconds: float | None = None


def build_backend_client() -> httpx.AsyncClient:
    """Create one shared async HTTP client for backend API requests."""
    headers = {INTERNAL_API_TOKEN_HEADER: INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else {}
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), headers=headers)


def backend_url(path: str) -> str:
    """Build absolute backend API URL from one absolute path."""
    return f"{BACKEND_BASE_URL}{path}"


def build_contadores_lead_review_url(lead_id: str) -> str:
    """Build the backoffice URL for one Contadores lead."""
    query = urlencode({"section": "contadores", "contadores_lead": lead_id})
    return f"{CONTADORES_REVIEW_BASE_URL}/?{query}"


async def is_backend_healthy(client: httpx.AsyncClient) -> bool:
    """Return True when the backend health endpoint is reachable."""
    try:
        response = await client.get(backend_url("/health"))
        return response.status_code == 200
    except httpx.RequestError:
        return False


async def wait_for_backend_ready(
    client: httpx.AsyncClient,
    *,
    timeout_seconds: int = BACKEND_BOOT_TIMEOUT_SECONDS,
    poll_seconds: int = BACKEND_BOOT_POLL_SECONDS,
) -> bool:
    """Wait until the backend health endpoint becomes reachable."""
    start = monotonic()
    while True:
        if await is_backend_healthy(client):
            return True
        if monotonic() - start >= timeout_seconds:
            return False
        await asyncio.sleep(poll_seconds)


async def fetch_contadores_config(client: httpx.AsyncClient) -> ContadoresConfigPayload:
    """Fetch Contadores runtime config from the backend."""
    response = await client.get(backend_url("/api/contadores/config"))
    response.raise_for_status()
    return ContadoresConfigPayload.model_validate(response.json())


async def fetch_funnels(client: httpx.AsyncClient) -> list[FunnelConfigPayload]:
    """Fetch configured funnels from the backend."""
    response = await client.get(backend_url("/api/funnels"))
    response.raise_for_status()
    return FunnelListPayload.model_validate(response.json()).funnels


async def fetch_pending_contadores_outbound(
    client: httpx.AsyncClient,
    *,
    limit: int = 200,
) -> list[PendingContadoresDeliveryMessage]:
    """Fetch Contadores outbound messages ready for WhatsApp dispatch."""
    response = await client.get(
        backend_url("/api/contadores/messages/pending-delivery"),
        params={"limit": limit},
    )
    response.raise_for_status()
    payload = PendingContadoresDeliveryResponse.model_validate(response.json())
    return payload.messages


def build_contadores_sheet_csv_url(config: ContadoresConfigPayload) -> str | None:
    """Resolve a public Google Sheets CSV URL from backend config."""
    base_url = (config.sheet_url or "").strip()
    if not base_url:
        return None
    if any(marker in base_url for marker in ["output=csv", "format=csv", "tqx=out:csv"]):
        return base_url

    gid = (config.sheet_gid or "").strip()
    separator = "&" if "?" in base_url else "?"
    if gid and "gid=" not in base_url:
        return f"{base_url}{separator}gid={gid}&output=csv"
    if "?" in base_url:
        return f"{base_url}&output=csv"
    return f"{base_url}?output=csv"


def build_contadores_sheet_xlsx_url(config: ContadoresConfigPayload) -> str | None:
    """Resolve a public Google Sheets XLSX URL from backend config."""
    base_url = (config.sheet_url or "").strip()
    if not base_url or "docs.google.com/spreadsheets/d/" not in base_url:
        return None

    marker = "/spreadsheets/d/"
    spreadsheet_id = base_url.split(marker, 1)[1].split("/", 1)[0].split("?", 1)[0]
    if not spreadsheet_id:
        return None
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"


def has_sheet_import_headers(rows: list[dict[str, str]]) -> bool:
    """Return True when parsed rows include the minimum import columns."""
    if not rows:
        return False
    headers = {key.strip() for key in rows[0].keys()}
    return SHEET_IMPORT_HEADERS.issubset(headers)


def read_xlsx_sheet_rows(content: bytes) -> list[dict[str, str]]:
    """Read the first XLSX worksheet that looks like a Meta leads export."""
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required to read Google Sheets XLSX exports.") from exc

    workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        for worksheet in workbook.worksheets:
            raw_rows = list(worksheet.iter_rows(values_only=True))
            if not raw_rows:
                continue

            headers = [str(value or "").strip() for value in raw_rows[0]]
            if not SHEET_IMPORT_HEADERS.issubset(set(headers)):
                continue

            records: list[dict[str, str]] = []
            for raw_row in raw_rows[1:]:
                record = {
                    header: "" if value is None else str(value).strip()
                    for header, value in zip(headers, raw_row, strict=False)
                    if header
                }
                if any(record.values()):
                    records.append(record)
            return records
    finally:
        workbook.close()

    return []


async def fetch_contadores_sheet_rows(
    *,
    config: ContadoresConfigPayload,
) -> list[dict[str, str]]:
    """Fetch publicly readable sheet rows as CSV dictionaries."""
    csv_url = build_contadores_sheet_csv_url(config)
    if not csv_url:
        return []

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        response = await client.get(csv_url)
        response.raise_for_status()

    reader = csv.DictReader(StringIO(response.text))
    csv_rows = [dict(row) for row in reader]
    if has_sheet_import_headers(csv_rows):
        return csv_rows

    xlsx_url = build_contadores_sheet_xlsx_url(config)
    if not xlsx_url:
        return csv_rows

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        response = await client.get(xlsx_url)
        response.raise_for_status()
    return read_xlsx_sheet_rows(response.content)


async def import_contadores_sheet_rows(
    client: httpx.AsyncClient,
    *,
    funnel_id: str = "contadores",
    rows: list[dict[str, str | None]],
) -> dict[str, Any]:
    """Send fetched sheet rows to the backend for upsert."""
    response = await client.post(
        backend_url("/api/contadores/leads/import"),
        json={"funnel_id": funnel_id, "rows": rows},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"status": "invalid"}


def keep_sheet_row_for_import(row: dict[str, str]) -> bool:
    """Return True when a sheet row has enough data and is not contacted yet."""
    has_id = bool(str(row.get("id") or "").strip())
    has_phone = bool(str(row.get("phone_number") or "").strip())
    already_contacted = str(row.get("is_contactado") or "").strip().lower() in {"true", "1", "yes"}
    return has_id and has_phone and not already_contacted


def build_importable_sheet_row(row: dict[str, str]) -> dict[str, str | None]:
    """Map one raw sheet CSV row into the backend import shape."""
    return {
        "id": str(row.get("id") or "").strip(),
        "created_time": str(row.get("created_time") or "").strip() or None,
        "platform": str(row.get("platform") or "").strip() or None,
        "email": str(row.get("email") or "").strip() or None,
        "full_name": str(row.get("full_name") or "").strip() or None,
        "phone_number": str(row.get("phone_number") or "").strip(),
        "lead_status": str(row.get("lead_status") or "").strip() or None,
        "is_contactado": str(row.get("is_contactado") or "").strip() or None,
    }


def build_testing_lead_row(
    *,
    funnel_id: str = "contadores",
    test_phone: str | None = None,
    test_name: str | None = None,
) -> dict[str, str | None] | None:
    """Build the synthetic lead row used when the runtime source is testing."""
    resolved_phone = (test_phone if test_phone is not None else CONTADORES_TEST_PHONE).strip()
    resolved_name = (test_name if test_name is not None else CONTADORES_TEST_NAME).strip()
    if not resolved_phone:
        return None
    phone_digits = "".join(ch for ch in resolved_phone if ch.isdigit())
    row_id = f"testing-{funnel_id}-{phone_digits or 'lead'}"
    return {
        "id": row_id,
        "created_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": "testing",
        "email": None,
        "full_name": resolved_name,
        "phone_number": resolved_phone,
        "lead_status": "testing",
        "is_contactado": "FALSE",
    }


async def run_contadores_sheet_sync_iteration(
    client: httpx.AsyncClient,
    *,
    funnel_id: str = "contadores",
    funnel: FunnelConfigPayload | None = None,
) -> dict[str, Any]:
    """Fetch the public Contadores sheet and import new live leads."""
    config = await fetch_contadores_config(client) if funnel is None else ContadoresConfigPayload(
        enabled=funnel.enabled,
        sheet_url=funnel.sheet_url,
        sheet_gid=funnel.sheet_gid,
        sheet_poll_seconds=funnel.sheet_poll_seconds,
        loom_url="",
        calendly_base_url="",
        alert_emails=[],
        initial_reply_quiet_seconds=30,
        post_loom_min_seconds=300,
        post_loom_quiet_seconds=30,
    )
    if not config.enabled:
        return {"status": "disabled", "funnel_id": funnel_id}

    source_mode = funnel.source_mode if funnel is not None else CONTADORES_SOURCE_MODE
    if source_mode == "testing":
        test_row = build_testing_lead_row(
            funnel_id=funnel_id,
            test_phone=funnel.test_phone if funnel else None,
            test_name=funnel.test_name if funnel else None,
        )
        if test_row is None:
            return {
                "status": "misconfigured",
                "funnel_id": funnel_id,
                "source_mode": source_mode,
                "reason": "missing_CONTADORES_TEST_PHONE",
                "fetched": 0,
                "submitted": 0,
            }
        result = await import_contadores_sheet_rows(client, funnel_id=funnel_id, rows=[test_row])
        result["status"] = "ok"
        result["funnel_id"] = funnel_id
        result["source_mode"] = source_mode
        result["fetched"] = 1
        result["submitted"] = 1
        return result

    rows = await fetch_contadores_sheet_rows(config=config)
    filtered_rows = [build_importable_sheet_row(row) for row in rows if keep_sheet_row_for_import(row)]
    result = await import_contadores_sheet_rows(client, funnel_id=funnel_id, rows=filtered_rows)
    result["status"] = "ok"
    result["funnel_id"] = funnel_id
    result["source_mode"] = source_mode
    result["fetched"] = len(rows)
    result["submitted"] = len(filtered_rows)
    return result


async def run_contadores_automation_iteration(
    client: httpx.AsyncClient,
    *,
    funnel_id: str = "contadores",
) -> dict[str, Any]:
    """Ask the backend to advance Contadores automation state."""
    response = await client.post(
        backend_url("/api/contadores/automation/tick"),
        params={"funnel_id": funnel_id},
    )
    response.raise_for_status()
    return ContadoresAutomationTickResponse.model_validate(response.json()).model_dump()


async def update_backend_contadores_message_text(
    client: httpx.AsyncClient,
    *,
    message_id: int,
    text: str,
) -> None:
    """Update one Contadores outbound message text to match provider output."""
    response = await client.put(
        backend_url(f"/api/contadores/messages/{message_id}"),
        json={"text": text},
    )
    response.raise_for_status()


async def mark_backend_contadores_message_sent(
    client: httpx.AsyncClient,
    *,
    message_id: int,
    receipt: DeliveryReceipt,
) -> None:
    """Mark one Contadores outbound message as accepted by WhatsApp."""
    response = await client.put(
        backend_url(f"/api/contadores/messages/{message_id}/delivery"),
        json={
            "status": "sent",
            "external_id": receipt.external_id,
        },
    )
    response.raise_for_status()


async def mark_backend_contadores_message_status(
    client: httpx.AsyncClient,
    *,
    external_id: str,
    status: str,
) -> dict[str, Any]:
    """Update one Contadores outbound message by provider external id."""
    response = await client.put(
        backend_url("/api/contadores/messages/delivery/by-external-id"),
        json={
            "external_id": external_id,
            "status": status,
        },
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"status": "updated"}


async def process_contadores_whatsapp_inbound_event(
    client: httpx.AsyncClient,
    *,
    event: WhatsAppInboundEvent,
) -> dict[str, Any]:
    """Forward one raw WhatsApp inbound event to the backend."""
    response = await client.post(
        backend_url("/api/contadores/whatsapp/inbound"),
        json={
            "phone": event.phone,
            "text": event.text,
            "external_id": event.external_id,
            "in_reply_to": event.in_reply_to,
            "referral": event.referral.model_dump(exclude_none=True) if event.referral else None,
            "media_type": event.media_type,
            "media_path": event.media_path,
            "media_caption": event.media_caption,
            "media_mime_type": event.media_mime_type,
            "media_filename": event.media_filename,
            "media_sha256": event.media_sha256,
            "media_id": event.media_id,
        },
    )
    response.raise_for_status()
    payload = ContadoresWhatsAppInboundResponse.model_validate(response.json())
    return payload.model_dump()


async def process_whatsapp_inbound_event(
    client: httpx.AsyncClient,
    *,
    event: WhatsAppInboundEvent,
) -> dict[str, Any]:
    """Route one WhatsApp inbound event through the Contadores backend."""
    result = await process_contadores_whatsapp_inbound_event(client, event=event)
    result["phone"] = event.phone
    result["in_reply_to"] = event.in_reply_to
    result["external_id"] = event.external_id
    if event.referral:
        result["referral"] = event.referral.model_dump(exclude_none=True)
    return result


def map_whatsapp_provider_status(status: str) -> str:
    """Map provider-specific WhatsApp status names to backend delivery statuses."""
    normalized = (status or "").strip().lower()
    if normalized == "failed":
        return "failed"
    if normalized == "sent":
        return "sent"
    return "delivered"


async def process_whatsapp_message_status_event(
    client: httpx.AsyncClient,
    *,
    event: WhatsAppMessageStatusEvent,
) -> dict[str, Any]:
    """Persist one outbound WhatsApp provider status update in Contadores."""
    target_status = map_whatsapp_provider_status(event.status)
    try:
        result = await mark_backend_contadores_message_status(
            client,
            external_id=event.external_id,
            status=target_status,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {
                "status": "ignored",
                "reason": "external_id_not_found",
                "external_id": event.external_id,
                "provider_status": event.status,
            }
        raise

    result["provider_status"] = event.status
    result["route"] = "contadores"
    return result


async def fetch_pending_contadores_alerts(
    client: httpx.AsyncClient,
    *,
    funnel_id: str = "contadores",
) -> list[PendingContadoresAlertItem]:
    """Fetch Contadores leads waiting for human notification emails."""
    response = await client.get(
        backend_url("/api/contadores/alerts/pending"),
        params={"funnel_id": funnel_id},
    )
    response.raise_for_status()
    payload = PendingContadoresAlertsResponse.model_validate(response.json())
    return payload.items


async def mark_backend_contadores_alert_sent(
    client: httpx.AsyncClient,
    *,
    lead_id: str,
) -> None:
    """Mark one pending Contadores needs-human alert as sent."""
    response = await client.post(
        backend_url(f"/api/contadores/leads/{lead_id}/mark-alerted"),
        json={},
    )
    response.raise_for_status()


async def send_contadores_pending_alerts(
    client: httpx.AsyncClient,
    *,
    email_provider: AgentMailProvider,
    funnel_id: str = "contadores",
    funnel_label: str = "Contadores",
) -> list[dict[str, Any]]:
    """Send Contadores needs-human notification emails when required."""
    items = await fetch_pending_contadores_alerts(client, funnel_id=funnel_id)
    if not items:
        return []
    if not email_provider.configured:
        return [
            {
                "lead_id": item.lead_id,
                "status": "deferred",
                "reason": "email_provider_not_configured",
            }
            for item in items
        ]

    alert_inbox = await email_provider.ensure_alert_inbox()
    outcomes: list[dict[str, Any]] = []
    for item in items:
        recipients = [email for email in item.alert_emails if email]
        if not recipients:
            outcomes.append(
                {
                    "lead_id": item.lead_id,
                    "status": "skipped",
                    "reason": "missing_alert_emails",
                }
            )
            continue

        body = "\n".join(
            [
                f"Se freno la automatizacion de {funnel_label} y requiere revision humana.",
                "",
                f"Lead ID: {item.lead_id}",
                f"Lead link: {build_contadores_lead_review_url(item.lead_id)}",
                f"Nombre: {item.full_name or '-'}",
                f"WhatsApp: {item.phone}",
                f"Email: {item.email or '-'}",
                f"Stage: {item.stage}",
                f"Motivo: {item.reason or '-'}",
                "",
                "Ultimo mensaje inbound:",
                item.latest_inbound_text or "-",
            ]
        )
        for recipient in recipients:
            await email_provider.send_message(
                inbox_id=alert_inbox.inbox_id,
                inbox_address=alert_inbox.inbox_address,
                recipient=recipient,
                text=body,
                subject=f"[{funnel_label}] needs_human {item.phone}",
                attachments=None,
                thread_id=None,
                in_reply_to=None,
                references=None,
            )
        await mark_backend_contadores_alert_sent(client, lead_id=item.lead_id)
        outcomes.append(
            {
                "lead_id": item.lead_id,
                "status": "sent",
                "recipients": recipients,
            }
        )

    return outcomes


async def register_contadores_calendly_event(
    client: httpx.AsyncClient,
    *,
    token: str,
    event_type: str,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Forward one Calendly booking event to the backend by tracking token."""
    response = await client.post(
        backend_url("/api/contadores/calendly/webhook"),
        json={
            "token": token,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat() if occurred_at else None,
        },
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"status": "processed"}


async def dispatch_one_contadores_message(
    *,
    item: PendingContadoresDeliveryMessage,
    whatsapp_provider: WhatsAppProvider,
) -> DeliveryReceipt:
    """Dispatch one Contadores WhatsApp outbound message."""
    to_phone = item.phone or item.normalized_phone
    if (item.media_type or "").strip().lower() == "video":
        return await whatsapp_provider.send_video(
            to=to_phone,
            video_path=item.media_path or "",
            caption=item.media_caption,
            delivered_text=item.text,
        )

    has_template_payload = bool(
        (item.whatsapp_template_name or "").strip()
        and (item.whatsapp_template_language or "").strip()
    )
    if has_template_payload:
        return await whatsapp_provider.send_template_message(
            to=to_phone,
            template_name=item.whatsapp_template_name or "",
            template_language=item.whatsapp_template_language or "es",
            body_params=item.whatsapp_template_body_params,
            delivered_text=item.text,
        )
    return await whatsapp_provider.send_message(to_phone, item.text)


async def dispatch_pending_contadores_messages(
    client: httpx.AsyncClient,
    *,
    pending: list[PendingContadoresDeliveryMessage],
    whatsapp_provider: WhatsAppProvider,
) -> list[DispatchResult]:
    """Dispatch Contadores pending messages through WhatsApp."""
    if not pending:
        return []
    if not whatsapp_provider.configured:
        return [
            DispatchResult(
                message_id=item.message_id,
                contact_id=item.lead_id,
                channel="whatsapp",
                status="deferred",
                contact_value=item.phone,
                error="whatsapp_provider_not_configured",
            )
            for item in pending
        ]

    results: list[DispatchResult] = []
    for item in pending:
        try:
            receipt = await dispatch_one_contadores_message(
                item=item,
                whatsapp_provider=whatsapp_provider,
            )
            if receipt.delivered_text and receipt.delivered_text.strip() != item.text.strip():
                await update_backend_contadores_message_text(
                    client,
                    message_id=item.message_id,
                    text=receipt.delivered_text,
                )
            await mark_backend_contadores_message_sent(
                client,
                message_id=item.message_id,
                receipt=receipt,
            )
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.lead_id,
                    channel="whatsapp",
                    status="delivered",
                    contact_value=item.phone,
                )
            )
        except Exception as exc:
            logger.exception(
                "Failed Contadores dispatch for message_id=%s lead_id=%s",
                item.message_id,
                item.lead_id,
            )
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.lead_id,
                    channel="whatsapp",
                    status="failed",
                    contact_value=item.phone,
                    error=str(exc),
                )
            )

    return results


async def get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
    """Compatibility hook: Contadores uses backend timing and no bot jitter."""
    del delay_key
    return 0.0
