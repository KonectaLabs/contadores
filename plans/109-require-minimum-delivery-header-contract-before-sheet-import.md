# Plan 109: Require Minimum Delivery Header Contract Before Sheet Import

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: plans/104-make-delivery-sheet-sync-explicit-in-frontend.md
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: IMPORT-02

## Why This Matters

Delivery sheet import uses header presence to decide whether a fetched tab is a real lead sheet instead of an HTML/login page or wrong tab. Today a sheet is accepted if any expected header exists. A wrong tab with only `email`, `created_time`, or a phone-like column can pass the guard, then import blocked rows or queue wrong notifications.

Before importing rows that can trigger Delivery notifications, the source should meet a minimum header contract.

## Current State

- The header guard builds expected headers from the mapping:

```python
src/backend/endpoints/client_leads.py:936
def records_have_mappable_headers(records: list[dict[str, str]], mapping: dict[str, str]) -> bool:
```

```python
src/backend/endpoints/client_leads.py:943
expected_headers: set[str] = set()
```

- Public/private sheet fetches accept records when the guard passes:

```python
src/backend/endpoints/client_leads.py:1127
if records_have_mappable_headers(records, source.column_mapping):
```

- Accepted records are imported row by row:

```python
src/backend/endpoints/client_leads.py:1167
for index, row in enumerate(records, start=2):
```

```python
src/backend/endpoints/client_leads.py:1176
normalized_phone = normalize_phone(phone)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Header contract scan | `rg -n "records_have_mappable_headers|expected_headers|column_mapping|sheet_helpers|sync" src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py` | minimum required headers are explicit and tested |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -k "sheet_helpers or sync" -q` | exit 0 |
| Full Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |

## Scope

**In scope**:
- Define a minimum Delivery header contract before import, such as requiring a lead identity/phone path plus enough context to classify the tab as a lead sheet.
- Return a clear blocked/sync error when fetched records do not meet the contract.
- Add tests for wrong tab with one matching header.
- Preserve support for custom `column_mapping` and aliases.

**Out of scope**:
- Sheet URL allowlisting; plan 002 covers that.
- Frontend explicit sync controls; plan 104 covers hidden POST behavior.
- Public submission dedupe; plans 016 and 017 cover public form paths.
- Delivery row identity fallback; plan 110 covers fallback source row keys.

## Git Workflow

- Branch: `codex/minimum-delivery-header-contract`
- Commit message: `Require Delivery sheet header contract`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define required header groups

Pick a small readable rule. For example:

- source id or row identity path is preferred,
- phone header is required for sendable Delivery imports,
- at least one human/context field may be required depending on current template behavior.

Avoid brittle exact-header lists. Respect configured mappings.

### Step 2: Update `records_have_mappable_headers`

Make the helper return false when only one weak header matches.

If useful, add a companion helper that returns a reason string for diagnostics.

### Step 3: Surface failure clearly

When public/private sheet records fail the header contract, sync should report a clear note instead of silently returning an empty list or importing noise.

### Step 4: Add tests

Add tests for:

- a valid configured sheet,
- a wrong tab with only `email`,
- a wrong tab with only `phone_number`,
- a custom mapping that still passes when all required mapped headers exist.

## Test Plan

- Focused Delivery sheet helper/sync tests.
- Full Delivery tests.

## Done Criteria

- [ ] Delivery import refuses wrong tabs with only one weak matching header.
- [ ] Valid mapped sheets still sync.
- [ ] Operators receive a clear sync failure reason.

## STOP Conditions

- Real configured Delivery sheets do not have enough stable headers for the proposed minimum contract.
- Product owner prefers importing blocked rows from partial tabs for manual cleanup.
- The required header rule cannot be expressed without breaking custom mappings.

## Maintenance Notes

Header detection is a safety gate. Make it permissive enough for configured sheets, but strict enough to reject accidental tabs and login pages.
