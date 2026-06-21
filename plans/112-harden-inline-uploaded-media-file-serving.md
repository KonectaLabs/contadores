# Plan 112: Harden Inline Uploaded Media File Serving

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/endpoints/workstation.py src/backend/endpoints/contadores.py src/backend/endpoints/platform.py src/backend/tests/test_system_cache_headers.py src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py src/backend/tests/test_platform.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: STATIC-01

## Why This Matters

Several authenticated media routes serve uploaded or mirrored files inline on the same CRM origin. Some upload paths trust caller-supplied MIME types, and response routes do not set an explicit content-sniffing policy. A mislabeled SVG/HTML-like payload could become a same-origin script execution or content-sniffing problem when an operator previews the file.

Uploaded media should be treated as untrusted bytes. Inline preview should be reserved for a narrow, verified set of safe media types; everything else should download or use `application/octet-stream`, and file responses should send `X-Content-Type-Options: nosniff`.

## Current State

- Workstation media upload stores arbitrary bytes and a caller-provided content type:

```python
src/backend/endpoints/workstation.py:4566
async def upload_workstation_media(
```

```python
src/backend/endpoints/workstation.py:4582
content_type=file.content_type or mimetypes.guess_type(safe_name)[0],
```

- Workstation media is served inline using that stored content type:

```python
src/backend/endpoints/workstation.py:4631
async def get_workstation_media_file(asset_id: str) -> FileResponse:
```

```python
src/backend/endpoints/workstation.py:4639
return FileResponse(
```

- Manual outbound media stores the upload content type before classifying the file:

```python
src/backend/endpoints/contadores.py:2507
async def save_manual_outbound_media_async(*, lead: ContadoresLead, upload: UploadFile) -> tuple[str, str, str, str | None]:
```

```python
src/backend/endpoints/contadores.py:2522
content_type = upload.content_type or mimetypes.guess_type(safe_name)[0]
```

- Stored Contadores media is served inline:

```python
src/backend/endpoints/contadores.py:5090
async def get_contadores_media_by_path(media_path_token: str) -> FileResponse:
```

```python
src/backend/endpoints/contadores.py:5101
return FileResponse(
```

- Platform creative uploads accept any declared `image/*` or `video/*` family:

```python
src/backend/endpoints/platform.py:799
if media_type.startswith("image/"):
```

```python
src/backend/endpoints/platform.py:1282
content_type = file.content_type or mimetypes.guess_type(safe_name)[0]
```

- Creative assets are served inline:

```python
src/backend/endpoints/platform.py:1321
async def get_creative_asset_file(asset_id: str) -> FileResponse:
```

```python
src/backend/endpoints/platform.py:1330
return FileResponse(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| File serving scan | `rg -n "nosniff|Content-Type-Options|content_disposition_type=\"inline\"|FileResponse|UploadFile|content_type" src/backend` | untrusted media responses use nosniff and conservative inline/download policy |
| System header tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_system_cache_headers.py -q` | exit 0 |
| Media route tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py src/backend/tests/test_platform.py -k "media or creative or file" -q` | exit 0 |

## Scope

**In scope**:
- Add a small helper for safe file responses or safe media classification.
- Set `X-Content-Type-Options: nosniff` for uploaded media responses.
- Restrict inline serving to safe preview types such as JPEG, PNG, WebP, MP4, and other explicitly approved binary media.
- Treat SVG, HTML, XML, JavaScript, and unknown types as downloads or `application/octet-stream`.
- Normalize upload content types from extension and allowed-type checks instead of trusting `UploadFile.content_type` alone.
- Add focused tests for mislabeled SVG/HTML payloads, unknown file types, and allowed images/videos.

**Out of scope**:
- Upload size/count caps; plans 077 and 098 cover those limits.
- Workstation public page asset traversal; plan 035 covers public generated-page asset restrictions.
- Media retention or cleanup; plans 048 and 096 cover pruning.
- Rebuilding media preview UI.

## Git Workflow

- Branch: `codex/harden-inline-uploaded-media-serving`
- Commit message: `Harden inline uploaded media serving`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define safe preview policy

Create one readable helper that maps stored path, stored content type, and original filename to:

- response media type,
- content-disposition mode,
- extra headers.

Prefer deny-by-default for inline preview. Keep the allowed list small and obvious.

### Step 2: Use the helper on uploaded media routes

Apply the helper to:

- Workstation media files,
- Contadores message media files,
- Platform creative asset files.

Generated professional photos can stay inline as JPEG, but should still include `nosniff`.

### Step 3: Tighten upload classification

For uploads that classify by `image/*` or `video/*`, reject dangerous subtypes such as `image/svg+xml` unless there is a product-approved sanitizer.

Do not rely on client-declared MIME type alone when the extension and content type disagree.

### Step 4: Add regression tests

Cover:

- SVG uploaded as `image/svg+xml` does not get served as inline executable content,
- unknown file type downloads or uses octet-stream,
- valid PNG/JPEG media still previews,
- all affected file responses include `X-Content-Type-Options: nosniff`.

## Test Plan

- System header tests pass.
- Contadores, Workstation, and Platform media tests pass.
- `rg` scan confirms all uploaded-media `FileResponse` paths go through the safe helper or set equivalent headers.

## Done Criteria

- [ ] Uploaded media cannot be served inline as SVG/HTML/XML/JavaScript.
- [ ] Uploaded media file responses include `X-Content-Type-Options: nosniff`.
- [ ] Safe image/video previews still work.
- [ ] Tests cover at least one malicious or mislabeled content type.

## STOP Conditions

- Existing operators intentionally upload SVG files that must remain inline and no sanitizer exists.
- WhatsApp/media provider behavior requires preserving unsafe MIME types for dispatch.
- Starlette/FastAPI response behavior prevents setting the required headers without a broader response helper.

## Maintenance Notes

Keep media safety centralized. Future upload routes should call the same helper instead of hand-writing `FileResponse` options.
