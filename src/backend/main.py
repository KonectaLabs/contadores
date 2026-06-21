"""FastAPI application for the Contadores backoffice."""

from __future__ import annotations

import logging
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    INTERNAL_API_TOKEN_HEADER,
    LOGIN_PAGE_HTML,
    SESSION_COOKIE_NAME,
    auth_manager,
    has_valid_internal_api_token,
)
from backend.client_lead_config import sync_client_lead_sources_from_config
from backend.database import (
    get_current_correlation_id,
    init_db,
    reset_current_correlation_id,
    set_current_correlation_id,
)
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


class RequestIdLogFilter(logging.Filter):
    """Attach the current request id to backend log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_current_correlation_id() or "-"
        return True
        try:
            return int(args[4]) >= 400
        except (TypeError, ValueError):
            return True


def configure_backend_logging() -> None:
    """Configure concise backend logs and suppress noisy access entries."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | request_id=%(request_id)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    for handler in logging.getLogger().handlers:
        if not any(isinstance(current, RequestIdLogFilter) for current in handler.filters):
            handler.addFilter(RequestIdLogFilter())
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
    for host in os.getenv("PUBLIC_HTTPS_HOSTS", "crm.fgoiriz.com").split(",")
    if host.strip()
}
CRM_PUBLIC_HOSTS = {
    host.strip().lower()
    for host in os.getenv("CRM_PUBLIC_HOSTS", "").split(",")
    if host.strip()
}
STRICT_TRANSPORT_SECURITY = "max-age=31536000"
UNSAFE_SESSION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
PUBLIC_ROUTE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,127}$")
PUBLIC_RESERVED_SEGMENTS = {"admin", "api", "assets", "login", "static"}
PUBLIC_WORKSTATION_ASSET_FILES = {"styles.css", "script.js"}
INTERNAL_TOKEN_EXACT_ROUTES = {
    ("GET", "/api/agent/capabilities"),
    ("GET", "/api/agent/me"),
    ("GET", "/api/agent/tools"),
    ("GET", "/api/client-lead-deliveries/pending"),
    ("GET", "/api/client-lead-sources"),
    ("GET", "/api/contadores/alerts/pending"),
    ("GET", "/api/contadores/config"),
    ("GET", "/api/contadores/followup/runner/status"),
    ("GET", "/api/contadores/followup/snapshot"),
    ("GET", "/api/contadores/followup/snapshot.csv"),
    ("GET", "/api/contadores/messages/pending-delivery"),
    ("GET", "/api/funnels"),
    ("GET", "/api/platform/events"),
    ("GET", "/api/platform/human-questions"),
    ("GET", "/api/platform/overview"),
    ("GET", "/api/runtime"),
    ("POST", "/api/contadores/automation/tick"),
    ("POST", "/api/contadores/calendly/webhook"),
    ("POST", "/api/contadores/followup/runner/status"),
    ("POST", "/api/contadores/leads/import"),
    ("POST", "/api/contadores/runtime-alerts/email-reply"),
    ("POST", "/api/contadores/whatsapp/inbound"),
    ("POST", "/api/workstation/automation/tick"),
    ("PUT", "/api/client-lead-deliveries/delivery/by-external-id"),
    ("PUT", "/api/contadores/messages/delivery/by-external-id"),
}
INTERNAL_ONLY_EXACT_ROUTES = {
    ("GET", "/api/client-lead-deliveries/pending"),
    ("GET", "/api/contadores/alerts/pending"),
    ("GET", "/api/contadores/followup/runner/status"),
    ("GET", "/api/contadores/followup/snapshot"),
    ("GET", "/api/contadores/followup/snapshot.csv"),
    ("GET", "/api/contadores/messages/pending-delivery"),
    ("POST", "/api/contadores/automation/tick"),
    ("POST", "/api/contadores/calendly/webhook"),
    ("POST", "/api/contadores/followup/runner/status"),
    ("POST", "/api/contadores/leads/import"),
    ("POST", "/api/contadores/runtime-alerts/email-reply"),
    ("POST", "/api/contadores/whatsapp/inbound"),
    ("POST", "/api/workstation/automation/tick"),
    ("PUT", "/api/client-lead-deliveries/delivery/by-external-id"),
    ("PUT", "/api/contadores/messages/delivery/by-external-id"),
}
REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def resolve_request_id(header_value: str | None) -> str:
    """Preserve a safe request id or create a compact one."""
    clean_value = (header_value or "").strip()
    if clean_value and REQUEST_ID_RE.fullmatch(clean_value):
        return clean_value
    return secrets.token_hex(8)


def path_segments(path: str) -> list[str]:
    """Return non-empty URL path segments."""
    return [segment for segment in path.split("/") if segment]


def clean_route_path(path: str) -> str:
    """Normalize a route path for exact auth checks."""
    if path != "/" and path.endswith("/"):
        return path.rstrip("/")
    return path


def is_public_slug(value: str) -> bool:
    """Return True for public slugs/tokens that should bypass auth."""
    clean_value = value.strip()
    return bool(
        PUBLIC_ROUTE_SEGMENT_RE.fullmatch(clean_value)
        and clean_value.lower() not in PUBLIC_RESERVED_SEGMENTS
    )


def is_public_workstation_asset_path(asset_path: str) -> bool:
    """Return True for public Workstation page files allowed before auth."""
    if not asset_path or asset_path.startswith("/"):
        return False
    parts = asset_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return False
    if asset_path in PUBLIC_WORKSTATION_ASSET_FILES:
        return True
    return parts[0] == "assets" and len(parts) > 1


def is_public_route(method: str, path: str) -> bool:
    """Return True only for deliberate public method/path pairs."""
    clean_method = method.upper()
    clean_path = clean_route_path(path)
    if clean_path in PUBLIC_PATHS_WITHOUT_SESSION:
        return True

    segments = path_segments(path)
    if clean_method == "GET" and len(segments) == 2 and segments[0] == "c":
        return is_public_slug(segments[1])
    if clean_method == "GET" and len(segments) == 4 and segments[:3] == ["api", "public", "campaigns"]:
        return is_public_slug(segments[3])
    if (
        clean_method == "POST"
        and len(segments) == 5
        and segments[:3] == ["api", "public", "campaigns"]
        and segments[4] == "submissions"
    ):
        return is_public_slug(segments[3])
    if clean_method == "GET" and len(segments) == 2 and segments[0] == "p":
        return is_public_slug(segments[1]) and len(segments[1]) >= 16
    if clean_method == "GET" and len(segments) > 2 and segments[0] == "p":
        return (
            is_public_slug(segments[1])
            and len(segments[1]) >= 16
            and is_public_workstation_asset_path("/".join(segments[2:]))
        )
    return False


def is_public_crm_path(method: str, path: str) -> bool:
    """Return True for public CRM pages and public CRM form API routes."""
    return (
        path.startswith("/p/")
        or path.startswith("/c/")
        or path.startswith("/api/public/campaigns/")
    ) and is_public_route(method, path)


def internal_token_can_access(method: str, path: str) -> bool:
    """Return True when the internal token grants this exact machine capability."""
    clean_method = method.upper()
    clean_path = clean_route_path(path)
    if (clean_method, clean_path) in INTERNAL_TOKEN_EXACT_ROUTES:
        return True

    segments = path_segments(clean_path)
    if clean_method == "POST" and len(segments) == 4 and segments[:2] == ["api", "client-lead-sources"]:
        return segments[3] == "sync"
    if len(segments) == 4 and segments[:3] == ["api", "contadores", "messages"]:
        return clean_method == "PUT"
    if len(segments) == 5 and segments[:3] == ["api", "contadores", "messages"]:
        return (clean_method, segments[4]) in {
            ("PUT", "delivery"),
            ("POST", "delivery-failure"),
        }
    if len(segments) == 5 and segments[:3] == ["api", "client-lead-deliveries"]:
        return (clean_method, segments[4]) in {
            ("PUT", "delivery"),
            ("POST", "delivery-failure"),
        }
    if len(segments) == 5 and segments[:3] == ["api", "contadores", "leads"]:
        return clean_method == "POST" and segments[4] == "mark-alerted"
    if len(segments) == 5 and segments[:3] == ["api", "contadores", "runtime-alerts"]:
        return clean_method == "POST" and segments[4] == "mark-alerted"
    if len(segments) == 6 and segments[:3] == ["api", "contadores", "followup"]:
        return clean_method in {"POST", "PATCH"} and segments[3] == "leads"
    return False


def is_internal_bot_api_path(path: str) -> bool:
    """Return True when any internal-token method can access this path."""
    return any(
        internal_token_can_access(method, path)
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE")
    )


def is_internal_only_machine_route(method: str, path: str) -> bool:
    """Return True for worker/callback routes that browser sessions must not call."""
    clean_method = method.upper()
    clean_path = clean_route_path(path)
    if (clean_method, clean_path) in INTERNAL_ONLY_EXACT_ROUTES:
        return True

    segments = path_segments(clean_path)
    if len(segments) == 4 and segments[:3] == ["api", "contadores", "messages"]:
        return clean_method == "PUT"
    if len(segments) == 5 and segments[:3] == ["api", "contadores", "messages"]:
        return (clean_method, segments[4]) in {
            ("PUT", "delivery"),
            ("POST", "delivery-failure"),
        }
    if len(segments) == 5 and segments[:3] == ["api", "client-lead-deliveries"]:
        return (clean_method, segments[4]) in {
            ("PUT", "delivery"),
            ("POST", "delivery-failure"),
        }
    if len(segments) == 5 and segments[:3] == ["api", "contadores", "leads"]:
        return clean_method == "POST" and segments[4] == "mark-alerted"
    if len(segments) == 5 and segments[:3] == ["api", "contadores", "runtime-alerts"]:
        return clean_method == "POST" and segments[4] == "mark-alerted"
    if len(segments) == 6 and segments[:3] == ["api", "contadores", "followup"]:
        return clean_method in {"POST", "PATCH"} and segments[3] == "leads"
    return False


def required_capability_for_request(method: str, path: str) -> str | None:
    """Return the browser/CLI capability required for one mutation."""
    clean_method = method.upper()
    if clean_method not in UNSAFE_SESSION_METHODS:
        return None

    clean_path = clean_route_path(path)
    segments = path_segments(clean_path)
    if clean_path == "/api/contadores/config" or segments[:2] == ["api", "funnels"]:
        return "config:write"
    if len(segments) >= 2 and segments[1] in {"client-lead-sources", "client-lead-deliveries", "client-leads"}:
        return "delivery:write"
    if len(segments) >= 2 and segments[1] == "campaigns":
        return "campaigns:write"
    if len(segments) >= 3 and segments[:3] == ["api", "platform", "meta-publish-attempts"]:
        return "meta:publish"
    if clean_path == "/api/platform/meta-inventory/sync":
        return "meta:publish"
    if len(segments) >= 3 and segments[:3] == ["api", "workstation", "clients"]:
        return "workstation:write"
    if len(segments) >= 3 and segments[:3] == ["api", "contadores", "leads"]:
        return "leads:write"
    if len(segments) >= 3 and segments[:3] == ["api", "contadores", "messages"]:
        return "leads:write"
    if len(segments) >= 3 and segments[:3] == ["api", "agent", "campaigns"]:
        return "campaigns:write"
    if len(segments) >= 3 and segments[:3] == ["api", "agent", "meta"]:
        return "meta:publish"
    if len(segments) >= 3 and segments[:3] == ["api", "agent", "conversations"]:
        return "leads:write"
    if len(segments) >= 3 and segments[:3] == ["api", "agent", "clients"]:
        return "workstation:write"
    if len(segments) >= 3 and segments[:3] == ["api", "agent", "runs"]:
        return "workstation:write"
    return None


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
    cf_visitor = request.headers.get("cf-visitor", "").replace(" ", "").lower()
    if '"scheme":"http"' in cf_visitor:
        return "http"
    if '"scheme":"https"' in cf_visitor:
        return "https"
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded_proto in {"http", "https"}:
        return forwarded_proto
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


def build_forbidden_error(detail: str) -> JSONResponse:
    """Return one consistent 403 for browser/CLI auth boundary failures."""
    return JSONResponse(status_code=403, content={"detail": detail})


def public_request_origin_host(request: Request) -> str:
    """Return the browser-facing host, preserving the port for Origin checks."""
    return request.headers.get("host", "").strip().lower()


def same_origin_header(request: Request, value: str | None) -> bool:
    """Return True when Origin/Referer points at this public origin."""
    if not value:
        return False
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    expected_scheme = public_request_scheme(request) or request.url.scheme
    return parsed.scheme.lower() == expected_scheme and parsed.netloc.lower() == public_request_origin_host(request)


def request_has_same_origin_evidence(request: Request) -> bool:
    """Require Origin or Referer for browser-session unsafe requests."""
    origin = request.headers.get("origin")
    if origin:
        return same_origin_header(request, origin)
    return same_origin_header(request, request.headers.get("referer"))


def browser_csrf_error(request: Request, session_token: str | None) -> JSONResponse | None:
    """Validate browser-session unsafe requests before handlers run."""
    if request.method.upper() not in UNSAFE_SESSION_METHODS:
        return None
    if not request_has_same_origin_evidence(request):
        return build_forbidden_error("Same-origin browser request required.")
    if not auth_manager.validate_csrf_token(session_token, request.headers.get(CSRF_HEADER_NAME)):
        return build_forbidden_error("Valid CSRF token required.")
    return None


def set_browser_csrf_cookie(response, session_token: str | None) -> None:
    """Expose the session-bound CSRF token to same-origin browser JavaScript."""
    csrf_token = auth_manager.create_csrf_token(session_token)
    if not csrf_token:
        return
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=auth_manager.session_max_age_seconds,
        httponly=False,
        samesite="strict",
        secure=auth_manager.cookie_secure,
        path="/",
    )


def clear_browser_csrf_cookie(response) -> None:
    """Clear the CSRF cookie alongside logout."""
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
        httponly=False,
        samesite="strict",
        secure=auth_manager.cookie_secure,
    )


def capability_error(user: str, method: str, path: str) -> JSONResponse | None:
    """Reject authenticated sessions missing a route capability."""
    capability = required_capability_for_request(method, path)
    if capability and not auth_manager.user_has_capability(user, capability):
        return build_forbidden_error(f"Missing capability: {capability}.")
    return None


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
async def restrict_public_crm_hosts(request: Request, call_next):
    """Serve public CRM routes only on explicitly approved hosts when configured."""
    if (
        CRM_PUBLIC_HOSTS
        and is_public_crm_path(request.method, request.url.path)
        and public_request_host(request) not in CRM_PUBLIC_HOSTS
    ):
        return JSONResponse(status_code=404, content={"detail": "Public CRM host not found."})
    return await call_next(request)


@app.middleware("http")
async def enforce_primitive_auth(request: Request, call_next):
    """Block API/frontend access unless a valid cookie session or internal token exists."""
    if not auth_manager.enabled:
        return await call_next(request)

    path = request.url.path
    method = request.method.upper()
    internal_token_valid = has_valid_internal_api_token(request.headers.get(INTERNAL_API_TOKEN_HEADER))
    if path.startswith("/api/agent/"):
        bearer_user = resolve_bearer_session_user(request.headers.get("Authorization"))
        if bearer_user:
            missing_capability = capability_error(bearer_user, method, path)
            if missing_capability:
                return missing_capability
            request.state.authenticated_user = bearer_user
            request.state.auth_capabilities = auth_manager.capabilities_for_user(bearer_user)
            request.state.auth_source = "cli"
            return await call_next(request)

    if path == "/login":
        session_token = request.cookies.get(SESSION_COOKIE_NAME)
        session_user = auth_manager.resolve_session(session_token)
        if session_user:
            response = RedirectResponse(
                url=safe_local_redirect_path(request.query_params.get("next")),
                status_code=303,
            )
            set_browser_csrf_cookie(response, session_token)
            return response
        return await call_next(request)

    if is_public_route(method, path):
        response = await call_next(request)
        if clean_route_path(path) == "/api/auth/logout":
            clear_browser_csrf_cookie(response)
        return response

    if internal_token_valid and internal_token_can_access(method, path):
        request.state.authenticated_user = "internal-bot"
        request.state.auth_capabilities = frozenset()
        request.state.auth_source = "internal-token"
        return await call_next(request)

    if is_internal_only_machine_route(method, path):
        return build_internal_auth_error()

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    session_user = auth_manager.resolve_session(session_token)
    if not session_user:
        if path == "/api/agent/auth/cli/start":
            return login_redirect_for_request(request)
        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Authentication required."})
        return login_redirect_for_request(request)

    csrf_error = browser_csrf_error(request, session_token)
    if csrf_error:
        return csrf_error
    missing_capability = capability_error(session_user, method, path)
    if missing_capability:
        return missing_capability

    request.state.authenticated_user = session_user
    request.state.auth_capabilities = auth_manager.capabilities_for_user(session_user)
    request.state.auth_source = "browser-session"
    response = await call_next(request)
    set_browser_csrf_cookie(response, session_token)
    return response


@app.middleware("http")
async def prevent_api_response_caching(request: Request, call_next):
    """Keep CRM API responses out of browser and proxy caches."""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    """Attach one bounded correlation id to the request, response, logs, and events."""
    request_id = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
    request.state.request_id = request_id
    token = set_current_correlation_id(request_id)
    try:
        response = await call_next(request)
    finally:
        reset_current_correlation_id(token)
    response.headers[REQUEST_ID_HEADER] = request_id
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
