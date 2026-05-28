"""File-backed funnel definitions for Konecta niche funnels."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.database import DATA_DIR, normalize_email
from backend.lead_template_utils import opener_template_name_for_funnel, opener_text_template_for_funnel

FunnelKind = Literal["campaign", "inbox"]
StrategyDelivery = Literal["link", "video"]

CONTADORES_FUNNEL_ID = "contadores"
GENERAL_INBOX_FUNNEL_ID = "general"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FUNNELS_SEED_CONFIG_PATH = REPO_ROOT / "config" / "default-funnels.json"


def slugify_funnel_id(value: str) -> str:
    """Normalize one funnel id to a small stable slug."""
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "funnel"


def normalize_whatsapp_referral_source_id(value: str | None) -> str:
    """Normalize one Meta Click-to-WhatsApp source id."""
    return (value or "").strip()


def get_funnels_config_path() -> Path:
    """Return the file used by the UI and Codex to edit funnels."""
    raw_path = (os.getenv("FUNNELS_CONFIG_PATH", "") or "").strip()
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else Path.cwd() / path
    return DATA_DIR / "funnels.json"


def get_funnels_seed_config_path() -> Path:
    """Return the versioned seed file used before local overrides exist."""
    raw_path = (os.getenv("FUNNELS_SEED_CONFIG_PATH", "") or "").strip()
    if raw_path:
        path = Path(raw_path)
        return path if path.is_absolute() else Path.cwd() / path
    return DEFAULT_FUNNELS_SEED_CONFIG_PATH


class FunnelStrategyDefinition(BaseModel):
    """One configurable strategy for a funnel step."""

    step: str = "loom"
    id: str
    label: str
    weight: int = Field(default=100, ge=0, le=100)
    delivery: StrategyDelivery = "video"
    sequence_step: str = "loom_video"
    message_text: str = ""
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None

    @field_validator("step", "id", "sequence_step")
    @classmethod
    def normalize_slug_field(cls, value: str) -> str:
        """Keep machine ids stable and easy to inspect."""
        return slugify_funnel_id(value).replace("-", "_")

    @field_validator("label", "message_text", "media_type", "media_path", "media_caption")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        """Strip freeform values."""
        if value is None:
            return None
        return value.strip()


class FunnelDefinition(BaseModel):
    """Complete configuration for one niche funnel."""

    id: str
    label: str
    kind: FunnelKind = "campaign"
    enabled: bool = True
    sheet_url: str | None = None
    sheet_gid: str | None = None
    sheet_source_filter: str | None = None
    sheet_poll_seconds: int = Field(default=30, ge=30)
    template_language: str = "es"
    opener_text: str
    opener_template_name: str | None = None
    opener_followup_text: str
    opener_followup_template_name: str | None = None
    manual_ping_text: str = ""
    manual_ping_template_name: str | None = None
    loom_intro_text: str
    loom_url: str = ""
    video_check_text: str
    calendly_intro_text: str
    calendly_base_url: str = ""
    alert_emails: list[str] = Field(default_factory=list)
    whatsapp_referral_source_ids: list[str] = Field(default_factory=list)
    initial_reply_quiet_seconds: int = Field(default=30, ge=1)
    post_loom_min_seconds: int = Field(default=600, ge=60)
    post_loom_quiet_seconds: int = Field(default=30, ge=1)
    strategies: list[FunnelStrategyDefinition] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        """Normalize the public funnel id."""
        return slugify_funnel_id(value)

    @field_validator(
        "label",
        "template_language",
        "opener_text",
        "opener_followup_text",
        "manual_ping_text",
        "loom_intro_text",
        "loom_url",
        "video_check_text",
        "calendly_intro_text",
        "calendly_base_url",
    )
    @classmethod
    def strip_text(cls, value: str) -> str:
        """Strip text fields."""
        return (value or "").strip()

    @field_validator("calendly_base_url")
    @classmethod
    def normalize_calendly_base_url(cls, value: str) -> str:
        """Keep booking URLs stable without choosing a product URL in code."""
        return (value or "").strip().rstrip("/")

    @field_validator(
        "sheet_url",
        "sheet_gid",
        "sheet_source_filter",
        "opener_template_name",
        "opener_followup_template_name",
        "manual_ping_template_name",
    )
    @classmethod
    def strip_nullable_text(cls, value: str | None) -> str | None:
        """Normalize blank optional strings to null."""
        clean_value = (value or "").strip()
        return clean_value or None

    @field_validator("alert_emails")
    @classmethod
    def normalize_alert_emails(cls, values: list[str]) -> list[str]:
        """Keep only valid email recipients."""
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            email = normalize_email(str(value))
            if not email or email in seen:
                continue
            seen.add(email)
            normalized.append(email)
        return normalized

    @field_validator("whatsapp_referral_source_ids")
    @classmethod
    def normalize_whatsapp_referral_source_ids(cls, values: list[str]) -> list[str]:
        """Keep one clean list of CTWA ad/post source ids."""
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            source_id = normalize_whatsapp_referral_source_id(str(value))
            if not source_id or source_id in seen:
                continue
            seen.add(source_id)
            normalized.append(source_id)
        return normalized

    @model_validator(mode="after")
    def normalize_known_opener_copy(self) -> "FunnelDefinition":
        """Keep built-in opener templates on the latest name/country version."""
        self.opener_text = opener_text_template_for_funnel(self.id, self.opener_text)
        self.opener_template_name = opener_template_name_for_funnel(self.id, self.opener_template_name)
        return self


class FunnelListResponse(BaseModel):
    """Response payload for funnel definitions."""

    seed_config_path: str
    config_path: str
    config_errors: list[str] = Field(default_factory=list)
    funnels: list[FunnelDefinition]


class FunnelConfigReadResult(BaseModel):
    """Parsed funnel config plus operator-facing validation errors."""

    funnels: list[FunnelDefinition] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _read_config_file_result(path: Path) -> FunnelConfigReadResult:
    """Read file-backed funnels with a forgiving parser."""
    if not path.exists():
        return FunnelConfigReadResult()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as reason:
        return FunnelConfigReadResult(errors=[f"Could not read {path}: {reason}"])
    except json.JSONDecodeError as reason:
        return FunnelConfigReadResult(
            errors=[f"Could not parse {path}: invalid JSON at line {reason.lineno}, column {reason.colno}."]
        )
    raw_funnels = payload.get("funnels", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_funnels, list):
        return FunnelConfigReadResult(errors=[f"{path} must contain a top-level funnels array or a JSON array."])

    funnels: list[FunnelDefinition] = []
    errors: list[str] = []
    for index, raw_item in enumerate(raw_funnels):
        try:
            funnels.append(FunnelDefinition.model_validate(raw_item))
        except Exception as reason:
            errors.append(f"{path} funnels[{index}] was ignored: {reason}")
            continue
    return FunnelConfigReadResult(funnels=funnels, errors=errors)


def list_funnels() -> list[FunnelDefinition]:
    """Return every configured funnel from the seed file plus local overrides."""
    funnels, _errors = list_funnels_with_config_errors()
    return funnels


def list_funnels_with_config_errors() -> tuple[list[FunnelDefinition], list[str]]:
    """Return configured funnels and any non-fatal file parser errors."""
    by_id: dict[str, FunnelDefinition] = {}
    seed_result = _read_config_file_result(get_funnels_seed_config_path())
    for funnel in seed_result.funnels:
        by_id[funnel.id] = funnel
    config_result = _read_config_file_result(get_funnels_config_path())
    for funnel in config_result.funnels:
        by_id[funnel.id] = funnel
    return sorted(by_id.values(), key=_funnel_sort_key), [*seed_result.errors, *config_result.errors]


def _funnel_sort_key(item: FunnelDefinition) -> tuple[int, str]:
    """Keep campaign tabs predictable and put the general inbox last."""
    if item.id == CONTADORES_FUNNEL_ID:
        return (0, item.label.casefold())
    if item.kind == "inbox":
        return (2, item.label.casefold())
    return (1, item.label.casefold())


def get_funnel(funnel_id: str = CONTADORES_FUNNEL_ID) -> FunnelDefinition | None:
    """Return one configured funnel."""
    clean_id = slugify_funnel_id(funnel_id)
    for funnel in list_funnels():
        if funnel.id == clean_id:
            return funnel
    return None


def list_funnels_by_whatsapp_referral_source_id(source_id: str | None) -> list[FunnelDefinition]:
    """Return funnels configured for one Click-to-WhatsApp ad/post source id."""
    clean_source_id = normalize_whatsapp_referral_source_id(source_id)
    if not clean_source_id:
        return []
    return [
        funnel
        for funnel in list_funnels()
        if clean_source_id in funnel.whatsapp_referral_source_ids
    ]


def get_file_backed_funnel(funnel_id: str = CONTADORES_FUNNEL_ID) -> FunnelDefinition | None:
    """Return one funnel from the seed-plus-override file-backed config."""
    return get_funnel(funnel_id)


def get_funnel_override(funnel_id: str = CONTADORES_FUNNEL_ID) -> FunnelDefinition | None:
    """Return one funnel only when the per-server override defines it."""
    clean_id = slugify_funnel_id(funnel_id)
    for funnel in _read_config_file_result(get_funnels_config_path()).funnels:
        if funnel.id == clean_id:
            return funnel
    return None


def get_contadores_funnel() -> FunnelDefinition:
    """Return the Contadores funnel definition."""
    funnel = get_funnel(CONTADORES_FUNNEL_ID)
    if funnel is not None:
        return funnel
    fallback = next((item for item in list_funnels() if item.kind == "campaign"), None)
    if fallback is not None:
        return fallback
    raise RuntimeError(
        f"No campaign funnel is configured. Add one to {get_funnels_seed_config_path()} or {get_funnels_config_path()}."
    )


def save_funnels(funnels: list[FunnelDefinition]) -> list[FunnelDefinition]:
    """Persist funnel definitions to the shared JSON file."""
    path = get_funnels_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized: dict[str, FunnelDefinition] = {}
    for funnel in funnels:
        normalized[funnel.id] = funnel
    items = sorted(normalized.values(), key=_funnel_sort_key)
    payload = {
        "version": 1,
        "funnels": [item.model_dump(mode="json") for item in items],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return list_funnels()


def upsert_funnel(funnel: FunnelDefinition) -> FunnelDefinition:
    """Create or replace one funnel in the shared config file."""
    by_id = {item.id: item for item in list_funnels()}
    by_id[funnel.id] = funnel
    save_funnels(list(by_id.values()))
    saved = get_funnel(funnel.id)
    if saved is None:
        raise RuntimeError("Funnel was not saved.")
    return saved
