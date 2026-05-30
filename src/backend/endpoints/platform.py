"""Platform lifecycle and observability endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.database import (
    PlatformAdCampaign,
    PlatformClientProfile,
    PlatformClientUpdate,
    PlatformCreativeAsset,
    PlatformEvent,
    PlatformHumanQuestion,
    PlatformMeeting,
    PlatformMetaPublishAttempt,
)

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
    calendar_event_id: str = ""
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
    calendar_event_id: str
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
    failure_reason: str
    created_at: datetime
    updated_at: datetime


class PlatformCreativeAssetListResponse(BaseModel):
    """Creative asset list response."""

    assets: list[PlatformCreativeAssetResponse]


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
        calendar_event_id=row.calendar_event_id,
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
        calendar_event_id=command.calendar_event_id,
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
    row = PlatformMetaPublishAttempt.add(**command.model_dump())
    emit_lifecycle_event(
        event_type="meta_publish_attempt.staged",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=row.id,
        summary=f"Staged Meta publish attempt {row.id}.",
        payload={"campaign_id": row.campaign_id, "status": row.status, "approval_status": row.approval_status},
    )
    return serialize_meta_publish_attempt(row)


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
