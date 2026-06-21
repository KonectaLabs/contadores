# Plan 084: Enforce Unique Meta Lead Form Routing

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/meta_leads.py src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: 020
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DELIVERY-09

## Why This Matters

Delivery Meta lead webhooks route by `form_id` when no explicit source id is supplied. The database only indexes `meta_lead_form_id`, and the lookup returns the first enabled source ordered by label/id. If two enabled sources share one form id, paid leads can silently route to the wrong recipient.

## Current State

- `meta_lead_form_id` is indexed, not unique:

```python
src/backend/database.py:2447
meta_lead_form_id: str = Field(default="", index=True)
```

- Lookup returns the first enabled row:

```python
src/backend/database.py:2536
def get_by_meta_lead_form_id(cls, form_id: str) -> Optional["ClientLeadSource"]:
```

```python
src/backend/database.py:2546
.order_by(cls.label, cls.id)
```

```python
src/backend/database.py:2548
item = session.exec(statement).first()
```

- The webhook resolver uses that lookup:

```python
src/backend/endpoints/meta_leads.py:84
form_id = _clean(value.get("form_id"))
```

```python
src/backend/endpoints/meta_leads.py:86
source = ClientLeadSource.get_by_meta_lead_form_id(form_id)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Routing scan | `rg -n "meta_lead_form_id|get_by_meta_lead_form_id|META_LEAD_WEBHOOK_DEFAULT_SOURCE_ID|meta-leads/webhook" src/backend src/backend/tests` | duplicate handling is explicit |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -k "meta or source or webhook" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/database.py src/backend/endpoints/meta_leads.py src/backend/endpoints/client_leads.py` | exit 0 |

## Scope

**In scope**:
- Add a duplicate scanner/report for non-empty enabled `meta_lead_form_id` values.
- Reject duplicate non-empty form ids during `ClientLeadSource` create/update/upsert.
- Make webhook routing fail closed when a form id is ambiguous.
- Add a partial unique index or migration-backed uniqueness guard after duplicate cleanup.
- Add tests for duplicate source configuration and webhook ambiguity.

**Out of scope**:
- Meta form creation/subscription idempotency; plan 058 covers provider writes.
- Meta webhook HMAC validation; plan 001 covers signatures.
- Broad migration framework; plan 020 covers migration discipline.

## Git Workflow

- Branch: `codex/unique-meta-lead-form-routing`
- Commit message: `Enforce unique Meta lead form routing`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a duplicate report first

Before adding a unique constraint, add a small read-only helper or command that reports duplicate enabled non-empty `meta_lead_form_id` values.

The output should include form id, source ids, labels, and enabled status.

### Step 2: Reject new duplicates

In source create/update paths, reject a non-empty `meta_lead_form_id` if another enabled source already owns it.

Disabled sources can keep historical values, but enabling a duplicate source should fail.

### Step 3: Make webhook routing fail closed

Replace first-row lookup behavior with an explicit result:

- zero matches: fallback to configured default source if present,
- one match: route normally,
- multiple matches: return a clear error and record an operator-visible event if the repo has a suitable event surface.

Do not silently pick one.

### Step 4: Add migration-backed uniqueness

After plan 020 is in place, add a partial unique index for enabled, non-empty `meta_lead_form_id` if SQLite support and migration conventions allow it.

If a partial index is not practical, keep the application-level guard plus duplicate scanner and document the limitation.

### Step 5: Add tests

Cover:

- duplicate enabled form ids are rejected,
- disabled duplicate does not break existing enabled source,
- webhook with one matching source routes correctly,
- webhook with duplicate matches fails closed.

## Test Plan

- Delivery Meta tests pass.
- Duplicate scanner returns no duplicates in clean test setup.
- Existing Delivery source create/update tests still pass.

## Done Criteria

- [ ] Duplicate enabled Meta form routing cannot be created.
- [ ] Existing duplicates are reportable before migration.
- [ ] Webhook routing no longer silently chooses the first duplicate.
- [ ] Tests cover unique and ambiguous cases.

## STOP Conditions

- Production already has duplicate enabled form ids and the owner cannot choose the correct source.
- Plan 020 has not landed and the implementation requires a schema migration.
- Meta legitimately sends the same form id to multiple recipients and a fan-out design is required.

## Maintenance Notes

Treat Meta form id as a routing key, not just metadata. Any source import/export path must preserve this uniqueness rule.
