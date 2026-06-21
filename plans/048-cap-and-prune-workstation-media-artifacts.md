# Plan 048: Cap And Prune Workstation Media Artifacts

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/047-add-data-volume-backup-restore-runbook.md
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-04

## Why This Matters

Workstation uploads, manual outbound media, generated landing-page versions, preview videos, mirrored WhatsApp images, and professional-photo outputs all persist under `data/`. Some paths read whole uploads into memory and there is no quota, retention, or pruning policy, so the server can grow without bound.

## Current State

- Workstation upload reads full file into memory:

```python
src/backend/endpoints/workstation.py:4566
contents = await file.read()
```

- Manual outbound media does the same:

```python
src/backend/endpoints/contadores.py:2509
contents = await upload.read()
```

- Landing page versions are unbounded:

```python
src/backend/endpoints/workstation.py:1564
def next_landing_page_version_dir(client: WorkstationClient) -> Path:
```

- Every preview is registered as media:

```python
src/backend/endpoints/workstation.py:2690
register_generated_workstation_media(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Workstation media tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "workstation and media" -q` | exit 0 |
| Manual media tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "manual_outbound or media" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add upload size caps for Workstation and manual outbound media.
- Add configurable retention or max-version caps for generated Workstation artifacts.
- Add a read-only usage report or prune preview command.
- Update README and `.env.example`.

**Out of scope**:
- Deleting existing production files automatically on deploy.
- Compressing existing media.
- Moving media to object storage.
- Changing WhatsApp media send behavior.

## Git Workflow

- Branch: `codex/cap-prune-workstation-media`
- Commit message: `Cap and prune Workstation media artifacts`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add upload caps

Add env-backed caps with conservative defaults:

- `WORKSTATION_MEDIA_MAX_UPLOAD_BYTES`,
- `CONTADORES_MANUAL_MEDIA_MAX_UPLOAD_BYTES`.

Reject oversized uploads before writing them. If streaming validation is practical with FastAPI `UploadFile`, avoid reading unbounded contents into memory.

### Step 2: Add artifact retention settings

Add simple settings such as:

- max landing page versions per client,
- max generated preview videos per client,
- max professional photo versions per client.

Start with reporting and explicit prune commands, not automatic destructive deletion.

### Step 3: Add a usage/prune command

Add a script or backend helper that can:

- report data usage by Workstation client,
- list candidates beyond retention,
- prune only with explicit confirmation.

Do not prune active public-page current versions.

### Step 4: Add tests

Cover:

- oversized Workstation upload rejected,
- oversized manual media upload rejected,
- usage report identifies old generated versions,
- prune skips current active public version.

## Test Plan

- Run targeted media tests.
- Run backend import smoke.
- Run usage/prune command in dry-run mode.

## Done Criteria

- [ ] Upload caps exist and are documented.
- [ ] Oversized uploads are rejected before disk writes.
- [ ] Workstation artifact usage can be reported.
- [ ] Prune behavior is explicit and skips active public/current artifacts.

## STOP Conditions

- Current production media exceeds proposed defaults and operator has not approved new limits.
- Prune logic cannot reliably identify active/current artifacts.
- Backup plan 047 has not landed and destructive pruning is being implemented.

## Maintenance Notes

Make deletion opt-in. The first safe win is visibility plus caps on new growth.
