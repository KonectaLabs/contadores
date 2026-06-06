"""Agnostic persistence for company/contact/message workflows."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional, overload
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import phonenumbers
from pydantic import BaseModel, Field as PydanticField, field_serializer
from phonenumbers import NumberParseException
from sqlalchemy import Column, Enum as SQLAlchemyEnum, String, UniqueConstraint, and_, event, inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Field, Session, SQLModel, create_engine, select

from backend.calendly import normalize_calendly_url

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DATABASE_URL = f"sqlite:///{DATA_DIR / 'database.sqlite'}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _is_sqlite_url(database_url: str) -> bool:
    """Return True when SQLAlchemy is configured for SQLite."""
    return database_url.startswith("sqlite:")


def _build_engine():
    """Create the SQLAlchemy engine with conservative SQLite concurrency settings."""
    connect_args: dict[str, object] = {}
    if _is_sqlite_url(DATABASE_URL):
        connect_args = {
            "check_same_thread": False,
            "timeout": 30,
        }
    return create_engine(DATABASE_URL, echo=False, connect_args=connect_args)


engine = _build_engine()


if _is_sqlite_url(DATABASE_URL):

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
        """Use WAL and a busy timeout so reads and short writes can coexist."""
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


CONTACT_TYPE_ALIASES = {
    "phone": "whatsapp",
}
WHATSAPP_LIKE_CONTACT_TYPES = {"whatsapp"}
DEFAULT_REPORT_WINDOW_HOURS = 24
DEFAULT_REPORT_WINDOW_MINUTES = DEFAULT_REPORT_WINDOW_HOURS * 60
EMAIL_LOCAL_DISALLOWED_CHARACTERS = set('<>,;:"[]\\()')


def _extract_email_address(value: str) -> str:
    """Extract one normalized email address candidate from raw input."""
    return parseaddr(value or "")[1].strip().lower()


def _has_unsafe_email_character(value: str) -> bool:
    """Return True when text has whitespace or control characters."""
    return any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value)


def _is_valid_email_local_part(value: str) -> bool:
    """Validate an unquoted local part, including international characters."""
    if not value or len(value) > 64 or value.startswith(".") or value.endswith(".") or ".." in value:
        return False
    if "@" in value or _has_unsafe_email_character(value):
        return False
    return not any(char in EMAIL_LOCAL_DISALLOWED_CHARACTERS for char in value)


def _is_valid_email_domain(value: str) -> bool:
    """Validate a domain using IDNA so internationalized domains work."""
    if not value or len(value) > 253 or "." not in value:
        return False
    if value.startswith(".") or value.endswith(".") or "@" in value or _has_unsafe_email_character(value):
        return False

    ascii_labels: list[str] = []
    for label in value.split("."):
        if not label:
            return False
        try:
            ascii_label = label.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return False
        if not ascii_label or len(ascii_label) > 63:
            return False
        if ascii_label.startswith("-") or ascii_label.endswith("-"):
            return False
        if re.fullmatch(r"[a-z0-9-]+", ascii_label) is None:
            return False
        ascii_labels.append(ascii_label)
    return len(".".join(ascii_labels)) <= 253


def is_valid_email(value: str) -> bool:
    """Return True when the input is a syntactically complete email address."""
    clean = _extract_email_address(value)
    if not clean or len(clean) > 254 or clean.count("@") != 1 or ".." in clean:
        return False
    local_part, domain = clean.rsplit("@", 1)
    return _is_valid_email_local_part(local_part) and _is_valid_email_domain(domain)


def normalize_email(value: str) -> str:
    """Normalize one email value into canonical lowercase mailbox."""
    clean = _extract_email_address(value)
    return clean if is_valid_email(clean) else ""


def _default_phone_region() -> str:
    """Return the default region used for local phone normalization."""
    return (os.getenv("PHONE_DEFAULT_REGION", "AR") or "AR").strip().upper() or "AR"


def _extract_phone_candidate(value: str) -> str:
    """Extract one phone-like candidate from raw text or WhatsApp links."""
    raw = unquote((value or "").strip())
    if not raw:
        return ""
    if "://" in raw or raw.lower().startswith("wa.me/"):
        candidate_url = raw if "://" in raw else f"https://{raw}"
        parsed = urlsplit(candidate_url)
        host = (parsed.netloc or "").strip().lower()
        if host.endswith("wa.me"):
            return parsed.path.strip("/").split("/", 1)[0].strip()
        phone = parse_qs(parsed.query).get("phone", [""])[0].strip()
        if phone:
            return phone
    return raw


def _looks_like_argentine_local_phone(digits: str) -> bool:
    """Return True when digits look like an Argentina-local WhatsApp number."""
    compact = (digits or "").strip()
    if not compact:
        return False
    if compact.startswith("0"):
        return True
    if "15" in compact[:7]:
        return True
    return len(compact) == 10 and compact.startswith("11")


def _normalize_parsed_phone(parsed: phonenumbers.PhoneNumber) -> str:
    """Convert one parsed phone to canonical digits-only outbound form."""
    country_code = str(parsed.country_code or "").strip()
    national_number = str(parsed.national_number or "").strip()
    if not country_code or not national_number:
        return ""
    if country_code == "54":
        if national_number.startswith("9"):
            national_number = national_number[1:]
        return f"549{national_number}" if national_number else ""
    if country_code == "56" and len(national_number) == 8:
        return f"569{national_number}"
    return f"{country_code}{national_number}"


def normalize_phone(value: str) -> str:
    """Normalize one phone-like value to canonical digits-only WhatsApp form."""
    raw = _extract_phone_candidate(value)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""

    parse_candidate = ""
    region: str | None = None
    if raw.startswith("+"):
        parse_candidate = f"+{digits}"
    elif digits.startswith("00") and len(digits) > 2:
        parse_candidate = f"+{digits[2:]}"
    elif len(digits) > 10 and not digits.startswith("0"):
        parse_candidate = f"+{digits}"
    elif _default_phone_region() == "AR" and _looks_like_argentine_local_phone(digits):
        parse_candidate = raw
        region = "AR"
    else:
        return digits

    try:
        parsed = phonenumbers.parse(parse_candidate, region)
    except NumberParseException:
        return digits

    normalized = _normalize_parsed_phone(parsed)
    if not phonenumbers.is_possible_number(parsed):
        return normalized if normalized != digits and normalized.startswith("569") else digits
    return normalized or digits


def canonical_contact_type(contact_type: str) -> str:
    """Canonicalize one raw contact type to stable backend categories."""
    normalized = (contact_type or "").strip().lower()
    return CONTACT_TYPE_ALIASES.get(normalized, normalized)


def normalize_contact_value(contact_type: str, value: str) -> str:
    """Normalize one contact value according to contact type."""
    normalized_type = canonical_contact_type(contact_type)
    raw_value = (value or "").strip()
    if normalized_type == "email":
        return normalize_email(raw_value)
    if normalized_type in WHATSAPP_LIKE_CONTACT_TYPES:
        return normalize_phone(raw_value)
    return raw_value.lower()


class ConversationMessage(BaseModel):
    """Single conversation message."""

    from_me: bool
    text: str = PydanticField(min_length=1)
    timestamp: datetime = PydanticField(default_factory=lambda: datetime.now(timezone.utc))

    @field_serializer("timestamp", when_used="json")
    def serialize_timestamp_seconds(self, value: datetime) -> str:
        """Serialize timestamp with second precision (no milliseconds)."""
        dt = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


class ContactConversationStats(BaseModel):
    """Deterministic conversation stats used for Stage 3 report context."""

    first_response_seconds: float | None = None
    avg_response_seconds: float | None = None


class ContactLLMInfo(BaseModel):
    """Complete contact-level LLM context for Stage 3 report generation."""

    contact_type: str
    contact_value: str
    objective: str | None = None
    conversation_done: bool = False
    notes: str | None = None
    additional_context: str | None = None
    stats: ContactConversationStats
    conversation: list[ConversationMessage] = PydanticField(default_factory=list)


class CompanyLLMInfo(BaseModel):
    """Complete company-level LLM context for Stage 3 report generation."""

    company_name: str
    source_url: str
    company_info: str
    ceo_email: str | None = None
    objective: str | None = None
    contacts: list[ContactLLMInfo] = PydanticField(default_factory=list)


def compute_contact_conversation_stats(messages: list[ConversationMessage]) -> ContactConversationStats:
    """Compute deterministic transcript stats for one contact."""
    first_outbound_at: datetime | None = None
    first_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    response_deltas: list[float] = []

    for message in messages:
        ts = message.timestamp
        if message.from_me:
            if first_outbound_at is None:
                first_outbound_at = ts
            last_outbound_at = ts
            continue

        if first_inbound_at is None:
            first_inbound_at = ts
        if last_outbound_at is not None:
            delta = (ts - last_outbound_at).total_seconds()
            if delta >= 0:
                response_deltas.append(delta)

    first_response_seconds: float | None = None
    if first_outbound_at is not None and first_inbound_at is not None:
        first_response_seconds = max(0.0, (first_inbound_at - first_outbound_at).total_seconds())
    avg_response_seconds: float | None = None
    if response_deltas:
        avg_response_seconds = float(statistics.mean(response_deltas))

    return ContactConversationStats(
        first_response_seconds=first_response_seconds,
        avg_response_seconds=avg_response_seconds,
    )


class CompanyStatus(str, Enum):
    """Status of one company workflow."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    INITIALIZING = "initializing"
    AUDITED = "audited"


class CompanyLanguage(str, Enum):
    """Allowed company communication languages."""

    EN = "en"
    ES = "es"


def normalize_company_language(
    language: CompanyLanguage | str | None,
) -> CompanyLanguage | None:
    """Normalize one raw language value to CompanyLanguage."""
    if isinstance(language, CompanyLanguage):
        return language
    normalized = (language or "").strip().lower().replace("-", "_")
    if not normalized:
        return None
    if normalized.startswith("en"):
        return CompanyLanguage.EN
    if normalized.startswith("es"):
        return CompanyLanguage.ES
    return None


def normalize_company_size(company_size: str | None) -> str:
    """Normalize one raw company size value to supported buckets."""
    normalized = (company_size or "").strip().lower()
    if normalized in {"small", "medium", "large"}:
        return normalized
    return "unknown"


def normalize_company_industry(industry: str | None) -> str:
    """Normalize one raw industry slug to lowercase underscore format."""
    normalized = (industry or "").strip().lower().replace("-", "_").replace(" ", "_")
    compact = "_".join(part for part in normalized.split("_") if part)
    return compact or "unknown"


def _parse_company_source_url(value: str):
    """Parse one company URL candidate after adding a default scheme when needed."""
    raw_value = (value or "").strip()
    if not raw_value:
        return None

    candidate = raw_value
    if "://" not in candidate:
        if any(ch.isspace() for ch in candidate):
            return None
        candidate = f"https://{candidate.lstrip('/')}"

    parsed = urlsplit(candidate)
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname or "." not in hostname:
        return None
    return parsed


def normalize_company_source_url(value: str) -> str:
    """Normalize one company URL for stable storage/display."""
    parsed = _parse_company_source_url(value)
    if parsed is None:
        return ""

    scheme = (parsed.scheme or "https").strip().lower() or "https"
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = hostname if port is None else f"{hostname}:{port}"
    path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
    if path == "/":
        path = ""
    return urlunsplit((scheme, netloc, path, "", ""))


def normalize_company_source_url_key(value: str) -> str:
    """Normalize one company URL into a duplicate-detection key that ignores scheme."""
    normalized_url = normalize_company_source_url(value)
    if not normalized_url:
        return ""
    parsed = urlsplit(normalized_url)
    path = (parsed.path or "").rstrip("/")
    if path == "/":
        path = ""
    return f"{parsed.netloc}{path}"


def normalize_company_tag(value: str | None) -> str:
    """Normalize one freeform company tag while preserving operator wording."""
    return " ".join(str(value or "").split())


def normalize_company_tags(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize one company tag list with stable order and case-insensitive dedupe."""
    if not values:
        return []

    normalized_tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_company_tag(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_tags.append(normalized)
    return normalized_tags


def serialize_company_tags(values: list[str] | tuple[str, ...] | None) -> str:
    """Serialize normalized company tags into one stable JSON string."""
    return json.dumps(normalize_company_tags(values), ensure_ascii=True)


def deserialize_company_tags(raw_value: str | None) -> list[str]:
    """Deserialize one stored company tag JSON payload with safe fallback."""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return normalize_company_tags([str(item) for item in parsed])


def normalize_report_window_hours(report_window_hours: int | None) -> int:
    """Normalize report window hours to a positive integer."""
    if report_window_hours is None:
        return DEFAULT_REPORT_WINDOW_HOURS
    return max(1, int(report_window_hours))


def normalize_report_window_minutes(
    report_window_minutes: int | None = None,
    *,
    report_window_hours: int | None = None,
) -> int:
    """Normalize report window minutes, keeping legacy hour callers supported."""
    if report_window_minutes is not None:
        return max(1, int(report_window_minutes))
    return normalize_report_window_hours(report_window_hours) * 60


def legacy_report_window_hours_from_minutes(report_window_minutes: int) -> int:
    """Approximate minute-based schedules back into legacy whole hours."""
    normalized_minutes = max(1, int(report_window_minutes))
    return max(1, (normalized_minutes + 59) // 60)


def normalize_schedule_datetime(value: datetime | None) -> datetime | None:
    """Normalize schedule datetimes to UTC minute precision."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.replace(second=0, microsecond=0)


def compute_report_scheduled_send_at(
    created_at: datetime,
    *,
    report_window_minutes: int | None = None,
    report_window_hours: int | None = None,
    report_scheduled_send_at: datetime | None = None,
) -> datetime:
    """Resolve one persisted scheduled-send datetime from legacy or minute inputs."""
    normalized_created_at = normalize_schedule_datetime(created_at) or datetime.now(timezone.utc).replace(
        second=0,
        microsecond=0,
    )
    normalized_scheduled_send_at = normalize_schedule_datetime(report_scheduled_send_at)
    if normalized_scheduled_send_at is not None:
        return normalized_scheduled_send_at
    normalized_minutes = normalize_report_window_minutes(
        report_window_minutes,
        report_window_hours=report_window_hours,
    )
    return normalized_created_at + timedelta(minutes=normalized_minutes)


def compute_report_window_minutes(
    created_at: datetime,
    *,
    report_scheduled_send_at: datetime | None = None,
    report_window_hours: int | None = None,
) -> int:
    """Resolve one minute-based window from persisted company schedule state."""
    scheduled_at = compute_report_scheduled_send_at(
        created_at,
        report_window_hours=report_window_hours,
        report_scheduled_send_at=report_scheduled_send_at,
    )
    normalized_created_at = normalize_schedule_datetime(created_at) or scheduled_at
    delta_seconds = max(60.0, (scheduled_at - normalized_created_at).total_seconds())
    return max(1, round(delta_seconds / 60))


class ContactStatus(str, Enum):
    """Lifecycle status of one contact."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class MessageDeliveryStatus(str, Enum):
    """Manual delivery status for outbound messages."""

    UNDELIVERED = "undelivered"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class ClientLeadDeliveryStatus(str, Enum):
    """Delivery state for client-owned lead notifications."""

    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class CrmMessageDirection(str, Enum):
    """Direction for one CRM email message."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CrmMessageKind(str, Enum):
    """Semantic kind for one CRM email message."""

    REPORT_DELIVERY = "report_delivery"
    MANUAL_REPLY = "manual_reply"
    CEO_REPLY = "ceo_reply"


class CrmMessageStatus(str, Enum):
    """Lifecycle status for one CRM email message."""

    PENDING = "pending"
    SENT = "sent"
    RECEIVED = "received"


class TaskStatus(str, Enum):
    """Status of an async backend task."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(SQLModel, table=True):
    """Background task state for API polling."""

    __tablename__ = "tasks"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    status: TaskStatus = Field(default=TaskStatus.QUEUED, index=True)
    task_type: str = Field(default="", index=True)
    resource_id: Optional[str] = Field(default=None, index=True)
    error: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        *,
        task_type: str,
        resource_id: Optional[str] = None,
    ) -> "Task":
        """Persist one task in queued status."""
        with Session(engine) as session:
            task = cls(
                task_type=task_type,
                resource_id=resource_id,
            )
            session.add(task)
            session.commit()
            session.refresh(task)
            session.expunge(task)
            return task

    @classmethod
    def get_by_id(cls, task_id: str) -> Optional["Task"]:
        """Get one task by ID."""
        with Session(engine) as session:
            task = session.get(cls, task_id)
            if task:
                session.expunge(task)
            return task

    @classmethod
    def set_status(cls, task_id: str, *, status: TaskStatus, error: Optional[str] = None) -> None:
        """Update task status and error message."""
        with Session(engine) as session:
            task = session.get(cls, task_id)
            if not task:
                return
            task.status = status
            task.error = error
            task.updated_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()

    @classmethod
    def has_pending_for_resource(
        cls,
        *,
        resource_id: str,
        task_type: Optional[str] = None,
    ) -> bool:
        """Return True when one resource has queued/running tasks."""
        with Session(engine) as session:
            statement = select(cls.id).where(
                cls.resource_id == resource_id,
                cls.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING]),
            )
            if task_type:
                statement = statement.where(cls.task_type == task_type)
            return session.exec(statement.limit(1)).first() is not None

    @classmethod
    def list_pending_task_types_for_resource(
        cls,
        *,
        resource_id: str,
    ) -> list[str]:
        """List non-terminal task types for one resource in creation order."""
        with Session(engine) as session:
            statement = (
                select(cls.task_type)
                .where(
                    cls.resource_id == resource_id,
                    cls.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING]),
                )
                .order_by(cls.created_at, cls.id)
            )
            return list(session.exec(statement).all())

    @classmethod
    def run_async(
        cls,
        background_tasks,
        fn,
        *,
        resource_id: Optional[str] = None,
        timeout_seconds: float | None = None,
        **fn_kwargs,
    ) -> "Task":
        """Queue one function and track status in tasks table."""
        task_name = getattr(fn, "__name__", "task")
        task = cls.create(task_type=task_name, resource_id=resource_id)

        async def runner() -> None:
            cls.set_status(task.id, status=TaskStatus.RUNNING)
            try:
                if asyncio.iscoroutinefunction(fn):
                    work = fn(**fn_kwargs)
                else:
                    work = asyncio.to_thread(fn, **fn_kwargs)

                if timeout_seconds is not None and timeout_seconds > 0:
                    await asyncio.wait_for(work, timeout=timeout_seconds)
                else:
                    await work

                cls.set_status(task.id, status=TaskStatus.COMPLETED)
            except asyncio.TimeoutError:
                error_message = (
                    f"Task timed out after {timeout_seconds:.0f}s"
                    if timeout_seconds
                    else "Task timed out"
                )
                logger.error(
                    "Task %s (%s) timed out after %ss",
                    task.id,
                    task_name,
                    timeout_seconds,
                )
                cls.set_status(task.id, status=TaskStatus.FAILED, error=error_message)
            except Exception as exc:
                error_message = str(exc)
                logger.exception(
                    "Task %s (%s) failed: %s",
                    task.id,
                    task_name,
                    error_message,
                )
                cls.set_status(task.id, status=TaskStatus.FAILED, error=error_message)

        background_tasks.add_task(runner)
        return task


def _default_contadores_alert_emails_json() -> str:
    """Build default Contadores alert recipients from env."""
    raw_value = (os.getenv("CONTADORES_ALERT_EMAILS", "") or "").strip()
    emails = [
        normalize_email(part)
        for part in raw_value.split(",")
        if normalize_email(part)
    ]
    return json.dumps(emails)


def normalize_contadores_tag(value: str | None) -> str:
    """Normalize one operator tag while preserving readable wording."""
    return " ".join(str(value or "").split())


def normalize_contadores_tags(values: list[str] | tuple[str, ...] | None) -> list[str]:
    """Normalize a tag list with stable order and case-insensitive dedupe."""
    if not values:
        return []

    normalized_tags: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_contadores_tag(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized_tags.append(normalized)
    return normalized_tags


def serialize_contadores_tags(values: list[str] | tuple[str, ...] | None) -> str:
    """Serialize normalized lead tags into one JSON field."""
    return json.dumps(normalize_contadores_tags(values), ensure_ascii=True)


def deserialize_contadores_tags(raw_value: str | None) -> list[str]:
    """Deserialize stored lead tags with a safe fallback."""
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return normalize_contadores_tags([str(item) for item in parsed])


class ContadoresLeadStage(str, Enum):
    """Lifecycle stage for one Contadores lead."""

    AWAITING_INITIAL_REPLY = "awaiting_initial_reply"
    AWAITING_VIDEO_REPLY = "awaiting_video_reply"
    NEEDS_HUMAN = "needs_human"
    CALENDLY_SENT = "calendly_sent"
    BOOKED = "booked"
    CLOSED = "closed"
    ARCHIVED = "archived"


CONTADORES_LEAD_PIPELINE_STAGES = {
    "new",
    "contacted",
    "offer_sent",
    "meeting_sent",
    "converted",
    "closed",
    "archived",
}
CONTADORES_LEAD_QUEUE_STATES = {"automation", "operator", "workstation", "paused", "none"}
CONTADORES_LEAD_TERMINAL_STATES = {"open", "closed", "archived"}
CONTADORES_LEAD_ATTENTION_STATES = {"clear", "needs_reply", "answered", "paused", "converted", "closed", "archived"}
CONTADORES_LEAD_MANUAL_CONVERTED_REASON = "manual_converted"
CONTADORES_LEAD_LEGACY_MANUAL_BOOKED_REASON = "manual_booked"
CONTADORES_CLOSED_LEAD_DELIVERY_SEQUENCE_STEPS = {"ai_rejection_survey"}
CONTADORES_CONVERTED_LEAD_DELIVERY_SEQUENCE_STEPS = {
    "workstation_intake",
    "workstation_preview_video",
    "workstation_revision_video",
    "workstation_public_page_link",
    "workstation_codex_heartbeat",
    "workstation_handoff",
}
WORKSTATION_OPERATOR_HANDOFF_REASONS = {
    "workstation_agent_handoff",
    "workstation_no_response_handoff",
    "workstation_solo_page_approved",
}


def normalize_lifecycle_datetime(value: datetime | None) -> datetime | None:
    """Return a timezone-aware datetime for lifecycle comparisons."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _default_contadores_post_loom_min_seconds() -> int:
    """Return the configured post-Loom minimum wait, defaulting to 5 minutes."""
    return max(60, int(os.getenv("CONTADORES_POST_LOOM_MIN_SECONDS", "300")))


def _normalize_contadores_strategy_weights(value: Any) -> dict[str, dict[str, int]]:
    """Normalize configured strategy rollout weights."""
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, dict[str, int]] = {}
    for raw_step, raw_strategies in value.items():
        step = str(raw_step or "").strip()
        if not step or not isinstance(raw_strategies, dict):
            continue

        strategy_weights: dict[str, int] = {}
        for raw_strategy_id, raw_weight in raw_strategies.items():
            strategy_id = str(raw_strategy_id or "").strip()
            if not strategy_id:
                continue
            try:
                strategy_weights[strategy_id] = min(100, max(0, int(raw_weight)))
            except (TypeError, ValueError):
                continue

        if strategy_weights:
            normalized[step] = strategy_weights
    return normalized


def _default_contadores_strategy_weights_json() -> str:
    """Return configured strategy weights from env as JSON text."""
    raw_value = (os.getenv("CONTADORES_STRATEGY_WEIGHTS_JSON", "") or "").strip()
    if not raw_value:
        return "{}"
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        logger.warning("Ignoring invalid CONTADORES_STRATEGY_WEIGHTS_JSON.")
        return "{}"
    return json.dumps(_normalize_contadores_strategy_weights(payload), ensure_ascii=True)


def _normalize_contadores_calendly_base_url(base_url: str | None) -> str:
    """Normalize the configured Contadores booking URL."""
    return normalize_calendly_url(base_url)


class ContadoresConfig(SQLModel, table=True):
    """Singleton-style runtime configuration for Contadores."""

    __tablename__ = "contadores_config"

    id: str = Field(default="default", primary_key=True)
    enabled: bool = Field(default=False)
    sheet_url: str | None = Field(default_factory=lambda: (os.getenv("CONTADORES_SHEET_URL", "") or None))
    sheet_gid: str | None = Field(default_factory=lambda: (os.getenv("CONTADORES_SHEET_GID", "") or None))
    sheet_poll_seconds: int = Field(
        default_factory=lambda: max(30, int(os.getenv("CONTADORES_SHEET_POLL_SECONDS", "30")))
    )
    loom_url: str = Field(
        default_factory=lambda: (os.getenv("CONTADORES_LOOM_URL", "") or "").strip()
    )
    calendly_base_url: str = Field(
        default_factory=lambda: _normalize_contadores_calendly_base_url(
            os.getenv("CONTADORES_CALENDLY_BASE_URL")
        )
    )
    alert_emails_json: str = Field(default_factory=_default_contadores_alert_emails_json)
    initial_reply_quiet_seconds: int = Field(
        default_factory=lambda: max(1, int(os.getenv("CONTADORES_INITIAL_REPLY_QUIET_SECONDS", "30")))
    )
    post_loom_min_seconds: int = Field(
        default_factory=_default_contadores_post_loom_min_seconds
    )
    post_loom_quiet_seconds: int = Field(
        default_factory=lambda: max(1, int(os.getenv("CONTADORES_POST_LOOM_QUIET_SECONDS", "30")))
    )
    strategy_weights_json: str = Field(default_factory=_default_contadores_strategy_weights_json)
    last_sheet_sync_at: datetime | None = Field(default=None)
    last_sheet_sync_status: str | None = Field(default=None)
    last_sheet_sync_note: str | None = Field(default=None)
    last_alert_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def alert_emails(self) -> list[str]:
        """Return configured alert emails as a normalized list."""
        try:
            payload = json.loads(self.alert_emails_json or "[]")
        except json.JSONDecodeError:
            payload = []
        return [
            normalize_email(str(item))
            for item in payload
            if normalize_email(str(item))
        ]

    @property
    def strategy_weights(self) -> dict[str, dict[str, int]]:
        """Return configured strategy rollout weights by step and strategy id."""
        try:
            payload = json.loads(self.strategy_weights_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        return _normalize_contadores_strategy_weights(payload)

    @classmethod
    def get(cls) -> "ContadoresConfig":
        """Get the singleton config row, creating it from env defaults if missing."""
        with Session(engine) as session:
            item = session.get(cls, "default")
            if item is None:
                item = cls()
                session.add(item)
                session.commit()
                session.refresh(item)
            elif (
                "CONTADORES_POST_LOOM_MIN_SECONDS" not in os.environ
                and item.post_loom_min_seconds == 600
            ):
                item.post_loom_min_seconds = _default_contadores_post_loom_min_seconds()
                item.updated_at = datetime.now(timezone.utc)
                session.add(item)
                session.commit()
                session.refresh(item)
            if "CONTADORES_SHEET_POLL_SECONDS" not in os.environ and item.sheet_poll_seconds == 300:
                item.sheet_poll_seconds = 30
                item.updated_at = datetime.now(timezone.utc)
                session.add(item)
                session.commit()
                session.refresh(item)
            normalized_calendly_base_url = _normalize_contadores_calendly_base_url(item.calendly_base_url)
            if item.calendly_base_url != normalized_calendly_base_url:
                item.calendly_base_url = normalized_calendly_base_url
                item.updated_at = datetime.now(timezone.utc)
                session.add(item)
                session.commit()
                session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update(
        cls,
        *,
        enabled: bool | None = None,
        sheet_url: str | None = None,
        sheet_gid: str | None = None,
        sheet_poll_seconds: int | None = None,
        loom_url: str | None = None,
        calendly_base_url: str | None = None,
        alert_emails: list[str] | None = None,
        initial_reply_quiet_seconds: int | None = None,
        post_loom_min_seconds: int | None = None,
        post_loom_quiet_seconds: int | None = None,
        strategy_weights: dict[str, dict[str, int]] | None = None,
    ) -> "ContadoresConfig":
        """Update the singleton config row."""
        with Session(engine) as session:
            item = session.get(cls, "default")
            if item is None:
                item = cls()
            if enabled is not None:
                item.enabled = bool(enabled)
            if sheet_url is not None:
                item.sheet_url = (sheet_url or "").strip() or None
            if sheet_gid is not None:
                item.sheet_gid = (sheet_gid or "").strip() or None
            if sheet_poll_seconds is not None:
                item.sheet_poll_seconds = max(30, int(sheet_poll_seconds))
            if loom_url is not None:
                item.loom_url = (loom_url or "").strip()
            if calendly_base_url is not None:
                item.calendly_base_url = _normalize_contadores_calendly_base_url(calendly_base_url)
            if alert_emails is not None:
                item.alert_emails_json = json.dumps(
                    [
                        normalize_email(raw_email)
                        for raw_email in alert_emails
                        if normalize_email(raw_email)
                    ]
                )
            if initial_reply_quiet_seconds is not None:
                item.initial_reply_quiet_seconds = max(1, int(initial_reply_quiet_seconds))
            if post_loom_min_seconds is not None:
                item.post_loom_min_seconds = max(60, int(post_loom_min_seconds))
            if post_loom_quiet_seconds is not None:
                item.post_loom_quiet_seconds = max(1, int(post_loom_quiet_seconds))
            if strategy_weights is not None:
                item.strategy_weights_json = json.dumps(
                    _normalize_contadores_strategy_weights(strategy_weights),
                    ensure_ascii=True,
                )
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def mark_sheet_sync(cls, *, status: str, note: str | None = None) -> None:
        """Persist latest sheet sync health."""
        with Session(engine) as session:
            item = session.get(cls, "default") or cls()
            now = datetime.now(timezone.utc)
            item.last_sheet_sync_at = now
            item.last_sheet_sync_status = (status or "").strip() or None
            item.last_sheet_sync_note = (note or "").strip() or None
            item.updated_at = now
            session.add(item)
            session.commit()

    @classmethod
    def mark_alert_sent(cls, *, sent_at: datetime | None = None) -> None:
        """Persist latest alert timestamp."""
        with Session(engine) as session:
            item = session.get(cls, "default") or cls()
            now = sent_at or datetime.now(timezone.utc)
            item.last_alert_at = now
            item.updated_at = now
            session.add(item)
            session.commit()


class ContadoresLead(SQLModel, table=True):
    """Contadores lead state tracked independently from audit contacts."""

    __tablename__ = "contadores_leads"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    funnel_id: str = Field(default="contadores", index=True)
    external_lead_id: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    phone: str = Field(default="")
    normalized_phone: str = Field(default="", index=True)
    full_name: str | None = Field(default=None)
    email: str | None = Field(default=None)
    platform: str | None = Field(default=None, index=True)
    lead_status: str | None = Field(default=None)
    tags_json: str = Field(default="[]")
    sheet_created_time: datetime | None = Field(default=None)
    stage: ContadoresLeadStage = Field(default=ContadoresLeadStage.AWAITING_INITIAL_REPLY, index=True)
    pipeline_stage: str = Field(default="new", index=True)
    queue_state: str = Field(default="automation", index=True)
    terminal_state: str = Field(default="open", index=True)
    attention_state: str = Field(default="clear", index=True)
    calendly_tracking_token: str = Field(default_factory=lambda: uuid.uuid4().hex, index=True)
    last_classification_label: str | None = Field(default=None, index=True)
    last_classification_reason: str | None = Field(default=None)
    opener_sent_at: datetime | None = Field(default=None, index=True)
    first_reply_received_at: datetime | None = Field(default=None, index=True)
    loom_sent_at: datetime | None = Field(default=None, index=True)
    video_check_sent_at: datetime | None = Field(default=None, index=True)
    classification_completed_at: datetime | None = Field(default=None)
    calendly_sent_at: datetime | None = Field(default=None, index=True)
    meeting_scheduled_at: datetime | None = Field(default=None, index=True)
    booked_at: datetime | None = Field(default=None, index=True)
    closed_at: datetime | None = Field(default=None, index=True)
    stage_before_closed: ContadoresLeadStage | None = Field(default=None)
    needs_human_notified_at: datetime | None = Field(default=None)
    manual_reply_handled_at: datetime | None = Field(default=None)
    last_inbound_at: datetime | None = Field(default=None, index=True)
    last_outbound_at: datetime | None = Field(default=None, index=True)
    conversation_processing_started_at: datetime | None = Field(default=None, index=True)
    conversation_processing_latest_inbound_id: int | None = Field(default=None, index=True)
    codex_conversation_thread_id: str | None = Field(default=None, index=True)
    archived_at: datetime | None = Field(default=None, index=True)
    automation_paused: bool = Field(default=False, index=True)
    automation_paused_reason: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def tags(self) -> list[str]:
        """Return normalized operator tags for this lead."""
        return deserialize_contadores_tags(self.tags_json)

    @classmethod
    def normalize_stage(cls, stage: ContadoresLeadStage | str | None) -> ContadoresLeadStage:
        """Normalize raw lead stage values."""
        if isinstance(stage, ContadoresLeadStage):
            return stage
        value = (stage or "").strip().lower()
        for candidate in ContadoresLeadStage:
            if candidate.value == value:
                return candidate
        return ContadoresLeadStage.AWAITING_INITIAL_REPLY

    @classmethod
    def open_workstation_client(cls, lead: "ContadoresLead") -> Any | None:
        """Return the active Workstation client without importing endpoint code."""
        workstation_client_cls = globals().get("WorkstationClient")
        workstation_status_cls = globals().get("WorkstationClientStatus")
        if workstation_client_cls is None or workstation_status_cls is None:
            return None
        client = workstation_client_cls.get_by_lead_id(lead.id)
        if client is None:
            return None
        if client.status in {workstation_status_cls.CLOSED, workstation_status_cls.ARCHIVED}:
            return None
        return client

    @classmethod
    def workstation_handoff_requires_operator(
        cls,
        lead: "ContadoresLead",
        client: Any | None = None,
    ) -> bool:
        """Return True only when Workstation explicitly handed the lead back."""
        workstation_client = client or cls.open_workstation_client(lead)
        workstation_automation_status_cls = globals().get("WorkstationAutomationStatus")
        if workstation_client is None or workstation_automation_status_cls is None:
            return False
        return (
            workstation_client.automation_status == workstation_automation_status_cls.NEEDS_HUMAN
            and lead.automation_paused_reason in WORKSTATION_OPERATOR_HANDOFF_REASONS
        )

    @classmethod
    def lead_is_workstation_managed_without_operator_handoff(cls, lead: "ContadoresLead") -> bool:
        """Return True when Workstation owns the lead without an operator handoff."""
        workstation_client = cls.open_workstation_client(lead)
        if workstation_client is None:
            return False
        return not cls.workstation_handoff_requires_operator(lead, workstation_client)

    @classmethod
    def lead_is_converted(
        cls,
        lead: "ContadoresLead",
        *,
        effective_stage: ContadoresLeadStage | None = None,
    ) -> bool:
        """Return True when stored lead evidence crosses the conversion boundary."""
        if effective_stage == ContadoresLeadStage.BOOKED:
            return True
        return lead.stage == ContadoresLeadStage.BOOKED or lead.booked_at is not None

    @classmethod
    def derive_effective_stage(cls, lead: "ContadoresLead") -> ContadoresLeadStage:
        """Return the current operator-facing legacy stage."""
        if lead.stage == ContadoresLeadStage.ARCHIVED or lead.archived_at is not None:
            return ContadoresLeadStage.ARCHIVED
        if lead.stage == ContadoresLeadStage.CLOSED or lead.closed_at is not None:
            return ContadoresLeadStage.CLOSED
        if lead.stage == ContadoresLeadStage.NEEDS_HUMAN:
            workstation_client = cls.open_workstation_client(lead)
            if workstation_client is not None:
                if cls.workstation_handoff_requires_operator(lead, workstation_client):
                    return ContadoresLeadStage.NEEDS_HUMAN
                return ContadoresLeadStage.BOOKED
            if cls.lead_is_converted(lead):
                return ContadoresLeadStage.BOOKED
            if lead.meeting_scheduled_at is not None:
                return ContadoresLeadStage.CALENDLY_SENT
            return ContadoresLeadStage.NEEDS_HUMAN
        if cls.lead_is_converted(lead):
            return ContadoresLeadStage.BOOKED
        if lead.meeting_scheduled_at is not None:
            return ContadoresLeadStage.CALENDLY_SENT
        if lead.calendly_sent_at is not None:
            return ContadoresLeadStage.CALENDLY_SENT
        return lead.stage

    @classmethod
    def derive_manual_reply_status(
        cls,
        lead: "ContadoresLead",
        *,
        effective_stage: ContadoresLeadStage | None = None,
    ) -> str | None:
        """Return whether the current manual handoff needs an operator reply."""
        if cls.lead_is_workstation_managed_without_operator_handoff(lead):
            return None
        if (effective_stage or cls.derive_effective_stage(lead)) != ContadoresLeadStage.NEEDS_HUMAN:
            return None

        last_inbound_at = normalize_lifecycle_datetime(lead.last_inbound_at)
        latest_answer_at = max(
            [
                item
                for item in [
                    normalize_lifecycle_datetime(lead.last_outbound_at),
                    normalize_lifecycle_datetime(lead.manual_reply_handled_at),
                ]
                if item is not None
            ],
            default=None,
        )
        if last_inbound_at is not None and (latest_answer_at is None or last_inbound_at > latest_answer_at):
            return "needs_reply"
        if last_inbound_at is not None or latest_answer_at is not None:
            return "answered"
        return None

    @classmethod
    def derive_terminal_state(
        cls,
        lead: "ContadoresLead",
        *,
        effective_stage: ContadoresLeadStage | None = None,
    ) -> str:
        """Return the terminal overlay without mixing it into the sales pipeline."""
        stage = effective_stage or cls.derive_effective_stage(lead)
        if stage == ContadoresLeadStage.ARCHIVED or lead.archived_at is not None:
            return "archived"
        if stage == ContadoresLeadStage.CLOSED or lead.closed_at is not None:
            return "closed"
        return "open"

    @classmethod
    def derive_pipeline_stage(
        cls,
        lead: "ContadoresLead",
        *,
        effective_stage: ContadoresLeadStage | None = None,
    ) -> str:
        """Return the conceptual commercial milestone for operator UI and filters."""
        stage = effective_stage or cls.derive_effective_stage(lead)
        if stage == ContadoresLeadStage.ARCHIVED:
            return "archived"
        if stage == ContadoresLeadStage.CLOSED:
            return "closed"
        if cls.lead_is_converted(lead, effective_stage=stage):
            return "converted"
        if (
            stage == ContadoresLeadStage.CALENDLY_SENT
            or lead.calendly_sent_at is not None
            or lead.meeting_scheduled_at is not None
        ):
            return "meeting_sent"
        if stage == ContadoresLeadStage.AWAITING_VIDEO_REPLY or lead.loom_sent_at is not None:
            return "offer_sent"
        if lead.opener_sent_at is not None:
            return "contacted"
        return "new"

    @classmethod
    def derive_queue_state(
        cls,
        lead: "ContadoresLead",
        *,
        effective_stage: ContadoresLeadStage | None = None,
        manual_reply_status: str | None = None,
    ) -> str:
        """Return who owns the next action."""
        stage = effective_stage or cls.derive_effective_stage(lead)
        terminal_state = cls.derive_terminal_state(lead, effective_stage=stage)
        if terminal_state != "open":
            return "none"
        if manual_reply_status in {"needs_reply", "answered"} or stage == ContadoresLeadStage.NEEDS_HUMAN:
            return "operator"
        if cls.open_workstation_client(lead) is not None:
            return "workstation"
        if cls.lead_is_converted(lead, effective_stage=stage):
            return "none"
        if lead.automation_paused:
            return "paused"
        return "automation"

    @classmethod
    def derive_attention_state(
        cls,
        lead: "ContadoresLead",
        *,
        effective_stage: ContadoresLeadStage | None = None,
        manual_reply_status: str | None = None,
    ) -> str:
        """Return the strongest operator-facing attention state."""
        stage = effective_stage or cls.derive_effective_stage(lead)
        terminal_state = cls.derive_terminal_state(lead, effective_stage=stage)
        if terminal_state != "open":
            return terminal_state
        if manual_reply_status in {"needs_reply", "answered"}:
            return manual_reply_status
        if cls.lead_is_converted(lead, effective_stage=stage):
            return "converted"
        if lead.automation_paused:
            return "paused"
        return "clear"

    @classmethod
    def refresh_lifecycle_fields(cls, lead: "ContadoresLead") -> None:
        """Persist the v2 lifecycle projection on the lead row itself."""
        effective_stage = cls.derive_effective_stage(lead)
        manual_reply_status = cls.derive_manual_reply_status(lead, effective_stage=effective_stage)
        lead.pipeline_stage = cls.derive_pipeline_stage(lead, effective_stage=effective_stage)
        lead.terminal_state = cls.derive_terminal_state(lead, effective_stage=effective_stage)
        lead.queue_state = cls.derive_queue_state(
            lead,
            effective_stage=effective_stage,
            manual_reply_status=manual_reply_status,
        )
        lead.attention_state = cls.derive_attention_state(
            lead,
            effective_stage=effective_stage,
            manual_reply_status=manual_reply_status,
        )

    @classmethod
    def sync_lifecycle_fields(cls, lead_id: str) -> Optional["ContadoresLead"]:
        """Recompute persisted lifecycle fields for one existing lead."""
        with Session(engine) as session:
            item = session.get(cls, lead_id)
            if item is None:
                return None
            before = (item.pipeline_stage, item.queue_state, item.terminal_state, item.attention_state)
            cls.refresh_lifecycle_fields(item)
            after = (item.pipeline_stage, item.queue_state, item.terminal_state, item.attention_state)
            if after != before:
                session.add(item)
                session.commit()
                session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def get_by_id(cls, lead_id: str) -> Optional["ContadoresLead"]:
        """Get one lead by ID."""
        with Session(engine) as session:
            item = session.get(cls, lead_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_by_external_lead_id(
        cls,
        external_lead_id: str,
        *,
        funnel_id: str | None = None,
    ) -> Optional["ContadoresLead"]:
        """Get one lead by sheet external id."""
        clean_external_lead_id = (external_lead_id or "").strip()
        if not clean_external_lead_id:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.external_lead_id == clean_external_lead_id).limit(1)
            if funnel_id is not None:
                statement = statement.where(cls.funnel_id == ((funnel_id or "").strip() or "contadores"))
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_by_calendly_tracking_token(cls, token: str) -> Optional["ContadoresLead"]:
        """Get one lead by stable Calendly tracking token."""
        clean_token = (token or "").strip()
        if not clean_token:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.calendly_tracking_token == clean_token).limit(1)
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_by_normalized_phone(
        cls,
        normalized_phone: str,
        *,
        include_archived: bool = False,
    ) -> list["ContadoresLead"]:
        """List leads by normalized WhatsApp phone."""
        clean_phone = (normalized_phone or "").strip()
        if not clean_phone:
            return []
        with Session(engine) as session:
            statement = select(cls).where(cls.normalized_phone == clean_phone)
            if not include_archived:
                statement = statement.where(cls.stage != ContadoresLeadStage.ARCHIVED)
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc(), cls.id.desc())
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_recent(
        cls,
        *,
        limit: int = 500,
        funnel_id: str | None = None,
        stage: ContadoresLeadStage | str | None = None,
        platform: str | None = None,
        include_archived: bool = True,
    ) -> list["ContadoresLead"]:
        """List recent leads with optional filters."""
        with Session(engine) as session:
            statement = select(cls)
            if funnel_id is not None:
                statement = statement.where(cls.funnel_id == ((funnel_id or "").strip() or "contadores"))
            if stage is not None:
                statement = statement.where(cls.stage == cls.normalize_stage(stage))
            if platform is not None:
                statement = statement.where(cls.platform == ((platform or "").strip() or None))
            if not include_archived:
                statement = statement.where(cls.stage != ContadoresLeadStage.ARCHIVED)
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc(), cls.id.desc()).limit(limit)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_needs_human_without_notification(
        cls,
        *,
        funnel_id: str | None = None,
        limit: int = 100,
    ) -> list["ContadoresLead"]:
        """List leads that entered needs_human and still require alerting."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.stage == ContadoresLeadStage.NEEDS_HUMAN,
                    cls.needs_human_notified_at.is_(None),
                )
                .order_by(cls.updated_at, cls.created_at, cls.id)
                .limit(limit)
            )
            if funnel_id is not None:
                statement = statement.where(cls.funnel_id == ((funnel_id or "").strip() or "contadores"))
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_manual_attention_candidates(cls, *, funnel_ids: list[str]) -> list["ContadoresLead"]:
        """List manual-stage leads that can still require an operator reply."""
        clean_funnel_ids = [((item or "").strip() or "contadores") for item in funnel_ids]
        if not clean_funnel_ids:
            return []

        with Session(engine) as session:
            statement = select(cls).where(
                cls.stage == ContadoresLeadStage.NEEDS_HUMAN,
                cls.funnel_id.in_(clean_funnel_ids),
            )
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def upsert(
        cls,
        *,
        funnel_id: str = "contadores",
        external_lead_id: str,
        phone: str,
        full_name: str | None = None,
        email: str | None = None,
        platform: str | None = None,
        lead_status: str | None = None,
        tags: list[str] | None = None,
        sheet_created_time: datetime | None = None,
        reset_flow: bool = False,
    ) -> "ContadoresLead":
        """Create or update one lead from sheet ingestion."""
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            raise ValueError("phone is invalid")

        with Session(engine) as session:
            statement = select(cls).where(cls.external_lead_id == external_lead_id).limit(1)
            item = session.exec(statement).first()
            now = datetime.now(timezone.utc)
            if item is None:
                item = cls(
                    funnel_id=(funnel_id or "").strip() or "contadores",
                    external_lead_id=external_lead_id.strip(),
                    phone=phone.strip(),
                    normalized_phone=normalized_phone,
                    full_name=(full_name or "").strip() or None,
                    email=(normalize_email(email) or None) if email else None,
                    platform=(platform or "").strip() or None,
                    lead_status=(lead_status or "").strip() or None,
                    tags_json=serialize_contadores_tags(tags),
                    sheet_created_time=sheet_created_time,
                    stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
                    created_at=now,
                    updated_at=now,
                )
                cls.refresh_lifecycle_fields(item)
                session.add(item)
                session.commit()
                session.refresh(item)
                session.expunge(item)
                return item

            item.phone = phone.strip()
            item.funnel_id = (funnel_id or "").strip() or item.funnel_id or "contadores"
            item.normalized_phone = normalized_phone
            item.full_name = (full_name or "").strip() or None
            item.email = (normalize_email(email) or None) if email else None
            item.platform = (platform or "").strip() or None
            item.lead_status = (lead_status or "").strip() or None
            if tags is not None:
                item.tags_json = serialize_contadores_tags([*item.tags, *tags])
            item.sheet_created_time = sheet_created_time
            if reset_flow:
                item.stage = ContadoresLeadStage.AWAITING_INITIAL_REPLY
                item.last_classification_label = None
                item.last_classification_reason = None
                item.opener_sent_at = None
                item.first_reply_received_at = None
                item.loom_sent_at = None
                item.video_check_sent_at = None
                item.classification_completed_at = None
                item.calendly_sent_at = None
                item.meeting_scheduled_at = None
                item.booked_at = None
                item.closed_at = None
                item.stage_before_closed = None
                item.needs_human_notified_at = None
                item.manual_reply_handled_at = None
                item.last_inbound_at = None
                item.last_outbound_at = None
                item.archived_at = None
                item.calendly_tracking_token = uuid.uuid4().hex
            item.updated_at = now
            cls.refresh_lifecycle_fields(item)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def claim_conversation_processing(
        cls,
        *,
        lead_id: str,
        latest_inbound_id: int,
        latest_inbound_at: datetime,
        claimed_at: datetime,
        stale_after_seconds: int,
    ) -> bool:
        """Claim one lead conversation batch across processes."""
        stale_before = claimed_at - timedelta(seconds=max(1, int(stale_after_seconds)))
        with engine.begin() as connection:
            result = connection.exec_driver_sql(
                """
                UPDATE contadores_leads
                SET conversation_processing_started_at = ?,
                    conversation_processing_latest_inbound_id = ?,
                    updated_at = ?
                WHERE id = ?
                  AND (
                    classification_completed_at IS NULL
                    OR classification_completed_at < ?
                  )
                  AND (
                    conversation_processing_started_at IS NULL
                    OR conversation_processing_started_at <= ?
                  )
                """,
                (
                    claimed_at,
                    latest_inbound_id,
                    claimed_at,
                    lead_id,
                    latest_inbound_at,
                    stale_before,
                ),
            )
            return result.rowcount == 1

    @classmethod
    def clear_conversation_processing(
        cls,
        *,
        lead_id: str,
        latest_inbound_id: int | None = None,
    ) -> None:
        """Release one conversation-processing claim if it still belongs to this batch."""
        with engine.begin() as connection:
            if latest_inbound_id is None:
                connection.exec_driver_sql(
                    """
                    UPDATE contadores_leads
                    SET conversation_processing_started_at = NULL,
                        conversation_processing_latest_inbound_id = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (datetime.now(timezone.utc), lead_id),
                )
                return
            connection.exec_driver_sql(
                """
                UPDATE contadores_leads
                SET conversation_processing_started_at = NULL,
                    conversation_processing_latest_inbound_id = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND conversation_processing_latest_inbound_id = ?
                """,
                (datetime.now(timezone.utc), lead_id, latest_inbound_id),
            )

    @classmethod
    def update_codex_conversation_thread_id(
        cls,
        lead_id: str,
        *,
        thread_id: str | None,
    ) -> Optional["ContadoresLead"]:
        """Persist the Codex conversation thread used for one lead."""
        with Session(engine) as session:
            item = session.get(cls, lead_id)
            if item is None:
                return None
            item.codex_conversation_thread_id = (thread_id or "").strip() or None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def set_tags(cls, lead_id: str, *, tags: list[str]) -> Optional["ContadoresLead"]:
        """Replace the operator tags for one lead."""
        with Session(engine) as session:
            item = session.get(cls, lead_id)
            if item is None:
                return None
            item.tags_json = serialize_contadores_tags(tags)
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def set_full_name_if_missing(cls, lead_id: str, *, full_name: str | None) -> Optional["ContadoresLead"]:
        """Set the lead name only when it is currently empty."""
        clean_full_name = " ".join((full_name or "").split()).strip()
        if not clean_full_name:
            return cls.get_by_id(lead_id)

        with Session(engine) as session:
            item = session.get(cls, lead_id)
            if item is None:
                return None
            if item.full_name:
                session.expunge(item)
                return item
            item.full_name = clean_full_name
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def move_to_funnel(
        cls,
        lead_id: str,
        *,
        funnel_id: str,
        stage: ContadoresLeadStage | str,
    ) -> Optional["ContadoresLead"]:
        """Route one lead to another funnel and operator-selected handoff point."""
        with Session(engine) as session:
            item = session.get(cls, lead_id)
            if item is None:
                return None
            item.funnel_id = (funnel_id or "").strip() or "contadores"
            item.stage = cls.normalize_stage(stage)
            item.automation_paused = item.stage == ContadoresLeadStage.NEEDS_HUMAN
            item.automation_paused_reason = "manual_funnel_move" if item.automation_paused else None
            item.updated_at = datetime.now(timezone.utc)
            cls.refresh_lifecycle_fields(item)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_flow_state(
        cls,
        lead_id: str,
        *,
        stage: ContadoresLeadStage | str | None = None,
        last_classification_label: str | None = None,
        last_classification_reason: str | None = None,
        opener_sent_at: datetime | None = None,
        first_reply_received_at: datetime | None = None,
        loom_sent_at: datetime | None = None,
        video_check_sent_at: datetime | None = None,
        classification_completed_at: datetime | None = None,
        calendly_sent_at: datetime | None = None,
        meeting_scheduled_at: datetime | None = None,
        booked_at: datetime | None = None,
        closed_at: datetime | None = None,
        clear_closed_at: bool = False,
        stage_before_closed: ContadoresLeadStage | str | None = None,
        clear_stage_before_closed: bool = False,
        needs_human_notified_at: datetime | None = None,
        clear_needs_human_notified_at: bool = False,
        manual_reply_handled_at: datetime | None = None,
        clear_manual_reply_handled_at: bool = False,
        last_inbound_at: datetime | None = None,
        last_outbound_at: datetime | None = None,
        archived_at: datetime | None = None,
        clear_archived_at: bool = False,
        automation_paused: bool | None = None,
        automation_paused_reason: str | None = None,
    ) -> Optional["ContadoresLead"]:
        """Update lead flow timestamps and stage fields."""
        with Session(engine) as session:
            item = session.get(cls, lead_id)
            if item is None:
                return None
            normalized_stage = cls.normalize_stage(stage) if stage is not None else None
            if stage is not None:
                item.stage = normalized_stage or cls.normalize_stage(stage)
            if last_classification_label is not None:
                item.last_classification_label = (last_classification_label or "").strip() or None
            if last_classification_reason is not None:
                item.last_classification_reason = (last_classification_reason or "").strip() or None
            if opener_sent_at is not None:
                item.opener_sent_at = opener_sent_at
            if first_reply_received_at is not None:
                item.first_reply_received_at = first_reply_received_at
            if loom_sent_at is not None:
                item.loom_sent_at = loom_sent_at
            if video_check_sent_at is not None:
                item.video_check_sent_at = video_check_sent_at
            if classification_completed_at is not None:
                item.classification_completed_at = classification_completed_at
            if calendly_sent_at is not None:
                item.calendly_sent_at = calendly_sent_at
            if meeting_scheduled_at is not None:
                item.meeting_scheduled_at = meeting_scheduled_at
            if booked_at is not None:
                item.booked_at = booked_at
            if normalized_stage is not None and normalized_stage != ContadoresLeadStage.CLOSED:
                item.closed_at = None
                item.stage_before_closed = None
            if closed_at is not None:
                item.closed_at = closed_at
            elif clear_closed_at:
                item.closed_at = None
            if stage_before_closed is not None:
                item.stage_before_closed = cls.normalize_stage(stage_before_closed)
            elif clear_stage_before_closed:
                item.stage_before_closed = None
            if needs_human_notified_at is not None:
                item.needs_human_notified_at = needs_human_notified_at
            elif clear_needs_human_notified_at:
                item.needs_human_notified_at = None
            if manual_reply_handled_at is not None:
                item.manual_reply_handled_at = manual_reply_handled_at
            elif clear_manual_reply_handled_at:
                item.manual_reply_handled_at = None
            if last_inbound_at is not None:
                item.last_inbound_at = last_inbound_at
            if last_outbound_at is not None:
                item.last_outbound_at = last_outbound_at
            if archived_at is not None:
                item.archived_at = archived_at
            elif clear_archived_at:
                item.archived_at = None
            if automation_paused is not None:
                item.automation_paused = automation_paused
                if automation_paused is False:
                    item.automation_paused_reason = None
            if automation_paused_reason is not None:
                item.automation_paused_reason = (automation_paused_reason or "").strip() or None
            item.updated_at = datetime.now(timezone.utc)
            cls.refresh_lifecycle_fields(item)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def mark_converted(
        cls,
        lead_id: str,
        *,
        converted_at: datetime | None = None,
        automation_paused: bool | None = None,
        automation_paused_reason: str | None = None,
    ) -> Optional["ContadoresLead"]:
        """Record a completed conversion without making Booked the canonical write state."""
        flow_updates: dict[str, Any] = {
            "booked_at": converted_at or datetime.now(timezone.utc),
        }
        if automation_paused is not None:
            flow_updates["automation_paused"] = automation_paused
        if automation_paused_reason is not None:
            flow_updates["automation_paused_reason"] = automation_paused_reason
        return cls.update_flow_state(lead_id, **flow_updates)


class ContadoresStrategyAssignment(SQLModel, table=True):
    """One stable strategy assignment for a Contadores lead step."""

    __tablename__ = "contadores_strategy_assignments"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
    step: str = Field(index=True)
    strategy_id: str = Field(index=True)
    strategy_label: str = Field(default="")
    assigned_by: str = Field(default="system", index=True)
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        lead_id: str,
        step: str,
        strategy_id: str,
        strategy_label: str,
        assigned_by: str = "system",
        assigned_at: datetime | None = None,
    ) -> "ContadoresStrategyAssignment":
        """Persist one lead strategy assignment."""
        with Session(engine) as session:
            now = assigned_at or datetime.now(timezone.utc)
            row = cls(
                lead_id=lead_id,
                step=(step or "").strip(),
                strategy_id=(strategy_id or "").strip(),
                strategy_label=(strategy_label or "").strip(),
                assigned_by=(assigned_by or "").strip() or "system",
                assigned_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_all(cls, *, funnel_id: str | None = None) -> list["ContadoresStrategyAssignment"]:
        """List all persisted assignments in assignment order."""
        with Session(engine) as session:
            statement = select(cls).join(ContadoresLead, ContadoresLead.id == cls.lead_id)
            if funnel_id is not None:
                statement = statement.where(ContadoresLead.funnel_id == ((funnel_id or "").strip() or "contadores"))
            statement = statement.order_by(cls.assigned_at, cls.id)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows


class ContadoresMessage(SQLModel, table=True):
    """Stored WhatsApp messages for Contadores leads."""

    __tablename__ = "contadores_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
    from_me: bool
    text: str
    delivery_status: MessageDeliveryStatus = Field(default=MessageDeliveryStatus.DELIVERED, index=True)
    external_id: str | None = Field(default=None, index=True)
    delivery_attempts: int = Field(default=0, index=True)
    last_delivery_error: str | None = Field(default=None)
    last_delivery_error_at: datetime | None = Field(default=None)
    delivery_error_acknowledged_at: datetime | None = Field(default=None, index=True)
    dispatch_after: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    sequence_step: str | None = Field(default=None, index=True)
    strategy_assignment_id: int | None = Field(
        default=None,
        foreign_key="contadores_strategy_assignments.id",
        index=True,
    )
    strategy_step: str | None = Field(default=None, index=True)
    strategy_id: str | None = Field(default=None, index=True)
    strategy_label: str | None = Field(default=None)
    media_type: str | None = Field(default=None, index=True)
    media_path: str | None = Field(default=None)
    media_caption: str | None = Field(default=None)
    media_mime_type: str | None = Field(default=None)
    media_filename: str | None = Field(default=None)
    media_sha256: str | None = Field(default=None)
    media_id: str | None = Field(default=None, index=True)
    whatsapp_template_name: str | None = Field(default=None, index=True)
    whatsapp_template_language: str | None = Field(default=None)
    whatsapp_template_body_params_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @property
    def whatsapp_template_body_params(self) -> list[str]:
        """Return positional WhatsApp template params stored for this row."""
        try:
            payload = json.loads(self.whatsapp_template_body_params_json or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [str(item) for item in payload]

    @classmethod
    def add(
        cls,
        *,
        lead_id: str,
        from_me: bool,
        text: str,
        external_id: str | None = None,
        delivery_status: MessageDeliveryStatus | str | None = None,
        dispatch_after: datetime | None = None,
        sequence_step: str | None = None,
        strategy_assignment_id: int | None = None,
        strategy_step: str | None = None,
        strategy_id: str | None = None,
        strategy_label: str | None = None,
        media_type: str | None = None,
        media_path: str | None = None,
        media_caption: str | None = None,
        media_mime_type: str | None = None,
        media_filename: str | None = None,
        media_sha256: str | None = None,
        media_id: str | None = None,
        whatsapp_template_name: str | None = None,
        whatsapp_template_language: str | None = None,
        whatsapp_template_body_params: list[str] | tuple[str, ...] | None = None,
        created_at: datetime | None = None,
    ) -> "ContadoresMessage":
        """Persist one lead message and keep lead activity timestamps updated."""
        with Session(engine) as session:
            now = created_at or datetime.now(timezone.utc)
            effective_dispatch_after = dispatch_after or now
            if effective_dispatch_after.tzinfo is None:
                effective_dispatch_after = effective_dispatch_after.replace(tzinfo=timezone.utc)
            row = cls(
                lead_id=lead_id,
                from_me=from_me,
                text=text.strip(),
                delivery_status=Message.normalize_delivery_status(delivery_status, from_me=from_me),
                external_id=(external_id or "").strip() or None,
                dispatch_after=effective_dispatch_after,
                sequence_step=(sequence_step or "").strip() or None,
                strategy_assignment_id=strategy_assignment_id,
                strategy_step=(strategy_step or "").strip() or None,
                strategy_id=(strategy_id or "").strip() or None,
                strategy_label=(strategy_label or "").strip() or None,
                media_type=(media_type or "").strip() or None,
                media_path=(media_path or "").strip() or None,
                media_caption=(media_caption or "").strip() or None,
                media_mime_type=(media_mime_type or "").strip() or None,
                media_filename=(media_filename or "").strip() or None,
                media_sha256=(media_sha256 or "").strip() or None,
                media_id=(media_id or "").strip() or None,
                whatsapp_template_name=(whatsapp_template_name or "").strip() or None,
                whatsapp_template_language=(whatsapp_template_language or "").strip() or None,
                whatsapp_template_body_params_json=json.dumps(
                    [str(item) for item in (whatsapp_template_body_params or [])],
                    ensure_ascii=True,
                ),
                created_at=now,
            )
            session.add(row)
            lead = session.get(ContadoresLead, lead_id)
            if lead:
                if from_me:
                    lead.last_outbound_at = now
                else:
                    lead.last_inbound_at = now
                    if lead.first_reply_received_at is None:
                        lead.first_reply_received_at = now
                lead.updated_at = now
                ContadoresLead.refresh_lifecycle_fields(lead)
                session.add(lead)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_by_lead(cls, lead_id: str) -> list["ContadoresMessage"]:
        """List messages for one lead in chronological order."""
        with Session(engine) as session:
            statement = select(cls).where(cls.lead_id == lead_id).order_by(cls.created_at, cls.id)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def get_by_id(cls, message_id: int) -> Optional["ContadoresMessage"]:
        """Get one Contadores message by ID."""
        with Session(engine) as session:
            row = session.get(cls, message_id)
            if row:
                session.expunge(row)
            return row

    @classmethod
    def has_inbound_for_lead(cls, lead_id: str) -> bool:
        """Return True when the lead already replied at least once."""
        with Session(engine) as session:
            statement = (
                select(cls.id)
                .where(
                    cls.lead_id == lead_id,
                    cls.from_me.is_(False),
                )
                .limit(1)
            )
            return session.exec(statement).first() is not None

    @classmethod
    def has_outbound_sequence_step(
        cls,
        lead_id: str,
        *,
        sequence_step: str,
        created_after: datetime | None = None,
    ) -> bool:
        """Return True when one outbound step already exists for this lead."""
        clean_step = (sequence_step or "").strip()
        if not clean_step:
            return False
        with Session(engine) as session:
            statement = (
                select(cls.id)
                .where(
                    cls.lead_id == lead_id,
                    cls.from_me.is_(True),
                    cls.sequence_step == clean_step,
                )
                .limit(1)
            )
            if created_after is not None:
                statement = statement.where(cls.created_at >= created_after)
            return session.exec(statement).first() is not None

    @classmethod
    def get_latest_inbound_message(cls, lead_id: str) -> Optional["ContadoresMessage"]:
        """Return latest inbound lead message."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.lead_id == lead_id,
                    cls.from_me.is_(False),
                )
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(1)
            )
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def get_latest_outbound_message(cls, lead_id: str) -> Optional["ContadoresMessage"]:
        """Return latest outbound lead message."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.lead_id == lead_id,
                    cls.from_me.is_(True),
                )
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(1)
            )
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def list_by_external_id(
        cls,
        external_id: str,
        *,
        from_me: bool | None = None,
    ) -> list["ContadoresMessage"]:
        """List messages by provider external id."""
        clean_external_id = (external_id or "").strip()
        if not clean_external_id:
            return []
        with Session(engine) as session:
            statement = select(cls).where(cls.external_id == clean_external_id)
            if from_me is not None:
                statement = statement.where(cls.from_me.is_(from_me))
            statement = statement.order_by(cls.created_at.desc(), cls.id.desc())
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def count_delivery_issues_by_lead(cls, lead_id: str) -> int:
        """Count outbound messages that still need operator attention."""
        with Session(engine) as session:
            statement = (
                select(cls.id)
                .where(
                    cls.lead_id == lead_id,
                    cls.from_me.is_(True),
                    cls.delivery_status == MessageDeliveryStatus.FAILED,
                    cls.delivery_error_acknowledged_at.is_(None),
                )
            )
            return len(list(session.exec(statement).all()))

    @classmethod
    def latest_delivery_issue_for_lead(cls, lead_id: str) -> str | None:
        """Return the newest stored delivery error for one lead."""
        with Session(engine) as session:
            statement = (
                select(cls.last_delivery_error)
                .where(
                    cls.lead_id == lead_id,
                    cls.from_me.is_(True),
                    cls.delivery_status == MessageDeliveryStatus.FAILED,
                    cls.delivery_error_acknowledged_at.is_(None),
                    cls.last_delivery_error.is_not(None),
                )
                .order_by(cls.last_delivery_error_at.desc(), cls.id.desc())
                .limit(1)
            )
            return session.exec(statement).first()

    @classmethod
    def list_pending_delivery(cls, *, limit: int = 100) -> list["ContadoresMessage"]:
        """List every pending outbound step that is due for dispatch."""
        now_utc = datetime.now(timezone.utc)
        with Session(engine) as session:
            statement = (
                select(cls)
                .join(ContadoresLead, ContadoresLead.id == cls.lead_id)
                .where(
                    cls.from_me.is_(True),
                    cls.delivery_status == MessageDeliveryStatus.UNDELIVERED,
                    cls.dispatch_after <= now_utc,
                    ContadoresLead.stage != ContadoresLeadStage.ARCHIVED,
                    ContadoresLead.archived_at.is_(None),
                    (
                        (
                            (ContadoresLead.stage != ContadoresLeadStage.BOOKED)
                            & ContadoresLead.booked_at.is_(None)
                        )
                        | cls.sequence_step.in_(CONTADORES_CONVERTED_LEAD_DELIVERY_SEQUENCE_STEPS)
                    ),
                    (
                        (ContadoresLead.stage != ContadoresLeadStage.CLOSED)
                        & ContadoresLead.closed_at.is_(None)
                    )
                    | cls.sequence_step.in_(CONTADORES_CLOSED_LEAD_DELIVERY_SEQUENCE_STEPS),
                )
                .order_by(cls.dispatch_after, cls.id)
                .limit(limit)
            )
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def update_text(
        cls,
        *,
        message_id: int,
        text: str,
    ) -> Optional["ContadoresMessage"]:
        """Update one message text."""
        with Session(engine) as session:
            row = session.get(cls, message_id)
            if row is None:
                return None
            row.text = text.strip()
            session.add(row)
            lead = session.get(ContadoresLead, row.lead_id)
            if lead:
                lead.updated_at = datetime.now(timezone.utc)
                session.add(lead)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def update_delivery_status(
        cls,
        *,
        message_id: int,
        delivery_status: MessageDeliveryStatus | str,
        external_id: str | None = None,
        delivery_attempts: int | None = None,
        last_delivery_error: str | None = None,
        clear_delivery_error: bool = False,
        dispatch_after: datetime | None = None,
    ) -> Optional["ContadoresMessage"]:
        """Update one outbound message delivery status."""
        with Session(engine) as session:
            row = session.get(cls, message_id)
            if row is None:
                return None
            row.delivery_status = Message.normalize_delivery_status(
                delivery_status,
                from_me=row.from_me,
            )
            if external_id is not None:
                row.external_id = (external_id or "").strip() or None
            if delivery_attempts is not None:
                row.delivery_attempts = max(0, int(delivery_attempts))
            if dispatch_after is not None:
                row.dispatch_after = dispatch_after
            if clear_delivery_error:
                row.last_delivery_error = None
                row.last_delivery_error_at = None
                row.delivery_error_acknowledged_at = None
            elif last_delivery_error is not None:
                row.last_delivery_error = " ".join(str(last_delivery_error).split()).strip()[:2000] or None
                row.last_delivery_error_at = datetime.now(timezone.utc) if row.last_delivery_error else None
                row.delivery_error_acknowledged_at = None
            session.add(row)
            lead = session.get(ContadoresLead, row.lead_id)
            if lead:
                lead.updated_at = datetime.now(timezone.utc)
                session.add(lead)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def record_delivery_failure(
        cls,
        *,
        message_id: int,
        error: str,
        max_attempts: int = 3,
        retry_delay_seconds: int = 60,
    ) -> Optional["ContadoresMessage"]:
        """Store a failed send attempt and requeue until the retry budget is spent."""
        with Session(engine) as session:
            row = session.get(cls, message_id)
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            attempts = max(0, int(row.delivery_attempts or 0)) + 1
            row.delivery_attempts = attempts
            row.last_delivery_error = " ".join(str(error).split()).strip()[:2000] or "unknown delivery error"
            row.last_delivery_error_at = now
            row.delivery_error_acknowledged_at = None
            if attempts < max_attempts:
                row.delivery_status = MessageDeliveryStatus.UNDELIVERED
                row.dispatch_after = now + timedelta(seconds=max(0, retry_delay_seconds))
            else:
                row.delivery_status = MessageDeliveryStatus.FAILED
            session.add(row)
            lead = session.get(ContadoresLead, row.lead_id)
            if lead:
                lead.updated_at = now
                session.add(lead)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def acknowledge_delivery_error(cls, *, message_id: int) -> Optional["ContadoresMessage"]:
        """Mark one failed outbound delivery error as seen by the operator."""
        with Session(engine) as session:
            row = session.get(cls, message_id)
            if row is None:
                return None
            if row.from_me and row.delivery_status == MessageDeliveryStatus.FAILED:
                now = datetime.now(timezone.utc)
                row.delivery_error_acknowledged_at = now
                session.add(row)
                lead = session.get(ContadoresLead, row.lead_id)
                if lead:
                    lead.updated_at = now
                    session.add(lead)
                session.commit()
                session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def requeue_failed_delivery(
        cls,
        *,
        message_id: int,
        reset_attempts: bool = True,
    ) -> Optional["ContadoresMessage"]:
        """Put one failed outbound message back into the pending delivery queue."""
        with Session(engine) as session:
            row = session.get(cls, message_id)
            if row is None:
                return None
            row.delivery_status = MessageDeliveryStatus.UNDELIVERED
            row.dispatch_after = datetime.now(timezone.utc)
            if reset_attempts:
                row.delivery_attempts = 0
            session.add(row)
            lead = session.get(ContadoresLead, row.lead_id)
            if lead:
                lead.updated_at = datetime.now(timezone.utc)
                session.add(lead)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row


CLIENT_LEAD_DEFAULT_TEMPLATE_NAME = "konecta_client_lead_alert_es_v2"
CLIENT_LEAD_CONTEXT_TEMPLATE_NAME = "konecta_client_lead_alert_context_es_v1"
CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE = "es"
CLIENT_LEAD_DEFAULT_COLUMN_MAPPING = {
    "source_id": "id",
    "created_time": "created_time",
    "full_name": "full_name",
    "phone_number": "phone_number",
    "email": "email",
}


def normalize_client_lead_column_mapping(value: Any) -> dict[str, str]:
    """Normalize operator-provided column names for client lead sheets."""
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except json.JSONDecodeError:
            value = {}
    if not isinstance(value, dict):
        value = {}

    mapping: dict[str, str] = {}
    for key, default_value in CLIENT_LEAD_DEFAULT_COLUMN_MAPPING.items():
        raw_value = value.get(key, default_value)
        clean_value = " ".join(str(raw_value or "").split()).strip()
        if clean_value:
            mapping[key] = clean_value
    for raw_key, raw_value in value.items():
        key = " ".join(str(raw_key or "").split()).strip()
        if not key or key in mapping:
            continue
        clean_value = " ".join(str(raw_value or "").split()).strip()
        if clean_value:
            mapping[key] = clean_value
    return mapping


def client_lead_default_column_mapping_json() -> str:
    """Return the JSON default for client lead column mapping."""
    return json.dumps(CLIENT_LEAD_DEFAULT_COLUMN_MAPPING, ensure_ascii=True)


def normalize_client_lead_context_field_mapping(value: Any) -> dict[str, str]:
    """Normalize operator-provided context fields for Delivery alerts."""
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except json.JSONDecodeError:
            value = {}
    if isinstance(value, list):
        value = {str(item): str(item) for item in value}
    if not isinstance(value, dict):
        return {}

    mapping: dict[str, str] = {}
    for raw_label, raw_column in value.items():
        label = " ".join(str(raw_label or "").split()).strip()
        column = " ".join(str(raw_column or "").split()).strip()
        if label and column:
            mapping[label] = column
    return mapping


def client_lead_default_context_field_mapping_json() -> str:
    """Return the JSON default for Delivery context field mapping."""
    return "{}"


class ClientLeadSource(SQLModel, table=True):
    """One client-owned lead source that polls a Google Sheet and notifies a recipient."""

    __tablename__ = "client_lead_sources"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    label: str = Field(index=True)
    enabled: bool = Field(default=True, index=True)
    sheet_url: str = Field(default="")
    sheet_gid: str | None = Field(default=None)
    sheet_tab_name: str | None = Field(default=None)
    meta_page_id: str = Field(default="")
    meta_lead_form_id: str = Field(default="", index=True)
    sheet_poll_seconds: int = Field(default=10)
    recipient_name: str | None = Field(default=None)
    recipient_phone: str = Field(default="")
    normalized_recipient_phone: str = Field(default="", index=True)
    template_name: str = Field(default=CLIENT_LEAD_DEFAULT_TEMPLATE_NAME)
    template_language: str = Field(default=CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE)
    prefilled_reply_text: str = Field(default="")
    column_mapping_json: str = Field(default_factory=client_lead_default_column_mapping_json)
    context_field_mapping_json: str = Field(default_factory=client_lead_default_context_field_mapping_json)
    last_sync_at: datetime | None = Field(default=None, index=True)
    last_sync_status: str | None = Field(default=None)
    last_sync_note: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def column_mapping(self) -> dict[str, str]:
        """Return normalized column mapping."""
        return normalize_client_lead_column_mapping(self.column_mapping_json)

    @property
    def context_field_mapping(self) -> dict[str, str]:
        """Return normalized alert context field mapping."""
        return normalize_client_lead_context_field_mapping(self.context_field_mapping_json)

    @classmethod
    def normalize_enabled(cls, enabled: bool | None) -> bool:
        """Normalize optional enabled flags."""
        return True if enabled is None else bool(enabled)

    @classmethod
    def get_by_id(cls, source_id: str) -> Optional["ClientLeadSource"]:
        """Get one source by id."""
        with Session(engine) as session:
            item = session.get(cls, source_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_all(cls) -> list["ClientLeadSource"]:
        """List every client lead source."""
        with Session(engine) as session:
            statement = select(cls).order_by(cls.label, cls.id)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_enabled(cls) -> list["ClientLeadSource"]:
        """List enabled sources for bot polling."""
        with Session(engine) as session:
            statement = select(cls).where(cls.enabled.is_(True)).order_by(cls.label, cls.id)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def get_by_meta_lead_form_id(cls, form_id: str) -> Optional["ClientLeadSource"]:
        """Return the enabled Delivery source bound to one Meta instant form."""
        clean_form_id = " ".join(str(form_id or "").split()).strip()
        if not clean_form_id:
            return None
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.enabled.is_(True))
                .where(cls.meta_lead_form_id == clean_form_id)
                .order_by(cls.label, cls.id)
            )
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def upsert(
        cls,
        *,
        source_id: str | None = None,
        label: str,
        enabled: bool | None = True,
        sheet_url: str,
        sheet_gid: str | None = None,
        sheet_tab_name: str | None = None,
        meta_page_id: str | None = None,
        meta_lead_form_id: str | None = None,
        sheet_poll_seconds: int = 10,
        recipient_name: str | None = None,
        recipient_phone: str,
        template_name: str | None = None,
        template_language: str | None = None,
        prefilled_reply_text: str | None = None,
        column_mapping: dict[str, str] | None = None,
        context_field_mapping: dict[str, str] | list[str] | None = None,
    ) -> "ClientLeadSource":
        """Create or update one client lead source."""
        clean_label = " ".join((label or "").split()).strip()
        if not clean_label:
            raise ValueError("label is required")
        clean_sheet_url = (sheet_url or "").strip()
        clean_recipient_phone = (recipient_phone or "").strip()
        normalized_recipient_phone = normalize_phone(clean_recipient_phone)
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            item = session.get(cls, source_id) if source_id else None
            if item is None:
                item = cls(id=source_id or str(uuid.uuid4()), label=clean_label, created_at=now)

            item.label = clean_label
            item.enabled = cls.normalize_enabled(enabled)
            item.sheet_url = clean_sheet_url
            item.sheet_gid = (sheet_gid or "").strip() or None
            item.sheet_tab_name = " ".join((sheet_tab_name or "").split()).strip() or None
            if meta_page_id is not None:
                item.meta_page_id = " ".join(meta_page_id.split()).strip()
            if meta_lead_form_id is not None:
                item.meta_lead_form_id = " ".join(meta_lead_form_id.split()).strip()
            item.sheet_poll_seconds = max(5, int(sheet_poll_seconds or 10))
            item.recipient_name = " ".join((recipient_name or "").split()).strip() or None
            item.recipient_phone = clean_recipient_phone
            item.normalized_recipient_phone = normalized_recipient_phone
            clean_context_mapping = normalize_client_lead_context_field_mapping(
                context_field_mapping if context_field_mapping is not None else item.context_field_mapping
            )
            clean_template_name = (template_name or CLIENT_LEAD_DEFAULT_TEMPLATE_NAME).strip()
            if clean_context_mapping and clean_template_name == CLIENT_LEAD_DEFAULT_TEMPLATE_NAME:
                clean_template_name = CLIENT_LEAD_CONTEXT_TEMPLATE_NAME
            if not clean_context_mapping and clean_template_name == CLIENT_LEAD_CONTEXT_TEMPLATE_NAME:
                clean_template_name = CLIENT_LEAD_DEFAULT_TEMPLATE_NAME
            item.template_name = clean_template_name
            item.template_language = (template_language or CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE).strip() or "es"
            item.prefilled_reply_text = " ".join((prefilled_reply_text or "").split()).strip()
            item.column_mapping_json = json.dumps(
                normalize_client_lead_column_mapping(column_mapping or item.column_mapping),
                ensure_ascii=True,
            )
            item.context_field_mapping_json = json.dumps(clean_context_mapping, ensure_ascii=False)
            item.updated_at = now
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def delete(cls, source_id: str) -> bool:
        """Delete one source and its imported client leads."""
        with Session(engine) as session:
            item = session.get(cls, source_id)
            if item is None:
                return False
            deliveries = session.exec(select(ClientLeadDelivery).where(ClientLeadDelivery.source_id == source_id)).all()
            for delivery in deliveries:
                session.delete(delivery)
            session.delete(item)
            session.commit()
            return True

    @classmethod
    def mark_sync(
        cls,
        source_id: str,
        *,
        status: str,
        note: str | None = None,
        synced_at: datetime | None = None,
    ) -> Optional["ClientLeadSource"]:
        """Persist the latest sync result for one source."""
        with Session(engine) as session:
            item = session.get(cls, source_id)
            if item is None:
                return None
            now = synced_at or datetime.now(timezone.utc)
            item.last_sync_at = now
            item.last_sync_status = (status or "").strip() or None
            item.last_sync_note = " ".join(str(note or "").split()).strip()[:1000] or None
            item.updated_at = now
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item


class ClientLeadDelivery(SQLModel, table=True):
    """One imported lead row from a client's campaign sheet."""

    __tablename__ = "client_lead_deliveries"
    __table_args__ = (
        UniqueConstraint("source_id", "source_row_key", name="uq_client_lead_deliveries_source_row_key"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    source_id: str = Field(foreign_key="client_lead_sources.id", index=True)
    source_row_key: str = Field(index=True)
    row_number: int = Field(default=0, index=True)
    raw_row_json: str = Field(default="{}")
    created_time: datetime | None = Field(default=None, index=True)
    full_name: str | None = Field(default=None, index=True)
    phone_number: str = Field(default="")
    normalized_phone: str = Field(default="", index=True)
    email: str | None = Field(default=None, index=True)
    wa_link: str = Field(default="")
    notification_text: str = Field(default="")
    sent_text: str = Field(default="")
    delivery_status: ClientLeadDeliveryStatus = Field(default=ClientLeadDeliveryStatus.PENDING, index=True)
    external_id: str | None = Field(default=None, index=True)
    delivery_attempts: int = Field(default=0, index=True)
    last_delivery_error: str | None = Field(default=None)
    last_delivery_error_at: datetime | None = Field(default=None)
    block_reason: str | None = Field(default=None)
    dispatch_after: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    sent_at: datetime | None = Field(default=None, index=True)
    delivered_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @property
    def raw_row(self) -> dict[str, str]:
        """Return stored sheet row values."""
        try:
            payload = json.loads(self.raw_row_json or "{}")
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    @classmethod
    def normalize_status(
        cls,
        status: ClientLeadDeliveryStatus | str | None,
    ) -> ClientLeadDeliveryStatus:
        """Normalize one delivery status."""
        if isinstance(status, ClientLeadDeliveryStatus):
            return status
        value = (status or "").strip().lower()
        for candidate in ClientLeadDeliveryStatus:
            if candidate.value == value:
                return candidate
        return ClientLeadDeliveryStatus.PENDING

    @classmethod
    def get_by_id(cls, delivery_id: str) -> Optional["ClientLeadDelivery"]:
        """Get one imported client lead row by id."""
        with Session(engine) as session:
            item = session.get(cls, delivery_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_by_source(
        cls,
        source_id: str,
        *,
        limit: int = 500,
    ) -> list["ClientLeadDelivery"]:
        """List imported lead rows for one source."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.source_id == source_id)
                .order_by(cls.row_number.desc(), cls.created_at.desc(), cls.id.desc())
                .limit(limit)
            )
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_pending_notification(cls, *, limit: int = 100) -> list["ClientLeadDelivery"]:
        """List pending client lead notifications ready for WhatsApp dispatch."""
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            statement = (
                select(cls)
                .join(ClientLeadSource, ClientLeadSource.id == cls.source_id)
                .where(
                    ClientLeadSource.enabled.is_(True),
                    cls.delivery_status == ClientLeadDeliveryStatus.PENDING,
                    cls.dispatch_after <= now,
                )
                .order_by(cls.dispatch_after, cls.created_at, cls.id)
                .limit(limit)
            )
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def count_by_status_for_sources(cls) -> dict[str, dict[str, int]]:
        """Return per-source delivery status counts."""
        with Session(engine) as session:
            rows = session.exec(select(cls.source_id, cls.delivery_status)).all()
        counts: dict[str, dict[str, int]] = {}
        for source_id, status in rows:
            by_status = counts.setdefault(source_id, {})
            status_key = str(status.value if isinstance(status, ClientLeadDeliveryStatus) else status)
            by_status[status_key] = by_status.get(status_key, 0) + 1
            by_status["total"] = by_status.get("total", 0) + 1
        return counts

    @classmethod
    def upsert_from_sheet_row(
        cls,
        *,
        source: ClientLeadSource,
        source_row_key: str,
        row_number: int,
        raw_row: dict[str, str],
        full_name: str | None,
        phone_number: str,
        email: str | None,
        created_time: datetime | None,
        wa_link: str,
        notification_text: str,
        block_reason: str | None = None,
    ) -> tuple["ClientLeadDelivery", bool]:
        """Create or update one imported sheet row without double-notifying."""
        normalized_phone = normalize_phone(phone_number)
        now = datetime.now(timezone.utc)
        next_status = (
            ClientLeadDeliveryStatus.BLOCKED
            if block_reason
            else ClientLeadDeliveryStatus.PENDING
        )

        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.source_id == source.id, cls.source_row_key == source_row_key)
                .limit(1)
            )
            item = session.exec(statement).first()
            created = item is None
            if item is None:
                item = cls(
                    source_id=source.id,
                    source_row_key=source_row_key,
                    delivery_status=next_status,
                    dispatch_after=now,
                    created_at=now,
                )

            item.row_number = row_number
            item.raw_row_json = json.dumps(raw_row, ensure_ascii=False)
            item.created_time = created_time
            item.full_name = " ".join((full_name or "").split()).strip() or None
            item.phone_number = (phone_number or "").strip()
            item.normalized_phone = normalized_phone
            item.email = (normalize_email(email) or None) if email else None
            item.wa_link = (wa_link or "").strip()
            item.notification_text = (notification_text or "").strip()
            item.block_reason = (block_reason or "").strip() or None
            item.updated_at = now

            if block_reason:
                item.delivery_status = ClientLeadDeliveryStatus.BLOCKED
            elif item.delivery_status in {
                ClientLeadDeliveryStatus.BLOCKED,
                ClientLeadDeliveryStatus.SKIPPED,
            }:
                item.delivery_status = ClientLeadDeliveryStatus.PENDING
                item.dispatch_after = now
                item.delivery_attempts = 0
                item.last_delivery_error = None
                item.last_delivery_error_at = None

            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item, created

    @classmethod
    def update_delivery_status(
        cls,
        *,
        delivery_id: str,
        delivery_status: ClientLeadDeliveryStatus | str,
        external_id: str | None = None,
        sent_text: str | None = None,
        last_delivery_error: str | None = None,
        clear_delivery_error: bool = False,
    ) -> Optional["ClientLeadDelivery"]:
        """Update one client lead notification delivery status."""
        with Session(engine) as session:
            row = session.get(cls, delivery_id)
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            row.delivery_status = cls.normalize_status(delivery_status)
            if external_id is not None:
                row.external_id = (external_id or "").strip() or None
            if row.delivery_status == ClientLeadDeliveryStatus.SENT:
                row.sent_at = now
            if row.delivery_status in {
                ClientLeadDeliveryStatus.SENT,
                ClientLeadDeliveryStatus.DELIVERED,
            }:
                clean_sent_text = " ".join(str(sent_text or row.notification_text or "").split()).strip()
                row.sent_text = clean_sent_text or row.sent_text or row.notification_text
            if row.delivery_status == ClientLeadDeliveryStatus.DELIVERED:
                row.delivered_at = now
            if clear_delivery_error:
                row.last_delivery_error = None
                row.last_delivery_error_at = None
            elif last_delivery_error is not None:
                row.last_delivery_error = " ".join(str(last_delivery_error).split()).strip()[:2000] or None
                row.last_delivery_error_at = now if row.last_delivery_error else None
            row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def update_delivery_status_by_external_id(
        cls,
        *,
        external_id: str,
        delivery_status: ClientLeadDeliveryStatus | str,
        last_delivery_error: str | None = None,
    ) -> Optional["ClientLeadDelivery"]:
        """Update a client lead notification by provider message id."""
        clean_external_id = (external_id or "").strip()
        if not clean_external_id:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.external_id == clean_external_id).limit(1)
            row = session.exec(statement).first()
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            row.delivery_status = cls.normalize_status(delivery_status)
            if row.delivery_status == ClientLeadDeliveryStatus.DELIVERED:
                row.delivered_at = now
            if last_delivery_error is not None:
                row.last_delivery_error = " ".join(str(last_delivery_error).split()).strip()[:2000] or None
                row.last_delivery_error_at = now if row.last_delivery_error else None
            row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def record_delivery_failure(
        cls,
        *,
        delivery_id: str,
        error: str,
        max_attempts: int = 3,
        retry_delay_seconds: int = 60,
    ) -> Optional["ClientLeadDelivery"]:
        """Store a failed notification attempt and retry until the budget is spent."""
        with Session(engine) as session:
            row = session.get(cls, delivery_id)
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            attempts = max(0, int(row.delivery_attempts or 0)) + 1
            row.delivery_attempts = attempts
            row.last_delivery_error = " ".join(str(error).split()).strip()[:2000] or "unknown delivery error"
            row.last_delivery_error_at = now
            if attempts < max_attempts:
                row.delivery_status = ClientLeadDeliveryStatus.PENDING
                row.dispatch_after = now + timedelta(seconds=max(0, retry_delay_seconds))
            else:
                row.delivery_status = ClientLeadDeliveryStatus.FAILED
            row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def requeue_failed(cls, delivery_id: str, *, reset_attempts: bool = True) -> Optional["ClientLeadDelivery"]:
        """Requeue one failed client lead notification."""
        with Session(engine) as session:
            row = session.get(cls, delivery_id)
            if row is None:
                return None
            row.delivery_status = ClientLeadDeliveryStatus.PENDING
            row.dispatch_after = datetime.now(timezone.utc)
            row.last_delivery_error = None
            row.last_delivery_error_at = None
            row.block_reason = None
            if reset_attempts:
                row.delivery_attempts = 0
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row


LEAD_CAPTURE_DEFAULT_FIELD_TYPES = {
    "text",
    "textarea",
    "email",
    "phone",
    "yes_no",
    "select",
    "multi_select",
}


def normalize_lead_capture_slug(value: str | None) -> str:
    """Return a public-safe lead capture slug."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized[:96] or uuid.uuid4().hex[:12]


def default_lead_capture_form_schema() -> dict[str, Any]:
    """Return the default mobile form schema for owned lead capture."""
    return {
        "fields": [
            {
                "id": "full_name",
                "label": "Cual es tu nombre?",
                "type": "text",
                "required": True,
                "placeholder": "Nombre completo",
            },
            {
                "id": "phone",
                "label": "Cual es tu numero de WhatsApp?",
                "type": "phone",
                "required": True,
                "placeholder": "+54 9 ...",
            },
            {
                "id": "email",
                "label": "Cual es tu email?",
                "type": "email",
                "required": False,
                "placeholder": "nombre@email.com",
            },
        ],
        "layout": "multi_step",
    }


def normalize_lead_capture_form_schema(value: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a public form schema into the compact contract the app serves."""
    raw_fields = (value or {}).get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        return default_lead_capture_form_schema()

    fields: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_field in enumerate(raw_fields, start=1):
        if not isinstance(raw_field, dict):
            continue
        field_id = normalize_lead_capture_slug(str(raw_field.get("id") or raw_field.get("label") or f"field_{index}"))
        field_id = field_id.replace("-", "_")
        if not field_id or field_id in seen_ids:
            field_id = f"field_{index}"
        seen_ids.add(field_id)
        field_type = str(raw_field.get("type") or "text").strip().lower()
        if field_type not in LEAD_CAPTURE_DEFAULT_FIELD_TYPES:
            field_type = "text"
        options = raw_field.get("options") if isinstance(raw_field.get("options"), list) else []
        fields.append(
            {
                "id": field_id[:80],
                "label": " ".join(str(raw_field.get("label") or field_id).split()).strip()[:120],
                "type": field_type,
                "required": bool(raw_field.get("required")),
                "placeholder": " ".join(str(raw_field.get("placeholder") or "").split()).strip()[:160],
                "options": [
                    " ".join(str(option).split()).strip()[:120]
                    for option in options
                    if " ".join(str(option).split()).strip()
                ][:30],
            }
        )

    if not fields:
        return default_lead_capture_form_schema()
    return {
        "fields": fields,
        "layout": str((value or {}).get("layout") or "multi_step").strip() or "multi_step",
    }


def default_lead_capture_form_schema_json() -> str:
    """Return the default owned-campaign form schema as JSON."""
    return json.dumps(default_lead_capture_form_schema(), ensure_ascii=False)


class LeadCaptureCampaign(SQLModel, table=True):
    """Owned public lead-capture campaign linked to one converted client."""

    __tablename__ = "lead_capture_campaigns"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(default="", index=True)
    client_lead_source_id: str = Field(default="", index=True)
    platform_ad_campaign_id: str = Field(default="", index=True)
    funnel_id: str = Field(default="contadores", index=True)
    name: str = Field(index=True)
    status: str = Field(default="draft", index=True)
    public_slug: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
    daily_budget_usd: int | None = Field(default=None, index=True)
    budget_currency: str = Field(default="USD")
    location: str = Field(default="")
    campaign_info_json: str = Field(default="{}")
    creative_brief: str = Field(default="")
    form_schema_json: str = Field(default_factory=default_lead_capture_form_schema_json)
    thank_you_title: str = Field(default="Gracias")
    thank_you_body: str = Field(default="Recibimos tus datos. Te vamos a contactar por WhatsApp.")
    destination_url: str = Field(default="")
    meta_pixel_id: str = Field(default="", index=True)
    meta_event_name: str = Field(default="Lead")
    meta_events_enabled: bool = Field(default=False, index=True)
    meta_test_event_code: str = Field(default="")
    meta_campaign_id: str = Field(default="", index=True)
    meta_adset_id: str = Field(default="", index=True)
    meta_ad_id: str = Field(default="", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def unique_slug(cls, value: str) -> str:
        """Return a slug that does not already exist."""
        base_slug = normalize_lead_capture_slug(value)
        slug = base_slug
        suffix = 2
        with Session(engine) as session:
            while session.exec(select(cls).where(cls.public_slug == slug).limit(1)).first() is not None:
                slug = f"{base_slug[:84]}-{suffix}"
                suffix += 1
        return slug

    @classmethod
    def add(
        cls,
        *,
        client_id: str = "",
        client_lead_source_id: str = "",
        platform_ad_campaign_id: str = "",
        funnel_id: str = "contadores",
        name: str,
        status: str = "draft",
        public_slug: str | None = None,
        daily_budget_usd: int | None = None,
        budget_currency: str = "USD",
        location: str = "",
        campaign_info: dict[str, Any] | None = None,
        creative_brief: str = "",
        form_schema: dict[str, Any] | None = None,
        thank_you_title: str = "Gracias",
        thank_you_body: str = "Recibimos tus datos. Te vamos a contactar por WhatsApp.",
        destination_url: str = "",
        meta_pixel_id: str = "",
        meta_event_name: str = "Lead",
        meta_events_enabled: bool = False,
        meta_test_event_code: str = "",
        meta_campaign_id: str = "",
        meta_adset_id: str = "",
        meta_ad_id: str = "",
    ) -> "LeadCaptureCampaign":
        """Create one owned lead-capture campaign."""
        clean_name = " ".join((name or "").split()).strip()
        if not clean_name:
            raise ValueError("name is required")
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                client_id=(client_id or "").strip(),
                client_lead_source_id=(client_lead_source_id or "").strip(),
                platform_ad_campaign_id=(platform_ad_campaign_id or "").strip(),
                funnel_id=(funnel_id or "").strip() or "contadores",
                name=clean_name,
                status=(status or "draft").strip().lower() or "draft",
                public_slug=cls.unique_slug(public_slug or clean_name),
                daily_budget_usd=daily_budget_usd if daily_budget_usd and daily_budget_usd > 0 else None,
                budget_currency=((budget_currency or "USD").strip().upper()[:12] or "USD"),
                location=" ".join((location or "").split()).strip(),
                campaign_info_json=_json_dumps(campaign_info or {}),
                creative_brief=str(creative_brief or "").strip(),
                form_schema_json=_json_dumps(normalize_lead_capture_form_schema(form_schema)),
                thank_you_title=" ".join((thank_you_title or "Gracias").split()).strip()[:160] or "Gracias",
                thank_you_body=str(thank_you_body or "").strip()[:1000],
                destination_url=(destination_url or "").strip(),
                meta_pixel_id=(meta_pixel_id or "").strip(),
                meta_event_name=(meta_event_name or "Lead").strip() or "Lead",
                meta_events_enabled=bool(meta_events_enabled),
                meta_test_event_code=(meta_test_event_code or "").strip(),
                meta_campaign_id=(meta_campaign_id or "").strip(),
                meta_adset_id=(meta_adset_id or "").strip(),
                meta_ad_id=(meta_ad_id or "").strip(),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_id(cls, campaign_id: str) -> Optional["LeadCaptureCampaign"]:
        """Return one lead-capture campaign."""
        with Session(engine) as session:
            row = session.get(cls, campaign_id)
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def get_by_slug(cls, slug: str) -> Optional["LeadCaptureCampaign"]:
        """Return one public campaign by slug."""
        clean_slug = normalize_lead_capture_slug(slug)
        with Session(engine) as session:
            row = session.exec(select(cls).where(cls.public_slug == clean_slug).limit(1)).first()
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        client_id: str | None = None,
        status: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list["LeadCaptureCampaign"]:
        """List owned campaigns."""
        clean_limit = max(1, min(int(limit or 100), 500))
        with Session(engine) as session:
            statement = select(cls)
            if client_id:
                statement = statement.where(cls.client_id == client_id.strip())
            if status:
                statement = statement.where(cls.status == status.strip().lower())
            clean_query = (query or "").strip().lower()
            if clean_query:
                like_value = f"%{clean_query}%"
                statement = statement.where(
                    or_(
                        cls.name.ilike(like_value),
                        cls.public_slug.ilike(like_value),
                        cls.location.ilike(like_value),
                    )
                )
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc(), cls.id.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def update(
        cls,
        campaign_id: str,
        **updates: Any,
    ) -> Optional["LeadCaptureCampaign"]:
        """Patch one lead-capture campaign."""
        with Session(engine) as session:
            row = session.get(cls, campaign_id)
            if row is None:
                return None
            if "name" in updates and updates["name"] is not None:
                row.name = " ".join(str(updates["name"]).split()).strip() or row.name
            if "status" in updates and updates["status"] is not None:
                row.status = str(updates["status"]).strip().lower() or row.status
            if "public_slug" in updates and updates["public_slug"] is not None:
                next_slug = normalize_lead_capture_slug(str(updates["public_slug"]))
                if next_slug != row.public_slug:
                    existing = session.exec(select(cls).where(cls.public_slug == next_slug).limit(1)).first()
                    if existing is not None and existing.id != row.id:
                        raise ValueError("public_slug is already in use")
                    row.public_slug = next_slug
            simple_strings = [
                "client_id",
                "client_lead_source_id",
                "platform_ad_campaign_id",
                "funnel_id",
                "location",
                "creative_brief",
                "thank_you_title",
                "thank_you_body",
                "destination_url",
                "meta_pixel_id",
                "meta_event_name",
                "meta_test_event_code",
                "meta_campaign_id",
                "meta_adset_id",
                "meta_ad_id",
            ]
            for field_name in simple_strings:
                if field_name in updates and updates[field_name] is not None:
                    value = str(updates[field_name] or "").strip()
                    if field_name == "budget_currency":
                        value = value.upper()[:12] or "USD"
                    setattr(row, field_name, value)
            if "daily_budget_usd" in updates:
                value = updates["daily_budget_usd"]
                row.daily_budget_usd = value if value and int(value) > 0 else None
            if "budget_currency" in updates and updates["budget_currency"] is not None:
                row.budget_currency = str(updates["budget_currency"] or "USD").strip().upper()[:12] or "USD"
            if "campaign_info" in updates and updates["campaign_info"] is not None:
                row.campaign_info_json = _json_dumps(updates["campaign_info"])
            if "form_schema" in updates and updates["form_schema"] is not None:
                row.form_schema_json = _json_dumps(normalize_lead_capture_form_schema(updates["form_schema"]))
            if "meta_events_enabled" in updates and updates["meta_events_enabled"] is not None:
                row.meta_events_enabled = bool(updates["meta_events_enabled"])
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @property
    def campaign_info(self) -> dict[str, Any]:
        """Return parsed campaign metadata."""
        return _json_object(self.campaign_info_json)

    @property
    def form_schema(self) -> dict[str, Any]:
        """Return parsed public form schema."""
        return normalize_lead_capture_form_schema(_json_object(self.form_schema_json))


class LeadCaptureSubmission(SQLModel, table=True):
    """One public owned-campaign lead capture submission."""

    __tablename__ = "lead_capture_submissions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    campaign_id: str = Field(foreign_key="lead_capture_campaigns.id", index=True)
    client_id: str = Field(default="", index=True)
    client_lead_delivery_id: str = Field(default="", index=True)
    idempotency_key: str | None = Field(default=None, sa_column=Column(String, unique=True, index=True, nullable=True))
    full_name: str | None = Field(default=None, index=True)
    phone: str = Field(default="")
    normalized_phone: str = Field(default="", index=True)
    email: str | None = Field(default=None, index=True)
    answers_json: str = Field(default="{}")
    tracking_json: str = Field(default="{}")
    meta_event_id: str = Field(default="", index=True)
    meta_event_status: str = Field(default="", index=True)
    meta_event_response_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def get_by_id(cls, submission_id: str) -> Optional["LeadCaptureSubmission"]:
        """Return one submission by id."""
        with Session(engine) as session:
            row = session.get(cls, submission_id)
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def get_by_idempotency_key(cls, idempotency_key: str | None) -> Optional["LeadCaptureSubmission"]:
        """Return one submission by idempotency key."""
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            return None
        with Session(engine) as session:
            row = session.exec(select(cls).where(cls.idempotency_key == clean_key).limit(1)).first()
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def get_latest_by_campaign_phone(
        cls,
        campaign_id: str,
        phone: str,
    ) -> Optional["LeadCaptureSubmission"]:
        """Return the latest submission for one campaign and normalized phone."""
        clean_campaign_id = (campaign_id or "").strip()
        normalized_phone = normalize_phone(phone)
        if not clean_campaign_id or not normalized_phone:
            return None
        with Session(engine) as session:
            row = session.exec(
                select(cls)
                .where(cls.campaign_id == clean_campaign_id)
                .where(cls.normalized_phone == normalized_phone)
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(1)
            ).first()
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def add(
        cls,
        *,
        campaign_id: str,
        client_id: str = "",
        client_lead_delivery_id: str = "",
        idempotency_key: str | None = None,
        full_name: str | None,
        phone: str,
        email: str | None = None,
        answers: dict[str, Any] | None = None,
        tracking: dict[str, Any] | None = None,
        meta_event_id: str = "",
        meta_event_status: str = "",
        meta_event_response: dict[str, Any] | None = None,
    ) -> "LeadCaptureSubmission":
        """Persist one public campaign submission."""
        clean_key = (idempotency_key or "").strip() or None
        if clean_key:
            existing = cls.get_by_idempotency_key(clean_key)
            if existing is not None:
                return existing
        normalized_phone = normalize_phone(phone)
        if not normalized_phone:
            raise ValueError("phone is invalid")
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                campaign_id=(campaign_id or "").strip(),
                client_id=(client_id or "").strip(),
                client_lead_delivery_id=(client_lead_delivery_id or "").strip(),
                idempotency_key=clean_key,
                full_name=" ".join((full_name or "").split()).strip() or None,
                phone=(phone or "").strip(),
                normalized_phone=normalized_phone,
                email=(normalize_email(email) or None) if email else None,
                answers_json=_json_dumps(answers or {}),
                tracking_json=_json_dumps(tracking or {}),
                meta_event_id=(meta_event_id or "").strip(),
                meta_event_status=(meta_event_status or "").strip(),
                meta_event_response_json=_json_dumps(meta_event_response or {}),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def update_delivery_and_meta(
        cls,
        submission_id: str,
        *,
        client_lead_delivery_id: str | None = None,
        meta_event_id: str | None = None,
        meta_event_status: str | None = None,
        meta_event_response: dict[str, Any] | None = None,
    ) -> Optional["LeadCaptureSubmission"]:
        """Attach Delivery and Meta event results after async-safe side effects."""
        with Session(engine) as session:
            row = session.get(cls, submission_id)
            if row is None:
                return None
            if client_lead_delivery_id is not None:
                row.client_lead_delivery_id = (client_lead_delivery_id or "").strip()
            if meta_event_id is not None:
                row.meta_event_id = (meta_event_id or "").strip()
            if meta_event_status is not None:
                row.meta_event_status = (meta_event_status or "").strip()
            if meta_event_response is not None:
                row.meta_event_response_json = _json_dumps(meta_event_response)
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_by_campaign(
        cls,
        campaign_id: str,
        *,
        limit: int = 500,
    ) -> list["LeadCaptureSubmission"]:
        """List submissions for one campaign."""
        clean_limit = max(1, min(int(limit or 500), 1000))
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.campaign_id == campaign_id)
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(clean_limit)
            )
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def count_by_campaign(cls) -> dict[str, int]:
        """Return submission counts per campaign."""
        with Session(engine) as session:
            rows = session.exec(select(cls.campaign_id)).all()
        counts: dict[str, int] = {}
        for campaign_id in rows:
            counts[campaign_id] = counts.get(campaign_id, 0) + 1
        return counts

    @property
    def answers(self) -> dict[str, Any]:
        """Return parsed form answers."""
        return _json_object(self.answers_json)

    @property
    def tracking(self) -> dict[str, Any]:
        """Return parsed tracking metadata."""
        return _json_object(self.tracking_json)

    @property
    def meta_event_response(self) -> dict[str, Any]:
        """Return parsed Meta CAPI response."""
        return _json_object(self.meta_event_response_json)


class AgentRun(SQLModel, table=True):
    """One autonomous Codex employee run and its audited outcome."""

    __tablename__ = "agent_runs"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    agent_kind: str = Field(default="codex", index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    status: str = Field(default="running", index=True)
    prompt_version: str = Field(default="")
    context_path: str = Field(default="")
    codex_thread_id: str | None = Field(default=None, index=True)
    codex_turn_id: str | None = Field(default=None, index=True)
    final_response: str = Field(default="")
    error: str = Field(default="")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    finished_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def start(
        cls,
        *,
        run_id: str,
        agent_kind: str,
        target_type: str,
        target_id: str,
        prompt_version: str = "",
        context_path: str = "",
    ) -> "AgentRun":
        """Persist the start of one autonomous run."""
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                id=run_id,
                agent_kind=(agent_kind or "codex").strip() or "codex",
                target_type=(target_type or "").strip(),
                target_id=(target_id or "").strip(),
                status="running",
                prompt_version=(prompt_version or "").strip(),
                context_path=(context_path or "").strip(),
                started_at=now,
                created_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_id(cls, run_id: str) -> Optional["AgentRun"]:
        """Return one agent run by ID."""
        clean_id = (run_id or "").strip()
        if not clean_id:
            return None
        with Session(engine) as session:
            row = session.get(cls, clean_id)
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def ensure(
        cls,
        *,
        run_id: str,
        agent_kind: str = "codex_tool",
        target_type: str = "",
        target_id: str = "",
        prompt_version: str = "agent-native-tool-call",
        context_path: str = "",
    ) -> Optional["AgentRun"]:
        """Create the audit parent run when an agent-native tool is called directly."""
        clean_id = (run_id or "").strip()
        if not clean_id:
            return None
        existing = cls.get_by_id(clean_id)
        if existing is not None:
            return existing
        try:
            return cls.start(
                run_id=clean_id,
                agent_kind=agent_kind,
                target_type=target_type,
                target_id=target_id,
                prompt_version=prompt_version,
                context_path=context_path,
            )
        except IntegrityError:
            return cls.get_by_id(clean_id)

    @classmethod
    def finish(
        cls,
        run_id: str,
        *,
        status: str,
        final_response: str = "",
        error: str = "",
        codex_thread_id: str | None = None,
        codex_turn_id: str | None = None,
        finished_at: datetime | None = None,
    ) -> Optional["AgentRun"]:
        """Mark one autonomous run as completed or failed."""
        with Session(engine) as session:
            row = session.get(cls, run_id)
            if row is None:
                return None
            row.status = (status or "").strip() or row.status
            row.final_response = str(final_response or "")[:20000]
            row.error = str(error or "")[:12000]
            if codex_thread_id is not None:
                row.codex_thread_id = (codex_thread_id or "").strip() or None
            if codex_turn_id is not None:
                row.codex_turn_id = (codex_turn_id or "").strip() or None
            row.finished_at = finished_at or datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        status: str | None = None,
        target_type: str | None = None,
        limit: int = 100,
    ) -> list["AgentRun"]:
        """List recent autonomous runs for operator observability."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if status:
                statement = statement.where(cls.status == status.strip())
            if target_type:
                statement = statement.where(cls.target_type == target_type.strip())
            statement = statement.order_by(cls.started_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows


class AgentToolCall(SQLModel, table=True):
    """One tool call made by an autonomous Codex run."""

    __tablename__ = "agent_tool_calls"

    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: str = Field(foreign_key="agent_runs.id", index=True)
    tool_name: str = Field(index=True)
    target_type: str = Field(default="", index=True)
    target_id: str = Field(default="", index=True)
    arguments_json: str = Field(default="{}")
    result_json: str = Field(default="{}")
    status: str = Field(default="succeeded", index=True)
    idempotency_key: str | None = Field(default=None, index=True)
    error: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        run_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any] | None = None,
        status: str = "succeeded",
        target_type: str = "",
        target_id: str = "",
        idempotency_key: str | None = None,
        error: str = "",
    ) -> "AgentToolCall":
        """Persist one audited tool call."""
        with Session(engine) as session:
            row = cls(
                run_id=(run_id or "").strip(),
                tool_name=(tool_name or "").strip(),
                target_type=(target_type or "").strip(),
                target_id=(target_id or "").strip(),
                arguments_json=json.dumps(arguments or {}, ensure_ascii=True, default=str),
                result_json=json.dumps(result or {}, ensure_ascii=True, default=str),
                status=(status or "").strip() or "succeeded",
                idempotency_key=(idempotency_key or "").strip() or None,
                error=str(error or "")[:12000],
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_by_run(cls, run_id: str) -> list["AgentToolCall"]:
        """List audited tool calls for one run."""
        with Session(engine) as session:
            statement = select(cls).where(cls.run_id == run_id).order_by(cls.created_at, cls.id)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def list_recent(
        cls,
        *,
        run_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list["AgentToolCall"]:
        """List recent audited tool calls for the platform cockpit."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if run_id:
                statement = statement.where(cls.run_id == run_id.strip())
            if status:
                statement = statement.where(cls.status == status.strip())
            statement = statement.order_by(cls.created_at.desc(), cls.id.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows


class PlatformEvent(SQLModel, table=True):
    """Append-only lifecycle event for platform observability."""

    __tablename__ = "platform_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = Field(index=True)
    lifecycle_stage: str = Field(default="", index=True)
    target_type: str = Field(default="", index=True)
    target_id: str = Field(default="", index=True)
    funnel_id: str = Field(default="", index=True)
    severity: str = Field(default="info", index=True)
    source: str = Field(default="", index=True)
    actor: str = Field(default="")
    summary: str = Field(default="")
    payload_json: str = Field(default="{}")
    idempotency_key: str | None = Field(default=None, index=True)
    correlation_id: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        event_type: str,
        lifecycle_stage: str = "",
        target_type: str = "",
        target_id: str = "",
        funnel_id: str = "",
        severity: str = "info",
        source: str = "",
        actor: str = "",
        summary: str = "",
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        created_at: datetime | None = None,
    ) -> "PlatformEvent":
        """Persist one event, preserving idempotency when a key is supplied."""
        clean_key = (idempotency_key or "").strip() or None
        if clean_key:
            existing = cls.get_by_idempotency_key(clean_key)
            if existing is not None:
                return existing
        with Session(engine) as session:
            row = cls(
                event_type=(event_type or "").strip(),
                lifecycle_stage=(lifecycle_stage or "").strip(),
                target_type=(target_type or "").strip(),
                target_id=(target_id or "").strip(),
                funnel_id=(funnel_id or "").strip(),
                severity=(severity or "info").strip() or "info",
                source=(source or "").strip(),
                actor=(actor or "").strip(),
                summary=str(summary or "")[:1000],
                payload_json=json.dumps(payload or {}, ensure_ascii=True, default=str),
                idempotency_key=clean_key,
                correlation_id=(correlation_id or "").strip() or None,
                created_at=created_at or datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_idempotency_key(cls, idempotency_key: str) -> Optional["PlatformEvent"]:
        """Return the event for one idempotency key."""
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            return None
        with Session(engine) as session:
            row = session.exec(select(cls).where(cls.idempotency_key == clean_key)).first()
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        funnel_id: str | None = None,
        limit: int = 100,
    ) -> list["PlatformEvent"]:
        """List recent events, optionally scoped to one target or funnel."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if target_type:
                statement = statement.where(cls.target_type == target_type.strip())
            if target_id:
                statement = statement.where(cls.target_id == target_id.strip())
            if funnel_id:
                statement = statement.where(cls.funnel_id == funnel_id.strip())
            statement = statement.order_by(cls.created_at.desc(), cls.id.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def payload_dict(self) -> dict[str, Any]:
        """Return the parsed event payload."""
        try:
            payload = json.loads(self.payload_json or "{}")
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}


def _json_object(raw_value: str) -> dict[str, Any]:
    """Parse a stored JSON object."""
    try:
        payload = json.loads(raw_value or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_array(raw_value: str) -> list[Any]:
    """Parse a stored JSON array."""
    try:
        payload = json.loads(raw_value or "[]")
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _json_dumps(value: Any) -> str:
    """Store JSON consistently for platform lifecycle records."""
    return json.dumps(value if value is not None else {}, ensure_ascii=True, default=str)


def _meta_publish_idempotency_payload(value: dict[str, Any] | None) -> dict[str, Any]:
    """Return the immutable part of a Meta publish request for idempotency checks."""
    payload = dict(value or {})
    if payload.get("schema_version") == "konecta.meta_publish_plan.v1":
        payload.pop("approval_policy", None)
        payload.pop("live_execution_state", None)
        payload.pop("live_writes_allowed", None)
        payload.pop("publish_mode", None)
        lead_routing = payload.get("lead_routing")
        if isinstance(lead_routing, dict):
            normalized_routing = dict(lead_routing)
            normalized_routing.pop("mapped_source_ids", None)
            normalized_routing.pop("routing_blockers", None)
            payload["lead_routing"] = normalized_routing
    return payload


def _meeting_zone_or_utc(timezone_name: str) -> ZoneInfo | timezone:
    """Return the meeting timezone, falling back to UTC when missing or invalid."""
    clean_timezone = (timezone_name or "").strip()
    if not clean_timezone:
        return timezone.utc
    try:
        return ZoneInfo(clean_timezone)
    except ZoneInfoNotFoundError:
        return timezone.utc


def _normalize_platform_meeting_scheduled_at(
    scheduled_at: datetime | None,
    timezone_name: str,
) -> datetime | None:
    """Persist meeting start times as UTC-naive because SQLite drops tzinfo."""
    if scheduled_at is None:
        return None
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=_meeting_zone_or_utc(timezone_name))
    return scheduled_at.astimezone(timezone.utc).replace(tzinfo=None)


class PlatformMeeting(SQLModel, table=True):
    """Meeting scheduling and transcript handoff state."""

    __tablename__ = "platform_meetings"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    lead_id: str = Field(default="", index=True)
    client_id: str = Field(default="", index=True)
    funnel_id: str = Field(default="", index=True)
    status: str = Field(default="collecting_details", index=True)
    lead_email: str = Field(default="", index=True)
    timezone: str = Field(default="")
    requested_day: str = Field(default="")
    requested_time: str = Field(default="")
    calendar_id: str = Field(default="")
    calendar_event_id: str = Field(default="", index=True)
    calendar_event_link: str = Field(default="")
    calendar_event_payload_json: str = Field(default="{}")
    calendar_result_json: str = Field(default="{}")
    calendar_error: str = Field(default="")
    context_summary: str = Field(default="")
    transcript_text: str = Field(default="")
    transcript_path: str = Field(default="")
    extracted_profile_json: str = Field(default="{}")
    idempotency_key: str | None = Field(default=None, index=True)
    scheduled_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        lead_id: str = "",
        client_id: str = "",
        funnel_id: str = "",
        status: str = "collecting_details",
        lead_email: str = "",
        timezone_name: str = "",
        requested_day: str = "",
        requested_time: str = "",
        calendar_id: str = "",
        calendar_event_id: str = "",
        calendar_event_link: str = "",
        calendar_event_payload: dict[str, Any] | None = None,
        calendar_result: dict[str, Any] | None = None,
        calendar_error: str = "",
        context_summary: str = "",
        transcript_text: str = "",
        transcript_path: str = "",
        extracted_profile: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> "PlatformMeeting":
        """Create or return one meeting record."""
        clean_key = (idempotency_key or "").strip() or None
        if clean_key:
            existing = cls.get_by_idempotency_key(clean_key)
            if existing is not None:
                return existing
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                lead_id=(lead_id or "").strip(),
                client_id=(client_id or "").strip(),
                funnel_id=(funnel_id or "").strip(),
                status=(status or "collecting_details").strip() or "collecting_details",
                lead_email=normalize_email(lead_email),
                timezone=(timezone_name or "").strip(),
                requested_day=(requested_day or "").strip(),
                requested_time=(requested_time or "").strip(),
                calendar_id=(calendar_id or "").strip(),
                calendar_event_id=(calendar_event_id or "").strip(),
                calendar_event_link=(calendar_event_link or "").strip(),
                calendar_event_payload_json=_json_dumps(calendar_event_payload or {}),
                calendar_result_json=_json_dumps(calendar_result or {}),
                calendar_error=str(calendar_error or "")[:12000],
                context_summary=str(context_summary or "")[:4000],
                transcript_text=str(transcript_text or "")[:50000],
                transcript_path=(transcript_path or "").strip(),
                extracted_profile_json=_json_dumps(extracted_profile or {}),
                idempotency_key=clean_key,
                scheduled_at=_normalize_platform_meeting_scheduled_at(scheduled_at, timezone_name),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def update_calendar(
        cls,
        meeting_id: str,
        *,
        status: str | None = None,
        calendar_id: str | None = None,
        calendar_event_id: str | None = None,
        calendar_event_link: str | None = None,
        calendar_event_payload: dict[str, Any] | None = None,
        calendar_result: dict[str, Any] | None = None,
        calendar_error: str | None = None,
    ) -> Optional["PlatformMeeting"]:
        """Persist Google Calendar scheduling state for one meeting."""
        with Session(engine) as session:
            row = session.get(cls, meeting_id)
            if row is None:
                return None
            if status is not None:
                row.status = (status or row.status or "collecting_details").strip() or "collecting_details"
            if calendar_id is not None:
                row.calendar_id = (calendar_id or "").strip()
            if calendar_event_id is not None:
                row.calendar_event_id = (calendar_event_id or "").strip()
            if calendar_event_link is not None:
                row.calendar_event_link = (calendar_event_link or "").strip()
            if calendar_event_payload is not None:
                row.calendar_event_payload_json = _json_dumps(calendar_event_payload)
            if calendar_result is not None:
                row.calendar_result_json = _json_dumps(calendar_result)
            if calendar_error is not None:
                row.calendar_error = str(calendar_error or "")[:12000]
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_id(cls, row_id: str) -> Optional["PlatformMeeting"]:
        """Return one meeting."""
        with Session(engine) as session:
            row = session.get(cls, row_id)
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def get_by_idempotency_key(cls, idempotency_key: str) -> Optional["PlatformMeeting"]:
        """Return one meeting by idempotency key."""
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            return None
        with Session(engine) as session:
            row = session.exec(select(cls).where(cls.idempotency_key == clean_key)).first()
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        status: str | None = None,
        lead_id: str | None = None,
        client_id: str | None = None,
        funnel_id: str | None = None,
        limit: int = 100,
    ) -> list["PlatformMeeting"]:
        """List recent meetings."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if status:
                statement = statement.where(cls.status == status.strip())
            if lead_id:
                statement = statement.where(cls.lead_id == lead_id.strip())
            if client_id:
                statement = statement.where(cls.client_id == client_id.strip())
            if funnel_id:
                statement = statement.where(cls.funnel_id == funnel_id.strip())
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def attach_transcript(
        cls,
        meeting_id: str,
        *,
        transcript_text: str = "",
        transcript_path: str = "",
        extracted_profile: dict[str, Any] | None = None,
        status: str = "transcript_received",
    ) -> Optional["PlatformMeeting"]:
        """Attach conversion transcript data to one meeting."""
        with Session(engine) as session:
            row = session.get(cls, meeting_id)
            if row is None:
                return None
            row.transcript_text = str(transcript_text or row.transcript_text or "")[:50000]
            row.transcript_path = (transcript_path or row.transcript_path or "").strip()
            if extracted_profile is not None:
                row.extracted_profile_json = _json_dumps(extracted_profile)
            row.status = (status or row.status).strip() or row.status
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    def extracted_profile(self) -> dict[str, Any]:
        """Return parsed extracted profile fields."""
        return _json_object(self.extracted_profile_json)

    def calendar_event_payload(self) -> dict[str, Any]:
        """Return parsed Google Calendar event payload."""
        return _json_object(self.calendar_event_payload_json)

    def calendar_result(self) -> dict[str, Any]:
        """Return parsed Google Calendar scheduling result."""
        return _json_object(self.calendar_result_json)


class PlatformClientProfile(SQLModel, table=True):
    """Reviewed client knowledge extracted after conversion."""

    __tablename__ = "platform_client_profiles"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(index=True)
    lead_id: str = Field(default="", index=True)
    funnel_id: str = Field(default="", index=True)
    status: str = Field(default="draft", index=True)
    source_meeting_id: str = Field(default="", index=True)
    business_summary: str = Field(default="")
    offer_summary: str = Field(default="")
    market_summary: str = Field(default="")
    objections_json: str = Field(default="[]")
    segments_json: str = Field(default="[]")
    knowledge_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def upsert(
        cls,
        *,
        client_id: str,
        lead_id: str = "",
        funnel_id: str = "",
        status: str = "draft",
        source_meeting_id: str = "",
        business_summary: str = "",
        offer_summary: str = "",
        market_summary: str = "",
        objections: list[Any] | None = None,
        segments: list[Any] | None = None,
        knowledge: dict[str, Any] | None = None,
    ) -> "PlatformClientProfile":
        """Create or update one profile for a converted client."""
        clean_client_id = (client_id or "").strip()
        if not clean_client_id:
            raise ValueError("client_id is required")
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = session.exec(select(cls).where(cls.client_id == clean_client_id)).first()
            if row is None:
                row = cls(client_id=clean_client_id, created_at=now)
            row.lead_id = (lead_id or row.lead_id or "").strip()
            row.funnel_id = (funnel_id or row.funnel_id or "").strip()
            row.status = (status or row.status or "draft").strip() or "draft"
            row.source_meeting_id = (source_meeting_id or row.source_meeting_id or "").strip()
            row.business_summary = str(business_summary or row.business_summary or "")[:8000]
            row.offer_summary = str(offer_summary or row.offer_summary or "")[:8000]
            row.market_summary = str(market_summary or row.market_summary or "")[:8000]
            if objections is not None:
                row.objections_json = _json_dumps(objections)
            if segments is not None:
                row.segments_json = _json_dumps(segments)
            if knowledge is not None:
                row.knowledge_json = _json_dumps(knowledge)
            row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_recent(cls, *, client_id: str | None = None, limit: int = 100) -> list["PlatformClientProfile"]:
        """List recent profiles."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if client_id:
                statement = statement.where(cls.client_id == client_id.strip())
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def objections(self) -> list[Any]:
        """Return parsed objections."""
        return _json_array(self.objections_json)

    def segments(self) -> list[Any]:
        """Return parsed target segments."""
        return _json_array(self.segments_json)

    def knowledge(self) -> dict[str, Any]:
        """Return parsed reviewed knowledge."""
        return _json_object(self.knowledge_json)


class PlatformAdCampaign(SQLModel, table=True):
    """Staged or published ad campaign state."""

    __tablename__ = "platform_ad_campaigns"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(default="", index=True)
    funnel_id: str = Field(default="", index=True)
    status: str = Field(default="draft", index=True)
    objective: str = Field(default="")
    budget_daily_usd: int | None = Field(default=None, index=True)
    budget_total_usd: int | None = Field(default=None)
    budget_currency: str = Field(default="USD")
    target_segments_json: str = Field(default="[]")
    angles_json: str = Field(default="[]")
    creative_benchmark_json: str = Field(default="{}")
    creative_testing_json: str = Field(default="{}")
    meta_campaign_id: str = Field(default="", index=True)
    approval_status: str = Field(default="not_requested", index=True)
    idempotency_key: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        client_id: str = "",
        funnel_id: str = "",
        status: str = "draft",
        objective: str = "",
        budget_daily_usd: int | None = None,
        budget_total_usd: int | None = None,
        budget_currency: str = "USD",
        target_segments: list[Any] | None = None,
        angles: list[Any] | None = None,
        creative_benchmark: dict[str, Any] | None = None,
        creative_testing: dict[str, Any] | None = None,
        approval_status: str = "not_requested",
        idempotency_key: str | None = None,
    ) -> "PlatformAdCampaign":
        """Create or return one campaign."""
        clean_key = (idempotency_key or "").strip() or None
        if clean_key:
            existing = cls.get_by_idempotency_key(clean_key)
            if existing is not None:
                return existing
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                client_id=(client_id or "").strip(),
                funnel_id=(funnel_id or "").strip(),
                status=(status or "draft").strip() or "draft",
                objective=str(objective or "")[:2000],
                budget_daily_usd=budget_daily_usd,
                budget_total_usd=budget_total_usd,
                budget_currency=(budget_currency or "USD").strip() or "USD",
                target_segments_json=_json_dumps(target_segments or []),
                angles_json=_json_dumps(angles or []),
                creative_benchmark_json=_json_dumps(creative_benchmark or {}),
                creative_testing_json=_json_dumps(creative_testing or {}),
                approval_status=(approval_status or "not_requested").strip() or "not_requested",
                idempotency_key=clean_key,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_id(cls, campaign_id: str) -> Optional["PlatformAdCampaign"]:
        """Return one ad campaign."""
        with Session(engine) as session:
            row = session.get(cls, campaign_id)
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def get_by_idempotency_key(cls, idempotency_key: str) -> Optional["PlatformAdCampaign"]:
        """Return one campaign by idempotency key."""
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            return None
        with Session(engine) as session:
            row = session.exec(select(cls).where(cls.idempotency_key == clean_key)).first()
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        client_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list["PlatformAdCampaign"]:
        """List recent campaigns."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if client_id:
                statement = statement.where(cls.client_id == client_id.strip())
            if status:
                statement = statement.where(cls.status == status.strip())
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def target_segments(self) -> list[Any]:
        """Return parsed targeting segments."""
        return _json_array(self.target_segments_json)

    def angles(self) -> list[Any]:
        """Return parsed ad angles."""
        return _json_array(self.angles_json)

    def creative_benchmark(self) -> dict[str, Any]:
        """Return parsed creative benchmark instructions."""
        return _json_object(self.creative_benchmark_json)

    def creative_testing(self) -> dict[str, Any]:
        """Return parsed creative testing policy."""
        return _json_object(self.creative_testing_json)


class PlatformCreativeAsset(SQLModel, table=True):
    """Generated or staged creative asset for an ad campaign."""

    __tablename__ = "platform_creative_assets"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    campaign_id: str = Field(default="", index=True)
    client_id: str = Field(default="", index=True)
    status: str = Field(default="draft", index=True)
    asset_type: str = Field(default="image", index=True)
    prompt: str = Field(default="")
    file_path: str = Field(default="")
    dimensions: str = Field(default="")
    source_refs_json: str = Field(default="[]")
    meta_creative_id: str = Field(default="", index=True)
    image_hash: str = Field(default="", index=True)
    video_id: str = Field(default="", index=True)
    meta_upload_response_json: str = Field(default="{}")
    failure_reason: str = Field(default="")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        campaign_id: str = "",
        client_id: str = "",
        status: str = "draft",
        asset_type: str = "image",
        prompt: str = "",
        file_path: str = "",
        dimensions: str = "",
        source_refs: list[Any] | None = None,
        meta_creative_id: str = "",
        image_hash: str = "",
        video_id: str = "",
        meta_upload_response: dict[str, Any] | None = None,
        failure_reason: str = "",
    ) -> "PlatformCreativeAsset":
        """Create one creative asset record."""
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                campaign_id=(campaign_id or "").strip(),
                client_id=(client_id or "").strip(),
                status=(status or "draft").strip() or "draft",
                asset_type=(asset_type or "image").strip() or "image",
                prompt=str(prompt or "")[:12000],
                file_path=(file_path or "").strip(),
                dimensions=(dimensions or "").strip(),
                source_refs_json=_json_dumps(source_refs or []),
                meta_creative_id=(meta_creative_id or "").strip(),
                image_hash=(image_hash or "").strip(),
                video_id=(video_id or "").strip(),
                meta_upload_response_json=_json_dumps(meta_upload_response or {}),
                failure_reason=str(failure_reason or "")[:4000],
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_id(cls, asset_id: str) -> Optional["PlatformCreativeAsset"]:
        """Return one creative asset by ID."""
        clean_id = (asset_id or "").strip()
        if not clean_id:
            return None
        with Session(engine) as session:
            row = session.get(cls, clean_id)
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def update_meta_refs(
        cls,
        asset_id: str,
        *,
        status: str | None = None,
        meta_creative_id: str | None = None,
        image_hash: str | None = None,
        video_id: str | None = None,
        meta_upload_response: dict[str, Any] | None = None,
        failure_reason: str | None = None,
    ) -> Optional["PlatformCreativeAsset"]:
        """Persist provider asset references returned by Meta."""
        clean_id = (asset_id or "").strip()
        if not clean_id:
            return None
        with Session(engine) as session:
            row = session.get(cls, clean_id)
            if row is None:
                return None
            if status is not None:
                row.status = (status or row.status or "draft").strip() or "draft"
            if meta_creative_id is not None:
                row.meta_creative_id = (meta_creative_id or "").strip()
            if image_hash is not None:
                row.image_hash = (image_hash or "").strip()
            if video_id is not None:
                row.video_id = (video_id or "").strip()
            if meta_upload_response is not None:
                row.meta_upload_response_json = _json_dumps(meta_upload_response)
            if failure_reason is not None:
                row.failure_reason = str(failure_reason or "")[:4000]
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        campaign_id: str | None = None,
        client_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list["PlatformCreativeAsset"]:
        """List recent creative assets."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if campaign_id:
                statement = statement.where(cls.campaign_id == campaign_id.strip())
            if client_id:
                statement = statement.where(cls.client_id == client_id.strip())
            if status:
                statement = statement.where(cls.status == status.strip())
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def source_refs(self) -> list[Any]:
        """Return parsed source references."""
        return _json_array(self.source_refs_json)

    def meta_upload_response(self) -> dict[str, Any]:
        """Return sanitized Meta upload response payload."""
        return _json_object(self.meta_upload_response_json)


class PlatformMetaPublishAttempt(SQLModel, table=True):
    """One staged or executed Meta Marketing API publish attempt."""

    __tablename__ = "platform_meta_publish_attempts"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_platform_meta_publish_attempts_idempotency_key"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    campaign_id: str = Field(default="", index=True)
    status: str = Field(default="staged", index=True)
    approval_status: str = Field(default="pending", index=True)
    request_json: str = Field(default="{}")
    response_json: str = Field(default="{}")
    error: str = Field(default="")
    idempotency_key: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        campaign_id: str = "",
        status: str = "staged",
        approval_status: str = "pending",
        request_payload: dict[str, Any] | None = None,
        response_payload: dict[str, Any] | None = None,
        error: str = "",
        idempotency_key: str | None = None,
    ) -> "PlatformMetaPublishAttempt":
        """Create or return one publish attempt."""
        clean_key = (idempotency_key or "").strip() or None
        clean_campaign_id = (campaign_id or "").strip()
        clean_request_payload = request_payload or {}

        def matches_existing(row: "PlatformMetaPublishAttempt") -> bool:
            existing_payload = _meta_publish_idempotency_payload(row.request_payload())
            next_payload = _meta_publish_idempotency_payload(clean_request_payload)
            return row.campaign_id == clean_campaign_id and existing_payload == next_payload

        if clean_key:
            existing = cls.get_by_idempotency_key(clean_key)
            if existing is not None:
                if not matches_existing(existing):
                    raise ValueError(
                        "Meta publish attempt idempotency conflict: "
                        "existing attempt has a different campaign_id or request_payload"
                    )
                return existing
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                campaign_id=clean_campaign_id,
                status=(status or "staged").strip() or "staged",
                approval_status=(approval_status or "pending").strip() or "pending",
                request_json=_json_dumps(clean_request_payload),
                response_json=_json_dumps(response_payload or {}),
                error=str(error or "")[:12000],
                idempotency_key=clean_key,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                if clean_key:
                    existing = cls.get_by_idempotency_key(clean_key)
                    if existing is not None and matches_existing(existing):
                        return existing
                    if existing is not None:
                        raise ValueError(
                            "Meta publish attempt idempotency conflict: "
                            "existing attempt has a different campaign_id or request_payload"
                        ) from error
                raise
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_idempotency_key(cls, idempotency_key: str) -> Optional["PlatformMetaPublishAttempt"]:
        """Return one publish attempt by idempotency key."""
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            return None
        with Session(engine) as session:
            row = session.exec(select(cls).where(cls.idempotency_key == clean_key)).first()
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def get_by_id(cls, attempt_id: str) -> Optional["PlatformMetaPublishAttempt"]:
        """Return one publish attempt by ID."""
        clean_id = (attempt_id or "").strip()
        if not clean_id:
            return None
        with Session(engine) as session:
            row = session.get(cls, clean_id)
            if row is not None:
                session.expunge(row)
            return row

    @classmethod
    def update_execution(
        cls,
        attempt_id: str,
        *,
        status: str | None = None,
        approval_status: str | None = None,
        request_payload: dict[str, Any] | None = None,
        response_payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Optional["PlatformMetaPublishAttempt"]:
        """Update publish execution/preflight state."""
        clean_id = (attempt_id or "").strip()
        if not clean_id:
            return None
        with Session(engine) as session:
            row = session.get(cls, clean_id)
            if row is None:
                return None
            if status is not None:
                row.status = (status or row.status or "staged").strip() or "staged"
            if approval_status is not None:
                row.approval_status = (approval_status or row.approval_status or "pending").strip() or "pending"
            if request_payload is not None:
                row.request_json = _json_dumps(request_payload)
            if response_payload is not None:
                row.response_json = _json_dumps(response_payload)
            if error is not None:
                row.error = str(error or "")[:12000]
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        campaign_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list["PlatformMetaPublishAttempt"]:
        """List recent publish attempts."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if campaign_id:
                statement = statement.where(cls.campaign_id == campaign_id.strip())
            if status:
                statement = statement.where(cls.status == status.strip())
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def request_payload(self) -> dict[str, Any]:
        """Return parsed publish request."""
        return _json_object(self.request_json)

    def response_payload(self) -> dict[str, Any]:
        """Return parsed publish response."""
        return _json_object(self.response_json)


class PlatformMetaInventorySnapshot(SQLModel, table=True):
    """Read-only Meta inventory snapshot used before publishing."""

    __tablename__ = "platform_meta_inventory_snapshots"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    status: str = Field(default="missing_credentials", index=True)
    source: str = Field(default="", index=True)
    actor: str = Field(default="")
    ad_account_id: str = Field(default="", index=True)
    business_id: str = Field(default="", index=True)
    api_version: str = Field(default="")
    inventory_json: str = Field(default="{}")
    errors_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        status: str = "missing_credentials",
        source: str = "",
        actor: str = "",
        ad_account_id: str = "",
        business_id: str = "",
        api_version: str = "",
        inventory: dict[str, Any] | None = None,
        errors: list[Any] | None = None,
    ) -> "PlatformMetaInventorySnapshot":
        """Persist one Meta inventory snapshot."""
        with Session(engine) as session:
            row = cls(
                status=(status or "missing_credentials").strip() or "missing_credentials",
                source=(source or "").strip(),
                actor=(actor or "").strip(),
                ad_account_id=(ad_account_id or "").strip(),
                business_id=(business_id or "").strip(),
                api_version=(api_version or "").strip(),
                inventory_json=_json_dumps(inventory or {}),
                errors_json=_json_dumps(errors or []),
                created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list["PlatformMetaInventorySnapshot"]:
        """List recent inventory snapshots."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if status:
                statement = statement.where(cls.status == status.strip())
            statement = statement.order_by(cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def inventory(self) -> dict[str, Any]:
        """Return parsed inventory payload."""
        return _json_object(self.inventory_json)

    def errors(self) -> list[Any]:
        """Return parsed inventory errors."""
        return _json_array(self.errors_json)


class PlatformClientUpdate(SQLModel, table=True):
    """24-hour client update draft/send state."""

    __tablename__ = "platform_client_updates"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(default="", index=True)
    campaign_id: str = Field(default="", index=True)
    status: str = Field(default="draft", index=True)
    summary_text: str = Field(default="")
    leads_count: int = Field(default=0)
    blockers_json: str = Field(default="[]")
    next_action: str = Field(default="")
    whatsapp_message_id: int | None = Field(default=None, index=True)
    window_started_at: datetime | None = Field(default=None, index=True)
    window_ended_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        client_id: str = "",
        campaign_id: str = "",
        status: str = "draft",
        summary_text: str = "",
        leads_count: int = 0,
        blockers: list[Any] | None = None,
        next_action: str = "",
        whatsapp_message_id: int | None = None,
        window_started_at: datetime | None = None,
        window_ended_at: datetime | None = None,
    ) -> "PlatformClientUpdate":
        """Create one client update record."""
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                client_id=(client_id or "").strip(),
                campaign_id=(campaign_id or "").strip(),
                status=(status or "draft").strip() or "draft",
                summary_text=str(summary_text or "")[:4000],
                leads_count=max(0, int(leads_count or 0)),
                blockers_json=_json_dumps(blockers or []),
                next_action=str(next_action or "")[:2000],
                whatsapp_message_id=whatsapp_message_id,
                window_started_at=window_started_at,
                window_ended_at=window_ended_at,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        client_id: str | None = None,
        campaign_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list["PlatformClientUpdate"]:
        """List recent client updates."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if client_id:
                statement = statement.where(cls.client_id == client_id.strip())
            if campaign_id:
                statement = statement.where(cls.campaign_id == campaign_id.strip())
            if status:
                statement = statement.where(cls.status == status.strip())
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def blockers(self) -> list[Any]:
        """Return parsed blockers."""
        return _json_array(self.blockers_json)


class PlatformHumanQuestion(SQLModel, table=True):
    """Human doubt escalation addressed to Facundo/operator."""

    __tablename__ = "platform_human_questions"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    workflow: str = Field(default="", index=True)
    target_type: str = Field(default="", index=True)
    target_id: str = Field(default="", index=True)
    funnel_id: str = Field(default="", index=True)
    status: str = Field(default="pending", index=True)
    context_summary: str = Field(default="")
    trying_to_do: str = Field(default="")
    question: str = Field(default="")
    options_json: str = Field(default="[]")
    default_action: str = Field(default="")
    timeout_at: datetime | None = Field(default=None, index=True)
    whatsapp_message_id: str = Field(default="", index=True)
    answer_text: str = Field(default="")
    answered_at: datetime | None = Field(default=None, index=True)
    promoted_to_memory_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        workflow: str = "",
        target_type: str = "",
        target_id: str = "",
        funnel_id: str = "",
        context_summary: str = "",
        trying_to_do: str = "",
        question: str,
        options: list[Any] | None = None,
        default_action: str = "",
        timeout_at: datetime | None = None,
        whatsapp_message_id: str = "",
    ) -> "PlatformHumanQuestion":
        """Create one pending human question."""
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            row = cls(
                workflow=(workflow or "").strip(),
                target_type=(target_type or "").strip(),
                target_id=(target_id or "").strip(),
                funnel_id=(funnel_id or "").strip(),
                status="pending",
                context_summary=str(context_summary or "")[:4000],
                trying_to_do=str(trying_to_do or "")[:2000],
                question=str(question or "")[:4000],
                options_json=_json_dumps(options or []),
                default_action=str(default_action or "")[:2000],
                timeout_at=timeout_at,
                whatsapp_message_id=(whatsapp_message_id or "").strip(),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def answer(
        cls,
        question_id: str,
        *,
        answer_text: str,
        status: str = "answered",
        promoted_to_memory_at: datetime | None = None,
    ) -> Optional["PlatformHumanQuestion"]:
        """Store an answer to one human question."""
        with Session(engine) as session:
            row = session.get(cls, question_id)
            if row is None:
                return None
            now = datetime.now(timezone.utc)
            row.answer_text = str(answer_text or "")[:4000]
            row.status = (status or "answered").strip() or "answered"
            row.answered_at = now
            row.promoted_to_memory_at = promoted_to_memory_at
            row.updated_at = now
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_recent(
        cls,
        *,
        status: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        limit: int = 100,
    ) -> list["PlatformHumanQuestion"]:
        """List recent human questions."""
        clean_limit = max(1, min(limit, 500))
        with Session(engine) as session:
            statement = select(cls)
            if status:
                statement = statement.where(cls.status == status.strip())
            if target_type:
                statement = statement.where(cls.target_type == target_type.strip())
            if target_id:
                statement = statement.where(cls.target_id == target_id.strip())
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc()).limit(clean_limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    def options(self) -> list[Any]:
        """Return parsed answer options."""
        return _json_array(self.options_json)


class ScheduledAgentTask(SQLModel, table=True):
    """A DB-backed wake-up task for a future autonomous Codex run."""

    __tablename__ = "scheduled_agent_tasks"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    run_id: str | None = Field(default=None, index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    due_at: datetime = Field(index=True)
    reason: str = Field(default="")
    instruction: str = Field(default="")
    idempotency_key: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    claimed_at: datetime | None = Field(default=None, index=True)
    completed_at: datetime | None = Field(default=None, index=True)
    last_error: str = Field(default="")

    @classmethod
    def create(
        cls,
        *,
        target_type: str,
        target_id: str,
        due_at: datetime,
        reason: str,
        instruction: str,
        run_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> "ScheduledAgentTask":
        """Create a pending wake-up unless the idempotency key already exists."""
        clean_key = (idempotency_key or "").strip() or None
        if clean_key:
            existing = cls.get_by_idempotency_key(clean_key)
            if existing is not None:
                return existing
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        with Session(engine) as session:
            row = cls(
                run_id=(run_id or "").strip() or None,
                target_type=(target_type or "").strip(),
                target_id=(target_id or "").strip(),
                due_at=due_at,
                reason=(reason or "").strip(),
                instruction=(instruction or "").strip(),
                idempotency_key=clean_key,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_idempotency_key(cls, idempotency_key: str) -> Optional["ScheduledAgentTask"]:
        """Return one task by idempotency key."""
        clean_key = (idempotency_key or "").strip()
        if not clean_key:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.idempotency_key == clean_key).limit(1)
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def list_due(cls, *, now: datetime, limit: int = 20) -> list["ScheduledAgentTask"]:
        """List pending wake-up tasks ready to run."""
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.status == "pending", cls.due_at <= now)
                .order_by(cls.due_at, cls.created_at, cls.id)
                .limit(limit)
            )
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def get_open_for_target(
        cls,
        *,
        target_type: str,
        target_id: str,
        reason_prefix: str,
    ) -> Optional["ScheduledAgentTask"]:
        """Return a pending/running task for one target and reason prefix."""
        clean_target_type = (target_type or "").strip()
        clean_target_id = (target_id or "").strip()
        clean_prefix = (reason_prefix or "").strip()
        if not clean_target_type or not clean_target_id or not clean_prefix:
            return None
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.target_type == clean_target_type)
                .where(cls.target_id == clean_target_id)
                .where(cls.status.in_({"pending", "running"}))
                .where(cls.reason.like(f"{clean_prefix}%"))
                .order_by(cls.due_at, cls.created_at, cls.id)
                .limit(1)
            )
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def mark_status(
        cls,
        task_id: str,
        *,
        status: str,
        run_id: str | None = None,
        error: str = "",
        timestamp: datetime | None = None,
    ) -> Optional["ScheduledAgentTask"]:
        """Update task lifecycle status."""
        now = timestamp or datetime.now(timezone.utc)
        with Session(engine) as session:
            row = session.get(cls, task_id)
            if row is None:
                return None
            row.status = (status or "").strip() or row.status
            if run_id is not None:
                row.run_id = (run_id or "").strip() or None
            if row.status == "running":
                row.claimed_at = now
            if row.status in {"completed", "failed"}:
                row.completed_at = now
            row.last_error = str(error or "")[:12000]
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def complete_open_for_target(
        cls,
        *,
        target_type: str,
        target_id: str,
        error: str,
        timestamp: datetime | None = None,
    ) -> int:
        """Complete pending/running wake-up tasks for one target."""
        now = timestamp or datetime.now(timezone.utc)
        with engine.begin() as connection:
            result = connection.exec_driver_sql(
                """
                UPDATE scheduled_agent_tasks
                SET status = 'completed',
                    completed_at = ?,
                    last_error = ?
                WHERE target_type = ?
                  AND target_id = ?
                  AND status IN ('pending', 'running')
                """,
                (
                    now,
                    str(error or "")[:12000],
                    (target_type or "").strip(),
                    (target_id or "").strip(),
                ),
            )
            return int(result.rowcount or 0)


class ContadoresRuntimeAlert(SQLModel, table=True):
    """Lightweight operator alert that does not change the lead stage."""

    __tablename__ = "contadores_runtime_alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
    funnel_id: str = Field(default="contadores", index=True)
    funnel_label: str = ""
    phone: str = Field(default="", index=True)
    full_name: str | None = Field(default=None)
    alert_type: str = Field(default="codex_fallback", index=True)
    error: str = ""
    fallback_action: str = ""
    previous_stage: str | None = Field(default=None, index=True)
    latest_inbound_text: str = ""
    email_thread_id: str | None = Field(default=None, index=True)
    email_message_id: str | None = Field(default=None, index=True)
    email_inbox_id: str | None = Field(default=None, index=True)
    email_inbox_address: str | None = Field(default=None)
    resolved_at: datetime | None = Field(default=None, index=True)
    operator_reply_text: str | None = Field(default=None)
    notified_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        lead: ContadoresLead,
        funnel_label: str,
        alert_type: str,
        error: str,
        fallback_action: str,
        latest_inbound_text: str,
        previous_stage: str | None = None,
    ) -> "ContadoresRuntimeAlert":
        """Persist one runtime alert for later email notification."""
        with Session(engine) as session:
            row = cls(
                lead_id=lead.id,
                funnel_id=(lead.funnel_id or "contadores").strip() or "contadores",
                funnel_label=(funnel_label or "").strip(),
                phone=(lead.phone or "").strip(),
                full_name=(lead.full_name or "").strip() or None,
                alert_type=(alert_type or "runtime_alert").strip() or "runtime_alert",
                error=" ".join(str(error or "").split()).strip()[:2000],
                fallback_action=(fallback_action or "").strip(),
                previous_stage=(previous_stage or "").strip() or None,
                latest_inbound_text=(latest_inbound_text or "").strip()[:2000],
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_pending(
        cls,
        *,
        funnel_id: str | None = None,
        limit: int = 100,
    ) -> list["ContadoresRuntimeAlert"]:
        """List runtime alerts that still need an operator email."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.notified_at.is_(None), cls.resolved_at.is_(None))
                .order_by(cls.created_at, cls.id)
                .limit(limit)
            )
            if funnel_id is not None:
                statement = statement.where(cls.funnel_id == ((funnel_id or "").strip() or "contadores"))
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def list_recent_by_lead(
        cls,
        lead_id: str,
        *,
        limit: int = 20,
    ) -> list["ContadoresRuntimeAlert"]:
        """List recent runtime alerts for one lead."""
        clean_lead_id = (lead_id or "").strip()
        if not clean_lead_id:
            return []
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.lead_id == clean_lead_id)
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(max(1, int(limit)))
            )
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def mark_notified(
        cls,
        *,
        alert_id: int,
        notified_at: datetime | None = None,
        email_thread_id: str | None = None,
        email_message_id: str | None = None,
        email_inbox_id: str | None = None,
        email_inbox_address: str | None = None,
    ) -> Optional["ContadoresRuntimeAlert"]:
        """Mark one runtime alert as emailed."""
        with Session(engine) as session:
            row = session.get(cls, alert_id)
            if row is None:
                return None
            row.notified_at = notified_at or datetime.now(timezone.utc)
            if email_thread_id is not None:
                row.email_thread_id = (email_thread_id or "").strip() or None
            if email_message_id is not None:
                row.email_message_id = (email_message_id or "").strip() or None
            if email_inbox_id is not None:
                row.email_inbox_id = (email_inbox_id or "").strip() or None
            if email_inbox_address is not None:
                row.email_inbox_address = (email_inbox_address or "").strip() or None
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_unresolved_by_email_thread(
        cls,
        *,
        thread_id: str,
    ) -> Optional["ContadoresRuntimeAlert"]:
        """Return one unresolved runtime alert by AgentMail thread id."""
        clean_thread_id = (thread_id or "").strip()
        if not clean_thread_id:
            return None
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.email_thread_id == clean_thread_id,
                    cls.resolved_at.is_(None),
                )
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(1)
            )
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def mark_resolved(
        cls,
        *,
        alert_id: int,
        operator_reply_text: str,
        resolved_at: datetime | None = None,
    ) -> Optional["ContadoresRuntimeAlert"]:
        """Mark one runtime alert as resolved by an operator email reply."""
        with Session(engine) as session:
            row = session.get(cls, alert_id)
            if row is None:
                return None
            row.resolved_at = resolved_at or datetime.now(timezone.utc)
            row.operator_reply_text = " ".join(str(operator_reply_text or "").split()).strip()[:4000] or None
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row


class WorkstationClientStatus(str, Enum):
    """Status for one converted client."""

    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    IN_PROGRESS = "in_progress"
    CLOSED = "closed"
    ARCHIVED = "archived"


class WorkstationClientWorkType(str, Enum):
    """Commercial job type for one Workstation client."""

    SOLO_PAGINA = "solo_pagina"
    PAGINA_ADS = "pagina_ads"
    SOLO_ADS = "solo_ads"


class WorkstationAutomationStatus(str, Enum):
    """Automation lifecycle for a Workstation delivery job."""

    INTAKE = "intake"
    DRAFTING = "drafting"
    AWAITING_REVIEW = "awaiting_review"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    NEEDS_HUMAN = "needs_human"
    FAILED = "failed"


def normalize_workstation_client_status(
    status: WorkstationClientStatus | str | None,
) -> WorkstationClientStatus:
    """Normalize raw Workstation status values."""
    if isinstance(status, WorkstationClientStatus):
        return status
    value = (status or "").strip().lower()
    for candidate in WorkstationClientStatus:
        if candidate.value == value:
            return candidate
    return WorkstationClientStatus.PAID


def normalize_workstation_work_type(
    work_type: WorkstationClientWorkType | str | None,
) -> WorkstationClientWorkType:
    """Normalize raw Workstation job-type values."""
    if isinstance(work_type, WorkstationClientWorkType):
        return work_type
    value = (work_type or "").strip().lower()
    for candidate in WorkstationClientWorkType:
        if candidate.value == value:
            return candidate
    return WorkstationClientWorkType.PAGINA_ADS


def normalize_workstation_automation_status(
    status: WorkstationAutomationStatus | str | None,
) -> WorkstationAutomationStatus:
    """Normalize raw Workstation automation status values."""
    if isinstance(status, WorkstationAutomationStatus):
        return status
    value = (status or "").strip().lower()
    for candidate in WorkstationAutomationStatus:
        if candidate.value == value:
            return candidate
    return WorkstationAutomationStatus.NEEDS_HUMAN


def normalize_workstation_slug(value: str | None) -> str:
    """Build a readable ASCII-ish slug for a client folder name."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return normalized[:80] or "client"


def build_workstation_folder_name(*, client_id: str, display_name: str | None) -> str:
    """Return the stable folder name used by Codex and the app."""
    short_id = (client_id or "").strip()[:8] or uuid.uuid4().hex[:8]
    return f"{short_id}-{normalize_workstation_slug(display_name)}"


class WorkstationClient(SQLModel, table=True):
    """Converted paid client profile used for client work."""

    __tablename__ = "workstation_clients"
    __table_args__ = (UniqueConstraint("lead_id", name="uq_workstation_clients_lead_id"),)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
    funnel_id: str = Field(default="contadores", index=True)
    status: WorkstationClientStatus = Field(default=WorkstationClientStatus.PAID, index=True)
    work_type: WorkstationClientWorkType = Field(default=WorkstationClientWorkType.PAGINA_ADS, index=True)
    automation_status: WorkstationAutomationStatus = Field(
        default=WorkstationAutomationStatus.NEEDS_HUMAN,
        index=True,
    )
    codex_workstation_thread_id: str | None = Field(default=None, index=True)
    offer_price_usd: int | None = Field(default=None, index=True)
    offer_currency: str = Field(default="USD")
    display_name: str = Field(default="")
    folder_name: str = Field(default="", index=True)
    notes: str = Field(default="")
    last_automation_handled_at: datetime | None = Field(default=None, index=True)
    last_preview_sent_at: datetime | None = Field(default=None, index=True)
    approved_at: datetime | None = Field(default=None, index=True)
    ping_1_sent_at: datetime | None = Field(default=None, index=True)
    ping_2_sent_at: datetime | None = Field(default=None, index=True)
    handoff_sent_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def get_by_id(cls, client_id: str) -> Optional["WorkstationClient"]:
        """Get one Workstation client by ID."""
        with Session(engine) as session:
            item = session.get(cls, client_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_by_lead_id(cls, lead_id: str) -> Optional["WorkstationClient"]:
        """Get one Workstation client by source lead."""
        clean_lead_id = (lead_id or "").strip()
        if not clean_lead_id:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.lead_id == clean_lead_id).limit(1)
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_recent(
        cls,
        *,
        limit: int = 300,
        funnel_id: str | None = None,
        status: WorkstationClientStatus | str | None = None,
        work_type: WorkstationClientWorkType | str | None = None,
        automation_status: WorkstationAutomationStatus | str | None = None,
    ) -> list["WorkstationClient"]:
        """List recent converted clients."""
        with Session(engine) as session:
            statement = select(cls)
            if funnel_id is not None:
                statement = statement.where(cls.funnel_id == ((funnel_id or "").strip() or "contadores"))
            if status is not None:
                statement = statement.where(cls.status == normalize_workstation_client_status(status))
            if work_type is not None:
                statement = statement.where(cls.work_type == normalize_workstation_work_type(work_type))
            if automation_status is not None:
                statement = statement.where(
                    cls.automation_status == normalize_workstation_automation_status(automation_status)
                )
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc(), cls.id.desc()).limit(limit)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def list_active_automation(
        cls,
        *,
        limit: int = 100,
        work_type: WorkstationClientWorkType | str = WorkstationClientWorkType.SOLO_PAGINA,
    ) -> list["WorkstationClient"]:
        """List Workstation clients whose automation can still advance."""
        terminal_statuses = {
            WorkstationAutomationStatus.APPROVED,
            WorkstationAutomationStatus.FAILED,
        }
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.work_type == normalize_workstation_work_type(work_type))
                .where(cls.status.not_in({WorkstationClientStatus.ARCHIVED, WorkstationClientStatus.CLOSED}))
                .where(cls.automation_status.not_in(terminal_statuses))
                .where(
                    or_(
                        cls.automation_status != WorkstationAutomationStatus.NEEDS_HUMAN,
                        and_(cls.approved_at.is_(None), cls.handoff_sent_at.is_not(None)),
                    )
                )
                .order_by(cls.updated_at, cls.created_at, cls.id)
                .limit(limit)
            )
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def create_for_lead(
        cls,
        lead: ContadoresLead,
        *,
        work_type: WorkstationClientWorkType | str = WorkstationClientWorkType.PAGINA_ADS,
        status: WorkstationClientStatus | str = WorkstationClientStatus.PAID,
        automation_status: WorkstationAutomationStatus | str = WorkstationAutomationStatus.NEEDS_HUMAN,
        offer_price_usd: int | None = None,
        offer_currency: str = "USD",
    ) -> "WorkstationClient":
        """Create one Workstation client for a paid lead, idempotently."""
        existing = cls.get_by_lead_id(lead.id)
        if existing is not None:
            return existing

        client_id = str(uuid.uuid4())
        display_name = (lead.full_name or lead.phone or lead.normalized_phone or "Client").strip()
        folder_name = build_workstation_folder_name(client_id=client_id, display_name=display_name)
        now = datetime.now(timezone.utc)
        with Session(engine) as session:
            item = cls(
                id=client_id,
                lead_id=lead.id,
                funnel_id=lead.funnel_id or "contadores",
                status=normalize_workstation_client_status(status),
                work_type=normalize_workstation_work_type(work_type),
                automation_status=normalize_workstation_automation_status(automation_status),
                offer_price_usd=offer_price_usd if offer_price_usd and offer_price_usd > 0 else None,
                offer_currency=((offer_currency or "USD").strip().upper()[:12] or "USD"),
                display_name=display_name,
                folder_name=folder_name,
                created_at=now,
                updated_at=now,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            ContadoresLead.sync_lifecycle_fields(lead.id)
            return item

    @classmethod
    def update_offer(
        cls,
        client_id: str,
        *,
        offer_price_usd: int | None,
        offer_currency: str = "USD",
        only_if_missing: bool = True,
    ) -> Optional["WorkstationClient"]:
        """Persist the fixed commercial offer attached to one Workstation job."""
        clean_price = offer_price_usd if offer_price_usd and offer_price_usd > 0 else None
        clean_currency = ((offer_currency or "USD").strip().upper()[:12] or "USD")
        with Session(engine) as session:
            item = session.get(cls, client_id)
            if item is None:
                return None
            if only_if_missing and item.offer_price_usd is not None:
                session.expunge(item)
                return item
            item.offer_price_usd = clean_price
            item.offer_currency = clean_currency
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_automation_state(
        cls,
        client_id: str,
        *,
        automation_status: WorkstationAutomationStatus | str | None = None,
        status: WorkstationClientStatus | str | None = None,
        last_automation_handled_at: datetime | None = None,
        last_preview_sent_at: datetime | None = None,
        approved_at: datetime | None = None,
        ping_1_sent_at: datetime | None = None,
        ping_2_sent_at: datetime | None = None,
        handoff_sent_at: datetime | None = None,
    ) -> Optional["WorkstationClient"]:
        """Update automation fields for one Workstation client."""
        with Session(engine) as session:
            item = session.get(cls, client_id)
            if item is None:
                return None
            lead_id = item.lead_id
            if automation_status is not None:
                item.automation_status = normalize_workstation_automation_status(automation_status)
            if status is not None:
                item.status = normalize_workstation_client_status(status)
            if last_automation_handled_at is not None:
                item.last_automation_handled_at = last_automation_handled_at
            if last_preview_sent_at is not None:
                item.last_preview_sent_at = last_preview_sent_at
            if approved_at is not None:
                item.approved_at = approved_at
            if ping_1_sent_at is not None:
                item.ping_1_sent_at = ping_1_sent_at
            if ping_2_sent_at is not None:
                item.ping_2_sent_at = ping_2_sent_at
            if handoff_sent_at is not None:
                item.handoff_sent_at = handoff_sent_at
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            ContadoresLead.sync_lifecycle_fields(lead_id)
            return item

    @classmethod
    def update_notes(cls, client_id: str, *, notes: str) -> Optional["WorkstationClient"]:
        """Update meeting notes for one converted client."""
        with Session(engine) as session:
            item = session.get(cls, client_id)
            if item is None:
                return None
            item.notes = notes.strip()
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_status(
        cls,
        client_id: str,
        *,
        status: WorkstationClientStatus | str,
    ) -> Optional["WorkstationClient"]:
        """Update one converted client's status."""
        with Session(engine) as session:
            item = session.get(cls, client_id)
            if item is None:
                return None
            lead_id = item.lead_id
            item.status = normalize_workstation_client_status(status)
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            ContadoresLead.sync_lifecycle_fields(lead_id)
            return item

    @classmethod
    def update_codex_workstation_thread_id(
        cls,
        client_id: str,
        *,
        thread_id: str | None,
    ) -> Optional["WorkstationClient"]:
        """Persist the Codex Workstation thread used for one client."""
        with Session(engine) as session:
            item = session.get(cls, client_id)
            if item is None:
                return None
            item.codex_workstation_thread_id = (thread_id or "").strip() or None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item


def build_workstation_public_page_token() -> str:
    """Return an unguessable token for a Workstation trial page."""
    return secrets.token_urlsafe(24)


class WorkstationPublicPage(SQLModel, table=True):
    """Stable public trial URL for one Workstation solo-page client."""

    __tablename__ = "workstation_public_pages"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_workstation_public_pages_client_id"),
        UniqueConstraint("public_token", name="uq_workstation_public_pages_public_token"),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(foreign_key="workstation_clients.id", index=True)
    public_token: str = Field(default_factory=build_workstation_public_page_token, index=True)
    current_version: str = Field(default="", index=True)
    version_path: str = Field(default="")
    status: str = Field(default="active", index=True)
    first_published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    last_sent_at: datetime | None = Field(default=None, index=True)

    @classmethod
    def get_by_client_id(cls, client_id: str) -> Optional["WorkstationPublicPage"]:
        """Get the public page row for one Workstation client."""
        clean_client_id = (client_id or "").strip()
        if not clean_client_id:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.client_id == clean_client_id).limit(1)
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_active_by_token(cls, public_token: str) -> Optional["WorkstationPublicPage"]:
        """Get one active public page by its unguessable token."""
        clean_token = (public_token or "").strip()
        if not clean_token:
            return None
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.public_token == clean_token)
                .where(cls.status == "active")
                .limit(1)
            )
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def create_or_update_for_client(
        cls,
        *,
        client_id: str,
        current_version: str,
        version_path: str,
    ) -> "WorkstationPublicPage":
        """Create or move the stable public URL to the latest page version."""
        now = datetime.now(timezone.utc)
        clean_client_id = (client_id or "").strip()
        clean_version = (current_version or "").strip()
        clean_path = (version_path or "").strip()
        with Session(engine) as session:
            statement = select(cls).where(cls.client_id == clean_client_id).limit(1)
            item = session.exec(statement).first()
            if item is None:
                item = cls(
                    client_id=clean_client_id,
                    public_token=build_workstation_public_page_token(),
                    current_version=clean_version,
                    version_path=clean_path,
                    first_published_at=now,
                    updated_at=now,
                )
            else:
                item.current_version = clean_version
                item.version_path = clean_path
                item.status = "active"
                item.updated_at = now
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def mark_sent(cls, client_id: str, *, sent_at: datetime | None = None) -> Optional["WorkstationPublicPage"]:
        """Persist when the public URL was last sent to the client."""
        clean_client_id = (client_id or "").strip()
        if not clean_client_id:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.client_id == clean_client_id).limit(1)
            item = session.exec(statement).first()
            if item is None:
                return None
            item.last_sent_at = sent_at or datetime.now(timezone.utc)
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item


class WorkstationMediaAsset(SQLModel, table=True):
    """One file attached to a converted client profile."""

    __tablename__ = "workstation_media_assets"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    client_id: str = Field(foreign_key="workstation_clients.id", index=True)
    title: str = Field(default="")
    original_filename: str = Field(default="")
    stored_filename: str = Field(default="")
    stored_path: str = Field(default="")
    content_type: str | None = Field(default=None)
    size_bytes: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def list_by_client(cls, client_id: str) -> list["WorkstationMediaAsset"]:
        """List media files for one Workstation client."""
        with Session(engine) as session:
            statement = select(cls).where(cls.client_id == client_id).order_by(cls.created_at.desc(), cls.id.desc())
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def get_by_id(cls, asset_id: str) -> Optional["WorkstationMediaAsset"]:
        """Get one media asset by ID."""
        with Session(engine) as session:
            item = session.get(cls, asset_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def create(
        cls,
        *,
        client_id: str,
        asset_id: str,
        title: str,
        original_filename: str,
        stored_filename: str,
        stored_path: str,
        content_type: str | None,
        size_bytes: int,
    ) -> "WorkstationMediaAsset":
        """Persist one media asset row."""
        with Session(engine) as session:
            row = cls(
                id=asset_id,
                client_id=client_id,
                title=(title or "").strip(),
                original_filename=(original_filename or "").strip(),
                stored_filename=(stored_filename or "").strip(),
                stored_path=(stored_path or "").strip(),
                content_type=(content_type or "").strip() or None,
                size_bytes=max(0, int(size_bytes)),
            )
            session.add(row)
            client = session.get(WorkstationClient, client_id)
            if client:
                client.updated_at = datetime.now(timezone.utc)
                session.add(client)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def update_metadata(cls, asset_id: str, *, title: str, original_filename: str) -> Optional["WorkstationMediaAsset"]:
        """Update the operator-facing media labels."""
        with Session(engine) as session:
            row = session.get(cls, asset_id)
            if row is None:
                return None
            row.title = (title or "").strip()
            row.original_filename = (original_filename or "").strip()
            client = session.get(WorkstationClient, row.client_id)
            if client:
                client.updated_at = datetime.now(timezone.utc)
                session.add(client)
            session.add(row)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def delete(cls, asset_id: str) -> Optional["WorkstationMediaAsset"]:
        """Delete one media asset row and return its detached data."""
        with Session(engine) as session:
            row = session.get(cls, asset_id)
            if row is None:
                return None
            copy = cls.model_validate(row)
            client = session.get(WorkstationClient, row.client_id)
            if client:
                client.updated_at = datetime.now(timezone.utc)
                session.add(client)
            session.delete(row)
            session.commit()
            return copy


class Company(SQLModel, table=True):
    """Top-level company record."""

    __tablename__ = "companies"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    source_url: str
    normalized_source_url: str = Field(default="", index=True)
    company_name: str
    company_info: str = Field(default="")
    website_markdown: str = Field(default="")
    tags_json: str = Field(default="[]")
    ceo_email: str | None = Field(default=None)
    company_size: str = Field(default="unknown")
    industry: str = Field(default="unknown")
    language: CompanyLanguage | None = Field(
        default=None,
        sa_column=Column(
            SQLAlchemyEnum(
                CompanyLanguage,
                values_callable=lambda enum_cls: [item.value for item in enum_cls],
                native_enum=False,
                name="company_language",
            ),
            nullable=True,
        ),
    )
    objective: Optional[str] = Field(default=None)
    conversation_automation_enabled: bool = Field(default=False, index=True)
    ceo_delivery_enabled: bool = Field(default=False, index=True)
    report_window_hours: int = Field(default=DEFAULT_REPORT_WINDOW_HOURS)
    report_scheduled_send_at: datetime | None = Field(default=None, index=True)
    ceo_delivery_sent_at: datetime | None = Field(default=None)
    ceo_delivery_thread_id: str | None = Field(default=None, index=True)
    ceo_delivery_external_id: str | None = Field(default=None, index=True)
    ceo_delivery_rfc_message_id: str | None = Field(default=None, index=True)
    ceo_delivery_blocked_reason: str | None = Field(default=None)
    ceo_delivery_blocked_at: datetime | None = Field(default=None)
    status: CompanyStatus = Field(default=CompanyStatus.ACTIVE, index=True)
    report_snapshot_json: str | None = Field(default=None)
    report_pdf_model_json: str | None = Field(default=None)
    report_html: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def tags(self) -> list[str]:
        """Return normalized operator tags for this company."""
        return deserialize_company_tags(self.tags_json)

    @classmethod
    def create(
        cls,
        *,
        source_url: str,
        company_name: str,
        company_info: str = "",
        website_markdown: str = "",
        tags: list[str] | None = None,
        ceo_email: str | None = None,
        company_size: str = "unknown",
        industry: str = "unknown",
        language: CompanyLanguage | str | None = None,
        objective: Optional[str] = None,
        conversation_automation_enabled: bool = False,
        ceo_delivery_enabled: bool = False,
        report_window_hours: int = DEFAULT_REPORT_WINDOW_HOURS,
        report_window_minutes: int | None = None,
        report_scheduled_send_at: datetime | None = None,
        status: CompanyStatus | str = CompanyStatus.ACTIVE,
    ) -> "Company":
        """Create one company."""
        with Session(engine) as session:
            created_at_now = datetime.now(timezone.utc)
            normalized_report_window_minutes = normalize_report_window_minutes(
                report_window_minutes,
                report_window_hours=report_window_hours,
            )
            stored_source_url = normalize_company_source_url(source_url) or source_url.strip()
            normalized_source_url = normalize_company_source_url_key(stored_source_url)
            normalized_company_info = company_info.strip()
            normalized_website_markdown = website_markdown.strip()
            normalized_status = (
                status
                if isinstance(status, CompanyStatus)
                else CompanyStatus((status or CompanyStatus.ACTIVE.value).strip().lower())
            )
            item = cls(
                source_url=stored_source_url,
                normalized_source_url=normalized_source_url,
                company_name=company_name.strip() or "Unknown company",
                company_info=normalized_company_info,
                website_markdown=normalized_website_markdown,
                tags_json=serialize_company_tags(tags),
                ceo_email=(normalize_email(ceo_email) or None) if ceo_email else None,
                company_size=normalize_company_size(company_size),
                industry=normalize_company_industry(industry),
                language=normalize_company_language(language),
                objective=(objective.strip() if objective else None),
                conversation_automation_enabled=conversation_automation_enabled,
                ceo_delivery_enabled=ceo_delivery_enabled,
                report_window_hours=legacy_report_window_hours_from_minutes(normalized_report_window_minutes),
                report_scheduled_send_at=compute_report_scheduled_send_at(
                    created_at_now,
                    report_window_minutes=normalized_report_window_minutes,
                    report_scheduled_send_at=report_scheduled_send_at,
                ),
                status=normalized_status,
                created_at=created_at_now,
                updated_at=created_at_now,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def get_by_id(cls, company_id: str) -> Optional["Company"]:
        """Get one company by ID."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_most_recent_by_normalized_source_url(
        cls,
        source_url: str,
        *,
        include_failed: bool = False,
    ) -> Optional["Company"]:
        """Get the latest company that matches one normalized scan URL."""
        normalized_source_url = normalize_company_source_url_key(source_url)
        if not normalized_source_url:
            return None

        with Session(engine) as session:
            statement = select(cls).where(cls.normalized_source_url == normalized_source_url)
            if not include_failed:
                statement = statement.where(cls.status != CompanyStatus.FAILED)
            statement = statement.order_by(cls.updated_at.desc(), cls.created_at.desc(), cls.id.desc())
            item = session.exec(statement.limit(1)).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_recent(cls, limit: int = 100) -> list["Company"]:
        """List companies ordered by most recent update."""
        with Session(engine) as session:
            statement = select(cls).order_by(cls.updated_at.desc()).limit(limit)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_conversation_automation_enabled_ids(
        cls,
        *,
        company_ids: set[str] | None = None,
    ) -> set[str]:
        """List company IDs where conversation automation is enabled."""
        cleaned_ids = (
            {value.strip() for value in company_ids if value and value.strip()}
            if company_ids is not None
            else None
        )
        if cleaned_ids is not None and not cleaned_ids:
            return set()

        with Session(engine) as session:
            statement = select(cls.id).where(cls.conversation_automation_enabled.is_(True))
            if cleaned_ids is not None:
                statement = statement.where(cls.id.in_(cleaned_ids))
            return set(session.exec(statement).all())

    @classmethod
    def list_ceo_delivery_tracked_senders(cls) -> set[str]:
        """List CEO emails for companies that already received an audit delivery email."""
        with Session(engine) as session:
            statement = select(cls.ceo_email).where(
                cls.ceo_delivery_sent_at.is_not(None),
                cls.ceo_delivery_thread_id.is_not(None),
                cls.ceo_email.is_not(None),
            )
            rows = session.exec(statement).all()
            return {
                normalize_email(value)
                for value in rows
                if value and normalize_email(value)
            }

    @classmethod
    def list_by_ceo_delivery_thread_id(cls, thread_id: str) -> list["Company"]:
        """List companies that match one CEO delivery thread id."""
        clean_thread_id = (thread_id or "").strip()
        if not clean_thread_id:
            return []
        with Session(engine) as session:
            statement = select(cls).where(cls.ceo_delivery_thread_id == clean_thread_id)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    def get_contacts(self, include_archived: bool = False) -> list["Contact"]:
        """List contacts for this company.

        By default only active contacts are returned. Set include_archived=True to
        include archived contacts instead.
        """
        with Session(engine) as session:
            statement = select(Contact).where(Contact.company_id == self.id)
            if not include_archived:
                statement = statement.where(Contact.status == ContactStatus.ACTIVE)
            statement = statement.order_by(Contact.created_at)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    def count_contacts(self, include_archived: bool = False) -> int:
        """Count contacts for this company. Defaults to active only."""
        return len(self.get_contacts(include_archived=include_archived))

    def list_reportable_contacts(self, include_archived: bool = False) -> list["Contact"]:
        """List contacts eligible for reports and audit delivery copy."""
        allowed_contact_types = {"email", "whatsapp"}
        return [
            contact
            for contact in self.get_contacts(include_archived=include_archived)
            if not contact.is_archived
            and contact.canonical_type in allowed_contact_types
            and Message.has_delivered_outbound_for_contact(contact.id)
        ]

    def build_reportable_contact_lines(self, include_archived: bool = False) -> str:
        """Build deterministic contact lines from reportable contacts only."""
        unique_lines: list[str] = []
        for item in self.list_reportable_contacts(include_archived=include_archived):
            line = f"- {item.canonical_type}: {item.value.strip()}"
            if line not in unique_lines:
                unique_lines.append(line)
        return "\n".join(unique_lines[:8])

    def build_reportable_objective_lines(self, include_archived: bool = False) -> str:
        """Build deterministic objective lines from reportable contacts only."""
        unique_lines: list[str] = []
        for item in self.list_reportable_contacts(include_archived=include_archived):
            objective = (item.objective or self.objective or "").strip()
            if not objective:
                continue
            line = f"- {item.value.strip()}: {objective}"
            if line not in unique_lines:
                unique_lines.append(line)
        return "\n".join(unique_lines[:8])

    def to_llm_info(self, include_archived: bool = False) -> CompanyLLMInfo:
        """Build complete Stage 3 report context from this company and its contacts."""
        contacts = self.list_reportable_contacts(include_archived=include_archived)
        return CompanyLLMInfo(
            company_name=self.company_name,
            source_url=self.source_url,
            company_info=self.company_info,
            ceo_email=self.ceo_email,
            objective=self.objective,
            contacts=[
                contact.to_llm_info(default_objective=self.objective)
                for contact in contacts
            ],
        )

    @classmethod
    def update_status(cls, company_id: str, status: CompanyStatus) -> None:
        """Update one company status."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item:
                return
            item.status = status
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()

    @classmethod
    def update(
        cls,
        company_id: str,
        *,
        company_name: str | None = None,
        company_info: str | None = None,
        website_markdown: str | None = None,
        ceo_email: str | None = None,
        company_size: str | None = None,
        industry: str | None = None,
        language: CompanyLanguage | str | None = None,
        objective: str | None = None,
        tags: list[str] | None = None,
        conversation_automation_enabled: bool | None = None,
        ceo_delivery_enabled: bool | None = None,
        report_window_hours: int | None = None,
        report_window_minutes: int | None = None,
        report_scheduled_send_at: datetime | None = None,
        update_ceo_email: bool = False,
    ) -> None:
        """Update company fields."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item:
                return
            if company_name is not None:
                item.company_name = company_name.strip() or item.company_name
            if company_info is not None:
                item.company_info = company_info.strip()
            if website_markdown is not None:
                item.website_markdown = website_markdown.strip()
            if update_ceo_email:
                normalized_ceo_email = (normalize_email(ceo_email) or None) if ceo_email else None
                item.ceo_email = normalized_ceo_email
                if (
                    normalized_ceo_email
                    and (item.ceo_delivery_blocked_reason or "").strip() == "missing_ceo_email"
                ):
                    item.ceo_delivery_blocked_reason = None
                    item.ceo_delivery_blocked_at = None
            if company_size is not None:
                item.company_size = normalize_company_size(company_size)
            if industry is not None:
                item.industry = normalize_company_industry(industry)
            if language is not None:
                item.language = normalize_company_language(language)
            if objective is not None:
                item.objective = objective.strip() or None
            if tags is not None:
                item.tags_json = serialize_company_tags(tags)
            if conversation_automation_enabled is not None:
                item.conversation_automation_enabled = conversation_automation_enabled
            if ceo_delivery_enabled is not None:
                item.ceo_delivery_enabled = ceo_delivery_enabled
            if (
                report_window_hours is not None
                or report_window_minutes is not None
                or report_scheduled_send_at is not None
            ):
                if report_scheduled_send_at is not None:
                    item.report_scheduled_send_at = normalize_schedule_datetime(report_scheduled_send_at)
                    resolved_minutes = compute_report_window_minutes(
                        item.created_at,
                        report_scheduled_send_at=item.report_scheduled_send_at,
                        report_window_hours=report_window_hours or item.report_window_hours,
                    )
                else:
                    resolved_minutes = normalize_report_window_minutes(
                        report_window_minutes,
                        report_window_hours=report_window_hours or item.report_window_hours,
                    )
                    item.report_scheduled_send_at = compute_report_scheduled_send_at(
                        item.created_at,
                        report_window_minutes=resolved_minutes,
                    )
                item.report_window_hours = legacy_report_window_hours_from_minutes(resolved_minutes)
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()

    @classmethod
    def mark_ceo_delivery_delivered(
        cls,
        company_id: str,
        *,
        thread_id: str,
        external_id: str,
        rfc_message_id: str | None = None,
        delivered_at: datetime | None = None,
    ) -> None:
        """Persist successful CEO delivery metadata for one company."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item:
                return
            now = datetime.now(timezone.utc)
            item.ceo_delivery_sent_at = delivered_at or now
            item.ceo_delivery_thread_id = thread_id.strip() or None
            item.ceo_delivery_external_id = external_id.strip() or None
            item.ceo_delivery_rfc_message_id = (rfc_message_id or "").strip() or None
            item.ceo_delivery_blocked_reason = None
            item.ceo_delivery_blocked_at = None
            item.updated_at = now
            session.add(item)
            session.commit()

    @classmethod
    def mark_ceo_delivery_blocked(cls, company_id: str, reason: str) -> None:
        """Mark one company as blocked for CEO delivery."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item:
                return
            if item.ceo_delivery_blocked_reason:
                return
            now = datetime.now(timezone.utc)
            item.ceo_delivery_blocked_reason = reason.strip() or "blocked"
            item.ceo_delivery_blocked_at = now
            item.updated_at = now
            session.add(item)
            session.commit()

    @classmethod
    def update_report_snapshot(cls, company_id: str, snapshot_json: str | None) -> None:
        """Persist or clear report snapshot JSON for one company."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item:
                return
            item.report_snapshot_json = snapshot_json.strip() if snapshot_json else None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()

    @classmethod
    def update_report_pdf_model(cls, company_id: str, model_json: str | None) -> None:
        """Persist or clear render-ready PDF model JSON for one company."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item:
                return
            item.report_pdf_model_json = model_json.strip() if model_json else None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()

    @classmethod
    def update_report_html(cls, company_id: str, html: str | None) -> None:
        """Persist or clear rendered report HTML for one company."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item:
                return
            item.report_html = html if html else None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()

    @classmethod
    def get_report_snapshot(cls, company_id: str):
        """Return the legacy report snapshot JSON for one company, if available."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item or not item.report_snapshot_json:
                return None
            raw_snapshot = item.report_snapshot_json

        try:
            return json.loads(raw_snapshot)
        except Exception:
            logger.exception("Failed parsing report snapshot for company_id=%s", company_id)
            return None

    @classmethod
    def get_report_pdf_model(cls, company_id: str):
        """Return the legacy report PDF model JSON for one company, if available."""
        with Session(engine) as session:
            item = session.get(cls, company_id)
            if not item or not item.report_pdf_model_json:
                return None
            raw_model = item.report_pdf_model_json

        try:
            return json.loads(raw_model)
        except Exception:
            logger.exception("Failed parsing report PDF model for company_id=%s", company_id)
            return None

    @classmethod
    def delete(cls, company_id: str) -> None:
        """Delete one company and all related contacts/messages."""
        with Session(engine) as session:
            company = session.get(cls, company_id)
            if not company:
                return

            contacts = list(
                session.exec(select(Contact).where(Contact.company_id == company_id)).all()
            )
            contact_ids = [contact.id for contact in contacts]
            for contact in contacts:
                session.delete(contact)

            if contact_ids:
                messages = list(
                    session.exec(
                        select(Message).where(Message.contact_id.in_(contact_ids))
                    ).all()
                )
                for message in messages:
                    session.delete(message)

            crm_threads = list(
                session.exec(select(CrmThread).where(CrmThread.company_id == company_id)).all()
            )
            crm_thread_ids = [thread.id for thread in crm_threads if thread.id]
            if crm_thread_ids:
                crm_messages = list(
                    session.exec(
                        select(CrmEmailMessage).where(CrmEmailMessage.thread_id.in_(crm_thread_ids))
                    ).all()
                )
                for message in crm_messages:
                    session.delete(message)
            for thread in crm_threads:
                session.delete(thread)

            task_rows = list(
                session.exec(select(Task).where(Task.resource_id == company_id)).all()
            )
            for task in task_rows:
                session.delete(task)

            session.delete(company)
            session.commit()


class CrmThread(SQLModel, table=True):
    """One CRM email conversation thread with one CEO or founder."""

    __tablename__ = "crm_threads"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="companies.id", index=True)
    participant_email: str
    subject: str
    gmail_thread_id: str | None = Field(default=None, index=True)
    last_read_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        *,
        company_id: str,
        participant_email: str,
        subject: str,
        gmail_thread_id: str | None = None,
        last_read_at: datetime | None = None,
    ) -> "CrmThread":
        """Create one CRM thread."""
        with Session(engine) as session:
            now = datetime.now(timezone.utc)
            normalized_participant_email = normalize_email(participant_email)
            if not normalized_participant_email:
                raise ValueError("participant_email is invalid")
            item = cls(
                company_id=company_id,
                participant_email=normalized_participant_email,
                subject=subject.strip(),
                gmail_thread_id=(gmail_thread_id.strip() if gmail_thread_id else None),
                last_read_at=last_read_at,
                created_at=now,
                updated_at=now,
            )
            session.add(item)
            company = session.get(Company, company_id)
            if company:
                company.updated_at = now
                session.add(company)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def get_by_id(cls, thread_id: str) -> Optional["CrmThread"]:
        """Get one CRM thread by ID."""
        with Session(engine) as session:
            item = session.get(cls, thread_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_by_gmail_thread_id(cls, gmail_thread_id: str) -> Optional["CrmThread"]:
        """Get one CRM thread by Gmail thread id."""
        clean_thread_id = (gmail_thread_id or "").strip()
        if not clean_thread_id:
            return None
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.gmail_thread_id == clean_thread_id)
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(1)
            )
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_recent(cls, *, limit: int = 500) -> list["CrmThread"]:
        """List CRM threads ordered by latest update."""
        with Session(engine) as session:
            statement = select(cls).order_by(cls.updated_at.desc(), cls.id.desc()).limit(limit)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_tracked_participant_emails(cls) -> set[str]:
        """List participant emails for threads that already have a Gmail thread id."""
        with Session(engine) as session:
            statement = select(cls.participant_email).where(
                cls.gmail_thread_id.is_not(None),
                cls.participant_email.is_not(None),
            )
            rows = session.exec(statement).all()
            return {
                normalize_email(value)
                for value in rows
                if value and normalize_email(value)
            }

    @classmethod
    def update_gmail_thread_id(
        cls,
        thread_id: str,
        *,
        gmail_thread_id: str | None,
    ) -> Optional["CrmThread"]:
        """Update Gmail thread id for one CRM thread."""
        with Session(engine) as session:
            item = session.get(cls, thread_id)
            if not item:
                return None
            item.gmail_thread_id = (gmail_thread_id or "").strip() or None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_last_read_at(
        cls,
        thread_id: str,
        *,
        read_at: datetime | None = None,
    ) -> Optional["CrmThread"]:
        """Mark one CRM thread as read."""
        with Session(engine) as session:
            item = session.get(cls, thread_id)
            if not item:
                return None
            item.last_read_at = read_at or datetime.now(timezone.utc)
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def touch(
        cls,
        thread_id: str,
        *,
        updated_at: datetime | None = None,
    ) -> Optional["CrmThread"]:
        """Refresh one CRM thread updated timestamp."""
        with Session(engine) as session:
            item = session.get(cls, thread_id)
            if not item:
                return None
            item.updated_at = updated_at or datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item


class CrmEmailMessage(SQLModel, table=True):
    """One message inside one CRM email thread."""

    __tablename__ = "crm_email_messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    thread_id: str = Field(foreign_key="crm_threads.id", index=True)
    direction: CrmMessageDirection = Field(index=True)
    kind: CrmMessageKind = Field(index=True)
    body: str
    subject: str
    from_email: str | None = Field(default=None)
    to_email: str | None = Field(default=None)
    gmail_message_id: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True, unique=True, index=True),
    )
    rfc_message_id: str | None = Field(default=None, index=True)
    in_reply_to: str | None = Field(default=None)
    references: str | None = Field(default=None)
    status: CrmMessageStatus = Field(index=True)
    sent_at: datetime | None = Field(default=None)
    received_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        thread_id: str,
        direction: CrmMessageDirection | str,
        kind: CrmMessageKind | str,
        body: str,
        subject: str,
        from_email: str | None = None,
        to_email: str | None = None,
        gmail_message_id: str | None = None,
        rfc_message_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        status: CrmMessageStatus | str,
        sent_at: datetime | None = None,
        received_at: datetime | None = None,
        created_at: datetime | None = None,
    ) -> "CrmEmailMessage":
        """Persist one CRM email message."""
        with Session(engine) as session:
            now = created_at or datetime.now(timezone.utc)
            row = cls(
                thread_id=thread_id,
                direction=cls.normalize_direction(direction),
                kind=cls.normalize_kind(kind),
                body=body.strip(),
                subject=subject.strip(),
                from_email=(normalize_email(from_email) or None) if from_email else None,
                to_email=(normalize_email(to_email) or None) if to_email else None,
                gmail_message_id=(gmail_message_id or "").strip() or None,
                rfc_message_id=(rfc_message_id or "").strip() or None,
                in_reply_to=(in_reply_to or "").strip() or None,
                references=(references or "").strip() or None,
                status=cls.normalize_status(status),
                sent_at=sent_at,
                received_at=received_at,
                created_at=now,
            )
            session.add(row)
            thread = session.get(CrmThread, thread_id)
            if thread:
                thread.updated_at = now
                session.add(thread)
                company = session.get(Company, thread.company_id)
                if company:
                    company.updated_at = now
                    session.add(company)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def normalize_direction(cls, direction: CrmMessageDirection | str) -> CrmMessageDirection:
        """Normalize raw CRM message direction."""
        if isinstance(direction, CrmMessageDirection):
            return direction
        value = (direction or "").strip().lower()
        if value == CrmMessageDirection.INBOUND.value:
            return CrmMessageDirection.INBOUND
        return CrmMessageDirection.OUTBOUND

    @classmethod
    def normalize_kind(cls, kind: CrmMessageKind | str) -> CrmMessageKind:
        """Normalize raw CRM message kind."""
        if isinstance(kind, CrmMessageKind):
            return kind
        value = (kind or "").strip().lower()
        if value == CrmMessageKind.REPORT_DELIVERY.value:
            return CrmMessageKind.REPORT_DELIVERY
        if value == CrmMessageKind.CEO_REPLY.value:
            return CrmMessageKind.CEO_REPLY
        return CrmMessageKind.MANUAL_REPLY

    @classmethod
    def normalize_status(cls, status: CrmMessageStatus | str) -> CrmMessageStatus:
        """Normalize raw CRM message status."""
        if isinstance(status, CrmMessageStatus):
            return status
        value = (status or "").strip().lower()
        if value == CrmMessageStatus.SENT.value:
            return CrmMessageStatus.SENT
        if value == CrmMessageStatus.RECEIVED.value:
            return CrmMessageStatus.RECEIVED
        return CrmMessageStatus.PENDING

    @classmethod
    def get_by_id(cls, message_id: int) -> Optional["CrmEmailMessage"]:
        """Get one CRM message by ID."""
        with Session(engine) as session:
            item = session.get(cls, message_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_by_gmail_message_id(cls, gmail_message_id: str) -> Optional["CrmEmailMessage"]:
        """Get one CRM message by Gmail message id."""
        clean_message_id = (gmail_message_id or "").strip()
        if not clean_message_id:
            return None
        with Session(engine) as session:
            statement = select(cls).where(cls.gmail_message_id == clean_message_id)
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_by_thread(cls, thread_id: str) -> list["CrmEmailMessage"]:
        """List messages for one CRM thread."""
        with Session(engine) as session:
            statement = select(cls).where(cls.thread_id == thread_id).order_by(cls.created_at, cls.id)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_pending_outbound(cls, *, limit: int = 100) -> list["CrmEmailMessage"]:
        """List outbound CRM messages waiting for provider dispatch."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.direction == CrmMessageDirection.OUTBOUND,
                    cls.status == CrmMessageStatus.PENDING,
                )
                .order_by(cls.created_at, cls.id)
                .limit(limit)
            )
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def count_unread_inbound_for_thread(
        cls,
        *,
        thread_id: str,
        last_read_at: datetime | None,
    ) -> int:
        """Count unread inbound CRM messages for one thread."""
        with Session(engine) as session:
            statement = select(cls).where(
                cls.thread_id == thread_id,
                cls.direction == CrmMessageDirection.INBOUND,
                cls.status == CrmMessageStatus.RECEIVED,
            )
            rows = list(session.exec(statement).all())
            if last_read_at is None:
                return len(rows)
            return len(
                [
                    item
                    for item in rows
                    if (item.received_at or item.created_at) > last_read_at
                ]
            )

    @classmethod
    def get_latest_sent_outbound_for_thread(cls, thread_id: str) -> Optional["CrmEmailMessage"]:
        """Return latest sent outbound CRM message for one thread."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.thread_id == thread_id,
                    cls.direction == CrmMessageDirection.OUTBOUND,
                    cls.status == CrmMessageStatus.SENT,
                )
                .order_by(cls.sent_at.desc(), cls.created_at.desc(), cls.id.desc())
                .limit(1)
            )
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def mark_sent(
        cls,
        *,
        message_id: int,
        gmail_message_id: str,
        gmail_thread_id: str | None = None,
        rfc_message_id: str | None = None,
        from_email: str | None = None,
        sent_at: datetime | None = None,
    ) -> Optional["CrmEmailMessage"]:
        """Mark one outbound CRM message as sent."""
        with Session(engine) as session:
            row = session.get(cls, message_id)
            if not row:
                return None
            resolved_sent_at = sent_at or datetime.now(timezone.utc)
            row.status = CrmMessageStatus.SENT
            row.gmail_message_id = gmail_message_id.strip()
            row.rfc_message_id = (rfc_message_id or "").strip() or None
            if from_email is not None:
                row.from_email = (normalize_email(from_email) or None) if from_email else None
            row.sent_at = resolved_sent_at
            session.add(row)
            thread = session.get(CrmThread, row.thread_id)
            if thread:
                if gmail_thread_id is not None:
                    thread.gmail_thread_id = gmail_thread_id.strip() or None
                thread.updated_at = resolved_sent_at
                session.add(thread)
                company = session.get(Company, thread.company_id)
                if company:
                    company.updated_at = resolved_sent_at
                    session.add(company)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row


class Contact(SQLModel, table=True):
    """One contact channel inside one company."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "type",
            "normalized_value",
            name="uq_contacts_company_type_normalized_value",
        ),
    )

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    company_id: str = Field(foreign_key="companies.id", index=True)
    type: str
    value: str
    notes: Optional[str] = Field(default=None)
    additional_info: Optional[str] = Field(default=None)
    objective: Optional[str] = Field(default=None)
    conversation_done: bool = Field(default=False, index=True)
    email_subject: Optional[str] = Field(default=None)
    email_inbox_id: Optional[str] = Field(default=None, index=True)
    email_inbox_address: Optional[str] = Field(default=None)
    normalized_value: str = Field(default="", index=True)
    email_thread_id: Optional[str] = Field(default=None, index=True)
    email_last_outbound_rfc_id: Optional[str] = Field(default=None, index=True)
    status: ContactStatus = Field(default=ContactStatus.ACTIVE, index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def create(
        cls,
        *,
        company_id: str,
        type: str,
        value: str,
        notes: Optional[str] = None,
        additional_info: Optional[str] = None,
        objective: Optional[str] = None,
        conversation_done: bool = False,
        email_subject: Optional[str] = None,
        status: ContactStatus | str = ContactStatus.ACTIVE,
    ) -> "Contact":
        """Create one contact."""
        normalized_type = canonical_contact_type(type)
        normalized_value = value.strip()
        normalized_contact_value = normalize_contact_value(
            normalized_type,
            normalized_value,
        )
        if not normalized_contact_value:
            raise ValueError(f"Contact value is invalid for type {normalized_type}")

        existing_matches = [
            item
            for item in cls.list_by_normalized_value(normalized_contact_value, status=None)
            if item.company_id == company_id and canonical_contact_type(item.type) == normalized_type
        ]
        if existing_matches:
            return existing_matches[0]

        with Session(engine) as session:
            normalized_status = cls.normalize_status(status)
            item = cls(
                company_id=company_id,
                type=normalized_type,
                value=normalized_value,
                notes=(notes.strip() if notes else None),
                additional_info=(additional_info.strip() if additional_info else None),
                objective=(objective.strip() if objective else None),
                conversation_done=bool(conversation_done),
                email_subject=(email_subject.strip() if email_subject else None),
                normalized_value=normalized_contact_value,
                status=normalized_status,
            )
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def normalize_status(cls, status: ContactStatus | str | None) -> ContactStatus:
        """Normalize a raw status value to ContactStatus."""
        if isinstance(status, ContactStatus):
            return status
        value = (status or "").strip().lower()
        if value == ContactStatus.ARCHIVED.value:
            return ContactStatus.ARCHIVED
        return ContactStatus.ACTIVE

    @classmethod
    def get_by_id(cls, contact_id: str) -> Optional["Contact"]:
        """Get one contact by ID."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if item:
                session.expunge(item)
            return item

    @classmethod
    def get_by_email_inbox_id(cls, email_inbox_id: str) -> Optional["Contact"]:
        """Get one active contact by AgentMail inbox id."""
        clean_inbox_id = (email_inbox_id or "").strip()
        if not clean_inbox_id:
            return None
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.email_inbox_id == clean_inbox_id,
                    cls.status == ContactStatus.ACTIVE,
                )
                .order_by(cls.updated_at.desc(), cls.created_at.desc(), cls.id.desc())
                .limit(1)
            )
            item = session.exec(statement).first()
            if item:
                session.expunge(item)
            return item

    @classmethod
    def list_by_company(
        cls,
        company_id: str,
        *,
        status: ContactStatus | str | None = ContactStatus.ACTIVE,
    ) -> list["Contact"]:
        """List contacts for one company filtered by lifecycle status."""
        with Session(engine) as session:
            statement = select(cls).where(cls.company_id == company_id)
            normalized_status = cls.normalize_status(status)
            if status is not None:
                statement = statement.where(cls.status == normalized_status)
            statement = statement.order_by(cls.created_at)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_active(cls) -> list["Contact"]:
        """List all active contacts."""
        with Session(engine) as session:
            statement = select(cls).where(cls.status == ContactStatus.ACTIVE).order_by(cls.created_at)
            items = list(session.exec(statement).all())
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def list_by_normalized_value(
        cls,
        normalized_value: str,
        *,
        status: ContactStatus | str | None = ContactStatus.ACTIVE,
    ) -> list["Contact"]:
        """List contacts by normalized value."""
        normalized = (normalized_value or "").strip().lower()
        if not normalized:
            return []
        with Session(engine) as session:
            statement = select(cls).where(cls.normalized_value == normalized)
            if status is not None:
                statement = statement.where(cls.status == cls.normalize_status(status))
            statement = statement.order_by(cls.created_at, cls.id)
            items = list(session.exec(statement).all())
            if not items:
                fallback_statement = select(cls)
                if status is not None:
                    fallback_statement = fallback_statement.where(cls.status == cls.normalize_status(status))
                fallback_statement = fallback_statement.order_by(cls.created_at, cls.id)
                items = [
                    item
                    for item in session.exec(fallback_statement).all()
                    if normalize_contact_value(item.canonical_type, item.value) == normalized
                ]
            for item in items:
                session.expunge(item)
            return items

    @classmethod
    def count_by_company(
        cls,
        company_id: str,
        *,
        status: ContactStatus | str | None = ContactStatus.ACTIVE,
    ) -> int:
        """Count contacts for one company filtered by lifecycle status."""
        return len(cls.list_by_company(company_id, status=status))

    @classmethod
    def update_additional_info(cls, contact_id: str, additional_info: str | None) -> Optional["Contact"]:
        """Update additional info for one contact."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if not item:
                return None
            item.additional_info = additional_info.strip() if additional_info else None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_objective(cls, contact_id: str, objective: str | None) -> Optional["Contact"]:
        """Update one contact objective."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if not item:
                return None
            item.objective = objective.strip() if objective else None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_conversation_done(cls, contact_id: str, conversation_done: bool) -> Optional["Contact"]:
        """Update automated conversation completion state for one contact."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if not item:
                return None
            item.conversation_done = bool(conversation_done)
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_email_subject(cls, contact_id: str, email_subject: str | None) -> Optional["Contact"]:
        """Update first outbound email subject for one contact."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if not item:
                return None
            item.email_subject = email_subject.strip() if email_subject else None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_email_delivery_state(
        cls,
        contact_id: str,
        *,
        email_inbox_id: str | None = None,
        email_inbox_address: str | None = None,
        email_thread_id: str | None = None,
        email_last_outbound_rfc_id: str | None = None,
    ) -> Optional["Contact"]:
        """Update AgentMail inbox and thread metadata for one contact."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if not item:
                return None
            if email_inbox_id is not None:
                item.email_inbox_id = email_inbox_id.strip() or None
            if email_inbox_address is not None:
                item.email_inbox_address = normalize_email(email_inbox_address) or None
            if email_thread_id is not None:
                item.email_thread_id = email_thread_id.strip() or None
            if email_last_outbound_rfc_id is not None:
                item.email_last_outbound_rfc_id = email_last_outbound_rfc_id.strip() or None
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def update_status(
        cls,
        contact_id: str,
        status: ContactStatus | str,
    ) -> Optional["Contact"]:
        """Update lifecycle status for one contact."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if not item:
                return None
            normalized_status = cls.normalize_status(status)
            item.status = normalized_status
            item.updated_at = datetime.now(timezone.utc)
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item

    @classmethod
    def delete_by_id(cls, contact_id: str) -> bool:
        """Delete one contact and all related messages by contact ID."""
        with Session(engine) as session:
            item = session.get(cls, contact_id)
            if not item:
                return False

            rows = list(session.exec(select(Message).where(Message.contact_id == contact_id)).all())
            for row in rows:
                session.delete(row)

            company = session.get(Company, item.company_id)
            if company:
                company.updated_at = datetime.now(timezone.utc)
                session.add(company)

            session.delete(item)
            session.commit()
            return True

    @property
    def is_archived(self) -> bool:
        """Return True when this contact is archived."""
        return self.status == ContactStatus.ARCHIVED

    @property
    def canonical_type(self) -> str:
        """Return canonical channel type for this contact."""
        return canonical_contact_type(self.type)

    @property
    def is_email(self) -> bool:
        """Return True when this contact channel is email."""
        return self.canonical_type == "email"

    @property
    def is_whatsapp(self) -> bool:
        """Return True when this contact channel is whatsapp."""
        return self.canonical_type == "whatsapp"

    @overload
    def get_messages(self, *, simple: Literal[False] = False) -> list["Message"]: ...

    @overload
    def get_messages(self, *, simple: Literal[True]) -> list[ConversationMessage]: ...

    def get_messages(self, *, simple: bool = False) -> list["Message"] | list[ConversationMessage]:
        """List contact messages in full DB shape or simple stage-friendly shape."""
        rows = Message.list_by_contact(self.id)
        if not simple:
            return rows
        return [
            ConversationMessage(
                from_me=row.from_me,
                text=row.text,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

    def to_llm_info(self, default_objective: str | None = None) -> ContactLLMInfo:
        """Build complete Stage 3 report context for this contact."""
        conversation = self.get_messages(simple=True)
        return ContactLLMInfo(
            contact_type=self.canonical_type,
            contact_value=self.value,
            objective=(self.objective or default_objective or "").strip() or None,
            conversation_done=self.conversation_done,
            notes=self.notes,
            additional_context=self.additional_info,
            stats=compute_contact_conversation_stats(conversation),
            conversation=conversation,
        )


class Message(SQLModel, table=True):
    """Stored contact turn (inbound or outbound)."""

    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    contact_id: str = Field(foreign_key="contacts.id", index=True)
    from_me: bool
    text: str
    delivery_status: MessageDeliveryStatus = Field(default=MessageDeliveryStatus.DELIVERED, index=True)
    external_id: Optional[str] = Field(default=None, index=True)
    dispatch_after: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def add(
        cls,
        *,
        contact_id: str,
        from_me: bool,
        text: str,
        external_id: Optional[str] = None,
        delivery_status: MessageDeliveryStatus | str | None = None,
        dispatch_after: datetime | None = None,
    ) -> "Message":
        """Persist one message."""
        with Session(engine) as session:
            timestamp_now = datetime.now(timezone.utc)
            effective_dispatch_after = dispatch_after or timestamp_now
            if effective_dispatch_after.tzinfo is None:
                effective_dispatch_after = effective_dispatch_after.replace(tzinfo=timezone.utc)
            normalized_delivery = cls.normalize_delivery_status(
                delivery_status,
                from_me=from_me,
            )
            row = cls(
                contact_id=contact_id,
                from_me=from_me,
                text=text,
                delivery_status=normalized_delivery,
                external_id=(external_id.strip() if external_id else None),
                dispatch_after=effective_dispatch_after,
                timestamp=timestamp_now,
            )
            session.add(row)
            contact = session.get(Contact, contact_id)
            if contact:
                contact.updated_at = datetime.now(timezone.utc)
                session.add(contact)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def get_by_external_id(
        cls,
        *,
        contact_id: str,
        external_id: str,
        from_me: bool | None = None,
    ) -> Optional["Message"]:
        """Find one message by contact and external provider ID."""
        with Session(engine) as session:
            statement = select(cls).where(
                cls.contact_id == contact_id,
                cls.external_id == external_id,
            )
            if from_me is not None:
                statement = statement.where(cls.from_me.is_(from_me))
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def list_by_external_id(
        cls,
        external_id: str,
        *,
        from_me: bool | None = None,
    ) -> list["Message"]:
        """List messages by external provider ID, optionally filtered by direction."""
        clean_external_id = (external_id or "").strip()
        if not clean_external_id:
            return []
        with Session(engine) as session:
            statement = select(cls).where(cls.external_id == clean_external_id)
            if from_me is not None:
                statement = statement.where(cls.from_me.is_(from_me))
            statement = statement.order_by(cls.timestamp.desc(), cls.id.desc())
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def get_by_id_for_contact(
        cls,
        *,
        contact_id: str,
        message_id: int,
    ) -> Optional["Message"]:
        """Get one message scoped to one contact."""
        with Session(engine) as session:
            statement = select(cls).where(
                cls.id == message_id,
                cls.contact_id == contact_id,
            )
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def normalize_delivery_status(
        cls,
        delivery_status: MessageDeliveryStatus | str | None,
        *,
        from_me: bool,
    ) -> MessageDeliveryStatus:
        """Normalize raw delivery status with safe defaults by message direction."""
        if not from_me:
            return MessageDeliveryStatus.DELIVERED
        if isinstance(delivery_status, MessageDeliveryStatus):
            return delivery_status
        if isinstance(delivery_status, str):
            value = delivery_status.strip().lower()
            if value == MessageDeliveryStatus.UNDELIVERED.value:
                return MessageDeliveryStatus.UNDELIVERED
            if value == MessageDeliveryStatus.SENT.value:
                return MessageDeliveryStatus.SENT
            if value == MessageDeliveryStatus.DELIVERED.value:
                return MessageDeliveryStatus.DELIVERED
            if value == MessageDeliveryStatus.FAILED.value:
                return MessageDeliveryStatus.FAILED
        return MessageDeliveryStatus.UNDELIVERED

    @classmethod
    def list_by_contact(
        cls,
        contact_id: str,
    ) -> list["Message"]:
        """List full message history for one contact."""
        with Session(engine) as session:
            statement = select(cls).where(cls.contact_id == contact_id).order_by(cls.timestamp)
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def has_inbound_for_contact(
        cls,
        contact_id: str,
    ) -> bool:
        """Return True when one contact already has at least one inbound message."""
        with Session(engine) as session:
            statement = (
                select(cls.id)
                .where(
                    cls.contact_id == contact_id,
                    cls.from_me.is_(False),
                )
                .limit(1)
            )
            return session.exec(statement).first() is not None

    @classmethod
    def get_latest_inbound_message(
        cls,
        contact_id: str,
    ) -> Optional["Message"]:
        """Return the latest inbound message for one contact."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(
                    cls.contact_id == contact_id,
                    cls.from_me.is_(False),
                )
                .order_by(cls.timestamp.desc(), cls.id.desc())
                .limit(1)
            )
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def count_contacts_with_inbound_messages(
        cls,
        company_id: str,
        *,
        include_archived: bool = True,
    ) -> int:
        """Count company contacts that already have at least one inbound message."""
        with Session(engine) as session:
            statement = (
                select(cls.contact_id)
                .join(Contact, Contact.id == cls.contact_id)
                .where(
                    Contact.company_id == company_id,
                    cls.from_me.is_(False),
                )
                .distinct()
            )
            if not include_archived:
                statement = statement.where(Contact.status == ContactStatus.ACTIVE)
            contact_ids = list(session.exec(statement).all())
            return len(contact_ids)

    @classmethod
    def has_delivered_outbound_for_contact(
        cls,
        contact_id: str,
    ) -> bool:
        """Return True when one contact has at least one provider-confirmed outbound delivery."""
        with Session(engine) as session:
            statement = (
                select(cls.id)
                .where(
                    cls.contact_id == contact_id,
                    cls.from_me.is_(True),
                    cls.delivery_status == MessageDeliveryStatus.DELIVERED,
                )
                .limit(1)
            )
            return session.exec(statement).first() is not None

    @classmethod
    def delete_pending_outbound_for_contact(
        cls,
        contact_id: str,
    ) -> int:
        """Delete unsent outbound drafts for one contact."""
        with Session(engine) as session:
            rows = list(
                session.exec(
                    select(cls).where(
                        cls.contact_id == contact_id,
                        cls.from_me.is_(True),
                        cls.delivery_status == MessageDeliveryStatus.UNDELIVERED,
                    )
                ).all()
            )
            if not rows:
                return 0

            deleted_count = 0
            for row in rows:
                session.delete(row)
                deleted_count += 1

            contact = session.get(Contact, contact_id)
            if contact:
                contact.updated_at = datetime.now(timezone.utc)
                session.add(contact)

            session.commit()
            return deleted_count

    @classmethod
    def update_delivery_status(
        cls,
        *,
        contact_id: str,
        message_id: int,
        delivery_status: MessageDeliveryStatus | str,
        external_id: str | None = None,
    ) -> Optional["Message"]:
        """Update manual delivery status for one message."""
        with Session(engine) as session:
            statement = select(cls).where(
                cls.id == message_id,
                cls.contact_id == contact_id,
            )
            row = session.exec(statement).first()
            if not row:
                return None
            row.delivery_status = cls.normalize_delivery_status(
                delivery_status,
                from_me=row.from_me,
            )
            if external_id is not None:
                row.external_id = external_id.strip() or None
            session.add(row)
            contact = session.get(Contact, contact_id)
            if contact:
                contact.updated_at = datetime.now(timezone.utc)
                session.add(contact)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_pending_delivery(
        cls,
        *,
        limit: int = 100,
    ) -> list["Message"]:
        """List current outbound drafts that are still the latest turn for each contact."""
        now_utc = datetime.now(timezone.utc)
        newer_message = aliased(cls)
        with Session(engine) as session:
            statement = (
                select(cls)
                .join(Contact, Contact.id == cls.contact_id)
                .where(
                    cls.from_me.is_(True),
                    cls.delivery_status == MessageDeliveryStatus.UNDELIVERED,
                    cls.dispatch_after <= now_utc,
                    Contact.status == ContactStatus.ACTIVE,
                    ~select(newer_message.id)
                    .where(
                        newer_message.contact_id == cls.contact_id,
                        newer_message.id > cls.id,
                    )
                    .exists(),
                )
                .order_by(cls.dispatch_after, cls.id)
                .limit(limit)
            )
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows

    @classmethod
    def count_contacts_with_pending_delivery(
        cls,
        company_id: str,
    ) -> int:
        """Count active contacts whose latest message is one pending outbound draft."""
        newer_message = aliased(cls)
        with Session(engine) as session:
            statement = (
                select(cls.contact_id)
                .join(Contact, Contact.id == cls.contact_id)
                .where(
                    Contact.company_id == company_id,
                    Contact.status == ContactStatus.ACTIVE,
                    cls.from_me.is_(True),
                    cls.delivery_status == MessageDeliveryStatus.UNDELIVERED,
                    ~select(newer_message.id)
                    .where(
                        newer_message.contact_id == cls.contact_id,
                        newer_message.id > cls.id,
                    )
                    .exists(),
                )
                .distinct()
            )
            contact_ids = list(session.exec(statement).all())
            return len(contact_ids)

    @classmethod
    def get_latest_ai_message(
        cls,
        contact_id: str,
    ) -> Optional["Message"]:
        """Get latest outbound message for one contact."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.contact_id == contact_id, cls.from_me.is_(True))
                .order_by(cls.timestamp.desc())
                .limit(1)
            )
            row = session.exec(statement).first()
            if row:
                session.expunge(row)
            return row

    @classmethod
    def update_text(
        cls,
        *,
        contact_id: str,
        message_id: int,
        text: str,
    ) -> Optional["Message"]:
        """Update one message text for one contact."""
        with Session(engine) as session:
            statement = select(cls).where(
                cls.id == message_id,
                cls.contact_id == contact_id,
            )
            row = session.exec(statement).first()
            if not row:
                return None
            row.text = text.strip()
            session.add(row)
            contact = session.get(Contact, contact_id)
            if contact:
                contact.updated_at = datetime.now(timezone.utc)
                session.add(contact)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row


def init_db() -> None:
    """Create all persistence tables."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    ensure_client_lead_source_prefilled_reply_text_column()
    drop_legacy_contadores_events_table()
    ensure_company_tags_column()
    ensure_company_normalized_source_url_column()
    ensure_contact_email_provider_columns()
    ensure_contadores_automation_paused_columns()
    ensure_contadores_closed_state_columns()
    ensure_contadores_manual_reply_columns()
    ensure_contadores_conversation_processing_columns()
    ensure_contadores_codex_thread_columns()
    ensure_contadores_funnel_columns()
    ensure_contadores_tags_column()
    ensure_contadores_strategy_columns()
    ensure_contadores_message_delivery_columns()
    ensure_contadores_message_template_columns()
    ensure_client_lead_source_sheet_tab_name_column()
    ensure_client_lead_source_meta_columns()
    ensure_client_lead_source_context_field_mapping_column()
    ensure_client_lead_delivery_sent_text_column()
    ensure_contadores_runtime_alert_columns()
    ensure_agent_run_codex_thread_columns()
    ensure_contadores_config_strategy_weights_column()
    ensure_workstation_client_automation_columns()
    ensure_workstation_codex_thread_columns()
    ensure_contadores_lifecycle_columns()
    ensure_platform_human_question_context_columns()
    ensure_platform_ad_campaign_creative_columns()
    ensure_platform_creative_asset_meta_columns()
    ensure_platform_meta_publish_attempt_idempotency_index()
    ensure_platform_meeting_calendar_columns()
    logger.info(f"Database initialized at {DATABASE_URL}")


def drop_legacy_contadores_events_table() -> None:
    """Remove the retired event timeline table from existing databases."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_events" not in inspector.get_table_names():
            return
        connection.exec_driver_sql("DROP TABLE contadores_events")
        logger.info("Dropped legacy contadores_events table.")


def ensure_platform_meta_publish_attempt_idempotency_index() -> None:
    """Enforce Meta publish idempotency keys on existing SQLite databases."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "platform_meta_publish_attempts" not in inspector.get_table_names():
            return
        connection.exec_driver_sql(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_platform_meta_publish_attempts_idempotency_key
            ON platform_meta_publish_attempts (idempotency_key)
            WHERE idempotency_key IS NOT NULL
            """
        )


def ensure_platform_creative_asset_meta_columns() -> None:
    """Add provider creative upload fields to existing creative asset tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "platform_creative_assets" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("platform_creative_assets")}
        column_sql = {
            "image_hash": "ALTER TABLE platform_creative_assets ADD COLUMN image_hash TEXT NOT NULL DEFAULT ''",
            "video_id": "ALTER TABLE platform_creative_assets ADD COLUMN video_id TEXT NOT NULL DEFAULT ''",
            "meta_upload_response_json": (
                "ALTER TABLE platform_creative_assets ADD COLUMN meta_upload_response_json TEXT NOT NULL DEFAULT '{}'"
            ),
        }
        for column_name, statement in column_sql.items():
            if column_name not in columns:
                connection.exec_driver_sql(statement)
                logger.info("Added missing platform_creative_assets.%s column.", column_name)
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_platform_creative_assets_image_hash "
            "ON platform_creative_assets (image_hash)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_platform_creative_assets_video_id "
            "ON platform_creative_assets (video_id)"
        )


def ensure_platform_ad_campaign_creative_columns() -> None:
    """Add creative benchmark/testing fields to existing ad campaign tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "platform_ad_campaigns" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("platform_ad_campaigns")}
        column_sql = {
            "creative_benchmark_json": (
                "ALTER TABLE platform_ad_campaigns ADD COLUMN creative_benchmark_json TEXT NOT NULL DEFAULT '{}'"
            ),
            "creative_testing_json": (
                "ALTER TABLE platform_ad_campaigns ADD COLUMN creative_testing_json TEXT NOT NULL DEFAULT '{}'"
            ),
        }
        for column_name, statement in column_sql.items():
            if column_name not in columns:
                connection.exec_driver_sql(statement)
                logger.info("Added missing platform_ad_campaigns.%s column.", column_name)


def ensure_platform_meeting_calendar_columns() -> None:
    """Add Google Calendar scheduling columns to existing platform meeting tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "platform_meetings" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("platform_meetings")}
        column_sql = {
            "calendar_id": "ALTER TABLE platform_meetings ADD COLUMN calendar_id TEXT NOT NULL DEFAULT ''",
            "calendar_event_link": "ALTER TABLE platform_meetings ADD COLUMN calendar_event_link TEXT NOT NULL DEFAULT ''",
            "calendar_event_payload_json": "ALTER TABLE platform_meetings ADD COLUMN calendar_event_payload_json TEXT NOT NULL DEFAULT '{}'",
            "calendar_result_json": "ALTER TABLE platform_meetings ADD COLUMN calendar_result_json TEXT NOT NULL DEFAULT '{}'",
            "calendar_error": "ALTER TABLE platform_meetings ADD COLUMN calendar_error TEXT NOT NULL DEFAULT ''",
        }
        for column_name, sql in column_sql.items():
            if column_name not in columns:
                connection.exec_driver_sql(sql)
                logger.info("Added missing platform_meetings.%s column.", column_name)


def ensure_contadores_funnel_columns() -> None:
    """Add funnel_id columns for multi-funnel Contadores-style flows."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        table_names = set(inspector.get_table_names())
        if "contadores_leads" in table_names:
            lead_columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
            if "funnel_id" not in lead_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE contadores_leads ADD COLUMN funnel_id TEXT NOT NULL DEFAULT 'contadores'"
                )
                logger.info("Added missing contadores_leads.funnel_id column.")
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_contadores_leads_funnel_id ON contadores_leads (funnel_id)"
            )


def ensure_contadores_tags_column() -> None:
    """Add operator lead tags to existing Contadores lead tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_leads" not in inspector.get_table_names():
            return
        lead_columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
        if "tags_json" in lead_columns:
            return
        connection.exec_driver_sql(
            "ALTER TABLE contadores_leads ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
        )
        logger.info("Added missing contadores_leads.tags_json column.")


def ensure_contadores_automation_paused_columns() -> None:
    """Add automation_paused/reason columns to existing contadores_leads tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_leads" not in inspector.get_table_names():
            return
        lead_columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
        if "automation_paused" not in lead_columns:
            connection.exec_driver_sql(
                "ALTER TABLE contadores_leads ADD COLUMN automation_paused INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("Added missing contadores_leads.automation_paused column.")
        if "automation_paused_reason" not in lead_columns:
            connection.exec_driver_sql(
                "ALTER TABLE contadores_leads ADD COLUMN automation_paused_reason TEXT"
            )
            logger.info("Added missing contadores_leads.automation_paused_reason column.")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_contadores_leads_automation_paused ON contadores_leads (automation_paused)"
        )


def ensure_contadores_closed_state_columns() -> None:
    """Add closed-state columns to existing contadores_leads tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_leads" not in inspector.get_table_names():
            return
        lead_columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
        if "closed_at" not in lead_columns:
            connection.exec_driver_sql(
                "ALTER TABLE contadores_leads ADD COLUMN closed_at TIMESTAMP"
            )
            logger.info("Added missing contadores_leads.closed_at column.")
        if "stage_before_closed" not in lead_columns:
            connection.exec_driver_sql(
                "ALTER TABLE contadores_leads ADD COLUMN stage_before_closed VARCHAR"
            )
            logger.info("Added missing contadores_leads.stage_before_closed column.")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_contadores_leads_closed_at ON contadores_leads (closed_at)"
        )


def ensure_contadores_manual_reply_columns() -> None:
    """Add manual reply handling columns to existing contadores_leads tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_leads" not in inspector.get_table_names():
            return
        lead_columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
        if "manual_reply_handled_at" not in lead_columns:
            connection.exec_driver_sql(
                "ALTER TABLE contadores_leads ADD COLUMN manual_reply_handled_at TIMESTAMP"
            )
            logger.info("Added missing contadores_leads.manual_reply_handled_at column.")


def ensure_contadores_lifecycle_columns() -> None:
    """Add and backfill persisted v2 lifecycle columns for Contadores leads."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_leads" not in inspector.get_table_names():
            return
        lead_columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
        column_definitions = {
            "pipeline_stage": "TEXT NOT NULL DEFAULT 'new'",
            "queue_state": "TEXT NOT NULL DEFAULT 'automation'",
            "terminal_state": "TEXT NOT NULL DEFAULT 'open'",
            "attention_state": "TEXT NOT NULL DEFAULT 'clear'",
            "meeting_scheduled_at": "TIMESTAMP",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in lead_columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE contadores_leads ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing contadores_leads.%s column.", column_name)
        for column_name in column_definitions:
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_contadores_leads_{column_name} "
                f"ON contadores_leads ({column_name})"
            )

    backfill_contadores_lifecycle_columns()


def backfill_contadores_lifecycle_columns() -> None:
    """Recompute persisted v2 lifecycle fields for existing rows."""
    with Session(engine) as session:
        leads = list(session.exec(select(ContadoresLead)).all())
        changed = 0
        for lead in leads:
            before = (lead.pipeline_stage, lead.queue_state, lead.terminal_state, lead.attention_state)
            ContadoresLead.refresh_lifecycle_fields(lead)
            after = (lead.pipeline_stage, lead.queue_state, lead.terminal_state, lead.attention_state)
            if after == before:
                continue
            session.add(lead)
            changed += 1
        if changed:
            session.commit()
            logger.info("Backfilled lifecycle fields for %s Contadores leads.", changed)


def ensure_contadores_conversation_processing_columns() -> None:
    """Add cross-process conversation processing claim columns."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_leads" not in inspector.get_table_names():
            return
        lead_columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
        column_definitions = {
            "conversation_processing_started_at": "TIMESTAMP",
            "conversation_processing_latest_inbound_id": "INTEGER",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in lead_columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE contadores_leads ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing contadores_leads.%s column.", column_name)
        for column_name in column_definitions:
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_contadores_leads_{column_name} "
                f"ON contadores_leads ({column_name})"
            )


def ensure_contadores_runtime_alert_columns() -> None:
    """Add email-thread and resolution metadata to runtime alerts."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_runtime_alerts" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("contadores_runtime_alerts")}
        column_definitions = {
            "previous_stage": "TEXT",
            "email_thread_id": "TEXT",
            "email_message_id": "TEXT",
            "email_inbox_id": "TEXT",
            "email_inbox_address": "TEXT",
            "resolved_at": "TIMESTAMP",
            "operator_reply_text": "TEXT",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE contadores_runtime_alerts ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing contadores_runtime_alerts.%s column.", column_name)
        for column_name in ["previous_stage", "email_thread_id", "email_message_id", "email_inbox_id", "resolved_at"]:
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_contadores_runtime_alerts_{column_name} "
                f"ON contadores_runtime_alerts ({column_name})"
            )


def ensure_contadores_codex_thread_columns() -> None:
    """Add persisted Codex conversation thread metadata to leads."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_leads" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("contadores_leads")}
        if "codex_conversation_thread_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE contadores_leads ADD COLUMN codex_conversation_thread_id TEXT"
            )
            logger.info("Added missing contadores_leads.codex_conversation_thread_id column.")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_contadores_leads_codex_conversation_thread_id "
            "ON contadores_leads (codex_conversation_thread_id)"
        )


def ensure_agent_run_codex_thread_columns() -> None:
    """Add Codex thread and turn metadata to autonomous run audit rows."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "agent_runs" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("agent_runs")}
        column_definitions = {
            "codex_thread_id": "TEXT",
            "codex_turn_id": "TEXT",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE agent_runs ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing agent_runs.%s column.", column_name)
        for column_name in column_definitions:
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_agent_runs_{column_name} "
                f"ON agent_runs ({column_name})"
            )


def ensure_workstation_client_automation_columns() -> None:
    """Add solo-page automation columns to existing Workstation tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "workstation_clients" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("workstation_clients")}
        column_definitions = {
            "work_type": "TEXT NOT NULL DEFAULT 'PAGINA_ADS'",
            "automation_status": "TEXT NOT NULL DEFAULT 'NEEDS_HUMAN'",
            "offer_price_usd": "INTEGER",
            "offer_currency": "TEXT NOT NULL DEFAULT 'USD'",
            "last_automation_handled_at": "TIMESTAMP",
            "last_preview_sent_at": "TIMESTAMP",
            "approved_at": "TIMESTAMP",
            "ping_1_sent_at": "TIMESTAMP",
            "ping_2_sent_at": "TIMESTAMP",
            "handoff_sent_at": "TIMESTAMP",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE workstation_clients ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing workstation_clients.%s column.", column_name)

        enum_value_fixes = {
            "status": {
                "pending_payment": "PENDING_PAYMENT",
                "paid": "PAID",
                "in_progress": "IN_PROGRESS",
                "archived": "ARCHIVED",
            },
            "work_type": {
                "solo_pagina": "SOLO_PAGINA",
                "pagina_ads": "PAGINA_ADS",
                "solo_ads": "SOLO_ADS",
            },
            "automation_status": {
                "intake": "INTAKE",
                "drafting": "DRAFTING",
                "awaiting_review": "AWAITING_REVIEW",
                "revision_requested": "REVISION_REQUESTED",
                "approved": "APPROVED",
                "needs_human": "NEEDS_HUMAN",
                "failed": "FAILED",
            },
        }
        for column_name, replacements in enum_value_fixes.items():
            if column_name not in columns and column_name not in column_definitions:
                continue
            for old_value, new_value in replacements.items():
                connection.exec_driver_sql(
                    f"UPDATE workstation_clients SET {column_name} = ? WHERE {column_name} = ?",
                    (new_value, old_value),
                )

        for column_name in [
            "work_type",
            "automation_status",
            "offer_price_usd",
            "last_automation_handled_at",
            "last_preview_sent_at",
            "approved_at",
            "ping_1_sent_at",
            "ping_2_sent_at",
            "handoff_sent_at",
        ]:
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_workstation_clients_{column_name} "
                f"ON workstation_clients ({column_name})"
            )


def ensure_workstation_codex_thread_columns() -> None:
    """Add persisted Codex Workstation thread metadata to clients."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "workstation_clients" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("workstation_clients")}
        if "codex_workstation_thread_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE workstation_clients ADD COLUMN codex_workstation_thread_id TEXT"
            )
            logger.info("Added missing workstation_clients.codex_workstation_thread_id column.")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_workstation_clients_codex_workstation_thread_id "
            "ON workstation_clients (codex_workstation_thread_id)"
        )


def ensure_platform_human_question_context_columns() -> None:
    """Add MISSION doubt-context fields when the lifecycle table already exists."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "platform_human_questions" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("platform_human_questions")}
        additions = {
            "context_summary": "TEXT NOT NULL DEFAULT ''",
            "trying_to_do": "TEXT NOT NULL DEFAULT ''",
        }
        for column_name, column_type in additions.items():
            if column_name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE platform_human_questions ADD COLUMN {column_name} {column_type}"
                )
                logger.info("Added missing platform_human_questions.%s column.", column_name)


def ensure_contadores_strategy_columns() -> None:
    """Add strategy/media columns to existing Contadores message tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_messages" not in inspector.get_table_names():
            return
        message_columns = {column["name"] for column in inspector.get_columns("contadores_messages")}
        column_definitions = {
            "strategy_assignment_id": "INTEGER",
            "strategy_step": "TEXT",
            "strategy_id": "TEXT",
            "strategy_label": "TEXT",
            "media_type": "TEXT",
            "media_path": "TEXT",
            "media_caption": "TEXT",
            "media_mime_type": "TEXT",
            "media_filename": "TEXT",
            "media_sha256": "TEXT",
            "media_id": "TEXT",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in message_columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE contadores_messages ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing contadores_messages.%s column.", column_name)

        for column_name in [
            "strategy_assignment_id",
            "strategy_step",
            "strategy_id",
            "media_type",
            "media_id",
        ]:
            connection.exec_driver_sql(
                f"CREATE INDEX IF NOT EXISTS ix_contadores_messages_{column_name} "
                f"ON contadores_messages ({column_name})"
            )


def ensure_contadores_message_delivery_columns() -> None:
    """Add retry/error metadata to existing Contadores message tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_messages" not in inspector.get_table_names():
            return
        message_columns = {column["name"] for column in inspector.get_columns("contadores_messages")}
        column_definitions = {
            "delivery_attempts": "INTEGER NOT NULL DEFAULT 0",
            "last_delivery_error": "TEXT",
            "last_delivery_error_at": "TIMESTAMP",
            "delivery_error_acknowledged_at": "TIMESTAMP",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in message_columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE contadores_messages ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing contadores_messages.%s column.", column_name)
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_contadores_messages_delivery_attempts "
            "ON contadores_messages (delivery_attempts)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_contadores_messages_delivery_error_acknowledged_at "
            "ON contadores_messages (delivery_error_acknowledged_at)"
        )


def ensure_contadores_message_template_columns() -> None:
    """Add per-message WhatsApp template metadata to existing message tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_messages" not in inspector.get_table_names():
            return
        message_columns = {column["name"] for column in inspector.get_columns("contadores_messages")}
        column_definitions = {
            "whatsapp_template_name": "TEXT",
            "whatsapp_template_language": "TEXT",
            "whatsapp_template_body_params_json": "TEXT NOT NULL DEFAULT '[]'",
        }
        for column_name, column_type in column_definitions.items():
            if column_name in message_columns:
                continue
            connection.exec_driver_sql(
                f"ALTER TABLE contadores_messages ADD COLUMN {column_name} {column_type}"
            )
            logger.info("Added missing contadores_messages.%s column.", column_name)
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_contadores_messages_whatsapp_template_name "
            "ON contadores_messages (whatsapp_template_name)"
        )


def ensure_client_lead_delivery_sent_text_column() -> None:
    """Add immutable sent-text snapshot storage to existing Delivery rows."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "client_lead_deliveries" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("client_lead_deliveries")}
        if "sent_text" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE client_lead_deliveries ADD COLUMN sent_text TEXT NOT NULL DEFAULT ''"
            )
            logger.info("Added missing client_lead_deliveries.sent_text column.")

        result = connection.exec_driver_sql(
            """
            UPDATE client_lead_deliveries
            SET sent_text = notification_text
            WHERE COALESCE(sent_text, '') = ''
              AND COALESCE(notification_text, '') != ''
              AND delivery_status IN (
                'sent',
                'delivered',
                'SENT',
                'DELIVERED',
                'ClientLeadDeliveryStatus.SENT',
                'ClientLeadDeliveryStatus.DELIVERED'
              )
            """
        )
        if result.rowcount and result.rowcount > 0:
            logger.info(
                "Backfilled %s client_lead_deliveries.sent_text snapshots.",
                result.rowcount,
            )


def ensure_client_lead_source_sheet_tab_name_column() -> None:
    """Add optional Google Sheet tab-name selection to existing Delivery sources."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "client_lead_sources" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("client_lead_sources")}
        if "sheet_tab_name" in columns:
            return
        connection.exec_driver_sql(
            "ALTER TABLE client_lead_sources ADD COLUMN sheet_tab_name TEXT"
        )
        logger.info("Added missing client_lead_sources.sheet_tab_name column.")


def ensure_client_lead_source_meta_columns() -> None:
    """Add Meta instant-form routing fields to existing Delivery sources."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "client_lead_sources" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("client_lead_sources")}
        if "meta_page_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE client_lead_sources ADD COLUMN meta_page_id TEXT NOT NULL DEFAULT ''"
            )
            logger.info("Added missing client_lead_sources.meta_page_id column.")
        if "meta_lead_form_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE client_lead_sources ADD COLUMN meta_lead_form_id TEXT NOT NULL DEFAULT ''"
            )
            logger.info("Added missing client_lead_sources.meta_lead_form_id column.")
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_client_lead_sources_meta_lead_form_id "
            "ON client_lead_sources (meta_lead_form_id)"
        )


def ensure_client_lead_source_context_field_mapping_column() -> None:
    """Add configurable Delivery alert context fields to existing sources."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "client_lead_sources" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("client_lead_sources")}
        if "context_field_mapping_json" in columns:
            return
        connection.exec_driver_sql(
            "ALTER TABLE client_lead_sources ADD COLUMN context_field_mapping_json TEXT NOT NULL DEFAULT '{}'"
        )
        logger.info("Added missing client_lead_sources.context_field_mapping_json column.")


def ensure_client_lead_source_prefilled_reply_text_column() -> None:
    """Keep older Delivery databases compatible after the reply-text removal."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "client_lead_sources" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("client_lead_sources")}
        if "prefilled_reply_text" in columns:
            return
        connection.exec_driver_sql(
            "ALTER TABLE client_lead_sources ADD COLUMN prefilled_reply_text TEXT NOT NULL DEFAULT ''"
        )
        logger.info("Added missing client_lead_sources.prefilled_reply_text column.")


def ensure_contadores_config_strategy_weights_column() -> None:
    """Add configurable strategy weights to existing Contadores config tables."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contadores_config" not in inspector.get_table_names():
            return
        config_columns = {column["name"] for column in inspector.get_columns("contadores_config")}
        if "strategy_weights_json" in config_columns:
            return
        connection.exec_driver_sql(
            "ALTER TABLE contadores_config ADD COLUMN strategy_weights_json TEXT NOT NULL DEFAULT '{}'"
        )
        logger.info("Added missing contadores_config.strategy_weights_json column.")


def ensure_company_tags_column() -> None:
    """Add the tags column to existing SQLite databases without migrations."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "companies" not in inspector.get_table_names():
            return
        company_columns = {column["name"] for column in inspector.get_columns("companies")}
        if "tags_json" in company_columns:
            return
        connection.exec_driver_sql(
            "ALTER TABLE companies ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'"
        )
        logger.info("Added missing companies.tags_json column.")


def ensure_company_normalized_source_url_column() -> None:
    """Add/backfill the normalized company URL column for duplicate detection."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "companies" not in inspector.get_table_names():
            return
        company_columns = {column["name"] for column in inspector.get_columns("companies")}
        if "normalized_source_url" not in company_columns:
            connection.exec_driver_sql(
                "ALTER TABLE companies ADD COLUMN normalized_source_url TEXT NOT NULL DEFAULT ''"
            )
            logger.info("Added missing companies.normalized_source_url column.")

        rows = connection.exec_driver_sql(
            "SELECT id, source_url, normalized_source_url FROM companies"
        ).fetchall()
        updated_rows = 0
        for company_id, source_url, normalized_source_url in rows:
            normalized_key = normalize_company_source_url_key(source_url or "")
            if (normalized_source_url or "") == normalized_key:
                continue
            connection.exec_driver_sql(
                "UPDATE companies SET normalized_source_url = ? WHERE id = ?",
                (normalized_key, company_id),
            )
            updated_rows += 1

        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_companies_normalized_source_url ON companies (normalized_source_url)"
        )
        if updated_rows:
            logger.info("Backfilled companies.normalized_source_url for %s rows.", updated_rows)


def ensure_contact_email_provider_columns() -> None:
    """Add AgentMail inbox columns to existing contact tables without migrations."""
    with engine.begin() as connection:
        inspector = inspect(connection)
        if "contacts" not in inspector.get_table_names():
            return
        contact_columns = {column["name"] for column in inspector.get_columns("contacts")}
        if "email_inbox_id" not in contact_columns:
            connection.exec_driver_sql(
                "ALTER TABLE contacts ADD COLUMN email_inbox_id TEXT"
            )
            logger.info("Added missing contacts.email_inbox_id column.")
        if "email_inbox_address" not in contact_columns:
            connection.exec_driver_sql(
                "ALTER TABLE contacts ADD COLUMN email_inbox_address TEXT"
            )
            logger.info("Added missing contacts.email_inbox_address column.")

        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_contacts_email_inbox_id ON contacts (email_inbox_id)"
        )
