# Plan 052: Make Contadores Message Status Transitions Monotonic

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/051-claim-contadores-outbound-messages-before-dispatch.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-02

## Why This Matters

Late provider callbacks or retry failures can regress a message that was already sent or delivered back to `undelivered` or `failed`. Plan 018 covers `ClientLeadDelivery`; this plan covers core `ContadoresMessage` rows.

## Current State

- Provider status maps `failed` directly to failed:

```python
src/bot/utils.py:774
def map_whatsapp_provider_status(status: str) -> str:
```

- External-id callback updates a row by provider id:

```python
src/backend/endpoints/contadores.py:5482
if command.status.strip().lower() == MessageDeliveryStatus.FAILED.value:
```

- Database update overwrites status:

```python
src/backend/database.py:2256
row.delivery_status = Message.normalize_delivery_status(
```

- Failure retry can move rows back to undelivered:

```python
src/backend/database.py:2304
if attempts < max_attempts:
    row.delivery_status = MessageDeliveryStatus.UNDELIVERED
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Contadores delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "delivery_status or external_id or delivery_failure" -q` | exit 0 |
| Bot delivery tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_client_lead_delivery.py -q` | exit 0 |

## Scope

**In scope**:
- Define monotonic status precedence for `ContadoresMessage`.
- Prevent delivered/sent rows from regressing on late failures.
- Preserve legitimate retry behavior before a send is confirmed.

**Out of scope**:
- Client Lead Delivery status transitions.
- Changing provider webhook parsing.
- Replaying historical provider callbacks.

## Git Workflow

- Branch: `codex/monotonic-contadores-message-status`
- Commit message: `Make Contadores message status transitions monotonic`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define precedence

Add a small helper that encodes precedence, for example:

- `undelivered` < `failed` < `sent` < `delivered`,
- terminal delivered cannot regress,
- sent can move to delivered,
- failed can move to sent/delivered on provider recovery if that is possible.

Document the choice with tests.

### Step 2: Use it in status updates

Apply the helper in:

- direct message status update,
- external-id provider callback update,
- record-delivery-failure path.

Failure recording should still store the error note, but not regress terminal successful status.

### Step 3: Add tests

Cover:

- delivered plus late failed callback stays delivered,
- sent plus late failed callback stays sent or moves only by explicit operator action,
- undelivered plus failed retry still requeues within retry budget,
- failed can recover to delivered when provider sends a later delivered callback.

## Test Plan

- Run targeted Contadores delivery tests.
- Run bot delivery tests.
- Run backend import smoke if backend files changed.

## Done Criteria

- [ ] Successful statuses do not regress on late failures.
- [ ] Retry behavior still works before success.
- [ ] Error details can still be recorded without status regression.
- [ ] Tests cover late failed, late delivered, and retry paths.

## STOP Conditions

- Product semantics require failed callbacks to override delivered status.
- External reporting depends on current regressive status behavior.
- Plan 051 changes the status model in a conflicting way.

## Maintenance Notes

Keep ContadoresMessage and ClientLeadDelivery transition semantics aligned unless there is a documented reason to diverge.
