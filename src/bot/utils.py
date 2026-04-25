"""Stateless backend orchestration helpers for bot runtime."""

from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from io import StringIO
import logging
import os
import random
import re
from time import monotonic
from typing import Any
from urllib.parse import unquote, urlencode
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, Field

try:
    from .providers import (
        AgentMailProvider,
        DeliveryReceipt,
        EmailAttachment,
        EmailInboundEvent,
        GmailProvider,
        InvalidRecipientEmailError,
        WhatsAppInboundEvent,
        WhatsAppMessageStatusEvent,
        WhatsAppProvider,
    )
except ImportError:
    from providers import (
        AgentMailProvider,
        DeliveryReceipt,
        EmailAttachment,
        EmailInboundEvent,
        GmailProvider,
        InvalidRecipientEmailError,
        WhatsAppInboundEvent,
        WhatsAppMessageStatusEvent,
        WhatsAppProvider,
    )

logger = logging.getLogger(__name__)


def summarize_exception_message(error: Exception) -> str:
    """Return one compact lowercase error message for deterministic checks."""
    parts = [str(arg).strip() for arg in getattr(error, "args", ()) if str(arg).strip()]
    if not parts:
        parts = [str(error).strip()]
    return " ".join(part for part in parts if part).strip().lower()


def should_remove_audit_delivery_recipient(error: Exception) -> bool:
    """Return True when the stored CEO email should be deleted and not retried."""
    if isinstance(error, InvalidRecipientEmailError):
        return True

    error_name = type(error).__name__.strip().lower()
    message = summarize_exception_message(error)
    if error_name != "messagerejectederror":
        return False
    if "recipient" in message and ("blocked" in message or "bounced" in message):
        return True
    return False


def env_flag(name: str, default: bool) -> bool:
    """Parse one boolean-like environment variable."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


BACKEND_BASE_URL = os.getenv("BACKEND_BASE_URL", "http://backend:8000").strip().rstrip("/")
CONTADORES_REVIEW_BASE_URL = os.getenv("CONTADORES_REVIEW_BASE_URL", "https://chatterface.fgoiriz.com").strip().rstrip("/")
INTERNAL_API_TOKEN_HEADER = "X-Internal-Token"
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "").strip()
BOT_TICK_SECONDS = max(5, int(os.getenv("BOT_TICK_SECONDS", "5")))
BACKEND_BOOT_TIMEOUT_SECONDS = max(5, int(os.getenv("BACKEND_BOOT_TIMEOUT_SECONDS", "120")))
BACKEND_BOOT_POLL_SECONDS = max(1, int(os.getenv("BACKEND_BOOT_POLL_SECONDS", "2")))
EMAIL_DISPATCH_DELAY_MIN_SECONDS = max(0.0, float(os.getenv("EMAIL_DISPATCH_DELAY_MIN_SECONDS", "600")))
EMAIL_DISPATCH_DELAY_MAX_SECONDS = max(
    EMAIL_DISPATCH_DELAY_MIN_SECONDS,
    float(os.getenv("EMAIL_DISPATCH_DELAY_MAX_SECONDS", "1800")),
)
WHATSAPP_DISPATCH_DELAY_MIN_SECONDS = max(
    0.0,
    float(os.getenv("WHATSAPP_DISPATCH_DELAY_MIN_SECONDS", "2700")),
)
WHATSAPP_DISPATCH_DELAY_MAX_SECONDS = max(
    WHATSAPP_DISPATCH_DELAY_MIN_SECONDS,
    float(os.getenv("WHATSAPP_DISPATCH_DELAY_MAX_SECONDS", "2700")),
)
AUDIT_DELIVERY_POLL_SECONDS = max(10, int(os.getenv("AUDIT_DELIVERY_POLL_SECONDS", "60")))
AUTOMATED_AUDITOR_INTAKE_ENABLED = env_flag("AUTOMATED_AUDITOR_INTAKE_ENABLED", False)
AUTOMATED_AUDITOR_INTAKE_POLL_SECONDS = max(
    60,
    int(os.getenv("AUTOMATED_AUDITOR_INTAKE_POLL_SECONDS", "300")),
)
AUTOMATED_AUDITOR_DISCOVERY_MAX_ATTEMPTS = max(
    1,
    int(os.getenv("AUTOMATED_AUDITOR_DISCOVERY_MAX_ATTEMPTS", "5")),
)
AUTOMATED_AUDITOR_DISCOVERY_TIMEOUT_SECONDS = max(
    30.0,
    float(os.getenv("AUTOMATED_AUDITOR_DISCOVERY_TIMEOUT_SECONDS", "180")),
)
AUTOMATED_AUDITOR_SCAN_TIMEOUT_SECONDS = max(
    30.0,
    float(os.getenv("AUTOMATED_AUDITOR_SCAN_TIMEOUT_SECONDS", "180")),
)
AUTOMATED_AUDITOR_COMPANIES_PER_DAY = max(
    1,
    int(os.getenv("AUTOMATED_AUDITOR_COMPANIES_PER_DAY", "2")),
)
AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT = max(
    1,
    int(os.getenv("AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT", "500")),
)
AUTOMATED_AUDITOR_RUN_HOUR_LOCAL = min(
    23,
    max(0, int(os.getenv("AUTOMATED_AUDITOR_RUN_HOUR_LOCAL", "9"))),
)
AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL = min(
    59,
    max(0, int(os.getenv("AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL", "0"))),
)
AUTOMATED_AUDITOR_WEEKEND_HOLD_HOUR_LOCAL = min(
    23,
    max(0, int(os.getenv("AUTOMATED_AUDITOR_WEEKEND_HOLD_HOUR_LOCAL", "20"))),
)
AUTOMATED_AUDITOR_TIMEZONE_NAME = (
    os.getenv("AUTOMATED_AUDITOR_TIMEZONE", "America/Sao_Paulo").strip()
    or "America/Sao_Paulo"
)
try:
    AUTOMATED_AUDITOR_TIMEZONE = ZoneInfo(AUTOMATED_AUDITOR_TIMEZONE_NAME)
except Exception:
    AUTOMATED_AUDITOR_TIMEZONE = timezone.utc
AUTOMATED_AUDITOR_OBJECTIVE = (
    os.getenv(
        "AUTOMATED_AUDITOR_OBJECTIVE",
        "Audit inbound sales handling from first response to next-step progression.",
    ).strip()
    or "Audit inbound sales handling from first response to next-step progression."
)
AUTOMATED_AUDITOR_TAG_PREFIX = "auto-intake"
EMAIL_DELAY_KEY_PREFIX_MESSAGE = "message:"
WHATSAPP_DELAY_KEY_PREFIX_MESSAGE = "wa-message:"


@dataclass
class EmailDispatchDelayState:
    """In-memory schedule for outbound email random delays."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    due_by_key: dict[str, float] = field(default_factory=dict)


_email_dispatch_delay_state = EmailDispatchDelayState()


@dataclass
class WhatsAppDispatchDelayState:
    """In-memory schedule for outbound WhatsApp random delays."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    due_by_key: dict[str, float] = field(default_factory=dict)


_whatsapp_dispatch_delay_state = WhatsAppDispatchDelayState()


class ResolvedContact(BaseModel):
    """Resolved backend contact target for one inbound event."""

    company_id: str
    contact_id: str
    contact_type: str
    contact_value: str


class PendingDeliveryMessage(BaseModel):
    """One backend outbound message awaiting provider dispatch."""

    message_id: int
    company_id: str
    company_name: str
    company_source_url: str | None = None
    company_language: str | None = None
    contact_id: str
    contact_has_inbound: bool = False
    contact_type: str
    contact_value: str
    text: str
    dispatch_after: str
    timestamp: str
    email_inbox_id: str | None = None
    email_inbox_address: str | None = None
    email_thread_id: str | None = None
    email_last_outbound_rfc_id: str | None = None
    whatsapp_template_name: str | None = None
    whatsapp_template_language: str | None = None
    whatsapp_template_client_name: str | None = None
    whatsapp_template_company_url: str | None = None


class PendingDeliveryResponse(BaseModel):
    """Backend pending delivery API payload."""

    messages: list[PendingDeliveryMessage] = Field(default_factory=list)


class TrackedContactValuesResponse(BaseModel):
    """Tracked normalized values for one channel."""

    channel: str
    values: list[str] = Field(default_factory=list)


class DispatchResult(BaseModel):
    """One pending dispatch execution result."""

    message_id: int
    contact_id: str
    channel: str
    status: str
    contact_value: str | None = None
    error: str | None = None
    wait_seconds: float | None = None


class AuditDeliveryPollStateItem(BaseModel):
    """Backend audit-delivery poll-state row."""

    company_id: str
    created_at: str
    report_window_hours: int | None = 24
    report_window_minutes: int | None = None
    scheduled_send_at: str | None = None
    conversation_automation_enabled: bool
    ceo_delivery_enabled: bool
    has_report_pdf_model: bool
    ceo_delivery_sent_at: str | None = None
    ceo_delivery_blocked_reason: str | None = None
    pending_full_audit_task: bool
    eligible_for_full_audit: bool


class AuditDeliveryCeoEmail(BaseModel):
    """CEO recipient payload for one company."""

    company_id: str
    ceo_email: str | None = None


class AuditDeliveryEmailContent(BaseModel):
    """Subject/body payload for one company audit delivery email."""

    company_id: str
    subject: str
    body: str


class AuditDeliveryPdfAttachment(BaseModel):
    """One audit PDF attachment resolved from backend response headers."""

    filename: str
    data: bytes


class CompanySummary(BaseModel):
    """Subset of backend company list payload used by the bot."""

    id: str
    source_url: str
    company_name: str
    tags: list[str] = Field(default_factory=list)


class AuditorCandidateCompany(BaseModel):
    """One company candidate returned by backend discovery."""

    company_name: str
    website_url: str
    industry: str
    country_or_region: str | None = None
    fit_summary: str
    likely_contact_owner: str
    leadership_recipient_name: str | None = None
    leadership_recipient_role: str
    leadership_recipient_email: str
    leadership_recipient_evidence: str
    public_contact_channels: list[str] = Field(default_factory=list)
    public_contact_paths: list[str] = Field(default_factory=list)
    lead_dependency_evidence: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class DiscoverAuditorCompaniesResponse(BaseModel):
    """Backend response for automated company discovery."""

    companies: list[AuditorCandidateCompany] = Field(default_factory=list)


class ScanCompanyTaskResponse(BaseModel):
    """Backend response for company scan creation."""

    task_id: str | None = None
    company_id: str
    status: str
    duplicate_ignored: bool = False


class UpdateCompanyReportScheduleResponse(BaseModel):
    """Backend response after updating one company schedule."""

    company_id: str
    scheduled_send_at: str


class PendingCrmOutboundMessage(BaseModel):
    """One CRM outbound message waiting for immediate email dispatch."""

    message_id: int
    thread_id: str
    company_id: str
    company_name: str
    participant_email: str
    subject: str
    body: str
    gmail_thread_id: str
    latest_sent_rfc_message_id: str | None = None


class PendingCrmOutboundResponse(BaseModel):
    """Backend pending CRM outbound payload."""

    messages: list[PendingCrmOutboundMessage] = Field(default_factory=list)


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


class ContadoresWhatsAppInboundResponse(BaseModel):
    """Unified WhatsApp inbound routing result."""

    status: str
    route: str | None = None
    lead_id: str | None = None
    company_id: str | None = None
    contact_id: str | None = None
    task_id: str | None = None
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


class CrmInboundMessageResponse(BaseModel):
    """Backend response for inbound CRM email persistence."""

    status: str
    thread_id: str | None = None
    company_id: str | None = None
    message_id: int | None = None
    reason: str | None = None


class CrmTrackedSendersResponse(BaseModel):
    """Tracked CRM sender emails."""

    values: list[str] = Field(default_factory=list)


class ReportDeliverySentResponse(BaseModel):
    """Backend response for report-delivery CRM seeding."""

    thread_id: str
    company_id: str
    message_id: int
    duplicate_ignored: bool = False


class MarkCrmMessageSentResponse(BaseModel):
    """Backend response for CRM sent confirmation."""

    id: int
    thread_id: str
    status: str
    gmail_message_id: str | None = None
    reason: str | None = None


def sample_email_dispatch_delay_seconds() -> float:
    """Sample randomized delay for outbound emails."""
    if EMAIL_DISPATCH_DELAY_MAX_SECONDS <= 0:
        return 0.0
    if EMAIL_DISPATCH_DELAY_MAX_SECONDS <= EMAIL_DISPATCH_DELAY_MIN_SECONDS:
        return EMAIL_DISPATCH_DELAY_MIN_SECONDS
    return random.uniform(
        EMAIL_DISPATCH_DELAY_MIN_SECONDS,
        EMAIL_DISPATCH_DELAY_MAX_SECONDS,
    )


def sample_whatsapp_dispatch_delay_seconds() -> float:
    """Sample randomized delay for outbound WhatsApp messages."""
    if WHATSAPP_DISPATCH_DELAY_MAX_SECONDS <= 0:
        return 0.0
    if WHATSAPP_DISPATCH_DELAY_MAX_SECONDS <= WHATSAPP_DISPATCH_DELAY_MIN_SECONDS:
        return WHATSAPP_DISPATCH_DELAY_MIN_SECONDS
    return random.uniform(
        WHATSAPP_DISPATCH_DELAY_MIN_SECONDS,
        WHATSAPP_DISPATCH_DELAY_MAX_SECONDS,
    )


def build_message_email_delay_key(message_id: int) -> str:
    """Build one in-memory delay key for a pending outbound message."""
    return f"{EMAIL_DELAY_KEY_PREFIX_MESSAGE}{message_id}"


def build_message_whatsapp_delay_key(message_id: int) -> str:
    """Build one in-memory delay key for a pending outbound WhatsApp message."""
    return f"{WHATSAPP_DELAY_KEY_PREFIX_MESSAGE}{message_id}"


async def prune_email_dispatch_delay_keys(
    *,
    prefix: str,
    active_keys: set[str],
) -> None:
    """Remove stale in-memory delay keys that are no longer active."""
    async with _email_dispatch_delay_state.lock:
        stale_keys = [
            key
            for key in _email_dispatch_delay_state.due_by_key
            if key.startswith(prefix) and key not in active_keys
        ]
        for key in stale_keys:
            _email_dispatch_delay_state.due_by_key.pop(key, None)


async def clear_email_dispatch_delay_key(delay_key: str) -> None:
    """Clear one in-memory outbound email delay key."""
    async with _email_dispatch_delay_state.lock:
        _email_dispatch_delay_state.due_by_key.pop(delay_key, None)


async def prune_whatsapp_dispatch_delay_keys(
    *,
    active_keys: set[str],
) -> None:
    """Remove stale in-memory WhatsApp delay keys that are no longer active."""
    async with _whatsapp_dispatch_delay_state.lock:
        stale_keys = [
            key
            for key in _whatsapp_dispatch_delay_state.due_by_key
            if key.startswith(WHATSAPP_DELAY_KEY_PREFIX_MESSAGE) and key not in active_keys
        ]
        for key in stale_keys:
            _whatsapp_dispatch_delay_state.due_by_key.pop(key, None)


async def clear_whatsapp_dispatch_delay_key(delay_key: str) -> None:
    """Clear one in-memory outbound WhatsApp delay key."""
    async with _whatsapp_dispatch_delay_state.lock:
        _whatsapp_dispatch_delay_state.due_by_key.pop(delay_key, None)


async def get_email_dispatch_wait_seconds(delay_key: str) -> float:
    """Get remaining delay before one email can be sent."""
    if EMAIL_DISPATCH_DELAY_MAX_SECONDS <= 0:
        return 0.0

    async with _email_dispatch_delay_state.lock:
        now = monotonic()
        due_at = _email_dispatch_delay_state.due_by_key.get(delay_key)
        if due_at is None:
            next_gap_seconds = sample_email_dispatch_delay_seconds()
            due_at = now + next_gap_seconds
            _email_dispatch_delay_state.due_by_key[delay_key] = due_at
        return max(0.0, due_at - now)


async def get_whatsapp_dispatch_wait_seconds(delay_key: str) -> float:
    """Get remaining delay before one WhatsApp message can be sent."""
    if WHATSAPP_DISPATCH_DELAY_MAX_SECONDS <= 0:
        return 0.0

    async with _whatsapp_dispatch_delay_state.lock:
        now = monotonic()
        due_at = _whatsapp_dispatch_delay_state.due_by_key.get(delay_key)
        if due_at is None:
            next_gap_seconds = sample_whatsapp_dispatch_delay_seconds()
            due_at = now + next_gap_seconds
            _whatsapp_dispatch_delay_state.due_by_key[delay_key] = due_at
        return max(0.0, due_at - now)


async def enforce_email_dispatch_spacing(*, delay_key: str) -> bool:
    """Return True when one email delay key is ready for dispatch."""
    wait_seconds = await get_email_dispatch_wait_seconds(delay_key)
    return wait_seconds <= 0


async def enforce_whatsapp_dispatch_spacing(*, delay_key: str) -> bool:
    """Return True when one WhatsApp delay key is ready for dispatch."""
    wait_seconds = await get_whatsapp_dispatch_wait_seconds(delay_key)
    return wait_seconds <= 0


def build_backend_client() -> httpx.AsyncClient:
    """Create one shared async HTTP client for backend API requests."""
    headers = (
        {INTERNAL_API_TOKEN_HEADER: INTERNAL_API_TOKEN}
        if INTERNAL_API_TOKEN
        else {}
    )
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), headers=headers)


def backend_url(path: str) -> str:
    """Build absolute backend API URL from one path."""
    return f"{BACKEND_BASE_URL}{path}"


def build_contadores_lead_review_url(lead_id: str) -> str:
    """Build the backoffice URL for one Contadores lead."""
    query = urlencode({"section": "contadores", "contadores_lead": lead_id})
    return f"{CONTADORES_REVIEW_BASE_URL}/?{query}"


async def is_backend_healthy(client: httpx.AsyncClient) -> bool:
    """Return True when backend health endpoint is reachable."""
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
    """Wait until backend health endpoint becomes reachable."""
    start = monotonic()
    while True:
        if await is_backend_healthy(client):
            return True
        if monotonic() - start >= timeout_seconds:
            return False
        await asyncio.sleep(poll_seconds)


def automated_auditor_daily_tag(run_date: date) -> str:
    """Build the stable per-day intake tag."""
    return f"{AUTOMATED_AUDITOR_TAG_PREFIX}:{run_date.isoformat()}"


def automated_auditor_industry_tag(industry: str) -> str | None:
    """Build one readable industry tag from discovery output."""
    text = re.sub(r"[^a-z0-9]+", "-", str(industry or "").strip().lower()).strip("-")
    if not text:
        return None
    return f"industry:{text}"


def build_automated_auditor_tags(
    *,
    run_date: date,
    industry: str,
    weekend_hold: bool,
) -> list[str]:
    """Build the tags used when the bot loads a discovered company."""
    tags = [
        AUTOMATED_AUDITOR_TAG_PREFIX,
        automated_auditor_daily_tag(run_date),
    ]
    industry_tag = automated_auditor_industry_tag(industry)
    if industry_tag:
        tags.append(industry_tag)
    if weekend_hold:
        tags.append("weekend-hold")
    return tags


def get_automated_auditor_now_utc() -> datetime:
    """Return the current UTC time for daily intake decisions."""
    return datetime.now(timezone.utc)


def should_run_automated_auditor_now(now_local: datetime) -> bool:
    """Return True when the local daily intake window is already open."""
    return (
        now_local.hour,
        now_local.minute,
    ) >= (
        AUTOMATED_AUDITOR_RUN_HOUR_LOCAL,
        AUTOMATED_AUDITOR_RUN_MINUTE_LOCAL,
    )


def should_hold_weekend_audit_delivery(now_local: datetime) -> bool:
    """Hold report delivery when the company is created on Saturday or Sunday."""
    return now_local.weekday() >= 5


def build_weekend_hold_scheduled_send_at(now_local: datetime) -> datetime:
    """Return the next Monday at the configured local evening hour."""
    days_until_monday = 2 if now_local.weekday() == 5 else 1
    monday_local = (now_local + timedelta(days=days_until_monday)).replace(
        hour=AUTOMATED_AUDITOR_WEEKEND_HOLD_HOUR_LOCAL,
        minute=0,
        second=0,
        microsecond=0,
    )
    return monday_local


async def fetch_pending_outbound(client: httpx.AsyncClient, *, limit: int = 200) -> list[PendingDeliveryMessage]:
    """Fetch outbound messages ready for provider dispatch."""
    response = await client.get(
        backend_url("/api/messages/pending-delivery"),
        params={"limit": limit},
    )
    response.raise_for_status()
    payload = PendingDeliveryResponse.model_validate(response.json())
    return payload.messages


async def fetch_contadores_config(client: httpx.AsyncClient) -> ContadoresConfigPayload:
    """Fetch Contadores runtime config from backend."""
    response = await client.get(backend_url("/api/contadores/config"))
    response.raise_for_status()
    return ContadoresConfigPayload.model_validate(response.json())


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
    """Resolve public Google Sheets CSV URL from backend config."""
    base_url = (config.sheet_url or "").strip()
    if not base_url:
        return None
    if "output=csv" in base_url:
        return base_url
    gid = (config.sheet_gid or "").strip()
    separator = "&" if "?" in base_url else "?"
    if gid and "gid=" not in base_url:
        return f"{base_url}{separator}gid={gid}&output=csv"
    if "?" in base_url:
        return f"{base_url}&output=csv"
    return f"{base_url}?output=csv"


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
    return [dict(row) for row in reader]


async def import_contadores_sheet_rows(
    client: httpx.AsyncClient,
    *,
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    """Send fetched sheet rows to backend for upsert."""
    response = await client.post(
        backend_url("/api/contadores/leads/import"),
        json={"rows": rows},
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"status": "invalid"}


async def run_contadores_sheet_sync_iteration(
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Fetch the public Contadores sheet and import new live leads."""
    config = await fetch_contadores_config(client)
    if not config.enabled:
        return {"status": "disabled"}

    rows = await fetch_contadores_sheet_rows(config=config)
    filtered_rows = [
        {
            "id": str(row.get("id") or "").strip(),
            "created_time": str(row.get("created_time") or "").strip() or None,
            "platform": str(row.get("platform") or "").strip() or None,
            "email": str(row.get("email") or "").strip() or None,
            "full_name": str(row.get("full_name") or "").strip() or None,
            "phone_number": str(row.get("phone_number") or "").strip(),
            "lead_status": str(row.get("lead_status") or "").strip() or None,
            "is_contactado": str(row.get("is_contactado") or "").strip() or None,
        }
        for row in rows
        if (
            str(row.get("id") or "").strip()
            and str(row.get("phone_number") or "").strip()
            and str(row.get("is_contactado") or "").strip().lower() not in {"true", "1", "yes"}
        )
    ]
    result = await import_contadores_sheet_rows(
        client,
        rows=filtered_rows,
    )
    result["status"] = "ok"
    result["fetched"] = len(rows)
    result["submitted"] = len(filtered_rows)
    return result


async def fetch_company_summaries(
    client: httpx.AsyncClient,
    *,
    limit: int = AUTOMATED_AUDITOR_COMPANY_LIST_LIMIT,
) -> list[CompanySummary]:
    """Fetch recent companies so the bot can build exclusions and daily quotas."""
    response = await client.get(
        backend_url("/api/companies"),
        params={"limit": limit},
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [CompanySummary.model_validate(item) for item in payload]


async def discover_auditor_companies(
    client: httpx.AsyncClient,
    *,
    count: int,
    exclude_company_urls: list[str],
    exclude_company_names: list[str],
) -> list[AuditorCandidateCompany]:
    """Call the backend discovery endpoint for strong auditor-fit companies."""
    response = await client.post(
        backend_url("/api/companies/discover-auditor-candidates"),
        json={
            "count": count,
            "exclude_company_urls": exclude_company_urls,
            "exclude_company_names": exclude_company_names,
        },
        timeout=httpx.Timeout(AUTOMATED_AUDITOR_DISCOVERY_TIMEOUT_SECONDS, connect=10.0),
    )
    response.raise_for_status()
    payload = DiscoverAuditorCompaniesResponse.model_validate(response.json())
    return payload.companies


async def scan_company_for_automated_auditor(
    client: httpx.AsyncClient,
    *,
    candidate: AuditorCandidateCompany,
    tags: list[str],
) -> ScanCompanyTaskResponse:
    """Create one company through the normal scan endpoint."""
    response = await client.post(
        backend_url("/api/companies/scan"),
        json={
            "url": candidate.website_url,
            "objective": AUTOMATED_AUDITOR_OBJECTIVE,
            "tags": tags,
            "conversation_automation_enabled": True,
            "ceo_delivery_enabled": True,
        },
        timeout=httpx.Timeout(AUTOMATED_AUDITOR_SCAN_TIMEOUT_SECONDS, connect=10.0),
    )
    response.raise_for_status()
    return ScanCompanyTaskResponse.model_validate(response.json())


async def update_company_report_schedule(
    client: httpx.AsyncClient,
    *,
    company_id: str,
    scheduled_send_at: datetime,
) -> UpdateCompanyReportScheduleResponse:
    """Apply an exact report delivery timestamp for one company."""
    response = await client.put(
        backend_url(f"/api/companies/{company_id}/report-schedule"),
        json={"scheduled_send_at": scheduled_send_at.isoformat()},
    )
    response.raise_for_status()
    return UpdateCompanyReportScheduleResponse.model_validate(response.json())


async def run_automated_auditor_intake_iteration(
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Discover and load the missing daily auditor companies."""
    if not AUTOMATED_AUDITOR_INTAKE_ENABLED:
        return {"status": "disabled"}

    now_utc = get_automated_auditor_now_utc()
    now_local = now_utc.astimezone(AUTOMATED_AUDITOR_TIMEZONE)
    if not should_run_automated_auditor_now(now_local):
        return {
            "status": "before_window",
            "local_date": now_local.date().isoformat(),
            "target_count": AUTOMATED_AUDITOR_COMPANIES_PER_DAY,
        }

    companies = await fetch_company_summaries(client)
    run_tag = automated_auditor_daily_tag(now_local.date())
    already_loaded_today = sum(1 for item in companies if run_tag in item.tags)
    remaining = max(0, AUTOMATED_AUDITOR_COMPANIES_PER_DAY - already_loaded_today)
    if remaining <= 0:
        return {
            "status": "quota_met",
            "local_date": now_local.date().isoformat(),
            "target_count": AUTOMATED_AUDITOR_COMPANIES_PER_DAY,
            "already_loaded_today": already_loaded_today,
        }

    weekend_hold = should_hold_weekend_audit_delivery(now_local)
    scheduled_send_at = (
        build_weekend_hold_scheduled_send_at(now_local)
        if weekend_hold
        else None
    )
    excluded_company_urls = {item.source_url for item in companies if item.source_url}
    excluded_company_names = {item.company_name for item in companies if item.company_name}
    attempts = 0
    discovered_total = 0
    created = 0
    duplicates = 0
    rejected = 0
    scheduled = 0

    while created < remaining and attempts < AUTOMATED_AUDITOR_DISCOVERY_MAX_ATTEMPTS:
        attempts += 1
        discovered_companies = await discover_auditor_companies(
            client,
            count=remaining - created,
            exclude_company_urls=sorted(excluded_company_urls),
            exclude_company_names=sorted(excluded_company_names),
        )
        if not discovered_companies:
            continue

        discovered_total += len(discovered_companies)
        for candidate in discovered_companies:
            excluded_company_urls.add(candidate.website_url)
            if candidate.company_name:
                excluded_company_names.add(candidate.company_name)

            tags = build_automated_auditor_tags(
                run_date=now_local.date(),
                industry=candidate.industry,
                weekend_hold=weekend_hold,
            )
            try:
                result = await scan_company_for_automated_auditor(
                    client,
                    candidate=candidate,
                    tags=tags,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response is not None and exc.response.status_code == 422:
                    rejected += 1
                    continue
                raise

            if result.duplicate_ignored:
                duplicates += 1
                continue

            created += 1
            if scheduled_send_at is not None:
                await update_company_report_schedule(
                    client,
                    company_id=result.company_id,
                    scheduled_send_at=scheduled_send_at,
                )
                scheduled += 1

            if created >= remaining:
                break

    return {
        "status": "completed",
        "local_date": now_local.date().isoformat(),
        "target_count": AUTOMATED_AUDITOR_COMPANIES_PER_DAY,
        "already_loaded_today": already_loaded_today,
        "discovered": discovered_total,
        "created": created,
        "duplicates": duplicates,
        "rejected": rejected,
        "attempts": attempts,
        "scheduled_weekend_holds": scheduled,
        "remaining_after": max(0, remaining - created),
        "run_tag": run_tag,
    }


def should_apply_email_dispatch_delay(item: PendingDeliveryMessage) -> bool:
    """Delay only cold outbound emails, not active back-and-forth replies."""
    return not item.contact_has_inbound


async def fetch_tracked_contact_values(
    client: httpx.AsyncClient,
    *,
    channel: str,
) -> set[str]:
    """Fetch tracked normalized contact values for one channel."""
    response = await client.get(
        backend_url("/api/contacts/tracked-values"),
        params={"channel": channel},
    )
    response.raise_for_status()
    payload = TrackedContactValuesResponse.model_validate(response.json())
    return {value for value in payload.values if value}


async def fetch_tracked_email_senders(client: httpx.AsyncClient) -> set[str]:
    """Fetch tracked normalized email sender values from backend."""
    conversation_senders = await fetch_tracked_contact_values(client, channel="email")
    crm_senders = await fetch_tracked_crm_senders(client)
    return conversation_senders | crm_senders


async def fetch_tracked_crm_senders(client: httpx.AsyncClient) -> set[str]:
    """Fetch tracked CRM sender values."""
    response = await client.get(
        backend_url("/api/crm/tracked-senders"),
    )
    if response.status_code == 404:
        return set()
    response.raise_for_status()
    payload = CrmTrackedSendersResponse.model_validate(response.json())
    return {str(value).strip().lower() for value in payload.values if str(value).strip()}


async def fetch_pending_crm_outbound(
    client: httpx.AsyncClient,
    *,
    limit: int = 200,
) -> list[PendingCrmOutboundMessage]:
    """Fetch pending manual CRM replies ready for email dispatch."""
    response = await client.get(
        backend_url("/api/crm/outbound/pending"),
        params={"limit": limit},
    )
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = PendingCrmOutboundResponse.model_validate(response.json())
    return payload.messages


async def mark_backend_crm_message_sent(
    client: httpx.AsyncClient,
    *,
    message_id: int,
    receipt: DeliveryReceipt,
) -> MarkCrmMessageSentResponse:
    """Persist provider send metadata for one CRM outbound reply."""
    response = await client.post(
        backend_url(f"/api/crm/messages/{message_id}/mark-sent"),
        json={
            "gmail_message_id": receipt.external_id,
            "gmail_thread_id": receipt.thread_id,
            "rfc_message_id": receipt.rfc_message_id,
            "from_email": receipt.from_email,
        },
    )
    response.raise_for_status()
    return MarkCrmMessageSentResponse.model_validate(response.json())


async def register_backend_crm_inbound(
    client: httpx.AsyncClient,
    *,
    event: EmailInboundEvent,
) -> CrmInboundMessageResponse:
    """Register one inbound CEO reply against the CRM inbox."""
    if not event.thread_id:
        return CrmInboundMessageResponse(status="ignored", reason="missing_thread_id")
    response = await client.post(
        backend_url("/api/crm/messages/inbound"),
        json={
            "gmail_message_id": event.message_id,
            "gmail_thread_id": event.thread_id,
            "from_email": event.from_email,
            "subject": event.subject,
            "body": event.plain_text,
            "in_reply_to": event.in_reply_to,
            "references": event.references,
            "received_at": None,
        },
    )
    if response.status_code == 404:
        return CrmInboundMessageResponse(status="ignored", reason="endpoint_not_available")
    response.raise_for_status()
    return CrmInboundMessageResponse.model_validate(response.json())


async def register_backend_report_delivery_sent(
    client: httpx.AsyncClient,
    *,
    company_id: str,
    participant_email: str,
    subject: str,
    body: str,
    receipt: DeliveryReceipt,
) -> ReportDeliverySentResponse:
    """Seed the CRM thread after the first audit email is sent."""
    if not receipt.thread_id:
        raise RuntimeError("Missing AgentMail thread_id for CRM report-delivery seed")
    response = await client.post(
        backend_url("/api/crm/report-delivery/sent"),
        json={
            "company_id": company_id,
            "participant_email": participant_email,
            "subject": subject,
            "body": body,
            "gmail_thread_id": receipt.thread_id,
            "gmail_message_id": receipt.external_id,
            "rfc_message_id": receipt.rfc_message_id,
            "from_email": receipt.from_email,
        },
    )
    response.raise_for_status()
    return ReportDeliverySentResponse.model_validate(response.json())


async def mark_backend_message_delivered(
    client: httpx.AsyncClient,
    *,
    company_id: str,
    contact_id: str,
    message_id: int,
    receipt: DeliveryReceipt,
) -> None:
    """Mark one backend outbound message as delivered."""
    body = {
        "status": "delivered",
        "external_id": receipt.external_id,
        "inbox_id": receipt.inbox_id,
        "inbox_address": receipt.inbox_address,
        "thread_id": receipt.thread_id,
        "rfc_message_id": receipt.rfc_message_id,
    }
    response = await client.put(
        backend_url(f"/api/companies/{company_id}/contacts/{contact_id}/messages/{message_id}/delivery"),
        json=body,
    )
    response.raise_for_status()


async def mark_backend_message_sent(
    client: httpx.AsyncClient,
    *,
    company_id: str,
    contact_id: str,
    message_id: int,
    receipt: DeliveryReceipt,
) -> None:
    """Mark one backend outbound message as sent after provider accepts send."""
    body = {
        "status": "sent",
        "external_id": receipt.external_id,
        "inbox_id": receipt.inbox_id,
        "inbox_address": receipt.inbox_address,
        "thread_id": receipt.thread_id,
        "rfc_message_id": receipt.rfc_message_id,
    }
    response = await client.put(
        backend_url(f"/api/companies/{company_id}/contacts/{contact_id}/messages/{message_id}/delivery"),
        json=body,
    )
    response.raise_for_status()


async def mark_backend_message_failed(
    client: httpx.AsyncClient,
    *,
    company_id: str,
    contact_id: str,
    message_id: int,
) -> None:
    """Mark one backend outbound message as permanently failed."""
    response = await client.put(
        backend_url(f"/api/companies/{company_id}/contacts/{contact_id}/messages/{message_id}/delivery"),
        json={"status": "failed"},
    )
    response.raise_for_status()


async def update_backend_message_text(
    client: httpx.AsyncClient,
    *,
    company_id: str,
    contact_id: str,
    message_id: int,
    text: str,
) -> None:
    """Update one outbound message text to match what provider sent."""
    response = await client.put(
        backend_url(f"/api/companies/{company_id}/contacts/{contact_id}/messages/{message_id}"),
        json={"text": text},
    )
    response.raise_for_status()


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
    """Mark one Contadores outbound message as provider-accepted."""
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
    """Forward one raw WhatsApp inbound event to unified Contadores backend routing."""
    response = await client.post(
        backend_url("/api/contadores/whatsapp/inbound"),
        json={
            "phone": event.phone,
            "text": event.text,
            "external_id": event.external_id,
            "in_reply_to": event.in_reply_to,
        },
    )
    response.raise_for_status()
    payload = ContadoresWhatsAppInboundResponse.model_validate(response.json())
    return payload.model_dump()


async def run_contadores_automation_iteration(
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    """Ask backend to advance Contadores automation state."""
    response = await client.post(backend_url("/api/contadores/automation/tick"))
    response.raise_for_status()
    return ContadoresAutomationTickResponse.model_validate(response.json()).model_dump()


async def fetch_pending_contadores_alerts(
    client: httpx.AsyncClient,
) -> list[PendingContadoresAlertItem]:
    """Fetch Contadores leads waiting for human notification emails."""
    response = await client.get(backend_url("/api/contadores/alerts/pending"))
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
) -> list[dict[str, Any]]:
    """Send Contadores needs-human notification emails when required."""
    items = await fetch_pending_contadores_alerts(client)
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

    crm_inbox = await email_provider.ensure_crm_inbox()
    outcomes: list[dict[str, Any]] = []
    for item in items:
        recipient_list = [email for email in item.alert_emails if email]
        if not recipient_list:
            outcomes.append(
                {
                    "lead_id": item.lead_id,
                    "status": "skipped",
                    "reason": "missing_alert_emails",
                }
            )
            continue

        body_lines = [
            "Se frenó la automatización de Contadores y requiere revisión humana.",
            "",
            f"Lead ID: {item.lead_id}",
            f"Lead link: {build_contadores_lead_review_url(item.lead_id)}",
            f"Nombre: {item.full_name or '-'}",
            f"WhatsApp: {item.phone}",
            f"Email: {item.email or '-'}",
            f"Stage: {item.stage}",
            f"Motivo: {item.reason or '-'}",
            "",
            "Último mensaje inbound:",
            item.latest_inbound_text or "-",
        ]
        for recipient in recipient_list:
            await email_provider.send_message(
                inbox_id=crm_inbox.inbox_id,
                inbox_address=crm_inbox.inbox_address,
                recipient=recipient,
                text="\n".join(body_lines),
                subject=f"[Contadores] needs_human {item.phone}",
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
                "recipients": recipient_list,
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
    """Forward one Calendly booking event to backend by tracking token."""
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


async def resolve_backend_contact(
    client: httpx.AsyncClient,
    *,
    channel: str,
    value: str,
    inbox_id: str | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
) -> ResolvedContact | None:
    """Resolve contact target from inbound provider metadata."""
    response = await client.get(
        backend_url("/api/contacts/resolve"),
        params={
            "channel": channel,
            "value": value,
            "inbox_id": inbox_id,
            "thread_id": thread_id,
            "in_reply_to": in_reply_to,
        },
    )

    if response.status_code in {404, 409}:
        logger.debug(
            "No unique backend contact match for channel=%s value=%s status=%s",
            channel,
            value,
            response.status_code,
        )
        return None

    response.raise_for_status()
    return ResolvedContact.model_validate(response.json())


async def register_backend_inbound(
    client: httpx.AsyncClient,
    *,
    resolved: ResolvedContact,
    message: str,
    external_id: str | None,
    channel: str,
    inbox_id: str | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> None:
    """Register one inbound message in backend transcript pipeline."""
    body = {
        "message": message,
        "external_id": external_id,
        "channel": channel,
        "inbox_id": inbox_id,
        "thread_id": thread_id,
        "in_reply_to": in_reply_to,
        "references": references,
    }
    response = await client.post(
        backend_url(f"/api/companies/{resolved.company_id}/contacts/{resolved.contact_id}/messages/inbound"),
        json=body,
    )
    response.raise_for_status()


async def update_backend_message_delivery_status_by_external_id(
    client: httpx.AsyncClient,
    *,
    external_id: str,
    status: str,
) -> dict[str, Any]:
    """Update one outbound message delivery status using provider external id."""
    response = await client.put(
        backend_url("/api/messages/delivery/by-external-id"),
        json={
            "external_id": external_id,
            "status": status,
        },
    )
    response.raise_for_status()
    return response.json()


async def fetch_audit_delivery_poll_state(client: httpx.AsyncClient) -> list[AuditDeliveryPollStateItem]:
    """Fetch audit-delivery polling state for all companies."""
    response = await client.get(backend_url("/api/companies/audit-delivery/poll-state"))
    if response.status_code == 404:
        return []
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        return []
    return [AuditDeliveryPollStateItem.model_validate(item) for item in payload]


async def trigger_generate_full_audit(client: httpx.AsyncClient, *, company_id: str) -> bool:
    """Trigger full audit generation task for one company."""
    response = await client.post(
        backend_url(f"/api/companies/{company_id}/audit-delivery/generate-full-audit"),
    )
    if response.status_code in {404, 409}:
        return False
    response.raise_for_status()
    return True


async def fetch_company_audit_ceo_email(
    client: httpx.AsyncClient,
    *,
    company_id: str,
) -> AuditDeliveryCeoEmail:
    """Fetch CEO recipient email for one company."""
    response = await client.get(
        backend_url(f"/api/companies/{company_id}/audit-delivery/ceo-email"),
    )
    response.raise_for_status()
    return AuditDeliveryCeoEmail.model_validate(response.json())


async def fetch_company_audit_email_content(
    client: httpx.AsyncClient,
    *,
    company_id: str,
) -> AuditDeliveryEmailContent:
    """Fetch deterministic subject/body for one company audit delivery email."""
    response = await client.get(
        backend_url(f"/api/companies/{company_id}/audit-delivery/email-content"),
    )
    response.raise_for_status()
    return AuditDeliveryEmailContent.model_validate(response.json())


async def fetch_company_audit_pdf(
    client: httpx.AsyncClient,
    *,
    company_id: str,
) -> AuditDeliveryPdfAttachment | None:
    """Fetch render-on-demand PDF bytes and backend-provided filename."""
    response = await client.get(
        backend_url(f"/api/companies/{company_id}/audit-delivery/pdf"),
    )
    if response.status_code in {404, 409}:
        return None
    response.raise_for_status()
    return AuditDeliveryPdfAttachment(
        filename=parse_content_disposition_filename(
            response.headers.get("Content-Disposition"),
            fallback_name=f"audit-{company_id}.pdf",
        ),
        data=response.content,
    )


async def mark_company_audit_blocked(
    client: httpx.AsyncClient,
    *,
    company_id: str,
    reason: str,
) -> None:
    """Mark one company as blocked for CEO audit delivery."""
    response = await client.post(
        backend_url(f"/api/companies/{company_id}/audit-delivery/mark-blocked"),
        json={"reason": reason},
    )
    if response.status_code == 404:
        return
    response.raise_for_status()


async def clear_company_audit_ceo_email(
    client: httpx.AsyncClient,
    *,
    company_id: str,
) -> None:
    """Delete the stored CEO email so rejected recipients stop retrying."""
    response = await client.put(
        backend_url(f"/api/companies/{company_id}"),
        json={"ceo_email": None},
    )
    if response.status_code == 404:
        return
    response.raise_for_status()


def parse_backend_timestamp(value: str | None) -> datetime | None:
    """Parse backend ISO datetime string to UTC aware datetime."""
    raw = (value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_content_disposition_filename(content_disposition: str | None, fallback_name: str) -> str:
    """Extract one attachment filename from Content-Disposition headers."""
    header = (content_disposition or "").strip()
    utf8_match = re.search(r"filename\*=UTF-8''([^;]+)", header, re.IGNORECASE)
    if utf8_match and utf8_match.group(1):
        return unquote(utf8_match.group(1).strip())
    basic_match = re.search(r'filename="?([^";]+)"?', header, re.IGNORECASE)
    if basic_match and basic_match.group(1):
        return basic_match.group(1).strip()
    return fallback_name


def should_trigger_full_audit(row: AuditDeliveryPollStateItem, *, now: datetime) -> bool:
    """Return True when company metadata says full audit generation should start."""
    if not row.conversation_automation_enabled:
        return False
    if not row.ceo_delivery_enabled:
        return False
    if row.pending_full_audit_task:
        return False
    if row.ceo_delivery_sent_at:
        return False
    if row.has_report_pdf_model:
        return False
    scheduled_send_at = parse_backend_timestamp(row.scheduled_send_at)
    if scheduled_send_at is not None:
        return now >= scheduled_send_at
    created_at = parse_backend_timestamp(row.created_at)
    if created_at is None:
        return False
    if row.report_window_minutes is not None:
        report_window_minutes = max(1, int(row.report_window_minutes))
        return now >= created_at + timedelta(minutes=report_window_minutes)
    report_window_hours = max(1, int(row.report_window_hours or 24))
    return now >= created_at + timedelta(hours=report_window_hours)


async def run_audit_delivery_iteration(
    client: httpx.AsyncClient,
    *,
    email_provider: AgentMailProvider,
) -> dict[str, int]:
    """Run one audit generation + CEO delivery iteration."""
    state_rows = await fetch_audit_delivery_poll_state(client)
    generated_requested = 0
    blocked = 0
    delivered = 0
    now = datetime.now(timezone.utc)
    crm_inbox = None

    for row in state_rows:
        blocked_reason = (row.ceo_delivery_blocked_reason or "").strip()
        if blocked_reason and blocked_reason != "missing_ceo_email":
            continue

        if should_trigger_full_audit(row, now=now):
            requested = await trigger_generate_full_audit(client, company_id=row.company_id)
            if requested:
                generated_requested += 1
            continue

        if not row.has_report_pdf_model or row.ceo_delivery_sent_at:
            continue

        ceo_payload = await fetch_company_audit_ceo_email(client, company_id=row.company_id)
        ceo_email = (ceo_payload.ceo_email or "").strip()
        if not ceo_email:
            await mark_company_audit_blocked(
                client,
                company_id=row.company_id,
                reason="missing_ceo_email",
            )
            blocked += 1
            continue
        if not email_provider.configured:
            continue
        if crm_inbox is None:
            crm_inbox = await email_provider.ensure_crm_inbox()
        if crm_inbox is None:
            continue

        content = await fetch_company_audit_email_content(client, company_id=row.company_id)
        pdf_attachment = await fetch_company_audit_pdf(client, company_id=row.company_id)
        if not pdf_attachment:
            continue

        try:
            receipt = await email_provider.send_message(
                inbox_id=crm_inbox.inbox_id,
                inbox_address=crm_inbox.inbox_address,
                recipient=ceo_email,
                text=content.body,
                subject=content.subject,
                attachments=[
                    EmailAttachment(
                        filename=pdf_attachment.filename,
                        content_type="application/pdf",
                        data=pdf_attachment.data,
                    )
                ],
                thread_id=None,
                in_reply_to=None,
                references=None,
            )
        except Exception as exc:
            if should_remove_audit_delivery_recipient(exc):
                await clear_company_audit_ceo_email(
                    client,
                    company_id=row.company_id,
                )
                await mark_company_audit_blocked(
                    client,
                    company_id=row.company_id,
                    reason="missing_ceo_email",
                )
                blocked += 1
                logger.warning(
                    "Removed rejected CEO email for company_id=%s recipient=%s",
                    row.company_id,
                    ceo_email,
                )
                continue
            logger.exception(
                "❌ Could not deliver CEO audit for company_id=%s recipient=%s",
                row.company_id,
                ceo_email,
            )
            continue

        await register_backend_report_delivery_sent(
            client,
            company_id=row.company_id,
            participant_email=ceo_email,
            subject=content.subject,
            body=content.body,
            receipt=receipt,
        )
        delivered += 1

    return {
        "state_rows": len(state_rows),
        "generated_requested": generated_requested,
        "blocked": blocked,
        "delivered": delivered,
    }


async def dispatch_pending_messages(
    client: httpx.AsyncClient,
    *,
    pending: list[PendingDeliveryMessage],
    email_provider: AgentMailProvider,
    whatsapp_provider: WhatsAppProvider,
) -> list[DispatchResult]:
    """Dispatch backend pending messages through configured providers."""
    results: list[DispatchResult] = []
    active_email_delay_keys = {
        build_message_email_delay_key(item.message_id)
        for item in pending
        if item.contact_type.strip().lower() == "email"
    }
    active_whatsapp_delay_keys = {
        build_message_whatsapp_delay_key(item.message_id)
        for item in pending
        if item.contact_type.strip().lower() in {"whatsapp", "phone"}
    }
    await prune_email_dispatch_delay_keys(
        prefix=EMAIL_DELAY_KEY_PREFIX_MESSAGE,
        active_keys=active_email_delay_keys,
    )
    await prune_whatsapp_dispatch_delay_keys(
        active_keys=active_whatsapp_delay_keys,
    )

    for item in pending:
        channel = item.contact_type.strip().lower()
        email_delay_key = build_message_email_delay_key(item.message_id) if channel == "email" else None
        whatsapp_delay_key = (
            build_message_whatsapp_delay_key(item.message_id)
            if channel in {"whatsapp", "phone"}
            else None
        )
        if channel == "email" and not email_provider.configured:
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.contact_id,
                    channel=channel,
                    status="deferred",
                    contact_value=item.contact_value,
                    error="email_provider_not_configured",
                )
            )
            continue
        if channel in {"whatsapp", "phone"} and not whatsapp_provider.configured:
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.contact_id,
                    channel=channel,
                    status="deferred",
                    contact_value=item.contact_value,
                    error="whatsapp_provider_not_configured",
                )
            )
            continue
        if channel not in {"email", "whatsapp", "phone"}:
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.contact_id,
                    channel=channel,
                    status="deferred",
                    contact_value=item.contact_value,
                    error="unsupported_contact_type",
                )
            )
            continue

        try:
            if channel == "email":
                if should_apply_email_dispatch_delay(item):
                    wait_seconds = await get_email_dispatch_wait_seconds(email_delay_key or "")
                    if wait_seconds > 0:
                        results.append(
                            DispatchResult(
                                message_id=item.message_id,
                                contact_id=item.contact_id,
                                channel=channel,
                                status="deferred",
                                contact_value=item.contact_value,
                                error="email_delay_not_elapsed",
                                wait_seconds=wait_seconds,
                            )
                        )
                        continue
                elif email_delay_key:
                    await clear_email_dispatch_delay_key(email_delay_key)
            if channel in {"whatsapp", "phone"}:
                wait_seconds = await get_whatsapp_dispatch_wait_seconds(whatsapp_delay_key or "")
                if wait_seconds > 0:
                    results.append(
                        DispatchResult(
                            message_id=item.message_id,
                            contact_id=item.contact_id,
                            channel=channel,
                            status="deferred",
                            contact_value=item.contact_value,
                            error="whatsapp_delay_not_elapsed",
                            wait_seconds=wait_seconds,
                        )
                    )
                    continue
            receipt = await dispatch_one_message(
                item=item,
                email_provider=email_provider,
                whatsapp_provider=whatsapp_provider,
            )
            if receipt.delivered_text and receipt.delivered_text.strip() and receipt.delivered_text.strip() != item.text.strip():
                await update_backend_message_text(
                    client,
                    company_id=item.company_id,
                    contact_id=item.contact_id,
                    message_id=item.message_id,
                    text=receipt.delivered_text,
                )
            await mark_backend_message_sent(
                client,
                company_id=item.company_id,
                contact_id=item.contact_id,
                message_id=item.message_id,
                receipt=receipt,
            )
            if email_delay_key:
                await clear_email_dispatch_delay_key(email_delay_key)
            if whatsapp_delay_key:
                await clear_whatsapp_dispatch_delay_key(whatsapp_delay_key)
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.contact_id,
                    channel=channel,
                    status="sent" if channel == "email" else "delivered",
                    contact_value=item.contact_value,
                )
            )
        except InvalidRecipientEmailError as exc:
            logger.error(
                "Permanent email dispatch failure for message_id=%s contact_id=%s value=%s: %s",
                item.message_id,
                item.contact_id,
                item.contact_value,
                exc,
            )
            await mark_backend_message_failed(
                client,
                company_id=item.company_id,
                contact_id=item.contact_id,
                message_id=item.message_id,
            )
            if email_delay_key:
                await clear_email_dispatch_delay_key(email_delay_key)
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.contact_id,
                    channel=channel,
                    status="failed",
                    contact_value=item.contact_value,
                    error=str(exc),
                )
            )
        except Exception as exc:
            logger.exception(
                "Failed dispatch for message_id=%s contact_id=%s channel=%s",
                item.message_id,
                item.contact_id,
                channel,
            )
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.contact_id,
                    channel=channel,
                    status="failed",
                    contact_value=item.contact_value,
                    error=str(exc),
                )
            )

    return results


async def dispatch_one_contadores_message(
    *,
    item: PendingContadoresDeliveryMessage,
    whatsapp_provider: WhatsAppProvider,
) -> DeliveryReceipt:
    """Dispatch one Contadores WhatsApp outbound message."""
    if (item.media_type or "").strip().lower() == "video":
        return await whatsapp_provider.send_video(
            to=item.phone or item.normalized_phone,
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
            to=item.phone or item.normalized_phone,
            template_name=item.whatsapp_template_name or "",
            template_language=item.whatsapp_template_language or "es",
            body_params=item.whatsapp_template_body_params,
            delivered_text=item.text,
        )
    return await whatsapp_provider.send_message(item.phone or item.normalized_phone, item.text)


async def dispatch_pending_contadores_messages(
    client: httpx.AsyncClient,
    *,
    pending: list[PendingContadoresDeliveryMessage],
    whatsapp_provider: WhatsAppProvider,
) -> list[DispatchResult]:
    """Dispatch Contadores pending messages through WhatsApp without extra random delay."""
    results: list[DispatchResult] = []
    if not pending:
        return results
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


async def dispatch_pending_crm_messages(
    client: httpx.AsyncClient,
    *,
    pending: list[PendingCrmOutboundMessage],
    email_provider: AgentMailProvider,
) -> list[DispatchResult]:
    """Dispatch pending CRM replies immediately with no extra spacing."""
    results: list[DispatchResult] = []
    crm_inbox = await email_provider.ensure_crm_inbox() if email_provider.configured else None
    for item in pending:
        if crm_inbox is None:
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.thread_id,
                    channel="email",
                    status="deferred",
                    contact_value=item.participant_email,
                    error="email_provider_not_configured",
                )
            )
            continue

        try:
            receipt = await email_provider.send_message(
                inbox_id=crm_inbox.inbox_id,
                inbox_address=crm_inbox.inbox_address,
                recipient=item.participant_email,
                text=item.body,
                subject=item.subject,
                attachments=None,
                thread_id=item.gmail_thread_id,
                in_reply_to=item.latest_sent_rfc_message_id,
                references=item.latest_sent_rfc_message_id,
            )
            await mark_backend_crm_message_sent(
                client,
                message_id=item.message_id,
                receipt=receipt,
            )
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.thread_id,
                    channel="email",
                    status="sent",
                    contact_value=item.participant_email,
                )
            )
        except Exception as exc:
            logger.exception(
                "Failed CRM dispatch for message_id=%s thread_id=%s",
                item.message_id,
                item.thread_id,
            )
            results.append(
                DispatchResult(
                    message_id=item.message_id,
                    contact_id=item.thread_id,
                    channel="email",
                    status="failed",
                    contact_value=item.participant_email,
                    error=str(exc),
                )
            )

    return results


async def dispatch_one_message(
    *,
    item: PendingDeliveryMessage,
    email_provider: AgentMailProvider,
    whatsapp_provider: WhatsAppProvider,
) -> DeliveryReceipt:
    """Dispatch one backend pending message by contact channel."""
    channel = item.contact_type.strip().lower()
    if channel == "email":
        inbox = await email_provider.ensure_contact_inbox(
            contact_id=item.contact_id,
            company_id=item.company_id,
            current_inbox_id=item.email_inbox_id,
            current_inbox_address=item.email_inbox_address,
            current_thread_id=item.email_thread_id,
        )
        return await email_provider.send_message(
            inbox_id=inbox.inbox_id,
            inbox_address=inbox.inbox_address,
            recipient=item.contact_value,
            text=item.text,
            subject=None,
            attachments=None,
            thread_id=item.email_thread_id,
            in_reply_to=item.email_last_outbound_rfc_id,
            references=item.email_last_outbound_rfc_id,
        )

    if channel in {"whatsapp", "phone"}:
        has_template_payload = bool(
            (item.whatsapp_template_name or "").strip()
            and (item.whatsapp_template_language or "").strip()
            and (item.whatsapp_template_client_name or "").strip()
        )
        if not item.contact_has_inbound and has_template_payload:
            return await whatsapp_provider.send_intro_template(
                to=item.contact_value,
                template_name=item.whatsapp_template_name,
                template_language=item.whatsapp_template_language,
                client_name=item.whatsapp_template_client_name,
                company_url=item.whatsapp_template_company_url or item.company_source_url,
            )
        return await whatsapp_provider.send_message(item.contact_value, item.text)

    raise RuntimeError(f"Unsupported contact type for dispatch: {item.contact_type}")


async def process_email_inbound_events(
    client: httpx.AsyncClient,
    *,
    email_provider: AgentMailProvider,
    events: list[EmailInboundEvent],
) -> list[dict[str, Any]]:
    """Resolve and register AgentMail inbound events in backend."""
    outcomes: list[dict[str, Any]] = []

    for event in events:
        should_acknowledge = False
        try:
            if event.thread_id:
                crm_inbound = await register_backend_crm_inbound(
                    client,
                    event=event,
                )
                if crm_inbound.status in {"stored", "duplicate"}:
                    outcomes.append(
                        {
                            "message_id": event.message_id,
                            "inbox_id": event.inbox_id,
                            "status": crm_inbound.status,
                            "company_id": crm_inbound.company_id,
                            "thread_id": crm_inbound.thread_id,
                            "backend_message_id": crm_inbound.message_id,
                            "reason": crm_inbound.reason,
                        }
                    )
                    should_acknowledge = True
                    await email_provider.acknowledge_message(
                        inbox_id=event.inbox_id,
                        message_id=event.message_id,
                    )
                    continue

            resolved = await resolve_backend_contact(
                client,
                channel="email",
                value=event.from_email,
                inbox_id=event.inbox_id,
                thread_id=event.thread_id,
                in_reply_to=event.in_reply_to,
            )
            if not resolved:
                outcomes.append(
                    {
                        "message_id": event.message_id,
                        "inbox_id": event.inbox_id,
                        "status": "ignored",
                        "reason": "contact_not_resolved",
                    }
                )
                should_acknowledge = True
            else:
                await register_backend_inbound(
                    client,
                    resolved=resolved,
                    message=event.plain_text,
                    external_id=event.message_id,
                    channel="email",
                    inbox_id=event.inbox_id,
                    thread_id=event.thread_id,
                    in_reply_to=event.in_reply_to,
                    references=event.references,
                )
                outcomes.append(
                    {
                        "message_id": event.message_id,
                        "inbox_id": event.inbox_id,
                        "status": "processed",
                        "contact_id": resolved.contact_id,
                    }
                )
                should_acknowledge = True
        except Exception as exc:
            logger.exception("Failed processing inbound AgentMail message %s", event.message_id)
            outcomes.append(
                {
                    "message_id": event.message_id,
                    "inbox_id": event.inbox_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        if should_acknowledge:
            await email_provider.acknowledge_message(
                inbox_id=event.inbox_id,
                message_id=event.message_id,
            )

    return outcomes


async def poll_gmail_inbound_batch(
    gmail_provider: GmailProvider,
    *,
    max_results: int = 50,
    tracked_senders: set[str] | None = None,
) -> list[EmailInboundEvent]:
    """Read unread inbound Gmail events for legacy pre-AgentMail threads."""
    if not gmail_provider.configured:
        return []
    return await gmail_provider.list_unread_messages(
        max_results=max_results,
        tracked_senders=tracked_senders,
    )


async def process_legacy_gmail_inbound_events(
    client: httpx.AsyncClient,
    *,
    gmail_provider: GmailProvider,
    events: list[EmailInboundEvent],
) -> list[dict[str, Any]]:
    """Resolve and register Gmail inbound replies for legacy Gmail-sent threads."""
    outcomes: list[dict[str, Any]] = []

    for event in events:
        should_mark_as_read = False
        try:
            crm_inbound = await register_backend_crm_inbound(
                client,
                event=event,
            )
            if crm_inbound.status in {"stored", "duplicate"}:
                outcomes.append(
                    {
                        "message_id": event.message_id,
                        "status": crm_inbound.status,
                        "company_id": crm_inbound.company_id,
                        "thread_id": crm_inbound.thread_id,
                        "backend_message_id": crm_inbound.message_id,
                    }
                )
                should_mark_as_read = True
            else:
                resolved = await resolve_backend_contact(
                    client,
                    channel="email",
                    value=event.from_email,
                    thread_id=event.thread_id,
                    in_reply_to=event.in_reply_to,
                )
                if resolved:
                    await register_backend_inbound(
                        client,
                        resolved=resolved,
                        message=event.plain_text,
                        external_id=event.message_id,
                        channel="email",
                        inbox_id=None,
                        thread_id=event.thread_id,
                        in_reply_to=event.in_reply_to,
                        references=event.references,
                    )
                    outcomes.append(
                        {
                            "message_id": event.message_id,
                            "status": "processed",
                            "contact_id": resolved.contact_id,
                        }
                    )
                    should_mark_as_read = True
                else:
                    outcomes.append(
                        {
                            "message_id": event.message_id,
                            "status": crm_inbound.status,
                            "reason": crm_inbound.reason or "contact_not_resolved",
                        }
                    )
                    should_mark_as_read = True
        except Exception as exc:
            logger.exception("Failed processing legacy Gmail message %s", event.message_id)
            outcomes.append(
                {
                    "message_id": event.message_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )

        if should_mark_as_read:
            await gmail_provider.mark_as_read(event.message_id)

    return outcomes


async def process_whatsapp_inbound_event(
    client: httpx.AsyncClient,
    *,
    event: WhatsAppInboundEvent,
) -> dict[str, Any]:
    """Route one WhatsApp inbound event through backend Contadores/Auditor resolver."""
    result = await process_contadores_whatsapp_inbound_event(
        client,
        event=event,
    )
    result["phone"] = event.phone
    result["in_reply_to"] = event.in_reply_to
    return result


async def process_whatsapp_message_status_event(
    client: httpx.AsyncClient,
    *,
    event: WhatsAppMessageStatusEvent,
) -> dict[str, Any]:
    """Persist one outbound WhatsApp provider status update in backend."""
    if event.status == "failed":
        target_status = "failed"
    elif event.status == "sent":
        target_status = "sent"
    else:
        target_status = "delivered"

    try:
        result = await mark_backend_contadores_message_status(
            client,
            external_id=event.external_id,
            status=target_status,
        )
        result["provider_status"] = event.status
        result["route"] = "contadores"
        return result
    except httpx.HTTPStatusError as exc:
        if exc.response is None or exc.response.status_code != 404:
            raise

    try:
        result = await update_backend_message_delivery_status_by_external_id(
            client,
            external_id=event.external_id,
            status=target_status,
        )
        result["provider_status"] = event.status
        result["route"] = "auditor"
        return result
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return {
                "status": "ignored",
                "reason": "external_id_not_found",
                "external_id": event.external_id,
                "provider_status": event.status,
            }
        raise
