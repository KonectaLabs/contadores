# Plan 120: Persist Or Recover Workstation Professional Photo Jobs

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/database.py src/frontend/src/App.tsx src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WORKSTATION-09

## Why This Matters

Professional-photo generation jobs are held in process memory. A backend restart can make the polling endpoint return 404 for a job that is still conceptually in progress or already wrote output files.

The operator experience should recover cleanly after restart instead of hiding job state.

## Current State

- Job state is documented as in-process:

```python
src/backend/endpoints/workstation.py:788
class ProfessionalPhotoJobRecord:
```

```python
src/backend/endpoints/workstation.py:802
professional_photo_jobs: dict[str, ProfessionalPhotoJobRecord] = {}
```

- Active-job dedupe depends on that dict:

```python
src/backend/endpoints/workstation.py:1274
for job in jobs:
```

- Starting a job returns the existing active in-memory job if present:

```python
src/backend/endpoints/workstation.py:4473
if active_job is not None:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Photo job scan | `rg -n "professional_photo_jobs|ProfessionalPhotoJobRecord|get_active_professional_photo_job|professional-photo/jobs" src/backend src/frontend src/backend/tests plans` | job state has persistence or restart recovery |
| Photo job tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py -k "professional_photo_job" -q` | exit 0 |

## Scope

**In scope**:
- Persist professional-photo job metadata or recover it from generated output directories.
- Make polling after restart return a useful terminal or recoverable state.
- Preserve active-job dedupe across restart where practical.
- Update frontend behavior if a job becomes recoverable/expired.

**Out of scope**:
- Image-generation model behavior.
- Workstation media upload semantics.
- Durable claiming for broader automation ticks; plan 119 covers that.

## Git Workflow

- Branch: `codex/persist-workstation-photo-jobs`
- Commit message: `Persist Workstation photo job state`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Pick persistence or recovery model

Use database/data-root job records, a metadata file beside generated versions, or recovery from output directories. Choose the smallest model that avoids misleading 404s.

### Step 2: Update start and poll paths

Record metadata before background work begins. Polling should distinguish queued/running, completed, failed, and expired/recovered.

### Step 3: Keep frontend state honest

If the backend returns `expired` or `recovered`, show that state instead of a generic error.

### Step 4: Add tests

Cover start metadata, poll after simulated in-memory clear, completed output recovery, and duplicate active start.

## Test Plan

- Backend professional-photo job tests pass.
- Frontend build passes if frontend state changes.
- Manual browser check: start job, simulate backend restart or clear, poll shows a clear state.

## Done Criteria

- [ ] Job state does not disappear silently on backend restart.
- [ ] Polling returns clear statuses instead of misleading 404s.
- [ ] Active-job dedupe survives restart or has a documented boundary.
- [ ] Operators can retry safely after failure/expiration.

## STOP Conditions

- Persisting job state requires schema changes and plan 020 has not landed.
- Image jobs cannot be cancelled/recovered safely after process death.
- Product accepts current restart behavior because photo generation is best-effort.

## Maintenance Notes

Async UI jobs need a restart story. If the server cannot continue a job, it should still explain that state and let the operator retry deliberately.
