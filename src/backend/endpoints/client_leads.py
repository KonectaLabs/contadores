"""Client lead delivery endpoints and sheet sync helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.client_lead_config import ClientLeadConfigSyncResult, sync_client_lead_sources_from_config
from backend.database import (
    CLIENT_LEAD_CONTEXT_TEMPLATE_NAME,
    CLIENT_LEAD_DEFAULT_COLUMN_MAPPING,
    CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE,
    CLIENT_LEAD_DEFAULT_TEMPLATE_NAME,
    ClientLeadDelivery,
    ClientLeadDeliveryStatus,
    ClientLeadSource,
    ContadoresLead,
    ContadoresLeadStage,
    PlatformEvent,
    normalize_client_lead_context_field_mapping,
    normalize_client_lead_column_mapping,
    normalize_phone,
)
from backend.meta_lead_ads import (
    DEFAULT_META_LEAD_FIELDS,
    MetaLeadAdsCredentialsError,
    MetaLeadAdsError,
    fetch_meta_form_leads,
    fetch_meta_lead_payload,
)

client_leads_router = APIRouter(prefix="/api/client-lead-sources", tags=["client-leads"])
client_lead_deliveries_router = APIRouter(prefix="/api/client-lead-deliveries", tags=["client-leads"])
client_leads_actions_router = APIRouter(prefix="/api/client-leads", tags=["client-leads"])

HEADER_ALIASES = {
    "source_id": ("id", "lead_id", "row_id", "source_id", "codigo", "code"),
    "created_time": ("created_time", "timestamp", "submitted_at", "created_at", "fecha", "fecha_de_creacion"),
    "full_name": ("full_name", "name", "nombre", "nombre_completo", "cliente", "contacto"),
    "phone_number": ("phone_number", "phone", "telefono", "whatsapp", "celular", "mobile", "telefono_whatsapp"),
    "email": ("email", "correo", "correo_electronico", "mail", "e_mail"),
}
DEFAULT_PENDING_LIMIT = 100
MAX_CONTEXT_VALUE_CHARS = 240
MAX_CONTEXT_BLOCK_CHARS = 1000
META_SHEET_PREFERRED_HEADERS = [
    "id",
    "leadgen_id",
    "created_time",
    "form_id",
    "ad_id",
    "ad_name",
    "adset_id",
    "adset_name",
    "campaign_id",
    "campaign_name",
    "platform",
    "full_name",
    "phone_number",
    "email",
]


class ClientLeadSourceCommand(BaseModel):
    """Editable source configuration."""

    id: str | None = None
    label: str = Field(min_length=1)
    enabled: bool = True
    sheet_url: str | None = ""
    sheet_gid: str | None = None
    sheet_tab_name: str | None = None
    meta_page_id: str | None = None
    meta_lead_form_id: str | None = None
    sheet_poll_seconds: int = Field(default=10, ge=5)
    recipient_name: str | None = None
    recipient_phone: str | None = ""
    template_name: str | None = CLIENT_LEAD_DEFAULT_TEMPLATE_NAME
    template_language: str | None = CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE
    column_mapping: dict[str, str] = Field(default_factory=lambda: dict(CLIENT_LEAD_DEFAULT_COLUMN_MAPPING))
    context_field_mapping: dict[str, str] = Field(default_factory=dict)


class ClientLeadSourceResponse(BaseModel):
    """Serialized source configuration with delivery counters."""

    id: str
    label: str
    enabled: bool
    sheet_url: str
    sheet_gid: str | None
    sheet_tab_name: str | None
    meta_page_id: str
    meta_lead_form_id: str
    sheet_poll_seconds: int
    recipient_name: str | None
    recipient_phone: str
    normalized_recipient_phone: str
    template_name: str
    template_language: str
    column_mapping: dict[str, str]
    context_field_mapping: dict[str, str]
    last_sync_at: str | None
    last_sync_status: str | None
    last_sync_note: str | None
    counts: dict[str, int]
    created_at: str
    updated_at: str


class ClientLeadSourceListResponse(BaseModel):
    """Client lead source list payload."""

    sources: list[ClientLeadSourceResponse]


class ClientLeadDeliveryResponse(BaseModel):
    """Serialized imported client lead row."""

    id: str
    source_id: str
    source_row_key: str
    row_number: int
    raw_row: dict[str, str]
    created_time: str | None
    full_name: str | None
    phone_number: str
    normalized_phone: str
    email: str | None
    wa_link: str
    notification_text: str
    sent_text: str
    delivery_status: str
    external_id: str | None
    delivery_attempts: int
    last_delivery_error: str | None
    last_delivery_error_at: str | None
    block_reason: str | None
    dispatch_after: str
    sent_at: str | None
    delivered_at: str | None
    created_at: str
    updated_at: str


class ClientLeadDeliveryListResponse(BaseModel):
    """Imported client lead list payload."""

    source: ClientLeadSourceResponse
    leads: list[ClientLeadDeliveryResponse]


class ClientLeadRecipientCrmLeadResponse(BaseModel):
    """Existing CRM lead that matches the Delivery recipient phone."""

    id: str
    funnel_id: str
    full_name: str | None
    phone: str
    normalized_phone: str
    stage: str
    updated_at: str


class ClientLeadRecipientChatMessageResponse(BaseModel):
    """One WhatsApp notification sent to the Delivery recipient."""

    delivery_id: str
    row_number: int
    lead_name: str | None
    lead_phone: str
    lead_email: str | None
    text: str
    delivery_status: str
    external_id: str | None
    sent_at: str | None
    delivered_at: str | None
    last_delivery_error: str | None
    created_at: str
    updated_at: str


class ClientLeadRecipientChatResponse(BaseModel):
    """Audit view for messages sent from Delivery to the recipient."""

    source: ClientLeadSourceResponse
    recipient_name: str | None
    recipient_phone: str
    normalized_recipient_phone: str
    crm_leads: list[ClientLeadRecipientCrmLeadResponse]
    messages: list[ClientLeadRecipientChatMessageResponse]


class ClientLeadSyncResponse(BaseModel):
    """Result of one source sync."""

    status: str
    source: ClientLeadSourceResponse
    fetched: int = 0
    imported: int = 0
    updated: int = 0
    blocked: int = 0
    skipped: int = 0
    queued: int = 0
    sheet_appended: int = 0
    sheet_append_errors: list[str] = Field(default_factory=list)


class MetaLeadFormImportCommand(BaseModel):
    """One retrieved Meta Lead Ads instant-form lead."""

    leadgen_id: str = Field(min_length=1)
    created_time: str | None = None
    form_id: str | None = None
    ad_id: str | None = None
    ad_name: str | None = None
    adset_id: str | None = None
    adset_name: str | None = None
    campaign_id: str | None = None
    campaign_name: str | None = None
    platform: str | None = None
    field_data: list[dict[str, Any]] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class MetaLeadFormFetchCommand(BaseModel):
    """Fetch one Meta Lead Ads instant-form lead and import it."""

    leadgen_id: str = Field(min_length=1)
    fields: str | None = DEFAULT_META_LEAD_FIELDS
    reason: str | None = Field(default=None, max_length=1000)


class MetaLeadFormBackfillCommand(BaseModel):
    """Fetch recent leads from one Meta instant form and import them."""

    form_id: str | None = None
    fields: str | None = DEFAULT_META_LEAD_FIELDS
    limit: int = Field(default=100, ge=1, le=500)
    reason: str | None = Field(default=None, max_length=1000)


class ClientLeadPendingNotification(BaseModel):
    """One pending WhatsApp notification consumed by the bot."""

    delivery_id: str
    source_id: str
    source_label: str
    recipient_phone: str
    normalized_recipient_phone: str
    template_name: str
    template_language: str
    template_body_params: list[str]
    delivered_text: str


class ClientLeadPendingNotificationResponse(BaseModel):
    """Pending notification payload for the bot."""

    notifications: list[ClientLeadPendingNotification]


class ClientLeadDeliveryUpdateCommand(BaseModel):
    """Provider delivery update by local delivery id."""

    status: str = Field(min_length=1)
    external_id: str | None = None
    sent_text: str | None = None


class ClientLeadDeliveryByExternalIdCommand(BaseModel):
    """Provider delivery update by external provider id."""

    external_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    error: str | None = None
    error_code: int | None = None
    error_title: str | None = None
    error_message: str | None = None
    error_details: str | None = None
    error_user_message: str | None = None


class ClientLeadDeliveryFailureCommand(BaseModel):
    """Provider send failure by local delivery id."""

    error: str = Field(min_length=1)
    error_code: int | None = None
    error_title: str | None = None
    error_message: str | None = None
    error_details: str | None = None
    error_user_message: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: int = Field(default=60, ge=0, le=3600)


class ClientLeadCopyAllResponse(BaseModel):
    """Clipboard-ready client lead text."""

    text: str


def format_timestamp_seconds(value: datetime | None) -> str | None:
    """Format datetimes with second precision in UTC."""
    if value is None:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_source_response(source: ClientLeadSource, counts: dict[str, dict[str, int]] | None = None) -> ClientLeadSourceResponse:
    """Serialize a client lead source."""
    return ClientLeadSourceResponse(
        id=source.id,
        label=source.label,
        enabled=source.enabled,
        sheet_url=source.sheet_url,
        sheet_gid=source.sheet_gid,
        sheet_tab_name=source.sheet_tab_name,
        meta_page_id=source.meta_page_id,
        meta_lead_form_id=source.meta_lead_form_id,
        sheet_poll_seconds=source.sheet_poll_seconds,
        recipient_name=source.recipient_name,
        recipient_phone=source.recipient_phone,
        normalized_recipient_phone=source.normalized_recipient_phone,
        template_name=source.template_name,
        template_language=source.template_language,
        column_mapping=source.column_mapping,
        context_field_mapping=source.context_field_mapping,
        last_sync_at=format_timestamp_seconds(source.last_sync_at),
        last_sync_status=source.last_sync_status,
        last_sync_note=source.last_sync_note,
        counts=(counts or {}).get(source.id, {}),
        created_at=format_timestamp_seconds(source.created_at) or "",
        updated_at=format_timestamp_seconds(source.updated_at) or "",
    )


def build_delivery_response(item: ClientLeadDelivery) -> ClientLeadDeliveryResponse:
    """Serialize one imported client lead."""
    delivery_status = (
        item.delivery_status.value
        if isinstance(item.delivery_status, ClientLeadDeliveryStatus)
        else str(item.delivery_status)
    )
    return ClientLeadDeliveryResponse(
        id=item.id,
        source_id=item.source_id,
        source_row_key=item.source_row_key,
        row_number=item.row_number,
        raw_row=item.raw_row,
        created_time=format_timestamp_seconds(item.created_time),
        full_name=item.full_name,
        phone_number=item.phone_number,
        normalized_phone=item.normalized_phone,
        email=item.email,
        wa_link=item.wa_link,
        notification_text=item.notification_text,
        sent_text=item.sent_text,
        delivery_status=delivery_status,
        external_id=item.external_id,
        delivery_attempts=item.delivery_attempts,
        last_delivery_error=item.last_delivery_error,
        last_delivery_error_at=format_timestamp_seconds(item.last_delivery_error_at),
        block_reason=item.block_reason,
        dispatch_after=format_timestamp_seconds(item.dispatch_after) or "",
        sent_at=format_timestamp_seconds(item.sent_at),
        delivered_at=format_timestamp_seconds(item.delivered_at),
        created_at=format_timestamp_seconds(item.created_at) or "",
        updated_at=format_timestamp_seconds(item.updated_at) or "",
    )


def build_recipient_crm_lead_response(lead: ContadoresLead) -> ClientLeadRecipientCrmLeadResponse:
    """Serialize a matching CRM lead without importing CRM endpoint models."""
    stage = lead.stage.value if isinstance(lead.stage, ContadoresLeadStage) else str(lead.stage)
    return ClientLeadRecipientCrmLeadResponse(
        id=lead.id,
        funnel_id=lead.funnel_id,
        full_name=lead.full_name,
        phone=lead.phone,
        normalized_phone=lead.normalized_phone,
        stage=stage,
        updated_at=format_timestamp_seconds(lead.updated_at) or "",
    )


def build_recipient_chat_message_response(item: ClientLeadDelivery) -> ClientLeadRecipientChatMessageResponse:
    """Serialize one sent/attempted Delivery notification as chat-like audit."""
    delivery_status = (
        item.delivery_status.value
        if isinstance(item.delivery_status, ClientLeadDeliveryStatus)
        else str(item.delivery_status)
    )
    return ClientLeadRecipientChatMessageResponse(
        delivery_id=item.id,
        row_number=item.row_number,
        lead_name=item.full_name,
        lead_phone=item.phone_number,
        lead_email=item.email,
        text=item.sent_text or item.notification_text,
        delivery_status=delivery_status,
        external_id=item.external_id,
        sent_at=format_timestamp_seconds(item.sent_at),
        delivered_at=format_timestamp_seconds(item.delivered_at),
        last_delivery_error=item.last_delivery_error,
        created_at=format_timestamp_seconds(item.created_at) or "",
        updated_at=format_timestamp_seconds(item.updated_at) or "",
    )


def should_show_recipient_chat_message(item: ClientLeadDelivery) -> bool:
    """Return True when this row represents a notification attempted to the recipient."""
    status = item.delivery_status.value if isinstance(item.delivery_status, ClientLeadDeliveryStatus) else str(item.delivery_status)
    if status in {ClientLeadDeliveryStatus.PENDING.value, ClientLeadDeliveryStatus.BLOCKED.value}:
        return False
    return bool(item.sent_text.strip() or item.notification_text.strip() or item.external_id or item.last_delivery_error)


def recipient_chat_sort_key(item: ClientLeadDelivery) -> tuple[datetime, int, str]:
    """Sort recipient chat messages chronologically."""
    timestamp = item.sent_at or item.delivered_at or item.last_delivery_error_at or item.updated_at or item.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return (timestamp, item.row_number, item.id)


def normalize_header(value: str) -> str:
    """Normalize a sheet header for robust matching."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", plain.casefold()).strip("_")


def header_lookup(row: dict[str, str]) -> dict[str, str]:
    """Build normalized header to original header lookup."""
    lookup: dict[str, str] = {}
    for key in row:
        normalized = normalize_header(key)
        if normalized and normalized not in lookup:
            lookup[normalized] = key
    return lookup


def get_mapped_value(row: dict[str, str], mapping: dict[str, str], field: str) -> str:
    """Return a mapped value from one sheet row."""
    lookup = header_lookup(row)
    configured = normalize_header(mapping.get(field, ""))
    if configured and configured in lookup:
        return str(row.get(lookup[configured]) or "").strip()
    for alias in HEADER_ALIASES.get(field, ()):
        normalized = normalize_header(alias)
        if normalized in lookup:
            return str(row.get(lookup[normalized]) or "").strip()
    return ""


def get_configured_row_value(row: dict[str, str], column_name: str) -> str:
    """Return a row value for one configured sheet column."""
    lookup = header_lookup(row)
    configured = normalize_header(column_name)
    if configured and configured in lookup:
        return str(row.get(lookup[configured]) or "").strip()
    return ""


def clean_context_value(value: str) -> str:
    """Keep one context value compact enough for WhatsApp templates."""
    clean_value = " ".join(str(value or "").split()).strip()
    if len(clean_value) <= MAX_CONTEXT_VALUE_CHARS:
        return clean_value
    return f"{clean_value[:MAX_CONTEXT_VALUE_CHARS - 3].rstrip()}..."


def build_context_lines_from_row(source: ClientLeadSource, row: dict[str, str]) -> list[str]:
    """Build configured context lines from one raw sheet row."""
    lines: list[str] = []
    mapping = normalize_client_lead_context_field_mapping(source.context_field_mapping)
    for label, column_name in mapping.items():
        value = clean_context_value(get_configured_row_value(row, column_name))
        if value:
            lines.append(f"{label}: {value}")
    return lines


def build_context_text_from_row(source: ClientLeadSource, row: dict[str, str]) -> str:
    """Build the multiline context block from one raw sheet row."""
    lines = build_context_lines_from_row(source, row)
    if not lines:
        return ""
    text = "\n".join(lines)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    return f"{text[:MAX_CONTEXT_BLOCK_CHARS - 3].rstrip()}..."


def build_context_text(source: ClientLeadSource, item: ClientLeadDelivery) -> str:
    """Build the multiline context block used by WhatsApp and audit text."""
    return build_context_text_from_row(source, item.raw_row)


def parse_datetime(value: str | None) -> datetime | None:
    """Parse common Google/Meta timestamp strings."""
    clean_value = (value or "").strip()
    if not clean_value:
        return None
    try:
        if clean_value.replace(".", "", 1).isdigit():
            serial = float(clean_value)
            google_epoch = datetime(1899, 12, 30, tzinfo=timezone.utc)
            return google_epoch + timedelta(days=serial)
    except ValueError:
        pass
    candidate = clean_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def row_is_empty(row: dict[str, str]) -> bool:
    """Return True when every row value is blank."""
    return not any(str(value or "").strip() for value in row.values())


def stable_row_hash(row: dict[str, str]) -> str:
    """Return a compact stable hash for one raw row."""
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def source_row_key_for(row: dict[str, str], *, row_number: int, source_id_value: str) -> str:
    """Build the idempotency key for one imported sheet row."""
    clean_source_id = " ".join((source_id_value or "").split()).strip()
    if clean_source_id:
        return clean_source_id[:240]
    return f"row:{row_number}:{stable_row_hash(row)}"


def build_wa_link(*, phone: str) -> str:
    """Build a plain wa.me chat link without a text query parameter."""
    normalized_phone = normalize_phone(phone)
    return f"https://wa.me/{normalized_phone}" if normalized_phone else ""


def build_notification_title(
    source: ClientLeadSource,
    *,
    raw_row: dict[str, str] | None = None,
) -> str:
    """Return the public campaign name when present, else the source label."""
    row = raw_row or {}
    campaign_name = " ".join(str(row.get("campaign_name") or "").split()).strip()
    return campaign_name or source.label


def build_notification_text(
    source: ClientLeadSource,
    *,
    name: str,
    phone: str,
    email: str | None,
    wa_link: str,
    context_text: str = "",
    title: str | None = None,
) -> str:
    """Build the operator-visible notification copy stored for audit/UI."""
    parts = [
        f"Nuevo Lead: {title or source.label}.",
        "",
        "datos del Lead:",
        build_lead_data_text(name=name, phone=phone, email=email, context_text=context_text),
        "",
        "Para abrir el chat:",
        wa_link or "-",
        "Para abrir el chat entrar al link.",
    ]
    return "\n".join(parts)


def build_lead_data_lines(
    *,
    name: str,
    phone: str,
    email: str | None,
    context_text: str = "",
) -> list[str]:
    """Build lead data lines for the single WhatsApp template param."""
    lines = [
        f"Nombre: {name or '-'}",
        f"WhatsApp: {phone or '-'}",
        f"Email: {email or '-'}",
    ]
    if context_text:
        lines.extend(line for line in context_text.splitlines() if line.strip())
    return lines


def build_lead_data_text(
    *,
    name: str,
    phone: str,
    email: str | None,
    context_text: str = "",
) -> str:
    """Build the multiline lead data block shown in Delivery audit surfaces."""
    return "\n".join(build_lead_data_lines(name=name, phone=phone, email=email, context_text=context_text))


def build_lead_data_template_param(source: ClientLeadSource, item: ClientLeadDelivery) -> str:
    """Build the single Meta-safe template param containing all lead data."""
    lines = build_lead_data_lines(
        name=item.full_name or "",
        phone=item.normalized_phone or item.phone_number,
        email=item.email,
        context_text=build_context_text(source, item),
    )
    return "; ".join(lines) or "-"


def build_template_params(source: ClientLeadSource, item: ClientLeadDelivery) -> list[str]:
    """Build positional params for the approved client lead alert template."""
    return [
        build_notification_title(source, raw_row=item.raw_row),
        build_lead_data_template_param(source, item),
        item.wa_link or "-",
    ]


def build_delivery_notification_text(source: ClientLeadSource, item: ClientLeadDelivery) -> str:
    """Build the current notification text for one persisted Delivery row."""
    return build_notification_text(
        source,
        name=item.full_name or "",
        phone=item.normalized_phone or item.phone_number,
        email=item.email,
        wa_link=item.wa_link,
        context_text=build_context_text(source, item),
        title=build_notification_title(source, raw_row=item.raw_row),
    )


def stringify_meta_field_value(value: Any) -> str:
    """Return a stable string for one Meta lead field value."""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [stringify_meta_field_value(item) for item in value]
        return ", ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return " ".join(str(value).split()).strip()


def meta_field_data_to_row(command: MetaLeadFormImportCommand) -> dict[str, str]:
    """Convert Meta Lead Ads field_data into the generic Delivery row shape."""
    raw_payload = command.raw_payload if isinstance(command.raw_payload, dict) else {}
    row: dict[str, str] = {
        "id": command.leadgen_id.strip(),
        "leadgen_id": command.leadgen_id.strip(),
    }
    for key in [
        "created_time",
        "form_id",
        "ad_id",
        "ad_name",
        "adset_id",
        "adset_name",
        "campaign_id",
        "campaign_name",
        "platform",
    ]:
        value = stringify_meta_field_value(getattr(command, key, None) or raw_payload.get(key))
        if value:
            row[key] = value
    for item in command.field_data:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split()).strip()
        if not name:
            continue
        raw_values = item.get("values")
        if raw_values is None:
            raw_values = item.get("value")
        value = stringify_meta_field_value(raw_values)
        if value:
            row[name] = value
    return row


def import_meta_lead_form_record(source: ClientLeadSource, command: MetaLeadFormImportCommand) -> ClientLeadSyncResponse:
    """Import one retrieved Meta Lead Ads record through the Delivery queue."""
    row = meta_field_data_to_row(command)
    result = import_sheet_records(source, [row])
    if result.imported <= 0 or not source.sheet_url.strip():
        return result
    try:
        append_record_to_sheet(source, row)
        result.sheet_appended = 1
    except Exception as exc:
        result.sheet_append_errors.append(str(exc))
    return result


def meta_payload_to_import_command(payload: dict[str, Any], requested_leadgen_id: str) -> MetaLeadFormImportCommand:
    """Convert a fetched Graph payload into the generic import command."""
    leadgen_id = stringify_meta_field_value(
        payload.get("id") or payload.get("leadgen_id") or requested_leadgen_id
    )
    field_data = payload.get("field_data")
    return MetaLeadFormImportCommand(
        leadgen_id=leadgen_id,
        created_time=stringify_meta_field_value(payload.get("created_time")) or None,
        form_id=stringify_meta_field_value(payload.get("form_id")) or None,
        ad_id=stringify_meta_field_value(payload.get("ad_id")) or None,
        ad_name=stringify_meta_field_value(payload.get("ad_name")) or None,
        adset_id=stringify_meta_field_value(payload.get("adset_id") or payload.get("adgroup_id")) or None,
        adset_name=stringify_meta_field_value(payload.get("adset_name") or payload.get("adgroup_name")) or None,
        campaign_id=stringify_meta_field_value(payload.get("campaign_id")) or None,
        campaign_name=stringify_meta_field_value(payload.get("campaign_name")) or None,
        platform=stringify_meta_field_value(payload.get("platform")) or None,
        field_data=field_data if isinstance(field_data, list) else [],
        raw_payload=payload,
    )


def fetch_and_import_meta_lead_form_record(
    source: ClientLeadSource,
    command: MetaLeadFormFetchCommand,
    *,
    event_source: str,
    actor: str,
) -> ClientLeadSyncResponse:
    """Fetch one Meta lead by id and import it through Delivery."""
    payload = fetch_meta_lead_payload(
        leadgen_id=command.leadgen_id,
        fields=command.fields or DEFAULT_META_LEAD_FIELDS,
    )
    import_command = meta_payload_to_import_command(payload, command.leadgen_id)
    result = import_meta_lead_form_record(source, import_command)
    PlatformEvent.add(
        event_type="client_lead.meta_form_fetched_imported",
        lifecycle_stage="delivery",
        target_type="client_lead_source",
        target_id=source.id,
        source=event_source,
        actor=actor,
        summary=f"Fetched and imported Meta lead {import_command.leadgen_id.strip()} into Delivery source {source.id}.",
        payload={
            "reason": command.reason,
            "leadgen_id": import_command.leadgen_id.strip(),
            "requested_leadgen_id": command.leadgen_id.strip(),
            "form_id": import_command.form_id,
            "campaign_id": import_command.campaign_id,
            "ad_id": import_command.ad_id,
            "imported": result.imported,
            "updated": result.updated,
            "blocked": result.blocked,
            "queued": result.queued,
            "sheet_appended": result.sheet_appended,
            "sheet_append_errors": result.sheet_append_errors,
        },
        idempotency_key=f"meta_lead_fetch:{source.id}:{import_command.leadgen_id.strip()}",
    )
    return result


def fetch_and_import_meta_lead_form_records(
    source: ClientLeadSource,
    command: MetaLeadFormBackfillCommand,
    *,
    event_source: str,
    actor: str,
) -> ClientLeadSyncResponse:
    """Fetch recent Meta leads for a form and import them through Delivery."""
    form_id = " ".join((command.form_id or source.meta_lead_form_id or "").split()).strip()
    if not form_id:
        raise MetaLeadAdsError("form_id is required")
    payloads = fetch_meta_form_leads(
        form_id=form_id,
        fields=command.fields or DEFAULT_META_LEAD_FIELDS,
        limit=command.limit,
    )
    totals = {
        "imported": 0,
        "updated": 0,
        "blocked": 0,
        "skipped": 0,
        "queued": 0,
        "sheet_appended": 0,
    }
    sheet_append_errors: list[str] = []
    for payload in payloads:
        leadgen_id = stringify_meta_field_value(payload.get("id") or payload.get("leadgen_id"))
        import_command = meta_payload_to_import_command(payload, leadgen_id)
        if not import_command.form_id:
            import_command.form_id = form_id
        result = import_meta_lead_form_record(source, import_command)
        totals["imported"] += result.imported
        totals["updated"] += result.updated
        totals["blocked"] += result.blocked
        totals["skipped"] += result.skipped
        totals["queued"] += result.queued
        totals["sheet_appended"] += result.sheet_appended
        sheet_append_errors.extend(result.sheet_append_errors)

    note = (
        f"meta_form={form_id} fetched={len(payloads)} imported={totals['imported']} "
        f"updated={totals['updated']} blocked={totals['blocked']} queued={totals['queued']}"
    )
    source = ClientLeadSource.mark_sync(source.id, status="ok", note=note) or source
    result = ClientLeadSyncResponse(
        status="ok",
        source=build_source_response(source, ClientLeadDelivery.count_by_status_for_sources()),
        fetched=len(payloads),
        imported=totals["imported"],
        updated=totals["updated"],
        blocked=totals["blocked"],
        skipped=totals["skipped"],
        queued=totals["queued"],
        sheet_appended=totals["sheet_appended"],
        sheet_append_errors=sheet_append_errors,
    )
    PlatformEvent.add(
        event_type="client_lead.meta_form_backfilled",
        lifecycle_stage="delivery",
        target_type="client_lead_source",
        target_id=source.id,
        source=event_source,
        actor=actor,
        summary=f"Backfilled {len(payloads)} Meta leads from form {form_id} into Delivery source {source.id}.",
        payload={
            "reason": command.reason,
            "form_id": form_id,
            "fetched": result.fetched,
            "imported": result.imported,
            "updated": result.updated,
            "blocked": result.blocked,
            "queued": result.queued,
            "sheet_appended": result.sheet_appended,
            "sheet_append_errors": result.sheet_append_errors,
        },
        idempotency_key=f"meta_lead_backfill:{source.id}:{form_id}:{len(payloads)}",
    )
    return result


def normalize_delivery_error(command: ClientLeadDeliveryFailureCommand | ClientLeadDeliveryByExternalIdCommand) -> str:
    """Build one compact provider error string for UI and retry records."""
    parts: list[str] = []
    for value in [
        command.error,
        command.error_user_message,
        command.error_message,
        command.error_details,
        command.error_title,
    ]:
        clean_value = " ".join(str(value or "").split()).strip()
        if clean_value and clean_value not in parts:
            parts.append(clean_value)
    if command.error_code is not None:
        parts.append(f"Meta code: {command.error_code}")
    return " | ".join(parts)[:2000] or "unknown delivery error"


def parse_sheet_target(sheet_url: str, sheet_gid: str | None) -> tuple[str, str | None]:
    """Return spreadsheet id and gid from a raw id or Google Sheets URL."""
    clean_sheet_url = (sheet_url or "").strip()
    if re.fullmatch(r"[A-Za-z0-9-_]+", clean_sheet_url):
        return clean_sheet_url, (sheet_gid or "").strip() or None
    match = re.search(r"/spreadsheets/d/([A-Za-z0-9-_]+)", clean_sheet_url)
    if not match:
        raise ValueError("No pude extraer el spreadsheet_id de la sheet.")
    gid = (sheet_gid or "").strip() or None
    if gid is None:
        parsed = urlparse(clean_sheet_url)
        query_params = parse_qs(parsed.query)
        fragment_params = parse_qs(parsed.fragment)
        gid = query_params.get("gid", [None])[0] or fragment_params.get("gid", [None])[0]
    return match.group(1), gid


def public_csv_url(sheet_url: str, sheet_gid: str | None, sheet_tab_name: str | None = None) -> str:
    """Build a public CSV export URL for a Google Sheet."""
    if any(marker in sheet_url for marker in ["output=csv", "format=csv", "tqx=out:csv"]):
        return sheet_url
    spreadsheet_id, gid = parse_sheet_target(sheet_url, sheet_gid)
    clean_tab_name = " ".join((sheet_tab_name or "").split()).strip()
    if clean_tab_name:
        return (
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq"
            f"?tqx=out:csv&sheet={quote(clean_tab_name, safe='')}"
        )
    suffix = f"&gid={gid}" if gid else ""
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv{suffix}"


def public_xlsx_url(sheet_url: str) -> str:
    """Build a public XLSX export URL for a Google Sheet."""
    spreadsheet_id, _gid = parse_sheet_target(sheet_url, None)
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"


def rows_to_records(rows: list[list[str]]) -> list[dict[str, str]]:
    """Convert rows with first-row headers into dict records."""
    if not rows:
        return []
    headers = [str(value or "").strip() for value in rows[0]]
    records: list[dict[str, str]] = []
    for raw_row in rows[1:]:
        record = {
            header: str(raw_row[index] if index < len(raw_row) and raw_row[index] is not None else "").strip()
            for index, header in enumerate(headers)
            if header
        }
        if not row_is_empty(record):
            records.append(record)
    return records


def records_have_mappable_headers(records: list[dict[str, str]], mapping: dict[str, str]) -> bool:
    """Return True when parsed records look like a lead sheet, not an HTML/login page."""
    if not records:
        return False
    lookup = header_lookup(records[0])
    if not lookup:
        return False
    expected_headers: set[str] = set()
    for field in ["source_id", "created_time", "full_name", "phone_number", "email"]:
        configured = normalize_header(mapping.get(field, ""))
        if configured:
            expected_headers.add(configured)
        expected_headers.update(normalize_header(alias) for alias in HEADER_ALIASES.get(field, ()))
    return any(header in lookup for header in expected_headers if header)


def read_xlsx_records(content: bytes, sheet_tab_name: str | None = None) -> list[dict[str, str]]:
    """Read a named worksheet, or the first non-empty worksheet, in an XLSX export."""
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("openpyxl is required for XLSX Google Sheets exports.") from exc

    workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
    try:
        clean_tab_name = " ".join((sheet_tab_name or "").split()).strip()
        worksheets = workbook.worksheets
        if clean_tab_name:
            matches = [worksheet for worksheet in worksheets if worksheet.title.casefold() == clean_tab_name.casefold()]
            worksheets = matches or []
        for worksheet in worksheets:
            raw_rows = list(worksheet.iter_rows(values_only=True))
            records = rows_to_records([
                ["" if value is None else str(value) for value in raw_row]
                for raw_row in raw_rows
            ])
            if records:
                return records
    finally:
        workbook.close()
    return []


def service_account_file() -> str | None:
    """Return configured Google service account path if present."""
    for env_name in ["CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE", "GOOGLE_SERVICE_ACCOUNT_FILE"]:
        value = (os.getenv(env_name, "") or "").strip()
        if value:
            return value
    return None


def build_sheets_service(credentials_path: str, *, readonly: bool = True):
    """Build a Google Sheets API service."""
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("google-api-python-client and google-auth are required for private sheets.") from exc
    scope = (
        "https://www.googleapis.com/auth/spreadsheets.readonly"
        if readonly
        else "https://www.googleapis.com/auth/spreadsheets"
    )
    credentials = Credentials.from_service_account_file(
        credentials_path,
        scopes=[scope],
    )
    return build("sheets", "v4", credentials=credentials)


def quote_sheet_title(title: str) -> str:
    """Quote a Google Sheets tab title for A1 ranges."""
    escaped = title.replace("'", "''")
    return f"'{escaped}'"


def resolve_range_from_gid(
    service: Any,
    spreadsheet_id: str,
    gid: str | None,
    sheet_tab_name: str | None = None,
) -> str:
    """Resolve a sheet tab name or gid to the corresponding A1 range."""
    metadata = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(sheetId,title))")
        .execute()
    )
    sheets = metadata.get("sheets", [])
    if not sheets:
        raise RuntimeError("La spreadsheet no tiene pestañas visibles.")
    clean_tab_name = " ".join((sheet_tab_name or "").split()).strip()
    if clean_tab_name:
        for sheet in sheets:
            title = str(sheet.get("properties", {}).get("title") or "")
            if title.casefold() == clean_tab_name.casefold():
                return quote_sheet_title(title)
        raise RuntimeError(f"No encontré ninguna pestaña llamada {clean_tab_name!r}.")
    if gid is None:
        return quote_sheet_title(sheets[0]["properties"]["title"])
    for sheet in sheets:
        properties = sheet.get("properties", {})
        if str(properties.get("sheetId")) == str(gid):
            return quote_sheet_title(str(properties.get("title") or ""))
    raise RuntimeError(f"No encontré ninguna pestaña con gid={gid}.")


def read_records_with_service_account(source: ClientLeadSource) -> list[dict[str, str]]:
    """Read one sheet with Google Sheets API."""
    credentials_path = service_account_file()
    if not credentials_path:
        return []
    spreadsheet_id, gid = parse_sheet_target(source.sheet_url, source.sheet_gid)
    service = build_sheets_service(credentials_path)
    resolved_range = resolve_range_from_gid(service, spreadsheet_id, gid, source.sheet_tab_name)
    response = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=resolved_range)
        .execute()
    )
    return rows_to_records(response.get("values", []))


def meta_sheet_headers_for_record(row: dict[str, str]) -> list[str]:
    """Return a stable Google Sheet header order for Meta lead rows."""
    headers = [header for header in META_SHEET_PREFERRED_HEADERS if header in row]
    headers.extend(key for key in row.keys() if key and key not in headers)
    return headers


def append_record_to_sheet(source: ClientLeadSource, row: dict[str, str]) -> dict[str, Any]:
    """Append one imported Meta lead row to the source Google Sheet."""
    if not source.sheet_url.strip():
        raise RuntimeError("Sheet URL is required to append Meta leads.")
    credentials_path = service_account_file()
    if not credentials_path:
        raise RuntimeError("Google service account file is required to append Meta leads.")

    spreadsheet_id, gid = parse_sheet_target(source.sheet_url, source.sheet_gid)
    service = build_sheets_service(credentials_path, readonly=False)
    resolved_range = resolve_range_from_gid(service, spreadsheet_id, gid, source.sheet_tab_name)
    values_api = service.spreadsheets().values()
    header_range = f"{resolved_range}!1:1"
    response = values_api.get(spreadsheetId=spreadsheet_id, range=header_range).execute()
    existing_headers = [
        str(value or "").strip()
        for value in (response.get("values", [[]]) or [[]])[0]
    ]
    headers = [header for header in existing_headers if header]
    if not headers:
        headers = meta_sheet_headers_for_record(row)
    else:
        for header in meta_sheet_headers_for_record(row):
            if header not in headers:
                headers.append(header)

    values_api.update(
        spreadsheetId=spreadsheet_id,
        range=header_range,
        valueInputOption="RAW",
        body={"values": [headers]},
    ).execute()
    append_response = values_api.append(
        spreadsheetId=spreadsheet_id,
        range=f"{resolved_range}!A1",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [[row.get(header, "") for header in headers]]},
    ).execute()
    return {
        "spreadsheet_id": spreadsheet_id,
        "range": resolved_range,
        "headers": headers,
        "provider_response": append_response,
    }


async def fetch_sheet_records(source: ClientLeadSource) -> list[dict[str, str]]:
    """Fetch sheet records through public export or service account fallback."""
    if not source.sheet_url.strip():
        raise RuntimeError("Sheet URL is required.")

    public_access_errors: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        try:
            response = await client.get(public_csv_url(source.sheet_url, source.sheet_gid, source.sheet_tab_name))
            response.raise_for_status()
            records = [dict(row) for row in csv.DictReader(StringIO(response.text))]
            records = [row for row in records if not row_is_empty(row)]
            if records_have_mappable_headers(records, source.column_mapping):
                return records
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {401, 403, 404}:
                raise
            public_access_errors.append(f"public CSV returned HTTP {exc.response.status_code}")

        try:
            response = await client.get(public_xlsx_url(source.sheet_url))
            response.raise_for_status()
            records = read_xlsx_records(response.content, source.sheet_tab_name)
            if records_have_mappable_headers(records, source.column_mapping):
                return records
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {401, 403, 404}:
                raise
            public_access_errors.append(f"public XLSX returned HTTP {exc.response.status_code}")

    if not service_account_file() and public_access_errors:
        details = "; ".join(public_access_errors)
        raise RuntimeError(f"No pude leer el Google Sheet ({details}) y no hay service account configurada.")

    private_records = read_records_with_service_account(source)
    if records_have_mappable_headers(private_records, source.column_mapping):
        return private_records
    return []


def import_sheet_records(source: ClientLeadSource, records: list[dict[str, str]]) -> ClientLeadSyncResponse:
    """Persist sheet records and queue valid new notifications."""
    fetched = len(records)
    imported = 0
    updated = 0
    blocked = 0
    skipped = 0
    queued = 0

    mapping = source.column_mapping
    recipient_valid = bool(normalize_phone(source.recipient_phone))

    for index, row in enumerate(records, start=2):
        if row_is_empty(row):
            skipped += 1
            continue
        source_id_value = get_mapped_value(row, mapping, "source_id")
        name = get_mapped_value(row, mapping, "full_name")
        phone = get_mapped_value(row, mapping, "phone_number")
        email = get_mapped_value(row, mapping, "email")
        created_time = parse_datetime(get_mapped_value(row, mapping, "created_time"))
        normalized_phone = normalize_phone(phone)
        source_row_key = source_row_key_for(row, row_number=index, source_id_value=source_id_value)
        block_reason = ""
        if not normalized_phone:
            block_reason = "lead_phone_invalid"
        elif not recipient_valid:
            block_reason = "recipient_phone_invalid"
        wa_link = build_wa_link(phone=phone)
        notification_text = build_notification_text(
            source,
            name=name,
            phone=normalized_phone or phone,
            email=email,
            wa_link=wa_link,
            context_text=build_context_text_from_row(source, row),
            title=build_notification_title(source, raw_row=row),
        )
        item, created = ClientLeadDelivery.upsert_from_sheet_row(
            source=source,
            source_row_key=source_row_key,
            row_number=index,
            raw_row=row,
            full_name=name,
            phone_number=phone,
            email=email,
            created_time=created_time,
            wa_link=wa_link,
            notification_text=notification_text,
            block_reason=block_reason or None,
        )
        if created:
            imported += 1
        else:
            updated += 1
        if item.delivery_status == ClientLeadDeliveryStatus.BLOCKED:
            blocked += 1
        if created and item.delivery_status == ClientLeadDeliveryStatus.PENDING:
            queued += 1

    status = "ok"
    note = f"fetched={fetched} imported={imported} updated={updated} blocked={blocked} skipped={skipped} queued={queued}"
    source = ClientLeadSource.mark_sync(source.id, status=status, note=note) or source
    counts = ClientLeadDelivery.count_by_status_for_sources()
    return ClientLeadSyncResponse(
        status=status,
        source=build_source_response(source, counts),
        fetched=fetched,
        imported=imported,
        updated=updated,
        blocked=blocked,
        skipped=skipped,
        queued=queued,
    )


def build_copy_text(source: ClientLeadSource, item: ClientLeadDelivery) -> str:
    """Build clipboard-ready text for one client lead."""
    raw_lines = [f"- {key}: {value}" for key, value in item.raw_row.items()]
    context_text = build_context_text(source, item)
    delivery_status = (
        item.delivery_status.value
        if isinstance(item.delivery_status, ClientLeadDeliveryStatus)
        else str(item.delivery_status)
    )
    parts = [
        f"Fuente: {source.label}",
        f"Estado: {delivery_status}",
        f"Nombre: {item.full_name or '-'}",
        f"WhatsApp: {item.normalized_phone or item.phone_number or '-'}",
        f"Email: {item.email or '-'}",
    ]
    if context_text:
        parts.extend(["", "Contexto:", context_text])
    parts.extend(["", f"Link: {item.wa_link or '-'}", "", "Datos completos del sheet:", *raw_lines])
    return "\n".join(parts).strip() + "\n"


def get_required_source(source_id: str) -> ClientLeadSource:
    """Return a source or raise 404."""
    source = ClientLeadSource.get_by_id(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Client lead source not found.")
    return source


def get_required_delivery(delivery_id: str) -> ClientLeadDelivery:
    """Return a delivery row or raise 404."""
    item = ClientLeadDelivery.get_by_id(delivery_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Client lead not found.")
    return item


@client_leads_router.get("", response_model=ClientLeadSourceListResponse)
async def list_client_lead_sources() -> ClientLeadSourceListResponse:
    """List every Delivery source."""
    counts = ClientLeadDelivery.count_by_status_for_sources()
    return ClientLeadSourceListResponse(
        sources=[build_source_response(source, counts) for source in ClientLeadSource.list_all()]
    )


@client_leads_router.post("/config/reload", response_model=ClientLeadConfigSyncResult)
async def reload_client_lead_sources_config() -> ClientLeadConfigSyncResult:
    """Reload file-backed Delivery sources into the database."""
    return sync_client_lead_sources_from_config()


@client_leads_router.post("", response_model=ClientLeadSourceResponse)
async def create_client_lead_source(command: ClientLeadSourceCommand) -> ClientLeadSourceResponse:
    """Create one Delivery source."""
    try:
        source = ClientLeadSource.upsert(
            source_id=(command.id or "").strip() or None,
            **command.model_dump(exclude={"id"}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_source_response(source, ClientLeadDelivery.count_by_status_for_sources())


@client_leads_router.put("/{source_id}", response_model=ClientLeadSourceResponse)
async def update_client_lead_source(source_id: str, command: ClientLeadSourceCommand) -> ClientLeadSourceResponse:
    """Update one Delivery source."""
    get_required_source(source_id)
    try:
        source = ClientLeadSource.upsert(source_id=source_id, **command.model_dump(exclude={"id"}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_source_response(source, ClientLeadDelivery.count_by_status_for_sources())


@client_leads_router.delete("/{source_id}", response_model=dict[str, str])
async def delete_client_lead_source(source_id: str) -> dict[str, str]:
    """Delete a Delivery source and imported rows."""
    if not ClientLeadSource.delete(source_id):
        raise HTTPException(status_code=404, detail="Client lead source not found.")
    return {"status": "deleted", "source_id": source_id}


@client_leads_router.post("/{source_id}/sync", response_model=ClientLeadSyncResponse)
async def sync_client_lead_source(source_id: str) -> ClientLeadSyncResponse:
    """Fetch and import one Delivery source sheet."""
    source = get_required_source(source_id)
    if not source.enabled:
        source = ClientLeadSource.mark_sync(source.id, status="disabled", note="source disabled") or source
        return ClientLeadSyncResponse(status="disabled", source=build_source_response(source))
    if source.id.startswith("campaign-") and not source.sheet_url.strip():
        source = ClientLeadSource.mark_sync(
            source.id,
            status="ok",
            note="owned campaign form source; submissions arrive directly",
        ) or source
        counts = ClientLeadDelivery.count_by_status_for_sources()
        return ClientLeadSyncResponse(status="ok", source=build_source_response(source, counts))
    try:
        records = await fetch_sheet_records(source)
    except Exception as exc:
        source = ClientLeadSource.mark_sync(source.id, status="failed", note=str(exc)) or source
        raise HTTPException(status_code=502, detail=f"Could not sync sheet: {exc}") from exc
    return import_sheet_records(source, records)


@client_leads_router.post("/{source_id}/meta-lead", response_model=ClientLeadSyncResponse)
async def import_meta_lead_form_for_source(
    source_id: str,
    command: MetaLeadFormImportCommand,
) -> ClientLeadSyncResponse:
    """Import one retrieved Meta Lead Ads instant-form lead into Delivery."""
    source = get_required_source(source_id)
    if not source.enabled:
        source = ClientLeadSource.mark_sync(source.id, status="disabled", note="source disabled") or source
        return ClientLeadSyncResponse(status="disabled", source=build_source_response(source))
    result = import_meta_lead_form_record(source, command)
    PlatformEvent.add(
        event_type="client_lead.meta_form_imported",
        lifecycle_stage="delivery",
        target_type="client_lead_source",
        target_id=source.id,
        source="meta_lead_ads",
        actor="agent",
        summary=f"Imported Meta lead {command.leadgen_id.strip()} into Delivery source {source.id}.",
        payload={
            "leadgen_id": command.leadgen_id.strip(),
            "form_id": command.form_id,
            "campaign_id": command.campaign_id,
            "ad_id": command.ad_id,
            "imported": result.imported,
            "updated": result.updated,
            "blocked": result.blocked,
            "queued": result.queued,
            "sheet_appended": result.sheet_appended,
            "sheet_append_errors": result.sheet_append_errors,
        },
        idempotency_key=f"meta_lead:{source.id}:{command.leadgen_id.strip()}",
    )
    return result


@client_leads_router.post("/{source_id}/meta-lead/fetch", response_model=ClientLeadSyncResponse)
async def fetch_meta_lead_form_for_source(
    source_id: str,
    command: MetaLeadFormFetchCommand,
) -> ClientLeadSyncResponse:
    """Fetch one Meta Lead Ads instant-form lead and import it into Delivery."""
    source = get_required_source(source_id)
    if not source.enabled:
        source = ClientLeadSource.mark_sync(source.id, status="disabled", note="source disabled") or source
        return ClientLeadSyncResponse(status="disabled", source=build_source_response(source))
    try:
        return fetch_and_import_meta_lead_form_record(
            source,
            command,
            event_source="meta_lead_ads_graph",
            actor="agent",
        )
    except MetaLeadAdsCredentialsError as exc:
        note = f"missing Meta Lead Ads credentials: {', '.join(exc.missing)}"
        ClientLeadSource.mark_sync(source.id, status="failed", note=note)
        PlatformEvent.add(
            event_type="client_lead.meta_form_fetch_blocked",
            lifecycle_stage="delivery",
            target_type="client_lead_source",
            target_id=source.id,
            source="meta_lead_ads_graph",
            actor="agent",
            summary=f"Could not fetch Meta lead {command.leadgen_id.strip()}: {note}.",
            payload={"leadgen_id": command.leadgen_id.strip(), "errors": exc.missing},
            idempotency_key=f"meta_lead_fetch_blocked:{source.id}:{command.leadgen_id.strip()}",
        )
        raise HTTPException(
            status_code=503,
            detail={"status": "missing_credentials", "errors": exc.missing},
        ) from exc
    except MetaLeadAdsError as exc:
        ClientLeadSource.mark_sync(source.id, status="failed", note=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@client_leads_router.post("/{source_id}/meta-leads/backfill", response_model=ClientLeadSyncResponse)
async def backfill_meta_lead_form_for_source(
    source_id: str,
    command: MetaLeadFormBackfillCommand,
) -> ClientLeadSyncResponse:
    """Fetch recent leads from one Meta instant form and import them into Delivery."""
    source = get_required_source(source_id)
    if not source.enabled:
        source = ClientLeadSource.mark_sync(source.id, status="disabled", note="source disabled") or source
        return ClientLeadSyncResponse(status="disabled", source=build_source_response(source))
    try:
        return fetch_and_import_meta_lead_form_records(
            source,
            command,
            event_source="meta_lead_ads_graph",
            actor="agent",
        )
    except MetaLeadAdsCredentialsError as exc:
        note = f"missing Meta Lead Ads credentials: {', '.join(exc.missing)}"
        ClientLeadSource.mark_sync(source.id, status="failed", note=note)
        PlatformEvent.add(
            event_type="client_lead.meta_form_backfill_blocked",
            lifecycle_stage="delivery",
            target_type="client_lead_source",
            target_id=source.id,
            source="meta_lead_ads_graph",
            actor="agent",
            summary=f"Could not backfill Meta form leads for source {source.id}: {note}.",
            payload={"form_id": command.form_id or source.meta_lead_form_id, "errors": exc.missing},
            idempotency_key=f"meta_lead_backfill_blocked:{source.id}:{command.form_id or source.meta_lead_form_id}",
        )
        raise HTTPException(
            status_code=503,
            detail={"status": "missing_credentials", "errors": exc.missing},
        ) from exc
    except MetaLeadAdsError as exc:
        ClientLeadSource.mark_sync(source.id, status="failed", note=str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@client_leads_router.get("/{source_id}/leads", response_model=ClientLeadDeliveryListResponse)
async def list_client_leads_for_source(
    source_id: str,
    limit: int = Query(default=500, ge=1, le=5000),
) -> ClientLeadDeliveryListResponse:
    """List imported client leads for one source."""
    source = get_required_source(source_id)
    counts = ClientLeadDelivery.count_by_status_for_sources()
    return ClientLeadDeliveryListResponse(
        source=build_source_response(source, counts),
        leads=[build_delivery_response(item) for item in ClientLeadDelivery.list_by_source(source_id, limit=limit)],
    )


@client_leads_router.get("/{source_id}/recipient-chat", response_model=ClientLeadRecipientChatResponse)
async def get_client_lead_recipient_chat(
    source_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> ClientLeadRecipientChatResponse:
    """Return the Delivery recipient's sent-notification audit thread."""
    source = get_required_source(source_id)
    counts = ClientLeadDelivery.count_by_status_for_sources()
    crm_leads = ContadoresLead.list_by_normalized_phone(source.normalized_recipient_phone, include_archived=False)
    sibling_source_ids = [
        item.id
        for item in ClientLeadSource.list_all()
        if item.normalized_recipient_phone and item.normalized_recipient_phone == source.normalized_recipient_phone
    ] or [source.id]
    deliveries = []
    for sibling_source_id in sibling_source_ids:
        deliveries.extend(
            item
            for item in ClientLeadDelivery.list_by_source(sibling_source_id, limit=5000)
            if should_show_recipient_chat_message(item)
        )
    deliveries = sorted(deliveries, key=recipient_chat_sort_key)[-limit:]
    return ClientLeadRecipientChatResponse(
        source=build_source_response(source, counts),
        recipient_name=source.recipient_name,
        recipient_phone=source.recipient_phone,
        normalized_recipient_phone=source.normalized_recipient_phone,
        crm_leads=[build_recipient_crm_lead_response(lead) for lead in crm_leads],
        messages=[build_recipient_chat_message_response(item) for item in deliveries],
    )


@client_leads_actions_router.get("/{delivery_id}/copy-all", response_model=ClientLeadCopyAllResponse)
async def get_client_lead_copy_all(delivery_id: str) -> ClientLeadCopyAllResponse:
    """Return one client lead as clipboard-friendly text."""
    item = get_required_delivery(delivery_id)
    source = get_required_source(item.source_id)
    return ClientLeadCopyAllResponse(text=build_copy_text(source, item))


@client_leads_actions_router.post("/{delivery_id}/retry", response_model=ClientLeadDeliveryResponse)
async def retry_client_lead_notification(delivery_id: str) -> ClientLeadDeliveryResponse:
    """Requeue a failed client lead notification."""
    item = get_required_delivery(delivery_id)
    if item.delivery_status not in {ClientLeadDeliveryStatus.FAILED, ClientLeadDeliveryStatus.BLOCKED}:
        raise HTTPException(status_code=400, detail="Only failed or blocked client lead notifications can be retried.")
    if not item.normalized_phone:
        raise HTTPException(status_code=400, detail="Client lead phone is invalid.")
    source = get_required_source(item.source_id)
    if not normalize_phone(source.recipient_phone):
        raise HTTPException(status_code=400, detail="Recipient phone is invalid.")
    updated = ClientLeadDelivery.requeue_failed(item.id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Client lead not found.")
    return build_delivery_response(updated)


@client_lead_deliveries_router.get("/pending", response_model=ClientLeadPendingNotificationResponse)
async def list_pending_client_lead_notifications(
    limit: int = Query(default=DEFAULT_PENDING_LIMIT, ge=1, le=500),
) -> ClientLeadPendingNotificationResponse:
    """Return Delivery notifications ready for bot dispatch."""
    notifications: list[ClientLeadPendingNotification] = []
    for item in ClientLeadDelivery.list_pending_notification(limit=limit):
        source = ClientLeadSource.get_by_id(item.source_id)
        if source is None or not source.enabled:
            continue
        if not normalize_phone(source.recipient_phone):
            ClientLeadDelivery.update_delivery_status(
                delivery_id=item.id,
                delivery_status=ClientLeadDeliveryStatus.BLOCKED,
                last_delivery_error="recipient_phone_invalid",
            )
            continue
        notifications.append(
            ClientLeadPendingNotification(
                delivery_id=item.id,
                source_id=source.id,
                source_label=source.label,
                recipient_phone=source.recipient_phone,
                normalized_recipient_phone=source.normalized_recipient_phone,
                template_name=source.template_name,
                template_language=source.template_language,
                template_body_params=build_template_params(source, item),
                delivered_text=build_delivery_notification_text(source, item),
            )
        )
    return ClientLeadPendingNotificationResponse(notifications=notifications)


@client_lead_deliveries_router.put("/delivery/by-external-id", response_model=ClientLeadDeliveryResponse)
async def update_client_lead_delivery_by_external_id(
    command: ClientLeadDeliveryByExternalIdCommand,
) -> ClientLeadDeliveryResponse:
    """Apply a WhatsApp delivery webhook by external message id."""
    updated = ClientLeadDelivery.update_delivery_status_by_external_id(
        external_id=command.external_id,
        delivery_status=command.status,
        last_delivery_error=normalize_delivery_error(command) if command.status == "failed" else None,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Client lead notification not found.")
    return build_delivery_response(updated)


@client_lead_deliveries_router.put("/{delivery_id}/delivery", response_model=ClientLeadDeliveryResponse)
async def update_client_lead_delivery_status(
    delivery_id: str,
    command: ClientLeadDeliveryUpdateCommand,
) -> ClientLeadDeliveryResponse:
    """Mark one Delivery notification as accepted by WhatsApp."""
    updated = ClientLeadDelivery.update_delivery_status(
        delivery_id=delivery_id,
        delivery_status=command.status,
        external_id=command.external_id,
        sent_text=command.sent_text,
        clear_delivery_error=True,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Client lead not found.")
    return build_delivery_response(updated)


@client_lead_deliveries_router.post("/{delivery_id}/delivery-failure", response_model=ClientLeadDeliveryResponse)
async def record_client_lead_delivery_failure(
    delivery_id: str,
    command: ClientLeadDeliveryFailureCommand,
) -> ClientLeadDeliveryResponse:
    """Record one failed Delivery WhatsApp send attempt."""
    updated = ClientLeadDelivery.record_delivery_failure(
        delivery_id=delivery_id,
        error=normalize_delivery_error(command),
        max_attempts=command.max_attempts,
        retry_delay_seconds=command.retry_delay_seconds,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Client lead not found.")
    return build_delivery_response(updated)
