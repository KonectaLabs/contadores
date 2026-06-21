# Plan 111: Require Sendable WhatsApp Phone Validation For Imports

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/client_leads.py src/backend/endpoints/contadores.py src/bot/utils.py src/backend/tests/test_client_lead_delivery.py src/backend/tests/test_contadores.py src/bot/tests/test_contadores_flow.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: IMPORT-04

## Why This Matters

Phone normalization currently returns bare digits when a value cannot be parsed as an international or configured-region phone number. Import paths treat any non-empty normalized phone as valid, and the bot dispatch guard only rejects very short numbers. That can queue WhatsApp sends to local-looking numbers without a country code, which is risky for paid lead delivery.

Imports should distinguish "phone-like text" from "sendable WhatsApp destination."

## Current State

- Generic normalization returns raw digits for ambiguous numbers:

```python
src/backend/database.py:190
def normalize_phone(value: str) -> str:
```

```python
src/backend/database.py:208
else:
    return digits
```

- Delivery import treats non-empty normalized phone as usable:

```python
src/backend/endpoints/client_leads.py:1176
normalized_phone = normalize_phone(phone)
```

```python
src/backend/endpoints/client_leads.py:1179
if not normalized_phone:
```

- Legacy Contadores import has the same boundary:

```python
src/backend/endpoints/contadores.py:4643
phone = row.phone_number.replace("p:", "").strip()
```

```python
src/backend/endpoints/contadores.py:4644
if not normalize_phone(phone):
```

- Bot dispatch only checks digit count:

```python
src/bot/utils.py:1282
to_phone = item.recipient_phone or item.normalized_recipient_phone
```

```python
src/bot/utils.py:1285
if len("".join(ch for ch in str(to_phone) if ch.isdigit())) < 8:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Phone validation scan | `rg -n "normalize_phone|sendable|invalid_whatsapp_phone|recipient_phone_invalid|lead_phone_invalid|phone_number" src/backend src/bot src/backend/tests src/bot/tests` | import and dispatch use a sendable-phone helper where appropriate |
| Delivery phone tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -k "phone or import or delivery" -q` | exit 0 |
| Contadores import tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "phone or import" -q` | exit 0 |
| Bot dispatch tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k "phone or delivery" -q` | exit 0 |

## Scope

**In scope**:
- Add a stricter helper for sendable WhatsApp destinations.
- Use it in import paths that queue Delivery/Contadores WhatsApp work.
- Use it in bot dispatch guards before provider send.
- Keep generic `normalize_phone` available for search/display if other code depends on permissive normalization.
- Add tests for local digits, international numbers, and configured-region numbers.

**Out of scope**:
- Changing public form client-side validation; plan 012 covers public form UX.
- Rewriting all phone storage history.
- Country-specific product policy beyond existing default region support.
- Provider send failures after a number passes local validation.

## Git Workflow

- Branch: `codex/require-sendable-import-phones`
- Commit message: `Require sendable phone validation for imports`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define sendable phone semantics

Add a helper such as `normalize_sendable_whatsapp_phone` or `is_sendable_whatsapp_phone`.

It should reject ambiguous local-looking digits unless the configured default region can parse and validate them.

### Step 2: Update import paths

Use the stricter helper when deciding whether to import/queue:

- Delivery lead phone,
- Delivery recipient phone,
- legacy Contadores lead phone.

Preserve existing error/block reasons where possible.

### Step 3: Update bot dispatch guard

Before calling the WhatsApp provider, validate the destination with the same sendable-phone semantics.

Avoid relying only on digit length.

### Step 4: Add tests

Cover:

- valid international `+` numbers,
- valid configured-region local numbers if supported,
- bare ambiguous local digits that should block,
- recipient phone invalid path,
- lead phone invalid path.

## Test Plan

- Delivery phone/import tests.
- Contadores import tests.
- Bot dispatch tests.

## Done Criteria

- [ ] Import paths reject ambiguous unsendable WhatsApp numbers.
- [ ] Bot dispatch rejects unsendable destinations before provider calls.
- [ ] Valid configured-region numbers still work.
- [ ] Error/block reasons remain visible to operators.

## STOP Conditions

- Current production sheets intentionally use local numbers without country codes and no configured default-region policy exists.
- Strict validation would block a known paid campaign without a migration path.
- The WhatsApp provider accepts formats that local validation cannot model and product owner prefers provider-side failure handling.

## Maintenance Notes

Keep permissive normalization separate from sendability. Search can be flexible; dispatch should be strict.
