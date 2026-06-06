"""FastAPI application for the Contadores backoffice."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

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
from backend.client_lead_config import sync_client_lead_sources_from_config
from backend.database import init_db
from backend.endpoints import (
    auth_router,
    agent_router,
    campaigns_router,
    client_lead_deliveries_router,
    client_leads_actions_router,
    client_leads_router,
    contadores_router,
    funnels_router,
    meta_leads_router,
    platform_router,
    public_campaigns_router,
    public_workstation_router,
    workstation_router,
)
from backend.runtime_settings import get_runtime_settings


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

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"
PUBLIC_PATHS_WITHOUT_SESSION = {
    "/health",
    "/login",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/meta-leads/webhook",
    "/api/agent/auth/cli/exchange",
}
PUBLIC_HTTPS_HOSTS = {
    host.strip().lower()
    for host in os.getenv("PUBLIC_HTTPS_HOSTS", "crm.fgoiriz.com,chatterface.fgoiriz.com").split(",")
    if host.strip()
}
STRICT_TRANSPORT_SECURITY = "max-age=31536000"


def is_internal_bot_api_path(path: str) -> bool:
    """Return True when a path belongs to internal machine-consumed APIs."""
    return (
        path.startswith("/api/contadores/")
        or path.startswith("/api/agent/")
        or path.startswith("/api/client-lead-sources")
        or path.startswith("/api/client-lead-deliveries")
        or path.startswith("/api/campaigns")
        or path.startswith("/api/meta-leads")
        or path.startswith("/api/workstation/automation/")
        or path.startswith("/api/platform/")
        or path == "/api/runtime"
        or path == "/api/funnels"
    )


def safe_local_redirect_path(value: str | None, *, default: str = "/") -> str:
    """Return a same-origin redirect path."""
    clean_value = (value or "").strip()
    if clean_value.startswith("/") and not clean_value.startswith("//"):
        return clean_value
    return default


def login_redirect_for_request(request: Request) -> RedirectResponse:
    """Redirect a browser request to login and preserve the local target path."""
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(
        url=f"/login?next={quote(safe_local_redirect_path(target), safe='')}",
        status_code=303,
    )


def public_request_scheme(request: Request) -> str:
    """Return the browser-facing scheme reported by Cloudflare/proxies."""
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded_proto in {"http", "https"}:
        return forwarded_proto
    cf_visitor = request.headers.get("cf-visitor", "").replace(" ", "").lower()
    if '"scheme":"http"' in cf_visitor:
        return "http"
    if '"scheme":"https"' in cf_visitor:
        return "https"
    return ""


def public_request_host(request: Request) -> str:
    """Return the browser-facing host without port."""
    return request.headers.get("host", "").split(":", 1)[0].strip().lower()


def resolve_bearer_session_user(header_value: str | None) -> str | None:
    """Resolve an Authorization bearer session token for CLI clients."""
    scheme, _, token = (header_value or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return auth_manager.resolve_session(token.strip())


def build_internal_auth_error() -> JSONResponse:
    """Return one consistent 401 for machine-to-machine routes."""
    return JSONResponse(status_code=401, content={"detail": "Internal authentication required."})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize auth and database state."""
    auth_manager.reload_from_env()
    logger.info("Auth %s.", "enabled" if auth_manager.enabled else "disabled")
    settings = get_runtime_settings()
    logger.info(
        "Runtime ready=%s.",
        not settings.readiness_issues(),
    )
    if auth_manager.enabled and not (os.getenv("INTERNAL_API_TOKEN") or "").strip():
        logger.warning("INTERNAL_API_TOKEN is not configured; bot routes will reject internal requests.")
    logger.info("Backend online.")
    init_db()
    client_lead_config_sync = sync_client_lead_sources_from_config()
    if client_lead_config_sync.configured:
        logger.info(
            "Delivery config sources=%s upserted=%s.",
            client_lead_config_sync.configured,
            len(client_lead_config_sync.upserted),
        )
    for error in client_lead_config_sync.errors:
        logger.warning("Delivery config warning: %s", error)
    from backend.endpoints.workstation import backfill_workstation_public_pages

    published_pages = backfill_workstation_public_pages()
    if published_pages:
        logger.info("Workstation public trial pages ready=%s.", published_pages)
    yield
    logger.info("Backend stopped.")


app = FastAPI(
    title="Contadores",
    description="Contadores backoffice, sheet intake, WhatsApp automation, and operator tools.",
    version="0.3.0",
    lifespan=lifespan,
    openapi_tags=[
        {
            "name": "agent",
            "description": "Agent-ready HTTP contract and CLI/browser-login session endpoints.",
        },
        {
            "name": "auth",
            "description": "User/password login backed by TOML credentials and HttpOnly cookie sessions.",
        },
        {
            "name": "contadores",
            "description": "Spreadsheet leads, WhatsApp automation, quick actions, and operator observability.",
        },
        {
            "name": "funnels",
            "description": "File-backed niche funnel definitions used by the CRM and Codex.",
        },
        {
            "name": "workstation",
            "description": "Converted paid clients, delivery notes, media files, and Codex-ready exports.",
        },
        {
            "name": "client-leads",
            "description": "Delivery sources for client-owned campaign leads and WhatsApp notifications.",
        },
        {
            "name": "platform",
            "description": "Lifecycle events and cross-domain platform observability.",
        },
        {
            "name": "system",
            "description": "System endpoints and frontend serving.",
        },
    ],
)

ASSETS_DIR = FRONTEND_DIST_DIR / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

STATIC_DIR = FRONTEND_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth_router)
app.include_router(agent_router)
app.include_router(public_campaigns_router)
app.include_router(public_workstation_router)
app.include_router(contadores_router)
app.include_router(client_leads_router)
app.include_router(client_lead_deliveries_router)
app.include_router(client_leads_actions_router)
app.include_router(funnels_router)
app.include_router(meta_leads_router)
app.include_router(platform_router)
app.include_router(campaigns_router)
app.include_router(workstation_router)


@app.middleware("http")
async def force_public_https(request: Request, call_next):
    """Redirect public Cloudflare HTTP visits to HTTPS without looping Flexible SSL."""
    if public_request_host(request) in PUBLIC_HTTPS_HOSTS:
        browser_scheme = public_request_scheme(request)
        if browser_scheme == "http":
            return RedirectResponse(url=str(request.url.replace(scheme="https")), status_code=308)
        response = await call_next(request)
        if browser_scheme == "https":
            response.headers.setdefault("Strict-Transport-Security", STRICT_TRANSPORT_SECURITY)
        return response
    return await call_next(request)


@app.middleware("http")
async def enforce_primitive_auth(request: Request, call_next):
    """Block API/frontend access unless a valid cookie session or internal token exists."""
    if not auth_manager.enabled:
        return await call_next(request)

    path = request.url.path
    internal_token_valid = has_valid_internal_api_token(request.headers.get(INTERNAL_API_TOKEN_HEADER))
    if path.startswith("/api/agent/"):
        bearer_user = resolve_bearer_session_user(request.headers.get("Authorization"))
        if bearer_user:
            request.state.authenticated_user = bearer_user
            request.state.auth_source = "cli"
            return await call_next(request)

    if path == "/login":
        session_user = auth_manager.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))
        if session_user:
            return RedirectResponse(
                url=safe_local_redirect_path(request.query_params.get("next")),
                status_code=303,
            )
        return await call_next(request)

    if (
        path in PUBLIC_PATHS_WITHOUT_SESSION
        or path == "/p"
        or path.startswith("/p/")
        or path == "/c"
        or path.startswith("/c/")
        or path.startswith("/api/public/campaigns/")
    ):
        return await call_next(request)

    if is_internal_bot_api_path(path) and internal_token_valid:
        request.state.authenticated_user = "internal-bot"
        request.state.auth_source = "internal-token"
        return await call_next(request)

    session_user = auth_manager.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))
    if not session_user:
        if path == "/api/agent/auth/cli/start":
            return login_redirect_for_request(request)
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
        return login_redirect_for_request(request)

    request.state.authenticated_user = session_user
    request.state.auth_source = "browser-session"
    return await call_next(request)


@app.middleware("http")
async def prevent_api_response_caching(request: Request, call_next):
    """Keep CRM API responses out of browser and proxy caches."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/health", tags=["system"])
async def health() -> dict[str, object]:
    """Health check endpoint."""
    settings = get_runtime_settings()
    return {
        "status": "ok",
        "enabled": settings.enabled,
        "ready": not settings.readiness_issues(),
    }


@app.get("/api/runtime", tags=["system"])
async def runtime() -> dict[str, object]:
    """Return non-secret runtime settings."""
    return get_runtime_settings().public_dict()


@app.get("/login", tags=["system"])
async def login_page():
    """Serve primitive login page when auth is enabled."""
    if not auth_manager.enabled:
        return RedirectResponse(url="/", status_code=303)
    return HTMLResponse(LOGIN_PAGE_HTML)


@app.get("/favicon.svg", tags=["system"])
async def favicon_svg():
    """Serve the frontend favicon from the Vite build output."""
    favicon_file = FRONTEND_DIST_DIR / "favicon.svg"
    if favicon_file.exists():
        return FileResponse(favicon_file, media_type="image/svg+xml")
    return JSONResponse(status_code=404, content={"detail": "favicon not found"})


@app.get("/favicon.ico", tags=["system"])
async def favicon_ico():
    """Serve the SVG favicon for browsers that still request favicon.ico."""
    return await favicon_svg()


@app.get("/", tags=["system"])
async def serve_frontend():
    """Serve frontend when available, otherwise return service metadata."""
    index_file = FRONTEND_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    source_index_file = FRONTEND_DIR / "index.html"
    if source_index_file.exists():
        return FileResponse(source_index_file, media_type="text/html")
    return {"service": "contadores", "status": "ok"}
