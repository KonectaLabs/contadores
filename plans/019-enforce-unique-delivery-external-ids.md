# Plan 019: Enforce Unique Delivery External IDs

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/018-make-delivery-status-transitions-monotonic.md, plans/020-add-migration-discipline-for-production-schema-changes.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Provider callbacks identify sent WhatsApp messages by external id. The database only indexes `external_id`, and the callback updater selects the first match. If two rows share an external id because of a provider retry, test fixture, or bug, the callback can update the wrong Delivery row.

## Current State

- `external_id` is indexed but not unique:

```python
src/backend/database.py:2686
external_id: str | None = Field(default=None, index=True)
```

- Callback lookup updates the first row:

```python
src/backend/database.py:2937
statement = select(cls).where(cls.external_id == clean_external_id).limit(1)
row = session.exec(statement).first()
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/database.py`
- `src/backend/tests/test_client_lead_delivery.py`

**Out of scope**:
- Changing Contadores message external id behavior.
- Changing provider webhook parsing.
- Broad migration framework; plan 020 covers migration discipline and should land before this plan adds the unique index.

## Git Workflow

- Branch: `codex/unique-delivery-external-ids`
- Commit message: `Enforce unique Delivery external ids`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add duplicate audit helper

Add a helper that finds duplicate non-empty Delivery external ids. Keep it simple:

```sql
SELECT external_id, COUNT(*) FROM client_lead_deliveries
WHERE external_id IS NOT NULL AND external_id != ''
GROUP BY external_id
HAVING COUNT(*) > 1
```

Use it in tests and in the migration/index function.

### Step 2: Add a partial unique index

Using the migration/index pattern from plan 020, add an `ensure_client_lead_delivery_external_id_index()` startup schema helper:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_client_lead_deliveries_external_id
ON client_lead_deliveries (external_id)
WHERE external_id IS NOT NULL AND external_id != ''
```

Before creating it, detect duplicates. If duplicates exist, log the count and skip index creation or raise a clear migration error depending on repo rollout preference. Do not let SQLite fail with an opaque stack trace.

### Step 3: Make callback ambiguity explicit

Update `update_delivery_status_by_external_id()` so it fails clearly if more than one row matches before the index exists.

Implementation shape:

- query up to 2 rows,
- return `None` if 0,
- raise a readable `ValueError` or custom error if 2,
- update exactly one row.

Route the endpoint to return a non-2xx error for ambiguity.

### Step 4: Add regression tests

Test:

- a callback updates exactly one row when external id is unique,
- duplicate rows cause an explicit error before the unique index exists,
- empty external ids are still allowed on unsent rows.

## Test Plan

- Delivery callback tests.
- Existing send/failure/retry tests.
- Backend import smoke.

## Done Criteria

- [ ] Non-empty Delivery external ids are unique or duplicate data blocks the migration clearly.
- [ ] Callback updater cannot silently update an arbitrary row.
- [ ] Empty external ids remain allowed before send.
- [ ] Delivery tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- Production DB already has duplicate external ids and there is no safe repair rule.
- Provider can legitimately reuse one external id for multiple recipients.

## Maintenance Notes

This plan should land after plan 018 so callback updates already respect monotonic status transitions.
