"""Small helpers for rendering lead-specific WhatsApp templates."""

from __future__ import annotations

import re

import phonenumbers
from phonenumbers import NumberParseException

COUNTRY_NAMES = {
    "AR": "Argentina",
    "BE": "Belgica",
    "BO": "Bolivia",
    "BR": "Brasil",
    "CL": "Chile",
    "CO": "Colombia",
    "EC": "Ecuador",
    "ES": "Espana",
    "FI": "Finlandia",
    "GR": "Grecia",
    "HU": "Hungria",
    "MX": "Mexico",
    "NA": "Namibia",
    "NL": "Paises Bajos",
    "NZ": "Nueva Zelanda",
    "PA": "Panama",
    "PE": "Peru",
    "PY": "Paraguay",
    "US": "Estados Unidos",
    "UY": "Uruguay",
    "VE": "Venezuela",
    "ZM": "Zambia",
}

NAME_PREFIXES = {
    "abg",
    "abogada",
    "abogado",
    "cpa",
    "cpn",
    "dra",
    "dr",
    "estudio",
    "firma",
    "lic",
    "licda",
    "licdo",
    "sra",
    "sr",
}

BUSINESS_WORDS = {
    "abogados",
    "asesores",
    "asociados",
    "contable",
    "contables",
    "contadores",
    "consultores",
    "corporacion",
    "empresa",
    "grupo",
    "juridico",
    "legal",
    "oficina",
    "servicios",
}

FUNNEL_OPENER_TEXT_TEMPLATES = {
    "abogados": (
        "Hola {nombre}, llenaste el formulario para abogados de {pais} sobre como conseguir "
        "casos redituables a tu whatsapp. es correcto?"
    ),
    "contadores": (
        "Hola {nombre}, llenaste el formulario para contadores de {pais} sobre como conseguir "
        "clientes a tu whatsapp. es correcto?"
    ),
}

FUNNEL_OPENER_TEMPLATE_NAMES = {
    "abogados": "abogados_intro_nombre_pais_es_v1",
    "contadores": "contadores_intro_nombre_pais_es_v1",
}

LEGACY_OPENER_TEMPLATE_NAMES = {
    "abogados": {"abogados_intro_es_v1"},
    "contadores": {"contadores_intro_es_v1", "contadores_intro_es_v2"},
}

NON_DIGITS_RE = re.compile(r"\D+")
WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def clean_spaces(value: str | None) -> str:
    """Collapse whitespace and trim one string."""
    return " ".join(str(value or "").split()).strip()


def title_name(value: str) -> str:
    """Format one short name without forcing already-mixed casing."""
    if not value:
        return value
    if value.isupper() or value.islower():
        return value[:1].upper() + value[1:].lower()
    return value[:1].upper() + value[1:]


def choose_short_lead_name(full_name: str | None) -> str:
    """Choose the short WhatsApp name used in positional templates."""
    clean_name = clean_spaces(full_name)
    if not clean_name:
        return "buen dia"

    words = [match.group(0) for match in WORD_RE.finditer(clean_name)]
    if not words:
        return "buen dia"

    while words and words[0].lower().rstrip(".") in NAME_PREFIXES:
        words = words[1:]

    for word in words:
        normalized = word.lower().rstrip(".")
        if len(normalized) < 2:
            continue
        if normalized in NAME_PREFIXES or normalized in BUSINESS_WORDS:
            continue
        return title_name(word)

    return "buen dia"


def infer_country_code_from_phone(phone: str | None, normalized_phone: str | None = None) -> str:
    """Infer a two-letter country code from a WhatsApp phone."""
    raw_phone = clean_spaces(normalized_phone or phone)
    digits = NON_DIGITS_RE.sub("", raw_phone)
    if not digits:
        return "unknown"

    try:
        parsed = phonenumbers.parse(f"+{digits}", None)
    except NumberParseException:
        return "unknown"

    return phonenumbers.region_code_for_number(parsed) or "unknown"


def country_name(country_code: str) -> str:
    """Return the country display name used in Spanish WhatsApp copy."""
    return COUNTRY_NAMES.get(country_code, "Latinoamerica")


def lead_country_name(phone: str | None, normalized_phone: str | None = None) -> str:
    """Return a readable country name inferred from a lead phone."""
    return country_name(infer_country_code_from_phone(phone, normalized_phone))


def opener_text_template_for_funnel(funnel_id: str | None, configured_text: str | None) -> str:
    """Return the opener template text, upgrading old built-in funnel copy."""
    clean_funnel_id = clean_spaces(funnel_id).lower()
    clean_text = (configured_text or "").strip()
    if "{nombre}" in clean_text or "{pais}" in clean_text:
        return clean_text
    return FUNNEL_OPENER_TEXT_TEMPLATES.get(clean_funnel_id, clean_text)


def render_opener_text(
    *,
    funnel_id: str | None,
    configured_text: str | None,
    full_name: str | None,
    phone: str | None,
    normalized_phone: str | None = None,
) -> str:
    """Render the opener copy stored in the conversation transcript."""
    template = opener_text_template_for_funnel(funnel_id, configured_text)
    return template.replace("{nombre}", choose_short_lead_name(full_name)).replace(
        "{pais}",
        lead_country_name(phone, normalized_phone),
    )


def opener_template_name_for_funnel(funnel_id: str | None, configured_name: str | None) -> str | None:
    """Return the approved opener template name, upgrading legacy built-ins."""
    clean_funnel_id = clean_spaces(funnel_id).lower()
    clean_name = clean_spaces(configured_name)
    default_name = FUNNEL_OPENER_TEMPLATE_NAMES.get(clean_funnel_id)
    if not default_name:
        return clean_name or None
    if not clean_name or clean_name in LEGACY_OPENER_TEMPLATE_NAMES.get(clean_funnel_id, set()):
        return default_name
    return clean_name


def opener_template_uses_lead_params(template_name: str | None) -> bool:
    """Return True for opener templates that expect name and country params."""
    clean_name = clean_spaces(template_name)
    return clean_name in set(FUNNEL_OPENER_TEMPLATE_NAMES.values()) or "_nombre_pais_" in clean_name


def opener_template_body_params(
    *,
    full_name: str | None,
    phone: str | None,
    normalized_phone: str | None = None,
) -> list[str]:
    """Return positional params for the name/country opener template."""
    return [
        choose_short_lead_name(full_name),
        lead_country_name(phone, normalized_phone),
    ]
