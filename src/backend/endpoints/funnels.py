"""Funnel configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.funnel_config import (
    FunnelDefinition,
    FunnelListResponse,
    get_funnel,
    get_funnels_config_path,
    list_funnels,
    slugify_funnel_id,
    upsert_funnel,
)

funnels_router = APIRouter(prefix="/api/funnels", tags=["funnels"])


def build_funnel_list_response() -> FunnelListResponse:
    """Serialize every configured funnel."""
    return FunnelListResponse(
        config_path=str(get_funnels_config_path()),
        funnels=list_funnels(),
    )


@funnels_router.get("", response_model=FunnelListResponse)
async def get_funnels() -> FunnelListResponse:
    """Return configured niche funnels."""
    return build_funnel_list_response()


@funnels_router.post("", response_model=FunnelDefinition)
async def create_funnel(command: FunnelDefinition) -> FunnelDefinition:
    """Create or replace one funnel definition."""
    return upsert_funnel(command)


@funnels_router.put("/{funnel_id}", response_model=FunnelDefinition)
async def update_funnel(funnel_id: str, command: FunnelDefinition) -> FunnelDefinition:
    """Replace one funnel definition by id."""
    clean_id = slugify_funnel_id(funnel_id)
    if clean_id != command.id:
        raise HTTPException(status_code=400, detail="Path funnel id and payload id do not match.")
    existing = get_funnel(clean_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Funnel not found.")
    return upsert_funnel(command)

