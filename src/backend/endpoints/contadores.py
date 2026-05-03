"""Dedicated Contadores endpoints: config, leads, automation, and delivery contracts."""

from __future__ import annotations

import base64
import csv
import json
import mimetypes
import os
import re
import uuid
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Literal
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.calendly import normalize_calendly_url
from backend.ai.contadores_post_loom_classifier import PostLoomReplyClassifierProgram
from backend.auth import INTERNAL_API_TOKEN_HEADER, has_valid_internal_api_token
from backend.contadores_strategies import (
    LOOM_STEP,
    choose_contadores_strategy as choose_default_contadores_strategy,
    choose_funnel_strategy,
    get_contadores_strategy_weight,
    list_funnel_strategies,
)
from backend.database import (
    ContadoresConfig,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    ContadoresStrategyAssignment,
    DATA_DIR,
    MessageDeliveryStatus,
    WorkstationClient,
    engine,
    normalize_contadores_tags,
    normalize_email,
    normalize_phone,
)
from backend.funnel_config import GENERAL_INBOX_FUNNEL_ID, get_contadores_funnel
from backend.funnel_config import get_file_backed_funnel, get_funnel, upsert_funnel
from backend.funnel_config import list_funnels, list_funnels_by_whatsapp_referral_source_id

contadores_router = APIRouter(prefix="/api/contadores", tags=["contadores"])

OPENER_FOLLOWUP_SEQUENCE_STEP = "opener_followup_24h"
OPENER_FOLLOWUP_RETRY_SEQUENCE_STEP = "opener_followup_24h_template_retry_20260424"
MANUAL_PING_SEQUENCE_STEP = "manual_ping_template"
OPENER_FOLLOWUP_DELAY = timedelta(hours=24)
WHATSAPP_CUSTOM_MESSAGE_WINDOW = timedelta(hours=24)
CONTADORES_DELIVERY_MAX_ATTEMPTS = max(1, int(os.getenv("CONTADORES_DELIVERY_MAX_ATTEMPTS", "3")))
CONTADORES_DELIVERY_RETRY_DELAY_SECONDS = max(
    0,
    int(os.getenv("CONTADORES_DELIVERY_RETRY_DELAY_SECONDS", "60")),
)
ABOGADOS_FUNNEL_ID = "abogados"
ABOGADOS_PREFILLED_MESSAGE_ROUTE = "abogados_prefilled_proposal"
FOLLOWUP_DEFAULT_FUNNEL_IDS = {"contadores", ABOGADOS_FUNNEL_ID}
ABOGADOS_PREFILLED_WHATSAPP_TEXTS = {
    "hola quiero mas informacion de su propuesta para abogados",
}
FORM_LEAD_TAG = "form"
WHATSAPP_GENERAL_TAG = "whatsapp"
WHATSAPP_FUNNEL_TAG = "whatsapp_funnel"
BULK_SET_TAGS_ACTION = "set-tags"
VENEZUELA_MOBILE_PREFIXES = ("412", "414", "416", "424", "426")
PHONE_DIGITS_RE = re.compile(r"\D+")

WHATSAPP_DELIVERY_ERROR_BY_CODE = {
    130429: "WhatsApp throughput limit was reached. Retry later.",
    130497: "This WhatsApp Business Account is restricted from messaging this country.",
    131000: "WhatsApp failed with an unknown provider error.",
    131005: "WhatsApp rejected the send because the app is missing permission or access.",
    131008: "WhatsApp rejected the send because a required parameter is missing.",
    131009: "WhatsApp rejected the send because one of the parameters is invalid.",
    131016: "WhatsApp service is temporarily unavailable. Retry later.",
    131021: "The sender and recipient WhatsApp numbers are the same.",
    131026: (
        "WhatsApp could not deliver this message. Most common cause: the recipient phone "
        "is not registered on WhatsApp or cannot currently receive business messages."
    ),
    131030: "This recipient is not in the allowed list for the configured WhatsApp test number.",
    131031: "The WhatsApp Business Account is locked or restricted.",
    131042: "WhatsApp blocked the send because the business payment method has an issue.",
    131044: "WhatsApp blocked the send because the business payment method has an issue.",
    131047: (
        "WhatsApp blocked this free-form message because the 24-hour customer service "
        "window is closed. Use an approved template instead."
    ),
    131048: "WhatsApp rate-limited this phone number because recent messages looked like spam.",
    131050: "The user has opted out of marketing messages from this business.",
    131052: "WhatsApp could not download the media attached by the user.",
    131053: "WhatsApp could not upload the media file for this outbound message.",
    131056: "Too many messages were sent to the same recipient in a short period.",
    131057: "The WhatsApp Business Account is in maintenance mode.",
    132000: "The template parameters do not match the template definition.",
    132001: "The WhatsApp template does not exist in this language or has not been approved.",
    132005: "The WhatsApp template text is too long.",
    132007: "The WhatsApp template content violates a policy.",
    132008: "A WhatsApp template parameter value is invalid.",
    132012: "A WhatsApp template parameter format does not match the template definition.",
    132015: "The WhatsApp template is paused because of low quality.",
    132016: "The WhatsApp template was disabled because of repeated low quality.",
    135000: "WhatsApp failed with a generic provider error.",
}


def format_timestamp_seconds(value: datetime | None) -> str | None:
    """Format datetimes with second precision in UTC."""
    if value is None:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def require_internal_api_token(request: Request) -> None:
    """Require the machine-token header for automation-only endpoints."""
    if not has_valid_internal_api_token(request.headers.get(INTERNAL_API_TOKEN_HEADER)):
        raise HTTPException(status_code=401, detail="Internal authentication required.")


def phone_digits(value: str | None) -> str:
    """Return only digits from a phone-like value."""
    return PHONE_DIGITS_RE.sub("", value or "")


def is_likely_venezuelan_phone(*values: str | None) -> bool:
    """Return True for country-coded or local Venezuelan mobile numbers."""
    for value in values:
        digits = phone_digits(value)
        if digits.startswith("58"):
            return True
        if len(digits) == 11 and digits.startswith(("0412", "0414", "0416", "0424", "0426")):
            return True
        if len(digits) == 10 and digits.startswith(VENEZUELA_MOBILE_PREFIXES):
            return True
    return False


def normalize_followup_text(value: str | None) -> str:
    """Normalize short lead text for follow-up heuristics."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    plain_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(plain_text.casefold().split())


def now_utc() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def clean_delivery_error_part(value: object | None) -> str:
    """Normalize one provider error field for operator-facing text."""
    return " ".join(str(value or "").split()).strip()


def parse_delivery_error_code(*values: object | None) -> int | None:
    """Return the first explicit or embedded WhatsApp/Meta error code."""
    for value in values:
        clean_value = clean_delivery_error_part(value)
        if not clean_value:
            continue
        if clean_value.isdigit():
            return int(clean_value)
        match = re.search(r"\b(13\d{4}|130\d{3})\b", clean_value)
        if match:
            return int(match.group(1))
    return None


def append_delivery_error_detail(parts: list[str], label: str, value: object | None) -> None:
    """Append one non-empty detail once."""
    clean_value = clean_delivery_error_part(value)
    if not clean_value:
        return
    detail = f"{label}: {clean_value}"
    if detail not in parts:
        parts.append(detail)


def format_whatsapp_delivery_error(
    error: str | None = None,
    *,
    error_code: int | None = None,
    error_title: str | None = None,
    error_message: str | None = None,
    error_details: str | None = None,
    error_user_message: str | None = None,
) -> str:
    """Turn raw WhatsApp/Meta failure data into a useful operator explanation."""
    raw_error = clean_delivery_error_part(error)
    if raw_error.startswith(("WhatsApp could not", "WhatsApp blocked", "WhatsApp rejected", "WhatsApp reported")):
        return raw_error

    code = parse_delivery_error_code(error_code, raw_error, error_message, error_details)
    if code in WHATSAPP_DELIVERY_ERROR_BY_CODE:
        parts = [WHATSAPP_DELIVERY_ERROR_BY_CODE[code], f"Meta code: {code}."]
    else:
        normalized = raw_error.lower()
        if normalized in {"whatsapp_provider_status_failed", "failed"}:
            parts = [
                "WhatsApp reported delivery failure but did not include a reason. "
                "Check whether the phone exists on WhatsApp and can receive business messages."
            ]
        elif "invalid" in normalized and ("phone" in normalized or "recipient" in normalized):
            parts = ["Recipient phone looks invalid before sending. Check the country code and WhatsApp digits."]
        elif "missing" in normalized and ("phone" in normalized or "recipient" in normalized):
            parts = ["No WhatsApp recipient phone was available for this lead."]
        elif "media file not found" in normalized:
            parts = ["The media file configured for this WhatsApp message was not found on the server."]
        elif "provider is not configured" in normalized:
            parts = ["WhatsApp sending is not configured on the bot."]
        else:
            parts = [raw_error or "WhatsApp delivery failed, but the provider did not include a reason."]

    append_delivery_error_detail(parts, "Meta title", error_title)
    append_delivery_error_detail(parts, "Meta message", error_user_message or error_message)
    append_delivery_error_detail(parts, "Meta details", error_details)
    return " ".join(parts)[:2000]


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize DB datetimes so SQLite naive rows behave like UTC timestamps."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def resolve_funnel(funnel_id: str | None = None):
    """Return a configured funnel, defaulting to Contadores."""
    return get_funnel(funnel_id or "contadores") or get_contadores_funnel()


def build_opener_text(funnel_id: str | None = None) -> str:
    """Return the rendered opener text used in transcript history."""
    return resolve_funnel(funnel_id).opener_text


def build_loom_intro_text(funnel_id: str | None = None) -> str:
    """Return the pre-Loom explanatory text."""
    return resolve_funnel(funnel_id).loom_intro_text


def build_opener_followup_text(funnel_id: str | None = None) -> str:
    """Return the reminder sent 24 hours after the opener when there is no reply."""
    return resolve_funnel(funnel_id).opener_followup_text


def build_manual_ping_text(funnel_id: str | None = None) -> str:
    """Return the manual ping text used to reopen a WhatsApp window."""
    return resolve_funnel(funnel_id).manual_ping_text


def resolve_contadores_template_name(
    sequence_step: str | None,
    *,
    funnel_id: str | None = None,
) -> str | None:
    """Return the WhatsApp template name for template-backed Contadores steps."""
    funnel = resolve_funnel(funnel_id)
    if sequence_step == "opener":
        return funnel.opener_template_name
    if sequence_step in {OPENER_FOLLOWUP_SEQUENCE_STEP, OPENER_FOLLOWUP_RETRY_SEQUENCE_STEP}:
        return funnel.opener_followup_template_name
    if sequence_step == MANUAL_PING_SEQUENCE_STEP:
        return funnel.manual_ping_template_name
    return None


def is_whatsapp_custom_window_open(lead: ContadoresLead, *, now: datetime | None = None) -> bool:
    """Return True when non-template WhatsApp sends are still allowed."""
    last_inbound_at = ensure_utc_datetime(lead.last_inbound_at)
    if last_inbound_at is None:
        refreshed = ContadoresLead.get_by_id(lead.id)
        last_inbound_at = ensure_utc_datetime(refreshed.last_inbound_at) if refreshed else None
    if last_inbound_at is None:
        return False
    return (now or now_utc()) < last_inbound_at + WHATSAPP_CUSTOM_MESSAGE_WINDOW


def assert_lead_open_for_outbound(lead: ContadoresLead) -> None:
    """Reject any outbound WhatsApp send for a closed lead."""
    if derive_effective_lead_stage(lead) != ContadoresLeadStage.CLOSED:
        return
    raise HTTPException(
        status_code=400,
        detail="Lead is closed. Reopen the lead before sending WhatsApp messages.",
    )


def assert_whatsapp_custom_window_open(lead: ContadoresLead, *, sequence_step: str | None) -> None:
    """Reject non-template outbound messages outside WhatsApp's 24-hour window."""
    assert_lead_open_for_outbound(lead)
    if resolve_contadores_template_name(sequence_step, funnel_id=lead.funnel_id):
        return
    if is_whatsapp_custom_window_open(lead):
        return
    raise HTTPException(
        status_code=400,
        detail=(
            "WhatsApp 24-hour customer service window is closed for this lead. "
            "Send an approved template such as Manual ping instead of a custom message."
        ),
    )


def build_video_check_text(funnel_id: str | None = None) -> str:
    """Return the follow-up prompt sent after the Loom wait window."""
    return resolve_funnel(funnel_id).video_check_text


def build_calendly_intro_text(funnel_id: str | None = None) -> str:
    """Return the Calendly follow-up text."""
    return resolve_funnel(funnel_id).calendly_intro_text


def build_classifier_context() -> str:
    """Return stable classifier context instructions for post-Loom replies."""
    return (
        "Ya se enviaron: opener, explicación breve, video/propuesta y eventualmente la pregunta "
        "'¿conseguiste ver el video?'. Clasificá si la persona claramente quiere avanzar "
        "al siguiente paso o si necesita intervención humana."
    )


def build_calendly_url(*, base_url: str) -> str:
    """Return the shared Calendly URL without per-lead tracking."""
    return normalize_calendly_url(base_url)


def build_funnel_strategy_weights(funnel) -> dict[str, dict[str, int]]:
    """Return rollout weights encoded in a funnel definition."""
    weights: dict[str, dict[str, int]] = {}
    for strategy in funnel.strategies:
        weights.setdefault(strategy.step, {})[strategy.id] = strategy.weight
    return weights


def choose_contadores_strategy(
    *,
    step: str,
    lead_id: str,
    strategy_id: str | None = None,
    strategy_weights: dict[str, dict[str, int]] | None = None,
):
    """Compatibility wrapper for Contadores strategy selection."""
    return choose_default_contadores_strategy(
        step=step,
        lead_id=lead_id,
        strategy_id=strategy_id,
        strategy_weights=strategy_weights,
    )


def apply_funnel_to_config(config: ContadoresConfig, funnel) -> ContadoresConfig:
    """Overlay file-backed funnel fields onto the legacy runtime config row."""
    config.enabled = funnel.enabled
    config.sheet_url = funnel.sheet_url
    config.sheet_gid = funnel.sheet_gid
    config.sheet_poll_seconds = funnel.sheet_poll_seconds
    config.loom_url = funnel.loom_url
    config.calendly_base_url = funnel.calendly_base_url
    config.alert_emails_json = json.dumps(funnel.alert_emails)
    config.initial_reply_quiet_seconds = funnel.initial_reply_quiet_seconds
    config.post_loom_min_seconds = funnel.post_loom_min_seconds
    config.post_loom_quiet_seconds = funnel.post_loom_quiet_seconds
    config.strategy_weights_json = json.dumps(build_funnel_strategy_weights(funnel), ensure_ascii=True)
    return config


def get_effective_contadores_config() -> ContadoresConfig:
    """Return runtime config, preferring `data/funnels.json` when Contadores is file-backed."""
    return get_effective_funnel_config("contadores")


def get_effective_funnel_config(funnel_id: str | None = None) -> ContadoresConfig:
    """Return runtime config for one funnel, overlaying file-backed fields when present."""
    config = ContadoresConfig.get()
    clean_funnel_id = (funnel_id or "contadores").strip() or "contadores"
    funnel = get_file_backed_funnel(clean_funnel_id)
    if funnel is None and clean_funnel_id != "contadores":
        funnel = get_funnel(clean_funnel_id)
    if funnel is None:
        return config
    return apply_funnel_to_config(config, funnel)


def apply_config_update_to_file_backed_funnel(command: "UpdateContadoresConfigCommand") -> None:
    """Persist rollout-control edits into the shared funnel config file when enabled."""
    funnel = get_file_backed_funnel("contadores")
    if funnel is None:
        return

    updates: dict[str, Any] = {}
    for field_name in [
        "enabled",
        "sheet_url",
        "sheet_gid",
        "sheet_poll_seconds",
        "loom_url",
        "calendly_base_url",
        "alert_emails",
        "initial_reply_quiet_seconds",
        "post_loom_min_seconds",
        "post_loom_quiet_seconds",
    ]:
        value = getattr(command, field_name)
        if value is not None:
            updates[field_name] = value

    next_funnel = funnel.model_copy(update=updates)
    if command.strategy_weights is not None:
        strategies = []
        for strategy in next_funnel.strategies:
            weight = command.strategy_weights.get(strategy.step, {}).get(strategy.id, strategy.weight)
            strategies.append(strategy.model_copy(update={"weight": max(0, min(100, int(weight)))}))
        next_funnel = next_funnel.model_copy(update={"strategies": strategies})

    upsert_funnel(next_funnel)


def lead_has_new_inbound_after_calendly(lead: ContadoresLead) -> bool:
    """Return True when the lead replied after the latest Calendly handoff."""
    calendly_sent_at = ensure_utc_datetime(lead.calendly_sent_at)
    last_inbound_at = ensure_utc_datetime(lead.last_inbound_at)
    if calendly_sent_at is None or last_inbound_at is None or lead.booked_at is not None:
        return False
    return last_inbound_at > calendly_sent_at


def derive_effective_lead_stage(lead: ContadoresLead) -> ContadoresLeadStage:
    """Return the operator-facing stage derived from the clearest completed milestone."""
    if lead.stage == ContadoresLeadStage.ARCHIVED or lead.archived_at is not None:
        return ContadoresLeadStage.ARCHIVED
    if lead.stage == ContadoresLeadStage.CLOSED or lead.closed_at is not None:
        return ContadoresLeadStage.CLOSED
    if lead.booked_at is not None:
        return ContadoresLeadStage.BOOKED
    if lead.stage == ContadoresLeadStage.NEEDS_HUMAN:
        return ContadoresLeadStage.NEEDS_HUMAN
    if lead.calendly_sent_at is not None:
        return ContadoresLeadStage.CALENDLY_SENT
    return lead.stage


def lead_counts_in_calendly_bucket(lead: ContadoresLead) -> bool:
    """Return True when the lead should appear in the Calendly milestone bucket."""
    effective_stage = derive_effective_lead_stage(lead)
    if effective_stage in {
        ContadoresLeadStage.ARCHIVED,
        ContadoresLeadStage.CLOSED,
        ContadoresLeadStage.BOOKED,
    }:
        return False
    return lead.calendly_sent_at is not None


def derive_manual_reply_status(lead: ContadoresLead) -> str | None:
    """Return whether the current manual handoff needs an operator reply."""
    if derive_effective_lead_stage(lead) != ContadoresLeadStage.NEEDS_HUMAN:
        return None

    last_inbound_at = ensure_utc_datetime(lead.last_inbound_at)
    last_outbound_at = ensure_utc_datetime(lead.last_outbound_at)
    handled_at = ensure_utc_datetime(lead.manual_reply_handled_at)
    latest_answer_at = max(
        [item for item in [last_outbound_at, handled_at] if item is not None],
        default=None,
    )

    if last_inbound_at is not None and (latest_answer_at is None or last_inbound_at > latest_answer_at):
        return "needs_reply"
    if last_inbound_at is not None or latest_answer_at is not None:
        return "answered"
    return None


def get_lead_last_interaction_at(lead: ContadoresLead) -> datetime | None:
    """Return the newest inbound or outbound interaction timestamp for a lead."""
    timestamps = [
        ensure_utc_datetime(lead.last_inbound_at),
        ensure_utc_datetime(lead.last_outbound_at),
    ]
    interactions = [item for item in timestamps if item is not None]
    if interactions:
        return max(interactions)
    return ensure_utc_datetime(lead.created_at)


def sort_leads_by_last_interaction(leads: list[ContadoresLead]) -> list[ContadoresLead]:
    """Sort leads from newest interaction to oldest."""
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(
        leads,
        key=lambda lead: (
            get_lead_last_interaction_at(lead) or oldest,
            ensure_utc_datetime(lead.created_at) or oldest,
            lead.id,
        ),
        reverse=True,
    )


def build_contadores_metrics(leads: list[ContadoresLead]) -> "ContadoresMetrics":
    """Aggregate lead counts for the list view."""
    return ContadoresMetrics(
        total=len(leads),
        awaiting_initial_reply=sum(
            1 for item in leads if derive_effective_lead_stage(item) == ContadoresLeadStage.AWAITING_INITIAL_REPLY
        ),
        awaiting_video_reply=sum(
            1 for item in leads if derive_effective_lead_stage(item) == ContadoresLeadStage.AWAITING_VIDEO_REPLY
        ),
        needs_human=sum(1 for item in leads if derive_effective_lead_stage(item) == ContadoresLeadStage.NEEDS_HUMAN),
        calendly_sent=sum(1 for item in leads if lead_counts_in_calendly_bucket(item)),
        booked=sum(1 for item in leads if derive_effective_lead_stage(item) == ContadoresLeadStage.BOOKED),
        closed=sum(1 for item in leads if derive_effective_lead_stage(item) == ContadoresLeadStage.CLOSED),
        archived=sum(1 for item in leads if derive_effective_lead_stage(item) == ContadoresLeadStage.ARCHIVED),
    )


def build_manual_attention_counts() -> dict[str, int]:
    """Return operator-reply counts keyed by funnel id."""
    funnels = list_funnels()
    counts = {funnel.id: 0 for funnel in funnels}
    candidates = ContadoresLead.list_manual_attention_candidates(
        funnel_ids=[funnel.id for funnel in funnels],
    )
    for lead in candidates:
        if derive_manual_reply_status(lead) == "needs_reply":
            counts[lead.funnel_id] = counts.get(lead.funnel_id, 0) + 1
    return counts


def group_strategy_assignments_by_lead(funnel_id: str = "contadores") -> dict[str, list[ContadoresStrategyAssignment]]:
    """Return strategy assignments grouped by lead id."""
    grouped: dict[str, list[ContadoresStrategyAssignment]] = {}
    for assignment in ContadoresStrategyAssignment.list_all(funnel_id=funnel_id):
        grouped.setdefault(assignment.lead_id, []).append(assignment)
    return grouped


def lead_matches_strategy_filter(
    lead: ContadoresLead,
    *,
    assignments_by_lead: dict[str, list[ContadoresStrategyAssignment]],
    strategy_step: str | None,
    strategy_id: str | None,
) -> bool:
    """Return True when a lead has the selected strategy assignment."""
    normalized_step = (strategy_step or "").strip()
    normalized_strategy_id = (strategy_id or "").strip()
    if not normalized_step and not normalized_strategy_id:
        return True

    assignments = assignments_by_lead.get(lead.id, [])
    for assignment in assignments:
        if normalized_step and assignment.step != normalized_step:
            continue
        if normalized_strategy_id and assignment.strategy_id != normalized_strategy_id:
            continue
        return True
    return False


def lead_matches_tag_filter(lead: ContadoresLead, tag: str | None) -> bool:
    """Return True when the lead has the requested operator tag."""
    clean_tag = normalize_contadores_tags([tag or ""])
    if not clean_tag:
        return True
    tag_key = clean_tag[0].casefold()
    return any(item.casefold() == tag_key for item in lead.tags)


def build_tag_options(leads: list[ContadoresLead]) -> list[str]:
    """Return every tag used by a group of leads."""
    by_key: dict[str, str] = {}
    for lead in leads:
        for tag in lead.tags:
            by_key.setdefault(tag.casefold(), tag)
    return sorted(by_key.values(), key=str.casefold)


def build_contadores_strategy_stats(funnel_id: str = "contadores") -> "ContadoresStrategyStatsResponse":
    """Aggregate strategy assignment and conversion counts."""
    funnel = resolve_funnel(funnel_id)
    config = get_effective_funnel_config(funnel.id)
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    for strategy in list_funnel_strategies(funnel):
        stats[(strategy.step, strategy.id)] = {
            "step": strategy.step,
            "strategy_id": strategy.id,
            "strategy_label": strategy.label,
            "weight": get_contadores_strategy_weight(strategy, config.strategy_weights),
            "assigned": 0,
            "sent": 0,
            "delivered": 0,
            "reached_calendly": 0,
            "booked": 0,
        }

    assignments = ContadoresStrategyAssignment.list_all(funnel_id=funnel.id)
    with Session(engine) as session:
        message_rows = list(
            session.exec(
                select(ContadoresMessage).where(ContadoresMessage.strategy_assignment_id.is_not(None))
            ).all()
        )
        lead_rows = list(session.exec(select(ContadoresLead).where(ContadoresLead.funnel_id == funnel.id)).all())

    messages_by_assignment: dict[int, list[ContadoresMessage]] = {}
    for row in message_rows:
        if row.strategy_assignment_id is None:
            continue
        messages_by_assignment.setdefault(row.strategy_assignment_id, []).append(row)

    leads_by_id = {lead.id: lead for lead in lead_rows}
    for assignment in assignments:
        key = (assignment.step, assignment.strategy_id)
        if key not in stats:
            stats[key] = {
                "step": assignment.step,
                "strategy_id": assignment.strategy_id,
                "strategy_label": assignment.strategy_label or assignment.strategy_id,
                "weight": 0,
                "assigned": 0,
                "sent": 0,
                "delivered": 0,
                "reached_calendly": 0,
                "booked": 0,
            }

        item = stats[key]
        item["assigned"] += 1
        rows = messages_by_assignment.get(assignment.id or 0, [])
        if any(row.delivery_status in {MessageDeliveryStatus.SENT, MessageDeliveryStatus.DELIVERED} for row in rows):
            item["sent"] += 1
        if rows and all(row.delivery_status == MessageDeliveryStatus.DELIVERED for row in rows):
            item["delivered"] += 1

        lead = leads_by_id.get(assignment.lead_id)
        assigned_at = ensure_utc_datetime(assignment.assigned_at)
        calendly_sent_at = ensure_utc_datetime(lead.calendly_sent_at) if lead else None
        booked_at = ensure_utc_datetime(lead.booked_at) if lead else None
        if assigned_at is not None and calendly_sent_at is not None and calendly_sent_at >= assigned_at:
            item["reached_calendly"] += 1
        if assigned_at is not None and booked_at is not None and booked_at >= assigned_at:
            item["booked"] += 1

    items: list[ContadoresStrategyStatsItem] = []
    for raw in stats.values():
        assigned = int(raw["assigned"] or 0)
        items.append(
            ContadoresStrategyStatsItem(
                **raw,
                calendly_rate=round(raw["reached_calendly"] / assigned, 4) if assigned else 0.0,
                booked_rate=round(raw["booked"] / assigned, 4) if assigned else 0.0,
            )
        )
    return ContadoresStrategyStatsResponse(
        items=sorted(items, key=lambda item: (item.step, item.strategy_id))
    )


def infer_stage_from_timestamps(lead: ContadoresLead) -> ContadoresLeadStage:
    """Pick the most plausible active stage based on persisted milestones."""
    if lead.booked_at is not None:
        return ContadoresLeadStage.BOOKED
    if lead.calendly_sent_at is not None:
        return ContadoresLeadStage.CALENDLY_SENT
    if lead.loom_sent_at is not None:
        return ContadoresLeadStage.AWAITING_VIDEO_REPLY
    return ContadoresLeadStage.AWAITING_INITIAL_REPLY


def resolve_stage_before_closing(lead: ContadoresLead) -> ContadoresLeadStage:
    """Remember the lead stage that should come back after reopening."""
    effective_stage = derive_effective_lead_stage(lead)
    if effective_stage == ContadoresLeadStage.CLOSED and lead.stage_before_closed is not None:
        return lead.stage_before_closed
    if effective_stage == ContadoresLeadStage.CLOSED:
        return infer_stage_from_timestamps(lead)
    return effective_stage


def resolve_stage_after_reopening(lead: ContadoresLead) -> ContadoresLeadStage:
    """Restore the previous stage after a lead leaves the closed bucket."""
    if lead.stage_before_closed is not None and lead.stage_before_closed != ContadoresLeadStage.CLOSED:
        return lead.stage_before_closed
    return infer_stage_from_timestamps(lead)


def infer_resume_stage_from_timestamps(lead: ContadoresLead) -> ContadoresLeadStage:
    """Infer the stage to resume without changing archived leads unexpectedly."""
    if lead.stage == ContadoresLeadStage.ARCHIVED or lead.archived_at is not None:
        return ContadoresLeadStage.ARCHIVED
    return infer_stage_from_timestamps(lead)


def build_config_response(config: ContadoresConfig) -> "ContadoresConfigResponse":
    """Serialize config row for operator UI."""
    return ContadoresConfigResponse(
        enabled=config.enabled,
        sheet_url=config.sheet_url,
        sheet_gid=config.sheet_gid,
        sheet_poll_seconds=config.sheet_poll_seconds,
        loom_url=config.loom_url,
        calendly_base_url=config.calendly_base_url,
        alert_emails=config.alert_emails,
        initial_reply_quiet_seconds=config.initial_reply_quiet_seconds,
        post_loom_min_seconds=config.post_loom_min_seconds,
        post_loom_quiet_seconds=config.post_loom_quiet_seconds,
        strategy_weights=config.strategy_weights,
        last_sheet_sync_at=format_timestamp_seconds(config.last_sheet_sync_at),
        last_sheet_sync_status=config.last_sheet_sync_status,
        last_sheet_sync_note=config.last_sheet_sync_note,
        last_alert_at=format_timestamp_seconds(config.last_alert_at),
    )


def build_strategy_assignment_response(assignment: ContadoresStrategyAssignment) -> "ContadoresLeadStrategyAssignmentResponse":
    """Serialize a lead strategy assignment for list/detail filters."""
    return ContadoresLeadStrategyAssignmentResponse(
        id=assignment.id or 0,
        step=assignment.step,
        strategy_id=assignment.strategy_id,
        strategy_label=assignment.strategy_label,
        assigned_at=format_timestamp_seconds(assignment.assigned_at) or "",
    )


def build_lead_summary(
    lead: ContadoresLead,
    *,
    config: ContadoresConfig,
    strategy_assignments: list[ContadoresStrategyAssignment] | None = None,
) -> "ContadoresLeadSummary":
    """Serialize one lead row for list/detail views."""
    effective_stage = derive_effective_lead_stage(lead)
    workstation_client = WorkstationClient.get_by_lead_id(lead.id)
    outbound_error_count = ContadoresMessage.count_delivery_issues_by_lead(lead.id)
    return ContadoresLeadSummary(
        id=lead.id,
        funnel_id=lead.funnel_id,
        external_lead_id=lead.external_lead_id,
        phone=lead.phone,
        normalized_phone=lead.normalized_phone,
        full_name=lead.full_name,
        email=lead.email,
        platform=lead.platform,
        lead_status=lead.lead_status,
        tags=lead.tags,
        sheet_created_time=format_timestamp_seconds(lead.sheet_created_time),
        stage=effective_stage.value,
        raw_stage=lead.stage.value,
        calendly_url=build_calendly_url(base_url=config.calendly_base_url),
        last_classification_label=lead.last_classification_label,
        last_classification_reason=lead.last_classification_reason,
        opener_sent_at=format_timestamp_seconds(lead.opener_sent_at),
        first_reply_received_at=format_timestamp_seconds(lead.first_reply_received_at),
        loom_sent_at=format_timestamp_seconds(lead.loom_sent_at),
        video_check_sent_at=format_timestamp_seconds(lead.video_check_sent_at),
        classification_completed_at=format_timestamp_seconds(lead.classification_completed_at),
        calendly_sent_at=format_timestamp_seconds(lead.calendly_sent_at),
        booked_at=format_timestamp_seconds(lead.booked_at),
        closed_at=format_timestamp_seconds(lead.closed_at),
        stage_before_closed=lead.stage_before_closed.value if lead.stage_before_closed else None,
        needs_human_notified_at=format_timestamp_seconds(lead.needs_human_notified_at),
        manual_reply_status=derive_manual_reply_status(lead),
        manual_reply_handled_at=format_timestamp_seconds(lead.manual_reply_handled_at),
        last_inbound_at=format_timestamp_seconds(lead.last_inbound_at),
        last_outbound_at=format_timestamp_seconds(lead.last_outbound_at),
        archived_at=format_timestamp_seconds(lead.archived_at),
        strategy_assignments=[
            build_strategy_assignment_response(assignment)
            for assignment in (strategy_assignments or [])
        ],
        workstation_client_id=workstation_client.id if workstation_client else None,
        automation_paused=bool(lead.automation_paused),
        automation_paused_reason=lead.automation_paused_reason,
        outbound_error_count=outbound_error_count,
        latest_outbound_error=(
            format_whatsapp_delivery_error(ContadoresMessage.latest_delivery_issue_for_lead(lead.id))
            if outbound_error_count
            else None
        ),
        created_at=format_timestamp_seconds(lead.created_at) or "",
        updated_at=format_timestamp_seconds(lead.updated_at) or "",
    )


def build_message_response(message: ContadoresMessage) -> "ContadoresMessageResponse":
    """Serialize one stored lead message."""
    return ContadoresMessageResponse(
        id=message.id or 0,
        lead_id=message.lead_id,
        from_me=message.from_me,
        text=message.text,
        delivery_status=message.delivery_status.value,
        external_id=message.external_id,
        delivery_attempts=message.delivery_attempts,
        last_delivery_error=format_whatsapp_delivery_error(message.last_delivery_error)
        if message.last_delivery_error
        else None,
        last_delivery_error_at=format_timestamp_seconds(message.last_delivery_error_at),
        delivery_error_acknowledged_at=format_timestamp_seconds(message.delivery_error_acknowledged_at),
        dispatch_after=format_timestamp_seconds(message.dispatch_after) or "",
        sequence_step=message.sequence_step,
        strategy_assignment_id=message.strategy_assignment_id,
        strategy_step=message.strategy_step,
        strategy_id=message.strategy_id,
        strategy_label=message.strategy_label,
        media_type=message.media_type,
        media_path=message.media_path,
        media_caption=message.media_caption,
        media_mime_type=message.media_mime_type,
        media_filename=message.media_filename,
        media_sha256=message.media_sha256,
        media_id=message.media_id,
        media_url=build_message_media_url(message),
        created_at=format_timestamp_seconds(message.created_at) or "",
    )


def build_followup_message_snapshot(message: ContadoresMessage) -> ContadoresFollowupMessageSnapshot:
    """Serialize one message for automation snapshot consumers."""
    formatted_error = (
        format_whatsapp_delivery_error(message.last_delivery_error)
        if message.last_delivery_error
        else None
    )
    return ContadoresFollowupMessageSnapshot(
        id=message.id or 0,
        from_me=message.from_me,
        text=message.text,
        delivery_status=message.delivery_status.value,
        delivery_attempts=message.delivery_attempts,
        sequence_step=message.sequence_step,
        created_at=format_timestamp_seconds(message.created_at) or "",
        dispatch_after=format_timestamp_seconds(message.dispatch_after) or "",
        last_delivery_error=formatted_error,
        last_delivery_error_code=parse_delivery_error_code(message.last_delivery_error),
        delivery_error_acknowledged_at=format_timestamp_seconds(message.delivery_error_acknowledged_at),
    )


def build_followup_exclusion_reasons(
    lead: ContadoresLead,
    *,
    workstation_client: WorkstationClient | None,
    latest_outbound: ContadoresMessage | None,
) -> list[str]:
    """Return hard-stop reasons for CRM follow-up automation."""
    reasons: list[str] = []
    if is_likely_venezuelan_phone(lead.phone, lead.normalized_phone):
        reasons.append("venezuela")
    if workstation_client is not None:
        reasons.append("workstation_client")
    if derive_effective_lead_stage(lead) in {
        ContadoresLeadStage.CLOSED,
        ContadoresLeadStage.BOOKED,
        ContadoresLeadStage.ARCHIVED,
    }:
        reasons.append("closed_booked_or_archived")
    if latest_outbound and parse_delivery_error_code(latest_outbound.last_delivery_error) == 131050:
        reasons.append("marketing_opt_out")
    return reasons


def inbound_suggests_booking_time(message: ContadoresMessage | None) -> bool:
    """Return True when an inbound looks like a concrete call-time reply."""
    if message is None or message.from_me:
        return False
    text = normalize_followup_text(message.text)
    if not text:
        return False
    day_words = {
        "hoy",
        "manana",
        "pasado",
        "lunes",
        "martes",
        "miercoles",
        "jueves",
        "viernes",
        "sabado",
        "domingo",
    }
    has_day = any(re.search(rf"\b{day}\b", text) for day in day_words)
    has_date = bool(re.search(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b", text))
    has_time = bool(
        re.search(r"\b(?:a las\s*)?\d{1,2}(?::\d{2})?\s*(?:hs?|hrs?|am|pm)\b", text)
        or re.search(r"\ba las\s+\d{1,2}(?::\d{2})?\b", text)
    )
    has_call_word = any(
        word in text
        for word in ("llamada", "reunion", "reunir", "agendar", "agenda", "coordinar", "meet", "zoom")
    )
    has_email = bool(re.search(r"\b[^@\s]+@[^@\s]+\.[^@\s]+\b", text))
    return (has_time and (has_day or has_date or has_call_word)) or (has_email and has_call_word)


def build_followup_suggested_buckets(
    lead: ContadoresLead,
    *,
    latest_inbound: ContadoresMessage | None,
    latest_outbound: ContadoresMessage | None,
    exclusion_reasons: list[str],
) -> list[str]:
    """Return deterministic buckets for an automation to inspect."""
    if exclusion_reasons:
        return []

    buckets: list[str] = []
    effective_stage = derive_effective_lead_stage(lead)
    latest_error_code = (
        parse_delivery_error_code(latest_outbound.last_delivery_error)
        if latest_outbound
        else None
    )
    if (
        latest_outbound
        and latest_outbound.from_me
        and latest_outbound.delivery_status == MessageDeliveryStatus.FAILED
        and latest_outbound.delivery_error_acknowledged_at is None
    ):
        if latest_error_code in {130472, 131026, 131049, 131050}:
            buckets.append("provider_failure_review")
        else:
            buckets.append("repair_delivery")

    if inbound_suggests_booking_time(latest_inbound):
        buckets.append("booking_time_provided")
    if derive_manual_reply_status(lead) == "needs_reply":
        buckets.append("needs_answer_now")
    if effective_stage == ContadoresLeadStage.NEEDS_HUMAN and lead.last_inbound_at is not None:
        buckets.append("close_call")
    if effective_stage == ContadoresLeadStage.AWAITING_VIDEO_REPLY:
        buckets.append("retomar_video")
    if effective_stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY and lead.opener_sent_at is not None:
        buckets.append("opener_followup")
    return list(dict.fromkeys(buckets))


def build_followup_lead_snapshot(
    lead: ContadoresLead,
    *,
    messages_per_lead: int,
) -> ContadoresFollowupLeadSnapshot:
    """Build one read-only lead snapshot for external automation."""
    messages = ContadoresMessage.list_by_lead(lead.id)
    recent_messages = messages[-messages_per_lead:]
    latest_inbound = next((message for message in reversed(messages) if not message.from_me), None)
    latest_outbound = next((message for message in reversed(messages) if message.from_me), None)
    workstation_client = WorkstationClient.get_by_lead_id(lead.id)
    exclusion_reasons = build_followup_exclusion_reasons(
        lead,
        workstation_client=workstation_client,
        latest_outbound=latest_outbound,
    )
    suggested_buckets = build_followup_suggested_buckets(
        lead,
        latest_inbound=latest_inbound,
        latest_outbound=latest_outbound,
        exclusion_reasons=exclusion_reasons,
    )
    effective_stage = derive_effective_lead_stage(lead)
    return ContadoresFollowupLeadSnapshot(
        id=lead.id,
        funnel_id=lead.funnel_id,
        full_name=lead.full_name,
        email=lead.email,
        phone=lead.phone,
        normalized_phone=lead.normalized_phone,
        platform=lead.platform,
        tags=lead.tags,
        stage=effective_stage.value,
        raw_stage=lead.stage.value,
        manual_reply_status=derive_manual_reply_status(lead),
        last_inbound_at=format_timestamp_seconds(lead.last_inbound_at),
        last_outbound_at=format_timestamp_seconds(lead.last_outbound_at),
        opener_sent_at=format_timestamp_seconds(lead.opener_sent_at),
        loom_sent_at=format_timestamp_seconds(lead.loom_sent_at),
        video_check_sent_at=format_timestamp_seconds(lead.video_check_sent_at),
        calendly_sent_at=format_timestamp_seconds(lead.calendly_sent_at),
        booked_at=format_timestamp_seconds(lead.booked_at),
        closed_at=format_timestamp_seconds(lead.closed_at),
        archived_at=format_timestamp_seconds(lead.archived_at),
        automation_paused=bool(lead.automation_paused),
        workstation_client_id=workstation_client.id if workstation_client else None,
        excluded=bool(exclusion_reasons),
        exclusion_reasons=exclusion_reasons,
        suggested_buckets=suggested_buckets,
        latest_inbound=build_followup_message_snapshot(latest_inbound) if latest_inbound else None,
        latest_outbound=build_followup_message_snapshot(latest_outbound) if latest_outbound else None,
        recent_messages=[build_followup_message_snapshot(message) for message in recent_messages],
    )


def list_followup_snapshot_leads(
    *,
    limit: int,
    funnel_id: str | None,
    include_all_funnels: bool,
) -> list[ContadoresLead]:
    """List all CRM leads that the follow-up automation may inspect."""
    clean_funnel_id = (funnel_id or "").strip() or None
    leads = ContadoresLead.list_recent(
        limit=limit,
        funnel_id=clean_funnel_id,
        include_archived=True,
    )
    if clean_funnel_id is None and not include_all_funnels:
        leads = [lead for lead in leads if lead.funnel_id in FOLLOWUP_DEFAULT_FUNNEL_IDS]
    return leads


def build_followup_snapshot_response(
    leads: list[ContadoresLead],
    *,
    messages_per_lead: int,
) -> ContadoresFollowupSnapshotResponse:
    """Build a full read-only follow-up snapshot from lead rows."""
    snapshots = [
        build_followup_lead_snapshot(lead, messages_per_lead=messages_per_lead)
        for lead in leads
    ]

    bucket_counts: Counter[str] = Counter()
    exclusion_counts: Counter[str] = Counter()
    failed_code_counts: Counter[str] = Counter()
    for snapshot in snapshots:
        bucket_counts.update(snapshot.suggested_buckets)
        exclusion_counts.update(snapshot.exclusion_reasons)
        latest_outbound = snapshot.latest_outbound
        if latest_outbound and latest_outbound.delivery_status == MessageDeliveryStatus.FAILED.value:
            code = str(latest_outbound.last_delivery_error_code or "unknown")
            failed_code_counts[code] += 1

    return ContadoresFollowupSnapshotResponse(
        generated_at=format_timestamp_seconds(now_utc()) or "",
        funnel_ids=sorted({snapshot.funnel_id for snapshot in snapshots}),
        leads=snapshots,
        counts_by_bucket=dict(sorted(bucket_counts.items())),
        counts_by_exclusion_reason=dict(sorted(exclusion_counts.items())),
        failed_delivery_codes=dict(sorted(failed_code_counts.items())),
    )


def build_followup_snapshot_csv(snapshots: list[ContadoresFollowupLeadSnapshot]) -> str:
    """Return a flat CSV view of lead snapshots for automation analysis."""
    output = StringIO()
    fieldnames = [
        "lead_id",
        "funnel_id",
        "full_name",
        "email",
        "phone",
        "normalized_phone",
        "platform",
        "stage",
        "raw_stage",
        "manual_reply_status",
        "excluded",
        "exclusion_reasons",
        "suggested_buckets",
        "last_inbound_at",
        "last_outbound_at",
        "opener_sent_at",
        "loom_sent_at",
        "video_check_sent_at",
        "calendly_sent_at",
        "booked_at",
        "closed_at",
        "archived_at",
        "automation_paused",
        "workstation_client_id",
        "latest_inbound_text",
        "latest_outbound_text",
        "latest_outbound_status",
        "latest_outbound_error_code",
        "latest_outbound_error",
        "recent_transcript",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for snapshot in snapshots:
        latest_outbound = snapshot.latest_outbound
        recent_transcript = "\n".join(
            f"{'me' if message.from_me else 'lead'}: {message.text}"
            for message in snapshot.recent_messages
        )
        writer.writerow(
            {
                "lead_id": snapshot.id,
                "funnel_id": snapshot.funnel_id,
                "full_name": snapshot.full_name or "",
                "email": snapshot.email or "",
                "phone": snapshot.phone,
                "normalized_phone": snapshot.normalized_phone,
                "platform": snapshot.platform or "",
                "stage": snapshot.stage,
                "raw_stage": snapshot.raw_stage,
                "manual_reply_status": snapshot.manual_reply_status or "",
                "excluded": str(snapshot.excluded).lower(),
                "exclusion_reasons": ",".join(snapshot.exclusion_reasons),
                "suggested_buckets": ",".join(snapshot.suggested_buckets),
                "last_inbound_at": snapshot.last_inbound_at or "",
                "last_outbound_at": snapshot.last_outbound_at or "",
                "opener_sent_at": snapshot.opener_sent_at or "",
                "loom_sent_at": snapshot.loom_sent_at or "",
                "video_check_sent_at": snapshot.video_check_sent_at or "",
                "calendly_sent_at": snapshot.calendly_sent_at or "",
                "booked_at": snapshot.booked_at or "",
                "closed_at": snapshot.closed_at or "",
                "archived_at": snapshot.archived_at or "",
                "automation_paused": str(snapshot.automation_paused).lower(),
                "workstation_client_id": snapshot.workstation_client_id or "",
                "latest_inbound_text": snapshot.latest_inbound.text if snapshot.latest_inbound else "",
                "latest_outbound_text": latest_outbound.text if latest_outbound else "",
                "latest_outbound_status": latest_outbound.delivery_status if latest_outbound else "",
                "latest_outbound_error_code": latest_outbound.last_delivery_error_code if latest_outbound else "",
                "latest_outbound_error": latest_outbound.last_delivery_error if latest_outbound else "",
                "recent_transcript": recent_transcript,
            }
        )
    return output.getvalue()


def format_file_mtime(path: Path) -> str | None:
    """Return an ISO-ish UTC timestamp for a file mtime."""
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None
    return format_timestamp_seconds(modified_at)


def read_text_file(path: Path) -> str:
    """Read a text file for operator-facing diagnostics."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_text_tail(path: Path, max_lines: int) -> str:
    """Return the last lines of a text file without failing if it is absent."""
    text = read_text_file(path)
    if not text:
        return ""
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])


def parse_runner_pid(lock_dir: Path) -> int | None:
    """Read the runner pid from the lock directory."""
    raw_pid = read_text_file(lock_dir / "pid").strip()
    if not raw_pid:
        return None
    try:
        pid = int(raw_pid)
    except ValueError:
        return None
    return pid if pid > 0 else None


def process_is_visible(pid: int | None) -> bool:
    """Return True when the current host can see a running process."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def build_runner_log_item(path: Path) -> ContadoresRunnerLogItem:
    """Serialize one runner log file."""
    try:
        size_bytes = path.stat().st_size
    except OSError:
        size_bytes = 0
    return ContadoresRunnerLogItem(
        name=path.name,
        path=str(path),
        size_bytes=size_bytes,
        modified_at=format_file_mtime(path),
    )


def list_followup_runner_logs(limit: int) -> list[ContadoresRunnerLogItem]:
    """List recent timestamped CRM follow-up runner logs."""
    reports_dir = DATA_DIR / "reports"
    if not reports_dir.exists():
        return []
    log_paths = sorted(
        reports_dir.glob("contadores-crm-followup-*.log"),
        key=lambda path: path.stat().st_mtime if path.exists() else 0,
        reverse=True,
    )
    return [build_runner_log_item(path) for path in log_paths[:limit]]


def build_followup_runner_status(
    *,
    log_tail_lines: int = 120,
    log_limit: int = 12,
) -> ContadoresRunnerStatusResponse:
    """Build a read-only status snapshot from local runner artifacts."""
    reports_dir = DATA_DIR / "reports"
    lock_dir = DATA_DIR / "locks" / "contadores-crm-hourly-followup.lock"
    latest_summary_path = reports_dir / "contadores-crm-followup-latest.md"
    launchd_out_path = reports_dir / "launchd-contadores-crm-followup.out.log"
    launchd_err_path = reports_dir / "launchd-contadores-crm-followup.err.log"

    pid = parse_runner_pid(lock_dir) if lock_dir.exists() else None
    lock_age_seconds: int | None = None
    if lock_dir.exists():
        try:
            lock_age_seconds = max(0, int(now_utc().timestamp() - lock_dir.stat().st_mtime))
        except OSError:
            lock_age_seconds = None
    running = lock_dir.exists() and (
        process_is_visible(pid) or lock_age_seconds is None or lock_age_seconds < 21600
    )

    logs = list_followup_runner_logs(limit=log_limit)
    latest_log_path = Path(logs[0].path) if logs else None

    return ContadoresRunnerStatusResponse(
        generated_at=format_timestamp_seconds(now_utc()) or "",
        running=running,
        pid=pid,
        started_at=read_text_file(lock_dir / "started_at").strip() or None,
        lock_age_seconds=lock_age_seconds,
        latest_summary=read_text_file(latest_summary_path),
        latest_summary_updated_at=format_file_mtime(latest_summary_path),
        latest_log_path=str(latest_log_path) if latest_log_path else None,
        latest_log_tail=read_text_tail(latest_log_path, log_tail_lines) if latest_log_path else "",
        launchd_out_tail=read_text_tail(launchd_out_path, log_tail_lines),
        launchd_err_tail=read_text_tail(launchd_err_path, log_tail_lines),
        logs=logs,
    )


def normalize_message_for_dedupe(text: str) -> str:
    """Normalize outbound text enough to prevent accidental duplicate sends."""
    return " ".join(text.split()).strip()


def find_recent_duplicate_outbound(
    *,
    lead_id: str,
    text: str,
    dedupe_hours: int,
) -> ContadoresMessage | None:
    """Return a recent exact outbound duplicate if one exists."""
    if dedupe_hours <= 0:
        return None
    normalized_text = normalize_message_for_dedupe(text)
    if not normalized_text:
        return None
    cutoff = now_utc() - timedelta(hours=dedupe_hours)
    for message in reversed(ContadoresMessage.list_by_lead(lead_id)):
        created_at = ensure_utc_datetime(message.created_at)
        if created_at is not None and created_at < cutoff:
            return None
        if not message.from_me:
            continue
        if normalize_message_for_dedupe(message.text) == normalized_text:
            return message
    return None


def assert_followup_lead_can_receive_outbound(lead: ContadoresLead) -> None:
    """Block automation sends to hard-excluded leads."""
    latest_outbound = ContadoresMessage.get_latest_outbound_message(lead.id)
    workstation_client = WorkstationClient.get_by_lead_id(lead.id)
    exclusion_reasons = build_followup_exclusion_reasons(
        lead,
        workstation_client=workstation_client,
        latest_outbound=latest_outbound,
    )
    if exclusion_reasons:
        raise HTTPException(
            status_code=400,
            detail=f"Lead is excluded from follow-up: {', '.join(exclusion_reasons)}",
        )


def build_message_media_url(message: ContadoresMessage) -> str | None:
    """Return the protected API URL for stored message media."""
    media_path = (message.media_path or "").strip()
    if not media_path:
        return None
    return f"/api/contadores/media/{encode_media_path_token(media_path)}"


def allowed_message_media_roots() -> list[Path]:
    """Return filesystem roots from which stored message media may be served."""
    return [DATA_DIR.expanduser().resolve()]


def encode_media_path_token(media_path: str) -> str:
    """Encode one media path into a URL-safe stable token."""
    raw = (media_path or "").strip().encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_media_path_token(media_path_token: str) -> str:
    """Decode one URL-safe media path token."""
    clean_token = (media_path_token or "").strip()
    padding = "=" * (-len(clean_token) % 4)
    try:
        return base64.urlsafe_b64decode(f"{clean_token}{padding}".encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def resolve_message_media_file(media_path: str | None) -> Path | None:
    """Resolve one stored data/... media path without allowing path traversal."""
    clean_path = (media_path or "").strip()
    if not clean_path:
        return None

    media_roots = allowed_message_media_roots()
    data_dir = media_roots[0]
    candidate = Path(clean_path).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        parts = candidate.parts
        relative_parts = parts[1:] if parts and parts[0] == "data" else parts
        resolved = data_dir.joinpath(*relative_parts).resolve()

    for root in media_roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    return None


def safe_message_media_filename(filename: str | None) -> str:
    """Return a readable upload filename that cannot escape the media folder."""
    raw_name = Path(filename or "file").name
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", Path(raw_name).stem).strip(".-").lower()
    suffix = "".join(ch for ch in Path(raw_name).suffix.lower() if ch.isalnum() or ch == ".")[:12]
    return f"{stem or 'file'}{suffix}"


def classify_message_media_type(content_type: str | None, filename: str) -> str:
    """Map an uploaded file to the WhatsApp media family used by the bot."""
    media_type = (content_type or mimetypes.guess_type(filename)[0] or "").lower()
    if media_type.startswith("image/"):
        return "image"
    if media_type.startswith("video/"):
        return "video"
    if media_type.startswith("audio/"):
        return "audio"
    return "document"


async def save_manual_outbound_media_async(*, lead: ContadoresLead, upload: UploadFile) -> tuple[str, str, str, str | None]:
    """Persist one operator-uploaded outbound media file under the shared data volume."""
    contents = await upload.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    original_filename = Path(upload.filename or "file").name
    safe_name = safe_message_media_filename(original_filename)
    stored_filename = f"{uuid.uuid4().hex[:8]}-{safe_name}"
    target_dir = DATA_DIR / "contadores" / "outbound_media" / lead.id
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / stored_filename
    target_path.write_bytes(contents)

    content_type = upload.content_type or mimetypes.guess_type(safe_name)[0]
    media_type = classify_message_media_type(content_type, safe_name)
    relative_path = str(Path("data") / "contadores" / "outbound_media" / lead.id / stored_filename)
    return relative_path, media_type, original_filename, content_type


def enqueue_lead_outbound(
    *,
    lead: ContadoresLead,
    text: str,
    sequence_step: str,
    dispatch_after: datetime | None = None,
    strategy_assignment: ContadoresStrategyAssignment | None = None,
    media_type: str | None = None,
    media_path: str | None = None,
    media_caption: str | None = None,
    media_mime_type: str | None = None,
    media_filename: str | None = None,
) -> ContadoresMessage:
    """Create one pending outbound message."""
    assert_whatsapp_custom_window_open(lead, sequence_step=sequence_step)
    row = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=True,
        text=text,
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        dispatch_after=dispatch_after,
        sequence_step=sequence_step,
        strategy_assignment_id=strategy_assignment.id if strategy_assignment else None,
        strategy_step=strategy_assignment.step if strategy_assignment else None,
        strategy_id=strategy_assignment.strategy_id if strategy_assignment else None,
        strategy_label=strategy_assignment.strategy_label if strategy_assignment else None,
        media_type=media_type,
        media_path=media_path,
        media_caption=media_caption,
        media_mime_type=media_mime_type,
        media_filename=media_filename,
    )
    return row


def send_opener_sequence(*, lead: ContadoresLead) -> list[ContadoresMessage]:
    """Queue the first template-backed opener message."""
    opener = enqueue_lead_outbound(
        lead=lead,
        text=build_opener_text(lead.funnel_id),
        sequence_step="opener",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        opener_sent_at=opener.created_at,
        stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
    )
    return [opener]


def send_loom_sequence(
    *,
    lead: ContadoresLead,
    config: ContadoresConfig,
    strategy_id: str | None = None,
    assigned_by: str = "system",
) -> list[ContadoresMessage]:
    """Queue the selected Loom/video strategy."""
    assert_whatsapp_custom_window_open(lead, sequence_step="loom_intro")
    funnel = resolve_funnel(lead.funnel_id)
    if funnel.id == "contadores":
        strategy = choose_contadores_strategy(
            step=LOOM_STEP,
            lead_id=lead.id,
            strategy_id=strategy_id,
            strategy_weights=config.strategy_weights,
        )
    else:
        strategy = choose_funnel_strategy(
            funnel=funnel,
            step=LOOM_STEP,
            lead_id=lead.id,
            strategy_id=strategy_id,
            strategy_weights=config.strategy_weights,
        )
    assignment = ContadoresStrategyAssignment.add(
        lead_id=lead.id,
        step=strategy.step,
        strategy_id=strategy.id,
        strategy_label=strategy.label,
        assigned_by=assigned_by,
    )

    queued_rows: list[ContadoresMessage] = []
    first_dispatch_after: datetime | None = None
    for draft in strategy.build_messages(lead=lead, config=config):
        row = enqueue_lead_outbound(
            lead=lead,
            text=draft.text,
            sequence_step=draft.sequence_step,
            dispatch_after=first_dispatch_after,
            strategy_assignment=assignment,
            media_type=draft.media_type,
            media_path=draft.media_path,
            media_caption=draft.media_caption,
        )
        if first_dispatch_after is None:
            first_dispatch_after = row.dispatch_after
        queued_rows.append(row)

    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        loom_sent_at=queued_rows[0].created_at if queued_rows else now_utc(),
    )
    return queued_rows


def send_opener_followup(*, lead: ContadoresLead) -> list[ContadoresMessage]:
    """Queue the 24-hour opener reminder without changing the lead stage."""
    row = enqueue_lead_outbound(
        lead=lead,
        text=build_opener_followup_text(lead.funnel_id),
        sequence_step=OPENER_FOLLOWUP_SEQUENCE_STEP,
    )
    return [row]


def send_manual_ping_template(*, lead: ContadoresLead) -> list[ContadoresMessage]:
    """Queue the operator-triggered ping template."""
    row = enqueue_lead_outbound(
        lead=lead,
        text=build_manual_ping_text(lead.funnel_id),
        sequence_step=MANUAL_PING_SEQUENCE_STEP,
    )
    return [row]


def send_video_check(*, lead: ContadoresLead) -> list[ContadoresMessage]:
    """Queue the post-Loom follow-up question."""
    row = enqueue_lead_outbound(
        lead=lead,
        text=build_video_check_text(lead.funnel_id),
        sequence_step="video_check",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.AWAITING_VIDEO_REPLY,
        video_check_sent_at=row.created_at,
    )
    return [row]


def send_calendly_sequence(*, lead: ContadoresLead, config: ContadoresConfig) -> list[ContadoresMessage]:
    """Queue the Calendly explanation text + configured URL."""
    intro = enqueue_lead_outbound(
        lead=lead,
        text=build_calendly_intro_text(lead.funnel_id),
        sequence_step="calendly_intro",
    )
    calendly_url = enqueue_lead_outbound(
        lead=lead,
        text=build_calendly_url(base_url=config.calendly_base_url),
        sequence_step="calendly_url",
        dispatch_after=intro.dispatch_after,
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=intro.created_at,
        clear_needs_human_notified_at=True,
        automation_paused=False,
    )
    return [intro, calendly_url]


def send_calendly_link_only(*, lead: ContadoresLead, config: ContadoresConfig) -> list[ContadoresMessage]:
    """Queue only the configured Calendly URL and mark the milestone."""
    calendly_url = enqueue_lead_outbound(
        lead=lead,
        text=build_calendly_url(base_url=config.calendly_base_url),
        sequence_step="calendly_url",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.CALENDLY_SENT,
        calendly_sent_at=calendly_url.created_at,
        clear_needs_human_notified_at=True,
        automation_paused=False,
    )
    return [calendly_url]


def keep_manual_handoff_after_calendly_send(lead_id: str, *, sent_at: datetime) -> None:
    """Keep operator-sent Calendly leads in Manual while recording the milestone."""
    ContadoresLead.update_flow_state(
        lead_id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        calendly_sent_at=sent_at,
        automation_paused=True,
        automation_paused_reason="manual_calendly_send",
    )


def get_reply_batch_since_loom(lead_id: str, *, loom_sent_at: datetime | None) -> list[ContadoresMessage]:
    """Return inbound messages received after the Loom sequence started."""
    if loom_sent_at is None:
        return []
    resolved_loom_sent_at = ensure_utc_datetime(loom_sent_at)
    if resolved_loom_sent_at is None:
        return []
    return [
        row
        for row in ContadoresMessage.list_by_lead(lead_id)
        if not row.from_me and ensure_utc_datetime(row.created_at) >= resolved_loom_sent_at
    ]


def has_quiet_window(*, last_message_at: datetime | None, quiet_seconds: int, now: datetime) -> bool:
    """Return True when the quiet window already elapsed."""
    resolved_last_message_at = ensure_utc_datetime(last_message_at)
    if resolved_last_message_at is None:
        return False
    return now >= resolved_last_message_at + timedelta(seconds=quiet_seconds)


def queue_manual_message_for_lead(
    *,
    lead: ContadoresLead,
    text: str,
    media_path: str | None = None,
    media_type: str | None = None,
    media_filename: str | None = None,
    media_mime_type: str | None = None,
) -> list[ContadoresMessage]:
    """Queue one custom operator message and pause automation for the lead."""
    clean_text = text.strip()
    clean_media_type = (media_type or "").strip() or None
    display_text = clean_text
    if clean_media_type and not display_text:
        display_text = f"[{clean_media_type}] {media_filename or 'attachment'}"

    row = enqueue_lead_outbound(
        lead=lead,
        text=display_text,
        sequence_step="manual",
        media_type=clean_media_type,
        media_path=media_path,
        media_caption=clean_text if clean_media_type and clean_text else None,
        media_mime_type=media_mime_type,
        media_filename=media_filename,
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_message",
    )
    return [row]


def run_quick_action_for_lead(
    *,
    lead: ContadoresLead,
    action: str,
    config: ContadoresConfig,
) -> tuple[ContadoresLead, list[ContadoresMessage]]:
    """Run one operator quick action and return the refreshed lead plus queued rows."""
    queued_rows: list[ContadoresMessage] = []
    normalized_action = (action or "").strip().lower()
    pausing_send_actions = {"send-opener", "send-loom", "send-video-check", "send-manual-ping"}

    if normalized_action == "send-opener":
        queued_rows = send_opener_sequence(lead=lead)
    elif normalized_action == "send-manual-ping":
        if not resolve_funnel(lead.funnel_id).manual_ping_template_name:
            raise HTTPException(status_code=400, detail="Manual ping template is not configured")
        queued_rows = send_manual_ping_template(lead=lead)
    elif normalized_action in {"mark-booked", "send-manual-booked"}:
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.BOOKED,
            booked_at=now_utc(),
            automation_paused=True,
            automation_paused_reason="manual_booked",
        )
        return updated or lead, []
    elif normalized_action == "send-loom":
        queued_rows = send_loom_sequence(lead=lead, config=config, assigned_by="operator")
    elif normalized_action == "send-video-check":
        queued_rows = send_video_check(lead=lead)
    elif normalized_action == "send-calendly":
        queued_rows = send_calendly_sequence(lead=lead, config=config)
        if queued_rows:
            keep_manual_handoff_after_calendly_send(lead.id, sent_at=queued_rows[0].created_at)
    elif normalized_action == "send-calendly-link":
        queued_rows = send_calendly_link_only(lead=lead, config=config)
        if queued_rows:
            keep_manual_handoff_after_calendly_send(lead.id, sent_at=queued_rows[0].created_at)
    elif normalized_action == "mark-answered":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            manual_reply_handled_at=now_utc(),
        )
        return updated or lead, []
    elif normalized_action == "close":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.CLOSED,
            closed_at=now_utc(),
            stage_before_closed=resolve_stage_before_closing(lead),
        )
        return updated or lead, []
    elif normalized_action == "reopen":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=resolve_stage_after_reopening(lead),
            clear_closed_at=True,
            clear_stage_before_closed=True,
        )
        return updated or lead, []
    elif normalized_action == "archive":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.ARCHIVED,
            archived_at=now_utc(),
        )
        return updated or lead, []
    elif normalized_action == "unarchive":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
            clear_archived_at=True,
        )
        return updated or lead, []
    else:
        raise HTTPException(status_code=404, detail="Unknown quick action")

    if normalized_action in pausing_send_actions:
        ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.NEEDS_HUMAN,
            automation_paused=True,
            automation_paused_reason=f"manual_{normalized_action}",
        )
    return ContadoresLead.get_by_id(lead.id) or lead, queued_rows


def list_contadores_matches_by_replied_message(in_reply_to: str | None) -> tuple[list[ContadoresLead], bool]:
    """Resolve Contadores lead candidates from replied outbound WhatsApp id."""
    replied_external_id = (in_reply_to or "").strip()
    if not replied_external_id:
        return [], False
    matches: list[ContadoresLead] = []
    seen_ids: set[str] = set()
    for row in ContadoresMessage.list_by_external_id(replied_external_id, from_me=True):
        lead = ContadoresLead.get_by_id(row.lead_id)
        if not lead or lead.stage == ContadoresLeadStage.ARCHIVED:
            continue
        if lead.id in seen_ids:
            continue
        seen_ids.add(lead.id)
        matches.append(lead)
    return matches, len(matches) > 1


def build_phone_lookup_variants(phone: str) -> list[str]:
    """Return normalized phone keys that can represent the same WhatsApp sender."""
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return []

    variants = [normalized_phone]
    if normalized_phone.startswith("521") and len(normalized_phone) == 13:
        variants.append(f"52{normalized_phone[3:]}")
    elif normalized_phone.startswith("52") and len(normalized_phone) == 12:
        variants.append(f"521{normalized_phone[2:]}")

    return list(dict.fromkeys(variants))


def list_contadores_matches_by_phone(
    phone: str,
    *,
    funnel_id: str | None = None,
) -> tuple[list[ContadoresLead], bool]:
    """Resolve Contadores leads from normalized phone."""
    matches_by_id: dict[str, ContadoresLead] = {}
    for normalized_phone in build_phone_lookup_variants(phone):
        for lead in ContadoresLead.list_by_normalized_phone(normalized_phone, include_archived=False):
            matches_by_id[lead.id] = lead
    matches = list(matches_by_id.values())
    if funnel_id is not None:
        clean_funnel_id = (funnel_id or "").strip() or "contadores"
        matches = [lead for lead in matches if lead.funnel_id == clean_funnel_id]
    return matches, len(matches) > 1


class ContadoresMetrics(BaseModel):
    """Lead counts shown in Contadores overview."""

    total: int = 0
    awaiting_initial_reply: int = 0
    awaiting_video_reply: int = 0
    needs_human: int = 0
    calendly_sent: int = 0
    booked: int = 0
    closed: int = 0
    archived: int = 0


class ContadoresStrategyStatsItem(BaseModel):
    """Aggregated conversion stats for one strategy."""

    step: str
    strategy_id: str
    strategy_label: str
    weight: int = 0
    assigned: int = 0
    sent: int = 0
    delivered: int = 0
    reached_calendly: int = 0
    booked: int = 0
    calendly_rate: float = 0.0
    booked_rate: float = 0.0


class ContadoresStrategyStatsResponse(BaseModel):
    """Strategy stats payload for operator UI."""

    items: list[ContadoresStrategyStatsItem] = Field(default_factory=list)


class ManualAttentionCountsResponse(BaseModel):
    """Needs-answer counts grouped by funnel."""

    counts: dict[str, int] = Field(default_factory=dict)


class ContadoresLeadStrategyAssignmentResponse(BaseModel):
    """One strategy assignment attached to a lead."""

    id: int
    step: str
    strategy_id: str
    strategy_label: str
    assigned_at: str


class ContadoresConfigResponse(BaseModel):
    """Serialized Contadores config for UI."""

    enabled: bool
    sheet_url: str | None = None
    sheet_gid: str | None = None
    sheet_poll_seconds: int
    loom_url: str
    calendly_base_url: str
    alert_emails: list[str] = Field(default_factory=list)
    initial_reply_quiet_seconds: int
    post_loom_min_seconds: int
    post_loom_quiet_seconds: int
    strategy_weights: dict[str, dict[str, int]] = Field(default_factory=dict)
    last_sheet_sync_at: str | None = None
    last_sheet_sync_status: str | None = None
    last_sheet_sync_note: str | None = None
    last_alert_at: str | None = None


class UpdateContadoresConfigCommand(BaseModel):
    """Config update payload."""

    enabled: bool | None = None
    sheet_url: str | None = None
    sheet_gid: str | None = None
    sheet_poll_seconds: int | None = Field(default=None, ge=30)
    loom_url: str | None = None
    calendly_base_url: str | None = None
    alert_emails: list[str] | None = None
    initial_reply_quiet_seconds: int | None = Field(default=None, ge=1)
    post_loom_min_seconds: int | None = Field(default=None, ge=60)
    post_loom_quiet_seconds: int | None = Field(default=None, ge=1)
    strategy_weights: dict[str, dict[str, int]] | None = None


class ContadoresLeadSummary(BaseModel):
    """List/detail summary for one lead."""

    id: str
    funnel_id: str = "contadores"
    external_lead_id: str
    phone: str
    normalized_phone: str
    full_name: str | None = None
    email: str | None = None
    platform: str | None = None
    lead_status: str | None = None
    tags: list[str] = Field(default_factory=list)
    sheet_created_time: str | None = None
    stage: str
    raw_stage: str
    calendly_url: str
    last_classification_label: str | None = None
    last_classification_reason: str | None = None
    opener_sent_at: str | None = None
    first_reply_received_at: str | None = None
    loom_sent_at: str | None = None
    video_check_sent_at: str | None = None
    classification_completed_at: str | None = None
    calendly_sent_at: str | None = None
    booked_at: str | None = None
    closed_at: str | None = None
    stage_before_closed: str | None = None
    needs_human_notified_at: str | None = None
    manual_reply_status: str | None = None
    manual_reply_handled_at: str | None = None
    last_inbound_at: str | None = None
    last_outbound_at: str | None = None
    archived_at: str | None = None
    strategy_assignments: list[ContadoresLeadStrategyAssignmentResponse] = Field(default_factory=list)
    workstation_client_id: str | None = None
    automation_paused: bool = False
    automation_paused_reason: str | None = None
    outbound_error_count: int = 0
    latest_outbound_error: str | None = None
    created_at: str
    updated_at: str


class ContadoresMessageResponse(BaseModel):
    """Serialized Contadores message."""

    id: int
    lead_id: str
    from_me: bool
    text: str
    delivery_status: str
    external_id: str | None = None
    delivery_attempts: int = 0
    last_delivery_error: str | None = None
    last_delivery_error_at: str | None = None
    delivery_error_acknowledged_at: str | None = None
    dispatch_after: str
    sequence_step: str | None = None
    strategy_assignment_id: int | None = None
    strategy_step: str | None = None
    strategy_id: str | None = None
    strategy_label: str | None = None
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None
    media_sha256: str | None = None
    media_id: str | None = None
    media_url: str | None = None
    created_at: str


class ContadoresLeadListResponse(BaseModel):
    """List endpoint payload."""

    metrics: ContadoresMetrics
    config: ContadoresConfigResponse
    leads: list[ContadoresLeadSummary] = Field(default_factory=list)
    tag_options: list[str] = Field(default_factory=list)


class ContadoresLeadDetailResponse(BaseModel):
    """Detail endpoint payload."""

    lead: ContadoresLeadSummary
    config: ContadoresConfigResponse
    messages: list[ContadoresMessageResponse] = Field(default_factory=list)


class ContadoresFollowupMessageSnapshot(BaseModel):
    """Small message view for external CRM automation analysis."""

    id: int
    from_me: bool
    text: str
    delivery_status: str
    delivery_attempts: int = 0
    sequence_step: str | None = None
    created_at: str
    dispatch_after: str
    last_delivery_error: str | None = None
    last_delivery_error_code: int | None = None
    delivery_error_acknowledged_at: str | None = None


class ContadoresFollowupLeadSnapshot(BaseModel):
    """One lead plus the fields an automation needs to decide next action."""

    id: str
    funnel_id: str
    full_name: str | None = None
    email: str | None = None
    phone: str
    normalized_phone: str
    platform: str | None = None
    tags: list[str] = Field(default_factory=list)
    stage: str
    raw_stage: str
    manual_reply_status: str | None = None
    last_inbound_at: str | None = None
    last_outbound_at: str | None = None
    opener_sent_at: str | None = None
    loom_sent_at: str | None = None
    video_check_sent_at: str | None = None
    calendly_sent_at: str | None = None
    booked_at: str | None = None
    closed_at: str | None = None
    archived_at: str | None = None
    automation_paused: bool = False
    workstation_client_id: str | None = None
    excluded: bool = False
    exclusion_reasons: list[str] = Field(default_factory=list)
    suggested_buckets: list[str] = Field(default_factory=list)
    latest_inbound: ContadoresFollowupMessageSnapshot | None = None
    latest_outbound: ContadoresFollowupMessageSnapshot | None = None
    recent_messages: list[ContadoresFollowupMessageSnapshot] = Field(default_factory=list)


class ContadoresFollowupSnapshotResponse(BaseModel):
    """Read-only CRM snapshot for automation runners that cannot SSH."""

    generated_at: str
    funnel_ids: list[str] = Field(default_factory=list)
    leads: list[ContadoresFollowupLeadSnapshot] = Field(default_factory=list)
    counts_by_bucket: dict[str, int] = Field(default_factory=dict)
    counts_by_exclusion_reason: dict[str, int] = Field(default_factory=dict)
    failed_delivery_codes: dict[str, int] = Field(default_factory=dict)


class ContadoresRunnerLogItem(BaseModel):
    """One CRM follow-up runner log file."""

    name: str
    path: str
    size_bytes: int
    modified_at: str | None = None


class ContadoresRunnerStatusResponse(BaseModel):
    """Read-only status for the local CRM follow-up runner artifacts."""

    generated_at: str
    running: bool = False
    pid: int | None = None
    started_at: str | None = None
    lock_age_seconds: int | None = None
    latest_summary: str = ""
    latest_summary_updated_at: str | None = None
    latest_log_path: str | None = None
    latest_log_tail: str = ""
    launchd_out_tail: str = ""
    launchd_err_tail: str = ""
    logs: list[ContadoresRunnerLogItem] = Field(default_factory=list)


class ContadoresFollowupSendMessageCommand(BaseModel):
    """Internal automation command to queue one manual outbound message."""

    text: str = Field(min_length=1)
    dedupe_hours: int = Field(default=24, ge=0, le=720)


class ContadoresFollowupActionCommand(BaseModel):
    """Internal automation command to run one existing lead quick action."""

    action: str = Field(min_length=1)


class ContadoresFollowupLeadUpdateCommand(BaseModel):
    """Internal automation command to update one lead's CRM classification."""

    stage: str | None = None
    classification_label: str | None = None
    classification_reason: str | None = None
    manual_reply_status: Literal["needs_reply", "answered"] | None = None
    automation_paused: bool | None = None
    automation_paused_reason: str | None = None
    tags: list[str] | None = None


class ImportContadoresLeadRow(BaseModel):
    """One sheet row import payload."""

    id: str = Field(min_length=1)
    created_time: datetime | None = None
    platform: str | None = None
    email: str | None = None
    full_name: str | None = None
    phone_number: str = Field(min_length=1)
    lead_status: str | None = None
    is_contactado: str | bool | None = None


class ImportContadoresLeadsCommand(BaseModel):
    """Batch import command from bot sheet sync."""

    funnel_id: str = "contadores"
    rows: list[ImportContadoresLeadRow] = Field(default_factory=list)


class ImportContadoresLeadsResponse(BaseModel):
    """Batch import result."""

    imported: int = 0
    updated: int = 0
    skipped: int = 0
    lead_ids: list[str] = Field(default_factory=list)


class CreateContadoresMessageCommand(BaseModel):
    """Manual outbound composer payload."""

    text: str = Field(min_length=1)


class UpdateContadoresLeadTagsCommand(BaseModel):
    """Operator tags for one lead."""

    tags: list[str] = Field(default_factory=list)


class MoveContadoresLeadCommand(BaseModel):
    """Move one lead into another funnel and stage."""

    funnel_id: str = Field(min_length=1)
    stage: str = Field(default=ContadoresLeadStage.NEEDS_HUMAN.value)


class BulkContadoresActionCommand(BaseModel):
    """Batch action payload for selected operator chats."""

    lead_ids: list[str] = Field(default_factory=list, min_length=1, max_length=500)
    action: str = Field(min_length=1)
    text: str | None = None
    tags: list[str] = Field(default_factory=list)
    manual_ping_confirmed: bool = False


class ContadoresQuickActionResponse(BaseModel):
    """Result after one quick action or manual queue."""

    lead: ContadoresLeadSummary
    queued_message_ids: list[int] = Field(default_factory=list)


class ContadoresBulkActionItem(BaseModel):
    """Result for one lead in a batch action."""

    lead_id: str
    ok: bool
    lead: ContadoresLeadSummary | None = None
    queued_message_ids: list[int] = Field(default_factory=list)
    error: str | None = None


class ContadoresBulkActionResponse(BaseModel):
    """Batch action result for selected operator chats."""

    action: str
    total: int
    succeeded: int
    failed: int
    queued_message_ids: list[int] = Field(default_factory=list)
    results: list[ContadoresBulkActionItem] = Field(default_factory=list)


class DeleteContadoresLeadResponse(BaseModel):
    """Deletion result for one Contadores lead."""

    status: str
    lead_id: str


class PendingContadoresDeliveryMessage(BaseModel):
    """One pending Contadores outbound message."""

    message_id: int
    lead_id: str
    external_lead_id: str
    phone: str
    normalized_phone: str
    full_name: str | None = None
    text: str
    dispatch_after: str
    created_at: str
    sequence_step: str | None = None
    strategy_assignment_id: int | None = None
    strategy_step: str | None = None
    strategy_id: str | None = None
    strategy_label: str | None = None
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None
    contact_has_inbound: bool = False
    whatsapp_template_name: str | None = None
    whatsapp_template_language: str | None = None
    whatsapp_template_body_params: list[str] = Field(default_factory=list)


class PendingContadoresDeliveryResponse(BaseModel):
    """Pending delivery payload for bot dispatch."""

    messages: list[PendingContadoresDeliveryMessage] = Field(default_factory=list)


class SetContadoresMessageDeliveryCommand(BaseModel):
    """Provider delivery update keyed by external id."""

    external_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    error: str | None = None
    error_code: int | None = None
    error_title: str | None = None
    error_message: str | None = None
    error_details: str | None = None
    error_user_message: str | None = None


class SetContadoresMessageDeliveryByIdCommand(BaseModel):
    """Provider delivery update keyed by message id."""

    status: str = Field(min_length=1)
    external_id: str | None = None


class RecordContadoresMessageFailureCommand(BaseModel):
    """Provider send failure keyed by local message id."""

    error: str = Field(min_length=1)
    error_code: int | None = None
    error_title: str | None = None
    error_message: str | None = None
    error_details: str | None = None
    error_user_message: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_delay_seconds: int = Field(default=60, ge=0, le=3600)


class UpdateContadoresMessageCommand(BaseModel):
    """Manual text update for one stored Contadores message."""

    text: str = Field(min_length=1)


class WhatsAppReferralContext(BaseModel):
    """Click-to-WhatsApp referral metadata forwarded by the bot."""

    source_type: str | None = None
    source_id: str | None = None
    headline: str | None = None
    body: str | None = None
    ctwa_clid: str | None = None


class ContadoresWhatsAppInboundCommand(BaseModel):
    """Raw inbound WhatsApp event delivered by the bot."""

    phone: str = Field(min_length=1)
    text: str = Field(min_length=1)
    profile_name: str | None = None
    external_id: str | None = None
    in_reply_to: str | None = None
    referral: WhatsAppReferralContext | None = None
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None
    media_sha256: str | None = None
    media_id: str | None = None


class ContadoresWhatsAppInboundResponse(BaseModel):
    """Result of unified WhatsApp inbound routing."""

    status: str
    route: str | None = None
    lead_id: str | None = None
    company_id: str | None = None
    contact_id: str | None = None
    task_id: str | None = None
    reason: str | None = None


def get_referral_source_id(referral: WhatsAppReferralContext | None) -> str:
    """Return the configured source id from a CTWA referral."""
    return str(getattr(referral, "source_id", "") or "").strip()


def normalize_prefilled_whatsapp_text(value: str | None) -> str:
    """Normalize user-editable WhatsApp text for narrow routing fallbacks."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    plain_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", plain_text.casefold()).split())


def resolve_prefilled_whatsapp_route(text: str | None) -> tuple[str, str] | None:
    """Return the funnel route for explicitly approved prefilled WhatsApp text."""
    normalized_text = normalize_prefilled_whatsapp_text(text)
    if normalized_text in ABOGADOS_PREFILLED_WHATSAPP_TEXTS:
        return ABOGADOS_FUNNEL_ID, ABOGADOS_PREFILLED_MESSAGE_ROUTE
    return None


def build_ctwa_external_lead_id(*, funnel_id: str, phone: str) -> str | None:
    """Build the stable external id used for Click-to-WhatsApp leads."""
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return None
    return f"ctwa:{(funnel_id or '').strip() or 'contadores'}:{normalized_phone}"


def build_general_inbox_external_lead_id(*, phone: str) -> str | None:
    """Build the stable external id used for unmatched WhatsApp inbox leads."""
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return None
    return f"whatsapp:{GENERAL_INBOX_FUNNEL_ID}:{normalized_phone}"


def normalize_whatsapp_profile_name(value: str | None) -> str | None:
    """Normalize the sender profile name Meta includes in WhatsApp webhooks."""
    clean_name = " ".join((value or "").split()).strip()
    return clean_name or None


def resolve_inbound_full_name(
    *,
    existing: ContadoresLead | None,
    command: ContadoresWhatsAppInboundCommand,
) -> str | None:
    """Prefer the latest WhatsApp profile name, preserving existing names when absent."""
    return normalize_whatsapp_profile_name(command.profile_name) or (existing.full_name if existing else None)


def fill_missing_lead_name_from_whatsapp(
    *,
    lead: ContadoresLead,
    command: ContadoresWhatsAppInboundCommand,
) -> ContadoresLead:
    """Use WhatsApp profile name for matched leads that still only have a phone."""
    profile_name = normalize_whatsapp_profile_name(command.profile_name)
    if not profile_name or lead.full_name:
        return lead
    return ContadoresLead.set_full_name_if_missing(lead.id, full_name=profile_name) or lead


def upsert_ctwa_lead_from_inbound(
    *,
    funnel_id: str,
    command: ContadoresWhatsAppInboundCommand,
) -> tuple[ContadoresLead, bool]:
    """Create or refresh one lead that entered through a Click-to-WhatsApp ad."""
    external_lead_id = build_ctwa_external_lead_id(funnel_id=funnel_id, phone=command.phone)
    if external_lead_id is None:
        raise ValueError("phone is invalid")

    existing = ContadoresLead.get_by_external_lead_id(external_lead_id, funnel_id=funnel_id)
    reset_flow = existing is not None and existing.stage in {
        ContadoresLeadStage.ARCHIVED,
        ContadoresLeadStage.BOOKED,
        ContadoresLeadStage.CLOSED,
    }
    lead = ContadoresLead.upsert(
        funnel_id=funnel_id,
        external_lead_id=external_lead_id,
        phone=command.phone,
        full_name=resolve_inbound_full_name(existing=existing, command=command),
        platform="whatsapp_ctwa",
        lead_status="new",
        tags=[WHATSAPP_FUNNEL_TAG],
        sheet_created_time=now_utc(),
        reset_flow=reset_flow,
    )
    return lead, existing is None


def upsert_general_inbox_lead_from_inbound(
    *,
    command: ContadoresWhatsAppInboundCommand,
) -> tuple[ContadoresLead, bool]:
    """Create or refresh one lead for the general WhatsApp inbox."""
    external_lead_id = build_general_inbox_external_lead_id(phone=command.phone)
    if external_lead_id is None:
        raise ValueError("phone is invalid")

    existing = ContadoresLead.get_by_external_lead_id(
        external_lead_id,
        funnel_id=GENERAL_INBOX_FUNNEL_ID,
    )
    lead = ContadoresLead.upsert(
        funnel_id=GENERAL_INBOX_FUNNEL_ID,
        external_lead_id=external_lead_id,
        phone=command.phone,
        full_name=resolve_inbound_full_name(existing=existing, command=command),
        platform="whatsapp_general",
        lead_status="new",
        tags=[WHATSAPP_GENERAL_TAG],
        sheet_created_time=now_utc(),
        reset_flow=existing is not None and existing.stage == ContadoresLeadStage.ARCHIVED,
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="general_inbox",
    )
    return ContadoresLead.get_by_id(lead.id) or lead, existing is None


def record_whatsapp_inbound_for_lead(
    *,
    lead: ContadoresLead,
    command: ContadoresWhatsAppInboundCommand,
) -> tuple[ContadoresLead, ContadoresMessage]:
    """Persist one inbound WhatsApp message."""
    row = ContadoresMessage.add(
        lead_id=lead.id,
        from_me=False,
        text=command.text,
        external_id=command.external_id,
        media_type=command.media_type,
        media_path=command.media_path,
        media_caption=command.media_caption,
        media_mime_type=command.media_mime_type,
        media_filename=command.media_filename,
        media_sha256=command.media_sha256,
        media_id=command.media_id,
    )
    return ContadoresLead.get_by_id(lead.id) or lead, row


class ContadoresAutomationTickResponse(BaseModel):
    """Result of one automation tick."""

    status: str
    opener_sent: int = 0
    loom_sent: int = 0
    video_checks_sent: int = 0
    classified_wants_to_proceed: int = 0
    classified_needs_human: int = 0
    calendly_sent: int = 0


class PendingContadoresAlertItem(BaseModel):
    """One lead that needs human alerting."""

    lead_id: str
    full_name: str | None = None
    phone: str
    email: str | None = None
    stage: str
    latest_inbound_text: str | None = None
    reason: str | None = None
    alert_emails: list[str] = Field(default_factory=list)


class PendingContadoresAlertsResponse(BaseModel):
    """Pending alert payload for bot email notifications."""

    items: list[PendingContadoresAlertItem] = Field(default_factory=list)


class MarkContadoresAlertedCommand(BaseModel):
    """Command to mark a needs_human alert as already sent."""

    sent_at: datetime | None = None


class MarkContadoresBookedCommand(BaseModel):
    """Manual or webhook booking mark command."""

    booked_at: datetime | None = None


class ContadoresCalendlyWebhookCommand(BaseModel):
    """Bot-delivered Calendly webhook payload reduced to tracking token."""

    token: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    occurred_at: datetime | None = None


@contadores_router.get("/config", response_model=ContadoresConfigResponse)
async def get_contadores_config(
    funnel_id: str = Query(default="contadores"),
) -> ContadoresConfigResponse:
    """Return current Contadores config."""
    return build_config_response(get_effective_funnel_config(funnel_id))


@contadores_router.put("/config", response_model=ContadoresConfigResponse)
async def update_contadores_config(
    command: UpdateContadoresConfigCommand,
) -> ContadoresConfigResponse:
    """Update Contadores config."""
    apply_config_update_to_file_backed_funnel(command)
    config = ContadoresConfig.update(
        enabled=command.enabled,
        sheet_url=command.sheet_url,
        sheet_gid=command.sheet_gid,
        sheet_poll_seconds=command.sheet_poll_seconds,
        loom_url=command.loom_url,
        calendly_base_url=command.calendly_base_url,
        alert_emails=command.alert_emails,
        initial_reply_quiet_seconds=command.initial_reply_quiet_seconds,
        post_loom_min_seconds=command.post_loom_min_seconds,
        post_loom_quiet_seconds=command.post_loom_quiet_seconds,
        strategy_weights=command.strategy_weights,
    )
    return build_config_response(get_effective_contadores_config())


@contadores_router.post("/leads/import", response_model=ImportContadoresLeadsResponse)
async def import_contadores_leads(
    command: ImportContadoresLeadsCommand,
) -> ImportContadoresLeadsResponse:
    """Upsert leads imported from the sheet poller."""
    imported = 0
    updated = 0
    skipped = 0
    lead_ids: list[str] = []

    funnel_id = (command.funnel_id or "").strip() or "contadores"
    for row in command.rows:
        raw_contacted = str(row.is_contactado or "").strip().lower()
        if raw_contacted in {"true", "1", "yes"}:
            skipped += 1
            continue
        phone = row.phone_number.replace("p:", "").strip()
        if not normalize_phone(phone):
            skipped += 1
            continue
        external_lead_id = row.id if funnel_id == "contadores" else f"{funnel_id}:{row.id}"
        existing = ContadoresLead.get_by_external_lead_id(external_lead_id, funnel_id=funnel_id)
        lead = ContadoresLead.upsert(
            funnel_id=funnel_id,
            external_lead_id=external_lead_id,
            phone=phone,
            full_name=row.full_name,
            email=row.email,
            platform=row.platform,
            lead_status=row.lead_status,
            tags=[FORM_LEAD_TAG],
            sheet_created_time=row.created_time,
        )
        lead_ids.append(lead.id)
        if existing is None:
            imported += 1
        else:
            updated += 1

    ContadoresConfig.mark_sheet_sync(
        status="ok",
        note=f"imported={imported} updated={updated} skipped={skipped}",
    )
    return ImportContadoresLeadsResponse(
        imported=imported,
        updated=updated,
        skipped=skipped,
        lead_ids=lead_ids,
    )


@contadores_router.get("/strategy-stats", response_model=ContadoresStrategyStatsResponse)
async def get_contadores_strategy_stats(
    funnel_id: str = Query(default="contadores"),
) -> ContadoresStrategyStatsResponse:
    """Return strategy assignment and conversion stats."""
    return build_contadores_strategy_stats(funnel_id=funnel_id)


@contadores_router.get("/manual-attention-counts", response_model=ManualAttentionCountsResponse)
async def get_manual_attention_counts() -> ManualAttentionCountsResponse:
    """Return the number of chats that need an operator answer per funnel."""
    return ManualAttentionCountsResponse(counts=build_manual_attention_counts())


@contadores_router.get("/followup/snapshot", response_model=ContadoresFollowupSnapshotResponse)
async def get_followup_snapshot(
    request: Request,
    limit: int = Query(default=5000, ge=1, le=20000),
    messages_per_lead: int = Query(default=8, ge=1, le=30),
    funnel_id: str | None = Query(default=None),
    include_all_funnels: bool = Query(default=False),
) -> ContadoresFollowupSnapshotResponse:
    """Return a read-only CRM state snapshot for external automation."""
    require_internal_api_token(request)
    leads = list_followup_snapshot_leads(
        limit=limit,
        funnel_id=funnel_id,
        include_all_funnels=include_all_funnels,
    )
    return build_followup_snapshot_response(leads, messages_per_lead=messages_per_lead)


@contadores_router.get("/followup/snapshot.csv")
async def get_followup_snapshot_csv(
    request: Request,
    limit: int = Query(default=5000, ge=1, le=20000),
    messages_per_lead: int = Query(default=8, ge=1, le=30),
    funnel_id: str | None = Query(default=None),
    include_all_funnels: bool = Query(default=False),
) -> Response:
    """Return a flat CSV CRM snapshot for external automation analysis."""
    require_internal_api_token(request)
    leads = list_followup_snapshot_leads(
        limit=limit,
        funnel_id=funnel_id,
        include_all_funnels=include_all_funnels,
    )
    snapshot = build_followup_snapshot_response(leads, messages_per_lead=messages_per_lead)
    return Response(
        content=build_followup_snapshot_csv(snapshot.leads),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="contadores-followup-snapshot.csv"'},
    )


@contadores_router.get("/followup/runner/status", response_model=ContadoresRunnerStatusResponse)
async def get_followup_runner_status(
    log_tail_lines: int = Query(default=120, ge=1, le=500),
    log_limit: int = Query(default=12, ge=1, le=50),
) -> ContadoresRunnerStatusResponse:
    """Return local CRM follow-up runner logs and lock status."""
    return build_followup_runner_status(
        log_tail_lines=log_tail_lines,
        log_limit=log_limit,
    )


@contadores_router.post("/followup/leads/{lead_id}/messages", response_model=ContadoresQuickActionResponse)
async def create_followup_manual_message(
    request: Request,
    lead_id: str,
    command: ContadoresFollowupSendMessageCommand,
) -> ContadoresQuickActionResponse:
    """Queue one internal automation free-text message for a lead."""
    require_internal_api_token(request)
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    assert_followup_lead_can_receive_outbound(lead)
    clean_text = normalize_message_for_dedupe(command.text)
    if not clean_text:
        raise HTTPException(status_code=400, detail="Message text is required")
    duplicate = find_recent_duplicate_outbound(
        lead_id=lead.id,
        text=clean_text,
        dedupe_hours=command.dedupe_hours,
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate outbound message already exists: {duplicate.id}",
        )

    config = get_effective_funnel_config(lead.funnel_id)
    queued_rows = queue_manual_message_for_lead(lead=lead, text=clean_text)
    updated = ContadoresLead.get_by_id(lead.id) or lead
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated, config=config),
        queued_message_ids=[row.id or 0 for row in queued_rows],
    )


@contadores_router.post("/followup/leads/{lead_id}/actions", response_model=ContadoresQuickActionResponse)
async def run_followup_lead_action(
    request: Request,
    lead_id: str,
    command: ContadoresFollowupActionCommand,
) -> ContadoresQuickActionResponse:
    """Run one existing CRM quick action from an internal automation."""
    require_internal_api_token(request)
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    normalized_action = command.action.strip().lower()
    send_actions = {
        "send-opener",
        "send-loom",
        "send-video-check",
        "send-manual-ping",
        "send-calendly",
        "send-calendly-link",
    }
    if normalized_action in send_actions:
        assert_followup_lead_can_receive_outbound(lead)
    config = get_effective_funnel_config(lead.funnel_id)
    updated, queued_rows = run_quick_action_for_lead(
        lead=lead,
        action=normalized_action,
        config=config,
    )
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated, config=config),
        queued_message_ids=[row.id or 0 for row in queued_rows],
    )


@contadores_router.patch("/followup/leads/{lead_id}", response_model=ContadoresLeadSummary)
async def update_followup_lead_classification(
    request: Request,
    lead_id: str,
    command: ContadoresFollowupLeadUpdateCommand,
) -> ContadoresLeadSummary:
    """Update stage/classification fields from an internal automation."""
    require_internal_api_token(request)
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    updated = lead
    if command.tags is not None:
        updated = ContadoresLead.set_tags(lead.id, tags=command.tags) or updated

    now = now_utc()
    flow_updates: dict[str, Any] = {}
    if command.stage is not None:
        target_stage = ContadoresLead.normalize_stage(command.stage)
        flow_updates["stage"] = target_stage
        if target_stage == ContadoresLeadStage.CLOSED:
            flow_updates["closed_at"] = now
            flow_updates["stage_before_closed"] = resolve_stage_before_closing(updated)
        elif target_stage == ContadoresLeadStage.BOOKED:
            flow_updates["booked_at"] = now
            flow_updates["clear_archived_at"] = True
        elif target_stage == ContadoresLeadStage.ARCHIVED:
            flow_updates["archived_at"] = now
        else:
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

    if flow_updates:
        updated = ContadoresLead.update_flow_state(updated.id, **flow_updates) or updated
    if command.tags is None and not flow_updates:
        raise HTTPException(status_code=400, detail="No lead updates were provided")

    config = get_effective_funnel_config(updated.funnel_id)
    return build_lead_summary(updated, config=config)


@contadores_router.get("/leads", response_model=ContadoresLeadListResponse)
async def list_contadores_leads(
    limit: int = Query(default=300, ge=1, le=1000),
    funnel_id: str = Query(default="contadores"),
    stage: str | None = None,
    platform: str | None = None,
    strategy_step: str | None = None,
    strategy_id: str | None = None,
    manual_reply_status: Literal["needs_reply", "answered"] | None = None,
    booked: bool | None = None,
    needs_human: bool | None = None,
    archived: bool | None = None,
    tag: str | None = None,
    query: str | None = None,
) -> ContadoresLeadListResponse:
    """List leads with list-view metrics and lightweight filtering."""
    config = get_effective_funnel_config(funnel_id)
    normalized_stage = ContadoresLead.normalize_stage(stage) if stage is not None else None
    base_leads = ContadoresLead.list_recent(
        limit=1000,
        funnel_id=funnel_id,
        platform=platform,
        include_archived=True,
    )
    tag_options = build_tag_options(base_leads)
    assignments_by_lead = group_strategy_assignments_by_lead(funnel_id)
    metric_leads: list[ContadoresLead] = []
    visible_leads: list[ContadoresLead] = []
    query_value = (query or "").strip().lower()

    for lead in base_leads:
        if query_value:
            haystack = " ".join(
                [
                    lead.external_lead_id,
                    lead.phone,
                    lead.normalized_phone,
                    lead.full_name or "",
                    lead.email or "",
                    lead.platform or "",
                    lead.lead_status or "",
                    " ".join(lead.tags),
                ]
            ).lower()
            if query_value not in haystack:
                continue
        if not lead_matches_tag_filter(lead, tag):
            continue
        if not lead_matches_strategy_filter(
            lead,
            assignments_by_lead=assignments_by_lead,
            strategy_step=strategy_step,
            strategy_id=strategy_id,
        ):
            continue

        metric_leads.append(lead)
        effective_stage = derive_effective_lead_stage(lead)
        if normalized_stage == ContadoresLeadStage.CALENDLY_SENT:
            if not lead_counts_in_calendly_bucket(lead):
                continue
        elif normalized_stage is not None and effective_stage != normalized_stage:
            continue
        if booked is True and lead.booked_at is None:
            continue
        if booked is False and lead.booked_at is not None:
            continue
        if needs_human is True and effective_stage != ContadoresLeadStage.NEEDS_HUMAN:
            continue
        if needs_human is False and effective_stage == ContadoresLeadStage.NEEDS_HUMAN:
            continue
        if manual_reply_status is not None and derive_manual_reply_status(lead) != manual_reply_status:
            continue
        if archived is True and effective_stage != ContadoresLeadStage.ARCHIVED:
            continue
        if archived is False and effective_stage == ContadoresLeadStage.ARCHIVED:
            continue
        visible_leads.append(lead)

    visible_leads = sort_leads_by_last_interaction(visible_leads)[:limit]
    return ContadoresLeadListResponse(
        metrics=build_contadores_metrics(metric_leads),
        config=build_config_response(config),
        tag_options=tag_options,
        leads=[
            build_lead_summary(
                item,
                config=config,
                strategy_assignments=assignments_by_lead.get(item.id, []),
            )
            for item in visible_leads
        ],
    )


@contadores_router.get("/leads/{lead_id}", response_model=ContadoresLeadDetailResponse)
async def get_contadores_lead_detail(lead_id: str) -> ContadoresLeadDetailResponse:
    """Return the lead detail and message timeline."""
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(lead.funnel_id)
    assignments_by_lead = group_strategy_assignments_by_lead(lead.funnel_id)
    messages = [build_message_response(item) for item in ContadoresMessage.list_by_lead(lead_id)]
    return ContadoresLeadDetailResponse(
        lead=build_lead_summary(
            lead,
            config=config,
            strategy_assignments=assignments_by_lead.get(lead.id, []),
        ),
        config=build_config_response(config),
        messages=messages,
    )


@contadores_router.get("/media/{media_path_token}")
async def get_contadores_media_by_path(media_path_token: str) -> FileResponse:
    """Serve one stored message media file through authenticated backend access."""
    media_path = decode_media_path_token(media_path_token)
    media_file = resolve_message_media_file(media_path)
    if media_file is None or not media_file.is_file():
        raise HTTPException(status_code=404, detail="Contadores media not found")

    media_type = (
        mimetypes.guess_type(media_file.name)[0]
        or "application/octet-stream"
    )
    return FileResponse(
        media_file,
        media_type=media_type,
        filename=media_file.name,
        content_disposition_type="inline",
    )


@contadores_router.delete("/leads/{lead_id}", response_model=DeleteContadoresLeadResponse)
async def delete_contadores_lead(lead_id: str) -> DeleteContadoresLeadResponse:
    """Delete one Contadores lead together with its messages."""
    with Session(engine) as session:
        lead = session.get(ContadoresLead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        for message in session.exec(select(ContadoresMessage).where(ContadoresMessage.lead_id == lead_id)).all():
            session.delete(message)
        session.delete(lead)
        session.commit()
    return DeleteContadoresLeadResponse(status="deleted", lead_id=lead_id)


@contadores_router.post("/leads/{lead_id}/messages/manual", response_model=ContadoresQuickActionResponse)
async def create_contadores_manual_message(
    lead_id: str,
    command: CreateContadoresMessageCommand,
) -> ContadoresQuickActionResponse:
    """Queue one manual outbound WhatsApp message."""
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(lead.funnel_id)
    queued_rows = queue_manual_message_for_lead(lead=lead, text=command.text)
    updated = ContadoresLead.get_by_id(lead.id) or lead
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated, config=config),
        queued_message_ids=[row.id or 0 for row in queued_rows],
    )


@contadores_router.post("/leads/{lead_id}/messages/manual-media", response_model=ContadoresQuickActionResponse)
async def create_contadores_manual_media_message(
    lead_id: str,
    text: str = Form(default=""),
    file: list[UploadFile] = File(...),
) -> ContadoresQuickActionResponse:
    """Queue one manual outbound WhatsApp media/file send with one or more files."""
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not file:
        raise HTTPException(status_code=400, detail="Attach at least one file")
    assert_whatsapp_custom_window_open(lead, sequence_step="manual")

    config = get_effective_funnel_config(lead.funnel_id)
    queued_rows: list[ContadoresMessage] = []
    for index, upload in enumerate(file):
        media_path, media_type, media_filename, media_mime_type = await save_manual_outbound_media_async(
            lead=lead,
            upload=upload,
        )
        queued_rows.extend(
            queue_manual_message_for_lead(
                lead=lead,
                text=text if index == 0 else "",
                media_path=media_path,
                media_type=media_type,
                media_filename=media_filename,
                media_mime_type=media_mime_type,
            )
        )
    updated = ContadoresLead.get_by_id(lead.id) or lead
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated, config=config),
        queued_message_ids=[row.id or 0 for row in queued_rows],
    )


@contadores_router.put("/leads/{lead_id}/tags", response_model=ContadoresLeadSummary)
async def update_contadores_lead_tags(
    lead_id: str,
    command: UpdateContadoresLeadTagsCommand,
) -> ContadoresLeadSummary:
    """Replace operator tags for one lead."""
    updated = ContadoresLead.set_tags(lead_id, tags=command.tags)
    if updated is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(updated.funnel_id)
    return build_lead_summary(updated, config=config)


@contadores_router.post("/leads/{lead_id}/move", response_model=ContadoresLeadSummary)
async def move_contadores_lead(
    lead_id: str,
    command: MoveContadoresLeadCommand,
) -> ContadoresLeadSummary:
    """Move one lead to an existing campaign funnel and selected stage."""
    target_funnel = get_funnel(command.funnel_id)
    if target_funnel is None:
        raise HTTPException(status_code=404, detail="Target funnel not found")
    if target_funnel.kind == "inbox":
        raise HTTPException(status_code=400, detail="Choose a campaign funnel")
    target_stage = ContadoresLead.normalize_stage(command.stage)
    updated = ContadoresLead.move_to_funnel(
        lead_id,
        funnel_id=target_funnel.id,
        stage=target_stage,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(updated.funnel_id)
    return build_lead_summary(updated, config=config)


@contadores_router.post("/leads/bulk-action", response_model=ContadoresBulkActionResponse)
async def run_contadores_bulk_action(
    command: BulkContadoresActionCommand,
) -> ContadoresBulkActionResponse:
    """Run one operator action for selected chats."""
    normalized_action = command.action.strip().lower()
    clean_lead_ids = list(dict.fromkeys(item.strip() for item in command.lead_ids if item.strip()))
    if not clean_lead_ids:
        raise HTTPException(status_code=400, detail="Select at least one lead")

    if normalized_action == "custom":
        message_text = (command.text or "").strip()
        if not message_text:
            raise HTTPException(status_code=400, detail="Custom message text is required")
    if normalized_action == BULK_SET_TAGS_ACTION:
        command_tags = command.tags or (command.text or "").split(",")
        clean_tags = normalize_contadores_tags(command_tags)
        if not clean_tags:
            raise HTTPException(status_code=400, detail="At least one tag is required")
    if normalized_action == "send-manual-ping" and not command.manual_ping_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Bulk Manual ping requires explicit confirmation.",
        )

    bulk_action_id = uuid.uuid4().hex[:12]
    results: list[ContadoresBulkActionItem] = []
    queued_message_ids: list[int] = []

    for lead_id in clean_lead_ids:
        lead = ContadoresLead.get_by_id(lead_id)
        if lead is None:
            results.append(
                ContadoresBulkActionItem(
                    lead_id=lead_id,
                    ok=False,
                    error="Lead not found",
                )
            )
            continue

        config = get_effective_funnel_config(lead.funnel_id)
        try:
            if normalized_action == BULK_SET_TAGS_ACTION:
                updated = ContadoresLead.set_tags(lead.id, tags=clean_tags)
                if updated is None:
                    raise HTTPException(status_code=404, detail="Lead not found")
                queued_rows = []
            elif normalized_action == "custom":
                queued_rows = queue_manual_message_for_lead(lead=lead, text=command.text or "")
                updated = ContadoresLead.get_by_id(lead.id) or lead
            else:
                updated, queued_rows = run_quick_action_for_lead(
                    lead=lead,
                    action=normalized_action,
                    config=config,
                )
        except HTTPException as exc:
            results.append(
                ContadoresBulkActionItem(
                    lead_id=lead_id,
                    ok=False,
                    error=str(exc.detail),
                )
            )
            continue

        item_message_ids = [row.id or 0 for row in queued_rows]
        queued_message_ids.extend(item_message_ids)
        results.append(
            ContadoresBulkActionItem(
                lead_id=lead_id,
                ok=True,
                lead=build_lead_summary(updated, config=config),
                queued_message_ids=item_message_ids,
            )
        )

    succeeded = sum(1 for item in results if item.ok)
    failed = len(results) - succeeded
    return ContadoresBulkActionResponse(
        action=normalized_action,
        total=len(results),
        succeeded=succeeded,
        failed=failed,
        queued_message_ids=queued_message_ids,
        results=results,
    )


@contadores_router.post("/leads/{lead_id}/actions/{action}", response_model=ContadoresQuickActionResponse)
async def run_contadores_quick_action(
    lead_id: str,
    action: str,
) -> ContadoresQuickActionResponse:
    """Run one operator quick action."""
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(lead.funnel_id)

    updated, queued_rows = run_quick_action_for_lead(
        lead=lead,
        action=action,
        config=config,
    )
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated, config=config),
        queued_message_ids=[row.id or 0 for row in queued_rows],
    )


@contadores_router.post("/leads/{lead_id}/resume-automation", response_model=ContadoresQuickActionResponse)
async def resume_contadores_automation(lead_id: str) -> ContadoresQuickActionResponse:
    """Clear automation_paused and infer the right stage so the bot resumes."""
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(lead.funnel_id)
    target_stage = infer_resume_stage_from_timestamps(lead)
    updated = ContadoresLead.update_flow_state(
        lead.id,
        stage=target_stage,
        automation_paused=False,
    )
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated or lead, config=config),
        queued_message_ids=[],
    )


@contadores_router.get("/messages/pending-delivery", response_model=PendingContadoresDeliveryResponse)
async def list_pending_contadores_delivery_messages(
    limit: int = Query(default=100, ge=1, le=500),
) -> PendingContadoresDeliveryResponse:
    """List pending Contadores outbound messages for bot dispatch."""
    rows = ContadoresMessage.list_pending_delivery(limit=limit)
    items: list[PendingContadoresDeliveryMessage] = []
    for row in rows:
        lead = ContadoresLead.get_by_id(row.lead_id)
        if lead is None:
            continue
        funnel = resolve_funnel(lead.funnel_id)
        template_name = resolve_contadores_template_name(row.sequence_step, funnel_id=lead.funnel_id)
        items.append(
            PendingContadoresDeliveryMessage(
                message_id=row.id or 0,
                lead_id=lead.id,
                external_lead_id=lead.external_lead_id,
                phone=lead.phone,
                normalized_phone=lead.normalized_phone,
                full_name=lead.full_name,
                text=row.text,
                dispatch_after=format_timestamp_seconds(row.dispatch_after) or "",
                created_at=format_timestamp_seconds(row.created_at) or "",
                sequence_step=row.sequence_step,
                strategy_assignment_id=row.strategy_assignment_id,
                strategy_step=row.strategy_step,
                strategy_id=row.strategy_id,
                strategy_label=row.strategy_label,
                media_type=row.media_type,
                media_path=row.media_path,
                media_caption=row.media_caption,
                media_mime_type=row.media_mime_type,
                media_filename=row.media_filename,
                contact_has_inbound=ContadoresMessage.has_inbound_for_lead(lead.id),
                whatsapp_template_name=template_name,
                whatsapp_template_language=funnel.template_language if template_name else None,
                whatsapp_template_body_params=[],
            )
        )
    return PendingContadoresDeliveryResponse(messages=items)


@contadores_router.put("/messages/{message_id}", response_model=ContadoresMessageResponse)
async def update_contadores_message_text(
    message_id: int,
    command: UpdateContadoresMessageCommand,
) -> ContadoresMessageResponse:
    """Update one stored Contadores message text."""
    updated = ContadoresMessage.update_text(
        message_id=message_id,
        text=command.text.strip(),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Contadores message not found")
    return build_message_response(updated)


@contadores_router.put("/messages/{message_id}/delivery", response_model=ContadoresMessageResponse)
async def set_contadores_message_delivery_by_id(
    message_id: int,
    command: SetContadoresMessageDeliveryByIdCommand,
) -> ContadoresMessageResponse:
    """Update one Contadores outbound message status by local message id."""
    updated = ContadoresMessage.update_delivery_status(
        message_id=message_id,
        delivery_status=command.status,
        external_id=command.external_id,
        clear_delivery_error=command.status.strip().lower() in {
            MessageDeliveryStatus.SENT.value,
            MessageDeliveryStatus.DELIVERED.value,
        },
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Contadores message not found")
    return build_message_response(updated)


@contadores_router.post("/messages/{message_id}/delivery-failure", response_model=ContadoresMessageResponse)
async def record_contadores_message_delivery_failure(
    message_id: int,
    command: RecordContadoresMessageFailureCommand,
) -> ContadoresMessageResponse:
    """Record one failed WhatsApp send attempt and requeue up to the retry cap."""
    delivery_error = format_whatsapp_delivery_error(
        command.error,
        error_code=command.error_code,
        error_title=command.error_title,
        error_message=command.error_message,
        error_details=command.error_details,
        error_user_message=command.error_user_message,
    )
    updated = ContadoresMessage.record_delivery_failure(
        message_id=message_id,
        error=delivery_error,
        max_attempts=command.max_attempts,
        retry_delay_seconds=command.retry_delay_seconds,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Contadores message not found")
    return build_message_response(updated)


@contadores_router.post("/messages/{message_id}/delivery-error/acknowledge", response_model=ContadoresMessageResponse)
async def acknowledge_contadores_message_delivery_error(message_id: int) -> ContadoresMessageResponse:
    """Mark one visible delivery error as acknowledged by the operator."""
    updated = ContadoresMessage.acknowledge_delivery_error(message_id=message_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Contadores message not found")
    return build_message_response(updated)


@contadores_router.put("/messages/delivery/by-external-id", response_model=ContadoresMessageResponse)
async def set_contadores_message_delivery_by_external_id(
    command: SetContadoresMessageDeliveryCommand,
) -> ContadoresMessageResponse:
    """Update one Contadores outbound message status using provider external id."""
    matches = ContadoresMessage.list_by_external_id(command.external_id, from_me=True)
    if not matches:
        raise HTTPException(status_code=404, detail="Outbound Contadores message not found for external_id")
    if len(matches) > 1:
        raise HTTPException(status_code=409, detail="Ambiguous external_id across Contadores messages")
    row = matches[0]
    if row.id is None:
        raise HTTPException(status_code=404, detail="Outbound Contadores message not found for external_id")
    if command.status.strip().lower() == MessageDeliveryStatus.FAILED.value:
        delivery_error = format_whatsapp_delivery_error(
            command.error or "whatsapp_provider_status_failed",
            error_code=command.error_code,
            error_title=command.error_title,
            error_message=command.error_message,
            error_details=command.error_details,
            error_user_message=command.error_user_message,
        )
        updated = ContadoresMessage.record_delivery_failure(
            message_id=row.id,
            error=delivery_error,
            max_attempts=CONTADORES_DELIVERY_MAX_ATTEMPTS,
            retry_delay_seconds=CONTADORES_DELIVERY_RETRY_DELAY_SECONDS,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Outbound Contadores message not found for external_id")
        return build_message_response(updated)
    updated = ContadoresMessage.update_delivery_status(
        message_id=row.id,
        delivery_status=command.status,
        external_id=command.external_id,
        clear_delivery_error=command.status.strip().lower() in {
            MessageDeliveryStatus.SENT.value,
            MessageDeliveryStatus.DELIVERED.value,
        },
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Outbound Contadores message not found for external_id")
    return build_message_response(updated)


@contadores_router.post("/whatsapp/inbound", response_model=ContadoresWhatsAppInboundResponse)
async def register_contadores_whatsapp_inbound(
    command: ContadoresWhatsAppInboundCommand,
) -> ContadoresWhatsAppInboundResponse:
    """Route one raw WhatsApp inbound event to a Contadores lead safely."""
    contadores_reply_matches, contadores_reply_ambiguous = list_contadores_matches_by_replied_message(
        command.in_reply_to
    )
    if contadores_reply_ambiguous:
        return ContadoresWhatsAppInboundResponse(
            status="ignored",
            route="ambiguous",
            reason="ambiguous_reply_context",
        )

    contadores_matches = contadores_reply_matches

    if not contadores_matches:
        source_id = get_referral_source_id(command.referral)
        referral_funnels = list_funnels_by_whatsapp_referral_source_id(source_id)
        if len(referral_funnels) > 1:
            return ContadoresWhatsAppInboundResponse(
                status="ignored",
                route="ambiguous",
                reason="ambiguous_referral_source_id",
            )
        if referral_funnels:
            funnel = referral_funnels[0]
            funnel_matches, funnel_ambiguous = list_contadores_matches_by_phone(
                command.phone,
                funnel_id=funnel.id,
            )
            if funnel_ambiguous:
                return ContadoresWhatsAppInboundResponse(
                    status="ignored",
                    route="ambiguous",
                    reason="ambiguous_funnel_phone_match",
            )
            if funnel_matches:
                contadores_matches = funnel_matches
            else:
                try:
                    lead, _ = upsert_ctwa_lead_from_inbound(
                        funnel_id=funnel.id,
                        command=command,
                    )
                except ValueError:
                    return ContadoresWhatsAppInboundResponse(
                        status="ignored",
                        route="none",
                        reason="invalid_phone",
                    )
                refreshed_lead, _ = record_whatsapp_inbound_for_lead(
                    lead=lead,
                    command=command,
                )
                return ContadoresWhatsAppInboundResponse(
                    status="processed",
                    route=funnel.id,
                    lead_id=refreshed_lead.id,
                )

    if not contadores_matches:
        prefilled_route = resolve_prefilled_whatsapp_route(command.text)
        if prefilled_route is not None:
            prefilled_funnel_id, _ = prefilled_route
            funnel = get_funnel(prefilled_funnel_id)
            if funnel is not None:
                funnel_matches, funnel_ambiguous = list_contadores_matches_by_phone(
                    command.phone,
                    funnel_id=funnel.id,
                )
                if funnel_ambiguous:
                    return ContadoresWhatsAppInboundResponse(
                        status="ignored",
                        route="ambiguous",
                        reason="ambiguous_prefilled_phone_match",
                )
                if funnel_matches:
                    contadores_matches = funnel_matches
                else:
                    try:
                        lead, _ = upsert_ctwa_lead_from_inbound(
                            funnel_id=funnel.id,
                            command=command,
                        )
                    except ValueError:
                        return ContadoresWhatsAppInboundResponse(
                            status="ignored",
                            route="none",
                            reason="invalid_phone",
                        )
                    refreshed_lead, _ = record_whatsapp_inbound_for_lead(
                        lead=lead,
                        command=command,
                    )
                    return ContadoresWhatsAppInboundResponse(
                        status="processed",
                        route=funnel.id,
                        lead_id=refreshed_lead.id,
                    )

    if not contadores_matches:
        contadores_phone_matches, contadores_phone_ambiguous = list_contadores_matches_by_phone(command.phone)
        if contadores_phone_ambiguous:
            return ContadoresWhatsAppInboundResponse(
                status="ignored",
                route="ambiguous",
                reason="ambiguous_phone_match",
            )
        contadores_matches = contadores_phone_matches

    if contadores_matches:
        lead = fill_missing_lead_name_from_whatsapp(
            lead=contadores_matches[0],
            command=command,
        )
        refreshed_lead, row = record_whatsapp_inbound_for_lead(
            lead=lead,
            command=command,
        )
        if derive_effective_lead_stage(refreshed_lead) == ContadoresLeadStage.CLOSED:
            return ContadoresWhatsAppInboundResponse(
                status="processed",
                route=refreshed_lead.funnel_id,
                lead_id=refreshed_lead.id,
            )
        if lead_has_new_inbound_after_calendly(refreshed_lead):
            updated = ContadoresLead.update_flow_state(
                lead.id,
                stage=ContadoresLeadStage.NEEDS_HUMAN,
                last_classification_label="needs_human",
                last_classification_reason="Inbound reply received after Calendly sequence.",
                classification_completed_at=ensure_utc_datetime(row.created_at) or now_utc(),
                automation_paused=True,
                automation_paused_reason="post_calendly_inbound",
            )
            refreshed_lead = updated or refreshed_lead
        return ContadoresWhatsAppInboundResponse(
            status="processed",
            route=refreshed_lead.funnel_id,
            lead_id=refreshed_lead.id,
        )

    try:
        lead, _ = upsert_general_inbox_lead_from_inbound(command=command)
    except ValueError:
        return ContadoresWhatsAppInboundResponse(
            status="ignored",
            route="none",
            reason="invalid_phone",
        )
    refreshed_lead, _ = record_whatsapp_inbound_for_lead(
        lead=lead,
        command=command,
    )
    return ContadoresWhatsAppInboundResponse(
        status="processed",
        route=GENERAL_INBOX_FUNNEL_ID,
        lead_id=refreshed_lead.id,
    )


@contadores_router.post("/automation/tick", response_model=ContadoresAutomationTickResponse)
async def run_contadores_automation_tick(
    funnel_id: str = Query(default="contadores"),
) -> ContadoresAutomationTickResponse:
    """Advance Contadores automation state and queue due outbound messages."""
    funnel = resolve_funnel(funnel_id)
    if funnel.kind == "inbox":
        return ContadoresAutomationTickResponse(status="inbox")
    config = get_effective_funnel_config(funnel_id)
    if not config.enabled:
        return ContadoresAutomationTickResponse(status="disabled")

    leads = ContadoresLead.list_recent(limit=1000, funnel_id=funnel_id, include_archived=False)
    classifier = PostLoomReplyClassifierProgram()
    now = now_utc()
    opener_sent = 0
    loom_sent = 0
    video_checks_sent = 0
    classified_wants_to_proceed = 0
    classified_needs_human = 0
    calendly_sent = 0

    for lead in leads:
        if lead.stage in {ContadoresLeadStage.ARCHIVED, ContadoresLeadStage.CLOSED, ContadoresLeadStage.BOOKED}:
            continue
        if lead.automation_paused:
            continue
        exclusion_reasons = build_followup_exclusion_reasons(
            lead,
            workstation_client=WorkstationClient.get_by_lead_id(lead.id),
            latest_outbound=ContadoresMessage.get_latest_outbound_message(lead.id),
        )
        if exclusion_reasons:
            continue

        if (
            lead.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
            and lead.opener_sent_at is None
            and lead.first_reply_received_at is None
        ):
            send_opener_sequence(lead=lead)
            opener_sent += 1
            continue

        if (
            lead.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
            and lead.first_reply_received_at is not None
            and lead.loom_sent_at is None
            and has_quiet_window(
                last_message_at=lead.last_inbound_at,
                quiet_seconds=config.initial_reply_quiet_seconds,
                now=now,
            )
        ):
            send_loom_sequence(lead=lead, config=config)
            loom_sent += 1
            continue

        opener_sent_at = ensure_utc_datetime(lead.opener_sent_at)
        if (
            lead.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
            and lead.first_reply_received_at is None
            and opener_sent_at is not None
            and now >= opener_sent_at + OPENER_FOLLOWUP_DELAY
            and not ContadoresMessage.has_outbound_sequence_step(
                lead.id,
                sequence_step=OPENER_FOLLOWUP_SEQUENCE_STEP,
                created_after=opener_sent_at,
            )
        ):
            send_opener_followup(lead=lead)
            continue

        if lead.stage != ContadoresLeadStage.AWAITING_VIDEO_REPLY or lead.loom_sent_at is None:
            continue

        replies_since_loom = get_reply_batch_since_loom(lead.id, loom_sent_at=lead.loom_sent_at)
        last_reply_at = ensure_utc_datetime(replies_since_loom[-1].created_at) if replies_since_loom else None
        loom_sent_at = ensure_utc_datetime(lead.loom_sent_at)
        if loom_sent_at is None:
            continue
        reached_min_wait = now >= loom_sent_at + timedelta(seconds=config.post_loom_min_seconds)

        if (
            not replies_since_loom
            and reached_min_wait
            and lead.video_check_sent_at is None
        ):
            send_video_check(lead=lead)
            video_checks_sent += 1
            continue

        if not replies_since_loom or not reached_min_wait:
            continue

        if not has_quiet_window(
            last_message_at=last_reply_at,
            quiet_seconds=config.post_loom_quiet_seconds,
            now=now,
        ):
            continue

        batch_text = "\n".join(
            f"- {item.text.strip()}"
            for item in replies_since_loom
            if item.text.strip()
        ).strip()
        if not batch_text:
            continue

        result = await classifier.aforward(
            loom_context=build_classifier_context(),
            reply_batch=batch_text,
        )
        label = result.label
        updated = ContadoresLead.update_flow_state(
            lead.id,
            classification_completed_at=now,
            last_classification_label=label,
            last_classification_reason=result.reasoning,
        )
        lead = updated or lead
        if label == "wants_to_proceed":
            send_calendly_sequence(lead=lead, config=config)
            classified_wants_to_proceed += 1
            calendly_sent += 1
            continue

        ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.NEEDS_HUMAN,
        )
        classified_needs_human += 1

    return ContadoresAutomationTickResponse(
        status="ok",
        opener_sent=opener_sent,
        loom_sent=loom_sent,
        video_checks_sent=video_checks_sent,
        classified_wants_to_proceed=classified_wants_to_proceed,
        classified_needs_human=classified_needs_human,
        calendly_sent=calendly_sent,
    )


@contadores_router.get("/alerts/pending", response_model=PendingContadoresAlertsResponse)
async def list_pending_contadores_alerts(
    funnel_id: str = Query(default="contadores"),
) -> PendingContadoresAlertsResponse:
    """List leads waiting for needs_human alert emails."""
    config = get_effective_funnel_config(funnel_id)
    items: list[PendingContadoresAlertItem] = []
    for lead in ContadoresLead.list_needs_human_without_notification(funnel_id=funnel_id, limit=100):
        if derive_effective_lead_stage(lead) != ContadoresLeadStage.NEEDS_HUMAN:
            continue
        if derive_manual_reply_status(lead) == "answered":
            continue
        latest_inbound = ContadoresMessage.get_latest_inbound_message(lead.id)
        items.append(
            PendingContadoresAlertItem(
                lead_id=lead.id,
                full_name=lead.full_name,
                phone=lead.phone,
                email=lead.email,
                stage=derive_effective_lead_stage(lead).value,
                latest_inbound_text=latest_inbound.text if latest_inbound else None,
                reason=lead.last_classification_reason,
                alert_emails=config.alert_emails,
            )
        )
    return PendingContadoresAlertsResponse(items=items)


@contadores_router.post("/leads/{lead_id}/mark-alerted", response_model=ContadoresLeadSummary)
async def mark_contadores_alerted(
    lead_id: str,
    command: MarkContadoresAlertedCommand,
) -> ContadoresLeadSummary:
    """Mark that the needs_human notification email was sent."""
    updated = ContadoresLead.update_flow_state(
        lead_id,
        needs_human_notified_at=command.sent_at or now_utc(),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(updated.funnel_id)
    ContadoresConfig.mark_alert_sent(sent_at=command.sent_at or now_utc())
    return build_lead_summary(updated, config=config)


@contadores_router.post("/bookings/mark", response_model=ContadoresLeadSummary)
async def mark_contadores_booked(
    command: MarkContadoresBookedCommand,
    lead_id: str = Query(..., min_length=1),
) -> ContadoresLeadSummary:
    """Manually mark one lead as booked."""
    updated = ContadoresLead.update_flow_state(
        lead_id,
        stage=ContadoresLeadStage.BOOKED,
        booked_at=command.booked_at or now_utc(),
        automation_paused=True,
        automation_paused_reason="manual_booked",
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    config = get_effective_funnel_config(updated.funnel_id)
    return build_lead_summary(updated, config=config)


@contadores_router.post("/calendly/webhook", response_model=ContadoresLeadSummary)
async def register_contadores_calendly_event(
    command: ContadoresCalendlyWebhookCommand,
) -> ContadoresLeadSummary:
    """Mark booked from a Calendly webhook token."""
    lead = ContadoresLead.get_by_calendly_tracking_token(command.token)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found for Calendly token")
    config = get_effective_funnel_config(lead.funnel_id)
    if command.event_type.strip().lower() in {"invitee.created", "booking_created", "scheduled"}:
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.BOOKED,
            booked_at=command.occurred_at or now_utc(),
        )
        return build_lead_summary(updated or lead, config=config)
    return build_lead_summary(lead, config=config)
