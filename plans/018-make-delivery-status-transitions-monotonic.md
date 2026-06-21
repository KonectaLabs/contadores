# Plan 018: Make Delivery Status Transitions Monotonic

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py src/bot/tests/test_client_lead_delivery.py src/bot/utils.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/004-claim-client-lead-deliveries-before-dispatch.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

WhatsApp send attempts and webhook callbacks can arrive out of order. A row that is already `sent` or `delivered` should not move back to `pending` or `failed` because a late failure report from an earlier attempt arrived after success.

## Current State

- Status update overwrites the row unconditionally:

```python
src/backend/database.py:2898
row.delivery_status = cls.normalize_status(delivery_status)
```

- Webhook callback by external id also overwrites unconditionally:

```python
src/backend/database.py:2942
row.delivery_status = cls.normalize_status(delivery_status)
```

- Failure handling can move any row back to pending or failed:

```python
src/backend/database.py:2974
if attempts < max_attempts:
    row.delivery_status = ClientLeadDeliveryStatus.PENDING
else:
    row.delivery_status = ClientLeadDeliveryStatus.FAILED
```

- Existing tests cover failure and manual retry, but not late failure after success:

```python
src/backend/tests/test_client_lead_delivery.py:722
def test_client_lead_failure_and_retry(...)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Bot Delivery tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/database.py`
- `src/backend/tests/test_client_lead_delivery.py`
- `src/bot/tests/test_client_lead_delivery.py` if bot assumptions need coverage.

**Out of scope**:
- Changing user-facing status labels.
- Changing webhook inbox replay semantics.
- Manual operator retry for failed rows, except preserving its existing behavior.

## Git Workflow

- Branch: `codex/monotonic-delivery-status`
- Commit message: `Make Delivery status transitions monotonic`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define allowed transitions in one place

Add a small helper on `ClientLeadDelivery`, for example:

```python
should_apply_delivery_status(current, incoming, *, manual_retry=False) -> bool
```

Recommended rules:

- `pending -> sent`, `pending -> failed`, `pending -> blocked`, `pending -> skipped` are allowed.
- `sent -> delivered` is allowed.
- `delivered -> sent`, `delivered -> pending`, `delivered -> failed` are ignored.
- `sent -> pending` and `sent -> failed` are ignored for automatic failure paths.
- Manual retry can still move `failed` or `blocked` back to `pending`.

Keep the rules explicit; do not encode them as clever numeric ranks unless the enum semantics are obvious.

### Step 2: Apply the rules to automatic updates

Use the helper in:

- `update_delivery_status()`,
- `update_delivery_status_by_external_id()`,
- `record_delivery_failure()`.

For ignored transitions, preserve useful error diagnostics only if they do not change the final success status. Do not clear `sent_at`, `delivered_at`, or `sent_text` when ignoring a stale failure.

### Step 3: Preserve manual retry

Keep `requeue_failed()` behavior for operator retry from `failed` and `blocked`.

Do not allow manual retry from `sent` or `delivered` unless the product owner explicitly asks for resend behavior.

### Step 4: Add regression tests

Add tests for:

- mark sent, then record failure; status remains `sent`,
- mark delivered by external id, then record failure; status remains `delivered`,
- mark delivered, then callback `sent`; status remains `delivered`,
- failed row can still be retried by the existing retry endpoint.

## Test Plan

- Delivery status transition regression tests.
- Existing failure/retry test.
- Bot delivery test that sends a Client Lead notification.

## Done Criteria

- [ ] Late failure cannot regress `sent` or `delivered`.
- [ ] Late `sent` callback cannot regress `delivered`.
- [ ] Manual retry still works for failed or blocked rows.
- [ ] Delivery tests exit 0.
- [ ] Bot Delivery tests exit 0.

## STOP Conditions

- Product owner wants successful rows to be resendable through automatic failure callbacks.
- External provider semantics require a status not represented by the current enum.

## Maintenance Notes

Plan 004 should still claim rows before dispatch. This plan handles provider ordering after dispatch.
