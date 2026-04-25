"""CRM inbox endpoints for CEO audit email threads."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import (
    Company,
    CrmEmailMessage,
    CrmMessageDirection,
    CrmMessageKind,
    CrmMessageStatus,
    CrmThread,
)

crm_router = APIRouter(prefix="/api/crm", tags=["crm"])


def format_timestamp_seconds(value: datetime | None) -> str | None:
    """Format datetimes with second precision and UTC marker."""
    if value is None:
        return None
    dt = value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def to_utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize optional datetime to UTC aware datetime."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def build_preview(body: str, *, max_length: int = 160) -> str:
    """Build one single-line preview from one CRM message body."""
    compact = " ".join((body or "").split()).strip()
    if len(compact) <= max_length:
        return compact
    return f"{compact[: max_length - 1].rstrip()}…"


def ensure_company(company_id: str) -> Company:
    """Return one company or 404."""
    company = Company.get_by_id(company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def ensure_thread(thread_id: str) -> CrmThread:
    """Return one CRM thread or 404."""
    thread = CrmThread.get_by_id(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="CRM thread not found")
    return thread


def build_message_response(message: CrmEmailMessage) -> "CrmMessageResponse":
    """Build API payload for one CRM message."""
    return CrmMessageResponse(
        id=message.id or 0,
        thread_id=message.thread_id,
        direction=message.direction.value,
        kind=message.kind.value,
        body=message.body,
        subject=message.subject,
        from_email=message.from_email,
        to_email=message.to_email,
        gmail_message_id=message.gmail_message_id,
        rfc_message_id=message.rfc_message_id,
        in_reply_to=message.in_reply_to,
        references=message.references,
        status=message.status.value,
        sent_at=format_timestamp_seconds(message.sent_at),
        received_at=format_timestamp_seconds(message.received_at),
        created_at=format_timestamp_seconds(message.created_at) or "",
    )


def build_thread_summary(thread: CrmThread) -> "CrmThreadSummary":
    """Build API payload for one CRM thread."""
    company = ensure_company(thread.company_id)
    messages = CrmEmailMessage.list_by_thread(thread.id)
    latest = messages[-1] if messages else None
    unread_count = CrmEmailMessage.count_unread_inbound_for_thread(
        thread_id=thread.id,
        last_read_at=thread.last_read_at,
    )
    return CrmThreadSummary(
        id=thread.id,
        company_id=thread.company_id,
        company_name=company.company_name,
        participant_email=thread.participant_email,
        subject=thread.subject,
        gmail_thread_id=thread.gmail_thread_id,
        last_read_at=format_timestamp_seconds(thread.last_read_at),
        unread_message_count=unread_count,
        last_message_preview=build_preview(latest.body) if latest else "",
        last_message_direction=latest.direction.value if latest else None,
        last_message_status=latest.status.value if latest else None,
        last_message_at=(
            format_timestamp_seconds(latest.sent_at or latest.received_at or latest.created_at)
            if latest
            else format_timestamp_seconds(thread.updated_at)
        ),
        updated_at=format_timestamp_seconds(thread.updated_at) or "",
        created_at=format_timestamp_seconds(thread.created_at) or "",
    )


def build_threads_response(threads: list[CrmThread]) -> "CrmThreadsResponse":
    """Build inbox response for all CRM threads."""
    items = sorted(
        [build_thread_summary(thread) for thread in threads],
        key=lambda item: item.last_message_at or item.updated_at,
        reverse=True,
    )
    unread_thread_count = len([item for item in items if item.unread_message_count > 0])
    unread_message_count = sum(item.unread_message_count for item in items)
    return CrmThreadsResponse(
        unread_thread_count=unread_thread_count,
        unread_message_count=unread_message_count,
        threads=items,
    )


class CrmMessageResponse(BaseModel):
    """One CRM message payload."""

    id: int
    thread_id: str
    direction: str
    kind: str
    body: str
    subject: str
    from_email: str | None = None
    to_email: str | None = None
    gmail_message_id: str | None = None
    rfc_message_id: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    status: str
    sent_at: str | None = None
    received_at: str | None = None
    created_at: str


class CrmThreadSummary(BaseModel):
    """Inbox row for one CRM thread."""

    id: str
    company_id: str
    company_name: str
    participant_email: str
    subject: str
    gmail_thread_id: str | None = None
    last_read_at: str | None = None
    unread_message_count: int = 0
    last_message_preview: str = ""
    last_message_direction: str | None = None
    last_message_status: str | None = None
    last_message_at: str | None = None
    updated_at: str
    created_at: str


class CrmThreadsResponse(BaseModel):
    """Inbox response for all CRM threads."""

    unread_thread_count: int = 0
    unread_message_count: int = 0
    threads: list[CrmThreadSummary] = Field(default_factory=list)


class CrmThreadDetailResponse(BaseModel):
    """CRM thread detail payload."""

    thread: CrmThreadSummary
    messages: list[CrmMessageResponse] = Field(default_factory=list)


class CreateCrmReplyCommand(BaseModel):
    """Create one manual CRM reply."""

    body: str = Field(min_length=1)


class PendingCrmOutboundMessage(BaseModel):
    """One outbound CRM message pending provider dispatch."""

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
    """Pending CRM outbound messages."""

    messages: list[PendingCrmOutboundMessage] = Field(default_factory=list)


class MarkCrmMessageSentCommand(BaseModel):
    """Provider send confirmation for one CRM message."""

    gmail_message_id: str = Field(min_length=1)
    gmail_thread_id: str | None = None
    rfc_message_id: str | None = None
    from_email: str | None = None
    sent_at: datetime | None = None


class CrmInboundMessageCommand(BaseModel):
    """Inbound CEO reply registration payload."""

    gmail_message_id: str = Field(min_length=1)
    gmail_thread_id: str = Field(min_length=1)
    from_email: str = Field(min_length=1)
    subject: str | None = None
    body: str = Field(min_length=1)
    in_reply_to: str | None = None
    references: str | None = None
    received_at: datetime | None = None


class CrmInboundMessageResponse(BaseModel):
    """Result of storing one inbound CRM message."""

    status: str
    thread_id: str | None = None
    company_id: str | None = None
    message_id: int | None = None
    reason: str | None = None


class CrmTrackedSendersResponse(BaseModel):
    """Tracked sender values for CRM inbound polling."""

    values: list[str] = Field(default_factory=list)


class ReportDeliverySentCommand(BaseModel):
    """Persist first CRM report-delivery email after bot send."""

    company_id: str = Field(min_length=1)
    participant_email: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    gmail_thread_id: str = Field(min_length=1)
    gmail_message_id: str = Field(min_length=1)
    rfc_message_id: str | None = None
    from_email: str | None = None
    sent_at: datetime | None = None


class ReportDeliverySentResponse(BaseModel):
    """Persisted CRM thread/message created from audit delivery."""

    thread_id: str
    company_id: str
    message_id: int
    duplicate_ignored: bool = False


@crm_router.get("/threads", response_model=CrmThreadsResponse)
async def list_crm_threads(
    limit: int = Query(default=200, ge=1, le=1000),
) -> CrmThreadsResponse:
    """Return CRM inbox threads with unread counters."""
    threads = CrmThread.list_recent(limit=limit)
    return build_threads_response(threads)


@crm_router.get("/threads/{thread_id}", response_model=CrmThreadDetailResponse)
async def get_crm_thread(thread_id: str) -> CrmThreadDetailResponse:
    """Return one CRM thread with full message history."""
    thread = ensure_thread(thread_id)
    summary = build_thread_summary(thread)
    messages = [build_message_response(item) for item in CrmEmailMessage.list_by_thread(thread_id)]
    return CrmThreadDetailResponse(thread=summary, messages=messages)


@crm_router.post("/threads/{thread_id}/reply", response_model=CrmMessageResponse)
async def create_crm_reply(
    thread_id: str,
    request: CreateCrmReplyCommand,
) -> CrmMessageResponse:
    """Create one outbound pending CRM reply."""
    thread = ensure_thread(thread_id)
    if not thread.gmail_thread_id:
        raise HTTPException(status_code=409, detail="CRM thread is missing provider thread id")
    body = request.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="body is required")
    row = CrmEmailMessage.add(
        thread_id=thread.id,
        direction=CrmMessageDirection.OUTBOUND,
        kind=CrmMessageKind.MANUAL_REPLY,
        body=body,
        subject=thread.subject,
        to_email=thread.participant_email,
        status=CrmMessageStatus.PENDING,
    )
    return build_message_response(row)


@crm_router.post("/threads/{thread_id}/mark-read", response_model=CrmThreadSummary)
async def mark_crm_thread_read(thread_id: str) -> CrmThreadSummary:
    """Mark all current inbound CRM messages as read for one thread."""
    thread = ensure_thread(thread_id)
    updated = CrmThread.update_last_read_at(thread.id)
    if not updated:
        raise HTTPException(status_code=404, detail="CRM thread not found")
    return build_thread_summary(updated)


@crm_router.get("/outbound/pending", response_model=PendingCrmOutboundResponse)
async def list_pending_crm_outbound(
    limit: int = Query(default=100, ge=1, le=500),
) -> PendingCrmOutboundResponse:
    """Return pending manual CRM replies ready for provider dispatch."""
    items: list[PendingCrmOutboundMessage] = []
    for message in CrmEmailMessage.list_pending_outbound(limit=limit):
        thread = CrmThread.get_by_id(message.thread_id)
        if not thread or not thread.gmail_thread_id:
            continue
        company = ensure_company(thread.company_id)
        latest_sent = CrmEmailMessage.get_latest_sent_outbound_for_thread(thread.id)
        items.append(
            PendingCrmOutboundMessage(
                message_id=message.id or 0,
                thread_id=thread.id,
                company_id=thread.company_id,
                company_name=company.company_name,
                participant_email=thread.participant_email,
                subject=message.subject,
                body=message.body,
                gmail_thread_id=thread.gmail_thread_id,
                latest_sent_rfc_message_id=latest_sent.rfc_message_id if latest_sent else None,
            )
        )
    return PendingCrmOutboundResponse(messages=items)


@crm_router.post("/messages/{message_id}/mark-sent", response_model=CrmMessageResponse)
async def mark_crm_message_sent(
    message_id: int,
    request: MarkCrmMessageSentCommand,
) -> CrmMessageResponse:
    """Persist provider send metadata for one CRM outbound message."""
    row = CrmEmailMessage.get_by_id(message_id)
    if not row:
        raise HTTPException(status_code=404, detail="CRM message not found")
    if row.direction != CrmMessageDirection.OUTBOUND:
        raise HTTPException(status_code=409, detail="Only outbound CRM messages can be marked as sent")
    existing = CrmEmailMessage.get_by_gmail_message_id(request.gmail_message_id)
    if existing and existing.id != row.id:
        raise HTTPException(status_code=409, detail="gmail_message_id already belongs to another CRM message")
    updated = CrmEmailMessage.mark_sent(
        message_id=message_id,
        gmail_message_id=request.gmail_message_id,
        gmail_thread_id=request.gmail_thread_id,
        rfc_message_id=request.rfc_message_id,
        from_email=request.from_email,
        sent_at=to_utc_datetime(request.sent_at),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="CRM message not found")
    return build_message_response(updated)


@crm_router.post("/messages/inbound", response_model=CrmInboundMessageResponse)
async def register_crm_inbound_message(
    request: CrmInboundMessageCommand,
) -> CrmInboundMessageResponse:
    """Persist one inbound CRM email matched by provider thread id."""
    existing = CrmEmailMessage.get_by_gmail_message_id(request.gmail_message_id)
    if existing:
        thread = CrmThread.get_by_id(existing.thread_id)
        return CrmInboundMessageResponse(
            status="duplicate",
            thread_id=existing.thread_id,
            company_id=thread.company_id if thread else None,
            message_id=existing.id,
        )

    thread = CrmThread.get_by_gmail_thread_id(request.gmail_thread_id)
    if not thread:
        return CrmInboundMessageResponse(status="ignored", reason="thread_not_found")

    row = CrmEmailMessage.add(
        thread_id=thread.id,
        direction=CrmMessageDirection.INBOUND,
        kind=CrmMessageKind.CEO_REPLY,
        body=request.body.strip(),
        subject=(request.subject or thread.subject).strip() or thread.subject,
        from_email=request.from_email,
        to_email=None,
        gmail_message_id=request.gmail_message_id,
        in_reply_to=request.in_reply_to,
        references=request.references,
        status=CrmMessageStatus.RECEIVED,
        received_at=to_utc_datetime(request.received_at) or datetime.now(timezone.utc),
    )
    return CrmInboundMessageResponse(
        status="stored",
        thread_id=thread.id,
        company_id=thread.company_id,
        message_id=row.id,
    )


@crm_router.post("/report-delivery/sent", response_model=ReportDeliverySentResponse)
async def register_report_delivery_sent(
    request: ReportDeliverySentCommand,
) -> ReportDeliverySentResponse:
    """Create CRM thread and first outbound report-delivery message after bot send."""
    company = ensure_company(request.company_id)
    existing = CrmEmailMessage.get_by_gmail_message_id(request.gmail_message_id)
    if existing:
        thread = ensure_thread(existing.thread_id)
        return ReportDeliverySentResponse(
            thread_id=thread.id,
            company_id=thread.company_id,
            message_id=existing.id or 0,
            duplicate_ignored=True,
        )

    thread = CrmThread.get_by_gmail_thread_id(request.gmail_thread_id)
    if thread is None:
        thread = CrmThread.create(
            company_id=company.id,
            participant_email=request.participant_email,
            subject=request.subject.strip(),
            gmail_thread_id=request.gmail_thread_id,
        )

    sent_at = to_utc_datetime(request.sent_at) or datetime.now(timezone.utc)
    message = CrmEmailMessage.add(
        thread_id=thread.id,
        direction=CrmMessageDirection.OUTBOUND,
        kind=CrmMessageKind.REPORT_DELIVERY,
        body=request.body.strip(),
        subject=request.subject.strip(),
        from_email=request.from_email,
        to_email=request.participant_email,
        gmail_message_id=request.gmail_message_id,
        rfc_message_id=request.rfc_message_id,
        status=CrmMessageStatus.SENT,
        sent_at=sent_at,
        created_at=sent_at,
    )
    Company.mark_ceo_delivery_delivered(
        company.id,
        thread_id=request.gmail_thread_id,
        external_id=request.gmail_message_id,
        rfc_message_id=request.rfc_message_id,
        delivered_at=sent_at,
    )
    return ReportDeliverySentResponse(
        thread_id=thread.id,
        company_id=company.id,
        message_id=message.id or 0,
        duplicate_ignored=False,
    )


@crm_router.get("/tracked-senders", response_model=CrmTrackedSendersResponse)
async def get_crm_tracked_senders() -> CrmTrackedSendersResponse:
    """Return participant sender emails tracked by the CRM inbox."""
    return CrmTrackedSendersResponse(values=sorted(CrmThread.list_tracked_participant_emails()))
