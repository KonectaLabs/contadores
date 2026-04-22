from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv


SourceMode = Literal["testing", "live"]


def _load_env_once() -> None:
    load_dotenv()


def _read_str(*env_names: str, default: str = "") -> str:
    for env_name in env_names:
        value = os.getenv(env_name)
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return default


def _read_optional_int(*env_names: str) -> int | None:
    raw_value = _read_str(*env_names, default="")
    if not raw_value:
        return None
    return int(raw_value)


def _read_int(*env_names: str, default: int) -> int:
    raw_value = _read_str(*env_names, default="")
    if not raw_value:
        return default
    return int(raw_value)


def _read_bool(env_name: str, *, default: bool) -> bool:
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _read_alert_emails(*env_names: str) -> tuple[str, ...]:
    raw_value = _read_str(*env_names, default="")
    if not raw_value:
        return ()
    emails = []
    for value in raw_value.split(","):
        email = value.strip()
        if email:
            emails.append(email)
    return tuple(emails)


def _read_source_mode() -> SourceMode:
    raw_value = _read_str("CONTADORES_SOURCE_MODE", default="testing").lower()
    if raw_value not in {"testing", "live"}:
        return "testing"
    return raw_value


@dataclass(frozen=True)
class Settings:
    enabled: bool
    source_mode: SourceMode
    test_phone: str
    test_name: str
    sheet_url: str
    sheet_gid: int | None
    sheet_poll_seconds: int
    loom_url: str
    calendly_base_url: str
    alert_emails: tuple[str, ...]
    initial_reply_quiet_seconds: int
    post_loom_min_seconds: int
    post_loom_quiet_seconds: int

    @property
    def is_testing(self) -> bool:
        return self.source_mode == "testing"

    @property
    def is_live(self) -> bool:
        return self.source_mode == "live"

    def readiness_issues(self) -> list[str]:
        issues: list[str] = []

        if self.is_testing and not self.test_phone:
            issues.append("Testing mode requires CONTADORES_TEST_PHONE.")

        if self.is_live and not self.sheet_url:
            issues.append("Live mode requires CONTADORES_SHEET_URL or GOOGLE_SHEET_URL.")

        if not self.loom_url:
            issues.append("CONTADORES_LOOM_URL is empty.")

        if not self.calendly_base_url:
            issues.append("CONTADORES_CALENDLY_BASE_URL is empty.")

        return issues

    def public_dict(self) -> dict[str, object]:
        issues = self.readiness_issues()
        return {
            "enabled": self.enabled,
            "source_mode": self.source_mode,
            "testing_phone_configured": bool(self.test_phone),
            "testing_name": self.test_name,
            "sheet_configured": bool(self.sheet_url),
            "sheet_gid": self.sheet_gid,
            "sheet_poll_seconds": self.sheet_poll_seconds,
            "loom_url_configured": bool(self.loom_url),
            "calendly_base_url": self.calendly_base_url,
            "alert_emails": list(self.alert_emails),
            "initial_reply_quiet_seconds": self.initial_reply_quiet_seconds,
            "post_loom_min_seconds": self.post_loom_min_seconds,
            "post_loom_quiet_seconds": self.post_loom_quiet_seconds,
            "ready": not issues,
            "readiness_issues": issues,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_env_once()

    return Settings(
        enabled=_read_bool("CONTADORES_ENABLED", default=True),
        source_mode=_read_source_mode(),
        test_phone=_read_str("CONTADORES_TEST_PHONE", default=""),
        test_name=_read_str("CONTADORES_TEST_NAME", default="Test Contador"),
        sheet_url=_read_str("CONTADORES_SHEET_URL", "GOOGLE_SHEET_URL", default=""),
        sheet_gid=_read_optional_int("CONTADORES_SHEET_GID", "GOOGLE_SHEET_GID"),
        sheet_poll_seconds=_read_int("CONTADORES_SHEET_POLL_SECONDS", default=300),
        loom_url=_read_str("CONTADORES_LOOM_URL", default=""),
        calendly_base_url=_read_str(
            "CONTADORES_CALENDLY_BASE_URL",
            "CONTADORES_CALENDLY_URL",
            default="https://calendly.com",
        ),
        alert_emails=_read_alert_emails("CONTADORES_ALERT_EMAILS"),
        initial_reply_quiet_seconds=_read_int(
            "CONTADORES_INITIAL_REPLY_QUIET_SECONDS",
            default=30,
        ),
        post_loom_min_seconds=_read_int("CONTADORES_POST_LOOM_MIN_SECONDS", default=600),
        post_loom_quiet_seconds=_read_int(
            "CONTADORES_POST_LOOM_QUIET_SECONDS",
            default=30,
        ),
    )
