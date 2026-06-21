# Plan 119: Add Durable Workstation Automation Claiming

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/database.py src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/086-make-scheduled-agent-task-idempotency-and-claiming-atomic.md
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WORKSTATION-08

## Why This Matters

Workstation automation uses an in-process asyncio lock. That prevents overlap inside one backend process, but not across processes, restarts, or manual tick invocations from another runtime. The same tick can send pings or start draft work.

Workstation automation needs durable claiming for active client advancement.

## Current State

- The tick lock is process-local:

```python
src/backend/endpoints/workstation.py:134
workstation_automation_tick_lock = asyncio.Lock()
```

- The route skips only if that in-process lock is held:

```python
src/backend/endpoints/workstation.py:1138
if workstation_automation_tick_lock.locked():
```

- The tick advances active clients:

```python
src/backend/endpoints/workstation.py:1211
for client in WorkstationClient.list_active_automation(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Workstation tick scan | `rg -n "workstation_automation_tick_lock|run_workstation_automation_tick|list_active_automation|advance_solo_page_client|claim" src/backend src/backend/tests plans/086*.md` | active client advancement uses a durable claim or explicit single-worker guard |
| Workstation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py -k "workstation_tick or solo_page or heartbeat" -q` | exit 0 |

## Scope

**In scope**:
- Add durable claim semantics for Workstation client automation advancement.
- Ensure active clients are not advanced twice by overlapping ticks.
- Keep scheduled task claiming aligned with plan 086.
- Add stale-claim recovery.

**Out of scope**:
- Workstation state-machine redesign.
- Professional-photo job persistence; plan 120 covers that.
- Frontend confirmation for live Codex controls; plan 129 covers operator UX.

## Git Workflow

- Branch: `codex/durable-workstation-automation-claiming`
- Commit message: `Add durable Workstation automation claiming`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define claim target

Decide whether the durable claim belongs on each Workstation client row, a lightweight lease table/file, or an existing task row.

### Step 2: Claim before advancement

Before `advance_solo_page_client`, acquire a durable claim for the client. If another tick owns the claim, skip that client and report it.

### Step 3: Release or complete the claim

Release after successful advancement. On failure, record error and timestamp so a later tick can retry after a safe window.

### Step 4: Add overlap tests

Simulate two tick calls or helper calls against the same active client and assert only one advancement/send/start path runs.

## Test Plan

- Workstation tick tests pass.
- A concurrency test proves duplicate advancement cannot happen.
- Stale claim recovery is covered or documented.

## Done Criteria

- [ ] Active Workstation client automation uses durable claiming.
- [ ] Overlapping ticks cannot double-advance a client.
- [ ] Crashed/stale claims recover safely.
- [ ] Tick summaries distinguish busy/skipped/failed work.

## STOP Conditions

- Durable claiming requires schema changes and plan 020 has not landed.
- Product confirms the backend will always run one process and one tick caller.
- Existing Workstation automation statuses cannot represent claim/retry state.

## Maintenance Notes

Process-local locks are useful as a fast path, but production automation needs persisted ownership for work that can send messages or spend model time.
