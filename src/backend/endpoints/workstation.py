"""Workstation endpoints for paid client profiles."""

from __future__ import annotations

import json
import mimetypes
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

import backend.database as database_module
from backend.codex_utils import CodexSkill, run_codex_with_context
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

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFESSIONAL_PHOTO_SKILL = Path(".codex/skills/client-professional-photo/SKILL.md")
PROFESSIONAL_PHOTO_EDIT_SKILL = Path(".codex/skills/client-professional-photo-edit/SKILL.md")


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
    professional_photos: list["WorkstationProfessionalPhotoVersion"] = Field(default_factory=list)


class CreateWorkstationClientCommand(BaseModel):
    """Create converted client from a CRM lead."""

    lead_id: str = Field(min_length=1)


class UpdateWorkstationNotesCommand(BaseModel):
    """Meeting notes payload."""

    notes: str = ""


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


class CreateProfessionalPhotoCommand(BaseModel):
    """Generate professional photo from selected media assets."""

    media_asset_ids: list[str] = Field(default_factory=list, min_length=1)
    context: str = ""


class EditProfessionalPhotoCommand(BaseModel):
    """Create a new professional photo version from an existing version."""

    base_version: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    media_asset_ids: list[str] = Field(default_factory=list)


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
    return build_professional_photo_response(client, version_dir)


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
    return build_professional_photo_response(client, version_dir)


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
    ContadoresEvent.add(
        lead_id=client.lead_id,
        event_type="workstation_professional_photo_created",
        actor="operator",
        summary="Generated a Workstation professional photo.",
        payload={"client_id": client.id, "version": version.version, "image_path": version.image_path},
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
    ContadoresEvent.add(
        lead_id=client.lead_id,
        event_type="workstation_professional_photo_edited",
        actor="operator",
        summary="Generated an edited Workstation professional photo.",
        payload={
            "client_id": client.id,
            "base_version": command.base_version,
            "version": version.version,
            "image_path": version.image_path,
        },
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
