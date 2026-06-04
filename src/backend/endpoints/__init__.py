"""Endpoint routers for the Contadores API."""

from backend.endpoints.auth import auth_router
from backend.endpoints.agent import agent_router
from backend.endpoints.client_leads import (
    client_lead_deliveries_router,
    client_leads_actions_router,
    client_leads_router,
)
from backend.endpoints.contadores import contadores_router
from backend.endpoints.funnels import funnels_router
from backend.endpoints.meta_leads import meta_leads_router
from backend.endpoints.platform import platform_router
from backend.endpoints.workstation import public_workstation_router, workstation_router

__all__ = [
    "auth_router",
    "agent_router",
    "client_lead_deliveries_router",
    "client_leads_actions_router",
    "client_leads_router",
    "contadores_router",
    "funnels_router",
    "meta_leads_router",
    "platform_router",
    "public_workstation_router",
    "workstation_router",
]
