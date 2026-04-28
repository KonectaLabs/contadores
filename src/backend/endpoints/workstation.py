"""Workstation endpoints for paid client profiles."""

from __future__ import annotations

import json
import mimetypes
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import backend.database as database_module
from backend.database import (
    ContadoresEvent,
    ContadoresLead,
    ContadoresMessage,
    WorkstationClient,
    WorkstationMediaAsset,
    normalize_workstation_slug,
)
from backend.endpoints.contadores import (
    ContadoresLeadSummary,
    ContadoresMessageResponse,
    build_lead_summary,
    build_message_response,
    format_timestamp_seconds,
    get_effective_funnel_config,
    group_strategy_assignments_by_lead,
    now_utc,
)

workstation_router = APIRouter(prefix="/api/workstation", tags=["workstation"])


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
        lines.append(f"[{timestamp}] {author}{media}: {message.text}")
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
            "display_name": client.display_name,
            "folder_name": client.folder_name,
            "folder_path": relative_data_path(folder),
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
    display_name: str
    folder_name: str
    folder_path: str
    media_count: int = 0
    lead: ContadoresLeadSummary | None = None
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


class CreateWorkstationClientCommand(BaseModel):
    """Create converted client from a CRM lead."""

    lead_id: str = Field(min_length=1)


class UpdateWorkstationNotesCommand(BaseModel):
    """Meeting notes payload."""

    notes: str = ""


class WorkstationCopyAllResponse(BaseModel):
    """Clipboard context payload."""

    text: str


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


def build_client_summary(client: WorkstationClient) -> WorkstationClientSummary:
    """Serialize one Workstation client for list/detail views."""
    lead = ContadoresLead.get_by_id(client.lead_id)
    folder = client_folder(client)
    media = WorkstationMediaAsset.list_by_client(client.id)
    return WorkstationClientSummary(
        id=client.id,
        lead_id=client.lead_id,
        funnel_id=client.funnel_id,
        display_name=client.display_name,
        folder_name=client.folder_name,
        folder_path=relative_data_path(folder),
        media_count=len(media),
        lead=lead_summary_for_workstation(lead) if lead else None,
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
                client.display_name,
                client.funnel_id,
                client.folder_name,
                lead.full_name if lead else "",
                lead.phone if lead else "",
                lead.email if lead else "",
                lead.external_lead_id if lead else "",
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
    return await create_workstation_client_from_lead(command.lead_id)


@workstation_router.post("/clients/from-lead/{lead_id}", response_model=WorkstationClientDetailResponse)
async def create_workstation_client_from_lead(lead_id: str) -> WorkstationClientDetailResponse:
    """Convert a CRM lead into a paid Workstation client."""
    lead = get_required_lead(lead_id)
    existing = WorkstationClient.get_by_lead_id(lead.id)
    client = existing or WorkstationClient.create_for_lead(lead)
    if existing is None:
        ContadoresLead.update_flow_state(
            lead.id,
            booked_at=lead.booked_at or now_utc(),
            automation_paused=True,
            automation_paused_reason="manual_workstation_conversion",
        )
        ContadoresEvent.add(
            lead_id=lead.id,
            event_type="workstation_client_created",
            actor="operator",
            summary="Lead converted into a paid Workstation client.",
            payload={"client_id": client.id, "folder_name": client.folder_name},
        )
    fresh_client = WorkstationClient.get_by_id(client.id) or client
    return build_client_detail(fresh_client)


@workstation_router.get("/clients/{client_id}", response_model=WorkstationClientDetailResponse)
async def get_workstation_client(client_id: str) -> WorkstationClientDetailResponse:
    """Return one converted client profile."""
    return build_client_detail(get_required_client(client_id))


@workstation_router.put("/clients/{client_id}/notes", response_model=WorkstationClientDetailResponse)
async def update_workstation_notes(
    client_id: str,
    command: UpdateWorkstationNotesCommand,
) -> WorkstationClientDetailResponse:
    """Save meeting notes for one converted client."""
    updated = WorkstationClient.update_notes(client_id, notes=command.notes)
    if updated is None:
        raise HTTPException(status_code=404, detail="Workstation client not found")
    ContadoresEvent.add(
        lead_id=updated.lead_id,
        event_type="workstation_notes_updated",
        actor="operator",
        summary="Operator updated Workstation notes.",
        payload={"client_id": updated.id},
    )
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
