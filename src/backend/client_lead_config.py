"""File-backed Client Lead Delivery source configuration."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.database import (
    CLIENT_LEAD_DEFAULT_COLUMN_MAPPING,
    CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE,
    CLIENT_LEAD_DEFAULT_TEMPLATE_NAME,
    DATA_DIR,
    ClientLeadSource,
    normalize_client_lead_context_field_mapping,
    normalize_client_lead_column_mapping,
    normalize_phone,
)

logger = logging.getLogger(__name__)

DEFAULT_CLIENT_LEAD_SOURCES_SEED_CONFIG_PATH = Path("config/default-client-lead-sources.json")


def slugify_client_lead_source_id(value: str) -> str:
    """Normalize one Delivery source id to a stable slug."""
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "client-lead-source"


def _resolve_config_path(raw_path: str | None, *, default_path: Path) -> Path:
    """Resolve a repo-relative or absolute config path."""
    clean_path = (raw_path or "").strip()
    if not clean_path:
        return default_path
    path = Path(clean_path)
    return path if path.is_absolute() else Path.cwd() / path


def get_client_lead_sources_seed_config_path() -> Path:
    """Return the versioned default Delivery source config path."""
    return _resolve_config_path(
        os.getenv("CLIENT_LEAD_SOURCES_SEED_CONFIG_PATH"),
        default_path=Path.cwd() / DEFAULT_CLIENT_LEAD_SOURCES_SEED_CONFIG_PATH,
    )


def get_client_lead_sources_config_path() -> Path:
    """Return the server-local editable Delivery source config path."""
    return _resolve_config_path(
        os.getenv("CLIENT_LEAD_SOURCES_CONFIG_PATH"),
        default_path=DATA_DIR / "client-lead-sources.json",
    )


def normalize_client_lead_column_mapping_override(value: Any) -> dict[str, str]:
    """Normalize sheet-level column mapping overrides without filling defaults."""
    if isinstance(value, str):
        try:
            value = json.loads(value or "{}")
        except json.JSONDecodeError:
            value = {}
    if not isinstance(value, dict):
        return {}

    mapping: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = " ".join(str(raw_key or "").split()).strip()
        clean_value = " ".join(str(raw_value or "").split()).strip()
        if key and clean_value:
            mapping[key] = clean_value
    return mapping


class ClientLeadRecipientDefinition(BaseModel):
    """One WhatsApp recipient for a file-backed Delivery source."""

    id: str | None = None
    name: str | None = None
    phone: str = ""

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str | None) -> str | None:
        """Normalize recipient id when provided."""
        if not (value or "").strip():
            return None
        return slugify_client_lead_source_id(value or "")

    @field_validator("name", "phone")
    @classmethod
    def strip_text(cls, value: str | None) -> str:
        """Strip freeform recipient fields."""
        return (value or "").strip()


class ClientLeadSheetDefinition(BaseModel):
    """One Google Sheet/tab feeding a file-backed Delivery source."""

    id: str | None = None
    label: str | None = None
    sheet_url: str = ""
    sheet_gid: str | None = None
    sheet_tab_name: str | None = None
    meta_page_id: str | None = None
    meta_lead_form_id: str | None = None
    column_mapping: dict[str, str] | None = None
    context_fields: list[str] | None = None
    context_field_mapping: dict[str, str] | None = None

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str | None) -> str | None:
        """Normalize sheet ids when provided."""
        if not (value or "").strip():
            return None
        return slugify_client_lead_source_id(value or "")

    @field_validator("label", "sheet_url", "sheet_gid", "sheet_tab_name", "meta_page_id", "meta_lead_form_id")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        """Strip optional sheet fields."""
        if value is None:
            return None
        return str(value).strip()

    @field_validator("context_fields")
    @classmethod
    def strip_context_fields(cls, value: list[str] | None) -> list[str] | None:
        """Normalize simple context field lists."""
        if value is None:
            return None
        return [" ".join(str(item or "").split()).strip() for item in value if str(item or "").strip()]

    @field_validator("column_mapping")
    @classmethod
    def normalize_column_mapping(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """Normalize optional sheet-level column mapping overrides."""
        if value is None:
            return None
        return normalize_client_lead_column_mapping_override(value)

    @field_validator("context_field_mapping")
    @classmethod
    def normalize_context_field_mapping(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """Normalize spreadsheet context field mapping."""
        if value is None:
            return None
        return normalize_client_lead_context_field_mapping(value)

    def resolved_context_field_mapping(self) -> dict[str, str] | None:
        """Return sheet-level context mapping from explicit mapping or field list."""
        if self.context_field_mapping is not None:
            return self.context_field_mapping
        if self.context_fields is None:
            return None
        return normalize_client_lead_context_field_mapping(self.context_fields)


class ClientLeadSourceFileEntry(BaseModel):
    """One DB-ready Delivery source loaded from config files."""

    id: str
    label: str
    enabled: bool = True
    sheet_url: str = ""
    sheet_gid: str | None = None
    sheet_tab_name: str | None = None
    meta_page_id: str = ""
    meta_lead_form_id: str = ""
    sheet_poll_seconds: int = Field(default=10, ge=5)
    recipient_name: str | None = None
    recipient_phone: str = ""
    template_name: str = CLIENT_LEAD_DEFAULT_TEMPLATE_NAME
    template_language: str = CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE
    column_mapping: dict[str, str] = Field(default_factory=lambda: dict(CLIENT_LEAD_DEFAULT_COLUMN_MAPPING))
    context_field_mapping: dict[str, str] | None = None


class ClientLeadSourceDefinition(BaseModel):
    """File schema for one configurable Delivery source."""

    id: str
    label: str
    enabled: bool = True
    sheet_url: str | None = ""
    sheet_gid: str | None = None
    sheet_tab_name: str | None = None
    meta_page_id: str | None = None
    meta_lead_form_id: str | None = None
    sheets: list[ClientLeadSheetDefinition] = Field(default_factory=list)
    sheet_poll_seconds: int = Field(default=10, ge=5)
    recipient_name: str | None = None
    recipient_phone: str | None = ""
    recipients: list[ClientLeadRecipientDefinition] = Field(default_factory=list)
    template_name: str | None = CLIENT_LEAD_DEFAULT_TEMPLATE_NAME
    template_language: str | None = CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE
    column_mapping: dict[str, str] = Field(default_factory=lambda: dict(CLIENT_LEAD_DEFAULT_COLUMN_MAPPING))
    context_fields: list[str] | None = None
    context_field_mapping: dict[str, str] | None = None

    @field_validator("id")
    @classmethod
    def normalize_id(cls, value: str) -> str:
        """Normalize source ids."""
        return slugify_client_lead_source_id(value)

    @field_validator(
        "label",
        "sheet_url",
        "sheet_gid",
        "sheet_tab_name",
        "meta_page_id",
        "meta_lead_form_id",
        "recipient_name",
        "recipient_phone",
        "template_name",
        "template_language",
    )
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        """Normalize blank strings to empty optional values."""
        if value is None:
            return None
        return str(value).strip()

    @field_validator("column_mapping")
    @classmethod
    def normalize_column_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        """Normalize spreadsheet column mapping."""
        return normalize_client_lead_column_mapping(value)

    @field_validator("context_fields")
    @classmethod
    def strip_context_fields(cls, value: list[str] | None) -> list[str] | None:
        """Normalize simple context field lists."""
        if value is None:
            return None
        return [" ".join(str(item or "").split()).strip() for item in value if str(item or "").strip()]

    @field_validator("context_field_mapping")
    @classmethod
    def normalize_context_field_mapping(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """Normalize spreadsheet context field mapping."""
        if value is None:
            return None
        return normalize_client_lead_context_field_mapping(value)

    def resolved_context_field_mapping(self) -> dict[str, str] | None:
        """Return source-level context mapping from explicit mapping or field list."""
        if self.context_field_mapping is not None:
            return self.context_field_mapping
        if self.context_fields is None:
            return None
        return normalize_client_lead_context_field_mapping(self.context_fields)

    def expand_recipients(self) -> list[ClientLeadSourceFileEntry]:
        """Return DB-ready sources, expanding multiple sheets and recipients."""
        sheets = self.sheets or [
            ClientLeadSheetDefinition(
                id=None,
                label=None,
                sheet_url=self.sheet_url or "",
                sheet_gid=self.sheet_gid,
                sheet_tab_name=self.sheet_tab_name,
            )
        ]
        recipients = self.recipients or [
            ClientLeadRecipientDefinition(name=self.recipient_name, phone=self.recipient_phone or "")
        ]
        entries: list[ClientLeadSourceFileEntry] = []
        has_multiple_sheets = len(sheets) > 1
        has_multiple_recipients = len(recipients) > 1
        source_context_mapping = self.resolved_context_field_mapping()

        for sheet in sheets:
            sheet_suffix = sheet.id or slugify_client_lead_source_id(
                sheet.label or sheet.sheet_tab_name or sheet.sheet_gid or sheet.sheet_url
            )
            sheet_label = sheet.label or sheet.sheet_tab_name or sheet.sheet_gid or sheet_suffix
            for recipient in recipients:
                recipient_suffix = recipient.id or slugify_client_lead_source_id(
                    normalize_phone(recipient.phone) or recipient.name or recipient.phone
                )
                suffixes = []
                if has_multiple_sheets:
                    suffixes.append(sheet_suffix)
                if has_multiple_recipients:
                    suffixes.append(recipient_suffix)
                source_id = self.id if not suffixes else "-".join([self.id, *suffixes])

                label_parts = [self.label]
                if has_multiple_sheets:
                    label_parts.append(sheet_label)
                if has_multiple_recipients:
                    label_parts.append(recipient.name or recipient.phone or recipient_suffix)

                sheet_column_mapping = normalize_client_lead_column_mapping(
                    {**self.column_mapping, **(sheet.column_mapping or {})}
                )
                sheet_context_mapping = sheet.resolved_context_field_mapping()
                entries.append(
                    ClientLeadSourceFileEntry(
                        id=source_id,
                        label=" · ".join(label_parts),
                        enabled=self.enabled,
                        sheet_url=sheet.sheet_url or "",
                        sheet_gid=sheet.sheet_gid or None,
                        sheet_tab_name=sheet.sheet_tab_name or None,
                        meta_page_id=sheet.meta_page_id or self.meta_page_id or "",
                        meta_lead_form_id=sheet.meta_lead_form_id or self.meta_lead_form_id or "",
                        sheet_poll_seconds=self.sheet_poll_seconds,
                        recipient_name=recipient.name or self.recipient_name,
                        recipient_phone=recipient.phone,
                        template_name=(self.template_name or CLIENT_LEAD_DEFAULT_TEMPLATE_NAME).strip(),
                        template_language=(self.template_language or CLIENT_LEAD_DEFAULT_TEMPLATE_LANGUAGE).strip() or "es",
                        column_mapping=sheet_column_mapping,
                        context_field_mapping=(
                            sheet_context_mapping if sheet_context_mapping is not None else source_context_mapping
                        ),
                    )
                )
        return entries


class ClientLeadConfigSyncResult(BaseModel):
    """Result of syncing file-backed Delivery sources into the DB."""

    seed_config_path: str
    config_path: str
    configured: int = 0
    upserted: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def read_client_lead_sources_config_file(path: Path) -> tuple[list[ClientLeadSourceDefinition], list[str]]:
    """Read one Delivery source config file with a forgiving parser."""
    if not path.exists():
        return [], []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [f"{path}: {exc}"]

    raw_sources = payload.get("sources", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw_sources, list):
        return [], [f"{path}: expected a list or an object with a sources list"]

    sources: list[ClientLeadSourceDefinition] = []
    errors: list[str] = []
    for index, raw_item in enumerate(raw_sources, start=1):
        try:
            sources.append(ClientLeadSourceDefinition.model_validate(raw_item))
        except Exception as exc:
            errors.append(f"{path}: source #{index}: {exc}")
    return sources, errors


def list_file_backed_client_lead_sources() -> tuple[list[ClientLeadSourceFileEntry], list[str]]:
    """Return expanded source entries from seed and server-local config files."""
    by_id: dict[str, ClientLeadSourceFileEntry] = {}
    errors: list[str] = []

    for path in [get_client_lead_sources_seed_config_path(), get_client_lead_sources_config_path()]:
        sources, read_errors = read_client_lead_sources_config_file(path)
        errors.extend(read_errors)
        for source in sources:
            for entry in source.expand_recipients():
                by_id[entry.id] = entry

    return sorted(by_id.values(), key=lambda item: (item.label.casefold(), item.id)), errors


def sync_client_lead_sources_from_config() -> ClientLeadConfigSyncResult:
    """Upsert every file-backed Delivery source into the database."""
    entries, errors = list_file_backed_client_lead_sources()
    result = ClientLeadConfigSyncResult(
        seed_config_path=str(get_client_lead_sources_seed_config_path()),
        config_path=str(get_client_lead_sources_config_path()),
        configured=len(entries),
        errors=list(errors),
    )
    for entry in entries:
        try:
            source = ClientLeadSource.upsert(
                source_id=entry.id,
                label=entry.label,
                enabled=entry.enabled,
                sheet_url=entry.sheet_url,
                sheet_gid=entry.sheet_gid,
                sheet_tab_name=entry.sheet_tab_name,
                meta_page_id=entry.meta_page_id,
                meta_lead_form_id=entry.meta_lead_form_id,
                sheet_poll_seconds=entry.sheet_poll_seconds,
                recipient_name=entry.recipient_name,
                recipient_phone=entry.recipient_phone,
                template_name=entry.template_name,
                template_language=entry.template_language,
                column_mapping=entry.column_mapping,
                context_field_mapping=entry.context_field_mapping,
            )
        except Exception as exc:
            error = f"{entry.id}: {exc}"
            logger.warning("Could not sync file-backed Delivery source %s.", error)
            result.errors.append(error)
            continue
        result.upserted.append(source.id)
    return result
