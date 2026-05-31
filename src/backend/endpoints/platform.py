"""Platform lifecycle and observability endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import (
    AgentRun,
    AgentToolCall,
    PlatformAdCampaign,
    PlatformClientProfile,
    PlatformClientUpdate,
    PlatformCreativeAsset,
    PlatformEvent,
    PlatformHumanQuestion,
    PlatformMeeting,
    PlatformMetaInventorySnapshot,
    PlatformMetaPublishAttempt,
)
from backend.calendar_events import CalendarSchedulingError, schedule_meeting_calendar_event
from backend.platform_profile_extraction import PlatformProfileExtractionError, extract_client_profile_from_meeting
from backend.meta_ads_publish import (
    MetaAdsPublishError,
    approve_meta_publish_attempt,
    execute_meta_publish_attempt,
    preflight_meta_publish_attempt,
    upload_meta_creative_asset,
)
from backend.meta_ads_inventory import MetaInventoryError, sync_meta_inventory

platform_router = APIRouter(prefix="/api/platform", tags=["platform"])


class PlatformEventResponse(BaseModel):
    """Serialized platform lifecycle event."""

    id: int
    event_type: str
    lifecycle_stage: str
    target_type: str
    target_id: str
    funnel_id: str
    severity: str
    source: str
    actor: str
    summary: str
    payload: dict[str, Any]
    idempotency_key: str | None
    correlation_id: str | None
    created_at: datetime


class PlatformEventListResponse(BaseModel):
    """Recent platform events for operator observability."""

    events: list[PlatformEventResponse]


class PlatformAgentRunResponse(BaseModel):
    """Serialized autonomous agent run."""

    id: str
    agent_kind: str
    target_type: str
    target_id: str
    status: str
    prompt_version: str
    context_path: str
    codex_thread_id: str | None
    codex_turn_id: str | None
    final_response_preview: str
    error_preview: str
    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class PlatformAgentToolCallResponse(BaseModel):
    """Serialized audited agent tool call."""

    id: int
    run_id: str
    tool_name: str
    target_type: str
    target_id: str
    status: str
    idempotency_key: str | None
    arguments_preview: str
    result_preview: str
    error_preview: str
    created_at: datetime


class PlatformMeetingCommand(BaseModel):
    """Create one meeting handoff record."""

    lead_id: str = ""
    client_id: str = ""
    funnel_id: str = ""
    status: str = "collecting_details"
    lead_email: str = ""
    timezone: str = ""
    requested_day: str = ""
    requested_time: str = ""
    calendar_id: str = ""
    calendar_event_id: str = ""
    calendar_event_link: str = ""
    calendar_event_payload: dict[str, Any] = Field(default_factory=dict)
    calendar_result: dict[str, Any] = Field(default_factory=dict)
    calendar_error: str = ""
    context_summary: str = ""
    transcript_text: str = ""
    transcript_path: str = ""
    extracted_profile: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    scheduled_at: datetime | None = None


class PlatformMeetingTranscriptCommand(BaseModel):
    """Attach transcript/profile extraction to a meeting."""

    transcript_text: str = ""
    transcript_path: str = ""
    extracted_profile: dict[str, Any] = Field(default_factory=dict)
    status: str = "transcript_received"


class PlatformMeetingProfileExtractionCommand(BaseModel):
    """Extract a draft client profile from one meeting transcript."""

    client_id: str = ""
    lead_id: str = ""
    funnel_id: str = ""
    status: str = "draft"
    existing_context: dict[str, Any] = Field(default_factory=dict)


class PlatformMeetingResponse(BaseModel):
    """Serialized meeting lifecycle record."""

    id: str
    lead_id: str
    client_id: str
    funnel_id: str
    status: str
    lead_email: str
    timezone: str
    requested_day: str
    requested_time: str
    calendar_id: str
    calendar_event_id: str
    calendar_event_link: str
    calendar_event_payload: dict[str, Any]
    calendar_result: dict[str, Any]
    calendar_error: str
    context_summary: str
    transcript_text: str
    transcript_path: str
    extracted_profile: dict[str, Any]
    idempotency_key: str | None
    scheduled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformMeetingListResponse(BaseModel):
    """Meeting list response."""

    meetings: list[PlatformMeetingResponse]


class PlatformMeetingCalendarCommand(BaseModel):
    """Preflight or create one Google Calendar event for a meeting."""

    calendar_id: str = ""
    internal_attendees: list[str] = Field(default_factory=list)
    duration_minutes: int = Field(default=15, ge=5, le=180)
    create_google_meet: bool = False
    live_writes_requested: bool = False
    send_updates: Literal["all", "externalOnly", "none"] = "all"


class PlatformMeetingCalendarResponse(BaseModel):
    """Meeting calendar scheduling response."""

    meeting: PlatformMeetingResponse
    calendar: dict[str, Any]


class PlatformClientProfileCommand(BaseModel):
    """Create or update one reviewed client profile."""

    client_id: str = Field(min_length=1)
    lead_id: str = ""
    funnel_id: str = ""
    status: str = "draft"
    source_meeting_id: str = ""
    business_summary: str = ""
    offer_summary: str = ""
    market_summary: str = ""
    objections: list[Any] = Field(default_factory=list)
    segments: list[Any] = Field(default_factory=list)
    knowledge: dict[str, Any] = Field(default_factory=dict)


class PlatformClientProfileResponse(BaseModel):
    """Serialized client profile."""

    id: str
    client_id: str
    lead_id: str
    funnel_id: str
    status: str
    source_meeting_id: str
    business_summary: str
    offer_summary: str
    market_summary: str
    objections: list[Any]
    segments: list[Any]
    knowledge: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PlatformClientProfileListResponse(BaseModel):
    """Client profile list response."""

    profiles: list[PlatformClientProfileResponse]


class PlatformMeetingProfileExtractionResponse(BaseModel):
    """Saved profile extraction response."""

    meeting: PlatformMeetingResponse
    profile: PlatformClientProfileResponse
    extraction: dict[str, Any]


class PlatformAdCampaignCommand(BaseModel):
    """Create one staged ad campaign."""

    client_id: str = ""
    funnel_id: str = ""
    status: str = "draft"
    objective: str = ""
    budget_daily_usd: int | None = Field(default=None, ge=0)
    budget_total_usd: int | None = Field(default=None, ge=0)
    budget_currency: str = "USD"
    target_segments: list[Any] = Field(default_factory=list)
    angles: list[Any] = Field(default_factory=list)
    creative_benchmark: dict[str, Any] = Field(default_factory=dict)
    creative_testing: dict[str, Any] = Field(default_factory=dict)
    approval_status: str = "not_requested"
    idempotency_key: str | None = None


class PlatformAdCampaignResponse(BaseModel):
    """Serialized ad campaign."""

    id: str
    client_id: str
    funnel_id: str
    status: str
    objective: str
    budget_daily_usd: int | None
    budget_total_usd: int | None
    budget_currency: str
    target_segments: list[Any]
    angles: list[Any]
    creative_benchmark: dict[str, Any]
    creative_testing: dict[str, Any]
    meta_campaign_id: str
    approval_status: str
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime


class PlatformAdCampaignListResponse(BaseModel):
    """Ad campaign list response."""

    campaigns: list[PlatformAdCampaignResponse]


class PlatformCreativeAssetCommand(BaseModel):
    """Create one staged creative asset."""

    campaign_id: str = ""
    client_id: str = ""
    status: str = "draft"
    asset_type: str = "image"
    prompt: str = ""
    file_path: str = ""
    dimensions: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    meta_creative_id: str = ""
    image_hash: str = ""
    video_id: str = ""
    meta_upload_response: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str = ""


class PlatformCreativeAssetResponse(BaseModel):
    """Serialized creative asset."""

    id: str
    campaign_id: str
    client_id: str
    status: str
    asset_type: str
    prompt: str
    file_path: str
    dimensions: str
    source_refs: list[Any]
    meta_creative_id: str
    image_hash: str
    video_id: str
    meta_upload_response: dict[str, Any]
    failure_reason: str
    created_at: datetime
    updated_at: datetime


class PlatformCreativeAssetListResponse(BaseModel):
    """Creative asset list response."""

    assets: list[PlatformCreativeAssetResponse]


class PlatformCreativeAssetUploadCommand(BaseModel):
    """Upload one staged creative asset to Meta media storage."""

    ad_account_id: str = ""
    live_writes_requested: bool = False


class PlatformCreativeAssetUploadResponse(BaseModel):
    """Meta creative upload response."""

    asset: PlatformCreativeAssetResponse
    upload: dict[str, Any]


class PlatformMetaPublishAttemptCommand(BaseModel):
    """Stage one Meta publish attempt."""

    campaign_id: str = ""
    status: str = "staged"
    approval_status: str = "pending"
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    idempotency_key: str | None = None


class PlatformMetaPublishAttemptResponse(BaseModel):
    """Serialized Meta publish attempt."""

    id: str
    campaign_id: str
    status: str
    approval_status: str
    request_payload: dict[str, Any]
    response_payload: dict[str, Any]
    error: str
    idempotency_key: str | None
    created_at: datetime
    updated_at: datetime


class PlatformMetaPublishAttemptListResponse(BaseModel):
    """Meta publish attempt list response."""

    attempts: list[PlatformMetaPublishAttemptResponse]


class PlatformMetaPublishPreflightCommand(BaseModel):
    """Build/check a staged Meta publish plan without live writes by default."""

    live_writes_requested: bool = False


class PlatformMetaPublishPreflightResponse(BaseModel):
    """Meta publish preflight response."""

    attempt: PlatformMetaPublishAttemptResponse
    preflight: dict[str, Any]


class PlatformMetaPublishApprovalCommand(BaseModel):
    """Approve a staged Meta publish plan after budget and inventory checks."""

    approved_by: str = Field(min_length=1)
    approval_note: str = Field(default="", max_length=2000)
    approve_live_writes: bool = False
    require_inventory_ready: bool = True
    max_daily_budget_usd: int = Field(default=50, ge=1)
    max_lifetime_budget_usd: int = Field(default=1500, ge=0)
    max_estimated_monthly_budget_usd: int = Field(default=1500, ge=1)


class PlatformMetaPublishApprovalResponse(BaseModel):
    """Meta publish approval gate response."""

    attempt: PlatformMetaPublishAttemptResponse
    approval: dict[str, Any]


class PlatformMetaPublishExecutionCommand(BaseModel):
    """Execute an approved Meta publish plan."""

    live_writes_requested: bool = False


class PlatformMetaPublishExecutionResponse(BaseModel):
    """Meta publish execution response."""

    attempt: PlatformMetaPublishAttemptResponse
    execution: dict[str, Any]


class PlatformMetaInventorySyncCommand(BaseModel):
    """Read Meta inventory without publishing ads."""

    ad_account_id: str = ""
    business_id: str = ""
    page_ids: list[str] = Field(default_factory=list)
    include_campaigns: bool = True
    include_lead_forms: bool = True
    include_pixels: bool = True
    include_whatsapp: bool = True
    limit: int = Field(default=50, ge=1, le=200)


class PlatformMetaInventorySnapshotResponse(BaseModel):
    """Serialized Meta inventory snapshot."""

    id: str
    status: str
    source: str
    actor: str
    ad_account_id: str
    business_id: str
    api_version: str
    inventory: dict[str, Any]
    errors: list[Any]
    created_at: datetime


class PlatformMetaInventoryListResponse(BaseModel):
    """Meta inventory snapshot list response."""

    snapshots: list[PlatformMetaInventorySnapshotResponse]


class PlatformMetaInventorySyncResponse(BaseModel):
    """Meta inventory sync response."""

    snapshot: PlatformMetaInventorySnapshotResponse
    result: dict[str, Any]


class PlatformClientUpdateCommand(BaseModel):
    """Create one client status update record."""

    client_id: str = ""
    campaign_id: str = ""
    status: str = "draft"
    summary_text: str = ""
    leads_count: int = Field(default=0, ge=0)
    blockers: list[Any] = Field(default_factory=list)
    next_action: str = ""
    whatsapp_message_id: int | None = None
    window_started_at: datetime | None = None
    window_ended_at: datetime | None = None


class PlatformClientUpdateResponse(BaseModel):
    """Serialized client update."""

    id: str
    client_id: str
    campaign_id: str
    status: str
    summary_text: str
    leads_count: int
    blockers: list[Any]
    next_action: str
    whatsapp_message_id: int | None
    window_started_at: datetime | None
    window_ended_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformClientUpdateListResponse(BaseModel):
    """Client update list response."""

    updates: list[PlatformClientUpdateResponse]


class PlatformHumanQuestionCommand(BaseModel):
    """Create one human escalation question."""

    workflow: str = ""
    target_type: str = ""
    target_id: str = ""
    funnel_id: str = ""
    context_summary: str = ""
    trying_to_do: str = ""
    question: str = Field(min_length=1)
    options: list[Any] = Field(default_factory=list)
    default_action: str = ""
    timeout_at: datetime | None = None
    whatsapp_message_id: str = ""


class PlatformHumanQuestionAnswerCommand(BaseModel):
    """Answer one human escalation question."""

    answer_text: str = Field(min_length=1)
    status: str = "answered"
    promoted_to_memory_at: datetime | None = None


class PlatformHumanQuestionResponse(BaseModel):
    """Serialized human question."""

    id: str
    workflow: str
    target_type: str
    target_id: str
    funnel_id: str
    status: str
    context_summary: str
    trying_to_do: str
    question: str
    options: list[Any]
    default_action: str
    timeout_at: datetime | None
    whatsapp_message_id: str
    answer_text: str
    answered_at: datetime | None
    promoted_to_memory_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PlatformHumanQuestionListResponse(BaseModel):
    """Human question list response."""

    questions: list[PlatformHumanQuestionResponse]


class PlatformOverviewCounts(BaseModel):
    """Operator cockpit aggregate counts."""

    active_blockers: int
    open_human_questions: int
    blocked_meta_attempts: int
    blocked_meta_inventory: int
    pending_campaigns: int
    meetings: int
    campaigns: int
    creative_assets: int
    meta_inventory_snapshots: int
    client_updates: int
    agent_runs: int
    failed_agent_runs: int
    agent_tool_calls: int
    failed_agent_tool_calls: int
    recent_events: int


class PlatformOverviewResponse(BaseModel):
    """Operator cockpit read model over platform lifecycle records."""

    generated_at: datetime
    counts: PlatformOverviewCounts
    events: list[PlatformEventResponse]
    meetings: list[PlatformMeetingResponse]
    client_profiles: list[PlatformClientProfileResponse]
    ad_campaigns: list[PlatformAdCampaignResponse]
    creative_assets: list[PlatformCreativeAssetResponse]
    meta_inventory_snapshots: list[PlatformMetaInventorySnapshotResponse]
    meta_publish_attempts: list[PlatformMetaPublishAttemptResponse]
    client_updates: list[PlatformClientUpdateResponse]
    human_questions: list[PlatformHumanQuestionResponse]
    agent_runs: list[PlatformAgentRunResponse]
    agent_tool_calls: list[PlatformAgentToolCallResponse]


def serialize_platform_event(event: PlatformEvent) -> PlatformEventResponse:
    """Convert a persistence row to an API response."""
    return PlatformEventResponse(
        id=int(event.id or 0),
        event_type=event.event_type,
        lifecycle_stage=event.lifecycle_stage,
        target_type=event.target_type,
        target_id=event.target_id,
        funnel_id=event.funnel_id,
        severity=event.severity,
        source=event.source,
        actor=event.actor,
        summary=event.summary,
        payload=event.payload_dict(),
        idempotency_key=event.idempotency_key,
        correlation_id=event.correlation_id,
        created_at=event.created_at,
    )


def compact_overview_text(value: str, *, limit: int = 500) -> str:
    """Return a small single-line preview for high-frequency overview payloads."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def serialize_agent_run(row: AgentRun) -> PlatformAgentRunResponse:
    """Convert one agent run to the platform cockpit shape."""
    return PlatformAgentRunResponse(
        id=row.id,
        agent_kind=row.agent_kind,
        target_type=row.target_type,
        target_id=row.target_id,
        status=row.status,
        prompt_version=row.prompt_version,
        context_path=row.context_path,
        codex_thread_id=row.codex_thread_id,
        codex_turn_id=row.codex_turn_id,
        final_response_preview=compact_overview_text(row.final_response),
        error_preview=compact_overview_text(row.error, limit=320),
        started_at=row.started_at,
        finished_at=row.finished_at,
        created_at=row.created_at,
    )


def serialize_agent_tool_call(row: AgentToolCall) -> PlatformAgentToolCallResponse:
    """Convert one audited tool call to the platform cockpit shape."""
    return PlatformAgentToolCallResponse(
        id=int(row.id or 0),
        run_id=row.run_id,
        tool_name=row.tool_name,
        target_type=row.target_type,
        target_id=row.target_id,
        status=row.status,
        idempotency_key=row.idempotency_key,
        arguments_preview=compact_overview_text(row.arguments_json, limit=700),
        result_preview=compact_overview_text(row.result_json, limit=700),
        error_preview=compact_overview_text(row.error, limit=320),
        created_at=row.created_at,
    )


def serialize_meeting(row: PlatformMeeting) -> PlatformMeetingResponse:
    """Serialize one meeting."""
    return PlatformMeetingResponse(
        id=row.id,
        lead_id=row.lead_id,
        client_id=row.client_id,
        funnel_id=row.funnel_id,
        status=row.status,
        lead_email=row.lead_email,
        timezone=row.timezone,
        requested_day=row.requested_day,
        requested_time=row.requested_time,
        calendar_id=row.calendar_id,
        calendar_event_id=row.calendar_event_id,
        calendar_event_link=row.calendar_event_link,
        calendar_event_payload=row.calendar_event_payload(),
        calendar_result=row.calendar_result(),
        calendar_error=row.calendar_error,
        context_summary=row.context_summary,
        transcript_text=row.transcript_text,
        transcript_path=row.transcript_path,
        extracted_profile=row.extracted_profile(),
        idempotency_key=row.idempotency_key,
        scheduled_at=row.scheduled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def serialize_client_profile(row: PlatformClientProfile) -> PlatformClientProfileResponse:
    """Serialize one client profile."""
    return PlatformClientProfileResponse(
        id=row.id,
        client_id=row.client_id,
        lead_id=row.lead_id,
        funnel_id=row.funnel_id,
        status=row.status,
        source_meeting_id=row.source_meeting_id,
        business_summary=row.business_summary,
        offer_summary=row.offer_summary,
        market_summary=row.market_summary,
        objections=row.objections(),
        segments=row.segments(),
        knowledge=row.knowledge(),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def serialize_ad_campaign(row: PlatformAdCampaign) -> PlatformAdCampaignResponse:
    """Serialize one ad campaign."""
    return PlatformAdCampaignResponse(
        id=row.id,
        client_id=row.client_id,
        funnel_id=row.funnel_id,
        status=row.status,
        objective=row.objective,
        budget_daily_usd=row.budget_daily_usd,
        budget_total_usd=row.budget_total_usd,
        budget_currency=row.budget_currency,
        target_segments=row.target_segments(),
        angles=row.angles(),
        creative_benchmark=row.creative_benchmark(),
        creative_testing=row.creative_testing(),
        meta_campaign_id=row.meta_campaign_id,
        approval_status=row.approval_status,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def serialize_creative_asset(row: PlatformCreativeAsset) -> PlatformCreativeAssetResponse:
    """Serialize one creative asset."""
    return PlatformCreativeAssetResponse(
        id=row.id,
        campaign_id=row.campaign_id,
        client_id=row.client_id,
        status=row.status,
        asset_type=row.asset_type,
        prompt=row.prompt,
        file_path=row.file_path,
        dimensions=row.dimensions,
        source_refs=row.source_refs(),
        meta_creative_id=row.meta_creative_id,
        image_hash=row.image_hash,
        video_id=row.video_id,
        meta_upload_response=row.meta_upload_response(),
        failure_reason=row.failure_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def serialize_meta_publish_attempt(row: PlatformMetaPublishAttempt) -> PlatformMetaPublishAttemptResponse:
    """Serialize one Meta publish attempt."""
    return PlatformMetaPublishAttemptResponse(
        id=row.id,
        campaign_id=row.campaign_id,
        status=row.status,
        approval_status=row.approval_status,
        request_payload=row.request_payload(),
        response_payload=row.response_payload(),
        error=row.error,
        idempotency_key=row.idempotency_key,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def serialize_meta_inventory_snapshot(row: PlatformMetaInventorySnapshot) -> PlatformMetaInventorySnapshotResponse:
    """Serialize one Meta inventory snapshot."""
    return PlatformMetaInventorySnapshotResponse(
        id=row.id,
        status=row.status,
        source=row.source,
        actor=row.actor,
        ad_account_id=row.ad_account_id,
        business_id=row.business_id,
        api_version=row.api_version,
        inventory=row.inventory(),
        errors=row.errors(),
        created_at=row.created_at,
    )


def serialize_client_update(row: PlatformClientUpdate) -> PlatformClientUpdateResponse:
    """Serialize one client update."""
    return PlatformClientUpdateResponse(
        id=row.id,
        client_id=row.client_id,
        campaign_id=row.campaign_id,
        status=row.status,
        summary_text=row.summary_text,
        leads_count=row.leads_count,
        blockers=row.blockers(),
        next_action=row.next_action,
        whatsapp_message_id=row.whatsapp_message_id,
        window_started_at=row.window_started_at,
        window_ended_at=row.window_ended_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def serialize_human_question(row: PlatformHumanQuestion) -> PlatformHumanQuestionResponse:
    """Serialize one human question."""
    return PlatformHumanQuestionResponse(
        id=row.id,
        workflow=row.workflow,
        target_type=row.target_type,
        target_id=row.target_id,
        funnel_id=row.funnel_id,
        status=row.status,
        context_summary=row.context_summary,
        trying_to_do=row.trying_to_do,
        question=row.question,
        options=row.options(),
        default_action=row.default_action,
        timeout_at=row.timeout_at,
        whatsapp_message_id=row.whatsapp_message_id,
        answer_text=row.answer_text,
        answered_at=row.answered_at,
        promoted_to_memory_at=row.promoted_to_memory_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def emit_lifecycle_event(
    *,
    event_type: str,
    lifecycle_stage: str,
    target_type: str,
    target_id: str,
    funnel_id: str = "",
    summary: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Best-effort event write for lifecycle API changes."""
    PlatformEvent.add(
        event_type=event_type,
        lifecycle_stage=lifecycle_stage,
        target_type=target_type,
        target_id=target_id,
        funnel_id=funnel_id,
        source="platform_api",
        actor="operator",
        summary=summary,
        payload=payload or {},
    )


def is_open_human_question(row: PlatformHumanQuestion) -> bool:
    """Return whether a human question still needs an operator answer."""
    return row.status not in {"answered", "closed", "resolved", "cancelled"}


def is_blocked_meta_attempt(row: PlatformMetaPublishAttempt) -> bool:
    """Return whether a Meta publish attempt needs preflight or recovery."""
    return row.status in {"blocked", "failed", "error"} or row.approval_status in {"needs_preflight", "rejected"}


def is_blocked_meta_inventory(row: PlatformMetaInventorySnapshot) -> bool:
    """Return whether the latest Meta inventory sync blocks publishing."""
    return row.status in {"missing_credentials", "partial", "error", "blocked"}


def is_pending_campaign(row: PlatformAdCampaign) -> bool:
    """Return whether an ad campaign needs approval or publishing work."""
    return row.status not in {"published", "closed", "archived"} or row.approval_status not in {"approved", "published"}


@platform_router.get("/events", response_model=PlatformEventListResponse)
async def list_platform_events(
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    funnel_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformEventListResponse:
    """Return recent append-only lifecycle events."""
    events = PlatformEvent.list_recent(
        target_type=target_type,
        target_id=target_id,
        funnel_id=funnel_id,
        limit=limit,
    )
    return PlatformEventListResponse(events=[serialize_platform_event(event) for event in events])


@platform_router.get("/overview", response_model=PlatformOverviewResponse)
async def platform_overview(
    limit: int = Query(default=80, ge=1, le=200),
) -> PlatformOverviewResponse:
    """Return the lifecycle cockpit read model used by operators and agents."""
    events = PlatformEvent.list_recent(limit=limit)
    meetings = PlatformMeeting.list_recent(limit=limit)
    client_profiles = PlatformClientProfile.list_recent(limit=limit)
    ad_campaigns = PlatformAdCampaign.list_recent(limit=limit)
    creative_assets = PlatformCreativeAsset.list_recent(limit=limit)
    meta_inventory_snapshots = PlatformMetaInventorySnapshot.list_recent(limit=limit)
    meta_publish_attempts = PlatformMetaPublishAttempt.list_recent(limit=limit)
    client_updates = PlatformClientUpdate.list_recent(limit=limit)
    human_questions = PlatformHumanQuestion.list_recent(limit=limit)
    agent_runs = AgentRun.list_recent(limit=limit)
    agent_tool_calls = AgentToolCall.list_recent(limit=limit)

    open_questions = sum(1 for row in human_questions if is_open_human_question(row))
    blocked_meta = sum(1 for row in meta_publish_attempts if is_blocked_meta_attempt(row))
    blocked_inventory = 1 if meta_inventory_snapshots and is_blocked_meta_inventory(meta_inventory_snapshots[0]) else 0
    pending_campaigns = sum(1 for row in ad_campaigns if is_pending_campaign(row))
    updates_with_blockers = sum(1 for row in client_updates if row.blockers())
    failed_agent_runs = sum(1 for row in agent_runs if row.status in {"failed", "error", "blocked"})
    failed_tool_calls = sum(1 for row in agent_tool_calls if row.status == "failed")

    return PlatformOverviewResponse(
        generated_at=datetime.now(timezone.utc),
        counts=PlatformOverviewCounts(
            active_blockers=open_questions + blocked_meta + blocked_inventory + updates_with_blockers,
            open_human_questions=open_questions,
            blocked_meta_attempts=blocked_meta,
            blocked_meta_inventory=blocked_inventory,
            pending_campaigns=pending_campaigns,
            meetings=len(meetings),
            campaigns=len(ad_campaigns),
            creative_assets=len(creative_assets),
            meta_inventory_snapshots=len(meta_inventory_snapshots),
            client_updates=len(client_updates),
            agent_runs=len(agent_runs),
            failed_agent_runs=failed_agent_runs,
            agent_tool_calls=len(agent_tool_calls),
            failed_agent_tool_calls=failed_tool_calls,
            recent_events=len(events),
        ),
        events=[serialize_platform_event(event) for event in events],
        meetings=[serialize_meeting(row) for row in meetings],
        client_profiles=[serialize_client_profile(row) for row in client_profiles],
        ad_campaigns=[serialize_ad_campaign(row) for row in ad_campaigns],
        creative_assets=[serialize_creative_asset(row) for row in creative_assets],
        meta_inventory_snapshots=[serialize_meta_inventory_snapshot(row) for row in meta_inventory_snapshots],
        meta_publish_attempts=[serialize_meta_publish_attempt(row) for row in meta_publish_attempts],
        client_updates=[serialize_client_update(row) for row in client_updates],
        human_questions=[serialize_human_question(row) for row in human_questions],
        agent_runs=[serialize_agent_run(row) for row in agent_runs],
        agent_tool_calls=[serialize_agent_tool_call(row) for row in agent_tool_calls],
    )


@platform_router.get("/meetings", response_model=PlatformMeetingListResponse)
async def list_meetings(
    status: str | None = Query(default=None),
    lead_id: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    funnel_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformMeetingListResponse:
    """Return meeting scheduling/transcript records."""
    rows = PlatformMeeting.list_recent(
        status=status,
        lead_id=lead_id,
        client_id=client_id,
        funnel_id=funnel_id,
        limit=limit,
    )
    return PlatformMeetingListResponse(meetings=[serialize_meeting(row) for row in rows])


@platform_router.post("/meetings", response_model=PlatformMeetingResponse)
async def create_meeting(command: PlatformMeetingCommand) -> PlatformMeetingResponse:
    """Create one meeting scheduling record without creating a Google Calendar event."""
    row = PlatformMeeting.add(
        lead_id=command.lead_id,
        client_id=command.client_id,
        funnel_id=command.funnel_id,
        status=command.status,
        lead_email=command.lead_email,
        timezone_name=command.timezone,
        requested_day=command.requested_day,
        requested_time=command.requested_time,
        calendar_id=command.calendar_id,
        calendar_event_id=command.calendar_event_id,
        calendar_event_link=command.calendar_event_link,
        calendar_event_payload=command.calendar_event_payload,
        calendar_result=command.calendar_result,
        calendar_error=command.calendar_error,
        context_summary=command.context_summary,
        transcript_text=command.transcript_text,
        transcript_path=command.transcript_path,
        extracted_profile=command.extracted_profile,
        idempotency_key=command.idempotency_key,
        scheduled_at=command.scheduled_at,
    )
    emit_lifecycle_event(
        event_type="meeting.record_created",
        lifecycle_stage="meeting",
        target_type="meeting",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Created meeting record {row.id}.",
        payload={"lead_id": row.lead_id, "client_id": row.client_id, "status": row.status},
    )
    return serialize_meeting(row)


@platform_router.post("/meetings/{meeting_id}/calendar-event", response_model=PlatformMeetingCalendarResponse)
async def schedule_meeting_calendar_event_endpoint(
    meeting_id: str,
    command: PlatformMeetingCalendarCommand,
) -> PlatformMeetingCalendarResponse:
    """Build or create a Google Calendar event for one meeting."""
    try:
        row, result = schedule_meeting_calendar_event(
            meeting_id=meeting_id,
            calendar_id=command.calendar_id,
            internal_attendees=command.internal_attendees,
            duration_minutes=command.duration_minutes,
            create_google_meet=command.create_google_meet,
            live_writes_requested=command.live_writes_requested,
            send_updates=command.send_updates,
            source="platform_api",
            actor="operator",
        )
    except CalendarSchedulingError as error:
        message = str(error)
        status_code = 404 if message.startswith("Meeting not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from error
    return PlatformMeetingCalendarResponse(
        meeting=serialize_meeting(row),
        calendar=result.model_dump(mode="json"),
    )


@platform_router.post("/meetings/{meeting_id}/transcript", response_model=PlatformMeetingResponse)
async def attach_meeting_transcript(
    meeting_id: str,
    command: PlatformMeetingTranscriptCommand,
) -> PlatformMeetingResponse:
    """Attach a conversion transcript and extracted profile data."""
    row = PlatformMeeting.attach_transcript(
        meeting_id,
        transcript_text=command.transcript_text,
        transcript_path=command.transcript_path,
        extracted_profile=command.extracted_profile,
        status=command.status,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found.")
    emit_lifecycle_event(
        event_type="meeting.transcript_attached",
        lifecycle_stage="post_conversion",
        target_type="meeting",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Attached transcript to meeting {row.id}.",
        payload={"client_id": row.client_id, "lead_id": row.lead_id, "profile_keys": list(row.extracted_profile())},
    )
    return serialize_meeting(row)


@platform_router.post(
    "/meetings/{meeting_id}/extract-client-profile",
    response_model=PlatformMeetingProfileExtractionResponse,
)
async def extract_meeting_client_profile(
    meeting_id: str,
    command: PlatformMeetingProfileExtractionCommand,
) -> PlatformMeetingProfileExtractionResponse:
    """Use the meeting transcript to create a draft client profile for ads and Meta planning."""
    try:
        result = extract_client_profile_from_meeting(
            meeting_id=meeting_id,
            client_id=command.client_id,
            lead_id=command.lead_id,
            funnel_id=command.funnel_id,
            status=command.status,
            existing_context=command.existing_context,
            source="platform_api",
            actor="operator",
        )
    except PlatformProfileExtractionError as error:
        message = str(error)
        status_code = 404 if message.startswith("Meeting not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Client profile extraction failed: {error}") from error
    return PlatformMeetingProfileExtractionResponse(
        meeting=serialize_meeting(result.meeting),
        profile=serialize_client_profile(result.profile),
        extraction=result.extraction.model_dump(mode="json"),
    )


@platform_router.get("/client-profiles", response_model=PlatformClientProfileListResponse)
async def list_client_profiles(
    client_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformClientProfileListResponse:
    """Return reviewed client profiles."""
    rows = PlatformClientProfile.list_recent(client_id=client_id, limit=limit)
    return PlatformClientProfileListResponse(profiles=[serialize_client_profile(row) for row in rows])


@platform_router.post("/client-profiles", response_model=PlatformClientProfileResponse)
async def upsert_client_profile(command: PlatformClientProfileCommand) -> PlatformClientProfileResponse:
    """Create or update one post-conversion client profile."""
    row = PlatformClientProfile.upsert(**command.model_dump())
    emit_lifecycle_event(
        event_type="client_profile.upserted",
        lifecycle_stage="post_conversion",
        target_type="client_profile",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Upserted client profile for {row.client_id}.",
        payload={"client_id": row.client_id, "status": row.status, "source_meeting_id": row.source_meeting_id},
    )
    return serialize_client_profile(row)


@platform_router.get("/ad-campaigns", response_model=PlatformAdCampaignListResponse)
async def list_ad_campaigns(
    client_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformAdCampaignListResponse:
    """Return staged or published ad campaigns."""
    rows = PlatformAdCampaign.list_recent(client_id=client_id, status=status, limit=limit)
    return PlatformAdCampaignListResponse(campaigns=[serialize_ad_campaign(row) for row in rows])


@platform_router.post("/ad-campaigns", response_model=PlatformAdCampaignResponse)
async def create_ad_campaign(command: PlatformAdCampaignCommand) -> PlatformAdCampaignResponse:
    """Create one staged ad campaign. This does not publish to Meta."""
    row = PlatformAdCampaign.add(**command.model_dump())
    emit_lifecycle_event(
        event_type="ad_campaign.staged",
        lifecycle_stage="ads",
        target_type="ad_campaign",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Staged ad campaign {row.id}.",
        payload={
            "client_id": row.client_id,
            "budget_daily_usd": row.budget_daily_usd,
            "creative_testing": row.creative_testing(),
            "approval_status": row.approval_status,
        },
    )
    return serialize_ad_campaign(row)


@platform_router.get("/creative-assets", response_model=PlatformCreativeAssetListResponse)
async def list_creative_assets(
    campaign_id: str | None = Query(default=None),
    client_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformCreativeAssetListResponse:
    """Return creative assets."""
    rows = PlatformCreativeAsset.list_recent(
        campaign_id=campaign_id,
        client_id=client_id,
        status=status,
        limit=limit,
    )
    return PlatformCreativeAssetListResponse(assets=[serialize_creative_asset(row) for row in rows])


@platform_router.post("/creative-assets", response_model=PlatformCreativeAssetResponse)
async def create_creative_asset(command: PlatformCreativeAssetCommand) -> PlatformCreativeAssetResponse:
    """Create one creative asset record."""
    row = PlatformCreativeAsset.add(**command.model_dump())
    emit_lifecycle_event(
        event_type="creative_asset.staged",
        lifecycle_stage="ads",
        target_type="creative_asset",
        target_id=row.id,
        summary=f"Staged creative asset {row.id}.",
        payload={"campaign_id": row.campaign_id, "client_id": row.client_id, "asset_type": row.asset_type},
    )
    return serialize_creative_asset(row)


@platform_router.post(
    "/creative-assets/{asset_id}/upload-to-meta",
    response_model=PlatformCreativeAssetUploadResponse,
)
async def upload_creative_asset_to_meta(
    asset_id: str,
    command: PlatformCreativeAssetUploadCommand,
) -> PlatformCreativeAssetUploadResponse:
    """Upload one creative asset to Meta media storage when live writes are allowed."""
    try:
        asset, result = upload_meta_creative_asset(
            asset_id=asset_id,
            ad_account_id=command.ad_account_id,
            live_writes_requested=command.live_writes_requested,
            source="platform_api",
            actor="operator",
        )
    except MetaAdsPublishError as error:
        message = str(error)
        status_code = 404 if message.startswith("Creative asset not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from error
    return PlatformCreativeAssetUploadResponse(
        asset=serialize_creative_asset(asset),
        upload=result.model_dump(mode="json"),
    )


@platform_router.get("/meta-publish-attempts", response_model=PlatformMetaPublishAttemptListResponse)
async def list_meta_publish_attempts(
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformMetaPublishAttemptListResponse:
    """Return Meta publish attempts."""
    rows = PlatformMetaPublishAttempt.list_recent(campaign_id=campaign_id, status=status, limit=limit)
    return PlatformMetaPublishAttemptListResponse(attempts=[serialize_meta_publish_attempt(row) for row in rows])


@platform_router.post("/meta-publish-attempts", response_model=PlatformMetaPublishAttemptResponse)
async def create_meta_publish_attempt(command: PlatformMetaPublishAttemptCommand) -> PlatformMetaPublishAttemptResponse:
    """Stage a Meta publish attempt without live Marketing API writes."""
    try:
        row = PlatformMetaPublishAttempt.add(**command.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    emit_lifecycle_event(
        event_type="meta_publish_attempt.staged",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=row.id,
        summary=f"Staged Meta publish attempt {row.id}.",
        payload={"campaign_id": row.campaign_id, "status": row.status, "approval_status": row.approval_status},
    )
    return serialize_meta_publish_attempt(row)


@platform_router.post(
    "/meta-publish-attempts/{attempt_id}/preflight",
    response_model=PlatformMetaPublishPreflightResponse,
)
async def preflight_meta_publish_attempt_endpoint(
    attempt_id: str,
    command: PlatformMetaPublishPreflightCommand,
) -> PlatformMetaPublishPreflightResponse:
    """Build an ordered Meta execution graph and persist preflight status."""
    try:
        attempt, result = preflight_meta_publish_attempt(
            attempt_id=attempt_id,
            live_writes_requested=command.live_writes_requested,
            source="platform_api",
            actor="operator",
        )
    except MetaAdsPublishError as error:
        message = str(error)
        status_code = 404 if message.startswith("Meta publish attempt not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from error
    return PlatformMetaPublishPreflightResponse(
        attempt=serialize_meta_publish_attempt(attempt),
        preflight=result.model_dump(mode="json"),
    )


@platform_router.post(
    "/meta-publish-attempts/{attempt_id}/approve",
    response_model=PlatformMetaPublishApprovalResponse,
)
async def approve_meta_publish_attempt_endpoint(
    attempt_id: str,
    command: PlatformMetaPublishApprovalCommand,
) -> PlatformMetaPublishApprovalResponse:
    """Apply the audited approval and budget gate before live Meta writes."""
    try:
        attempt, result = approve_meta_publish_attempt(
            attempt_id=attempt_id,
            approved_by=command.approved_by,
            approval_note=command.approval_note,
            approve_live_writes=command.approve_live_writes,
            require_inventory_ready=command.require_inventory_ready,
            max_daily_budget_usd=command.max_daily_budget_usd,
            max_lifetime_budget_usd=command.max_lifetime_budget_usd,
            max_estimated_monthly_budget_usd=command.max_estimated_monthly_budget_usd,
            source="platform_api",
            actor="operator",
        )
    except MetaAdsPublishError as error:
        message = str(error)
        status_code = 404 if message.startswith("Meta publish attempt not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from error
    return PlatformMetaPublishApprovalResponse(
        attempt=serialize_meta_publish_attempt(attempt),
        approval=result.model_dump(mode="json"),
    )


@platform_router.post(
    "/meta-publish-attempts/{attempt_id}/execute",
    response_model=PlatformMetaPublishExecutionResponse,
)
async def execute_meta_publish_attempt_endpoint(
    attempt_id: str,
    command: PlatformMetaPublishExecutionCommand,
) -> PlatformMetaPublishExecutionResponse:
    """Execute approved Meta writes and persist provider IDs."""
    try:
        attempt, result = execute_meta_publish_attempt(
            attempt_id=attempt_id,
            live_writes_requested=command.live_writes_requested,
            source="platform_api",
            actor="operator",
        )
    except MetaAdsPublishError as error:
        message = str(error)
        status_code = 404 if message.startswith("Meta publish attempt not found") else 400
        raise HTTPException(status_code=status_code, detail=message) from error
    return PlatformMetaPublishExecutionResponse(
        attempt=serialize_meta_publish_attempt(attempt),
        execution=result.model_dump(mode="json"),
    )


@platform_router.get("/meta-inventory", response_model=PlatformMetaInventoryListResponse)
async def list_meta_inventory_snapshots(
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> PlatformMetaInventoryListResponse:
    """Return recent read-only Meta inventory snapshots."""
    rows = PlatformMetaInventorySnapshot.list_recent(status=status, limit=limit)
    return PlatformMetaInventoryListResponse(snapshots=[serialize_meta_inventory_snapshot(row) for row in rows])


@platform_router.post("/meta-inventory/sync", response_model=PlatformMetaInventorySyncResponse)
async def sync_meta_inventory_endpoint(command: PlatformMetaInventorySyncCommand) -> PlatformMetaInventorySyncResponse:
    """Read Meta inventory when credentials exist, or persist credential blockers."""
    try:
        snapshot, result = sync_meta_inventory(
            ad_account_id=command.ad_account_id,
            business_id=command.business_id,
            page_ids=command.page_ids,
            include_campaigns=command.include_campaigns,
            include_lead_forms=command.include_lead_forms,
            include_pixels=command.include_pixels,
            include_whatsapp=command.include_whatsapp,
            limit=command.limit,
            source="platform_api",
            actor="operator",
        )
    except MetaInventoryError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return PlatformMetaInventorySyncResponse(
        snapshot=serialize_meta_inventory_snapshot(snapshot),
        result=result.model_dump(mode="json"),
    )


@platform_router.get("/client-updates", response_model=PlatformClientUpdateListResponse)
async def list_client_updates(
    client_id: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformClientUpdateListResponse:
    """Return client status update records."""
    rows = PlatformClientUpdate.list_recent(
        client_id=client_id,
        campaign_id=campaign_id,
        status=status,
        limit=limit,
    )
    return PlatformClientUpdateListResponse(updates=[serialize_client_update(row) for row in rows])


@platform_router.post("/client-updates", response_model=PlatformClientUpdateResponse)
async def create_client_update(command: PlatformClientUpdateCommand) -> PlatformClientUpdateResponse:
    """Create one client update draft/send record."""
    row = PlatformClientUpdate.add(**command.model_dump())
    emit_lifecycle_event(
        event_type="client_update.created",
        lifecycle_stage="client_update",
        target_type="client_update",
        target_id=row.id,
        summary=f"Created client update {row.id}.",
        payload={"client_id": row.client_id, "campaign_id": row.campaign_id, "status": row.status},
    )
    return serialize_client_update(row)


@platform_router.get("/human-questions", response_model=PlatformHumanQuestionListResponse)
async def list_human_questions(
    status: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> PlatformHumanQuestionListResponse:
    """Return human escalation questions."""
    rows = PlatformHumanQuestion.list_recent(
        status=status,
        target_type=target_type,
        target_id=target_id,
        limit=limit,
    )
    return PlatformHumanQuestionListResponse(questions=[serialize_human_question(row) for row in rows])


@platform_router.post("/human-questions", response_model=PlatformHumanQuestionResponse)
async def create_human_question(command: PlatformHumanQuestionCommand) -> PlatformHumanQuestionResponse:
    """Create one human escalation question without sending WhatsApp yet."""
    row = PlatformHumanQuestion.add(**command.model_dump())
    emit_lifecycle_event(
        event_type="human_question.created",
        lifecycle_stage="human_escalation",
        target_type="human_question",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Created human question {row.id}.",
        payload={
            "workflow": row.workflow,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "trying_to_do": row.trying_to_do,
        },
    )
    return serialize_human_question(row)


@platform_router.post("/human-questions/{question_id}/answer", response_model=PlatformHumanQuestionResponse)
async def answer_human_question(
    question_id: str,
    command: PlatformHumanQuestionAnswerCommand,
) -> PlatformHumanQuestionResponse:
    """Store the answer for one human escalation question."""
    row = PlatformHumanQuestion.answer(
        question_id,
        answer_text=command.answer_text,
        status=command.status,
        promoted_to_memory_at=command.promoted_to_memory_at,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Human question not found.")
    emit_lifecycle_event(
        event_type="human_question.answered",
        lifecycle_stage="human_escalation",
        target_type="human_question",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Answered human question {row.id}.",
        payload={"target_type": row.target_type, "target_id": row.target_id, "status": row.status},
    )
    return serialize_human_question(row)
