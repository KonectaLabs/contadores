"""Static WhatsApp template definitions for operator workflows."""

from __future__ import annotations

import random
from typing import Literal

from pydantic import BaseModel, Field


class WhatsAppTemplateDefinition(BaseModel):
    """WhatsApp template metadata for creation and later runtime wiring."""

    name: str
    language: Literal["es", "en_US"]
    category: Literal["UTILITY", "MARKETING", "AUTHENTICATION"]
    parameter_format: Literal["POSITIONAL", "NAMED"] = "POSITIONAL"
    template_text: str
    template_variables: list[str] = Field(default_factory=list)
    template_id: str | None = None


class WhatsAppIntroTemplatePayload(BaseModel):
    """Resolved intro template payload for one outbound WhatsApp first message."""

    whatsapp_template_name: str
    whatsapp_template_language: Literal["es", "en_US"]
    whatsapp_template_client_name: str
    whatsapp_template_company_url: str
    rendered_text: str


KONECTA_INTRO_ES_V2 = WhatsAppTemplateDefinition(
    name="konecta_intro_es_v2",
    language="es",
    category="MARKETING",
    parameter_format="POSITIONAL",
    template_text="Hola, soy {{1}}. Encontré tu contacto en {{2}} y quería consultarte algo puntual.",
    template_variables=["1", "2"],
    template_id="1674145660118012",
)


KONECTA_INTRO_EN_V2 = WhatsAppTemplateDefinition(
    name="konecta_intro_en_v2",
    language="en_US",
    category="MARKETING",
    parameter_format="POSITIONAL",
    template_text="Hi, I’m {{1}}. I found your contact listed on {{2}} and wanted to ask you a quick question.",
    template_variables=["1", "2"],
    template_id="1519357342880659",
)


CONTADORES_INTRO_ES_V2 = WhatsAppTemplateDefinition(
    name="contadores_intro_es_v2",
    language="es",
    category="MARKETING",
    parameter_format="POSITIONAL",
    template_text="Hola, llenaste el formulario para contadores sobre como conseguir clientes a tu whatsapp. Es correcto?",
    template_id="1499601978428585",
)

CONTADORES_OPENER_FOLLOWUP_24H_ES_V1 = WhatsAppTemplateDefinition(
    name="contadores_opener_followup_24h_es_v1",
    language="es",
    category="MARKETING",
    parameter_format="NAMED",
    template_text="Queria compartirte informacion sobre como podes obtener clientes para tu estudio contable",
    template_id="2203765190420918",
)

INTRO_TEMPLATE_SENDER_NAMES_ES = [
    "Mateo",
    "Santiago",
    "Nicolas",
    "Martin",
    "Diego",
    "Juan",
    "Lucas",
    "Sebastian",
    "Alejandro",
    "Tomas",
]

INTRO_TEMPLATE_SENDER_NAMES_EN = [
    "Liam",
    "Noah",
    "Ethan",
    "Mason",
    "Lucas",
    "James",
    "William",
    "Benjamin",
    "Henry",
    "Jack",
]


WHATSAPP_TEMPLATE_REGISTRY = {
    KONECTA_INTRO_ES_V2.name: KONECTA_INTRO_ES_V2,
    KONECTA_INTRO_EN_V2.name: KONECTA_INTRO_EN_V2,
    CONTADORES_INTRO_ES_V2.name: CONTADORES_INTRO_ES_V2,
    CONTADORES_OPENER_FOLLOWUP_24H_ES_V1.name: CONTADORES_OPENER_FOLLOWUP_24H_ES_V1,
}


def get_whatsapp_template_registry() -> dict[str, WhatsAppTemplateDefinition]:
    """Return a copy-safe registry of known templates."""
    return dict(WHATSAPP_TEMPLATE_REGISTRY)


def normalize_intro_template_language(
    company_language: str | object | None,
) -> Literal["es", "en_US"]:
    """Resolve intro template language from optional company language."""
    raw_value = getattr(company_language, "value", company_language)
    normalized = str(raw_value or "").strip().lower().replace("-", "_")
    if normalized.startswith("en"):
        return "en_US"
    return "es"


def resolve_intro_template_definition(
    company_language: str | object | None,
) -> WhatsAppTemplateDefinition:
    """Resolve intro template definition using company language."""
    language = normalize_intro_template_language(company_language)
    if language == "en_US":
        return KONECTA_INTRO_EN_V2
    return KONECTA_INTRO_ES_V2


def intro_sender_name_pool(
    company_language: str | object | None,
) -> list[str]:
    """Return sender-name pool by intro template language."""
    language = normalize_intro_template_language(company_language)
    if language == "en_US":
        return INTRO_TEMPLATE_SENDER_NAMES_EN[:]
    return INTRO_TEMPLATE_SENDER_NAMES_ES[:]


def normalize_intro_sender_name(value: str) -> str:
    """Normalize sender-name text for case-insensitive comparisons."""
    return " ".join((value or "").split()).strip().casefold()


def extract_intro_sender_name(text: str) -> str | None:
    """Extract intro sender name from one persisted intro message text."""
    clean_text = " ".join((text or "").split()).strip()
    if not clean_text:
        return None
    for prefix in ("Hola, soy ", "Hi, I’m ", "Hi, I'm "):
        if not clean_text.startswith(prefix):
            continue
        sender_name = clean_text[len(prefix):].split(".", 1)[0].strip()
        if sender_name:
            return sender_name
    return None


def pick_intro_sender_name(
    *,
    company_language: str | object | None,
    excluded_names: set[str] | None = None,
) -> str:
    """Pick one intro sender name, excluding already-used names while possible."""
    pool = intro_sender_name_pool(company_language)
    if not pool:
        return "Konecta"
    normalized_excluded: set[str] = set()
    for raw_name in excluded_names or set():
        normalized_name = normalize_intro_sender_name(raw_name)
        if normalized_name:
            normalized_excluded.add(normalized_name)
    available = [
        candidate
        for candidate in pool
        if normalize_intro_sender_name(candidate) not in normalized_excluded
    ]
    candidates = available or pool
    return random.SystemRandom().choice(candidates)


def render_intro_template_text(
    *,
    template_language: Literal["es", "en_US"],
    client_name: str,
    company_url: str,
) -> str:
    """Render intro template body text used for transcript persistence consistency."""
    if template_language == "en_US":
        return (
            f"Hi, I’m {client_name}. "
            f"I found your contact listed on {company_url} and wanted to ask you a quick question."
        )
    return (
        f"Hola, soy {client_name}. "
        f"Encontré tu contacto en {company_url} y quería consultarte algo puntual."
    )


def build_intro_template_payload(
    *,
    company_language: str | object | None,
    company_url: str | None,
    client_name: str,
) -> WhatsAppIntroTemplatePayload:
    """Build resolved intro template payload + rendered text for one contact."""
    template = resolve_intro_template_definition(company_language)
    resolved_url = (company_url or "").strip() or "https://example.com"
    resolved_client_name = client_name.strip() or "Konecta"
    rendered_text = render_intro_template_text(
        template_language=template.language,
        client_name=resolved_client_name,
        company_url=resolved_url,
    )
    return WhatsAppIntroTemplatePayload(
        whatsapp_template_name=template.name,
        whatsapp_template_language=template.language,
        whatsapp_template_client_name=resolved_client_name,
        whatsapp_template_company_url=resolved_url,
        rendered_text=rendered_text,
    )
