# Plan 077: Cap CRM Manual Media Upload Size And Count

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/frontend/src/App.tsx .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: MEDIA-04

## Why This Matters

CRM manual media sends accept multiple operator-uploaded files and read each file fully into memory before writing to disk. There is no backend count limit, total-size limit, or per-file limit. A mistaken large upload can spike memory and disk usage before WhatsApp rejects it.

## Current State

- Manual media upload accepts a list of files:

```python
src/backend/endpoints/contadores.py:5141
@contadores_router.post("/leads/{lead_id}/messages/manual-media", response_model=ContadoresQuickActionResponse)
```

```python
src/backend/endpoints/contadores.py:5145
file: list[UploadFile] = File(...),
```

- Each file is read into memory before any size check:

```python
src/backend/endpoints/contadores.py:2507
async def save_manual_outbound_media_async(*, lead: ContadoresLead, upload: UploadFile) -> tuple[str, str, str, str | None]:
```

```python
src/backend/endpoints/contadores.py:2509
contents = await upload.read()
```

- The frontend accepts multiple files via picker, drag/drop, and paste:

```tsx
src/frontend/src/App.tsx:8390
function mergeFiles(nextFiles: File[]) {
```

```tsx
src/frontend/src/App.tsx:8488
<input
  type="file"
  multiple
```

- Creative asset upload already has a max upload size pattern:

```python
src/backend/endpoints/platform.py:43
CREATIVE_ASSET_MAX_UPLOAD_BYTES = 250 * 1024 * 1024
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Manual media tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "manual_media or manual_outbound or media" -q` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Upload cap scan | `rg -n "MANUAL.*MEDIA|MAX.*UPLOAD|manual-media|mergeFiles" src/backend/endpoints/contadores.py src/frontend/src/App.tsx .env.example README.md` | caps are visible |

## Scope

**In scope**:
- Add backend per-file, total-size, and file-count limits for CRM manual media uploads.
- Reject oversized uploads before enqueueing any messages.
- Add frontend limits and operator-visible rejection text.
- Document env defaults if the limits are configurable.

**Out of scope**:
- Workstation media retention; plan 048 covers Workstation media caps/pruning.
- Outbound data-root restrictions; plan 046 covers path safety.
- Changing WhatsApp provider upload behavior.

## Git Workflow

- Branch: `codex/cap-crm-manual-media-upload`
- Commit message: `Cap CRM manual media uploads`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define conservative limits

Use readable constants in `contadores.py`, for example:

```python
CONTADORES_MANUAL_MEDIA_MAX_FILES = 5
CONTADORES_MANUAL_MEDIA_MAX_FILE_BYTES = 25 * 1024 * 1024
CONTADORES_MANUAL_MEDIA_MAX_TOTAL_BYTES = 50 * 1024 * 1024
```

Make them env-configurable only if operators need that flexibility. If configurable, document in `.env.example`.

### Step 2: Validate before enqueueing

Validate file count before reading files.

When reading files, enforce per-file and cumulative byte limits before writing any queued message rows. If one file fails, the request should fail without partial enqueue.

### Step 3: Keep stored-file writes simple

After validation, continue storing files under the existing outbound media path.

Do not change media URL/token behavior in this plan.

### Step 4: Add frontend feedback

In `ManualDock`, reject files that exceed the frontend mirror of the backend limits and show a short error near the file picker.

The backend remains authoritative.

### Step 5: Add tests

Cover:

- too many files,
- one oversized file,
- total size exceeded,
- valid multiple files still enqueue in order,
- failure does not enqueue partial messages.

## Test Plan

- Manual media test slice passes.
- Frontend build passes.
- Manual browser check rejects oversized/many files before submit where possible.

## Done Criteria

- [ ] Manual media upload has backend count and size limits.
- [ ] Oversized requests do not create partial queued messages.
- [ ] Frontend shows the same limits.
- [ ] README or `.env.example` documents configurable limits if added.

## STOP Conditions

- WhatsApp template/media requirements demand larger files than the proposed defaults.
- FastAPI upload handling makes pre-read total limits unreliable without a broader middleware.
- Existing production use regularly sends more than the proposed file count.

## Maintenance Notes

Keep limits aligned with WhatsApp practical media constraints and server memory, not with arbitrary browser behavior.
