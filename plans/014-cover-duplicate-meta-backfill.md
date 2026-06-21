# Plan 014: Cover Duplicate Meta Backfill Runs

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Meta lead-form backfill can append imported leads to a connected Google Sheet. The single-lead import path has repeat coverage, but the backfill test only runs once. A retry or scheduled backfill regression could duplicate Sheet rows even if the database dedupes locally.

## Current State

- Backfill loops fetched leads and accumulates sheet append counts:

```python
src/backend/endpoints/client_leads.py:785
async def backfill_meta_lead_form_records(...)
...
    for payload in payloads:
        result = import_meta_lead_form_record(source, meta_payload_to_import_command(payload, ""))
        totals["sheet_appended"] += result.sheet_appended
```

- Existing test covers one run:

```python
src/backend/tests/test_client_lead_delivery.py:476
def test_meta_lead_form_backfill_imports_form_leads(...):
    ...
    imported = client.post(f"/api/client-lead-sources/{source_id}/meta-leads/backfill", json={})
    assert imported.status_code == 200
    assert payload["sheet_appended"] == 2
    assert len(appended_rows) == 2
```

- Single lead import already covers repeat append behavior:

```python
src/backend/tests/test_client_lead_delivery.py:388
repeated = client.post(f"/api/client-lead-sources/{source_id}/meta-lead", json=command)
assert repeated.json()["sheet_appended"] == 0
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |

## Scope

**In scope**:
- `src/backend/tests/test_client_lead_delivery.py`
- `src/backend/endpoints/client_leads.py` only if the repeat test exposes a bug.

**Out of scope**:
- Live Meta fetches.
- Live Google Sheet appends.
- Changing source configuration.

## Git Workflow

- Branch: `codex/test-duplicate-meta-backfill`
- Commit message: `Cover duplicate Meta backfill runs`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extend the existing backfill test

In `test_meta_lead_form_backfill_imports_form_leads`, after the first assertions, call the same backfill endpoint again.

Assert:

- status code 200,
- `fetched == 2`,
- `imported == 0`,
- `updated == 2` or the existing code's correct update count,
- `queued == 0`,
- `sheet_appended == 0`,
- `len(appended_rows) == 2`.

Use the actual response shape if it differs, but do not weaken the sheet append assertion.

**Verify**: Delivery tests exit 0 or expose a real bug.

### Step 2: Fix only if the repeat test fails

If the repeat backfill appends rows again, update `import_meta_lead_form_record()` or the backfill loop so Sheet append happens only when the local import created a new delivery row.

Keep existing single-lead import behavior unchanged.

**Verify**: Delivery tests exit 0.

## Test Plan

- Repeat-backfill regression.
- Existing single-lead import repeat test.

## Done Criteria

- [ ] Repeating the same Meta form backfill does not append duplicate Google Sheet rows.
- [ ] Repeat response reports no newly queued rows.
- [ ] Delivery tests exit 0.

## STOP Conditions

- Product owner intentionally wants every backfill run appended to Sheets even for already imported leads.
- Existing endpoint response semantics make it impossible to distinguish imported vs updated without a broader API change.

## Maintenance Notes

This is a test-first plan. If the implementation already behaves correctly, the final diff should be only the regression test.
