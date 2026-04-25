"""Deterministic CEO audit delivery email templates and builder."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse

from backend.database import (
    DEFAULT_REPORT_WINDOW_HOURS,
    DEFAULT_REPORT_WINDOW_MINUTES,
    CompanyLanguage,
    normalize_report_window_minutes,
)

AUDIT_DELIVERY_SUBJECT_EN = "Quick analysis of your website contacts"
AUDIT_DELIVERY_SUBJECT_ES = "Analisis rapido de los contactos de tu sitio"

AUDIT_DELIVERY_BODY_EN = (
    "Hey,\n\n"
    "Below you will find an analysis we prepared for {company_name} using the contacts listed on your website ({source_url}).\n\n"
    "Analyzed contacts:\n"
    "{contact_lines}\n\n"
    "In this case we wanted to test whether your sellers were able to achieve these objectives:\n"
    "{objective_lines}\n\n"
    "What we did was: we took those contacts from your website, reached out as genuine prospects (following the path a real lead would follow), and then continued the conversations for {report_window_duration}.\n\n"
    "From those conversations, we compiled what we believe is most relevant so you can quickly understand how leads are being treated today.\n\n"
    "The report is attached in PDF format.\n\n"
    "Our proposal is simple: bring you visibility into things most owners/CEOs usually cannot see inside their own business. If this report was helpful, just reply to this email and we can discuss anything that caught your attention. I can also share solutions I have in mind for your specific case.\n\n"
    "Best,\n"
    "Konecta Labs\n"
    "konectalabs.com"
)

AUDIT_DELIVERY_BODY_ES = (
    "Hey,\n\n"
    "Debajo vas a encontrar un analisis que preparamos para {company_name} usando los contactos publicados en tu website ({source_url}).\n\n"
    "Contactos analizados:\n"
    "{contact_lines}\n\n"
    "En este caso quisimos probar si tus vendedores eran capaces de cumplir estos objetivos:\n"
    "{objective_lines}\n\n"
    "Lo que hicimos fue tomar esos contactos de tu website, hablarles como si fueramos clientes genuinos (siguiendo el path que seguiria un lead real), y luego sostener conversaciones durante {report_window_duration}.\n\n"
    "De esas conversaciones recopilamos lo que creemos que puede ser mas relevante para vos, asi tenes una idea clara de como estan siendo tratados tus leads.\n\n"
    "Te dejo adjunto el reporte en formato PDF.\n\n"
    "Nuestra propuesta es simple: aportarte valor para que puedas ver cosas que la mayoria de dueños o CEOs no suelen ver sobre sus propios negocios. Si el reporte te fue util, responde este email y conversamos sobre lo que te haya generado curiosidad; tambien te puedo comentar soluciones pensadas para tu caso particular.\n\n"
    "Saludos,\n"
    "Konecta Labs\n"
    "konectalabs.com"
)


def build_audit_delivery_pdf_filename(
    *,
    company_name: str,
    source_url: str = "",
    fallback_stem: str = "company",
) -> str:
    """Build a deterministic, filesystem-safe PDF filename for audit delivery."""
    candidate = (
        company_name.strip()
        or extract_audit_delivery_filename_source(source_url)
        or fallback_stem.strip()
        or "company"
    )
    slug = slugify_audit_delivery_filename_part(candidate)
    if not slug:
        slug = slugify_audit_delivery_filename_part(fallback_stem) or "company"
    return f"audit-{slug}.pdf"


def extract_audit_delivery_filename_source(source_url: str) -> str:
    """Extract a compact hostname fallback for filename generation."""
    raw_source_url = source_url.strip()
    if not raw_source_url:
        return ""
    parsed = urlparse(raw_source_url if "://" in raw_source_url else f"https://{raw_source_url}")
    hostname = (parsed.netloc or parsed.path).strip().lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def slugify_audit_delivery_filename_part(value: str) -> str:
    """Normalize one human label to a lowercase ASCII slug for filenames."""
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.lower())
    return re.sub(r"-{2,}", "-", cleaned).strip("-")


def build_audit_delivery_subject_reference(company_id: str | None) -> str:
    """Build one short stable subject reference for a company-specific audit thread."""
    clean_company_id = (company_id or "").strip()
    if not clean_company_id:
        return ""
    return hashlib.sha1(clean_company_id.encode("utf-8")).hexdigest()[:6]


def format_audit_delivery_subject(
    subject: str,
    *,
    company_id: str | None,
) -> str:
    """Append one stable reference so recreated companies do not collapse into old email threads."""
    clean_subject = " ".join((subject or "").split()).strip() or AUDIT_DELIVERY_SUBJECT_EN
    subject_reference = build_audit_delivery_subject_reference(company_id)
    if not subject_reference:
        return clean_subject
    return f"{clean_subject} [Ref {subject_reference}]"


def format_report_window_duration(
    report_window_minutes: int = DEFAULT_REPORT_WINDOW_MINUTES,
    *,
    company_language: CompanyLanguage | None,
) -> str:
    """Return one human-readable duration string for CEO delivery copy."""
    normalized_minutes = normalize_report_window_minutes(report_window_minutes)
    hours, minutes = divmod(normalized_minutes, 60)
    if company_language == CompanyLanguage.ES:
        parts: list[str] = []
        if hours:
            parts.append(f"{hours} hora" if hours == 1 else f"{hours} horas")
        if minutes:
            parts.append(f"{minutes} minuto" if minutes == 1 else f"{minutes} minutos")
        return " y ".join(parts) or "1 minuto"

    parts = []
    if hours:
        parts.append(f"{hours} hour" if hours == 1 else f"{hours} hours")
    if minutes:
        parts.append(f"{minutes} minute" if minutes == 1 else f"{minutes} minutes")
    return " and ".join(parts) or "1 minute"


def get_audit_delivery_email_content(
    *,
    company_id: str | None = None,
    company_language: CompanyLanguage | None,
    company_name: str,
    source_url: str,
    contact_lines: str,
    objective_lines: str,
    report_window_hours: int = DEFAULT_REPORT_WINDOW_HOURS,
    report_window_minutes: int | None = None,
) -> tuple[str, str]:
    """Return deterministic subject/body for CEO delivery email."""
    normalized_source_url = source_url.strip()
    normalized_company_name = company_name.strip() or normalized_source_url
    raw_contact_lines = contact_lines.strip()
    raw_objective_lines = objective_lines.strip()
    normalized_report_window_minutes = normalize_report_window_minutes(
        report_window_minutes,
        report_window_hours=report_window_hours,
    )
    report_window_duration = format_report_window_duration(
        normalized_report_window_minutes,
        company_language=company_language,
    )

    if company_language == CompanyLanguage.ES:
        normalized_contact_lines = raw_contact_lines or "- No se identificaron contactos activos."
        normalized_objective_lines = raw_objective_lines or "- No se definieron objetivos especificos."
        subject = format_audit_delivery_subject(
            AUDIT_DELIVERY_SUBJECT_ES.format(company_name=normalized_company_name),
            company_id=company_id,
        )
        body = AUDIT_DELIVERY_BODY_ES.format(
            company_name=normalized_company_name,
            source_url=normalized_source_url,
            contact_lines=normalized_contact_lines,
            objective_lines=normalized_objective_lines,
            report_window_duration=report_window_duration,
        )
        return subject, body

    normalized_contact_lines = raw_contact_lines or "- No active contacts were identified."
    normalized_objective_lines = raw_objective_lines or "- No specific objectives were defined."
    subject = format_audit_delivery_subject(
        AUDIT_DELIVERY_SUBJECT_EN.format(company_name=normalized_company_name),
        company_id=company_id,
    )
    body = AUDIT_DELIVERY_BODY_EN.format(
        company_name=normalized_company_name,
        source_url=normalized_source_url,
        contact_lines=normalized_contact_lines,
        objective_lines=normalized_objective_lines,
        report_window_duration=report_window_duration,
    )
    return subject, body
