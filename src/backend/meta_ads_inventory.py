"""Read-only Meta Marketing API inventory sync."""

from __future__ import annotations

import os
import re
from typing import Any, Callable

import httpx
from pydantic import BaseModel, Field

from backend.database import PlatformEvent, PlatformMetaInventorySnapshot


class MetaInventoryError(RuntimeError):
    """Raised when Meta inventory cannot be synced."""


class MetaInventorySyncResult(BaseModel):
    """Result persisted for a read-only Meta inventory sync."""

    schema_version: str = "konecta.meta_inventory.v1"
    status: str
    ad_account_id: str = ""
    business_id: str = ""
    api_version: str = ""
    credentials_present: bool = False
    inventory: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


GraphGetter = Callable[[str, dict[str, Any] | None], dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _clean_graph_payload(value: Any) -> Any:
    """Remove token-like fields before persisting provider payloads."""
    if isinstance(value, dict):
        return {
            key: _clean_graph_payload(item)
            for key, item in value.items()
            if "token" not in key.lower() and "secret" not in key.lower()
        }
    if isinstance(value, list):
        return [_clean_graph_payload(item) for item in value]
    return value


def _redact_graph_error(value: Any) -> str:
    """Remove bearer/query tokens from provider error strings before persistence."""
    text = str(value)
    text = re.sub(r"(?i)(access_token=)[^&\s'\"<>]+", r"\1[redacted]", text)
    text = re.sub(r"(?i)(access_token%3D)[^&\s'\"<>]+", r"\1[redacted]", text)
    return text


def _graph_base_url(api_version: str) -> str:
    version = _clean(api_version).strip("/")
    if not version:
        raise MetaInventoryError("META_MARKETING_API_VERSION is required for Meta inventory sync")
    return f"https://graph.facebook.com/{version}"


def _default_graph_getter(*, api_version: str, access_token: str, timeout: float = 20) -> GraphGetter:
    base_url = _graph_base_url(api_version)

    def graph_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = dict(params or {})
        request_params["access_token"] = access_token
        response = httpx.get(f"{base_url}/{path.strip('/')}", params=request_params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    return graph_get


def _data_list(payload: dict[str, Any]) -> list[Any]:
    data = payload.get("data")
    return data if isinstance(data, list) else []


def _try_read(
    *,
    graph_get: GraphGetter,
    path: str,
    params: dict[str, Any] | None,
    errors: list[str],
) -> dict[str, Any]:
    try:
        return _clean_graph_payload(graph_get(path, params))
    except Exception as error:
        errors.append(f"{path}: {error.__class__.__name__}: {_redact_graph_error(error)}")
        return {}


def sync_meta_inventory(
    *,
    ad_account_id: str = "",
    business_id: str = "",
    page_ids: list[str] | None = None,
    include_campaigns: bool = True,
    include_lead_forms: bool = True,
    include_pixels: bool = True,
    include_whatsapp: bool = True,
    limit: int = 50,
    source: str = "codex_agent_tool",
    actor: str = "agent",
    graph_get: GraphGetter | None = None,
) -> tuple[PlatformMetaInventorySnapshot, MetaInventorySyncResult]:
    """Read Meta inventory when credentials exist, otherwise persist blockers."""
    api_version = _clean(os.getenv("META_MARKETING_API_VERSION"))
    access_token = _clean(os.getenv("META_MARKETING_ACCESS_TOKEN")) or _clean(os.getenv("META_ACCESS_TOKEN"))
    clean_limit = max(1, min(int(limit or 50), 200))
    errors: list[str] = []
    inventory: dict[str, Any] = {
        "schema_version": "konecta.meta_inventory.v1",
        "ad_accounts": [],
        "selected_ad_account": {},
        "pages": [],
        "lead_forms": [],
        "pixels": [],
        "whatsapp_business_accounts": [],
        "whatsapp_phone_numbers": [],
        "campaigns": [],
    }

    if not api_version:
        errors.append("META_MARKETING_API_VERSION")
    if not access_token and graph_get is None:
        errors.append("META_MARKETING_ACCESS_TOKEN")

    if errors:
        result = MetaInventorySyncResult(
            status="missing_credentials",
            ad_account_id=_clean(ad_account_id),
            business_id=_clean(business_id),
            api_version=api_version,
            credentials_present=bool(access_token),
            inventory=inventory,
            errors=errors,
        )
        snapshot = _persist_inventory_result(result, source=source, actor=actor)
        return snapshot, result

    getter = graph_get or _default_graph_getter(api_version=api_version, access_token=access_token)
    account_id = _clean(ad_account_id)
    business = _clean(business_id)

    accounts_payload = _try_read(
        graph_get=getter,
        path="me/adaccounts",
        params={"fields": "id,account_id,name,currency,account_status,timezone_name", "limit": clean_limit},
        errors=errors,
    )
    inventory["ad_accounts"] = _data_list(accounts_payload)

    if account_id:
        inventory["selected_ad_account"] = _try_read(
            graph_get=getter,
            path=account_id,
            params={"fields": "id,account_id,name,currency,account_status,timezone_name,business"},
            errors=errors,
        )
        if include_campaigns:
            campaigns_payload = _try_read(
                graph_get=getter,
                path=f"{account_id}/campaigns",
                params={"fields": "id,name,status,effective_status,objective,created_time,updated_time", "limit": clean_limit},
                errors=errors,
            )
            inventory["campaigns"] = _data_list(campaigns_payload)
        if include_pixels:
            pixels_payload = _try_read(
                graph_get=getter,
                path=f"{account_id}/adspixels",
                params={"fields": "id,name,last_fired_time", "limit": clean_limit},
                errors=errors,
            )
            inventory["pixels"] = _data_list(pixels_payload)

    pages_payload = _try_read(
        graph_get=getter,
        path="me/accounts",
        params={"fields": "id,name,tasks,instagram_business_account", "limit": clean_limit},
        errors=errors,
    )
    pages = _data_list(pages_payload)
    inventory["pages"] = pages
    selected_page_ids = [_clean(page_id) for page_id in (page_ids or []) if _clean(page_id)]
    if not selected_page_ids:
        selected_page_ids = [_clean(page.get("id")) for page in pages if isinstance(page, dict) and _clean(page.get("id"))]
    if include_lead_forms:
        forms: list[Any] = []
        for page_id in selected_page_ids[:10]:
            forms_payload = _try_read(
                graph_get=getter,
                path=f"{page_id}/leadgen_forms",
                params={"fields": "id,name,status,leads_count,created_time", "limit": clean_limit},
                errors=errors,
            )
            for form in _data_list(forms_payload):
                if isinstance(form, dict):
                    form = {"page_id": page_id, **form}
                forms.append(form)
        inventory["lead_forms"] = forms

    if include_whatsapp and business:
        wabas_payload = _try_read(
            graph_get=getter,
            path=f"{business}/owned_whatsapp_business_accounts",
            params={"fields": "id,name,currency,timezone_id", "limit": clean_limit},
            errors=errors,
        )
        wabas = _data_list(wabas_payload)
        inventory["whatsapp_business_accounts"] = wabas
        phone_numbers: list[Any] = []
        for waba in wabas:
            if not isinstance(waba, dict) or not _clean(waba.get("id")):
                continue
            phone_payload = _try_read(
                graph_get=getter,
                path=f"{waba['id']}/phone_numbers",
                params={"fields": "id,display_phone_number,verified_name,quality_rating", "limit": clean_limit},
                errors=errors,
            )
            for phone in _data_list(phone_payload):
                if isinstance(phone, dict):
                    phone = {"whatsapp_business_account_id": waba["id"], **phone}
                phone_numbers.append(phone)
        inventory["whatsapp_phone_numbers"] = phone_numbers

    status = "ready" if not errors else "partial"
    result = MetaInventorySyncResult(
        status=status,
        ad_account_id=account_id,
        business_id=business,
        api_version=api_version,
        credentials_present=bool(access_token),
        inventory=inventory,
        errors=errors,
    )
    snapshot = _persist_inventory_result(result, source=source, actor=actor)
    return snapshot, result


def _persist_inventory_result(
    result: MetaInventorySyncResult,
    *,
    source: str,
    actor: str,
) -> PlatformMetaInventorySnapshot:
    snapshot = PlatformMetaInventorySnapshot.add(
        status=result.status,
        source=source,
        actor=actor,
        ad_account_id=result.ad_account_id,
        business_id=result.business_id,
        api_version=result.api_version,
        inventory=result.inventory,
        errors=result.errors,
    )
    PlatformEvent.add(
        event_type="meta_inventory.synced",
        lifecycle_stage="meta_publish",
        target_type="meta_inventory",
        target_id=snapshot.id,
        source=source,
        actor=actor,
        summary=f"Synced Meta inventory snapshot {snapshot.id}.",
        payload={
            "status": result.status,
            "ad_account_id": result.ad_account_id,
            "business_id": result.business_id,
            "errors": result.errors,
            "counts": {
                key: len(value)
                for key, value in result.inventory.items()
                if isinstance(value, list)
            },
        },
    )
    return snapshot
