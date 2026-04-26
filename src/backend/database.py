"""Agnostic persistence for company/contact/message workflows."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional, overload
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit

import phonenumbers
from pydantic import BaseModel, Field as PydanticField, field_serializer
from phonenumbers import NumberParseException
from sqlalchemy import Column, Enum as SQLAlchemyEnum, String, UniqueConstraint, event, inspect
from sqlalchemy.orm import aliased
from sqlmodel import Field, Session, SQLModel, create_engine, select

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
EMAIL_ADDRESS_PATTERN = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+$",
    re.IGNORECASE,
)


def _extract_email_address(value: str) -> str:
    """Extract one normalized email address candidate from raw input."""
    return parseaddr(value or "")[1].strip().lower()


def is_valid_email(value: str) -> bool:
    """Return True when the input is a syntactically complete email address."""
    clean = _extract_email_address(value)
    if not clean or len(clean) > 254 or clean.count("@") != 1 or ".." in clean:
        return False
    local_part, domain = clean.rsplit("@", 1)
    if not local_part or not domain or "." not in domain:
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    if any(not label or label.startswith("-") or label.endswith("-") for label in domain.split(".")):
        return False
    return EMAIL_ADDRESS_PATTERN.fullmatch(clean) is not None


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


def serialize_json_payload(payload: dict[str, Any] | list[Any] | None) -> str:
    """Serialize optional payloads to stable JSON text."""
    if payload is None:
        return "{}"
    return json.dumps(payload, ensure_ascii=False, default=str)


class ContadoresLeadStage(str, Enum):
    """Lifecycle stage for one Contadores lead."""

    AWAITING_INITIAL_REPLY = "awaiting_initial_reply"
    AWAITING_VIDEO_REPLY = "awaiting_video_reply"
    NEEDS_HUMAN = "needs_human"
    CALENDLY_SENT = "calendly_sent"
    BOOKED = "booked"
    CLOSED = "closed"
    ARCHIVED = "archived"


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
    """Return a usable Calendly base URL for Contadores."""
    default_url = "https://calendly.com/yoelkravchuk/konecta-meet"
    raw_value = (base_url or "").strip()
    if not raw_value:
        return default_url
    parsed = urlsplit(raw_value)
    normalized_host = (parsed.netloc or parsed.path).strip().lower()
    normalized_path = parsed.path.strip("/")
    if normalized_host in {"calendly.com", "www.calendly.com"} and not normalized_path:
        return default_url
    return raw_value


class ContadoresConfig(SQLModel, table=True):
    """Singleton-style runtime configuration for Contadores."""

    __tablename__ = "contadores_config"

    id: str = Field(default="default", primary_key=True)
    enabled: bool = Field(default=False)
    sheet_url: str | None = Field(default_factory=lambda: (os.getenv("CONTADORES_SHEET_URL", "") or None))
    sheet_gid: str | None = Field(default_factory=lambda: (os.getenv("CONTADORES_SHEET_GID", "") or None))
    sheet_poll_seconds: int = Field(
        default_factory=lambda: max(60, int(os.getenv("CONTADORES_SHEET_POLL_SECONDS", "300")))
    )
    loom_url: str = Field(
        default_factory=lambda: (
            os.getenv(
                "CONTADORES_LOOM_URL",
                "https://www.loom.com/share/36b054dea1c94bbaa7470014c2337fca",
            ).strip()
            or "https://www.loom.com/share/36b054dea1c94bbaa7470014c2337fca"
        )
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
                item.sheet_poll_seconds = max(60, int(sheet_poll_seconds))
            if loom_url is not None:
                item.loom_url = (loom_url or "").strip() or item.loom_url
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
    sheet_created_time: datetime | None = Field(default=None)
    stage: ContadoresLeadStage = Field(default=ContadoresLeadStage.AWAITING_INITIAL_REPLY, index=True)
    calendly_tracking_token: str = Field(default_factory=lambda: uuid.uuid4().hex, index=True)
    last_classification_label: str | None = Field(default=None, index=True)
    last_classification_reason: str | None = Field(default=None)
    opener_sent_at: datetime | None = Field(default=None, index=True)
    first_reply_received_at: datetime | None = Field(default=None, index=True)
    loom_sent_at: datetime | None = Field(default=None, index=True)
    video_check_sent_at: datetime | None = Field(default=None, index=True)
    classification_completed_at: datetime | None = Field(default=None)
    calendly_sent_at: datetime | None = Field(default=None, index=True)
    booked_at: datetime | None = Field(default=None, index=True)
    closed_at: datetime | None = Field(default=None, index=True)
    stage_before_closed: ContadoresLeadStage | None = Field(default=None)
    needs_human_notified_at: datetime | None = Field(default=None)
    manual_reply_handled_at: datetime | None = Field(default=None)
    last_inbound_at: datetime | None = Field(default=None, index=True)
    last_outbound_at: datetime | None = Field(default=None, index=True)
    archived_at: datetime | None = Field(default=None, index=True)
    automation_paused: bool = Field(default=False, index=True)
    automation_paused_reason: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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
        sheet_created_time: datetime | None = None,
        reset_flow: bool = False,
    ) -> "ContadoresLead":
        """Create or update one lead from sheet/testing ingestion."""
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
                    sheet_created_time=sheet_created_time,
                    stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
                    created_at=now,
                    updated_at=now,
                )
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
            session.add(item)
            session.commit()
            session.refresh(item)
            session.expunge(item)
            return item


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

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
                    ContadoresLead.stage != ContadoresLeadStage.CLOSED,
                    ContadoresLead.stage != ContadoresLeadStage.BOOKED,
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
            session.add(row)
            lead = session.get(ContadoresLead, row.lead_id)
            if lead:
                lead.updated_at = datetime.now(timezone.utc)
                session.add(lead)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row


class ContadoresEvent(SQLModel, table=True):
    """Operational timeline events for Contadores observability."""

    __tablename__ = "contadores_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    funnel_id: str = Field(default="contadores", index=True)
    lead_id: str | None = Field(default=None, foreign_key="contadores_leads.id", index=True)
    event_type: str = Field(default="", index=True)
    actor: str | None = Field(default=None)
    summary: str = Field(default="")
    payload_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), index=True)

    @classmethod
    def add(
        cls,
        *,
        event_type: str,
        summary: str,
        lead_id: str | None = None,
        funnel_id: str | None = None,
        actor: str | None = None,
        payload: dict[str, Any] | list[Any] | None = None,
        created_at: datetime | None = None,
    ) -> "ContadoresEvent":
        """Persist one observability event."""
        with Session(engine) as session:
            now = created_at or datetime.now(timezone.utc)
            resolved_funnel_id = (funnel_id or "").strip() or "contadores"
            if lead_id:
                lead = session.get(ContadoresLead, lead_id)
                if lead:
                    resolved_funnel_id = lead.funnel_id or resolved_funnel_id
            row = cls(
                funnel_id=resolved_funnel_id,
                lead_id=lead_id,
                event_type=(event_type or "").strip(),
                actor=(actor or "").strip() or None,
                summary=summary.strip(),
                payload_json=serialize_json_payload(payload),
                created_at=now,
            )
            session.add(row)
            if lead_id:
                lead = session.get(ContadoresLead, lead_id)
                if lead:
                    lead.updated_at = now
                    session.add(lead)
            session.commit()
            session.refresh(row)
            session.expunge(row)
            return row

    @classmethod
    def list_by_lead(cls, lead_id: str, *, limit: int = 500) -> list["ContadoresEvent"]:
        """List recent events for one lead in reverse chronological order."""
        with Session(engine) as session:
            statement = (
                select(cls)
                .where(cls.lead_id == lead_id)
                .order_by(cls.created_at.desc(), cls.id.desc())
                .limit(limit)
            )
            rows = list(session.exec(statement).all())
            for row in rows:
                session.expunge(row)
            return rows


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
    ensure_company_tags_column()
    ensure_company_normalized_source_url_column()
    ensure_contact_email_provider_columns()
    ensure_contadores_automation_paused_columns()
    ensure_contadores_closed_state_columns()
    ensure_contadores_manual_reply_columns()
    ensure_contadores_funnel_columns()
    ensure_contadores_strategy_columns()
    ensure_contadores_config_strategy_weights_column()
    logger.info(f"Database initialized at {DATABASE_URL}")


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

        if "contadores_events" in table_names:
            event_columns = {column["name"] for column in inspector.get_columns("contadores_events")}
            if "funnel_id" not in event_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE contadores_events ADD COLUMN funnel_id TEXT NOT NULL DEFAULT 'contadores'"
                )
                logger.info("Added missing contadores_events.funnel_id column.")
            connection.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_contadores_events_funnel_id ON contadores_events (funnel_id)"
            )


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
