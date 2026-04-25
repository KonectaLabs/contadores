"""Channel provider integrations for stateless bot runtime."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from datetime import datetime, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

import httpx
import phonenumbers
from agentmail import AsyncAgentMail, AgentMailEnvironment
from fastapi import FastAPI
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from phonenumbers import NumberParseException
from pydantic import BaseModel
from pywa.types.templates import BodyText, TemplateLanguage
from pywa_async import WhatsApp, types, utils as pywa_utils
from svix.webhooks import Webhook as SvixWebhook
from unquotemail import Unquote

logger = logging.getLogger(__name__)

WA_MAX_LENGTH = 4096
DEFAULT_EMAIL_SUBJECT = "Inquiry"
AGENTMAIL_ALERT_INBOX_CLIENT_ID = "contadores-alerts"
AGENTMAIL_WEBHOOK_CLIENT_ID = "contadores-agentmail-webhook"
AGENTMAIL_SHARED_INBOX_IDS_ENV = "AGENTMAIL_SHARED_INBOX_IDS"
DEFAULT_AGENTMAIL_SHARED_INBOX_IDS = (
    "maximorodriguez@agentmail.to",
    "rodrio@agentmail.to",
    "jrazzler@agentmail.to",
)
AGENTMAIL_WEBHOOK_EVENT_TYPES = [
    "message.received",
    "message.delivered",
    "message.bounced",
    "message.rejected",
]
EMAIL_ADDRESS_PATTERN = re.compile(
    r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+$",
    re.IGNORECASE,
)


class InvalidRecipientEmailError(ValueError):
    """Raised when an outbound email recipient is syntactically invalid."""


def normalize_email_address(value: str) -> str:
    """Normalize one email address candidate for provider validation."""
    return parseaddr(value or "")[1].strip().lower()


def is_valid_email_address(value: str) -> bool:
    """Return True when an outbound email address is syntactically complete."""
    clean = normalize_email_address(value)
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


def default_phone_region() -> str:
    """Return the default region used for local WhatsApp phone normalization."""
    return (os.getenv("PHONE_DEFAULT_REGION", "AR") or "AR").strip().upper() or "AR"


def extract_phone_candidate(value: str) -> str:
    """Extract one phone-like candidate from raw text or WhatsApp links."""
    raw = unquote((value or "").strip())
    if not raw:
        return ""
    if "://" in raw or raw.lower().startswith("wa.me/"):
        candidate_url = raw if "://" in raw else f"https://{raw}"
        parsed = urlparse(candidate_url)
        host = (parsed.netloc or "").strip().lower()
        if host.endswith("wa.me"):
            return parsed.path.strip("/").split("/", 1)[0].strip()
        phone = parse_qs(parsed.query).get("phone", [""])[0].strip()
        if phone:
            return phone
    return raw


def looks_like_argentine_local_phone(digits: str) -> bool:
    """Return True when digits look like an Argentina-local WhatsApp number."""
    compact = (digits or "").strip()
    if not compact:
        return False
    if compact.startswith("0"):
        return True
    if "15" in compact[:7]:
        return True
    return len(compact) == 10 and compact.startswith("11")


def normalize_parsed_phone(parsed: phonenumbers.PhoneNumber) -> str:
    """Convert one parsed phone to canonical digits-only WhatsApp form."""
    country_code = str(parsed.country_code or "").strip()
    national_number = str(parsed.national_number or "").strip()
    if not country_code or not national_number:
        return ""
    if country_code == "54":
        if national_number.startswith("9"):
            national_number = national_number[1:]
        return f"549{national_number}" if national_number else ""
    return f"{country_code}{national_number}"


def normalize_whatsapp_phone(value: str) -> str:
    """Normalize one WhatsApp destination to canonical digits-only form."""
    raw = extract_phone_candidate(value)
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
    elif default_phone_region() == "AR" and looks_like_argentine_local_phone(digits):
        parse_candidate = raw
        region = "AR"
    else:
        return digits

    try:
        parsed = phonenumbers.parse(parse_candidate, region)
    except NumberParseException:
        return digits

    if not phonenumbers.is_possible_number(parsed):
        return digits

    normalized = normalize_parsed_phone(parsed)
    return normalized or digits


class DeliveryReceipt(BaseModel):
    """Provider send response metadata."""

    external_id: str
    inbox_id: str | None = None
    inbox_address: str | None = None
    thread_id: str | None = None
    rfc_message_id: str | None = None
    delivered_text: str | None = None
    from_email: str | None = None


class EmailAttachment(BaseModel):
    """One outbound email attachment payload."""

    filename: str
    content_type: str = "application/octet-stream"
    data: bytes


class EmailInboundEvent(BaseModel):
    """One inbound email event from AgentMail."""

    inbox_id: str
    message_id: str
    from_email: str
    plain_text: str
    thread_id: str | None = None
    in_reply_to: str | None = None
    references: str | None = None
    subject: str | None = None


class EmailInboxState(BaseModel):
    """One persisted AgentMail inbox assignment."""

    inbox_id: str
    inbox_address: str


class WhatsAppInboundEvent(BaseModel):
    """One inbound WhatsApp event from webhook."""

    phone: str
    text: str
    external_id: str | None = None
    in_reply_to: str | None = None


class WhatsAppMessageStatusEvent(BaseModel):
    """One outbound WhatsApp message status update from webhook."""

    external_id: str
    status: str


class GmailProvider:
    """Legacy Gmail inbound provider kept for replies sent before AgentMail rollout."""

    def __init__(self) -> None:
        self.client_id = os.getenv("GMAIL_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("GMAIL_CLIENT_SECRET", "").strip()
        self.refresh_token = os.getenv("GMAIL_REFRESH_TOKEN", "").strip()

    @property
    def configured(self) -> bool:
        """Return True when Gmail OAuth config is available."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def _get_credentials(self) -> Credentials:
        """Build refreshed OAuth2 credentials."""
        if not self.configured:
            raise RuntimeError("Gmail is not configured")
        credentials = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.modify",
            ],
        )
        credentials.refresh(Request())
        return credentials

    def _build_service(self) -> Any:
        """Build Gmail API service client."""
        credentials = self._get_credentials()
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def _decode_data(self, raw_data: str | None) -> str:
        """Decode one Gmail payload body fragment."""
        if not raw_data:
            return ""
        return base64.urlsafe_b64decode(raw_data.encode("utf-8")).decode("utf-8", errors="ignore")

    def _extract_header(self, headers: list[dict[str, str]], header_name: str) -> str:
        """Extract one email header by name."""
        target = header_name.lower()
        for header in headers:
            if str(header.get("name", "")).lower() == target:
                return str(header.get("value", "")).strip()
        return ""

    def _extract_mime_part(self, payload: dict[str, Any], *, target_mime_type: str) -> str:
        """Extract first matching MIME part from Gmail payload tree."""
        mime_type = str(payload.get("mimeType", "")).lower()
        body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
        parts = payload.get("parts") if isinstance(payload.get("parts"), list) else []

        if mime_type == target_mime_type:
            return self._decode_data(body.get("data"))

        for part in parts:
            if not isinstance(part, dict):
                continue
            part_text = self._extract_mime_part(part, target_mime_type=target_mime_type)
            if part_text.strip():
                return part_text

        if not parts:
            if mime_type and mime_type != target_mime_type:
                return ""
            return self._decode_data(body.get("data"))
        return ""

    def _extract_plain_text(self, payload: dict[str, Any]) -> str:
        """Extract first plain text part from Gmail payload tree."""
        return self._extract_mime_part(payload, target_mime_type="text/plain")

    def _extract_html_text(self, payload: dict[str, Any]) -> str:
        """Extract first HTML part from Gmail payload tree."""
        return self._extract_mime_part(payload, target_mime_type="text/html")

    def _extract_latest_reply_text(
        self,
        *,
        plain_text: str,
        html_text: str,
        snippet: str,
    ) -> str:
        """Return only the latest human reply from one inbound Gmail body."""
        clean_text = plain_text.strip() or snippet.strip()
        if not clean_text:
            return ""

        clean_html = html_text.strip() or clean_text
        try:
            parsed = Unquote(html=clean_html, text=clean_text, parse=True).get_text().strip()
            return parsed or clean_text
        except Exception:
            logger.debug("Failed to parse inbound Gmail quoted thread; using raw plain text", exc_info=True)
            return clean_text

    def _build_sender_query(self, tracked_senders: set[str] | None) -> str | None:
        """Build Gmail search query for tracked sender filters."""
        if not tracked_senders:
            return None
        terms = [f"from:{sender}" for sender in sorted(tracked_senders)]
        if len(terms) == 1:
            return terms[0]
        return f"({' OR '.join(terms)})"

    async def list_unread_messages(
        self,
        *,
        max_results: int = 50,
        tracked_senders: set[str] | None = None,
    ) -> list[EmailInboundEvent]:
        """List unread inbound Gmail messages that match tracked senders."""
        if not self.configured:
            return []

        service = await asyncio.to_thread(self._build_service)
        query_parts = ["is:unread", "-from:me"]
        sender_query = self._build_sender_query(tracked_senders)
        if sender_query:
            query_parts.append(sender_query)
        query = " ".join(query_parts)

        response = await asyncio.to_thread(
            lambda: service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_results,
            ).execute()
        )
        items = response.get("messages", []) if isinstance(response, dict) else []
        events: list[EmailInboundEvent] = []

        for item in items:
            gmail_id = str(item.get("id") or "").strip()
            if not gmail_id:
                continue

            message = await asyncio.to_thread(
                lambda: service.users().messages().get(userId="me", id=gmail_id, format="full").execute()
            )
            payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
            headers = payload.get("headers") if isinstance(payload.get("headers"), list) else []
            from_email = normalize_email_address(self._extract_header(headers, "From"))
            if tracked_senders and from_email not in tracked_senders:
                continue

            plain_text = self._extract_plain_text(payload)
            html_text = self._extract_html_text(payload)
            latest_reply = self._extract_latest_reply_text(
                plain_text=plain_text,
                html_text=html_text,
                snippet=str(message.get("snippet") or ""),
            )
            events.append(
                EmailInboundEvent(
                    inbox_id="legacy-gmail",
                    message_id=gmail_id,
                    from_email=from_email,
                    plain_text=latest_reply,
                    thread_id=str(message.get("threadId") or "").strip() or None,
                    in_reply_to=self._extract_header(headers, "In-Reply-To") or None,
                    references=self._extract_header(headers, "References") or None,
                    subject=self._extract_header(headers, "Subject") or None,
                )
            )

        return events

    async def mark_as_read(self, gmail_id: str) -> None:
        """Mark one Gmail message as read."""
        if not self.configured:
            return
        clean_gmail_id = (gmail_id or "").strip()
        if not clean_gmail_id:
            return
        service = await asyncio.to_thread(self._build_service)
        await asyncio.to_thread(
            lambda: service.users().messages().modify(
                userId="me",
                id=clean_gmail_id,
                body={"removeLabelIds": ["UNREAD"]},
            ).execute()
        )


class AgentMailProvider:
    """AgentMail provider with per-contact inbox provisioning and webhook support."""

    def __init__(self) -> None:
        self.api_key = os.getenv("AGENTMAIL_API_KEY", "").strip()
        self.domain = (os.getenv("AGENTMAIL_DOMAIN", "") or "").strip() or None
        self.webhook_url = self._resolve_webhook_url()
        self.webhook_secret = (os.getenv("AGENTMAIL_WEBHOOK_SECRET", "") or "").strip() or None
        self._alert_inbox_id_env = (
            (os.getenv("AGENTMAIL_ALERT_INBOX_ID", "") or "").strip()
            or (os.getenv("AGENTMAIL_CRM_INBOX_ID", "") or "").strip()
            or None
        )
        self._shared_inbox_refs = self._resolve_shared_inbox_refs()
        self._http_client: httpx.AsyncClient | None = None
        self._client: AsyncAgentMail | None = None
        self._alert_inbox: EmailInboxState | None = None
        self._shared_inboxes: list[EmailInboxState] = []
        self._shared_inbox_assignments: dict[str, EmailInboxState] = {}
        self._polled_message_ids: set[str] = set()
        self._synced_contact_inbox_display_names: set[str] = set()
        self._webhook_lock = asyncio.Lock()
        self._shared_inbox_selection_lock = asyncio.Lock()
        self._next_shared_inbox_index = 0

        if not self.api_key:
            return

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=True,
        )
        self._client = AsyncAgentMail(
            api_key=self.api_key,
            environment=self._resolve_environment(),
            httpx_client=self._http_client,
        )

    @property
    def configured(self) -> bool:
        """Return True when AgentMail API config is available."""
        return self._client is not None

    async def initialize(self) -> None:
        """Initialize AgentMail client state and restore webhook coverage for existing inboxes."""
        if not self.configured:
            logger.info("⚪ AgentMail is disabled because AGENTMAIL_API_KEY is missing.")
            return
        logger.info(
            "✅ AgentMail ready (webhook_url=%s).",
            self.webhook_url or "disabled",
        )
        inbox_ids = set(await self._list_inbox_ids())
        if inbox_ids:
            await self.ensure_webhook(inbox_ids)
        await self._load_shared_inboxes()

    async def close(self) -> None:
        """Close the underlying async HTTP client."""
        if self._http_client is None:
            return
        await self._http_client.aclose()

    async def ensure_alert_inbox(self) -> EmailInboxState:
        """Return the shared inbox used for Contadores human-review alerts."""
        if self._alert_inbox is not None:
            return self._alert_inbox

        if self._alert_inbox_id_env:
            self._alert_inbox = await self._resolve_existing_inbox(self._alert_inbox_id_env)
            await self.ensure_webhook({self._alert_inbox.inbox_id})
            return self._alert_inbox

        existing = await self._find_inbox_by_client_id(AGENTMAIL_ALERT_INBOX_CLIENT_ID)
        if existing is not None:
            self._alert_inbox = existing
            await self.ensure_webhook({self._alert_inbox.inbox_id})
            return existing

        shared_inboxes = await self._load_shared_inboxes()
        self._alert_inbox = shared_inboxes[0]
        await self.ensure_webhook({self._alert_inbox.inbox_id})
        return self._alert_inbox

    async def ensure_crm_inbox(self) -> EmailInboxState:
        """Backward-compatible alias for older Contadores alert code."""
        return await self.ensure_alert_inbox()

    async def ensure_contact_inbox(
        self,
        *,
        contact_id: str,
        company_name: str,
        contact_value: str,
        current_inbox_id: str | None,
        current_inbox_address: str | None,
        current_thread_id: str | None,
    ) -> EmailInboxState:
        """Return one shared existing inbox for a contact."""
        del company_name, contact_value

        shared_inboxes = await self._load_shared_inboxes()
        shared_inbox_ids = {item.inbox_id for item in shared_inboxes}
        clean_inbox_id = (current_inbox_id or "").strip()
        clean_inbox_address = normalize_email_address(current_inbox_address or "")
        if clean_inbox_id or clean_inbox_address:
            state = await self._resolve_existing_inbox(clean_inbox_id or clean_inbox_address)
            if current_thread_id or state.inbox_id in shared_inbox_ids:
                await self._sync_contact_inbox_display_name(
                    inbox_id=state.inbox_id,
                    inbox_address=state.inbox_address,
                )
                await self.ensure_webhook({state.inbox_id})
                return state

        state = await self._select_shared_inbox(contact_id=contact_id, inboxes=shared_inboxes)
        await self._sync_contact_inbox_display_name(
            inbox_id=state.inbox_id,
            inbox_address=state.inbox_address,
        )
        await self.ensure_webhook({state.inbox_id})
        return state

    async def poll_inbound_events(
        self,
        *,
        limit_per_inbox: int = 20,
    ) -> list[EmailInboundEvent]:
        """Poll recent received messages as a fallback when webhooks are unavailable."""
        if not self.configured:
            return []

        events: list[EmailInboundEvent] = []
        inbox_ids = await self._list_inbox_ids()
        for inbox_id in inbox_ids:
            payload = await self._client.inboxes.messages.list(inbox_id, limit=limit_per_inbox)
            for item in payload.messages:
                clean_message_id = str(item.message_id or "").strip()
                if not clean_message_id:
                    continue
                if clean_message_id in self._polled_message_ids:
                    continue
                labels = {
                    str(label).strip().lower()
                    for label in (item.labels or [])
                    if str(label).strip()
                }
                if "received" not in labels:
                    continue

                message = await self._client.inboxes.messages.get(inbox_id, clean_message_id)
                event = self._build_inbound_event_from_values(
                    inbox_id=message.inbox_id,
                    message_id=message.message_id,
                    from_value=message.from_,
                    plain_text=message.extracted_text or message.text or message.preview,
                    thread_id=message.thread_id,
                    in_reply_to=message.in_reply_to,
                    references=message.references,
                    subject=message.subject,
                )
                if event is None:
                    continue
                events.append(event)

        return events

    async def ensure_webhook(self, inbox_ids: set[str]) -> None:
        """Create or update the AgentMail webhook for the monitored inboxes."""
        cleaned_inbox_ids = {value.strip() for value in inbox_ids if value and value.strip()}
        if not cleaned_inbox_ids:
            return
        if not self.webhook_url:
            return

        async with self._webhook_lock:
            webhook = await self._find_webhook()
            if webhook is None:
                webhook = await self._client.webhooks.create(
                    url=self.webhook_url,
                    event_types=AGENTMAIL_WEBHOOK_EVENT_TYPES,
                    inbox_ids=sorted(cleaned_inbox_ids),
                    client_id=AGENTMAIL_WEBHOOK_CLIENT_ID,
                )
            else:
                current_inbox_ids = {value.strip() for value in (webhook.inbox_ids or []) if value and value.strip()}
                missing_inbox_ids = sorted(cleaned_inbox_ids - current_inbox_ids)
                if missing_inbox_ids:
                    await self._client.webhooks.update(
                        webhook.webhook_id,
                        add_inbox_ids=missing_inbox_ids,
                    )
                    webhook = await self._client.webhooks.get(webhook.webhook_id)

            self.webhook_secret = webhook.secret or self.webhook_secret

    async def send_message(
        self,
        *,
        inbox_id: str,
        inbox_address: str | None,
        recipient: str,
        text: str,
        subject: str | None,
        attachments: list[EmailAttachment] | None,
        thread_id: str | None,
        in_reply_to: str | None,
        references: str | None,
    ) -> DeliveryReceipt:
        """Send one email from a specific AgentMail inbox."""
        del in_reply_to, references

        recipient_email = normalize_email_address(recipient)
        if not recipient_email or not is_valid_email_address(recipient_email):
            raise InvalidRecipientEmailError(f"Recipient email is invalid: {recipient}")

        clean_inbox_id = (inbox_id or "").strip()
        if not clean_inbox_id:
            raise RuntimeError("AgentMail inbox_id is required before sending email")

        clean_thread_id = (thread_id or "").strip() or None
        clean_text = (text or "").strip()
        clean_subject = self._derive_subject(clean_text, subject)
        attachment_payloads = self._build_attachment_payloads(attachments)

        if clean_thread_id:
            reply_message_id = await self._resolve_reply_message_id(
                inbox_id=clean_inbox_id,
                thread_id=clean_thread_id,
            )
            response = await self._client.inboxes.messages.reply(
                clean_inbox_id,
                reply_message_id,
                text=clean_text,
                attachments=attachment_payloads or None,
            )
        else:
            response = await self._client.inboxes.messages.send(
                clean_inbox_id,
                to=[recipient_email],
                subject=clean_subject,
                text=clean_text,
                attachments=attachment_payloads or None,
            )

        sent_message = await self._client.inboxes.messages.get(clean_inbox_id, response.message_id)
        headers = sent_message.headers or {}
        from_email = normalize_email_address(sent_message.from_ or "")
        return DeliveryReceipt(
            external_id=response.message_id,
            inbox_id=clean_inbox_id,
            inbox_address=normalize_email_address(inbox_address or "") or None,
            thread_id=response.thread_id,
            rfc_message_id=headers.get("Message-ID"),
            from_email=from_email or normalize_email_address(inbox_address or "") or None,
        )

    async def acknowledge_message(
        self,
        *,
        inbox_id: str,
        message_id: str,
    ) -> None:
        """Mark one inbound message as read and archived after processing."""
        clean_inbox_id = (inbox_id or "").strip()
        clean_message_id = (message_id or "").strip()
        if not clean_inbox_id or not clean_message_id:
            return
        await self._client.inboxes.messages.update(
            clean_inbox_id,
            clean_message_id,
            add_labels=["archived"],
            remove_labels=["unread"],
        )
        self._polled_message_ids.add(clean_message_id)

    def verify_webhook_payload(self, *, payload: str, headers: dict[str, str]) -> dict[str, Any]:
        """Verify one AgentMail webhook payload and return decoded JSON."""
        secret = (self.webhook_secret or "").strip()
        if not secret:
            raise RuntimeError("AgentMail webhook secret is not configured")
        SvixWebhook(secret).verify(payload, headers)
        return json.loads(payload)

    def build_inbound_event(self, payload: dict[str, Any]) -> EmailInboundEvent | None:
        """Convert one verified webhook payload into an inbound email event."""
        message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
        return self._build_inbound_event_from_values(
            inbox_id=message.get("inbox_id"),
            message_id=message.get("message_id"),
            from_value=message.get("from"),
            plain_text=message.get("extracted_text") or message.get("text") or message.get("preview"),
            thread_id=message.get("thread_id"),
            in_reply_to=message.get("in_reply_to"),
            references=message.get("references"),
            subject=message.get("subject"),
        )

    def is_alert_inbox(self, inbox_id: str | None) -> bool:
        """Return True when the inbox id belongs to the shared alert inbox."""
        clean_inbox_id = (inbox_id or "").strip()
        if not clean_inbox_id:
            return False
        if self._alert_inbox is None:
            return False
        return self._alert_inbox.inbox_id == clean_inbox_id

    def is_crm_inbox(self, inbox_id: str | None) -> bool:
        """Backward-compatible alias for older alert-inbox checks."""
        return self.is_alert_inbox(inbox_id)

    def _resolve_environment(self) -> AgentMailEnvironment:
        """Resolve AgentMail environment from environment variables."""
        raw_value = (os.getenv("AGENTMAIL_ENVIRONMENT", "") or "").strip().upper()
        if raw_value == "EU_PROD":
            return AgentMailEnvironment.EU_PROD
        if raw_value == "PROD_X_402":
            return AgentMailEnvironment.PROD_X_402
        if raw_value == "PROD_MPP":
            return AgentMailEnvironment.PROD_MPP
        if hasattr(AgentMailEnvironment, "PROD"):
            return AgentMailEnvironment.PROD
        return AgentMailEnvironment.PRODUCTION

    def _resolve_webhook_url(self) -> str | None:
        """Resolve public webhook URL from explicit or shared bot callback settings."""
        explicit_url = (os.getenv("AGENTMAIL_WEBHOOK_URL", "") or "").strip()
        if explicit_url:
            return explicit_url

        whatsapp_callback_url = (os.getenv("WA_CALLBACK_URL", "") or "").strip()
        if not whatsapp_callback_url:
            return None

        parsed = urlparse(whatsapp_callback_url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return urlunparse((parsed.scheme, parsed.netloc, "/webhooks/agentmail", "", "", ""))

    def _build_contact_inbox_display_name(self, inbox_address: str) -> str:
        """Build the sender name shown for one dedicated contact inbox."""
        clean_address = normalize_email_address(inbox_address)
        if "@" not in clean_address:
            return "Contadores"
        local_part, _, _domain = clean_address.partition("@")
        return local_part.strip() or "Contadores"

    def _build_inbound_event_from_values(
        self,
        *,
        inbox_id: Any,
        message_id: Any,
        from_value: Any,
        plain_text: Any,
        thread_id: Any,
        in_reply_to: Any,
        references: Any,
        subject: Any,
    ) -> EmailInboundEvent | None:
        """Normalize one inbound event from webhook JSON or polled SDK message objects."""
        clean_inbox_id = str(inbox_id or "").strip()
        clean_message_id = str(message_id or "").strip()
        clean_from_email = normalize_email_address(str(from_value or "").strip())
        clean_plain_text = str(plain_text or "").strip()
        clean_thread_id = str(thread_id or "").strip() or None
        clean_in_reply_to = self._stringify_message_reference(in_reply_to)
        clean_references = self._stringify_message_reference(references)
        clean_subject = str(subject or "").strip() or None
        if not clean_inbox_id or not clean_message_id or not clean_from_email:
            return None
        if not clean_plain_text:
            clean_plain_text = "(empty email body)"
        return EmailInboundEvent(
            inbox_id=clean_inbox_id,
            message_id=clean_message_id,
            from_email=clean_from_email,
            plain_text=clean_plain_text,
            thread_id=clean_thread_id,
            in_reply_to=clean_in_reply_to,
            references=clean_references,
            subject=clean_subject,
        )

    def _build_attachment_payloads(self, attachments: list[EmailAttachment] | None) -> list[dict[str, str]]:
        """Convert local attachments into AgentMail SDK payloads."""
        payloads: list[dict[str, str]] = []
        for attachment in attachments or []:
            filename = attachment.filename.strip() or "attachment.bin"
            content_type = attachment.content_type.strip() or "application/octet-stream"
            payloads.append(
                {
                    "filename": filename,
                    "content_type": content_type,
                    "content": base64.b64encode(attachment.data).decode("utf-8"),
                }
            )
        return payloads

    async def _resolve_reply_message_id(self, *, inbox_id: str, thread_id: str) -> str:
        """Resolve the latest message id in a thread for AgentMail reply sends."""
        thread = await self._client.inboxes.threads.get(inbox_id, thread_id)
        if thread.messages:
            latest_message = thread.messages[-1]
            latest_message_id = str(latest_message.message_id or "").strip()
            if latest_message_id:
                return latest_message_id
        clean_last_message_id = str(thread.last_message_id or "").strip()
        if clean_last_message_id:
            return clean_last_message_id
        raise RuntimeError(f"AgentMail thread {thread_id} has no reply target message")

    async def _find_inbox_by_client_id(self, client_id: str) -> EmailInboxState | None:
        """Find one inbox by client_id across the account inbox list."""
        page_token: str | None = None
        while True:
            payload = await self._client.inboxes.list(limit=100, page_token=page_token)
            for inbox in payload.inboxes:
                if str(getattr(inbox, "client_id", "") or "").strip() != client_id:
                    continue
                return self._build_inbox_state(inbox.inbox_id, inbox.email)
            if not payload.next_page_token:
                return None
            page_token = payload.next_page_token

    async def _load_shared_inboxes(self) -> list[EmailInboxState]:
        """Resolve the configured shared inbox pool once."""
        if self._shared_inboxes:
            return list(self._shared_inboxes)

        resolved: list[EmailInboxState] = []
        seen_inbox_ids: set[str] = set()

        for inbox_ref in self._shared_inbox_refs:
            state = await self._resolve_existing_inbox(inbox_ref)
            if state.inbox_id in seen_inbox_ids:
                continue
            seen_inbox_ids.add(state.inbox_id)
            resolved.append(state)

        if not resolved:
            raise RuntimeError("No AgentMail shared inboxes are configured")

        self._shared_inboxes = resolved
        return list(self._shared_inboxes)

    async def _list_inbox_ids(self) -> list[str]:
        """List all inbox ids available on the current AgentMail account."""
        inbox_ids: list[str] = []
        page_token: str | None = None
        while True:
            payload = await self._client.inboxes.list(limit=100, page_token=page_token)
            for inbox in payload.inboxes:
                clean_inbox_id = str(inbox.inbox_id or "").strip()
                if clean_inbox_id:
                    inbox_ids.append(clean_inbox_id)
            if not payload.next_page_token:
                return inbox_ids
            page_token = payload.next_page_token

    async def _sync_contact_inbox_display_name(
        self,
        *,
        inbox_id: str,
        inbox_address: str,
    ) -> None:
        """Ensure one contact inbox uses a readable sender name instead of the AgentMail default."""
        clean_inbox_id = (inbox_id or "").strip()
        clean_inbox_address = normalize_email_address(inbox_address)
        if not clean_inbox_id or not clean_inbox_address:
            return
        if clean_inbox_id in self._synced_contact_inbox_display_names:
            return

        desired_display_name = self._build_contact_inbox_display_name(clean_inbox_address)
        inbox = await self._client.inboxes.get(clean_inbox_id)
        current_display_name = " ".join((getattr(inbox, "display_name", "") or "").split()).strip()
        if current_display_name != desired_display_name:
            await self._client.inboxes.update(
                clean_inbox_id,
                display_name=desired_display_name,
            )
        self._synced_contact_inbox_display_names.add(clean_inbox_id)

    async def _resolve_existing_inbox(self, inbox_ref: str) -> EmailInboxState:
        """Resolve one configured inbox id or inbox email into stable inbox state."""
        clean_inbox_ref = (inbox_ref or "").strip()
        if not clean_inbox_ref:
            raise RuntimeError("AgentMail inbox reference is required")
        inbox = await self._client.inboxes.get(clean_inbox_ref)
        return self._build_inbox_state(inbox.inbox_id, inbox.email)

    def _resolve_shared_inbox_refs(self) -> tuple[str, ...]:
        """Resolve the configured shared inbox pool in preferred order."""
        raw_value = (os.getenv(AGENTMAIL_SHARED_INBOX_IDS_ENV, "") or "").strip()
        raw_parts = raw_value.split(",") if raw_value else list(DEFAULT_AGENTMAIL_SHARED_INBOX_IDS)

        clean_parts: list[str] = []
        seen_values: set[str] = set()
        for raw_part in raw_parts:
            clean_value = normalize_email_address(raw_part) or raw_part.strip()
            if not clean_value or clean_value in seen_values:
                continue
            clean_parts.append(clean_value)
            seen_values.add(clean_value)
        return tuple(clean_parts)

    async def _select_shared_inbox(
        self,
        *,
        contact_id: str,
        inboxes: list[EmailInboxState],
    ) -> EmailInboxState:
        """Pick one inbox from the shared pool with stable minimal-repeat rotation."""
        if not inboxes:
            raise RuntimeError("No AgentMail shared inboxes are available")
        if len(inboxes) == 1:
            return inboxes[0]
        cached = self._shared_inbox_assignments.get(contact_id)
        if cached is not None:
            return cached

        async with self._shared_inbox_selection_lock:
            cached = self._shared_inbox_assignments.get(contact_id)
            if cached is not None:
                return cached
            state = inboxes[self._next_shared_inbox_index % len(inboxes)]
            self._next_shared_inbox_index += 1
            self._shared_inbox_assignments[contact_id] = state
            return state

    def _stringify_message_reference(self, value: Any) -> str | None:
        """Convert AgentMail reference fields into the plain string shape expected by the backend."""
        if value is None:
            return None
        if isinstance(value, list):
            clean_parts = [str(item).strip() for item in value if str(item).strip()]
            if not clean_parts:
                return None
            return " ".join(clean_parts)
        clean_value = str(value).strip()
        return clean_value or None

    async def _find_webhook(self):
        """Find the managed AgentMail webhook by client_id or URL."""
        page_token: str | None = None
        while True:
            payload = await self._client.webhooks.list(limit=100, page_token=page_token)
            for webhook in payload.webhooks:
                if str(getattr(webhook, "client_id", "") or "").strip() == AGENTMAIL_WEBHOOK_CLIENT_ID:
                    return webhook
                if self.webhook_url and str(webhook.url or "").strip() == self.webhook_url:
                    return webhook
            if not payload.next_page_token:
                return None
            page_token = payload.next_page_token

    def _build_inbox_state(self, inbox_id: str, inbox_address: str) -> EmailInboxState:
        """Normalize one inbox state from AgentMail responses."""
        clean_inbox_id = (inbox_id or "").strip()
        clean_inbox_address = normalize_email_address(inbox_address)
        if not clean_inbox_id or not clean_inbox_address:
            raise RuntimeError("AgentMail returned an inbox without stable id or email")
        return EmailInboxState(
            inbox_id=clean_inbox_id,
            inbox_address=clean_inbox_address,
        )

    def _derive_subject(self, text: str, explicit_subject: str | None) -> str:
        """Resolve a plain-text subject for first outbound sends."""
        clean_explicit_subject = " ".join((explicit_subject or "").split()).strip()
        if clean_explicit_subject:
            return clean_explicit_subject[:100]

        clean_text = " ".join((text or "").split()).strip()
        if not clean_text:
            return DEFAULT_EMAIL_SUBJECT
        for separator in [". ", "! ", "? ", "\n"]:
            if separator in clean_text:
                clean_text = clean_text.split(separator, 1)[0]
                break
        clean_text = clean_text.strip(" .!?-")
        return clean_text[:100] or DEFAULT_EMAIL_SUBJECT


class WhatsAppProvider:
    """PyWA provider for inbound webhooks and outbound sends."""

    def __init__(
        self,
        app: FastAPI,
        on_inbound: Callable[[WhatsAppInboundEvent], Awaitable[None]],
        on_status: Callable[[WhatsAppMessageStatusEvent], Awaitable[None]] | None = None,
    ) -> None:
        self._on_inbound = on_inbound
        self._on_status = on_status
        self._session: httpx.AsyncClient | None = None
        self._wa: WhatsApp | None = None

        self.phone_id = os.getenv("WA_PHONE_ID", "").strip()
        self.access_token = os.getenv("WA_ACCESS_TOKEN", "").strip()
        self.app_id = os.getenv("WA_APP_ID", "").strip()
        self.app_secret = os.getenv("WA_APP_SECRET", "").strip()
        self.verify_token = os.getenv("WA_VERIFY_TOKEN", "").strip()
        callback_url_raw = os.getenv("WA_CALLBACK_URL", "").strip()
        self.callback_url = callback_url_raw if callback_url_raw else None
        self.webhook_challenge_delay = self._resolve_webhook_challenge_delay(
            os.getenv("WA_WEBHOOK_CHALLENGE_DELAY", "").strip()
        )
        self.max_inbound_age_seconds = self._resolve_inbound_max_age_seconds(
            os.getenv("WA_INBOUND_MAX_AGE_SECONDS", "").strip()
        )
        self.business_phone_digits = self._normalize_phone_digits(
            os.getenv("WA_BUSINESS_PHONE", "").strip()
        )
        self.webhook_endpoint, self._callback_base_url = self._parse_callback_url(self.callback_url)
        self.template_source_url_fallback = (
            os.getenv("WA_TEMPLATE_SOURCE_URL_FALLBACK", "https://example.com").strip()
            or "https://example.com"
        )

        if not self._has_credentials():
            logger.info("⚪ WhatsApp sending is disabled because WA_PHONE_ID or WA_ACCESS_TOKEN is missing.")
            return

        if not self.verify_token:
            logger.error("❌ WhatsApp webhooks are disabled because WA_VERIFY_TOKEN is missing.")
            return
        if not self.callback_url:
            logger.warning("⚠️ WA_CALLBACK_URL is missing. Automatic webhook registration will be skipped.")

        self._session = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
        try:
            self._wa = self._build_client(app=app)
            self._register_handlers()
            logger.info(
                "✅ WhatsApp client ready (callback_url=%s, webhook_challenge_delay=%s).",
                self.callback_url,
                self.webhook_challenge_delay,
            )
        except Exception as exc:
            self._wa = None
            if self._is_meta_app_validation_error(exc):
                logger.warning(
                    "⚠️ WhatsApp startup failed. "
                    "Check WA_ACCESS_TOKEN / WA_APP_ID / WA_PHONE_ID / WA_APP_SECRET and Meta app status. "
                    "Error: %s.",
                    exc,
                )
            else:
                logger.exception(
                    "❌ WhatsApp client initialization failed (callback_url=%s, webhook_endpoint=%s).",
                    self.callback_url,
                    self.webhook_endpoint,
                )

    def _build_client(
        self,
        *,
        app: FastAPI,
    ) -> WhatsApp:
        """Build one PyWA client that handles both outbound sends and inbound webhooks."""
        kwargs: dict[str, Any] = {
            "phone_id": self.phone_id,
            "token": self.access_token,
            "session": self._session,
            "server": app,
            "webhook_endpoint": self.webhook_endpoint,
            "verify_token": self.verify_token,
            "app_secret": self.app_secret or None,
            "validate_updates": bool(self.app_secret),
            "webhook_challenge_delay": self.webhook_challenge_delay,
        }
        if self._callback_base_url:
            kwargs.update(
                {
                    "callback_url": self._callback_base_url,
                    "callback_url_scope": pywa_utils.CallbackURLScope.PHONE,
                }
            )
        return WhatsApp(**kwargs)

    @property
    def configured(self) -> bool:
        """Return True when provider client is initialized and ready."""
        return bool(self._wa)

    def _has_credentials(self) -> bool:
        """Return True when minimum WhatsApp credentials are present."""
        return bool(self.phone_id and self.access_token)

    @staticmethod
    def _parse_optional_int(raw: str, *, env_name: str) -> int | None:
        """Parse optional positive integer env var; return None when empty/invalid."""
        clean = (raw or "").strip()
        if not clean:
            return None
        if clean.isdigit():
            return int(clean)
        logger.warning("Ignoring invalid %s value: expected positive integer", env_name)
        return None

    @staticmethod
    def _resolve_webhook_challenge_delay(raw: str) -> int:
        """Resolve webhook challenge delay from env with safe default."""
        clean = (raw or "").strip()
        if not clean:
            return 10
        if clean.isdigit() and int(clean) > 0:
            return int(clean)
        logger.warning("Ignoring invalid WA_WEBHOOK_CHALLENGE_DELAY value: %r. Using default 10", raw)
        return 10

    @staticmethod
    def _resolve_inbound_max_age_seconds(raw: str) -> int:
        """Resolve max allowed inbound age in seconds (0 disables stale filter)."""
        clean = (raw or "").strip()
        if not clean:
            return 3600
        if clean.isdigit():
            return int(clean)
        logger.warning("Ignoring invalid WA_INBOUND_MAX_AGE_SECONDS value: %r. Using default 3600", raw)
        return 3600

    @staticmethod
    def _normalize_phone_digits(raw: str | None) -> str:
        """Normalize one phone-like value to canonical digits-only form."""
        return normalize_whatsapp_phone(raw or "")

    @staticmethod
    def _is_meta_app_validation_error(exc: Exception) -> bool:
        """Return True when exception text matches Meta OAuthException app validation failures."""
        message = str(exc).lower()
        return (
            "error validating application" in message
            or ("oauthexception" in message and "101" in message)
        )

    @staticmethod
    def _parse_callback_url(callback_url: str | None) -> tuple[str, str | None]:
        """Derive webhook path and base URL from full callback URL. PyWA registers Meta URL as base+path and mounts route at path."""
        if not callback_url or not callback_url.strip():
            return "/", None
        parsed = urlparse(callback_url)
        path = (parsed.path or "/").strip() or "/"
        if not path.startswith("/"):
            path = f"/{path}"
        path = path.rstrip("/") or "/"
        base = f"{parsed.scheme or 'https'}://{parsed.netloc}" if parsed.netloc else None
        return path, base

    def _register_handlers(self) -> None:
        """Register webhook handlers on initialized PyWA client."""
        if not self._wa:
            return

        @self._wa.on_message()
        async def _handle_message(_wa, msg: types.Message):
            await self._dispatch_inbound_event(
                self._build_inbound_event_from_message(msg),
                source=f"message:{getattr(getattr(msg, 'type', None), 'value', 'unknown')}",
            )

        @self._wa.on_callback_button()
        async def _handle_callback_button(_wa, btn: types.CallbackButton):
            await self._dispatch_inbound_event(
                self._build_inbound_event_from_callback(btn),
                source="callback_button",
            )

        @self._wa.on_callback_selection()
        async def _handle_callback_selection(_wa, selection: types.CallbackSelection):
            await self._dispatch_inbound_event(
                self._build_inbound_event_from_callback(selection),
                source="callback_selection",
            )

        @self._wa.on_message_status()
        async def _handle_message_status(_wa, status: types.MessageStatus):
            await self._dispatch_status_event(
                self._build_message_status_event(status),
            )

    async def _dispatch_inbound_event(
        self,
        event: WhatsAppInboundEvent | None,
        *,
        source: str,
    ) -> None:
        """Dispatch one mapped inbound event to outer runtime handler."""
        if not event:
            logger.info("🔕 Ignored a WhatsApp webhook update (%s) because it had no usable content.", source)
            return
        await self._on_inbound(event)

    async def _dispatch_status_event(
        self,
        event: WhatsAppMessageStatusEvent | None,
    ) -> None:
        """Dispatch one mapped outbound status event to outer runtime handler."""
        if not event:
            return
        if not self._on_status:
            return
        await self._on_status(event)

    def _extract_wa_id(self, update: Any) -> str:
        """Extract sender WhatsApp ID from one inbound update."""
        from_user = getattr(update, "from_user", None)
        return str(getattr(from_user, "wa_id", "") or "").strip()

    def _extract_display_phone(self, update: Any) -> str:
        """Extract recipient business display phone from webhook metadata."""
        metadata = getattr(update, "metadata", None)
        return str(getattr(metadata, "display_phone_number", "") or "").strip()

    def _is_self_authored_update(self, update: Any) -> bool:
        """Return True when webhook update originated from this business phone."""
        sender_digits = self._normalize_phone_digits(self._extract_wa_id(update))
        if not sender_digits:
            return False
        display_digits = self._normalize_phone_digits(self._extract_display_phone(update))
        if display_digits and sender_digits == display_digits:
            return True
        business_digits = self._normalize_phone_digits(getattr(self, "business_phone_digits", ""))
        if business_digits and sender_digits == business_digits:
            return True
        return False

    def _is_stale_update(self, update: Any) -> bool:
        """Return True when inbound update is older than configured max age."""
        max_age_seconds = max(0, int(getattr(self, "max_inbound_age_seconds", 0)))
        if max_age_seconds <= 0:
            return False
        timestamp = getattr(update, "timestamp", None)
        if not isinstance(timestamp, datetime):
            return False
        event_ts = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - event_ts.astimezone(timezone.utc)).total_seconds()
        return age_seconds > max_age_seconds

    def _extract_message_text(self, msg: types.Message) -> str:
        """Extract normalized textual content from a message update."""
        direct_text = str(getattr(msg, "text", "") or "").strip()
        if direct_text:
            return direct_text

        caption = str(getattr(msg, "caption", "") or "").strip()
        if caption:
            return caption

        reaction = getattr(msg, "reaction", None)
        emoji = str(getattr(reaction, "emoji", "") or "").strip()
        if emoji:
            return f"[reaction] {emoji}"

        return ""

    def _extract_callback_text(
        self,
        callback_update: types.CallbackButton | types.CallbackSelection,
    ) -> str:
        """Extract normalized textual content from callback updates."""
        title = str(getattr(callback_update, "title", "") or "").strip()
        data = str(getattr(callback_update, "data", "") or "").strip()
        if title and data and data != title:
            return f"{title} ({data})"
        return title or data

    def _build_inbound_event(
        self,
        *,
        phone: str,
        text: str,
        external_id: str | None,
        in_reply_to: str | None = None,
    ) -> WhatsAppInboundEvent | None:
        """Build typed inbound event from normalized payload fields."""
        clean_phone = phone.strip()
        clean_text = text.strip()
        if not clean_phone or not clean_text:
            return None
        clean_external_id = (external_id or "").strip() or None
        clean_in_reply_to = (in_reply_to or "").strip() or None
        return WhatsAppInboundEvent(
            phone=clean_phone,
            text=clean_text,
            external_id=clean_external_id,
            in_reply_to=clean_in_reply_to,
        )

    def _extract_in_reply_to_message_id(self, msg: types.Message) -> str | None:
        """Extract replied outbound message id from inbound message context when present."""
        replied_message = getattr(msg, "reply_to_message", None)
        replied_id = str(getattr(replied_message, "message_id", "") or "").strip()
        if replied_id:
            return replied_id
        reaction = getattr(msg, "reaction", None)
        reaction_id = str(getattr(reaction, "message_id", "") or "").strip()
        if reaction_id:
            return reaction_id
        return None

    def _extract_callback_in_reply_to_message_id(
        self,
        callback_update: types.CallbackButton | types.CallbackSelection,
    ) -> str | None:
        """Extract replied outbound message id from callback context."""
        replied_message = getattr(callback_update, "reply_to_message", None)
        replied_id = str(getattr(replied_message, "message_id", "") or "").strip()
        if replied_id:
            return replied_id
        return None

    def _build_inbound_event_from_message(
        self,
        msg: types.Message,
    ) -> WhatsAppInboundEvent | None:
        """Map raw message update into typed inbound event."""
        if getattr(msg, "from_me", False):
            return None
        if self._is_self_authored_update(msg):
            return None
        if self._is_stale_update(msg):
            return None
        return self._build_inbound_event(
            phone=self._extract_wa_id(msg),
            text=self._extract_message_text(msg),
            external_id=str(getattr(msg, "id", "") or "").strip() or None,
            in_reply_to=self._extract_in_reply_to_message_id(msg),
        )

    def _build_inbound_event_from_callback(
        self,
        callback_update: types.CallbackButton | types.CallbackSelection,
    ) -> WhatsAppInboundEvent | None:
        """Map raw callback update into typed inbound event."""
        if self._is_self_authored_update(callback_update):
            return None
        if self._is_stale_update(callback_update):
            return None
        return self._build_inbound_event(
            phone=self._extract_wa_id(callback_update),
            text=self._extract_callback_text(callback_update),
            external_id=str(getattr(callback_update, "id", "") or "").strip() or None,
            in_reply_to=self._extract_callback_in_reply_to_message_id(callback_update),
        )

    def _build_message_status_event(
        self,
        status_update: types.MessageStatus,
    ) -> WhatsAppMessageStatusEvent | None:
        """Map raw outbound status update into typed delivery-status event."""
        external_id = str(getattr(status_update, "id", "") or "").strip()
        raw_status = getattr(status_update, "status", None)
        status_value = getattr(raw_status, "value", raw_status)
        normalized_status = str(status_value or "").strip().lower()
        if not external_id or not normalized_status:
            return None
        if normalized_status not in {"sent", "delivered", "read", "failed"}:
            return None
        return WhatsAppMessageStatusEvent(
            external_id=external_id,
            status=normalized_status,
        )

    def _normalize_outbound_recipient(self, to: str) -> str:
        """Normalize WhatsApp destination to digits-only phone format accepted by Cloud API."""
        raw = (to or "").strip()
        if not raw:
            raise RuntimeError("Missing WhatsApp recipient value")
        digits = normalize_whatsapp_phone(raw)
        if not digits:
            raise RuntimeError(f"Invalid WhatsApp recipient value: {raw!r}")
        return digits

    async def send_message(self, to: str, text: str) -> DeliveryReceipt:
        """Send one WhatsApp text message with size-aware splitting."""
        if not self._wa:
            raise RuntimeError("WhatsApp provider is not configured")

        clean_text = (text or "").strip()
        recipient = self._normalize_outbound_recipient(to)
        outbound_id = ""
        chunks = self._split_message(clean_text)
        for chunk in chunks:
            sent_msg = await self._wa.send_message(to=recipient, text=chunk)
            outbound_id = str(getattr(sent_msg, "id", sent_msg)).strip()
        if not outbound_id:
            raise RuntimeError("WhatsApp provider returned empty message id")
        return DeliveryReceipt(external_id=outbound_id, delivered_text=clean_text)

    async def send_template_message(
        self,
        *,
        to: str,
        template_name: str,
        template_language: str,
        body_params: list[str],
        delivered_text: str | None = None,
    ) -> DeliveryReceipt:
        """Send a generic WhatsApp template with positional body params."""
        if not self._wa:
            raise RuntimeError("WhatsApp provider is not configured")

        recipient = self._normalize_outbound_recipient(to)
        normalized_language = (template_language or "").strip().lower().replace("-", "_")
        resolved_language = (
            TemplateLanguage.ENGLISH_US
            if normalized_language.startswith("en")
            else TemplateLanguage.SPANISH
        )
        sent_msg = await self._wa.send_template(
            to=recipient,
            name=(template_name or "").strip(),
            language=resolved_language,
            params=[BodyText.params(*body_params)] if body_params else None,
        )
        outbound_id = str(getattr(sent_msg, "id", sent_msg)).strip()
        if not outbound_id:
            raise RuntimeError("WhatsApp template send returned empty message id")
        return DeliveryReceipt(
            external_id=outbound_id,
            delivered_text=(delivered_text or "").strip() or None,
        )

    async def send_video(
        self,
        *,
        to: str,
        video_path: str,
        caption: str | None = None,
        delivered_text: str | None = None,
    ) -> DeliveryReceipt:
        """Send one WhatsApp video from a local path visible to the bot."""
        if not self._wa:
            raise RuntimeError("WhatsApp provider is not configured")

        recipient = self._normalize_outbound_recipient(to)
        resolved_path = self._resolve_local_media_path(video_path)
        sent_msg = await self._wa.send_video(
            to=recipient,
            video=str(resolved_path),
            caption=(caption or "").strip() or None,
        )
        outbound_id = str(getattr(sent_msg, "id", sent_msg)).strip()
        if not outbound_id:
            raise RuntimeError("WhatsApp video send returned empty message id")
        return DeliveryReceipt(
            external_id=outbound_id,
            delivered_text=(delivered_text or "").strip() or None,
        )

    def _resolve_local_media_path(self, media_path: str) -> Path:
        """Resolve a repo/data media path from Docker or local bot cwd."""
        raw_path = (media_path or "").strip()
        if not raw_path:
            raise RuntimeError("Missing WhatsApp media path")

        candidate = Path(raw_path)
        candidates = [candidate]
        if not candidate.is_absolute():
            candidates.append(Path.cwd() / candidate)
            candidates.append(Path.cwd().parent / candidate)

        for item in candidates:
            if item.exists() and item.is_file():
                return item

        raise RuntimeError(f"WhatsApp media file not found: {raw_path}")

    def _render_intro_message_text(
        self,
        *,
        sender_name: str,
        source_url: str,
        language: str,
    ) -> str:
        """Render local copy of intro template body for transcript consistency."""
        if language == "en_US":
            return (
                f"Hi, I’m {sender_name}. "
                f"I found your contact listed on {source_url} and wanted to ask you a quick question."
            )
        return (
            f"Hola, soy {sender_name}. "
            f"Encontré tu contacto en {source_url} y quería consultarte algo puntual."
        )

    async def send_intro_template(
        self,
        *,
        to: str,
        template_name: str | None,
        template_language: str | None,
        client_name: str | None,
        company_url: str | None,
    ) -> DeliveryReceipt:
        """Send initial WhatsApp intro template using backend-provided payload."""
        if not self._wa:
            raise RuntimeError("WhatsApp provider is not configured")

        recipient = self._normalize_outbound_recipient(to)
        resolved_template_name = (template_name or "").strip()
        if not resolved_template_name:
            raise RuntimeError("Missing intro template name for first WhatsApp delivery")

        normalized_language = (template_language or "").strip().lower().replace("-", "_")
        resolved_language = "en_US" if normalized_language.startswith("en") else "es"
        resolved_template_language = (
            TemplateLanguage.ENGLISH_US
            if resolved_language == "en_US"
            else TemplateLanguage.SPANISH
        )
        resolved_client_name = (client_name or "").strip() or "Konecta"
        resolved_url = (company_url or "").strip() or self.template_source_url_fallback
        sent_msg = await self._wa.send_template(
            to=recipient,
            name=resolved_template_name,
            language=resolved_template_language,
            params=[BodyText.params(resolved_client_name, resolved_url)],
        )
        outbound_id = str(getattr(sent_msg, "id", sent_msg)).strip()
        if not outbound_id:
            raise RuntimeError("WhatsApp template send returned empty message id")

        delivered_text = self._render_intro_message_text(
            sender_name=resolved_client_name,
            source_url=resolved_url,
            language=resolved_language,
        )
        return DeliveryReceipt(
            external_id=outbound_id,
            delivered_text=delivered_text,
        )

    def _split_message(self, text: str) -> list[str]:
        """Split oversized WhatsApp message preserving line boundaries."""
        clean_text = (text or "").strip()
        if len(clean_text) <= WA_MAX_LENGTH:
            return [clean_text]

        parts: list[str] = []
        current = ""
        for line in clean_text.split("\n"):
            candidate = f"{current}\n{line}" if current else line
            if len(candidate) <= WA_MAX_LENGTH:
                current = candidate
                continue

            if current:
                parts.append(current)
            if len(line) <= WA_MAX_LENGTH:
                current = line
                continue

            while len(line) > WA_MAX_LENGTH:
                parts.append(line[:WA_MAX_LENGTH])
                line = line[WA_MAX_LENGTH:]
            current = line

        if current:
            parts.append(current)
        return parts

    async def close(self) -> None:
        """Close underlying HTTP session."""
        if self._session:
            await self._session.aclose()
