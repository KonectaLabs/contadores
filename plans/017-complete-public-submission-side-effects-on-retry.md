# Plan 017: Complete Public Submission Side Effects On Retry

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/campaigns.py src/backend/database.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/016-make-public-submission-deduplication-atomic.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Public submission persistence and side effects happen in separate steps. If the server stores the submission and then fails before queueing Delivery or recording Meta status, a browser retry with the same idempotency key returns early as a duplicate. That can leave a valid public lead with no WhatsApp Delivery row and incomplete Meta/event state.

## Current State

- Duplicate requests return before side effects:

```python
src/backend/endpoints/campaigns.py:2233
duplicate = LeadCaptureSubmission.get_by_idempotency_key(scoped_idempotency_key)
if duplicate is not None:
    return _public_submission_receipt(campaign=campaign, submission=duplicate, duplicate=True)
```

- Delivery queueing happens only after a new submission is created:

```python
src/backend/endpoints/campaigns.py:2265
deliveries = _queue_deliveries_for_submission(campaign=campaign, submission=submission)
delivery = deliveries[0] if deliveries else None
if delivery is not None:
    submission = LeadCaptureSubmission.update_delivery_and_meta(
        submission.id,
        client_lead_delivery_id=delivery.id,
    ) or submission
```

- Meta tracking and event rows happen after queueing:

```python
src/backend/endpoints/campaigns.py:2272
submission = _track_meta_event(request=request, campaign=campaign, submission=submission)
...
PlatformEvent.add(... idempotency_key=f"lead-capture-submission:{submission.id}")
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/campaigns.py`
- `src/backend/tests/test_campaigns.py`
- `src/backend/database.py` only if a small helper is needed.

**Out of scope**:
- Changing public receipt schema.
- Retrying live Meta CAPI repeatedly without idempotency safeguards.
- Changing Delivery dispatch worker behavior.

## Git Workflow

- Branch: `codex/reconcile-public-submission-retry`
- Commit message: `Complete public submission side effects on retry`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extract a reconciliation helper

Create a small helper in `campaigns.py`, for example:

```python
def _ensure_submission_side_effects(request, campaign, submission) -> tuple[LeadCaptureSubmission, list[ClientLeadDelivery]]:
```

It should:

- inspect existing deliveries for `campaign-submission:{submission.id}`,
- create missing Delivery rows through `_queue_deliveries_for_submission()`,
- attach `client_lead_delivery_id` when missing,
- fill `meta_event_status` when it is empty or `pending`,
- rely on existing idempotency keys for `PlatformEvent.add()`.

Keep each branch explicit. Avoid a generic side-effect framework.

### Step 2: Use the helper for duplicates and new submissions

In the duplicate branch, call the reconciliation helper before returning the duplicate receipt.

For a new submission, replace the inline queue/track/event sequence with the same helper plus the existing `PlatformEvent.add()` call if it is not already covered.

### Step 3: Add regression tests

Add tests that simulate a partially completed submission:

- create a campaign,
- insert a `LeadCaptureSubmission` directly with the same scoped idempotency key and `meta_event_status="pending"`,
- do not create Delivery rows,
- POST the public submission with the same idempotency key,
- assert duplicate is true,
- assert Delivery rows now exist,
- assert the submission has a delivery id or delivery statuses through the submissions endpoint.

If Meta events are disabled in the test, assert `meta_event_status == "disabled"` after reconciliation.

## Test Plan

- New duplicate-retry reconciliation test.
- Existing public submission idempotency and phone dedupe test.
- Campaign tests.
- Delivery tests.

## Done Criteria

- [ ] Duplicate/idempotent retry completes missing Delivery rows.
- [ ] Duplicate/idempotent retry completes missing Meta status without duplicating provider events.
- [ ] Public receipt shape stays unchanged.
- [ ] Campaign tests exit 0.
- [ ] Delivery tests exit 0.

## STOP Conditions

- Reconciliation would resend a live Meta event without a stable provider idempotency key.
- Existing Delivery row-key conventions cannot distinguish one submission's rows.

## Maintenance Notes

This plan makes retries self-healing. It should not loosen spam/honeypot behavior or backend validation.
