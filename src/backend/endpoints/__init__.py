"""Endpoint routers for Konecta-Auditor API."""

from backend.endpoints.auth import auth_router
from backend.endpoints.companies import companies_router
from backend.endpoints.contadores import contadores_router
from backend.endpoints.crm import crm_router
from backend.endpoints.messages import messages_router
from backend.endpoints.tasks import tasks_router

__all__ = [
    "auth_router",
    "companies_router",
    "contadores_router",
    "crm_router",
    "messages_router",
    "tasks_router",
]
