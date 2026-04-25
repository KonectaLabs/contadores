"""Endpoint routers for the Contadores API."""

from backend.endpoints.auth import auth_router
from backend.endpoints.contadores import contadores_router

__all__ = [
    "auth_router",
    "contadores_router",
]
