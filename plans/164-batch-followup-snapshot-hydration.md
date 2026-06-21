# Plan 164: Batch Follow-up Snapshot Hydration

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py scripts/build_contadores_crm_runner_delta.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: SNAPSHOT-01

## Why This Matters

The follow-up snapshot endpoints can request up to 20,000 leads and 30 recent messages per lead. Snapshot construction currently loads full message history for each lead and performs a Workstation lookup per lead. That can turn a runner snapshot into tens of thousands of queries and far more rows than the response needs.

Snapshot hydration should batch recent messages, latest inbound/outbound, and Workstation client lookups.

## Current State

- Snapshot endpoint has high limits:

```python
src/backend/endpoints/contadores.py:4692
limit: int = Query(default=5000, ge=1, le=20000),
messages_per_lead: int = Query(default=8, ge=1, le=30),
```

- Each lead loads full conversation history:

```python
src/backend/endpoints/contadores.py:1855
messages = ContadoresMessage.list_by_lead(lead.id)
```

- Each lead performs a Workstation lookup:

```python
src/backend/endpoints/contadores.py:1859
workstation_client = WorkstationClient.get_by_lead_id(lead.id)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Snapshot hydration scan | `rg -n "build_followup_lead_snapshot|build_followup_snapshot_response|list_by_lead|get_by_lead_id|followup/snapshot|messages_per_lead" src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py` | snapshot hydration is batched |
| Snapshot tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "followup_snapshot or snapshot_csv" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add batch message hydration keyed by lead id.
- Fetch only the latest N messages per lead plus latest inbound/outbound data needed for buckets.
- Batch Workstation clients by lead id.
- Keep JSON and CSV response shapes unchanged unless plan 146 has already changed CSV profile behavior.
- Add regression tests that catch full-history and per-lead query patterns.

**Out of scope**:
- Snapshot CSV redaction/formula safety; plans 143 and 146 own export content.
- Runner target/report retention; plans 093 and 096 own runner ops.
- Changing automation decisions.
- Replacing SQLite.

## Git Workflow

- Branch: `codex/batch-followup-snapshot-hydration`
- Commit message: `Batch follow-up snapshot hydration`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add batch message helpers

Add helpers that accept lead ids and return:

- recent messages by lead id, capped to `messages_per_lead`,
- latest inbound by lead id,
- latest outbound by lead id.

Use SQL ordering/windowing where practical. If SQLite window functions are needed, confirm supported version or use a readable bounded fallback.

### Step 2: Add Workstation batch lookup

Add `WorkstationClient.get_by_lead_ids()` or equivalent returning a map by lead id.

### Step 3: Refactor snapshot builder

Update `build_followup_snapshot_response()` to build hydration maps once and pass data into each per-lead serializer.

Keep a simple fallback for single-lead tests if useful.

### Step 4: Add regression tests

Create many leads with long histories and assert:

- response includes only requested recent message count,
- latest inbound/outbound are correct,
- Workstation exclusion logic still works,
- query count or selected row volume is bounded if the test harness can observe it.

## Test Plan

- Snapshot JSON/CSV tests pass.
- Backend import smoke passes.
- No live runner is started.

## Done Criteria

- [ ] Snapshot hydration avoids per-lead full-history reads.
- [ ] Workstation client lookup is batched.
- [ ] Response shape remains compatible.
- [ ] Tests cover many leads with long histories.

## STOP Conditions

- SQLite version lacks the query features needed for readable batching.
- Existing runner relies on full conversation histories beyond `messages_per_lead`.
- The refactor would duplicate too much snapshot logic without first splitting helpers.

## Maintenance Notes

The snapshot endpoint is an automation boundary. Keep it predictable at production volumes.
