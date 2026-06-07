"""Safety helpers for stopping live Meta Ads objects owned by CRM campaigns."""

from __future__ import annotations

import os
from typing import Any

from backend.database import LeadCaptureCampaign, PlatformEvent, PlatformMetaPublishAttempt
from backend.meta_ads_publish import (
    GraphPoster,
    _clean,
    _default_graph_poster,
    _env_truthy,
    _redact_graph_error,
)


class MetaCampaignLifecycleError(RuntimeError):
    """Raised when a live Meta object could not be paused safely."""


META_PAUSE_OBJECT_ORDER = {"ad": 0, "ad_set": 1, "campaign": 2}


def _execution_payload(attempt: PlatformMetaPublishAttempt) -> dict[str, Any]:
    """Return the latest live execution payload for one publish attempt."""
    response = attempt.response_payload()
    if response.get("schema_version") == "konecta.meta_publish_execution.v1":
        return response
    request = attempt.request_payload()
    state = request.get("live_execution_state") if isinstance(request, dict) else {}
    return state if isinstance(state, dict) else {}


def _attempt_campaign_ids(campaign: LeadCaptureCampaign) -> list[str]:
    """Return local campaign references that may own Meta publish attempts."""
    return list(dict.fromkeys([
        _clean(campaign.id),
        _clean(campaign.platform_ad_campaign_id),
    ]))


def _add_ref(refs: list[dict[str, str]], *, object_type: str, provider_id: str, source: str) -> None:
    """Append one Meta object ref once."""
    clean_type = _clean(object_type).lower()
    clean_provider_id = _clean(provider_id)
    if clean_type not in META_PAUSE_OBJECT_ORDER or not clean_provider_id:
        return
    key = (clean_type, clean_provider_id)
    if any((item["object_type"], item["provider_id"]) == key for item in refs):
        return
    refs.append({"object_type": clean_type, "provider_id": clean_provider_id, "source": source})


def meta_provider_refs_for_campaign(campaign: LeadCaptureCampaign) -> list[dict[str, str]]:
    """Return provider IDs for Meta objects linked to one local campaign."""
    refs: list[dict[str, str]] = []
    _add_ref(refs, object_type="ad", provider_id=campaign.meta_ad_id, source="lead_capture_campaign")
    _add_ref(refs, object_type="ad_set", provider_id=campaign.meta_adset_id, source="lead_capture_campaign")
    _add_ref(refs, object_type="campaign", provider_id=campaign.meta_campaign_id, source="lead_capture_campaign")

    for campaign_id in _attempt_campaign_ids(campaign):
        if not campaign_id:
            continue
        for attempt in PlatformMetaPublishAttempt.list_recent(campaign_id=campaign_id, limit=100):
            payload = _execution_payload(attempt)
            results = payload.get("operation_results") if isinstance(payload.get("operation_results"), list) else []
            for result in results:
                if not isinstance(result, dict):
                    continue
                if result.get("status") not in {"executed", "skipped"}:
                    continue
                _add_ref(
                    refs,
                    object_type=_clean(result.get("object_type")),
                    provider_id=_clean(result.get("provider_id")),
                    source=f"meta_publish_attempt:{attempt.id}",
                )

    return sorted(refs, key=lambda item: META_PAUSE_OBJECT_ORDER[item["object_type"]])


def pause_meta_objects_for_campaign(
    campaign: LeadCaptureCampaign,
    *,
    actor: str = "operator",
    source: str = "campaign_api",
    graph_post: GraphPoster | None = None,
) -> dict[str, Any]:
    """Pause every live Meta object known for one local campaign before local stop/delete."""
    refs = meta_provider_refs_for_campaign(campaign)
    if not refs:
        return {"needed": False, "status": "no_meta_objects", "objects": []}

    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    blocked: list[str] = []
    if graph_post is None:
        if not _env_truthy("META_MARKETING_LIVE_WRITES_ENABLED"):
            blocked.append("META_MARKETING_LIVE_WRITES_ENABLED")
        if not access_token:
            blocked.append("META_MARKETING_ACCESS_TOKEN")
        if not api_version:
            blocked.append("META_MARKETING_API_VERSION")

    if blocked:
        result = {
            "needed": True,
            "status": "blocked",
            "blocked_reasons": list(dict.fromkeys(blocked)),
            "objects": refs,
        }
        _emit_meta_pause_event(campaign, result, source=source, actor=actor)
        raise MetaCampaignLifecycleError(
            "Cannot pause Meta campaign objects before changing the local campaign: "
            + ", ".join(result["blocked_reasons"])
        )

    poster = graph_post or _default_graph_poster(api_version=api_version, access_token=access_token)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for ref in refs:
        try:
            response = poster(f"/{ref['provider_id']}", {"status": "PAUSED"})
            results.append({**ref, "status": "paused", "response": response})
        except Exception as error:
            error_text = _redact_graph_error(error)
            errors.append(error_text)
            results.append({**ref, "status": "failed", "error": error_text})

    result_status = "paused" if not errors else "failed"
    result = {
        "needed": True,
        "status": result_status,
        "objects": results,
        "errors": errors,
    }
    _emit_meta_pause_event(campaign, result, source=source, actor=actor)
    if errors:
        raise MetaCampaignLifecycleError(
            "Meta campaign objects were not fully paused; local campaign was not changed. "
            + "; ".join(errors)
        )
    return result


def _emit_meta_pause_event(
    campaign: LeadCaptureCampaign,
    result: dict[str, Any],
    *,
    source: str,
    actor: str,
) -> None:
    """Persist one lifecycle event for Meta pause attempts."""
    PlatformEvent.add(
        event_type="meta_campaign.pause_checked",
        lifecycle_stage="meta_publish",
        target_type="lead_capture_campaign",
        target_id=campaign.id,
        funnel_id=campaign.funnel_id,
        source=source,
        actor=actor,
        summary=f"Checked Meta pause for campaign {campaign.name}.",
        payload={
            "campaign_id": campaign.id,
            "platform_ad_campaign_id": campaign.platform_ad_campaign_id,
            "status": result.get("status"),
            "objects": result.get("objects", []),
            "blocked_reasons": result.get("blocked_reasons", []),
            "errors": result.get("errors", []),
        },
    )
