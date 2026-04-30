"""Public image-generation endpoint powered by Codex."""

from __future__ import annotations

import json
import mimetypes
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

import backend.database as database_module
from backend.codex_utils import run_codex_with_context

public_image_generation_router = APIRouter(
    prefix="/api/public/image-generation",
    tags=["public-image-generation"],
)

MAX_PROMPT_LENGTH = 10_000
MAX_IMAGE_COUNT = 8
MAX_IMAGE_BYTES = 12 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024
OUTPUT_FILENAME = "generated-image.png"


def generation_root() -> Path:
    """Return the persistent folder for public generation jobs."""
    root = database_module.DATA_DIR / "public-image-generations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def safe_upload_filename(index: int, filename: str | None) -> str:
    """Return a readable upload name that cannot escape the job folder."""
    raw_name = Path(filename or f"image-{index}").name
    stem = "".join(
        character.lower() if character.isalnum() else "-"
        for character in Path(raw_name).stem
    ).strip("-")
    suffix = "".join(
        character
        for character in Path(raw_name).suffix.lower()
        if character.isalnum() or character == "."
    )[:12]
    return f"{index:02d}-{stem or 'image'}{suffix or '.png'}"


async def save_image_uploads(job_dir: Path, images: list[UploadFile]) -> list[Path]:
    """Persist uploaded image files and return their paths."""
    if len(images) > MAX_IMAGE_COUNT:
        raise HTTPException(status_code=400, detail=f"At most {MAX_IMAGE_COUNT} images are allowed.")

    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []

    for index, upload in enumerate(images, start=1):
        content_type = (upload.content_type or "").lower()
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail=f"Upload is not an image: {upload.filename or index}")

        path = input_dir / safe_upload_filename(index, upload.filename)
        total_bytes = 0
        with path.open("wb") as output_file:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > MAX_IMAGE_BYTES:
                    path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=400,
                        detail=f"Image is larger than {MAX_IMAGE_BYTES // 1024 // 1024} MB: {upload.filename or index}",
                    )
                output_file.write(chunk)
        saved_paths.append(path)

    return saved_paths


def run_public_image_generation_sync(
    *,
    job_dir: Path,
    user_prompt: str,
    input_paths: list[Path],
) -> Path:
    """Ask Codex to generate one image and save it at a known path."""
    output_path = job_dir / OUTPUT_FILENAME
    input_list = "\n".join(str(path) for path in input_paths) or "(none)"
    codex_prompt = f"""
Generate exactly one final raster image from the user's prompt and optional image references.

User prompt:
{user_prompt.strip()}

Input image paths:
{input_list}

Required output path:
{output_path}

Rules:
- Use the provided input images as visual references when present.
- Save the final image as a PNG exactly at the required output path.
- Do not create placeholder files, SVG files, HTML files, screenshots, or text-only outputs.
- Do not inspect unrelated repository files or modify anything outside this job folder.
- After saving the image, respond only with a short confirmation and the output path.
""".strip()

    try:
        result = run_codex_with_context(
            codex_prompt,
            local_images=input_paths,
            cwd=job_dir,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise HTTPException(
            status_code=502,
            detail="Codex did not create the expected output image.",
        )

    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "prompt": user_prompt,
        "input_image_paths": [str(path) for path in input_paths],
        "output_image_path": str(output_path),
        "codex_response": result.final_response,
        "items_count": result.items_count,
        "model": result.model,
        "effort": result.effort,
    }
    (job_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return output_path


@public_image_generation_router.post("")
async def generate_public_image(
    prompt: str = Form(..., min_length=1, max_length=MAX_PROMPT_LENGTH),
    images: list[UploadFile] | None = File(None),
):
    """Generate one image from a public multipart request and return the image."""
    image_uploads = images or []
    job_dir = generation_root() / uuid.uuid4().hex
    job_dir.mkdir(parents=True, exist_ok=False)

    try:
        input_paths = await save_image_uploads(job_dir, image_uploads)
        output_path = await run_in_threadpool(
            run_public_image_generation_sync,
            job_dir=job_dir,
            user_prompt=prompt,
            input_paths=input_paths,
        )
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except Exception as error:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(error)) from error

    media_type = mimetypes.guess_type(output_path.name)[0] or "image/png"
    return FileResponse(
        output_path,
        media_type=media_type,
        filename=OUTPUT_FILENAME,
    )
