"""Runtime settings exposed to operators without leaking secrets."""

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
class RuntimeFunnelSettings:
    """Non-secret readiness state for one configured funnel."""

    id: str
    label: str
    kind: str
    enabled: bool
    sheet_url_configured: bool
    sheet_gid: str
    sheet_poll_seconds: int

    @property
    def sheet_configured(self) -> bool:
        """Return True when the funnel has enough sheet config to import leads."""
        return self.sheet_url_configured and bool(self.sheet_gid)

    def readiness_issues(self) -> list[str]:
        """Return missing per-funnel fields that block sheet sync."""
        issues: list[str] = []
        if not self.sheet_url_configured:
            issues.append(f"{self.id}: sheet_url is empty.")
        if not self.sheet_gid:
            issues.append(f"{self.id}: sheet_gid is empty.")
        return issues

    def public_dict(self) -> dict[str, object]:
        """Serialize funnel readiness without exposing the sheet URL."""
        return {
            "id": self.id,
            "label": self.label,
            "kind": self.kind,
            "enabled": self.enabled,
            "sheet_configured": self.sheet_configured,
            "sheet_url_configured": self.sheet_url_configured,
            "sheet_gid": self.sheet_gid,
            "sheet_poll_seconds": self.sheet_poll_seconds,
        }


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
    funnel_config_path: str
    funnels: list[RuntimeFunnelSettings]

    @property
    def enabled_campaign_funnels(self) -> list[RuntimeFunnelSettings]:
        """Return enabled campaign funnels that can run automation."""
        return [
            funnel
            for funnel in self.funnels
            if funnel.enabled and funnel.kind == "campaign"
        ]

    @property
    def ready_campaign_funnels(self) -> list[RuntimeFunnelSettings]:
        """Return enabled campaign funnels with sheet URL and GID configured."""
        return [
            funnel
            for funnel in self.enabled_campaign_funnels
            if funnel.sheet_configured
        ]

    def readiness_issues(self) -> list[str]:
        """Return missing config needed before any campaign funnel can sync."""
        if self.ready_campaign_funnels:
            return []
        if not self.enabled_campaign_funnels:
            return ["No enabled campaign funnel is configured."]
        issues = ["No enabled campaign funnel has both sheet_url and sheet_gid."]
        for funnel in self.enabled_campaign_funnels:
            issues.extend(funnel.readiness_issues())
        return issues

    def public_dict(self) -> dict[str, object]:
        """Serialize settings without exposing secrets."""
        issues = self.readiness_issues()
        ready_campaign_ids = [funnel.id for funnel in self.ready_campaign_funnels]
        enabled_campaign_ids = [funnel.id for funnel in self.enabled_campaign_funnels]
        first_ready_funnel = self.ready_campaign_funnels[0] if self.ready_campaign_funnels else None
        return {
            "enabled": self.enabled,
            "ready": not issues,
            "readiness_issues": issues,
            "sheet_configured": bool(ready_campaign_ids),
            "sheet_gid": self.sheet_gid or (first_ready_funnel.sheet_gid if first_ready_funnel else ""),
            "sheet_poll_seconds": self.sheet_poll_seconds,
            "loom_url_configured": bool(self.loom_url),
            "calendly_base_url": self.calendly_base_url,
            "alert_emails": self.alert_emails,
            "funnel_config_path": self.funnel_config_path,
            "enabled_campaign_funnels": enabled_campaign_ids,
            "ready_campaign_funnels": ready_campaign_ids,
            "funnels": [funnel.public_dict() for funnel in self.funnels],
        }


def _read_funnel_settings() -> tuple[str, list[RuntimeFunnelSettings]]:
    """Read non-secret funnel settings from the shared config file."""
    from backend.funnel_config import get_funnels_config_path, list_funnels

    return str(get_funnels_config_path()), [
        RuntimeFunnelSettings(
            id=funnel.id,
            label=funnel.label,
            kind=funnel.kind,
            enabled=funnel.enabled,
            sheet_url_configured=bool(funnel.sheet_url),
            sheet_gid=funnel.sheet_gid or "",
            sheet_poll_seconds=funnel.sheet_poll_seconds,
        )
        for funnel in list_funnels()
    ]


def get_runtime_settings() -> RuntimeSettings:
    """Read runtime settings from the current environment."""
    funnel_config_path, funnels = _read_funnel_settings()
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
        funnel_config_path=funnel_config_path,
        funnels=funnels,
    )
