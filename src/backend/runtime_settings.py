"""Runtime settings that must come from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

from backend.calendly import normalize_calendly_url


def _read_str(*names: str, default: str = "") -> str:
    """Read the first non-empty environment value."""
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        clean_value = value.strip()
        if clean_value:
            return clean_value
    return default


def _read_bool(name: str, *, default: bool) -> bool:
    """Read one boolean environment value."""
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _read_int(*names: str, default: int) -> int:
    """Read one integer environment value."""
    raw_value = _read_str(*names, default="")
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _read_alert_emails() -> list[str]:
    """Read comma-separated alert emails from the environment."""
    raw_value = _read_str("CONTADORES_ALERT_EMAILS", default="")
    return [item.strip() for item in raw_value.split(",") if item.strip()]


@dataclass(frozen=True)
class RuntimeSettings:
    """Environment-driven runtime settings safe to expose to operators."""

    enabled: bool
    sheet_url: str
    sheet_gid: str
    sheet_poll_seconds: int
    loom_url: str
    calendly_base_url: str
    alert_emails: list[str]

    def readiness_issues(self) -> list[str]:
        """Return missing config needed by the runtime."""
        issues: list[str] = []
        if not self.sheet_url:
            issues.append("CONTADORES_SHEET_URL is empty.")
        if not self.sheet_gid:
            issues.append("CONTADORES_SHEET_GID is empty.")
        return issues

    def public_dict(self) -> dict[str, object]:
        """Serialize settings without exposing secrets."""
        issues = self.readiness_issues()
        return {
            "enabled": self.enabled,
            "ready": not issues,
            "readiness_issues": issues,
            "sheet_configured": bool(self.sheet_url and self.sheet_gid),
            "sheet_gid": self.sheet_gid,
            "sheet_poll_seconds": self.sheet_poll_seconds,
            "loom_url_configured": bool(self.loom_url),
            "calendly_base_url": self.calendly_base_url,
            "alert_emails": self.alert_emails,
        }


def get_runtime_settings() -> RuntimeSettings:
    """Read runtime settings from the current environment."""
    return RuntimeSettings(
        enabled=_read_bool("CONTADORES_ENABLED", default=True),
        sheet_url=_read_str("CONTADORES_SHEET_URL", "GOOGLE_SHEET_URL", default=""),
        sheet_gid=_read_str("CONTADORES_SHEET_GID", "GOOGLE_SHEET_GID", default=""),
        sheet_poll_seconds=max(30, _read_int("CONTADORES_SHEET_POLL_SECONDS", default=30)),
        loom_url=_read_str("CONTADORES_LOOM_URL", default=""),
        calendly_base_url=normalize_calendly_url(
            _read_str(
                "CONTADORES_CALENDLY_BASE_URL",
                "CONTADORES_CALENDLY_URL",
                default="",
            )
        ),
        alert_emails=_read_alert_emails(),
    )
