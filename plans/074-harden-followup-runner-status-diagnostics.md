# Plan 074: Harden Followup Runner Status Diagnostics

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OBS-04

## Why This Matters

The followup runner status endpoint is an operator diagnostic surface. Missing or corrupt files currently collapse into empty values, and a lock with no visible process can report `running=True` for up to six hours. That makes it harder to distinguish healthy, stale, missing, and corrupt states.

## Current State

- Missing read errors return empty text:

```python
src/backend/endpoints/contadores.py:2051
def read_text_file(path: Path) -> str:
```

- JSON read errors return `None`:

```python
src/backend/endpoints/contadores.py:2059
def read_json_object_file(path: Path) -> dict[str, Any] | None:
```

- Lock running status allows old invisible locks until six hours:

```python
src/backend/endpoints/contadores.py:2143
pid = parse_runner_pid(lock_dir) if lock_dir.exists() else None
```

```python
src/backend/endpoints/contadores.py:2150
running = lock_dir.exists() and (
```

- Status endpoint returns the read model:

```python
src/backend/endpoints/contadores.py:4733
@contadores_router.get("/followup/runner/status", response_model=ContadoresRunnerStatusResponse)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runner status tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "followup_runner_status or runner_status" -q` | exit 0 |
| Contadores tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -q` | exit 0 |
| Diagnostics scan | `rg -n "diagnostic|degraded|stale|read_errors|runner/status" src/backend/endpoints/contadores.py README.md` | degraded states are documented |

## Scope

**In scope**:
- Expose artifact read errors instead of hiding them.
- Classify lock status as healthy, stale, missing_pid, invisible_process, or unknown.
- Include freshness for latest summary, delta JSON, launchd logs, and runner logs.
- Update README with incident-triage examples.

**Out of scope**:
- Changing the LaunchAgent itself.
- Deleting stale locks automatically.
- Moving runner artifacts to another location.

## Git Workflow

- Branch: `codex/harden-runner-status-diagnostics`
- Commit message: `Harden followup runner diagnostics`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extend response model

Add explicit diagnostic fields such as:

- `state`,
- `warnings`,
- `artifact_errors`,
- `lock_state`,
- `latest_summary_modified_at`,
- `latest_delta_modified_at`.

Keep existing fields backward compatible.

### Step 2: Preserve read errors

Replace silent empty/None reads with helpers that return value plus error metadata.

Do not raise for missing optional files; report them.

### Step 3: Classify lock state

If a lock exists but no PID is visible, return a degraded/stale state with age.

Avoid reporting long-invisible locks as healthy running.

### Step 4: Add tests

Cover:

- no artifacts,
- valid fresh lock with visible process,
- stale lock with missing PID,
- corrupt delta JSON,
- missing latest log.

### Step 5: Update docs

Document how to interpret the new states and what operators should check next.

## Test Plan

- Runner status tests pass.
- Full Contadores test file passes, or the narrow followup runner slice passes if the full file is too slow locally.
- Manual `GET /api/contadores/followup/runner/status` returns structured diagnostics.

## Done Criteria

- [ ] Missing/corrupt artifacts are visible in response metadata.
- [ ] Stale lock conditions are explicit.
- [ ] Existing consumers remain compatible.
- [ ] Tests cover healthy and degraded states.

## STOP Conditions

- Existing UI consumers crash on added response fields.
- Lock-state classification cannot be tested without touching real system locks.
- The endpoint would need privileged process inspection.

## Maintenance Notes

Diagnostics should tell the operator what is true. Recovery actions can remain manual.
