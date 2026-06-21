# Plan 110: Stabilize Delivery Sheet Row Identity Without Source ID

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/client_leads.py src/backend/database.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/018-make-delivery-status-transitions-monotonic.md, plans/109-require-minimum-delivery-header-contract-before-sheet-import.md
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: IMPORT-03

## Why This Matters

Delivery deduplication depends on `(source_id, source_row_key)`. When a sheet row has no mapped source id, the fallback key includes a hash of the entire raw row. Editing a non-identity field such as name, email, or context on the same sheet row changes the hash, creates a new key, and can queue a second notification for the same lead.

This is separate from public form dedupe. It is the identity contract for sheet-imported Delivery rows.

## Current State

- The fallback row hash covers the whole raw row:

```python
src/backend/endpoints/client_leads.py:541
def stable_row_hash(row: dict[str, str]) -> str:
```

```python
src/backend/endpoints/client_leads.py:543
payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
```

- Rows without a source id use row number plus whole-row hash:

```python
src/backend/endpoints/client_leads.py:547
def source_row_key_for(row: dict[str, str], *, row_number: int, source_id_value: str) -> str:
```

```python
src/backend/endpoints/client_leads.py:552
return f"row:{row_number}:{stable_row_hash(row)}"
```

- Import uses that key for upsert:

```python
src/backend/endpoints/client_leads.py:1177
source_row_key = source_row_key_for(row, row_number=index, source_id_value=source_id_value)
```

```python
src/backend/endpoints/client_leads.py:1193
item, created = ClientLeadDelivery.upsert_from_sheet_row(
```

- Database uniqueness is scoped to source id plus row key:

```python
src/backend/database.py:2669
UniqueConstraint("source_id", "source_row_key", name="uq_client_lead_deliveries_source_row_key"),
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Row identity scan | `rg -n "stable_row_hash|source_row_key_for|source_row_key|upsert_from_sheet_row" src/backend/endpoints/client_leads.py src/backend/database.py src/backend/tests/test_client_lead_delivery.py` | fallback identity excludes mutable non-identity fields or requires explicit source id |
| Delivery identity tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -k "sync or dedupe or source_row_key" -q` | exit 0 |
| Full Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |

## Scope

**In scope**:
- Stabilize fallback row identity when `source_id` is missing.
- Prefer a deterministic key based on row number plus stable identity fields, or require source id for auto-sendable imports.
- Add tests proving mutable context changes do not queue duplicate notifications.
- Preserve existing rows where possible and document migration/backfill risk.

**Out of scope**:
- Public campaign submission dedupe; plans 016 and 017 cover that path.
- Delivery status transition monotonicity; plan 018 covers status semantics.
- External-id uniqueness for provider callbacks; plan 019 covers that.
- Header contract validation; plan 109 covers minimum sheet shape.

## Git Workflow

- Branch: `codex/stabilize-delivery-row-identity`
- Commit message: `Stabilize Delivery sheet row identity`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose fallback identity policy

Pick one clear rule:

- require mapped `source_id` for sendable Delivery imports and block rows without it, or
- use row number plus stable lead identity fields like normalized phone and created time, not the full mutable row.

The safer product choice may depend on existing configured sheets.

### Step 2: Implement the helper change

Update `source_row_key_for` and any helper tests. Keep the helper easy to reason about.

### Step 3: Protect existing rows

Decide how existing fallback keys should behave:

- no migration, only future imports use the new key,
- or lookup legacy fallback keys for the same row during transition.

Avoid creating a destructive migration unless plan 020 has landed.

### Step 4: Add duplicate prevention tests

Test that:

- same row and same phone with changed name/email/context updates the existing delivery row,
- different source id still creates a distinct row,
- rows without enough identity are blocked instead of queued if that policy is chosen.

## Test Plan

- Focused Delivery sync/dedupe tests.
- Full Delivery tests.

## Done Criteria

- [ ] Mutable sheet context changes do not create duplicate pending Delivery notifications.
- [ ] Fallback identity policy is explicit and tested.
- [ ] Existing configured sheets have a clear migration/compatibility path.

## STOP Conditions

- Existing production sheets lack stable source ids and row-number fallback cannot safely identify leads.
- Any identity change would duplicate or orphan existing pending Delivery rows without a migration plan.
- Plan 109 changes the header/source-id requirements in a way that supersedes this plan.

## Maintenance Notes

Identity should come from stable lead facts, not the entire mutable row payload.
