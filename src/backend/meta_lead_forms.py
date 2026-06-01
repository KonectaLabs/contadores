"""Meta Lead Ads instant-form write helpers."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field

from backend.database import ClientLeadSource, PlatformEvent


GraphPoster = Callable[[str, dict[str, Any]], dict[str, Any]]


class MetaLeadFormsError(RuntimeError):
    """Raised when a Meta lead form write fails."""


class CreateMetaLeadFormArgs(BaseModel):
    """Arguments for creating one Meta instant form."""

    page_id: str = ""
    name: str = Field(min_length=1, max_length=240)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    privacy_policy_url: str = Field(min_length=1, max_length=2000)
    privacy_policy_link_text: str = Field(default="Politica de privacidad", max_length=240)
    locale: str = "es_LA"
    form_type: str = "MORE_VOLUME"
    follow_up_action_url: str = ""
    thank_you_page: dict[str, Any] = Field(default_factory=dict)
    tracking_parameters: dict[str, Any] = Field(default_factory=dict)
    client_lead_source_id: str = ""
    live_writes_requested: bool = False
    reason: str = Field(default="Created by Codex agent.", max_length=1000)


class SubscribeMetaLeadWebhookArgs(BaseModel):
    """Arguments for subscribing a Page app to Meta leadgen webhooks."""

    page_id: str = ""
    subscribed_fields: list[str] = Field(default_factory=lambda: ["leadgen"])
    live_writes_requested: bool = False
    reason: str = Field(default="Subscribed by Codex agent.", max_length=1000)


class MetaLeadWriteResult(BaseModel):
    """Result for a Meta lead form write operation."""

    status: str
    page_id: str = ""
    lead_form_id: str = ""
    blocked: list[str] = Field(default_factory=list)
    response_payload: dict[str, Any] = Field(default_factory=dict)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _env_truthy(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on"}


def _graph_base_url(api_version: str) -> str:
    version = _clean(api_version).strip("/")
    if not version:
        raise MetaLeadFormsError("META_MARKETING_API_VERSION is required")
    return f"https://graph.facebook.com/{version}"


def _sanitize_provider_payload(value: Any) -> Any:
    """Remove token-like fields before storing provider responses."""
    if isinstance(value, dict):
        return {
            key: _sanitize_provider_payload(item)
            for key, item in value.items()
            if "token" not in str(key).lower() and "secret" not in str(key).lower()
        }
    if isinstance(value, list):
        return [_sanitize_provider_payload(item) for item in value]
    return value


def _redact_graph_error(value: Any) -> str:
    text = str(value)
    text = re.sub(r"(?i)(access_token=)[^&\s'\"<>]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(access_token%3D)[^&\s'\"<>]+", r"\1[redacted]", text)
    return text


def _encode_graph_params(params: dict[str, Any]) -> dict[str, Any]:
    """Encode nested Graph API params as JSON strings for form posts."""
    encoded: dict[str, Any] = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            encoded[key] = json.dumps(value, ensure_ascii=True)
        else:
            encoded[key] = value
    return encoded


def _default_graph_poster(*, api_version: str, access_token: str, timeout: float = 30) -> GraphPoster:
    base_url = _graph_base_url(api_version)

    def graph_post(path: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = _encode_graph_params(params)
        request_params["access_token"] = access_token
        response = httpx.post(f"{base_url}/{path.strip('/')}", data=request_params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return _sanitize_provider_payload(payload if isinstance(payload, dict) else {"data": payload})

    return graph_post


def _write_blockers(*, page_id: str, live_writes_requested: bool, graph_post: GraphPoster | None) -> list[str]:
    blocked: list[str] = []
    if not _clean(page_id):
        blocked.append("page_id")
    if not live_writes_requested:
        blocked.append("live_writes_requested")
    if not _env_truthy("META_MARKETING_LIVE_WRITES_ENABLED"):
        blocked.append("META_MARKETING_LIVE_WRITES_ENABLED")
    if not _clean(os.getenv("META_MARKETING_API_VERSION")):
        blocked.append("META_MARKETING_API_VERSION")
    if graph_post is None and not (
        _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    ):
        blocked.append("META_MARKETING_ACCESS_TOKEN")
    return blocked


def _default_questions() -> list[dict[str, Any]]:
    return [
        {"type": "FULL_NAME"},
        {"type": "PHONE"},
        {"type": "EMAIL"},
    ]


def create_meta_lead_form(
    args: CreateMetaLeadFormArgs,
    *,
    graph_post: GraphPoster | None = None,
    source: str = "codex_agent_tool",
    actor: str = "agent",
) -> MetaLeadWriteResult:
    """Create a Meta Lead Ads instant form through the Graph API."""
    page_id = _clean(args.page_id or os.getenv("META_PAGE_ID"))
    blocked = _write_blockers(
        page_id=page_id,
        live_writes_requested=args.live_writes_requested,
        graph_post=graph_post,
    )
    if blocked:
        result = MetaLeadWriteResult(status="blocked", page_id=page_id, blocked=blocked)
        PlatformEvent.add(
            event_type="meta_lead.form_create_blocked",
            lifecycle_stage="meta_publish",
            target_type="meta_page",
            target_id=page_id or "unknown",
            source=source,
            actor=actor,
            summary=f"Blocked Meta lead form create: {', '.join(blocked)}.",
            payload={"blocked": blocked, "reason": args.reason},
        )
        return result

    params: dict[str, Any] = {
        "name": _clean(args.name),
        "questions": args.questions or _default_questions(),
        "privacy_policy": {
            "url": _clean(args.privacy_policy_url),
            "link_text": _clean(args.privacy_policy_link_text) or "Politica de privacidad",
        },
        "locale": _clean(args.locale) or "es_LA",
        "form_type": _clean(args.form_type) or "MORE_VOLUME",
    }
    if _clean(args.follow_up_action_url):
        params["follow_up_action_url"] = _clean(args.follow_up_action_url)
    if args.thank_you_page:
        params["thank_you_page"] = args.thank_you_page
    if args.tracking_parameters:
        params["tracking_parameters"] = args.tracking_parameters

    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    poster = graph_post or _default_graph_poster(api_version=api_version, access_token=access_token)
    try:
        response_payload = poster(f"{page_id}/leadgen_forms", params)
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:500] if error.response is not None else str(error)
        raise MetaLeadFormsError(f"Meta lead form create failed: {_redact_graph_error(detail)}") from error
    except httpx.HTTPError as error:
        raise MetaLeadFormsError(f"Meta lead form create failed: {_redact_graph_error(error)}") from error

    lead_form_id = _clean(response_payload.get("id") or response_payload.get("leadgen_form_id"))
    result = MetaLeadWriteResult(
        status="created",
        page_id=page_id,
        lead_form_id=lead_form_id,
        response_payload=_sanitize_provider_payload(response_payload),
    )
    client_lead_source_id = _clean(args.client_lead_source_id)
    if client_lead_source_id and lead_form_id:
        source_row = ClientLeadSource.get_by_id(client_lead_source_id)
        if source_row is not None:
            ClientLeadSource.upsert(
                source_id=source_row.id,
                label=source_row.label,
                enabled=source_row.enabled,
                sheet_url=source_row.sheet_url,
                sheet_gid=source_row.sheet_gid,
                sheet_tab_name=source_row.sheet_tab_name,
                meta_page_id=page_id,
                meta_lead_form_id=lead_form_id,
                sheet_poll_seconds=source_row.sheet_poll_seconds,
                recipient_name=source_row.recipient_name,
                recipient_phone=source_row.recipient_phone,
                template_name=source_row.template_name,
                template_language=source_row.template_language,
                column_mapping=source_row.column_mapping,
                context_field_mapping=source_row.context_field_mapping,
            )
    PlatformEvent.add(
        event_type="meta_lead.form_created",
        lifecycle_stage="meta_publish",
        target_type="meta_page",
        target_id=page_id,
        source=source,
        actor=actor,
        summary=f"Created Meta lead form {lead_form_id or 'unknown'} on page {page_id}.",
        payload={
            "reason": args.reason,
            "name": args.name,
            "lead_form_id": lead_form_id,
            "client_lead_source_id": client_lead_source_id,
            "response": result.response_payload,
        },
        idempotency_key=f"meta_lead_form_created:{page_id}:{lead_form_id or args.name}",
    )
    return result


def subscribe_meta_lead_webhook(
    args: SubscribeMetaLeadWebhookArgs,
    *,
    graph_post: GraphPoster | None = None,
    source: str = "codex_agent_tool",
    actor: str = "agent",
) -> MetaLeadWriteResult:
    """Subscribe the app installed on a Page to leadgen webhooks."""
    page_id = _clean(args.page_id or os.getenv("META_PAGE_ID"))
    blocked = _write_blockers(
        page_id=page_id,
        live_writes_requested=args.live_writes_requested,
        graph_post=graph_post,
    )
    if blocked:
        result = MetaLeadWriteResult(status="blocked", page_id=page_id, blocked=blocked)
        PlatformEvent.add(
            event_type="meta_lead.webhook_subscribe_blocked",
            lifecycle_stage="meta_publish",
            target_type="meta_page",
            target_id=page_id or "unknown",
            source=source,
            actor=actor,
            summary=f"Blocked Meta lead webhook subscription: {', '.join(blocked)}.",
            payload={"blocked": blocked, "reason": args.reason},
        )
        return result

    fields = [_clean(field) for field in args.subscribed_fields if _clean(field)]
    if not fields:
        fields = ["leadgen"]
    params = {"subscribed_fields": ",".join(fields)}
    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    poster = graph_post or _default_graph_poster(api_version=api_version, access_token=access_token)
    try:
        response_payload = poster(f"{page_id}/subscribed_apps", params)
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:500] if error.response is not None else str(error)
        raise MetaLeadFormsError(f"Meta lead webhook subscription failed: {_redact_graph_error(detail)}") from error
    except httpx.HTTPError as error:
        raise MetaLeadFormsError(f"Meta lead webhook subscription failed: {_redact_graph_error(error)}") from error

    result = MetaLeadWriteResult(
        status="subscribed",
        page_id=page_id,
        response_payload=_sanitize_provider_payload(response_payload),
    )
    PlatformEvent.add(
        event_type="meta_lead.webhook_subscribed",
        lifecycle_stage="meta_publish",
        target_type="meta_page",
        target_id=page_id,
        source=source,
        actor=actor,
        summary=f"Subscribed page {page_id} to Meta lead webhooks.",
        payload={"reason": args.reason, "fields": fields, "response": result.response_payload},
        idempotency_key=f"meta_lead_webhook_subscribed:{page_id}:{','.join(fields)}",
    )
    return result
