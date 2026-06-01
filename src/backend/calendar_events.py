"""Google Calendar scheduling gate for platform meetings."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field

from backend.database import ContadoresLead, PlatformEvent, PlatformMeeting, normalize_email


class CalendarSchedulingError(RuntimeError):
    """Raised when a meeting calendar event cannot be prepared."""


class CalendarSchedulingResult(BaseModel):
    """Result persisted after checking or creating a Google Calendar event."""

    schema_version: str = "konecta.calendar_event.v1"
    meeting_id: str
    status: str
    calendar_id: str = ""
    calendar_event_id: str = ""
    calendar_event_link: str = ""
    live_writes_requested: bool = False
    live_write_executed: bool = False
    create_google_meet: bool = False
    send_updates: str = "all"
    timezone: str = ""
    start_at: str = ""
    end_at: str = ""
    attendees: list[str] = Field(default_factory=list)
    event_payload: dict[str, Any] = Field(default_factory=dict)
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provider_response: dict[str, Any] = Field(default_factory=dict)


CalendarInsert = Callable[[str, dict[str, Any], str, int], dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _split_emails(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw_values = [str(item) for item in value]
    else:
        raw_values = str(value or "").replace(";", ",").split(",")
    emails: list[str] = []
    for raw in raw_values:
        email = normalize_email(raw)
        if email and email not in emails:
            emails.append(email)
    return emails


def _env_internal_attendees() -> list[str]:
    return _split_emails(
        os.getenv("PLATFORM_MEETING_INTERNAL_ATTENDEES")
        or os.getenv("GOOGLE_CALENDAR_INTERNAL_ATTENDEES")
        or ""
    )


def _env_calendar_id() -> str:
    return _clean(os.getenv("PLATFORM_MEETING_CALENDAR_ID") or os.getenv("GOOGLE_CALENDAR_ID"))


def _service_account_file() -> str:
    for env_name in [
        "GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE",
        "CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE",
        "GOOGLE_SERVICE_ACCOUNT_FILE",
    ]:
        value = _clean(os.getenv(env_name))
        if value:
            return value
    return ""


def _delegated_user() -> str:
    return normalize_email(os.getenv("GOOGLE_CALENDAR_DELEGATED_USER") or os.getenv("GOOGLE_WORKSPACE_DELEGATED_USER"))


def _google_insert_payload(event_payload: dict[str, Any], delegated_user: str) -> tuple[dict[str, Any], list[str]]:
    """Return the payload Google Calendar can accept for the configured auth mode."""
    if delegated_user or not event_payload.get("attendees"):
        return event_payload, []
    payload = dict(event_payload)
    payload.pop("attendees", None)
    return payload, [
        "Google Calendar service-account writes cannot invite attendees without Domain-Wide Delegation; "
        "inserted the event without Google attendees."
    ]


def _coerce_start(meeting: PlatformMeeting, timezone_name: str) -> datetime | None:
    if meeting.scheduled_at is None:
        return None
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return None
    if meeting.scheduled_at.tzinfo is None:
        return meeting.scheduled_at.replace(tzinfo=timezone.utc).astimezone(zone)
    return meeting.scheduled_at.astimezone(zone)


def _valid_timezone(timezone_name: str) -> bool:
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return False
    return True


def _event_title(meeting: PlatformMeeting) -> str:
    reference = meeting.client_id or meeting.lead_id or meeting.lead_email or "lead"
    return f"Konecta discovery call - {reference}"


def _event_description(meeting: PlatformMeeting) -> str:
    lines = [
        "Meeting scheduled by the Konecta platform.",
        f"Lead ID: {meeting.lead_id or '-'}",
        f"Client ID: {meeting.client_id or '-'}",
        f"Funnel: {meeting.funnel_id or '-'}",
        f"Requested: {' '.join([meeting.requested_day, meeting.requested_time]).strip() or '-'}",
        "",
        "Conversation context:",
        meeting.context_summary or "-",
    ]
    return "\n".join(lines)


def build_meeting_calendar_event_payload(
    meeting: PlatformMeeting,
    *,
    calendar_id: str = "",
    internal_attendees: list[str] | None = None,
    duration_minutes: int = 15,
    create_google_meet: bool = False,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Build a Google Calendar event payload and return blockers/warnings."""
    clean_calendar_id = _clean(calendar_id) or _env_calendar_id()
    attendees = _split_emails([meeting.lead_email, *list(internal_attendees or _env_internal_attendees())])
    timezone_name = _clean(meeting.timezone)
    blocked: list[str] = []
    warnings: list[str] = []

    if not clean_calendar_id:
        blocked.append("calendar_id")
    if not normalize_email(meeting.lead_email):
        blocked.append("lead_email")
    if len(attendees) < 2:
        blocked.append("internal_attendees")
    if not timezone_name:
        blocked.append("timezone")
    elif not _valid_timezone(timezone_name):
        blocked.append("timezone")
    if meeting.scheduled_at is None:
        blocked.append("scheduled_at")
    if not meeting.context_summary.strip():
        warnings.append("Meeting context is empty.")

    start_at = _coerce_start(meeting, timezone_name) if timezone_name else None
    end_at = start_at + timedelta(minutes=max(5, min(duration_minutes, 180))) if start_at else None
    payload: dict[str, Any] = {}
    if start_at and end_at:
        payload = {
            "summary": _event_title(meeting),
            "description": _event_description(meeting),
            "start": {"dateTime": start_at.isoformat(), "timeZone": timezone_name},
            "end": {"dateTime": end_at.isoformat(), "timeZone": timezone_name},
            "attendees": [{"email": email} for email in attendees],
            "guestsCanModify": False,
            "guestsCanInviteOthers": False,
            "guestsCanSeeOtherGuests": True,
            "reminders": {"useDefault": True},
            "extendedProperties": {
                "private": {
                    "platform_meeting_id": meeting.id,
                    "lead_id": meeting.lead_id,
                    "client_id": meeting.client_id,
                    "funnel_id": meeting.funnel_id,
                }
            },
        }
        if create_google_meet:
            payload["conferenceData"] = {
                "createRequest": {
                    "requestId": f"konecta-{meeting.id[:16]}-{uuid.uuid4().hex[:8]}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }
    return payload, list(dict.fromkeys(blocked)), warnings


def _insert_google_calendar_event(
    calendar_id: str,
    event_payload: dict[str, Any],
    send_updates: str,
    conference_data_version: int,
) -> dict[str, Any]:
    """Create one Google Calendar event using the configured service account."""
    credentials_path = _service_account_file()
    delegated_user = _delegated_user()
    if not credentials_path:
        raise CalendarSchedulingError("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE is required")
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise CalendarSchedulingError("google-api-python-client and google-auth are required") from exc

    credentials = Credentials.from_service_account_file(
        credentials_path,
        scopes=["https://www.googleapis.com/auth/calendar.events"],
    )
    event_payload, _warnings = _google_insert_payload(event_payload, delegated_user)
    if delegated_user:
        # Optional: only use Domain-Wide Delegation when writing as a Workspace user.
        credentials = credentials.with_subject(delegated_user)
    service = build("calendar", "v3", credentials=credentials)
    return (
        service.events()
        .insert(
            calendarId=calendar_id,
            body=event_payload,
            sendUpdates=send_updates,
            conferenceDataVersion=conference_data_version,
        )
        .execute()
    )


def schedule_meeting_calendar_event(
    *,
    meeting_id: str,
    calendar_id: str = "",
    internal_attendees: list[str] | None = None,
    duration_minutes: int = 15,
    create_google_meet: bool = False,
    live_writes_requested: bool = False,
    send_updates: str = "all",
    actor: str = "agent",
    source: str = "codex_agent_tool",
    calendar_insert: CalendarInsert | None = None,
) -> tuple[PlatformMeeting, CalendarSchedulingResult]:
    """Preflight or create a Google Calendar event for one platform meeting."""
    meeting = PlatformMeeting.get_by_id(meeting_id)
    if meeting is None:
        raise CalendarSchedulingError(f"Meeting not found: {meeting_id}")

    clean_calendar_id = _clean(calendar_id) or _env_calendar_id()
    event_payload, blocked, warnings = build_meeting_calendar_event_payload(
        meeting,
        calendar_id=clean_calendar_id,
        internal_attendees=internal_attendees,
        duration_minutes=duration_minutes,
        create_google_meet=create_google_meet,
    )
    if live_writes_requested:
        existing_event_id = _clean(meeting.calendar_event_id)
        if existing_event_id:
            warnings.append("Meeting already has a Google Calendar event; skipped duplicate creation.")
        if not existing_event_id and not _service_account_file() and calendar_insert is None:
            blocked.append("GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE")

    blocked = list(dict.fromkeys(blocked))
    existing_event_id = _clean(meeting.calendar_event_id)
    if existing_event_id:
        if blocked:
            warnings.append(f"Current meeting details are incomplete: {', '.join(blocked)}.")
        blocked = []
    attendees = [item["email"] for item in event_payload.get("attendees", []) if isinstance(item, dict)]
    start_at = event_payload.get("start", {}).get("dateTime", "")
    end_at = event_payload.get("end", {}).get("dateTime", "")
    status = "scheduled" if existing_event_id else ("calendar_blocked" if blocked else "calendar_ready")
    provider_response: dict[str, Any] = {}
    live_write_executed = False
    error = "" if existing_event_id else ", ".join(blocked)

    if live_writes_requested and not blocked and not existing_event_id:
        try:
            insert = calendar_insert or _insert_google_calendar_event
            insert_payload, insert_warnings = _google_insert_payload(event_payload, _delegated_user())
            warnings.extend(insert_warnings)
            provider_response = insert(
                clean_calendar_id,
                insert_payload,
                send_updates,
                1 if create_google_meet else 0,
            )
            live_write_executed = True
            status = "scheduled"
            error = ""
        except Exception as exc:
            status = "calendar_failed"
            error = str(exc)[:12000]
            blocked.append("google_calendar.create_failed")

    result = CalendarSchedulingResult(
        meeting_id=meeting.id,
        status=status,
        calendar_id=clean_calendar_id,
        calendar_event_id=_clean(provider_response.get("id")) or meeting.calendar_event_id,
        calendar_event_link=_clean(provider_response.get("htmlLink")) or meeting.calendar_event_link,
        live_writes_requested=live_writes_requested,
        live_write_executed=live_write_executed,
        create_google_meet=create_google_meet,
        send_updates=send_updates,
        timezone=meeting.timezone,
        start_at=start_at,
        end_at=end_at,
        attendees=attendees,
        event_payload=event_payload,
        blocked_reasons=list(dict.fromkeys(blocked)),
        warnings=warnings,
        provider_response=provider_response,
    )
    updated = PlatformMeeting.update_calendar(
        meeting.id,
        status=status,
        calendar_id=clean_calendar_id,
        calendar_event_id=result.calendar_event_id,
        calendar_event_link=result.calendar_event_link,
        calendar_event_payload=result.event_payload,
        calendar_result=result.model_dump(mode="json"),
        calendar_error=error,
    )
    if updated is None:
        raise CalendarSchedulingError(f"Meeting disappeared during calendar scheduling: {meeting.id}")
    if updated.lead_id and updated.scheduled_at is not None:
        ContadoresLead.update_flow_state(
            updated.lead_id,
            meeting_scheduled_at=updated.scheduled_at,
            automation_paused=True,
            automation_paused_reason="meeting_scheduled",
        )
    PlatformEvent.add(
        event_type="meeting.calendar_event_checked",
        lifecycle_stage="meeting",
        target_type="meeting",
        target_id=updated.id,
        funnel_id=updated.funnel_id,
        source=source,
        actor=actor,
        summary=f"Checked calendar scheduling for meeting {updated.id}.",
        payload={
            "status": result.status,
            "calendar_id": result.calendar_id,
            "calendar_event_id": result.calendar_event_id,
            "live_writes_requested": result.live_writes_requested,
            "live_write_executed": result.live_write_executed,
            "blocked_reasons": result.blocked_reasons,
        },
    )
    return updated, result
