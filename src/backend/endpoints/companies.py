"""Company endpoints for URL -> contacts -> report workflow."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from time import monotonic
from urllib.parse import quote

from attachments import Attachments
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Query, Request, Response, UploadFile
from pydantic import AliasChoices, BaseModel, Field, ValidationError, model_validator

from backend.ai.auditor_company_discovery import (
    AuditorCandidateCompany,
    AuditorCompanyDiscoveryProgram,
)
from backend.ai.auditor_leadership_recipient import AuditorLeadershipRecipientProgram
from backend.ai.batch_input_to_company_urls import BatchInputToCompanyUrlsProgram
from backend.ai.stage1_url_to_contacts import (
    ContactType,
    DiscoveredContact,
    UrlToContactsProgram,
)
from backend.ai.stage2_contact_to_conversation import FirstMessageProgram
from backend.ai.stage3_company_to_report import CompanyReport, CompanyReportProgram
from backend.ai.stage4_report_to_html import ReportPdfModelProgram
from backend.audit_delivery_email_content import (
    build_audit_delivery_pdf_filename,
    get_audit_delivery_email_content as build_deterministic_audit_delivery_email_content,
)
from backend.config import SMART_MODEL
from backend.database import (
    DEFAULT_REPORT_WINDOW_MINUTES,
    Company,
    CompanyLanguage,
    CompanyStatus,
    Contact,
    ContactStatus,
    Message,
    MessageDeliveryStatus,
    Task,
    TaskStatus,
    canonical_contact_type,
    normalize_company_source_url,
    compute_report_window_minutes as compute_persisted_report_window_minutes,
    normalize_contact_value,
    normalize_email,
    normalize_report_window_minutes,
)
from backend.templates import (
    build_intro_template_payload,
    extract_intro_sender_name,
    normalize_intro_sender_name,
    pick_intro_sender_name,
)
from backend.report_pdf import ReportDocumentModel, build_vector_pdf

logger = logging.getLogger(__name__)

companies_router = APIRouter(prefix="/api", tags=["companies"])

DEFAULT_CONTACT_OBJECTIVE = "Evaluate sales process quality through a buyer conversation."
REPORT_TASK_TIMEOUT_SECONDS = 240
REPORT_HTML_TIMEOUT_SECONDS = max(10 * 60, REPORT_TASK_TIMEOUT_SECONDS * 3)
FULL_AUDIT_TIMEOUT_SECONDS = REPORT_TASK_TIMEOUT_SECONDS + REPORT_HTML_TIMEOUT_SECONDS
BATCH_SCAN_URL_EXTRACTION_TIMEOUT_SECONDS = 180
SCAN_COMPANY_TIMEOUT_SECONDS = max(300, int(os.getenv("SCAN_COMPANY_TIMEOUT_SECONDS", "3000")))
BATCH_SCAN_MAX_CONCURRENCY = max(1, int(os.getenv("BATCH_SCAN_MAX_CONCURRENCY", "3")))
FULL_AUDIT_TASK_TYPE = "generate_company_full_audit_core"
MISSING_LEADERSHIP_RECIPIENT_DETAIL = "No leadership recipient email was found for this company."
REPORT_SCHEDULE_ALIGNMENT_TOLERANCE_SECONDS = 1.0
DEV_TEXT_SOURCE_LABEL_FALLBACK = "Dev text input"
BATCH_SCAN_SECTION_SEPARATOR = "----"


class ContactSummary(BaseModel):
    """Contact state for UI."""

    id: str
    type: str
    value: str
    notes: str | None = None
    additional_info: str | None = None
    status: str = ContactStatus.ACTIVE.value
    archived: bool = False
    objective: str | None = None
    conversation_done: bool = False
    wa_link: str | None = None
    email_link: str | None = None
    email_subject: str | None = None
    email_thread_link: str | None = None
    requires_email_thread_link: bool = False
    message_count: int = 0
    pending_delivery: bool = False
    pending_delivery_count: int = 0
    latest_message: Message | None = None
    created_at: str
    updated_at: str


class CompanySummary(BaseModel):
    """Company list item."""

    id: str
    source_url: str
    company_name: str
    objective: str | None = None
    tags: list[str] = Field(default_factory=list)
    industry: str = "unknown"
    company_size: str = "unknown"
    language: CompanyLanguage | None = None
    conversation_automation_enabled: bool = False
    ceo_delivery_enabled: bool = False
    has_ceo_email: bool = False
    report_window_hours: int | None = None
    report_window_minutes: int = DEFAULT_REPORT_WINDOW_MINUTES
    scheduled_send_at: str
    ceo_delivery_sent_at: str | None = None
    ceo_delivery_blocked_reason: str | None = None
    status: str
    processing: bool = False
    total_contacts: int
    can_rescan: bool = False
    pending_delivery_contacts: int = 0
    has_contact_reply: bool = False
    has_report_snapshot: bool = False
    has_report_pdf_model: bool = False
    has_report_html: bool = False
    created_at: str
    updated_at: str


class CompanyDetail(CompanySummary):
    """Company detail with contacts."""

    company_info: str = ""
    website_markdown: str = ""
    ceo_email: str | None = None
    contacts: list[ContactSummary] = Field(default_factory=list)


class BatchCompanyScanJob(BaseModel):
    """Internal batch scan job tracked as one company task."""

    task_id: str
    company_id: str
    source_value: str
    request_ceo_email: str | None = None


def resolve_stage2_contact_type(raw_type: str) -> ContactType:
    """Resolve stored contact type into Stage 2 enum with safe fallback."""
    value = canonical_contact_type(raw_type)
    try:
        return ContactType(value)
    except ValueError:
        return ContactType.EMAIL


def should_create_contact_for_company(
    company_id: str,
    *,
    contact_type: str,
    normalized_value: str,
) -> bool:
    """Return True when discovered contact value can be persisted for this company."""
    existing = Contact.list_by_normalized_value(normalized_value, status=None)
    if not existing:
        return True

    normalized_type = canonical_contact_type(contact_type)
    existing_types = {
        item.canonical_type
        for item in existing
        if item.company_id == company_id
    }
    return normalized_type not in existing_types


def whatsapp_link(contact_type: str, contact_value: str) -> str | None:
    """Build wa.me link for WhatsApp contacts."""
    if canonical_contact_type(contact_type) != ContactType.WHATSAPP.value:
        return None
    digits = "".join(ch for ch in contact_value if ch.isdigit())
    if not digits:
        return None
    return f"https://wa.me/{digits}"


def email_link(contact_type: str, contact_value: str) -> str | None:
    """Build generic compose link for email contacts."""
    if contact_type != ContactType.EMAIL.value:
        return None
    value = contact_value.strip()
    if not value or "@" not in value:
        return None
    return f"mailto:{quote(value)}"


def email_thread_link(raw_value: str | None) -> str | None:
    """Normalize stored email thread URL."""
    value = (raw_value or "").strip()
    if not value:
        return None
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return None


def email_gmail_thread_link(thread_id: str | None) -> str | None:
    """Return None because provider thread ids are not browser-stable URLs."""
    del thread_id
    return None


def resolve_contact_objective(contact: Contact, company_objective: str | None) -> str | None:
    """Resolve one contact objective with a stable fallback for legacy rows."""
    return (contact.objective or company_objective or DEFAULT_CONTACT_OBJECTIVE).strip() or None


def first_outbound_message(rows: list[Message]) -> Message | None:
    """Get first outbound message in transcript order."""
    for row in rows:
        if row.from_me and row.text.strip():
            return row
    return None


def compose_first_email_link(
    contact_type: str,
    contact_value: str,
    rows: list[Message],
    email_subject: str | None,
) -> tuple[str | None, str | None]:
    """Build generic compose link + subject for first outbound email draft."""
    if contact_type != ContactType.EMAIL.value:
        return None, None
    address = contact_value.strip()
    if not address or "@" not in address:
        return None, None
    first_outbound = first_outbound_message(rows)
    if not first_outbound:
        return None, None
    subject = (email_subject or "").strip()
    if not subject:
        return None, None
    body = first_outbound.text.strip()
    query_parts = [f"subject={quote(subject)}"]
    if body:
        query_parts.append(f"body={quote(body)}")
    return f"mailto:{quote(address)}?{'&'.join(query_parts)}", subject


def build_contact_summary(contact: Contact, company_objective: str | None) -> ContactSummary:
    """Assemble one UI-friendly contact summary."""
    rows = contact.get_messages()
    normalized_contact_type = contact.canonical_type
    latest_row = rows[-1] if rows else None
    pending_delivery = bool(
        latest_row
        and latest_row.from_me
        and latest_row.delivery_status == MessageDeliveryStatus.UNDELIVERED
    )
    pending_delivery_count = 1 if pending_delivery else 0
    wa_link = whatsapp_link(normalized_contact_type, contact.value)
    manual_thread_link = email_thread_link(contact.additional_info)
    auto_thread_link = email_gmail_thread_link(contact.email_thread_id)
    first_email_open_link, email_subject = compose_first_email_link(
        normalized_contact_type,
        contact.value,
        rows,
        contact.email_subject,
    )
    mail_link = manual_thread_link
    requires_thread_link = False
    if normalized_contact_type == ContactType.EMAIL.value:
        mail_link = manual_thread_link or auto_thread_link
        if not mail_link and len(rows) <= 1:
            mail_link = first_email_open_link
        if not manual_thread_link and not auto_thread_link and len(rows) > 1:
            requires_thread_link = True

    return ContactSummary(
        id=contact.id,
        type=normalized_contact_type,
        value=contact.value,
        notes=contact.notes,
        additional_info=contact.additional_info,
        status=contact.status.value,
        archived=contact.is_archived,
        objective=resolve_contact_objective(contact, company_objective),
        conversation_done=contact.conversation_done,
        wa_link=wa_link,
        email_link=mail_link,
        email_subject=email_subject,
        email_thread_link=manual_thread_link,
        requires_email_thread_link=requires_thread_link,
        message_count=len(rows),
        pending_delivery=pending_delivery,
        pending_delivery_count=pending_delivery_count,
        latest_message=latest_row,
        created_at=format_timestamp_seconds(contact.created_at),
        updated_at=format_timestamp_seconds(contact.updated_at),
    )


def format_timestamp_seconds(value: datetime) -> str:
    """Format datetimes with second precision and UTC marker."""
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def to_utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize one datetime to UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_report_schedule_start(value: datetime | None) -> datetime | None:
    """Normalize schedule computations to UTC minute precision for stable UI editing."""
    utc_value = to_utc_datetime(value)
    if utc_value is None:
        return None
    return utc_value.replace(second=0, microsecond=0)


def compute_report_schedule_at(
    *,
    created_at: datetime,
    report_window_minutes: int | None = None,
    report_window_hours: int | None = None,
    scheduled_send_at: datetime | None = None,
) -> datetime:
    """Compute one company report schedule timestamp from scan start and configured settings."""
    start_utc = normalize_report_schedule_start(created_at)
    if start_utc is None:
        raise HTTPException(status_code=422, detail="Company creation timestamp is invalid")
    scheduled_utc = normalize_report_schedule_start(scheduled_send_at)
    if scheduled_utc is not None:
        return scheduled_utc
    return start_utc + timedelta(
        minutes=normalize_report_window_minutes(
            report_window_minutes,
            report_window_hours=report_window_hours,
        )
    )


def compute_report_window_minutes_for_scheduled_send(
    *,
    created_at: datetime,
    scheduled_send_at: datetime,
) -> int:
    """Resolve whole report-window minutes from an explicit scheduled-send timestamp."""
    start_utc = normalize_report_schedule_start(created_at)
    scheduled_raw_utc = to_utc_datetime(scheduled_send_at)
    scheduled_utc = normalize_report_schedule_start(scheduled_send_at)
    if start_utc is None or scheduled_utc is None or scheduled_raw_utc is None:
        raise HTTPException(status_code=422, detail="scheduled_send_at is invalid")
    if abs((scheduled_raw_utc - scheduled_utc).total_seconds()) > REPORT_SCHEDULE_ALIGNMENT_TOLERANCE_SECONDS:
        raise HTTPException(
            status_code=422,
            detail="scheduled_send_at must stay aligned to the scan start in whole-minute increments",
        )

    delta_seconds = (scheduled_utc - start_utc).total_seconds()
    if delta_seconds < 60:
        raise HTTPException(
            status_code=422,
            detail="scheduled_send_at must be at least 1 minute after scan start",
        )

    resolved_minutes = round(delta_seconds / 60)
    aligned_seconds = float(max(1, resolved_minutes) * 60)
    if abs(delta_seconds - aligned_seconds) > REPORT_SCHEDULE_ALIGNMENT_TOLERANCE_SECONDS:
        raise HTTPException(
            status_code=422,
            detail="scheduled_send_at must stay aligned to the scan start in whole-minute increments",
        )
    return max(1, resolved_minutes)


def get_company_report_schedule_at(company: Company) -> datetime:
    """Resolve one company scheduled-send timestamp from persisted state."""
    return compute_report_schedule_at(
        created_at=company.created_at,
        report_window_hours=company.report_window_hours,
        scheduled_send_at=company.report_scheduled_send_at,
    )


def get_company_report_window_minutes(company: Company) -> int:
    """Resolve one company configured report window in minutes."""
    if company.report_scheduled_send_at is not None:
        return compute_report_window_minutes_for_scheduled_send(
            created_at=company.created_at,
            scheduled_send_at=company.report_scheduled_send_at,
        )
    return compute_persisted_report_window_minutes(
        company.created_at,
        report_window_hours=company.report_window_hours,
    )


def get_legacy_report_window_hours(report_window_minutes: int) -> int | None:
    """Expose the legacy hour alias only for exact whole-hour schedules."""
    normalized_minutes = normalize_report_window_minutes(report_window_minutes)
    if normalized_minutes % 60 != 0:
        return None
    return max(1, normalized_minutes // 60)


def can_rescan_company(
    company: Company,
    *,
    total_contacts: int | None = None,
    pending_task_types: list[str] | None = None,
) -> bool:
    """Return True when one existing company can be rescanned in place."""
    if (total_contacts if total_contacts is not None else company.count_contacts()) > 0:
        return False
    if pending_task_types is None:
        pending_task_types = Task.list_pending_task_types_for_resource(resource_id=company.id)
    if pending_task_types:
        return False
    return bool(normalize_company_source_url(company.source_url))


def has_elapsed_report_window(
    *,
    start: datetime,
    now: datetime,
    report_window_minutes: int | None = None,
    report_window_hours: int | None = None,
    scheduled_send_at: datetime | None = None,
) -> bool:
    """Return True when elapsed UTC time reaches the configured company report window."""
    scheduled_at = compute_report_schedule_at(
        created_at=start,
        report_window_minutes=report_window_minutes,
        report_window_hours=report_window_hours,
        scheduled_send_at=scheduled_send_at,
    )
    now_utc = normalize_report_schedule_start(now)
    if now_utc is None or now_utc < scheduled_at:
        return False
    return now_utc >= scheduled_at


def build_company_summary(company: Company) -> CompanySummary:
    """Assemble one company summary row."""
    total = company.count_contacts()
    pending_delivery_contacts = Message.count_contacts_with_pending_delivery(company.id)
    has_contact_reply = Message.count_contacts_with_inbound_messages(company.id) > 0
    pending_task_types = Task.list_pending_task_types_for_resource(resource_id=company.id)
    report_window_minutes = get_company_report_window_minutes(company)
    scheduled_send_at = get_company_report_schedule_at(company)
    status = (
        CompanyStatus.INITIALIZING.value
        if pending_task_types
        else (
            company.status.value
            if isinstance(company.status, CompanyStatus)
            else str(company.status)
        )
    )
    return CompanySummary(
        id=company.id,
        source_url=company.source_url,
        company_name=company.company_name,
        objective=company.objective,
        tags=list(getattr(company, "tags", []) or []),
        industry=company.industry,
        company_size=company.company_size,
        language=company.language,
        conversation_automation_enabled=company.conversation_automation_enabled,
        ceo_delivery_enabled=company.ceo_delivery_enabled,
        has_ceo_email=bool((getattr(company, "ceo_email", None) or "").strip()),
        report_window_hours=get_legacy_report_window_hours(report_window_minutes),
        report_window_minutes=report_window_minutes,
        scheduled_send_at=format_timestamp_seconds(scheduled_send_at),
        ceo_delivery_sent_at=(
            format_timestamp_seconds(company.ceo_delivery_sent_at)
            if company.ceo_delivery_sent_at
            else None
        ),
        ceo_delivery_blocked_reason=company.ceo_delivery_blocked_reason,
        status=status,
        processing=bool(pending_task_types),
        total_contacts=total,
        can_rescan=can_rescan_company(
            company,
            total_contacts=total,
            pending_task_types=pending_task_types,
        ),
        pending_delivery_contacts=pending_delivery_contacts,
        has_contact_reply=has_contact_reply,
        has_report_snapshot=bool((company.report_snapshot_json or "").strip()),
        has_report_pdf_model=bool((company.report_pdf_model_json or "").strip()),
        has_report_html=bool((company.report_html or "").strip()),
        created_at=format_timestamp_seconds(company.created_at),
        updated_at=format_timestamp_seconds(company.updated_at),
    )


def choose_report_language(company: Company) -> str:
    """Resolve report language fallback when company language is unknown."""
    return company.language.value if company.language else CompanyLanguage.EN.value


def should_generate_full_audit(company: Company, *, now: datetime) -> bool:
    """Return True when one company should start full-audit generation."""
    if not company.conversation_automation_enabled:
        return False
    if not company.ceo_delivery_enabled:
        return False
    if company.ceo_delivery_blocked_reason:
        return False
    if (company.report_pdf_model_json or "").strip():
        return False
    if not has_elapsed_report_window(
        start=company.created_at,
        now=now,
        report_window_hours=company.report_window_hours,
        scheduled_send_at=company.report_scheduled_send_at,
    ):
        return False
    return not Task.has_pending_for_resource(
        resource_id=company.id,
        task_type=FULL_AUDIT_TASK_TYPE,
    )


def build_audit_contact_lines(company: Company) -> str:
    """Build deterministic contact evidence lines for CEO email body."""
    return company.build_reportable_contact_lines()


def build_audit_objective_lines(company: Company) -> str:
    """Build deterministic audited-objective lines for CEO email body."""
    return company.build_reportable_objective_lines()


async def create_contacts_for_company(company_id: str, contacts: list[DiscoveredContact]) -> int:
    """Create contacts for one company without generating first messages."""
    seen: set[tuple[str, str]] = set()
    created = 0
    for discovered in contacts:
        raw_type = discovered.type.value.strip().lower()
        if raw_type == ContactType.PHONE.value:
            logger.info(
                "Skipping generic phone contact for company %s: value=%s notes=%s",
                company_id,
                discovered.value,
                discovered.notes,
            )
            continue

        normalized_type = canonical_contact_type(raw_type)
        normalized_value = normalize_contact_value(normalized_type, discovered.value)
        if not normalized_value:
            logger.warning(
                "Skipping invalid discovered contact for company %s: type=%s raw_value=%s",
                company_id,
                normalized_type,
                discovered.value,
            )
            continue
        key = (normalized_type, normalized_value)
        if key in seen:
            continue
        seen.add(key)
        if not should_create_contact_for_company(
            company_id,
            contact_type=normalized_type,
            normalized_value=normalized_value,
        ):
            logger.info(
                "Skipping duplicated contact value across companies: type=%s value=%s normalized=%s",
                normalized_type,
                discovered.value,
                normalized_value,
            )
            continue
        Contact.create(
            company_id=company_id,
            type=normalized_type,
            value=discovered.value,
            notes=discovered.notes,
            additional_info=None,
            objective=discovered.objective,
        )
        created += 1
    return created


async def generate_first_message_for_contact(
    company: Company,
    contact: Contact,
    *,
    first_message_program: FirstMessageProgram,
    force: bool = False,
) -> tuple[int | None, str | None, bool]:
    """Generate and persist first outbound draft for one contact."""
    if contact.canonical_type != ContactType.EMAIL.value:
        return None, "first message generation is only supported for email contacts", False
    if contact.get_messages() and not force:
        return None, "contact already has conversation", False

    objective = resolve_contact_objective(contact, company.objective)
    contact_type = resolve_stage2_contact_type(contact.canonical_type)
    try:
        first_message = await first_message_program.aforward(
            objective=objective,
            contact_type=contact_type,
            company_context=company.company_info,
            target_language=company.language.value if company.language else None,
        )
    except Exception:
        logger.exception("Failed generating first draft for contact %s", contact.id)
        return None, "failed generating first message", True

    text = first_message.first_message.strip()
    if not text:
        logger.warning("AI returned empty first message for contact %s", contact.id)
        return None, "AI returned empty first message", True
    subject = first_message.subject.strip()
    if not subject:
        logger.warning("AI returned empty first message subject for contact %s", contact.id)
        return None, "AI returned empty first message subject", True

    row = Message.add(
        contact_id=contact.id,
        from_me=True,
        text=text,
    )
    if row.id is None:
        return None, "failed persisting first message", True
    Contact.update_email_subject(contact.id, subject)
    return row.id, None, False


async def generate_first_messages_for_company(company: Company, contacts: list[Contact]) -> tuple[int, int]:
    """Generate and persist first outbound drafts for contacts without conversation."""
    tasks = [
        generate_first_message_for_contact(
            company,
            contact,
            first_message_program=FirstMessageProgram(),
            force=False,
        )
        for contact in contacts
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    generated = 0
    skipped = 0
    for contact, result in zip(contacts, results, strict=False):
        if isinstance(result, Exception):
            logger.error(
                "Unhandled first-message generation error for contact %s: %r",
                contact.id,
                result,
            )
            skipped += 1
            continue

        message_id, _reason, _failed = result
        if message_id is None:
            skipped += 1
        else:
            generated += 1

    return generated, skipped


def ordered_whatsapp_contacts(contacts: list[Contact]) -> list[Contact]:
    """Sort active WhatsApp contacts in deterministic company order."""
    whatsapp_contacts = [
        contact
        for contact in contacts
        if contact.canonical_type == ContactType.WHATSAPP.value
    ]
    return sorted(whatsapp_contacts, key=lambda item: (item.created_at, item.id))


def build_company_whatsapp_intro_payloads(
    company: Company,
    contacts: list[Contact],
) -> dict[str, str]:
    """Build rendered intro texts keyed by contact id for first WhatsApp outbound."""
    ordered_contacts = ordered_whatsapp_contacts(contacts)
    if not ordered_contacts:
        return {}
    used_sender_names: set[str] = set()
    payloads_by_contact: dict[str, str] = {}
    for contact in ordered_contacts:
        first_outbound = first_outbound_message(contact.get_messages())
        if first_outbound:
            existing_sender_name = extract_intro_sender_name(first_outbound.text)
            if existing_sender_name:
                used_sender_names.add(normalize_intro_sender_name(existing_sender_name))
            continue
        sender_name = pick_intro_sender_name(
            company_language=company.language,
            excluded_names=used_sender_names,
        )
        used_sender_names.add(normalize_intro_sender_name(sender_name))
        payloads_by_contact[contact.id] = build_intro_template_payload(
            company_language=company.language,
            company_url=company.source_url,
            client_name=sender_name,
        ).rendered_text
    return payloads_by_contact


async def seed_whatsapp_intro_messages_for_company(
    company: Company,
    contacts: list[Contact],
) -> tuple[int, int]:
    """Persist first WhatsApp intro outbound for contacts without conversation."""
    rendered_intro_by_contact = build_company_whatsapp_intro_payloads(company, contacts)
    if not rendered_intro_by_contact:
        return 0, 0

    seeded = 0
    skipped = 0
    for contact in contacts:
        try:
            if contact.canonical_type != ContactType.WHATSAPP.value:
                continue
            if contact.get_messages():
                skipped += 1
                continue
            text = rendered_intro_by_contact.get(contact.id, "").strip()
            if not text:
                logger.warning("Missing WhatsApp intro template text for contact %s", contact.id)
                skipped += 1
                continue
            row = Message.add(
                contact_id=contact.id,
                from_me=True,
                text=text,
            )
            if row.id is None:
                skipped += 1
                continue
            seeded += 1
        except Exception:
            logger.exception("Failed seeding WhatsApp intro message for contact %s", contact.id)
            skipped += 1
    return seeded, skipped


async def seed_initial_outbound_messages_for_company(
    company: Company,
    contacts: list[Contact],
) -> tuple[int, int]:
    """Seed first outbound messages for all supported channels after discovery."""
    email_contacts = [
        contact
        for contact in contacts
        if contact.canonical_type == ContactType.EMAIL.value
    ]
    generated_email, skipped_email = await generate_first_messages_for_company(company, email_contacts)
    generated_whatsapp, skipped_whatsapp = await seed_whatsapp_intro_messages_for_company(company, contacts)
    generated = generated_email + generated_whatsapp
    skipped = skipped_email + skipped_whatsapp
    return generated, skipped


class ScanCompanyRequest(BaseModel):
    """Scan one company URL and discover contacts."""

    url: str = Field(min_length=1)
    objective: str | None = None
    tags: list[str] = Field(default_factory=list)
    ceo_email: str | None = None
    conversation_automation_enabled: bool = False
    ceo_delivery_enabled: bool = False
    report_window_hours: int | None = Field(default=None, ge=1)
    report_window_minutes: int | None = Field(default=None, ge=1)


class ScanCompanyTaskResponse(BaseModel):
    """Task creation response for company scan."""

    task_id: str | None = None
    company_id: str
    status: str
    duplicate_ignored: bool = False


class BatchScanTaskResponse(BaseModel):
    """Task creation response for batch company scan."""

    task_id: str | None = None
    company_ids: list[str]
    company_count: int
    status: str
    duplicate_count: int = 0
    duplicate_company_ids: list[str] = Field(default_factory=list)
    rejected_count: int = 0
    rejected_urls: list[str] = Field(default_factory=list)


class DiscoverAuditorCompaniesRequest(BaseModel):
    """Discovery request for strong daily auditor candidates."""

    count: int = Field(default=2, ge=1, le=10)
    exclude_company_urls: list[str] = Field(default_factory=list)
    exclude_company_names: list[str] = Field(default_factory=list)


class DiscoverAuditorCompaniesResponse(BaseModel):
    """Structured list of discovery candidates."""

    companies: list[AuditorCandidateCompany] = Field(default_factory=list)


def normalize_company_scan_source_value(source_value: str) -> str:
    """Normalize one scan source URL when it is URL-like, otherwise keep the raw value."""
    raw_value = (source_value or "").strip()
    return normalize_company_source_url(raw_value) or raw_value


def get_duplicate_company_for_scan(source_value: str) -> Company | None:
    """Resolve an existing company row for one normalized scan URL."""
    return Company.get_most_recent_by_normalized_source_url(source_value)


class DevScanCompanyRequest(BaseModel):
    """Scan one company from raw text and continue the normal pipeline."""

    text: str = Field(min_length=1)
    source_label: str | None = None
    objective: str | None = None
    tags: list[str] = Field(default_factory=list)
    ceo_email: str | None = None
    conversation_automation_enabled: bool = False
    ceo_delivery_enabled: bool = False
    report_window_hours: int | None = Field(default=None, ge=1)
    report_window_minutes: int | None = Field(default=None, ge=1)


def resolve_requested_report_window_minutes(
    *,
    report_window_minutes: int | None = None,
    report_window_hours: int | None = None,
) -> int:
    """Resolve one requested report window in minutes from new or legacy inputs."""
    return normalize_report_window_minutes(
        report_window_minutes,
        report_window_hours=report_window_hours,
    )


def build_dev_text_source_label(text: str, source_label: str | None = None) -> str:
    """Build one compact persisted label for dev text scans."""
    explicit_label = (source_label or "").strip()
    if explicit_label:
        return explicit_label

    normalized_text = " ".join(part for part in text.split())
    if not normalized_text:
        return DEV_TEXT_SOURCE_LABEL_FALLBACK
    if len(normalized_text) <= 72:
        return f"Dev text: {normalized_text}"
    return f"Dev text: {normalized_text[:69].rstrip()}..."


async def extract_upload_file_text(file: UploadFile) -> str:
    """Convert one uploaded file to text using the simple-avatar Attachments pattern."""
    await file.seek(0)
    content = await file.read()
    suffix = Path(file.filename or "attachment").suffix.lower()

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        extracted = await asyncio.to_thread(Attachments, tmp_path)
        return str(extracted)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)


async def build_batch_scan_bundle(
    *,
    freeform_text: str,
    files: list[UploadFile],
) -> str:
    """Build the canonical batch extractor bundle from freeform text plus attachments."""
    sections: list[str] = []
    if freeform_text:
        sections.append(f"freeform text:\n{freeform_text}")

    extracted_file_texts = (
        await asyncio.gather(*(extract_upload_file_text(file) for file in files))
        if files
        else []
    )
    for file, extracted_text in zip(files, extracted_file_texts, strict=False):
        if extracted_text:
            sections.append(f"{file.filename or 'attachment'}:\n{extracted_text}")

    return f"\n{BATCH_SCAN_SECTION_SEPARATOR}\n".join(sections)


async def discover_company_contacts(
    stage1: UrlToContactsProgram,
    *,
    url: str | None = None,
    text: str | None = None,
):
    """Dispatch Stage 1 discovery to the correct input mode."""
    normalized_text = (text or "").strip()
    if normalized_text:
        return await stage1.dev_aforward(text=normalized_text)

    normalized_url = (url or "").strip()
    if normalized_url:
        return await stage1.aforward(url=normalized_url)

    raise ValueError("url or text is required")


async def resolve_scan_leadership_recipient_email(
    *,
    source_value: str,
    request_ceo_email: str | None = None,
) -> str:
    """Resolve one required leadership recipient email before company creation."""
    normalized_request_ceo_email = normalize_email(request_ceo_email or "") or None
    if normalized_request_ceo_email:
        return normalized_request_ceo_email

    program = AuditorLeadershipRecipientProgram()
    result = await program.aforward(website_url=source_value)
    resolved_email = normalize_email(result.leadership_recipient_email or "") or None
    if resolved_email:
        return resolved_email

    logger.info(
        "Rejecting company scan because no leadership recipient was found: source=%s",
        source_value,
    )
    raise HTTPException(
        status_code=422,
        detail=MISSING_LEADERSHIP_RECIPIENT_DETAIL,
    )


async def scan_company_core(
    company_id: str,
    source_value: str,
    request_ceo_email: str | None = None,
    text: str | None = None,
) -> None:
    """Discover contacts and update company record."""
    try:
        stage1 = UrlToContactsProgram()
        discovery = await discover_company_contacts(
            stage1,
            url=source_value if not (text or "").strip() else None,
            text=text,
        )

        company = Company.get_by_id(company_id)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        stage1_ceo_email = (discovery.ceo_email or "").strip() or None
        resolved_ceo_email = request_ceo_email or stage1_ceo_email

        Company.update(
            company_id=company_id,
            company_name=discovery.company_name.strip() or source_value,
            company_info=discovery.company_info,
            website_markdown=discovery.website_markdown,
            ceo_email=resolved_ceo_email,
            industry=discovery.industry,
            company_size=discovery.company_size,
            language=discovery.language,
            update_ceo_email=True,
        )

        await create_contacts_for_company(company_id, discovery.contacts)

        refreshed_company = Company.get_by_id(company_id)
        if not refreshed_company:
            raise HTTPException(status_code=404, detail="Company not found")
        active_contacts = refreshed_company.get_contacts()
        try:
            generated_count, skipped_count = await seed_initial_outbound_messages_for_company(
                refreshed_company,
                active_contacts,
            )
            logger.info(
                "Initial outbound seeding completed for company %s: generated=%s skipped=%s",
                company_id,
                generated_count,
                skipped_count,
            )
        except Exception:
            logger.exception(
                "Initial outbound seeding failed for company %s. Discovery data remains persisted.",
                company_id,
            )
        Company.update_status(company_id, CompanyStatus.ACTIVE)
    except Exception:
        Company.update_status(company_id, CompanyStatus.FAILED)
        raise


async def run_company_scan_task(
    *,
    company_id: str,
    source_value: str,
    request_ceo_email: str | None = None,
    text: str | None = None,
) -> None:
    """Run one tracked company scan and fail the company cleanly on cancellation."""
    try:
        await scan_company_core(
            company_id=company_id,
            source_value=source_value,
            request_ceo_email=request_ceo_email,
            text=text,
        )
    except asyncio.CancelledError:
        Company.update_status(company_id, CompanyStatus.FAILED)
        raise


async def execute_company_scan_task(job: BatchCompanyScanJob) -> TaskStatus:
    """Execute one queued batch scan job while keeping its task row synchronized."""
    started_at = monotonic()
    logger.info(
        "Batch scan job started: task_id=%s company_id=%s source=%s timeout=%ss",
        job.task_id,
        job.company_id,
        job.source_value,
        SCAN_COMPANY_TIMEOUT_SECONDS,
    )
    Task.set_status(job.task_id, status=TaskStatus.RUNNING)
    try:
        await asyncio.wait_for(
            run_company_scan_task(
                company_id=job.company_id,
                source_value=job.source_value,
                request_ceo_email=job.request_ceo_email,
            ),
            timeout=SCAN_COMPANY_TIMEOUT_SECONDS,
        )
        Task.set_status(job.task_id, status=TaskStatus.COMPLETED)
        logger.info(
            "Batch scan job completed: task_id=%s company_id=%s source=%s elapsed=%.1fs",
            job.task_id,
            job.company_id,
            job.source_value,
            monotonic() - started_at,
        )
        return TaskStatus.COMPLETED
    except asyncio.TimeoutError:
        Company.update_status(job.company_id, CompanyStatus.FAILED)
        Task.set_status(
            job.task_id,
            status=TaskStatus.FAILED,
            error=f"Task timed out after {SCAN_COMPANY_TIMEOUT_SECONDS:.0f}s",
        )
        logger.error(
            "Batch scan job timed out: task_id=%s company_id=%s source=%s elapsed=%.1fs",
            job.task_id,
            job.company_id,
            job.source_value,
            monotonic() - started_at,
        )
        return TaskStatus.FAILED
    except Exception as exc:
        logger.exception(
            "Batch scan job failed: task_id=%s company_id=%s source=%s error=%s",
            job.task_id,
            job.company_id,
            job.source_value,
            exc,
        )
        Task.set_status(job.task_id, status=TaskStatus.FAILED, error=str(exc))
        return TaskStatus.FAILED


async def scan_companies_batch_core(scan_jobs: list[BatchCompanyScanJob]) -> None:
    """Execute all company scans with a fixed max concurrency while keeping the pipe full."""
    semaphore = asyncio.Semaphore(BATCH_SCAN_MAX_CONCURRENCY)

    async def run_job(job: BatchCompanyScanJob) -> tuple[BatchCompanyScanJob, TaskStatus]:
        async with semaphore:
            return job, await execute_company_scan_task(job)

    results = await asyncio.gather(*(run_job(job) for job in scan_jobs))
    failed_jobs = [job for job, status in results if status != TaskStatus.COMPLETED]
    logger.info(
        "Batch scan finished: total=%s completed=%s failed=%s concurrency=%s",
        len(results),
        len(results) - len(failed_jobs),
        len(failed_jobs),
        BATCH_SCAN_MAX_CONCURRENCY,
    )
    if failed_jobs:
        preview = ", ".join(job.source_value for job in failed_jobs[:5])
        raise RuntimeError(
            f"Batch scan completed with {len(failed_jobs)}/{len(results)} failed company scans. "
            f"Failed URL preview: {preview}"
        )


@companies_router.post("/companies/scan", response_model=ScanCompanyTaskResponse)
async def scan_company(request: ScanCompanyRequest, background_tasks: BackgroundTasks):
    """Start one company scan and queue discovery as background task."""
    url = normalize_company_scan_source_value(request.url)
    request_ceo_email = (request.ceo_email or "").strip() or None
    report_window_minutes = resolve_requested_report_window_minutes(
        report_window_minutes=request.report_window_minutes,
        report_window_hours=request.report_window_hours,
    )
    if not url:
        raise HTTPException(status_code=422, detail="url is required")

    duplicate_company = get_duplicate_company_for_scan(url)
    if duplicate_company is not None:
        logger.info(
            "Skipping duplicate company scan: source=%s normalized=%s existing_company_id=%s",
            request.url,
            duplicate_company.normalized_source_url,
            duplicate_company.id,
        )
        return ScanCompanyTaskResponse(
            task_id=None,
            company_id=duplicate_company.id,
            status="duplicate",
            duplicate_ignored=True,
        )

    resolved_ceo_email = await resolve_scan_leadership_recipient_email(
        source_value=url,
        request_ceo_email=request_ceo_email,
    )

    company = Company.create(
        source_url=url,
        company_name=url,
        objective=request.objective,
        tags=request.tags,
        ceo_email=resolved_ceo_email,
        conversation_automation_enabled=request.conversation_automation_enabled,
        ceo_delivery_enabled=request.ceo_delivery_enabled,
        report_window_minutes=report_window_minutes,
        status=CompanyStatus.INITIALIZING,
    )

    task = Task.run_async(
        background_tasks,
        run_company_scan_task,
        resource_id=company.id,
        timeout_seconds=SCAN_COMPANY_TIMEOUT_SECONDS,
        company_id=company.id,
        source_value=url,
        request_ceo_email=resolved_ceo_email,
    )

    return ScanCompanyTaskResponse(
        task_id=task.id,
        company_id=company.id,
        status=task.status.value,
    )


@companies_router.post(
    "/companies/discover-auditor-candidates",
    response_model=DiscoverAuditorCompaniesResponse,
)
async def discover_auditor_companies(
    request: DiscoverAuditorCompaniesRequest,
) -> DiscoverAuditorCompaniesResponse:
    """Discover strong auditor-fit companies without persisting anything."""
    program = AuditorCompanyDiscoveryProgram()
    result = await program.aforward(
        count=request.count,
        exclude_company_urls=request.exclude_company_urls,
        exclude_company_names=request.exclude_company_names,
    )
    return DiscoverAuditorCompaniesResponse(companies=result.companies)


class BatchScanRequest(BaseModel):
    """Shared batch scan settings accepted from form-data or JSON bodies."""

    freeform_text: str = Field(default="", validation_alias=AliasChoices("freeform_text", "text"))
    objective: str = ""
    tags: list[str] = Field(default_factory=list)
    conversation_automation_enabled: bool = False
    ceo_delivery_enabled: bool = False
    report_window_hours: int | None = Field(default=None, ge=1)
    report_window_minutes: int | None = Field(default=None, ge=1)


async def resolve_batch_scan_request(
    request: Request,
    *,
    freeform_text: str,
    text: str,
    objective: str,
    tags: list[str] | None,
    conversation_automation_enabled: bool,
    ceo_delivery_enabled: bool,
    report_window_hours: int | None,
    report_window_minutes: int | None,
) -> BatchScanRequest:
    """Read batch scan settings/files from either multipart form-data or a JSON body."""
    if "application/json" not in request.headers.get("content-type", "").lower():
        return BatchScanRequest(
            freeform_text=freeform_text or text,
            objective=objective,
            tags=tags or [],
            conversation_automation_enabled=conversation_automation_enabled,
            ceo_delivery_enabled=ceo_delivery_enabled,
            report_window_hours=report_window_hours,
            report_window_minutes=report_window_minutes,
        )

    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("Batch scan rejected: invalid JSON body")
        raise HTTPException(status_code=422, detail="Invalid JSON body for batch scan.") from exc

    if not isinstance(payload, dict):
        logger.warning("Batch scan rejected: JSON body must be an object")
        raise HTTPException(status_code=422, detail="Batch scan JSON body must be an object.")

    try:
        return BatchScanRequest.model_validate(payload)
    except ValidationError as exc:
        logger.warning("Batch scan rejected: invalid JSON payload %s", exc.errors(include_url=False))
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc


@companies_router.post("/companies/scan-batch", response_model=BatchScanTaskResponse)
async def scan_company_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    freeform_text: str = Form(default=""),
    text: str = Form(default=""),
    files: list[UploadFile] | None = File(default=None),
    objective: str = Form(default=""),
    tags: list[str] | None = Form(default=None),
    conversation_automation_enabled: bool = Form(default=False),
    ceo_delivery_enabled: bool = Form(default=False),
    report_window_hours: int | None = Form(default=None),
    report_window_minutes: int | None = Form(default=None),
):
    """Extract company URLs from text/files and queue the normal scan pipeline for all of them."""
    batch_request = await resolve_batch_scan_request(
        request,
        freeform_text=freeform_text,
        text=text,
        objective=objective,
        tags=tags,
        conversation_automation_enabled=conversation_automation_enabled,
        ceo_delivery_enabled=ceo_delivery_enabled,
        report_window_hours=report_window_hours,
        report_window_minutes=report_window_minutes,
    )
    batch_report_window_minutes = resolve_requested_report_window_minutes(
        report_window_minutes=batch_request.report_window_minutes,
        report_window_hours=batch_request.report_window_hours,
    )

    try:
        bundled_input = await build_batch_scan_bundle(
            freeform_text=batch_request.freeform_text,
            files=files or [],
        )
    except Exception as exc:
        logger.warning("Batch scan rejected: file text extraction failed (%s)", exc)
        raise HTTPException(
            status_code=422,
            detail=f"Failed extracting text from uploaded files: {exc}",
        ) from exc

    if not bundled_input.strip():
        logger.warning(
            "Batch scan rejected: empty bundled input (content_type=%s, text_len=%s, files=%s)",
            request.headers.get("content-type", ""),
            len(batch_request.freeform_text),
            len(files or []),
        )
        raise HTTPException(
            status_code=422,
            detail="Provide freeform text and/or at least one attachment.",
        )

    try:
        extractor = BatchInputToCompanyUrlsProgram()
        extraction = await asyncio.wait_for(
            extractor.aforward(bundled_input=bundled_input),
            timeout=BATCH_SCAN_URL_EXTRACTION_TIMEOUT_SECONDS,
        )
        urls = extraction.urls
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail="Timed out extracting company URLs from the batch input.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed extracting company URLs: {exc}",
        ) from exc

    if not urls:
        logger.warning("Batch scan rejected: no company URLs found in bundled input")
        raise HTTPException(
            status_code=422,
            detail="No company URLs were found in the provided text/files.",
        )

    batch_jobs: list[BatchCompanyScanJob] = []
    duplicate_company_ids: list[str] = []
    duplicate_count = 0
    rejected_count = 0
    rejected_urls: list[str] = []
    for url in urls:
        normalized_url = normalize_company_scan_source_value(url)
        duplicate_company = get_duplicate_company_for_scan(normalized_url)
        if duplicate_company is not None:
            duplicate_count += 1
            if duplicate_company.id not in duplicate_company_ids:
                duplicate_company_ids.append(duplicate_company.id)
            logger.info(
                "Skipping duplicate company scan in batch: source=%s normalized=%s existing_company_id=%s",
                url,
                duplicate_company.normalized_source_url,
                duplicate_company.id,
            )
            continue

        try:
            resolved_ceo_email = await resolve_scan_leadership_recipient_email(
                source_value=normalized_url,
            )
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            rejected_count += 1
            rejected_urls.append(normalized_url)
            continue

        company = Company.create(
            source_url=normalized_url,
            company_name=normalized_url,
            objective=batch_request.objective.strip() or None,
            tags=batch_request.tags,
            ceo_email=resolved_ceo_email,
            conversation_automation_enabled=batch_request.conversation_automation_enabled,
            ceo_delivery_enabled=batch_request.ceo_delivery_enabled,
            report_window_minutes=batch_report_window_minutes,
            status=CompanyStatus.INITIALIZING,
        )
        task = Task.create(
            task_type=run_company_scan_task.__name__,
            resource_id=company.id,
        )
        batch_jobs.append(
            BatchCompanyScanJob(
                task_id=task.id,
                company_id=company.id,
                source_value=normalized_url,
                request_ceo_email=resolved_ceo_email,
            )
        )

    if not batch_jobs:
        return BatchScanTaskResponse(
            task_id=None,
            company_ids=[],
            company_count=0,
            status="duplicate" if duplicate_count > 0 and rejected_count == 0 else "rejected",
            duplicate_count=duplicate_count,
            duplicate_company_ids=duplicate_company_ids,
            rejected_count=rejected_count,
            rejected_urls=rejected_urls,
        )

    batch_task = Task.run_async(
        background_tasks,
        scan_companies_batch_core,
        scan_jobs=batch_jobs,
    )
    return BatchScanTaskResponse(
        task_id=batch_task.id,
        company_ids=[job.company_id for job in batch_jobs],
        company_count=len(batch_jobs),
        status=batch_task.status.value,
        duplicate_count=duplicate_count,
        duplicate_company_ids=duplicate_company_ids,
        rejected_count=rejected_count,
        rejected_urls=rejected_urls,
    )


@companies_router.post("/dev/companies/scan", response_model=ScanCompanyTaskResponse)
async def scan_company_from_text(request: DevScanCompanyRequest, background_tasks: BackgroundTasks):
    """Start one dev-only company scan from raw text and queue normal downstream processing."""
    text = request.text.strip()
    request_ceo_email = (request.ceo_email or "").strip() or None
    report_window_minutes = resolve_requested_report_window_minutes(
        report_window_minutes=request.report_window_minutes,
        report_window_hours=request.report_window_hours,
    )
    if not text:
        raise HTTPException(status_code=422, detail="text is required")

    source_label = build_dev_text_source_label(text, request.source_label)
    normalized_source_url = normalize_company_source_url(source_label)
    if normalized_source_url:
        resolved_ceo_email = await resolve_scan_leadership_recipient_email(
            source_value=normalized_source_url,
            request_ceo_email=request_ceo_email,
        )
    else:
        resolved_ceo_email = normalize_email(request_ceo_email or "") or None
        if not resolved_ceo_email:
            raise HTTPException(
                status_code=422,
                detail="Dev text scans require ceo_email unless source_label is a company website URL.",
            )

    company = Company.create(
        source_url=source_label,
        company_name=source_label,
        objective=request.objective,
        tags=request.tags,
        ceo_email=resolved_ceo_email,
        conversation_automation_enabled=request.conversation_automation_enabled,
        ceo_delivery_enabled=request.ceo_delivery_enabled,
        report_window_minutes=report_window_minutes,
        status=CompanyStatus.INITIALIZING,
    )

    task = Task.run_async(
        background_tasks,
        run_company_scan_task,
        resource_id=company.id,
        timeout_seconds=SCAN_COMPANY_TIMEOUT_SECONDS,
        company_id=company.id,
        source_value=source_label,
        text=text,
        request_ceo_email=resolved_ceo_email,
    )

    return ScanCompanyTaskResponse(
        task_id=task.id,
        company_id=company.id,
        status=task.status.value,
    )


@companies_router.post("/companies/{company_id}/rescan", response_model=ScanCompanyTaskResponse)
async def rescan_company(company_id: str, background_tasks: BackgroundTasks):
    """Queue one fresh scan for the same company row when it has no active contacts."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    pending_task_types = Task.list_pending_task_types_for_resource(resource_id=company_id)
    if pending_task_types:
        raise HTTPException(status_code=409, detail="Company already has a pending task")

    total_contacts = company.count_contacts()
    if total_contacts > 0:
        raise HTTPException(
            status_code=409,
            detail="Re-scan is only available for companies with 0 active contacts",
        )

    normalized_source_url = normalize_company_source_url(company.source_url)
    if not normalized_source_url:
        raise HTTPException(
            status_code=409,
            detail="Re-scan is only available for companies created from a URL source",
        )

    resolved_ceo_email = await resolve_scan_leadership_recipient_email(
        source_value=normalized_source_url,
        request_ceo_email=(company.ceo_email or "").strip() or None,
    )
    Company.update_status(company_id, CompanyStatus.INITIALIZING)
    task = Task.run_async(
        background_tasks,
        run_company_scan_task,
        resource_id=company.id,
        timeout_seconds=SCAN_COMPANY_TIMEOUT_SECONDS,
        company_id=company.id,
        source_value=normalized_source_url,
        request_ceo_email=resolved_ceo_email,
    )

    return ScanCompanyTaskResponse(
        task_id=task.id,
        company_id=company.id,
        status=task.status.value,
    )


class CreateManualContactRequest(BaseModel):
    """Manual contact creation input."""

    type: str = Field(min_length=1)
    value: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    notes: str | None = None
    additional_info: str | None = None


class CreateManualContactResponse(BaseModel):
    """Manual contact creation response."""

    company_id: str
    created: bool
    contact: ContactSummary


@companies_router.post("/companies/{company_id}/contacts", response_model=CreateManualContactResponse)
async def create_manual_contact(
    company_id: str,
    request: CreateManualContactRequest,
):
    """Create one manual contact for one existing company."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    contact_type = canonical_contact_type(request.type)
    if contact_type not in {ContactType.EMAIL.value, ContactType.WHATSAPP.value}:
        raise HTTPException(status_code=422, detail="type must be one of: email, whatsapp")

    value = request.value.strip()
    if not value:
        raise HTTPException(status_code=422, detail="value is required")
    objective = request.objective.strip()
    if not objective:
        raise HTTPException(status_code=422, detail="objective is required")

    normalized_value = normalize_contact_value(contact_type, value)
    if not normalized_value:
        raise HTTPException(status_code=422, detail="value is invalid for the selected type")

    existing = next(
        (
            item
            for item in Contact.list_by_normalized_value(normalized_value, status=None)
            if item.company_id == company_id and item.canonical_type == contact_type
        ),
        None,
    )
    if existing:
        if existing.status == ContactStatus.ARCHIVED:
            raise HTTPException(
                status_code=409,
                detail="Contact already exists but is archived. Unarchive it to reuse this contact.",
            )
        contact = existing
        created = False
    else:
        contact = Contact.create(
            company_id=company_id,
            type=contact_type,
            value=value,
            objective=objective,
            notes=request.notes,
            additional_info=request.additional_info,
        )
        created = True

    try:
        refreshed_company = Company.get_by_id(company_id)
        if not refreshed_company:
            raise HTTPException(status_code=404, detail="Company not found")
        active_contacts = refreshed_company.get_contacts()
        generated_count, skipped_count = await seed_initial_outbound_messages_for_company(
            refreshed_company,
            active_contacts,
        )
        logger.info(
            "Manual contact initial outbound seeding for company %s contact %s: generated=%s skipped=%s",
            company_id,
            contact.id,
            generated_count,
            skipped_count,
        )
    except Exception:
        logger.exception(
            "Manual contact initial outbound seeding failed for company %s contact %s",
            company_id,
            contact.id,
        )

    return CreateManualContactResponse(
        company_id=company_id,
        created=created,
        contact=build_contact_summary(contact, company.objective),
    )


@companies_router.get("/companies", response_model=list[CompanySummary])
async def list_companies(limit: int = Query(default=100, ge=1, le=1000)):
    """List companies."""
    return [build_company_summary(item) for item in Company.list_recent(limit=limit)]


@companies_router.get("/companies/{company_id}", response_model=CompanyDetail)
async def get_company(company_id: str, archived: bool = False):
    """Get one company detail with active or archived contacts."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    contacts = company.get_contacts(include_archived=archived)
    visible_total = company.count_contacts(include_archived=archived)
    base = build_company_summary(company)
    base_data = base.model_dump()
    base_data["total_contacts"] = visible_total
    return CompanyDetail(
        **base_data,
        company_info=company.company_info,
        website_markdown=company.website_markdown,
        ceo_email=company.ceo_email,
        contacts=[build_contact_summary(item, company.objective) for item in contacts],
    )


class UpdateCompanyRequest(BaseModel):
    """Shared company settings update command."""

    company_name: str | None = None
    company_info: str | None = None
    website_markdown: str | None = None
    ceo_email: str | None = None
    language: CompanyLanguage | None = None
    objective: str | None = None
    conversation_automation_enabled: bool | None = None
    ceo_delivery_enabled: bool | None = None
    report_window_hours: int | None = Field(default=None, ge=1)
    report_window_minutes: int | None = Field(default=None, ge=1)


class UpdateCompanyResponse(BaseModel):
    """Updated company settings payload."""

    company_id: str
    company_name: str
    company_info: str
    website_markdown: str
    ceo_email: str | None
    language: CompanyLanguage | None
    objective: str | None
    conversation_automation_enabled: bool
    ceo_delivery_enabled: bool
    report_window_hours: int | None = None
    report_window_minutes: int
    scheduled_send_at: str
    updated_at: str


@companies_router.put("/companies/{company_id}", response_model=UpdateCompanyResponse)
async def update_company(company_id: str, request: UpdateCompanyRequest):
    """Update one company settings payload."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    has_ceo_email_update = "ceo_email" in request.model_fields_set

    Company.update(
        company_id=company_id,
        company_name=request.company_name,
        company_info=request.company_info,
        website_markdown=request.website_markdown,
        ceo_email=request.ceo_email,
        language=request.language,
        objective=request.objective,
        conversation_automation_enabled=request.conversation_automation_enabled,
        ceo_delivery_enabled=request.ceo_delivery_enabled,
        report_window_hours=request.report_window_hours,
        report_window_minutes=request.report_window_minutes,
        update_ceo_email=has_ceo_email_update,
    )
    updated = Company.get_by_id(company_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Company not found")
    report_window_minutes = get_company_report_window_minutes(updated)

    return UpdateCompanyResponse(
        company_id=updated.id,
        company_name=updated.company_name,
        company_info=updated.company_info,
        website_markdown=updated.website_markdown,
        ceo_email=updated.ceo_email,
        language=updated.language,
        objective=updated.objective,
        conversation_automation_enabled=updated.conversation_automation_enabled,
        ceo_delivery_enabled=updated.ceo_delivery_enabled,
        report_window_hours=get_legacy_report_window_hours(report_window_minutes),
        report_window_minutes=report_window_minutes,
        scheduled_send_at=format_timestamp_seconds(get_company_report_schedule_at(updated)),
        updated_at=format_timestamp_seconds(updated.updated_at),
    )


class UpdateCompanyReportScheduleRequest(BaseModel):
    """Dedicated company report-schedule update command."""

    report_window_hours: int | None = Field(default=None, ge=1)
    report_window_minutes: int | None = Field(default=None, ge=1)
    scheduled_send_at: datetime | None = None

    @model_validator(mode="after")
    def validate_schedule_update_fields(self) -> "UpdateCompanyReportScheduleRequest":
        """Require at least one schedule field in the update payload."""
        if (
            self.report_window_hours is None
            and self.report_window_minutes is None
            and self.scheduled_send_at is None
        ):
            raise ValueError("report_window_hours, report_window_minutes, or scheduled_send_at is required")
        return self


class UpdateCompanyReportScheduleResponse(BaseModel):
    """Updated report-schedule payload for one company."""

    company_id: str
    report_window_hours: int | None = None
    report_window_minutes: int
    scheduled_send_at: str
    updated_at: str


def resolve_company_report_schedule_update(
    company: Company,
    request: UpdateCompanyReportScheduleRequest,
) -> tuple[int, datetime]:
    """Resolve one validated report-schedule update from request fields."""
    if request.scheduled_send_at is None:
        resolved_minutes = resolve_requested_report_window_minutes(
            report_window_minutes=request.report_window_minutes,
            report_window_hours=request.report_window_hours,
        )
        return (
            resolved_minutes,
            compute_report_schedule_at(
                created_at=company.created_at,
                report_window_minutes=resolved_minutes,
            ),
        )

    scheduled_minutes = compute_report_window_minutes_for_scheduled_send(
        created_at=company.created_at,
        scheduled_send_at=request.scheduled_send_at,
    )
    if request.report_window_minutes is not None:
        requested_minutes = normalize_report_window_minutes(request.report_window_minutes)
        if requested_minutes != scheduled_minutes:
            raise HTTPException(
                status_code=422,
                detail="report_window_minutes must match scheduled_send_at for this company",
            )
    elif request.report_window_hours is not None:
        requested_minutes = resolve_requested_report_window_minutes(
            report_window_hours=request.report_window_hours,
        )
        if requested_minutes != scheduled_minutes:
            raise HTTPException(
                status_code=422,
                detail="report_window_hours must match scheduled_send_at for this company",
            )

    return scheduled_minutes, compute_report_schedule_at(
        created_at=company.created_at,
        scheduled_send_at=request.scheduled_send_at,
    )


def build_company_report_schedule_response(company: Company) -> UpdateCompanyReportScheduleResponse:
    """Build one dedicated report-schedule response payload."""
    report_window_minutes = get_company_report_window_minutes(company)
    scheduled_send_at = get_company_report_schedule_at(company)
    return UpdateCompanyReportScheduleResponse(
        company_id=company.id,
        report_window_hours=get_legacy_report_window_hours(report_window_minutes),
        report_window_minutes=report_window_minutes,
        scheduled_send_at=format_timestamp_seconds(scheduled_send_at),
        updated_at=format_timestamp_seconds(company.updated_at),
    )


@companies_router.put(
    "/companies/{company_id}/report-schedule",
    response_model=UpdateCompanyReportScheduleResponse,
)
async def update_company_report_schedule(
    company_id: str,
    request: UpdateCompanyReportScheduleRequest,
) -> UpdateCompanyReportScheduleResponse:
    """Update one company's report window / scheduled-send settings."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    resolved_minutes, resolved_scheduled_send_at = resolve_company_report_schedule_update(company, request)
    Company.update(
        company_id=company_id,
        report_window_minutes=resolved_minutes,
        report_scheduled_send_at=resolved_scheduled_send_at,
    )
    updated = Company.get_by_id(company_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Company not found")
    return build_company_report_schedule_response(updated)


class SetContactArchiveRequest(BaseModel):
    """Archive/unarchive command for one contact."""

    archived: bool = True


class SetContactArchiveResponse(BaseModel):
    """Updated archive status for one contact."""

    contact_id: str
    status: str
    archived: bool


@companies_router.put(
    "/companies/{company_id}/contacts/{contact_id}/archive",
    response_model=SetContactArchiveResponse,
)
async def set_contact_archive_status(
    company_id: str,
    contact_id: str,
    request: SetContactArchiveRequest,
):
    """Archive or unarchive one contact in one company."""
    contact = Contact.get_by_id(contact_id)
    if not contact or contact.company_id != company_id:
        raise HTTPException(status_code=404, detail="Contact not found in this company")

    target_status = ContactStatus.ARCHIVED if request.archived else ContactStatus.ACTIVE
    updated = Contact.update_status(contact_id, target_status)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")

    Company.update(company_id)
    return SetContactArchiveResponse(
        contact_id=updated.id,
        status=updated.status.value,
        archived=updated.is_archived,
    )


@companies_router.delete("/companies/{company_id}")
async def delete_company(company_id: str):
    """Delete one company and all related contacts/messages."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    Company.delete(company_id)
    return {"message": "Company deleted"}


class PrepareReportRequest(BaseModel):
    """Report preparation request (slow stage)."""

    language: CompanyLanguage = CompanyLanguage.EN


class PrepareReportTaskResponse(BaseModel):
    """Task creation response for report preparation."""

    task_id: str
    company_id: str
    status: str


class AuditDeliveryPollStateItem(BaseModel):
    """Poll payload row for stateless bot audit-delivery decisions."""

    company_id: str
    created_at: str
    report_window_hours: int | None = None
    report_window_minutes: int = DEFAULT_REPORT_WINDOW_MINUTES
    scheduled_send_at: str
    conversation_automation_enabled: bool
    ceo_delivery_enabled: bool
    has_report_pdf_model: bool
    ceo_delivery_sent_at: str | None = None
    ceo_delivery_blocked_reason: str | None = None
    pending_full_audit_task: bool
    eligible_for_full_audit: bool


def build_audit_delivery_poll_item(company: Company, *, now: datetime) -> AuditDeliveryPollStateItem:
    """Build one audit-delivery poll row from company state."""
    has_report_pdf_model = bool((company.report_pdf_model_json or "").strip())
    pending_full_audit_task = Task.has_pending_for_resource(
        resource_id=company.id,
        task_type=FULL_AUDIT_TASK_TYPE,
    )
    eligible = should_generate_full_audit(company, now=now)
    scheduled_send_at = get_company_report_schedule_at(company)
    report_window_minutes = get_company_report_window_minutes(company)
    return AuditDeliveryPollStateItem(
        company_id=company.id,
        created_at=format_timestamp_seconds(company.created_at),
        report_window_hours=get_legacy_report_window_hours(report_window_minutes),
        report_window_minutes=report_window_minutes,
        scheduled_send_at=format_timestamp_seconds(scheduled_send_at),
        conversation_automation_enabled=company.conversation_automation_enabled,
        ceo_delivery_enabled=company.ceo_delivery_enabled,
        has_report_pdf_model=has_report_pdf_model,
        ceo_delivery_sent_at=(
            format_timestamp_seconds(company.ceo_delivery_sent_at)
            if company.ceo_delivery_sent_at
            else None
        ),
        ceo_delivery_blocked_reason=company.ceo_delivery_blocked_reason,
        pending_full_audit_task=pending_full_audit_task,
        eligible_for_full_audit=eligible,
    )


@companies_router.get("/companies/audit-delivery/poll-state", response_model=list[AuditDeliveryPollStateItem])
async def get_audit_delivery_poll_state() -> list[AuditDeliveryPollStateItem]:
    """Return backend state used by bot audit-delivery polling logic."""
    now = datetime.now(timezone.utc)
    companies = Company.list_recent(limit=1000)
    return [build_audit_delivery_poll_item(item, now=now) for item in companies]


@companies_router.post("/companies/{company_id}/audit-delivery/generate-full-audit", response_model=PrepareReportTaskResponse)
async def generate_full_audit(
    company_id: str,
    background_tasks: BackgroundTasks,
):
    """Queue one full-audit task (Stage 3 + Stage 4) for one company."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if (company.report_pdf_model_json or "").strip():
        raise HTTPException(status_code=409, detail="Company already has report PDF model")
    if Task.has_pending_for_resource(resource_id=company_id, task_type=FULL_AUDIT_TASK_TYPE):
        raise HTTPException(status_code=409, detail="Full audit generation is already in progress")

    task = Task.run_async(
        background_tasks,
        generate_company_full_audit_core,
        resource_id=company_id,
        timeout_seconds=FULL_AUDIT_TIMEOUT_SECONDS,
        company_id=company_id,
    )
    return PrepareReportTaskResponse(
        task_id=task.id,
        company_id=company_id,
        status=task.status.value,
    )


async def prepare_company_audit_report_core(
    company_id: str,
    *,
    language: str,
):
    """Prepare structured report artifact and reset stale PDF model state."""
    company = Company.get_by_id(company_id)
    if not company:
        raise RuntimeError("Company not found")

    stage3 = CompanyReportProgram(lm=SMART_MODEL)
    report = await stage3.aforward(company, language=language)
    Company.update_report_snapshot(company_id, report.model_dump_json(by_alias=True))
    Company.update_report_pdf_model(company_id, None)
    Company.update_status(company_id, CompanyStatus.COMPLETED)


async def build_company_audit_pdf_model_core(company_id: str):
    """Build PDF content model from persisted report snapshot and mark company as audited."""
    company = Company.get_by_id(company_id)
    if not company:
        raise RuntimeError("Company not found")

    report = Company.get_report_snapshot(company_id)
    if not report:
        raise RuntimeError("Report snapshot not found. Run prepare-report first.")

    stage4 = ReportPdfModelProgram(lm=SMART_MODEL)
    pdf_model = await stage4.aforward(report=report)
    Company.update_report_pdf_model(company_id, pdf_model.model_dump_json(by_alias=True))
    Company.update_status(company_id, CompanyStatus.AUDITED)


async def generate_company_full_audit_core(company_id: str) -> None:
    """Generate Stage 3 + Stage 4 artifacts for one company in one task."""
    company = Company.get_by_id(company_id)
    if not company:
        raise RuntimeError("Company not found")
    if (company.report_pdf_model_json or "").strip():
        return

    language = choose_report_language(company)
    stage3 = CompanyReportProgram(lm=SMART_MODEL)
    report = await stage3.aforward(company, language=language)
    Company.update_report_snapshot(company_id, report.model_dump_json(by_alias=True))

    stage4 = ReportPdfModelProgram(lm=SMART_MODEL)
    pdf_model = await stage4.aforward(report=report)
    Company.update_report_pdf_model(company_id, pdf_model.model_dump_json(by_alias=True))
    Company.update_status(company_id, CompanyStatus.AUDITED)


@companies_router.post("/companies/{company_id}/prepare-report", response_model=PrepareReportTaskResponse)
async def prepare_report(
    company_id: str,
    request: PrepareReportRequest,
    background_tasks: BackgroundTasks,
):
    """Queue report preparation and return task metadata for polling."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    task = Task.run_async(
        background_tasks,
        prepare_company_audit_report_core,
        resource_id=company_id,
        timeout_seconds=REPORT_TASK_TIMEOUT_SECONDS,
        company_id=company_id,
        language=request.language.value,
    )

    return PrepareReportTaskResponse(
        task_id=task.id,
        company_id=company_id,
        status=task.status.value,
    )


@companies_router.post("/companies/{company_id}/build-report-html", response_model=PrepareReportTaskResponse)
async def build_report_html(
    company_id: str,
    background_tasks: BackgroundTasks,
):
    """Queue PDF-model rendering from persisted report snapshot and return task metadata."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    task = Task.run_async(
        background_tasks,
        build_company_audit_pdf_model_core,
        resource_id=company_id,
        timeout_seconds=REPORT_HTML_TIMEOUT_SECONDS,
        company_id=company_id,
    )

    return PrepareReportTaskResponse(
        task_id=task.id,
        company_id=company_id,
        status=task.status.value,
    )


@companies_router.post("/companies/{company_id}/build-report-pdf-model", response_model=PrepareReportTaskResponse)
async def build_report_pdf_model(
    company_id: str,
    background_tasks: BackgroundTasks,
):
    """Queue PDF-model rendering from persisted report snapshot and return task metadata."""
    return await build_report_html(
        company_id=company_id,
        background_tasks=background_tasks,
    )


class CompanyReportArtifactResponse(BaseModel):
    """Latest persisted structured report artifact."""

    generated_at: str
    report: CompanyReport


class CompanyHtmlArtifactResponse(BaseModel):
    """Latest persisted rendered HTML artifact."""

    generated_at: str
    html: str


class CompanyPdfModelArtifactResponse(BaseModel):
    """Latest persisted render-ready PDF content model artifact."""

    generated_at: str
    pdf_model: ReportDocumentModel


class CompanyArtifactResponse(BaseModel):
    """Latest persisted company artifact."""

    generated_at: str
    pdf_model: ReportDocumentModel
    report: CompanyReport


@companies_router.get(
    "/companies/{company_id}/artifact-report",
    response_model=CompanyReportArtifactResponse,
    responses={204: {"description": "No report artifact generated yet"}},
)
async def get_company_report_artifact(company_id: str) -> CompanyReportArtifactResponse | Response:
    """Return latest persisted structured report artifact. Returns 204 if missing."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    report = Company.get_report_snapshot(company_id)
    if not report:
        return Response(status_code=204)

    return CompanyReportArtifactResponse(
        generated_at=format_timestamp_seconds(company.updated_at),
        report=report,
    )


@companies_router.get(
    "/companies/{company_id}/artifact-pdf-model",
    response_model=CompanyPdfModelArtifactResponse,
    responses={204: {"description": "No PDF model artifact generated yet"}},
)
async def get_company_pdf_model_artifact(company_id: str) -> CompanyPdfModelArtifactResponse | Response:
    """Return latest persisted PDF model artifact. Returns 204 if missing."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    pdf_model = Company.get_report_pdf_model(company_id)
    if not pdf_model:
        return Response(status_code=204)

    return CompanyPdfModelArtifactResponse(
        generated_at=format_timestamp_seconds(company.updated_at),
        pdf_model=pdf_model,
    )


@companies_router.get(
    "/companies/{company_id}/artifact",
    response_model=CompanyArtifactResponse,
    responses={204: {"description": "No artifact generated yet"}},
)
async def get_company_artifact(company_id: str) -> CompanyArtifactResponse | Response:
    """Return latest persisted report + PDF model artifacts for one company. Returns 204 if not built yet."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    report = Company.get_report_snapshot(company_id)
    pdf_model = Company.get_report_pdf_model(company_id)
    if not report or not pdf_model:
        return Response(status_code=204)

    return CompanyArtifactResponse(
        generated_at=format_timestamp_seconds(company.updated_at),
        pdf_model=pdf_model,
        report=report,
    )


class AuditDeliveryCeoEmailResponse(BaseModel):
    """CEO recipient payload for audit delivery."""

    company_id: str
    ceo_email: str | None = None


class AuditDeliveryEmailContentResponse(BaseModel):
    """Deterministic subject/body payload for audit delivery email."""

    company_id: str
    subject: str
    body: str


class MarkAuditDeliveryDeliveredRequest(BaseModel):
    """Delivery confirmation input after provider send."""

    thread_id: str = Field(min_length=1)
    external_id: str = Field(min_length=1)
    rfc_message_id: str | None = None
    delivered_at: datetime | None = None


class MarkAuditDeliveryDeliveredResponse(BaseModel):
    """Persisted delivery metadata response."""

    company_id: str
    ceo_delivery_sent_at: str | None = None
    ceo_delivery_thread_id: str | None = None
    ceo_delivery_external_id: str | None = None
    ceo_delivery_rfc_message_id: str | None = None


class MarkAuditDeliveryBlockedRequest(BaseModel):
    """Blocking reason command for audit delivery."""

    reason: str = Field(min_length=1)


class MarkAuditDeliveryBlockedResponse(BaseModel):
    """Blocked state response for audit delivery."""

    company_id: str
    ceo_delivery_blocked_reason: str | None = None
    ceo_delivery_blocked_at: str | None = None


@companies_router.get("/companies/{company_id}/audit-delivery/ceo-email", response_model=AuditDeliveryCeoEmailResponse)
async def get_audit_delivery_ceo_email(company_id: str) -> AuditDeliveryCeoEmailResponse:
    """Return CEO recipient email for one company."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return AuditDeliveryCeoEmailResponse(
        company_id=company.id,
        ceo_email=(company.ceo_email or "").strip() or None,
    )


@companies_router.get(
    "/companies/{company_id}/audit-delivery/email-content",
    response_model=AuditDeliveryEmailContentResponse,
)
async def get_audit_delivery_email_content(company_id: str) -> AuditDeliveryEmailContentResponse:
    """Return deterministic subject/body for one company audit delivery email."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    subject, body = build_deterministic_audit_delivery_email_content(
        company_id=company.id,
        company_language=company.language,
        company_name=company.company_name,
        source_url=company.source_url,
        contact_lines=build_audit_contact_lines(company),
        objective_lines=build_audit_objective_lines(company),
        report_window_minutes=get_company_report_window_minutes(company),
    )
    return AuditDeliveryEmailContentResponse(
        company_id=company.id,
        subject=subject,
        body=body,
    )


@companies_router.get("/companies/{company_id}/audit-delivery/pdf")
async def get_audit_delivery_pdf(company_id: str) -> Response:
    """Return render-on-demand PDF binary for one company audit."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    pdf_model = Company.get_report_pdf_model(company_id)
    if not pdf_model:
        raise HTTPException(status_code=409, detail="PDF model not available for this company")

    pdf_bytes = build_vector_pdf(pdf_model, strict_layout_fit=False)
    filename = build_audit_delivery_pdf_filename(
        company_name=company.company_name,
        source_url=company.source_url,
        fallback_stem=company.id,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quote(filename)}'
            )
        },
    )


@companies_router.post(
    "/companies/{company_id}/audit-delivery/mark-delivered",
    response_model=MarkAuditDeliveryDeliveredResponse,
)
async def mark_audit_delivery_delivered(
    company_id: str,
    request: MarkAuditDeliveryDeliveredRequest,
) -> MarkAuditDeliveryDeliveredResponse:
    """Persist successful CEO audit delivery metadata."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    Company.mark_ceo_delivery_delivered(
        company_id,
        thread_id=request.thread_id,
        external_id=request.external_id,
        rfc_message_id=request.rfc_message_id,
        delivered_at=to_utc_datetime(request.delivered_at),
    )
    updated = Company.get_by_id(company_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Company not found")

    return MarkAuditDeliveryDeliveredResponse(
        company_id=updated.id,
        ceo_delivery_sent_at=(
            format_timestamp_seconds(updated.ceo_delivery_sent_at)
            if updated.ceo_delivery_sent_at
            else None
        ),
        ceo_delivery_thread_id=updated.ceo_delivery_thread_id,
        ceo_delivery_external_id=updated.ceo_delivery_external_id,
        ceo_delivery_rfc_message_id=updated.ceo_delivery_rfc_message_id,
    )


@companies_router.post(
    "/companies/{company_id}/audit-delivery/mark-blocked",
    response_model=MarkAuditDeliveryBlockedResponse,
)
async def mark_audit_delivery_blocked(
    company_id: str,
    request: MarkAuditDeliveryBlockedRequest,
) -> MarkAuditDeliveryBlockedResponse:
    """Mark CEO audit delivery as blocked for one company."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    if company.ceo_delivery_sent_at is None:
        Company.mark_ceo_delivery_blocked(company_id, request.reason)
    updated = Company.get_by_id(company_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Company not found")
    return MarkAuditDeliveryBlockedResponse(
        company_id=updated.id,
        ceo_delivery_blocked_reason=updated.ceo_delivery_blocked_reason,
        ceo_delivery_blocked_at=(
            format_timestamp_seconds(updated.ceo_delivery_blocked_at)
            if updated.ceo_delivery_blocked_at
            else None
        ),
    )
