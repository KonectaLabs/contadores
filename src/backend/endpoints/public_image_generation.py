"""Public image-generation endpoint powered by Codex."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import uuid
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import base64
import binascii
import httpx
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
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
OPENAI_IMAGE_FALLBACK_MODEL = os.getenv("OPENAI_IMAGE_FALLBACK_MODEL", "gpt-image-1.5")
OPENAI_IMAGE_FALLBACK_SIZE = os.getenv("OPENAI_IMAGE_FALLBACK_SIZE", "1024x1024")
OPENAI_IMAGE_FALLBACK_QUALITY = os.getenv("OPENAI_IMAGE_FALLBACK_QUALITY", "medium")
OPENAI_IMAGE_FALLBACK_LIMIT = 10
PUBLIC_IMAGE_GENERATION_PROVIDER = os.getenv("PUBLIC_IMAGE_GENERATION_PROVIDER", "openai-first")
openai_image_fallback_count = 0
openai_image_fallback_lock = Lock()


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


def output_is_png(path: Path) -> bool:
    """Return True when a generated file looks like a PNG image."""
    if not path.exists() or path.stat().st_size <= len(PNG_SIGNATURE):
        return False
    with path.open("rb") as image_file:
        return image_file.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE


def require_png_output(path: Path, *, provider: str) -> None:
    """Raise a clear error when a provider leaves a broken PNG output."""
    if output_is_png(path):
        return
    raise RuntimeError(f"{provider} did not create a valid PNG image.")


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


async def run_public_image_generation(
    *,
    job_dir: Path,
    user_prompt: str,
    input_paths: list[Path],
) -> Path:
    """Generate one public image with the fastest configured provider."""
    output_path = job_dir / OUTPUT_FILENAME
    codex_error: str | None = None
    openai_error: str | None = None

    if should_try_openai_first():
        try:
            metadata = await run_in_threadpool(
                run_openai_image_fallback_sync,
                output_path=output_path,
                user_prompt=user_prompt,
                input_paths=input_paths,
                codex_error=None,
            )
            write_generation_metadata(job_dir=job_dir, metadata=metadata)
            return output_path
        except Exception as error:
            openai_error = str(error)

    try:
        metadata = await run_codex_image_generation(
            job_dir=job_dir,
            output_path=output_path,
            user_prompt=user_prompt,
            input_paths=input_paths,
        )
        write_generation_metadata(job_dir=job_dir, metadata=metadata)
        return output_path
    except Exception as error:
        codex_error = str(error)

    if openai_error is not None:
        raise HTTPException(
            status_code=502,
            detail=combined_provider_error(codex_error=codex_error, openai_error=openai_error),
        )

    metadata = await run_in_threadpool(
        run_openai_image_fallback_sync,
        output_path=output_path,
        user_prompt=user_prompt,
        input_paths=input_paths,
        codex_error=combined_provider_error(codex_error=codex_error, openai_error=openai_error),
    )
    write_generation_metadata(job_dir=job_dir, metadata=metadata)
    return output_path


def should_try_openai_first() -> bool:
    """Return True when public requests should prefer the Images API."""
    provider = os.getenv(
        "PUBLIC_IMAGE_GENERATION_PROVIDER",
        PUBLIC_IMAGE_GENERATION_PROVIDER,
    ).strip().lower()
    return provider in {"openai", "openai-first", "openai-images-api"} and bool(
        (os.getenv("OPENAI_API_KEY") or "").strip()
    )


def combined_provider_error(
    *,
    codex_error: str | None,
    openai_error: str | None,
) -> str | None:
    """Return a compact fallback reason for metadata and HTTP errors."""
    parts = []
    if codex_error:
        parts.append(f"Codex failed: {codex_error}")
    if openai_error:
        parts.append(f"OpenAI first attempt failed: {openai_error}")
    return " | ".join(parts) or None


async def run_codex_image_generation(
    *,
    job_dir: Path,
    output_path: Path,
    user_prompt: str,
    input_paths: list[Path],
) -> dict[str, object]:
    """Ask Codex to generate one image and return metadata for the job."""
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
        result = await run_codex_with_context(
            codex_prompt,
            local_images=input_paths,
            cwd=job_dir,
        )
    except RuntimeError as error:
        raise RuntimeError(str(error)) from error

    require_png_output(output_path, provider="Codex")

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "codex",
        "prompt": user_prompt,
        "input_image_paths": [str(path) for path in input_paths],
        "output_image_path": str(output_path),
        "codex_response": result.final_response,
        "items_count": result.items_count,
        "model": result.model,
        "effort": result.effort,
    }


def run_openai_image_fallback_sync(
    *,
    output_path: Path,
    user_prompt: str,
    input_paths: list[Path],
    codex_error: str | None,
) -> dict[str, object]:
    """Generate the image through the OpenAI Images API after Codex fails."""
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=f"Codex failed and OPENAI_API_KEY is not configured for fallback: {codex_error}",
        )

    fallback_number = reserve_openai_image_fallback()

    if input_paths:
        response_payload = call_openai_image_edit(
            api_key=api_key,
            prompt=user_prompt,
            input_paths=input_paths,
        )
    else:
        response_payload = call_openai_image_generation(
            api_key=api_key,
            prompt=user_prompt,
        )

    image_base64 = first_response_image_base64(response_payload)
    if not image_base64:
        raise HTTPException(
            status_code=502,
            detail="OpenAI image fallback did not return image data.",
        )

    try:
        output_path.write_bytes(base64.b64decode(image_base64, validate=True))
    except (binascii.Error, ValueError) as error:
        raise HTTPException(status_code=502, detail="OpenAI image fallback returned invalid image data.") from error
    try:
        require_png_output(output_path, provider="OpenAI image fallback")
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "openai-images-api",
        "fallback_reason": codex_error,
        "prompt": user_prompt,
        "input_image_paths": [str(path) for path in input_paths],
        "output_image_path": str(output_path),
        "model": OPENAI_IMAGE_FALLBACK_MODEL,
        "size": OPENAI_IMAGE_FALLBACK_SIZE,
        "quality": OPENAI_IMAGE_FALLBACK_QUALITY,
        "fallback_number": fallback_number,
        "fallback_limit": OPENAI_IMAGE_FALLBACK_LIMIT,
    }


def reserve_openai_image_fallback() -> int:
    """Reserve one in-process Images API fallback slot or fail before calling OpenAI."""
    global openai_image_fallback_count

    with openai_image_fallback_lock:
        if openai_image_fallback_count >= OPENAI_IMAGE_FALLBACK_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=f"OpenAI image fallback limit reached ({OPENAI_IMAGE_FALLBACK_LIMIT}).",
            )
        openai_image_fallback_count += 1
        return openai_image_fallback_count


def call_openai_image_generation(*, api_key: str, prompt: str) -> dict[str, object]:
    """Call the OpenAI Images API generation endpoint."""
    response = httpx.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": OPENAI_IMAGE_FALLBACK_MODEL,
            "prompt": prompt,
            "size": OPENAI_IMAGE_FALLBACK_SIZE,
            "quality": OPENAI_IMAGE_FALLBACK_QUALITY,
            "output_format": "png",
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def call_openai_image_edit(
    *,
    api_key: str,
    prompt: str,
    input_paths: list[Path],
) -> dict[str, object]:
    """Call the OpenAI Images API edit endpoint with one or more input images."""
    with ExitStack() as stack:
        files = [
            (
                "image",
                (
                    path.name,
                    stack.enter_context(path.open("rb")),
                    mimetypes.guess_type(path.name)[0] or "image/png",
                ),
            )
            for path in input_paths
        ]
        response = httpx.post(
            "https://api.openai.com/v1/images/edits",
            headers={"Authorization": f"Bearer {api_key}"},
            data={
                "model": OPENAI_IMAGE_FALLBACK_MODEL,
                "prompt": prompt,
                "size": OPENAI_IMAGE_FALLBACK_SIZE,
                "quality": OPENAI_IMAGE_FALLBACK_QUALITY,
                "output_format": "png",
            },
            files=files,
            timeout=180,
        )
    response.raise_for_status()
    return response.json()


def first_response_image_base64(response_payload: dict[str, object]) -> str | None:
    """Return the first base64 image payload from an Images API response."""
    data = response_payload.get("data")
    if not isinstance(data, list):
        return None
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("b64_json"), str):
            return item["b64_json"]
    return None


def write_generation_metadata(*, job_dir: Path, metadata: dict[str, object]) -> None:
    """Persist job metadata for debugging and audits."""
    (job_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


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
        output_path = await run_public_image_generation(
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
