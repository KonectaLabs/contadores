#!/usr/bin/env python3
"""Build a structured CRM follow-up delta from two snapshot JSON files."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BOOKING_RE = re.compile(
    r"\b("
    r"lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo|"
    r"hoy|manana|mañana|pasado|am|pm|hs|hora|horario|agenda|agendar|llamada|meet|"
    r"zoom|calendly|email|correo"
    r")\b|\b\d{1,2}[:.]\d{2}\b",
    re.IGNORECASE,
)

ACTION_BUCKETS = {"needs_answer_now", "close_call", "retomar_video", "repair_delivery", "provider_failure_review"}


def read_json(path: Path | None) -> dict[str, Any] | None:
    """Read one JSON object if the file exists."""
    if path is None or not path.exists() or path.stat().st_size == 0:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def read_text(path: Path | None) -> str:
    """Read text from an optional file."""
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def utc_now() -> str:
    """Return a compact UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def lead_map(snapshot: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index snapshot leads by id."""
    if not snapshot:
        return {}
    leads = snapshot.get("leads")
    if not isinstance(leads, list):
        return {}
    return {str(lead.get("id")): lead for lead in leads if isinstance(lead, dict) and lead.get("id")}


def count_map(snapshot: dict[str, Any] | None, key: str) -> dict[str, int]:
    """Return a normalized count map from a snapshot."""
    if not snapshot:
        return {}
    raw = snapshot.get(key)
    if not isinstance(raw, dict):
        return {}
    return {str(item_key): int(item_value or 0) for item_key, item_value in raw.items()}


def metric_deltas(previous: dict[str, int], current: dict[str, int]) -> list[dict[str, Any]]:
    """Build sorted metric deltas."""
    rows: list[dict[str, Any]] = []
    for key in sorted(set(previous) | set(current)):
        before = previous.get(key, 0)
        after = current.get(key, 0)
        delta = after - before
        if delta == 0:
            continue
        rows.append({"key": key, "previous": before, "current": after, "delta": delta})
    return sorted(rows, key=lambda row: (abs(int(row["delta"])), row["key"]), reverse=True)


def message_id(message: dict[str, Any] | None) -> str:
    """Return a stable message id string."""
    if not isinstance(message, dict):
        return ""
    value = message.get("id")
    return str(value) if value is not None else ""


def message_text(message: dict[str, Any] | None) -> str:
    """Return compact message text."""
    if not isinstance(message, dict):
        return ""
    return str(message.get("text") or "").strip()


def message_status(message: dict[str, Any] | None) -> tuple[str, str]:
    """Return delivery status and error code."""
    if not isinstance(message, dict):
        return "", ""
    return str(message.get("delivery_status") or ""), str(message.get("last_delivery_error_code") or "")


def message_time(message: dict[str, Any] | None) -> str | None:
    """Return the best message timestamp."""
    if not isinstance(message, dict):
        return None
    return str(message.get("created_at") or message.get("dispatch_after") or "") or None


def lead_label(lead: dict[str, Any]) -> str:
    """Return a readable lead label."""
    return str(lead.get("full_name") or lead.get("phone") or lead.get("id") or "Unknown lead")


def lead_event(
    *,
    lead: dict[str, Any],
    kind: str,
    severity: str,
    title: str,
    detail: str,
    suggested_action: str,
    occurred_at: str | None = None,
    text: str = "",
) -> dict[str, Any]:
    """Build one event row for the UI and summaries."""
    return {
        "lead_id": str(lead.get("id") or ""),
        "funnel_id": str(lead.get("funnel_id") or ""),
        "full_name": lead.get("full_name"),
        "phone": lead.get("phone"),
        "kind": kind,
        "severity": severity,
        "title": title,
        "detail": detail,
        "suggested_action": suggested_action,
        "occurred_at": occurred_at,
        "stage": lead.get("stage"),
        "manual_reply_status": lead.get("manual_reply_status"),
        "latest_text": text,
        "excluded": bool(lead.get("excluded")),
        "exclusion_reasons": lead.get("exclusion_reasons") or [],
    }


def sort_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort events by operational priority and recency."""
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    kind_rank = {
        "booking_time_provided": 0,
        "new_reply": 1,
        "delivery_changed": 2,
        "state_changed": 3,
        "due_next_step": 4,
        "outbound_sent": 5,
        "new_exclusion": 6,
        "new_lead": 7,
    }

    def event_timestamp(event: dict[str, Any]) -> float:
        raw_value = str(event.get("occurred_at") or "")
        if not raw_value:
            return 0.0
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    return sorted(
        events,
        key=lambda event: (
            severity_rank.get(str(event.get("severity")), 9),
            kind_rank.get(str(event.get("kind")), 9),
            -event_timestamp(event),
        ),
        reverse=False,
    )


def build_delta(
    *,
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    status: str,
    summary: str,
    source: str,
) -> dict[str, Any]:
    """Build the structured delta consumed by the runner UI."""
    previous_leads = lead_map(previous)
    current_leads = lead_map(current)
    baseline_available = bool(previous_leads)
    events: list[dict[str, Any]] = []

    if baseline_available:
        for lead_id, lead in current_leads.items():
            previous_lead = previous_leads.get(lead_id)
            if previous_lead is None:
                if not lead.get("excluded"):
                    events.append(
                        lead_event(
                            lead=lead,
                            kind="new_lead",
                            severity="low",
                            title=f"{lead_label(lead)} entered the snapshot",
                            detail="This lead was not present in the previous run snapshot.",
                            suggested_action="Let normal bucket rules decide whether the opener/follow-up is due.",
                            occurred_at=lead.get("last_inbound_at") or lead.get("last_outbound_at"),
                        )
                    )
                continue

            was_excluded = bool(previous_lead.get("excluded"))
            is_excluded = bool(lead.get("excluded"))
            if is_excluded and not was_excluded:
                events.append(
                    lead_event(
                        lead=lead,
                        kind="new_exclusion",
                        severity="info",
                        title=f"{lead_label(lead)} is now excluded",
                        detail=", ".join(str(item) for item in lead.get("exclusion_reasons") or []) or "No reason recorded.",
                        suggested_action="Do not send anything unless a human deliberately reopens this lead.",
                        occurred_at=lead.get("closed_at") or lead.get("archived_at") or lead.get("booked_at"),
                    )
                )
            if is_excluded:
                continue

            current_inbound = lead.get("latest_inbound") if isinstance(lead.get("latest_inbound"), dict) else None
            previous_inbound = (
                previous_lead.get("latest_inbound")
                if isinstance(previous_lead.get("latest_inbound"), dict)
                else None
            )
            if message_id(current_inbound) and message_id(current_inbound) != message_id(previous_inbound):
                text = message_text(current_inbound)
                booking = bool(BOOKING_RE.search(text))
                events.append(
                    lead_event(
                        lead=lead,
                        kind="booking_time_provided" if booking else "new_reply",
                        severity="critical" if booking else "high",
                        title=f"{lead_label(lead)} replied",
                        detail=text[:220] or "Inbound message changed.",
                        suggested_action=(
                            "Treat as scheduling intent: book/coordinate the 15-minute call or ask for missing email."
                            if booking
                            else "Read the chat first. Answer or confirm that the bot already handled it."
                        ),
                        occurred_at=message_time(current_inbound),
                        text=text,
                    )
                )

            current_outbound = lead.get("latest_outbound") if isinstance(lead.get("latest_outbound"), dict) else None
            previous_outbound = (
                previous_lead.get("latest_outbound")
                if isinstance(previous_lead.get("latest_outbound"), dict)
                else None
            )
            if message_id(current_outbound) and message_id(current_outbound) != message_id(previous_outbound):
                text = message_text(current_outbound)
                events.append(
                    lead_event(
                        lead=lead,
                        kind="outbound_sent",
                        severity="info",
                        title=f"Outbound changed for {lead_label(lead)}",
                        detail=text[:220] or "A new outbound message was queued or delivered.",
                        suggested_action="Watch for reply; do not double-send until the timing rule allows it.",
                        occurred_at=message_time(current_outbound),
                        text=text,
                    )
                )

            current_status = message_status(current_outbound)
            previous_status = message_status(previous_outbound)
            if current_status != previous_status and any(current_status):
                failed = current_status[0] in {"failed", "undelivered"} or bool(current_status[1])
                events.append(
                    lead_event(
                        lead=lead,
                        kind="delivery_changed",
                        severity="high" if failed else "medium",
                        title=f"Delivery changed for {lead_label(lead)}",
                        detail=f"{previous_status[0] or '-'} / {previous_status[1] or '-'} -> {current_status[0] or '-'} / {current_status[1] or '-'}",
                        suggested_action="Repair delivery or classify as provider failure before interpreting silence.",
                        occurred_at=message_time(current_outbound),
                    )
                )

            old_stage = str(previous_lead.get("stage") or "")
            new_stage = str(lead.get("stage") or "")
            old_manual = str(previous_lead.get("manual_reply_status") or "")
            new_manual = str(lead.get("manual_reply_status") or "")
            if old_stage != new_stage or old_manual != new_manual:
                needs_human = new_stage == "needs_human" or new_manual == "needs_reply"
                events.append(
                    lead_event(
                        lead=lead,
                        kind="state_changed",
                        severity="high" if needs_human else "medium",
                        title=f"State changed for {lead_label(lead)}",
                        detail=f"{old_stage or '-'} / {old_manual or '-'} -> {new_stage or '-'} / {new_manual or '-'}",
                        suggested_action="Review the chat if it moved into Manual or Needs answer.",
                        occurred_at=lead.get("last_inbound_at") or lead.get("last_outbound_at"),
                    )
                )

            previous_buckets = set(previous_lead.get("suggested_buckets") or [])
            current_buckets = set(lead.get("suggested_buckets") or [])
            entered_buckets = sorted((current_buckets - previous_buckets) & ACTION_BUCKETS)
            if entered_buckets:
                events.append(
                    lead_event(
                        lead=lead,
                        kind="due_next_step",
                        severity="medium",
                        title=f"{lead_label(lead)} entered {', '.join(entered_buckets)}",
                        detail="A follow-up bucket became newly relevant since the previous run.",
                        suggested_action="Apply the matching bucket copy/template if timing and delivery status allow it.",
                        occurred_at=lead.get("last_inbound_at") or lead.get("last_outbound_at"),
                    )
                )

    sorted_events = sort_events(events)
    attention_events = [
        event
        for event in sorted_events
        if event["severity"] in {"critical", "high"} and event["kind"] != "outbound_sent"
    ]
    sent_events = [event for event in sorted_events if event["kind"] == "outbound_sent"]
    state_events = [event for event in sorted_events if event["kind"] == "state_changed"]
    delivery_events = [event for event in sorted_events if event["kind"] == "delivery_changed"]

    bucket_deltas = metric_deltas(
        count_map(previous, "counts_by_bucket"),
        count_map(current, "counts_by_bucket"),
    )
    exclusion_deltas = metric_deltas(
        count_map(previous, "counts_by_exclusion_reason"),
        count_map(current, "counts_by_exclusion_reason"),
    )
    failure_deltas = metric_deltas(
        count_map(previous, "failed_delivery_codes"),
        count_map(current, "failed_delivery_codes"),
    )

    delta = {
        "schema_version": 1,
        "status": status,
        "source": source,
        "created_at": utc_now(),
        "baseline_available": baseline_available,
        "previous_generated_at": previous.get("generated_at") if previous else None,
        "current_generated_at": current.get("generated_at"),
        "summary_excerpt": summary.strip()[:1200],
        "metrics": {
            "total_leads": len(current_leads),
            "new_replies": sum(1 for event in sorted_events if event["kind"] in {"new_reply", "booking_time_provided"}),
            "needs_action": len(attention_events),
            "new_outbound": len(sent_events),
            "delivery_changes": len(delivery_events),
            "state_changes": len(state_events),
            "due_next_steps": sum(1 for event in sorted_events if event["kind"] == "due_next_step"),
            "new_exclusions": sum(1 for event in sorted_events if event["kind"] == "new_exclusion"),
        },
        "bucket_deltas": bucket_deltas,
        "exclusion_deltas": exclusion_deltas,
        "failure_deltas": failure_deltas,
        "events": sorted_events[:80],
        "attention_events": attention_events[:30],
        "sent_events": sent_events[:30],
    }
    delta["markdown"] = build_markdown(delta)
    return delta


def format_metric_delta(row: dict[str, Any]) -> str:
    """Format one metric delta line."""
    delta = int(row["delta"])
    sign = "+" if delta > 0 else ""
    return f"- `{row['key']}`: {row['previous']} -> {row['current']} ({sign}{delta})"


def build_markdown(delta: dict[str, Any]) -> str:
    """Build human-readable markdown from a structured delta."""
    metrics = delta["metrics"]
    lines = [
        "# Delta since previous run",
        "",
        f"- Previous snapshot: `{delta.get('previous_generated_at') or 'none'}`",
        f"- Current snapshot: `{delta.get('current_generated_at') or 'unknown'}`",
        f"- Baseline available: `{str(delta.get('baseline_available')).lower()}`",
        "",
        "## What changed",
        "",
        f"- New replies: **{metrics['new_replies']}**",
        f"- Needs action: **{metrics['needs_action']}**",
        f"- New outbound messages: **{metrics['new_outbound']}**",
        f"- Delivery changes: **{metrics['delivery_changes']}**",
        f"- State changes: **{metrics['state_changes']}**",
        f"- Due next steps: **{metrics['due_next_steps']}**",
        "",
    ]

    attention_events = delta.get("attention_events") or []
    lines.extend(["## Needs action now", ""])
    if not delta.get("baseline_available"):
        lines.append("- No previous structured snapshot yet. This run establishes the baseline.")
    elif not attention_events:
        lines.append("- No new high-priority CRM change since the previous run.")
    else:
        for event in attention_events[:12]:
            lines.append(
                f"- **{event['title']}**: {event['detail']} Action: {event['suggested_action']}"
            )

    lines.extend(["", "## Count changes", ""])
    count_lines = [
        *[format_metric_delta(row) for row in delta.get("bucket_deltas") or []],
        *[format_metric_delta(row) for row in delta.get("failure_deltas") or []],
        *[format_metric_delta(row) for row in delta.get("exclusion_deltas") or []],
    ]
    lines.extend(count_lines[:18] or ["- No bucket, provider-failure, or exclusion count changed."])
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", default="")
    parser.add_argument("--current", required=True)
    parser.add_argument("--summary", default="")
    parser.add_argument("--status", default="completed")
    parser.add_argument("--source", default="local_launchd")
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--output-md", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    previous = read_json(Path(args.previous)) if args.previous else None
    current = read_json(Path(args.current))
    if current is None:
        raise SystemExit(f"current snapshot is missing or invalid: {args.current}")
    delta = build_delta(
        previous=previous,
        current=current,
        status=args.status,
        summary=read_text(Path(args.summary)) if args.summary else "",
        source=args.source,
    )
    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(delta, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        Path(args.output_md).write_text(delta["markdown"], encoding="utf-8")
    print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
