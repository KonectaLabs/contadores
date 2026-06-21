#!/usr/bin/env python3
"""Requeue failed Contadores WhatsApp messages for another delivery attempt."""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from backend.database import (
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    MessageDeliveryStatus,
    engine,
)


def list_failed_message_ids(*, opener_only: bool) -> list[int]:
    """Return failed outbound message ids ordered by creation time."""
    with Session(engine) as session:
        statement = (
            select(ContadoresMessage.id)
            .join(ContadoresLead, ContadoresLead.id == ContadoresMessage.lead_id)
            .where(
                ContadoresMessage.from_me.is_(True),
                ContadoresMessage.delivery_status == MessageDeliveryStatus.FAILED,
                ContadoresLead.stage != ContadoresLeadStage.ARCHIVED,
                ContadoresLead.stage != ContadoresLeadStage.CLOSED,
                ContadoresLead.stage != ContadoresLeadStage.BOOKED,
                ContadoresLead.archived_at.is_(None),
                ContadoresLead.closed_at.is_(None),
                ContadoresLead.booked_at.is_(None),
            )
            .order_by(ContadoresMessage.created_at, ContadoresMessage.id)
        )
        if opener_only:
            statement = statement.where(ContadoresMessage.sequence_step == "opener")
        return [message_id for message_id in session.exec(statement).all() if message_id is not None]


def requeue_failed_messages(*, execute: bool, opener_only: bool, reset_attempts: bool) -> tuple[int, int]:
    """Requeue failed outbound messages and record an audit event."""
    message_ids = list_failed_message_ids(opener_only=opener_only)
    if not execute:
        return len(message_ids), 0

    requeued = 0
    for message_id in message_ids:
        row = ContadoresMessage.requeue_failed_delivery(
            message_id=message_id,
            reset_attempts=reset_attempts,
        )
        if row is None:
            continue
        requeued += 1
    return len(message_ids), requeued


def main() -> None:
    """Run the one-off requeue command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually requeue messages. Default is preview only.")
    parser.add_argument("--dry-run", action="store_true", help="Preview only. Kept for older safe runbooks.")
    parser.add_argument("--opener-only", action="store_true")
    parser.add_argument("--keep-attempts", action="store_true")
    args = parser.parse_args()
    if args.execute and args.dry_run:
        parser.error("--execute cannot be combined with --dry-run")

    candidate_count, requeued_count = requeue_failed_messages(
        execute=args.execute,
        opener_only=args.opener_only,
        reset_attempts=not args.keep_attempts,
    )
    print(f"candidate_failed_messages={candidate_count}")
    print(f"requeued_failed_messages={requeued_count}")


if __name__ == "__main__":
    main()
