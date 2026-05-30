"""Shared orchestration for transcript-to-client-profile extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.ai.client_profile_extractor import ClientProfileExtractionResult, run_client_profile_extraction
from backend.database import PlatformClientProfile, PlatformEvent, PlatformMeeting


class PlatformProfileExtractionError(RuntimeError):
    """Raised when a meeting transcript cannot produce a saved profile."""


@dataclass(frozen=True)
class PlatformProfileExtraction:
    """Saved extraction result for API and agent-tool responses."""

    meeting: PlatformMeeting
    profile: PlatformClientProfile
    extraction: ClientProfileExtractionResult


Extractor = Callable[..., ClientProfileExtractionResult | dict[str, Any]]


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _resolve_client_id(meeting: PlatformMeeting, client_id: str) -> str:
    resolved = _clean(client_id) or _clean(meeting.client_id)
    if not resolved:
        raise PlatformProfileExtractionError("client_id is required to save an extracted client profile")
    return resolved


def _normalize_extraction(raw_result: ClientProfileExtractionResult | dict[str, Any]) -> ClientProfileExtractionResult:
    if isinstance(raw_result, ClientProfileExtractionResult):
        return raw_result
    return ClientProfileExtractionResult.model_validate(raw_result)


def extract_client_profile_from_meeting(
    *,
    meeting_id: str,
    client_id: str = "",
    lead_id: str = "",
    funnel_id: str = "",
    status: str = "draft",
    existing_context: dict[str, Any] | None = None,
    source: str = "platform",
    actor: str = "agent",
    extractor: Extractor | None = None,
) -> PlatformProfileExtraction:
    """Extract and save a draft client profile from one meeting transcript."""
    meeting = PlatformMeeting.get_by_id(meeting_id)
    if meeting is None:
        raise PlatformProfileExtractionError(f"Meeting not found: {meeting_id}")

    transcript_text = _clean(meeting.transcript_text)
    if not transcript_text:
        raise PlatformProfileExtractionError(f"Meeting has no transcript text: {meeting_id}")

    resolved_client_id = _resolve_client_id(meeting, client_id)
    resolved_lead_id = _clean(lead_id) or meeting.lead_id
    resolved_funnel_id = _clean(funnel_id) or meeting.funnel_id
    context = {
        "meeting": {
            "id": meeting.id,
            "lead_id": meeting.lead_id,
            "client_id": meeting.client_id,
            "funnel_id": meeting.funnel_id,
            "context_summary": meeting.context_summary,
            "lead_email": meeting.lead_email,
            "timezone": meeting.timezone,
            "requested_day": meeting.requested_day,
            "requested_time": meeting.requested_time,
        },
        "existing_profile": meeting.extracted_profile(),
        "operator_context": existing_context or {},
    }

    runner = extractor or run_client_profile_extraction
    extraction = _normalize_extraction(
        runner(
            transcript_text=transcript_text,
            existing_context=context,
        )
    )
    profile_payload = extraction.to_profile_payload()
    profile = PlatformClientProfile.upsert(
        client_id=resolved_client_id,
        lead_id=resolved_lead_id,
        funnel_id=resolved_funnel_id,
        status=status,
        source_meeting_id=meeting.id,
        **profile_payload,
    )
    updated_meeting = PlatformMeeting.attach_transcript(
        meeting.id,
        transcript_text=meeting.transcript_text,
        transcript_path=meeting.transcript_path,
        extracted_profile=extraction.to_meeting_profile_payload(profile_id=profile.id),
        status="profile_extracted",
    )
    if updated_meeting is None:
        raise PlatformProfileExtractionError(f"Meeting disappeared during extraction: {meeting.id}")

    PlatformEvent.add(
        event_type="client_profile.extracted_from_transcript",
        lifecycle_stage="post_conversion",
        target_type="client_profile",
        target_id=profile.id,
        funnel_id=resolved_funnel_id,
        source=source,
        actor=actor,
        summary=f"Extracted client profile for {resolved_client_id} from meeting {meeting.id}.",
        payload={
            "meeting_id": meeting.id,
            "client_id": resolved_client_id,
            "lead_id": resolved_lead_id,
            "status": status,
            "confidence": extraction.confidence,
            "ad_angles": len(extraction.ad_angles),
            "segments": len(extraction.segments),
            "required_before_meta_publish": extraction.meta_planning.get("required_before_meta_publish", []),
        },
    )
    return PlatformProfileExtraction(meeting=updated_meeting, profile=profile, extraction=extraction)
