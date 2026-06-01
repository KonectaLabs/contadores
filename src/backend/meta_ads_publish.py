"""Safe Meta Ads publish preflight and execution-plan builder."""

from __future__ import annotations

import math
import os
import json
import mimetypes
import re
from pathlib import Path
from typing import Any, Literal
from collections.abc import Callable

import httpx
from pydantic import BaseModel, Field

from backend.database import (
    DATA_DIR,
    ClientLeadSource,
    PlatformCreativeAsset,
    PlatformEvent,
    PlatformMetaInventorySnapshot,
    PlatformMetaPublishAttempt,
)
from backend.funnel_config import (
    FunnelDefinition,
    get_funnel,
    list_funnels_by_whatsapp_referral_source_id,
    slugify_funnel_id,
    upsert_funnel,
)


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


class MetaPublishOperationResult(BaseModel):
    """Provider result for one Meta publish operation."""

    step: int
    local_ref: str
    object_type: str
    path: str
    status: Literal["executed", "skipped", "failed"]
    provider_id: str = ""
    request_params: dict[str, Any] = Field(default_factory=dict)
    response: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class MetaPublishExecutionResult(BaseModel):
    """Live execution result for a staged and approved Meta publish attempt."""

    schema_version: str = "konecta.meta_publish_execution.v1"
    attempt_id: str
    campaign_id: str = ""
    status: Literal["blocked", "submitted", "partial_failed", "already_submitted"]
    live_writes_requested: bool = False
    live_write_executed: bool = False
    api_version: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    operation_results: list[MetaPublishOperationResult] = Field(default_factory=list)


class MetaCreativeAssetUploadResult(BaseModel):
    """Result of uploading one generated asset to Meta's media library."""

    schema_version: str = "konecta.meta_creative_asset_upload.v1"
    asset_id: str
    campaign_id: str = ""
    status: Literal["blocked", "uploaded", "already_uploaded", "failed"]
    live_writes_requested: bool = False
    live_write_executed: bool = False
    ad_account_id: str = ""
    api_version: str = ""
    provider_asset_type: Literal["image", "video", "creative"] = "image"
    image_hash: str = ""
    video_id: str = ""
    meta_creative_id: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    linked_publish_attempts: list[str] = Field(default_factory=list)
    response: dict[str, Any] = Field(default_factory=dict)


class MetaPublishBudgetSummary(BaseModel):
    """Budget totals reviewed before a staged Meta plan can be approved."""

    currency: str = "USD"
    total_daily_budget_usd: int = 0
    total_lifetime_budget_usd: int = 0
    estimated_monthly_budget_usd: int = 0
    ad_sets: list[dict[str, Any]] = Field(default_factory=list)
    max_daily_budget_usd: int
    max_lifetime_budget_usd: int
    max_estimated_monthly_budget_usd: int


class MetaPublishApprovalResult(BaseModel):
    """Approval gate result stored on PlatformMetaPublishAttempt.response_payload."""

    schema_version: str = "konecta.meta_publish_approval.v1"
    attempt_id: str
    campaign_id: str = ""
    approved: bool
    approval_status: str
    approved_by: str = ""
    approval_note: str = ""
    live_writes_allowed: bool = False
    budget: MetaPublishBudgetSummary
    inventory_snapshot_id: str = ""
    inventory_status: str = ""
    blocked_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


GraphPoster = Callable[[str, dict[str, Any]], dict[str, Any]]
GraphUploader = Callable[[str, Path, str, dict[str, Any]], dict[str, Any]]


def _sanitize_provider_payload(value: Any) -> Any:
    """Remove token-like fields before persisting provider payloads."""
    if isinstance(value, dict):
        return {
            key: _sanitize_provider_payload(item)
            for key, item in value.items()
            if "token" not in key.lower() and "secret" not in key.lower()
        }
    if isinstance(value, list):
        return [_sanitize_provider_payload(item) for item in value]
    return value


def _redact_graph_error(value: Any) -> str:
    """Remove bearer/query tokens from provider error strings before persistence."""
    text = str(value)
    text = re.sub(r"(?i)(access_token=)[^&\s'\"<>]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(access_token%3D)[^&\s'\"<>]+", r"\1[redacted]", text)
    return text


def _graph_base_url(api_version: str) -> str:
    version = _clean(api_version).strip("/")
    if not version:
        raise MetaAdsPublishError("META_MARKETING_API_VERSION is required for Meta publish execution")
    return f"https://graph.facebook.com/{version}"


def _encode_graph_params(params: dict[str, Any]) -> dict[str, Any]:
    """Encode nested Graph API params as JSON strings for form posts."""
    encoded: dict[str, Any] = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            encoded[key] = json.dumps(value, ensure_ascii=True)
        else:
            encoded[key] = value
    return encoded


def _default_graph_poster(*, api_version: str, access_token: str, timeout: float = 30) -> GraphPoster:
    base_url = _graph_base_url(api_version)

    def graph_post(path: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = _encode_graph_params(params)
        request_params["access_token"] = access_token
        response = httpx.post(f"{base_url}/{path.strip('/')}", data=request_params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return _sanitize_provider_payload(payload if isinstance(payload, dict) else {"data": payload})

    return graph_post


def _default_graph_uploader(*, api_version: str, access_token: str, timeout: float = 120) -> GraphUploader:
    base_url = _graph_base_url(api_version)

    def graph_upload(path: str, file_path: Path, file_field: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = _encode_graph_params(params)
        request_params["access_token"] = access_token
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        with file_path.open("rb") as handle:
            files = {file_field: (file_path.name, handle, mime_type)}
            response = httpx.post(
                f"{base_url}/{path.strip('/')}",
                data=request_params,
                files=files,
                timeout=timeout,
            )
        response.raise_for_status()
        payload = response.json()
        return _sanitize_provider_payload(payload if isinstance(payload, dict) else {"data": payload})

    return graph_upload


REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_creative_file(file_path: str) -> Path | None:
    """Resolve a staged creative file without allowing path traversal."""
    clean_path = _clean(file_path)
    if not clean_path:
        return None
    candidate = Path(clean_path).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        parts = candidate.parts
        if parts and parts[0] == "data":
            resolved = DATA_DIR.joinpath(*parts[1:]).expanduser().resolve()
        else:
            resolved = (REPO_ROOT / candidate).resolve()
    allowed_roots = [REPO_ROOT.resolve(), DATA_DIR.expanduser().resolve()]
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    return None


def _provider_asset_type(asset: PlatformCreativeAsset) -> Literal["image", "video", "creative"]:
    """Map local asset type to a Meta uploadable asset family."""
    asset_type = _clean(asset.asset_type).lower()
    if asset_type == "video":
        return "video"
    if asset_type == "creative":
        return "creative"
    return "image"


def _extract_uploaded_image_hash(response: dict[str, Any]) -> str:
    """Return an image hash from Meta adimages response variants."""
    if _clean(response.get("hash")):
        return _clean(response.get("hash"))
    images = response.get("images")
    if isinstance(images, dict):
        for item in images.values():
            if isinstance(item, dict) and _clean(item.get("hash")):
                return _clean(item.get("hash"))
    return ""


def _extract_uploaded_video_id(response: dict[str, Any]) -> str:
    """Return a video ID from Meta advideos response variants."""
    return _clean(response.get("id")) or _clean(response.get("video_id"))


def _link_uploaded_asset_to_publish_attempts(asset: PlatformCreativeAsset) -> list[str]:
    """Patch staged Meta plans that reference this asset with provider media IDs."""
    linked: list[str] = []
    if not asset.campaign_id:
        return linked
    attempts = PlatformMetaPublishAttempt.list_recent(campaign_id=asset.campaign_id, limit=100)
    for attempt in attempts:
        plan = attempt.request_payload()
        if plan.get("schema_version") != "konecta.meta_publish_plan.v1":
            continue
        changed = False
        ad_sets = plan.get("ad_sets") if isinstance(plan.get("ad_sets"), list) else []
        for ad_set in ad_sets:
            if not isinstance(ad_set, dict):
                continue
            ads = ad_set.get("ads") if isinstance(ad_set.get("ads"), list) else []
            for ad in ads:
                if not isinstance(ad, dict):
                    continue
                creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
                creative_asset_id = _clean(creative.get("creative_asset_id"))
                asset_file_path = _clean(creative.get("asset_file_path"))
                if creative_asset_id != asset.id and (not asset_file_path or asset_file_path != asset.file_path):
                    continue
                if asset.meta_creative_id and not _clean(creative.get("meta_creative_id")):
                    creative["meta_creative_id"] = asset.meta_creative_id
                    changed = True
                if asset.image_hash and not _clean(creative.get("image_hash")):
                    creative["image_hash"] = asset.image_hash
                    changed = True
                if asset.video_id and not _clean(creative.get("video_id")):
                    creative["video_id"] = asset.video_id
                    changed = True
                if changed:
                    ad["creative"] = creative
        if changed:
            remaining_provider_blockers = [
                blocker
                for blocker in _provider_creative_blockers(plan)
                if blocker not in set(plan.get("required_before_live_publish", []))
            ]
            if not remaining_provider_blockers and attempt.status == "blocked" and not _plan_blockers(plan):
                status = "staged"
                error = ""
            else:
                status = attempt.status
                error = attempt.error
            PlatformMetaPublishAttempt.update_execution(
                attempt.id,
                status=status,
                request_payload=plan,
                error=error,
            )
            linked.append(attempt.id)
    return linked


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


def _money_to_whole_usd(value: Any) -> int:
    """Return a non-negative whole-dollar budget value."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0
    if amount <= 0:
        return 0
    return math.ceil(amount)


def _require(condition: bool, field: str, blocked: list[str]) -> None:
    if not condition:
        blocked.append(field)


def _whatsapp_referral_source_maps_to_funnel(*, funnel_id: str, source_id: str) -> bool:
    """Return whether one Click-to-WhatsApp source id is configured for a funnel."""
    clean_funnel_id = slugify_funnel_id(funnel_id) if _clean(funnel_id) else ""
    clean_source_id = _clean(source_id)
    if not clean_funnel_id or not clean_source_id:
        return False
    return any(
        funnel.id == clean_funnel_id
        for funnel in list_funnels_by_whatsapp_referral_source_id(clean_source_id)
    )


def _client_lead_source_blockers(source_id: str) -> list[str]:
    """Return blockers that stop Meta lead forms from feeding Client Lead Delivery."""
    clean_source_id = _clean(source_id)
    if not clean_source_id:
        return ["destination.client_lead_source_id"]
    source = ClientLeadSource.get_by_id(clean_source_id)
    if source is None:
        return ["destination.client_lead_source_id.not_found"]
    blocked: list[str] = []
    if not source.enabled:
        blocked.append("destination.client_lead_source_id.enabled")
    if not _clean(source.sheet_url):
        blocked.append("destination.client_lead_source_id.sheet_url")
    if not source.sheet_gid and not source.sheet_tab_name:
        blocked.append("destination.client_lead_source_id.sheet_gid_or_tab_name")
    if not _clean(source.recipient_phone):
        blocked.append("destination.client_lead_source_id.recipient_phone")
    if not _clean(source.normalized_recipient_phone):
        blocked.append("destination.client_lead_source_id.normalized_recipient_phone")
    if not _clean(source.template_name):
        blocked.append("destination.client_lead_source_id.template_name")
    return blocked


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
        _require(bool(_clean(plan.get("funnel_id"))), "funnel_id", blocked)
        whatsapp_referral_source_id = _clean(destination.get("whatsapp_referral_source_id"))
        if whatsapp_referral_source_id and not _whatsapp_referral_source_maps_to_funnel(
            funnel_id=_clean(plan.get("funnel_id")),
            source_id=whatsapp_referral_source_id,
        ):
            blocked.append("destination.whatsapp_referral_source_id.funnel_mapping")
    elif destination_type == "instant_form":
        _require(bool(_clean(destination.get("page_id"))), "destination.page_id", blocked)
        _require(bool(_clean(destination.get("lead_form_id"))), "destination.lead_form_id", blocked)
        blocked.extend(_client_lead_source_blockers(_clean(destination.get("client_lead_source_id"))))
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


def _plan_budget_summary(
    plan: dict[str, Any],
    *,
    max_daily_budget_usd: int,
    max_lifetime_budget_usd: int,
    max_estimated_monthly_budget_usd: int,
) -> MetaPublishBudgetSummary:
    """Return summed budget values for one staged Meta plan."""
    ad_sets = plan.get("ad_sets") if isinstance(plan.get("ad_sets"), list) else []
    currency = _clean(plan.get("budget_currency")) or "USD"
    total_daily = 0
    total_lifetime = 0
    reviewed_sets: list[dict[str, Any]] = []
    for ad_set in ad_sets:
        if not isinstance(ad_set, dict):
            continue
        daily = _money_to_whole_usd(ad_set.get("budget_daily_usd"))
        lifetime = _money_to_whole_usd(ad_set.get("budget_total_usd"))
        total_daily += daily
        total_lifetime += lifetime
        reviewed_sets.append(
            {
                "name": _clean(ad_set.get("name")),
                "budget_daily_usd": daily,
                "budget_total_usd": lifetime,
                "status": _clean(ad_set.get("status")) or "PAUSED",
            }
        )
    return MetaPublishBudgetSummary(
        currency=currency,
        total_daily_budget_usd=total_daily,
        total_lifetime_budget_usd=total_lifetime,
        estimated_monthly_budget_usd=(total_daily * 30) + total_lifetime,
        ad_sets=reviewed_sets,
        max_daily_budget_usd=max_daily_budget_usd,
        max_lifetime_budget_usd=max_lifetime_budget_usd,
        max_estimated_monthly_budget_usd=max_estimated_monthly_budget_usd,
    )


def _status_blockers(plan: dict[str, Any]) -> list[str]:
    """Return non-PAUSED creation statuses that would risk spend after approval."""
    blocked: list[str] = []
    campaign = plan.get("campaign") if isinstance(plan.get("campaign"), dict) else {}
    if (_clean(campaign.get("create_status")) or "PAUSED") != "PAUSED":
        blocked.append("campaign.create_status=PAUSED")
    ad_sets = plan.get("ad_sets") if isinstance(plan.get("ad_sets"), list) else []
    for ad_set_index, ad_set in enumerate(ad_sets, start=1):
        if not isinstance(ad_set, dict):
            continue
        if (_clean(ad_set.get("status")) or "PAUSED") != "PAUSED":
            blocked.append(f"ad_sets[{ad_set_index}].status=PAUSED")
        ads = ad_set.get("ads") if isinstance(ad_set.get("ads"), list) else []
        for ad_index, ad in enumerate(ads, start=1):
            if isinstance(ad, dict) and (_clean(ad.get("status")) or "PAUSED") != "PAUSED":
                blocked.append(f"ad_sets[{ad_set_index}].ads[{ad_index}].status=PAUSED")
    return blocked


def _provider_creative_blockers(plan: dict[str, Any]) -> list[str]:
    """Return creatives that still need a Meta creative ID, image hash, or video ID."""
    blocked: list[str] = []
    ad_sets = plan.get("ad_sets") if isinstance(plan.get("ad_sets"), list) else []
    for ad_set_index, ad_set in enumerate(ad_sets, start=1):
        if not isinstance(ad_set, dict):
            continue
        ads = ad_set.get("ads") if isinstance(ad_set.get("ads"), list) else []
        for ad_index, ad in enumerate(ads, start=1):
            if not isinstance(ad, dict):
                continue
            creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
            has_provider_asset = any(
                _clean(creative.get(field))
                for field in ["meta_creative_id", "image_hash", "video_id"]
            )
            if not has_provider_asset:
                blocked.append(f"ad_sets[{ad_set_index}].ads[{ad_index}].creative.meta_asset")
    return blocked


def _budget_blockers(summary: MetaPublishBudgetSummary) -> list[str]:
    """Return budget policy violations."""
    blocked: list[str] = []
    if summary.currency != "USD":
        blocked.append("budget_currency=USD")
    if summary.total_daily_budget_usd > summary.max_daily_budget_usd:
        blocked.append("budget.daily_cap")
    if summary.total_lifetime_budget_usd > summary.max_lifetime_budget_usd:
        blocked.append("budget.lifetime_cap")
    if summary.estimated_monthly_budget_usd > summary.max_estimated_monthly_budget_usd:
        blocked.append("budget.estimated_monthly_cap")
    return blocked


def _latest_inventory_snapshot(plan: dict[str, Any]) -> PlatformMetaInventorySnapshot | None:
    """Return the most recent inventory snapshot for the plan's ad account."""
    ad_account_id = _clean(plan.get("ad_account_id"))
    for snapshot in PlatformMetaInventorySnapshot.list_recent(limit=50):
        if ad_account_id:
            if snapshot.ad_account_id == ad_account_id:
                return snapshot
            continue
        return snapshot
    return None


def _payload_contains_id(items: Any, object_id: str) -> bool:
    """Return whether a provider inventory list contains an ID."""
    clean_id = _clean(object_id)
    if not clean_id or not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and _clean(item.get("id")) == clean_id for item in items)


def _inventory_asset_blockers(plan: dict[str, Any], snapshot: PlatformMetaInventorySnapshot | None) -> list[str]:
    """Return inventory gaps for IDs referenced by a staged plan."""
    if snapshot is None or snapshot.status != "ready":
        return []
    inventory = snapshot.inventory()
    blocked: list[str] = []
    ad_account_id = _clean(plan.get("ad_account_id"))
    if ad_account_id and not (
        _clean(inventory.get("selected_ad_account", {}).get("id")) == ad_account_id
        or _payload_contains_id(inventory.get("ad_accounts"), ad_account_id)
    ):
        blocked.append("meta_inventory.ad_account_id")
    destination = plan.get("destination") if isinstance(plan.get("destination"), dict) else {}
    page_id = _clean(destination.get("page_id"))
    if page_id and not _payload_contains_id(inventory.get("pages"), page_id):
        blocked.append("meta_inventory.page_id")
    lead_form_id = _clean(destination.get("lead_form_id"))
    if lead_form_id and not _payload_contains_id(inventory.get("lead_forms"), lead_form_id):
        blocked.append("meta_inventory.lead_form_id")
    whatsapp_phone_number_id = _clean(destination.get("whatsapp_phone_number_id"))
    if whatsapp_phone_number_id and not _payload_contains_id(inventory.get("whatsapp_phone_numbers"), whatsapp_phone_number_id):
        blocked.append("meta_inventory.whatsapp_phone_number_id")
    return blocked


def _has_approval_gate_event(attempt_id: str) -> bool:
    """Return whether the audited approval gate approved this attempt."""
    events = PlatformEvent.list_recent(target_type="meta_publish_attempt", target_id=attempt_id, limit=20)
    for event in events:
        if event.event_type != "meta_publish.approval_checked":
            continue
        payload = event.payload_dict()
        if (
            payload.get("approved") is True
            and payload.get("approval_status") == "approved"
            and not payload.get("blocked_reasons")
        ):
            return True
    return False


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
    call_to_action = _clean(creative.get("call_to_action"))
    if not call_to_action:
        call_to_action = "WHATSAPP_MESSAGE" if destination_type == "whatsapp" else "LEARN_MORE"
    destination_url = (
        _clean(creative.get("destination_url"))
        or _clean(destination.get("landing_page_url"))
        or ("https://api.whatsapp.com/send" if destination_type == "whatsapp" else "")
    )
    cta_value: dict[str, Any] = {}
    if destination_url:
        cta_value["link"] = destination_url
    if destination_type == "whatsapp":
        cta_value["whatsapp_phone_number_id"] = _clean(destination.get("whatsapp_phone_number_id"))
    if destination_type == "instant_form":
        cta_value["lead_gen_form_id"] = _clean(destination.get("lead_form_id"))

    story_spec: dict[str, Any] = {"page_id": page_id}
    if _clean(creative.get("video_id")):
        story_spec["video_data"] = {
            "video_id": _clean(creative.get("video_id")),
            "message": _clean(creative.get("primary_text")),
            "title": _clean(creative.get("headline")),
            "call_to_action": {"type": call_to_action, "value": cta_value},
        }
        if _clean(creative.get("description")):
            story_spec["video_data"]["link_description"] = _clean(creative.get("description"))
    else:
        link_data: dict[str, Any] = {
            "message": _clean(creative.get("primary_text")),
            "name": _clean(creative.get("headline")),
            "call_to_action": {"type": call_to_action, "value": cta_value},
        }
        if destination_url:
            link_data["link"] = destination_url
        if _clean(creative.get("description")):
            link_data["description"] = _clean(creative.get("description"))
        if _clean(creative.get("image_hash")):
            link_data["image_hash"] = _clean(creative.get("image_hash"))
        story_spec["link_data"] = link_data

    params: dict[str, Any] = {
        "name": name,
        "object_story_spec": story_spec,
    }
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
        for placement_field in [
            "facebook_positions",
            "instagram_positions",
            "messenger_positions",
            "audience_network_positions",
            "device_platforms",
        ]:
            if isinstance(ad_set.get(placement_field), list) and ad_set[placement_field]:
                params[placement_field] = ad_set[placement_field]
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


def _created_whatsapp_ad_source_ids(plan: dict[str, Any], results: list[MetaPublishOperationResult]) -> list[str]:
    """Return source ids that should route Click-to-WhatsApp leads to this funnel."""
    destination = plan.get("destination") if isinstance(plan.get("destination"), dict) else {}
    if (_clean(destination.get("destination_type")) or "whatsapp") != "whatsapp":
        return []
    source_ids: list[str] = []
    existing_source_id = _clean(destination.get("whatsapp_referral_source_id"))
    if existing_source_id:
        source_ids.append(existing_source_id)
    for result in results:
        if result.object_type == "ad" and result.status in {"executed", "skipped"} and result.provider_id:
            source_ids.append(result.provider_id)
    return list(dict.fromkeys(source_ids))


def _map_whatsapp_ad_source_ids_to_funnel(
    plan: dict[str, Any],
    results: list[MetaPublishOperationResult],
    *,
    source: str,
    actor: str,
    attempt_id: str,
) -> tuple[list[str], list[str]]:
    """Persist returned Meta ad ids as funnel referral sources after live publish."""
    source_ids = _created_whatsapp_ad_source_ids(plan, results)
    if not source_ids:
        return [], []

    clean_funnel_id = _clean(plan.get("funnel_id"))
    funnel = get_funnel(clean_funnel_id) if clean_funnel_id else None
    if funnel is None:
        return [], ["funnel_id"]

    existing = list(funnel.whatsapp_referral_source_ids)
    additions = [source_id for source_id in source_ids if source_id not in existing]
    if not additions:
        return [], []

    try:
        payload = funnel.model_dump(mode="json")
        payload["whatsapp_referral_source_ids"] = [*existing, *additions]
        saved = upsert_funnel(FunnelDefinition.model_validate(payload))
    except Exception as error:
        return [], [f"whatsapp_referral_source_ids.persist: {str(error)[:500]}"]

    PlatformEvent.add(
        event_type="meta_publish.lead_routing_mapped",
        lifecycle_stage="meta_publish",
        target_type="funnel",
        target_id=saved.id,
        funnel_id=saved.id,
        source=source,
        actor=actor,
        summary=f"Mapped Meta ad ids to funnel {saved.id}.",
        payload={
            "attempt_id": attempt_id,
            "mapped_source_ids": additions,
            "whatsapp_referral_source_ids": saved.whatsapp_referral_source_ids,
        },
    )
    return additions, []


def upload_meta_creative_asset(
    *,
    asset_id: str,
    ad_account_id: str = "",
    live_writes_requested: bool = False,
    actor: str = "agent",
    source: str = "codex_agent_tool",
    graph_upload: GraphUploader | None = None,
) -> tuple[PlatformCreativeAsset, MetaCreativeAssetUploadResult]:
    """Upload one staged asset to Meta media storage and persist provider refs."""
    asset = PlatformCreativeAsset.get_by_id(asset_id)
    if asset is None:
        raise MetaAdsPublishError(f"Creative asset not found: {asset_id}")

    provider_asset_type = _provider_asset_type(asset)
    if asset.image_hash or asset.video_id or asset.meta_creative_id:
        result = MetaCreativeAssetUploadResult(
            asset_id=asset.id,
            campaign_id=asset.campaign_id,
            status="already_uploaded",
            ad_account_id=ad_account_id,
            provider_asset_type=provider_asset_type,
            image_hash=asset.image_hash,
            video_id=asset.video_id,
            meta_creative_id=asset.meta_creative_id,
            linked_publish_attempts=_link_uploaded_asset_to_publish_attempts(asset),
            response=asset.meta_upload_response(),
        )
        _emit_creative_upload_event(asset, result, source=source, actor=actor)
        return asset, result

    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    live_writes_enabled = _env_truthy("META_MARKETING_LIVE_WRITES_ENABLED")
    clean_ad_account_id = _clean(ad_account_id) or _clean(os.getenv("META_AD_ACCOUNT_ID"))
    file_path = _resolve_creative_file(asset.file_path)
    blocked: list[str] = []
    if not live_writes_requested:
        blocked.append("live_writes_requested=true")
    if not live_writes_enabled:
        blocked.append("META_MARKETING_LIVE_WRITES_ENABLED")
    if not access_token and graph_upload is None:
        blocked.append("META_MARKETING_ACCESS_TOKEN")
    if not api_version:
        blocked.append("META_MARKETING_API_VERSION")
    if not clean_ad_account_id:
        blocked.append("ad_account_id")
    if provider_asset_type not in {"image", "video"}:
        blocked.append("asset_type=image_or_video")
    if file_path is None:
        blocked.append("asset.file_path")
    elif not file_path.exists():
        blocked.append("asset.file_path.exists")
    else:
        mime_type = mimetypes.guess_type(file_path.name)[0] or ""
        if provider_asset_type == "image" and not mime_type.startswith("image/"):
            blocked.append("asset.file_type=image")
        if provider_asset_type == "video" and not mime_type.startswith("video/"):
            blocked.append("asset.file_type=video")

    if blocked:
        result = MetaCreativeAssetUploadResult(
            asset_id=asset.id,
            campaign_id=asset.campaign_id,
            status="blocked",
            live_writes_requested=live_writes_requested,
            ad_account_id=clean_ad_account_id,
            api_version=api_version,
            provider_asset_type=provider_asset_type,
            blocked_reasons=list(dict.fromkeys(blocked)),
        )
        updated = PlatformCreativeAsset.update_meta_refs(
            asset.id,
            status="upload_blocked",
            failure_reason=", ".join(result.blocked_reasons),
        )
        if updated is not None:
            asset = updated
        _emit_creative_upload_event(asset, result, source=source, actor=actor)
        return asset, result

    uploader = graph_upload or _default_graph_uploader(api_version=api_version, access_token=access_token)
    path = f"/{clean_ad_account_id}/adimages" if provider_asset_type == "image" else f"/{clean_ad_account_id}/advideos"
    file_field = "filename" if provider_asset_type == "image" else "source"
    params = {"name": file_path.name} if provider_asset_type == "image" else {"title": file_path.stem or file_path.name}
    try:
        response = _sanitize_provider_payload(uploader(path, file_path, file_field, params))
        image_hash = _extract_uploaded_image_hash(response) if provider_asset_type == "image" else ""
        video_id = _extract_uploaded_video_id(response) if provider_asset_type == "video" else ""
        if provider_asset_type == "image" and not image_hash:
            raise MetaAdsPublishError("Meta adimages response did not include an image hash")
        if provider_asset_type == "video" and not video_id:
            raise MetaAdsPublishError("Meta advideos response did not include a video id")
        updated = PlatformCreativeAsset.update_meta_refs(
            asset.id,
            status="uploaded_to_meta",
            image_hash=image_hash,
            video_id=video_id,
            meta_upload_response=response,
            failure_reason="",
        )
        if updated is None:
            raise MetaAdsPublishError(f"Creative asset disappeared during upload: {asset.id}")
        asset = updated
        linked_attempts = _link_uploaded_asset_to_publish_attempts(asset)
        result = MetaCreativeAssetUploadResult(
            asset_id=asset.id,
            campaign_id=asset.campaign_id,
            status="uploaded",
            live_writes_requested=live_writes_requested,
            live_write_executed=True,
            ad_account_id=clean_ad_account_id,
            api_version=api_version,
            provider_asset_type=provider_asset_type,
            image_hash=asset.image_hash,
            video_id=asset.video_id,
            linked_publish_attempts=linked_attempts,
            response=response,
        )
    except Exception as error:
        error_text = _redact_graph_error(error)
        result = MetaCreativeAssetUploadResult(
            asset_id=asset.id,
            campaign_id=asset.campaign_id,
            status="failed",
            live_writes_requested=live_writes_requested,
            ad_account_id=clean_ad_account_id,
            api_version=api_version,
            provider_asset_type=provider_asset_type,
            blocked_reasons=[error_text[:12000]],
        )
        updated = PlatformCreativeAsset.update_meta_refs(
            asset.id,
            status="upload_failed",
            failure_reason=error_text[:4000],
        )
        if updated is not None:
            asset = updated
    _emit_creative_upload_event(asset, result, source=source, actor=actor)
    return asset, result


def _emit_creative_upload_event(
    asset: PlatformCreativeAsset,
    result: MetaCreativeAssetUploadResult,
    *,
    source: str,
    actor: str,
) -> None:
    """Persist one observability event for Meta creative uploads."""
    event_type = "meta_creative_asset.uploaded" if result.status == "uploaded" else "meta_creative_asset.upload_checked"
    PlatformEvent.add(
        event_type=event_type,
        lifecycle_stage="meta_publish",
        target_type="creative_asset",
        target_id=asset.id,
        source=source,
        actor=actor,
        summary=f"Checked Meta creative upload for {asset.id}.",
        payload={
            "campaign_id": asset.campaign_id,
            "status": result.status,
            "live_write_executed": result.live_write_executed,
            "ad_account_id": result.ad_account_id,
            "provider_asset_type": result.provider_asset_type,
            "image_hash": result.image_hash,
            "video_id": result.video_id,
            "blocked_reasons": result.blocked_reasons,
            "linked_publish_attempts": result.linked_publish_attempts,
        },
    )


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
    approval_gate_present = _has_approval_gate_event(attempt.id)
    warnings: list[str] = []
    if not api_version:
        warnings.append("META_MARKETING_API_VERSION is not configured.")
    if not token_present:
        warnings.append("META_MARKETING_ACCESS_TOKEN is not configured; dry-run preflight can continue, live publish cannot.")
    if attempt.approval_status not in {"approved", "pending", "needs_preflight"}:
        warnings.append(f"Current approval_status is {attempt.approval_status}.")

    if live_writes_requested:
        blocked.extend(_provider_creative_blockers(plan))
        if not live_writes_enabled:
            blocked.append("META_MARKETING_LIVE_WRITES_ENABLED")
        if not token_present:
            blocked.append("META_MARKETING_ACCESS_TOKEN")
        if not api_version:
            blocked.append("META_MARKETING_API_VERSION")
        if attempt.approval_status != "approved":
            blocked.append("approval_status=approved")
        if plan.get("live_writes_allowed") is not True:
            blocked.append("plan.live_writes_allowed=true")
        if not approval_gate_present:
            blocked.append("meta_publish.approval_gate")

    live_write = live_writes_requested and not blocked and live_writes_enabled and token_present and bool(api_version)
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
        ready_for_live_publish=(
            ready
            and live_writes_enabled
            and token_present
            and bool(api_version)
            and attempt.approval_status == "approved"
            and plan.get("live_writes_allowed") is True
            and approval_gate_present
        ),
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


def _operation_result_from_existing(operation: MetaPublishOperation, provider_id: str) -> MetaPublishOperationResult:
    """Return a skipped result for an operation already present in execution state."""
    return MetaPublishOperationResult(
        step=operation.step,
        local_ref=operation.local_ref,
        object_type=operation.object_type,
        path=operation.path,
        status="skipped",
        provider_id=provider_id,
        request_params=operation.params,
        response={"id": provider_id, "already_executed": True},
    )


def _resolve_operation_params(params: dict[str, Any], provider_ids: dict[str, str]) -> dict[str, Any]:
    """Replace local reference placeholders with provider object IDs."""
    def resolve(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("{{") and value.endswith(".id}}"):
            ref = value.removeprefix("{{").removesuffix(".id}}")
            return provider_ids.get(ref, value)
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    return resolve(params)


def _execution_state_from_response(attempt: PlatformMetaPublishAttempt) -> dict[str, Any]:
    """Return the current execution state from the latest attempt response."""
    payload = attempt.response_payload()
    if payload.get("schema_version") == "konecta.meta_publish_execution.v1":
        return payload
    request_payload = attempt.request_payload()
    state = request_payload.get("live_execution_state") if isinstance(request_payload, dict) else {}
    return state if isinstance(state, dict) else {}


def _provider_ids_from_state(state: dict[str, Any]) -> dict[str, str]:
    """Return local_ref -> provider_id from previous execution results."""
    results = state.get("operation_results") if isinstance(state.get("operation_results"), list) else []
    provider_ids: dict[str, str] = {}
    for result in results:
        if not isinstance(result, dict):
            continue
        local_ref = _clean(result.get("local_ref"))
        provider_id = _clean(result.get("provider_id"))
        if local_ref and provider_id and result.get("status") in {"executed", "skipped"}:
            provider_ids[local_ref] = provider_id
    return provider_ids


def _execution_preflight_blockers(
    *,
    attempt: PlatformMetaPublishAttempt,
    plan: dict[str, Any],
    live_writes_requested: bool,
    live_writes_enabled: bool,
    token_present: bool,
    api_version: str,
) -> list[str]:
    """Return blockers that must pass before live Meta writes."""
    blocked = list(dict.fromkeys([*_plan_blockers(plan), *plan.get("required_before_live_publish", [])]))
    blocked.extend(_provider_creative_blockers(plan))
    if not live_writes_requested:
        blocked.append("live_writes_requested=true")
    if not live_writes_enabled:
        blocked.append("META_MARKETING_LIVE_WRITES_ENABLED")
    if not token_present:
        blocked.append("META_MARKETING_ACCESS_TOKEN")
    if not api_version:
        blocked.append("META_MARKETING_API_VERSION")
    if attempt.approval_status != "approved":
        blocked.append("approval_status=approved")
    if plan.get("live_writes_allowed") is not True:
        blocked.append("plan.live_writes_allowed=true")
    if not _has_approval_gate_event(attempt.id):
        blocked.append("meta_publish.approval_gate")
    return list(dict.fromkeys(blocked))


def execute_meta_publish_attempt(
    *,
    attempt_id: str,
    live_writes_requested: bool = False,
    actor: str = "agent",
    source: str = "codex_agent_tool",
    graph_post: GraphPoster | None = None,
) -> tuple[PlatformMetaPublishAttempt, MetaPublishExecutionResult]:
    """Execute an approved Meta publish plan with idempotent local retries."""
    attempt = PlatformMetaPublishAttempt.get_by_id(attempt_id)
    if attempt is None:
        raise MetaAdsPublishError(f"Meta publish attempt not found: {attempt_id}")

    plan = attempt.request_payload()
    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    live_writes_enabled = _env_truthy("META_MARKETING_LIVE_WRITES_ENABLED")
    blocked = _execution_preflight_blockers(
        attempt=attempt,
        plan=plan,
        live_writes_requested=live_writes_requested,
        live_writes_enabled=live_writes_enabled,
        token_present=bool(access_token) or graph_post is not None,
        api_version=api_version,
    )
    operations = build_meta_publish_operations(plan, live_write=True) if not _plan_blockers(plan) else []
    if not operations:
        blocked.append("operations")

    state = _execution_state_from_response(attempt)
    provider_ids = _provider_ids_from_state(state)
    previous_results = [
        MetaPublishOperationResult.model_validate(result)
        for result in state.get("operation_results", [])
        if isinstance(result, dict)
    ]
    if blocked:
        result = MetaPublishExecutionResult(
            attempt_id=attempt.id,
            campaign_id=attempt.campaign_id,
            status="blocked",
            live_writes_requested=live_writes_requested,
            api_version=api_version,
            blocked_reasons=list(dict.fromkeys(blocked)),
            operation_results=previous_results,
        )
        updated = PlatformMetaPublishAttempt.update_execution(
            attempt.id,
            status="blocked",
            response_payload=result.model_dump(mode="json"),
            error=", ".join(result.blocked_reasons),
        )
        if updated is None:
            raise MetaAdsPublishError(f"Meta publish attempt disappeared during execution: {attempt.id}")
        _emit_execution_event(updated, result, source=source, actor=actor, plan=plan)
        return updated, result

    poster = graph_post or _default_graph_poster(api_version=api_version, access_token=access_token)
    operation_results: list[MetaPublishOperationResult] = []
    for operation in operations:
        existing_provider_id = provider_ids.get(operation.local_ref)
        if existing_provider_id:
            operation_results.append(_operation_result_from_existing(operation, existing_provider_id))
            continue
        missing_dependencies = [ref for ref in operation.depends_on if not provider_ids.get(ref)]
        if missing_dependencies:
            operation_results.append(
                MetaPublishOperationResult(
                    step=operation.step,
                    local_ref=operation.local_ref,
                    object_type=operation.object_type,
                    path=operation.path,
                    status="failed",
                    request_params=operation.params,
                    error=f"Missing provider IDs for dependencies: {', '.join(missing_dependencies)}",
                )
            )
            break
        request_params = _resolve_operation_params(operation.params, provider_ids)
        try:
            response = _sanitize_provider_payload(poster(operation.path, request_params))
            provider_id = _clean(response.get("id"))
            if not provider_id:
                raise MetaAdsPublishError(f"Meta response for {operation.local_ref} did not include an id")
            provider_ids[operation.local_ref] = provider_id
            operation_results.append(
                MetaPublishOperationResult(
                    step=operation.step,
                    local_ref=operation.local_ref,
                    object_type=operation.object_type,
                    path=operation.path,
                    status="executed",
                    provider_id=provider_id,
                    request_params=request_params,
                    response=response,
                )
            )
        except Exception as error:
            error_text = _redact_graph_error(error)
            operation_results.append(
                MetaPublishOperationResult(
                    step=operation.step,
                    local_ref=operation.local_ref,
                    object_type=operation.object_type,
                    path=operation.path,
                    status="failed",
                    request_params=request_params,
                    error=error_text[:12000],
                )
            )
            break

    failed = any(item.status == "failed" for item in operation_results)
    routing_source_ids: list[str] = []
    routing_blockers: list[str] = []
    if not failed:
        routing_source_ids, routing_blockers = _map_whatsapp_ad_source_ids_to_funnel(
            plan,
            operation_results,
            source=source,
            actor=actor,
            attempt_id=attempt.id,
        )
    executed = any(item.status == "executed" for item in operation_results)
    all_skipped = operation_results and all(item.status == "skipped" for item in operation_results)
    status: Literal["blocked", "submitted", "partial_failed", "already_submitted"]
    if failed or routing_blockers:
        status = "partial_failed"
    elif all_skipped:
        status = "already_submitted"
    else:
        status = "submitted"
    result = MetaPublishExecutionResult(
        attempt_id=attempt.id,
        campaign_id=attempt.campaign_id,
        status=status,
        live_writes_requested=live_writes_requested,
        live_write_executed=executed,
        api_version=api_version,
        warnings=[f"lead_routing.{item}" for item in routing_blockers],
        operation_results=operation_results,
    )
    updated_plan = dict(plan)
    if routing_source_ids or routing_blockers:
        lead_routing = updated_plan.get("lead_routing") if isinstance(updated_plan.get("lead_routing"), dict) else {}
        lead_routing = dict(lead_routing)
        lead_routing["mapped_source_ids"] = list(dict.fromkeys([*lead_routing.get("mapped_source_ids", []), *routing_source_ids]))
        lead_routing["routing_blockers"] = routing_blockers
        updated_plan["lead_routing"] = lead_routing
    updated_plan["live_execution_state"] = result.model_dump(mode="json")
    updated = PlatformMetaPublishAttempt.update_execution(
        attempt.id,
        status=status,
        request_payload=updated_plan,
        response_payload=result.model_dump(mode="json"),
        error=", ".join([*[item.error for item in operation_results if item.error], *routing_blockers]),
    )
    if updated is None:
        raise MetaAdsPublishError(f"Meta publish attempt disappeared during execution: {attempt.id}")
    _emit_execution_event(updated, result, source=source, actor=actor, plan=plan)
    return updated, result


def _emit_execution_event(
    attempt: PlatformMetaPublishAttempt,
    result: MetaPublishExecutionResult,
    *,
    source: str,
    actor: str,
    plan: dict[str, Any],
) -> None:
    """Persist one observability event for Meta publish execution."""
    PlatformEvent.add(
        event_type="meta_publish.execution_checked",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=attempt.id,
        funnel_id=_clean(plan.get("funnel_id")),
        source=source,
        actor=actor,
        summary=f"Checked Meta publish execution for {attempt.id}.",
        payload={
            "campaign_id": attempt.campaign_id,
            "status": result.status,
            "live_write_executed": result.live_write_executed,
            "blocked_reasons": result.blocked_reasons,
            "operation_results": [
                {
                    "local_ref": item.local_ref,
                    "object_type": item.object_type,
                    "status": item.status,
                    "provider_id": item.provider_id,
                    "error": item.error,
                }
                for item in result.operation_results
            ],
        },
    )


def approve_meta_publish_attempt(
    *,
    attempt_id: str,
    approved_by: str,
    approval_note: str = "",
    approve_live_writes: bool = False,
    require_inventory_ready: bool = True,
    max_daily_budget_usd: int = 50,
    max_lifetime_budget_usd: int = 1500,
    max_estimated_monthly_budget_usd: int = 1500,
    actor: str = "operator",
    source: str = "codex_agent_tool",
) -> tuple[PlatformMetaPublishAttempt, MetaPublishApprovalResult]:
    """Apply the explicit approval and budget gate for a staged Meta plan."""
    attempt = PlatformMetaPublishAttempt.get_by_id(attempt_id)
    if attempt is None:
        raise MetaAdsPublishError(f"Meta publish attempt not found: {attempt_id}")

    clean_approved_by = _clean(approved_by)
    if not clean_approved_by:
        raise MetaAdsPublishError("approved_by is required for Meta publish approval")

    plan = attempt.request_payload()
    budget = _plan_budget_summary(
        plan,
        max_daily_budget_usd=max(1, int(max_daily_budget_usd or 50)),
        max_lifetime_budget_usd=max(0, int(max_lifetime_budget_usd or 0)),
        max_estimated_monthly_budget_usd=max(1, int(max_estimated_monthly_budget_usd or 1500)),
    )
    blocked = list(
        dict.fromkeys(
            [
                *_plan_blockers(plan),
                *plan.get("required_before_live_publish", []),
                *_status_blockers(plan),
                *_provider_creative_blockers(plan),
                *_budget_blockers(budget),
            ]
        )
    )
    warnings: list[str] = []
    if not attempt.idempotency_key:
        blocked.append("idempotency_key")
    inventory_snapshot = _latest_inventory_snapshot(plan)
    if approve_live_writes and not require_inventory_ready:
        blocked.append("require_inventory_ready=true")
    if require_inventory_ready:
        if inventory_snapshot is None:
            blocked.append("meta_inventory.ready")
        elif inventory_snapshot.status != "ready":
            blocked.append(f"meta_inventory.status={inventory_snapshot.status}")
        else:
            blocked.extend(_inventory_asset_blockers(plan, inventory_snapshot))
    elif inventory_snapshot is None:
        warnings.append("No Meta inventory snapshot was available for this plan.")

    live_writes_allowed = bool(approve_live_writes and not blocked)
    updated_plan = dict(plan)
    updated_plan["live_writes_allowed"] = live_writes_allowed
    updated_plan["publish_mode"] = "approved_live_candidate" if live_writes_allowed else "staged_only"
    updated_plan["approval_policy"] = {
        "approved_by": clean_approved_by,
        "approval_note": approval_note,
        "approve_live_writes": approve_live_writes,
        "require_inventory_ready": require_inventory_ready,
        "max_daily_budget_usd": budget.max_daily_budget_usd,
        "max_lifetime_budget_usd": budget.max_lifetime_budget_usd,
        "max_estimated_monthly_budget_usd": budget.max_estimated_monthly_budget_usd,
    }
    approval_status = "approved" if live_writes_allowed else "needs_approval"
    result = MetaPublishApprovalResult(
        attempt_id=attempt.id,
        campaign_id=attempt.campaign_id,
        approved=live_writes_allowed,
        approval_status=approval_status,
        approved_by=clean_approved_by,
        approval_note=approval_note,
        live_writes_allowed=live_writes_allowed,
        budget=budget,
        inventory_snapshot_id=inventory_snapshot.id if inventory_snapshot else "",
        inventory_status=inventory_snapshot.status if inventory_snapshot else "",
        blocked_reasons=list(dict.fromkeys(blocked)),
        warnings=warnings,
    )
    updated = PlatformMetaPublishAttempt.update_execution(
        attempt.id,
        status="approved" if live_writes_allowed else "blocked",
        approval_status=approval_status,
        request_payload=updated_plan,
        response_payload=result.model_dump(mode="json"),
        error=", ".join(result.blocked_reasons),
    )
    if updated is None:
        raise MetaAdsPublishError(f"Meta publish attempt disappeared during approval: {attempt.id}")
    PlatformEvent.add(
        event_type="meta_publish.approval_checked",
        lifecycle_stage="meta_publish",
        target_type="meta_publish_attempt",
        target_id=updated.id,
        funnel_id=_clean(plan.get("funnel_id")),
        source=source,
        actor=actor,
        summary=f"Checked Meta publish approval gate for {updated.id}.",
        payload={
            "campaign_id": updated.campaign_id,
            "approved": result.approved,
            "approval_status": result.approval_status,
            "approved_by": result.approved_by,
            "blocked_reasons": result.blocked_reasons,
            "budget": result.budget.model_dump(mode="json"),
            "inventory_snapshot_id": result.inventory_snapshot_id,
        },
    )
    return updated, result
