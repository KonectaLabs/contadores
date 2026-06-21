"""Small redaction helpers for operator diagnostics and durable errors."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

SECRET_RE = re.compile(
    r"(?i)\b(bearer\s+)[a-z0-9._~+/=-]+|"
    r"\b([a-z0-9_]*(?:token|secret|api[_-]?key)[a-z0-9_]*=)[^&\s'\"<>]+"
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)")
URL_QUERY_RE = re.compile(r"(https?://[^\s?\"'<>]+)\?[^\s\"'<>]+")
LOCAL_PATH_RE = re.compile(r"(?<!\w)/(?:Users|private|tmp|var|app|data)/[^\s\"'<>]+")


def _mask_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    suffix = digits[-4:] if len(digits) >= 4 else digits
    return f"[phone:*{suffix}]"


def redact_sensitive_text(value: object, *, limit: int | None = None) -> str:
    """Redact obvious secrets, contact details, URL queries, and local paths."""
    text = " ".join(str(value or "").split())
    text = URL_QUERY_RE.sub(r"\1?[redacted]", text)
    text = SECRET_RE.sub(lambda match: f"{match.group(1) or match.group(2)}[redacted]", text)
    text = EMAIL_RE.sub("[email:redacted]", text)
    text = PHONE_RE.sub(_mask_phone, text)
    text = LOCAL_PATH_RE.sub("[local-path:redacted]", text)
    if limit is not None and len(text) > limit:
        return f"{text[:limit]} [truncated]"
    return text


def redact_identifier(value: object, *, prefix: int = 6, suffix: int = 4) -> str:
    """Return a bounded identifier label."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= prefix + suffix + 3:
        return text
    return f"{text[:prefix]}...{text[-suffix:]}"


def redact_path(value: object) -> str:
    """Return only a useful path basename."""
    text = str(value or "").strip()
    if not text:
        return ""
    return Path(text).name or "[path:redacted]"


def redact_json(value: Any, *, text_limit: int = 500, max_items: int = 30) -> Any:
    """Redact a JSON-like value without changing its shape more than needed."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_items:
                result["_truncated_items"] = len(value) - max_items
                break
            lowered = str(key).lower()
            if any(part in lowered for part in ("token", "secret", "api_key", "apikey", "password")):
                result[key] = "[redacted]"
            elif any(part in lowered for part in ("phone", "email", "text", "message", "transcript", "prompt")):
                result[key] = redact_sensitive_text(item, limit=text_limit)
            elif "path" in lowered:
                result[key] = redact_path(item)
            elif lowered in {"external_id", "ctwa_clid"} or any(
                part in lowered
                for part in (
                    "account_id",
                    "business_id",
                    "page_id",
                    "form_id",
                    "phone_number_id",
                    "referral_source_id",
                )
            ):
                result[key] = redact_identifier(item)
            else:
                result[key] = redact_json(item, text_limit=text_limit, max_items=max_items)
        return result
    if isinstance(value, list):
        items = [redact_json(item, text_limit=text_limit, max_items=max_items) for item in value[:max_items]]
        if len(value) > max_items:
            items.append({"_truncated_items": len(value) - max_items})
        return items
    if isinstance(value, str):
        return redact_sensitive_text(value, limit=text_limit)
    return value
