"""FastAPI application for Konecta-Auditor core lab backend."""

import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import (
    INTERNAL_API_TOKEN_HEADER,
    LOGIN_PAGE_HTML,
    SESSION_COOKIE_NAME,
    auth_manager,
    has_valid_internal_api_token,
)
from backend.database import init_db
from backend.endpoints import (
    auth_router,
    companies_router,
    contadores_router,
    crm_router,
    messages_router,
    tasks_router,
)
from backend.endpoints.tasks import mark_running_tasks_as_failed


class ErrorOnlyAccessFilter(logging.Filter):
    """Keep only failing HTTP access logs from Uvicorn."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) < 5:
            return True
        try:
            return int(args[4]) >= 400
        except (TypeError, ValueError):
            return True


def configure_backend_logging() -> None:
    """Configure concise backend logs and suppress noisy access entries."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    for logger_name in ["httpx", "httpcore", "urllib3", "openai"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(current, ErrorOnlyAccessFilter) for current in access_logger.filters):
        access_logger.addFilter(ErrorOnlyAccessFilter())


configure_backend_logging()
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
PUBLIC_PATHS_WITHOUT_SESSION = {
    "/health",
    "/login",
    "/api/auth/login",
    "/api/auth/logout",
}
SHARED_COMPANY_CONTACT_MESSAGES_PATH_RE = re.compile(
    r"^/api/companies/[^/]+/contacts/[^/]+/messages(?:/(?:inbound|[^/]+(?:/delivery)?))?$"
)
SHARED_COMPANY_REPORT_SCHEDULE_PATH_RE = re.compile(
    r"^/api/companies/[^/]+/report-schedule$"
)
SHARED_COMPANY_SCAN_PATHS = {
    "/api/companies",
    "/api/companies/scan",
    "/api/companies/discover-auditor-candidates",
}
INTERNAL_ONLY_COMPANY_AUDIT_DELIVERY_SUFFIXES = (
    "/audit-delivery/generate-full-audit",
    "/audit-delivery/mark-delivered",
    "/audit-delivery/mark-blocked",
)
SHARED_COMPANY_AUDIT_DELIVERY_SUFFIXES = (
    "/audit-delivery/ceo-email",
    "/audit-delivery/email-content",
    "/audit-delivery/pdf",
)


def is_internal_bot_path(path: str) -> bool:
    """Return True when one path belongs to internal bot/backend transport flows."""
    if path in {
        "/api/messages/pending-delivery",
        "/api/contacts/tracked-values",
        "/api/contacts/resolve",
        "/api/contacts/resolve-by-value",
        "/api/messages/delivery/by-external-id",
        "/api/companies/audit-delivery/poll-state",
        "/api/crm/tracked-senders",
        "/api/crm/outbound/pending",
        "/api/crm/messages/inbound",
        "/api/crm/report-delivery/sent",
    }:
        return True

    if path.startswith("/api/crm/messages/") and path.endswith("/mark-sent"):
        return True

    return path.startswith("/api/companies/") and path.endswith(INTERNAL_ONLY_COMPANY_AUDIT_DELIVERY_SUFFIXES)


def is_shared_session_or_internal_path(path: str) -> bool:
    """Return True when one path is used by both operators and bot runtime."""
    return (
        path.startswith("/api/contadores/")
        or path in SHARED_COMPANY_SCAN_PATHS
        or SHARED_COMPANY_CONTACT_MESSAGES_PATH_RE.match(path) is not None
        or SHARED_COMPANY_REPORT_SCHEDULE_PATH_RE.match(path) is not None
        or (
            path.startswith("/api/companies/") and path.endswith(SHARED_COMPANY_AUDIT_DELIVERY_SUFFIXES)
        )
    )


def build_internal_auth_error() -> JSONResponse:
    """Return one consistent 401 for machine-to-machine routes."""
    return JSONResponse(status_code=401, content={"detail": "Internal authentication required."})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup and shutdown events."""
    auth_manager.reload_from_env()
    logger.info("🔐 Auth %s.", "enabled" if auth_manager.enabled else "disabled")
    if auth_manager.enabled and not (os.getenv("INTERNAL_API_TOKEN") or "").strip():
        logger.warning("⚠️ INTERNAL_API_TOKEN is not configured; bot/internal routes will reject requests.")
    logger.info("🚀 Backend online.")
    init_db()
    mark_running_tasks_as_failed()
    yield
    logger.info("🛑 Backend stopped.")


API_TAGS = [
    {
        "name": "auth",
        "description": "Primitive user/password login endpoints backed by TOML credentials and HttpOnly cookie sessions.",
    },
    {
        "name": "companies",
        "description": "Company flow: discover contacts, generate drafts, process inbound, produce structured reports, and render HTML artifacts.",
    },
    {
        "name": "messages",
        "description": "Conversation transcript and inbound message processing endpoints.",
    },
    {
        "name": "crm",
        "description": "CEO email inbox threads, replies, and bot-facing CRM delivery endpoints.",
    },
    {
        "name": "contadores",
        "description": "Spreadsheet leads, WhatsApp automation state, quick actions, and observability for the Contadores flow.",
    },
    {
        "name": "tasks",
        "description": "Generic background task polling endpoints.",
    },
    {
        "name": "system",
        "description": "System endpoints and frontend serving.",
    },
]

app = FastAPI(
    title="Konecta-Auditor",
    description="Agnostic conversation-auditing backend powered by DSPy stages",
    version="0.2.0",
    lifespan=lifespan,
    openapi_tags=API_TAGS,
)

STATIC_DIR = FRONTEND_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth_router)
app.include_router(companies_router)
app.include_router(contadores_router)
app.include_router(crm_router)
app.include_router(messages_router)
app.include_router(tasks_router)


@app.middleware("http")
async def enforce_primitive_auth(request: Request, call_next):
    """Block API/frontend access unless a valid cookie session exists."""
    if not auth_manager.enabled:
        return await call_next(request)

    path = request.url.path
    internal_token_valid = has_valid_internal_api_token(request.headers.get(INTERNAL_API_TOKEN_HEADER))
    if path == "/login":
        session_user = auth_manager.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))
        if session_user:
            return RedirectResponse(url="/", status_code=303)
        return await call_next(request)

    if path in PUBLIC_PATHS_WITHOUT_SESSION:
        return await call_next(request)

    if is_internal_bot_path(path):
        if not internal_token_valid:
            return build_internal_auth_error()
        request.state.authenticated_user = "internal-bot"
        return await call_next(request)

    if is_shared_session_or_internal_path(path) and internal_token_valid:
        request.state.authenticated_user = "internal-bot"
        return await call_next(request)

    session_user = auth_manager.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not session_user:
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
        return RedirectResponse(url="/login", status_code=303)

    request.state.authenticated_user = session_user
    return await call_next(request)


@app.get("/health", tags=["system"])
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@app.get("/login", tags=["system"])
async def login_page():
    """Serve primitive login page when auth is enabled."""
    if not auth_manager.enabled:
        return RedirectResponse(url="/", status_code=303)
    return HTMLResponse(LOGIN_PAGE_HTML)


@app.get("/", tags=["system"])
async def serve_frontend():
    """Serve frontend when available, otherwise return service metadata."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    return {"service": "konecta-auditor-core", "status": "ok"}
