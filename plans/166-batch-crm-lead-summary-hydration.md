# Plan 166: Batch CRM Lead Summary Hydration

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/165-push-crm-lead-list-filters-into-sql.md
- **Category**: perf
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CRM-LIST-02

## Why This Matters

The main CRM lead list serializes each row with additional database reads for Workstation state and failed outbound message counts. At list size, that becomes per-row query amplification on an operator-critical view.

Lead summaries should accept precomputed maps for Workstation clients and delivery issue summaries.

## Current State

- Each summary fetches Workstation by lead id:

```python
src/backend/endpoints/contadores.py:1597
workstation_client = WorkstationClient.get_by_lead_id(lead.id)
```

- Each summary counts failed outbound messages:

```python
src/backend/endpoints/contadores.py:1599
outbound_error_count = ContadoresMessage.count_delivery_issues_by_lead(lead.id)
```

- If failures exist, each summary fetches the latest error:

```python
src/backend/endpoints/contadores.py:1671
format_whatsapp_delivery_error(ContadoresMessage.latest_delivery_issue_for_lead(lead.id))
```

- Count helper selects ids and counts in Python:

```python
src/backend/database.py:2153
select(cls.id)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Summary hydration scan | `rg -n "build_lead_summary|get_by_lead_id|count_delivery_issues_by_lead|latest_delivery_issue_for_lead|outbound_error_count" src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py` | lead list hydration is batched |
| Lead list tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "lead list or outbound_error or workstation" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add Workstation batch lookup by lead id.
- Add SQL grouped count for unacknowledged failed outbound messages by lead id.
- Add a batch latest-error helper by lead id.
- Pass precomputed maps into `build_lead_summary()`.
- Preserve fallback behavior for detail/single-row callers.
- Add tests for response shape and batched helper correctness.

**Out of scope**:
- Filter correctness before limit; plan 165 owns that.
- Campaign/Delivery hydration; plans 005 and 006 own those surfaces.
- Changing lead summary fields.

## Git Workflow

- Branch: `codex/batch-crm-lead-summary-hydration`
- Commit message: `Batch CRM lead summary hydration`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add batch helpers

Add helpers such as:

- `WorkstationClient.get_by_lead_ids()`,
- `ContadoresMessage.count_delivery_issues_by_lead_ids()`,
- `ContadoresMessage.latest_delivery_issues_by_lead_ids()`.

Use SQL `COUNT/GROUP BY` for counts.

### Step 2: Extend serializer inputs

Update `build_lead_summary()` to accept optional precomputed maps. If absent, use existing single-row behavior.

### Step 3: Hydrate once in list endpoint

For `visible_leads`, build all maps once and pass them into summary serialization.

### Step 4: Add tests

Cover:

- summaries still include Workstation ids,
- outbound error counts and latest error remain correct,
- no response shape changes,
- batch helpers handle leads with zero errors.

## Test Plan

- Lead list/outbound error tests pass.
- Backend import smoke passes.
- Manual scan shows list endpoint no longer performs per-row Workstation/error queries.

## Done Criteria

- [ ] Main CRM lead list batches Workstation summary hydration.
- [ ] Outbound error count uses grouped SQL.
- [ ] Latest delivery issue is batched.
- [ ] Single-lead serializer fallback remains readable.

## STOP Conditions

- SQL for latest error per lead becomes too clever for the repo style.
- Existing detail endpoints depend on serializer side effects.
- Plan 165 changes list flow in a way that makes this patch conflict-heavy.

## Maintenance Notes

Keep list serializers pure where possible. Query once, then render rows.
