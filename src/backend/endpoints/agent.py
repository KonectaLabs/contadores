"""Agent-ready HTTP API for CRM and tool operations."""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.ai.codex_agent_tools import call_tool, tool_specs
from backend.auth import cli_login_manager, auth_manager
from backend.database import (
    AgentRun,
    AgentToolCall,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    LeadCaptureCampaign,
    LeadCaptureSubmission,
    PlatformMetaInventorySnapshot,
    WorkstationClient,
    engine,
    normalize_contadores_tags,
    normalize_phone,
)
from backend.meta_ads_inventory import sync_meta_inventory
from backend.endpoints.campaigns import (
    CampaignMetaPlanDuplicateCommand,
    CampaignMetaPlanGraphCommand,
    CampaignMetaPlanStageCommand,
    ConvertedClientCommand,
    LeadCaptureCampaignCommand,
    LeadCaptureCampaignPatchCommand,
    _campaign_payload,
    _client_payload,
    _submission_payload,
    create_campaign as create_owned_campaign,
    create_or_reuse_converted_client,
    duplicate_campaign_meta_plan_node as duplicate_owned_campaign_meta_plan_node,
    get_campaign_meta_plan_graph as get_owned_campaign_meta_plan_graph,
    refresh_campaign_delivery_source as refresh_owned_campaign_delivery_source,
    search_campaign_geo as search_owned_campaign_geo,
    set_campaign_meta_plan_graph as set_owned_campaign_meta_plan_graph,
    stage_campaign_meta_plan_graph as stage_owned_campaign_meta_plan_graph,
)
from backend.endpoints.contadores import (
    CANONICAL_CONVERTED_PIPELINE_STAGE,
    VALID_LEAD_ATTENTION_STATES,
    VALID_LEAD_PIPELINE_STAGES,
    VALID_LEAD_QUEUE_STATES,
    VALID_LEAD_TERMINAL_STATES,
    build_config_response,
    build_lead_summary,
    build_message_response,
    derive_effective_lead_stage,
    derive_lead_attention_state,
    derive_lead_pipeline_stage,
    derive_lead_queue_state,
    derive_lead_terminal_state,
    derive_manual_reply_status,
    format_timestamp_seconds,
    get_effective_funnel_config,
    group_strategy_assignments_by_lead,
    lead_matches_search_query,
    lead_matches_tag_filter,
    now_utc,
    resolve_stage_before_closing,
    run_quick_action_for_lead,
    sort_leads_by_last_interaction,
)


agent_router = APIRouter(prefix="/api/agent", tags=["agent"])

LOCAL_CALLBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
MANUAL_REPLY_STATUSES = {"needs_reply", "answered"}

QUEUE_FILTERS: dict[str, dict[str, str]] = {
    "needs-attention": {"attention_state": "needs_reply"},
    "operator": {"queue_state": "operator"},
    "automation": {"queue_state": "automation"},
    "paused": {"attention_state": "paused"},
    "workstation": {"queue_state": "workstation"},
    "converted": {"pipeline_stage": CANONICAL_CONVERTED_PIPELINE_STAGE},
    "closed": {"terminal_state": "closed"},
    "archived": {"terminal_state": "archived"},
    "all-open": {"terminal_state": "open"},
    "failed-delivery": {"delivery_state": "failed"},
}

QUICK_ACTIONS = [
    "offer-solo-page-promo",
    "send-opener",
    "send-manual-ping",
    "mark-converted",
    "manual-handoff",
    "pause-automation",
    "send-loom",
    "send-video-check",
    "send-page-example-video",
    "send-accountant-page-example-video",
    "send-lawyer-page-example-video",
    "send-calendly",
    "send-calendly-link",
    "mark-answered",
    "close",
    "reopen",
    "archive",
    "unarchive",
]

META_REQUIRED_PERMISSIONS = [
    "ads_read",
    "ads_management",
    "business_management",
    "whatsapp_business_management",
    "whatsapp_business_messaging",
]
META_NATIVE_LEAD_FORM_PERMISSIONS = ["leads_retrieval", "pages_manage_ads"]


class CliExchangeCommand(BaseModel):
    """One-time code exchange payload."""

    code: str = Field(min_length=1)


class AgentRunCreateCommand(BaseModel):
    """Create or reuse an audited agent run."""

    run_id: str | None = Field(default=None, max_length=160)
    agent_kind: str = Field(default="agent_api", max_length=80)
    target_type: str = Field(default="platform", max_length=80)
    target_id: str = Field(default="platform", max_length=240)
    prompt_version: str = Field(default="agent-api", max_length=160)
    context_path: str = Field(default="", max_length=1000)


class AgentToolCallCommand(BaseModel):
    """Request body for one audited tool call."""

    arguments: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    idempotency_key: str | None = Field(default=None, max_length=240)


class AgentSendMessageCommand(BaseModel):
    """Queue one outbound CRM message through the existing WhatsApp guards."""

    text: str = Field(min_length=1, max_length=4000)
    sequence_step: str = Field(default="agent_api_manual", max_length=120)
    dispatch_after_minutes: int = Field(default=0, ge=0, le=60 * 24 * 30)
    run_id: str | None = Field(default=None, max_length=160)
    dry_run: bool = False
    idempotency_key: str | None = Field(default=None, max_length=240)


class AgentLeadActionCommand(BaseModel):
    """Run one existing CRM quick action."""

    action: str = Field(min_length=1, max_length=120)
    run_id: str | None = Field(default=None, max_length=160)
    dry_run: bool = False


class AgentLeadNoteCommand(BaseModel):
    """Append one durable agent note for a lead."""

    text: str = Field(min_length=1, max_length=8000)
    title: str = Field(default="", max_length=160)
    importance: Literal["low", "normal", "high"] = "normal"
    run_id: str | None = Field(default=None, max_length=160)
    dry_run: bool = False


class AgentFollowupCommand(BaseModel):
    """Schedule one future agent wake-up."""

    minutes: int = Field(ge=1, le=60 * 24 * 30)
    instruction: str = Field(min_length=1, max_length=4000)
    reason: str = Field(default="agent_api_followup", max_length=1000)
    run_id: str | None = Field(default=None, max_length=160)
    dry_run: bool = False
    idempotency_key: str | None = Field(default=None, max_length=240)


class AgentConversationPatchCommand(BaseModel):
    """Update lead state through audited CRM lifecycle helpers."""

    stage: str | None = Field(default=None, max_length=80)
    classification_label: str | None = Field(default=None, max_length=160)
    classification_reason: str | None = Field(default=None, max_length=2000)
    manual_reply_status: Literal["needs_reply", "answered"] | None = None
    automation_paused: bool | None = None
    automation_paused_reason: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None
    run_id: str | None = Field(default=None, max_length=160)
    dry_run: bool = False


class AgentTagsCommand(BaseModel):
    """Replace or append lead tags through the audited tool layer."""

    tags: list[str] = Field(default_factory=list, min_length=1, max_length=20)
    mode: Literal["set", "append"] = "set"
    run_id: str | None = Field(default=None, max_length=160)
    dry_run: bool = False


class AgentConvertedClientCommand(ConvertedClientCommand):
    """Agent wrapper for manual converted-client creation."""

    dry_run: bool = False


class AgentCampaignCreateCommand(LeadCaptureCampaignCommand):
    """Agent wrapper for owned campaign creation."""

    dry_run: bool = False


class AgentCampaignPatchCommand(LeadCaptureCampaignPatchCommand):
    """Agent wrapper for owned campaign patching."""

    dry_run: bool = False


class AgentMetaInventorySyncCommand(BaseModel):
    """Read Meta inventory through configured Marketing API credentials."""

    ad_account_id: str = ""
    business_id: str = ""
    page_ids: list[str] = Field(default_factory=list)
    include_campaigns: bool = True
    include_lead_forms: bool = True
    include_pixels: bool = True
    include_whatsapp: bool = True
    limit: int = Field(default=50, ge=1, le=200)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_object(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _dump_model(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else dict(value)


def _current_user(request: Request) -> str:
    return str(getattr(request.state, "authenticated_user", "") or "auth-disabled")


def _auth_source(request: Request) -> str:
    return str(getattr(request.state, "auth_source", "") or "disabled")


def _tool_manifest() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "schema": spec.schema,
        }
        for spec in tool_specs()
    ]


def _allowed_tool_names() -> set[str]:
    return {item["name"] for item in _tool_manifest()}


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_list(*names: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for name in names:
        for raw_item in os.getenv(name, "").replace("\n", ",").split(","):
            clean_item = raw_item.strip()
            if clean_item and clean_item not in seen:
                values.append(clean_item)
                seen.add(clean_item)
    return values


def _inventory_counts(inventory: dict[str, Any]) -> dict[str, int]:
    return {key: len(value) for key, value in inventory.items() if isinstance(value, list)}


def _meta_inventory_snapshot_payload(snapshot: PlatformMetaInventorySnapshot | None) -> dict[str, Any] | None:
    if snapshot is None:
        return None
    inventory = snapshot.inventory()
    return {
        "id": snapshot.id,
        "status": snapshot.status,
        "source": snapshot.source,
        "actor": snapshot.actor,
        "ad_account_id": snapshot.ad_account_id,
        "business_id": snapshot.business_id,
        "api_version": snapshot.api_version,
        "created_at": format_timestamp_seconds(snapshot.created_at),
        "inventory_counts": _inventory_counts(inventory),
        "inventory": inventory,
        "errors": snapshot.errors(),
    }


def _meta_readiness_payload() -> dict[str, Any]:
    latest_snapshot = next(iter(PlatformMetaInventorySnapshot.list_recent(limit=1)), None)
    return {
        "configured": {
            "api_version": os.getenv("META_MARKETING_API_VERSION", "").strip(),
            "credentials_present": bool(
                os.getenv("META_MARKETING_ACCESS_TOKEN", "").strip()
                or os.getenv("META_ACCESS_TOKEN", "").strip()
            ),
            "ad_account_id": os.getenv("META_AD_ACCOUNT_ID", "").strip(),
            "business_id": os.getenv("META_BUSINESS_ID", "").strip(),
            "page_ids": _env_list("META_PAGE_IDS", "META_PAGE_ID"),
            "whatsapp_business_account_ids": _env_list(
                "META_WHATSAPP_BUSINESS_ACCOUNT_IDS",
                "META_WHATSAPP_BUSINESS_ACCOUNT_ID",
            ),
            "whatsapp_phone_number_ids": _env_list(
                "META_WHATSAPP_PHONE_NUMBER_IDS",
                "META_WHATSAPP_PHONE_NUMBER_ID",
            ),
            "live_writes_enabled": _env_truthy("META_MARKETING_LIVE_WRITES_ENABLED"),
        },
        "required_permissions": {
            "ads_whatsapp_inventory": META_REQUIRED_PERMISSIONS,
            "native_lead_forms": META_NATIVE_LEAD_FORM_PERMISSIONS,
        },
        "safe_defaults": {
            "owned_campaign_forms_require_meta_lead_forms": False,
            "inventory_sync_is_read_only": True,
            "live_writes_require_meta_marketing_live_writes_enabled": True,
        },
        "latest_snapshot": _meta_inventory_snapshot_payload(latest_snapshot),
    }


def _serialize_run(run: AgentRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "agent_kind": run.agent_kind,
        "target_type": run.target_type,
        "target_id": run.target_id,
        "status": run.status,
        "prompt_version": run.prompt_version,
        "context_path": run.context_path,
        "codex_thread_id": run.codex_thread_id,
        "codex_turn_id": run.codex_turn_id,
        "final_response": run.final_response,
        "error": run.error,
        "started_at": format_timestamp_seconds(run.started_at),
        "finished_at": format_timestamp_seconds(run.finished_at),
        "created_at": format_timestamp_seconds(run.created_at),
    }


def _serialize_tool_call(call: AgentToolCall) -> dict[str, Any]:
    return {
        "id": call.id,
        "run_id": call.run_id,
        "tool_name": call.tool_name,
        "target_type": call.target_type,
        "target_id": call.target_id,
        "status": call.status,
        "arguments": _json_object(call.arguments_json),
        "result": _json_object(call.result_json),
        "idempotency_key": call.idempotency_key,
        "error": call.error,
        "created_at": format_timestamp_seconds(call.created_at),
    }


def _serialize_lead(
    lead: ContadoresLead,
    *,
    assignments_cache: dict[str, dict[str, list[Any]]] | None = None,
) -> dict[str, Any]:
    config = get_effective_funnel_config(lead.funnel_id)
    assignments: list[Any] = []
    if assignments_cache is not None:
        funnel_assignments = assignments_cache.setdefault(
            lead.funnel_id,
            group_strategy_assignments_by_lead(lead.funnel_id),
        )
        assignments = funnel_assignments.get(lead.id, [])
    return _dump_model(
        build_lead_summary(
            lead,
            config=config,
            strategy_assignments=assignments,
        )
    )


def _serialize_message(message: ContadoresMessage) -> dict[str, Any]:
    return _dump_model(build_message_response(message))


def _conversation_payload(
    lead: ContadoresLead,
    *,
    messages_per_lead: int = 5,
    assignments_cache: dict[str, dict[str, list[Any]]] | None = None,
) -> dict[str, Any]:
    messages = ContadoresMessage.list_by_lead(lead.id)
    recent_messages = messages[-max(0, messages_per_lead):] if messages_per_lead else []
    return {
        "lead": _serialize_lead(lead, assignments_cache=assignments_cache),
        "recent_messages": [_serialize_message(item) for item in recent_messages],
    }


def _local_callback_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme != "http" or not parsed.netloc:
        raise HTTPException(status_code=400, detail="callback_url must be an http localhost URL.")
    if (parsed.hostname or "") not in LOCAL_CALLBACK_HOSTS:
        raise HTTPException(status_code=400, detail="callback_url host must be localhost, 127.0.0.1, or ::1.")
    return raw_url


def _append_query(raw_url: str, params: dict[str, str]) -> str:
    parsed = urlparse(raw_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend(params.items())
    return urlunparse(parsed._replace(query=urlencode(query)))


def _normalized_queue_name(queue_name: str) -> str:
    return (queue_name or "").strip().lower().replace("_", "-")


def _validate_filter(name: str, value: str | None, allowed: set[str]) -> str | None:
    clean_value = (value or "").strip().lower() or None
    if clean_value is not None and clean_value not in allowed:
        raise HTTPException(status_code=400, detail=f"Invalid {name}.")
    return clean_value


def _lead_outbound_error_count(lead: ContadoresLead) -> int:
    return ContadoresMessage.count_delivery_issues_by_lead(lead.id)


def _lead_matches_agent_filters(
    lead: ContadoresLead,
    *,
    queue_state: str | None,
    attention_state: str | None,
    manual_reply_status: str | None,
    pipeline_stage: str | None,
    terminal_state: str | None,
    tag: str | None,
    query: str | None,
    include_archived: bool,
    delivery_state: str | None,
) -> bool:
    if not lead_matches_tag_filter(lead, tag):
        return False
    if not lead_matches_search_query(lead, query):
        return False

    effective_stage = derive_effective_lead_stage(lead)
    lead_manual_reply_status = derive_manual_reply_status(lead, effective_stage=effective_stage)
    lead_pipeline_stage = derive_lead_pipeline_stage(lead, effective_stage=effective_stage)
    lead_queue_state = derive_lead_queue_state(
        lead,
        effective_stage=effective_stage,
        manual_reply_status=lead_manual_reply_status,
    )
    lead_terminal_state = derive_lead_terminal_state(lead, effective_stage=effective_stage)
    lead_attention_state = derive_lead_attention_state(
        lead,
        effective_stage=effective_stage,
        manual_reply_status=lead_manual_reply_status,
    )

    if not include_archived and lead_terminal_state == "archived":
        return False
    if queue_state is not None and lead_queue_state != queue_state:
        return False
    if attention_state is not None and lead_attention_state != attention_state:
        return False
    if manual_reply_status is not None and lead_manual_reply_status != manual_reply_status:
        return False
    if pipeline_stage is not None and lead_pipeline_stage != pipeline_stage:
        return False
    if terminal_state is not None and lead_terminal_state != terminal_state:
        return False
    if delivery_state == "failed" and _lead_outbound_error_count(lead) <= 0:
        return False
    return True


def _list_filtered_leads(
    *,
    funnel_id: str | None = None,
    queue_state: str | None = None,
    attention_state: str | None = None,
    manual_reply_status: str | None = None,
    pipeline_stage: str | None = None,
    terminal_state: str | None = None,
    tag: str | None = None,
    platform: str | None = None,
    query: str | None = None,
    limit: int = 100,
    include_archived: bool = False,
    delivery_state: str | None = None,
) -> list[ContadoresLead]:
    normalized_queue_state = _validate_filter("queue_state", queue_state, VALID_LEAD_QUEUE_STATES)
    normalized_attention_state = _validate_filter("attention_state", attention_state, VALID_LEAD_ATTENTION_STATES)
    normalized_pipeline_stage = _validate_filter("pipeline_stage", pipeline_stage, VALID_LEAD_PIPELINE_STAGES)
    normalized_terminal_state = _validate_filter("terminal_state", terminal_state, VALID_LEAD_TERMINAL_STATES)
    normalized_manual_reply_status = _validate_filter(
        "manual_reply_status",
        manual_reply_status,
        MANUAL_REPLY_STATUSES,
    )
    normalized_delivery_state = _validate_filter("delivery_state", delivery_state, {"failed"})
    base_leads = ContadoresLead.list_recent(
        limit=5000,
        funnel_id=(funnel_id or "").strip() or None,
        platform=(platform or "").strip() or None,
        include_archived=True,
    )
    visible = [
        lead
        for lead in base_leads
        if _lead_matches_agent_filters(
            lead,
            queue_state=normalized_queue_state,
            attention_state=normalized_attention_state,
            manual_reply_status=normalized_manual_reply_status,
            pipeline_stage=normalized_pipeline_stage,
            terminal_state=normalized_terminal_state,
            tag=tag,
            query=query,
            include_archived=include_archived,
            delivery_state=normalized_delivery_state,
        )
    ]
    return sort_leads_by_last_interaction(visible)[: max(1, min(limit, 1000))]


def _conversation_list_payload(
    *,
    funnel_id: str | None = None,
    queue_state: str | None = None,
    attention_state: str | None = None,
    manual_reply_status: str | None = None,
    pipeline_stage: str | None = None,
    terminal_state: str | None = None,
    tag: str | None = None,
    platform: str | None = None,
    query: str | None = None,
    limit: int = 100,
    messages_per_lead: int = 5,
    include_archived: bool = False,
    delivery_state: str | None = None,
) -> dict[str, Any]:
    leads = _list_filtered_leads(
        funnel_id=funnel_id,
        queue_state=queue_state,
        attention_state=attention_state,
        manual_reply_status=manual_reply_status,
        pipeline_stage=pipeline_stage,
        terminal_state=terminal_state,
        tag=tag,
        platform=platform,
        query=query,
        limit=limit,
        include_archived=include_archived,
        delivery_state=delivery_state,
    )
    assignments_cache: dict[str, dict[str, list[Any]]] = {}
    return {
        "generated_at": _utcnow_iso(),
        "count": len(leads),
        "filters": {
            "funnel_id": funnel_id,
            "queue_state": queue_state,
            "attention_state": attention_state,
            "manual_reply_status": manual_reply_status,
            "pipeline_stage": pipeline_stage,
            "terminal_state": terminal_state,
            "tag": tag,
            "platform": platform,
            "query": query,
            "limit": limit,
            "messages_per_lead": messages_per_lead,
            "include_archived": include_archived,
            "delivery_state": delivery_state,
        },
        "conversations": [
            _conversation_payload(
                lead,
                messages_per_lead=max(0, min(messages_per_lead, 50)),
                assignments_cache=assignments_cache,
            )
            for lead in leads
        ],
    }


def _new_run_id(prefix: str = "agent-api") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _ensure_run(
    run_id: str | None,
    *,
    target_type: str,
    target_id: str,
    agent_kind: str = "agent_api",
) -> str:
    clean_run_id = (run_id or "").strip() or _new_run_id()
    AgentRun.ensure(
        run_id=clean_run_id,
        agent_kind=agent_kind,
        target_type=target_type,
        target_id=target_id,
        prompt_version="agent-api",
    )
    return clean_run_id


def _idempotent_tool_call(
    *,
    idempotency_key: str | None,
    tool_name: str | None = None,
) -> AgentToolCall | None:
    clean_key = (idempotency_key or "").strip()
    if not clean_key:
        return None
    with Session(engine) as session:
        statement = select(AgentToolCall).where(
            AgentToolCall.idempotency_key == clean_key,
            AgentToolCall.status == "succeeded",
        )
        if tool_name:
            statement = statement.where(AgentToolCall.tool_name == tool_name)
        statement = statement.order_by(AgentToolCall.created_at.desc(), AgentToolCall.id.desc()).limit(1)
        row = session.exec(statement).first()
        if row is not None:
            session.expunge(row)
        return row


def _call_tool_or_raise(
    *,
    run_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    clean_tool_name = (tool_name or "").strip()
    if clean_tool_name not in _allowed_tool_names():
        raise HTTPException(status_code=404, detail=f"Unknown or disallowed tool: {clean_tool_name}")
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "tool": clean_tool_name,
            "arguments": arguments,
        }

    duplicate = _idempotent_tool_call(
        idempotency_key=str(arguments.get("idempotency_key") or ""),
        tool_name=clean_tool_name,
    )
    if duplicate is not None:
        return {
            "ok": True,
            "duplicate": True,
            "tool": clean_tool_name,
            "tool_call": _serialize_tool_call(duplicate),
            "result": _json_object(duplicate.result_json),
        }

    payload = call_tool(run_id=run_id, tool_name=clean_tool_name, arguments=arguments)
    if not payload.get("ok"):
        raise HTTPException(status_code=400, detail=payload)
    return payload


def _audit_custom_operation(
    *,
    run_id: str,
    tool_name: str,
    lead_id: str,
    arguments: dict[str, Any],
    operation: Any,
) -> dict[str, Any]:
    AgentRun.ensure(
        run_id=run_id,
        agent_kind="agent_api",
        target_type="lead",
        target_id=lead_id,
        prompt_version="agent-api",
    )
    try:
        result = operation()
    except HTTPException as error:
        payload = {"ok": False, "error": error.detail}
        AgentToolCall.add(
            run_id=run_id,
            tool_name=tool_name,
            arguments=arguments,
            result=payload,
            status="failed",
            target_type="lead",
            target_id=lead_id,
            error=str(error.detail),
        )
        raise
    except Exception as error:
        payload = {"ok": False, "error": str(error)}
        AgentToolCall.add(
            run_id=run_id,
            tool_name=tool_name,
            arguments=arguments,
            result=payload,
            status="failed",
            target_type="lead",
            target_id=lead_id,
            error=f"{error.__class__.__name__}: {error}",
        )
        raise HTTPException(status_code=400, detail=payload) from error

    AgentToolCall.add(
        run_id=run_id,
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        status="succeeded",
        target_type="lead",
        target_id=lead_id,
    )
    return {"ok": True, "tool": tool_name, "result": result}


def _lead_or_404(lead_id: str) -> ContadoresLead:
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@agent_router.get("/auth/cli/start")
async def start_cli_login(
    request: Request,
    callback_url: str = Query(min_length=1),
    state: str = Query(min_length=8),
) -> RedirectResponse:
    """Create a one-time CLI login code from an authenticated browser session."""
    if _auth_source(request) != "browser-session":
        raise HTTPException(status_code=401, detail="CLI login must start from a browser session.")
    callback = _local_callback_url(callback_url)
    ticket = cli_login_manager.create_code(_current_user(request))
    return RedirectResponse(
        url=_append_query(callback, {"code": str(ticket["code"]), "state": state}),
        status_code=303,
    )


@agent_router.post("/auth/cli/exchange")
async def exchange_cli_code(command: CliExchangeCommand) -> dict[str, Any]:
    """Exchange one short-lived CLI login code for a signed session token."""
    payload = cli_login_manager.exchange_code(command.code)
    if payload is None:
        raise HTTPException(status_code=400, detail="Invalid or expired CLI login code.")
    return payload


@agent_router.post("/auth/logout")
async def logout_agent_session(request: Request) -> dict[str, Any]:
    """Revoke the current bearer session token."""
    authorization = request.headers.get("Authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer":
        auth_manager.revoke_session(token.strip())
    return {"authenticated": False}


@agent_router.get("/me")
async def get_agent_me(request: Request) -> dict[str, Any]:
    """Return current agent API identity."""
    return {
        "authenticated": True,
        "user": _current_user(request),
        "auth_source": _auth_source(request),
        "api": "contadores-agent",
        "version": "1",
    }


@agent_router.get("/capabilities")
async def get_agent_capabilities() -> dict[str, Any]:
    """Return a compact map of agent-friendly API capabilities."""
    return {
        "api": "contadores-agent",
        "version": "1",
        "queues": sorted(QUEUE_FILTERS),
        "filters": [
            "funnel_id",
            "queue_state",
            "attention_state",
            "manual_reply_status",
            "pipeline_stage",
            "terminal_state",
            "tag",
            "platform",
            "query",
            "limit",
            "messages_per_lead",
            "include_archived",
        ],
        "quick_actions": QUICK_ACTIONS,
        "campaigns": {
            "endpoints": [
                "GET /api/agent/clients",
                "POST /api/agent/clients/converted",
                "GET /api/agent/campaigns",
                "POST /api/agent/campaigns",
                "GET /api/agent/campaigns/{campaign_id}",
                "PATCH /api/agent/campaigns/{campaign_id}",
                "GET /api/agent/campaigns/{campaign_id}/graph",
                "PUT /api/agent/campaigns/{campaign_id}/graph",
                "POST /api/agent/campaigns/{campaign_id}/graph/duplicate",
                "POST /api/agent/campaigns/{campaign_id}/meta-plan/stage",
                "GET /api/agent/campaigns/{campaign_id}/submissions",
                "POST /api/agent/campaigns/{campaign_id}/delivery-source",
            ],
            "public_form": "/c/{public_slug}/",
        },
        "meta": {
            "endpoints": [
                "GET /api/agent/meta/readiness",
                "POST /api/agent/meta/inventory/sync",
            ],
            "required_permissions": {
                "ads_whatsapp_inventory": META_REQUIRED_PERMISSIONS,
                "native_lead_forms": META_NATIVE_LEAD_FORM_PERMISSIONS,
            },
            "live_writes_gated_by": "META_MARKETING_LIVE_WRITES_ENABLED",
        },
        "mutations": {
            "dry_run": True,
            "idempotency_key": True,
            "audited_tables": ["agent_runs", "agent_tool_calls", "platform_events"],
        },
    }


@agent_router.get("/tools")
async def list_agent_tools() -> dict[str, Any]:
    """List audited product tools exposed to agents."""
    tools = _tool_manifest()
    return {"count": len(tools), "tools": tools}


@agent_router.get("/clients")
async def list_agent_clients(
    query: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """List converted clients available for owned campaigns."""
    clean_query = (query or "").strip().lower()
    clients = []
    for client in WorkstationClient.list_recent(limit=limit):
        payload = _client_payload(client)
        if clean_query and clean_query not in json.dumps(payload, ensure_ascii=False).lower():
            continue
        clients.append(payload)
    return {"count": len(clients), "clients": clients}


@agent_router.post("/clients/converted")
async def create_agent_converted_client(command: AgentConvertedClientCommand) -> dict[str, Any]:
    """Create or reuse a converted client from minimal contact data."""
    if command.dry_run:
        normalized_phone = normalize_phone(command.whatsapp)
        return {
            "ok": True,
            "dry_run": True,
            "would_create_or_reuse": True,
            "normalized_phone": normalized_phone,
            "client": command.model_dump(exclude={"dry_run"}, mode="json"),
        }
    return create_or_reuse_converted_client(command)


@agent_router.get("/campaigns")
async def list_agent_campaigns(
    request: Request,
    client_id: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """List owned lead-capture campaigns."""
    campaigns = LeadCaptureCampaign.list_recent(client_id=client_id, status=status, query=query, limit=limit)
    return {
        "count": len(campaigns),
        "campaigns": [_campaign_payload(campaign, request=request) for campaign in campaigns],
    }


@agent_router.post("/campaigns")
async def create_agent_campaign(request: Request, command: AgentCampaignCreateCommand) -> dict[str, Any]:
    """Create one owned lead-capture campaign."""
    if command.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "would_create": True,
            "campaign": command.model_dump(exclude={"dry_run"}, mode="json"),
        }
    return await create_owned_campaign(request, command)


@agent_router.get("/campaigns/geo/search")
async def search_agent_campaign_geo(
    country_code: str = Query(default="AR", min_length=2, max_length=2),
    kind: str = Query(default="city", pattern="^(region|city)$"),
    q: str = Query(default="", max_length=96),
    limit: int = Query(default=12, ge=1, le=25),
) -> dict[str, Any]:
    """Search selectable campaign geography through the agent API."""
    return await search_owned_campaign_geo(country_code=country_code, kind=kind, q=q, limit=limit)


@agent_router.get("/campaigns/{campaign_id}")
async def get_agent_campaign(request: Request, campaign_id: str) -> dict[str, Any]:
    """Return one owned lead-capture campaign and recent submissions."""
    campaign = LeadCaptureCampaign.get_by_id(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return {"campaign": _campaign_payload(campaign, request=request, include_submissions=True)}


@agent_router.patch("/campaigns/{campaign_id}")
async def patch_agent_campaign(
    request: Request,
    campaign_id: str,
    command: AgentCampaignPatchCommand,
) -> dict[str, Any]:
    """Patch one owned lead-capture campaign."""
    campaign = LeadCaptureCampaign.get_by_id(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    if command.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "campaign_id": campaign_id,
            "would_patch": command.model_dump(exclude={"dry_run"}, exclude_unset=True, mode="json"),
        }
    from backend.endpoints.campaigns import patch_campaign as patch_owned_campaign

    return await patch_owned_campaign(request, campaign_id, command)


@agent_router.get("/campaigns/{campaign_id}/graph")
async def get_agent_campaign_graph(request: Request, campaign_id: str) -> dict[str, Any]:
    """Return the normalized Campaign > Ad Set > Ad graph for one campaign."""
    return await get_owned_campaign_meta_plan_graph(request, campaign_id)


@agent_router.put("/campaigns/{campaign_id}/graph")
async def set_agent_campaign_graph(
    request: Request,
    campaign_id: str,
    command: CampaignMetaPlanGraphCommand,
) -> dict[str, Any]:
    """Replace the saved Campaign > Ad Set > Ad graph."""
    return await set_owned_campaign_meta_plan_graph(request, campaign_id, command)


@agent_router.post("/campaigns/{campaign_id}/graph/duplicate")
async def duplicate_agent_campaign_graph_node(
    request: Request,
    campaign_id: str,
    command: CampaignMetaPlanDuplicateCommand,
) -> dict[str, Any]:
    """Duplicate a Campaign, Ad Set, or Ad node in the saved graph."""
    return await duplicate_owned_campaign_meta_plan_node(request, campaign_id, command)


@agent_router.post("/campaigns/{campaign_id}/meta-plan/stage")
async def stage_agent_campaign_graph(
    request: Request,
    campaign_id: str,
    command: CampaignMetaPlanStageCommand,
) -> dict[str, Any]:
    """Stage the saved graph into audited Meta publish attempts."""
    return await stage_owned_campaign_meta_plan_graph(request, campaign_id, command)


@agent_router.get("/campaigns/{campaign_id}/submissions")
async def list_agent_campaign_submissions(
    campaign_id: str,
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict[str, Any]:
    """List submissions captured by one owned campaign form."""
    campaign = LeadCaptureCampaign.get_by_id(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    submissions = LeadCaptureSubmission.list_by_campaign(campaign.id, limit=limit)
    return {
        "campaign_id": campaign.id,
        "count": len(submissions),
        "submissions": [_submission_payload(submission) for submission in submissions],
    }


@agent_router.post("/campaigns/{campaign_id}/delivery-source")
async def refresh_agent_campaign_delivery_source(request: Request, campaign_id: str) -> dict[str, Any]:
    """Create or refresh the Delivery source for one owned campaign."""
    return await refresh_owned_campaign_delivery_source(request, campaign_id)


@agent_router.get("/meta/readiness")
async def get_agent_meta_readiness() -> dict[str, Any]:
    """Return configured Meta readiness and the latest inventory snapshot."""
    return _meta_readiness_payload()


@agent_router.post("/meta/inventory/sync")
async def sync_agent_meta_inventory(command: AgentMetaInventorySyncCommand) -> dict[str, Any]:
    """Run a read-only Meta inventory sync using configured defaults when omitted."""
    snapshot, result = sync_meta_inventory(
        ad_account_id=command.ad_account_id,
        business_id=command.business_id,
        page_ids=command.page_ids,
        include_campaigns=command.include_campaigns,
        include_lead_forms=command.include_lead_forms,
        include_pixels=command.include_pixels,
        include_whatsapp=command.include_whatsapp,
        limit=command.limit,
        source="agent_api",
        actor="agent",
    )
    return {
        "saved": True,
        "snapshot": _meta_inventory_snapshot_payload(snapshot),
        "result": result.model_dump(mode="json"),
    }


@agent_router.post("/runs")
async def create_agent_run(command: AgentRunCreateCommand) -> dict[str, Any]:
    """Create or reuse one audited agent run."""
    run_id = (command.run_id or "").strip() or _new_run_id()
    run = AgentRun.ensure(
        run_id=run_id,
        agent_kind=command.agent_kind,
        target_type=command.target_type,
        target_id=command.target_id,
        prompt_version=command.prompt_version,
        context_path=command.context_path,
    )
    if run is None:
        raise HTTPException(status_code=400, detail="Unable to create agent run.")
    return {"run": _serialize_run(run)}


@agent_router.get("/runs/{run_id}")
async def get_agent_run(run_id: str) -> dict[str, Any]:
    """Return one run and its chronological audited tool calls."""
    run = AgentRun.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return {
        "run": _serialize_run(run),
        "tool_calls": [_serialize_tool_call(item) for item in AgentToolCall.list_by_run(run.id)],
    }


@agent_router.post("/runs/{run_id}/tools/{tool_name}")
async def call_agent_tool(
    run_id: str,
    tool_name: str,
    command: AgentToolCallCommand,
) -> dict[str, Any]:
    """Execute one audited product tool by name."""
    arguments = dict(command.arguments)
    if command.idempotency_key and not arguments.get("idempotency_key"):
        arguments["idempotency_key"] = command.idempotency_key
    return _call_tool_or_raise(
        run_id=run_id,
        tool_name=tool_name,
        arguments=arguments,
        dry_run=command.dry_run,
    )


@agent_router.get("/queues")
async def list_agent_queues(
    funnel_id: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Return named CRM queues with live counts."""
    base_leads = ContadoresLead.list_recent(
        limit=5000,
        funnel_id=(funnel_id or "").strip() or None,
        include_archived=True,
    )
    counts: Counter[str] = Counter()
    for lead in base_leads:
        effective_stage = derive_effective_lead_stage(lead)
        manual_status = derive_manual_reply_status(lead, effective_stage=effective_stage)
        queue_state = derive_lead_queue_state(
            lead,
            effective_stage=effective_stage,
            manual_reply_status=manual_status,
        )
        attention_state = derive_lead_attention_state(
            lead,
            effective_stage=effective_stage,
            manual_reply_status=manual_status,
        )
        pipeline_stage = derive_lead_pipeline_stage(lead, effective_stage=effective_stage)
        terminal_state = derive_lead_terminal_state(lead, effective_stage=effective_stage)
        if not include_archived and terminal_state == "archived":
            continue
        if attention_state == "needs_reply":
            counts["needs-attention"] += 1
        if queue_state in {"operator", "automation", "paused", "workstation"}:
            counts[queue_state] += 1
        if pipeline_stage == CANONICAL_CONVERTED_PIPELINE_STAGE:
            counts["converted"] += 1
        if terminal_state in {"closed", "archived"}:
            counts[terminal_state] += 1
        if terminal_state == "open":
            counts["all-open"] += 1
        if _lead_outbound_error_count(lead) > 0:
            counts["failed-delivery"] += 1
    return {
        "generated_at": _utcnow_iso(),
        "queues": [
            {
                "name": name,
                "count": counts.get(name, 0),
                "filters": filters,
            }
            for name, filters in sorted(QUEUE_FILTERS.items())
        ],
    }


@agent_router.get("/queues/{queue_name}")
async def get_agent_queue(
    queue_name: str,
    funnel_id: str | None = None,
    tag: str | None = None,
    platform: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    messages_per_lead: int = Query(default=5, ge=0, le=50),
    include_archived: bool = False,
) -> dict[str, Any]:
    """Return conversations for one named CRM queue."""
    normalized_name = _normalized_queue_name(queue_name)
    filters = QUEUE_FILTERS.get(normalized_name)
    if filters is None:
        raise HTTPException(status_code=404, detail="Unknown queue.")
    return _conversation_list_payload(
        funnel_id=funnel_id,
        queue_state=filters.get("queue_state"),
        attention_state=filters.get("attention_state"),
        pipeline_stage=filters.get("pipeline_stage"),
        terminal_state=filters.get("terminal_state"),
        tag=tag,
        platform=platform,
        query=query,
        limit=limit,
        messages_per_lead=messages_per_lead,
        include_archived=include_archived,
        delivery_state=filters.get("delivery_state"),
    ) | {"queue": normalized_name}


@agent_router.get("/conversations")
async def list_agent_conversations(
    funnel_id: str | None = None,
    queue_state: str | None = None,
    attention_state: str | None = None,
    manual_reply_status: str | None = None,
    pipeline_stage: str | None = None,
    terminal_state: str | None = None,
    tag: str | None = None,
    platform: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    messages_per_lead: int = Query(default=5, ge=0, le=50),
    include_archived: bool = False,
) -> dict[str, Any]:
    """List CRM conversations with agent-friendly filters."""
    return _conversation_list_payload(
        funnel_id=funnel_id,
        queue_state=queue_state,
        attention_state=attention_state,
        manual_reply_status=manual_reply_status,
        pipeline_stage=pipeline_stage,
        terminal_state=terminal_state,
        tag=tag,
        platform=platform,
        query=query,
        limit=limit,
        messages_per_lead=messages_per_lead,
        include_archived=include_archived,
    )


@agent_router.get("/conversations/{lead_id}")
async def get_agent_conversation(
    lead_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Return one lead, funnel config, messages, and Workstation link if present."""
    lead = _lead_or_404(lead_id)
    messages = ContadoresMessage.list_by_lead(lead.id)[-limit:]
    config = get_effective_funnel_config(lead.funnel_id)
    return {
        "lead": _serialize_lead(lead, assignments_cache={}),
        "config": _dump_model(build_config_response(config)),
        "messages": [_serialize_message(item) for item in messages],
        "workstation_client_id": _serialize_lead(lead).get("workstation_client_id"),
    }


@agent_router.get("/conversations/{lead_id}/messages")
async def get_agent_messages(
    lead_id: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Return messages for one CRM conversation."""
    _lead_or_404(lead_id)
    messages = ContadoresMessage.list_by_lead(lead_id)[-limit:]
    return {
        "lead_id": lead_id,
        "count": len(messages),
        "messages": [_serialize_message(item) for item in messages],
    }


@agent_router.post("/conversations/{lead_id}/messages")
async def send_agent_message(
    lead_id: str,
    command: AgentSendMessageCommand,
) -> dict[str, Any]:
    """Queue one outbound message through the audited send_whatsapp_text tool."""
    _lead_or_404(lead_id)
    run_id = _ensure_run(command.run_id, target_type="lead", target_id=lead_id)
    arguments = {
        "lead_id": lead_id,
        "text": command.text,
        "sequence_step": command.sequence_step,
        "dispatch_after_minutes": command.dispatch_after_minutes,
    }
    if command.idempotency_key:
        arguments["idempotency_key"] = command.idempotency_key
    return _call_tool_or_raise(
        run_id=run_id,
        tool_name="send_whatsapp_text",
        arguments=arguments,
        dry_run=command.dry_run,
    )


@agent_router.post("/conversations/{lead_id}/actions")
async def run_agent_action(
    lead_id: str,
    command: AgentLeadActionCommand,
) -> dict[str, Any]:
    """Run one existing CRM quick action with an AgentToolCall audit row."""
    lead = _lead_or_404(lead_id)
    clean_action = command.action.strip().lower()
    if clean_action not in QUICK_ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown CRM action.")
    run_id = _ensure_run(command.run_id, target_type="lead", target_id=lead_id)
    if command.dry_run:
        return {"ok": True, "dry_run": True, "action": clean_action, "lead_id": lead_id}

    def operation() -> dict[str, Any]:
        config = get_effective_funnel_config(lead.funnel_id)
        updated, queued_rows = run_quick_action_for_lead(
            lead=lead,
            action=clean_action,
            config=config,
        )
        return {
            "lead": _serialize_lead(updated, assignments_cache={}),
            "queued_message_ids": [item.id for item in queued_rows if item.id is not None],
        }

    return _audit_custom_operation(
        run_id=run_id,
        tool_name="crm_action",
        lead_id=lead_id,
        arguments={"lead_id": lead_id, "action": clean_action},
        operation=operation,
    )


@agent_router.post("/conversations/{lead_id}/notes")
async def add_agent_note(
    lead_id: str,
    command: AgentLeadNoteCommand,
) -> dict[str, Any]:
    """Append an audited agent memory note for one lead."""
    _lead_or_404(lead_id)
    run_id = _ensure_run(command.run_id, target_type="lead", target_id=lead_id)
    return _call_tool_or_raise(
        run_id=run_id,
        tool_name="write_agent_memory",
        arguments={
            "target_type": "lead",
            "target_id": lead_id,
            "note": command.text,
            "title": command.title,
            "importance": command.importance,
        },
        dry_run=command.dry_run,
    )


@agent_router.post("/conversations/{lead_id}/followups")
async def schedule_agent_followup(
    lead_id: str,
    command: AgentFollowupCommand,
) -> dict[str, Any]:
    """Schedule an audited future agent wake-up for one lead."""
    _lead_or_404(lead_id)
    run_id = _ensure_run(command.run_id, target_type="lead", target_id=lead_id)
    arguments = {
        "target_type": "lead",
        "target_id": lead_id,
        "run_after_minutes": command.minutes,
        "reason": command.reason,
        "instruction": command.instruction,
    }
    if command.idempotency_key:
        arguments["idempotency_key"] = command.idempotency_key
    return _call_tool_or_raise(
        run_id=run_id,
        tool_name="schedule_followup",
        arguments=arguments,
        dry_run=command.dry_run,
    )


@agent_router.patch("/conversations/{lead_id}")
async def patch_agent_conversation(
    lead_id: str,
    command: AgentConversationPatchCommand,
) -> dict[str, Any]:
    """Update lead tags/state through existing CRM lifecycle helpers."""
    lead = _lead_or_404(lead_id)
    run_id = _ensure_run(command.run_id, target_type="lead", target_id=lead_id)
    arguments = command.model_dump(exclude={"run_id"}, mode="json")
    if command.dry_run:
        return {"ok": True, "dry_run": True, "lead_id": lead_id, "arguments": arguments}

    def operation() -> dict[str, Any]:
        updated = lead
        if command.tags is not None:
            updated = ContadoresLead.set_tags(lead.id, tags=command.tags) or updated

        now = now_utc()
        flow_updates: dict[str, Any] = {}
        mark_converted = False
        clean_stage = (command.stage or "").strip().lower()
        if clean_stage:
            if clean_stage in {"booked", "converted"}:
                mark_converted = True
                flow_updates["clear_archived_at"] = True
                flow_updates["clear_closed_at"] = True
                flow_updates["clear_stage_before_closed"] = True
            else:
                target_stage = ContadoresLead.normalize_stage(clean_stage)
                if target_stage == ContadoresLeadStage.CLOSED:
                    flow_updates["stage"] = target_stage
                    flow_updates["closed_at"] = now
                    flow_updates["stage_before_closed"] = resolve_stage_before_closing(updated)
                elif target_stage == ContadoresLeadStage.ARCHIVED:
                    flow_updates["stage"] = target_stage
                    flow_updates["archived_at"] = now
                else:
                    flow_updates["stage"] = target_stage
                    flow_updates["clear_archived_at"] = True

        if command.classification_label is not None:
            flow_updates["last_classification_label"] = command.classification_label
            flow_updates["classification_completed_at"] = now
        if command.classification_reason is not None:
            flow_updates["last_classification_reason"] = command.classification_reason
            flow_updates["classification_completed_at"] = now
        if command.manual_reply_status == "answered":
            flow_updates["manual_reply_handled_at"] = now
        elif command.manual_reply_status == "needs_reply":
            flow_updates["clear_manual_reply_handled_at"] = True
        if command.automation_paused is not None:
            flow_updates["automation_paused"] = command.automation_paused
        if command.automation_paused_reason is not None:
            flow_updates["automation_paused_reason"] = command.automation_paused_reason

        if mark_converted:
            updated = ContadoresLead.mark_converted(updated.id, converted_at=now) or updated
        if flow_updates:
            updated = ContadoresLead.update_flow_state(updated.id, **flow_updates) or updated
        if command.tags is None and not flow_updates and not mark_converted:
            raise HTTPException(status_code=400, detail="No lead updates were provided.")
        return {"lead": _serialize_lead(updated, assignments_cache={})}

    return _audit_custom_operation(
        run_id=run_id,
        tool_name="crm_update",
        lead_id=lead_id,
        arguments=arguments,
        operation=operation,
    )


@agent_router.put("/conversations/{lead_id}/tags")
async def set_agent_tags(
    lead_id: str,
    command: AgentTagsCommand,
) -> dict[str, Any]:
    """Replace or append tags through the audited set_lead_tags tool."""
    _lead_or_404(lead_id)
    run_id = _ensure_run(command.run_id, target_type="lead", target_id=lead_id)
    normalized_tags = normalize_contadores_tags(command.tags)
    mode = "replace" if command.mode == "set" else "append"
    return _call_tool_or_raise(
        run_id=run_id,
        tool_name="set_lead_tags",
        arguments={
            "lead_id": lead_id,
            "tags": normalized_tags,
            "mode": mode,
        },
        dry_run=command.dry_run,
    )
