"""Safe Meta Ads publish preflight and execution-plan builder."""

from __future__ import annotations

import os
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.database import PlatformEvent, PlatformMetaPublishAttempt


class MetaAdsPublishError(RuntimeError):
    """Raised when a Meta publish attempt cannot be prepared."""


class MetaPublishOperation(BaseModel):
    """One ordered provider operation for a Meta publish attempt."""

    step: int
    local_ref: str
    object_type: Literal["campaign", "ad_set", "creative", "ad"]
    method: Literal["POST"] = "POST"
    path: str
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    live_write: bool = False


class MetaPublishPreflightResult(BaseModel):
    """Preflight result stored on PlatformMetaPublishAttempt.response_payload."""

    schema_version: str = "konecta.meta_publish_preflight.v1"
    attempt_id: str
    campaign_id: str = ""
    execution_mode: Literal["dry_run", "live_blocked", "live_ready"] = "dry_run"
    status: str
    approval_status: str
    ready_for_live_publish: bool
    live_writes_requested: bool
    live_writes_enabled: bool
    credentials_present: bool
    api_version: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    operations: list[MetaPublishOperation] = Field(default_factory=list)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _money_to_minor_units(value: Any) -> int | None:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    return int(round(amount * 100))


def _require(condition: bool, field: str, blocked: list[str]) -> None:
    if not condition:
        blocked.append(field)


def _plan_blockers(plan: dict[str, Any]) -> list[str]:
    """Return missing fields that make a staged plan impossible to execute."""
    blocked: list[str] = []
    _require(plan.get("schema_version") == "konecta.meta_publish_plan.v1", "schema_version", blocked)
    _require(_clean(plan.get("provider")) == "meta_marketing_api", "provider", blocked)
    _require(bool(_clean(plan.get("ad_account_id"))), "ad_account_id", blocked)

    campaign = plan.get("campaign") if isinstance(plan.get("campaign"), dict) else {}
    _require(bool(_clean(campaign.get("name"))), "campaign.name", blocked)
    _require(bool(_clean(campaign.get("objective"))), "campaign.objective", blocked)

    destination = plan.get("destination") if isinstance(plan.get("destination"), dict) else {}
    destination_type = _clean(destination.get("destination_type")) or "whatsapp"
    if destination_type == "whatsapp":
        _require(bool(_clean(destination.get("page_id"))), "destination.page_id", blocked)
        _require(bool(_clean(destination.get("whatsapp_phone_number_id"))), "destination.whatsapp_phone_number_id", blocked)
    elif destination_type == "instant_form":
        _require(bool(_clean(destination.get("page_id"))), "destination.page_id", blocked)
        _require(bool(_clean(destination.get("lead_form_id"))), "destination.lead_form_id", blocked)
    elif destination_type == "landing_page":
        _require(bool(_clean(destination.get("landing_page_url"))), "destination.landing_page_url", blocked)
    else:
        blocked.append("destination.destination_type")

    ad_sets = plan.get("ad_sets") if isinstance(plan.get("ad_sets"), list) else []
    _require(bool(ad_sets), "ad_sets", blocked)
    for ad_set_index, ad_set in enumerate(ad_sets, start=1):
        if not isinstance(ad_set, dict):
            blocked.append(f"ad_sets[{ad_set_index}]")
            continue
        prefix = f"ad_sets[{ad_set_index}]"
        _require(bool(_clean(ad_set.get("name"))), f"{prefix}.name", blocked)
        has_budget = bool(_money_to_minor_units(ad_set.get("budget_daily_usd")) or _money_to_minor_units(ad_set.get("budget_total_usd")))
        _require(has_budget, f"{prefix}.budget", blocked)
        _require(isinstance(ad_set.get("targeting"), dict) and bool(ad_set.get("targeting")), f"{prefix}.targeting", blocked)
        ads = ad_set.get("ads") if isinstance(ad_set.get("ads"), list) else []
        _require(bool(ads), f"{prefix}.ads", blocked)
        for ad_index, ad in enumerate(ads, start=1):
            if not isinstance(ad, dict):
                blocked.append(f"{prefix}.ads[{ad_index}]")
                continue
            ad_prefix = f"{prefix}.ads[{ad_index}]"
            _require(bool(_clean(ad.get("name"))), f"{ad_prefix}.name", blocked)
            creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
            has_creative_ref = any(
                _clean(creative.get(field))
                for field in ["creative_asset_id", "asset_file_path", "meta_creative_id", "image_hash", "video_id"]
            )
            _require(has_creative_ref, f"{ad_prefix}.creative", blocked)
            _require(bool(_clean(creative.get("primary_text"))), f"{ad_prefix}.creative.primary_text", blocked)
            _require(bool(_clean(creative.get("headline"))), f"{ad_prefix}.creative.headline", blocked)
    return blocked


def _destination_promoted_object(destination: dict[str, Any]) -> dict[str, Any]:
    destination_type = _clean(destination.get("destination_type")) or "whatsapp"
    if destination_type == "whatsapp":
        return {
            "page_id": _clean(destination.get("page_id")),
            "whatsapp_phone_number_id": _clean(destination.get("whatsapp_phone_number_id")),
        }
    if destination_type == "instant_form":
        return {"page_id": _clean(destination.get("page_id")), "lead_form_id": _clean(destination.get("lead_form_id"))}
    return {"page_id": _clean(destination.get("page_id")), "landing_page_url": _clean(destination.get("landing_page_url"))}


def _creative_params(plan: dict[str, Any], creative: dict[str, Any], name: str) -> dict[str, Any]:
    destination = plan.get("destination") if isinstance(plan.get("destination"), dict) else {}
    destination_type = _clean(destination.get("destination_type")) or "whatsapp"
    page_id = _clean(destination.get("page_id"))
    call_to_action = _clean(creative.get("call_to_action")) or "WHATSAPP_MESSAGE"
    params: dict[str, Any] = {
        "name": name,
        "source_creative_asset_id": _clean(creative.get("creative_asset_id")),
        "source_asset_file_path": _clean(creative.get("asset_file_path")),
        "primary_text": _clean(creative.get("primary_text")),
        "headline": _clean(creative.get("headline")),
        "description": _clean(creative.get("description")),
        "destination_type": destination_type,
        "object_story_spec": {
            "page_id": page_id,
            "call_to_action": {
                "type": call_to_action,
                "value": {
                    "link": _clean(creative.get("destination_url")) or _clean(destination.get("landing_page_url")),
                    "whatsapp_phone_number_id": _clean(destination.get("whatsapp_phone_number_id")),
                    "lead_form_id": _clean(destination.get("lead_form_id")),
                },
            },
        },
    }
    if _clean(creative.get("image_hash")):
        params["image_hash"] = _clean(creative.get("image_hash"))
    if _clean(creative.get("video_id")):
        params["video_id"] = _clean(creative.get("video_id"))
    return params


def build_meta_publish_operations(plan: dict[str, Any], *, live_write: bool = False) -> list[MetaPublishOperation]:
    """Build the ordered campaign -> ad sets -> creatives -> ads operation graph."""
    ad_account_id = _clean(plan.get("ad_account_id"))
    campaign = plan.get("campaign") if isinstance(plan.get("campaign"), dict) else {}
    destination = plan.get("destination") if isinstance(plan.get("destination"), dict) else {}
    operations: list[MetaPublishOperation] = []
    step = 1

    campaign_ref = "campaign"
    operations.append(
        MetaPublishOperation(
            step=step,
            local_ref=campaign_ref,
            object_type="campaign",
            path=f"/{ad_account_id}/campaigns",
            live_write=live_write,
            params={
                "name": _clean(campaign.get("name")),
                "objective": _clean(campaign.get("objective")),
                "buying_type": _clean(campaign.get("buying_type")) or "AUCTION",
                "special_ad_categories": campaign.get("special_ad_categories") or [],
                "status": _clean(campaign.get("create_status")) or "PAUSED",
            },
        )
    )
    step += 1

    ad_sets = plan.get("ad_sets") if isinstance(plan.get("ad_sets"), list) else []
    for ad_set_index, ad_set in enumerate(ad_sets, start=1):
        if not isinstance(ad_set, dict):
            continue
        ad_set_ref = f"ad_set_{ad_set_index}"
        params: dict[str, Any] = {
            "name": _clean(ad_set.get("name")),
            "campaign_id": f"{{{{{campaign_ref}.id}}}}",
            "status": _clean(ad_set.get("status")) or "PAUSED",
            "optimization_goal": _clean(ad_set.get("optimization_goal")) or "LEAD_GENERATION",
            "billing_event": _clean(ad_set.get("billing_event")) or "IMPRESSIONS",
            "bid_strategy": _clean(ad_set.get("bid_strategy")) or "LOWEST_COST_WITHOUT_CAP",
            "targeting": ad_set.get("targeting") if isinstance(ad_set.get("targeting"), dict) else {},
            "promoted_object": _destination_promoted_object(destination),
        }
        daily_budget = _money_to_minor_units(ad_set.get("budget_daily_usd"))
        total_budget = _money_to_minor_units(ad_set.get("budget_total_usd"))
        if daily_budget is not None:
            params["daily_budget"] = daily_budget
        if total_budget is not None:
            params["lifetime_budget"] = total_budget
        if _clean(ad_set.get("start_time")):
            params["start_time"] = _clean(ad_set.get("start_time"))
        if _clean(ad_set.get("end_time")):
            params["end_time"] = _clean(ad_set.get("end_time"))
        if isinstance(ad_set.get("placements"), list) and ad_set["placements"]:
            params["publisher_platforms"] = ad_set["placements"]
        operations.append(
            MetaPublishOperation(
                step=step,
                local_ref=ad_set_ref,
                object_type="ad_set",
                path=f"/{ad_account_id}/adsets",
                depends_on=[campaign_ref],
                live_write=live_write,
                params=params,
            )
        )
        step += 1

        ads = ad_set.get("ads") if isinstance(ad_set.get("ads"), list) else []
        for ad_index, ad in enumerate(ads, start=1):
            if not isinstance(ad, dict):
                continue
            creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
            creative_ref = f"creative_{ad_set_index}_{ad_index}"
            ad_ref = f"ad_{ad_set_index}_{ad_index}"
            existing_creative_id = _clean(creative.get("meta_creative_id"))
            if not existing_creative_id:
                operations.append(
                    MetaPublishOperation(
                        step=step,
                        local_ref=creative_ref,
                        object_type="creative",
                        path=f"/{ad_account_id}/adcreatives",
                        depends_on=[ad_set_ref],
                        live_write=live_write,
                        params=_creative_params(plan, creative, _clean(creative.get("name")) or _clean(ad.get("name"))),
                    )
                )
                step += 1
                creative_id_ref = f"{{{{{creative_ref}.id}}}}"
            else:
                creative_id_ref = existing_creative_id
            operations.append(
                MetaPublishOperation(
                    step=step,
                    local_ref=ad_ref,
                    object_type="ad",
                    path=f"/{ad_account_id}/ads",
                    depends_on=[ad_set_ref] if existing_creative_id else [ad_set_ref, creative_ref],
                    live_write=live_write,
                    params={
                        "name": _clean(ad.get("name")),
                        "adset_id": f"{{{{{ad_set_ref}.id}}}}",
                        "creative": {"creative_id": creative_id_ref},
                        "status": _clean(ad.get("status")) or "PAUSED",
                    },
                )
            )
            step += 1
    return operations


def preflight_meta_publish_attempt(
    *,
    attempt_id: str,
    live_writes_requested: bool = False,
    actor: str = "agent",
    source: str = "codex_agent_tool",
) -> tuple[PlatformMetaPublishAttempt, MetaPublishPreflightResult]:
    """Preflight a staged Meta plan and persist the execution graph."""
    attempt = PlatformMetaPublishAttempt.get_by_id(attempt_id)
    if attempt is None:
        raise MetaAdsPublishError(f"Meta publish attempt not found: {attempt_id}")

    plan = attempt.request_payload()
    blocked = list(dict.fromkeys([*_plan_blockers(plan), *plan.get("required_before_live_publish", [])]))
    live_writes_enabled = _env_truthy("META_MARKETING_LIVE_WRITES_ENABLED")
    token_present = bool(_clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN")))
    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    warnings: list[str] = []
    if not api_version:
        warnings.append("META_MARKETING_API_VERSION is not configured.")
    if not token_present:
        warnings.append("META_MARKETING_ACCESS_TOKEN is not configured; dry-run preflight can continue, live publish cannot.")
    if attempt.approval_status not in {"approved", "pending", "needs_preflight"}:
        warnings.append(f"Current approval_status is {attempt.approval_status}.")

    if live_writes_requested:
        if not live_writes_enabled:
            blocked.append("META_MARKETING_LIVE_WRITES_ENABLED")
        if not token_present:
            blocked.append("META_MARKETING_ACCESS_TOKEN")
        if attempt.approval_status != "approved":
            blocked.append("approval_status=approved")
        if plan.get("live_writes_allowed") is not True:
            blocked.append("plan.live_writes_allowed=true")

    live_write = live_writes_requested and not blocked and live_writes_enabled and token_present
    operations = build_meta_publish_operations(plan, live_write=live_write) if not _plan_blockers(plan) else []
    ready = not blocked and bool(operations)
    execution_mode: Literal["dry_run", "live_blocked", "live_ready"] = "dry_run"
    if live_writes_requested and not live_write:
        execution_mode = "live_blocked"
    elif live_write:
        execution_mode = "live_ready"

    result = MetaPublishPreflightResult(
        attempt_id=attempt.id,
        campaign_id=attempt.campaign_id,
        execution_mode=execution_mode,
        status="preflight_ready" if ready else "blocked",
        approval_status=attempt.approval_status,
        ready_for_live_publish=ready and live_writes_enabled and token_present and attempt.approval_status == "approved",
        live_writes_requested=live_writes_requested,
        live_writes_enabled=live_writes_enabled,
        credentials_present=token_present,
        api_version=api_version,
        blocked_reasons=list(dict.fromkeys(blocked)),
        warnings=warnings,
        operations=operations,
    )
    updated = PlatformMetaPublishAttempt.update_execution(
        attempt.id,
        status=result.status,
        response_payload=result.model_dump(mode="json"),
        error=", ".join(result.blocked_reasons),
    )
    if updated is None:
        raise MetaAdsPublishError(f"Meta publish attempt disappeared during preflight: {attempt.id}")
    PlatformEvent.add(
        event_type="meta_publish.preflight_checked",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=updated.id,
        funnel_id=_clean(plan.get("funnel_id")),
        source=source,
        actor=actor,
        summary=f"Preflighted Meta publish attempt {updated.id}.",
        payload={
            "campaign_id": updated.campaign_id,
            "status": result.status,
            "execution_mode": result.execution_mode,
            "blocked_reasons": result.blocked_reasons,
            "operations": len(result.operations),
        },
    )
    return updated, result
