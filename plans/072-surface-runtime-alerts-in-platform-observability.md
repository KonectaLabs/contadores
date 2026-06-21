# Plan 072: Surface Runtime Alerts In Platform Observability

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/platform.py src/backend/endpoints/contadores.py src/backend/endpoints/workstation.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OBS-02

## Why This Matters

Runtime alerts are real production incidents, but global platform observability does not surface them. Operators can see pending alert delivery state in some contexts, yet `/api/platform/overview` does not count or list open runtime alerts.

## Current State

- Runtime alerts are stored in their own table:

```python
src/backend/database.py:5379
class ContadoresRuntimeAlert(SQLModel, table=True):
```

- Alerts are created via `ContadoresRuntimeAlert.add`:

```python
src/backend/database.py:5415
def add(
```

- Platform overview loads many lifecycle records but not runtime alerts:

```python
src/backend/endpoints/platform.py:972
@platform_router.get("/overview", response_model=PlatformOverviewResponse)
```

- Pending alert delivery is separate from platform overview:

```python
src/backend/endpoints/contadores.py:6049
pending_runtime_alerts = ContadoresRuntimeAlert.list_pending_notification(...)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Platform tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "platform or runtime_alert" -q` | exit 0 |
| Contadores alert tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "runtime_alert" -q` | exit 0 |
| Overview scan | `rg -n "runtime_alert|ContadoresRuntimeAlert|PlatformOverview" src/backend/endpoints/platform.py src/backend/database.py` | overview includes runtime alert state |

## Scope

**In scope**:
- Add runtime alert counts and recent items to platform overview.
- Include unresolved and unnotified counts separately if useful.
- Optionally mirror alert create/resolve into `PlatformEvent` with idempotency.

**Out of scope**:
- Changing AgentMail alert delivery claiming; plans 053 and 054 cover delivery safety.
- Changing Workstation detail runtime-alert display.
- Changing runtime-alert schema unless required by serialization.

## Git Workflow

- Branch: `codex/surface-runtime-alerts`
- Commit message: `Surface runtime alerts in platform overview`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add read helpers

Add database helpers to list recent runtime alerts and count unresolved alerts by funnel.

Keep limits bounded.

### Step 2: Extend platform response models

Add fields to overview counts and a small runtime-alert response model.

Do not put full inbound message text or long errors into the overview response.

### Step 3: Wire overview

Load runtime alerts in `/api/platform/overview` and include them in `active_blockers` if unresolved.

### Step 4: Add tests

Create unresolved, notified, and resolved alerts and assert overview counts.

### Step 5: Consider PlatformEvent mirroring

If adding event mirroring, use idempotency keys like `runtime-alert:{id}:created`.

If mirroring is too broad, leave it as a follow-up in the plan notes after counts land.

## Test Plan

- Platform overview tests pass.
- Existing runtime alert tests pass.
- Response contains no secrets or full long payloads.

## Done Criteria

- [ ] Platform overview shows runtime alert counts.
- [ ] Recent open runtime alerts are operator-visible.
- [ ] Resolved alerts do not inflate active blocker counts.
- [ ] Tests cover open/resolved states.

## STOP Conditions

- Runtime alert serialization would expose sensitive inbound text or long errors.
- Adding event mirroring causes duplicate events.
- The UI contract for platform overview cannot accept new fields safely.

## Maintenance Notes

Keep runtime alert visibility separate from email delivery success. An unsent email is not the same as the underlying incident.
