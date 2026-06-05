"""Owned campaign, public form, and converted-client endpoints."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from backend.database import (
    CLIENT_LEAD_CONTEXT_TEMPLATE_NAME,
    CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE,
    ClientLeadDelivery,
    ClientLeadDeliveryStatus,
    ClientLeadSource,
    ContadoresLead,
    LeadCaptureCampaign,
    LeadCaptureSubmission,
    PlatformAdCampaign,
    PlatformEvent,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationClientStatus,
    WorkstationClientWorkType,
    normalize_email,
    normalize_lead_capture_form_schema,
    normalize_phone,
)
from backend.endpoints.client_leads import (
    build_context_text_from_row,
    build_notification_text,
    build_source_response,
    build_wa_link,
    format_timestamp_seconds,
)
from backend.meta_conversions import build_user_data, send_meta_conversion_event


campaigns_router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
public_campaigns_router = APIRouter(tags=["campaigns"])

PUBLIC_ALLOWED_TRACKING_KEYS = {
    "href",
    "referrer",
    "fbp",
    "fbc",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
}
PUBLIC_MAX_ANSWER_FIELDS = 40
PUBLIC_MAX_ANSWER_BYTES = 20_000
PUBLIC_MAX_FIELD_TEXT = 2_000
PUBLIC_MAX_TRACKING_TEXT = 1_000
PUBLISHABLE_CAMPAIGN_STATUSES = {"active", "published"}


class ConvertedClientCommand(BaseModel):
    """Create or reuse a converted client from minimal contact data."""

    name: str = Field(min_length=1)
    whatsapp: str = Field(min_length=3)
    email: str | None = None
    extra_info: str | None = None
    funnel_id: str = "contadores"
    work_type: str = WorkstationClientWorkType.PAGINA_ADS.value
    status: str = WorkstationClientStatus.PAID.value
    automation_status: str = WorkstationAutomationStatus.NEEDS_HUMAN.value
    offer_price_usd: int | None = Field(default=None, ge=1)
    offer_currency: str = "USD"


class LeadCaptureCampaignCommand(BaseModel):
    """Create an owned lead-capture campaign."""

    name: str = Field(min_length=1)
    client_id: str | None = None
    client: ConvertedClientCommand | None = None
    status: str = "draft"
    public_slug: str | None = None
    daily_budget_usd: int | None = Field(default=None, ge=1)
    budget_currency: str = "USD"
    location: str | None = None
    campaign_info: dict[str, Any] = Field(default_factory=dict)
    creative_brief: str | None = None
    form_schema: dict[str, Any] = Field(default_factory=dict)
    thank_you_title: str = "Gracias"
    thank_you_body: str = "Recibimos tus datos. Te vamos a contactar por WhatsApp."
    destination_url: str | None = None
    meta_pixel_id: str | None = None
    meta_event_name: str = "Lead"
    meta_events_enabled: bool = False
    meta_test_event_code: str | None = None
    stage_platform_campaign: bool = True


class LeadCaptureCampaignPatchCommand(BaseModel):
    """Patch an owned lead-capture campaign."""

    name: str | None = None
    client_id: str | None = None
    status: str | None = None
    public_slug: str | None = None
    daily_budget_usd: int | None = Field(default=None, ge=1)
    budget_currency: str | None = None
    location: str | None = None
    campaign_info: dict[str, Any] | None = None
    creative_brief: str | None = None
    form_schema: dict[str, Any] | None = None
    thank_you_title: str | None = None
    thank_you_body: str | None = None
    destination_url: str | None = None
    meta_pixel_id: str | None = None
    meta_event_name: str | None = None
    meta_events_enabled: bool | None = None
    meta_test_event_code: str | None = None
    meta_campaign_id: str | None = None
    meta_adset_id: str | None = None
    meta_ad_id: str | None = None


class PublicSubmissionCommand(BaseModel):
    """Public lead-capture form submission."""

    answers: dict[str, Any] = Field(default_factory=dict)
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    tracking: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)
    honeypot: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if value is None:
        return ""
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def _request_origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _public_url(request: Request, campaign: LeadCaptureCampaign) -> str:
    return f"{_request_origin(request)}/c/{campaign.public_slug}"


def _lead_payload(lead: ContadoresLead | None) -> dict[str, Any] | None:
    if lead is None:
        return None
    return {
        "id": lead.id,
        "funnel_id": lead.funnel_id,
        "external_lead_id": lead.external_lead_id,
        "full_name": lead.full_name,
        "phone": lead.phone,
        "normalized_phone": lead.normalized_phone,
        "email": lead.email,
        "pipeline_stage": lead.pipeline_stage,
        "queue_state": lead.queue_state,
        "attention_state": lead.attention_state,
        "created_at": format_timestamp_seconds(lead.created_at),
        "updated_at": format_timestamp_seconds(lead.updated_at),
    }


def _client_payload(client: WorkstationClient | None) -> dict[str, Any] | None:
    if client is None:
        return None
    lead = ContadoresLead.get_by_id(client.lead_id)
    return {
        "id": client.id,
        "lead_id": client.lead_id,
        "funnel_id": client.funnel_id,
        "display_name": client.display_name,
        "status": client.status.value if hasattr(client.status, "value") else str(client.status),
        "work_type": client.work_type.value if hasattr(client.work_type, "value") else str(client.work_type),
        "automation_status": (
            client.automation_status.value
            if hasattr(client.automation_status, "value")
            else str(client.automation_status)
        ),
        "notes": client.notes,
        "lead": _lead_payload(lead),
        "created_at": format_timestamp_seconds(client.created_at),
        "updated_at": format_timestamp_seconds(client.updated_at),
    }


def _submission_payload(submission: LeadCaptureSubmission) -> dict[str, Any]:
    delivery = ClientLeadDelivery.get_by_id(submission.client_lead_delivery_id) if submission.client_lead_delivery_id else None
    return {
        "id": submission.id,
        "campaign_id": submission.campaign_id,
        "client_id": submission.client_id,
        "client_lead_delivery_id": submission.client_lead_delivery_id,
        "full_name": submission.full_name,
        "phone": submission.phone,
        "normalized_phone": submission.normalized_phone,
        "email": submission.email,
        "answers": submission.answers,
        "tracking": submission.tracking,
        "meta_event_id": submission.meta_event_id,
        "meta_event_status": submission.meta_event_status,
        "meta_event_response": submission.meta_event_response,
        "delivery_status": (
            delivery.delivery_status.value
            if delivery and hasattr(delivery.delivery_status, "value")
            else (str(delivery.delivery_status) if delivery else "")
        ),
        "created_at": format_timestamp_seconds(submission.created_at),
        "updated_at": format_timestamp_seconds(submission.updated_at),
    }


def _public_submission_receipt(
    *,
    campaign: LeadCaptureCampaign,
    submission: LeadCaptureSubmission | None = None,
    duplicate: bool = False,
    delivery_queued: bool = False,
    spam: bool = False,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "ok": True,
        "accepted": True,
        "duplicate": duplicate,
        "delivery_queued": delivery_queued,
        "thank_you": {"title": campaign.thank_you_title, "body": campaign.thank_you_body},
    }
    if spam:
        receipt["spam"] = True
    if submission is not None:
        receipt["submission"] = {
            "id": submission.id,
            "created_at": format_timestamp_seconds(submission.created_at),
        }
    return receipt


def _campaign_payload(
    campaign: LeadCaptureCampaign,
    *,
    request: Request | None = None,
    include_submissions: bool = False,
) -> dict[str, Any]:
    client = WorkstationClient.get_by_id(campaign.client_id) if campaign.client_id else None
    source = ClientLeadSource.get_by_id(campaign.client_lead_source_id) if campaign.client_lead_source_id else None
    counts = LeadCaptureSubmission.count_by_campaign()
    payload = {
        "id": campaign.id,
        "client_id": campaign.client_id,
        "client_lead_source_id": campaign.client_lead_source_id,
        "platform_ad_campaign_id": campaign.platform_ad_campaign_id,
        "funnel_id": campaign.funnel_id,
        "name": campaign.name,
        "status": campaign.status,
        "public_slug": campaign.public_slug,
        "public_url": _public_url(request, campaign) if request else f"/c/{campaign.public_slug}",
        "daily_budget_usd": campaign.daily_budget_usd,
        "budget_currency": campaign.budget_currency,
        "location": campaign.location,
        "campaign_info": campaign.campaign_info,
        "creative_brief": campaign.creative_brief,
        "form_schema": campaign.form_schema,
        "thank_you_title": campaign.thank_you_title,
        "thank_you_body": campaign.thank_you_body,
        "destination_url": campaign.destination_url,
        "meta_pixel_id": campaign.meta_pixel_id,
        "meta_event_name": campaign.meta_event_name,
        "meta_events_enabled": campaign.meta_events_enabled,
        "meta_campaign_id": campaign.meta_campaign_id,
        "meta_adset_id": campaign.meta_adset_id,
        "meta_ad_id": campaign.meta_ad_id,
        "submission_count": counts.get(campaign.id, 0),
        "client": _client_payload(client),
        "delivery_source": build_source_response(source).model_dump(mode="json") if source else None,
        "created_at": format_timestamp_seconds(campaign.created_at),
        "updated_at": format_timestamp_seconds(campaign.updated_at),
    }
    if include_submissions:
        payload["submissions"] = [
            _submission_payload(item)
            for item in LeadCaptureSubmission.list_by_campaign(campaign.id, limit=500)
        ]
    return payload


def _public_campaign_payload(campaign: LeadCaptureCampaign, *, request: Request) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "public_slug": campaign.public_slug,
        "public_url": _public_url(request, campaign),
        "form_schema": campaign.form_schema,
        "thank_you_title": campaign.thank_you_title,
        "thank_you_body": campaign.thank_you_body,
    }


def _get_campaign_or_404(campaign_id: str) -> LeadCaptureCampaign:
    campaign = LeadCaptureCampaign.get_by_id(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


def _get_public_campaign_or_404(public_slug: str) -> LeadCaptureCampaign:
    campaign = LeadCaptureCampaign.get_by_slug(public_slug)
    if campaign is None or campaign.status not in PUBLISHABLE_CAMPAIGN_STATUSES:
        raise HTTPException(status_code=404, detail="Campaign form not found.")
    return campaign


def _validate_campaign_client_link(client_id: str, status: str) -> WorkstationClient | None:
    clean_client_id = (client_id or "").strip()
    clean_status = (status or "draft").strip().lower()
    if not clean_client_id:
        if clean_status in PUBLISHABLE_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail="Active campaigns must be linked to a client.")
        return None
    client = WorkstationClient.get_by_id(clean_client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found.")
    lead = ContadoresLead.get_by_id(client.lead_id)
    if clean_status in PUBLISHABLE_CAMPAIGN_STATUSES and (lead is None or not normalize_phone(lead.phone)):
        raise HTTPException(status_code=400, detail="Active campaign client must have a valid WhatsApp.")
    return client


def _create_or_reuse_manual_lead(command: ConvertedClientCommand) -> ContadoresLead:
    normalized_phone = normalize_phone(command.whatsapp)
    if not normalized_phone:
        raise HTTPException(status_code=400, detail="WhatsApp is invalid.")
    clean_email = normalize_email(command.email or "") if command.email else None
    existing = next(
        (
            lead
            for lead in ContadoresLead.list_by_normalized_phone(normalized_phone, include_archived=True)
            if lead.terminal_state != "archived"
        ),
        None,
    )
    external_id = existing.external_lead_id if existing else f"manual-client:{normalized_phone}"
    try:
        lead = ContadoresLead.upsert(
            funnel_id=command.funnel_id,
            external_lead_id=external_id,
            phone=command.whatsapp,
            full_name=command.name,
            email=clean_email,
            platform="manual_client",
            lead_status="converted",
            tags=["manual-client", "converted-client"],
            sheet_created_time=_utcnow() if existing is None else existing.sheet_created_time,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ContadoresLead.mark_converted(
        lead.id,
        converted_at=_utcnow(),
        automation_paused=True,
        automation_paused_reason="manual_converted_client",
    ) or lead


def create_or_reuse_converted_client(command: ConvertedClientCommand) -> dict[str, Any]:
    """Create or reuse a Workstation client from manual contact data."""
    lead = _create_or_reuse_manual_lead(command)
    existing = WorkstationClient.get_by_lead_id(lead.id)
    client = existing or WorkstationClient.create_for_lead(
        lead,
        work_type=command.work_type,
        status=command.status,
        automation_status=command.automation_status,
        offer_price_usd=command.offer_price_usd,
        offer_currency=command.offer_currency,
    )
    client = WorkstationClient.update_automation_state(
        client.id,
        status=command.status,
        automation_status=command.automation_status,
    ) or client
    if command.offer_price_usd:
        client = WorkstationClient.update_offer(
            client.id,
            offer_price_usd=command.offer_price_usd,
            offer_currency=command.offer_currency,
            only_if_missing=False,
        ) or client
    if command.extra_info is not None:
        client = WorkstationClient.update_notes(client.id, notes=command.extra_info) or client

    PlatformEvent.add(
        event_type="workstation_client.manual_created",
        lifecycle_stage="post_conversion",
        target_type="workstation_client",
        target_id=client.id,
        funnel_id=client.funnel_id,
        source="campaign_api",
        actor="operator",
        summary=f"Manual converted client ready: {client.display_name}.",
        payload={"lead_id": lead.id, "existing_client": existing is not None},
        idempotency_key=f"manual-client:{lead.id}:{client.id}",
    )
    return {"client": _client_payload(client), "lead": _lead_payload(ContadoresLead.get_by_id(lead.id))}


def _context_mapping_for_form(form_schema: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field in form_schema.get("fields", []):
        if not isinstance(field, dict):
            continue
        field_id = str(field.get("id") or "").strip()
        field_type = str(field.get("type") or "").strip()
        label = " ".join(str(field.get("label") or field_id).split()).strip()
        if not field_id or field_id in {"full_name", "name", "phone", "email"} or field_type in {"phone", "email"}:
            continue
        mapping[label[:80] or field_id] = field_id
    return mapping


def ensure_campaign_delivery_source(campaign: LeadCaptureCampaign) -> ClientLeadSource | None:
    """Create or update the Delivery source used by one campaign."""
    if not campaign.client_id:
        return None
    client = WorkstationClient.get_by_id(campaign.client_id)
    if client is None:
        return None
    lead = ContadoresLead.get_by_id(client.lead_id)
    if lead is None or not normalize_phone(lead.phone):
        return None
    source_id = campaign.client_lead_source_id or f"campaign-{campaign.public_slug}"
    context_mapping = _context_mapping_for_form(campaign.form_schema)
    template_name = CLIENT_LEAD_CONTEXT_TEMPLATE_NAME if context_mapping else None
    try:
        source = ClientLeadSource.upsert(
            source_id=source_id,
            label=f"{client.display_name or lead.full_name or 'Cliente'} - {campaign.name}",
            enabled=campaign.status in {"active", "published"},
            sheet_url="",
            recipient_name=client.display_name or lead.full_name,
            recipient_phone=lead.phone,
            template_name=template_name,
            template_language=CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE,
            column_mapping={
                "source_id": "id",
                "created_time": "created_time",
                "full_name": "full_name",
                "phone_number": "phone_number",
                "email": "email",
            },
            context_field_mapping=context_mapping,
        )
    except ValueError:
        return None
    if campaign.client_lead_source_id != source.id:
        campaign = LeadCaptureCampaign.update(campaign.id, client_lead_source_id=source.id) or campaign
    return source


def _stage_platform_ad_campaign(command: LeadCaptureCampaignCommand, *, client_id: str, funnel_id: str) -> PlatformAdCampaign:
    target_segments = []
    if command.location:
        target_segments.append({"type": "location", "value": command.location})
    return PlatformAdCampaign.add(
        client_id=client_id,
        funnel_id=funnel_id,
        status="draft",
        objective="lead_capture_form",
        budget_daily_usd=command.daily_budget_usd,
        budget_currency=command.budget_currency,
        target_segments=target_segments,
        angles=[command.creative_brief] if command.creative_brief else [],
        creative_benchmark={"source": "owned_campaign_form", "campaign_info": command.campaign_info},
        creative_testing={"destination": "owned_form", "default_status": "PAUSED"},
        approval_status="not_requested",
        idempotency_key=f"lead-capture:{client_id}:{command.name}",
    )


def _answer_value(answers: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = answers.get(key)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if str(item).strip())
        clean = " ".join(str(value or "").split()).strip()
        if clean:
            return clean
    return ""


def _field_value_to_text(value: Any) -> str:
    if isinstance(value, list):
        values = [_field_value_to_text(item) for item in value]
        return ", ".join(item for item in values if item)
    if isinstance(value, dict):
        return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    return " ".join(str(value or "").split()).strip()


def _normalize_submission_value(field: dict[str, Any], raw_value: Any) -> Any:
    field_type = str(field.get("type") or "text")
    options = [str(option) for option in field.get("options", []) if str(option).strip()]

    if field_type == "multi_select":
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        clean_values = [_field_value_to_text(value)[:PUBLIC_MAX_FIELD_TEXT] for value in values]
        clean_values = [value for value in clean_values if value]
        if len(clean_values) > 20:
            raise HTTPException(status_code=400, detail=f"Too many values for {field.get('id')}.")
        if options and any(value not in options for value in clean_values):
            raise HTTPException(status_code=400, detail=f"Invalid option for {field.get('id')}.")
        return clean_values

    clean_value = _field_value_to_text(raw_value)
    if len(clean_value) > PUBLIC_MAX_FIELD_TEXT:
        raise HTTPException(status_code=400, detail=f"{field.get('label') or field.get('id')} is too long.")
    if field_type == "yes_no" and clean_value and clean_value not in {"Si", "No"}:
        raise HTTPException(status_code=400, detail=f"Invalid yes/no value for {field.get('id')}.")
    if field_type == "select" and clean_value and options and clean_value not in options:
        raise HTTPException(status_code=400, detail=f"Invalid option for {field.get('id')}.")
    if field_type == "email" and clean_value and not normalize_email(clean_value):
        raise HTTPException(status_code=400, detail=f"{field.get('label') or field.get('id')} is invalid.")
    if field_type == "phone" and clean_value and not normalize_phone(clean_value):
        raise HTTPException(status_code=400, detail=f"{field.get('label') or field.get('id')} is invalid.")
    return normalize_email(clean_value) if field_type == "email" and clean_value else clean_value


def _normalize_submission_answers(campaign: LeadCaptureCampaign, command: PublicSubmissionCommand) -> dict[str, Any]:
    raw_size = len(json.dumps(_jsonable(command.answers), ensure_ascii=False))
    if raw_size > PUBLIC_MAX_ANSWER_BYTES:
        raise HTTPException(status_code=400, detail="Submission is too large.")
    if len(command.answers) > PUBLIC_MAX_ANSWER_FIELDS:
        raise HTTPException(status_code=400, detail="Too many fields.")

    fields = campaign.form_schema.get("fields", [])
    field_map = {str(field.get("id") or "").strip(): field for field in fields if isinstance(field, dict)}
    raw_answers = {str(key).strip(): value for key, value in command.answers.items() if str(key).strip()}
    for aliases, value in (
        (("full_name", "name", "nombre", "nombre_completo"), command.full_name),
        (("phone", "phone_number", "whatsapp", "telefono", "celular"), command.phone),
        (("email", "correo", "mail"), command.email),
    ):
        if not value:
            continue
        for alias in aliases:
            if alias in field_map and alias not in raw_answers:
                raw_answers[alias] = value
                break
    unknown_fields = sorted(set(raw_answers) - set(field_map))
    if unknown_fields:
        raise HTTPException(status_code=400, detail=f"Unknown field: {unknown_fields[0]}.")

    answers: dict[str, Any] = {}
    for field_id, field in field_map.items():
        if field_id in raw_answers:
            value = _normalize_submission_value(field, raw_answers[field_id])
            if value != "" and value != []:
                answers[field_id] = value
        elif field.get("required"):
            label = field.get("label") or field_id
            raise HTTPException(status_code=400, detail=f"{label} is required.")
    return answers


def _normalize_tracking(value: dict[str, Any]) -> dict[str, str]:
    tracking: dict[str, str] = {}
    for key, item in value.items():
        clean_key = str(key or "").strip()
        if clean_key not in PUBLIC_ALLOWED_TRACKING_KEYS:
            continue
        clean_value = _field_value_to_text(item)
        if clean_value:
            tracking[clean_key] = clean_value[:PUBLIC_MAX_TRACKING_TEXT]
    return tracking


def _submission_idempotency_key(campaign: LeadCaptureCampaign, idempotency_key: str | None) -> str:
    clean_key = " ".join(str(idempotency_key or "").split()).strip()
    if clean_key:
        return f"lead-capture:{campaign.id}:{clean_key[:160]}"
    return f"lead-capture:{campaign.id}:{secrets.token_urlsafe(16)}"


def _submission_contact(command: PublicSubmissionCommand, answers: dict[str, Any]) -> tuple[str, str, str | None]:
    full_name = (
        command.full_name
        or _answer_value(answers, "full_name", "name", "nombre", "nombre_completo")
    )
    phone = command.phone or _answer_value(answers, "phone", "phone_number", "whatsapp", "telefono", "celular")
    email = command.email or _answer_value(answers, "email", "correo", "mail")
    clean_email = normalize_email(email or "") if email else None
    return " ".join((full_name or "").split()).strip(), phone, clean_email


def _raw_row_for_submission(campaign: LeadCaptureCampaign, submission: LeadCaptureSubmission) -> dict[str, str]:
    raw: dict[str, str] = {
        "id": submission.id,
        "created_time": format_timestamp_seconds(submission.created_at) or "",
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "campaign_slug": campaign.public_slug,
        "full_name": submission.full_name or "",
        "phone_number": submission.normalized_phone or submission.phone,
        "email": submission.email or "",
    }
    for key, value in submission.answers.items():
        if isinstance(value, list):
            raw[str(key)] = ", ".join(str(item) for item in value)
        else:
            raw[str(key)] = str(value or "")
    return raw


def _queue_delivery_for_submission(
    *,
    campaign: LeadCaptureCampaign,
    submission: LeadCaptureSubmission,
) -> ClientLeadDelivery | None:
    source = ensure_campaign_delivery_source(campaign)
    if source is None:
        return None
    raw_row = _raw_row_for_submission(campaign, submission)
    block_reason = ""
    if not normalize_phone(submission.phone):
        block_reason = "lead_phone_invalid"
    elif not normalize_phone(source.recipient_phone):
        block_reason = "recipient_phone_invalid"

    wa_link = build_wa_link(phone=submission.normalized_phone or submission.phone)
    notification_text = build_notification_text(
        source,
        name=submission.full_name or "",
        phone=submission.normalized_phone or submission.phone,
        email=submission.email,
        wa_link=wa_link,
        context_text=build_context_text_from_row(source, raw_row),
    )
    delivery, _created = ClientLeadDelivery.upsert_from_sheet_row(
        source=source,
        source_row_key=f"campaign-submission:{submission.id}",
        row_number=0,
        raw_row=raw_row,
        full_name=submission.full_name,
        phone_number=submission.phone,
        email=submission.email,
        created_time=submission.created_at,
        wa_link=wa_link,
        notification_text=notification_text,
        block_reason=block_reason or None,
    )
    return delivery


def _track_meta_event(
    *,
    request: Request,
    campaign: LeadCaptureCampaign,
    submission: LeadCaptureSubmission,
) -> LeadCaptureSubmission:
    if not campaign.meta_events_enabled:
        return LeadCaptureSubmission.update_delivery_and_meta(
            submission.id,
            meta_event_status="disabled",
        ) or submission

    tracking = submission.tracking
    user_data = build_user_data(
        email=submission.email,
        phone=submission.normalized_phone or submission.phone,
        client_ip_address=request.client.host if request.client else None,
        client_user_agent=request.headers.get("user-agent"),
        fbp=str(tracking.get("fbp") or request.cookies.get("_fbp") or ""),
        fbc=str(tracking.get("fbc") or request.cookies.get("_fbc") or ""),
    )
    result = send_meta_conversion_event(
        pixel_id=campaign.meta_pixel_id,
        event_name=campaign.meta_event_name,
        event_id=submission.meta_event_id or submission.id,
        event_source_url=_public_url(request, campaign),
        user_data=user_data,
        custom_data={
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "client_id": campaign.client_id,
            "lead_capture_submission_id": submission.id,
        },
        test_event_code=campaign.meta_test_event_code,
    )
    PlatformEvent.add(
        event_type=f"lead_capture.meta_event_{result.status}",
        lifecycle_stage="lead_capture",
        target_type="lead_capture_submission",
        target_id=submission.id,
        funnel_id=campaign.funnel_id,
        severity="info" if result.status in {"sent", "disabled"} else "warning",
        source="public_campaign_form",
        actor="system",
        summary=f"Meta CAPI event {result.status} for {campaign.name}.",
        payload=result.model_dump(mode="json"),
        idempotency_key=f"lead-capture-meta:{submission.id}",
    )
    return LeadCaptureSubmission.update_delivery_and_meta(
        submission.id,
        meta_event_id=result.event_id,
        meta_event_status=result.status,
        meta_event_response=result.model_dump(mode="json"),
    ) or submission


@campaigns_router.post("/clients/converted")
async def create_converted_client(command: ConvertedClientCommand) -> dict[str, Any]:
    """Create or reuse a converted Workstation client."""
    return create_or_reuse_converted_client(command)


@campaigns_router.get("/clients")
async def list_campaign_clients(
    query: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """List converted clients available for campaign linking."""
    clean_query = (query or "").strip().lower()
    clients = []
    for client in WorkstationClient.list_recent(limit=limit):
        payload = _client_payload(client)
        haystack = json.dumps(payload, ensure_ascii=False).lower()
        if clean_query and clean_query not in haystack:
            continue
        clients.append(payload)
    return {"count": len(clients), "clients": clients}


@campaigns_router.get("")
async def list_campaigns(
    request: Request,
    client_id: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """List owned lead-capture campaigns."""
    rows = LeadCaptureCampaign.list_recent(client_id=client_id, status=status, query=query, limit=limit)
    return {
        "count": len(rows),
        "campaigns": [_campaign_payload(row, request=request) for row in rows],
    }


@campaigns_router.post("")
async def create_campaign(request: Request, command: LeadCaptureCampaignCommand) -> dict[str, Any]:
    """Create one owned lead-capture campaign."""
    client_id = (command.client_id or "").strip()
    if not client_id and command.client is not None:
        client_payload = create_or_reuse_converted_client(command.client)
        client_id = str(client_payload["client"]["id"])
    linked_client = _validate_campaign_client_link(client_id, command.status)
    funnel_id = command.client.funnel_id if command.client else (linked_client.funnel_id if linked_client else "contadores")

    platform_campaign_id = ""
    if command.stage_platform_campaign and client_id:
        platform_campaign = _stage_platform_ad_campaign(
            command,
            client_id=client_id,
            funnel_id=funnel_id,
        )
        platform_campaign_id = platform_campaign.id

    try:
        campaign = LeadCaptureCampaign.add(
            client_id=client_id,
            platform_ad_campaign_id=platform_campaign_id,
            funnel_id=funnel_id,
            name=command.name,
            status=command.status,
            public_slug=command.public_slug,
            daily_budget_usd=command.daily_budget_usd,
            budget_currency=command.budget_currency,
            location=command.location or "",
            campaign_info=command.campaign_info,
            creative_brief=command.creative_brief or "",
            form_schema=command.form_schema,
            thank_you_title=command.thank_you_title,
            thank_you_body=command.thank_you_body,
            destination_url=command.destination_url or "",
            meta_pixel_id=command.meta_pixel_id or "",
            meta_event_name=command.meta_event_name,
            meta_events_enabled=command.meta_events_enabled,
            meta_test_event_code=command.meta_test_event_code or "",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if not campaign.destination_url:
        campaign = LeadCaptureCampaign.update(campaign.id, destination_url=_public_url(request, campaign)) or campaign
    source = ensure_campaign_delivery_source(campaign)
    if source and campaign.client_lead_source_id != source.id:
        campaign = LeadCaptureCampaign.update(campaign.id, client_lead_source_id=source.id) or campaign

    PlatformEvent.add(
        event_type="lead_capture_campaign.created",
        lifecycle_stage="lead_capture",
        target_type="lead_capture_campaign",
        target_id=campaign.id,
        funnel_id=campaign.funnel_id,
        source="campaign_api",
        actor="operator",
        summary=f"Owned campaign created: {campaign.name}.",
        payload={"public_url": _public_url(request, campaign), "client_id": campaign.client_id},
        idempotency_key=f"lead-capture-campaign-created:{campaign.id}",
    )
    return {"campaign": _campaign_payload(campaign, request=request)}


@campaigns_router.get("/{campaign_id}")
async def get_campaign(request: Request, campaign_id: str) -> dict[str, Any]:
    """Return one owned campaign."""
    return {"campaign": _campaign_payload(_get_campaign_or_404(campaign_id), request=request, include_submissions=True)}


@campaigns_router.patch("/{campaign_id}")
async def patch_campaign(
    request: Request,
    campaign_id: str,
    command: LeadCaptureCampaignPatchCommand,
) -> dict[str, Any]:
    """Patch one owned lead-capture campaign."""
    current = _get_campaign_or_404(campaign_id)
    updates = command.model_dump(exclude_unset=True)
    next_client_id = str(updates.get("client_id", current.client_id) or "").strip()
    next_status = str(updates.get("status", current.status) or "draft").strip().lower()
    linked_client = _validate_campaign_client_link(next_client_id, next_status)
    if "client_id" in updates and linked_client is not None:
        updates["funnel_id"] = linked_client.funnel_id
    try:
        campaign = LeadCaptureCampaign.update(campaign_id, **updates)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    source = ensure_campaign_delivery_source(campaign)
    if source and campaign.client_lead_source_id != source.id:
        campaign = LeadCaptureCampaign.update(campaign.id, client_lead_source_id=source.id) or campaign
    return {"campaign": _campaign_payload(campaign, request=request)}


@campaigns_router.post("/{campaign_id}/delivery-source")
async def refresh_campaign_delivery_source(request: Request, campaign_id: str) -> dict[str, Any]:
    """Create or refresh the Delivery source for one owned campaign."""
    campaign = _get_campaign_or_404(campaign_id)
    source = ensure_campaign_delivery_source(campaign)
    if source is None:
        raise HTTPException(status_code=400, detail="Campaign must be linked to a client with a valid WhatsApp.")
    campaign = LeadCaptureCampaign.get_by_id(campaign.id) or campaign
    return {"campaign": _campaign_payload(campaign, request=request), "source": build_source_response(source).model_dump(mode="json")}


@campaigns_router.get("/{campaign_id}/submissions")
async def list_campaign_submissions(
    campaign_id: str,
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict[str, Any]:
    """List public form submissions for one campaign."""
    campaign = _get_campaign_or_404(campaign_id)
    submissions = LeadCaptureSubmission.list_by_campaign(campaign.id, limit=limit)
    return {
        "campaign_id": campaign.id,
        "count": len(submissions),
        "submissions": [_submission_payload(item) for item in submissions],
    }


@campaigns_router.post("/{campaign_id}/meta/stage")
async def stage_campaign_meta_plan(request: Request, campaign_id: str) -> dict[str, Any]:
    """Stage or link the local PlatformAdCampaign record used before Meta publish."""
    campaign = _get_campaign_or_404(campaign_id)
    if campaign.platform_ad_campaign_id and PlatformAdCampaign.get_by_id(campaign.platform_ad_campaign_id):
        platform_campaign = PlatformAdCampaign.get_by_id(campaign.platform_ad_campaign_id)
    else:
        platform_campaign = PlatformAdCampaign.add(
            client_id=campaign.client_id,
            funnel_id=campaign.funnel_id,
            status="draft",
            objective="lead_capture_form",
            budget_daily_usd=campaign.daily_budget_usd,
            budget_currency=campaign.budget_currency,
            target_segments=[{"type": "location", "value": campaign.location}] if campaign.location else [],
            angles=[campaign.creative_brief] if campaign.creative_brief else [],
            creative_benchmark={"source": "owned_campaign_form", "campaign_info": campaign.campaign_info},
            creative_testing={"destination_url": _public_url(request, campaign), "default_status": "PAUSED"},
            approval_status="not_requested",
            idempotency_key=f"lead-capture:{campaign.id}",
        )
        campaign = LeadCaptureCampaign.update(campaign.id, platform_ad_campaign_id=platform_campaign.id) or campaign
    return {
        "campaign": _campaign_payload(campaign, request=request),
        "platform_ad_campaign": {
            "id": platform_campaign.id if platform_campaign else "",
            "status": platform_campaign.status if platform_campaign else "",
            "approval_status": platform_campaign.approval_status if platform_campaign else "",
            "next_steps": [
                "Use sync_meta_inventory to confirm ad account, pixel, Page, and WhatsApp assets.",
                "Use stage_meta_publish_plan and preflight_meta_publish_plan before any live Meta write.",
                "Start Meta objects PAUSED and execute only after approval plus META_MARKETING_LIVE_WRITES_ENABLED=true.",
            ],
        },
    }


@public_campaigns_router.get("/c/{public_slug}")
async def redirect_public_campaign_form(public_slug: str) -> RedirectResponse:
    """Redirect slashless public campaign URLs to the form root."""
    _get_public_campaign_or_404(public_slug)
    return RedirectResponse(url=f"/c/{public_slug}/", status_code=307)


@public_campaigns_router.get("/c/{public_slug}/")
async def serve_public_campaign_form(request: Request, public_slug: str) -> HTMLResponse:
    """Serve a mobile-first public campaign form."""
    campaign = _get_public_campaign_or_404(public_slug)
    payload = _public_campaign_payload(campaign, request=request)
    return HTMLResponse(render_public_form_html(payload))


@public_campaigns_router.get("/api/public/campaigns/{public_slug}")
async def get_public_campaign(request: Request, public_slug: str) -> dict[str, Any]:
    """Return public form config for one active campaign."""
    return {"campaign": _public_campaign_payload(_get_public_campaign_or_404(public_slug), request=request)}


@public_campaigns_router.post("/api/public/campaigns/{public_slug}/submissions")
async def submit_public_campaign_form(
    request: Request,
    public_slug: str,
    command: PublicSubmissionCommand,
) -> dict[str, Any]:
    """Accept one public campaign form submission and queue Delivery."""
    campaign = _get_public_campaign_or_404(public_slug)
    if command.honeypot:
        return _public_submission_receipt(campaign=campaign, spam=True)

    scoped_idempotency_key = _submission_idempotency_key(campaign, command.idempotency_key)
    duplicate = LeadCaptureSubmission.get_by_idempotency_key(scoped_idempotency_key)
    if duplicate is not None:
        return _public_submission_receipt(campaign=campaign, submission=duplicate, duplicate=True)

    answers = _normalize_submission_answers(campaign, command)
    tracking = _normalize_tracking(command.tracking)
    full_name, phone, email = _submission_contact(command, answers)
    if not full_name:
        raise HTTPException(status_code=400, detail="Name is required.")
    if not normalize_phone(phone):
        raise HTTPException(status_code=400, detail="WhatsApp is invalid.")
    phone_duplicate = LeadCaptureSubmission.get_latest_by_campaign_phone(campaign.id, phone)
    if phone_duplicate is not None:
        return _public_submission_receipt(campaign=campaign, submission=phone_duplicate, duplicate=True)
    try:
        submission = LeadCaptureSubmission.add(
            campaign_id=campaign.id,
            client_id=campaign.client_id,
            idempotency_key=scoped_idempotency_key,
            full_name=full_name,
            phone=phone,
            email=email,
            answers=answers,
            tracking=tracking,
            meta_event_id=f"lead-capture-{campaign.id}-{secrets.token_urlsafe(10)}",
            meta_event_status="pending",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    delivery = _queue_delivery_for_submission(campaign=campaign, submission=submission)
    if delivery is not None:
        submission = LeadCaptureSubmission.update_delivery_and_meta(
            submission.id,
            client_lead_delivery_id=delivery.id,
        ) or submission
    submission = _track_meta_event(request=request, campaign=campaign, submission=submission)

    PlatformEvent.add(
        event_type="lead_capture_submission.created",
        lifecycle_stage="lead_capture",
        target_type="lead_capture_campaign",
        target_id=campaign.id,
        funnel_id=campaign.funnel_id,
        source="public_campaign_form",
        actor="visitor",
        summary=f"New lead captured for {campaign.name}.",
        payload={
            "submission_id": submission.id,
            "client_id": campaign.client_id,
            "delivery_id": delivery.id if delivery else "",
            "delivery_status": (
                delivery.delivery_status.value
                if delivery and hasattr(delivery.delivery_status, "value")
                else (str(delivery.delivery_status) if delivery else "")
            ),
        },
        idempotency_key=f"lead-capture-submission:{submission.id}",
    )
    return _public_submission_receipt(
        campaign=campaign,
        submission=submission,
        delivery_queued=bool(delivery and delivery.delivery_status == ClientLeadDeliveryStatus.PENDING),
    )


def render_public_form_html(campaign: dict[str, Any]) -> str:
    """Render a self-contained public lead form."""
    payload_json = json.dumps(campaign, ensure_ascii=False).replace("</", "<\\/")
    title = escape(str(campaign.get("name") or "Consulta"))
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f5f7f8;
      color: #16201d;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; background: #f5f7f8; }}
    main {{ min-height: 100vh; display: grid; place-items: center; padding: 18px; }}
    .form-shell {{ width: min(100%, 560px); background: #fff; border: 1px solid #dfe7e4; border-radius: 8px; box-shadow: 0 18px 50px rgba(23, 37, 35, .10); overflow: hidden; }}
    .header {{ padding: 22px 20px 14px; border-bottom: 1px solid #e8eeec; }}
    .eyebrow {{ margin: 0 0 8px; font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #4b6d61; }}
    h1 {{ margin: 0; font-size: clamp(24px, 8vw, 38px); line-height: 1.04; letter-spacing: 0; }}
    .progress {{ height: 4px; background: #e8eeec; }}
    .progress > div {{ height: 100%; width: 0%; background: #128262; transition: width .2s ease; }}
    form {{ padding: 22px 20px 20px; }}
    .step {{ display: none; min-height: 260px; }}
    .step.active {{ display: block; }}
    label {{ display: block; font-size: 20px; font-weight: 760; line-height: 1.18; margin: 0 0 14px; }}
    input, textarea, select {{ width: 100%; min-height: 54px; border: 1px solid #c9d7d2; border-radius: 7px; padding: 14px 14px; font: inherit; font-size: 18px; color: #16201d; background: #fff; }}
    textarea {{ min-height: 140px; resize: vertical; }}
    input:focus, textarea:focus, select:focus {{ outline: 3px solid rgba(18, 130, 98, .18); border-color: #128262; }}
    .options {{ display: grid; gap: 10px; }}
    .option {{ min-height: 50px; border: 1px solid #c9d7d2; border-radius: 7px; padding: 13px 14px; font-size: 17px; background: #fff; cursor: pointer; }}
    .option.selected {{ border-color: #128262; background: #eaf6f1; }}
    .actions {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 24px; }}
    button {{ min-height: 46px; border: 0; border-radius: 7px; padding: 0 16px; font: inherit; font-weight: 750; cursor: pointer; }}
    .back {{ background: #ecf1ef; color: #31433d; }}
    .next, .submit {{ background: #128262; color: #fff; }}
    .next:disabled, .submit:disabled {{ opacity: .58; cursor: not-allowed; }}
    .error {{ min-height: 22px; color: #a03722; font-size: 14px; margin-top: 12px; }}
    .thanks {{ display: none; padding: 28px 22px 30px; }}
    .thanks.active {{ display: block; }}
    .thanks h2 {{ margin: 0 0 10px; font-size: 30px; letter-spacing: 0; }}
    .thanks p {{ margin: 0; color: #4f625c; font-size: 17px; line-height: 1.45; }}
    .hidden {{ position: absolute; left: -9999px; width: 1px; height: 1px; opacity: 0; }}
    @media (max-width: 520px) {{
      main {{ padding: 0; place-items: stretch; }}
      .form-shell {{ min-height: 100vh; border: 0; border-radius: 0; box-shadow: none; }}
      form {{ padding: 24px 18px; }}
      .step {{ min-height: calc(100vh - 240px); }}
      .actions {{ position: sticky; bottom: 0; background: #fff; padding-top: 12px; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="form-shell">
      <div class="header">
        <p class="eyebrow">Consulta</p>
        <h1 id="campaignTitle"></h1>
      </div>
      <div class="progress" aria-hidden="true"><div id="progressBar"></div></div>
      <form id="leadForm" novalidate>
        <input class="hidden" autocomplete="off" name="company_website" id="companyWebsite">
        <div id="steps"></div>
        <div class="error" id="error"></div>
        <div class="actions">
          <button type="button" class="back" id="backBtn">Atras</button>
          <button type="button" class="next" id="nextBtn">Siguiente</button>
          <button type="submit" class="submit" id="submitBtn">Enviar</button>
        </div>
      </form>
      <div class="thanks" id="thanks">
        <h2 id="thanksTitle"></h2>
        <p id="thanksBody"></p>
      </div>
    </section>
  </main>
  <script>
    const campaign = {payload_json};
    const fields = campaign.form_schema?.fields || [];
    const state = {{ index: 0, answers: {{}}, idempotencyKey: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) }};
    const stepsEl = document.getElementById("steps");
    const progressBar = document.getElementById("progressBar");
    const backBtn = document.getElementById("backBtn");
    const nextBtn = document.getElementById("nextBtn");
    const submitBtn = document.getElementById("submitBtn");
    const errorEl = document.getElementById("error");
    const htmlEscapes = {{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }};
    document.getElementById("campaignTitle").textContent = campaign.name || "Consulta";

    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, (char) => htmlEscapes[char]);
    }}
    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, "&#96;");
    }}
    function fieldInput(field) {{
      const id = `field-${{field.id}}`;
      const safeId = escapeAttr(id);
      const safePlaceholder = escapeAttr(field.placeholder || "");
      const safeFieldId = escapeAttr(field.id);
      if (field.type === "textarea") return `<textarea id="${{safeId}}" placeholder="${{safePlaceholder}}"></textarea>`;
      if (field.type === "yes_no") return `<div class="options" data-field="${{safeFieldId}}"><button type="button" class="option" data-value="Si">Si</button><button type="button" class="option" data-value="No">No</button></div>`;
      if (field.type === "select" || field.type === "multi_select") {{
        const options = (field.options || []).map((option) => `<button type="button" class="option" data-value="${{escapeAttr(option)}}">${{escapeHtml(option)}}</button>`).join("");
        return `<div class="options" data-field="${{safeFieldId}}" data-multi="${{field.type === "multi_select"}}">${{options}}</div>`;
      }}
      const inputType = field.type === "email" ? "email" : field.type === "phone" ? "tel" : "text";
      const autocomplete = field.type === "email" ? "email" : field.type === "phone" ? "tel" : "name";
      return `<input id="${{safeId}}" type="${{inputType}}" autocomplete="${{autocomplete}}" placeholder="${{safePlaceholder}}">`;
    }}

    function renderSteps() {{
      stepsEl.innerHTML = fields.map((field, idx) => `
        <section class="step" data-index="${{idx}}" data-field="${{escapeAttr(field.id)}}">
          <label for="field-${{escapeAttr(field.id)}}">${{escapeHtml(field.label || field.id)}}${{field.required ? " *" : ""}}</label>
          ${{fieldInput(field)}}
        </section>
      `).join("");
      stepsEl.querySelectorAll(".options").forEach((group) => {{
        group.querySelectorAll(".option").forEach((button) => {{
          button.addEventListener("click", () => {{
            const fieldId = group.dataset.field;
            const multi = group.dataset.multi === "true";
            if (multi) {{
              button.classList.toggle("selected");
              state.answers[fieldId] = Array.from(group.querySelectorAll(".selected")).map((item) => item.dataset.value);
            }} else {{
              group.querySelectorAll(".option").forEach((item) => item.classList.remove("selected"));
              button.classList.add("selected");
              state.answers[fieldId] = button.dataset.value || "";
            }}
          }});
        }});
      }});
    }}

    function currentField() {{ return fields[state.index]; }}
    function currentValue() {{
      const field = currentField();
      if (!field) return "";
      const direct = document.getElementById(`field-${{field.id}}`);
      if (direct) return direct.value.trim();
      const value = state.answers[field.id];
      return Array.isArray(value) ? value.join(", ").trim() : String(value || "").trim();
    }}
    function saveCurrent() {{
      const field = currentField();
      if (!field) return;
      const direct = document.getElementById(`field-${{field.id}}`);
      if (direct) state.answers[field.id] = direct.value.trim();
    }}
    function validCurrent() {{
      const field = currentField();
      if (!field || !field.required) return true;
      return Boolean(currentValue());
    }}
    function showStep() {{
      errorEl.textContent = "";
      document.querySelectorAll(".step").forEach((step) => step.classList.toggle("active", Number(step.dataset.index) === state.index));
      const last = state.index >= fields.length - 1;
      backBtn.style.visibility = state.index === 0 ? "hidden" : "visible";
      nextBtn.style.display = last ? "none" : "inline-flex";
      submitBtn.style.display = last ? "inline-flex" : "none";
      progressBar.style.width = `${{fields.length ? ((state.index + 1) / fields.length) * 100 : 100}}%`;
    }}
    backBtn.addEventListener("click", () => {{ saveCurrent(); state.index = Math.max(0, state.index - 1); showStep(); }});
    nextBtn.addEventListener("click", () => {{
      if (!validCurrent()) {{ errorEl.textContent = "Completa este dato para seguir."; return; }}
      saveCurrent(); state.index = Math.min(fields.length - 1, state.index + 1); showStep();
    }});
    document.getElementById("leadForm").addEventListener("submit", async (event) => {{
      event.preventDefault();
      if (!validCurrent()) {{ errorEl.textContent = "Completa este dato para enviar."; return; }}
      saveCurrent();
      submitBtn.disabled = true;
      errorEl.textContent = "";
      const body = {{
        answers: state.answers,
        idempotency_key: state.idempotencyKey,
        honeypot: document.getElementById("companyWebsite").value,
        tracking: {{
          href: window.location.href,
          referrer: document.referrer,
          fbp: document.cookie.match(/(?:^|; )_fbp=([^;]+)/)?.[1] || "",
          fbc: document.cookie.match(/(?:^|; )_fbc=([^;]+)/)?.[1] || ""
        }}
      }};
      try {{
        const response = await fetch(`/api/public/campaigns/${{campaign.public_slug}}/submissions`, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json", "Accept": "application/json" }},
          body: JSON.stringify(body)
        }});
        if (!response.ok) {{
          const payload = await response.json().catch(() => ({{ detail: "No se pudo enviar." }}));
          throw new Error(payload.detail || "No se pudo enviar.");
        }}
        const payload = await response.json();
        document.getElementById("leadForm").style.display = "none";
        document.getElementById("thanksTitle").textContent = payload.thank_you?.title || campaign.thank_you_title || "Gracias";
        document.getElementById("thanksBody").textContent = payload.thank_you?.body || campaign.thank_you_body || "";
        document.getElementById("thanks").classList.add("active");
        progressBar.style.width = "100%";
      }} catch (error) {{
        submitBtn.disabled = false;
        errorEl.textContent = error.message || "No se pudo enviar.";
      }}
    }});
    renderSteps();
    showStep();
  </script>
</body>
</html>"""
