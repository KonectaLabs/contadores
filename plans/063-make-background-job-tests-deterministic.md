# Plan 063: Make Background Job Tests Deterministic

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: plans/024-wire-ci-and-test-dependencies.md
- **Category**: test-safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: TEST-04

## Why This Matters

The professional-photo job test depends on background task scheduling, shared in-process job state, and polling with `time.sleep`. That can flake once the suite runs in CI or under parallel local load.

## Current State

- Jobs are held in global process state:

```python
src/backend/endpoints/workstation.py:802
professional_photo_jobs: dict[str, ProfessionalPhotoJobRecord] = {}
```

- The endpoint starts a background task:

```python
src/backend/endpoints/workstation.py:4484
asyncio.create_task(
    run_create_professional_photo_job(
```

- The test manually clears global state and polls:

```python
src/backend/tests/test_contadores.py:9697
workstation_endpoints.professional_photo_jobs.clear()
```

```python
src/backend/tests/test_contadores.py:9728
for _ in range(20):
    ...
    time.sleep(0.05)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Workstation photo job test | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k professional_photo_job -q` | exit 0 |
| Workstation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k workstation -q` | exit 0 |
| Polling scan | `rg -n "time\\.sleep|professional_photo_jobs\\.clear\\(\\)" src/backend/tests src/backend/endpoints/workstation.py` | no test-owned polling for professional-photo jobs |

## Scope

**In scope**:
- Add a deterministic test hook or injectable background-job scheduler for professional-photo jobs.
- Add autouse cleanup for the in-process professional-photo job registry.
- Remove polling sleeps from the professional-photo job test.

**Out of scope**:
- Replacing the production in-process job registry.
- Changing the API contract for professional-photo job polling.
- Adding a persistent queue.

## Git Workflow

- Branch: `codex/deterministic-background-job-tests`
- Commit message: `Make professional photo job tests deterministic`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add cleanup in test setup

Add an autouse fixture that clears `workstation_endpoints.professional_photo_jobs` before and after relevant backend tests.

### Step 2: Make job execution injectable

Wrap `asyncio.create_task(...)` behind a small local helper in `workstation.py`, for example:

```python
def schedule_background_task(coro) -> asyncio.Task:
    return asyncio.create_task(coro)
```

Tests can monkeypatch that helper to run the coroutine deterministically.

### Step 3: Remove polling sleeps from the test

Update the professional-photo job test to execute the job through the hook and then assert the final status without `time.sleep`.

### Step 4: Keep production behavior unchanged

The default helper must still call `asyncio.create_task` in production.

## Test Plan

- Targeted professional-photo job test passes repeatedly.
- Workstation `-k workstation` slice passes.
- The polling scan no longer finds this job test relying on sleep/manual clear.

## Done Criteria

- [ ] Professional-photo job tests are deterministic.
- [ ] Test cleanup owns global job-state reset.
- [ ] Production endpoint still returns `202` and pollable job status.
- [ ] No unrelated Workstation behavior changed.

## STOP Conditions

- Making the test deterministic requires a production queue refactor.
- The test hook changes endpoint response timing for production.
- Cleanup hides a real cross-test state dependency that needs a separate fix.

## Maintenance Notes

Keep this as a testability seam only. A durable job queue is a separate product/runtime decision.
