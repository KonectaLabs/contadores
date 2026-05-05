#!/usr/bin/env python3
"""Queue the May 2026 low-ticket web page promo template."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import phonenumbers
from phonenumbers import NumberParseException
from sqlmodel import Session, select

from backend.database import (
    ContadoresLead,
    ContadoresLeadStage,
    ContadoresMessage,
    MessageDeliveryStatus,
    WorkstationClient,
    engine,
    init_db,
)
from backend.endpoints.contadores import (
    derive_effective_lead_stage,
    ensure_utc_datetime,
    parse_delivery_error_code,
)


CAMPAIGN_ID = "promo_web_profesional_20260505"
SEQUENCE_STEP = "promo_web_profesional_20260505"
TEMPLATE_NAME = "konecta_promo_web_profesional_es_v1"
TEMPLATE_LANGUAGE = "es"
DEFAULT_ALIAS_PATH = Path("data/contadores/promo-web-profesional-2026-05-05-aliases.csv")
DEFAULT_PREVIEW_PATH = Path("data/reports/promo-web-profesional-2026-05-05-preview.csv")
DEFAULT_LEDGER_PATH = Path("data/contadores/promo-web-profesional-2026-05-05-ledger.json")
TARGET_FUNNEL_IDS = ("contadores", "abogados")
PRICE_OPTIONS = (19, 29, 49, 99)
NON_DIGITS_RE = re.compile(r"\D+")
WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+")

TEXT_TEMPLATE = (
    "Hola {alias}, promo para {profession} de {country}:\n\n"
    "te construimos una pagina web moderna y profesional para mostrar tus servicios.\n\n"
    "Solo {price} USD.\n"
    "La pagas solo cuando este terminada y te guste.\n\n"
    "Si te interesa esta oferta, respondeme y te mostramos un ejemplo."
)

COUNTRY_NAMES = {
    "AR": "Argentina",
    "BE": "Belgica",
    "BO": "Bolivia",
    "BR": "Brasil",
    "CL": "Chile",
    "CO": "Colombia",
    "EC": "Ecuador",
    "ES": "España",
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

COUNTRY_PRICE_WEIGHTS = {
    "VE": (50, 25, 20, 5),
    "BO": (40, 30, 25, 5),
    "EC": (35, 30, 25, 10),
    "CO": (35, 30, 25, 10),
    "PY": (35, 30, 25, 10),
    "PE": (35, 30, 25, 10),
    "AR": (30, 30, 25, 15),
    "BR": (30, 30, 25, 15),
    "MX": (30, 30, 25, 15),
    "PA": (30, 30, 25, 15),
    "CL": (25, 25, 25, 25),
    "UY": (25, 25, 25, 25),
    "US": (25, 25, 25, 25),
    "ES": (25, 25, 25, 25),
    "BE": (25, 25, 25, 25),
    "FI": (25, 25, 25, 25),
    "GR": (25, 25, 25, 25),
    "HU": (25, 25, 25, 25),
    "NA": (25, 25, 25, 25),
    "NL": (25, 25, 25, 25),
    "NZ": (25, 25, 25, 25),
    "ZM": (25, 25, 25, 25),
}
DEFAULT_PRICE_WEIGHTS = (30, 30, 25, 15)

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


@dataclass(frozen=True)
class AliasChoice:
    alias: str
    source: str
    needs_review: bool


@dataclass(frozen=True)
class CampaignCandidate:
    lead: ContadoresLead
    alias: AliasChoice
    country_code: str
    country_name: str
    profession: str
    price: int
    text: str
    template_params: list[str]
    latest_outbound_failed: bool


def clean_spaces(value: str | None) -> str:
    """Collapse whitespace and trim one string."""
    return " ".join(str(value or "").split()).strip()


def title_name(value: str) -> str:
    """Format one short name without changing it into a full formal name."""
    if not value:
        return value
    if value.isupper() or value.islower():
        return value[:1].upper() + value[1:].lower()
    return value[:1].upper() + value[1:]


def choose_short_alias(full_name: str | None) -> AliasChoice:
    """Choose a short WhatsApp-friendly alias from a CRM full name."""
    clean_name = clean_spaces(full_name)
    if not clean_name:
        return AliasChoice(alias="buen dia", source="fallback_empty_name", needs_review=True)

    words = [match.group(0) for match in WORD_RE.finditer(clean_name)]
    if not words:
        return AliasChoice(alias="buen dia", source="fallback_no_name_words", needs_review=True)

    while words and words[0].lower().rstrip(".") in NAME_PREFIXES:
        words = words[1:]
    for word in words:
        normalized = word.lower().rstrip(".")
        if len(normalized) < 2:
            continue
        if normalized in NAME_PREFIXES or normalized in BUSINESS_WORDS:
            continue
        return AliasChoice(
            alias=title_name(word),
            source="first_personal_token",
            needs_review=False,
        )

    return AliasChoice(alias="buen dia", source="fallback_business_name", needs_review=True)


def load_alias_overrides(path: Path) -> dict[str, str]:
    """Load manually reviewed aliases keyed by lead id."""
    if not path.exists():
        return {}
    aliases: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            lead_id = clean_spaces(row.get("lead_id"))
            alias = clean_spaces(row.get("alias"))
            if lead_id and alias:
                aliases[lead_id] = alias
    return aliases


def infer_country_code(lead: ContadoresLead) -> str:
    """Infer the lead country from the normalized WhatsApp phone."""
    raw_phone = clean_spaces(lead.normalized_phone or lead.phone)
    digits = NON_DIGITS_RE.sub("", raw_phone)
    if not digits:
        return "unknown"
    try:
        parsed = phonenumbers.parse(f"+{digits}", None)
    except NumberParseException:
        return "unknown"
    return phonenumbers.region_code_for_number(parsed) or "unknown"


def country_name(country_code: str) -> str:
    """Return a readable country name for template copy."""
    return COUNTRY_NAMES.get(country_code, "Latinoamerica")


def profession_for_funnel(funnel_id: str | None) -> str:
    """Return the short profession noun used in the promo template."""
    if funnel_id == "abogados":
        return "abogados"
    if funnel_id == "contadores":
        return "contadores"
    return "profesionales"


def pick_price(lead_id: str, country_code: str) -> int:
    """Pick one deterministic weighted price for a lead."""
    weights = COUNTRY_PRICE_WEIGHTS.get(country_code, DEFAULT_PRICE_WEIGHTS)
    digest = hashlib.sha256(f"{CAMPAIGN_ID}:{lead_id}:{country_code}".encode()).hexdigest()
    cursor = int(digest[:12], 16) % sum(weights)
    running_total = 0
    for price, weight in zip(PRICE_OPTIONS, weights):
        running_total += weight
        if cursor < running_total:
            return price
    return PRICE_OPTIONS[-1]


def latest_outbound_failed(lead_id: str) -> bool:
    """Return True when the latest outbound is already a failed provider send."""
    latest = ContadoresMessage.get_latest_outbound_message(lead_id)
    return bool(latest and latest.delivery_status == MessageDeliveryStatus.FAILED)


def latest_outbound_opted_out(lead_id: str) -> bool:
    """Return True when Meta reported a marketing opt-out for the latest outbound."""
    latest = ContadoresMessage.get_latest_outbound_message(lead_id)
    return bool(latest and parse_delivery_error_code(latest.last_delivery_error) == 131050)


def list_campaign_leads() -> list[ContadoresLead]:
    """Return campaign leads from the supported professional funnels."""
    with Session(engine) as session:
        statement = (
            select(ContadoresLead)
            .where(ContadoresLead.funnel_id.in_(TARGET_FUNNEL_IDS))
            .order_by(ContadoresLead.created_at, ContadoresLead.id)
        )
        leads = list(session.exec(statement).all())
        for lead in leads:
            session.expunge(lead)
        return leads


def build_exclusion_reasons(
    lead: ContadoresLead,
    *,
    include_provider_failures: bool,
) -> list[str]:
    """Return reasons this lead should not receive the promo."""
    reasons: list[str] = []
    effective_stage = derive_effective_lead_stage(lead)
    if WorkstationClient.get_by_lead_id(lead.id) is not None:
        reasons.append("workstation_client")
    if effective_stage in {
        ContadoresLeadStage.BOOKED,
        ContadoresLeadStage.CLOSED,
        ContadoresLeadStage.ARCHIVED,
    }:
        reasons.append(effective_stage.value)
    if latest_outbound_opted_out(lead.id):
        reasons.append("marketing_opt_out")
    if not include_provider_failures and latest_outbound_failed(lead.id):
        reasons.append("latest_outbound_failed")
    if ContadoresMessage.has_outbound_sequence_step(lead.id, sequence_step=SEQUENCE_STEP):
        reasons.append("already_queued")
    if not clean_spaces(lead.normalized_phone or lead.phone):
        reasons.append("missing_phone")
    return reasons


def build_candidate(lead: ContadoresLead, alias: AliasChoice) -> CampaignCandidate:
    """Build the final rendered template payload for one lead."""
    country_code = infer_country_code(lead)
    display_country = country_name(country_code)
    profession = profession_for_funnel(lead.funnel_id)
    price = pick_price(lead.id, country_code)
    text = TEXT_TEMPLATE.format(
        alias=alias.alias,
        profession=profession,
        country=display_country,
        price=price,
    )
    return CampaignCandidate(
        lead=lead,
        alias=alias,
        country_code=country_code,
        country_name=display_country,
        profession=profession,
        price=price,
        text=text,
        template_params=[alias.alias, profession, display_country, str(price)],
        latest_outbound_failed=latest_outbound_failed(lead.id),
    )


def resolve_aliases(
    leads: list[ContadoresLead],
    *,
    alias_path: Path,
) -> dict[str, AliasChoice]:
    """Use reviewed aliases when available and generate short aliases for missing rows."""
    overrides = load_alias_overrides(alias_path)
    aliases: dict[str, AliasChoice] = {}
    for lead in leads:
        override = overrides.get(lead.id)
        if override:
            aliases[lead.id] = AliasChoice(alias=override, source="alias_file", needs_review=False)
            continue
        aliases[lead.id] = choose_short_alias(lead.full_name)
    return aliases


def write_alias_file(
    path: Path,
    *,
    leads: list[ContadoresLead],
    aliases: dict[str, AliasChoice],
) -> None:
    """Write the current alias review file without phone numbers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "lead_id",
        "funnel_id",
        "full_name",
        "alias",
        "alias_source",
        "needs_review",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            alias = aliases[lead.id]
            writer.writerow(
                {
                    "lead_id": lead.id,
                    "funnel_id": lead.funnel_id,
                    "full_name": lead.full_name or "",
                    "alias": alias.alias,
                    "alias_source": alias.source,
                    "needs_review": str(alias.needs_review).lower(),
                }
            )


def write_preview(path: Path, candidates: list[CampaignCandidate]) -> None:
    """Write a CSV preview of the exact promo rows that would be queued."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "lead_id",
        "funnel_id",
        "full_name",
        "alias",
        "country_code",
        "country",
        "profession",
        "price",
        "latest_outbound_failed",
        "template_params_json",
        "rendered_text",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(
                {
                    "lead_id": candidate.lead.id,
                    "funnel_id": candidate.lead.funnel_id,
                    "full_name": candidate.lead.full_name or "",
                    "alias": candidate.alias.alias,
                    "country_code": candidate.country_code,
                    "country": candidate.country_name,
                    "profession": candidate.profession,
                    "price": candidate.price,
                    "latest_outbound_failed": str(candidate.latest_outbound_failed).lower(),
                    "template_params_json": json.dumps(candidate.template_params, ensure_ascii=False),
                    "rendered_text": candidate.text,
                }
            )


def queue_candidate(candidate: CampaignCandidate) -> int:
    """Queue one template-backed promo message and route replies through the offer-aware bot."""
    row = ContadoresMessage.add(
        lead_id=candidate.lead.id,
        from_me=True,
        text=candidate.text,
        delivery_status=MessageDeliveryStatus.UNDELIVERED,
        sequence_step=SEQUENCE_STEP,
        whatsapp_template_name=TEMPLATE_NAME,
        whatsapp_template_language=TEMPLATE_LANGUAGE,
        whatsapp_template_body_params=candidate.template_params,
    )
    ContadoresLead.update_flow_state(
        candidate.lead.id,
        last_classification_label="active_offer_sent",
        last_classification_reason="Se envio una promo/oferta activa; el bot debe seguir esa oferta si responde.",
        automation_paused=False,
    )
    return row.id or 0


def write_ledger(path: Path, *, queued_message_ids: list[int], candidates: list[CampaignCandidate]) -> None:
    """Persist an execution ledger under data for auditability."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "campaign_id": CAMPAIGN_ID,
        "sequence_step": SEQUENCE_STEP,
        "template_name": TEMPLATE_NAME,
        "template_language": TEMPLATE_LANGUAGE,
        "executed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "queued_message_ids": queued_message_ids,
        "leads": [
            {
                "lead_id": candidate.lead.id,
                "funnel_id": candidate.lead.funnel_id,
                "alias": candidate.alias.alias,
                "country_code": candidate.country_code,
                "country": candidate.country_name,
                "profession": candidate.profession,
                "price": candidate.price,
                "template_params": candidate.template_params,
            }
            for candidate in candidates
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def print_summary(
    *,
    candidates: list[CampaignCandidate],
    exclusions: Counter[str],
    alias_path: Path,
    preview_path: Path,
    executed: bool,
    queued_message_ids: list[int],
) -> None:
    """Print a compact operator summary."""
    print(f"campaign_id={CAMPAIGN_ID}")
    print(f"template_name={TEMPLATE_NAME}")
    print(f"execute={str(executed).lower()}")
    print(f"candidate_count={len(candidates)}")
    print(f"queued_count={len(queued_message_ids)}")
    print(f"alias_path={alias_path}")
    print(f"preview_path={preview_path}")
    print(f"by_funnel={dict(Counter(candidate.lead.funnel_id for candidate in candidates))}")
    print(f"by_country={dict(Counter(candidate.country_code for candidate in candidates).most_common())}")
    print(f"by_price={dict(Counter(candidate.price for candidate in candidates).most_common())}")
    print(f"aliases_needing_review={sum(1 for candidate in candidates if candidate.alias.needs_review)}")
    print(f"exclusions={dict(exclusions)}")
    if queued_message_ids:
        print(f"queued_message_ids={queued_message_ids[:20]}")
        if len(queued_message_ids) > 20:
            print(f"queued_message_ids_more={len(queued_message_ids) - 20}")


def main() -> None:
    """Prepare or queue the campaign."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Queue real WhatsApp template messages.")
    parser.add_argument(
        "--include-provider-failures",
        action="store_true",
        help="Include leads whose latest outbound already failed at provider level.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of candidates to queue.")
    parser.add_argument("--alias-path", type=Path, default=DEFAULT_ALIAS_PATH)
    parser.add_argument("--preview-path", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER_PATH)
    args = parser.parse_args()

    init_db()
    leads = list_campaign_leads()
    aliases = resolve_aliases(leads, alias_path=args.alias_path)
    write_alias_file(args.alias_path, leads=leads, aliases=aliases)

    candidates: list[CampaignCandidate] = []
    exclusions: Counter[str] = Counter()
    for lead in leads:
        reasons = build_exclusion_reasons(
            lead,
            include_provider_failures=args.include_provider_failures,
        )
        if reasons:
            exclusions.update(reasons)
            continue
        candidates.append(build_candidate(lead, aliases[lead.id]))

    if args.limit > 0:
        candidates = candidates[: args.limit]

    write_preview(args.preview_path, candidates)

    queued_message_ids: list[int] = []
    if args.execute:
        for candidate in candidates:
            queued_message_ids.append(queue_candidate(candidate))
        write_ledger(args.ledger_path, queued_message_ids=queued_message_ids, candidates=candidates)

    print_summary(
        candidates=candidates,
        exclusions=exclusions,
        alias_path=args.alias_path,
        preview_path=args.preview_path,
        executed=args.execute,
        queued_message_ids=queued_message_ids,
    )


if __name__ == "__main__":
    main()
