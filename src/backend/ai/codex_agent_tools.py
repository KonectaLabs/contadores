"""Approved product tools callable by autonomous Codex runs."""

from __future__ import annotations

import json
import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from backend.ai.codex_guard import assert_codex_enabled_for_target
from backend.ai.codex_agent_runtime import (
    CodexAgentToolSpec,
    agent_memory_path,
    read_agent_memory_text,
    run_context_dir,
    write_jsonl,
)
from backend.client_lead_config import (
    get_client_lead_sources_config_path,
    get_client_lead_sources_seed_config_path,
    list_file_backed_client_lead_sources,
)
from backend.database import (
    AgentToolCall,
    CLIENT_LEAD_DEFAULT_COLUMN_MAPPING,
    CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE,
    CLIENT_LEAD_DEFAULT_TEMPLATE_NAME,
    ClientLeadDelivery,
    ClientLeadSource,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    PlatformAdCampaign,
    PlatformClientProfile,
    PlatformClientUpdate,
    PlatformCreativeAsset,
    PlatformEvent,
    PlatformHumanQuestion,
    PlatformMeeting,
    PlatformMetaInventorySnapshot,
    PlatformMetaPublishAttempt,
    ScheduledAgentTask,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationClientStatus,
    WorkstationClientWorkType,
)
from backend.calendar_events import CalendarSchedulingError, schedule_meeting_calendar_event
from backend.funnel_config import (
    FunnelDefinition,
    FunnelStrategyDefinition,
    get_funnel,
    get_funnels_config_path,
    get_funnels_seed_config_path,
    list_funnels_with_config_errors,
    slugify_funnel_id,
    upsert_funnel,
)
from backend.platform_profile_extraction import (
    PlatformProfileExtractionError,
    extract_client_profile_from_meeting as save_client_profile_from_meeting,
)
from backend.meta_ads_publish import MetaAdsPublishError, approve_meta_publish_attempt, preflight_meta_publish_attempt
from backend.meta_ads_inventory import MetaInventoryError, sync_meta_inventory


DEFAULT_AGENT_SEQUENCE_STEP = "codex_agent"
AGENT_TARGET_PATTERN = (
    "^(lead|workstation_client|funnel|client_lead_source|meeting|client_profile|"
    "ad_campaign|creative_asset|meta_publish_attempt|client_update|human_question|client|platform)$"
)
AGENT_MEMORY_TARGET_PATTERN = (
    "^(lead|workstation_client|funnel|client|client_profile|ad_campaign|"
    "creative_asset|human_question|platform)$"
)


class AgentToolError(RuntimeError):
    """Raised when a tool request is valid JSON but not allowed."""


class LeadToolArgs(BaseModel):
    """Base args for lead tools."""

    lead_id: str = Field(min_length=1)


class ClientToolArgs(BaseModel):
    """Base args for Workstation client tools."""

    client_id: str = Field(min_length=1)


class SendWhatsAppTextArgs(LeadToolArgs):
    """Arguments for sending a text message."""

    text: str = Field(min_length=1, max_length=4000)
    sequence_step: str = DEFAULT_AGENT_SEQUENCE_STEP
    dispatch_after_minutes: int = Field(default=0, ge=0, le=60 * 24 * 30)
    idempotency_key: str | None = None


class SendWhatsAppMediaArgs(SendWhatsAppTextArgs):
    """Arguments for sending a media message."""

    media_type: str = Field(min_length=1)
    media_path: str = Field(min_length=1)
    media_caption: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None


class ScheduleFollowupArgs(BaseModel):
    """Arguments for a future agent wake-up."""

    target_type: str = Field(pattern=AGENT_TARGET_PATTERN)
    target_id: str = Field(min_length=1)
    run_after_minutes: int = Field(ge=1, le=60 * 24 * 30)
    reason: str = Field(min_length=1, max_length=1000)
    instruction: str = Field(min_length=1, max_length=4000)
    idempotency_key: str | None = None


class ScheduleHeartbeatArgs(ScheduleFollowupArgs):
    """Arguments for a future self-directed agent heartbeat."""


class AgentMemoryTargetArgs(BaseModel):
    """Arguments for reading one target memory file."""

    target_type: str = Field(pattern=AGENT_MEMORY_TARGET_PATTERN)
    target_id: str = Field(min_length=1)
    limit_chars: int = Field(default=12000, ge=100, le=50000)


class WriteAgentMemoryArgs(BaseModel):
    """Arguments for appending durable memory for a lead or client."""

    target_type: str = Field(pattern=AGENT_MEMORY_TARGET_PATTERN)
    target_id: str = Field(min_length=1)
    note: str = Field(min_length=1, max_length=8000)
    title: str = Field(default="", max_length=160)
    importance: str = Field(default="normal", pattern="^(low|normal|high)$")


class ListAgentToolCallsArgs(BaseModel):
    """Arguments for reading audited tool calls in the current or another run."""

    run_id: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, pattern="^(succeeded|failed)$")


class ReadPlatformConfigArgs(BaseModel):
    """Arguments for reading current platform configuration."""

    include_schema: bool = False


class UpsertFunnelConfigArgs(BaseModel):
    """Arguments for replacing one full funnel definition."""

    funnel: FunnelDefinition
    reason: str = Field(min_length=1, max_length=1000)


class ConfigureTextOfferFunnelArgs(BaseModel):
    """High-level args for creating a mission-style text offer funnel."""

    funnel_id: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    template_language: str | None = None
    sheet_url: str | None = None
    sheet_gid: str | None = None
    sheet_source_filter: str | None = None
    sheet_poll_seconds: int | None = Field(default=None, ge=30)
    opener_text: str | None = None
    opener_template_name: str | None = None
    opener_followup_text: str | None = None
    opener_followup_template_name: str | None = None
    manual_ping_text: str | None = None
    manual_ping_template_name: str | None = None
    offer_price_usd: int | None = Field(default=None, ge=0)
    offer_payment_model: str | None = Field(default=None, pattern="^(monthly|one_time|custom)$")
    offer_summary: str | None = None
    offer_text: str | None = None
    offer_includes_website: bool | None = None
    offer_version: str | None = None
    default_campaign_count: int | None = Field(default=None, ge=0)
    default_daily_ad_budget_usd: int | None = Field(default=None, ge=0)
    video_check_text: str | None = None
    calendly_intro_text: str | None = None
    calendly_base_url: str | None = None
    alert_emails: list[str] | None = None
    whatsapp_referral_source_ids: list[str] | None = None
    preserve_other_loom_strategies: bool = False
    reason: str = Field(default="Configured by Codex agent.", max_length=1000)


class UpsertClientLeadDeliverySourceArgs(BaseModel):
    """Arguments for creating one Client Lead Delivery source without the UI."""

    source_id: str | None = Field(default=None, max_length=120)
    label: str = Field(min_length=1, max_length=160)
    enabled: bool = True
    sheet_url: str = ""
    sheet_gid: str | None = None
    sheet_tab_name: str | None = None
    sheet_poll_seconds: int = Field(default=10, ge=5)
    recipient_name: str | None = None
    recipient_phone: str = ""
    template_name: str | None = CLIENT_LEAD_DEFAULT_TEMPLATE_NAME
    template_language: str | None = CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE
    column_mapping: dict[str, str] = Field(default_factory=lambda: dict(CLIENT_LEAD_DEFAULT_COLUMN_MAPPING))
    context_field_mapping: dict[str, str] = Field(default_factory=dict)
    reason: str = Field(default="Configured by Codex agent.", max_length=1000)


class ValidatePlatformConfigArgs(BaseModel):
    """Arguments for validating operator-facing setup state."""

    include_disabled: bool = False


class CreatePlatformMeetingArgs(BaseModel):
    """Arguments for recording meeting scheduling state without a UI."""

    lead_id: str = ""
    client_id: str = ""
    funnel_id: str = ""
    status: str = "collecting_details"
    lead_email: str = ""
    timezone: str = ""
    requested_day: str = ""
    requested_time: str = ""
    calendar_event_id: str = ""
    context_summary: str = Field(default="", max_length=4000)
    transcript_text: str = Field(default="", max_length=50000)
    transcript_path: str = ""
    extracted_profile: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    scheduled_at: datetime | None = None


class SchedulePlatformMeetingArgs(BaseModel):
    """Arguments for building or creating a Google Calendar meeting event."""

    meeting_id: str = Field(min_length=1)
    calendar_id: str = ""
    internal_attendees: list[str] = Field(default_factory=list)
    duration_minutes: int = Field(default=15, ge=5, le=180)
    create_google_meet: bool = False
    live_writes_requested: bool = False
    send_updates: Literal["all", "externalOnly", "none"] = "all"


class AttachMeetingTranscriptArgs(BaseModel):
    """Arguments for attaching conversion transcript context."""

    meeting_id: str = Field(min_length=1)
    transcript_text: str = Field(default="", max_length=50000)
    transcript_path: str = ""
    extracted_profile: dict[str, Any] = Field(default_factory=dict)
    status: str = "transcript_received"


class ExtractClientProfileFromMeetingArgs(BaseModel):
    """Arguments for extracting ad-ready client knowledge from a transcript."""

    meeting_id: str = Field(min_length=1)
    client_id: str = ""
    lead_id: str = ""
    funnel_id: str = ""
    status: str = "draft"
    existing_context: dict[str, Any] = Field(default_factory=dict)


class UpsertClientProfileArgs(BaseModel):
    """Arguments for upserting reviewed post-conversion client knowledge."""

    client_id: str = Field(min_length=1)
    lead_id: str = ""
    funnel_id: str = ""
    status: str = "draft"
    source_meeting_id: str = ""
    business_summary: str = Field(default="", max_length=8000)
    offer_summary: str = Field(default="", max_length=8000)
    market_summary: str = Field(default="", max_length=8000)
    objections: list[Any] = Field(default_factory=list)
    segments: list[Any] = Field(default_factory=list)
    knowledge: dict[str, Any] = Field(default_factory=dict)


class StageAdCampaignArgs(BaseModel):
    """Arguments for staging an ad campaign before Meta publishing."""

    client_id: str = ""
    funnel_id: str = ""
    status: str = "draft"
    objective: str = Field(default="", max_length=2000)
    budget_daily_usd: int | None = Field(default=None, ge=0)
    budget_total_usd: int | None = Field(default=None, ge=0)
    budget_currency: str = "USD"
    target_segments: list[Any] = Field(default_factory=list)
    angles: list[Any] = Field(default_factory=list)
    approval_status: str = "not_requested"
    idempotency_key: str | None = None


class StageCreativeAssetArgs(BaseModel):
    """Arguments for recording a generated or staged creative asset."""

    campaign_id: str = ""
    client_id: str = ""
    status: str = "draft"
    asset_type: str = "image"
    prompt: str = Field(default="", max_length=12000)
    file_path: str = ""
    dimensions: str = ""
    source_refs: list[Any] = Field(default_factory=list)
    meta_creative_id: str = ""
    failure_reason: str = Field(default="", max_length=4000)


class StageMetaPublishAttemptArgs(BaseModel):
    """Arguments for staging a Meta Marketing API publish attempt."""

    campaign_id: str = ""
    status: str = "staged"
    approval_status: str = "pending"
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    error: str = Field(default="", max_length=12000)
    idempotency_key: str | None = None


class MetaLeadDestinationPlan(BaseModel):
    """Lead destination for a staged Meta publish plan."""

    destination_type: str = Field(default="whatsapp", pattern="^(whatsapp|instant_form|landing_page)$")
    page_id: str = ""
    instagram_actor_id: str = ""
    whatsapp_phone_number_id: str = ""
    lead_form_id: str = ""
    landing_page_url: str = ""


class MetaCreativePlan(BaseModel):
    """Creative reference and copy for one Meta ad."""

    name: str = ""
    creative_asset_id: str = ""
    asset_file_path: str = ""
    meta_creative_id: str = ""
    image_hash: str = ""
    video_id: str = ""
    primary_text: str = Field(default="", max_length=4000)
    headline: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=1000)
    call_to_action: str = "WHATSAPP_MESSAGE"
    destination_url: str = ""


class MetaAdPlan(BaseModel):
    """One ad inside a staged Meta ad set."""

    name: str = ""
    status: str = "PAUSED"
    creative: MetaCreativePlan = Field(default_factory=MetaCreativePlan)


class MetaAdSetPlan(BaseModel):
    """One ad set inside a staged Meta campaign."""

    name: str = ""
    status: str = "PAUSED"
    budget_daily_usd: int | None = Field(default=None, ge=0)
    budget_total_usd: int | None = Field(default=None, ge=0)
    optimization_goal: str = "LEAD_GENERATION"
    billing_event: str = "IMPRESSIONS"
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"
    targeting: dict[str, Any] = Field(default_factory=dict)
    placements: list[str] = Field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    ads: list[MetaAdPlan] = Field(default_factory=list)


class StageMetaPublishPlanArgs(BaseModel):
    """Arguments for staging a first-class Meta campaign/adset/ad plan."""

    campaign_id: str = ""
    client_id: str = ""
    funnel_id: str = ""
    ad_account_id: str = ""
    campaign_name: str = ""
    objective: str = "OUTCOME_LEADS"
    buying_type: str = "AUCTION"
    special_ad_categories: list[str] = Field(default_factory=list)
    budget_currency: str = "USD"
    destination: MetaLeadDestinationPlan = Field(default_factory=MetaLeadDestinationPlan)
    ad_sets: list[MetaAdSetPlan] = Field(default_factory=list)
    notes: str = Field(default="", max_length=4000)
    approval_status: str = "pending"
    idempotency_key: str | None = None


class PreflightMetaPublishPlanArgs(BaseModel):
    """Arguments for checking a staged Meta plan before live publishing."""

    attempt_id: str = Field(min_length=1)
    live_writes_requested: bool = False


class ApproveMetaPublishPlanArgs(BaseModel):
    """Arguments for the audited Meta publish approval gate."""

    attempt_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)
    approval_note: str = Field(default="", max_length=2000)
    approve_live_writes: bool = False
    require_inventory_ready: bool = True
    max_daily_budget_usd: int = Field(default=50, ge=1)
    max_lifetime_budget_usd: int = Field(default=1500, ge=0)
    max_estimated_monthly_budget_usd: int = Field(default=1500, ge=1)


class SyncMetaInventoryArgs(BaseModel):
    """Arguments for reading Meta account/page/form inventory."""

    ad_account_id: str = ""
    business_id: str = ""
    page_ids: list[str] = Field(default_factory=list)
    include_campaigns: bool = True
    include_lead_forms: bool = True
    include_pixels: bool = True
    include_whatsapp: bool = True
    limit: int = Field(default=50, ge=1, le=200)


class CreateClientUpdateArgs(BaseModel):
    """Arguments for drafting or recording a 24-hour client update."""

    client_id: str = ""
    campaign_id: str = ""
    status: str = "draft"
    summary_text: str = Field(default="", max_length=4000)
    leads_count: int = Field(default=0, ge=0)
    blockers: list[Any] = Field(default_factory=list)
    next_action: str = Field(default="", max_length=2000)
    whatsapp_message_id: int | None = None
    window_started_at: datetime | None = None
    window_ended_at: datetime | None = None


class AskHumanQuestionArgs(BaseModel):
    """Arguments for raising a Facundo/operator doubt without blocking forever."""

    workflow: str = ""
    target_type: str = Field(default="", max_length=80)
    target_id: str = ""
    funnel_id: str = ""
    context_summary: str = Field(default="", max_length=4000)
    trying_to_do: str = Field(default="", max_length=2000)
    question: str = Field(min_length=1, max_length=4000)
    options: list[Any] = Field(default_factory=list)
    default_action: str = Field(default="", max_length=2000)
    timeout_minutes: int = Field(default=4, ge=1, le=60 * 24)
    timeout_at: datetime | None = None
    whatsapp_message_id: str = ""


class AnswerHumanQuestionArgs(BaseModel):
    """Arguments for storing a Facundo/operator answer and optional memory."""

    question_id: str = Field(min_length=1)
    answer_text: str = Field(min_length=1, max_length=4000)
    status: str = "answered"
    promote_to_memory: bool = True
    memory_target_type: str = Field(default="", max_length=80)
    memory_target_id: str = ""
    memory_title: str = Field(default="Facundo answer", max_length=160)


class CheckDomainAvailabilityArgs(BaseModel):
    """Arguments for checking whether a domain can be registered."""

    domain: str = Field(min_length=4, max_length=253)


class MoveLeadToFunnelArgs(LeadToolArgs):
    """Arguments for moving a lead to another funnel and stage."""

    funnel_id: str = Field(min_length=1, max_length=120)
    stage: str = Field(
        default=ContadoresLeadStage.AWAITING_INITIAL_REPLY.value,
        pattern="^(awaiting_initial_reply|awaiting_video_reply|needs_human|calendly_sent|booked|closed|archived)$",
    )
    reason: str = Field(min_length=1, max_length=4000)


class SetLeadTagsArgs(LeadToolArgs):
    """Arguments for replacing or appending operator tags."""

    tags: list[str] = Field(default_factory=list, min_length=1, max_length=20)
    mode: str = Field(default="append", pattern="^(append|replace)$")


class UpdateLeadStateArgs(LeadToolArgs):
    """Arguments for updating a lead state."""

    stage: str | None = None
    automation_paused: bool | None = None
    reason: str = Field(default="", max_length=4000)
    classification_label: str = Field(default="codex_agent")


class HandoffHumanArgs(LeadToolArgs):
    """Arguments for handing a lead to a person."""

    reason: str = Field(min_length=1, max_length=4000)
    optional_message: str = Field(default="", max_length=4000)


class CreateOrGetSoloPageClientArgs(LeadToolArgs):
    """Arguments for creating a Workstation solo-page client."""

    offer_price_usd: int | None = Field(default=None, ge=1)


class GenerateOrReviseSoloPageArgs(ClientToolArgs):
    """Arguments for page generation or revision."""

    instruction: str = Field(min_length=1, max_length=8000)
    revision: bool = True
    source_message_ids: list[int] = Field(default_factory=list)


class QueueWorkstationDeliverablesArgs(ClientToolArgs):
    """Arguments for queueing Workstation deliverables."""

    version: str = Field(min_length=1)
    sequence_step: str = "workstation_revision_video"


class SendWorkstationPublicPageLinkArgs(ClientToolArgs):
    """Arguments for sending the public trial page URL."""

    text: str | None = Field(default=None, max_length=4000)
    dispatch_after_minutes: int = Field(default=0, ge=0, le=60 * 24 * 30)
    idempotency_key: str | None = None


class MarkPreviewApprovedArgs(ClientToolArgs):
    """Arguments for marking a Workstation preview approved."""

    reason: str = Field(default="El cliente aprobo el boceto.", max_length=4000)


class WriteProgressArgs(ClientToolArgs):
    """Arguments for adding Workstation progress."""

    message: str = Field(min_length=1, max_length=2000)


def tool_specs() -> list[CodexAgentToolSpec]:
    """Return the toolbelt exposed to Codex."""
    specs: list[tuple[str, str, type[BaseModel]]] = [
        (
            "read_platform_config",
            "Read funnels, delivery sources, config file paths, validation issues, and optional schemas.",
            ReadPlatformConfigArgs,
        ),
        (
            "validate_platform_config",
            "Validate funnel and delivery setup before enabling automation.",
            ValidatePlatformConfigArgs,
        ),
        (
            "configure_text_offer_funnel",
            "Create or update a text-first $599-style funnel without using the UI.",
            ConfigureTextOfferFunnelArgs,
        ),
        (
            "upsert_funnel_config",
            "Create or replace one full validated funnel definition without using the UI.",
            UpsertFunnelConfigArgs,
        ),
        (
            "upsert_client_lead_delivery_source",
            "Create or update one Google Sheets to WhatsApp client lead delivery source without using the UI.",
            UpsertClientLeadDeliverySourceArgs,
        ),
        (
            "create_platform_meeting",
            "Record meeting scheduling or handoff state without using the UI.",
            CreatePlatformMeetingArgs,
        ),
        (
            "schedule_platform_meeting",
            "Build or create the Google Calendar event for a meeting with attendees, timezone, context, and credential blockers.",
            SchedulePlatformMeetingArgs,
        ),
        (
            "attach_meeting_transcript",
            "Attach call transcript context and extracted client profile fields to a meeting record.",
            AttachMeetingTranscriptArgs,
        ),
        (
            "extract_client_profile_from_meeting_transcript",
            "Run DSPy transcript extraction and save a draft client profile for ads and Meta planning.",
            ExtractClientProfileFromMeetingArgs,
        ),
        (
            "upsert_client_profile",
            "Create or update reviewed post-conversion client knowledge for ads, delivery, and support.",
            UpsertClientProfileArgs,
        ),
        (
            "stage_ad_campaign",
            "Stage an ad campaign plan before client approval or Meta publishing.",
            StageAdCampaignArgs,
        ),
        (
            "stage_creative_asset",
            "Record a generated or staged ad creative asset and its source prompt/context.",
            StageCreativeAssetArgs,
        ),
        (
            "stage_meta_publish_attempt",
            "Stage a Meta Marketing API publish request without making live external writes.",
            StageMetaPublishAttemptArgs,
        ),
        (
            "stage_meta_publish_plan",
            "Stage a typed Meta Campaign -> Ad Set -> Ad/Creative plan and preflight checklist.",
            StageMetaPublishPlanArgs,
        ),
        (
            "preflight_meta_publish_plan",
            "Build the ordered Meta publish execution graph and persist preflight state without live writes by default.",
            PreflightMetaPublishPlanArgs,
        ),
        (
            "approve_meta_publish_plan",
            "Apply the explicit Meta publish approval gate with budget caps, inventory readiness, idempotency, and PAUSED-start checks.",
            ApproveMetaPublishPlanArgs,
        ),
        (
            "sync_meta_inventory",
            "Read Meta ad accounts, pages, forms, pixels, WhatsApp numbers, and campaigns when credentials exist.",
            SyncMetaInventoryArgs,
        ),
        (
            "create_client_update",
            "Draft or record a 24-hour client update with lead counts, blockers, and next action.",
            CreateClientUpdateArgs,
        ),
        (
            "ask_human_question",
            "Create a bounded Facundo/operator doubt record with context, options, and default action.",
            AskHumanQuestionArgs,
        ),
        (
            "answer_human_question",
            "Store an operator answer to a doubt and optionally promote it to agent memory.",
            AnswerHumanQuestionArgs,
        ),
        ("get_lead_context", "Read lead state and recent WhatsApp messages.", LeadToolArgs),
        ("send_whatsapp_text", "Queue one WhatsApp text message, optionally delayed.", SendWhatsAppTextArgs),
        ("send_whatsapp_media", "Queue one WhatsApp media message, optionally delayed.", SendWhatsAppMediaArgs),
        ("schedule_followup", "Create a DB-backed future agent wake-up.", ScheduleFollowupArgs),
        (
            "schedule_heartbeat",
            "Schedule a future self-directed agent run with instructions for your future self.",
            ScheduleHeartbeatArgs,
        ),
        ("read_agent_memory", "Read durable Markdown memory for this lead or Workstation client.", AgentMemoryTargetArgs),
        ("write_agent_memory", "Append a concise durable memory note for future Codex runs.", WriteAgentMemoryArgs),
        ("list_agent_tool_calls", "Inspect audited tool calls for the current or a specified run.", ListAgentToolCallsArgs),
        (
            "check_domain_availability",
            "Check whether a domain exists and return public no-auth registrar price estimates when available.",
            CheckDomainAvailabilityArgs,
        ),
        ("move_lead_to_funnel", "Move a lead to another funnel and lifecycle stage.", MoveLeadToFunnelArgs),
        ("set_lead_tags", "Append or replace operator tags on a lead.", SetLeadTagsArgs),
        ("update_lead_state", "Update stage or automation pause state for a lead.", UpdateLeadStateArgs),
        ("handoff_human", "Pause automation and hand a lead to a human.", HandoffHumanArgs),
        (
            "create_or_get_solo_page_client",
            "Create or fetch the Workstation solo-page client for a lead.",
            CreateOrGetSoloPageClientArgs,
        ),
        ("get_workstation_context", "Read Workstation client state, folder, versions, and messages.", ClientToolArgs),
        ("write_progress", "Append one visible Workstation progress line.", WriteProgressArgs),
        ("generate_or_revise_solo_page", "Create or revise the client's static solo-page.", GenerateOrReviseSoloPageArgs),
        ("queue_workstation_deliverables", "Queue preview/media deliverables from a page version.", QueueWorkstationDeliverablesArgs),
        (
            "send_workstation_public_page_link",
            "Send the stable public trial page URL for this Workstation client.",
            SendWorkstationPublicPageLinkArgs,
        ),
        ("mark_preview_approved", "Mark the current Workstation preview approved and hand off.", MarkPreviewApprovedArgs),
    ]
    return [
        CodexAgentToolSpec(
            name=name,
            description=description,
            schema=model.model_json_schema(),
        )
        for name, description, model in specs
    ]


def _lead_or_error(lead_id: str) -> ContadoresLead:
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise AgentToolError(f"Lead not found: {lead_id}")
    return lead


def _client_or_error(client_id: str) -> WorkstationClient:
    client = WorkstationClient.get_by_id(client_id)
    if client is None:
        raise AgentToolError(f"Workstation client not found: {client_id}")
    return client


def _dispatch_after(minutes: int) -> datetime | None:
    if minutes <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _clean_text(value: str | None) -> str:
    """Return compact freeform text."""
    return " ".join(str(value or "").split()).strip()


def _clean_multiline(value: str | None) -> str:
    """Return stripped text while preserving intentional line breaks."""
    return str(value or "").strip()


def _first_non_empty(*values: str | None, default: str = "") -> str:
    """Return the first non-empty compact text value."""
    for value in values:
        clean_value = _clean_multiline(value)
        if clean_value:
            return clean_value
    return default


def _default_offer_summary(price: int) -> str:
    """Return the default mission offer summary."""
    if price > 0:
        return (
            f"Marketing y anuncios para recibir interesados directo al WhatsApp por {price} USD mensuales; "
            "sitio incluido si hace falta."
        )
    return "Marketing y anuncios para recibir interesados directo al WhatsApp; sitio incluido si hace falta."


def _default_offer_text(price: int) -> str:
    """Return the default text-only mission offer."""
    price_text = f"{price} USD mensuales" if price > 0 else "un plan mensual"
    return (
        f"Son {price_text}. A cambio recibis oportunidades de clientes potenciales directo a tu WhatsApp. "
        "Eso lo logramos con una pagina profesional y campanas enfocadas. "
        "Si te interesa, lo vemos en una llamada corta y revisamos si tiene sentido para tu caso."
    )


def _default_opener_text(label: str) -> str:
    """Return a safe disabled-funnel opener default."""
    return (
        "Hola {nombre}, vi que dejaste tus datos para recibir mas informacion "
        f"sobre la propuesta de {label}. Te escribo para contarte rapido."
    )


def _default_followup_text(label: str) -> str:
    """Return a safe disabled-funnel follow-up default."""
    return f"Hola {{nombre}}, te escribo de vuelta por la propuesta de {label}. Te interesa que te cuente?"


def _funnel_payload(funnel: FunnelDefinition) -> dict[str, Any]:
    """Serialize a funnel with only agent-useful fields."""
    return {
        "id": funnel.id,
        "label": funnel.label,
        "kind": funnel.kind,
        "enabled": funnel.enabled,
        "offer_price_usd": funnel.offer_price_usd,
        "offer_payment_model": funnel.offer_payment_model,
        "offer_summary": funnel.offer_summary,
        "offer_includes_website": funnel.offer_includes_website,
        "default_campaign_count": funnel.default_campaign_count,
        "default_daily_ad_budget_usd": funnel.default_daily_ad_budget_usd,
        "sheet_url_configured": bool(funnel.sheet_url),
        "sheet_gid": funnel.sheet_gid,
        "template_language": funnel.template_language,
        "opener_template_name": funnel.opener_template_name,
        "manual_ping_template_name": funnel.manual_ping_template_name,
        "calendly_base_url_configured": bool(funnel.calendly_base_url),
        "alert_emails": funnel.alert_emails,
        "whatsapp_referral_source_ids": funnel.whatsapp_referral_source_ids,
        "strategies": [
            {
                "step": strategy.step,
                "id": strategy.id,
                "label": strategy.label,
                "weight": strategy.weight,
                "delivery": strategy.delivery,
                "sequence_step": strategy.sequence_step,
                "has_message_text": bool(strategy.message_text),
                "media_type": strategy.media_type,
                "media_path": strategy.media_path,
            }
            for strategy in funnel.strategies
        ],
        "issues": _funnel_readiness_issues(funnel),
    }


def _client_source_payload(source: ClientLeadSource) -> dict[str, Any]:
    """Serialize a Client Lead Delivery source for agents."""
    counts = ClientLeadDelivery.count_by_status_for_sources().get(source.id, {})
    return {
        "id": source.id,
        "label": source.label,
        "enabled": source.enabled,
        "sheet_url_configured": bool(source.sheet_url),
        "sheet_gid": source.sheet_gid,
        "sheet_tab_name": source.sheet_tab_name,
        "sheet_poll_seconds": source.sheet_poll_seconds,
        "recipient_name": source.recipient_name,
        "recipient_phone_configured": bool(source.recipient_phone),
        "normalized_recipient_phone": source.normalized_recipient_phone,
        "template_name": source.template_name,
        "template_language": source.template_language,
        "context_field_mapping": source.context_field_mapping,
        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
        "last_sync_status": source.last_sync_status,
        "counts": counts,
        "issues": _client_source_readiness_issues(source),
    }


def _funnel_readiness_issues(funnel: FunnelDefinition) -> list[str]:
    """Return setup issues that matter before a funnel can run safely."""
    issues: list[str] = []
    if funnel.kind != "campaign":
        return issues
    if not funnel.sheet_url and not funnel.whatsapp_referral_source_ids:
        issues.append("Configure sheet_url/sheet_gid or whatsapp_referral_source_ids.")
    if funnel.sheet_url and not funnel.sheet_gid:
        issues.append("Configure sheet_gid for the Google Sheet.")
    if not funnel.strategies:
        issues.append("Configure at least one offer strategy.")
    if not any(
        (strategy.delivery == "text" and strategy.message_text.strip())
        or (strategy.delivery in {"video", "link"} and (strategy.media_path or strategy.message_text or funnel.loom_url))
        for strategy in funnel.strategies
    ):
        issues.append("Configure a text offer or media/link offer strategy.")
    if funnel.sheet_url and not funnel.opener_template_name:
        issues.append("Configure opener_template_name for sheet-imported leads.")
    if not funnel.video_check_text:
        issues.append("Configure offer follow-up text.")
    if not funnel.calendly_intro_text:
        issues.append("Configure meeting handoff text.")
    if not funnel.alert_emails:
        issues.append("Configure alert_emails for human handoff/failures.")
    return issues


def _client_source_readiness_issues(source: ClientLeadSource) -> list[str]:
    """Return setup issues for a delivery source."""
    issues: list[str] = []
    if not source.sheet_url:
        issues.append("Configure sheet_url.")
    if not source.sheet_gid and not source.sheet_tab_name:
        issues.append("Configure sheet_gid or sheet_tab_name.")
    if not source.recipient_phone:
        issues.append("Configure recipient_phone.")
    if not source.normalized_recipient_phone:
        issues.append("Recipient phone could not be normalized.")
    if not source.template_name:
        issues.append("Configure template_name.")
    return issues


def read_platform_config(arguments: dict[str, Any]) -> dict[str, Any]:
    args = ReadPlatformConfigArgs.model_validate(arguments)
    funnels, funnel_errors = list_funnels_with_config_errors()
    delivery_entries, delivery_config_errors = list_file_backed_client_lead_sources()
    payload: dict[str, Any] = {
        "funnel_seed_config_path": str(get_funnels_seed_config_path()),
        "funnel_config_path": str(get_funnels_config_path()),
        "funnel_config_errors": funnel_errors,
        "funnels": [_funnel_payload(funnel) for funnel in funnels],
        "delivery_seed_config_path": str(get_client_lead_sources_seed_config_path()),
        "delivery_config_path": str(get_client_lead_sources_config_path()),
        "delivery_config_errors": delivery_config_errors,
        "file_backed_delivery_sources": [entry.model_dump(mode="json") for entry in delivery_entries],
        "delivery_sources": [_client_source_payload(source) for source in ClientLeadSource.list_all()],
        "meta_marketing": {
            "api_version_configured": bool(os.getenv("META_MARKETING_API_VERSION", "").strip()),
            "access_token_configured": bool(
                os.getenv("META_MARKETING_ACCESS_TOKEN", "").strip() or os.getenv("META_ACCESS_TOKEN", "").strip()
            ),
            "live_writes_enabled": os.getenv("META_MARKETING_LIVE_WRITES_ENABLED", "").strip().lower()
            in {"1", "true", "yes", "on"},
        },
        "meta_inventory_snapshots": [
            _meta_inventory_snapshot_payload(snapshot)
            for snapshot in PlatformMetaInventorySnapshot.list_recent(limit=5)
        ],
        "agent_native_tools": [
            "read_platform_config",
            "validate_platform_config",
            "configure_text_offer_funnel",
            "upsert_funnel_config",
            "upsert_client_lead_delivery_source",
            "create_platform_meeting",
            "schedule_platform_meeting",
            "attach_meeting_transcript",
            "extract_client_profile_from_meeting_transcript",
            "upsert_client_profile",
            "stage_ad_campaign",
            "stage_creative_asset",
            "stage_meta_publish_attempt",
            "stage_meta_publish_plan",
            "preflight_meta_publish_plan",
            "approve_meta_publish_plan",
            "sync_meta_inventory",
            "create_client_update",
            "ask_human_question",
            "answer_human_question",
        ],
    }
    if args.include_schema:
        payload["schemas"] = {
            "funnel": FunnelDefinition.model_json_schema(),
            "configure_text_offer_funnel": ConfigureTextOfferFunnelArgs.model_json_schema(),
            "client_lead_delivery_source": UpsertClientLeadDeliverySourceArgs.model_json_schema(),
            "create_platform_meeting": CreatePlatformMeetingArgs.model_json_schema(),
            "schedule_platform_meeting": SchedulePlatformMeetingArgs.model_json_schema(),
            "extract_client_profile_from_meeting_transcript": ExtractClientProfileFromMeetingArgs.model_json_schema(),
            "upsert_client_profile": UpsertClientProfileArgs.model_json_schema(),
            "stage_ad_campaign": StageAdCampaignArgs.model_json_schema(),
            "stage_creative_asset": StageCreativeAssetArgs.model_json_schema(),
            "stage_meta_publish_attempt": StageMetaPublishAttemptArgs.model_json_schema(),
            "stage_meta_publish_plan": StageMetaPublishPlanArgs.model_json_schema(),
            "preflight_meta_publish_plan": PreflightMetaPublishPlanArgs.model_json_schema(),
            "approve_meta_publish_plan": ApproveMetaPublishPlanArgs.model_json_schema(),
            "sync_meta_inventory": SyncMetaInventoryArgs.model_json_schema(),
            "create_client_update": CreateClientUpdateArgs.model_json_schema(),
            "ask_human_question": AskHumanQuestionArgs.model_json_schema(),
            "answer_human_question": AnswerHumanQuestionArgs.model_json_schema(),
        }
    return payload


def validate_platform_config(arguments: dict[str, Any]) -> dict[str, Any]:
    args = ValidatePlatformConfigArgs.model_validate(arguments)
    funnels, funnel_errors = list_funnels_with_config_errors()
    funnel_payloads = [
        _funnel_payload(funnel)
        for funnel in funnels
        if args.include_disabled or funnel.enabled
    ]
    delivery_sources = ClientLeadSource.list_all()
    delivery_payloads = [
        _client_source_payload(source)
        for source in delivery_sources
        if args.include_disabled or source.enabled
    ]
    issues = [
        {"target_type": "funnel", "target_id": funnel["id"], "issues": funnel["issues"]}
        for funnel in funnel_payloads
        if funnel["issues"]
    ]
    issues.extend(
        {
            "target_type": "client_lead_source",
            "target_id": source["id"],
            "issues": source["issues"],
        }
        for source in delivery_payloads
        if source["issues"]
    )
    for error in funnel_errors:
        issues.append({"target_type": "funnel_config", "target_id": str(get_funnels_config_path()), "issues": [error]})
    return {
        "ok": not issues,
        "issues": issues,
        "funnels_checked": len(funnel_payloads),
        "delivery_sources_checked": len(delivery_payloads),
    }


def upsert_funnel_config(arguments: dict[str, Any]) -> dict[str, Any]:
    args = UpsertFunnelConfigArgs.model_validate(arguments)
    saved = upsert_funnel(args.funnel)
    PlatformEvent.add(
        event_type="platform.funnel_upserted",
        lifecycle_stage="configuration",
        target_type="funnel",
        target_id=saved.id,
        funnel_id=saved.id,
        source="codex_agent_tool",
        actor="agent",
        summary=f"Upserted funnel {saved.id}.",
        payload={"reason": args.reason, "config_path": str(get_funnels_config_path()), "enabled": saved.enabled},
    )
    return {"saved": True, "funnel": _funnel_payload(saved), "config_path": str(get_funnels_config_path())}


def configure_text_offer_funnel(arguments: dict[str, Any]) -> dict[str, Any]:
    args = ConfigureTextOfferFunnelArgs.model_validate(arguments)
    funnel_id = slugify_funnel_id(args.funnel_id)
    existing = get_funnel(funnel_id)
    label = _first_non_empty(args.label, existing.label if existing else None, default=funnel_id.replace("-", " ").title())
    offer_price = args.offer_price_usd if args.offer_price_usd is not None else (existing.offer_price_usd if existing else 599)
    offer_payment_model = args.offer_payment_model or (existing.offer_payment_model if existing else "monthly")
    offer_summary = _first_non_empty(
        args.offer_summary,
        existing.offer_summary if existing else None,
        default=_default_offer_summary(offer_price),
    )
    offer_text = _first_non_empty(args.offer_text, default=_default_offer_text(offer_price))
    strategy_id = f"text_offer_{offer_price}" if offer_price > 0 else "text_offer"
    text_strategy = FunnelStrategyDefinition(
        step="loom",
        id=strategy_id,
        label=f"Text offer {offer_price}" if offer_price > 0 else "Text offer",
        weight=100,
        delivery="text",
        sequence_step="text_offer",
        message_text=offer_text,
        media_type=None,
        media_path=None,
        media_caption=None,
    )
    existing_strategies = existing.strategies if existing else []
    if args.preserve_other_loom_strategies:
        strategies = [strategy for strategy in existing_strategies if strategy.id != text_strategy.id]
    else:
        strategies = [strategy for strategy in existing_strategies if strategy.step != "loom"]
    strategies.append(text_strategy)

    saved = upsert_funnel(
        FunnelDefinition(
            id=funnel_id,
            label=label,
            kind="campaign",
            enabled=args.enabled if args.enabled is not None else (existing.enabled if existing else False),
            offer_version=_first_non_empty(
                args.offer_version,
                existing.offer_version if existing else None,
                default="mission-2026-05-30",
            ),
            offer_price_usd=offer_price,
            offer_payment_model=offer_payment_model,  # type: ignore[arg-type]
            offer_summary=offer_summary,
            offer_includes_website=(
                args.offer_includes_website
                if args.offer_includes_website is not None
                else (existing.offer_includes_website if existing else True)
            ),
            default_campaign_count=(
                args.default_campaign_count
                if args.default_campaign_count is not None
                else (existing.default_campaign_count if existing else 3)
            ),
            default_daily_ad_budget_usd=(
                args.default_daily_ad_budget_usd
                if args.default_daily_ad_budget_usd is not None
                else (existing.default_daily_ad_budget_usd if existing else None)
            ),
            sheet_url=_clean_multiline(args.sheet_url) or (existing.sheet_url if existing else None),
            sheet_gid=_clean_text(args.sheet_gid) or (existing.sheet_gid if existing else None),
            sheet_source_filter=_clean_text(args.sheet_source_filter) or (existing.sheet_source_filter if existing else None),
            sheet_poll_seconds=args.sheet_poll_seconds or (existing.sheet_poll_seconds if existing else 30),
            template_language=_clean_text(args.template_language) or (existing.template_language if existing else "es"),
            opener_text=_first_non_empty(args.opener_text, existing.opener_text if existing else None, default=_default_opener_text(label)),
            opener_template_name=_clean_text(args.opener_template_name) or (existing.opener_template_name if existing else None),
            opener_followup_text=_first_non_empty(
                args.opener_followup_text,
                existing.opener_followup_text if existing else None,
                default=_default_followup_text(label),
            ),
            opener_followup_template_name=(
                _clean_text(args.opener_followup_template_name)
                or (existing.opener_followup_template_name if existing else None)
            ),
            manual_ping_text=_first_non_empty(
                args.manual_ping_text,
                existing.manual_ping_text if existing else None,
                default="Hola {nombre}, te escribo de vuelta por la propuesta. Te interesa que lo veamos?",
            ),
            manual_ping_template_name=_clean_text(args.manual_ping_template_name)
            or (existing.manual_ping_template_name if existing else None),
            loom_intro_text="",
            loom_url=existing.loom_url if existing else "",
            video_check_text=_first_non_empty(
                args.video_check_text,
                existing.video_check_text if existing else None,
                default="te interesa que lo veamos en una llamada corta?",
            ),
            calendly_intro_text=_first_non_empty(
                args.calendly_intro_text,
                existing.calendly_intro_text if existing else None,
                default=(
                    f"Para avanzar solo falta -> Reunion, nos conocemos -> definimos medio de pago -> "
                    f"pagas {offer_price} USD por el primer mes -> empezamos a trabajar para vos a las 24 horas.\n\n"
                    "Decime dia, horario y email y coordinamos la llamada:"
                ),
            ),
            calendly_base_url=_clean_multiline(args.calendly_base_url) or (existing.calendly_base_url if existing else ""),
            alert_emails=args.alert_emails if args.alert_emails is not None else (existing.alert_emails if existing else []),
            whatsapp_referral_source_ids=(
                args.whatsapp_referral_source_ids
                if args.whatsapp_referral_source_ids is not None
                else (existing.whatsapp_referral_source_ids if existing else [])
            ),
            initial_reply_quiet_seconds=existing.initial_reply_quiet_seconds if existing else 30,
            post_loom_min_seconds=existing.post_loom_min_seconds if existing else 600,
            post_loom_quiet_seconds=existing.post_loom_quiet_seconds if existing else 30,
            strategies=strategies,
        )
    )
    PlatformEvent.add(
        event_type="platform.funnel_text_offer_configured",
        lifecycle_stage="configuration",
        target_type="funnel",
        target_id=saved.id,
        funnel_id=saved.id,
        source="codex_agent_tool",
        actor="agent",
        summary=f"Configured text offer funnel {saved.id}.",
        payload={
            "reason": args.reason,
            "config_path": str(get_funnels_config_path()),
            "strategy_id": text_strategy.id,
            "offer_price_usd": offer_price,
            "enabled": saved.enabled,
        },
    )
    return {"saved": True, "funnel": _funnel_payload(saved), "config_path": str(get_funnels_config_path())}


def upsert_client_lead_delivery_source(arguments: dict[str, Any]) -> dict[str, Any]:
    args = UpsertClientLeadDeliverySourceArgs.model_validate(arguments)
    try:
        source = ClientLeadSource.upsert(
            source_id=slugify_funnel_id(args.source_id) if args.source_id else None,
            label=args.label,
            enabled=args.enabled,
            sheet_url=args.sheet_url,
            sheet_gid=args.sheet_gid,
            sheet_tab_name=args.sheet_tab_name,
            sheet_poll_seconds=args.sheet_poll_seconds,
            recipient_name=args.recipient_name,
            recipient_phone=args.recipient_phone,
            template_name=args.template_name,
            template_language=args.template_language,
            column_mapping=args.column_mapping,
            context_field_mapping=args.context_field_mapping,
        )
    except ValueError as error:
        raise AgentToolError(str(error)) from error
    PlatformEvent.add(
        event_type="platform.client_lead_source_upserted",
        lifecycle_stage="configuration",
        target_type="client_lead_source",
        target_id=source.id,
        source="codex_agent_tool",
        actor="agent",
        summary=f"Upserted client lead delivery source {source.id}.",
        payload={"reason": args.reason, "enabled": source.enabled, "sheet_url_configured": bool(source.sheet_url)},
    )
    return {"saved": True, "source": _client_source_payload(source)}


def _emit_agent_lifecycle_event(
    *,
    event_type: str,
    lifecycle_stage: str,
    target_type: str,
    target_id: str,
    funnel_id: str = "",
    summary: str,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> None:
    """Persist one audit event for an agent-native lifecycle action."""
    PlatformEvent.add(
        event_type=event_type,
        lifecycle_stage=lifecycle_stage,
        target_type=target_type,
        target_id=target_id,
        funnel_id=funnel_id,
        source="codex_agent_tool",
        actor="agent",
        summary=summary,
        payload=payload or {},
        idempotency_key=idempotency_key,
    )


def _meeting_payload(row: PlatformMeeting) -> dict[str, Any]:
    return {
        "id": row.id,
        "lead_id": row.lead_id,
        "client_id": row.client_id,
        "funnel_id": row.funnel_id,
        "status": row.status,
        "lead_email": row.lead_email,
        "timezone": row.timezone,
        "requested_day": row.requested_day,
        "requested_time": row.requested_time,
        "calendar_id": row.calendar_id,
        "calendar_event_id": row.calendar_event_id,
        "calendar_event_link": row.calendar_event_link,
        "calendar_event_payload": row.calendar_event_payload(),
        "calendar_result": row.calendar_result(),
        "calendar_error": row.calendar_error,
        "context_summary": row.context_summary,
        "transcript_path": row.transcript_path,
        "has_transcript_text": bool(row.transcript_text.strip()),
        "extracted_profile": row.extracted_profile(),
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
    }


def _client_profile_payload(row: PlatformClientProfile) -> dict[str, Any]:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "lead_id": row.lead_id,
        "funnel_id": row.funnel_id,
        "status": row.status,
        "source_meeting_id": row.source_meeting_id,
        "business_summary": row.business_summary,
        "offer_summary": row.offer_summary,
        "market_summary": row.market_summary,
        "objections": row.objections(),
        "segments": row.segments(),
        "knowledge": row.knowledge(),
    }


def _ad_campaign_payload(row: PlatformAdCampaign) -> dict[str, Any]:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "funnel_id": row.funnel_id,
        "status": row.status,
        "objective": row.objective,
        "budget_daily_usd": row.budget_daily_usd,
        "budget_total_usd": row.budget_total_usd,
        "budget_currency": row.budget_currency,
        "target_segments": row.target_segments(),
        "angles": row.angles(),
        "approval_status": row.approval_status,
    }


def _creative_asset_payload(row: PlatformCreativeAsset) -> dict[str, Any]:
    return {
        "id": row.id,
        "campaign_id": row.campaign_id,
        "client_id": row.client_id,
        "status": row.status,
        "asset_type": row.asset_type,
        "prompt": row.prompt,
        "file_path": row.file_path,
        "dimensions": row.dimensions,
        "source_refs": row.source_refs(),
        "meta_creative_id": row.meta_creative_id,
        "failure_reason": row.failure_reason,
    }


def _meta_publish_attempt_payload(row: PlatformMetaPublishAttempt) -> dict[str, Any]:
    return {
        "id": row.id,
        "campaign_id": row.campaign_id,
        "status": row.status,
        "approval_status": row.approval_status,
        "request_payload": row.request_payload(),
        "response_payload": row.response_payload(),
        "error": row.error,
    }


def _meta_inventory_snapshot_payload(row: PlatformMetaInventorySnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "status": row.status,
        "source": row.source,
        "actor": row.actor,
        "ad_account_id": row.ad_account_id,
        "business_id": row.business_id,
        "api_version": row.api_version,
        "inventory": row.inventory(),
        "errors": row.errors(),
        "created_at": row.created_at.isoformat(),
    }


def _client_update_payload(row: PlatformClientUpdate) -> dict[str, Any]:
    return {
        "id": row.id,
        "client_id": row.client_id,
        "campaign_id": row.campaign_id,
        "status": row.status,
        "summary_text": row.summary_text,
        "leads_count": row.leads_count,
        "blockers": row.blockers(),
        "next_action": row.next_action,
        "whatsapp_message_id": row.whatsapp_message_id,
    }


def _human_question_payload(row: PlatformHumanQuestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "workflow": row.workflow,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "funnel_id": row.funnel_id,
        "status": row.status,
        "context_summary": row.context_summary,
        "trying_to_do": row.trying_to_do,
        "question": row.question,
        "options": row.options(),
        "default_action": row.default_action,
        "timeout_at": row.timeout_at.isoformat() if row.timeout_at else None,
        "whatsapp_message_id": row.whatsapp_message_id,
        "answer_text": row.answer_text,
        "answered_at": row.answered_at.isoformat() if row.answered_at else None,
        "promoted_to_memory_at": row.promoted_to_memory_at.isoformat() if row.promoted_to_memory_at else None,
    }


def create_platform_meeting(arguments: dict[str, Any]) -> dict[str, Any]:
    args = CreatePlatformMeetingArgs.model_validate(arguments)
    row = PlatformMeeting.add(
        lead_id=args.lead_id,
        client_id=args.client_id,
        funnel_id=args.funnel_id,
        status=args.status,
        lead_email=args.lead_email,
        timezone_name=args.timezone,
        requested_day=args.requested_day,
        requested_time=args.requested_time,
        calendar_event_id=args.calendar_event_id,
        context_summary=args.context_summary,
        transcript_text=args.transcript_text,
        transcript_path=args.transcript_path,
        extracted_profile=args.extracted_profile,
        idempotency_key=args.idempotency_key,
        scheduled_at=args.scheduled_at,
    )
    _emit_agent_lifecycle_event(
        event_type="meeting.record_created",
        lifecycle_stage="meeting",
        target_type="meeting",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Agent created meeting record {row.id}.",
        payload={"lead_id": row.lead_id, "client_id": row.client_id, "status": row.status},
    )
    return {"saved": True, "meeting": _meeting_payload(row)}


def schedule_platform_meeting(arguments: dict[str, Any]) -> dict[str, Any]:
    args = SchedulePlatformMeetingArgs.model_validate(arguments)
    try:
        row, result = schedule_meeting_calendar_event(
            meeting_id=args.meeting_id,
            calendar_id=args.calendar_id,
            internal_attendees=args.internal_attendees,
            duration_minutes=args.duration_minutes,
            create_google_meet=args.create_google_meet,
            live_writes_requested=args.live_writes_requested,
            send_updates=args.send_updates,
            source="codex_agent_tool",
            actor="agent",
        )
    except CalendarSchedulingError as error:
        raise AgentToolError(str(error)) from error
    return {
        "saved": True,
        "meeting": _meeting_payload(row),
        "calendar": result.model_dump(mode="json"),
    }


def attach_meeting_transcript(arguments: dict[str, Any]) -> dict[str, Any]:
    args = AttachMeetingTranscriptArgs.model_validate(arguments)
    row = PlatformMeeting.attach_transcript(
        args.meeting_id,
        transcript_text=args.transcript_text,
        transcript_path=args.transcript_path,
        extracted_profile=args.extracted_profile,
        status=args.status,
    )
    if row is None:
        raise AgentToolError(f"Meeting not found: {args.meeting_id}")
    _emit_agent_lifecycle_event(
        event_type="meeting.transcript_attached",
        lifecycle_stage="post_conversion",
        target_type="meeting",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Agent attached transcript to meeting {row.id}.",
        payload={"client_id": row.client_id, "lead_id": row.lead_id, "profile_keys": list(row.extracted_profile())},
    )
    return {"saved": True, "meeting": _meeting_payload(row)}


def extract_client_profile_from_meeting_transcript(arguments: dict[str, Any]) -> dict[str, Any]:
    args = ExtractClientProfileFromMeetingArgs.model_validate(arguments)
    try:
        result = save_client_profile_from_meeting(
            meeting_id=args.meeting_id,
            client_id=args.client_id,
            lead_id=args.lead_id,
            funnel_id=args.funnel_id,
            status=args.status,
            existing_context=args.existing_context,
            source="codex_agent_tool",
            actor="agent",
        )
    except PlatformProfileExtractionError as error:
        raise AgentToolError(str(error)) from error
    return {
        "saved": True,
        "meeting": _meeting_payload(result.meeting),
        "profile": _client_profile_payload(result.profile),
        "extraction": result.extraction.model_dump(mode="json"),
    }


def upsert_client_profile(arguments: dict[str, Any]) -> dict[str, Any]:
    args = UpsertClientProfileArgs.model_validate(arguments)
    try:
        row = PlatformClientProfile.upsert(**args.model_dump())
    except ValueError as error:
        raise AgentToolError(str(error)) from error
    _emit_agent_lifecycle_event(
        event_type="client_profile.upserted",
        lifecycle_stage="post_conversion",
        target_type="client_profile",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Agent upserted client profile for {row.client_id}.",
        payload={"client_id": row.client_id, "status": row.status, "source_meeting_id": row.source_meeting_id},
    )
    return {"saved": True, "profile": _client_profile_payload(row)}


def stage_ad_campaign(arguments: dict[str, Any]) -> dict[str, Any]:
    args = StageAdCampaignArgs.model_validate(arguments)
    row = PlatformAdCampaign.add(**args.model_dump())
    _emit_agent_lifecycle_event(
        event_type="ad_campaign.staged",
        lifecycle_stage="ads",
        target_type="ad_campaign",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Agent staged ad campaign {row.id}.",
        payload={"client_id": row.client_id, "budget_daily_usd": row.budget_daily_usd},
    )
    return {"saved": True, "campaign": _ad_campaign_payload(row)}


def stage_creative_asset(arguments: dict[str, Any]) -> dict[str, Any]:
    args = StageCreativeAssetArgs.model_validate(arguments)
    row = PlatformCreativeAsset.add(**args.model_dump())
    _emit_agent_lifecycle_event(
        event_type="creative_asset.staged",
        lifecycle_stage="ads",
        target_type="creative_asset",
        target_id=row.id,
        summary=f"Agent staged creative asset {row.id}.",
        payload={"campaign_id": row.campaign_id, "client_id": row.client_id, "asset_type": row.asset_type},
    )
    return {"saved": True, "asset": _creative_asset_payload(row)}


def _missing_meta_plan_fields(args: StageMetaPublishPlanArgs) -> list[str]:
    """Return gaps that must be resolved before live Meta API writes."""
    missing: list[str] = []
    if not args.ad_account_id.strip():
        missing.append("ad_account_id")
    if not args.campaign_name.strip():
        missing.append("campaign_name")
    if not args.objective.strip():
        missing.append("objective")
    if not args.budget_currency.strip():
        missing.append("budget_currency")

    destination = args.destination
    if destination.destination_type == "whatsapp":
        if not destination.page_id.strip():
            missing.append("destination.page_id")
        if not destination.whatsapp_phone_number_id.strip():
            missing.append("destination.whatsapp_phone_number_id")
    if destination.destination_type == "instant_form":
        if not destination.page_id.strip():
            missing.append("destination.page_id")
        if not destination.lead_form_id.strip():
            missing.append("destination.lead_form_id")
    if destination.destination_type == "landing_page" and not destination.landing_page_url.strip():
        missing.append("destination.landing_page_url")

    if not args.ad_sets:
        missing.append("ad_sets")

    for ad_set_index, ad_set in enumerate(args.ad_sets, start=1):
        prefix = f"ad_sets[{ad_set_index}]"
        if not ad_set.name.strip():
            missing.append(f"{prefix}.name")
        daily_budget = ad_set.budget_daily_usd or 0
        total_budget = ad_set.budget_total_usd or 0
        if daily_budget <= 0 and total_budget <= 0:
            missing.append(f"{prefix}.budget")
        if not ad_set.targeting:
            missing.append(f"{prefix}.targeting")
        if not ad_set.ads:
            missing.append(f"{prefix}.ads")
        for ad_index, ad in enumerate(ad_set.ads, start=1):
            ad_prefix = f"{prefix}.ads[{ad_index}]"
            if not ad.name.strip():
                missing.append(f"{ad_prefix}.name")
            creative = ad.creative
            has_creative_ref = any(
                [
                    creative.creative_asset_id.strip(),
                    creative.asset_file_path.strip(),
                    creative.meta_creative_id.strip(),
                    creative.image_hash.strip(),
                    creative.video_id.strip(),
                ]
            )
            if not has_creative_ref:
                missing.append(f"{ad_prefix}.creative")
            if not creative.primary_text.strip():
                missing.append(f"{ad_prefix}.creative.primary_text")
            if not creative.headline.strip():
                missing.append(f"{ad_prefix}.creative.headline")
    return missing


def _meta_publish_plan_payload(args: StageMetaPublishPlanArgs, missing_fields: list[str]) -> dict[str, Any]:
    """Build the canonical staged payload that a future publisher executes."""
    return {
        "schema_version": "konecta.meta_publish_plan.v1",
        "provider": "meta_marketing_api",
        "publish_mode": "staged_only",
        "live_writes_allowed": False,
        "operator_approval_required": True,
        "client_id": args.client_id,
        "funnel_id": args.funnel_id,
        "ad_account_id": args.ad_account_id,
        "budget_currency": args.budget_currency,
        "campaign": {
            "name": args.campaign_name,
            "objective": args.objective,
            "buying_type": args.buying_type,
            "special_ad_categories": args.special_ad_categories,
            "create_status": "PAUSED",
        },
        "destination": args.destination.model_dump(mode="json"),
        "ad_sets": [ad_set.model_dump(mode="json") for ad_set in args.ad_sets],
        "required_before_live_publish": missing_fields,
        "live_execution_policy": {
            "read_inventory_first": True,
            "create_initial_status": "PAUSED",
            "publish_order": ["campaign", "ad_sets", "creatives", "ads"],
            "disable_order": ["ads", "ad_sets", "campaign"],
            "store_meta_ids_on_success": True,
        },
        "observability_events": [
            "meta_publish.plan_staged",
            "meta_publish.preflight_checked",
            "meta_publish.approval_requested",
            "meta_publish.submitted",
            "meta_publish.response_received",
        ],
        "notes": args.notes,
    }


def stage_meta_publish_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    args = StageMetaPublishPlanArgs.model_validate(arguments)
    missing_fields = _missing_meta_plan_fields(args)
    try:
        row = PlatformMetaPublishAttempt.add(
            campaign_id=args.campaign_id,
            status="blocked" if missing_fields else "staged",
            approval_status="needs_preflight" if missing_fields else args.approval_status,
            request_payload=_meta_publish_plan_payload(args, missing_fields),
            response_payload={},
            error="Missing live publish fields: " + ", ".join(missing_fields) if missing_fields else "",
            idempotency_key=args.idempotency_key,
        )
    except ValueError as error:
        raise AgentToolError(str(error)) from error
    _emit_agent_lifecycle_event(
        event_type="meta_publish.plan_staged",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=row.id,
        funnel_id=args.funnel_id,
        summary=f"Agent staged Meta publish plan {row.id}.",
        payload={
            "campaign_id": row.campaign_id,
            "client_id": args.client_id,
            "missing_fields": missing_fields,
            "approval_status": row.approval_status,
        },
    )
    return {
        "saved": True,
        "attempt": _meta_publish_attempt_payload(row),
        "required_before_live_publish": missing_fields,
    }


def preflight_meta_publish_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    args = PreflightMetaPublishPlanArgs.model_validate(arguments)
    try:
        attempt, result = preflight_meta_publish_attempt(
            attempt_id=args.attempt_id,
            live_writes_requested=args.live_writes_requested,
            source="codex_agent_tool",
            actor="agent",
        )
    except MetaAdsPublishError as error:
        raise AgentToolError(str(error)) from error
    return {
        "saved": True,
        "attempt": _meta_publish_attempt_payload(attempt),
        "preflight": result.model_dump(mode="json"),
    }


def approve_meta_publish_plan(arguments: dict[str, Any]) -> dict[str, Any]:
    args = ApproveMetaPublishPlanArgs.model_validate(arguments)
    try:
        attempt, result = approve_meta_publish_attempt(
            attempt_id=args.attempt_id,
            approved_by=args.approved_by,
            approval_note=args.approval_note,
            approve_live_writes=args.approve_live_writes,
            require_inventory_ready=args.require_inventory_ready,
            max_daily_budget_usd=args.max_daily_budget_usd,
            max_lifetime_budget_usd=args.max_lifetime_budget_usd,
            max_estimated_monthly_budget_usd=args.max_estimated_monthly_budget_usd,
            source="codex_agent_tool",
            actor="agent",
        )
    except MetaAdsPublishError as error:
        raise AgentToolError(str(error)) from error
    return {
        "saved": True,
        "attempt": _meta_publish_attempt_payload(attempt),
        "approval": result.model_dump(mode="json"),
    }


def sync_meta_inventory_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    args = SyncMetaInventoryArgs.model_validate(arguments)
    try:
        snapshot, result = sync_meta_inventory(
            ad_account_id=args.ad_account_id,
            business_id=args.business_id,
            page_ids=args.page_ids,
            include_campaigns=args.include_campaigns,
            include_lead_forms=args.include_lead_forms,
            include_pixels=args.include_pixels,
            include_whatsapp=args.include_whatsapp,
            limit=args.limit,
            source="codex_agent_tool",
            actor="agent",
        )
    except MetaInventoryError as error:
        raise AgentToolError(str(error)) from error
    return {
        "saved": True,
        "snapshot": _meta_inventory_snapshot_payload(snapshot),
        "result": result.model_dump(mode="json"),
    }


def stage_meta_publish_attempt(arguments: dict[str, Any]) -> dict[str, Any]:
    args = StageMetaPublishAttemptArgs.model_validate(arguments)
    try:
        row = PlatformMetaPublishAttempt.add(**args.model_dump())
    except ValueError as error:
        raise AgentToolError(str(error)) from error
    _emit_agent_lifecycle_event(
        event_type="meta_publish_attempt.staged",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=row.id,
        summary=f"Agent staged Meta publish attempt {row.id}.",
        payload={"campaign_id": row.campaign_id, "status": row.status, "approval_status": row.approval_status},
    )
    return {"saved": True, "attempt": _meta_publish_attempt_payload(row)}


def create_client_update(arguments: dict[str, Any]) -> dict[str, Any]:
    args = CreateClientUpdateArgs.model_validate(arguments)
    row = PlatformClientUpdate.add(**args.model_dump())
    _emit_agent_lifecycle_event(
        event_type="client_update.created",
        lifecycle_stage="client_update",
        target_type="client_update",
        target_id=row.id,
        summary=f"Agent created client update {row.id}.",
        payload={"client_id": row.client_id, "campaign_id": row.campaign_id, "status": row.status},
    )
    return {"saved": True, "update": _client_update_payload(row)}


def ask_human_question(arguments: dict[str, Any]) -> dict[str, Any]:
    args = AskHumanQuestionArgs.model_validate(arguments)
    timeout_at = args.timeout_at or datetime.now(timezone.utc) + timedelta(minutes=args.timeout_minutes)
    row = PlatformHumanQuestion.add(
        workflow=args.workflow,
        target_type=args.target_type,
        target_id=args.target_id,
        funnel_id=args.funnel_id,
        context_summary=args.context_summary,
        trying_to_do=args.trying_to_do,
        question=args.question,
        options=args.options,
        default_action=args.default_action,
        timeout_at=timeout_at,
        whatsapp_message_id=args.whatsapp_message_id,
    )
    _emit_agent_lifecycle_event(
        event_type="human_question.created",
        lifecycle_stage="human_escalation",
        target_type="human_question",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Agent created human question {row.id}.",
        payload={
            "workflow": row.workflow,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "trying_to_do": row.trying_to_do,
            "default_action": row.default_action,
        },
    )
    return {"saved": True, "question": _human_question_payload(row)}


def answer_human_question(arguments: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    args = AnswerHumanQuestionArgs.model_validate(arguments)
    promoted_at = datetime.now(timezone.utc) if args.promote_to_memory else None
    row = PlatformHumanQuestion.answer(
        args.question_id,
        answer_text=args.answer_text,
        status=args.status,
        promoted_to_memory_at=promoted_at,
    )
    if row is None:
        raise AgentToolError(f"Human question not found: {args.question_id}")

    memory_path: Path | None = None
    if args.promote_to_memory:
        memory_target_type = args.memory_target_type.strip() or row.target_type or "human_question"
        memory_target_id = args.memory_target_id.strip() or row.target_id or row.id
        note = (
            f"Workflow: {row.workflow or '-'}\n"
            f"Context: {row.context_summary or '-'}\n"
            f"Trying to do: {row.trying_to_do or '-'}\n"
            f"Question: {row.question}\n"
            f"Answer: {row.answer_text}\n"
        )
        memory_path = _append_agent_memory_entry(
            target_type=memory_target_type,
            target_id=memory_target_id,
            note=note,
            title=args.memory_title,
            importance="high",
            run_id=run_id,
        )

    _emit_agent_lifecycle_event(
        event_type="human_question.answered",
        lifecycle_stage="human_escalation",
        target_type="human_question",
        target_id=row.id,
        funnel_id=row.funnel_id,
        summary=f"Agent stored answer for human question {row.id}.",
        payload={
            "target_type": row.target_type,
            "target_id": row.target_id,
            "status": row.status,
            "promoted_to_memory": bool(memory_path),
        },
    )
    return {
        "saved": True,
        "question": _human_question_payload(row),
        "memory_path": str(memory_path) if memory_path else None,
    }


def _message_payload(row: ContadoresMessage) -> dict[str, Any]:
    return {
        "message_id": row.id,
        "lead_id": row.lead_id,
        "text": row.text,
        "sequence_step": row.sequence_step,
        "media_type": row.media_type,
        "media_path": row.media_path,
        "dispatch_after": row.dispatch_after.isoformat() if row.dispatch_after else None,
    }


def get_lead_context(arguments: dict[str, Any]) -> dict[str, Any]:
    args = LeadToolArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    messages = ContadoresMessage.list_by_lead(lead.id)[-30:]
    client = WorkstationClient.get_by_lead_id(lead.id)
    return {
        "lead": {
            "id": lead.id,
            "funnel_id": lead.funnel_id,
            "stage": lead.stage.value,
            "full_name": lead.full_name,
            "phone": lead.phone,
            "email": lead.email,
            "codex_enabled": lead.codex_enabled,
            "automation_paused": lead.automation_paused,
            "automation_paused_reason": lead.automation_paused_reason,
            "last_inbound_at": lead.last_inbound_at.isoformat() if lead.last_inbound_at else None,
            "last_outbound_at": lead.last_outbound_at.isoformat() if lead.last_outbound_at else None,
        },
        "workstation_client_id": client.id if client else None,
        "messages": [
            {
                "id": message.id,
                "from_me": message.from_me,
                "text": message.text,
                "media_type": message.media_type,
                "media_path": message.media_path,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
    }


def send_whatsapp_text(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints.contadores import enqueue_lead_outbound

    args = SendWhatsAppTextArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    row = enqueue_lead_outbound(
        lead=lead,
        text=args.text,
        sequence_step=args.sequence_step,
        dispatch_after=_dispatch_after(args.dispatch_after_minutes),
    )
    return {"queued": True, "message": _message_payload(row)}


def send_whatsapp_media(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints.contadores import enqueue_lead_outbound

    args = SendWhatsAppMediaArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    row = enqueue_lead_outbound(
        lead=lead,
        text=args.text,
        sequence_step=args.sequence_step,
        dispatch_after=_dispatch_after(args.dispatch_after_minutes),
        media_type=args.media_type,
        media_path=args.media_path,
        media_caption=args.media_caption,
        media_mime_type=args.media_mime_type,
        media_filename=args.media_filename,
    )
    return {"queued": True, "message": _message_payload(row)}


def schedule_followup(arguments: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    args = ScheduleFollowupArgs.model_validate(arguments)
    due_at = datetime.now(timezone.utc) + timedelta(minutes=args.run_after_minutes)
    key = args.idempotency_key or f"{run_id}:{args.target_type}:{args.target_id}:{args.run_after_minutes}"
    task = ScheduledAgentTask.create(
        target_type=args.target_type,
        target_id=args.target_id,
        due_at=due_at,
        reason=args.reason,
        instruction=args.instruction,
        run_id=run_id,
        idempotency_key=key,
    )
    return {
        "scheduled": True,
        "task_id": task.id,
        "target_type": task.target_type,
        "target_id": task.target_id,
        "due_at": task.due_at.isoformat(),
    }


def schedule_heartbeat(arguments: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    args = ScheduleHeartbeatArgs.model_validate(arguments)
    reason = f"heartbeat: {args.reason}"[:1000]
    return schedule_followup(
        {
            "target_type": args.target_type,
            "target_id": args.target_id,
            "run_after_minutes": args.run_after_minutes,
            "reason": reason,
            "instruction": args.instruction,
            "idempotency_key": args.idempotency_key,
        },
        run_id=run_id,
    )


def read_agent_memory(arguments: dict[str, Any]) -> dict[str, Any]:
    args = AgentMemoryTargetArgs.model_validate(arguments)
    path = agent_memory_path(args.target_type, args.target_id)
    text = read_agent_memory_text(
        target_type=args.target_type,
        target_id=args.target_id,
        limit_chars=args.limit_chars,
    )
    return {
        "found": bool(text.strip()),
        "target_type": args.target_type,
        "target_id": args.target_id,
        "path": str(path),
        "memory": text,
    }


def _append_agent_memory_entry(
    *,
    target_type: str,
    target_id: str,
    note: str,
    title: str,
    importance: str,
    run_id: str,
) -> Path:
    """Append one durable memory note for future agent turns."""
    path = agent_memory_path(target_type, target_id)
    now = datetime.now(timezone.utc).isoformat()
    clean_title = " ".join(title.split()).strip() or "Codex note"
    entry = (
        f"\n## {now} - {clean_title}\n"
        f"- run_id: {run_id}\n"
        f"- importance: {importance}\n\n"
        f"{note.strip()}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    return path


def write_agent_memory(arguments: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    args = WriteAgentMemoryArgs.model_validate(arguments)
    path = _append_agent_memory_entry(
        target_type=args.target_type,
        target_id=args.target_id,
        note=args.note,
        title=args.title,
        importance=args.importance,
        run_id=run_id,
    )
    return {
        "written": True,
        "target_type": args.target_type,
        "target_id": args.target_id,
        "path": str(path),
    }


def _parse_json_object(raw_value: str) -> dict[str, Any]:
    try:
        value = json.loads(raw_value or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def list_agent_tool_calls(arguments: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    args = ListAgentToolCallsArgs.model_validate(arguments)
    target_run_id = (args.run_id or run_id).strip()
    calls = AgentToolCall.list_by_run(target_run_id)
    if args.status:
        calls = [call for call in calls if call.status == args.status]
    return {
        "run_id": target_run_id,
        "calls": [
            {
                "id": call.id,
                "tool_name": call.tool_name,
                "target_type": call.target_type,
                "target_id": call.target_id,
                "status": call.status,
                "arguments": _parse_json_object(call.arguments_json),
                "result": _parse_json_object(call.result_json),
                "error": call.error,
                "created_at": call.created_at.isoformat(),
            }
            for call in calls
        ],
    }


def _normalize_domain(value: str) -> str:
    """Return a lower-case ASCII domain without URL or email noise."""
    clean = (value or "").strip().lower()
    if "://" in clean:
        clean = clean.split("://", 1)[1]
    clean = clean.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    clean = clean.rsplit("@", 1)[-1].strip(".")
    try:
        ascii_domain = clean.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise AgentToolError(f"Invalid domain: {value}") from error
    labels = ascii_domain.split(".")
    if len(labels) < 2 or len(ascii_domain) > 253:
        raise AgentToolError("Use a full domain like example.com.")
    if any(not label or len(label) > 63 or label.startswith("-") or label.endswith("-") for label in labels):
        raise AgentToolError(f"Invalid domain: {value}")
    return ascii_domain


def _audit_domain_target_id(value: Any) -> str:
    """Return a normalized domain for audit rows when possible."""
    if not value:
        return ""
    try:
        return _normalize_domain(str(value))
    except AgentToolError:
        return str(value)


def _best_domain_price(prices: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid_prices = [
        price
        for price in prices
        if isinstance(price.get("registration_price"), int | float) and price.get("currency")
    ]
    if not valid_prices:
        return None
    best = min(valid_prices, key=lambda price: float(price["registration_price"]))
    return {
        "registrar": best.get("registrar"),
        "registration_price": best.get("registration_price"),
        "renewal_price": best.get("renewal_price"),
        "currency": best.get("currency"),
    }


def _cloudflare_tld_price(domain: str) -> dict[str, Any] | None:
    """Return Cloudflare Registrar standard TLD pricing when public data has it."""
    tld = domain.rsplit(".", 1)[-1]
    response = httpx.get("https://cfdomainpricing.com/prices.json", timeout=8)
    response.raise_for_status()
    prices = response.json().get(tld)
    if not isinstance(prices, dict):
        return None
    registration = prices.get("registration")
    renewal = prices.get("renewal")
    if not isinstance(registration, int | float):
        return None
    return {
        "registrar": "cloudflare",
        "registration_price": registration,
        "renewal_price": renewal,
        "currency": "USD",
    }


def _public_tld_price(domain: str) -> dict[str, Any] | None:
    try:
        return _cloudflare_tld_price(domain)
    except Exception:
        return None


def _domain_result_from_namecrawl(domain: str) -> dict[str, Any]:
    response = httpx.post(
        "https://api.namecrawl.dev/v1/public/check",
        json={"domain": domain},
        timeout=12,
    )
    response.raise_for_status()
    payload = response.json()
    results = payload.get("data", {}).get("results", [])
    match = next(
        (result for result in results if str(result.get("fqdn", "")).lower().strip(".") == domain),
        None,
    )
    if not isinstance(match, dict):
        raise AgentToolError(f"No domain result returned for {domain}")

    prices = match.get("pricing") if isinstance(match.get("pricing"), list) else []
    best_price = _best_domain_price(prices) or _public_tld_price(domain)
    if best_price and not prices:
        prices = [best_price]
    return {
        "domain": domain,
        "exists": match.get("available") is False,
        "available": match.get("available") is True,
        "status": match.get("status"),
        "registrar": match.get("registrar"),
        "expiry_date": match.get("expiry_date"),
        "prices": prices,
        "best_price": best_price,
        "source": "namecrawl_public",
        "price_note": "Public registrar estimate. Final checkout price can vary by registrar, country, taxes, premium status, and promotions.",
    }


def _domain_result_from_rdap(domain: str) -> dict[str, Any]:
    response = httpx.get(f"https://rdap.org/domain/{domain}", timeout=12, follow_redirects=True)
    if response.status_code == 404:
        best_price = _public_tld_price(domain)
        return {
            "domain": domain,
            "exists": False,
            "available": True,
            "status": "not_found_in_rdap",
            "prices": [best_price] if best_price else [],
            "best_price": best_price,
            "source": "rdap",
            "price_note": "RDAP does not provide registrar prices. Price is a public standard TLD estimate when present.",
        }
    response.raise_for_status()
    payload = response.json()
    best_price = _public_tld_price(domain)
    return {
        "domain": domain,
        "exists": True,
        "available": False,
        "status": "registered",
        "registrar": payload.get("registrarName") or payload.get("name"),
        "prices": [best_price] if best_price else [],
        "best_price": best_price,
        "source": "rdap",
        "price_note": "Domain is registered. Price is only a public standard TLD registration estimate, not the market value of this taken domain.",
    }


def check_domain_availability(arguments: dict[str, Any]) -> dict[str, Any]:
    args = CheckDomainAvailabilityArgs.model_validate(arguments)
    domain = _normalize_domain(args.domain)
    try:
        return _domain_result_from_namecrawl(domain)
    except Exception as error:
        fallback = _domain_result_from_rdap(domain)
        fallback["primary_source_error"] = f"{error.__class__.__name__}: {error}"
        return fallback


def move_lead_to_funnel(arguments: dict[str, Any]) -> dict[str, Any]:
    args = MoveLeadToFunnelArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    updated = ContadoresLead.move_to_funnel(
        lead.id,
        funnel_id=args.funnel_id,
        stage=args.stage,
    )
    if updated is None:
        raise AgentToolError(f"Lead not found: {lead.id}")
    updated = ContadoresLead.update_flow_state(
        lead.id,
        stage=updated.stage,
        automation_paused=updated.automation_paused,
        automation_paused_reason=args.reason if updated.automation_paused else None,
        classification_completed_at=datetime.now(timezone.utc),
        last_classification_label="codex_agent_move_lead_to_funnel",
        last_classification_reason=args.reason,
    )
    return {
        "moved": updated is not None,
        "lead_id": lead.id,
        "funnel_id": updated.funnel_id if updated else args.funnel_id,
        "stage": updated.stage.value if updated else args.stage,
        "automation_paused": updated.automation_paused if updated else False,
    }


def set_lead_tags(arguments: dict[str, Any]) -> dict[str, Any]:
    args = SetLeadTagsArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    tags = args.tags if args.mode == "replace" else [*lead.tags, *args.tags]
    updated = ContadoresLead.set_tags(lead.id, tags=tags)
    if updated is None:
        raise AgentToolError(f"Lead not found: {lead.id}")
    return {
        "updated": True,
        "lead_id": updated.id,
        "tags": updated.tags,
        "mode": args.mode,
    }


def update_lead_state(arguments: dict[str, Any]) -> dict[str, Any]:
    args = UpdateLeadStateArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    stage = ContadoresLeadStage(args.stage) if args.stage else None
    updated = ContadoresLead.update_flow_state(
        lead.id,
        stage=stage,
        automation_paused=args.automation_paused,
        automation_paused_reason=args.reason if args.automation_paused else None,
        classification_completed_at=datetime.now(timezone.utc),
        last_classification_label=args.classification_label,
        last_classification_reason=args.reason or "Actualizado por Codex agent tool.",
    )
    return {"updated": updated is not None, "lead_id": lead.id, "stage": updated.stage.value if updated else lead.stage.value}


def handoff_human(arguments: dict[str, Any]) -> dict[str, Any]:
    args = HandoffHumanArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    queued: dict[str, Any] | None = None
    if args.optional_message.strip():
        queued = send_whatsapp_text(
            {
                "lead_id": lead.id,
                "text": args.optional_message,
                "sequence_step": "codex_agent_handoff",
            }
        )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="codex_agent_handoff",
        classification_completed_at=datetime.now(timezone.utc),
        last_classification_label="codex_agent_handoff",
        last_classification_reason=args.reason,
        clear_needs_human_notified_at=True,
    )
    client = WorkstationClient.get_by_lead_id(lead.id)
    if client is not None:
        WorkstationClient.update_automation_state(
            client.id,
            automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
            last_automation_handled_at=datetime.now(timezone.utc),
        )
    return {"handoff": True, "lead_id": lead.id, "queued_message": queued}


def create_or_get_solo_page_client(arguments: dict[str, Any]) -> dict[str, Any]:
    args = CreateOrGetSoloPageClientArgs.model_validate(arguments)
    lead = _lead_or_error(args.lead_id)
    client = WorkstationClient.create_for_lead(
        lead,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        status=WorkstationClientStatus.PENDING_PAYMENT,
        automation_status=WorkstationAutomationStatus.INTAKE,
        offer_price_usd=args.offer_price_usd,
    )
    return {
        "client_id": client.id,
        "lead_id": client.lead_id,
        "folder_name": client.folder_name,
        "automation_status": client.automation_status.value,
    }


def get_workstation_context(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = ClientToolArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    workstation_endpoints.write_client_files(client)
    folder = workstation_endpoints.client_folder(client)
    latest_version = workstation_endpoints.latest_landing_page_version_dir(client)
    public_page = workstation_endpoints.ensure_public_page_for_latest_version(client)
    public_page_payload = workstation_endpoints.workstation_public_page_payload(public_page)
    messages = ContadoresMessage.list_by_lead(lead.id)[-30:]
    return {
        "client": {
            "id": client.id,
            "lead_id": client.lead_id,
            "display_name": client.display_name,
            "automation_status": client.automation_status.value,
            "folder": str(folder),
            "latest_page_version": str(latest_version) if latest_version else None,
            "last_preview_sent_at": client.last_preview_sent_at.isoformat() if client.last_preview_sent_at else None,
            "approved_at": client.approved_at.isoformat() if client.approved_at else None,
        },
        "public_page": public_page_payload,
        "lead": {
            "id": lead.id,
            "full_name": lead.full_name,
            "phone": lead.phone,
            "codex_enabled": lead.codex_enabled,
        },
        "messages": [
            {
                "id": message.id,
                "from_me": message.from_me,
                "text": message.text,
                "media_type": message.media_type,
                "created_at": message.created_at.isoformat(),
            }
            for message in messages
        ],
    }


def write_progress(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = WriteProgressArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    workstation_endpoints.append_workstation_progress(client, args.message)
    return {"written": True, "client_id": client.id}


def generate_or_revise_solo_page(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = GenerateOrReviseSoloPageArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    messages = ContadoresMessage.list_by_lead(lead.id)
    if args.source_message_ids:
        selected = {int(message_id) for message_id in args.source_message_ids}
        replies = [message for message in messages if message.id in selected]
    else:
        replies = [message for message in messages if not message.from_me][-5:]
    version_dir = asyncio.run(
        workstation_endpoints.generate_solo_page_version(
            client=client,
            lead=lead,
            replies=replies,
            revision=args.revision,
            operator_prompt=args.instruction,
        )
    )
    return {
        "generated": True,
        "client_id": client.id,
        "version": version_dir.name,
        "version_dir": str(version_dir),
        "preview_path": str(version_dir / "preview.mp4"),
    }


def queue_workstation_deliverables(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = QueueWorkstationDeliverablesArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    version_dir = workstation_endpoints.landing_page_root(client) / Path(args.version).name
    if not version_dir.is_dir():
        raise AgentToolError(f"Page version not found: {args.version}")
    rows = workstation_endpoints.queue_workstation_preview(
        client=client,
        lead=lead,
        version_dir=version_dir,
        sequence_step=args.sequence_step,
    )
    if rows:
        WorkstationClient.update_automation_state(
            client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=datetime.now(timezone.utc),
            last_preview_sent_at=max(row.created_at for row in rows),
        )
    return {"queued": len(rows), "messages": [_message_payload(row) for row in rows]}


def send_workstation_public_page_link(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = SendWorkstationPublicPageLinkArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    row = workstation_endpoints.queue_workstation_public_page_link(
        client=client,
        lead=lead,
        text=args.text,
        dispatch_after=_dispatch_after(args.dispatch_after_minutes),
    )
    public_page = workstation_endpoints.ensure_public_page_for_latest_version(client)
    return {
        "queued": True,
        "message": _message_payload(row),
        "public_page": workstation_endpoints.workstation_public_page_payload(public_page),
    }


def mark_preview_approved(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.endpoints import workstation as workstation_endpoints

    args = MarkPreviewApprovedArgs.model_validate(arguments)
    client = _client_or_error(args.client_id)
    lead = _lead_or_error(client.lead_id)
    public_page = workstation_endpoints.ensure_public_page_for_latest_version(client)
    if public_page is not None and public_page.last_sent_at is None:
        row = workstation_endpoints.queue_workstation_public_page_link(
            client=client,
            lead=lead,
            text="La publique de prueba para que pueda revisarla online: {url}",
        )
        public_page = workstation_endpoints.ensure_public_page_for_latest_version(client)
        return {
            "approved": False,
            "public_link_sent": True,
            "client_id": client.id,
            "lead_id": lead.id,
            "message": _message_payload(row),
            "public_page": workstation_endpoints.workstation_public_page_payload(public_page),
        }
    now = datetime.now(timezone.utc)
    WorkstationClient.update_automation_state(
        client.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        approved_at=now,
        last_automation_handled_at=now,
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="workstation_solo_page_approved",
        classification_completed_at=now,
        last_classification_label="workstation_solo_page_approved",
        last_classification_reason=args.reason,
        clear_needs_human_notified_at=True,
    )
    return {"approved": True, "client_id": client.id, "lead_id": lead.id}


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "read_platform_config": read_platform_config,
    "validate_platform_config": validate_platform_config,
    "configure_text_offer_funnel": configure_text_offer_funnel,
    "upsert_funnel_config": upsert_funnel_config,
    "upsert_client_lead_delivery_source": upsert_client_lead_delivery_source,
    "create_platform_meeting": create_platform_meeting,
    "schedule_platform_meeting": schedule_platform_meeting,
    "attach_meeting_transcript": attach_meeting_transcript,
    "extract_client_profile_from_meeting_transcript": extract_client_profile_from_meeting_transcript,
    "upsert_client_profile": upsert_client_profile,
    "stage_ad_campaign": stage_ad_campaign,
    "stage_creative_asset": stage_creative_asset,
    "stage_meta_publish_attempt": stage_meta_publish_attempt,
    "stage_meta_publish_plan": stage_meta_publish_plan,
    "preflight_meta_publish_plan": preflight_meta_publish_plan,
    "approve_meta_publish_plan": approve_meta_publish_plan,
    "sync_meta_inventory": sync_meta_inventory_tool,
    "create_client_update": create_client_update,
    "ask_human_question": ask_human_question,
    "answer_human_question": answer_human_question,
    "get_lead_context": get_lead_context,
    "send_whatsapp_text": send_whatsapp_text,
    "send_whatsapp_media": send_whatsapp_media,
    "schedule_followup": schedule_followup,
    "schedule_heartbeat": schedule_heartbeat,
    "read_agent_memory": read_agent_memory,
    "write_agent_memory": write_agent_memory,
    "list_agent_tool_calls": list_agent_tool_calls,
    "check_domain_availability": check_domain_availability,
    "move_lead_to_funnel": move_lead_to_funnel,
    "set_lead_tags": set_lead_tags,
    "update_lead_state": update_lead_state,
    "handoff_human": handoff_human,
    "create_or_get_solo_page_client": create_or_get_solo_page_client,
    "get_workstation_context": get_workstation_context,
    "write_progress": write_progress,
    "generate_or_revise_solo_page": generate_or_revise_solo_page,
    "queue_workstation_deliverables": queue_workstation_deliverables,
    "send_workstation_public_page_link": send_workstation_public_page_link,
    "mark_preview_approved": mark_preview_approved,
}

RUN_AWARE_TOOLS = {
    "schedule_followup",
    "schedule_heartbeat",
    "write_agent_memory",
    "list_agent_tool_calls",
    "answer_human_question",
}


def _audit_target_for_tool(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str]:
    """Return the product target used for tool-call audit rows."""
    if tool_name in {"read_platform_config", "validate_platform_config"}:
        return "platform", "platform"
    if tool_name == "upsert_funnel_config":
        funnel = arguments.get("funnel")
        funnel_id = funnel.get("id") if isinstance(funnel, dict) else ""
        return "funnel", str(funnel_id or "")
    if tool_name == "configure_text_offer_funnel":
        return "funnel", str(arguments.get("funnel_id") or "")
    if tool_name == "upsert_client_lead_delivery_source":
        return "client_lead_source", str(arguments.get("source_id") or arguments.get("label") or "")
    if tool_name == "create_platform_meeting":
        return "meeting", str(arguments.get("idempotency_key") or arguments.get("lead_id") or arguments.get("client_id") or "")
    if tool_name == "schedule_platform_meeting":
        return "meeting", str(arguments.get("meeting_id") or "")
    if tool_name == "attach_meeting_transcript":
        return "meeting", str(arguments.get("meeting_id") or "")
    if tool_name == "extract_client_profile_from_meeting_transcript":
        return "client_profile", str(arguments.get("client_id") or arguments.get("meeting_id") or "")
    if tool_name == "upsert_client_profile":
        return "client_profile", str(arguments.get("client_id") or "")
    if tool_name == "stage_ad_campaign":
        return "ad_campaign", str(arguments.get("idempotency_key") or arguments.get("client_id") or "")
    if tool_name == "stage_creative_asset":
        return "creative_asset", str(arguments.get("campaign_id") or arguments.get("client_id") or "")
    if tool_name == "stage_meta_publish_attempt":
        return "meta_publish_attempt", str(arguments.get("idempotency_key") or arguments.get("campaign_id") or "")
    if tool_name == "stage_meta_publish_plan":
        return "meta_publish_attempt", str(arguments.get("idempotency_key") or arguments.get("campaign_id") or "")
    if tool_name == "preflight_meta_publish_plan":
        return "meta_publish_attempt", str(arguments.get("attempt_id") or "")
    if tool_name == "approve_meta_publish_plan":
        return "meta_publish_attempt", str(arguments.get("attempt_id") or "")
    if tool_name == "sync_meta_inventory":
        return "meta_inventory", str(arguments.get("ad_account_id") or arguments.get("business_id") or "meta_inventory")
    if tool_name == "create_client_update":
        return "client_update", str(arguments.get("client_id") or arguments.get("campaign_id") or "")
    if tool_name == "ask_human_question":
        return "human_question", str(arguments.get("target_id") or arguments.get("workflow") or "")
    if tool_name == "answer_human_question":
        return "human_question", str(arguments.get("question_id") or "")
    if arguments.get("domain"):
        return "domain", _audit_domain_target_id(arguments.get("domain"))
    if arguments.get("client_id"):
        return "workstation_client", str(arguments.get("client_id") or "")
    if arguments.get("lead_id"):
        return "lead", str(arguments.get("lead_id") or "")
    return str(arguments.get("target_type") or "lead"), str(arguments.get("target_id") or "")


def call_tool(*, run_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate, execute, and audit one product tool call."""
    clean_tool_name = (tool_name or "").strip()
    handler = TOOL_HANDLERS.get(clean_tool_name)
    default_target_type, default_target_id = _audit_target_for_tool(clean_tool_name, arguments)
    if clean_tool_name == "ask_human_question":
        target_type = default_target_type
        target_id = default_target_id
    else:
        target_type = str(arguments.get("target_type") or default_target_type)
        target_id = str(arguments.get("target_id") or default_target_id)
    idempotency_key = str(arguments.get("idempotency_key") or "").strip() or None
    try:
        if handler is None:
            raise AgentToolError(f"Unknown tool: {clean_tool_name}")
        if target_type in {"lead", "workstation_client"} and target_id:
            assert_codex_enabled_for_target(target_type, target_id)
        if clean_tool_name in RUN_AWARE_TOOLS:
            result = handler(arguments, run_id=run_id)
        else:
            result = handler(arguments)
        payload = {"ok": True, "tool": clean_tool_name, "result": result}
        AgentToolCall.add(
            run_id=run_id,
            tool_name=clean_tool_name,
            arguments=arguments,
            result=result,
            status="succeeded",
            target_type=target_type,
            target_id=target_id,
            idempotency_key=idempotency_key,
        )
    except (ValidationError, AgentToolError, Exception) as error:
        payload = {
            "ok": False,
            "tool": clean_tool_name,
            "error_type": error.__class__.__name__,
            "error": str(error),
        }
        AgentToolCall.add(
            run_id=run_id,
            tool_name=clean_tool_name,
            arguments=arguments,
            result=payload,
            status="failed",
            target_type=target_type,
            target_id=target_id,
            idempotency_key=idempotency_key,
            error=f"{error.__class__.__name__}: {error}",
        )
    write_jsonl(run_context_dir(run_id) / "tool_calls.jsonl", payload | {"arguments": arguments})
    return payload
