"""Owned campaign, public form, and converted-client endpoints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.database import (
    CLIENT_LEAD_CONTEXT_TEMPLATE_NAME,
    CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE,
    ClientLeadDelivery,
    ClientLeadDeliveryStatus,
    ClientLeadSource,
    ContadoresLead,
    LeadCaptureCampaign,
    LeadCaptureSubmission,
    PlatformAdCampaign,
    PlatformEvent,
    PlatformMetaInventorySnapshot,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationClientStatus,
    WorkstationClientWorkType,
    normalize_email,
    normalize_phone,
)
from backend.endpoints.client_leads import (
    build_context_text_from_row,
    build_notification_text,
    build_source_response,
    build_wa_link,
    format_timestamp_seconds,
)
from backend.meta_conversions import build_user_data, send_meta_conversion_event


campaigns_router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])
public_campaigns_router = APIRouter(tags=["campaigns"])

PUBLIC_ALLOWED_TRACKING_KEYS = {
    "href",
    "referrer",
    "fbp",
    "fbc",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
}
PUBLIC_MAX_ANSWER_FIELDS = 40
PUBLIC_MAX_ANSWER_BYTES = 20_000
PUBLIC_MAX_FIELD_TEXT = 2_000
PUBLIC_MAX_TRACKING_TEXT = 1_000
PUBLISHABLE_CAMPAIGN_STATUSES = {"active", "published"}
CAMPAIGN_GEO_SUPPORTED_COUNTRIES = {"AR", "UY", "CL", "PY", "BO", "PE", "CO", "EC", "MX", "US", "ES", "DE"}
CAMPAIGN_GEO_MAX_AREAS_PER_KIND = 20
CAMPAIGN_GEO_MAX_LOCATIONS = 20
CAMPAIGN_GEO_NAME_MAX_LENGTH = 96
CAMPAIGN_GEO_KEY_MAX_LENGTH = 80
CAMPAIGN_GEO_NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9 .,'()/-]{0,95}$")
CAMPAIGN_GEO_KEY_RE = re.compile(r"^[A-Za-z0-9_:-]{1,80}$")
CAMPAIGN_GEO_SEARCH_LIMIT = 12
DEFAULT_META_EVENT_NAME = "Lead"
META_PIXEL_ENV_NAMES = ("META_PIXEL_ID", "META_DEFAULT_PIXEL_ID", "META_MARKETING_PIXEL_ID")
SUBMISSION_PHONE_MISSING_TRACKING_KEY = "_lead_phone_missing"

CAMPAIGN_GEO_FALLBACKS: dict[str, dict[str, list[str]]] = {
    "AR": {
        "region": [
            "Buenos Aires",
            "Ciudad Autonoma de Buenos Aires",
            "Cordoba",
            "Santa Fe",
            "Mendoza",
            "Tucuman",
            "Salta",
            "Entre Rios",
            "Neuquen",
            "Rio Negro",
        ],
        "city": [
            "CABA",
            "Buenos Aires",
            "La Plata",
            "Cordoba",
            "Rosario",
            "Mendoza",
            "Mar del Plata",
            "San Miguel de Tucuman",
            "Salta",
            "Neuquen",
        ],
    },
    "UY": {
        "region": ["Montevideo", "Canelones", "Maldonado", "Colonia", "San Jose", "Rocha"],
        "city": ["Montevideo", "Ciudad de la Costa", "Punta del Este", "Maldonado", "Colonia del Sacramento"],
    },
    "CL": {
        "region": ["Region Metropolitana", "Valparaiso", "Biobio", "Maule", "Araucania"],
        "city": ["Santiago", "Valparaiso", "Concepcion", "Vina del Mar", "Temuco"],
    },
    "PY": {"region": ["Central", "Asuncion", "Alto Parana"], "city": ["Asuncion", "Ciudad del Este", "San Lorenzo"]},
    "BO": {"region": ["La Paz", "Santa Cruz", "Cochabamba"], "city": ["La Paz", "Santa Cruz de la Sierra", "Cochabamba"]},
    "PE": {"region": ["Lima", "Arequipa", "La Libertad"], "city": ["Lima", "Arequipa", "Trujillo"]},
    "CO": {"region": ["Bogota", "Antioquia", "Valle del Cauca"], "city": ["Bogota", "Medellin", "Cali"]},
    "EC": {"region": ["Pichincha", "Guayas", "Azuay", "Manabi"], "city": ["Quito", "Guayaquil", "Cuenca", "Manta"]},
    "MX": {"region": ["Ciudad de Mexico", "Jalisco", "Nuevo Leon"], "city": ["Ciudad de Mexico", "Guadalajara", "Monterrey"]},
    "US": {"region": ["Florida", "California", "Texas", "New York"], "city": ["Miami", "Los Angeles", "Houston", "New York"]},
    "ES": {"region": ["Madrid", "Cataluna", "Andalucia", "Valencia"], "city": ["Madrid", "Barcelona", "Valencia", "Sevilla"]},
    "DE": {
        "region": [
            "Baden-Wurttemberg",
            "Bavaria",
            "Berlin",
            "Brandenburg",
            "Hamburg",
            "Hesse",
            "Lower Saxony",
            "North Rhine-Westphalia",
            "Saxony",
        ],
        "city": ["Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt"],
    },
}

CAMPAIGN_DELIVERY_PRESETS = {
    "alan": {"id": "alan", "label": "Alan", "phone": "393716506381", "kind": "preset"},
    "mathi": {"id": "mathi", "label": "Mathi", "phone": "5491138033159", "kind": "preset"},
    "facu": {"id": "facu", "label": "Facu", "phone": "5491153484587", "kind": "preset"},
}


def _validate_country_code(value: str | None) -> str:
    """Return a normalized ISO-like country code or raise a validation error."""
    clean = "".join(str(value or "").upper().split())
    if len(clean) != 2 or not clean.isalpha():
        raise ValueError("country_code must be a two-letter country code")
    if clean not in CAMPAIGN_GEO_SUPPORTED_COUNTRIES:
        raise ValueError(f"country_code is not supported: {clean}")
    return clean


class ConvertedClientCommand(BaseModel):
    """Create or reuse a converted client from minimal contact data."""

    name: str = Field(min_length=1)
    whatsapp: str = Field(min_length=3)
    email: str | None = None
    extra_info: str | None = None
    funnel_id: str = "contadores"
    work_type: str = WorkstationClientWorkType.PAGINA_ADS.value
    status: str = WorkstationClientStatus.PAID.value
    automation_status: str = WorkstationAutomationStatus.NEEDS_HUMAN.value
    offer_price_usd: int | None = Field(default=None, ge=1)
    offer_currency: str = "USD"


class CampaignGeoAreaCommand(BaseModel):
    """One campaign geography item selected by the operator."""

    name: str = Field(min_length=1, max_length=CAMPAIGN_GEO_NAME_MAX_LENGTH)
    key: str | None = Field(default=None, max_length=CAMPAIGN_GEO_KEY_MAX_LENGTH)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        clean = " ".join(str(value or "").split()).strip()
        if not clean:
            raise ValueError("geo area name is required")
        if not CAMPAIGN_GEO_NAME_RE.fullmatch(clean):
            raise ValueError("geo area name has invalid characters")
        return clean

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str | None) -> str | None:
        clean = " ".join(str(value or "").split()).strip()
        if not clean:
            return None
        if not CAMPAIGN_GEO_KEY_RE.fullmatch(clean):
            raise ValueError("geo area key has invalid characters")
        return clean

    @field_validator("country_code")
    @classmethod
    def validate_area_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_country_code(value)


class CampaignGeoLocationCommand(BaseModel):
    """One complete target location: country, optional regions, optional cities."""

    country_code: str = Field(default="AR", min_length=2, max_length=2)
    regions: list[CampaignGeoAreaCommand] = Field(default_factory=list, max_length=CAMPAIGN_GEO_MAX_AREAS_PER_KIND)
    cities: list[CampaignGeoAreaCommand] = Field(default_factory=list, max_length=CAMPAIGN_GEO_MAX_AREAS_PER_KIND)

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        return _validate_country_code(value)

    @model_validator(mode="after")
    def validate_geo_shape(self) -> "CampaignGeoLocationCommand":
        seen: set[tuple[str, str]] = set()
        for kind, items in (("region", self.regions), ("city", self.cities)):
            for item in items:
                duplicate_key = (kind, item.name.casefold())
                if duplicate_key in seen:
                    raise ValueError(f"duplicate {kind}: {item.name}")
                seen.add(duplicate_key)
        return self


class CampaignGeoTargetingCommand(BaseModel):
    """Structured geography for Meta-compatible owned campaign planning."""

    country_code: str = Field(default="AR", min_length=2, max_length=2)
    regions: list[CampaignGeoAreaCommand] = Field(default_factory=list, max_length=CAMPAIGN_GEO_MAX_AREAS_PER_KIND)
    cities: list[CampaignGeoAreaCommand] = Field(default_factory=list, max_length=CAMPAIGN_GEO_MAX_AREAS_PER_KIND)
    locations: list[CampaignGeoLocationCommand] = Field(default_factory=list, max_length=CAMPAIGN_GEO_MAX_LOCATIONS)

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str) -> str:
        return _validate_country_code(value)

    @model_validator(mode="after")
    def validate_geo_shape(self) -> "CampaignGeoTargetingCommand":
        locations = self.locations or [
            CampaignGeoLocationCommand(country_code=self.country_code, regions=self.regions, cities=self.cities)
        ]
        seen_locations: set[str] = set()
        for location in locations:
            location_key = json.dumps(location.model_dump(mode="json"), sort_keys=True)
            if location_key in seen_locations:
                raise ValueError(f"duplicate location: {location.country_code}")
            seen_locations.add(location_key)
        return self


class CampaignDeliveryContactCommand(BaseModel):
    """One WhatsApp recipient for campaign Delivery alerts."""

    id: str | None = None
    label: str | None = None
    phone: str | None = None
    kind: str | None = None


class CampaignDeliveryConfigCommand(BaseModel):
    """Delivery behavior for one owned campaign."""

    enabled: bool = True
    contacts: list[CampaignDeliveryContactCommand] = Field(default_factory=list, max_length=12)


class CampaignMetaOptimizationCommand(BaseModel):
    """Meta ad-set optimization for one owned campaign."""

    enabled: bool = False
    event_name: str = DEFAULT_META_EVENT_NAME


class LeadCaptureCampaignCommand(BaseModel):
    """Create an owned lead-capture campaign."""

    name: str = Field(min_length=1)
    client_id: str | None = None
    client: ConvertedClientCommand | None = None
    status: str = "draft"
    public_slug: str | None = None
    daily_budget_usd: int | None = Field(default=None, ge=1)
    budget_currency: str = "USD"
    location: str | None = None
    geo_targeting: CampaignGeoTargetingCommand | None = None
    campaign_info: dict[str, Any] = Field(default_factory=dict)
    creative_brief: str | None = None
    form_schema: dict[str, Any] = Field(default_factory=dict)
    thank_you_title: str = "Gracias"
    thank_you_body: str = "Recibimos tus datos. Te vamos a contactar por WhatsApp."
    destination_url: str | None = None
    meta_pixel_id: str | None = None
    meta_event_name: str = "Lead"
    meta_events_enabled: bool = False
    meta_optimization: CampaignMetaOptimizationCommand | None = None
    meta_optimize_for_pixel: bool = False
    meta_test_event_code: str | None = None
    stage_platform_campaign: bool = True
    delivery_config: CampaignDeliveryConfigCommand | None = None


class LeadCaptureCampaignPatchCommand(BaseModel):
    """Patch an owned lead-capture campaign."""

    name: str | None = None
    client_id: str | None = None
    status: str | None = None
    public_slug: str | None = None
    daily_budget_usd: int | None = Field(default=None, ge=1)
    budget_currency: str | None = None
    location: str | None = None
    geo_targeting: CampaignGeoTargetingCommand | None = None
    campaign_info: dict[str, Any] | None = None
    creative_brief: str | None = None
    form_schema: dict[str, Any] | None = None
    thank_you_title: str | None = None
    thank_you_body: str | None = None
    destination_url: str | None = None
    meta_pixel_id: str | None = None
    meta_event_name: str | None = None
    meta_events_enabled: bool | None = None
    meta_optimization: CampaignMetaOptimizationCommand | None = None
    meta_optimize_for_pixel: bool | None = None
    meta_test_event_code: str | None = None
    meta_campaign_id: str | None = None
    meta_adset_id: str | None = None
    meta_ad_id: str | None = None
    delivery_config: CampaignDeliveryConfigCommand | None = None


class PublicSubmissionCommand(BaseModel):
    """Public lead-capture form submission."""

    answers: dict[str, Any] = Field(default_factory=dict)
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    tracking: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=160)
    honeypot: str | None = None


class CampaignMetaDefaultsResponse(BaseModel):
    """Operator-facing Meta tracking defaults for campaign creation."""

    meta_events_available: bool
    meta_event_name: str = DEFAULT_META_EVENT_NAME
    pixel_source: str = ""
    pixel_label: str = ""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if value is None:
        return ""
    return value if isinstance(value, (str, int, float, bool)) else str(value)


def _clean_country_code(value: str | None) -> str:
    """Return a two-letter country code accepted by Meta country targeting."""
    return _validate_country_code(value or "AR")


def _clean_graph_error(value: Any) -> str:
    """Redact Graph API token material from errors sent to operators."""
    text = str(value)
    text = re.sub(r"(?i)(access_token=)[^&\s'\"<>]+", r"\1[redacted]", text)
    return text[:500]


def _clean_meta_pixel_id(value: Any) -> str:
    """Return a compact Meta pixel ID string from config or inventory."""
    return " ".join(str(value or "").split()).strip()


def _meta_pixel_label(pixel_id: str) -> str:
    """Return a UI-safe label without needing to show the full pixel ID."""
    clean = _clean_meta_pixel_id(pixel_id)
    if not clean:
        return ""
    return f"Pixel ending {clean[-4:]}" if len(clean) > 4 else "Pixel configured"


def _default_meta_pixel_id() -> tuple[str, str]:
    """Resolve the default campaign pixel from owned config, then latest Meta inventory."""
    for env_name in META_PIXEL_ENV_NAMES:
        pixel_id = _clean_meta_pixel_id(os.getenv(env_name))
        if pixel_id:
            return pixel_id, f"env:{env_name}"

    for snapshot in PlatformMetaInventorySnapshot.list_recent(limit=20):
        inventory = snapshot.inventory()
        pixels = inventory.get("pixels") if isinstance(inventory, dict) else []
        if not isinstance(pixels, list):
            continue
        for pixel in pixels:
            if not isinstance(pixel, dict):
                continue
            pixel_id = _clean_meta_pixel_id(pixel.get("id") or pixel.get("pixel_id"))
            if pixel_id:
                return pixel_id, f"inventory:{snapshot.id}"
    return "", ""


def _campaign_meta_pixel_id(requested_pixel_id: str | None, *, events_enabled: bool) -> str:
    """Use the provided pixel only when present; otherwise auto-resolve when tracking is on."""
    clean_pixel_id = _clean_meta_pixel_id(requested_pixel_id)
    if clean_pixel_id or not events_enabled:
        return clean_pixel_id
    default_pixel_id, _source = _default_meta_pixel_id()
    return default_pixel_id


def _meta_standard_event_type(event_name: str | None) -> str:
    """Return the Meta standard event enum used in ad-set promoted objects."""
    clean = " ".join(str(event_name or DEFAULT_META_EVENT_NAME).split()).strip()
    if not clean:
        clean = DEFAULT_META_EVENT_NAME
    if clean.lower() == "lead":
        return "LEAD"
    return re.sub(r"[^A-Z0-9]+", "_", clean.upper()).strip("_") or "LEAD"


def _normalize_campaign_meta_optimization(
    raw_config: Any,
    *,
    pixel_id: str,
    event_name: str,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Return the owned-campaign Meta ad-set optimization settings."""
    if isinstance(raw_config, CampaignMetaOptimizationCommand):
        raw = raw_config.model_dump(mode="json")
    elif isinstance(raw_config, dict):
        raw = raw_config
    else:
        raw = {}

    requested_enabled = bool(raw.get("enabled", False)) if enabled is None else bool(enabled)
    clean_event_name = " ".join(str(raw.get("event_name") or event_name or DEFAULT_META_EVENT_NAME).split()).strip()
    clean_pixel_id = _clean_meta_pixel_id(raw.get("pixel_id") or pixel_id)
    custom_event_type = _meta_standard_event_type(clean_event_name)
    return {
        "enabled": requested_enabled,
        "pixel_id": clean_pixel_id if requested_enabled else "",
        "event_name": clean_event_name or DEFAULT_META_EVENT_NAME,
        "custom_event_type": custom_event_type,
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "billing_event": "IMPRESSIONS",
        "promoted_object": (
            {"pixel_id": clean_pixel_id, "custom_event_type": custom_event_type}
            if requested_enabled and clean_pixel_id
            else {}
        ),
    }


def _campaign_info_with_meta_optimization(
    campaign_info: dict[str, Any],
    meta_optimization: CampaignMetaOptimizationCommand | dict[str, Any] | None,
    *,
    pixel_id: str,
    event_name: str,
    enabled: bool,
) -> dict[str, Any]:
    """Merge Meta ad-set optimization settings into campaign info."""
    next_info = dict(campaign_info or {})
    next_info["meta_optimization"] = _normalize_campaign_meta_optimization(
        meta_optimization,
        pixel_id=pixel_id,
        event_name=event_name,
        enabled=enabled,
    )
    return next_info


def _requested_meta_optimization_enabled(
    meta_optimization: CampaignMetaOptimizationCommand | dict[str, Any] | None,
    meta_optimize_for_pixel: bool | None,
    *,
    default: bool = False,
) -> bool:
    """Return whether the operator requested pixel-optimized Meta ad sets."""
    if meta_optimization is not None:
        if isinstance(meta_optimization, CampaignMetaOptimizationCommand):
            return bool(meta_optimization.enabled)
        if isinstance(meta_optimization, dict):
            return bool(meta_optimization.get("enabled", default))
    if meta_optimize_for_pixel is not None:
        return bool(meta_optimize_for_pixel)
    return default


def _campaign_meta_optimization_config(campaign: LeadCaptureCampaign) -> dict[str, Any]:
    """Return normalized Meta optimization settings for an existing campaign."""
    raw = campaign.campaign_info.get("meta_optimization") if isinstance(campaign.campaign_info, dict) else None
    return _normalize_campaign_meta_optimization(
        raw,
        pixel_id=campaign.meta_pixel_id,
        event_name=campaign.meta_event_name or DEFAULT_META_EVENT_NAME,
    )


def _default_public_campaign_slug(platform_campaign_id: str) -> str:
    """Return an opaque public slug for new owned campaign form links."""
    clean_platform_id = " ".join(str(platform_campaign_id or "").split()).strip()
    if clean_platform_id:
        return clean_platform_id
    return secrets.token_urlsafe(16)


def _meta_graph_get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    """Read Meta Graph when marketing credentials are configured."""
    api_version = str(os.getenv("META_MARKETING_API_VERSION") or "").strip().strip("/")
    access_token = str(os.getenv("META_MARKETING_ACCESS_TOKEN") or os.getenv("META_ACCESS_TOKEN") or "").strip()
    if not api_version or not access_token:
        return {}
    request_params = dict(params)
    request_params["access_token"] = access_token
    response = httpx.get(f"https://graph.facebook.com/{api_version}/{path.strip('/')}", params=request_params, timeout=12)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def _geo_search_match_score(name: str, query: str) -> tuple[int, str]:
    """Rank prefix matches first, then contains matches."""
    clean_name = name.casefold()
    clean_query = query.casefold()
    if clean_name == clean_query:
        return (0, clean_name)
    if clean_name.startswith(clean_query):
        return (1, clean_name)
    if clean_query in clean_name:
        return (2, clean_name)
    return (3, clean_name)


def _fallback_geo_suggestions(*, country: str, kind: str, query: str, limit: int) -> list[dict[str, str]]:
    """Return curated local suggestions when Meta search is not configured or has no match."""
    names = CAMPAIGN_GEO_FALLBACKS.get(country, {}).get(kind, [])
    clean_query = " ".join(query.split()).strip()
    matches = [name for name in names if not clean_query or clean_query.casefold() in name.casefold()]
    ranked = sorted(matches, key=lambda name: _geo_search_match_score(name, clean_query or name))
    return [
        {
            "name": name,
            "country_code": country,
            "type": kind,
            "source": "local",
        }
        for name in ranked[:limit]
    ]


def _meta_geo_suggestions(*, country: str, kind: str, query: str, limit: int) -> tuple[list[dict[str, str]], str | None]:
    """Search Meta ad geolocations and return key-bearing suggestions."""
    if len(query.strip()) < 2:
        return [], None
    location_types = ["region"] if kind == "region" else ["city"]
    params = {
        "type": "adgeolocation",
        "q": query.strip(),
        "limit": limit,
        "location_types": json.dumps(location_types),
        "country_code": country,
    }
    try:
        rows = _meta_graph_get("search", params).get("data", [])
    except Exception as error:
        return [], _clean_graph_error(error)
    if not isinstance(rows, list):
        return [], None

    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_country = str(row.get("country_code") or country).upper()
        name = " ".join(str(row.get("name") or "").split()).strip()
        key = " ".join(str(row.get("key") or "").split()).strip()
        if row_country != country or not name or not key:
            continue
        suggestion = {
            "name": name,
            "key": key,
            "country_code": row_country,
            "type": kind,
            "source": "meta",
        }
        dedupe_key = f"{kind}:{key}"
        if dedupe_key not in seen:
            suggestions.append(suggestion)
            seen.add(dedupe_key)
    suggestions.sort(key=lambda item: _geo_search_match_score(item["name"], query))
    return suggestions[:limit], None


def _clean_geo_area(area: CampaignGeoAreaCommand, *, fallback_country: str) -> dict[str, str]:
    """Normalize one operator-selected region/city."""
    name = " ".join(area.name.split()).strip()
    item: dict[str, str] = {"name": name}
    key = " ".join(str(area.key or "").split()).strip()
    country = _clean_country_code(area.country_code or fallback_country)
    if key:
        item["key"] = key
    if country:
        item["country"] = country
    return item


def _campaign_geo_locations(command: CampaignGeoTargetingCommand) -> list[CampaignGeoLocationCommand]:
    """Return new multi-location targeting or one legacy location."""
    if command.locations:
        return command.locations
    return [CampaignGeoLocationCommand(country_code=command.country_code, regions=command.regions, cities=command.cities)]


def _build_geo_targeting(command: CampaignGeoTargetingCommand | None, fallback_location: str | None = None) -> dict[str, Any]:
    """Build Meta-shaped geo targeting without pretending unresolved labels are Meta IDs."""
    if command is None:
        fallback = " ".join(str(fallback_location or "").split()).strip()
        return {
            "label": fallback,
            "targeting": {},
            "locations": [],
            "countries": [],
            "regions": [],
            "cities": [],
            "unresolved": {"regions": [], "cities": []},
        }

    full_countries: list[str] = []
    all_regions: list[dict[str, str]] = []
    all_cities: list[dict[str, str]] = []
    clean_locations: list[dict[str, Any]] = []
    label_parts: list[str] = []
    for location in _campaign_geo_locations(command):
        country = _clean_country_code(location.country_code)
        regions = [_clean_geo_area(area, fallback_country=country) for area in location.regions if " ".join(area.name.split()).strip()]
        cities = [_clean_geo_area(area, fallback_country=country) for area in location.cities if " ".join(area.name.split()).strip()]
        if not regions and not cities:
            full_countries.append(country)
        all_regions.extend(regions)
        all_cities.extend(cities)
        location_label_parts = [country]
        if regions:
            location_label_parts.append(", ".join(item["name"] for item in regions))
        if cities:
            location_label_parts.append(", ".join(item["name"] for item in cities))
        label_parts.append(" · ".join(location_label_parts))
        clean_locations.append(
            {
                "country_code": country,
                "regions": regions,
                "cities": cities,
            }
        )

    geo_locations: dict[str, Any] = {}
    if full_countries:
        geo_locations["countries"] = sorted(set(full_countries))
    keyed_regions = [item for item in all_regions if item.get("key")]
    keyed_cities = [item for item in all_cities if item.get("key")]
    if keyed_regions:
        geo_locations["regions"] = keyed_regions
    if keyed_cities:
        geo_locations["cities"] = keyed_cities
    unresolved = {
        "regions": [item for item in all_regions if not item.get("key")],
        "cities": [item for item in all_cities if not item.get("key")],
    }
    return {
        "label": " | ".join(label_parts),
        "country_code": clean_locations[0]["country_code"] if clean_locations else "",
        "countries": sorted(set(full_countries)),
        "locations": clean_locations,
        "regions": all_regions,
        "cities": all_cities,
        "targeting": {"geo_locations": geo_locations},
        "unresolved": unresolved,
    }


def _campaign_info_with_geo(command: LeadCaptureCampaignCommand) -> tuple[dict[str, Any], str]:
    """Merge submitted campaign info with structured geography metadata."""
    campaign_info = _jsonable(command.campaign_info if isinstance(command.campaign_info, dict) else {})
    if not isinstance(campaign_info, dict):
        campaign_info = {}
    geo = _build_geo_targeting(command.geo_targeting, command.location)
    if command.geo_targeting is not None:
        campaign_info["location_country"] = geo["country_code"]
        campaign_info["location_countries"] = geo["countries"]
        campaign_info["location_locations"] = geo["locations"]
        campaign_info["location_regions"] = geo["regions"]
        campaign_info["location_cities"] = geo["cities"]
        campaign_info["location_unresolved"] = geo["unresolved"]
        campaign_info["meta_targeting"] = geo["targeting"]
    location_label = geo["label"] or " ".join(str(command.location or "").split()).strip()
    return campaign_info, location_label


def _campaign_client_delivery_contact(client_id: str) -> dict[str, Any] | None:
    """Return the campaign client as a Delivery contact when possible."""
    clean_client_id = (client_id or "").strip()
    if not clean_client_id:
        return None
    client = WorkstationClient.get_by_id(clean_client_id)
    if client is None:
        return None
    lead = ContadoresLead.get_by_id(client.lead_id)
    if lead is None or not normalize_phone(lead.phone):
        return None
    label = client.display_name or lead.full_name or "Cliente"
    return {"id": "client", "label": label, "phone": lead.phone, "kind": "client"}


def _delivery_contact_key(value: str, fallback: str) -> str:
    """Return a compact stable key for one Delivery contact."""
    raw = " ".join(str(value or fallback or "contact").split()).strip().lower()
    key = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return (key or "contact")[:48]


def _normalize_delivery_contact(raw_contact: Any, *, client_id: str, index: int) -> dict[str, Any] | None:
    """Normalize one submitted campaign Delivery contact."""
    if isinstance(raw_contact, CampaignDeliveryContactCommand):
        raw = raw_contact.model_dump(mode="json")
    elif isinstance(raw_contact, dict):
        raw = raw_contact
    else:
        return None

    raw_id = " ".join(str(raw.get("id") or "").split()).strip().lower()
    raw_kind = " ".join(str(raw.get("kind") or "").split()).strip().lower()
    if raw_id == "client" or raw_kind == "client":
        return _campaign_client_delivery_contact(client_id)
    if raw_id in CAMPAIGN_DELIVERY_PRESETS:
        return dict(CAMPAIGN_DELIVERY_PRESETS[raw_id])

    clean_phone = " ".join(str(raw.get("phone") or "").split()).strip()
    clean_label = " ".join(str(raw.get("label") or "").split()).strip()
    if not clean_phone and not clean_label:
        return None
    if not normalize_phone(clean_phone):
        raise ValueError(f"delivery contact phone is invalid: {clean_label or clean_phone}")
    label = clean_label or clean_phone
    contact_id = _delivery_contact_key(raw_id or label, f"custom-{index}")
    return {"id": contact_id, "label": label, "phone": clean_phone, "kind": "custom"}


def _normalize_campaign_delivery_config(
    raw_config: Any,
    *,
    client_id: str,
) -> dict[str, Any]:
    """Normalize Delivery config stored inside campaign_info."""
    if isinstance(raw_config, CampaignDeliveryConfigCommand):
        raw = raw_config.model_dump(mode="json")
    elif isinstance(raw_config, dict):
        raw = raw_config
    else:
        raw = {}

    contacts_input = raw.get("contacts") if isinstance(raw.get("contacts"), list) else []
    if not contacts_input:
        contacts_input = [{"id": "client", "kind": "client"}]

    contacts: list[dict[str, Any]] = []
    seen_contacts: set[str] = set()
    for index, raw_contact in enumerate(contacts_input):
        contact = _normalize_delivery_contact(raw_contact, client_id=client_id, index=index)
        if contact is None:
            continue
        normalized_phone = normalize_phone(contact.get("phone") or "")
        contact_key = str(contact.get("id") or normalized_phone).strip().lower()
        if not normalized_phone or contact_key in seen_contacts:
            continue
        seen_contacts.add(contact_key)
        contact["normalized_phone"] = normalized_phone
        contacts.append(contact)

    return {"enabled": bool(raw.get("enabled", True)), "contacts": contacts}


def _campaign_info_with_delivery(
    campaign_info: dict[str, Any],
    delivery_config: CampaignDeliveryConfigCommand | dict[str, Any] | None,
    *,
    client_id: str,
) -> dict[str, Any]:
    """Merge campaign Delivery settings into campaign info."""
    next_info = dict(campaign_info or {})
    next_info["delivery"] = _normalize_campaign_delivery_config(delivery_config, client_id=client_id)
    return next_info


def _campaign_delivery_config(campaign: LeadCaptureCampaign) -> dict[str, Any]:
    """Return normalized Delivery settings for an existing campaign."""
    raw = campaign.campaign_info.get("delivery") if isinstance(campaign.campaign_info, dict) else None
    return _normalize_campaign_delivery_config(raw, client_id=campaign.client_id)


def _campaign_delivery_source_prefix(campaign: LeadCaptureCampaign) -> str:
    """Return the source id prefix used by campaign Delivery contacts."""
    return f"campaign-{campaign.public_slug}"


def _campaign_delivery_source_id(campaign: LeadCaptureCampaign, contact: dict[str, Any], index: int) -> str:
    """Return the source id for one campaign Delivery contact."""
    if index == 0 and contact.get("id") == "client":
        return campaign.client_lead_source_id or _campaign_delivery_source_prefix(campaign)
    suffix = _delivery_contact_key(str(contact.get("id") or contact.get("label") or ""), f"contact-{index + 1}")
    return f"{_campaign_delivery_source_prefix(campaign)}-{suffix}"[:96]


def _campaign_meta_target_segments(campaign_info: dict[str, Any], location_label: str = "") -> list[Any]:
    """Return structured target segments for staged platform campaigns."""
    meta_targeting = campaign_info.get("meta_targeting") if isinstance(campaign_info, dict) else None
    segments: list[Any] = []
    if isinstance(meta_targeting, dict) and meta_targeting:
        segments.append({"type": "meta_targeting", "targeting": meta_targeting})
    unresolved = campaign_info.get("location_unresolved") if isinstance(campaign_info, dict) else None
    if isinstance(unresolved, dict) and (unresolved.get("regions") or unresolved.get("cities")):
        segments.append({"type": "unresolved_geo_locations", **unresolved})
    if not segments and location_label:
        segments.append({"type": "location_label", "value": location_label})
    return segments


def _request_origin(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _public_url(request: Request, campaign: LeadCaptureCampaign) -> str:
    return f"{_request_origin(request)}/c/{campaign.public_slug}"


def _lead_payload(lead: ContadoresLead | None) -> dict[str, Any] | None:
    if lead is None:
        return None
    return {
        "id": lead.id,
        "funnel_id": lead.funnel_id,
        "external_lead_id": lead.external_lead_id,
        "full_name": lead.full_name,
        "phone": lead.phone,
        "normalized_phone": lead.normalized_phone,
        "email": lead.email,
        "pipeline_stage": lead.pipeline_stage,
        "queue_state": lead.queue_state,
        "attention_state": lead.attention_state,
        "created_at": format_timestamp_seconds(lead.created_at),
        "updated_at": format_timestamp_seconds(lead.updated_at),
    }


def _client_payload(client: WorkstationClient | None) -> dict[str, Any] | None:
    if client is None:
        return None
    lead = ContadoresLead.get_by_id(client.lead_id)
    return {
        "id": client.id,
        "lead_id": client.lead_id,
        "funnel_id": client.funnel_id,
        "display_name": client.display_name,
        "status": client.status.value if hasattr(client.status, "value") else str(client.status),
        "work_type": client.work_type.value if hasattr(client.work_type, "value") else str(client.work_type),
        "automation_status": (
            client.automation_status.value
            if hasattr(client.automation_status, "value")
            else str(client.automation_status)
        ),
        "notes": client.notes,
        "lead": _lead_payload(lead),
        "created_at": format_timestamp_seconds(client.created_at),
        "updated_at": format_timestamp_seconds(client.updated_at),
    }


def _aggregate_delivery_status(statuses: list[str]) -> str:
    """Return one display status for several delivery attempts."""
    clean = {str(status or "").strip().lower() for status in statuses if str(status or "").strip()}
    if not clean:
        return ""
    for candidate in ["failed", "blocked", "pending", "sent", "delivered", "skipped"]:
        if candidate in clean:
            return candidate
    return sorted(clean)[0]


def _submission_payload(submission: LeadCaptureSubmission) -> dict[str, Any]:
    delivery_prefix = f"campaign-submission:{submission.id}"
    deliveries = ClientLeadDelivery.list_by_source_row_key_prefix(delivery_prefix)
    if not deliveries and submission.client_lead_delivery_id:
        primary = ClientLeadDelivery.get_by_id(submission.client_lead_delivery_id)
        deliveries = [primary] if primary else []
    delivery_statuses: list[dict[str, Any]] = []
    for delivery in deliveries:
        source = ClientLeadSource.get_by_id(delivery.source_id)
        status = delivery.delivery_status.value if hasattr(delivery.delivery_status, "value") else str(delivery.delivery_status)
        delivery_statuses.append(
            {
                "delivery_id": delivery.id,
                "source_id": delivery.source_id,
                "recipient_name": source.recipient_name if source else "",
                "recipient_phone": source.recipient_phone if source else "",
                "delivery_status": status,
                "last_delivery_error": delivery.last_delivery_error,
            }
        )
    aggregate_delivery_status = _aggregate_delivery_status(
        [item["delivery_status"] for item in delivery_statuses]
    )
    return {
        "id": submission.id,
        "campaign_id": submission.campaign_id,
        "client_id": submission.client_id,
        "client_lead_delivery_id": submission.client_lead_delivery_id,
        "full_name": submission.full_name,
        "phone": submission.phone,
        "normalized_phone": submission.normalized_phone,
        "email": submission.email,
        "answers": submission.answers,
        "tracking": submission.tracking,
        "meta_event_id": submission.meta_event_id,
        "meta_event_status": submission.meta_event_status,
        "meta_event_response": submission.meta_event_response,
        "delivery_status": aggregate_delivery_status,
        "delivery_statuses": delivery_statuses,
        "created_at": format_timestamp_seconds(submission.created_at),
        "updated_at": format_timestamp_seconds(submission.updated_at),
    }


def _public_submission_receipt(
    *,
    campaign: LeadCaptureCampaign,
    submission: LeadCaptureSubmission | None = None,
    duplicate: bool = False,
    delivery_queued: bool = False,
    spam: bool = False,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "ok": True,
        "accepted": True,
        "duplicate": duplicate,
        "delivery_queued": delivery_queued,
        "thank_you": {"title": campaign.thank_you_title, "body": campaign.thank_you_body},
    }
    if spam:
        receipt["spam"] = True
    if submission is not None:
        receipt["submission"] = {
            "id": submission.id,
            "created_at": format_timestamp_seconds(submission.created_at),
        }
    return receipt


def _campaign_payload(
    campaign: LeadCaptureCampaign,
    *,
    request: Request | None = None,
    include_submissions: bool = False,
) -> dict[str, Any]:
    client = WorkstationClient.get_by_id(campaign.client_id) if campaign.client_id else None
    source = ClientLeadSource.get_by_id(campaign.client_lead_source_id) if campaign.client_lead_source_id else None
    delivery_sources = ClientLeadSource.list_by_id_prefix(_campaign_delivery_source_prefix(campaign))
    counts = LeadCaptureSubmission.count_by_campaign()
    payload = {
        "id": campaign.id,
        "client_id": campaign.client_id,
        "client_lead_source_id": campaign.client_lead_source_id,
        "platform_ad_campaign_id": campaign.platform_ad_campaign_id,
        "funnel_id": campaign.funnel_id,
        "name": campaign.name,
        "status": campaign.status,
        "public_slug": campaign.public_slug,
        "public_url": _public_url(request, campaign) if request else f"/c/{campaign.public_slug}",
        "daily_budget_usd": campaign.daily_budget_usd,
        "budget_currency": campaign.budget_currency,
        "location": campaign.location,
        "campaign_info": campaign.campaign_info,
        "creative_brief": campaign.creative_brief,
        "form_schema": campaign.form_schema,
        "thank_you_title": campaign.thank_you_title,
        "thank_you_body": campaign.thank_you_body,
        "destination_url": campaign.destination_url,
        "meta_pixel_id": campaign.meta_pixel_id,
        "meta_event_name": campaign.meta_event_name,
        "meta_events_enabled": campaign.meta_events_enabled,
        "meta_optimization": _campaign_meta_optimization_config(campaign),
        "meta_campaign_id": campaign.meta_campaign_id,
        "meta_adset_id": campaign.meta_adset_id,
        "meta_ad_id": campaign.meta_ad_id,
        "submission_count": counts.get(campaign.id, 0),
        "client": _client_payload(client),
        "delivery_config": _campaign_delivery_config(campaign),
        "delivery_source": build_source_response(source).model_dump(mode="json") if source else None,
        "delivery_sources": [
            build_source_response(item).model_dump(mode="json")
            for item in delivery_sources
        ],
        "created_at": format_timestamp_seconds(campaign.created_at),
        "updated_at": format_timestamp_seconds(campaign.updated_at),
    }
    if include_submissions:
        submissions = LeadCaptureSubmission.list_by_campaign(campaign.id, limit=500)
        payload["submissions"] = [
            _submission_payload(item)
            for item in reversed(submissions)
        ]
    return payload


def _public_campaign_payload(campaign: LeadCaptureCampaign, *, request: Request) -> dict[str, Any]:
    meta_pixel_id = _clean_meta_pixel_id(campaign.meta_pixel_id) if campaign.meta_events_enabled else ""
    return {
        "id": campaign.id,
        "name": campaign.name,
        "status": campaign.status,
        "public_slug": campaign.public_slug,
        "public_url": _public_url(request, campaign),
        "form_schema": campaign.form_schema,
        "thank_you_title": campaign.thank_you_title,
        "thank_you_body": campaign.thank_you_body,
        "meta": {
            "events_enabled": bool(meta_pixel_id),
            "pixel_id": meta_pixel_id,
            "event_name": campaign.meta_event_name or DEFAULT_META_EVENT_NAME,
        },
    }


def _get_campaign_or_404(campaign_id: str) -> LeadCaptureCampaign:
    campaign = LeadCaptureCampaign.get_by_id(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


def _get_public_campaign_or_404(public_slug: str) -> LeadCaptureCampaign:
    campaign = LeadCaptureCampaign.get_by_slug(public_slug)
    if campaign is None or campaign.status not in PUBLISHABLE_CAMPAIGN_STATUSES:
        raise HTTPException(status_code=404, detail="Campaign form not found.")
    return campaign


def _validate_campaign_client_link(client_id: str, status: str) -> WorkstationClient | None:
    clean_client_id = (client_id or "").strip()
    clean_status = (status or "draft").strip().lower()
    if not clean_client_id:
        if clean_status in PUBLISHABLE_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail="Active campaigns must be linked to a client.")
        return None
    client = WorkstationClient.get_by_id(clean_client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found.")
    lead = ContadoresLead.get_by_id(client.lead_id)
    if clean_status in PUBLISHABLE_CAMPAIGN_STATUSES and (lead is None or not normalize_phone(lead.phone)):
        raise HTTPException(status_code=400, detail="Active campaign client must have a valid WhatsApp.")
    return client


def _create_or_reuse_manual_lead(command: ConvertedClientCommand) -> ContadoresLead:
    normalized_phone = normalize_phone(command.whatsapp)
    if not normalized_phone:
        raise HTTPException(status_code=400, detail="WhatsApp is invalid.")
    clean_email = normalize_email(command.email or "") if command.email else None
    existing = next(
        (
            lead
            for lead in ContadoresLead.list_by_normalized_phone(normalized_phone, include_archived=True)
            if lead.terminal_state != "archived"
        ),
        None,
    )
    external_id = existing.external_lead_id if existing else f"manual-client:{normalized_phone}"
    try:
        lead = ContadoresLead.upsert(
            funnel_id=command.funnel_id,
            external_lead_id=external_id,
            phone=command.whatsapp,
            full_name=command.name,
            email=clean_email,
            platform="manual_client",
            lead_status="converted",
            tags=["manual-client", "converted-client"],
            sheet_created_time=_utcnow() if existing is None else existing.sheet_created_time,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ContadoresLead.mark_converted(
        lead.id,
        converted_at=_utcnow(),
        automation_paused=True,
        automation_paused_reason="manual_converted_client",
    ) or lead


def create_or_reuse_converted_client(command: ConvertedClientCommand) -> dict[str, Any]:
    """Create or reuse a Workstation client from manual contact data."""
    lead = _create_or_reuse_manual_lead(command)
    existing = WorkstationClient.get_by_lead_id(lead.id)
    client = existing or WorkstationClient.create_for_lead(
        lead,
        work_type=command.work_type,
        status=command.status,
        automation_status=command.automation_status,
        offer_price_usd=command.offer_price_usd,
        offer_currency=command.offer_currency,
    )
    client = WorkstationClient.update_automation_state(
        client.id,
        status=command.status,
        automation_status=command.automation_status,
    ) or client
    if command.offer_price_usd:
        client = WorkstationClient.update_offer(
            client.id,
            offer_price_usd=command.offer_price_usd,
            offer_currency=command.offer_currency,
            only_if_missing=False,
        ) or client
    if command.extra_info is not None:
        client = WorkstationClient.update_notes(client.id, notes=command.extra_info) or client

    PlatformEvent.add(
        event_type="workstation_client.manual_created",
        lifecycle_stage="post_conversion",
        target_type="workstation_client",
        target_id=client.id,
        funnel_id=client.funnel_id,
        source="campaign_api",
        actor="operator",
        summary=f"Manual converted client ready: {client.display_name}.",
        payload={"lead_id": lead.id, "existing_client": existing is not None},
        idempotency_key=f"manual-client:{lead.id}:{client.id}",
    )
    return {"client": _client_payload(client), "lead": _lead_payload(ContadoresLead.get_by_id(lead.id))}


def _context_mapping_for_form(form_schema: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field in form_schema.get("fields", []):
        if not isinstance(field, dict):
            continue
        field_id = str(field.get("id") or "").strip()
        field_type = str(field.get("type") or "").strip()
        label = " ".join(str(field.get("label") or field_id).split()).strip()
        if not field_id or field_id in {"full_name", "name", "phone", "email"} or field_type in {"phone", "email"}:
            continue
        mapping[label[:80] or field_id] = field_id
    return mapping


def ensure_campaign_delivery_sources(campaign: LeadCaptureCampaign) -> list[ClientLeadSource]:
    """Create or update the Delivery sources used by one campaign."""
    delivery_config = _campaign_delivery_config(campaign)
    prefix = _campaign_delivery_source_prefix(campaign)
    existing_sources = ClientLeadSource.list_by_id_prefix(prefix)
    if not campaign.client_id or not delivery_config["enabled"]:
        for source in existing_sources:
            if source.enabled:
                ClientLeadSource.set_enabled(source.id, False)
        return []

    context_mapping = _context_mapping_for_form(campaign.form_schema)
    template_name = CLIENT_LEAD_CONTEXT_TEMPLATE_NAME if context_mapping else None
    sources: list[ClientLeadSource] = []
    desired_ids: set[str] = set()
    for index, contact in enumerate(delivery_config["contacts"]):
        source_id = _campaign_delivery_source_id(campaign, contact, index)
        desired_ids.add(source_id)
        try:
            source = ClientLeadSource.upsert(
                source_id=source_id,
                label=f"{campaign.name} -> {contact['label']}",
                enabled=campaign.status in {"active", "published"},
                sheet_url="",
                recipient_name=contact["label"],
                recipient_phone=contact["phone"],
                template_name=template_name,
                template_language=CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE,
                column_mapping={
                    "source_id": "id",
                    "created_time": "created_time",
                    "full_name": "full_name",
                    "phone_number": "phone_number",
                    "email": "email",
                },
                context_field_mapping=context_mapping,
            )
        except ValueError:
            continue
        sources.append(source)

    for source in existing_sources:
        if source.id not in desired_ids and source.enabled:
            ClientLeadSource.set_enabled(source.id, False)
    if sources and campaign.client_lead_source_id != sources[0].id:
        LeadCaptureCampaign.update(campaign.id, client_lead_source_id=sources[0].id)
    return sources


def ensure_campaign_delivery_source(campaign: LeadCaptureCampaign) -> ClientLeadSource | None:
    """Create or update the primary Delivery source used by one campaign."""
    sources = ensure_campaign_delivery_sources(campaign)
    return sources[0] if sources else None


def _stage_platform_ad_campaign(
    command: LeadCaptureCampaignCommand,
    *,
    client_id: str,
    funnel_id: str,
    meta_pixel_id: str,
    meta_events_enabled: bool,
    meta_optimization_enabled: bool,
) -> PlatformAdCampaign:
    campaign_info, location_label = _campaign_info_with_geo(command)
    campaign_info = _campaign_info_with_delivery(
        campaign_info,
        command.delivery_config,
        client_id=client_id,
    )
    campaign_info = _campaign_info_with_meta_optimization(
        campaign_info,
        command.meta_optimization,
        pixel_id=meta_pixel_id,
        event_name=command.meta_event_name or DEFAULT_META_EVENT_NAME,
        enabled=meta_optimization_enabled,
    )
    meta_optimization = campaign_info["meta_optimization"]
    return PlatformAdCampaign.add(
        client_id=client_id,
        funnel_id=funnel_id,
        status="draft",
        objective="lead_capture_form",
        budget_daily_usd=command.daily_budget_usd,
        budget_currency=command.budget_currency,
        target_segments=_campaign_meta_target_segments(campaign_info, location_label),
        angles=[command.creative_brief] if command.creative_brief else [],
        creative_benchmark={"source": "owned_campaign_form", "campaign_info": campaign_info},
        creative_testing={
            "destination": "owned_form",
            "default_status": "PAUSED",
            "meta_events_enabled": meta_events_enabled,
            "meta_optimization": meta_optimization,
        },
        approval_status="not_requested",
        idempotency_key=f"lead-capture:{client_id}:{command.name}",
    )


def _answer_value(answers: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = answers.get(key)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if str(item).strip())
        clean = " ".join(str(value or "").split()).strip()
        if clean:
            return clean
    return ""


def _field_value_to_text(value: Any) -> str:
    if isinstance(value, list):
        values = [_field_value_to_text(item) for item in value]
        return ", ".join(item for item in values if item)
    if isinstance(value, dict):
        return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    return " ".join(str(value or "").split()).strip()


def _normalize_submission_value(field: dict[str, Any], raw_value: Any) -> Any:
    field_type = str(field.get("type") or "text")
    options = [str(option) for option in field.get("options", []) if str(option).strip()]

    if field_type == "multi_select":
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        clean_values = [_field_value_to_text(value)[:PUBLIC_MAX_FIELD_TEXT] for value in values]
        clean_values = [value for value in clean_values if value]
        if len(clean_values) > 20:
            raise HTTPException(status_code=400, detail=f"Too many values for {field.get('id')}.")
        if options and any(value not in options for value in clean_values):
            raise HTTPException(status_code=400, detail=f"Invalid option for {field.get('id')}.")
        return clean_values

    clean_value = _field_value_to_text(raw_value)
    if len(clean_value) > PUBLIC_MAX_FIELD_TEXT:
        raise HTTPException(status_code=400, detail=f"{field.get('label') or field.get('id')} is too long.")
    if field_type == "yes_no" and clean_value and clean_value not in {"Si", "No"}:
        raise HTTPException(status_code=400, detail=f"Invalid yes/no value for {field.get('id')}.")
    if field_type == "select" and clean_value and options and clean_value not in options:
        raise HTTPException(status_code=400, detail=f"Invalid option for {field.get('id')}.")
    if field_type == "email" and clean_value and not normalize_email(clean_value):
        raise HTTPException(status_code=400, detail=f"{field.get('label') or field.get('id')} is invalid.")
    if field_type == "phone" and clean_value and not normalize_phone(clean_value):
        raise HTTPException(status_code=400, detail=f"{field.get('label') or field.get('id')} is invalid.")
    return normalize_email(clean_value) if field_type == "email" and clean_value else clean_value


def _normalize_submission_answers(campaign: LeadCaptureCampaign, command: PublicSubmissionCommand) -> dict[str, Any]:
    raw_size = len(json.dumps(_jsonable(command.answers), ensure_ascii=False))
    if raw_size > PUBLIC_MAX_ANSWER_BYTES:
        raise HTTPException(status_code=400, detail="Submission is too large.")
    if len(command.answers) > PUBLIC_MAX_ANSWER_FIELDS:
        raise HTTPException(status_code=400, detail="Too many fields.")

    fields = campaign.form_schema.get("fields", [])
    field_map = {str(field.get("id") or "").strip(): field for field in fields if isinstance(field, dict)}
    raw_answers = {str(key).strip(): value for key, value in command.answers.items() if str(key).strip()}
    for aliases, value in (
        (("full_name", "name", "nombre", "nombre_completo"), command.full_name),
        (("phone", "phone_number", "whatsapp", "telefono", "celular"), command.phone),
        (("email", "correo", "mail"), command.email),
    ):
        if not value:
            continue
        for alias in aliases:
            if alias in field_map and alias not in raw_answers:
                raw_answers[alias] = value
                break
    unknown_fields = sorted(set(raw_answers) - set(field_map))
    if unknown_fields:
        raise HTTPException(status_code=400, detail=f"Unknown field: {unknown_fields[0]}.")

    answers: dict[str, Any] = {}
    for field_id, field in field_map.items():
        if field_id in raw_answers:
            value = _normalize_submission_value(field, raw_answers[field_id])
            if value != "" and value != []:
                answers[field_id] = value
        elif field.get("required"):
            label = field.get("label") or field_id
            raise HTTPException(status_code=400, detail=f"{label} is required.")
    return answers


def _normalize_tracking(value: dict[str, Any]) -> dict[str, str]:
    tracking: dict[str, str] = {}
    for key, item in value.items():
        clean_key = str(key or "").strip()
        if clean_key not in PUBLIC_ALLOWED_TRACKING_KEYS:
            continue
        clean_value = _field_value_to_text(item)
        if clean_value:
            tracking[clean_key] = clean_value[:PUBLIC_MAX_TRACKING_TEXT]
    return tracking


def _submission_idempotency_key(campaign: LeadCaptureCampaign, idempotency_key: str | None) -> str:
    clean_key = " ".join(str(idempotency_key or "").split()).strip()
    if clean_key:
        return f"lead-capture:{campaign.id}:{clean_key[:160]}"
    return f"lead-capture:{campaign.id}:{secrets.token_urlsafe(16)}"


def _submission_placeholder_phone(campaign: LeadCaptureCampaign, scoped_idempotency_key: str) -> str:
    """Return a valid internal phone placeholder for forms that do not ask phone."""
    seed = f"{campaign.id}:{scoped_idempotency_key}".encode()
    digest = hashlib.sha256(seed).hexdigest()
    digits = "".join(str(int(char, 16) % 10) for char in digest[:18])
    return f"0000{digits}"


def _submission_contact(command: PublicSubmissionCommand, answers: dict[str, Any]) -> tuple[str, str, str | None]:
    full_name = (
        command.full_name
        or _answer_value(answers, "full_name", "name", "nombre", "nombre_completo")
    )
    phone = command.phone or _answer_value(answers, "phone", "phone_number", "whatsapp", "telefono", "celular")
    email = command.email or _answer_value(answers, "email", "correo", "mail")
    clean_email = normalize_email(email or "") if email else None
    return " ".join((full_name or "").split()).strip(), phone, clean_email


def _submission_phone_missing(submission: LeadCaptureSubmission) -> bool:
    value = submission.tracking.get(SUBMISSION_PHONE_MISSING_TRACKING_KEY)
    return str(value or "").strip().lower() == "true"


def _raw_row_for_submission(campaign: LeadCaptureCampaign, submission: LeadCaptureSubmission) -> dict[str, str]:
    display_phone = "" if _submission_phone_missing(submission) else submission.normalized_phone or submission.phone
    raw: dict[str, str] = {
        "id": submission.id,
        "created_time": format_timestamp_seconds(submission.created_at) or "",
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "campaign_slug": campaign.public_slug,
        "full_name": submission.full_name or "",
        "phone_number": display_phone,
        "email": submission.email or "",
    }
    for key, value in submission.answers.items():
        if isinstance(value, list):
            raw[str(key)] = ", ".join(str(item) for item in value)
        else:
            raw[str(key)] = str(value or "")
    return raw


def _queue_deliveries_for_submission(
    *,
    campaign: LeadCaptureCampaign,
    submission: LeadCaptureSubmission,
) -> list[ClientLeadDelivery]:
    sources = ensure_campaign_delivery_sources(campaign)
    if not sources:
        return []
    raw_row = _raw_row_for_submission(campaign, submission)
    deliveries: list[ClientLeadDelivery] = []
    for source in sources:
        block_reason = ""
        lead_phone = raw_row.get("phone_number", "")
        if _submission_phone_missing(submission):
            block_reason = "lead_phone_missing"
        elif not normalize_phone(lead_phone):
            block_reason = "lead_phone_invalid"
        elif not normalize_phone(source.recipient_phone):
            block_reason = "recipient_phone_invalid"

        wa_link = build_wa_link(phone=lead_phone)
        notification_text = build_notification_text(
            source,
            name=submission.full_name or "",
            phone=lead_phone,
            email=submission.email,
            wa_link=wa_link,
            context_text=build_context_text_from_row(source, raw_row),
        )
        delivery, _created = ClientLeadDelivery.upsert_from_sheet_row(
            source=source,
            source_row_key=f"campaign-submission:{submission.id}",
            row_number=0,
            raw_row=raw_row,
            full_name=submission.full_name,
            phone_number=lead_phone,
            email=submission.email,
            created_time=submission.created_at,
            wa_link=wa_link,
            notification_text=notification_text,
            block_reason=block_reason or None,
        )
        deliveries.append(delivery)
    return deliveries


def _track_meta_event(
    *,
    request: Request,
    campaign: LeadCaptureCampaign,
    submission: LeadCaptureSubmission,
) -> LeadCaptureSubmission:
    if not campaign.meta_events_enabled:
        return LeadCaptureSubmission.update_delivery_and_meta(
            submission.id,
            meta_event_status="disabled",
        ) or submission

    tracking = submission.tracking
    user_data = build_user_data(
        email=submission.email,
        phone=submission.normalized_phone or submission.phone,
        client_ip_address=request.client.host if request.client else None,
        client_user_agent=request.headers.get("user-agent"),
        fbp=str(tracking.get("fbp") or request.cookies.get("_fbp") or ""),
        fbc=str(tracking.get("fbc") or request.cookies.get("_fbc") or ""),
    )
    result = send_meta_conversion_event(
        pixel_id=campaign.meta_pixel_id,
        event_name=campaign.meta_event_name,
        event_id=submission.meta_event_id or submission.id,
        event_source_url=_public_url(request, campaign),
        user_data=user_data,
        custom_data={
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "client_id": campaign.client_id,
            "lead_capture_submission_id": submission.id,
        },
        test_event_code=campaign.meta_test_event_code,
    )
    PlatformEvent.add(
        event_type=f"lead_capture.meta_event_{result.status}",
        lifecycle_stage="lead_capture",
        target_type="lead_capture_submission",
        target_id=submission.id,
        funnel_id=campaign.funnel_id,
        severity="info" if result.status in {"sent", "disabled"} else "warning",
        source="public_campaign_form",
        actor="system",
        summary=f"Meta CAPI event {result.status} for {campaign.name}.",
        payload=result.model_dump(mode="json"),
        idempotency_key=f"lead-capture-meta:{submission.id}",
    )
    return LeadCaptureSubmission.update_delivery_and_meta(
        submission.id,
        meta_event_id=result.event_id,
        meta_event_status=result.status,
        meta_event_response=result.model_dump(mode="json"),
    ) or submission


@campaigns_router.post("/clients/converted")
async def create_converted_client(command: ConvertedClientCommand) -> dict[str, Any]:
    """Create or reuse a converted Workstation client."""
    return create_or_reuse_converted_client(command)


@campaigns_router.get("/clients")
async def list_campaign_clients(
    query: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """List converted clients available for campaign linking."""
    clean_query = (query or "").strip().lower()
    clients = []
    for client in WorkstationClient.list_recent(limit=limit):
        payload = _client_payload(client)
        haystack = json.dumps(payload, ensure_ascii=False).lower()
        if clean_query and clean_query not in haystack:
            continue
        clients.append(payload)
    return {"count": len(clients), "clients": clients}


@campaigns_router.get("/meta/defaults", response_model=CampaignMetaDefaultsResponse)
async def get_campaign_meta_defaults() -> CampaignMetaDefaultsResponse:
    """Return the automatic Meta tracking defaults used by owned campaign forms."""
    pixel_id, source = _default_meta_pixel_id()
    return CampaignMetaDefaultsResponse(
        meta_events_available=bool(pixel_id),
        meta_event_name=DEFAULT_META_EVENT_NAME,
        pixel_source=source,
        pixel_label=_meta_pixel_label(pixel_id),
    )


@campaigns_router.get("/geo/search")
async def search_campaign_geo(
    country_code: str = Query(default="AR", min_length=2, max_length=2),
    kind: str = Query(default="city", pattern="^(region|city)$"),
    q: str = Query(default="", max_length=96),
    limit: int = Query(default=CAMPAIGN_GEO_SEARCH_LIMIT, ge=1, le=25),
) -> dict[str, Any]:
    """Search campaign geography suggestions for Meta targeting selectors."""
    try:
        country = _clean_country_code(country_code)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    query = " ".join(q.split()).strip()
    meta_suggestions, meta_error = _meta_geo_suggestions(country=country, kind=kind, query=query, limit=limit)
    fallback_suggestions = _fallback_geo_suggestions(country=country, kind=kind, query=query, limit=limit)
    suggestions = meta_suggestions or fallback_suggestions
    return {
        "country_code": country,
        "kind": kind,
        "query": query,
        "source": "meta" if meta_suggestions else "local",
        "meta_error": meta_error,
        "suggestions": suggestions[:limit],
    }


@campaigns_router.get("")
async def list_campaigns(
    request: Request,
    client_id: str | None = None,
    status: str | None = None,
    query: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """List owned lead-capture campaigns."""
    rows = LeadCaptureCampaign.list_recent(client_id=client_id, status=status, query=query, limit=limit)
    return {
        "count": len(rows),
        "campaigns": [_campaign_payload(row, request=request) for row in rows],
    }


@campaigns_router.post("")
async def create_campaign(request: Request, command: LeadCaptureCampaignCommand) -> dict[str, Any]:
    """Create one owned lead-capture campaign."""
    client_id = (command.client_id or "").strip()
    if not client_id and command.client is not None:
        client_payload = create_or_reuse_converted_client(command.client)
        client_id = str(client_payload["client"]["id"])
    linked_client = _validate_campaign_client_link(client_id, command.status)
    funnel_id = command.client.funnel_id if command.client else (linked_client.funnel_id if linked_client else "contadores")
    meta_optimization_enabled = _requested_meta_optimization_enabled(
        command.meta_optimization,
        command.meta_optimize_for_pixel,
    )
    meta_events_enabled = bool(command.meta_events_enabled or meta_optimization_enabled)
    meta_pixel_id = _campaign_meta_pixel_id(command.meta_pixel_id, events_enabled=meta_events_enabled)
    if meta_optimization_enabled and not meta_pixel_id:
        raise HTTPException(status_code=400, detail="Meta pixel is required to optimize ad sets by Lead event.")

    platform_campaign_id = ""
    if command.stage_platform_campaign and client_id:
        try:
            platform_campaign = _stage_platform_ad_campaign(
                command,
                client_id=client_id,
                funnel_id=funnel_id,
                meta_pixel_id=meta_pixel_id,
                meta_events_enabled=meta_events_enabled,
                meta_optimization_enabled=meta_optimization_enabled,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        platform_campaign_id = platform_campaign.id

    campaign_info, location_label = _campaign_info_with_geo(command)
    try:
        campaign_info = _campaign_info_with_delivery(
            campaign_info,
            command.delivery_config,
            client_id=client_id,
        )
        campaign_info = _campaign_info_with_meta_optimization(
            campaign_info,
            command.meta_optimization,
            pixel_id=meta_pixel_id,
            event_name=command.meta_event_name or DEFAULT_META_EVENT_NAME,
            enabled=meta_optimization_enabled,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        campaign = LeadCaptureCampaign.add(
            client_id=client_id,
            platform_ad_campaign_id=platform_campaign_id,
            funnel_id=funnel_id,
            name=command.name,
            status=command.status,
            public_slug=command.public_slug or _default_public_campaign_slug(platform_campaign_id),
            daily_budget_usd=command.daily_budget_usd,
            budget_currency=command.budget_currency,
            location=location_label,
            campaign_info=campaign_info,
            creative_brief=command.creative_brief or "",
            form_schema=command.form_schema,
            thank_you_title=command.thank_you_title,
            thank_you_body=command.thank_you_body,
            destination_url=command.destination_url or "",
            meta_pixel_id=meta_pixel_id,
            meta_event_name=command.meta_event_name or DEFAULT_META_EVENT_NAME,
            meta_events_enabled=meta_events_enabled,
            meta_test_event_code=command.meta_test_event_code or "",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    if not campaign.destination_url:
        campaign = LeadCaptureCampaign.update(campaign.id, destination_url=_public_url(request, campaign)) or campaign
    sources = ensure_campaign_delivery_sources(campaign)
    if sources and campaign.client_lead_source_id != sources[0].id:
        campaign = LeadCaptureCampaign.update(campaign.id, client_lead_source_id=sources[0].id) or campaign

    PlatformEvent.add(
        event_type="lead_capture_campaign.created",
        lifecycle_stage="lead_capture",
        target_type="lead_capture_campaign",
        target_id=campaign.id,
        funnel_id=campaign.funnel_id,
        source="campaign_api",
        actor="operator",
        summary=f"Owned campaign created: {campaign.name}.",
        payload={"public_url": _public_url(request, campaign), "client_id": campaign.client_id},
        idempotency_key=f"lead-capture-campaign-created:{campaign.id}",
    )
    return {"campaign": _campaign_payload(campaign, request=request)}


@campaigns_router.get("/{campaign_id}")
async def get_campaign(request: Request, campaign_id: str) -> dict[str, Any]:
    """Return one owned campaign."""
    return {"campaign": _campaign_payload(_get_campaign_or_404(campaign_id), request=request, include_submissions=True)}


@campaigns_router.patch("/{campaign_id}")
async def patch_campaign(
    request: Request,
    campaign_id: str,
    command: LeadCaptureCampaignPatchCommand,
) -> dict[str, Any]:
    """Patch one owned lead-capture campaign."""
    current = _get_campaign_or_404(campaign_id)
    updates = command.model_dump(exclude_unset=True)
    delivery_config = updates.pop("delivery_config", None)
    meta_optimization = updates.pop("meta_optimization", None)
    meta_optimize_for_pixel = updates.pop("meta_optimize_for_pixel", None)
    next_client_id = str(updates.get("client_id", current.client_id) or "").strip()
    next_status = str(updates.get("status", current.status) or "draft").strip().lower()
    linked_client = _validate_campaign_client_link(next_client_id, next_status)
    if "client_id" in updates and linked_client is not None:
        updates["funnel_id"] = linked_client.funnel_id
    current_meta_optimization = _campaign_meta_optimization_config(current)
    meta_optimization_changed = (
        meta_optimization is not None
        or meta_optimize_for_pixel is not None
        or "meta_pixel_id" in updates
        or "meta_event_name" in updates
        or "meta_events_enabled" in updates
    )
    default_meta_optimization_enabled = bool(current_meta_optimization.get("enabled"))
    if (
        updates.get("meta_events_enabled") is False
        and meta_optimization is None
        and meta_optimize_for_pixel is None
    ):
        default_meta_optimization_enabled = False
    next_meta_optimization_enabled = _requested_meta_optimization_enabled(
        meta_optimization,
        meta_optimize_for_pixel,
        default=default_meta_optimization_enabled,
    )
    if next_meta_optimization_enabled:
        updates["meta_events_enabled"] = True
    next_meta_enabled = bool(updates.get("meta_events_enabled", current.meta_events_enabled))
    if not next_meta_enabled:
        next_meta_optimization_enabled = False
    requested_pixel_id = updates.get("meta_pixel_id", current.meta_pixel_id)
    if (next_meta_enabled or next_meta_optimization_enabled) and not _clean_meta_pixel_id(requested_pixel_id):
        updates["meta_pixel_id"] = _campaign_meta_pixel_id(None, events_enabled=True)
        requested_pixel_id = updates["meta_pixel_id"]
    if next_meta_optimization_enabled and not _clean_meta_pixel_id(requested_pixel_id):
        raise HTTPException(status_code=400, detail="Meta pixel is required to optimize ad sets by Lead event.")
    if "meta_event_name" in updates and not str(updates.get("meta_event_name") or "").strip():
        updates["meta_event_name"] = DEFAULT_META_EVENT_NAME
    if delivery_config is not None:
        try:
            updates["campaign_info"] = _campaign_info_with_delivery(
                updates.get("campaign_info") if isinstance(updates.get("campaign_info"), dict) else current.campaign_info,
                delivery_config,
                client_id=next_client_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    if meta_optimization_changed:
        updates["campaign_info"] = _campaign_info_with_meta_optimization(
            updates.get("campaign_info") if isinstance(updates.get("campaign_info"), dict) else current.campaign_info,
            meta_optimization if meta_optimization is not None else current_meta_optimization,
            pixel_id=_clean_meta_pixel_id(requested_pixel_id),
            event_name=str(updates.get("meta_event_name", current.meta_event_name) or DEFAULT_META_EVENT_NAME),
            enabled=next_meta_optimization_enabled,
        )
    try:
        campaign = LeadCaptureCampaign.update(campaign_id, **updates)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    sources = ensure_campaign_delivery_sources(campaign)
    if sources and campaign.client_lead_source_id != sources[0].id:
        campaign = LeadCaptureCampaign.update(campaign.id, client_lead_source_id=sources[0].id) or campaign
    return {"campaign": _campaign_payload(campaign, request=request)}


@campaigns_router.post("/{campaign_id}/delivery-source")
async def refresh_campaign_delivery_source(request: Request, campaign_id: str) -> dict[str, Any]:
    """Create or refresh the Delivery source for one owned campaign."""
    campaign = _get_campaign_or_404(campaign_id)
    sources = ensure_campaign_delivery_sources(campaign)
    if not sources:
        raise HTTPException(status_code=400, detail="Campaign delivery needs at least one valid contact.")
    campaign = LeadCaptureCampaign.get_by_id(campaign.id) or campaign
    return {
        "campaign": _campaign_payload(campaign, request=request),
        "sources": [build_source_response(source).model_dump(mode="json") for source in sources],
    }


@campaigns_router.get("/{campaign_id}/submissions")
async def list_campaign_submissions(
    campaign_id: str,
    limit: int = Query(default=500, ge=1, le=1000),
) -> dict[str, Any]:
    """List public form submissions for one campaign."""
    campaign = _get_campaign_or_404(campaign_id)
    submissions = LeadCaptureSubmission.list_by_campaign(campaign.id, limit=limit)
    submissions = list(reversed(submissions))
    return {
        "campaign_id": campaign.id,
        "count": len(submissions),
        "submissions": [_submission_payload(item) for item in submissions],
    }


@campaigns_router.post("/{campaign_id}/meta/stage")
async def stage_campaign_meta_plan(request: Request, campaign_id: str) -> dict[str, Any]:
    """Stage or link the local PlatformAdCampaign record used before Meta publish."""
    campaign = _get_campaign_or_404(campaign_id)
    meta_optimization = _campaign_meta_optimization_config(campaign)
    creative_testing = {
        "destination_url": _public_url(request, campaign),
        "default_status": "PAUSED",
        "meta_events_enabled": campaign.meta_events_enabled,
        "meta_optimization": meta_optimization,
    }
    creative_benchmark = {"source": "owned_campaign_form", "campaign_info": campaign.campaign_info}
    target_segments = _campaign_meta_target_segments(campaign.campaign_info, campaign.location)
    if campaign.platform_ad_campaign_id and PlatformAdCampaign.get_by_id(campaign.platform_ad_campaign_id):
        platform_campaign = PlatformAdCampaign.update(
            campaign.platform_ad_campaign_id,
            client_id=campaign.client_id,
            funnel_id=campaign.funnel_id,
            budget_daily_usd=campaign.daily_budget_usd,
            budget_currency=campaign.budget_currency,
            target_segments=target_segments,
            angles=[campaign.creative_brief] if campaign.creative_brief else [],
            creative_benchmark=creative_benchmark,
            creative_testing=creative_testing,
        )
    else:
        platform_campaign = PlatformAdCampaign.add(
            client_id=campaign.client_id,
            funnel_id=campaign.funnel_id,
            status="draft",
            objective="lead_capture_form",
            budget_daily_usd=campaign.daily_budget_usd,
            budget_currency=campaign.budget_currency,
            target_segments=target_segments,
            angles=[campaign.creative_brief] if campaign.creative_brief else [],
            creative_benchmark=creative_benchmark,
            creative_testing=creative_testing,
            approval_status="not_requested",
            idempotency_key=f"lead-capture:{campaign.id}",
        )
        campaign = LeadCaptureCampaign.update(campaign.id, platform_ad_campaign_id=platform_campaign.id) or campaign
    return {
        "campaign": _campaign_payload(campaign, request=request),
        "platform_ad_campaign": {
            "id": platform_campaign.id if platform_campaign else "",
            "status": platform_campaign.status if platform_campaign else "",
            "approval_status": platform_campaign.approval_status if platform_campaign else "",
            "next_steps": [
                "Use sync_meta_inventory to confirm ad account, pixel, Page, and WhatsApp assets.",
                "Use stage_meta_publish_plan and preflight_meta_publish_plan before any live Meta write.",
                "Start Meta objects PAUSED and execute only after approval plus META_MARKETING_LIVE_WRITES_ENABLED=true.",
            ],
        },
    }


@public_campaigns_router.get("/c/{public_slug}")
async def redirect_public_campaign_form(public_slug: str) -> RedirectResponse:
    """Redirect slashless public campaign URLs to the form root."""
    _get_public_campaign_or_404(public_slug)
    return RedirectResponse(url=f"/c/{public_slug}/", status_code=307)


@public_campaigns_router.get("/c/{public_slug}/")
async def serve_public_campaign_form(request: Request, public_slug: str) -> HTMLResponse:
    """Serve a mobile-first public campaign form."""
    campaign = _get_public_campaign_or_404(public_slug)
    payload = _public_campaign_payload(campaign, request=request)
    return HTMLResponse(render_public_form_html(payload))


@public_campaigns_router.get("/api/public/campaigns/{public_slug}")
async def get_public_campaign(request: Request, public_slug: str) -> dict[str, Any]:
    """Return public form config for one active campaign."""
    return {"campaign": _public_campaign_payload(_get_public_campaign_or_404(public_slug), request=request)}


@public_campaigns_router.post("/api/public/campaigns/{public_slug}/submissions")
async def submit_public_campaign_form(
    request: Request,
    public_slug: str,
    command: PublicSubmissionCommand,
) -> dict[str, Any]:
    """Accept one public campaign form submission and queue Delivery."""
    campaign = _get_public_campaign_or_404(public_slug)
    if command.honeypot:
        return _public_submission_receipt(campaign=campaign, spam=True)

    scoped_idempotency_key = _submission_idempotency_key(campaign, command.idempotency_key)
    duplicate = LeadCaptureSubmission.get_by_idempotency_key(scoped_idempotency_key)
    if duplicate is not None:
        return _public_submission_receipt(campaign=campaign, submission=duplicate, duplicate=True)

    answers = _normalize_submission_answers(campaign, command)
    tracking = _normalize_tracking(command.tracking)
    full_name, phone, email = _submission_contact(command, answers)
    normalized_phone = normalize_phone(phone)
    if phone and not normalized_phone:
        raise HTTPException(status_code=400, detail="WhatsApp is invalid.")
    storage_phone = phone if normalized_phone else _submission_placeholder_phone(campaign, scoped_idempotency_key)
    if not normalized_phone:
        tracking[SUBMISSION_PHONE_MISSING_TRACKING_KEY] = "true"
    else:
        phone_duplicate = LeadCaptureSubmission.get_latest_by_campaign_phone(campaign.id, phone)
        if phone_duplicate is not None:
            return _public_submission_receipt(campaign=campaign, submission=phone_duplicate, duplicate=True)
    try:
        submission = LeadCaptureSubmission.add(
            campaign_id=campaign.id,
            client_id=campaign.client_id,
            idempotency_key=scoped_idempotency_key,
            full_name=full_name,
            phone=storage_phone,
            email=email,
            answers=answers,
            tracking=tracking,
            meta_event_status="pending",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    deliveries = _queue_deliveries_for_submission(campaign=campaign, submission=submission)
    delivery = deliveries[0] if deliveries else None
    if delivery is not None:
        submission = LeadCaptureSubmission.update_delivery_and_meta(
            submission.id,
            client_lead_delivery_id=delivery.id,
        ) or submission
    submission = _track_meta_event(request=request, campaign=campaign, submission=submission)

    PlatformEvent.add(
        event_type="lead_capture_submission.created",
        lifecycle_stage="lead_capture",
        target_type="lead_capture_campaign",
        target_id=campaign.id,
        funnel_id=campaign.funnel_id,
        source="public_campaign_form",
        actor="visitor",
        summary=f"New lead captured for {campaign.name}.",
        payload={
            "submission_id": submission.id,
            "client_id": campaign.client_id,
            "delivery_id": delivery.id if delivery else "",
            "delivery_ids": [item.id for item in deliveries],
            "delivery_status": (
                delivery.delivery_status.value
                if delivery and hasattr(delivery.delivery_status, "value")
                else (str(delivery.delivery_status) if delivery else "")
            ),
        },
        idempotency_key=f"lead-capture-submission:{submission.id}",
    )
    return _public_submission_receipt(
        campaign=campaign,
        submission=submission,
        delivery_queued=any(item.delivery_status == ClientLeadDeliveryStatus.PENDING for item in deliveries),
    )


def render_public_form_html(campaign: dict[str, Any]) -> str:
    """Render a self-contained public lead form."""
    payload_json = json.dumps(campaign, ensure_ascii=False).replace("</", "<\\/")
    title = escape(str(campaign.get("name") or "Consulta"))
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #242423;
      color: #f3eee6;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; min-height: 100vh; background: #242423; }}
    main {{ min-height: 100dvh; display: grid; place-items: stretch; padding: 0; }}
    .form-shell {{ width: min(100%, 1040px); min-height: 100dvh; display: grid; grid-template-rows: auto auto 1fr; overflow: hidden; margin: 0 auto; border: 0; border-radius: 0; background: transparent; box-shadow: none; }}
    .header {{ display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 28px clamp(24px, 7vw, 82px) 16px; border-bottom: 0; }}
    .eyebrow {{ margin: 0; font-size: 11px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; color: #85827b; }}
    h1 {{ max-width: 46ch; margin: 0; overflow: hidden; color: #b7b1a7; font-size: clamp(14px, 1.8vw, 18px); font-weight: 650; line-height: 1.12; letter-spacing: 0; text-overflow: ellipsis; white-space: nowrap; }}
    .progress {{ height: 2px; margin: 0 clamp(24px, 7vw, 82px); background: #383735; }}
    .progress > div {{ height: 100%; width: 0%; background: #f3eee6; transition: width .28s cubic-bezier(.16, 1, .3, 1); }}
    form {{ display: grid; align-content: center; min-height: 0; padding: clamp(52px, 11vw, 132px) clamp(28px, 9vw, 112px) clamp(28px, 7vw, 72px); }}
    .step {{ display: none; min-height: 420px; align-content: center; }}
    .step.active {{ display: grid; animation: step-in .32s cubic-bezier(.16, 1, .3, 1); }}
    label {{ display: block; max-width: 820px; color: #f3eee6; font-size: clamp(32px, 5vw, 52px); font-weight: 500; line-height: 1.12; letter-spacing: 0; margin: 0 0 clamp(34px, 5vw, 56px); }}
    label::before {{ content: attr(data-number); min-width: 30px; min-height: 30px; display: inline-flex; align-items: center; justify-content: center; margin-right: 16px; transform: translateY(-4px); border-radius: 7px; background: #f3eee6; color: #242423; font-size: 16px; font-weight: 850; line-height: 1; vertical-align: middle; }}
    input, textarea, select {{ width: 100%; min-height: 68px; border: 0; border-bottom: 2px solid #d8d3ca; border-radius: 0; padding: 12px 0; font: inherit; font-size: clamp(27px, 4vw, 40px); font-weight: 450; color: #f3eee6; caret-color: #f3eee6; background: transparent; }}
    textarea {{ min-height: 150px; resize: vertical; line-height: 1.25; }}
    input::placeholder, textarea::placeholder {{ color: #6f6d68; }}
    input:focus, textarea:focus, select:focus {{ outline: none; border-color: #f3eee6; }}
    .options {{ display: grid; gap: 11px; max-width: 620px; }}
    .option {{ min-height: 58px; border: 1px solid #5d5a54; border-radius: 8px; padding: 0 18px; font-size: 18px; background: transparent; color: #f3eee6; cursor: pointer; text-align: left; transition: transform .18s cubic-bezier(.16, 1, .3, 1), border-color .18s ease, background .18s ease; }}
    .option:hover {{ transform: translateY(-1px); border-color: #f3eee6; background: #2d2c2a; }}
    .option.selected {{ border-color: #f3eee6; background: #f3eee6; color: #242423; }}
    .actions {{ display: grid; grid-template-columns: minmax(92px, auto) minmax(180px, 260px) minmax(92px, auto); align-items: center; justify-content: center; gap: 14px; margin-top: clamp(32px, 5vw, 60px); }}
    button {{ min-height: 58px; border: 0; border-radius: 8px; padding: 0 24px; font: inherit; font-weight: 800; cursor: pointer; transition: transform .18s cubic-bezier(.16, 1, .3, 1), opacity .18s ease; }}
    button:active {{ transform: translateY(1px) scale(.99); }}
    .back {{ justify-self: end; background: transparent; color: #aaa49b; }}
    .next, .submit {{ grid-column: 2; justify-self: stretch; display: inline-flex; align-items: center; justify-content: center; gap: 10px; background: #f3eee6; color: #242423; box-shadow: none; }}
    .next span, .submit span {{ display: inline-flex; align-items: center; font-size: 1.18em; line-height: 1; transform: translateY(-1px); }}
    .next:disabled, .submit:disabled {{ opacity: .58; cursor: not-allowed; box-shadow: none; }}
    .error {{ min-height: 22px; color: #f0a18d; font-size: 14px; font-weight: 700; margin-top: 12px; }}
    .thanks {{ display: none; align-content: center; min-height: 420px; padding: clamp(32px, 8vw, 86px); }}
    .thanks.active {{ display: block; }}
    .thanks h2 {{ margin: 0 0 12px; color: #f3eee6; font-size: clamp(34px, 7vw, 62px); line-height: 1; letter-spacing: 0; }}
    .thanks p {{ max-width: 46ch; margin: 0; color: #b7b1a7; font-size: 19px; line-height: 1.45; }}
    .hidden {{ position: absolute; left: -9999px; width: 1px; height: 1px; opacity: 0; }}
    @keyframes step-in {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
    @media (max-width: 520px) {{
      main {{ padding: 0; place-items: stretch; }}
      .form-shell {{ min-height: 100dvh; border: 0; border-radius: 0; box-shadow: none; }}
      .header {{ display: grid; padding: 22px 20px 16px; }}
      h1 {{ white-space: normal; }}
      .progress {{ margin: 0 20px; }}
      form {{ padding: 34px 24px 22px; }}
      .step {{ min-height: calc(100dvh - 246px); }}
      label {{ font-size: clamp(29px, 8.8vw, 42px); }}
      label::before {{ min-width: 27px; min-height: 27px; margin-right: 11px; font-size: 14px; transform: translateY(-3px); }}
      input, textarea, select {{ font-size: 26px; }}
      .actions {{ position: sticky; bottom: 0; grid-template-columns: 58px minmax(0, 1fr) 58px; gap: 10px; background: linear-gradient(180deg, rgba(36, 36, 35, .68), #242423 38%); padding-top: 14px; }}
      .next, .submit {{ min-height: 64px; font-size: 18px; }}
      .back {{ width: 58px; min-height: 58px; padding: 0; overflow: hidden; color: transparent; }}
      .back::before {{ content: "\\2190"; color: #aaa49b; font-size: 27px; line-height: 1; }}
    }}
  </style>
</head>
<body>
  <main>
    <section class="form-shell">
      <div class="header">
        <p class="eyebrow">Consulta</p>
        <h1 id="campaignTitle"></h1>
      </div>
      <div class="progress" aria-hidden="true"><div id="progressBar"></div></div>
      <form id="leadForm" novalidate>
        <input class="hidden" autocomplete="off" name="company_website" id="companyWebsite">
        <div id="steps"></div>
        <div class="error" id="error"></div>
        <div class="actions">
          <button type="button" class="back" id="backBtn">Atras</button>
          <button type="button" class="next" id="nextBtn">Siguiente <span aria-hidden="true">&rarr;</span></button>
          <button type="submit" class="submit" id="submitBtn">Enviar <span aria-hidden="true">&rarr;</span></button>
        </div>
      </form>
      <div class="thanks" id="thanks">
        <h2 id="thanksTitle"></h2>
        <p id="thanksBody"></p>
      </div>
    </section>
  </main>
  <script>
    const campaign = {payload_json};
    const metaTracking = campaign.meta || {{}};
    const fields = campaign.form_schema?.fields || [];
    const state = {{ index: 0, answers: {{}}, idempotencyKey: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) }};
    const stepsEl = document.getElementById("steps");
    const progressBar = document.getElementById("progressBar");
    const backBtn = document.getElementById("backBtn");
    const nextBtn = document.getElementById("nextBtn");
    const submitBtn = document.getElementById("submitBtn");
    const errorEl = document.getElementById("error");
    const htmlEscapes = {{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }};
    document.getElementById("campaignTitle").textContent = campaign.name || "Consulta";

    function installMetaPixel() {{
      if (!metaTracking.events_enabled || !metaTracking.pixel_id) return;
      if (!window.fbq) {{
        (function(f, b, e, v, n, t, s) {{
          n = f.fbq = function() {{
            n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
          }};
          if (!f._fbq) f._fbq = n;
          n.push = n;
          n.loaded = true;
          n.version = "2.0";
          n.queue = [];
          t = b.createElement(e);
          t.async = true;
          t.src = v;
          s = b.getElementsByTagName(e)[0];
          s.parentNode.insertBefore(t, s);
        }})(window, document, "script", "https://connect.facebook.net/en_US/fbevents.js");
      }}
      window.fbq("init", metaTracking.pixel_id);
      window.fbq("track", "PageView");
    }}
    function trackMetaLead(payload) {{
      if (!metaTracking.events_enabled || !window.fbq || payload?.duplicate || !payload?.submission?.id) return;
      window.fbq("track", metaTracking.event_name || "Lead", {{}}, {{ eventID: String(payload.submission.id) }});
    }}
    function escapeHtml(value) {{
      return String(value ?? "").replace(/[&<>"']/g, (char) => htmlEscapes[char]);
    }}
    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, "&#96;");
    }}
    function fieldInput(field) {{
      const id = `field-${{field.id}}`;
      const safeId = escapeAttr(id);
      const safePlaceholder = escapeAttr(field.placeholder || "");
      const safeFieldId = escapeAttr(field.id);
      if (field.type === "textarea") return `<textarea id="${{safeId}}" placeholder="${{safePlaceholder}}"></textarea>`;
      if (field.type === "yes_no") return `<div class="options" data-field="${{safeFieldId}}"><button type="button" class="option" data-value="Si">Si</button><button type="button" class="option" data-value="No">No</button></div>`;
      if (field.type === "select" || field.type === "multi_select") {{
        const options = (field.options || []).map((option) => `<button type="button" class="option" data-value="${{escapeAttr(option)}}">${{escapeHtml(option)}}</button>`).join("");
        return `<div class="options" data-field="${{safeFieldId}}" data-multi="${{field.type === "multi_select"}}">${{options}}</div>`;
      }}
      const inputType = field.type === "phone" ? "tel" : "text";
      const autocomplete = field.type === "email" ? "email" : field.type === "phone" ? "tel" : "name";
      const inputMode = field.type === "email" ? "email" : field.type === "phone" ? "tel" : "text";
      return `<input id="${{safeId}}" type="${{inputType}}" inputmode="${{inputMode}}" autocomplete="${{autocomplete}}" placeholder="${{safePlaceholder}}">`;
    }}

    function renderSteps() {{
      stepsEl.innerHTML = fields.map((field, idx) => `
        <section class="step" data-index="${{idx}}" data-field="${{escapeAttr(field.id)}}">
          <label for="field-${{escapeAttr(field.id)}}" data-number="${{idx + 1}}">${{escapeHtml(field.label || field.id)}}${{field.required ? " *" : ""}}</label>
          ${{fieldInput(field)}}
        </section>
      `).join("");
      stepsEl.querySelectorAll(".options").forEach((group) => {{
        group.querySelectorAll(".option").forEach((button) => {{
          button.addEventListener("click", () => {{
            const fieldId = group.dataset.field;
            const multi = group.dataset.multi === "true";
            if (multi) {{
              button.classList.toggle("selected");
              state.answers[fieldId] = Array.from(group.querySelectorAll(".selected")).map((item) => item.dataset.value);
            }} else {{
              group.querySelectorAll(".option").forEach((item) => item.classList.remove("selected"));
              button.classList.add("selected");
              state.answers[fieldId] = button.dataset.value || "";
            }}
          }});
        }});
      }});
    }}

    function currentField() {{ return fields[state.index]; }}
    function currentValue() {{
      const field = currentField();
      if (!field) return "";
      const direct = document.getElementById(`field-${{field.id}}`);
      if (direct) return direct.value.trim();
      const value = state.answers[field.id];
      return Array.isArray(value) ? value.join(", ").trim() : String(value || "").trim();
    }}
    function saveCurrent() {{
      const field = currentField();
      if (!field) return;
      const direct = document.getElementById(`field-${{field.id}}`);
      if (direct) state.answers[field.id] = direct.value.trim();
    }}
    function validCurrent() {{
      const field = currentField();
      if (!field || !field.required) return true;
      return Boolean(currentValue());
    }}
    function showStep() {{
      errorEl.textContent = "";
      document.querySelectorAll(".step").forEach((step) => step.classList.toggle("active", Number(step.dataset.index) === state.index));
      const last = state.index >= fields.length - 1;
      backBtn.style.display = state.index === 0 ? "none" : "inline-flex";
      nextBtn.style.display = last ? "none" : "inline-flex";
      submitBtn.style.display = last ? "inline-flex" : "none";
      progressBar.style.width = `${{fields.length ? ((state.index + 1) / fields.length) * 100 : 100}}%`;
    }}
    function goNext() {{
      if (!validCurrent()) {{ errorEl.textContent = "Completa este dato para seguir."; return; }}
      saveCurrent();
      state.index = Math.min(fields.length - 1, state.index + 1);
      showStep();
    }}
    function submitCurrentStep() {{
      if (state.index >= fields.length - 1) {{
        document.getElementById("leadForm").requestSubmit();
        return;
      }}
      goNext();
    }}
    backBtn.addEventListener("click", () => {{ saveCurrent(); state.index = Math.max(0, state.index - 1); showStep(); }});
    nextBtn.addEventListener("click", goNext);
    document.getElementById("leadForm").addEventListener("keydown", (event) => {{
      if (event.key !== "Enter" || event.isComposing) return;
      const tagName = event.target?.tagName?.toLowerCase();
      if (tagName === "textarea" && !event.metaKey && !event.ctrlKey) return;
      event.preventDefault();
      submitCurrentStep();
    }});
    document.getElementById("leadForm").addEventListener("submit", async (event) => {{
      event.preventDefault();
      if (!validCurrent()) {{ errorEl.textContent = "Completa este dato para enviar."; return; }}
      saveCurrent();
      submitBtn.disabled = true;
      errorEl.textContent = "";
      const body = {{
        answers: state.answers,
        idempotency_key: state.idempotencyKey,
        honeypot: document.getElementById("companyWebsite").value,
        tracking: {{
          href: window.location.href,
          referrer: document.referrer,
          fbp: document.cookie.match(/(?:^|; )_fbp=([^;]+)/)?.[1] || "",
          fbc: document.cookie.match(/(?:^|; )_fbc=([^;]+)/)?.[1] || ""
        }}
      }};
      try {{
        const response = await fetch(`/api/public/campaigns/${{campaign.public_slug}}/submissions`, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json", "Accept": "application/json" }},
          body: JSON.stringify(body)
        }});
        if (!response.ok) {{
          const payload = await response.json().catch(() => ({{ detail: "No se pudo enviar." }}));
          throw new Error(payload.detail || "No se pudo enviar.");
        }}
        const payload = await response.json();
        trackMetaLead(payload);
        document.getElementById("leadForm").style.display = "none";
        document.getElementById("thanksTitle").textContent = payload.thank_you?.title || campaign.thank_you_title || "Gracias";
        document.getElementById("thanksBody").textContent = payload.thank_you?.body || campaign.thank_you_body || "";
        document.getElementById("thanks").classList.add("active");
        progressBar.style.width = "100%";
      }} catch (error) {{
        submitBtn.disabled = false;
        errorEl.textContent = error.message || "No se pudo enviar.";
      }}
    }});
    installMetaPixel();
    renderSteps();
    showStep();
  </script>
</body>
</html>"""
