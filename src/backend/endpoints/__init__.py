"""Endpoint routers for the Contadores API."""

from backend.endpoints.auth import auth_router
from backend.endpoints.contadores import contadores_router
from backend.endpoints.funnels import funnels_router
from backend.endpoints.workstation import workstation_router

__all__ = [
    "auth_router",
    "contadores_router",
    "funnels_router",
    "workstation_router",
]
