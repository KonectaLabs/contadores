"""Meta Lead Ads form and webhook endpoints."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.database import ClientLeadSource, PlatformEvent
from backend.endpoints.client_leads import (
    MetaLeadFormFetchCommand,
    fetch_and_import_meta_lead_form_record,
)
from backend.meta_lead_ads import DEFAULT_META_LEAD_FIELDS, MetaLeadAdsCredentialsError, MetaLeadAdsError
from backend.meta_lead_forms import (
    CreateMetaLeadFormArgs,
    MetaLeadFormsError,
    MetaLeadWriteResult,
    SubscribeMetaLeadWebhookArgs,
    create_meta_lead_form,
    subscribe_meta_lead_webhook,
)


meta_leads_router = APIRouter(prefix="/api/meta-leads", tags=["client-leads"])


class MetaLeadWebhookItemResponse(BaseModel):
    """One processed Meta leadgen webhook change."""

    leadgen_id: str
    form_id: str = ""
    source_id: str = ""
    status: str
    detail: str = ""
    imported: int = 0
    updated: int = 0
    queued: int = 0


class MetaLeadWebhookResponse(BaseModel):
    """Webhook ingest summary returned to Meta."""

    status: str = "ok"
    processed: int = 0
    unresolved: int = 0
    failed: int = 0
    items: list[MetaLeadWebhookItemResponse] = Field(default_factory=list)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _webhook_verify_token() -> str:
    return _clean(os.getenv("META_LEAD_WEBHOOK_VERIFY_TOKEN") or os.getenv("META_WEBHOOK_VERIFY_TOKEN"))


def _iter_leadgen_changes(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract leadgen change values from a Meta Page webhook payload."""
    changes: list[dict[str, Any]] = []
    entries = payload.get("entry") if isinstance(payload.get("entry"), list) else []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") if isinstance(entry.get("changes"), list) else []:
            if not isinstance(change, dict) or _clean(change.get("field")) != "leadgen":
                continue
            value = change.get("value") if isinstance(change.get("value"), dict) else {}
            if value:
                changes.append(value)
    return changes


def _source_from_webhook_change(value: dict[str, Any], requested_source_id: str | None) -> ClientLeadSource | None:
    """Resolve which Delivery source should receive one Meta lead."""
    clean_source_id = _clean(requested_source_id)
    if clean_source_id:
        return ClientLeadSource.get_by_id(clean_source_id)

    form_id = _clean(value.get("form_id"))
    if form_id:
        source = ClientLeadSource.get_by_meta_lead_form_id(form_id)
        if source is not None:
            return source

    default_source_id = _clean(os.getenv("META_LEAD_WEBHOOK_DEFAULT_SOURCE_ID"))
    if default_source_id:
        return ClientLeadSource.get_by_id(default_source_id)
    return None


@meta_leads_router.post("/forms", response_model=MetaLeadWriteResult)
async def create_meta_lead_form_endpoint(command: CreateMetaLeadFormArgs) -> MetaLeadWriteResult:
    """Create one Meta Lead Ads instant form."""
    try:
        return create_meta_lead_form(command, source="api", actor="operator")
    except MetaLeadFormsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@meta_leads_router.post("/webhook-subscriptions", response_model=MetaLeadWriteResult)
async def subscribe_meta_lead_webhook_endpoint(command: SubscribeMetaLeadWebhookArgs) -> MetaLeadWriteResult:
    """Subscribe one Page app to Meta leadgen webhooks."""
    try:
        return subscribe_meta_lead_webhook(command, source="api", actor="operator")
    except MetaLeadFormsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@meta_leads_router.get("/webhook")
async def verify_meta_lead_webhook(request: Request) -> PlainTextResponse:
    """Complete Meta webhook verification challenge."""
    expected = _webhook_verify_token()
    if not expected:
        raise HTTPException(status_code=503, detail="META_LEAD_WEBHOOK_VERIFY_TOKEN is not configured.")
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and _clean(params.get("hub.verify_token")) == expected
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Invalid Meta webhook verification token.")


@meta_leads_router.post("/webhook", response_model=MetaLeadWebhookResponse)
async def receive_meta_lead_webhook(
    request: Request,
    source_id: str | None = Query(default=None),
) -> MetaLeadWebhookResponse:
    """Receive Meta leadgen webhooks and import fetched leads into Delivery."""
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON webhook payload.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object.")

    response = MetaLeadWebhookResponse()
    for value in _iter_leadgen_changes(payload):
        leadgen_id = _clean(value.get("leadgen_id"))
        form_id = _clean(value.get("form_id"))
        if not leadgen_id:
            response.unresolved += 1
            response.items.append(
                MetaLeadWebhookItemResponse(
                    leadgen_id="",
                    form_id=form_id,
                    status="unresolved",
                    detail="missing leadgen_id",
                )
            )
            continue

        source = _source_from_webhook_change(value, source_id)
        if source is None:
            response.unresolved += 1
            PlatformEvent.add(
                event_type="client_lead.meta_webhook_unresolved",
                lifecycle_stage="delivery",
                target_type="meta_lead",
                target_id=leadgen_id,
                source="meta_lead_webhook",
                actor="meta",
                summary=f"Could not resolve Delivery source for Meta lead {leadgen_id}.",
                payload={"leadgen_id": leadgen_id, "form_id": form_id, "requested_source_id": source_id},
                idempotency_key=f"meta_lead_webhook_unresolved:{leadgen_id}",
            )
            response.items.append(
                MetaLeadWebhookItemResponse(
                    leadgen_id=leadgen_id,
                    form_id=form_id,
                    status="unresolved",
                    detail="no delivery source matched form_id",
                )
            )
            continue
        if not source.enabled:
            response.failed += 1
            response.items.append(
                MetaLeadWebhookItemResponse(
                    leadgen_id=leadgen_id,
                    form_id=form_id,
                    source_id=source.id,
                    status="failed",
                    detail="delivery source disabled",
                )
            )
            continue

        try:
            result = fetch_and_import_meta_lead_form_record(
                source,
                MetaLeadFormFetchCommand(
                    leadgen_id=leadgen_id,
                    fields=DEFAULT_META_LEAD_FIELDS,
                    reason="Meta leadgen webhook",
                ),
                event_source="meta_lead_webhook",
                actor="meta",
            )
        except MetaLeadAdsCredentialsError as exc:
            response.failed += 1
            detail = f"missing Meta credentials: {', '.join(exc.missing)}"
            PlatformEvent.add(
                event_type="client_lead.meta_webhook_failed",
                lifecycle_stage="delivery",
                target_type="client_lead_source",
                target_id=source.id,
                source="meta_lead_webhook",
                actor="meta",
                summary=f"Could not fetch Meta webhook lead {leadgen_id}: {detail}.",
                payload={"leadgen_id": leadgen_id, "form_id": form_id, "errors": exc.missing},
                idempotency_key=f"meta_lead_webhook_failed:{source.id}:{leadgen_id}",
            )
            response.items.append(
                MetaLeadWebhookItemResponse(
                    leadgen_id=leadgen_id,
                    form_id=form_id,
                    source_id=source.id,
                    status="failed",
                    detail=detail,
                )
            )
        except MetaLeadAdsError as exc:
            response.failed += 1
            PlatformEvent.add(
                event_type="client_lead.meta_webhook_failed",
                lifecycle_stage="delivery",
                target_type="client_lead_source",
                target_id=source.id,
                source="meta_lead_webhook",
                actor="meta",
                summary=f"Could not import Meta webhook lead {leadgen_id}: {exc}.",
                payload={"leadgen_id": leadgen_id, "form_id": form_id, "error": str(exc)},
                idempotency_key=f"meta_lead_webhook_failed:{source.id}:{leadgen_id}",
            )
            response.items.append(
                MetaLeadWebhookItemResponse(
                    leadgen_id=leadgen_id,
                    form_id=form_id,
                    source_id=source.id,
                    status="failed",
                    detail=str(exc),
                )
            )
        else:
            response.processed += 1
            response.items.append(
                MetaLeadWebhookItemResponse(
                    leadgen_id=leadgen_id,
                    form_id=form_id,
                    source_id=source.id,
                    status="imported",
                    imported=result.imported,
                    updated=result.updated,
                    queued=result.queued,
                )
            )
    return response
