"""Meta Conversions API helpers for owned campaign forms."""

from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field


class MetaConversionResult(BaseModel):
    """Result of one Meta CAPI attempt."""

    status: str
    event_id: str
    live_write_executed: bool = False
    blocked_reasons: list[str] = Field(default_factory=list)
    response: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


GraphPoster = Callable[[str, dict[str, Any]], dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _graph_base_url(api_version: str) -> str:
    return f"https://graph.facebook.com/{api_version.strip('/')}"


def _sanitize_provider_payload(value: Any) -> Any:
    """Remove token-like fields before persisting provider payloads."""
    if isinstance(value, dict):
        return {
            key: _sanitize_provider_payload(item)
            for key, item in value.items()
            if "token" not in key.lower() and "secret" not in key.lower()
        }
    if isinstance(value, list):
        return [_sanitize_provider_payload(item) for item in value]
    return value


def _redact_graph_error(value: Any) -> str:
    text = str(value)
    text = re.sub(r"(?i)(access_token=)[^&\s'\"<>]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(access_token%3D)[^&\s'\"<>]+", r"\1[redacted]", text)
    return text


def _default_graph_poster(*, api_version: str, access_token: str, timeout: float = 20) -> GraphPoster:
    base_url = _graph_base_url(api_version)

    def graph_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        params = {"access_token": access_token}
        response = httpx.post(
            f"{base_url}/{path.strip('/')}",
            params=params,
            json=payload,
            timeout=timeout,
        )
        try:
            result = response.json()
        except ValueError:
            result = {"body": response.text}
        sanitized = _sanitize_provider_payload(result if isinstance(result, dict) else {"data": result})
        if response.is_error:
            raise RuntimeError(f"Meta Graph error {response.status_code}: {_redact_graph_error(sanitized)}")
        return sanitized

    return graph_post


def sha256_normalized(value: str) -> str:
    """Return Meta-compatible SHA-256 hash for normalized user data."""
    clean_value = _clean(value).casefold()
    if not clean_value:
        return ""
    return hashlib.sha256(clean_value.encode("utf-8")).hexdigest()


def sha256_phone(value: str) -> str:
    """Return SHA-256 for a phone number reduced to digits."""
    digits = re.sub(r"\D+", "", value or "")
    return sha256_normalized(digits)


def build_user_data(
    *,
    email: str | None = None,
    phone: str | None = None,
    client_ip_address: str | None = None,
    client_user_agent: str | None = None,
    fbp: str | None = None,
    fbc: str | None = None,
) -> dict[str, Any]:
    """Build hashed Meta CAPI user data."""
    user_data: dict[str, Any] = {}
    email_hash = sha256_normalized(email or "")
    phone_hash = sha256_phone(phone or "")
    if email_hash:
        user_data["em"] = [email_hash]
    if phone_hash:
        user_data["ph"] = [phone_hash]
    if client_ip_address:
        user_data["client_ip_address"] = client_ip_address
    if client_user_agent:
        user_data["client_user_agent"] = client_user_agent
    if fbp:
        user_data["fbp"] = fbp
    if fbc:
        user_data["fbc"] = fbc
    return user_data


def send_meta_conversion_event(
    *,
    pixel_id: str,
    event_name: str,
    event_id: str,
    event_source_url: str,
    user_data: dict[str, Any],
    custom_data: dict[str, Any] | None = None,
    test_event_code: str = "",
    graph_post: GraphPoster | None = None,
) -> MetaConversionResult:
    """Send one Meta CAPI event when live writes are explicitly enabled."""
    clean_pixel_id = _clean(pixel_id)
    clean_event_id = _clean(event_id)
    blocked: list[str] = []
    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    live_enabled = _env_truthy("META_MARKETING_LIVE_WRITES_ENABLED")

    if not clean_pixel_id:
        blocked.append("meta_pixel_id")
    if not api_version:
        blocked.append("META_MARKETING_API_VERSION")
    if not access_token and graph_post is None:
        blocked.append("META_MARKETING_ACCESS_TOKEN")
    if not live_enabled and graph_post is None:
        blocked.append("META_MARKETING_LIVE_WRITES_ENABLED")

    if blocked:
        return MetaConversionResult(
            status="blocked",
            event_id=clean_event_id,
            blocked_reasons=blocked,
        )

    payload: dict[str, Any] = {
        "data": [
            {
                "event_name": _clean(event_name) or "Lead",
                "event_time": int(time.time()),
                "event_id": clean_event_id,
                "event_source_url": _clean(event_source_url),
                "action_source": "website",
                "user_data": user_data,
                "custom_data": custom_data or {},
            }
        ],
    }
    if test_event_code:
        payload["test_event_code"] = _clean(test_event_code)

    poster = graph_post or _default_graph_poster(api_version=api_version, access_token=access_token)
    try:
        response = poster(f"{clean_pixel_id}/events", payload)
    except Exception as error:
        return MetaConversionResult(
            status="failed",
            event_id=clean_event_id,
            error=_redact_graph_error(f"{error.__class__.__name__}: {error}"),
        )
    return MetaConversionResult(
        status="sent",
        event_id=clean_event_id,
        live_write_executed=True,
        response=response,
    )
