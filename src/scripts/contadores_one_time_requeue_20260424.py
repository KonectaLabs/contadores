#!/usr/bin/env python3
"""Queue one-time Contadores recovery messages for the April 2026 template fix."""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from backend.contadores_strategies import LOOM_MP4_PATH, LOOM_STEP
from backend.database import (
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    ContadoresStrategyAssignment,
    MessageDeliveryStatus,
    engine,
)
from backend.endpoints.contadores import (
    OPENER_FOLLOWUP_RETRY_SEQUENCE_STEP,
    OPENER_FOLLOWUP_SEQUENCE_STEP,
    build_opener_followup_text,
)


LOOM_LINK_MP4_INTRO_STEP = "loom_link_mp4_intro_20260424"
LOOM_LINK_MP4_VIDEO_STEP = "loom_link_mp4_video_20260424"
LOOM_LINK_MP4_INTRO_TEXT = "No se si pudiste ver el video, te lo mando por aca, dura solo 60 segundos"
LOOM_LINK_MP4_VIDEO_TEXT = "Video de explicación enviado por WhatsApp."


def queue_outbound(
    *,
    lead_id: str,
    text: str,
    sequence_step: str,
    media_type: str | None = None,
    media_path: str | None = None,
) -> ContadoresMessage:
    """Queue one pending outbound message and record the matching event."""
    row = ContadoresMessage.add(
        lead_id=lead_id,
        from_me=True,
        text=text,
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step=sequence_step,
        media_type=media_type,
        media_path=media_path,
    )
    return row


def list_failed_followup_lead_ids() -> list[str]:
    """Return leads whose failed 24-hour follow-up needs one template retry."""
    with Session(engine) as session:
        already_retried = (
            select(ContadoresMessage.lead_id)
            .where(
                ContadoresMessage.from_me.is_(True),
                ContadoresMessage.sequence_step == OPENER_FOLLOWUP_RETRY_SEQUENCE_STEP,
            )
        )
        statement = (
            select(ContadoresMessage.lead_id)
            .join(ContadoresLead, ContadoresLead.id == ContadoresMessage.lead_id)
            .where(
                ContadoresMessage.from_me.is_(True),
                ContadoresMessage.sequence_step == OPENER_FOLLOWUP_SEQUENCE_STEP,
                ContadoresMessage.delivery_status == MessageDeliveryStatus.FAILED,
                ContadoresMessage.lead_id.not_in(already_retried),
                ContadoresLead.stage != ContadoresLeadStage.ARCHIVED,
                ContadoresLead.stage != ContadoresLeadStage.CLOSED,
                ContadoresLead.stage != ContadoresLeadStage.BOOKED,
                ContadoresLead.archived_at.is_(None),
                ContadoresLead.closed_at.is_(None),
                ContadoresLead.booked_at.is_(None),
            )
            .distinct()
            .order_by(ContadoresMessage.lead_id)
        )
        return list(session.exec(statement).all())


def list_loom_link_lead_ids() -> list[str]:
    """Return Loom-link leads that should receive the MP4 once."""
    with Session(engine) as session:
        already_queued = (
            select(ContadoresMessage.lead_id)
            .where(
                ContadoresMessage.from_me.is_(True),
                ContadoresMessage.sequence_step == LOOM_LINK_MP4_VIDEO_STEP,
            )
        )
        statement = (
            select(ContadoresLead.id)
            .join(ContadoresStrategyAssignment, ContadoresStrategyAssignment.lead_id == ContadoresLead.id)
            .where(
                ContadoresStrategyAssignment.step == LOOM_STEP,
                ContadoresStrategyAssignment.strategy_id == "loom_link",
                ContadoresLead.calendly_sent_at.is_(None),
                ContadoresLead.stage != ContadoresLeadStage.CALENDLY_SENT,
                ContadoresLead.stage != ContadoresLeadStage.BOOKED,
                ContadoresLead.stage != ContadoresLeadStage.CLOSED,
                ContadoresLead.stage != ContadoresLeadStage.ARCHIVED,
                ContadoresLead.booked_at.is_(None),
                ContadoresLead.closed_at.is_(None),
                ContadoresLead.archived_at.is_(None),
                ContadoresLead.id.not_in(already_queued),
            )
            .distinct()
            .order_by(ContadoresLead.id)
        )
        return list(session.exec(statement).all())


def queue_failed_followup_retries(*, dry_run: bool) -> int:
    """Queue template-backed retry rows for failed 24-hour follow-ups."""
    lead_ids = list_failed_followup_lead_ids()
    if dry_run:
        print(f"failed_followup_retry_leads={len(lead_ids)}")
        return len(lead_ids)

    for lead_id in lead_ids:
        queue_outbound(
            lead_id=lead_id,
            text=build_opener_followup_text(),
            sequence_step=OPENER_FOLLOWUP_RETRY_SEQUENCE_STEP,
        )
    return len(lead_ids)


def queue_loom_link_mp4_messages(*, dry_run: bool) -> int:
    """Queue the one-time MP4 replacement for Loom-link leads."""
    lead_ids = list_loom_link_lead_ids()
    if dry_run:
        print(f"loom_link_mp4_leads={len(lead_ids)}")
        return len(lead_ids)

    for lead_id in lead_ids:
        queue_outbound(
            lead_id=lead_id,
            text=LOOM_LINK_MP4_INTRO_TEXT,
            sequence_step=LOOM_LINK_MP4_INTRO_STEP,
        )
        queue_outbound(
            lead_id=lead_id,
            text=LOOM_LINK_MP4_VIDEO_TEXT,
            sequence_step=LOOM_LINK_MP4_VIDEO_STEP,
            media_type="video",
            media_path=LOOM_MP4_PATH,
        )
    return len(lead_ids)


def main() -> None:
    """Run the one-time recovery safely and idempotently."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    retry_count = queue_failed_followup_retries(dry_run=args.dry_run)
    mp4_count = queue_loom_link_mp4_messages(dry_run=args.dry_run)
    print(f"queued_failed_followup_retries={0 if args.dry_run else retry_count}")
    print(f"queued_loom_link_mp4_leads={0 if args.dry_run else mp4_count}")


if __name__ == "__main__":
    main()
