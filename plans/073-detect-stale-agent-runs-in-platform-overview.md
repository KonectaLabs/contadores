# Plan 073: Detect Stale Agent Runs In Platform Overview

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/ai/codex_agent_runtime.py src/backend/endpoints/platform.py src/backend/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OBS-03

## Why This Matters

Autonomous Codex runs can start and then crash or hang outside the normal exception path. A row can remain `running` forever. Platform overview currently counts failed runs, but not stale running runs that need operator intervention.

## Current State

- Agent runs default to `running`:

```python
src/backend/database.py:3710
status: str = Field(default="running", index=True)
```

- Runtime starts a row before invoking Codex:

```python
src/backend/ai/codex_agent_runtime.py:247
AgentRun.start(
```

- Success and handled exceptions finish the row:

```python
src/backend/ai/codex_agent_runtime.py:304
AgentRun.finish(
```

```python
src/backend/ai/codex_agent_runtime.py:317
except Exception as error:
```

- Platform overview counts failed runs only:

```python
src/backend/endpoints/platform.py:994
failed_agent_runs = sum(1 for row in agent_runs if row.status in {"failed", "error", "blocked"})
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Platform tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "agent_run or platform" -q` | exit 0 |
| Agent runtime tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_api.py src/backend/tests/test_agent_cli.py -q` | exit 0 |
| Stale scan | `rg -n "stale.*agent|running.*agent|AgentRun" src/backend/endpoints/platform.py src/backend/database.py` | stale detection is explicit |

## Scope

**In scope**:
- Define stale-running agent-run detection by age.
- Expose stale-running counts and recent stale rows in platform overview.
- Add tests for fresh running, stale running, failed, and completed runs.

**Out of scope**:
- Killing or restarting Codex runs automatically.
- Adding heartbeat writes from Codex turns unless needed for detection.
- Changing tool idempotency; plan 056 covers tool side effects.

## Git Workflow

- Branch: `codex/stale-agent-run-overview`
- Commit message: `Detect stale agent runs in platform overview`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define threshold

Start with an env-configurable threshold, for example:

```text
CODEX_AGENT_RUN_STALE_AFTER_SECONDS=3600
```

Default conservatively so long legitimate runs are not flagged too early.

### Step 2: Add helper logic

Add a simple function:

```python
is_stale_agent_run(row, now)
```

It should require `status == "running"` and `started_at` older than the threshold.

### Step 3: Extend overview counts

Add `stale_agent_runs` to `PlatformOverviewCounts` and include it in `active_blockers`.

### Step 4: Add tests

Test that:

- a fresh running run is not stale,
- an old running run is stale,
- failed/completed runs are not counted as stale-running,
- stale rows appear in overview.

### Step 5: Document operator response

Explain that this is diagnostic only. Manual cleanup or rerun is a separate operational action.

## Test Plan

- Platform tests pass.
- Agent API/CLI tests pass.
- No live Codex calls are made.

## Done Criteria

- [ ] Stale running agent runs are visible in platform overview.
- [ ] Threshold is configurable and documented.
- [ ] Active blocker count includes stale runs.
- [ ] Tests cover threshold behavior.

## STOP Conditions

- Existing long-running Codex jobs regularly exceed the default threshold.
- AgentRun timestamps are unreliable in production.
- The implementation would mutate stale rows instead of reporting them.

## Maintenance Notes

Detection should be read-only. Cleanup belongs in a later operator action plan.
