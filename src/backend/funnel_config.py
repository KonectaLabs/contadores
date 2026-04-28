"""File-backed funnel definitions for Konecta niche funnels."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.database import DATA_DIR, normalize_email

FunnelKind = Literal["campaign", "inbox"]
StrategyDelivery = Literal["link", "video"]

CONTADORES_FUNNEL_ID = "contadores"
GENERAL_INBOX_FUNNEL_ID = "general"
MP4_ONLY_FUNNEL_IDS = {CONTADORES_FUNNEL_ID, "abogados"}
DEFAULT_CONTADORES_LOOM_URL = "https://www.loom.com/share/36b054dea1c94bbaa7470014c2337fca"
DEFAULT_CONTADORES_CALENDLY_URL = "https://calendly.com/yoelkravchuk/konecta-meet"
DEFAULT_CONTADORES_VIDEO_PATH = "data/contadores/videos/loom_60_seconds_captions.mp4"
DEFAULT_MANUAL_PING_TEXT = (
    "Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion"
)


def slugify_funnel_id(value: str) -> str:
    """Normalize one funnel id to a small stable slug."""
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or CONTADORES_FUNNEL_ID


def _read_bool(name: str, *, default: bool) -> bool:
    """Read one env boolean."""
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _read_int(name: str, *, default: int, minimum: int = 1) -> int:
    """Read one positive integer from env."""
    raw_value = (os.getenv(name, "") or "").strip()
    if not raw_value:
        return max(minimum, default)
    try:
        return max(minimum, int(raw_value))
    except ValueError:
        return max(minimum, default)


def _read_list(name: str) -> list[str]:
    """Read a comma-separated env list."""
    raw_value = (os.getenv(name, "") or "").strip()
    return [item.strip() for item in raw_value.split(",") if item.strip()]


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
    manual_ping_text: str = DEFAULT_MANUAL_PING_TEXT
    manual_ping_template_name: str | None = None
    loom_intro_text: str
    loom_url: str = ""
    video_check_text: str
    calendly_intro_text: str
    calendly_base_url: str
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


class FunnelListResponse(BaseModel):
    """Response payload for funnel definitions."""

    config_path: str
    funnels: list[FunnelDefinition]


def build_default_contadores_funnel() -> FunnelDefinition:
    """Return the built-in Contadores definition seeded from env."""
    return FunnelDefinition(
        id=CONTADORES_FUNNEL_ID,
        label="Contadores",
        kind="campaign",
        enabled=_read_bool("CONTADORES_ENABLED", default=True),
        sheet_url=(os.getenv("CONTADORES_SHEET_URL", "") or "").strip() or None,
        sheet_gid=(os.getenv("CONTADORES_SHEET_GID", "") or "").strip() or None,
        sheet_poll_seconds=_read_int("CONTADORES_SHEET_POLL_SECONDS", default=30, minimum=30),
        template_language="es",
        opener_text=(
            "Hola, llenaste el formulario para contadores sobre como conseguir clientes "
            "a tu whatsapp. Es correcto?"
        ),
        opener_template_name="contadores_intro_es_v2",
        opener_followup_text="Queria compartirte informacion sobre como podes obtener clientes para tu estudio contable",
        opener_followup_template_name="contadores_opener_followup_24h_es_v1",
        manual_ping_text=DEFAULT_MANUAL_PING_TEXT,
        manual_ping_template_name="contadores_manual_ping_es_v1",
        loom_intro_text=(
            "Perfecto. Te cuento rapido:\n"
            "Los contadores que trabajan con nosotros reciben un flujo de prospectos y posibles "
            "clientes que les llega directo al WhatsApp de forma automatica.\n"
            "Te invito a que veas este video donde te explicamos la propuesta a detalle:"
        ),
        loom_url=(os.getenv("CONTADORES_LOOM_URL", DEFAULT_CONTADORES_LOOM_URL) or DEFAULT_CONTADORES_LOOM_URL).strip(),
        video_check_text="conseguiste ver el video?",
        calendly_intro_text=(
            "Para avanzar solo falta -> Reunion, nos conocemos -> definimos medio de pago -> "
            "pagas 300 USD -> empezamos a trabajar para vos a las 24 horas.\n\n"
            "Elige el horario que mejor te quede:"
        ),
        calendly_base_url=(
            os.getenv("CONTADORES_CALENDLY_BASE_URL", DEFAULT_CONTADORES_CALENDLY_URL)
            or DEFAULT_CONTADORES_CALENDLY_URL
        ).strip(),
        alert_emails=_read_list("CONTADORES_ALERT_EMAILS"),
        whatsapp_referral_source_ids=[],
        initial_reply_quiet_seconds=_read_int("CONTADORES_INITIAL_REPLY_QUIET_SECONDS", default=30),
        post_loom_min_seconds=_read_int("CONTADORES_POST_LOOM_MIN_SECONDS", default=600, minimum=60),
        post_loom_quiet_seconds=_read_int("CONTADORES_POST_LOOM_QUIET_SECONDS", default=30),
        strategies=[
            FunnelStrategyDefinition(
                step="loom",
                id="loom_mp4",
                label="WhatsApp MP4",
                weight=100,
                delivery="video",
                sequence_step="loom_video",
                message_text="Video de explicacion enviado por WhatsApp.",
                media_type="video",
                media_path=DEFAULT_CONTADORES_VIDEO_PATH,
            ),
        ],
    )


def build_default_general_inbox_funnel() -> FunnelDefinition:
    """Return the built-in inbox for unmatched WhatsApp conversations."""
    return FunnelDefinition(
        id=GENERAL_INBOX_FUNNEL_ID,
        label="General",
        kind="inbox",
        enabled=True,
        sheet_url=None,
        sheet_gid=None,
        sheet_source_filter=None,
        sheet_poll_seconds=30,
        template_language="es",
        opener_text="Hola, gracias por escribirnos. Decime que necesitás y te orientamos por acá.",
        opener_template_name=None,
        opener_followup_text="Queria saber si pudiste ver mi mensaje anterior y si queres que retomemos.",
        opener_followup_template_name=None,
        manual_ping_text=DEFAULT_MANUAL_PING_TEXT,
        manual_ping_template_name=None,
        loom_intro_text="",
        loom_url="",
        video_check_text="",
        calendly_intro_text="",
        calendly_base_url="",
        alert_emails=[],
        whatsapp_referral_source_ids=[],
        initial_reply_quiet_seconds=30,
        post_loom_min_seconds=600,
        post_loom_quiet_seconds=30,
        strategies=[],
    )


def _merge_default_with_override(default: FunnelDefinition, override: FunnelDefinition) -> FunnelDefinition:
    """Overlay a file-backed definition onto the built-in default."""
    payload = default.model_dump()
    override_payload = override.model_dump(exclude_unset=True)
    payload.update(override_payload)
    return sanitize_funnel_definition(FunnelDefinition.model_validate(payload))


def sanitize_funnel_definition(funnel: FunnelDefinition) -> FunnelDefinition:
    """Remove retired campaign wiring from persisted funnel configs."""
    updates: dict[str, object] = {}
    if funnel.id == CONTADORES_FUNNEL_ID and funnel.whatsapp_referral_source_ids:
        updates["whatsapp_referral_source_ids"] = []
    if funnel.id in MP4_ONLY_FUNNEL_IDS:
        strategies = [
            strategy
            for strategy in funnel.strategies
            if strategy.id != "loom_link" and strategy.delivery != "link"
        ]
        if len(strategies) != len(funnel.strategies):
            updates["strategies"] = strategies
    if not updates:
        return funnel
    return funnel.model_copy(update=updates)


def _read_config_file(path: Path) -> list[FunnelDefinition]:
    """Read file-backed funnels with a forgiving parser."""
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_funnels = payload.get("funnels", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_funnels, list):
        return []

    funnels: list[FunnelDefinition] = []
    for raw_item in raw_funnels:
        try:
            funnels.append(sanitize_funnel_definition(FunnelDefinition.model_validate(raw_item)))
        except Exception:
            continue
    return funnels


def list_funnels() -> list[FunnelDefinition]:
    """Return every configured funnel, with Contadores and General always present."""
    default_contadores = build_default_contadores_funnel()
    default_general = build_default_general_inbox_funnel()
    by_id: dict[str, FunnelDefinition] = {
        default_contadores.id: default_contadores,
        default_general.id: default_general,
    }
    for funnel in _read_config_file(get_funnels_config_path()):
        if funnel.id == default_contadores.id:
            by_id[funnel.id] = _merge_default_with_override(default_contadores, funnel)
        elif funnel.id == default_general.id:
            by_id[funnel.id] = _merge_default_with_override(default_general, funnel)
        else:
            by_id[funnel.id] = funnel
    return sorted(by_id.values(), key=_funnel_sort_key)


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
    """Return one funnel only when it is explicitly present in the shared config file."""
    clean_id = slugify_funnel_id(funnel_id)
    for funnel in _read_config_file(get_funnels_config_path()):
        if funnel.id == clean_id:
            return funnel
    return None


def get_contadores_funnel() -> FunnelDefinition:
    """Return the Contadores funnel definition."""
    return get_funnel(CONTADORES_FUNNEL_ID) or build_default_contadores_funnel()


def save_funnels(funnels: list[FunnelDefinition]) -> list[FunnelDefinition]:
    """Persist funnel definitions to the shared JSON file."""
    path = get_funnels_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized: dict[str, FunnelDefinition] = {}
    for funnel in funnels:
        clean_funnel = sanitize_funnel_definition(funnel)
        normalized[clean_funnel.id] = clean_funnel
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
