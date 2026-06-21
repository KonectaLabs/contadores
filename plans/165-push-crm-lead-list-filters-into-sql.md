# Plan 165: Push CRM Lead List Filters Into SQL

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CRM-LIST-01

## Why This Matters

The CRM lead list fetches a capped 1,000-row recent window and then applies many filters in Python. If the matching row is older than that initial window, filtered views can be incomplete even though the database has the row and relevant fields are indexed.

Exact persisted filters should be applied in SQL before `LIMIT`.

## Current State

- Lead list starts with a fixed 1,000-row window:

```python
src/backend/endpoints/contadores.py:4945
base_leads = ContadoresLead.list_recent(
    limit=1000,
```

- Pipeline, queue, terminal, attention, manual reply, tag, strategy, and text filters run after that window:

```python
src/backend/endpoints/contadores.py:4970
for lead in base_leads:
```

```python
src/backend/endpoints/contadores.py:5053
visible_leads.append(lead)
```

- `list_recent()` only accepts a few SQL filters:

```python
src/backend/database.py:1424
def list_recent(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Lead filter scan | `rg -n "list_recent\\(|pipeline_stage|queue_state|terminal_state|attention_state|manual_reply_status|lead_matches|sort_leads_by_last_interaction" src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py` | exact filters run before limit where possible |
| Lead list tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "lead list or leads or filter or pipeline_stage or attention_state" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Extend lead query helpers to push persisted exact filters into SQL before limit.
- Cover stage, platform, archived, converted/booked timestamps, closed/archived terminal state, and other directly persisted filters.
- Keep derived/text/tag/strategy filters in Python only where SQL would be brittle.
- Avoid silently dropping metrics or tag options.
- Add tests with more than 1,000 leads where the match is outside the old window.

**Out of scope**:
- Full-text search index.
- Strategy assignment schema redesign.
- Lead summary per-row hydration; plan 166 owns serializer query batching.
- Changing response JSON shape.

## Git Workflow

- Branch: `codex/sql-crm-lead-list-filters`
- Commit message: `Push CRM lead list filters into SQL`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Split filter classes

Classify filters into:

- SQL-safe persisted filters,
- derived filters that can be expressed safely,
- Python-only filters.

Document any Python-only filter in code comments or tests.

### Step 2: Extend query helper

Add a new helper or extend `ContadoresLead.list_recent()` with optional filters. Keep the signature readable; a filter object may be cleaner than many positional args.

Apply SQL filters before ordering and limit.

### Step 3: Preserve metrics and tag options

If metrics require a broader candidate set than visible rows, compute them intentionally. Do not let the new SQL-visible window make metrics inconsistent.

### Step 4: Add regression tests

Create more than 1,000 leads, with the matching filtered lead older than the initial window. Assert filtered endpoint returns it.

Cover at least one pipeline/terminal/attention-style filter.

## Test Plan

- Lead list/filter tests pass.
- Backend import smoke passes.
- Manual scan confirms exact persisted filters are in SQL before `LIMIT`.

## Done Criteria

- [ ] Filtered CRM lead list is not limited by an unrelated 1,000-row recent window.
- [ ] Persisted exact filters run in SQL before limit.
- [ ] Python-only filters are documented and tested.
- [ ] Response shape is unchanged.

## STOP Conditions

- Metrics/tag option semantics require a broader product decision.
- Derived filters cannot be safely translated without duplicating complex business logic.
- Test fixtures for >1,000 leads make the suite unacceptably slow.

## Maintenance Notes

Limit after filtering. Operator views must be complete before they are fast.
