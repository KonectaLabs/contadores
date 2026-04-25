"""Message loop endpoints for contact transcripts and inbound processing."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.ai.react_agent import (
    KonectaAuditorSidebarAssistant,
)
from backend.ai.stage2_contact_to_conversation import ContactConversationProgram, ConversationTurnResult
from backend.database import (
    Company,
    CompanyLanguage,
    Contact,
    ContactStatus,
    Message,
    MessageDeliveryStatus,
    Task,
    canonical_contact_type,
    normalize_contact_value,
)
from backend.templates import (
    WhatsAppIntroTemplatePayload,
    build_intro_template_payload,
    extract_intro_sender_name,
)

messages_router = APIRouter(prefix="/api", tags=["messages"])
logger = logging.getLogger(__name__)
INBOUND_REPLY_TIMEOUT_SECONDS = 90
EMAIL_REPLY_DELAY_SECONDS = max(0, int(os.getenv("EMAIL_REPLY_DELAY_SECONDS", "0")))
FIRST_MESSAGE_TASK_TYPE = "generate_contact_first_message_core"
DEFAULT_CONTACT_OBJECTIVE = "Evaluate sales process quality through a buyer conversation."


class InboundMessageCommand(BaseModel):
    """Inbound message processing input."""

    message: str = Field(min_length=1)
    external_id: str | None = None
    channel: str | None = None
    inbox_id: str | None = None
    thread_id: str | None = None
    in_reply_to: str | None = None
    references: str | None = None


class InboundMessageResult(BaseModel):
    """Inbound message processing output."""

    contact_id: str
    inbound_message_id: int | None = None
    outbound_message_id: int | None = None
    reply: str | None = None
    duplicate_ignored: bool = False


class InboundTaskCreatedResponse(BaseModel):
    """Task creation response for inbound processing."""

    task_id: str
    status: str


class ContactMessagesResponse(BaseModel):
    """Transcript payload for one contact."""

    company_id: str
    contact_id: str
    messages: list[Message] = Field(default_factory=list)


class UpdateMessageCommand(BaseModel):
    """Message text update input."""

    text: str = Field(min_length=1)


class UpdateEmailThreadLinkCommand(BaseModel):
    """Email thread link update input."""

    thread_link: str | None = None


class SetMessageDeliveryCommand(BaseModel):
    """Manual message delivery update input."""

    delivered: bool = True
    status: str | None = None
    external_id: str | None = None
    inbox_id: str | None = None
    inbox_address: str | None = None
    thread_id: str | None = None
    rfc_message_id: str | None = None


class SetMessageDeliveryByExternalIdCommand(BaseModel):
    """Delivery status update keyed by provider external id."""

    external_id: str = Field(min_length=1)
    status: str = Field(min_length=1)


class ResolveContactResponse(BaseModel):
    """Resolved contact target for one inbound event."""

    company_id: str
    contact_id: str
    contact_type: str
    contact_value: str


class ResolvedContactItem(BaseModel):
    """One contact resolved by value."""

    company_id: str
    contact_id: str
    contact_type: str
    contact_value: str
    status: str


class ResolveContactsByValueResponse(BaseModel):
    """Contact resolution payload by raw contact value."""

    query_value: str
    total_matches: int
    matches: list[ResolvedContactItem] = Field(default_factory=list)


class PendingDeliveryMessage(BaseModel):
    """One outbound message pending provider dispatch."""

    message_id: int
    company_id: str
    company_name: str
    company_source_url: str | None = None
    company_language: CompanyLanguage | None = None
    contact_id: str
    contact_has_inbound: bool = False
    contact_type: str
    contact_value: str
    text: str
    dispatch_after: datetime
    timestamp: datetime
    email_inbox_id: str | None = None
    email_inbox_address: str | None = None
    email_thread_id: str | None = None
    email_last_outbound_rfc_id: str | None = None
    whatsapp_template_name: str | None = None
    whatsapp_template_language: str | None = None
    whatsapp_template_client_name: str | None = None
    whatsapp_template_company_url: str | None = None


class PendingDeliveryResponse(BaseModel):
    """Pending outbound delivery payload."""

    messages: list[PendingDeliveryMessage] = Field(default_factory=list)


class DeleteContactResponse(BaseModel):
    """Deletion result for one contact."""

    deleted: bool = True
    company_id: str
    contact_id: str
    contact_type: str
    contact_value: str


def ensure_contact_in_company(company_id: str, contact_id: str) -> Contact:
    """Return one active contact scoped to one company."""
    contact = Contact.get_by_id(contact_id)
    if not contact or contact.company_id != company_id:
        raise HTTPException(status_code=404, detail="Contact not found in this company")
    if contact.status == ContactStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Contact is archived. Unarchive it to continue.")
    return contact


def ensure_active_contact(contact_id: str) -> Contact:
    """Return one active contact by ID."""
    contact = Contact.get_by_id(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    if contact.status == ContactStatus.ARCHIVED:
        raise HTTPException(status_code=409, detail="Contact is archived. Unarchive it to continue.")
    return contact


def ensure_contact_company(contact: Contact) -> Company:
    """Return company for one contact."""
    company = Company.get_by_id(contact.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


def normalize_provider_id(raw_value: str | None) -> str | None:
    """Normalize one external provider ID."""
    value = (raw_value or "").strip()
    return value or None


def get_duplicate_inbound(contact_id: str, external_id: str | None) -> Message | None:
    """Return previously persisted inbound message for same provider ID."""
    if not external_id:
        return None
    return Message.get_by_external_id(
        contact_id=contact_id,
        external_id=external_id,
        from_me=False,
    )


def build_duplicate_result(contact_id: str, duplicate: Message) -> InboundMessageResult:
    """Build idempotent response when inbound already exists."""
    latest_outbound = Message.get_latest_ai_message(contact_id)
    outbound_id = latest_outbound.id if latest_outbound and latest_outbound.id else None
    reply = latest_outbound.text if latest_outbound else None
    return InboundMessageResult(
        contact_id=contact_id,
        inbound_message_id=duplicate.id,
        outbound_message_id=outbound_id,
        reply=reply,
        duplicate_ignored=True,
    )


def persist_inbound_message(contact_id: str, message: str, external_id: str | None) -> Message:
    """Persist inbound message turn."""
    return Message.add(
        contact_id=contact_id,
        from_me=False,
        text=message,
        external_id=external_id,
    )


def sync_email_thread_from_inbound(
    contact: Contact,
    *,
    inbox_id: str | None,
    inbox_address: str | None,
    thread_id: str | None,
) -> None:
    """Persist latest AgentMail inbox and thread id when inbound metadata is available."""
    if not contact.is_email:
        return
    if not inbox_id and not inbox_address and not thread_id:
        return
    Contact.update_email_delivery_state(
        contact.id,
        email_inbox_id=inbox_id,
        email_inbox_address=inbox_address,
        email_thread_id=thread_id,
    )


def discard_pending_outbound_messages(contact_id: str) -> int:
    """Drop stale unsent outbound drafts before regenerating a reply."""
    return Message.delete_pending_outbound_for_contact(contact_id)


def is_latest_inbound_message(contact_id: str, inbound_message_id: int | None) -> bool:
    """Return True when one inbound message still owns the latest transcript state."""
    if inbound_message_id is None:
        return False
    latest_inbound = Message.get_latest_inbound_message(contact_id)
    return bool(latest_inbound and latest_inbound.id == inbound_message_id)


async def generate_reply_for_contact(contact: Contact, company: Company) -> ConversationTurnResult:
    """Generate next outbound reply for one contact."""
    stage2 = ContactConversationProgram()
    messages = contact.get_messages(simple=True)
    result = await stage2.aforward(
        conversation=messages,
        objective=(contact.objective or company.objective or DEFAULT_CONTACT_OBJECTIVE).strip() or None,
        company_context=company.company_info,
        target_language=company.language.value if company.language else None,
        industry=company.industry,
        channel=contact.canonical_type,
    )
    if not result.reply.strip():
        raise HTTPException(status_code=500, detail="AI failed to generate a reply")
    return ConversationTurnResult(
        reply=result.reply.strip(),
        done=result.done,
    )


def compute_dispatch_after(contact: Contact) -> datetime:
    """Compute outbound dispatch timestamp by channel policy."""
    delay_seconds = EMAIL_REPLY_DELAY_SECONDS if contact.is_email else 0
    return datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)


def persist_outbound_message(contact_id: str, reply: str, dispatch_after: datetime) -> Message:
    """Persist outbound reply message."""
    return Message.add(
        contact_id=contact_id,
        from_me=True,
        text=reply,
        dispatch_after=dispatch_after,
    )


async def register_contact_inbound_core(
    contact_id: str,
    message: str,
    external_id: str | None = None,
    channel: str | None = None,
    inbox_id: str | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> InboundMessageResult:
    """Persist inbound text, generate outbound reply, and persist the result."""
    del channel, in_reply_to, references

    contact = ensure_active_contact(contact_id)
    company = ensure_contact_company(contact)
    provider_external_id = normalize_provider_id(external_id)
    duplicate = get_duplicate_inbound(contact_id, provider_external_id)
    if duplicate:
        return build_duplicate_result(contact_id, duplicate)

    inbound = persist_inbound_message(contact_id, message, provider_external_id)
    sync_email_thread_from_inbound(
        contact,
        inbox_id=inbox_id,
        inbox_address=None,
        thread_id=thread_id,
    )
    if contact.conversation_done:
        logger.info(
            "Skipping automated reply for contact %s because conversation is already done.",
            contact_id,
        )
        return InboundMessageResult(
            contact_id=contact_id,
            inbound_message_id=inbound.id,
            outbound_message_id=None,
            reply=None,
            duplicate_ignored=False,
        )
    discard_pending_outbound_messages(contact_id)
    reply_result = await generate_reply_for_contact(contact, company)
    if not is_latest_inbound_message(contact_id, inbound.id):
        logger.info(
            "Skipping stale outbound draft for contact %s after newer inbound arrived.",
            contact_id,
        )
        return InboundMessageResult(
            contact_id=contact_id,
            inbound_message_id=inbound.id,
            outbound_message_id=None,
            reply=None,
            duplicate_ignored=False,
        )
    dispatch_after = compute_dispatch_after(contact)
    outbound = persist_outbound_message(contact_id, reply_result.reply, dispatch_after)
    if reply_result.done:
        Contact.update_conversation_done(contact_id, True)

    return InboundMessageResult(
        contact_id=contact_id,
        inbound_message_id=inbound.id,
        outbound_message_id=outbound.id,
        reply=reply_result.reply,
        duplicate_ignored=False,
    )


def normalize_channel(channel: str) -> str:
    """Normalize and validate inbound channel name."""
    value = canonical_contact_type(channel)
    if value in {"email", "whatsapp"}:
        return value
    raise HTTPException(status_code=422, detail="channel must be one of: email, whatsapp")


def effective_normalized_contact_value(contact: Contact) -> str:
    """Resolve one contact's canonical normalized value from its stored raw value."""
    return normalize_contact_value(contact.canonical_type, contact.value)


def parse_outbound_delivery_status(status: str | None) -> MessageDeliveryStatus:
    """Parse one outbound delivery status string into MessageDeliveryStatus."""
    value = (status or "").strip().lower()
    if value == MessageDeliveryStatus.UNDELIVERED.value:
        return MessageDeliveryStatus.UNDELIVERED
    if value == MessageDeliveryStatus.SENT.value:
        return MessageDeliveryStatus.SENT
    if value == MessageDeliveryStatus.DELIVERED.value:
        return MessageDeliveryStatus.DELIVERED
    if value == MessageDeliveryStatus.FAILED.value:
        return MessageDeliveryStatus.FAILED
    raise HTTPException(
        status_code=422,
        detail="status must be one of: undelivered, sent, delivered, failed",
    )


def filter_contacts_for_conversation_automation(contacts: list[Contact]) -> list[Contact]:
    """Keep contacts that belong to companies authorized for conversation automation."""
    if not contacts:
        return []
    enabled_company_ids = Company.list_conversation_automation_enabled_ids(
        company_ids={item.company_id for item in contacts},
    )
    if not enabled_company_ids:
        return []
    return [item for item in contacts if item.company_id in enabled_company_ids]


def resolve_whatsapp_contact_by_replied_message(in_reply_to: str | None) -> Contact | None:
    """Resolve one active WhatsApp contact by replied outbound message external id."""
    replied_external_id = (in_reply_to or "").strip()
    if not replied_external_id:
        return None

    outbound_rows = Message.list_by_external_id(replied_external_id, from_me=True)
    if not outbound_rows:
        return None

    candidate_contacts: list[Contact] = []
    seen_contact_ids: set[str] = set()
    for row in outbound_rows:
        contact_id = (row.contact_id or "").strip()
        if not contact_id:
            continue
        if contact_id in seen_contact_ids:
            continue
        seen_contact_ids.add(contact_id)
        contact = Contact.get_by_id(contact_id)
        if not contact:
            continue
        if contact.status != ContactStatus.ACTIVE:
            continue
        if not contact.is_whatsapp:
            continue
        candidate_contacts.append(contact)

    matches = filter_contacts_for_conversation_automation(candidate_contacts)

    if not matches:
        return None
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous whatsapp in-reply-to match")
    return matches[0]


def resolve_whatsapp_contact(value: str, in_reply_to: str | None = None) -> Contact:
    """Resolve one active WhatsApp contact by phone number."""
    resolved_by_reply = resolve_whatsapp_contact_by_replied_message(in_reply_to)
    if resolved_by_reply is not None:
        return resolved_by_reply

    normalized_value = normalize_contact_value("whatsapp", value)
    if not normalized_value:
        raise HTTPException(status_code=422, detail="value is required")

    active_contacts = filter_contacts_for_conversation_automation(
        Contact.list_by_normalized_value(
            normalized_value,
            status=ContactStatus.ACTIVE,
        )
    )
    matches = [
        item
        for item in active_contacts
        if item.is_whatsapp and effective_normalized_contact_value(item) == normalized_value
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="No active contact matched this whatsapp value")

    company_ids = {item.company_id for item in matches}
    if len(company_ids) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous whatsapp value across companies")

    whatsapp_matches = [item for item in matches if item.type.strip().lower() == "whatsapp"]
    if len(whatsapp_matches) == 1:
        return whatsapp_matches[0]
    if len(whatsapp_matches) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous whatsapp value inside one company")

    if len(matches) == 1:
        return matches[0]
    raise HTTPException(status_code=409, detail="Ambiguous whatsapp value inside one company")


def resolve_email_contact(
    value: str,
    thread_id: str | None,
    in_reply_to: str | None,
    inbox_id: str | None,
) -> Contact:
    """Resolve one active email contact by inbox, thread, in-reply-to, and sender fallback."""
    normalized_email = normalize_contact_value("email", value)
    if not normalized_email:
        raise HTTPException(status_code=422, detail="value is required")

    active_email_contacts = filter_contacts_for_conversation_automation(
        [
            item
            for item in Contact.list_active()
            if item.is_email
        ]
    )
    if not active_email_contacts:
        raise HTTPException(status_code=404, detail="No active contact matched this email value")

    clean_thread_id = (thread_id or "").strip()
    if clean_thread_id:
        by_thread = [
            item
            for item in active_email_contacts
            if (item.email_thread_id or "").strip() == clean_thread_id
        ]
        if len(by_thread) == 1:
            return by_thread[0]
        if len(by_thread) > 1:
            raise HTTPException(status_code=409, detail="Ambiguous email thread match")

    clean_reply_id = (in_reply_to or "").strip()
    if clean_reply_id:
        by_reply = [
            item
            for item in active_email_contacts
            if (item.email_last_outbound_rfc_id or "").strip() == clean_reply_id
        ]
        if len(by_reply) == 1:
            return by_reply[0]
        if len(by_reply) > 1:
            raise HTTPException(status_code=409, detail="Ambiguous email in-reply-to match")

    contacts = filter_contacts_for_conversation_automation(
        [
            item for item in active_email_contacts if item.normalized_value == normalized_email
        ]
    )
    if not contacts:
        clean_inbox_id = (inbox_id or "").strip()
        if clean_inbox_id:
            by_inbox = Contact.get_by_email_inbox_id(clean_inbox_id)
            if (
                by_inbox
                and by_inbox.is_email
                and not (by_inbox.email_thread_id or "").strip()
            ):
                return by_inbox
        raise HTTPException(status_code=404, detail="No active contact matched this email value")

    if len(contacts) == 1:
        contact = contacts[0]
        clean_inbox_id = (inbox_id or "").strip()
        assigned_inbox_id = (contact.email_inbox_id or "").strip()
        if clean_inbox_id and assigned_inbox_id and clean_inbox_id != assigned_inbox_id:
            raise HTTPException(status_code=404, detail="No active contact matched this email value")
        return contact
    raise HTTPException(status_code=409, detail="Ambiguous sender email across active contacts")


def build_pending_delivery_payload(limit: int) -> PendingDeliveryResponse:
    """Build pending delivery payload from DB state."""
    pending_rows = Message.list_pending_delivery(limit=limit)
    pending_pairs: list[tuple[Message, Contact, Company]] = []

    for row in pending_rows:
        if not row.id:
            continue
        contact = Contact.get_by_id(row.contact_id)
        if not contact or contact.status != ContactStatus.ACTIVE:
            continue
        company = Company.get_by_id(contact.company_id)
        if not company:
            continue
        pending_pairs.append((row, contact, company))

    enabled_company_ids = Company.list_conversation_automation_enabled_ids(
        company_ids={contact.company_id for _, contact, _ in pending_pairs},
    )
    items: list[PendingDeliveryMessage] = []

    for row, contact, company in pending_pairs:
        if contact.company_id not in enabled_company_ids:
            continue
        contact_has_inbound = Message.has_inbound_for_contact(contact.id)
        template_payload = resolve_pending_whatsapp_template_payload(
            row=row,
            contact=contact,
            company=company,
            contact_has_inbound=contact_has_inbound,
        )
        items.append(
            PendingDeliveryMessage(
                message_id=row.id,
                company_id=contact.company_id,
                company_name=company.company_name,
                company_source_url=company.source_url,
                company_language=company.language,
                contact_id=contact.id,
                contact_has_inbound=contact_has_inbound,
                contact_type=contact.canonical_type,
                contact_value=contact.value,
                text=row.text,
                dispatch_after=row.dispatch_after,
                timestamp=row.timestamp,
                email_inbox_id=contact.email_inbox_id,
                email_inbox_address=contact.email_inbox_address,
                email_thread_id=contact.email_thread_id,
                email_last_outbound_rfc_id=contact.email_last_outbound_rfc_id,
                whatsapp_template_name=(
                    template_payload.whatsapp_template_name
                    if template_payload
                    else None
                ),
                whatsapp_template_language=(
                    template_payload.whatsapp_template_language
                    if template_payload
                    else None
                ),
                whatsapp_template_client_name=(
                    template_payload.whatsapp_template_client_name
                    if template_payload
                    else None
                ),
                whatsapp_template_company_url=(
                    template_payload.whatsapp_template_company_url
                    if template_payload
                    else None
                ),
            )
        )

    return PendingDeliveryResponse(messages=items)


def is_first_outbound_message_for_contact(
    *,
    contact_id: str,
    message_id: int | None,
) -> bool:
    """Return True when message id matches first outbound turn for one contact."""
    if message_id is None:
        return False
    rows = Message.list_by_contact(contact_id)
    for item in rows:
        if item.from_me:
            return item.id == message_id
    return False


def resolve_pending_whatsapp_template_payload(
    *,
    row: Message,
    contact: Contact,
    company: Company,
    contact_has_inbound: bool,
) -> WhatsAppIntroTemplatePayload | None:
    """Resolve first-outbound WhatsApp template payload for pending dispatch row."""
    if contact.canonical_type != "whatsapp":
        return None
    if contact_has_inbound:
        return None
    if not is_first_outbound_message_for_contact(
        contact_id=contact.id,
        message_id=row.id,
    ):
        return None
    sender_name = extract_intro_sender_name(row.text) or "Konecta"
    return build_intro_template_payload(
        company_language=company.language,
        company_url=company.source_url,
        client_name=sender_name,
    )


def build_tracked_contact_values(channel: str) -> list[str]:
    """Build unique normalized contact values for one active channel."""
    normalized_channel = normalize_channel(channel)
    active_contacts = filter_contacts_for_conversation_automation(Contact.list_active())
    if normalized_channel == "email":
        return sorted(
            {
                effective_normalized_contact_value(item)
                for item in active_contacts
                if item.is_email and effective_normalized_contact_value(item)
            }
        )
    return sorted(
        {
            effective_normalized_contact_value(item)
            for item in active_contacts
            if item.is_whatsapp and effective_normalized_contact_value(item)
        }
    )


def resolve_contacts_by_value(value: str, channel: str | None = None) -> list[Contact]:
    """Resolve active contacts by raw value, optionally constrained by channel."""
    raw_value = value.strip()
    if not raw_value:
        raise HTTPException(status_code=422, detail="value is required")

    normalized_channel = normalize_channel(channel) if channel is not None else None
    active_contacts = Contact.list_active()
    matches: list[Contact] = []
    for item in active_contacts:
        if normalized_channel and item.canonical_type != normalized_channel:
            continue
        normalized_input = normalize_contact_value(item.canonical_type, raw_value)
        if not normalized_input:
            continue
        if effective_normalized_contact_value(item) == normalized_input:
            matches.append(item)
    return sorted(matches, key=lambda item: (item.created_at, item.id))


@messages_router.get("/companies/{company_id}/contacts/{contact_id}/messages", response_model=ContactMessagesResponse)
async def get_contact_messages_for_company(company_id: str, contact_id: str):
    """Get full transcript for one contact."""
    contact = ensure_contact_in_company(company_id, contact_id)

    messages = contact.get_messages()
    return ContactMessagesResponse(
        company_id=company_id,
        contact_id=contact.id,
        messages=messages,
    )


@messages_router.post("/companies/{company_id}/contacts/{contact_id}/messages/inbound", response_model=InboundTaskCreatedResponse)
async def register_contact_inbound(
    company_id: str,
    contact_id: str,
    request: InboundMessageCommand,
    background_tasks: BackgroundTasks,
):
    """Register inbound contact text and queue next AI draft generation."""
    contact = ensure_contact_in_company(company_id, contact_id)
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="message is required")
    if Task.has_pending_for_resource(
        resource_id=contact.id,
        task_type=FIRST_MESSAGE_TASK_TYPE,
    ):
        raise HTTPException(
            status_code=409,
            detail="First draft is still being generated for this contact.",
        )

    task = Task.run_async(
        background_tasks,
        register_contact_inbound_core,
        resource_id=contact.id,
        timeout_seconds=INBOUND_REPLY_TIMEOUT_SECONDS,
        contact_id=contact.id,
        message=message,
        external_id=request.external_id,
        channel=request.channel,
        inbox_id=request.inbox_id,
        thread_id=request.thread_id,
        in_reply_to=request.in_reply_to,
        references=request.references,
    )
    return InboundTaskCreatedResponse(task_id=task.id, status=task.status.value)


@messages_router.put("/companies/{company_id}/contacts/{contact_id}/messages/{message_id}", response_model=Message)
async def update_contact_message(
    company_id: str,
    contact_id: str,
    message_id: int,
    request: UpdateMessageCommand,
):
    """Update one message text in one contact transcript."""
    ensure_contact_in_company(company_id, contact_id)

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")

    row = Message.update_text(
        contact_id=contact_id,
        message_id=message_id,
        text=text,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Message not found in this contact")
    return row


@messages_router.put(
    "/companies/{company_id}/contacts/{contact_id}/messages/{message_id}/delivery",
    response_model=Message,
)
async def set_contact_message_delivery_status(
    company_id: str,
    contact_id: str,
    message_id: int,
    request: SetMessageDeliveryCommand,
):
    """Manually mark one outbound message as delivered/undelivered."""
    contact = ensure_contact_in_company(company_id, contact_id)

    row = Message.get_by_id_for_contact(contact_id=contact_id, message_id=message_id)
    if not row:
        raise HTTPException(status_code=404, detail="Message not found in this contact")
    if not row.from_me:
        raise HTTPException(status_code=409, detail="Only outbound messages support delivery status")

    target_status = (
        parse_outbound_delivery_status(request.status)
        if request.status is not None
        else (
            MessageDeliveryStatus.DELIVERED
            if request.delivered
            else MessageDeliveryStatus.UNDELIVERED
        )
    )
    updated = Message.update_delivery_status(
        contact_id=contact_id,
        message_id=message_id,
        delivery_status=target_status,
        external_id=request.external_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Message not found in this contact")

    if target_status in {MessageDeliveryStatus.SENT, MessageDeliveryStatus.DELIVERED} and contact.is_email:
        Contact.update_email_delivery_state(
            contact_id,
            email_inbox_id=request.inbox_id,
            email_inbox_address=request.inbox_address,
            email_thread_id=request.thread_id,
            email_last_outbound_rfc_id=request.rfc_message_id,
        )

    return updated


@messages_router.put("/messages/delivery/by-external-id", response_model=Message)
async def set_message_delivery_status_by_external_id(
    request: SetMessageDeliveryByExternalIdCommand,
):
    """Update one outbound message delivery status using provider external id."""
    matches = Message.list_by_external_id(request.external_id, from_me=True)
    if not matches:
        raise HTTPException(status_code=404, detail="Outbound message not found for external_id")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous external_id across outbound messages")

    row = matches[0]
    if row.id is None:
        raise HTTPException(status_code=404, detail="Outbound message not found for external_id")

    updated = Message.update_delivery_status(
        contact_id=row.contact_id,
        message_id=row.id,
        delivery_status=parse_outbound_delivery_status(request.status),
        external_id=request.external_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Outbound message not found for external_id")
    return updated


@messages_router.get("/contacts/resolve", response_model=ResolveContactResponse)
async def resolve_contact(
    channel: str,
    value: str,
    inbox_id: str | None = None,
    thread_id: str | None = None,
    in_reply_to: str | None = None,
):
    """Resolve one active contact from channel-level inbound metadata."""
    normalized_channel = normalize_channel(channel)
    contact = (
        resolve_email_contact(value, thread_id, in_reply_to, inbox_id)
        if normalized_channel == "email"
        else resolve_whatsapp_contact(value, in_reply_to)
    )
    return ResolveContactResponse(
        company_id=contact.company_id,
        contact_id=contact.id,
        contact_type=contact.canonical_type,
        contact_value=contact.value,
    )


@messages_router.get("/contacts/resolve-by-value", response_model=ResolveContactsByValueResponse)
async def resolve_contacts_by_contact_value(
    value: str,
    channel: str | None = None,
):
    """Resolve active contacts by value with optional channel filter."""
    matches = resolve_contacts_by_value(value, channel=channel)
    return ResolveContactsByValueResponse(
        query_value=value.strip(),
        total_matches=len(matches),
        matches=[
            ResolvedContactItem(
                company_id=item.company_id,
                contact_id=item.id,
                contact_type=item.canonical_type,
                contact_value=item.value,
                status=item.status.value,
            )
            for item in matches
        ],
    )


@messages_router.delete("/contacts/{contact_id}", response_model=DeleteContactResponse)
async def delete_contact_by_id(contact_id: str):
    """Delete one contact and all related messages by contact ID only."""
    contact = Contact.get_by_id(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    deleted = Contact.delete_by_id(contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    return DeleteContactResponse(
        company_id=contact.company_id,
        contact_id=contact.id,
        contact_type=contact.canonical_type,
        contact_value=contact.value,
    )


@messages_router.get("/messages/pending-delivery", response_model=PendingDeliveryResponse)
async def list_pending_delivery_messages(
    limit: int = Query(default=100, ge=1, le=500),
):
    """List outbound undelivered messages that are ready for provider dispatch."""
    return build_pending_delivery_payload(limit)


class TrackedContactValuesResponse(BaseModel):
    """Tracked normalized values for one channel."""

    channel: str
    values: list[str] = Field(default_factory=list)


@messages_router.get("/contacts/tracked-values", response_model=TrackedContactValuesResponse)
async def list_tracked_contact_values(
    channel: str,
):
    """List unique normalized active contact values for one channel."""
    normalized_channel = normalize_channel(channel)
    values = build_tracked_contact_values(normalized_channel)
    return TrackedContactValuesResponse(
        channel=normalized_channel,
        values=values,
    )


@messages_router.put("/companies/{company_id}/contacts/{contact_id}/email-thread-link")
async def update_contact_email_thread_link(
    company_id: str,
    contact_id: str,
    request: UpdateEmailThreadLinkCommand,
):
    """Store or clear a manually provided email thread URL for one contact."""
    ensure_contact_in_company(company_id, contact_id)

    raw_value = (request.thread_link or "").strip()
    if raw_value and not (raw_value.startswith("http://") or raw_value.startswith("https://")):
        raise HTTPException(status_code=422, detail="thread_link must be a full http(s) URL")

    updated = Contact.update_additional_info(contact_id, raw_value or None)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")

    return {
        "contact_id": updated.id,
        "thread_link": updated.additional_info,
    }


def format_sidebar_assistant_conversation(messages: list["SidebarAssistantChatMessage"]) -> str:
    """Convert one stateless chat payload into a compact transcript string."""
    lines: list[str] = []
    for item in messages:
        speaker = "User" if item.role == "user" else "Assistant"
        lines.append(f"{speaker}: {item.content.strip()}")
    return "\n\n".join(lines)


def build_sidebar_assistant_focus_context(
    company_id: str | None,
    contact_id: str | None,
) -> str:
    """Build optional selected company/contact context for the sidebar assistant."""
    parts: list[str] = []

    company = Company.get_by_id(company_id) if company_id else None
    if company:
        tags = ", ".join(company.tags) if company.tags else "none"
        parts.extend(
            [
                "Current selected company:",
                f"- company_id: {company.id}",
                f"- company_name: {company.company_name}",
                f"- source_url: {company.source_url}",
                f"- status: {company.status.value}",
                f"- language: {company.language.value if company.language else 'unknown'}",
                f"- industry: {company.industry}",
                f"- company_size: {company.company_size}",
                f"- tags: {tags}",
            ]
        )

    contact = Contact.get_by_id(contact_id) if contact_id else None
    if contact and (not company or contact.company_id == company.id):
        parts.extend(
            [
                "Current selected contact:",
                f"- contact_id: {contact.id}",
                f"- company_id: {contact.company_id}",
                f"- contact_type: {contact.canonical_type}",
                f"- contact_value: {contact.value}",
                f"- status: {contact.status.value}",
            ]
        )

    return "\n".join(parts) if parts else "No selected company or contact."


class SidebarAssistantChatMessage(BaseModel):
    """One stateless sidebar chat message."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class SidebarAssistantReplyCommand(BaseModel):
    """Sidebar assistant input payload."""

    conversation: list[SidebarAssistantChatMessage] = Field(min_length=1, max_length=40)
    company_id: str | None = None
    contact_id: str | None = None


class SidebarAssistantReply(BaseModel):
    """Sidebar assistant response payload."""

    reply: str


@messages_router.post("/sidebar-assistant/reply", response_model=SidebarAssistantReply)
async def generate_sidebar_assistant_reply(
    payload: SidebarAssistantReplyCommand,
    request: Request,
):
    """Generate one stateless sidebar assistant reply from the provided conversation."""
    logger.info(
        "Sidebar assistant request: conversation_length=%d, company_id=%s, contact_id=%s",
        len(payload.conversation),
        payload.company_id,
        payload.contact_id,
    )
    conversation = format_sidebar_assistant_conversation(payload.conversation)
    focus_context = build_sidebar_assistant_focus_context(
        payload.company_id,
        payload.contact_id,
    )
    user_id = str(getattr(request.state, "authenticated_user", "anonymous") or "anonymous").strip()
    assistant = KonectaAuditorSidebarAssistant(user_id=user_id or "anonymous")

    try:
        result = await assistant.aforward(
            conversation=conversation,
            focus_context=focus_context,
        )
    except Exception as exc:
        logger.exception("Sidebar assistant failed for user %s", user_id or "anonymous")
        raise HTTPException(status_code=500, detail=f"Sidebar assistant failed: {exc}") from exc

    reply = str(getattr(result, "response", "") or "").strip()
    if not reply:
        raise HTTPException(status_code=500, detail="Sidebar assistant returned an empty reply.")

    return SidebarAssistantReply(reply=reply)
