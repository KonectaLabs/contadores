"""Workstation endpoints for paid client profiles."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import mimetypes
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.ai.codex_agent_runtime import run_codex_agent
from backend.ai.codex_agent_tools import tool_specs as codex_agent_tool_specs
import backend.database as database_module
from backend.codex_utils import CodexSkill, interrupt_turn, run_codex_with_context, steer_turn
from backend.config import (
    CODEX_AGENT_TOOLS_ENABLED,
    CODEX_AGENT_TOOLS_WORKSTATION_ENABLED,
    CONVERSATION_BOT_CODEX_API_KEY_HOME,
    CONVERSATION_BOT_CODEX_CHATGPT_HOME,
    CONVERSATION_BOT_CODEX_EFFORT,
    CONVERSATION_BOT_CODEX_MODEL,
    CONVERSATION_BOT_CODEX_SERVICE_TIER,
    OPENAI_API_KEY,
    WORKSTATION_HANDOFF_TEMPLATE_NAME,
    WORKSTATION_CODEX_HEARTBEAT_ENABLED,
    WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS,
    WORKSTATION_HUMAN_HANDOFF_TEXT,
    WORKSTATION_PING_1_TEXT,
    WORKSTATION_PING_2_TEXT,
    WORKSTATION_PING_TEMPLATE_1_NAME,
    WORKSTATION_PING_TEMPLATE_2_NAME,
    WORKSTATION_PUBLIC_PAGE_BASE_URL,
    WORKSTATION_TEMPLATE_LANGUAGE,
    WA_CALLBACK_URL,
)
from backend.database import (
    ContadoresLead,
    ContadoresMessage,
    ContadoresRuntimeAlert,
    ScheduledAgentTask,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationMediaAsset,
    WorkstationClientStatus,
    WorkstationClientWorkType,
    WorkstationPublicPage,
    normalize_workstation_slug,
)
from backend.endpoints.contadores import (
    ContadoresLeadSummary,
    ContadoresMessageResponse,
    build_lead_summary,
    build_message_response,
    enqueue_lead_outbound,
    format_timestamp_seconds,
    get_effective_funnel_config,
    group_strategy_assignments_by_lead,
    now_utc,
    resolve_message_media_file,
    resolve_solo_page_offer_price_usd,
)

workstation_router = APIRouter(prefix="/api/workstation", tags=["workstation"])
public_workstation_router = APIRouter(tags=["workstation"])
logger = logging.getLogger(__name__)


async def await_if_needed(value):
    """Await async values while keeping old test fakes simple."""
    if inspect.isawaitable(value):
        return await value
    return value

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFESSIONAL_PHOTO_SKILL = Path(".codex/skills/client-professional-photo/SKILL.md")
PROFESSIONAL_PHOTO_EDIT_SKILL = Path(".codex/skills/client-professional-photo-edit/SKILL.md")
SOLO_PAGE_SKILL = Path(".codex/skills/workstation-solo-page/SKILL.md")
ACTIVE_PROFESSIONAL_PHOTO_JOB_STATUSES = {"queued", "running"}
WORKSTATION_INTAKE_SEQUENCE_STEP = "workstation_intake"
WORKSTATION_PREVIEW_SEQUENCE_STEP = "workstation_preview_video"
WORKSTATION_REVISION_SEQUENCE_STEP = "workstation_revision_video"
WORKSTATION_PUBLIC_PAGE_SEQUENCE_STEP = "workstation_public_page_link"
WORKSTATION_HEARTBEAT_SEQUENCE_STEP = "workstation_codex_heartbeat"
WORKSTATION_PING_1_SEQUENCE_STEP = "workstation_ping_1"
WORKSTATION_PING_2_SEQUENCE_STEP = "workstation_ping_2"
WORKSTATION_HANDOFF_SEQUENCE_STEP = "workstation_handoff"
WORKSTATION_CODEX_HEARTBEAT_REASON = "periodic_workstation_heartbeat"
WORKSTATION_BACKOFF_SECONDS = 20 * 60
WORKSTATION_PING_1_DELAY_SECONDS = 24 * 60 * 60
WORKSTATION_PING_2_DELAY_SECONDS = 48 * 60 * 60
WORKSTATION_HANDOFF_DELAY_SECONDS = 72 * 60 * 60
WORKSTATION_DEFAULT_PREVIEW_MESSAGE = (
    "Le mando un video con el boceto de su pagina. "
    "Digame que le gustaria cambiar o si asi esta bien."
)
CODEX_CHATGPT_REAUTH_URL = "https://auth.openai.com/codex/device"
CODEX_CHATGPT_REAUTH_HELP = (
    "Para reautenticar ChatGPT Codex, generar un codigo nuevo con "
    "`env -u OPENAI_API_KEY codex login --device-auth` y abrir "
    f"{CODEX_CHATGPT_REAUTH_URL}."
)
SOLO_PAGE_CONTEXT_MIN_CHARS = 35
WORKSTATION_PROGRESS_MAX_CHARS = 12000
WORKSTATION_WORKING_STALE_SECONDS = 2 * 60 * 60
WORKSTATION_INTAKE_TEXT = (
    "Perfecto, entonces arrancamos con la pagina.\n\n"
    "Mandeme por aca lo basico que quiere que aparezca: nombre del estudio, ciudad/pais, "
    "servicios principales y WhatsApp de contacto.\n\n"
    "Y mandeme cualquier foto donde se le vea la cara. No hace falta que sea profesional: "
    "puede ser la foto de perfil, una foto de redes sociales o cualquiera que tenga a mano. "
    "Nosotros la mejoramos con inteligencia artificial y con eso ya podemos trabajar.\n\n"
    "Si tiene pagina actual, logo o documento, mandemelo tambien. Con eso le preparo "
    "un primer boceto en video."
)
workstation_automation_tick_lock = asyncio.Lock()
manual_solo_page_work_client_ids: set[str] = set()
active_solo_page_codex_turns: dict[str, object] = {}
active_solo_page_codex_tasks: dict[str, object] = {}
active_solo_page_codex_started_at: dict[str, datetime] = {}
solo_page_stop_requested_client_ids: set[str] = set()


class WorkstationCodexStopped(RuntimeError):
    """Raised when an operator stops an active Workstation Codex run."""


@dataclass
class WorkstationOutboundMessageSpec:
    """One WhatsApp message that Codex asked Workstation to queue."""

    text: str
    sequence_step: str
    media_type: str | None = None
    media_path: str | None = None
    media_caption: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None


@dataclass
class WorkstationAgentDecision:
    """Next best Workstation action chosen from the client's latest reply."""

    action: Literal[
        "send_text",
        "ask_for_details",
        "generate_or_revise_page",
        "send_public_page_link",
        "approve_and_handoff",
        "handoff_human",
        "no_action",
    ]
    message: str = ""
    reason: str = ""


def register_solo_page_task(client_id: str, task: object) -> None:
    """Track the real asyncio task currently working on a client."""
    active_solo_page_codex_tasks[client_id] = task
    active_solo_page_codex_started_at.setdefault(client_id, now_utc())

    def cleanup(done_task: object) -> None:
        if active_solo_page_codex_tasks.get(client_id) is done_task:
            active_solo_page_codex_tasks.pop(client_id, None)
            active_solo_page_codex_started_at.pop(client_id, None)

    add_done_callback = getattr(task, "add_done_callback", None)
    if callable(add_done_callback):
        add_done_callback(cleanup)


def clear_solo_page_live_work(client_id: str) -> None:
    """Forget in-memory live-work markers for one client."""
    active_solo_page_codex_tasks.pop(client_id, None)
    active_solo_page_codex_turns.pop(client_id, None)
    active_solo_page_codex_started_at.pop(client_id, None)


def observed_solo_page_live_status(client_id: str) -> dict[str, object]:
    """Return process-observed work status, independent from persisted state."""
    task = active_solo_page_codex_tasks.get(client_id)
    task_done = getattr(task, "done", None)
    if task is not None and callable(task_done) and task_done():
        active_solo_page_codex_tasks.pop(client_id, None)
        active_solo_page_codex_started_at.pop(client_id, None)
        task = None
    has_task = task is not None
    has_turn = client_id in active_solo_page_codex_turns
    if has_turn:
        status = "codex_turn_active"
        detail = "A live Codex turn is connected and streaming work for this client."
    elif has_task:
        status = "background_task_active"
        detail = "A live backend task is preparing Codex, rendering, or queueing the preview."
    else:
        status = "not_running"
        detail = "No live backend task or Codex turn is currently registered for this client."
    return {
        "is_live_working": has_task or has_turn,
        "live_status": status,
        "live_detail": detail,
        "has_active_background_task": has_task,
        "has_active_codex_turn": has_turn,
        "live_started_at": format_timestamp_seconds(active_solo_page_codex_started_at.get(client_id)),
    }


def workstation_root() -> Path:
    """Return the persistent Workstation root folder."""
    root = database_module.DATA_DIR / "workstation" / "clients"
    root.mkdir(parents=True, exist_ok=True)
    return root


def client_folder(client: WorkstationClient) -> Path:
    """Return the filesystem folder for one converted client."""
    folder = workstation_root() / client.folder_name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "media").mkdir(parents=True, exist_ok=True)
    return folder


def workstation_progress_path(client: WorkstationClient) -> Path:
    """Return the operator-visible progress log for one Workstation client."""
    return client_folder(client) / "progress.md"


def append_workstation_progress(client: WorkstationClient, message: str) -> None:
    """Append one short timestamped progress event without blocking automation."""
    clean_message = " ".join((message or "").strip().split())
    if not clean_message:
        return
    try:
        path = workstation_progress_path(client)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"- `{timestamp}` {clean_message}\n")
    except Exception as error:
        logger.warning("Could not write Workstation progress for %s: %s", client.id, error)


def read_workstation_progress(client: WorkstationClient) -> tuple[str, str | None, str | None]:
    """Return progress markdown plus stable path and mtime for the detail UI."""
    path = workstation_progress_path(client)
    if not path.exists():
        return "", relative_data_path(path), None
    try:
        markdown = path.read_text(encoding="utf-8")
    except Exception as error:
        logger.warning("Could not read Workstation progress for %s: %s", client.id, error)
        return "", relative_data_path(path), None
    if len(markdown) > WORKSTATION_PROGRESS_MAX_CHARS:
        markdown = "... older progress omitted ...\n" + markdown[-WORKSTATION_PROGRESS_MAX_CHARS:]
    updated_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return markdown, relative_data_path(path), format_timestamp_seconds(updated_at)


def professional_photo_root(client: WorkstationClient) -> Path:
    """Return the deterministic generated portrait folder for one client."""
    root = client_folder(client) / "professional-photo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def relative_data_path(path: Path) -> str:
    """Return a stable data/... path for Codex and the UI."""
    data_dir = database_module.DATA_DIR.expanduser().resolve()
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(data_dir)
    except ValueError:
        return str(resolved)
    return str(Path("data") / relative)


def resolve_data_path(stored_path: str | None) -> Path | None:
    """Resolve a stored data/... path inside the shared data directory."""
    clean_path = (stored_path or "").strip()
    if not clean_path:
        return None
    candidate = Path(clean_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    parts = candidate.parts
    data_dir = database_module.DATA_DIR.expanduser().resolve()
    if parts and parts[0] == "data":
        return data_dir.joinpath(*parts[1:]).resolve()
    return (data_dir / candidate).resolve()


def workstation_public_page_base_url() -> str:
    """Return the configured public origin for trial pages, if available."""
    configured = (WORKSTATION_PUBLIC_PAGE_BASE_URL or "").strip().rstrip("/")
    if configured:
        return configured
    callback_url = (WA_CALLBACK_URL or "").strip()
    if not callback_url:
        return ""
    parsed = urlsplit(callback_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def workstation_public_page_path(public_page: WorkstationPublicPage) -> str:
    """Return the stable public path for one trial page."""
    return f"/p/{public_page.public_token}/"


def workstation_public_page_url(public_page: WorkstationPublicPage) -> str:
    """Return an absolute public URL when configured, otherwise a usable path."""
    path = workstation_public_page_path(public_page)
    base_url = workstation_public_page_base_url()
    return f"{base_url}{path}" if base_url else path


def workstation_public_page_payload(public_page: WorkstationPublicPage | None) -> dict[str, str | None] | None:
    """Serialize public trial page data for profile.json and agent context."""
    if public_page is None:
        return None
    return {
        "client_id": public_page.client_id,
        "public_token": public_page.public_token,
        "public_path": workstation_public_page_path(public_page),
        "public_url": workstation_public_page_url(public_page),
        "current_version": public_page.current_version,
        "version_path": public_page.version_path,
        "status": public_page.status,
        "first_published_at": format_timestamp_seconds(public_page.first_published_at),
        "updated_at": format_timestamp_seconds(public_page.updated_at),
        "last_sent_at": format_timestamp_seconds(public_page.last_sent_at),
    }


def ensure_workstation_public_page(client: WorkstationClient, version_dir: Path) -> WorkstationPublicPage | None:
    """Create or update the stable public trial URL for one generated page."""
    if client.work_type != WorkstationClientWorkType.SOLO_PAGINA:
        return None
    index_path = version_dir / "index.html"
    if not index_path.is_file():
        return None
    page_root = landing_page_root(client).resolve()
    resolved_version = version_dir.resolve()
    try:
        resolved_version.relative_to(page_root)
    except ValueError:
        raise RuntimeError(f"Version path is outside the landing-page folder: {version_dir}")
    return WorkstationPublicPage.create_or_update_for_client(
        client_id=client.id,
        current_version=version_dir.name,
        version_path=relative_data_path(version_dir),
    )


def ensure_public_page_for_latest_version(client: WorkstationClient) -> WorkstationPublicPage | None:
    """Backfill or refresh the stable public URL from the latest page version."""
    latest_version = latest_landing_page_version_dir(client)
    if latest_version is None:
        return WorkstationPublicPage.get_by_client_id(client.id)
    return ensure_workstation_public_page(client, latest_version)


def workstation_public_page_was_sent(client: WorkstationClient) -> bool:
    """Return True when the client has already received the public trial URL."""
    public_page = WorkstationPublicPage.get_by_client_id(client.id)
    return public_page is not None and public_page.last_sent_at is not None


def resolve_public_page_version_dir(public_page: WorkstationPublicPage) -> Path:
    """Resolve the version folder owned by a public trial page row."""
    path = resolve_data_path(public_page.version_path)
    if path is None or not path.is_dir():
        raise HTTPException(status_code=404, detail="Public page not found")
    client = WorkstationClient.get_by_id(public_page.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Public page not found")
    client_root = client_folder(client).resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(client_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Public page not found")
    return resolved_path


def safe_upload_filename(filename: str | None) -> str:
    """Return a readable filename segment that cannot escape the media folder."""
    raw_name = Path(filename or "file").name
    stem = normalize_workstation_slug(Path(raw_name).stem)
    suffix = "".join(ch for ch in Path(raw_name).suffix.lower() if ch.isalnum() or ch == ".")[:12]
    return f"{stem}{suffix}" if suffix else stem


def lead_summary_for_workstation(lead: ContadoresLead) -> ContadoresLeadSummary:
    """Serialize a lead for Workstation views."""
    config = get_effective_funnel_config(lead.funnel_id)
    assignments = group_strategy_assignments_by_lead(lead.funnel_id).get(lead.id, [])
    return build_lead_summary(lead, config=config, strategy_assignments=assignments)


def get_required_client(client_id: str) -> WorkstationClient:
    """Return one Workstation client or raise a 404."""
    client = WorkstationClient.get_by_id(client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Workstation client not found")
    return client


def get_required_lead(lead_id: str) -> ContadoresLead:
    """Return one source lead or raise a 404."""
    lead = ContadoresLead.get_by_id(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def message_content_for_transcript(message: ContadoresMessage) -> str:
    """Return readable transcript content for text and media messages."""
    clean_text = (message.text or "").strip()
    if clean_text:
        return clean_text

    media_parts = [
        getattr(message, "media_caption", None),
        getattr(message, "media_filename", None),
        getattr(message, "media_path", None),
    ]
    clean_media_parts = [
        str(part).strip()
        for part in media_parts
        if str(part or "").strip()
    ]
    if clean_media_parts:
        return " | ".join(clean_media_parts)

    if getattr(message, "media_type", None):
        return "(media sin texto)"
    return "(sin texto)"


def build_conversation_text(lead: ContadoresLead, messages: list[ContadoresMessage]) -> str:
    """Build one plain-text transcript for Codex context."""
    title = lead.full_name or lead.phone or lead.normalized_phone or "Lead"
    lines = [
        f"Cliente: {title}",
        f"Funnel: {lead.funnel_id}",
        f"Telefono: {lead.phone or lead.normalized_phone or '-'}",
        f"Email: {lead.email or '-'}",
        "",
        "Conversacion:",
    ]
    for message in messages:
        author = "Operador/Bot" if message.from_me else "Cliente"
        timestamp = format_timestamp_seconds(message.created_at) or ""
        media = f" [{message.media_type}]" if message.media_type else ""
        content = message_content_for_transcript(message)
        lines.append(f"[{timestamp}] {author}{media}: {content}")
    return "\n".join(lines).strip() + "\n"


def build_copy_all_text(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    messages: list[ContadoresMessage],
    media: list[WorkstationMediaAsset],
) -> str:
    """Build the clipboard-ready profile context for Codex."""
    public_page = ensure_public_page_for_latest_version(client)
    media_lines = [
        f"- {asset.title or asset.original_filename}: {asset.stored_path}"
        for asset in media
    ]
    return "\n\n".join(
        [
            "# Cliente Workstation",
            f"client_id: {client.id}",
            f"folder: {relative_data_path(client_folder(client))}",
            f"funnel: {client.funnel_id}",
            f"lead_id: {lead.id}",
            f"name: {lead.full_name or client.display_name}",
            f"phone: {lead.phone or lead.normalized_phone}",
            f"email: {lead.email or '-'}",
            f"offer: {client.offer_price_usd or '-'} {client.offer_currency or 'USD'}",
            f"public_trial_url: {workstation_public_page_url(public_page) if public_page else '-'}",
            "# Notas",
            client.notes or "(sin notas)",
            "# Media",
            "\n".join(media_lines) if media_lines else "(sin media)",
            "# Conversacion",
            build_conversation_text(lead, messages),
        ]
    ).strip() + "\n"


def write_client_files(
    client: WorkstationClient,
    *,
    public_page: WorkstationPublicPage | None = None,
) -> None:
    """Refresh the filesystem snapshot for one Workstation client."""
    folder = client_folder(client)
    lead = ContadoresLead.get_by_id(client.lead_id)
    messages = ContadoresMessage.list_by_lead(client.lead_id) if lead else []
    media = WorkstationMediaAsset.list_by_client(client.id)
    if public_page is None:
        public_page = ensure_public_page_for_latest_version(client)

    (folder / "notes.txt").write_text(client.notes or "", encoding="utf-8")
    if lead:
        (folder / "conversation.txt").write_text(build_conversation_text(lead, messages), encoding="utf-8")
    else:
        (folder / "conversation.txt").write_text("", encoding="utf-8")

    profile = {
        "client": {
            "id": client.id,
            "lead_id": client.lead_id,
            "funnel_id": client.funnel_id,
            "work_type": client.work_type.value,
            "status": client.status.value,
            "automation_status": client.automation_status.value,
            "offer_price_usd": client.offer_price_usd,
            "offer_currency": client.offer_currency,
            "display_name": client.display_name,
            "folder_name": client.folder_name,
            "folder_path": relative_data_path(folder),
            "last_automation_handled_at": format_timestamp_seconds(client.last_automation_handled_at),
            "last_preview_sent_at": format_timestamp_seconds(client.last_preview_sent_at),
            "approved_at": format_timestamp_seconds(client.approved_at),
            "ping_1_sent_at": format_timestamp_seconds(client.ping_1_sent_at),
            "ping_2_sent_at": format_timestamp_seconds(client.ping_2_sent_at),
            "handoff_sent_at": format_timestamp_seconds(client.handoff_sent_at),
            "created_at": format_timestamp_seconds(client.created_at),
            "updated_at": format_timestamp_seconds(client.updated_at),
        },
        "lead": {
            "id": lead.id,
            "full_name": lead.full_name,
            "phone": lead.phone,
            "normalized_phone": lead.normalized_phone,
            "email": lead.email,
            "platform": lead.platform,
            "external_lead_id": lead.external_lead_id,
        } if lead else None,
        "media": [
            {
                "id": asset.id,
                "title": asset.title,
                "original_filename": asset.original_filename,
                "stored_path": asset.stored_path,
                "content_type": asset.content_type,
                "size_bytes": asset.size_bytes,
                "created_at": format_timestamp_seconds(asset.created_at),
            }
            for asset in media
        ],
        "public_page": workstation_public_page_payload(public_page),
    }
    (folder / "profile.json").write_text(
        json.dumps(profile, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def build_client_zip(client: WorkstationClient) -> Path:
    """Refresh files and return a zip archive path for one client."""
    write_client_files(client)
    folder = client_folder(client)
    zip_path = folder / f"{client.folder_name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path == zip_path or path.is_dir():
                continue
            archive.write(path, path.relative_to(folder))
    return zip_path


class WorkstationMediaAssetResponse(BaseModel):
    """Serialized Workstation media file."""

    id: str
    client_id: str
    title: str
    original_filename: str
    stored_filename: str
    stored_path: str
    content_type: str | None = None
    size_bytes: int
    media_url: str
    created_at: str


class WorkstationPublicPageResponse(BaseModel):
    """Public trial page URL attached to one Workstation client."""

    client_id: str
    public_token: str
    public_path: str
    public_url: str
    current_version: str
    version_path: str
    status: str
    first_published_at: str | None = None
    updated_at: str | None = None
    last_sent_at: str | None = None


class WorkstationClientSummary(BaseModel):
    """List item for one converted client."""

    id: str
    lead_id: str
    funnel_id: str
    work_type: str
    status: str
    automation_status: str
    offer_price_usd: int | None = None
    offer_currency: str = "USD"
    display_name: str
    folder_name: str
    folder_path: str
    media_count: int = 0
    lead: ContadoresLeadSummary | None = None
    last_automation_handled_at: str | None = None
    last_preview_sent_at: str | None = None
    approved_at: str | None = None
    ping_1_sent_at: str | None = None
    ping_2_sent_at: str | None = None
    handoff_sent_at: str | None = None
    created_at: str
    updated_at: str


class WorkstationClientListResponse(BaseModel):
    """Workstation client list payload."""

    clients: list[WorkstationClientSummary] = Field(default_factory=list)


class WorkstationRuntimeAlertResponse(BaseModel):
    """Operator-visible runtime alert attached to a Workstation client."""

    id: int
    alert_type: str
    error: str
    fallback_action: str
    latest_inbound_text: str
    notified_at: str | None = None
    resolved_at: str | None = None
    email_thread_id: str | None = None
    email_message_id: str | None = None
    created_at: str


class WorkstationAutomationStateResponse(BaseModel):
    """Operator-facing status for the Workstation automation loop."""

    status: str
    label: str
    detail: str
    is_working: bool = False
    is_live_working: bool = False
    is_waiting_backoff: bool = False
    is_stale: bool = False
    live_status: str = "not_running"
    live_detail: str = ""
    live_started_at: str | None = None
    has_active_background_task: bool = False
    has_active_codex_turn: bool = False
    backoff_until: str | None = None
    latest_inbound_at: str | None = None
    progress_path: str | None = None
    progress_markdown: str = ""
    progress_updated_at: str | None = None


class WorkstationClientDetailResponse(BaseModel):
    """Full Workstation client profile payload."""

    client: WorkstationClientSummary
    notes: str
    messages: list[ContadoresMessageResponse] = Field(default_factory=list)
    media: list[WorkstationMediaAssetResponse] = Field(default_factory=list)
    runtime_alerts: list[WorkstationRuntimeAlertResponse] = Field(default_factory=list)
    automation_state: WorkstationAutomationStateResponse
    professional_photos: list["WorkstationProfessionalPhotoVersion"] = Field(default_factory=list)
    public_page: WorkstationPublicPageResponse | None = None


class CreateWorkstationClientCommand(BaseModel):
    """Create converted client from a CRM lead."""

    lead_id: str = Field(min_length=1)
    work_type: str = WorkstationClientWorkType.PAGINA_ADS.value
    status: str = WorkstationClientStatus.PAID.value
    automation_status: str = WorkstationAutomationStatus.NEEDS_HUMAN.value
    offer_price_usd: int | None = None
    offer_currency: str = "USD"


class UpdateWorkstationNotesCommand(BaseModel):
    """Meeting notes payload."""

    notes: str = ""


class UpdateWorkstationMediaCommand(BaseModel):
    """Operator-editable media labels."""

    title: str = ""
    original_filename: str = ""


class WorkstationCopyAllResponse(BaseModel):
    """Clipboard context payload."""

    text: str


class WorkstationProfessionalPhotoVersion(BaseModel):
    """One generated professional photo version."""

    version: str
    image_path: str
    image_url: str
    metadata_path: str | None = None
    operation: str | None = None
    created_at: str | None = None
    source_image_paths: list[str] = Field(default_factory=list)
    previous_version_path: str | None = None
    user_edit_prompt: str | None = None


ProfessionalPhotoJobStatus = Literal["queued", "running", "completed", "failed"]


class WorkstationProfessionalPhotoJobResponse(BaseModel):
    """Async professional-photo generation job status."""

    job_id: str
    client_id: str
    status: ProfessionalPhotoJobStatus
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: WorkstationProfessionalPhotoVersion | None = None


@dataclass
class ProfessionalPhotoJobRecord:
    """Mutable in-process state for one professional-photo generation job."""

    job_id: str
    client_id: str
    status: ProfessionalPhotoJobStatus
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None
    result: WorkstationProfessionalPhotoVersion | None = None


professional_photo_jobs: dict[str, ProfessionalPhotoJobRecord] = {}


class CreateProfessionalPhotoCommand(BaseModel):
    """Generate professional photo from selected media assets."""

    media_asset_ids: list[str] = Field(default_factory=list, min_length=1)
    context: str = ""


class StartSoloPageWorkCommand(BaseModel):
    """Start a manual solo-page Codex run with operator instructions."""

    prompt: str = Field(min_length=1, max_length=4000)


class SteerSoloPageWorkCommand(BaseModel):
    """Send additional operator guidance to an active solo-page Codex run."""

    message: str = Field(min_length=1, max_length=4000)


class EditProfessionalPhotoCommand(BaseModel):
    """Create a new professional photo version from an existing version."""

    base_version: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    media_asset_ids: list[str] = Field(default_factory=list)


class WorkstationAutomationTickResponse(BaseModel):
    """Summary of one Workstation automation pass."""

    status: str = "ok"
    intake_messages_sent: int = 0
    drafts_generated: int = 0
    revision_videos_sent: int = 0
    approvals: int = 0
    pings_sent: int = 0
    human_handoffs: int = 0
    failures: int = 0
    scheduled_agent_tasks_created: int = 0
    scheduled_agent_tasks_processed: int = 0


WorkstationClientDetailResponse.model_rebuild()


def empty_workstation_metrics() -> dict[str, int]:
    """Return the metric keys used by one Workstation automation step."""
    return {
        "intake_messages_sent": 0,
        "drafts_generated": 0,
        "revision_videos_sent": 0,
        "approvals": 0,
        "pings_sent": 0,
        "human_handoffs": 0,
        "failures": 0,
    }


def merge_workstation_metrics(summary: WorkstationAutomationTickResponse, metrics: dict[str, int]) -> None:
    """Add one Workstation metrics dict into a tick response."""
    summary.intake_messages_sent += metrics["intake_messages_sent"]
    summary.drafts_generated += metrics["drafts_generated"]
    summary.revision_videos_sent += metrics["revision_videos_sent"]
    summary.approvals += metrics["approvals"]
    summary.pings_sent += metrics["pings_sent"]
    summary.human_handoffs += metrics["human_handoffs"]
    summary.failures += metrics["failures"]


def workstation_heartbeat_interval() -> timedelta:
    """Return the configured Codex heartbeat interval for Workstation clients."""
    return timedelta(hours=max(1, int(WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS or 12)))


def workstation_heartbeat_client_is_candidate(client: WorkstationClient) -> bool:
    """Return True when a client can be checked by the periodic Codex heartbeat."""
    if client.work_type != WorkstationClientWorkType.SOLO_PAGINA:
        return False
    if client.status in {WorkstationClientStatus.ARCHIVED, WorkstationClientStatus.CLOSED}:
        return False
    if client.automation_status != WorkstationAutomationStatus.NEEDS_HUMAN:
        return False
    if workstation_handoff_can_resume(client):
        return False
    return True


def workstation_heartbeat_is_due(
    client: WorkstationClient,
    *,
    messages: list[ContadoresMessage],
    now: datetime,
) -> bool:
    """Return True when the periodic Codex heartbeat should inspect this client."""
    last_handled_at = normalize_utc(client.last_automation_handled_at)
    new_replies = inbound_after(messages, last_handled_at)
    if new_replies and latest_inbound_is_quiet(new_replies, now=now):
        return True
    anchor = last_handled_at or normalize_utc(client.created_at)
    if anchor is None:
        return True
    return now >= anchor + workstation_heartbeat_interval()


def ensure_workstation_codex_heartbeat_tasks(*, now: datetime, limit: int = 300) -> int:
    """Create due periodic Codex heartbeat tasks for active solo-page clients."""
    if not WORKSTATION_CODEX_HEARTBEAT_ENABLED:
        return 0
    created = 0
    interval_seconds = int(workstation_heartbeat_interval().total_seconds())
    bucket = int(now.timestamp() // max(1, interval_seconds))
    for client in WorkstationClient.list_recent(limit=limit, work_type=WorkstationClientWorkType.SOLO_PAGINA):
        if not workstation_heartbeat_client_is_candidate(client):
            continue
        if ScheduledAgentTask.get_open_for_target(
            target_type="workstation_client",
            target_id=client.id,
            reason_prefix=WORKSTATION_CODEX_HEARTBEAT_REASON,
        ):
            continue
        messages = ContadoresMessage.list_by_lead(client.lead_id)
        if not workstation_heartbeat_is_due(client, messages=messages, now=now):
            continue
        ScheduledAgentTask.create(
            target_type="workstation_client",
            target_id=client.id,
            due_at=now,
            reason=f"{WORKSTATION_CODEX_HEARTBEAT_REASON}: {client.automation_status.value}",
            instruction=(
                "Automatic 12-hour Workstation solo-page heartbeat. Re-read the client context and latest "
                "messages. Decide whether to do nothing, answer, send the public trial URL, revise the page, "
                "ask for missing factual content, or hand off. If the client asks for vague copy work such as "
                "'make the trajectory broader', ask five concrete questions and wait instead of inventing facts. "
                "If no client-facing action is useful, choose no_action and do not send a filler message."
            ),
            idempotency_key=f"{WORKSTATION_CODEX_HEARTBEAT_REASON}:{client.id}:{bucket}",
        )
        created += 1
    return created


async def apply_workstation_scheduled_decision(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    replies: list[ContadoresMessage],
    decision: WorkstationAgentDecision,
    now: datetime,
) -> dict[str, int]:
    """Apply a Codex decision produced by a scheduled Workstation heartbeat."""
    metrics = empty_workstation_metrics()
    fresh_client = WorkstationClient.get_by_id(client.id) or client
    reply_text = "\n".join(message.text for message in replies if message.text.strip())
    append_workstation_progress(
        fresh_client,
        f"Scheduled heartbeat decision: {decision.action}. {decision.reason[:240]}",
    )

    if decision.action == "no_action":
        WorkstationClient.update_automation_state(fresh_client.id, last_automation_handled_at=now)
        return metrics

    if decision.action in {"send_text", "ask_for_details"}:
        queue_workstation_agent_text(
            client=fresh_client,
            lead=lead,
            text=decision.message,
            sequence_step=WORKSTATION_HEARTBEAT_SEQUENCE_STEP,
            anchor_review_timer=False,
        )
        return metrics

    if decision.action == "send_public_page_link":
        queue_workstation_public_page_link(client=fresh_client, lead=lead, text=decision.message)
        return metrics

    if decision.action == "handoff_human":
        if decision.message:
            queue_workstation_agent_text(
                client=fresh_client,
                lead=lead,
                text=decision.message,
                sequence_step=WORKSTATION_HEARTBEAT_SEQUENCE_STEP,
                next_status=WorkstationAutomationStatus.NEEDS_HUMAN,
                anchor_review_timer=False,
            )
        else:
            WorkstationClient.update_automation_state(
                fresh_client.id,
                automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
                last_automation_handled_at=now,
            )
        metrics["human_handoffs"] = 1
        return metrics

    if decision.action == "approve_and_handoff" or text_shows_workstation_approval(reply_text):
        public_page = ensure_public_page_for_latest_version(fresh_client)
        if public_page is not None and public_page.last_sent_at is None:
            queue_workstation_public_page_link(client=fresh_client, lead=lead, text=decision.message)
            return metrics
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
            approved_at=now,
            last_automation_handled_at=now,
        )
        ContadoresLead.update_flow_state(
            lead.id,
            stage="needs_human",
            automation_paused=True,
            automation_paused_reason="workstation_solo_page_approved",
            last_classification_label="workstation_solo_page_approved",
            last_classification_reason="El cliente aprobo la pagina publica de prueba.",
            clear_needs_human_notified_at=True,
        )
        metrics["approvals"] = 1
        metrics["human_handoffs"] = 1
        return metrics

    if decision.action != "generate_or_revise_page":
        WorkstationClient.update_automation_state(fresh_client.id, last_automation_handled_at=now)
        return metrics

    revision = latest_landing_page_version_dir(fresh_client) is not None
    WorkstationClient.update_automation_state(
        fresh_client.id,
        automation_status=(
            WorkstationAutomationStatus.REVISION_REQUESTED
            if revision
            else WorkstationAutomationStatus.DRAFTING
        ),
        last_automation_handled_at=now,
    )
    await ensure_professional_photo_if_possible(fresh_client)
    version_dir = await generate_solo_page_version_observed(
        client=WorkstationClient.get_by_id(fresh_client.id) or fresh_client,
        lead=lead,
        replies=replies,
        revision=revision,
    )
    rows = queue_workstation_preview(
        client=fresh_client,
        lead=lead,
        version_dir=version_dir,
        sequence_step=WORKSTATION_REVISION_SEQUENCE_STEP if revision else WORKSTATION_PREVIEW_SEQUENCE_STEP,
    )
    if revision and workstation_public_page_was_sent(fresh_client):
        rows.append(
            queue_workstation_public_page_link(
                client=fresh_client,
                lead=lead,
                text="Ya actualice la pagina. Puede revisarla aca y decirme si asi queda bien: {url}",
            )
        )
    WorkstationClient.update_automation_state(
        fresh_client.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_automation_handled_at=now_utc(),
        last_preview_sent_at=latest_preview_queue_timestamp(rows),
    )
    metrics["drafts_generated"] = 0 if revision else 1
    metrics["revision_videos_sent"] = 1
    return metrics


def build_public_page_response(public_page: WorkstationPublicPage | None) -> WorkstationPublicPageResponse | None:
    """Serialize one public trial page row."""
    payload = workstation_public_page_payload(public_page)
    if payload is None:
        return None
    return WorkstationPublicPageResponse(
        client_id=str(payload["client_id"] or ""),
        public_token=str(payload["public_token"] or ""),
        public_path=str(payload["public_path"] or ""),
        public_url=str(payload["public_url"] or ""),
        current_version=str(payload["current_version"] or ""),
        version_path=str(payload["version_path"] or ""),
        status=str(payload["status"] or ""),
        first_published_at=payload["first_published_at"],
        updated_at=payload["updated_at"],
        last_sent_at=payload["last_sent_at"],
    )


def build_media_response(asset: WorkstationMediaAsset) -> WorkstationMediaAssetResponse:
    """Serialize one media asset."""
    return WorkstationMediaAssetResponse(
        id=asset.id,
        client_id=asset.client_id,
        title=asset.title,
        original_filename=asset.original_filename,
        stored_filename=asset.stored_filename,
        stored_path=asset.stored_path,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        media_url=f"/api/workstation/media/{asset.id}/file",
        created_at=format_timestamp_seconds(asset.created_at) or "",
    )


@workstation_router.post("/automation/tick", response_model=WorkstationAutomationTickResponse)
async def run_workstation_automation_tick() -> WorkstationAutomationTickResponse:
    """Advance automatic Workstation solo-page delivery jobs."""
    if workstation_automation_tick_lock.locked():
        return WorkstationAutomationTickResponse(status="busy")

    async with workstation_automation_tick_lock:
        summary = WorkstationAutomationTickResponse()
        now = now_utc()
        summary.scheduled_agent_tasks_created = ensure_workstation_codex_heartbeat_tasks(now=now)
        for task in ScheduledAgentTask.list_due(now=now, limit=20):
            if task.target_type != "workstation_client":
                continue
            ScheduledAgentTask.mark_status(task.id, status="running", timestamp=now)
            client = WorkstationClient.get_by_id(task.target_id)
            if client is None:
                ScheduledAgentTask.mark_status(
                    task.id,
                    status="failed",
                    error="Workstation client not found.",
                )
                summary.failures += 1
                continue
            lead = ContadoresLead.get_by_id(client.lead_id)
            if lead is None:
                ScheduledAgentTask.mark_status(task.id, status="failed", error="Lead not found.")
                summary.failures += 1
                continue
            try:
                messages = ContadoresMessage.list_by_lead(lead.id)
                replies = inbound_after(messages, client.last_automation_handled_at)
                if replies and not latest_inbound_is_quiet(replies, now=now):
                    ScheduledAgentTask.mark_status(
                        task.id,
                        status="pending",
                        error="Latest inbound is still inside the quiet window.",
                    )
                    continue
                decision = await decide_workstation_next_action(
                    client=client,
                    lead=lead,
                    replies=replies,
                    handoff_resume=True,
                    scheduled_instruction=task.instruction,
                )
                metrics = await apply_workstation_scheduled_decision(
                    client=client,
                    lead=lead,
                    replies=replies,
                    decision=decision,
                    now=now,
                )
                merge_workstation_metrics(summary, metrics)
                ScheduledAgentTask.mark_status(
                    task.id,
                    status="completed",
                    error=decision.reason,
                )
                summary.scheduled_agent_tasks_processed += 1
            except Exception as error:
                ScheduledAgentTask.mark_status(
                    task.id,
                    status="failed",
                    error=f"{error.__class__.__name__}: {error}",
                )
                summary.failures += 1
        for client in WorkstationClient.list_active_automation(
            work_type=WorkstationClientWorkType.SOLO_PAGINA,
            limit=100,
        ):
            metrics = await advance_solo_page_client(client, now=now)
            merge_workstation_metrics(summary, metrics)
        return summary


def build_professional_photo_response(client: WorkstationClient, version_dir: Path) -> WorkstationProfessionalPhotoVersion:
    """Serialize one generated professional photo version from disk."""
    image_path = version_dir / "professional-photo.jpg"
    metadata_path = version_dir / "metadata.json"
    metadata: dict[str, object] = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}

    source_paths = metadata.get("source_image_paths", [])
    return WorkstationProfessionalPhotoVersion(
        version=version_dir.name,
        image_path=relative_data_path(image_path),
        image_url=f"/api/workstation/clients/{client.id}/professional-photo/{version_dir.name}/file",
        metadata_path=relative_data_path(metadata_path) if metadata_path.exists() else None,
        operation=str(metadata.get("operation") or "") or None,
        created_at=str(metadata.get("created_at") or "") or None,
        source_image_paths=[str(path) for path in source_paths] if isinstance(source_paths, list) else [],
        previous_version_path=str(metadata.get("previous_version_path") or "") or None,
        user_edit_prompt=str(metadata.get("user_edit_prompt") or "") or None,
    )


def current_job_timestamp() -> str:
    """Return a compact UTC timestamp for job polling responses."""
    return datetime.now(timezone.utc).isoformat()


def build_professional_photo_job_response(
    job: ProfessionalPhotoJobRecord,
) -> WorkstationProfessionalPhotoJobResponse:
    """Serialize one async professional-photo job."""
    return WorkstationProfessionalPhotoJobResponse(
        job_id=job.job_id,
        client_id=job.client_id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        result=job.result,
    )


def get_professional_photo_job(client_id: str, job_id: str) -> ProfessionalPhotoJobRecord:
    """Return a job owned by one client or raise a 404."""
    job = professional_photo_jobs.get(job_id)
    if job is None or job.client_id != client_id:
        raise HTTPException(status_code=404, detail="Professional photo job not found")
    return job


def get_active_professional_photo_job(client_id: str) -> ProfessionalPhotoJobRecord | None:
    """Return the newest queued/running photo job for one client."""
    jobs = sorted(
        professional_photo_jobs.values(),
        key=lambda job: job.created_at,
        reverse=True,
    )
    for job in jobs:
        if job.client_id == client_id and job.status in ACTIVE_PROFESSIONAL_PHOTO_JOB_STATUSES:
            return job
    return None


def list_professional_photo_versions(client: WorkstationClient) -> list[WorkstationProfessionalPhotoVersion]:
    """Return generated photo versions in newest-last order."""
    root = professional_photo_root(client)
    versions = [
        path
        for path in sorted(root.iterdir())
        if path.is_dir() and path.name.startswith("v") and (path / "professional-photo.jpg").exists()
    ]
    return [build_professional_photo_response(client, version_dir) for version_dir in versions]


def latest_professional_photo_version(client: WorkstationClient) -> WorkstationProfessionalPhotoVersion | None:
    """Return the newest generated professional photo, if one exists."""
    versions = list_professional_photo_versions(client)
    return versions[-1] if versions else None


def next_professional_photo_version_dir(client: WorkstationClient) -> Path:
    """Create and return the next professional photo version directory."""
    root = professional_photo_root(client)
    existing_numbers = []
    for path in root.iterdir():
        if path.is_dir() and path.name.startswith("v") and path.name[1:].isdigit():
            existing_numbers.append(int(path.name[1:]))
    next_number = max(existing_numbers, default=0) + 1
    version_dir = root / f"v{next_number:03d}"
    version_dir.mkdir(parents=True, exist_ok=False)
    return version_dir


def get_client_image_assets(client: WorkstationClient, media_asset_ids: list[str]) -> list[WorkstationMediaAsset]:
    """Return selected image assets owned by a Workstation client."""
    assets: list[WorkstationMediaAsset] = []
    for asset_id in media_asset_ids:
        asset = WorkstationMediaAsset.get_by_id(asset_id)
        if asset is None or asset.client_id != client.id:
            raise HTTPException(status_code=404, detail=f"Media asset not found: {asset_id}")
        if not (asset.content_type or "").startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Media asset is not an image: {asset.original_filename}")
        if resolve_media_path(asset.stored_path) is None:
            raise HTTPException(status_code=404, detail=f"Media file not found: {asset.original_filename}")
        assets.append(asset)
    return assets


def write_professional_photo_metadata(
    *,
    version_dir: Path,
    operation: str,
    output_path: Path,
    source_image_paths: list[Path],
    final_prompt: str,
    codex_response: str,
    context: str = "",
    previous_version_path: Path | None = None,
    user_edit_prompt: str | None = None,
) -> None:
    """Write metadata for a generated professional photo version."""
    metadata = {
        "operation": operation,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_image_path": relative_data_path(output_path),
        "source_image_paths": [relative_data_path(path) for path in source_image_paths],
        "context": context,
        "previous_version_path": relative_data_path(previous_version_path) if previous_version_path else None,
        "user_edit_prompt": user_edit_prompt,
        "final_prompt": final_prompt,
        "codex_response": codex_response,
    }
    (version_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


async def generate_professional_photo(
    *,
    client: WorkstationClient,
    assets: list[WorkstationMediaAsset],
    context: str,
) -> WorkstationProfessionalPhotoVersion:
    """Run Codex SDK to create a professional photo version."""
    source_paths = [resolve_media_path(asset.stored_path) for asset in assets]
    resolved_source_paths = [path for path in source_paths if path is not None]
    version_dir = next_professional_photo_version_dir(client)
    output_path = version_dir / "professional-photo.jpg"
    prompt = f"""
Use the client-professional-photo skill to generate a professional portrait for this Workstation client.

Client folder:
{client_folder(client)}

Selected source image paths:
{chr(10).join(str(path) for path in resolved_source_paths)}

Optional context:
{context.strip() or "(none)"}

Required output path:
{output_path}

Requirements:
- Use the selected source images as identity references.
- Save the final generated JPG exactly at the required output path.
- Do not overwrite any source images.
- After saving, respond with a short confirmation and the output path.
""".strip()
    try:
        result = await run_codex_with_context(
            prompt,
            skills=[
                CodexSkill(
                    name="client-professional-photo",
                    path=str((REPO_ROOT / PROFESSIONAL_PHOTO_SKILL).resolve()),
                )
            ],
            local_images=resolved_source_paths,
            cwd=REPO_ROOT,
        )
    except RuntimeError as error:
        shutil.rmtree(version_dir, ignore_errors=True)
        raise HTTPException(status_code=503, detail=str(error)) from error

    if not output_path.exists():
        shutil.rmtree(version_dir, ignore_errors=True)
        raise HTTPException(
            status_code=502,
            detail=f"Codex did not create the expected image: {relative_data_path(output_path)}",
        )
    write_professional_photo_metadata(
        version_dir=version_dir,
        operation="create",
        output_path=output_path,
        source_image_paths=resolved_source_paths,
        final_prompt=prompt,
        codex_response=result.final_response,
        context=context,
    )
    register_generated_workstation_media(
        client=client,
        source_path=output_path,
        title=f"Foto profesional {version_dir.name}",
        stored_filename=f"generated-professional-photo-{version_dir.name}.jpg",
        content_type="image/jpeg",
    )
    return build_professional_photo_response(client, version_dir)


async def run_create_professional_photo_job(
    *,
    job_id: str,
    client: WorkstationClient,
    assets: list[WorkstationMediaAsset],
    context: str,
) -> None:
    """Generate one professional photo in the background and store pollable status."""
    job = professional_photo_jobs.get(job_id)
    if job is None:
        return

    job.status = "running"
    job.started_at = current_job_timestamp()

    try:
        version = await generate_professional_photo(
            client=client,
            assets=assets,
            context=context,
        )
    except HTTPException as error:
        job.status = "failed"
        job.error = str(error.detail)
        job.completed_at = current_job_timestamp()
        return
    except Exception as error:
        job.status = "failed"
        job.error = str(error)
        job.completed_at = current_job_timestamp()
        return

    job.status = "completed"
    job.result = version
    job.completed_at = current_job_timestamp()


async def edit_professional_photo(
    *,
    client: WorkstationClient,
    base_version: str,
    assets: list[WorkstationMediaAsset],
    user_prompt: str,
) -> WorkstationProfessionalPhotoVersion:
    """Run Codex SDK to create an edited professional photo version."""
    base_dir = professional_photo_root(client) / Path(base_version).name
    base_image = base_dir / "professional-photo.jpg"
    if not base_image.exists():
        raise HTTPException(status_code=404, detail="Base professional photo version not found")

    source_paths = [resolve_media_path(asset.stored_path) for asset in assets]
    resolved_source_paths = [path for path in source_paths if path is not None]
    version_dir = next_professional_photo_version_dir(client)
    output_path = version_dir / "professional-photo.jpg"
    prompt = f"""
Use the client-professional-photo-edit skill to create a new edited version of this professional portrait.

Client folder:
{client_folder(client)}

Previous generated professional photo:
{base_image}

Additional original identity reference images:
{chr(10).join(str(path) for path in resolved_source_paths) if resolved_source_paths else "(none)"}

User edit prompt:
{user_prompt.strip()}

Required output path:
{output_path}

Requirements:
- Use the previous professional photo as the main reference.
- Preserve identity and professional quality.
- Apply the user's requested modification.
- Save the final generated JPG exactly at the required output path.
- Do not overwrite previous versions or source images.
- After saving, respond with a short confirmation and the output path.
""".strip()
    try:
        result = await run_codex_with_context(
            prompt,
            skills=[
                CodexSkill(
                    name="client-professional-photo-edit",
                    path=str((REPO_ROOT / PROFESSIONAL_PHOTO_EDIT_SKILL).resolve()),
                )
            ],
            local_images=[base_image, *resolved_source_paths],
            cwd=REPO_ROOT,
        )
    except RuntimeError as error:
        shutil.rmtree(version_dir, ignore_errors=True)
        raise HTTPException(status_code=503, detail=str(error)) from error

    if not output_path.exists():
        shutil.rmtree(version_dir, ignore_errors=True)
        raise HTTPException(
            status_code=502,
            detail=f"Codex did not create the expected image: {relative_data_path(output_path)}",
        )
    write_professional_photo_metadata(
        version_dir=version_dir,
        operation="edit",
        output_path=output_path,
        source_image_paths=resolved_source_paths,
        final_prompt=prompt,
        codex_response=result.final_response,
        previous_version_path=base_image,
        user_edit_prompt=user_prompt,
    )
    register_generated_workstation_media(
        client=client,
        source_path=output_path,
        title=f"Foto profesional {version_dir.name}",
        stored_filename=f"generated-professional-photo-{version_dir.name}.jpg",
        content_type="image/jpeg",
    )
    return build_professional_photo_response(client, version_dir)


def landing_page_root(client: WorkstationClient) -> Path:
    """Return the generated static page root for one client."""
    root = client_folder(client) / "landing-page"
    root.mkdir(parents=True, exist_ok=True)
    return root


def next_landing_page_version_dir(client: WorkstationClient) -> Path:
    """Create and return the next landing page version directory."""
    root = landing_page_root(client)
    existing_numbers = []
    for path in root.iterdir():
        if path.is_dir() and path.name.startswith("v") and path.name[1:].isdigit():
            existing_numbers.append(int(path.name[1:]))
    version_dir = root / f"v{max(existing_numbers, default=0) + 1:03d}"
    version_dir.mkdir(parents=True, exist_ok=False)
    return version_dir


def latest_landing_page_version_dir(client: WorkstationClient) -> Path | None:
    """Return the newest generated landing page version, if any."""
    versions = [
        path
        for path in landing_page_root(client).iterdir()
        if path.is_dir() and path.name.startswith("v") and (path / "index.html").exists()
    ]
    return sorted(versions)[-1] if versions else None


def copy_previous_landing_page_version(*, previous_version: Path | None, version_dir: Path) -> None:
    """Seed a new version with the last page files so revisions stay visually stable."""
    if previous_version is None:
        return
    for filename in ("index.html", "styles.css", "script.js", "preview-message.txt", "outbound-messages.json"):
        source = previous_version / filename
        if source.exists():
            shutil.copy2(source, version_dir / filename)
    source_assets = previous_version / "assets"
    if source_assets.is_dir():
        shutil.copytree(source_assets, version_dir / "assets", dirs_exist_ok=True)


def run_git_command(command: list[str], *, cwd: Path) -> None:
    """Run a best-effort git command for client-local history."""
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        error_text = (completed.stderr or completed.stdout or "git command failed").strip()
        raise RuntimeError(error_text)


def ensure_client_git_project(client: WorkstationClient) -> None:
    """Initialize a lightweight git repo inside the client folder if needed."""
    folder = client_folder(client)
    if not (folder / ".git").exists():
        run_git_command(["git", "init"], cwd=folder)
    try:
        run_git_command(["git", "config", "user.email", "workstation@konecta.local"], cwd=folder)
        run_git_command(["git", "config", "user.name", "Konecta Workstation"], cwd=folder)
    except RuntimeError as error:
        append_workstation_progress(client, f"Git config skipped: {error}")


def commit_landing_page_version(client: WorkstationClient, version_dir: Path, *, operation: str) -> None:
    """Commit readable page source files in the client's local git history."""
    folder = client_folder(client)
    ensure_client_git_project(client)
    relative_version = version_dir.resolve().relative_to(folder.resolve())
    paths_to_track = [
        relative_version / "index.html",
        relative_version / "styles.css",
        relative_version / "script.js",
        relative_version / "preview-message.txt",
        relative_version / "outbound-messages.json",
        relative_version / "metadata.json",
        relative_version / "assets",
    ]
    existing_paths = [str(path) for path in paths_to_track if (folder / path).exists()]
    if not existing_paths:
        return
    run_git_command(["git", "add", *existing_paths], cwd=folder)
    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=folder,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode == 0:
        return
    if status.returncode not in {0, 1}:
        error_text = (status.stderr or status.stdout or "git diff failed").strip()
        raise RuntimeError(error_text)
    run_git_command(
        ["git", "commit", "-m", f"{operation.title()} {version_dir.name}"],
        cwd=folder,
    )


def render_landing_page_video_sync(*, index_path: Path, output_path: Path) -> None:
    """Record a desktop scroll preview of a static landing page as MP4."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("playwright is required to render Workstation preview videos") from error

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                record_video_dir=str(temp_path),
                record_video_size={"width": 1440, "height": 900},
            )
            page = context.new_page()
            page.goto(index_path.resolve().as_uri(), wait_until="networkidle")
            page.wait_for_timeout(800)
            page.evaluate(
                """
                async () => {
                  const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
                  const root = document.documentElement;
                  const previousBehavior = root.style.scrollBehavior;
                  root.style.scrollBehavior = "auto";
                  window.scrollTo(0, 0);
                  await new Promise((resolve) => setTimeout(resolve, 700));

                  const durationMs = Math.min(18000, Math.max(9500, max / 0.55));
                  const start = performance.now();
                  await new Promise((resolve) => {
                    const step = (now) => {
                      const progress = Math.min(1, (now - start) / durationMs);
                      window.scrollTo(0, Math.round(max * progress));
                      if (progress < 1) {
                        window.requestAnimationFrame(step);
                        return;
                      }
                      resolve();
                    };
                    window.requestAnimationFrame(step);
                  });

                  await new Promise((resolve) => setTimeout(resolve, 900));
                  root.style.scrollBehavior = previousBehavior;
                }
                """
            )
            context.close()
            browser.close()

        webm_files = sorted(temp_path.glob("*.webm"))
        if not webm_files:
            raise RuntimeError("Playwright did not record a preview video")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(webm_files[0]),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-an",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
            raise RuntimeError(f"ffmpeg could not create preview video: {error_text}")


def inbound_after(messages: list[ContadoresMessage], timestamp: datetime | None) -> list[ContadoresMessage]:
    """Return inbound messages newer than one timestamp."""
    anchor = normalize_utc(timestamp)
    replies: list[ContadoresMessage] = []
    for message in messages:
        if message.from_me:
            continue
        created_at = normalize_utc(message.created_at)
        if anchor is not None and created_at is not None and created_at <= anchor:
            continue
        replies.append(message)
    return replies


def normalize_utc(value: datetime | None) -> datetime | None:
    """Return a UTC-aware datetime when a value exists."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def latest_message_at(messages: list[ContadoresMessage]) -> datetime | None:
    """Return the latest usable message timestamp."""
    for message in reversed(messages):
        created_at = normalize_utc(message.created_at)
        if created_at is not None:
            return created_at
    return None


def backoff_until_for(messages: list[ContadoresMessage]) -> datetime | None:
    """Return when the current inbound quiet window ends."""
    latest_at = latest_message_at(messages)
    if latest_at is None:
        return None
    return latest_at + timedelta(seconds=WORKSTATION_BACKOFF_SECONDS)


def workstation_working_status_is_stale(client: WorkstationClient, *, now: datetime) -> bool:
    """Return True when a working state is too old to trust."""
    if client.automation_status not in {
        WorkstationAutomationStatus.DRAFTING,
        WorkstationAutomationStatus.REVISION_REQUESTED,
    }:
        return False
    started_at = normalize_utc(client.last_automation_handled_at)
    if started_at is None:
        return True
    return normalize_utc(now) >= started_at + timedelta(seconds=WORKSTATION_WORKING_STALE_SECONDS)


def latest_inbound_is_quiet(messages: list[ContadoresMessage], *, now: datetime) -> bool:
    """Return True when the latest inbound has passed the Workstation backoff."""
    if not messages:
        return False
    latest_at = latest_message_at(messages)
    if latest_at is None:
        return False
    return now >= latest_at + timedelta(seconds=WORKSTATION_BACKOFF_SECONDS)


def message_has_solo_page_context(message: ContadoresMessage) -> bool:
    """Return True when an old inbound contains enough page-building context."""
    if message.from_me:
        return False
    text = " ".join((message.text or "").strip().split())
    if not text or text.startswith("["):
        return False
    normalized = text.lower()
    interest_only_markers = (
        "si",
        "ok",
        "dale",
        "perfecto",
        "me interesa",
        "hagamos",
        "avancemos",
        "empecemos",
        "arranquemos",
    )
    if len(normalized) < SOLO_PAGE_CONTEXT_MIN_CHARS and any(marker in normalized for marker in interest_only_markers):
        return False
    context_markers = (
        "estudio",
        "despacho",
        "servicio",
        "trabajo",
        "derecho",
        "abogado",
        "contador",
        "impuesto",
        "sociedad",
        "logo",
        "foto",
        "whatsapp",
        "ciudad",
        "pais",
        "país",
        "direccion",
        "dirección",
        "pagina actual",
        "página actual",
    )
    return len(normalized) >= 100 or any(marker in normalized for marker in context_markers)


def has_existing_solo_page_context(client: WorkstationClient, messages: list[ContadoresMessage]) -> bool:
    """Return True when a manually started client can skip the first intake prompt."""
    if (client.notes or "").strip():
        return True
    return any(message_has_solo_page_context(message) for message in messages)


def text_shows_workstation_approval(text: str) -> bool:
    """Return True when the client accepts the current page version."""
    normalized = " ".join((text or "").lower().replace("á", "a").replace("í", "i").split())
    if not normalized:
        return False
    negative_markers = ("pero", "cambia", "cambiar", "modifica", "modificar", "no me gusta", "ajust")
    if any(marker in normalized for marker in negative_markers):
        return False
    approval_markers = (
        "me gusta",
        "aprobado",
        "asi esta bien",
        "esta bien",
        "listo",
        "perfecto",
        "queda bien",
        "todo bien",
        "dale",
        "ok",
    )
    return any(marker in normalized for marker in approval_markers)


def parse_workstation_agent_decision(raw_text: str) -> WorkstationAgentDecision:
    """Parse Codex JSON into a conservative Workstation decision."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start < 0 or end <= start:
            return WorkstationAgentDecision(
                action="ask_for_details",
                message="Conteme que quiere que cambie o que datos quiere agregar y lo ajusto.",
                reason="Codex did not return JSON.",
            )
        try:
            payload = json.loads(raw_text[start : end + 1])
        except json.JSONDecodeError:
            return WorkstationAgentDecision(
                action="ask_for_details",
                message="Conteme que quiere que cambie o que datos quiere agregar y lo ajusto.",
                reason="Codex returned invalid JSON.",
            )

    if not isinstance(payload, dict):
        return WorkstationAgentDecision(
            action="ask_for_details",
            message="Conteme que quiere que cambie o que datos quiere agregar y lo ajusto.",
            reason="Codex JSON was not an object.",
        )

    clean_action = str(payload.get("action") or "").strip().lower()
    allowed_actions = {
        "send_text",
        "ask_for_details",
        "generate_or_revise_page",
        "send_public_page_link",
        "approve_and_handoff",
        "handoff_human",
        "no_action",
    }
    if clean_action not in allowed_actions:
        clean_action = "ask_for_details"
    clean_message = clean_workstation_preview_message(payload.get("message"))
    clean_reason = clean_workstation_preview_message(payload.get("reason"))
    return WorkstationAgentDecision(action=clean_action, message=clean_message, reason=clean_reason)


def fallback_workstation_agent_decision(reply_text: str) -> WorkstationAgentDecision:
    """Choose a safe action when Codex decisioning is unavailable."""
    normalized = " ".join((reply_text or "").lower().split())
    if text_shows_workstation_approval(reply_text):
        return WorkstationAgentDecision(
            action="approve_and_handoff",
            reason="The reply appears to approve the current preview.",
        )
    public_link_markers = (
        "link",
        "url",
        "publica",
        "publicar",
        "publicada",
        "internet",
        "verla",
        "probarla",
        "deploy",
    )
    if any(marker in normalized for marker in public_link_markers):
        return WorkstationAgentDecision(
            action="send_public_page_link",
            reason="The client appears to ask for the public trial page URL.",
        )
    if reply_needs_workstation_content_intake(reply_text):
        return WorkstationAgentDecision(
            action="ask_for_details",
            message=build_workstation_content_intake_message(reply_text),
            reason="The requested copy change is too vague to revise without inventing client facts.",
        )
    question_markers = ("?", "como", "cómo", "donde", "dónde", "que ", "qué ", "cuando", "cuándo")
    content_markers = (
        "agrega",
        "agregale",
        "agregar",
        "cambia",
        "cambiar",
        "modifica",
        "saca",
        "quita",
        "pon",
        "pone",
        "inclui",
        "incluí",
        "foto",
        "logo",
        "servicio",
    )
    if any(marker in normalized for marker in content_markers):
        return WorkstationAgentDecision(
            action="generate_or_revise_page",
            reason="The reply includes concrete page change instructions.",
        )
    if "cosas que hice" in normalized or "trabajos" in normalized or any(marker in normalized for marker in question_markers):
        return WorkstationAgentDecision(
            action="send_text",
            message=(
                "Conteme por aca lo que tenga y lo sumo. Para la foto, no hace falta que sea profesional: "
                "puede ser su foto de perfil, una de redes o cualquier foto donde se le vea la cara. "
                "Nosotros la mejoramos con inteligencia artificial."
            ),
            reason="The client is asking how to provide content rather than requesting a visual revision.",
        )
    return WorkstationAgentDecision(
        action="ask_for_details",
        message=build_workstation_content_intake_message(reply_text),
        reason="The reply is not specific enough to revise the page yet.",
    )


def reply_needs_workstation_content_intake(reply_text: str) -> bool:
    """Return True when a revision request needs factual input before editing."""
    normalized = " ".join((reply_text or "").lower().split())
    if not normalized:
        return True
    vague_copy_markers = (
        "algo mas",
        "algo más",
        "mas amplio",
        "más amplio",
        "amplio",
        "ampliar",
        "mas completo",
        "más completo",
        "mas larga",
        "más larga",
        "mas largo",
        "más largo",
        "mejorar",
        "mejoralo",
        "mejorarla",
        "trayectoria",
        "experiencia",
        "perfil profesional",
        "biografia",
        "biografía",
        "historia",
    )
    if not any(marker in normalized for marker in vague_copy_markers):
        return False
    concrete_fact_markers = (
        "desde ",
        "ano",
        "año",
        "anos",
        "años",
        "universidad",
        "egres",
        "gradu",
        "diplom",
        "certifica",
        "colegio",
        "fundador",
        "directora",
        "director",
        "socia",
        "socio",
        "civil",
        "penal",
        "familia",
        "mercantil",
        "laboral",
        "inmigr",
        "contrato",
        "empresas",
        "audiencias",
        "clientes",
        "casos",
        "mas de ",
        "más de ",
    )
    if any(marker in normalized for marker in concrete_fact_markers):
        return False
    return True


def build_workstation_content_intake_message(reply_text: str) -> str:
    """Build a short structured request for missing page facts."""
    normalized = " ".join((reply_text or "").lower().split())
    if "trayectoria" in normalized or "experiencia" in normalized:
        return (
            "Perfecto. Para ampliar la trayectoria sin inventar datos, mandeme estas 5 cosas:\n\n"
            "1. Desde que ano ejerce o trabaja en esta area?\n"
            "2. Que areas principales quiere destacar?\n"
            "3. Que estudios, cargos, certificaciones o lugares de trabajo quiere mencionar?\n"
            "4. Que tipo de clientes, casos o logros quiere resaltar sin datos sensibles?\n"
            "5. Que tono prefiere: mas sobrio, cercano o fuerte?"
        )
    return (
        "Perfecto. Para ajustarla bien sin inventar datos, mandeme estas 5 cosas:\n\n"
        "1. Que seccion quiere cambiar?\n"
        "2. Que texto o idea quiere agregar?\n"
        "3. Que dato concreto no puede faltar?\n"
        "4. Que quiere evitar o sacar?\n"
        "5. Que tono prefiere: mas sobrio, cercano o fuerte?"
    )


def build_workstation_agent_decision_prompt(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    replies: list[ContadoresMessage],
    handoff_resume: bool = False,
    scheduled_instruction: str = "",
) -> str:
    """Build the prompt that lets Codex choose the next Workstation action."""
    public_page = ensure_public_page_for_latest_version(client)
    write_client_files(client, public_page=public_page)
    latest_reply_text = "\n".join(f"- {message.text}" for message in replies if message.text.strip()).strip()
    previous_version = latest_landing_page_version_dir(client)
    public_page_payload = workstation_public_page_payload(public_page)
    return f"""
You are the autonomous Workstation solo-page client agent.

Choose the best next action for the client. Do not default to making a website
revision. Sometimes the right move is to answer the client's question, ask for
more content, or confirm whether they like the current version.

Client folder:
{client_folder(client)}

Previous page version:
{previous_version or "(none)"}

Public trial page:
- URL: {public_page_payload["public_url"] if public_page_payload else "(none)"}
- last_sent_at: {public_page_payload["last_sent_at"] if public_page_payload else "(never)"}

Scheduled instruction:
{scheduled_instruction.strip() or "(none)"}

Client:
- Name: {lead.full_name or client.display_name}
- Funnel: {client.funnel_id}
- Phone: {lead.phone or lead.normalized_phone or "-"}

Latest client replies:
{latest_reply_text or "(no text)"}

Decision rules:
- If the client asks a question, answer it with text. Do not generate a page.
- If the client asks how to provide content or photos, ask them to send whatever
  they have and say you will add it.
- Encourage a face photo without creating friction: tell them any photo works,
  it does not need to be professional, and it can be a profile photo, social
  media photo, or any casual photo where their face is visible because we
  improve it with AI.
- If the client asks for vague factual/copy changes, do not revise yet. Examples:
  "hacer la trayectoria mas amplia", "poner algo mas completo", "mejorar la
  experiencia", or "agregar algo de historia" without the actual facts. Use
  ask_for_details and ask five compact questions so the client gives the facts.
- Do not invent trajectory, experience, cases, awards, credentials, cities,
  services, or legal/accounting facts just to make a section longer.
- If the client sent useful photos/content and a draft is helpful now, generate_or_revise_page is allowed.
- If the client gave concrete changes to the current page with enough factual
  detail to edit safely, use generate_or_revise_page.
- If the client asks to see, test, publish, or open the page online, use send_public_page_link.
- If the client approves the preview but the public trial URL has not been sent yet, use send_public_page_link.
- If the public trial URL was already sent and the client approves that public page, use approve_and_handoff.
- If the situation needs a person, use handoff_human.
- Use ask_for_details when the client intent is unclear.
- Keep any WhatsApp message short, natural, and in Rioplatense/neutral Spanish.
- Never invent payment, domain, hosting, or legal/accounting facts.

Return only JSON:
{{
  "action": "send_text | ask_for_details | generate_or_revise_page | send_public_page_link | approve_and_handoff | handoff_human | no_action",
  "message": "text to send if action is send_text, ask_for_details, send_public_page_link, or handoff_human",
  "reason": "short internal reason"
}}

handoff_resume: {"yes" if handoff_resume else "no"}
""".strip()


def build_workstation_tool_agent_context(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    replies: list[ContadoresMessage],
    handoff_resume: bool = False,
    scheduled_instruction: str = "",
) -> str:
    """Build decision context for the tool-capable Workstation employee."""
    public_page = ensure_public_page_for_latest_version(client)
    write_client_files(client, public_page=public_page)
    previous_version = latest_landing_page_version_dir(client)
    public_page_payload = workstation_public_page_payload(public_page)
    reply_lines = [
        f"- id={message.id} at={format_timestamp_seconds(message.created_at) or '-'}: {message.text or '[media]'}"
        for message in replies
    ]
    return f"""
# Workstation Client
- client_id: {client.id}
- lead_id: {lead.id}
- name: {lead.full_name or client.display_name or '-'}
- funnel: {client.funnel_id}
- phone: {lead.phone or lead.normalized_phone or '-'}
- automation_status: {client.automation_status.value}
- client_folder: {client_folder(client)}
- previous_page_version: {previous_version or '(none)'}
- public_trial_url: {public_page_payload["public_url"] if public_page_payload else '(none)'}
- public_trial_url_last_sent_at: {public_page_payload["last_sent_at"] if public_page_payload else '(never)'}
- handoff_resume: {"yes" if handoff_resume else "no"}
- scheduled_instruction: {scheduled_instruction.strip() or '(none)'}

# Latest Client Replies
{chr(10).join(reply_lines) if reply_lines else "(none)"}

# Operating Judgment
- If the client asks a question, answer with send_whatsapp_text. Do not generate a page for that.
- If the client asks how to send content, ask them to send it and say you will add it.
- If the client asks for vague factual/copy changes, do not revise yet. Examples:
  "hacer la trayectoria mas amplia", "poner algo mas completo", "mejorar la
  experiencia", or "agregar algo de historia" without the actual facts. Ask five
  compact questions and wait.
- Do not invent trajectory, experience, cases, awards, credentials, cities,
  services, or legal/accounting facts just to make a section longer.
- If the client gave concrete page changes or useful assets with enough factual
  detail to edit safely, use generate_or_revise_solo_page and then queue_workstation_deliverables.
- If the client asks to see, test, publish, or open the page online, use send_workstation_public_page_link.
- If the client approves the preview but public_trial_url_last_sent_at is never, send_workstation_public_page_link first.
- If public_trial_url_last_sent_at exists and the client approves the public test page, use mark_preview_approved.
- If the situation needs a person, use handoff_human.
- If the right move is to wait, use schedule_followup.
- If this is a scheduled heartbeat and no client-facing action is useful, do
  nothing. Do not send a filler message.
- Keep the current page design stable across revisions unless the client explicitly asks for a redesign.
""".strip()


async def run_workstation_tool_agent(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    replies: list[ContadoresMessage],
    handoff_resume: bool = False,
    scheduled_instruction: str = "",
) -> WorkstationAgentDecision | None:
    """Let Codex act through product tools and return no fallback decision if it acted."""
    if not (CODEX_AGENT_TOOLS_ENABLED and CODEX_AGENT_TOOLS_WORKSTATION_ENABLED):
        return None

    context_md = build_workstation_tool_agent_context(
        client=client,
        lead=lead,
        replies=replies,
        handoff_resume=handoff_resume,
        scheduled_instruction=scheduled_instruction,
    )

    def register_turn(turn: object) -> None:
        active_solo_page_codex_turns[client.id] = turn
        active_solo_page_codex_started_at.setdefault(client.id, now_utc())

    try:
        result = await await_if_needed(run_codex_agent(
            target_type="workstation_client",
            target_id=client.id,
            objective=(
                "Handle the client's latest Workstation solo-page turn with full judgment. "
                "Use tools for any product action. Do not return a JSON decision."
            ),
            context_md=context_md,
            tool_specs=codex_agent_tool_specs(),
            skills=[
                CodexSkill(
                    name="workstation-solo-page",
                    path=str((REPO_ROOT / SOLO_PAGE_SKILL).resolve()),
                )
            ],
            prompt_version="workstation-agent-tools-v1",
            on_turn_started=register_turn,
        ))
    except Exception as error:
        append_workstation_progress(
            client,
            f"Tool agent failed before completing action; falling back to legacy decision: {error.__class__.__name__}: {error}",
        )
        return None
    finally:
        active_solo_page_codex_turns.pop(client.id, None)

    successful_calls = [call for call in result.tool_calls if call.status == "succeeded"]
    append_workstation_progress(
        client,
        f"Tool agent run {result.run_id} completed with {len(successful_calls)} successful tool call(s).",
    )
    if successful_calls:
        return WorkstationAgentDecision(
            action="no_action",
            reason=f"Codex tool agent already acted in run {result.run_id}.",
        )
    return None


async def decide_workstation_next_action(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    replies: list[ContadoresMessage],
    handoff_resume: bool = False,
    scheduled_instruction: str = "",
) -> WorkstationAgentDecision:
    """Let Codex choose whether to reply, ask, revise, approve, or hand off."""
    reply_text = "\n".join(message.text for message in replies if message.text.strip())
    tool_decision = await run_workstation_tool_agent(
        client=client,
        lead=lead,
        replies=replies,
        handoff_resume=handoff_resume,
        scheduled_instruction=scheduled_instruction,
    )
    if tool_decision is not None:
        return tool_decision
    prompt = build_workstation_agent_decision_prompt(
        client=client,
        lead=lead,
        replies=replies,
        handoff_resume=handoff_resume,
        scheduled_instruction=scheduled_instruction,
    )
    try:
        result = await run_solo_page_codex_with_fallback(
            prompt=prompt,
            on_turn_started=lambda _turn: None,
            skills=[],
            thread_id=client.codex_workstation_thread_id,
        )
        result_thread_id = getattr(result, "thread_id", "") or ""
        if result_thread_id and result_thread_id != client.codex_workstation_thread_id:
            WorkstationClient.update_codex_workstation_thread_id(client.id, thread_id=result_thread_id)
        decision = parse_workstation_agent_decision(result.final_response)
    except Exception as error:
        decision = fallback_workstation_agent_decision(reply_text)
        decision.reason = f"{decision.reason} Codex decision fallback: {error.__class__.__name__}: {error}"
    if decision.action in {"send_text", "ask_for_details", "handoff_human"} and not decision.message:
        fallback = fallback_workstation_agent_decision(reply_text)
        decision.message = fallback.message
    return decision


def mirror_workstation_message_media(client: WorkstationClient, messages: list[ContadoresMessage]) -> list[WorkstationMediaAsset]:
    """Copy inbound WhatsApp media into the client's Workstation media folder."""
    existing_paths = {asset.stored_path for asset in WorkstationMediaAsset.list_by_client(client.id)}
    mirrored: list[WorkstationMediaAsset] = []
    for message in messages:
        if message.from_me or not message.media_path:
            continue
        source_path = resolve_message_media_file(message.media_path)
        if source_path is None or not source_path.is_file():
            continue
        safe_name = safe_upload_filename(message.media_filename or source_path.name)
        stored_filename = f"whatsapp-{message.id or uuid.uuid4().hex[:8]}-{safe_name}"
        target_path = client_folder(client) / "media" / stored_filename
        stored_path = relative_data_path(target_path)
        if stored_path in existing_paths:
            continue
        shutil.copy2(source_path, target_path)
        asset = WorkstationMediaAsset.create(
            client_id=client.id,
            asset_id=uuid.uuid4().hex,
            title=message.media_caption or message.media_filename or source_path.name,
            original_filename=message.media_filename or source_path.name,
            stored_filename=stored_filename,
            stored_path=stored_path,
            content_type=message.media_mime_type or mimetypes.guess_type(source_path.name)[0],
            size_bytes=target_path.stat().st_size,
        )
        mirrored.append(asset)
        existing_paths.add(stored_path)
    if mirrored:
        write_client_files(WorkstationClient.get_by_id(client.id) or client)
    return mirrored


def register_generated_workstation_media(
    *,
    client: WorkstationClient,
    source_path: Path,
    title: str,
    stored_filename: str,
    content_type: str | None = None,
) -> WorkstationMediaAsset | None:
    """Copy a generated artifact into media/ and expose it in the Workstation UI."""
    if not source_path.is_file():
        return None
    safe_name = safe_upload_filename(stored_filename or source_path.name)
    target_path = client_folder(client) / "media" / safe_name
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)

    stored_path = relative_data_path(target_path)
    for asset in WorkstationMediaAsset.list_by_client(client.id):
        if asset.stored_path == stored_path:
            return asset

    asset = WorkstationMediaAsset.create(
        client_id=client.id,
        asset_id=uuid.uuid4().hex,
        title=title,
        original_filename=safe_name,
        stored_filename=safe_name,
        stored_path=stored_path,
        content_type=content_type or mimetypes.guess_type(target_path.name)[0],
        size_bytes=target_path.stat().st_size,
    )
    write_client_files(WorkstationClient.get_by_id(client.id) or client)
    return asset


def first_workstation_image_assets(client: WorkstationClient) -> list[WorkstationMediaAsset]:
    """Return image assets that can act as identity/reference photos."""
    return [
        asset
        for asset in WorkstationMediaAsset.list_by_client(client.id)
        if (asset.content_type or "").startswith("image/")
    ]


async def ensure_professional_photo_if_possible(client: WorkstationClient) -> None:
    """Generate one professional photo when the client already provided an image."""
    if list_professional_photo_versions(client):
        return
    image_assets = first_workstation_image_assets(client)
    if not image_assets:
        return
    try:
        await generate_professional_photo(
            client=client,
            assets=[image_assets[0]],
            context=f"Funnel: {client.funnel_id}. Trabajo: pagina web profesional.",
        )
    except Exception as error:
        logger.warning("Could not auto-generate professional photo for %s: %s", client.id, error)


def build_solo_page_codex_prompt(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    version_dir: Path,
    replies: list[ContadoresMessage],
    revision: bool,
    operator_prompt: str = "",
) -> str:
    """Build the Codex prompt for one static solo-page version."""
    write_client_files(client)
    previous_version = latest_landing_page_version_dir(client)
    reply_text = "\n".join(f"- {message.text}" for message in replies if message.text.strip()).strip()
    base_template = (
        REPO_ROOT / "tmp" / "pagina_abogado_static"
        if client.funnel_id == "abogados"
        else REPO_ROOT / "tmp" / "pagina_contador_static"
    )
    professional_photos = list_professional_photo_versions(client)
    photo_paths = "\n".join(item.image_path for item in professional_photos) or "(none)"
    progress_path = workstation_progress_path(client)
    return f"""
Use the workstation-solo-page skill to create a static website draft for this client.

Client folder:
{client_folder(client)}

Client context files to read:
- profile.json
- notes.txt
- conversation.txt

Required output folder:
{version_dir}

Progress file:
{progress_path}

Base template folder to reuse:
{base_template}

Previous page version:
{previous_version or "(none)"}

Client profile:
- Name: {lead.full_name or client.display_name}
- Funnel: {client.funnel_id}
- Fixed offer price: {client.offer_price_usd or "-"} {client.offer_currency or "USD"}
- Phone: {lead.phone or lead.normalized_phone or "-"}
- Email: {lead.email or "-"}

Professional photo versions available:
{photo_paths}

Latest client messages for this version:
{reply_text or "(no new reply text)"}

Operator instruction for this run:
{operator_prompt.strip() or "(none)"}

Requirements:
- Create only static files: index.html, styles.css, script.js, assets/.
- Write preview-message.txt with the exact WhatsApp message to send alongside
  the preview video. Choose copy that fits this client and this run. Ask for
  changes or approval clearly, but do not hardcode a generic template.
- If a professional-photo version exists, treat it as a deliverable too. Prefer
  outbound-messages.json with the standalone professional photo first, asking
  if they like it, and the page preview video as the next message.
- When the client should receive more than one WhatsApp item, also write
  outbound-messages.json with a {{"messages": [...]}} object. Each message can be
  text-only or include media_type plus media_path. Use this for deliverables
  such as the preview video, professional-photo images, documents, or separate
  follow-up text. Keep the order exactly as the client should receive it.
- For outbound-messages.json media_path values, use paths under the client
  folder such as landing-page/vNNN/preview.mp4 or
  professional-photo/vNNN/professional-photo.jpg.
- Use easy-to-read HTML/CSS/JS. Avoid build tools.
- Treat the operator instruction as the main direction for this run when it exists.
- If this is a revision, the required output folder may already contain a copy
  of the previous HTML/CSS/JS/assets. Edit those files in place and keep the
  existing visual direction unless the client explicitly asked for a redesign.
- If client information is incomplete, still create a credible first draft with honest placeholders.
- If the client did not send photos and no professional-photo version exists,
  do not use a portrait, headshot, default person photo, or any image from
  another client. Use generic profession imagery instead, such as law books,
  courtroom details, accounting documents, a calculator, or an office interior.
- Save all files inside the required output folder only.
- Append short progress updates to progress.md after each meaningful step: context read, files written, checks done.
- Do not delete or rewrite old progress.md entries.
- Do not modify source templates, repo files, or other client folders.
- Respond with a short confirmation and the created paths.

Revision mode: {"yes" if revision else "no"}
""".strip()


async def run_solo_page_codex_with_fallback(
    *,
    prompt: str,
    on_turn_started,
    thread_id: str | None = None,
    skills: list[CodexSkill] | None = None,
):
    """Run solo-page Codex with ChatGPT auth first, then API-key auth."""
    selected_skills = skills
    if selected_skills is None:
        selected_skills = [
            CodexSkill(
                name="workstation-solo-page",
                path=str((REPO_ROOT / SOLO_PAGE_SKILL).resolve()),
            )
        ]
    common_kwargs = {
        "skills": selected_skills,
        "model": CONVERSATION_BOT_CODEX_MODEL,
        "effort": CONVERSATION_BOT_CODEX_EFFORT,
        "service_tier": CONVERSATION_BOT_CODEX_SERVICE_TIER,
        "cwd": REPO_ROOT,
        "on_turn_started": on_turn_started,
    }
    try:
        return await run_codex_with_context(
            prompt,
            thread_id=thread_id,
            codex_home=CONVERSATION_BOT_CODEX_CHATGPT_HOME,
            prefer_chatgpt_login=True,
            **common_kwargs,
        )
    except Exception as chatgpt_error:
        chatgpt_error_text = f"{chatgpt_error.__class__.__name__}: {chatgpt_error}"

    api_key_error_text = "OPENAI_API_KEY is not configured"
    if OPENAI_API_KEY.strip():
        try:
            return await run_codex_with_context(
                prompt,
                codex_home=CONVERSATION_BOT_CODEX_API_KEY_HOME,
                prefer_chatgpt_login=False,
                **common_kwargs,
            )
        except Exception as api_key_error:
            api_key_error_text = f"{api_key_error.__class__.__name__}: {api_key_error}"

    raise RuntimeError(
        "Codex ChatGPT failed: "
        f"{chatgpt_error_text}. {CODEX_CHATGPT_REAUTH_HELP}; "
        f"Codex API key failed: {api_key_error_text}"
    )


async def generate_solo_page_version(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    replies: list[ContadoresMessage],
    revision: bool,
    operator_prompt: str = "",
) -> Path:
    """Run Codex to create one landing-page version and render its preview video."""
    if client.id in solo_page_stop_requested_client_ids:
        raise WorkstationCodexStopped("Codex was stopped by the operator.")
    version_dir = next_landing_page_version_dir(client)
    operation = "revision" if revision else "draft"
    previous_version = latest_landing_page_version_dir(client)
    copy_previous_landing_page_version(
        previous_version=previous_version if revision else None,
        version_dir=version_dir,
    )
    append_workstation_progress(client, f"Starting {operation} generation in {relative_data_path(version_dir)}.")
    prompt = build_solo_page_codex_prompt(
        client=client,
        lead=lead,
        version_dir=version_dir,
        replies=replies,
        revision=revision,
        operator_prompt=operator_prompt,
    )

    async def register_turn(turn: object) -> None:
        active_solo_page_codex_turns[client.id] = turn
        active_solo_page_codex_started_at.setdefault(client.id, now_utc())
        if client.id in solo_page_stop_requested_client_ids:
            await interrupt_turn(turn)

    try:
        append_workstation_progress(client, "Prompt prepared. Codex is writing the static page files.")
        try:
            result = await run_solo_page_codex_with_fallback(
                prompt=prompt,
                on_turn_started=register_turn,
                thread_id=client.codex_workstation_thread_id,
            )
            result_thread_id = getattr(result, "thread_id", "") or ""
            if result_thread_id and result_thread_id != client.codex_workstation_thread_id:
                WorkstationClient.update_codex_workstation_thread_id(client.id, thread_id=result_thread_id)
        except Exception as error:
            if client.id in solo_page_stop_requested_client_ids:
                raise WorkstationCodexStopped("Codex was stopped by the operator.") from error
            raise
        finally:
            active_solo_page_codex_turns.pop(client.id, None)
        if client.id in solo_page_stop_requested_client_ids:
            raise WorkstationCodexStopped("Codex was stopped by the operator.")
        append_workstation_progress(client, "Codex finished. Validating generated files.")
        index_path = version_dir / "index.html"
        if not index_path.exists():
            raise RuntimeError(f"Codex did not create {index_path}")
        if not (version_dir / "styles.css").exists():
            raise RuntimeError(f"Codex did not create {version_dir / 'styles.css'}")
        if not (version_dir / "script.js").exists():
            (version_dir / "script.js").write_text("", encoding="utf-8")
        append_workstation_progress(client, "Static files are valid. Rendering preview video.")
        preview_path = version_dir / "preview.mp4"
        await run_in_threadpool(render_landing_page_video_sync, index_path=index_path, output_path=preview_path)
        append_workstation_progress(client, "Preview video rendered.")
        preview_message = read_workstation_preview_message(version_dir)
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "operation": "revision" if revision else "draft",
            "client_id": client.id,
            "lead_id": lead.id,
            "codex_response": result.final_response,
            "source_messages": [message.id for message in replies],
            "operator_prompt": operator_prompt.strip(),
            "preview_path": relative_data_path(preview_path),
            "preview_message": preview_message,
        }
        (version_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        public_page = ensure_workstation_public_page(client, version_dir)
        if public_page is not None:
            append_workstation_progress(
                client,
                f"Public trial URL ready: {workstation_public_page_url(public_page)}",
            )
            write_client_files(client, public_page=public_page)
        register_generated_workstation_media(
            client=client,
            source_path=preview_path,
            title=f"Preview pagina {version_dir.name}",
            stored_filename=f"generated-page-preview-{version_dir.name}.mp4",
            content_type="video/mp4",
        )
        try:
            commit_landing_page_version(client, version_dir, operation=operation)
            append_workstation_progress(client, f"Committed {version_dir.name} page source in client git.")
        except Exception as error:
            append_workstation_progress(client, f"Git commit skipped: {error.__class__.__name__}: {error}")
        append_workstation_progress(client, "Preview media registered in Workstation.")
        return version_dir
    except WorkstationCodexStopped as error:
        append_workstation_progress(client, str(error))
        shutil.rmtree(version_dir, ignore_errors=True)
        raise
    except Exception as error:
        append_workstation_progress(client, f"Failed: {error.__class__.__name__}: {error}")
        shutil.rmtree(version_dir, ignore_errors=True)
        raise


def add_workstation_runtime_alert(
    *,
    lead: ContadoresLead,
    alert_type: str,
    error: str,
    latest_inbound_text: str = "",
) -> None:
    """Create an operator email alert for Workstation automation failures."""
    config = get_effective_funnel_config(lead.funnel_id)
    funnel_label = getattr(config, "label", None) or (lead.funnel_id or "contadores")
    ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label=funnel_label,
        alert_type=alert_type,
        error=error,
        fallback_action="workstation_handoff",
        latest_inbound_text=latest_inbound_text,
    )


def mark_workstation_failed(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    error: str,
    latest_inbound_text: str = "",
) -> None:
    """Stop Workstation automation and alert operators."""
    append_workstation_progress(client, f"Automation failed: {error}")
    WorkstationClient.update_automation_state(
        client.id,
        automation_status=WorkstationAutomationStatus.FAILED,
        last_automation_handled_at=now_utc(),
    )
    add_workstation_runtime_alert(
        lead=lead,
        alert_type="workstation_codex_failure",
        error=error,
        latest_inbound_text=latest_inbound_text,
    )


def record_workstation_nonblocking_issue(
    *,
    client: WorkstationClient,
    error: str,
) -> None:
    """Log an internal Workstation issue that should not stop a delivered preview."""
    append_workstation_progress(client, f"Nonblocking automation issue: {error}")


def mark_workstation_stopped_by_operator(client: WorkstationClient, *, clear_stop_request: bool = True) -> None:
    """Stop automation cleanly without creating a failure alert."""
    clear_solo_page_live_work(client.id)
    if clear_stop_request:
        solo_page_stop_requested_client_ids.discard(client.id)
    manual_solo_page_work_client_ids.discard(client.id)
    WorkstationClient.update_automation_state(
        client.id,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        last_automation_handled_at=now_utc(),
    )
    append_workstation_progress(client, "Codex stopped by operator.")


def workstation_handoff_can_resume(client: WorkstationClient) -> bool:
    """Return True when a human-handoff client can resume from a late reply."""
    return (
        client.work_type == WorkstationClientWorkType.SOLO_PAGINA
        and client.automation_status == WorkstationAutomationStatus.NEEDS_HUMAN
        and client.approved_at is None
        and client.handoff_sent_at is not None
        and client.last_preview_sent_at is not None
    )


def clean_workstation_preview_message(text: object) -> str:
    """Return a safe one-message caption for a Workstation preview video."""
    clean_text = str(text or "").strip()
    if not clean_text:
        return ""
    return " ".join(clean_text.split())[:900].strip()


def read_workstation_preview_message(version_dir: Path) -> str:
    """Read the Codex-chosen WhatsApp caption for one generated preview."""
    message_path = version_dir / "preview-message.txt"
    if message_path.exists():
        text = clean_workstation_preview_message(message_path.read_text(encoding="utf-8"))
        if text:
            return text

    metadata_path = version_dir / "metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata = {}
        if isinstance(metadata, dict):
            for key in ("preview_message", "whatsapp_preview_message", "outbound_text"):
                text = clean_workstation_preview_message(metadata.get(key))
                if text:
                    return text

    return WORKSTATION_DEFAULT_PREVIEW_MESSAGE


def normalize_workstation_outbound_media_type(media_type: object) -> str | None:
    """Return a WhatsApp media type supported by the dispatcher."""
    clean_type = str(media_type or "").strip().lower()
    if clean_type in {"image", "video", "audio", "document"}:
        return clean_type
    return None


def resolve_workstation_outbound_media_path(
    *,
    client: WorkstationClient,
    version_dir: Path,
    media_path: object,
) -> Path | None:
    """Resolve a Codex-written outbound media path inside this Workstation client."""
    clean_path = str(media_path or "").strip()
    if not clean_path:
        return None

    client_root = client_folder(client).resolve()
    version_root = version_dir.resolve()
    data_root = database_module.DATA_DIR.expanduser().resolve()
    candidate = Path(clean_path).expanduser()

    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        parts = candidate.parts
        if parts and parts[0] == "data":
            candidates.append(data_root.joinpath(*parts[1:]))
        candidates.append(version_root / candidate)
        candidates.append(client_root / candidate)

    for path in candidates:
        resolved = path.resolve()
        try:
            resolved.relative_to(client_root)
        except ValueError:
            continue
        if resolved.is_file():
            return resolved
    return None


def build_fallback_workstation_outbound_message(
    *,
    client: WorkstationClient,
    version_dir: Path,
    sequence_step: str,
) -> WorkstationOutboundMessageSpec:
    """Return the preview-video message."""
    preview_path = version_dir / "preview.mp4"
    return WorkstationOutboundMessageSpec(
        text=read_workstation_preview_message(version_dir),
        sequence_step=sequence_step,
        media_type="video",
        media_path=relative_data_path(preview_path),
        media_filename=f"{client.folder_name}-{version_dir.name}.mp4",
    )


def build_professional_photo_outbound_message(
    *,
    client: WorkstationClient,
    sequence_step: str,
) -> WorkstationOutboundMessageSpec | None:
    """Return a standalone professional-photo message when one is available."""
    photo = latest_professional_photo_version(client)
    if photo is None:
        return None
    return WorkstationOutboundMessageSpec(
        text="Le dejo tambien esta foto profesional que armamos con la foto que me mando. Digame si le gusta.",
        sequence_step=sequence_step,
        media_type="image",
        media_path=photo.image_path,
        media_caption="Le dejo tambien esta foto profesional que armamos con la foto que me mando. Digame si le gusta.",
        media_filename=f"{client.folder_name}-{photo.version}-foto-profesional.jpg",
    )


def build_default_workstation_outbound_messages(
    *,
    client: WorkstationClient,
    version_dir: Path,
    sequence_step: str,
) -> list[WorkstationOutboundMessageSpec]:
    """Return the default Workstation delivery plan for generated previews."""
    messages: list[WorkstationOutboundMessageSpec] = []
    if sequence_step == WORKSTATION_PREVIEW_SEQUENCE_STEP:
        photo_message = build_professional_photo_outbound_message(
            client=client,
            sequence_step=sequence_step,
        )
        if photo_message is not None:
            messages.append(photo_message)
    messages.append(
        build_fallback_workstation_outbound_message(
            client=client,
            version_dir=version_dir,
            sequence_step=sequence_step,
        )
    )
    return messages


def parse_workstation_outbound_message(
    *,
    client: WorkstationClient,
    version_dir: Path,
    item: object,
    sequence_step: str,
) -> WorkstationOutboundMessageSpec | None:
    """Parse one Codex-written outbound message object."""
    if not isinstance(item, dict):
        return None

    text = clean_workstation_preview_message(item.get("text") or item.get("message"))
    media_type = normalize_workstation_outbound_media_type(item.get("media_type"))
    media_path: str | None = None
    media_mime_type: str | None = None
    media_filename: str | None = None

    if media_type:
        resolved_path = resolve_workstation_outbound_media_path(
            client=client,
            version_dir=version_dir,
            media_path=item.get("media_path") or item.get("path"),
        )
        if resolved_path is None:
            return None
        media_path = relative_data_path(resolved_path)
        media_mime_type = clean_workstation_preview_message(item.get("media_mime_type"))
        media_filename = clean_workstation_preview_message(item.get("media_filename")) or resolved_path.name

    media_caption = clean_workstation_preview_message(item.get("media_caption") or item.get("caption"))
    if media_type and not media_caption:
        media_caption = text or None

    if not text and not media_type:
        return None

    clean_sequence_step = clean_workstation_preview_message(item.get("sequence_step")) or sequence_step
    return WorkstationOutboundMessageSpec(
        text=text or (f"[{media_type}] {media_filename or 'attachment'}" if media_type else ""),
        sequence_step=clean_sequence_step,
        media_type=media_type,
        media_path=media_path,
        media_caption=media_caption,
        media_mime_type=media_mime_type,
        media_filename=media_filename,
    )


def read_workstation_outbound_messages(
    *,
    client: WorkstationClient,
    version_dir: Path,
    sequence_step: str,
) -> list[WorkstationOutboundMessageSpec]:
    """Read the flexible Codex-written WhatsApp delivery plan for a page version."""
    plan_path = version_dir / "outbound-messages.json"
    if not plan_path.exists():
        return build_default_workstation_outbound_messages(
            client=client,
            version_dir=version_dir,
            sequence_step=sequence_step,
        )

    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {}

    raw_messages = payload.get("messages") if isinstance(payload, dict) else payload
    if not isinstance(raw_messages, list):
        raw_messages = []

    messages: list[WorkstationOutboundMessageSpec] = []
    for item in raw_messages:
        parsed = parse_workstation_outbound_message(
            client=client,
            version_dir=version_dir,
            item=item,
            sequence_step=sequence_step,
        )
        if parsed is not None:
            messages.append(parsed)
    if messages:
        return messages

    return build_default_workstation_outbound_messages(
        client=client,
        version_dir=version_dir,
        sequence_step=sequence_step,
    )


def queue_workstation_preview(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    version_dir: Path,
    sequence_step: str,
) -> list[ContadoresMessage]:
    """Queue the generated Workstation deliverables for WhatsApp delivery."""
    rows: list[ContadoresMessage] = []
    outbound_messages = read_workstation_outbound_messages(
        client=client,
        version_dir=version_dir,
        sequence_step=sequence_step,
    )
    for message in outbound_messages:
        rows.append(
            enqueue_lead_outbound(
                lead=lead,
                text=message.text,
                sequence_step=message.sequence_step,
                media_type=message.media_type,
                media_path=message.media_path,
                media_caption=message.media_caption,
                media_mime_type=message.media_mime_type,
                media_filename=message.media_filename,
            )
        )
    return rows


def latest_preview_queue_timestamp(rows: list[ContadoresMessage]) -> datetime:
    """Return the timestamp to use for Workstation review timers."""
    if not rows:
        return now_utc()
    return max(row.created_at for row in rows)


def queue_workstation_template(
    *,
    lead: ContadoresLead,
    text: str,
    sequence_step: str,
    template_name: str,
) -> ContadoresMessage:
    """Queue a template-backed Workstation reactivation message."""
    clean_template = (template_name or "").strip()
    if not clean_template:
        raise RuntimeError(f"Missing WhatsApp template for {sequence_step}")
    return enqueue_lead_outbound(
        lead=lead,
        text=text,
        sequence_step=sequence_step,
        whatsapp_template_name=clean_template,
        whatsapp_template_language=WORKSTATION_TEMPLATE_LANGUAGE,
    )


def queue_workstation_agent_text(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    text: str,
    sequence_step: str,
    next_status: WorkstationAutomationStatus = WorkstationAutomationStatus.AWAITING_REVIEW,
    anchor_review_timer: bool = True,
) -> ContadoresMessage | None:
    """Queue one conversational Workstation reply chosen by the agent."""
    clean_text = clean_workstation_preview_message(text)
    if not clean_text:
        return None
    row = enqueue_lead_outbound(
        lead=lead,
        text=clean_text,
        sequence_step=sequence_step,
    )
    update_kwargs = {
        "automation_status": next_status,
        "last_automation_handled_at": row.created_at,
    }
    if anchor_review_timer:
        update_kwargs["last_preview_sent_at"] = row.created_at
    WorkstationClient.update_automation_state(client.id, **update_kwargs)
    append_workstation_progress(client, f"Queued agent text reply: {clean_text[:240]}")
    return row


def build_public_page_link_message(public_page: WorkstationPublicPage, text: str | None = None) -> str:
    """Return the WhatsApp text for a public trial page link."""
    clean_text = clean_workstation_preview_message(text)
    if clean_text:
        public_url = workstation_public_page_url(public_page)
        if "{url}" in clean_text:
            return clean_text.replace("{url}", public_url)
        return f"{clean_text}\n{public_url}"
    return (
        "Le dejo la pagina publicada de prueba para que pueda verla y probarla:\n"
        f"{workstation_public_page_url(public_page)}\n\n"
        "Digame si asi le gusta o que quiere ajustar."
    )


def queue_workstation_public_page_link(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    text: str | None = None,
    dispatch_after: datetime | None = None,
) -> ContadoresMessage:
    """Queue the stable public trial URL for the client."""
    public_page = ensure_public_page_for_latest_version(client)
    if public_page is None:
        raise RuntimeError("No public trial page is available for this client.")
    row = enqueue_lead_outbound(
        lead=lead,
        text=build_public_page_link_message(public_page, text),
        sequence_step=WORKSTATION_PUBLIC_PAGE_SEQUENCE_STEP,
        dispatch_after=dispatch_after,
    )
    WorkstationPublicPage.mark_sent(client.id, sent_at=row.created_at)
    WorkstationClient.update_automation_state(
        client.id,
        automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
        last_automation_handled_at=row.created_at,
        last_preview_sent_at=row.created_at,
    )
    append_workstation_progress(client, f"Queued public trial page URL: {workstation_public_page_url(public_page)}")
    return row


async def run_manual_solo_page_work(client_id: str, operator_prompt: str) -> None:
    """Run one operator-triggered solo-page draft or revision."""
    try:
        client = WorkstationClient.get_by_id(client_id)
        if client is None:
            return
        lead = ContadoresLead.get_by_id(client.lead_id)
        if lead is None:
            append_workstation_progress(client, "Manual Codex run failed: source lead was not found.")
            return

        now = now_utc()
        messages = ContadoresMessage.list_by_lead(lead.id)
        mirror_workstation_message_media(client, messages)
        fresh_client = WorkstationClient.get_by_id(client.id) or client
        revision = latest_landing_page_version_dir(fresh_client) is not None
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=(
                WorkstationAutomationStatus.REVISION_REQUESTED
                if revision
                else WorkstationAutomationStatus.DRAFTING
            ),
            last_automation_handled_at=now,
        )
        append_workstation_progress(
            fresh_client,
            "Operator started Codex manually from Workstation Actions.",
        )
        try:
            await ensure_professional_photo_if_possible(fresh_client)
            latest_client_replies = [message for message in messages if not message.from_me]
            version_dir = await generate_solo_page_version(
                client=WorkstationClient.get_by_id(fresh_client.id) or fresh_client,
                lead=lead,
                replies=latest_client_replies,
                revision=revision,
                operator_prompt=operator_prompt,
            )
            rows = queue_workstation_preview(
                client=fresh_client,
                lead=lead,
                version_dir=version_dir,
                sequence_step=(
                    WORKSTATION_REVISION_SEQUENCE_STEP
                    if revision
                    else WORKSTATION_PREVIEW_SEQUENCE_STEP
                ),
            )
            if revision and workstation_public_page_was_sent(fresh_client):
                rows.append(
                    queue_workstation_public_page_link(
                        client=fresh_client,
                        lead=lead,
                        text="Ya actualice la pagina. Puede revisarla aca y decirme si asi queda bien: {url}",
                    )
                )
        except WorkstationCodexStopped:
            mark_workstation_stopped_by_operator(fresh_client)
            return
        except Exception as error:
            mark_workstation_failed(
                client=fresh_client,
                lead=lead,
                error=f"{error.__class__.__name__}: {error}",
                latest_inbound_text=operator_prompt,
            )
            return

        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=now_utc(),
            last_preview_sent_at=latest_preview_queue_timestamp(rows),
        )
        append_workstation_progress(
            fresh_client,
            f"Queued {len(rows)} manual Codex deliverable(s) for WhatsApp.",
        )
    finally:
        manual_solo_page_work_client_ids.discard(client_id)
        solo_page_stop_requested_client_ids.discard(client_id)
        clear_solo_page_live_work(client_id)


async def generate_solo_page_version_observed(**kwargs) -> Path:
    """Run generation while marking the current backend task as live work."""
    client = kwargs["client"]
    current_task = asyncio.current_task()
    if current_task is not None:
        register_solo_page_task(client.id, current_task)
    try:
        return await generate_solo_page_version(**kwargs)
    finally:
        if active_solo_page_codex_tasks.get(client.id) is current_task:
            clear_solo_page_live_work(client.id)


def process_workstation_pings(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    messages: list[ContadoresMessage],
    now: datetime,
) -> int:
    """Send staged template pings when a preview is waiting for review."""
    if client.automation_status != WorkstationAutomationStatus.AWAITING_REVIEW:
        return 0
    if client.last_preview_sent_at is None:
        return 0
    if inbound_after(messages, client.last_preview_sent_at):
        return 0

    preview_sent_at = normalize_utc(client.last_preview_sent_at)
    current_time = normalize_utc(now) or now
    if preview_sent_at is None:
        return 0

    elapsed = current_time - preview_sent_at
    if client.handoff_sent_at is None and elapsed >= timedelta(seconds=WORKSTATION_HANDOFF_DELAY_SECONDS):
        queue_workstation_template(
            lead=lead,
            text=WORKSTATION_HUMAN_HANDOFF_TEXT,
            sequence_step=WORKSTATION_HANDOFF_SEQUENCE_STEP,
            template_name=WORKSTATION_HANDOFF_TEMPLATE_NAME,
        )
        WorkstationClient.update_automation_state(
            client.id,
            automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
            handoff_sent_at=now,
            last_automation_handled_at=now,
        )
        ContadoresLead.update_flow_state(
            lead.id,
            stage="needs_human",
            automation_paused=True,
            automation_paused_reason="workstation_no_response_handoff",
            last_classification_label="workstation_no_response_handoff",
            last_classification_reason="El cliente no respondio a los pings del boceto; seguir por humano.",
            clear_needs_human_notified_at=True,
        )
        return 1
    if client.ping_2_sent_at is None and elapsed >= timedelta(seconds=WORKSTATION_PING_2_DELAY_SECONDS):
        queue_workstation_template(
            lead=lead,
            text=WORKSTATION_PING_2_TEXT,
            sequence_step=WORKSTATION_PING_2_SEQUENCE_STEP,
            template_name=WORKSTATION_PING_TEMPLATE_2_NAME,
        )
        WorkstationClient.update_automation_state(
            client.id,
            ping_2_sent_at=now,
            last_automation_handled_at=now,
        )
        return 1
    if client.ping_1_sent_at is None and elapsed >= timedelta(seconds=WORKSTATION_PING_1_DELAY_SECONDS):
        queue_workstation_template(
            lead=lead,
            text=WORKSTATION_PING_1_TEXT,
            sequence_step=WORKSTATION_PING_1_SEQUENCE_STEP,
            template_name=WORKSTATION_PING_TEMPLATE_1_NAME,
        )
        WorkstationClient.update_automation_state(
            client.id,
            ping_1_sent_at=now,
            last_automation_handled_at=now,
        )
        return 1
    return 0


async def advance_solo_page_client(client: WorkstationClient, *, now: datetime) -> dict[str, int]:
    """Advance one solo-page Workstation client by at most one step."""
    metrics = {
        "intake_messages_sent": 0,
        "drafts_generated": 0,
        "revision_videos_sent": 0,
        "approvals": 0,
        "pings_sent": 0,
        "human_handoffs": 0,
        "failures": 0,
    }
    lead = ContadoresLead.get_by_id(client.lead_id)
    if lead is None:
        append_workstation_progress(client, "Automation failed: source lead was not found.")
        WorkstationClient.update_automation_state(
            client.id,
            automation_status=WorkstationAutomationStatus.FAILED,
            last_automation_handled_at=now,
        )
        metrics["failures"] = 1
        return metrics

    messages = ContadoresMessage.list_by_lead(lead.id)
    mirror_workstation_message_media(client, messages)
    fresh_client = WorkstationClient.get_by_id(client.id) or client

    if fresh_client.automation_status in {
        WorkstationAutomationStatus.DRAFTING,
        WorkstationAutomationStatus.REVISION_REQUESTED,
    }:
        if workstation_working_status_is_stale(fresh_client, now=now):
            operation = (
                "draft"
                if fresh_client.automation_status == WorkstationAutomationStatus.DRAFTING
                else "revision"
            )
            mark_workstation_failed(
                client=fresh_client,
                lead=lead,
                error=f"Workstation {operation} stayed in progress for more than 2 hours.",
            )
            metrics["failures"] = 1
        return metrics

    if fresh_client.automation_status == WorkstationAutomationStatus.INTAKE:
        intake_was_sent = any(
            message.from_me and message.sequence_step == WORKSTATION_INTAKE_SEQUENCE_STEP
            for message in messages
        )
        use_existing_context = (
            not intake_was_sent
            and fresh_client.last_automation_handled_at is None
            and has_existing_solo_page_context(fresh_client, messages)
        )
        if not intake_was_sent and not use_existing_context:
            enqueue_lead_outbound(
                lead=lead,
                text=WORKSTATION_INTAKE_TEXT,
                sequence_step=WORKSTATION_INTAKE_SEQUENCE_STEP,
            )
            append_workstation_progress(fresh_client, "Sent intake question to the client.")
            WorkstationClient.update_automation_state(
                fresh_client.id,
                automation_status=WorkstationAutomationStatus.INTAKE,
                last_automation_handled_at=now,
            )
            metrics["intake_messages_sent"] = 1
            return metrics

        replies = inbound_after(messages, None) if use_existing_context else inbound_after(
            messages,
            fresh_client.last_automation_handled_at,
        )
        if not replies or not latest_inbound_is_quiet(replies, now=now):
            return metrics
        decision = await decide_workstation_next_action(
            client=fresh_client,
            lead=lead,
            replies=replies,
        )
        append_workstation_progress(
            fresh_client,
            f"Intake agent decision: {decision.action}. {decision.reason[:240]}",
        )
        if decision.action in {"send_text", "ask_for_details"}:
            try:
                queue_workstation_agent_text(
                    client=fresh_client,
                    lead=lead,
                    text=decision.message,
                    sequence_step=WORKSTATION_INTAKE_SEQUENCE_STEP,
                    next_status=WorkstationAutomationStatus.INTAKE,
                    anchor_review_timer=False,
                )
                metrics["intake_messages_sent"] = 1
            except Exception as error:
                mark_workstation_failed(
                    client=fresh_client,
                    lead=lead,
                    error=f"{error.__class__.__name__}: {error}",
                    latest_inbound_text=replies[-1].text if replies else "",
                )
                metrics["failures"] = 1
            return metrics
        if decision.action in {"handoff_human", "approve_and_handoff"}:
            append_workstation_progress(fresh_client, "Agent chose human handoff during intake.")
            WorkstationClient.update_automation_state(
                fresh_client.id,
                automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
                last_automation_handled_at=now,
            )
            ContadoresLead.update_flow_state(
                lead.id,
                stage="needs_human",
                automation_paused=True,
                automation_paused_reason="workstation_agent_handoff",
                last_classification_label="workstation_agent_handoff",
                last_classification_reason=decision.reason or "El agente de Workstation pidio intervencion humana.",
                clear_needs_human_notified_at=True,
            )
            metrics["human_handoffs"] = 1
            return metrics
        if decision.action == "no_action":
            WorkstationClient.update_automation_state(
                fresh_client.id,
                last_automation_handled_at=now,
            )
            return metrics
        if decision.action != "generate_or_revise_page":
            return metrics
        append_workstation_progress(fresh_client, "Quiet window complete. Starting first draft.")
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.DRAFTING,
            last_automation_handled_at=now,
        )
        try:
            await ensure_professional_photo_if_possible(fresh_client)
            version_dir = await generate_solo_page_version_observed(
                client=WorkstationClient.get_by_id(fresh_client.id) or fresh_client,
                lead=lead,
                replies=replies,
                revision=False,
            )
            rows = queue_workstation_preview(
                client=fresh_client,
                lead=lead,
                version_dir=version_dir,
                sequence_step=WORKSTATION_PREVIEW_SEQUENCE_STEP,
            )
        except WorkstationCodexStopped:
            mark_workstation_stopped_by_operator(fresh_client)
            return metrics
        except Exception as error:
            mark_workstation_failed(
                client=fresh_client,
                lead=lead,
                error=f"{error.__class__.__name__}: {error}",
                latest_inbound_text=replies[-1].text if replies else "",
            )
            metrics["failures"] = 1
            return metrics
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=now,
            last_preview_sent_at=latest_preview_queue_timestamp(rows),
        )
        append_workstation_progress(fresh_client, f"Queued {len(rows)} draft deliverable(s) for WhatsApp.")
        metrics["drafts_generated"] = 1
        metrics["revision_videos_sent"] = 1
        return metrics

    if fresh_client.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW:
        replies = inbound_after(messages, fresh_client.last_preview_sent_at)
        if not replies:
            try:
                metrics["pings_sent"] = process_workstation_pings(
                    client=fresh_client,
                    lead=lead,
                    messages=messages,
                    now=now,
                )
                preview_sent_at = normalize_utc(fresh_client.last_preview_sent_at)
                current_time = normalize_utc(now) or now
                handoff_due = (
                    preview_sent_at is not None
                    and current_time - preview_sent_at >= timedelta(seconds=WORKSTATION_HANDOFF_DELAY_SECONDS)
                )
                metrics["human_handoffs"] = 1 if metrics["pings_sent"] and handoff_due else 0
            except Exception as error:
                record_workstation_nonblocking_issue(
                    client=fresh_client,
                    error=f"{error.__class__.__name__}: {error}",
                )
            return metrics
        if not latest_inbound_is_quiet(replies, now=now):
            return metrics
        reply_text = "\n".join(message.text for message in replies if message.text.strip())
        decision = await decide_workstation_next_action(
            client=fresh_client,
            lead=lead,
            replies=replies,
        )
        append_workstation_progress(
            fresh_client,
            f"Agent decision: {decision.action}. {decision.reason[:240]}",
        )
        if decision.action == "no_action":
            WorkstationClient.update_automation_state(
                fresh_client.id,
                last_automation_handled_at=now,
            )
            return metrics
        if decision.action in {"send_text", "ask_for_details"}:
            try:
                queue_workstation_agent_text(
                    client=fresh_client,
                    lead=lead,
                    text=decision.message,
                    sequence_step=WORKSTATION_REVISION_SEQUENCE_STEP,
                )
            except Exception as error:
                mark_workstation_failed(
                    client=fresh_client,
                    lead=lead,
                    error=f"{error.__class__.__name__}: {error}",
                    latest_inbound_text=replies[-1].text if replies else "",
                )
                metrics["failures"] = 1
            return metrics
        if decision.action == "send_public_page_link":
            try:
                queue_workstation_public_page_link(
                    client=fresh_client,
                    lead=lead,
                    text=decision.message,
                )
            except Exception as error:
                mark_workstation_failed(
                    client=fresh_client,
                    lead=lead,
                    error=f"{error.__class__.__name__}: {error}",
                    latest_inbound_text=replies[-1].text if replies else "",
                )
                metrics["failures"] = 1
            return metrics
        if decision.action == "handoff_human":
            append_workstation_progress(fresh_client, "Agent chose human handoff.")
            if decision.message:
                try:
                    queue_workstation_agent_text(
                        client=fresh_client,
                        lead=lead,
                        text=decision.message,
                        sequence_step=WORKSTATION_HANDOFF_SEQUENCE_STEP,
                    )
                except Exception as error:
                    record_workstation_nonblocking_issue(
                        client=fresh_client,
                        error=f"{error.__class__.__name__}: {error}",
                    )
            WorkstationClient.update_automation_state(
                fresh_client.id,
                automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
                last_automation_handled_at=now,
            )
            ContadoresLead.update_flow_state(
                lead.id,
                stage="needs_human",
                automation_paused=True,
                automation_paused_reason="workstation_agent_handoff",
                last_classification_label="workstation_agent_handoff",
                last_classification_reason=decision.reason or "El agente de Workstation pidio intervencion humana.",
                clear_needs_human_notified_at=True,
            )
            metrics["human_handoffs"] = 1
            return metrics
        if decision.action == "approve_and_handoff" or text_shows_workstation_approval(reply_text):
            public_page = ensure_public_page_for_latest_version(fresh_client)
            if public_page is not None and public_page.last_sent_at is None:
                append_workstation_progress(
                    fresh_client,
                    "Client approved the video preview. Sending public trial URL before final approval.",
                )
                try:
                    queue_workstation_public_page_link(
                        client=fresh_client,
                        lead=lead,
                        text=decision.message,
                    )
                except Exception as error:
                    mark_workstation_failed(
                        client=fresh_client,
                        lead=lead,
                        error=f"{error.__class__.__name__}: {error}",
                        latest_inbound_text=replies[-1].text if replies else "",
                    )
                    metrics["failures"] = 1
                return metrics
            append_workstation_progress(fresh_client, "Client approved the preview. Handing off to operator.")
            WorkstationClient.update_automation_state(
                fresh_client.id,
                automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
                approved_at=now,
                last_automation_handled_at=now,
            )
            ContadoresLead.update_flow_state(
                lead.id,
                stage="needs_human",
                automation_paused=True,
                automation_paused_reason="workstation_solo_page_approved",
                last_classification_label="workstation_solo_page_approved",
                last_classification_reason=(
                    "El cliente aprobo el boceto de pagina. Comprar dominio, deployar y coordinar cobro."
                ),
                clear_needs_human_notified_at=True,
            )
            metrics["approvals"] = 1
            metrics["human_handoffs"] = 1
            return metrics
        if decision.action != "generate_or_revise_page":
            return metrics

        append_workstation_progress(fresh_client, "Quiet window complete. Starting revision.")
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.REVISION_REQUESTED,
            last_automation_handled_at=now,
        )
        try:
            version_dir = await generate_solo_page_version_observed(
                client=fresh_client,
                lead=lead,
                replies=replies,
                revision=True,
            )
            rows = queue_workstation_preview(
                client=fresh_client,
                lead=lead,
                version_dir=version_dir,
                sequence_step=WORKSTATION_REVISION_SEQUENCE_STEP,
            )
            if workstation_public_page_was_sent(fresh_client):
                rows.append(
                    queue_workstation_public_page_link(
                        client=fresh_client,
                        lead=lead,
                        text="Ya actualice la pagina. Puede revisarla aca y decirme si asi queda bien: {url}",
                    )
                )
        except WorkstationCodexStopped:
            mark_workstation_stopped_by_operator(fresh_client)
            return metrics
        except Exception as error:
            mark_workstation_failed(
                client=fresh_client,
                lead=lead,
                error=f"{error.__class__.__name__}: {error}",
                latest_inbound_text=replies[-1].text if replies else "",
            )
            metrics["failures"] = 1
            return metrics
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=now,
            last_preview_sent_at=latest_preview_queue_timestamp(rows),
        )
        append_workstation_progress(fresh_client, f"Queued {len(rows)} revision deliverable(s) for WhatsApp.")
        metrics["revision_videos_sent"] = 1
        return metrics

    if workstation_handoff_can_resume(fresh_client):
        replies = inbound_after(messages, fresh_client.last_preview_sent_at)
        if not replies:
            return metrics
        if not latest_inbound_is_quiet(replies, now=now):
            return metrics
        reply_text = "\n".join(message.text for message in replies if message.text.strip())
        decision = await decide_workstation_next_action(
            client=fresh_client,
            lead=lead,
            replies=replies,
            handoff_resume=True,
        )
        append_workstation_progress(
            fresh_client,
            f"Post-handoff agent decision: {decision.action}. {decision.reason[:240]}",
        )
        if decision.action == "no_action":
            WorkstationClient.update_automation_state(
                fresh_client.id,
                last_automation_handled_at=now,
            )
            return metrics
        if decision.action in {"send_text", "ask_for_details"}:
            try:
                queue_workstation_agent_text(
                    client=fresh_client,
                    lead=lead,
                    text=decision.message,
                    sequence_step=WORKSTATION_REVISION_SEQUENCE_STEP,
                )
            except Exception as error:
                mark_workstation_failed(
                    client=fresh_client,
                    lead=lead,
                    error=f"{error.__class__.__name__}: {error}",
                    latest_inbound_text=replies[-1].text if replies else "",
                )
                metrics["failures"] = 1
            return metrics
        if decision.action == "send_public_page_link":
            try:
                queue_workstation_public_page_link(
                    client=fresh_client,
                    lead=lead,
                    text=decision.message,
                )
            except Exception as error:
                mark_workstation_failed(
                    client=fresh_client,
                    lead=lead,
                    error=f"{error.__class__.__name__}: {error}",
                    latest_inbound_text=replies[-1].text if replies else "",
                )
                metrics["failures"] = 1
            return metrics
        if decision.action == "handoff_human":
            append_workstation_progress(fresh_client, "Agent kept this post-handoff reply with a human.")
            WorkstationClient.update_automation_state(
                fresh_client.id,
                automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
                last_automation_handled_at=now,
            )
            metrics["human_handoffs"] = 1
            return metrics
        if decision.action == "approve_and_handoff" or text_shows_workstation_approval(reply_text):
            public_page = ensure_public_page_for_latest_version(fresh_client)
            if public_page is not None and public_page.last_sent_at is None:
                append_workstation_progress(
                    fresh_client,
                    "Client approved after handoff. Sending public trial URL before final approval.",
                )
                try:
                    queue_workstation_public_page_link(
                        client=fresh_client,
                        lead=lead,
                        text=decision.message,
                    )
                except Exception as error:
                    mark_workstation_failed(
                        client=fresh_client,
                        lead=lead,
                        error=f"{error.__class__.__name__}: {error}",
                        latest_inbound_text=replies[-1].text if replies else "",
                    )
                    metrics["failures"] = 1
                return metrics
            append_workstation_progress(fresh_client, "Client replied after handoff and approved the preview.")
            WorkstationClient.update_automation_state(
                fresh_client.id,
                approved_at=now,
                last_automation_handled_at=now,
            )
            metrics["approvals"] = 1
            return metrics
        if decision.action != "generate_or_revise_page":
            return metrics

        append_workstation_progress(fresh_client, "Client replied after handoff. Starting revision.")
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.REVISION_REQUESTED,
            last_automation_handled_at=now,
        )
        try:
            version_dir = await generate_solo_page_version_observed(
                client=fresh_client,
                lead=lead,
                replies=replies,
                revision=True,
            )
            rows = queue_workstation_preview(
                client=fresh_client,
                lead=lead,
                version_dir=version_dir,
                sequence_step=WORKSTATION_REVISION_SEQUENCE_STEP,
            )
            if workstation_public_page_was_sent(fresh_client):
                rows.append(
                    queue_workstation_public_page_link(
                        client=fresh_client,
                        lead=lead,
                        text="Ya actualice la pagina. Puede revisarla aca y decirme si asi queda bien: {url}",
                    )
                )
        except WorkstationCodexStopped:
            mark_workstation_stopped_by_operator(fresh_client)
            return metrics
        except Exception as error:
            mark_workstation_failed(
                client=fresh_client,
                lead=lead,
                error=f"{error.__class__.__name__}: {error}",
                latest_inbound_text=replies[-1].text if replies else "",
            )
            metrics["failures"] = 1
            return metrics
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=now,
            last_preview_sent_at=latest_preview_queue_timestamp(rows),
        )
        append_workstation_progress(
            fresh_client,
            f"Queued {len(rows)} post-handoff revision deliverable(s) for WhatsApp.",
        )
        metrics["revision_videos_sent"] = 1
        return metrics

    return metrics


def build_client_summary(client: WorkstationClient) -> WorkstationClientSummary:
    """Serialize one Workstation client for list/detail views."""
    lead = ContadoresLead.get_by_id(client.lead_id)
    folder = client_folder(client)
    media = WorkstationMediaAsset.list_by_client(client.id)
    return WorkstationClientSummary(
        id=client.id,
        lead_id=client.lead_id,
        funnel_id=client.funnel_id,
        work_type=client.work_type.value,
        status=client.status.value,
        automation_status=client.automation_status.value,
        offer_price_usd=client.offer_price_usd,
        offer_currency=client.offer_currency,
        display_name=client.display_name,
        folder_name=client.folder_name,
        folder_path=relative_data_path(folder),
        media_count=len(media),
        lead=lead_summary_for_workstation(lead) if lead else None,
        last_automation_handled_at=format_timestamp_seconds(client.last_automation_handled_at),
        last_preview_sent_at=format_timestamp_seconds(client.last_preview_sent_at),
        approved_at=format_timestamp_seconds(client.approved_at),
        ping_1_sent_at=format_timestamp_seconds(client.ping_1_sent_at),
        ping_2_sent_at=format_timestamp_seconds(client.ping_2_sent_at),
        handoff_sent_at=format_timestamp_seconds(client.handoff_sent_at),
        created_at=format_timestamp_seconds(client.created_at) or "",
        updated_at=format_timestamp_seconds(client.updated_at) or "",
    )


def build_runtime_alert_response(alert: ContadoresRuntimeAlert) -> WorkstationRuntimeAlertResponse:
    """Serialize one Workstation runtime alert for operators."""
    return WorkstationRuntimeAlertResponse(
        id=int(alert.id or 0),
        alert_type=alert.alert_type,
        error=alert.error,
        fallback_action=alert.fallback_action,
        latest_inbound_text=alert.latest_inbound_text,
        notified_at=format_timestamp_seconds(alert.notified_at),
        resolved_at=format_timestamp_seconds(alert.resolved_at),
        email_thread_id=alert.email_thread_id,
        email_message_id=alert.email_message_id,
        created_at=format_timestamp_seconds(alert.created_at) or "",
    )


def build_waiting_backoff_state(
    *,
    client: WorkstationClient,
    status: str,
    replies: list[ContadoresMessage],
    detail: str,
) -> WorkstationAutomationStateResponse:
    """Build the repeated backoff status shape for the UI."""
    progress_markdown, progress_path, progress_updated_at = read_workstation_progress(client)
    backoff_until = backoff_until_for(replies)
    return WorkstationAutomationStateResponse(
        status=status,
        label="Waiting backoff",
        detail=detail,
        is_waiting_backoff=True,
        backoff_until=format_timestamp_seconds(backoff_until),
        latest_inbound_at=format_timestamp_seconds(latest_message_at(replies)),
        progress_path=progress_path,
        progress_markdown=progress_markdown,
        progress_updated_at=progress_updated_at,
    )


def build_workstation_automation_state(
    client: WorkstationClient,
    messages: list[ContadoresMessage],
) -> WorkstationAutomationStateResponse:
    """Describe what the Workstation automation is doing right now."""
    progress_markdown, progress_path, progress_updated_at = read_workstation_progress(client)
    status = client.automation_status.value
    base = {
        "status": status,
        "progress_path": progress_path,
        "progress_markdown": progress_markdown,
        "progress_updated_at": progress_updated_at,
        **observed_solo_page_live_status(client.id),
    }
    if client.work_type != WorkstationClientWorkType.SOLO_PAGINA:
        return WorkstationAutomationStateResponse(
            **base,
            label="Manual workspace",
            detail="This client does not have solo-page automation assigned.",
        )
    if client.status == WorkstationClientStatus.CLOSED:
        return WorkstationAutomationStateResponse(
            **base,
            label="Closed lead",
            detail="Workstation is closed for this lead. Automation will not spend more tokens here.",
        )

    if client.automation_status == WorkstationAutomationStatus.FAILED:
        return WorkstationAutomationStateResponse(
            **base,
            label="Failed",
            detail="Automation stopped. The failure alert and email status are shown on this client.",
        )
    now = now_utc()
    if client.automation_status in {WorkstationAutomationStatus.DRAFTING, WorkstationAutomationStatus.REVISION_REQUESTED}:
        operation = "first draft" if client.automation_status == WorkstationAutomationStatus.DRAFTING else "revision"
        if workstation_working_status_is_stale(client, now=now):
            return WorkstationAutomationStateResponse(
                **base,
                label="Stale working state",
                detail=(
                    f"The {operation} has been marked as working for more than 2 hours. "
                    "The next Workstation tick will fail it and create an operator alert."
                ),
                is_stale=True,
            )
        live = bool(base["is_live_working"])
        if not live:
            return WorkstationAutomationStateResponse(
                **base,
                label="No live Codex process",
                detail=(
                    f"The database says the {operation} is in progress, but this backend "
                    "does not have a live task or Codex turn for it."
                ),
                is_working=False,
            )
        return WorkstationAutomationStateResponse(
            **base,
            label="Codex working",
            detail=f"Observed live process: Codex is generating the {operation} or rendering the preview video.",
            is_working=True,
        )
    if workstation_handoff_can_resume(client):
        replies = inbound_after(messages, client.last_preview_sent_at)
        if not replies:
            return WorkstationAutomationStateResponse(
                **base,
                label="Human handoff",
                detail="Automation handed this job to an operator after no preview response.",
            )
        if not latest_inbound_is_quiet(replies, now=now):
            return build_waiting_backoff_state(
                client=client,
                status=status,
                replies=replies,
                detail="The client replied after human handoff. Workstation waits 20 minutes before processing it.",
            )
        reply_text = "\n".join(message.text for message in replies if message.text.strip())
        if text_shows_workstation_approval(reply_text):
            return WorkstationAutomationStateResponse(
                **base,
                label="Approval ready",
                detail="The client replied after handoff and appears to approve the preview.",
                latest_inbound_at=format_timestamp_seconds(latest_message_at(replies)),
            )
        return WorkstationAutomationStateResponse(
            **base,
            label="Agent decision ready",
            detail="The client replied after handoff. The next tick will decide whether to answer, ask, revise, or hand off.",
            latest_inbound_at=format_timestamp_seconds(latest_message_at(replies)),
        )

    if client.automation_status == WorkstationAutomationStatus.NEEDS_HUMAN:
        approved = "approved by the client" if client.approved_at else "waiting for an operator"
        return WorkstationAutomationStateResponse(
            **base,
            label="Human handoff",
            detail=f"Automation is idle because this job is {approved}.",
        )
    if client.automation_status == WorkstationAutomationStatus.APPROVED:
        return WorkstationAutomationStateResponse(
            **base,
            label="Approved",
            detail="Automation is idle because the page was approved.",
        )

    if client.automation_status == WorkstationAutomationStatus.INTAKE:
        intake_was_sent = any(
            message.from_me and message.sequence_step == WORKSTATION_INTAKE_SEQUENCE_STEP
            for message in messages
        )
        use_existing_context = (
            not intake_was_sent
            and client.last_automation_handled_at is None
            and has_existing_solo_page_context(client, messages)
        )
        if not intake_was_sent and not use_existing_context:
            return WorkstationAutomationStateResponse(
                **base,
                label="Ready to send intake",
                detail="The next Workstation tick will ask the client for page details.",
            )
        replies = inbound_after(messages, None) if use_existing_context else inbound_after(
            messages,
            client.last_automation_handled_at,
        )
        if not replies:
            return WorkstationAutomationStateResponse(
                **base,
                label="Waiting for client info",
                detail="The intake question was sent and no page details have arrived yet.",
            )
        if not latest_inbound_is_quiet(replies, now=now):
            return build_waiting_backoff_state(
                client=client,
                status=status,
                replies=replies,
                detail="The client sent information recently. Workstation waits 20 minutes of silence before drafting.",
            )
        return WorkstationAutomationStateResponse(
            **base,
            label="Agent decision ready",
            detail="The quiet window is complete. The next Workstation tick will decide whether to answer, ask, draft, or hand off.",
            latest_inbound_at=format_timestamp_seconds(latest_message_at(replies)),
        )

    if client.automation_status == WorkstationAutomationStatus.AWAITING_REVIEW:
        replies = inbound_after(messages, client.last_preview_sent_at)
        if not replies:
            return WorkstationAutomationStateResponse(
                **base,
                label="Waiting for lead review",
                detail="The preview was sent and Workstation is waiting for the client's reply.",
            )
        if not latest_inbound_is_quiet(replies, now=now):
            return build_waiting_backoff_state(
                client=client,
                status=status,
                replies=replies,
                detail="The client sent replies or files after the preview. Workstation waits 20 minutes before processing them.",
            )
        reply_text = "\n".join(message.text for message in replies if message.text.strip())
        if text_shows_workstation_approval(reply_text):
            return WorkstationAutomationStateResponse(
                **base,
                label="Approval ready",
                detail="The client appears to have approved the preview. The next tick will hand this to an operator.",
                latest_inbound_at=format_timestamp_seconds(latest_message_at(replies)),
            )
        return WorkstationAutomationStateResponse(
            **base,
            label="Agent decision ready",
            detail="The quiet window is complete. The next tick will decide whether to answer, ask, revise, approve, or hand off.",
            latest_inbound_at=format_timestamp_seconds(latest_message_at(replies)),
        )

    return WorkstationAutomationStateResponse(
        **base,
        label="Idle",
        detail="No active Workstation automation step is running.",
    )


def build_client_detail(client: WorkstationClient) -> WorkstationClientDetailResponse:
    """Build one complete Workstation client response."""
    lead = get_required_lead(client.lead_id)
    messages = ContadoresMessage.list_by_lead(client.lead_id)
    media = WorkstationMediaAsset.list_by_client(client.id)
    runtime_alerts = ContadoresRuntimeAlert.list_recent_by_lead(client.lead_id)
    public_page = ensure_public_page_for_latest_version(client)
    write_client_files(client, public_page=public_page)
    return WorkstationClientDetailResponse(
        client=build_client_summary(client),
        notes=client.notes,
        messages=[build_message_response(message) for message in messages],
        media=[build_media_response(asset) for asset in media],
        runtime_alerts=[build_runtime_alert_response(alert) for alert in runtime_alerts],
        automation_state=build_workstation_automation_state(client, messages),
        professional_photos=list_professional_photo_versions(client),
        public_page=build_public_page_response(public_page),
    )


def backfill_workstation_public_pages(*, limit: int = 1000) -> int:
    """Create stable public URLs for existing solo-page clients with generated pages."""
    created_or_updated = 0
    for client in WorkstationClient.list_recent(
        limit=limit,
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
    ):
        public_page = ensure_public_page_for_latest_version(client)
        if public_page is None:
            continue
        write_client_files(client, public_page=public_page)
        created_or_updated += 1
    return created_or_updated


def get_public_page_or_404(public_token: str) -> WorkstationPublicPage:
    """Return one active public page or raise a 404."""
    public_page = WorkstationPublicPage.get_active_by_token(public_token)
    if public_page is None:
        raise HTTPException(status_code=404, detail="Public page not found")
    return public_page


def resolve_public_page_file(public_page: WorkstationPublicPage, asset_path: str | None) -> Path:
    """Resolve a public page asset without allowing directory traversal."""
    version_dir = resolve_public_page_version_dir(public_page)
    clean_path = (asset_path or "index.html").strip() or "index.html"
    candidate = (version_dir / Path(clean_path)).resolve()
    try:
        candidate.relative_to(version_dir)
    except ValueError:
        raise HTTPException(status_code=404, detail="Public page asset not found")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Public page asset not found")
    return candidate


@public_workstation_router.get("/p/{public_token}")
async def redirect_public_workstation_page(public_token: str) -> RedirectResponse:
    """Redirect slashless public trial URLs to the static page root."""
    get_public_page_or_404(public_token)
    return RedirectResponse(url=f"/p/{public_token}/", status_code=307)


@public_workstation_router.get("/p/{public_token}/")
async def serve_public_workstation_page(public_token: str) -> FileResponse:
    """Serve the current public trial page HTML."""
    public_page = get_public_page_or_404(public_token)
    path = resolve_public_page_file(public_page, "index.html")
    return FileResponse(path, media_type="text/html", content_disposition_type="inline")


@public_workstation_router.get("/p/{public_token}/{asset_path:path}")
async def serve_public_workstation_page_asset(public_token: str, asset_path: str) -> FileResponse:
    """Serve one static asset from the current public trial page version."""
    public_page = get_public_page_or_404(public_token)
    path = resolve_public_page_file(public_page, asset_path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, content_disposition_type="inline")


@workstation_router.get("/clients", response_model=WorkstationClientListResponse)
async def list_workstation_clients(
    limit: int = Query(default=300, ge=1, le=1000),
    funnel_id: str | None = None,
    query: str | None = None,
) -> WorkstationClientListResponse:
    """List converted clients for the Workstation."""
    clients = WorkstationClient.list_recent(
        limit=limit,
        funnel_id=funnel_id,
    )
    query_value = (query or "").strip().lower()
    visible: list[WorkstationClient] = []
    for client in clients:
        if client.status == WorkstationClientStatus.CLOSED:
            continue
        lead = ContadoresLead.get_by_id(client.lead_id)
        haystack = " ".join(
            [
                client.display_name or "",
                client.funnel_id or "",
                client.folder_name or "",
                (lead.full_name or "") if lead else "",
                (lead.phone or "") if lead else "",
                (lead.email or "") if lead else "",
                (lead.external_lead_id or "") if lead else "",
            ]
        ).lower()
        if query_value and query_value not in haystack:
            continue
        visible.append(client)

    return WorkstationClientListResponse(
        clients=[build_client_summary(client) for client in visible],
    )


@workstation_router.post("/clients", response_model=WorkstationClientDetailResponse)
async def create_workstation_client(command: CreateWorkstationClientCommand) -> WorkstationClientDetailResponse:
    """Create or return a Workstation client from one source lead."""
    return await create_workstation_client_from_lead(
        command.lead_id,
        work_type=command.work_type,
        status=command.status,
        automation_status=command.automation_status,
        offer_price_usd=command.offer_price_usd,
        offer_currency=command.offer_currency,
    )


@workstation_router.post("/clients/from-lead/{lead_id}", response_model=WorkstationClientDetailResponse)
async def create_workstation_client_from_lead(
    lead_id: str,
    work_type: str = WorkstationClientWorkType.PAGINA_ADS.value,
    status: str = WorkstationClientStatus.PAID.value,
    automation_status: str = WorkstationAutomationStatus.NEEDS_HUMAN.value,
    offer_price_usd: int | None = None,
    offer_currency: str = "USD",
) -> WorkstationClientDetailResponse:
    """Convert a CRM lead into a paid Workstation client."""
    lead = get_required_lead(lead_id)
    is_solo_page = (work_type or "").strip().lower() == WorkstationClientWorkType.SOLO_PAGINA.value
    resolved_offer_price_usd = (
        offer_price_usd
        if offer_price_usd is not None
        else (
            resolve_solo_page_offer_price_usd(lead.id)
            if is_solo_page
            else None
        )
    )
    existing = WorkstationClient.get_by_lead_id(lead.id)
    client = existing or WorkstationClient.create_for_lead(
        lead,
        work_type=work_type,
        status=status,
        automation_status=automation_status,
        offer_price_usd=resolved_offer_price_usd,
        offer_currency=offer_currency,
    )
    if resolved_offer_price_usd is not None:
        client = WorkstationClient.update_offer(
            client.id,
            offer_price_usd=resolved_offer_price_usd,
            offer_currency=offer_currency,
            only_if_missing=True,
        ) or client
    if existing is None:
        ContadoresLead.update_flow_state(
            lead.id,
            booked_at=lead.booked_at or now_utc(),
            automation_paused=True,
            automation_paused_reason=(
                "manual_workstation_solo_page_conversion"
                if is_solo_page
                else "manual_workstation_conversion"
            ),
        )
    fresh_client = WorkstationClient.get_by_id(client.id) or client
    mirror_workstation_message_media(fresh_client, ContadoresMessage.list_by_lead(lead.id))
    fresh_client = WorkstationClient.get_by_id(client.id) or fresh_client
    return build_client_detail(fresh_client)


@workstation_router.get("/clients/{client_id}", response_model=WorkstationClientDetailResponse)
async def get_workstation_client(client_id: str) -> WorkstationClientDetailResponse:
    """Return one converted client profile."""
    return build_client_detail(get_required_client(client_id))


@workstation_router.post("/clients/{client_id}/close", response_model=WorkstationClientDetailResponse)
async def close_workstation_client(client_id: str) -> WorkstationClientDetailResponse:
    """Close a Workstation client and stop CRM/Workstation automation."""
    client = get_required_client(client_id)
    lead = get_required_lead(client.lead_id)
    now = now_utc()

    solo_page_stop_requested_client_ids.add(client.id)
    turn = active_solo_page_codex_turns.get(client.id)
    if turn is not None:
        await interrupt_turn(turn)
    clear_solo_page_live_work(client.id)
    manual_solo_page_work_client_ids.discard(client.id)

    updated_client = WorkstationClient.update_automation_state(
        client.id,
        status=WorkstationClientStatus.CLOSED,
        automation_status=WorkstationAutomationStatus.NEEDS_HUMAN,
        last_automation_handled_at=now,
    ) or client
    ContadoresLead.update_flow_state(
        lead.id,
        stage="closed",
        closed_at=now,
        stage_before_closed=lead.stage,
        automation_paused=True,
        automation_paused_reason="manual_workstation_close",
        last_classification_label="manual_workstation_close",
        last_classification_reason="Closed from Workstation by operator.",
        manual_reply_handled_at=now,
    )
    ContadoresLead.clear_conversation_processing(lead_id=lead.id)
    append_workstation_progress(updated_client, "Lead closed from Workstation. Automation stopped.")
    return build_client_detail(WorkstationClient.get_by_id(client.id) or updated_client)


@workstation_router.post(
    "/clients/{client_id}/solo-page/work",
    response_model=WorkstationClientDetailResponse,
    status_code=202,
)
async def start_workstation_solo_page_work(
    client_id: str,
    command: StartSoloPageWorkCommand,
) -> WorkstationClientDetailResponse:
    """Start an operator-triggered Codex solo-page run."""
    client = get_required_client(client_id)
    if client.status == WorkstationClientStatus.CLOSED:
        raise HTTPException(status_code=409, detail="This Workstation lead is closed.")
    if client.work_type != WorkstationClientWorkType.SOLO_PAGINA:
        raise HTTPException(status_code=400, detail="This action is only available for solo-page clients.")

    operator_prompt = command.prompt.strip()
    if not operator_prompt:
        raise HTTPException(status_code=422, detail="Write a prompt before starting Codex.")
    live_status = observed_solo_page_live_status(client.id)
    if client.id in manual_solo_page_work_client_ids and live_status["is_live_working"]:
        raise HTTPException(status_code=409, detail="Workstation Codex is already working for this client.")
    if live_status["is_live_working"]:
        raise HTTPException(status_code=409, detail="Workstation Codex is already working for this client.")
    manual_solo_page_work_client_ids.discard(client.id)
    if client.automation_status in {
        WorkstationAutomationStatus.DRAFTING,
        WorkstationAutomationStatus.REVISION_REQUESTED,
    }:
        append_workstation_progress(
            client,
            "Operator restarted Codex because no live backend task or Codex turn was registered.",
        )

    revision = latest_landing_page_version_dir(client) is not None
    WorkstationClient.update_automation_state(
        client.id,
        automation_status=(
            WorkstationAutomationStatus.REVISION_REQUESTED
            if revision
            else WorkstationAutomationStatus.DRAFTING
        ),
        last_automation_handled_at=now_utc(),
    )
    append_workstation_progress(client, "Manual Codex run queued from Workstation Actions.")
    manual_solo_page_work_client_ids.add(client.id)
    try:
        task = asyncio.create_task(run_manual_solo_page_work(client.id, operator_prompt))
        register_solo_page_task(client.id, task)
    except Exception:
        manual_solo_page_work_client_ids.discard(client.id)
        clear_solo_page_live_work(client.id)
        raise
    return build_client_detail(WorkstationClient.get_by_id(client.id) or client)


@workstation_router.post(
    "/clients/{client_id}/solo-page/stop",
    response_model=WorkstationClientDetailResponse,
)
async def stop_workstation_solo_page_work(client_id: str) -> WorkstationClientDetailResponse:
    """Interrupt an active Workstation Codex solo-page run for one client."""
    client = get_required_client(client_id)
    if client.work_type != WorkstationClientWorkType.SOLO_PAGINA:
        raise HTTPException(status_code=400, detail="This action is only available for solo-page clients.")
    if client.automation_status not in {
        WorkstationAutomationStatus.DRAFTING,
        WorkstationAutomationStatus.REVISION_REQUESTED,
    } and client.id not in active_solo_page_codex_turns:
        raise HTTPException(status_code=409, detail="Codex is not working for this client.")

    solo_page_stop_requested_client_ids.add(client.id)
    turn = active_solo_page_codex_turns.get(client.id)
    if turn is not None:
        await interrupt_turn(turn)
    mark_workstation_stopped_by_operator(client, clear_stop_request=False)
    return build_client_detail(WorkstationClient.get_by_id(client.id) or client)


@workstation_router.post(
    "/clients/{client_id}/solo-page/steer",
    response_model=WorkstationClientDetailResponse,
)
async def steer_workstation_solo_page_work(
    client_id: str,
    command: SteerSoloPageWorkCommand,
) -> WorkstationClientDetailResponse:
    """Send additional operator guidance to a running Codex turn."""
    client = get_required_client(client_id)
    if client.work_type != WorkstationClientWorkType.SOLO_PAGINA:
        raise HTTPException(status_code=400, detail="This action is only available for solo-page clients.")
    turn = active_solo_page_codex_turns.get(client.id)
    if turn is None or client.automation_status not in {
        WorkstationAutomationStatus.DRAFTING,
        WorkstationAutomationStatus.REVISION_REQUESTED,
    }:
        raise HTTPException(status_code=409, detail="Codex is not working for this client.")

    message = command.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Write a steer message first.")
    if not hasattr(turn, "steer"):
        raise HTTPException(status_code=409, detail="This Codex run cannot receive steer messages.")
    await steer_turn(turn, message)
    append_workstation_progress(client, f"Operator steered Codex: {message[:240]}")
    return build_client_detail(WorkstationClient.get_by_id(client.id) or client)


@workstation_router.post(
    "/clients/{client_id}/professional-photo/jobs",
    response_model=WorkstationProfessionalPhotoJobResponse,
    status_code=202,
)
async def start_workstation_professional_photo_job(
    client_id: str,
    command: CreateProfessionalPhotoCommand,
) -> WorkstationProfessionalPhotoJobResponse:
    """Start async professional portrait generation from selected client media."""
    client = get_required_client(client_id)
    assets = get_client_image_assets(client, command.media_asset_ids)

    active_job = get_active_professional_photo_job(client.id)
    if active_job is not None:
        return build_professional_photo_job_response(active_job)

    job = ProfessionalPhotoJobRecord(
        job_id=uuid.uuid4().hex,
        client_id=client.id,
        status="queued",
        created_at=current_job_timestamp(),
    )
    professional_photo_jobs[job.job_id] = job
    asyncio.create_task(
        run_create_professional_photo_job(
            job_id=job.job_id,
            client=client,
            assets=assets,
            context=command.context,
        )
    )
    return build_professional_photo_job_response(job)


@workstation_router.get(
    "/clients/{client_id}/professional-photo/jobs/{job_id}",
    response_model=WorkstationProfessionalPhotoJobResponse,
)
async def get_workstation_professional_photo_job(
    client_id: str,
    job_id: str,
) -> WorkstationProfessionalPhotoJobResponse:
    """Return one async professional-photo generation job status."""
    return build_professional_photo_job_response(get_professional_photo_job(client_id, job_id))


@workstation_router.post(
    "/clients/{client_id}/professional-photo",
    response_model=WorkstationProfessionalPhotoVersion,
)
async def create_workstation_professional_photo(
    client_id: str,
    command: CreateProfessionalPhotoCommand,
) -> WorkstationProfessionalPhotoVersion:
    """Generate a professional portrait from selected client media images."""
    client = get_required_client(client_id)
    assets = get_client_image_assets(client, command.media_asset_ids)
    version = await generate_professional_photo(
        client=client,
        assets=assets,
        context=command.context,
    )
    return version


@workstation_router.post(
    "/clients/{client_id}/professional-photo/edit",
    response_model=WorkstationProfessionalPhotoVersion,
)
async def edit_workstation_professional_photo(
    client_id: str,
    command: EditProfessionalPhotoCommand,
) -> WorkstationProfessionalPhotoVersion:
    """Generate a new professional portrait version from a user edit prompt."""
    client = get_required_client(client_id)
    assets = get_client_image_assets(client, command.media_asset_ids) if command.media_asset_ids else []
    version = await edit_professional_photo(
        client=client,
        base_version=command.base_version,
        assets=assets,
        user_prompt=command.prompt,
    )
    return version


@workstation_router.put("/clients/{client_id}/notes", response_model=WorkstationClientDetailResponse)
async def update_workstation_notes(
    client_id: str,
    command: UpdateWorkstationNotesCommand,
) -> WorkstationClientDetailResponse:
    """Save meeting notes for one converted client."""
    updated = WorkstationClient.update_notes(client_id, notes=command.notes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Workstation client not found")
    return build_client_detail(updated)


@workstation_router.post("/clients/{client_id}/media", response_model=WorkstationMediaAssetResponse)
async def upload_workstation_media(
    client_id: str,
    title: str = Form(default=""),
    file: UploadFile = File(...),
) -> WorkstationMediaAssetResponse:
    """Attach one media file to a converted client folder."""
    client = get_required_client(client_id)
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    asset_id = str(uuid.uuid4())
    safe_name = safe_upload_filename(file.filename)
    stored_filename = f"{asset_id[:8]}-{safe_name}"
    media_path = client_folder(client) / "media" / stored_filename
    media_path.write_bytes(contents)
    asset = WorkstationMediaAsset.create(
        client_id=client.id,
        asset_id=asset_id,
        title=(title or "").strip() or Path(file.filename or "file").name,
        original_filename=Path(file.filename or "file").name,
        stored_filename=stored_filename,
        stored_path=relative_data_path(media_path),
        content_type=file.content_type or mimetypes.guess_type(safe_name)[0],
        size_bytes=len(contents),
    )
    write_client_files(WorkstationClient.get_by_id(client.id) or client)
    return build_media_response(asset)


@workstation_router.put("/clients/{client_id}/media/{asset_id}", response_model=WorkstationMediaAssetResponse)
async def update_workstation_media(
    client_id: str,
    asset_id: str,
    command: UpdateWorkstationMediaCommand,
) -> WorkstationMediaAssetResponse:
    """Update one media asset's operator-facing name."""
    client = get_required_client(client_id)
    asset = WorkstationMediaAsset.get_by_id(asset_id)
    if asset is None or asset.client_id != client.id:
        raise HTTPException(status_code=404, detail="Media asset not found")

    filename = safe_upload_filename(
        command.original_filename
        or asset.original_filename
        or asset.stored_filename
        or "file"
    )
    title = (command.title or "").strip() or filename
    updated = WorkstationMediaAsset.update_metadata(asset.id, title=title, original_filename=filename)
    if updated is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    write_client_files(WorkstationClient.get_by_id(client.id) or client)
    return build_media_response(updated)


@workstation_router.delete("/clients/{client_id}/media/{asset_id}", response_model=WorkstationClientDetailResponse)
async def delete_workstation_media(client_id: str, asset_id: str) -> WorkstationClientDetailResponse:
    """Delete one media asset from a converted client."""
    client = get_required_client(client_id)
    asset = WorkstationMediaAsset.get_by_id(asset_id)
    if asset is None or asset.client_id != client.id:
        raise HTTPException(status_code=404, detail="Media asset not found")
    deleted = WorkstationMediaAsset.delete(asset.id)
    if deleted and deleted.stored_path:
        path = resolve_media_path(deleted.stored_path)
        if path and path.exists():
            path.unlink()
    return build_client_detail(WorkstationClient.get_by_id(client.id) or client)


@workstation_router.get("/media/{asset_id}/file")
async def get_workstation_media_file(asset_id: str) -> FileResponse:
    """Serve one Workstation media file."""
    asset = WorkstationMediaAsset.get_by_id(asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Media asset not found")
    path = resolve_media_path(asset.stored_path)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(
        path,
        media_type=asset.content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        filename=asset.original_filename or path.name,
        content_disposition_type="inline",
    )


@workstation_router.get("/clients/{client_id}/professional-photo/{version}/file")
async def get_workstation_professional_photo_file(client_id: str, version: str) -> FileResponse:
    """Serve one generated professional photo version."""
    client = get_required_client(client_id)
    safe_version = Path(version).name
    path = professional_photo_root(client) / safe_version / "professional-photo.jpg"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Professional photo not found")
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=f"{client.folder_name}-{safe_version}-professional-photo.jpg",
        content_disposition_type="inline",
    )


@workstation_router.get("/clients/{client_id}/zip")
async def download_workstation_zip(client_id: str) -> FileResponse:
    """Download a complete client folder zip."""
    client = get_required_client(client_id)
    zip_path = build_client_zip(client)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_path.name,
        content_disposition_type="attachment",
    )


@workstation_router.get("/clients/{client_id}/copy-all", response_model=WorkstationCopyAllResponse)
async def get_workstation_copy_all(client_id: str) -> WorkstationCopyAllResponse:
    """Return all client context as one clipboard-friendly text block."""
    client = get_required_client(client_id)
    lead = get_required_lead(client.lead_id)
    messages = ContadoresMessage.list_by_lead(client.lead_id)
    media = WorkstationMediaAsset.list_by_client(client.id)
    return WorkstationCopyAllResponse(
        text=build_copy_all_text(client=client, lead=lead, messages=messages, media=media),
    )


def resolve_media_path(stored_path: str | None) -> Path | None:
    """Resolve a stored data/... path inside the Workstation data root."""
    clean_path = (stored_path or "").strip()
    if not clean_path:
        return None
    candidate = Path(clean_path)
    data_dir = database_module.DATA_DIR.expanduser().resolve()
    if candidate.is_absolute():
        resolved = candidate.expanduser().resolve()
    else:
        parts = candidate.parts
        relative_parts = parts[1:] if parts and parts[0] == "data" else parts
        resolved = data_dir.joinpath(*relative_parts).resolve()
    try:
        resolved.relative_to(workstation_root().resolve())
    except ValueError:
        return None
    return resolved
