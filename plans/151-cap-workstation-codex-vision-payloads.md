# Plan 151: Cap Workstation Codex Vision Payloads

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/tests/test_workstation.py src/backend/tests/test_contadores.py .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WORKSTATION-11

## Why This Matters

Workstation professional-photo generation sends selected local images and prompt/context text to Codex. The endpoint validates ownership and image MIME type, but it does not cap image count, individual image bytes, total bytes, edit prompt length, or context length before invoking Codex.

Vision payloads should fail early with clear operator-visible errors instead of creating oversized provider requests.

## Current State

- Create commands require at least one media asset but do not cap count or context length:

```python
src/backend/endpoints/workstation.py:805
class CreateProfessionalPhotoCommand(BaseModel):
    media_asset_ids: list[str] = Field(default_factory=list, min_length=1)
    context: str = ""
```

- Edit commands have no prompt/context count caps:

```python
src/backend/endpoints/workstation.py:824
class EditProfessionalPhotoCommand(BaseModel):
    base_version: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    media_asset_ids: list[str] = Field(default_factory=list)
```

- Asset resolution checks ownership and image type, not bytes/count:

```python
src/backend/endpoints/workstation.py:1317
def get_client_image_assets(client: WorkstationClient, media_asset_ids: list[str]) -> list[WorkstationMediaAsset]:
```

- All resolved paths are passed to Codex:

```python
src/backend/endpoints/workstation.py:1403
local_images=resolved_source_paths,
```

```python
src/backend/endpoints/workstation.py:1524
local_images=[base_image, *resolved_source_paths],
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Vision payload scan | `rg -n "CreateProfessionalPhotoCommand|EditProfessionalPhotoCommand|get_client_image_assets|local_images|max.*image|context|prompt" src/backend/endpoints/workstation.py src/backend/tests README.md .env.example` | image/text caps are visible |
| Workstation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_workstation.py src/backend/tests/test_contadores.py -k "professional_photo or workstation" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Cap selected reference image count.
- Cap individual image bytes and total image bytes before Codex invocation.
- Cap create context length and edit prompt length.
- Return clear 400 or failed job errors before calling `run_codex_with_context()`.
- Add tests for too many images, oversized image, oversized total payload, and too-long prompt/context.
- Document defaults if env vars are added.

**Out of scope**:
- Operator confirmation for live Codex controls; plan 129 owns that.
- Workstation media retention/pruning; plans 048 and 120 own storage lifecycle.
- Inline uploaded-media serving safety; plan 112 owns static serving.
- Changing generated image quality or model behavior.

## Git Workflow

- Branch: `codex/cap-workstation-codex-vision-payloads`
- Commit message: `Cap Workstation Codex vision payloads`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose readable defaults

Pick conservative defaults for:

- max reference images for create,
- max additional reference images for edit,
- max bytes per image,
- max total image bytes,
- max context/prompt characters.

Use env vars only if operations need tuning.

### Step 2: Validate before job execution

Add a validation helper that resolves media paths, checks ownership/type as today, then checks count and bytes.

For edit jobs, include the base image in the total-byte cap.

### Step 3: Return clear failures

Reject invalid payloads before creating expensive Codex work. If validation happens inside async job execution, mark the job failed with a short redacted error.

### Step 4: Add tests

Use tiny fixture files and mocked stat sizes where practical. Avoid real large files.

Cover create and edit paths.

## Test Plan

- Workstation/professional-photo tests pass.
- Backend import smoke passes.
- No live Codex call is made in cap tests.

## Done Criteria

- [ ] Workstation Codex vision jobs enforce image count and byte caps.
- [ ] Prompt/context text is bounded before Codex invocation.
- [ ] Oversized payloads produce clear operator-visible errors.
- [ ] Tests cover create and edit payload limits.

## STOP Conditions

- Current production client assets commonly exceed proposed caps.
- Existing UI cannot display validation errors without a broader frontend change.
- Cap enforcement would require reading remote files or untrusted paths.

## Maintenance Notes

Upload caps and provider payload caps are different boundaries. Validate what is sent to Codex, not only what was accepted into storage.
