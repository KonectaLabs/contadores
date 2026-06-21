# Plan 085: Enforce Contadores WhatsApp External ID Uniqueness

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: 020, 052
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WHATSAPP-08

## Why This Matters

WhatsApp provider external ids are durable idempotency keys for inbound retries and outbound delivery callbacks. The code can detect ambiguity after duplicates exist, but the database allows duplicate external ids. Once corrupted, callbacks can fail with 409 or inbound retries can attach to the wrong first row.

## Current State

- `ContadoresMessage.external_id` is indexed, not unique:

```python
src/backend/database.py:1917
external_id: str | None = Field(default=None, index=True)
```

- Inbound retry dedupe picks the first stored inbound message:

```python
src/backend/endpoints/contadores.py:4479
def duplicate_inbound_response(command: ContadoresWhatsAppInboundCommand) -> ContadoresWhatsAppInboundResponse | None:
```

```python
src/backend/endpoints/contadores.py:4485
existing_messages = ContadoresMessage.list_by_external_id(external_id, from_me=False)
```

```python
src/backend/endpoints/contadores.py:4489
existing_message = existing_messages[0]
```

- Outbound delivery callbacks detect duplicates only after they exist:

```python
src/backend/endpoints/contadores.py:5474
matches = ContadoresMessage.list_by_external_id(command.external_id, from_me=True)
```

```python
src/backend/endpoints/contadores.py:5477
if len(matches) > 1:
```

```python
src/backend/endpoints/contadores.py:5478
raise HTTPException(status_code=409, detail="Ambiguous external_id across Contadores messages")
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| External id scan | `rg -n "external_id|list_by_external_id|delivery/by-external-id|duplicate_inbound_response" src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py` | uniqueness and idempotency paths are explicit |
| Contadores message tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "external_id or inbound or delivery" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/database.py src/backend/endpoints/contadores.py` | exit 0 |

## Scope

**In scope**:
- Add a duplicate report for non-empty Contadores message external ids.
- Enforce uniqueness for non-empty external ids, scoped by `from_me` if inbound and outbound provider ids can overlap.
- Handle insert/update `IntegrityError` idempotently.
- Update inbound retry handling to fail closed if duplicates are discovered before migration cleanup.
- Add tests for inbound retry dedupe and outbound callback uniqueness.

**Out of scope**:
- Delivery table external ids; plan 019 covers Client Lead Delivery external ids.
- Status monotonicity rules; plan 052 covers Contadores message status transitions.
- Dispatch claiming; plan 051 covers claim-before-dispatch.

## Git Workflow

- Branch: `codex/unique-contadores-whatsapp-external-id`
- Commit message: `Enforce Contadores WhatsApp external ids`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Decide uniqueness scope

Confirm whether Meta/WhatsApp can reuse the same external id across inbound and outbound directions.

If reuse is possible, enforce uniqueness on `(from_me, external_id)` for non-empty ids. If not, enforce `external_id` globally.

### Step 2: Report existing duplicates

Add a read-only duplicate query for production preflight.

The report should group by the chosen uniqueness key and include message ids, lead ids, direction, created timestamps, and statuses.

### Step 3: Guard writes before migration

Before adding a DB constraint, update message insert/update paths so a duplicate external id returns the existing row when idempotent or fails with a clear error when it is conflicting.

### Step 4: Add migration-backed uniqueness

After plan 020 and duplicate cleanup, add a partial unique index for non-empty external ids using the chosen scope.

### Step 5: Add tests

Cover:

- duplicate inbound webhook with same external id is idempotent,
- conflicting duplicate inbound external id is rejected or fails closed,
- outbound delivery callback updates exactly one row,
- duplicate outbound external id cannot be introduced.

## Test Plan

- Focused Contadores tests pass.
- Duplicate report is safe to run read-only.
- Existing inbound and outbound callback tests still pass.

## Done Criteria

- [ ] Non-empty provider external ids cannot become ambiguous.
- [ ] Existing duplicates are reportable before migration.
- [ ] Inbound retry and outbound callback paths handle uniqueness errors idempotently.
- [ ] Tests cover duplicate and valid callback paths.

## STOP Conditions

- Production already has duplicates that cannot be resolved safely.
- Provider id scope across inbound/outbound is unclear.
- Plan 020 has not landed and the fix requires a schema constraint.

## Maintenance Notes

Do not rely on order-by-first behavior for provider idempotency. Provider ids should be treated as keys.
