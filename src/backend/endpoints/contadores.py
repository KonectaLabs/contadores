"""Dedicated Contadores endpoints: config, leads, automation, and delivery contracts."""

from __future__ import annotations

import json
import mimetypes
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from backend.ai.contadores_post_loom_classifier import PostLoomReplyClassifierProgram
from backend.contadores_strategies import (
    LOOM_STEP,
    build_loom_intro_text as build_strategy_loom_intro_text,
    choose_contadores_strategy,
    get_contadores_strategy_weight,
    list_contadores_strategies,
)
from backend.database import (
    ContadoresConfig,
    ContadoresEvent,
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    ContadoresStrategyAssignment,
    DATA_DIR,
    MessageDeliveryStatus,
    engine,
    normalize_email,
    normalize_phone,
)
from backend.funnel_config import get_contadores_funnel

contadores_router = APIRouter(prefix="/api/contadores", tags=["contadores"])

OPENER_FOLLOWUP_SEQUENCE_STEP = "opener_followup_24h"
OPENER_FOLLOWUP_RETRY_SEQUENCE_STEP = "opener_followup_24h_template_retry_20260424"
MANUAL_PING_SEQUENCE_STEP = "manual_ping_template"
OPENER_FOLLOWUP_DELAY = timedelta(hours=24)


def format_timestamp_seconds(value: datetime | None) -> str | None:
    """Format datetimes with second precision in UTC."""
    if value is None:
        return None
    dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def now_utc() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


def ensure_utc_datetime(value: datetime | None) -> datetime | None:
    """Normalize DB datetimes so SQLite naive rows behave like UTC timestamps."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def build_opener_text() -> str:
    """Return the rendered opener text used in transcript history."""
    return get_contadores_funnel().opener_text


def build_loom_intro_text() -> str:
    """Return the pre-Loom explanatory text."""
    return build_strategy_loom_intro_text()


def build_opener_followup_text() -> str:
    """Return the reminder sent 24 hours after the opener when there is no reply."""
    return get_contadores_funnel().opener_followup_text


def build_manual_ping_text() -> str:
    """Return the manual ping text used to reopen a WhatsApp window."""
    return get_contadores_funnel().manual_ping_text


def resolve_contadores_template_name(sequence_step: str | None) -> str | None:
    """Return the WhatsApp template name for template-backed Contadores steps."""
    funnel = get_contadores_funnel()
    if sequence_step == "opener":
        return funnel.opener_template_name
    if sequence_step in {OPENER_FOLLOWUP_SEQUENCE_STEP, OPENER_FOLLOWUP_RETRY_SEQUENCE_STEP}:
        return funnel.opener_followup_template_name
    if sequence_step == MANUAL_PING_SEQUENCE_STEP:
        return funnel.manual_ping_template_name
    return None


def build_video_check_text() -> str:
    """Return the follow-up prompt sent after the Loom wait window."""
    return get_contadores_funnel().video_check_text


def build_calendly_intro_text() -> str:
    """Return the Calendly follow-up text."""
    return get_contadores_funnel().calendly_intro_text


def build_classifier_context() -> str:
    """Return stable classifier context instructions for post-Loom replies."""
    return (
        "Ya se enviaron: opener, explicación breve, video/propuesta y eventualmente la pregunta "
        "'¿Terminaste de ver el video?'. Clasificá si la persona claramente quiere avanzar "
        "al siguiente paso o si necesita intervención humana."
    )


def build_calendly_url(*, base_url: str) -> str:
    """Return the configured Calendly URL without per-lead tracking."""
    parsed = urlsplit((base_url or "").strip() or "https://calendly.com/yoelkravchuk/konecta-meet")
    if not parsed.scheme and not parsed.netloc:
        return f"https://{parsed.path}"
    return urlunsplit(
        (
            parsed.scheme or "https",
            parsed.netloc,
            parsed.path or "",
            parsed.query,
            parsed.fragment,
        )
    )


def parse_event_payload(payload_json: str) -> dict[str, Any]:
    """Parse stored event payload safely."""
    try:
        payload = json.loads(payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {"value": payload}


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
    if lead.stage == ContadoresLeadStage.NEEDS_HUMAN and lead_has_new_inbound_after_calendly(lead):
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


def group_strategy_assignments_by_lead() -> dict[str, list[ContadoresStrategyAssignment]]:
    """Return strategy assignments grouped by lead id."""
    grouped: dict[str, list[ContadoresStrategyAssignment]] = {}
    for assignment in ContadoresStrategyAssignment.list_all():
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


def build_contadores_strategy_stats() -> "ContadoresStrategyStatsResponse":
    """Aggregate strategy assignment and conversion counts."""
    config = ContadoresConfig.get()
    stats: dict[tuple[str, str], dict[str, Any]] = {}
    for strategy in list_contadores_strategies():
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

    assignments = ContadoresStrategyAssignment.list_all()
    with Session(engine) as session:
        message_rows = list(
            session.exec(
                select(ContadoresMessage).where(ContadoresMessage.strategy_assignment_id.is_not(None))
            ).all()
        )
        lead_rows = list(session.exec(select(ContadoresLead)).all())

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
    return ContadoresLeadSummary(
        id=lead.id,
        external_lead_id=lead.external_lead_id,
        phone=lead.phone,
        normalized_phone=lead.normalized_phone,
        full_name=lead.full_name,
        email=lead.email,
        platform=lead.platform,
        lead_status=lead.lead_status,
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
        automation_paused=bool(lead.automation_paused),
        automation_paused_reason=lead.automation_paused_reason,
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


def build_message_media_url(message: ContadoresMessage) -> str | None:
    """Return the protected API URL for a stored message attachment."""
    if not message.id or not (message.media_path or "").strip():
        return None
    return f"/api/contadores/messages/{message.id}/media"


def allowed_message_media_roots() -> list[Path]:
    """Return filesystem roots from which stored message media may be served."""
    roots = [DATA_DIR.expanduser().resolve()]
    configured_media_dir = (os.getenv("WA_INBOUND_MEDIA_DIR", "") or "").strip()
    if configured_media_dir:
        roots.append(Path(configured_media_dir).expanduser().resolve())
    return roots


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


def build_event_response(event: ContadoresEvent) -> "ContadoresEventResponse":
    """Serialize one automation event."""
    return ContadoresEventResponse(
        id=event.id or 0,
        lead_id=event.lead_id,
        event_type=event.event_type,
        actor=event.actor,
        summary=event.summary,
        payload=parse_event_payload(event.payload_json),
        created_at=format_timestamp_seconds(event.created_at) or "",
    )


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
) -> ContadoresMessage:
    """Create one pending outbound message plus event."""
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
    )
    ContadoresEvent.add(
        lead_id=lead.id,
        event_type="outbound_queued",
        actor="system",
        summary=f"Queued outbound step `{sequence_step}`.",
        payload={
            "message_id": row.id,
            "sequence_step": sequence_step,
            "strategy_step": strategy_assignment.step if strategy_assignment else None,
            "strategy_id": strategy_assignment.strategy_id if strategy_assignment else None,
            "media_type": media_type,
        },
    )
    return row


def send_opener_sequence(*, lead: ContadoresLead) -> list[ContadoresMessage]:
    """Queue the first template-backed opener message."""
    opener = enqueue_lead_outbound(
        lead=lead,
        text=build_opener_text(),
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
    strategy = choose_contadores_strategy(
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
        text=build_opener_followup_text(),
        sequence_step=OPENER_FOLLOWUP_SEQUENCE_STEP,
    )
    return [row]


def send_manual_ping_template(*, lead: ContadoresLead) -> list[ContadoresMessage]:
    """Queue the operator-triggered ping template."""
    row = enqueue_lead_outbound(
        lead=lead,
        text=build_manual_ping_text(),
        sequence_step=MANUAL_PING_SEQUENCE_STEP,
    )
    return [row]


def send_video_check(*, lead: ContadoresLead) -> list[ContadoresMessage]:
    """Queue the post-Loom follow-up question."""
    row = enqueue_lead_outbound(
        lead=lead,
        text=build_video_check_text(),
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
        text=build_calendly_intro_text(),
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


def queue_manual_action_event(lead_id: str, action: str, actor: str = "operator") -> None:
    """Persist one manual action event."""
    ContadoresEvent.add(
        lead_id=lead_id,
        event_type="manual_action",
        actor=actor,
        summary=f"Manual action `{action}` executed.",
        payload={"action": action},
    )


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


def list_contadores_matches_by_phone(phone: str) -> tuple[list[ContadoresLead], bool]:
    """Resolve Contadores leads from normalized phone."""
    normalized_phone = normalize_phone(phone)
    matches = ContadoresLead.list_by_normalized_phone(normalized_phone, include_archived=False)
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
    sheet_poll_seconds: int | None = Field(default=None, ge=60)
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
    external_lead_id: str
    phone: str
    normalized_phone: str
    full_name: str | None = None
    email: str | None = None
    platform: str | None = None
    lead_status: str | None = None
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
    automation_paused: bool = False
    automation_paused_reason: str | None = None
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


class ContadoresEventResponse(BaseModel):
    """Serialized Contadores event."""

    id: int
    lead_id: str | None = None
    event_type: str
    actor: str | None = None
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ContadoresLeadListResponse(BaseModel):
    """List endpoint payload."""

    metrics: ContadoresMetrics
    config: ContadoresConfigResponse
    leads: list[ContadoresLeadSummary] = Field(default_factory=list)


class ContadoresLeadDetailResponse(BaseModel):
    """Detail endpoint payload."""

    lead: ContadoresLeadSummary
    config: ContadoresConfigResponse
    messages: list[ContadoresMessageResponse] = Field(default_factory=list)
    events: list[ContadoresEventResponse] = Field(default_factory=list)


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


class ContadoresQuickActionResponse(BaseModel):
    """Result after one quick action or manual queue."""

    lead: ContadoresLeadSummary
    queued_message_ids: list[int] = Field(default_factory=list)


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


class SetContadoresMessageDeliveryByIdCommand(BaseModel):
    """Provider delivery update keyed by message id."""

    status: str = Field(min_length=1)
    external_id: str | None = None


class UpdateContadoresMessageCommand(BaseModel):
    """Manual text update for one stored Contadores message."""

    text: str = Field(min_length=1)


class ContadoresWhatsAppInboundCommand(BaseModel):
    """Raw inbound WhatsApp event delivered by the bot."""

    phone: str = Field(min_length=1)
    text: str = Field(min_length=1)
    external_id: str | None = None
    in_reply_to: str | None = None
    media_id: str | None = None
    media_type: str | None = None
    media_path: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None
    media_sha256: str | None = None
    media_caption: str | None = None


class ContadoresWhatsAppInboundResponse(BaseModel):
    """Result of unified WhatsApp inbound routing."""

    status: str
    route: str | None = None
    lead_id: str | None = None
    company_id: str | None = None
    contact_id: str | None = None
    task_id: str | None = None
    reason: str | None = None


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
async def get_contadores_config() -> ContadoresConfigResponse:
    """Return current Contadores config."""
    return build_config_response(ContadoresConfig.get())


@contadores_router.put("/config", response_model=ContadoresConfigResponse)
async def update_contadores_config(
    command: UpdateContadoresConfigCommand,
) -> ContadoresConfigResponse:
    """Update Contadores config."""
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
    return build_config_response(config)


@contadores_router.post("/leads/import", response_model=ImportContadoresLeadsResponse)
async def import_contadores_leads(
    command: ImportContadoresLeadsCommand,
) -> ImportContadoresLeadsResponse:
    """Upsert leads imported from the sheet poller."""
    imported = 0
    updated = 0
    skipped = 0
    lead_ids: list[str] = []

    for row in command.rows:
        raw_contacted = str(row.is_contactado or "").strip().lower()
        if raw_contacted in {"true", "1", "yes"}:
            skipped += 1
            continue
        phone = row.phone_number.replace("p:", "").strip()
        if not normalize_phone(phone):
            skipped += 1
            continue
        existing = ContadoresLead.get_by_external_lead_id(row.id)
        lead = ContadoresLead.upsert(
            external_lead_id=row.id,
            phone=phone,
            full_name=row.full_name,
            email=row.email,
            platform=row.platform,
            lead_status=row.lead_status,
            sheet_created_time=row.created_time,
        )
        lead_ids.append(lead.id)
        if existing is None:
            imported += 1
            ContadoresEvent.add(
                lead_id=lead.id,
                event_type="sheet_import_created",
                actor="bot",
                summary="Lead imported from spreadsheet.",
                payload={"external_lead_id": row.id},
            )
        else:
            updated += 1
            ContadoresEvent.add(
                lead_id=lead.id,
                event_type="sheet_import_updated",
                actor="bot",
                summary="Lead refreshed from spreadsheet.",
                payload={"external_lead_id": row.id},
            )

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
async def get_contadores_strategy_stats() -> ContadoresStrategyStatsResponse:
    """Return strategy assignment and conversion stats."""
    return build_contadores_strategy_stats()


@contadores_router.get("/leads", response_model=ContadoresLeadListResponse)
async def list_contadores_leads(
    limit: int = Query(default=300, ge=1, le=1000),
    stage: str | None = None,
    platform: str | None = None,
    strategy_step: str | None = None,
    strategy_id: str | None = None,
    manual_reply_status: Literal["needs_reply", "answered"] | None = None,
    booked: bool | None = None,
    needs_human: bool | None = None,
    archived: bool | None = None,
    query: str | None = None,
) -> ContadoresLeadListResponse:
    """List leads with list-view metrics and lightweight filtering."""
    config = ContadoresConfig.get()
    normalized_stage = ContadoresLead.normalize_stage(stage) if stage is not None else None
    base_leads = ContadoresLead.list_recent(
        limit=1000,
        platform=platform,
        include_archived=True,
    )
    assignments_by_lead = group_strategy_assignments_by_lead()
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
                ]
            ).lower()
            if query_value not in haystack:
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
    """Return detail timeline for one lead."""
    config = ContadoresConfig.get()
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    assignments_by_lead = group_strategy_assignments_by_lead()
    messages = [build_message_response(item) for item in ContadoresMessage.list_by_lead(lead_id)]
    events = [build_event_response(item) for item in ContadoresEvent.list_by_lead(lead_id)]
    return ContadoresLeadDetailResponse(
        lead=build_lead_summary(
            lead,
            config=config,
            strategy_assignments=assignments_by_lead.get(lead.id, []),
        ),
        config=build_config_response(config),
        messages=messages,
        events=events,
    )


@contadores_router.get("/messages/{message_id}/media")
async def get_contadores_message_media(message_id: int) -> FileResponse:
    """Serve one stored WhatsApp media file through authenticated backend access."""
    message = ContadoresMessage.get_by_id(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Contadores message not found")
    media_file = resolve_message_media_file(message.media_path)
    if media_file is None or not media_file.is_file():
        raise HTTPException(status_code=404, detail="Contadores media not found")

    media_type = (
        (message.media_mime_type or "").strip()
        or mimetypes.guess_type(media_file.name)[0]
        or "application/octet-stream"
    )
    return FileResponse(
        media_file,
        media_type=media_type,
        filename=(message.media_filename or media_file.name),
        content_disposition_type="inline",
    )


@contadores_router.delete("/leads/{lead_id}", response_model=DeleteContadoresLeadResponse)
async def delete_contadores_lead(lead_id: str) -> DeleteContadoresLeadResponse:
    """Delete one Contadores lead together with its messages and events."""
    with Session(engine) as session:
        lead = session.get(ContadoresLead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        for message in session.exec(select(ContadoresMessage).where(ContadoresMessage.lead_id == lead_id)).all():
            session.delete(message)
        for event in session.exec(select(ContadoresEvent).where(ContadoresEvent.lead_id == lead_id)).all():
            session.delete(event)
        session.delete(lead)
        session.commit()
    return DeleteContadoresLeadResponse(status="deleted", lead_id=lead_id)


@contadores_router.post("/leads/{lead_id}/messages/manual", response_model=ContadoresQuickActionResponse)
async def create_contadores_manual_message(
    lead_id: str,
    command: CreateContadoresMessageCommand,
) -> ContadoresQuickActionResponse:
    """Queue one manual outbound WhatsApp message."""
    config = ContadoresConfig.get()
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    row = enqueue_lead_outbound(
        lead=lead,
        text=command.text.strip(),
        sequence_step="manual",
    )
    ContadoresLead.update_flow_state(
        lead.id,
        stage=ContadoresLeadStage.NEEDS_HUMAN,
        automation_paused=True,
        automation_paused_reason="manual_message",
    )
    ContadoresEvent.add(
        lead_id=lead.id,
        event_type="manual_send_queued",
        actor="operator",
        summary="Manual outbound message queued. Automation paused.",
        payload={"message_id": row.id},
    )
    updated = ContadoresLead.get_by_id(lead.id) or lead
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated, config=config),
        queued_message_ids=[row.id or 0],
    )


@contadores_router.post("/leads/{lead_id}/actions/{action}", response_model=ContadoresQuickActionResponse)
async def run_contadores_quick_action(
    lead_id: str,
    action: str,
) -> ContadoresQuickActionResponse:
    """Run one operator quick action."""
    config = ContadoresConfig.get()
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    queued_rows: list[ContadoresMessage] = []
    normalized_action = (action or "").strip().lower()
    pausing_send_actions = {"send-opener", "send-loom", "send-video-check", "send-manual-ping"}
    if normalized_action == "send-opener":
        queued_rows = send_opener_sequence(lead=lead)
    elif normalized_action == "send-manual-ping":
        if not get_contadores_funnel().manual_ping_template_name:
            raise HTTPException(status_code=400, detail="Manual ping template is not configured")
        queued_rows = send_manual_ping_template(lead=lead)
    elif normalized_action == "send-loom":
        queued_rows = send_loom_sequence(lead=lead, config=config, assigned_by="operator")
    elif normalized_action == "send-video-check":
        queued_rows = send_video_check(lead=lead)
    elif normalized_action == "send-calendly":
        queued_rows = send_calendly_sequence(lead=lead, config=config)
    elif normalized_action == "mark-booked":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.BOOKED,
            booked_at=now_utc(),
        )
        queue_manual_action_event(lead.id, normalized_action)
        return ContadoresQuickActionResponse(
            lead=build_lead_summary(updated or lead, config=config),
            queued_message_ids=[],
        )
    elif normalized_action == "mark-answered":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            manual_reply_handled_at=now_utc(),
        )
        ContadoresEvent.add(
            lead_id=lead.id,
            event_type="manual_reply_marked_answered",
            actor="operator",
            summary="Operator marked the current manual reply as already answered.",
            payload={"action": normalized_action},
        )
        return ContadoresQuickActionResponse(
            lead=build_lead_summary(updated or lead, config=config),
            queued_message_ids=[],
        )
    elif normalized_action == "close":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.CLOSED,
            closed_at=now_utc(),
            stage_before_closed=resolve_stage_before_closing(lead),
        )
        queue_manual_action_event(lead.id, normalized_action)
        return ContadoresQuickActionResponse(
            lead=build_lead_summary(updated or lead, config=config),
            queued_message_ids=[],
        )
    elif normalized_action == "reopen":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=resolve_stage_after_reopening(lead),
            clear_closed_at=True,
            clear_stage_before_closed=True,
        )
        queue_manual_action_event(lead.id, normalized_action)
        return ContadoresQuickActionResponse(
            lead=build_lead_summary(updated or lead, config=config),
            queued_message_ids=[],
        )
    elif normalized_action == "archive":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.ARCHIVED,
            archived_at=now_utc(),
        )
        queue_manual_action_event(lead.id, normalized_action)
        return ContadoresQuickActionResponse(
            lead=build_lead_summary(updated or lead, config=config),
            queued_message_ids=[],
        )
    elif normalized_action == "unarchive":
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.AWAITING_INITIAL_REPLY,
            clear_archived_at=True,
        )
        queue_manual_action_event(lead.id, normalized_action)
        return ContadoresQuickActionResponse(
            lead=build_lead_summary(updated or lead, config=config),
            queued_message_ids=[],
        )
    else:
        raise HTTPException(status_code=404, detail="Unknown quick action")

    if normalized_action in pausing_send_actions:
        ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.NEEDS_HUMAN,
            automation_paused=True,
            automation_paused_reason=f"manual_{normalized_action}",
        )
    queue_manual_action_event(lead.id, normalized_action)
    updated = ContadoresLead.get_by_id(lead.id) or lead
    return ContadoresQuickActionResponse(
        lead=build_lead_summary(updated, config=config),
        queued_message_ids=[row.id or 0 for row in queued_rows],
    )


@contadores_router.post("/leads/{lead_id}/resume-automation", response_model=ContadoresQuickActionResponse)
async def resume_contadores_automation(lead_id: str) -> ContadoresQuickActionResponse:
    """Clear automation_paused and infer the right stage so the bot resumes."""
    config = ContadoresConfig.get()
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    target_stage = infer_resume_stage_from_timestamps(lead)
    updated = ContadoresLead.update_flow_state(
        lead.id,
        stage=target_stage,
        automation_paused=False,
    )
    ContadoresEvent.add(
        lead_id=lead.id,
        event_type="automation_resumed",
        actor="operator",
        summary=f"Operator resumed automated flow (stage -> {target_stage.value}).",
        payload={"stage": target_stage.value},
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
        funnel = get_contadores_funnel()
        template_name = resolve_contadores_template_name(row.sequence_step)
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
    )
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
    updated = ContadoresMessage.update_delivery_status(
        message_id=row.id,
        delivery_status=command.status,
        external_id=command.external_id,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Outbound Contadores message not found for external_id")
    return build_message_response(updated)


@contadores_router.post("/whatsapp/inbound", response_model=ContadoresWhatsAppInboundResponse)
async def register_contadores_whatsapp_inbound(
    command: ContadoresWhatsAppInboundCommand,
) -> ContadoresWhatsAppInboundResponse:
    """Route one raw WhatsApp inbound event to a Contadores lead safely."""
    contadores_reply_matches, contadores_reply_ambiguous = list_contadores_matches_by_replied_message(command.in_reply_to)
    if contadores_reply_ambiguous:
        return ContadoresWhatsAppInboundResponse(
            status="ignored",
            route="ambiguous",
            reason="ambiguous_reply_context",
        )

    contadores_matches = contadores_reply_matches

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
        lead = contadores_matches[0]
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
        ContadoresEvent.add(
            lead_id=lead.id,
            event_type="whatsapp_inbound_received",
            actor="bot",
            summary="Inbound WhatsApp received for Contadores lead.",
            payload={
                "message_id": row.id,
                "in_reply_to": command.in_reply_to,
                "media_type": command.media_type,
                "media_path": command.media_path,
                "media_mime_type": command.media_mime_type,
                "media_filename": command.media_filename,
            },
        )
        refreshed_lead = ContadoresLead.get_by_id(lead.id) or lead
        if derive_effective_lead_stage(refreshed_lead) == ContadoresLeadStage.CLOSED:
            return ContadoresWhatsAppInboundResponse(
                status="processed",
                route="contadores",
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
            ContadoresEvent.add(
                lead_id=lead.id,
                event_type="post_calendly_inbound_handoff",
                actor="bot",
                summary="Lead replied after Calendly sequence. Human follow-up required.",
                payload={"message_id": row.id, "in_reply_to": command.in_reply_to},
            )
        return ContadoresWhatsAppInboundResponse(
            status="processed",
            route="contadores",
            lead_id=refreshed_lead.id,
        )

    return ContadoresWhatsAppInboundResponse(
        status="ignored",
        route="none",
        reason="no_match",
    )


@contadores_router.post("/automation/tick", response_model=ContadoresAutomationTickResponse)
async def run_contadores_automation_tick() -> ContadoresAutomationTickResponse:
    """Advance Contadores automation state and queue due outbound messages."""
    config = ContadoresConfig.get()
    if not config.enabled:
        return ContadoresAutomationTickResponse(status="disabled")

    leads = ContadoresLead.list_recent(limit=1000, include_archived=False)
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

        if lead.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY and lead.opener_sent_at is None:
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
        ContadoresEvent.add(
            lead_id=lead.id,
            event_type="post_loom_classified",
            actor="system",
            summary=f"Post-Loom replies classified as `{label}`.",
            payload={
                "label": label,
                "reasoning": result.reasoning,
                "reply_batch": batch_text,
            },
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
        ContadoresEvent.add(
            lead_id=lead.id,
            event_type="needs_human_handoff",
            actor="system",
            summary="Automation paused and handoff to human operator is required.",
            payload={"reasoning": result.reasoning},
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
async def list_pending_contadores_alerts() -> PendingContadoresAlertsResponse:
    """List leads waiting for needs_human alert emails."""
    config = ContadoresConfig.get()
    items: list[PendingContadoresAlertItem] = []
    for lead in ContadoresLead.list_needs_human_without_notification(limit=100):
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
    config = ContadoresConfig.get()
    updated = ContadoresLead.update_flow_state(
        lead_id,
        needs_human_notified_at=command.sent_at or now_utc(),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    ContadoresConfig.mark_alert_sent(sent_at=command.sent_at or now_utc())
    ContadoresEvent.add(
        lead_id=lead_id,
        event_type="needs_human_alert_sent",
        actor="bot",
        summary="Needs-human alert email sent.",
    )
    return build_lead_summary(updated, config=config)


@contadores_router.post("/bookings/mark", response_model=ContadoresLeadSummary)
async def mark_contadores_booked(
    command: MarkContadoresBookedCommand,
    lead_id: str = Query(..., min_length=1),
) -> ContadoresLeadSummary:
    """Manually mark one lead as booked."""
    config = ContadoresConfig.get()
    updated = ContadoresLead.update_flow_state(
        lead_id,
        stage=ContadoresLeadStage.BOOKED,
        booked_at=command.booked_at or now_utc(),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    ContadoresEvent.add(
        lead_id=lead_id,
        event_type="manual_booked",
        actor="operator",
        summary="Lead marked as booked manually.",
    )
    return build_lead_summary(updated, config=config)


@contadores_router.post("/calendly/webhook", response_model=ContadoresLeadSummary)
async def register_contadores_calendly_event(
    command: ContadoresCalendlyWebhookCommand,
) -> ContadoresLeadSummary:
    """Mark booked from a Calendly webhook token."""
    config = ContadoresConfig.get()
    lead = ContadoresLead.get_by_calendly_tracking_token(command.token)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found for Calendly token")
    if command.event_type.strip().lower() in {"invitee.created", "booking_created", "scheduled"}:
        updated = ContadoresLead.update_flow_state(
            lead.id,
            stage=ContadoresLeadStage.BOOKED,
            booked_at=command.occurred_at or now_utc(),
        )
        ContadoresEvent.add(
            lead_id=lead.id,
            event_type="calendly_booked",
            actor="bot",
            summary="Calendly webhook marked lead as booked.",
            payload={"event_type": command.event_type},
        )
        return build_lead_summary(updated or lead, config=config)
    ContadoresEvent.add(
        lead_id=lead.id,
        event_type="calendly_event",
        actor="bot",
        summary="Calendly webhook received non-booking event.",
        payload={"event_type": command.event_type},
    )
    return build_lead_summary(lead, config=config)
