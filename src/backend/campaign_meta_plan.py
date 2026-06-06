"""Deterministic Campaign > Ad Set > Ad graph helpers for owned Ads."""

from __future__ import annotations

import copy
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


META_PLAN_GRAPH_SCHEMA_VERSION = "konecta.meta_plan_graph.v1"
META_PLAN_GRAPH_KEY = "meta_plan_graph"

MetaPlanNodeType = Literal["campaign", "ad_set", "ad"]

STRATEGY_SHAPES: dict[str, tuple[int, int, int]] = {
    "1x1x3": (1, 1, 3),
    "1x3x3": (1, 3, 3),
    "3x3x3": (3, 3, 3),
}

DESTINATION_TYPES = {"form", "website", "whatsapp"}


def _clean_text(value: Any, *, max_length: int = 500) -> str:
    return " ".join(str(value or "").split()).strip()[:max_length]


def _clean_multiline(value: Any, *, max_length: int = 4000) -> str:
    return str(value or "").strip()[:max_length]


def _clean_status(value: Any, *, default: str = "PAUSED") -> str:
    clean = _clean_text(value, max_length=40).upper()
    if clean in {"ACTIVE", "PAUSED", "DELETED", "ARCHIVED"}:
        return clean
    if clean == "DRAFT":
        return "PAUSED"
    return default


def _clean_id(value: Any, prefix: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", _clean_text(value, max_length=80)).strip("-")
    return clean or f"{prefix}_{uuid.uuid4().hex[:12]}"


def _clean_budget(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        budget = int(value)
    except (TypeError, ValueError):
        return None
    return budget if budget > 0 else None


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _clean_area(area: Any, *, country_code: str) -> dict[str, Any] | None:
    if not isinstance(area, dict):
        return None
    name = _clean_text(area.get("name"), max_length=96)
    if not name:
        return None
    payload = {"name": name, "country_code": _clean_text(area.get("country_code") or country_code, max_length=2).upper()}
    key = _clean_text(area.get("key"), max_length=80)
    if key:
        payload["key"] = key
    return payload


def normalize_geo_locations(value: Any) -> list[dict[str, Any]]:
    """Normalize campaign targeting to country/province-only locations."""
    locations = _list_of_dicts(value)
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, location in enumerate(locations):
        country_code = _clean_text(location.get("country_code") or location.get("country") or "AR", max_length=2).upper()
        if len(country_code) != 2:
            country_code = "AR"
        regions = [
            region
            for region in (
                _clean_area(area, country_code=country_code)
                for area in _list_of_dicts(location.get("regions"))
            )
            if region is not None
        ][:20]
        key = f"{country_code}:{','.join((region.get('key') or region['name']).lower() for region in regions)}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append({"country_code": country_code, "regions": regions, "cities": []})
        if len(normalized) >= 20:
            break
    if not normalized:
        normalized.append({"country_code": "AR", "regions": [], "cities": []})
    return normalized


def meta_targeting_from_locations(locations: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the Meta geo_locations payload used by ad sets."""
    countries: list[str] = []
    regions: list[dict[str, Any]] = []
    for location in normalize_geo_locations(locations):
        country_code = _clean_text(location.get("country_code"), max_length=2).upper() or "AR"
        location_regions = _list_of_dicts(location.get("regions"))
        if not location_regions:
            countries.append(country_code)
            continue
        for region in location_regions:
            regions.append(
                {
                    "name": _clean_text(region.get("name"), max_length=96),
                    "country": _clean_text(region.get("country_code") or country_code, max_length=2).upper(),
                    **({"key": _clean_text(region.get("key"), max_length=80)} if _clean_text(region.get("key"), max_length=80) else {}),
                }
            )
    geo_locations: dict[str, Any] = {}
    if countries:
        geo_locations["countries"] = sorted(set(countries))
    if regions:
        geo_locations["regions"] = regions
    return {"geo_locations": geo_locations} if geo_locations else {}


class MetaPlanCreativeMedia(BaseModel):
    """One uploaded or external media reference attached to an ad."""

    creative_asset_id: str = ""
    asset_file_path: str = ""
    asset_type: str = "image"
    media_url: str = ""
    source: str = ""
    meta_creative_id: str = ""
    image_hash: str = ""
    video_id: str = ""

    @field_validator("*", mode="before")
    @classmethod
    def clean_string_fields(cls, value: Any) -> Any:
        return _clean_text(value, max_length=1000)


class MetaPlanAd(BaseModel):
    """One Meta ad creative and copy block."""

    id: str = ""
    name: str = ""
    status: str = "PAUSED"
    primary_text: str = ""
    headline: str = ""
    description: str = ""
    call_to_action: str = "LEARN_MORE"
    destination_url: str = ""
    media: list[MetaPlanCreativeMedia] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> "MetaPlanAd":
        self.id = _clean_id(self.id, "ad")
        self.name = _clean_text(self.name, max_length=160) or "Ad"
        self.status = _clean_status(self.status)
        self.primary_text = _clean_multiline(self.primary_text, max_length=4000)
        self.headline = _clean_text(self.headline, max_length=500)
        self.description = _clean_text(self.description, max_length=1000)
        self.call_to_action = _clean_text(self.call_to_action, max_length=80).upper() or "LEARN_MORE"
        self.destination_url = _clean_text(self.destination_url, max_length=1000)
        return self


class MetaPlanAdSet(BaseModel):
    """One Meta ad set, including audience and destination."""

    id: str = ""
    name: str = ""
    status: str = "PAUSED"
    destination_type: str = "form"
    page_id: str = ""
    instagram_actor_id: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_referral_source_id: str = ""
    lead_form_id: str = ""
    client_lead_source_id: str = ""
    landing_page_url: str = ""
    performance_goal: str = "LEAD_GENERATION"
    optimization_goal: str = "LEAD_GENERATION"
    billing_event: str = "IMPRESSIONS"
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP"
    budget_daily_usd: int | None = None
    budget_total_usd: int | None = None
    audience: dict[str, Any] = Field(default_factory=dict)
    targeting: dict[str, Any] = Field(default_factory=dict)
    placements: list[str] = Field(default_factory=list)
    facebook_positions: list[str] = Field(default_factory=list)
    instagram_positions: list[str] = Field(default_factory=list)
    messenger_positions: list[str] = Field(default_factory=list)
    audience_network_positions: list[str] = Field(default_factory=list)
    device_platforms: list[str] = Field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    ads: list[MetaPlanAd] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> "MetaPlanAdSet":
        self.id = _clean_id(self.id, "adset")
        self.name = _clean_text(self.name, max_length=160) or "Ad set"
        self.status = _clean_status(self.status)
        destination_type = _clean_text(self.destination_type, max_length=40).lower()
        self.destination_type = destination_type if destination_type in DESTINATION_TYPES else "form"
        self.performance_goal = _clean_text(self.performance_goal, max_length=80).upper() or "LEAD_GENERATION"
        self.optimization_goal = _clean_text(self.optimization_goal, max_length=80).upper() or self.performance_goal
        self.billing_event = _clean_text(self.billing_event, max_length=80).upper() or "IMPRESSIONS"
        self.bid_strategy = _clean_text(self.bid_strategy, max_length=120).upper() or "LOWEST_COST_WITHOUT_CAP"
        self.budget_daily_usd = _clean_budget(self.budget_daily_usd)
        self.budget_total_usd = _clean_budget(self.budget_total_usd)
        self.page_id = _clean_text(self.page_id, max_length=120)
        self.instagram_actor_id = _clean_text(self.instagram_actor_id, max_length=120)
        self.whatsapp_phone_number_id = _clean_text(self.whatsapp_phone_number_id, max_length=120)
        self.whatsapp_referral_source_id = _clean_text(self.whatsapp_referral_source_id, max_length=160)
        self.lead_form_id = _clean_text(self.lead_form_id, max_length=160)
        self.client_lead_source_id = _clean_text(self.client_lead_source_id, max_length=160)
        self.landing_page_url = _clean_text(self.landing_page_url, max_length=1000)
        locations = normalize_geo_locations(self.audience.get("locations") if isinstance(self.audience, dict) else [])
        self.audience = {"locations": locations}
        if not self.targeting:
            self.targeting = meta_targeting_from_locations(locations)
        if not self.ads:
            self.ads = [MetaPlanAd(id=f"{self.id}_ad_1", name="Ad 1")]
        return self


class MetaPlanCampaign(BaseModel):
    """One Meta campaign node in the CRM campaign workspace."""

    id: str = ""
    name: str = ""
    status: str = "PAUSED"
    objective: str = "OUTCOME_LEADS"
    buying_type: str = "AUCTION"
    special_ad_categories: list[str] = Field(default_factory=list)
    budget_daily_usd: int | None = None
    budget_total_usd: int | None = None
    ad_sets: list[MetaPlanAdSet] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> "MetaPlanCampaign":
        self.id = _clean_id(self.id, "campaign")
        self.name = _clean_text(self.name, max_length=160) or "Meta campaign"
        self.status = _clean_status(self.status)
        self.objective = _clean_text(self.objective, max_length=120).upper() or "OUTCOME_LEADS"
        self.buying_type = _clean_text(self.buying_type, max_length=80).upper() or "AUCTION"
        self.budget_daily_usd = _clean_budget(self.budget_daily_usd)
        self.budget_total_usd = _clean_budget(self.budget_total_usd)
        self.special_ad_categories = [_clean_text(item, max_length=80).upper() for item in self.special_ad_categories if _clean_text(item)]
        if not self.ad_sets:
            self.ad_sets = [MetaPlanAdSet(id=f"{self.id}_adset_1", name="Ad set 1")]
        return self


class MetaPlanGraph(BaseModel):
    """Versioned CRM-owned Meta hierarchy graph."""

    schema_version: str = META_PLAN_GRAPH_SCHEMA_VERSION
    strategy: str = "custom"
    campaigns: list[MetaPlanCampaign] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize(self) -> "MetaPlanGraph":
        self.schema_version = META_PLAN_GRAPH_SCHEMA_VERSION
        self.strategy = _clean_text(self.strategy, max_length=40) or "custom"
        if not self.campaigns:
            self.campaigns = [MetaPlanCampaign(id="campaign_1", name="Meta campaign 1")]
        return self


def _creative_from_campaign_info(campaign_info: dict[str, Any]) -> dict[str, Any]:
    creative = campaign_info.get("creative") if isinstance(campaign_info.get("creative"), dict) else {}
    media = _list_of_dicts(creative.get("media"))
    primary_media_url = _clean_text(creative.get("primary_media_url"), max_length=1000)
    if primary_media_url and not any(_clean_text(item.get("media_url"), max_length=1000) == primary_media_url for item in media):
        media = [{"source": "primary", "media_url": primary_media_url, "asset_type": "image"}, *media]
    return {
        "primary_text": _clean_multiline(creative.get("primary_text"), max_length=4000),
        "headline": _clean_text(creative.get("headline"), max_length=500),
        "description": _clean_text(creative.get("description"), max_length=1000),
        "call_to_action": _clean_text(creative.get("call_to_action"), max_length=80).upper() or "LEARN_MORE",
        "destination_url": _clean_text(creative.get("destination_url"), max_length=1000),
        "media": media,
    }


def _locations_from_campaign_info(campaign_info: dict[str, Any]) -> list[dict[str, Any]]:
    locations = campaign_info.get("location_locations")
    if isinstance(locations, list) and locations:
        return normalize_geo_locations(locations)
    geo_targeting = campaign_info.get("geo_targeting") if isinstance(campaign_info.get("geo_targeting"), dict) else {}
    return normalize_geo_locations(geo_targeting.get("locations"))


def build_strategy_meta_plan_graph(
    *,
    strategy: str,
    campaign_name: str,
    daily_budget_usd: int | None,
    campaign_info: dict[str, Any] | None = None,
    destination_url: str = "",
    client_lead_source_id: str = "",
) -> dict[str, Any]:
    """Create a graph skeleton from an operator strategy template."""
    info = campaign_info or {}
    campaign_count, ad_set_count, ad_count = STRATEGY_SHAPES.get(strategy, (1, 1, 1))
    locations = _locations_from_campaign_info(info)
    creative = _creative_from_campaign_info(info)
    if destination_url and not creative.get("destination_url"):
        creative["destination_url"] = destination_url

    campaigns: list[dict[str, Any]] = []
    for campaign_index in range(campaign_count):
        campaign_id = f"campaign_{campaign_index + 1}"
        ad_sets: list[dict[str, Any]] = []
        for ad_set_index in range(ad_set_count):
            ad_set_id = f"{campaign_id}_adset_{ad_set_index + 1}"
            ads = [
                {
                    "id": f"{ad_set_id}_ad_{ad_index + 1}",
                    "name": f"Ad {ad_index + 1}",
                    **creative,
                }
                for ad_index in range(ad_count)
            ]
            ad_sets.append(
                {
                    "id": ad_set_id,
                    "name": f"Ad set {ad_set_index + 1}",
                    "destination_type": "form",
                    "client_lead_source_id": client_lead_source_id,
                    "audience": {"locations": locations},
                    "targeting": meta_targeting_from_locations(locations),
                    "ads": ads,
                }
            )
        campaigns.append(
            {
                "id": campaign_id,
                "name": campaign_name if campaign_count == 1 else f"{campaign_name} {campaign_index + 1}",
                "budget_daily_usd": daily_budget_usd,
                "ad_sets": ad_sets,
            }
        )
    return MetaPlanGraph(strategy=strategy, campaigns=campaigns).model_dump(mode="json")


def normalize_meta_plan_graph(
    value: Any,
    *,
    campaign_name: str = "Meta campaign",
    daily_budget_usd: int | None = None,
    campaign_info: dict[str, Any] | None = None,
    destination_url: str = "",
    client_lead_source_id: str = "",
) -> dict[str, Any]:
    """Return a safe graph, building a backward-compatible default when absent."""
    raw = value if isinstance(value, dict) else {}
    raw_campaigns = raw.get("campaigns") if isinstance(raw.get("campaigns"), list) else []
    if not raw_campaigns:
        strategy = _clean_text(raw.get("strategy"), max_length=40) or "1x1x1"
        return build_strategy_meta_plan_graph(
            strategy=strategy,
            campaign_name=campaign_name,
            daily_budget_usd=daily_budget_usd,
            campaign_info=campaign_info,
            destination_url=destination_url,
            client_lead_source_id=client_lead_source_id,
        )
    graph = MetaPlanGraph.model_validate(raw).model_dump(mode="json")
    for campaign in graph["campaigns"]:
        campaign["budget_daily_usd"] = campaign.get("budget_daily_usd") or daily_budget_usd
        for ad_set in campaign.get("ad_sets", []):
            if client_lead_source_id and not ad_set.get("client_lead_source_id"):
                ad_set["client_lead_source_id"] = client_lead_source_id
            locations = normalize_geo_locations((ad_set.get("audience") or {}).get("locations"))
            ad_set["audience"] = {"locations": locations}
            if not ad_set.get("targeting"):
                ad_set["targeting"] = meta_targeting_from_locations(locations)
    return graph


def campaign_info_with_meta_plan_graph(
    campaign_info: dict[str, Any],
    graph: Any,
    *,
    campaign_name: str,
    daily_budget_usd: int | None,
    destination_url: str = "",
    client_lead_source_id: str = "",
) -> dict[str, Any]:
    """Merge a normalized Meta graph into campaign_info."""
    next_info = dict(campaign_info or {})
    next_info[META_PLAN_GRAPH_KEY] = normalize_meta_plan_graph(
        graph,
        campaign_name=campaign_name,
        daily_budget_usd=daily_budget_usd,
        campaign_info=next_info,
        destination_url=destination_url,
        client_lead_source_id=client_lead_source_id,
    )
    return next_info


def _clone_with_new_ids(value: dict[str, Any], *, node_type: MetaPlanNodeType) -> dict[str, Any]:
    clone = copy.deepcopy(value)
    suffix = uuid.uuid4().hex[:8]
    clone["id"] = f"{node_type}_{suffix}"
    clone["name"] = f"{_clean_text(clone.get('name'), max_length=140) or node_type.replace('_', ' ').title()} copy"
    if node_type == "campaign":
        for ad_set in clone.get("ad_sets", []):
            ad_set.update(_clone_with_new_ids(ad_set, node_type="ad_set"))
    if node_type == "ad_set":
        for ad in clone.get("ads", []):
            ad.update(_clone_with_new_ids(ad, node_type="ad"))
    return clone


def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    next_value = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(next_value.get(key), dict):
            next_value[key] = _deep_merge(next_value[key], value)
        else:
            next_value[key] = value
    return next_value


def duplicate_meta_plan_node(
    graph: Any,
    *,
    node_type: MetaPlanNodeType,
    node_id: str,
    target_parent_id: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Duplicate one graph node deterministically and apply explicit overrides."""
    normalized = normalize_meta_plan_graph(graph)
    clean_node_id = _clean_text(node_id, max_length=120)
    clean_parent_id = _clean_text(target_parent_id, max_length=120)
    patch = overrides if isinstance(overrides, dict) else {}

    if node_type == "campaign":
        source = next((campaign for campaign in normalized["campaigns"] if campaign["id"] == clean_node_id), None)
        if source is None:
            raise ValueError("campaign node not found")
        normalized["campaigns"].append(_deep_merge(_clone_with_new_ids(source, node_type="campaign"), patch))
        return normalize_meta_plan_graph(normalized)

    for campaign in normalized["campaigns"]:
        if node_type == "ad_set":
            source = next((ad_set for ad_set in campaign.get("ad_sets", []) if ad_set["id"] == clean_node_id), None)
            if source is None:
                continue
            target_campaign = next(
                (item for item in normalized["campaigns"] if item["id"] == clean_parent_id),
                campaign,
            )
            target_campaign.setdefault("ad_sets", []).append(_deep_merge(_clone_with_new_ids(source, node_type="ad_set"), patch))
            return normalize_meta_plan_graph(normalized)
        for ad_set in campaign.get("ad_sets", []):
            if node_type != "ad":
                continue
            source = next((ad for ad in ad_set.get("ads", []) if ad["id"] == clean_node_id), None)
            if source is None:
                continue
            target_ad_set = ad_set
            if clean_parent_id:
                for parent_campaign in normalized["campaigns"]:
                    for candidate in parent_campaign.get("ad_sets", []):
                        if candidate["id"] == clean_parent_id:
                            target_ad_set = candidate
            target_ad_set.setdefault("ads", []).append(_deep_merge(_clone_with_new_ids(source, node_type="ad"), patch))
            return normalize_meta_plan_graph(normalized)
    raise ValueError(f"{node_type} node not found")


def _stage_destination(ad_set: dict[str, Any], *, public_url: str, client_lead_source_id: str) -> dict[str, Any]:
    destination_type = _clean_text(ad_set.get("destination_type"), max_length=40).lower() or "form"
    base = {
        "page_id": _clean_text(ad_set.get("page_id"), max_length=120),
        "instagram_actor_id": _clean_text(ad_set.get("instagram_actor_id"), max_length=120),
        "whatsapp_phone_number_id": _clean_text(ad_set.get("whatsapp_phone_number_id"), max_length=120),
        "whatsapp_referral_source_id": _clean_text(ad_set.get("whatsapp_referral_source_id"), max_length=160),
        "lead_form_id": _clean_text(ad_set.get("lead_form_id"), max_length=160),
        "client_lead_source_id": _clean_text(ad_set.get("client_lead_source_id") or client_lead_source_id, max_length=160),
        "landing_page_url": _clean_text(ad_set.get("landing_page_url") or public_url, max_length=1000),
    }
    if destination_type == "website":
        return {"destination_type": "landing_page", **base}
    if destination_type == "whatsapp":
        return {"destination_type": "whatsapp", **base}
    return {"destination_type": "landing_page", **base}


def _stage_ad(ad: dict[str, Any]) -> dict[str, Any]:
    media = _list_of_dicts(ad.get("media"))
    primary_media = media[0] if media else {}
    return {
        "name": _clean_text(ad.get("name"), max_length=160) or "Ad",
        "status": _clean_status(ad.get("status")),
        "creative": {
            "name": _clean_text(ad.get("name"), max_length=160) or "Ad creative",
            "creative_asset_id": _clean_text(primary_media.get("creative_asset_id"), max_length=160),
            "asset_file_path": _clean_text(primary_media.get("asset_file_path"), max_length=1000),
            "meta_creative_id": _clean_text(primary_media.get("meta_creative_id"), max_length=160),
            "image_hash": _clean_text(primary_media.get("image_hash"), max_length=160),
            "video_id": _clean_text(primary_media.get("video_id"), max_length=160),
            "primary_text": _clean_multiline(ad.get("primary_text"), max_length=4000),
            "headline": _clean_text(ad.get("headline"), max_length=500),
            "description": _clean_text(ad.get("description"), max_length=1000),
            "call_to_action": _clean_text(ad.get("call_to_action"), max_length=80).upper() or "LEARN_MORE",
            "destination_url": _clean_text(ad.get("destination_url"), max_length=1000),
        },
    }


def meta_plan_graph_to_stage_payloads(
    graph: Any,
    *,
    campaign_id: str,
    client_id: str,
    funnel_id: str,
    ad_account_id: str = "",
    budget_currency: str = "USD",
    public_url: str,
    client_lead_source_id: str = "",
    notes: str = "",
    idempotency_key: str | None = None,
) -> list[dict[str, Any]]:
    """Convert the graph into one staged Meta publish payload per Meta campaign."""
    normalized = normalize_meta_plan_graph(graph)
    payloads: list[dict[str, Any]] = []
    for campaign in normalized["campaigns"]:
        ad_sets = _list_of_dicts(campaign.get("ad_sets"))
        primary_destination = _stage_destination(
            ad_sets[0] if ad_sets else {},
            public_url=public_url,
            client_lead_source_id=client_lead_source_id,
        )
        stage_ad_sets: list[dict[str, Any]] = []
        for ad_set in ad_sets:
            destination = _stage_destination(
                ad_set,
                public_url=public_url,
                client_lead_source_id=client_lead_source_id,
            )
            stage_ad_sets.append(
                {
                    "name": _clean_text(ad_set.get("name"), max_length=160) or "Ad set",
                    "status": _clean_status(ad_set.get("status")),
                    "budget_daily_usd": _clean_budget(ad_set.get("budget_daily_usd")) or _clean_budget(campaign.get("budget_daily_usd")),
                    "budget_total_usd": _clean_budget(ad_set.get("budget_total_usd")) or _clean_budget(campaign.get("budget_total_usd")),
                    "optimization_goal": _clean_text(ad_set.get("optimization_goal"), max_length=80).upper() or "LEAD_GENERATION",
                    "billing_event": _clean_text(ad_set.get("billing_event"), max_length=80).upper() or "IMPRESSIONS",
                    "bid_strategy": _clean_text(ad_set.get("bid_strategy"), max_length=120).upper() or "LOWEST_COST_WITHOUT_CAP",
                    "promoted_object": ad_set.get("promoted_object") if isinstance(ad_set.get("promoted_object"), dict) else {},
                    "targeting": ad_set.get("targeting") if isinstance(ad_set.get("targeting"), dict) else {},
                    "destination": destination,
                    "placements": ad_set.get("placements") if isinstance(ad_set.get("placements"), list) else [],
                    "facebook_positions": ad_set.get("facebook_positions") if isinstance(ad_set.get("facebook_positions"), list) else [],
                    "instagram_positions": ad_set.get("instagram_positions") if isinstance(ad_set.get("instagram_positions"), list) else [],
                    "messenger_positions": ad_set.get("messenger_positions") if isinstance(ad_set.get("messenger_positions"), list) else [],
                    "audience_network_positions": ad_set.get("audience_network_positions") if isinstance(ad_set.get("audience_network_positions"), list) else [],
                    "device_platforms": ad_set.get("device_platforms") if isinstance(ad_set.get("device_platforms"), list) else [],
                    "start_time": _clean_text(ad_set.get("start_time"), max_length=80),
                    "end_time": _clean_text(ad_set.get("end_time"), max_length=80),
                    "ads": [_stage_ad(ad) for ad in _list_of_dicts(ad_set.get("ads"))],
                }
            )
        payloads.append(
            {
                "campaign_id": campaign_id,
                "client_id": client_id,
                "funnel_id": funnel_id,
                "ad_account_id": ad_account_id,
                "campaign_name": _clean_text(campaign.get("name"), max_length=160) or "Meta campaign",
                "objective": _clean_text(campaign.get("objective"), max_length=120).upper() or "OUTCOME_LEADS",
                "buying_type": _clean_text(campaign.get("buying_type"), max_length=80).upper() or "AUCTION",
                "special_ad_categories": campaign.get("special_ad_categories") if isinstance(campaign.get("special_ad_categories"), list) else [],
                "budget_currency": _clean_text(budget_currency, max_length=12).upper() or "USD",
                "destination": primary_destination,
                "ad_sets": stage_ad_sets,
                "notes": notes,
                "approval_status": "pending",
                "idempotency_key": idempotency_key or f"meta-plan:{campaign_id}:{campaign.get('id')}",
            }
        )
    return payloads
