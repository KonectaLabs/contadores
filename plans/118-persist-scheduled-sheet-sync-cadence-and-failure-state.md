# Plan 118: Persist Scheduled Sheet Sync Cadence And Failure State

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/main.py src/bot/utils.py src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py src/bot/tests/test_worker_loop.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/009-make-funnel-config-source-of-truth.md
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WORKER-03

## Why This Matters

Scheduled sheet sync cadence is held in bot process memory. A restart clears throttle state, and Contadores sheet sync failures are logged but not surfaced through durable status like Delivery source failures.

Operators need to know when a funnel sync is failing, and restarts should not make scheduling behavior opaque.

## Current State

- Sync throttle state is local to the worker loop:

```python
src/bot/main.py:263
last_sheet_sync_at_by_funnel: dict[str, float] = {}
```

- The timestamp is updated before the sync attempt:

```python
src/bot/main.py:289
last_sheet_sync_at_by_funnel[funnel.id] = now
```

- Contadores sync failures are only logged:

```python
src/bot/main.py:296
logger.exception("%s sheet sync iteration failed.", funnel.label)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Sync state scan | `rg -n "last_sheet_sync_at_by_funnel|last_sheet_sync_status|sheet sync iteration failed|sheet_poll_seconds|sync" src/bot src/backend src/bot/tests src/backend/tests` | failure/cadence state is persisted or intentionally documented |
| Sync tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py src/bot/tests/test_worker_loop.py -k "sync or worker_loop" -q` | exit 0 |

## Scope

**In scope**:
- Persist last attempted sync time and last result per scheduled funnel/source.
- Mark Contadores funnel sync failures in backend-readable state.
- Keep Delivery source failure behavior aligned with existing `last_sync_status`.
- Avoid duplicate immediate syncs after bot restart unless explicitly due.

**Out of scope**:
- Sheet import semantics; plans 108-111 cover import contract issues.
- Funnel config source ownership; plan 009 covers config ownership.
- Adding a full scheduler service.

## Git Workflow

- Branch: `codex/persist-sheet-sync-scheduler-state`
- Commit message: `Persist sheet sync scheduler state`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose persistence location

Use existing backend config/status rows if possible. Keep cadence state close to the funnel/source it describes.

### Step 2: Record attempts and failures

Record last attempt timestamp, last success timestamp, status, and concise error for Contadores sync failures.

### Step 3: Update bot scheduling

Read durable last-attempt state before deciding whether a funnel/source is due. Only update attempt state when a sync starts.

### Step 4: Add tests

Cover failed sync recording, restart-like state, and successful sync clearing previous failure.

## Test Plan

- Backend sync tests pass.
- Bot worker-loop sync tests pass.
- UI/runtime status still displays useful sync state.

## Done Criteria

- [ ] Sync attempt/success/failure state survives bot restart.
- [ ] Contadores sync failures are visible beyond logs.
- [ ] Cadence calculations use durable state or clearly documented fallback.
- [ ] Delivery and Contadores sync status semantics remain aligned.

## STOP Conditions

- Persisting cadence requires schema changes and plan 020 has not landed.
- Current production relies on immediate sync after every bot restart.
- Existing status rows cannot represent failure without breaking UI assumptions.

## Maintenance Notes

Scheduling state should be observable. If the bot is the only place that knows a sync failed, operators cannot distinguish stale data from quiet leads.
