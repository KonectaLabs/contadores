"""Read-only Meta Lead Ads retrieval helpers."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx


GraphGetter = Callable[[str, dict[str, Any] | None], dict[str, Any]]

DEFAULT_META_LEAD_FIELDS = (
    "created_time,id,ad_id,ad_name,adset_id,adset_name,campaign_id,"
    "campaign_name,form_id,platform,field_data"
)


class MetaLeadAdsError(RuntimeError):
    """Raised when a Meta Lead Ads read cannot be completed."""


class MetaLeadAdsCredentialsError(MetaLeadAdsError):
    """Raised when the platform is missing read credentials for Lead Ads."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(", ".join(missing))


@dataclass
class MetaFormLeadFetchResult:
    """Fetched Meta form leads plus bounded pagination metadata."""

    leads: list[dict[str, Any]]
    pages_fetched: int = 0
    truncated: bool = False
    complete: bool = True
    next_cursor: str = ""
    errors: list[str] = field(default_factory=list)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _graph_base_url(api_version: str) -> str:
    version = _clean(api_version).strip("/")
    if not version:
        raise MetaLeadAdsCredentialsError(["META_MARKETING_API_VERSION"])
    return f"https://graph.facebook.com/{version}"


def _clean_graph_payload(value: Any) -> Any:
    """Remove token-like fields before a provider payload is stored locally."""
    if isinstance(value, dict):
        return {
            key: _clean_graph_payload(item)
            for key, item in value.items()
            if "token" not in str(key).lower() and "secret" not in str(key).lower()
        }
    if isinstance(value, list):
        return [_clean_graph_payload(item) for item in value]
    return value


def _redact_graph_error(value: Any) -> str:
    """Remove bearer/query tokens from provider error strings before reporting."""
    text = str(value)
    text = re.sub(r"(?i)(access_token=)[^&\s'\"<>]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(access_token%3D)[^&\s'\"<>]+", r"\1[redacted]", text)
    return text


def _default_graph_getter(*, api_version: str, access_token: str, timeout: float = 20) -> GraphGetter:
    base_url = _graph_base_url(api_version)

    def graph_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        request_params["access_token"] = access_token
        response = httpx.get(f"{base_url}/{path.strip('/')}", params=request_params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        return {"data": payload}

    return graph_get


def fetch_meta_lead_payload(
    *,
    leadgen_id: str,
    fields: str = DEFAULT_META_LEAD_FIELDS,
    graph_get: GraphGetter | None = None,
) -> dict[str, Any]:
    """Fetch one Lead Ads payload by leadgen_id from the Meta Graph API."""
    clean_leadgen_id = _clean(leadgen_id)
    if not clean_leadgen_id:
        raise MetaLeadAdsError("leadgen_id is required")

    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    missing: list[str] = []
    if not api_version:
        missing.append("META_MARKETING_API_VERSION")
    if not access_token and graph_get is None:
        missing.append("META_MARKETING_ACCESS_TOKEN")
    if missing:
        raise MetaLeadAdsCredentialsError(missing)

    getter = graph_get or _default_graph_getter(api_version=api_version, access_token=access_token)
    try:
        payload = getter(clean_leadgen_id, {"fields": fields or DEFAULT_META_LEAD_FIELDS})
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:500] if error.response is not None else str(error)
        raise MetaLeadAdsError(f"Meta lead fetch failed: {_redact_graph_error(detail)}") from error
    except httpx.HTTPError as error:
        raise MetaLeadAdsError(f"Meta lead fetch failed: {_redact_graph_error(error)}") from error
    if not isinstance(payload, dict):
        raise MetaLeadAdsError("Meta lead fetch returned a non-object payload")
    return _clean_graph_payload(payload)


def fetch_meta_form_leads(
    *,
    form_id: str,
    fields: str = DEFAULT_META_LEAD_FIELDS,
    limit: int = 100,
    graph_get: GraphGetter | None = None,
) -> list[dict[str, Any]]:
    """Fetch recent Lead Ads submissions for one instant form."""
    return fetch_meta_form_leads_with_paging(
        form_id=form_id,
        fields=fields,
        limit=limit,
        max_pages=1,
        max_leads=limit,
        graph_get=graph_get,
    ).leads


def fetch_meta_form_leads_with_paging(
    *,
    form_id: str,
    fields: str = DEFAULT_META_LEAD_FIELDS,
    limit: int = 100,
    max_pages: int = 5,
    max_leads: int = 500,
    graph_get: GraphGetter | None = None,
) -> MetaFormLeadFetchResult:
    """Fetch Lead Ads submissions for one instant form within explicit page caps."""
    clean_form_id = _clean(form_id)
    if not clean_form_id:
        raise MetaLeadAdsError("form_id is required")

    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    missing: list[str] = []
    if not api_version:
        missing.append("META_MARKETING_API_VERSION")
    if not access_token and graph_get is None:
        missing.append("META_MARKETING_ACCESS_TOKEN")
    if missing:
        raise MetaLeadAdsCredentialsError(missing)

    getter = graph_get or _default_graph_getter(api_version=api_version, access_token=access_token)
    page_limit = max(1, min(int(limit or 100), 500))
    page_cap = max(1, min(int(max_pages or 1), 25))
    lead_cap = max(1, min(int(max_leads or page_limit), 5000))
    leads: list[dict[str, Any]] = []
    next_cursor = ""
    errors: list[str] = []
    pages_fetched = 0

    for _page in range(page_cap):
        params = {
            "fields": fields or DEFAULT_META_LEAD_FIELDS,
            "limit": min(page_limit, max(1, lead_cap - len(leads))),
        }
        if next_cursor:
            params["after"] = next_cursor
        try:
            payload = getter(f"{clean_form_id}/leads", params)
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:500] if error.response is not None else str(error)
            message = f"Meta form leads fetch failed: {_redact_graph_error(detail)}"
            if leads:
                errors.append(message)
                return MetaFormLeadFetchResult(
                    leads=leads,
                    pages_fetched=pages_fetched,
                    truncated=True,
                    complete=False,
                    next_cursor=next_cursor,
                    errors=errors,
                )
            raise MetaLeadAdsError(message) from error
        except httpx.HTTPError as error:
            message = f"Meta form leads fetch failed: {_redact_graph_error(error)}"
            if leads:
                errors.append(message)
                return MetaFormLeadFetchResult(
                    leads=leads,
                    pages_fetched=pages_fetched,
                    truncated=True,
                    complete=False,
                    next_cursor=next_cursor,
                    errors=errors,
                )
            raise MetaLeadAdsError(message) from error
        except Exception as error:
            message = f"Meta form leads fetch failed: {_redact_graph_error(error)}"
            if leads:
                errors.append(message)
                return MetaFormLeadFetchResult(
                    leads=leads,
                    pages_fetched=pages_fetched,
                    truncated=True,
                    complete=False,
                    next_cursor=next_cursor,
                    errors=errors,
                )
            raise MetaLeadAdsError(message) from error
        if not isinstance(payload, dict):
            raise MetaLeadAdsError("Meta form leads fetch returned a non-object payload")
        data = payload.get("data", [])
        if not isinstance(data, list):
            raise MetaLeadAdsError("Meta form leads fetch returned a non-list data payload")
        pages_fetched += 1
        leads.extend(_clean_graph_payload(item) for item in data if isinstance(item, dict))

        paging = payload.get("paging") if isinstance(payload.get("paging"), dict) else {}
        cursors = paging.get("cursors") if isinstance(paging.get("cursors"), dict) else {}
        next_cursor = _clean(cursors.get("after")) if _clean(paging.get("next")) else ""
        if not next_cursor or len(leads) >= lead_cap:
            break

    truncated = bool(next_cursor and len(leads) >= lead_cap) or bool(next_cursor and pages_fetched >= page_cap)
    return MetaFormLeadFetchResult(
        leads=leads[:lead_cap],
        pages_fetched=pages_fetched,
        truncated=truncated,
        complete=not truncated and not errors,
        next_cursor=next_cursor if truncated else "",
        errors=errors,
    )
