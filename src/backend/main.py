"""FastAPI application for the Contadores backoffice."""

from __future__ import annotations

import logging
import os
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
from backend.endpoints import auth_router, contadores_router, funnels_router
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
}


def is_internal_bot_api_path(path: str) -> bool:
    """Return True when a path belongs to bot-consumed internal APIs."""
    return path.startswith("/api/contadores/") or path == "/api/funnels"


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
        "Runtime mode: %s (ready=%s).",
        settings.source_mode,
        not settings.readiness_issues(),
    )
    if auth_manager.enabled and not (os.getenv("INTERNAL_API_TOKEN") or "").strip():
        logger.warning("INTERNAL_API_TOKEN is not configured; bot routes will reject internal requests.")
    logger.info("Backend online.")
    init_db()
    yield
    logger.info("Backend stopped.")


app = FastAPI(
    title="Contadores",
    description="Contadores backoffice, sheet intake, WhatsApp automation, and operator tools.",
    version="0.3.0",
    lifespan=lifespan,
    openapi_tags=[
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
app.include_router(contadores_router)
app.include_router(funnels_router)


@app.middleware("http")
async def enforce_primitive_auth(request: Request, call_next):
    """Block API/frontend access unless a valid cookie session or internal token exists."""
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

    if is_internal_bot_api_path(path) and internal_token_valid:
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
async def health() -> dict[str, object]:
    """Health check endpoint."""
    settings = get_runtime_settings()
    return {
        "status": "ok",
        "enabled": settings.enabled,
        "source_mode": settings.source_mode,
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
