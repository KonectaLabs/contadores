"""Workstation endpoints for paid client profiles."""

from __future__ import annotations

import asyncio
import json
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

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

import backend.database as database_module
from backend.codex_utils import CodexSkill, run_codex_with_context
from backend.config import (
    WORKSTATION_HANDOFF_TEMPLATE_NAME,
    WORKSTATION_HUMAN_HANDOFF_TEXT,
    WORKSTATION_PING_1_TEXT,
    WORKSTATION_PING_2_TEXT,
    WORKSTATION_PING_TEMPLATE_1_NAME,
    WORKSTATION_PING_TEMPLATE_2_NAME,
    WORKSTATION_TEMPLATE_LANGUAGE,
)
from backend.database import (
    ContadoresLead,
    ContadoresMessage,
    ContadoresRuntimeAlert,
    WorkstationAutomationStatus,
    WorkstationClient,
    WorkstationMediaAsset,
    WorkstationClientStatus,
    WorkstationClientWorkType,
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

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFESSIONAL_PHOTO_SKILL = Path(".codex/skills/client-professional-photo/SKILL.md")
PROFESSIONAL_PHOTO_EDIT_SKILL = Path(".codex/skills/client-professional-photo-edit/SKILL.md")
SOLO_PAGE_SKILL = Path(".codex/skills/workstation-solo-page/SKILL.md")
ACTIVE_PROFESSIONAL_PHOTO_JOB_STATUSES = {"queued", "running"}
WORKSTATION_INTAKE_SEQUENCE_STEP = "workstation_intake"
WORKSTATION_PREVIEW_SEQUENCE_STEP = "workstation_preview_video"
WORKSTATION_REVISION_SEQUENCE_STEP = "workstation_revision_video"
WORKSTATION_PING_1_SEQUENCE_STEP = "workstation_ping_1"
WORKSTATION_PING_2_SEQUENCE_STEP = "workstation_ping_2"
WORKSTATION_HANDOFF_SEQUENCE_STEP = "workstation_handoff"
WORKSTATION_BACKOFF_SECONDS = 30
WORKSTATION_PING_1_DELAY_SECONDS = 24 * 60 * 60
WORKSTATION_PING_2_DELAY_SECONDS = 48 * 60 * 60
WORKSTATION_HANDOFF_DELAY_SECONDS = 72 * 60 * 60
SOLO_PAGE_CONTEXT_MIN_CHARS = 35
WORKSTATION_INTAKE_TEXT = (
    "Perfecto, entonces arrancamos con la pagina.\n\n"
    "Mandeme por aca lo basico que quiere que aparezca: nombre del estudio, ciudad/pais, "
    "servicios principales y WhatsApp de contacto.\n\n"
    "Si tiene una foto suya, pagina actual, logo o documento, mandemelo tambien. "
    "Con eso le preparo un primer boceto en video."
)


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
            "# Notas",
            client.notes or "(sin notas)",
            "# Media",
            "\n".join(media_lines) if media_lines else "(sin media)",
            "# Conversacion",
            build_conversation_text(lead, messages),
        ]
    ).strip() + "\n"


def write_client_files(client: WorkstationClient) -> None:
    """Refresh the filesystem snapshot for one Workstation client."""
    folder = client_folder(client)
    lead = ContadoresLead.get_by_id(client.lead_id)
    messages = ContadoresMessage.list_by_lead(client.lead_id) if lead else []
    media = WorkstationMediaAsset.list_by_client(client.id)

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


class WorkstationClientDetailResponse(BaseModel):
    """Full Workstation client profile payload."""

    client: WorkstationClientSummary
    notes: str
    messages: list[ContadoresMessageResponse] = Field(default_factory=list)
    media: list[WorkstationMediaAssetResponse] = Field(default_factory=list)
    professional_photos: list["WorkstationProfessionalPhotoVersion"] = Field(default_factory=list)


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


WorkstationClientDetailResponse.model_rebuild()


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
    summary = WorkstationAutomationTickResponse()
    now = now_utc()
    for client in WorkstationClient.list_active_automation(
        work_type=WorkstationClientWorkType.SOLO_PAGINA,
        limit=100,
    ):
        metrics = await advance_solo_page_client(client, now=now)
        summary.intake_messages_sent += metrics["intake_messages_sent"]
        summary.drafts_generated += metrics["drafts_generated"]
        summary.revision_videos_sent += metrics["revision_videos_sent"]
        summary.approvals += metrics["approvals"]
        summary.pings_sent += metrics["pings_sent"]
        summary.human_handoffs += metrics["human_handoffs"]
        summary.failures += metrics["failures"]
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


def generate_professional_photo_sync(
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
        result = run_codex_with_context(
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
        version = await run_in_threadpool(
            generate_professional_photo_sync,
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


def edit_professional_photo_sync(
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
        result = run_codex_with_context(
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
    anchor = timestamp.astimezone(timezone.utc) if timestamp and timestamp.tzinfo else timestamp
    replies: list[ContadoresMessage] = []
    for message in messages:
        if message.from_me:
            continue
        created_at = message.created_at
        if created_at and created_at.tzinfo:
            created_at = created_at.astimezone(timezone.utc)
        if anchor is not None and created_at is not None and created_at <= anchor:
            continue
        replies.append(message)
    return replies


def latest_inbound_is_quiet(messages: list[ContadoresMessage], *, now: datetime) -> bool:
    """Return True when the latest inbound has passed the Workstation backoff."""
    if not messages:
        return False
    latest_at = messages[-1].created_at
    if latest_at is None:
        return False
    if latest_at.tzinfo is None:
        latest_at = latest_at.replace(tzinfo=timezone.utc)
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


def ensure_professional_photo_if_possible(client: WorkstationClient) -> None:
    """Generate one professional photo when the client already provided an image."""
    if list_professional_photo_versions(client):
        return
    image_assets = first_workstation_image_assets(client)
    if not image_assets:
        return
    try:
        generate_professional_photo_sync(
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
    return f"""
Use the workstation-solo-page skill to create a static website draft for this client.

Client folder:
{client_folder(client)}

Required output folder:
{version_dir}

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

Requirements:
- Create only static files: index.html, styles.css, script.js, assets/.
- Use easy-to-read HTML/CSS/JS. Avoid build tools.
- If this is a revision, apply the requested changes to the previous version.
- If client information is incomplete, still create a credible first draft with honest placeholders.
- Save all files inside the required output folder only.
- Do not modify source templates, repo files, or other client folders.
- Respond with a short confirmation and the created paths.

Revision mode: {"yes" if revision else "no"}
""".strip()


def generate_solo_page_version_sync(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    replies: list[ContadoresMessage],
    revision: bool,
) -> Path:
    """Run Codex to create one landing-page version and render its preview video."""
    client_workdir = client_folder(client)
    version_dir = next_landing_page_version_dir(client)
    prompt = build_solo_page_codex_prompt(
        client=client,
        lead=lead,
        version_dir=version_dir,
        replies=replies,
        revision=revision,
    )
    try:
        result = run_codex_with_context(
            prompt,
            skills=[
                CodexSkill(
                    name="workstation-solo-page",
                    path=str((REPO_ROOT / SOLO_PAGE_SKILL).resolve()),
                )
            ],
            cwd=REPO_ROOT,
        )
        index_path = version_dir / "index.html"
        if not index_path.exists():
            raise RuntimeError(f"Codex did not create {index_path}")
        if not (version_dir / "styles.css").exists():
            raise RuntimeError(f"Codex did not create {version_dir / 'styles.css'}")
        if not (version_dir / "script.js").exists():
            (version_dir / "script.js").write_text("", encoding="utf-8")
        preview_path = version_dir / "preview.mp4"
        render_landing_page_video_sync(index_path=index_path, output_path=preview_path)
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "operation": "revision" if revision else "draft",
            "client_id": client.id,
            "lead_id": lead.id,
            "codex_response": result.final_response,
            "source_messages": [message.id for message in replies],
            "preview_path": relative_data_path(preview_path),
        }
        (version_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        register_generated_workstation_media(
            client=client,
            source_path=preview_path,
            title=f"Preview pagina {version_dir.name}",
            stored_filename=f"generated-page-preview-{version_dir.name}.mp4",
            content_type="video/mp4",
        )
        return version_dir
    except Exception:
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
    ContadoresRuntimeAlert.add(
        lead=lead,
        funnel_label=config.label,
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


def queue_workstation_preview(
    *,
    client: WorkstationClient,
    lead: ContadoresLead,
    version_dir: Path,
    sequence_step: str,
) -> ContadoresMessage:
    """Queue one generated preview MP4 for WhatsApp delivery."""
    preview_path = version_dir / "preview.mp4"
    return enqueue_lead_outbound(
        lead=lead,
        text="Le mando un video con el boceto de su pagina. Digame que le gustaria cambiar o si asi esta bien.",
        sequence_step=sequence_step,
        media_type="video",
        media_path=relative_data_path(preview_path),
        media_filename=f"{client.folder_name}-{version_dir.name}.mp4",
    )


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

    elapsed = now - client.last_preview_sent_at
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
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.DRAFTING,
            last_automation_handled_at=now,
        )
        try:
            ensure_professional_photo_if_possible(fresh_client)
            version_dir = await run_in_threadpool(
                generate_solo_page_version_sync,
                client=WorkstationClient.get_by_id(fresh_client.id) or fresh_client,
                lead=lead,
                replies=replies,
                revision=False,
            )
            row = queue_workstation_preview(
                client=fresh_client,
                lead=lead,
                version_dir=version_dir,
                sequence_step=WORKSTATION_PREVIEW_SEQUENCE_STEP,
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
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=now,
            last_preview_sent_at=row.created_at,
        )
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
                handoff_due = (
                    fresh_client.last_preview_sent_at is not None
                    and now - fresh_client.last_preview_sent_at >= timedelta(seconds=WORKSTATION_HANDOFF_DELAY_SECONDS)
                )
                metrics["human_handoffs"] = 1 if metrics["pings_sent"] and handoff_due else 0
            except Exception as error:
                mark_workstation_failed(
                    client=fresh_client,
                    lead=lead,
                    error=f"{error.__class__.__name__}: {error}",
                )
                metrics["failures"] = 1
            return metrics
        if not latest_inbound_is_quiet(replies, now=now):
            return metrics
        reply_text = "\n".join(message.text for message in replies if message.text.strip())
        if text_shows_workstation_approval(reply_text):
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

        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.REVISION_REQUESTED,
            last_automation_handled_at=now,
        )
        try:
            version_dir = await run_in_threadpool(
                generate_solo_page_version_sync,
                client=fresh_client,
                lead=lead,
                replies=replies,
                revision=True,
            )
            row = queue_workstation_preview(
                client=fresh_client,
                lead=lead,
                version_dir=version_dir,
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
        WorkstationClient.update_automation_state(
            fresh_client.id,
            automation_status=WorkstationAutomationStatus.AWAITING_REVIEW,
            last_automation_handled_at=now,
            last_preview_sent_at=row.created_at,
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


def build_client_detail(client: WorkstationClient) -> WorkstationClientDetailResponse:
    """Build one complete Workstation client response."""
    lead = get_required_lead(client.lead_id)
    messages = ContadoresMessage.list_by_lead(client.lead_id)
    media = WorkstationMediaAsset.list_by_client(client.id)
    write_client_files(client)
    return WorkstationClientDetailResponse(
        client=build_client_summary(client),
        notes=client.notes,
        messages=[build_message_response(message) for message in messages],
        media=[build_media_response(asset) for asset in media],
        professional_photos=list_professional_photo_versions(client),
    )


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
    return build_client_detail(fresh_client)


@workstation_router.get("/clients/{client_id}", response_model=WorkstationClientDetailResponse)
async def get_workstation_client(client_id: str) -> WorkstationClientDetailResponse:
    """Return one converted client profile."""
    return build_client_detail(get_required_client(client_id))


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
    version = await run_in_threadpool(
        generate_professional_photo_sync,
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
    version = await run_in_threadpool(
        edit_professional_photo_sync,
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
