#!/usr/bin/env python3
"""Requeue failed Contadores WhatsApp messages for another delivery attempt."""

from __future__ import annotations

import argparse

from sqlmodel import Session, select

from backend.database import (
    ContadoresEvent,
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
            )
            .order_by(ContadoresMessage.created_at, ContadoresMessage.id)
        )
        if opener_only:
            statement = statement.where(ContadoresMessage.sequence_step == "opener")
        return [message_id for message_id in session.exec(statement).all() if message_id is not None]


def requeue_failed_messages(*, dry_run: bool, opener_only: bool, reset_attempts: bool) -> int:
    """Requeue failed outbound messages and record an audit event."""
    message_ids = list_failed_message_ids(opener_only=opener_only)
    if dry_run:
        print(f"failed_messages={len(message_ids)}")
        return len(message_ids)

    requeued = 0
    for message_id in message_ids:
        row = ContadoresMessage.requeue_failed_delivery(
            message_id=message_id,
            reset_attempts=reset_attempts,
        )
        if row is None:
            continue
        ContadoresEvent.add(
            lead_id=row.lead_id,
            event_type="outbound_delivery_requeued",
            actor="system",
            summary=f"Requeued failed WhatsApp message #{row.id}.",
            payload={
                "message_id": row.id,
                "sequence_step": row.sequence_step,
                "reset_attempts": reset_attempts,
            },
        )
        requeued += 1
    return requeued


def main() -> None:
    """Run the one-off requeue command."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--opener-only", action="store_true")
    parser.add_argument("--keep-attempts", action="store_true")
    args = parser.parse_args()

    count = requeue_failed_messages(
        dry_run=args.dry_run,
        opener_only=args.opener_only,
        reset_attempts=not args.keep_attempts,
    )
    print(f"requeued_failed_messages={0 if args.dry_run else count}")


if __name__ == "__main__":
    main()
