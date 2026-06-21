# Plan 004: Claim Delivery Notifications Before Dispatch

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py src/bot/utils.py src/bot/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Client Lead Delivery sends WhatsApp alerts to customers when their forms receive leads. The current pending endpoint returns rows without reserving them. Two bot loops, retries, or overlapping workers can read the same pending row and send the same WhatsApp template before either reports success or failure. This is a customer-visible duplicate alert risk.

## Current State

- Pending rows are listed by status only:

```python
src/backend/database.py:2776
def list_pending_notification(cls, *, limit: int = 100) -> list["ClientLeadDelivery"]:
    now = datetime.now(timezone.utc)
    ...
    .where(
        ClientLeadSource.enabled.is_(True),
        cls.delivery_status == ClientLeadDeliveryStatus.PENDING,
        cls.dispatch_after <= now,
    )
```

- The API returns pending notifications without changing state:

```python
src/backend/endpoints/client_leads.py:1526
@client_lead_deliveries_router.get("/pending", response_model=ClientLeadPendingNotificationResponse)
async def list_pending_client_lead_notifications(...):
    for item in ClientLeadDelivery.list_pending_notification(limit=limit):
        ...
        notifications.append(ClientLeadPendingNotification(...))
```

- The bot marks the row only after provider send succeeds:

```python
src/bot/utils.py:1319
for item in pending:
    try:
        receipt = await dispatch_one_client_lead_notification(...)
        await mark_backend_client_lead_notification_sent(...)
```

- Contadores conversation processing already has an explicit claim pattern:

```python
src/backend/database.py:1578
def claim_conversation_processing(...)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Bot Delivery tests | `PYTHONPATH=src/bot PYTHONDONTWRITEBYTECODE=1 uv run --project src/bot pytest -p no:cacheprovider src/bot/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/database.py`
- `src/backend/endpoints/client_leads.py`
- `src/backend/tests/test_client_lead_delivery.py`
- `src/bot/utils.py`
- `src/bot/tests/test_client_lead_delivery.py`
- Keeping GET pending reads diagnostic/read-only and moving worker reservation to an explicit POST claim route.

**Out of scope**:
- Contadores CRM message dispatch claim behavior.
- WhatsApp provider implementation.
- Changing template bodies or recipient selection.
- Adding a new queue service.

## Git Workflow

- Branch: `codex/claim-client-lead-deliveries`
- Commit message: `Claim Delivery notifications before dispatch`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add an in-flight status

In `ClientLeadDeliveryStatus`, add a status such as `DISPATCHING = "dispatching"` or `CLAIMED = "dispatching"` following the enum style in `src/backend/database.py`.

Update serializers and count handling only as needed so this status can round-trip.

**Verify**: backend import smoke prints `backend-import-ok`.

### Step 2: Add an atomic claim helper

Add a `ClientLeadDelivery.claim_pending_notifications(limit: int = 100) -> list[ClientLeadDelivery]` classmethod.

Expected behavior:

- Select eligible pending rows joined to enabled sources, ordered exactly like `list_pending_notification()`.
- In one session, transition selected rows from `pending` to `dispatching`.
- Set `updated_at = now`.
- Expunge and return claimed rows.
- Do not claim blocked, sent, delivered, failed, skipped, or future `dispatch_after` rows.

SQLite does not support every advanced locking primitive. Keep this simple and deterministic for the current stack; if true cross-process atomicity cannot be guaranteed with the existing SQLModel pattern, document that as a STOP condition.

**Verify**: add a direct database-level test first if useful.

### Step 3: Add a POST claim endpoint and keep GET read-only

Do not make `GET /api/client-lead-deliveries/pending` reserve rows. Keep that GET read-only for diagnostics, or remove it from the bot dispatch path if no UI/operator flow needs it.

Add a dedicated claim route such as:

```http
POST /api/client-lead-deliveries/pending/claim
```

The POST claim route should call the claim helper and return the rows reserved for dispatch.

If a row has an invalid recipient phone, move it to blocked as today.

Important: a second POST claim before any `/delivery` acknowledgment should return no notifications for the same row.

**Verify**: add an API test:

1. Create source and sync one valid row.
2. GET `/api/client-lead-deliveries/pending` returns one notification and does not change status.
3. First POST `/api/client-lead-deliveries/pending/claim` returns one notification.
4. Second POST claim returns `[]`.
5. Row status is `dispatching`.

### Step 4: Allow failure retry from dispatching

`record_delivery_failure()` should accept a dispatching row and either move it back to pending with delayed retry or failed when attempts are exhausted, preserving current retry semantics.

`update_delivery_status()` should allow `sent` and `delivered` from dispatching.

If existing methods already do this because they set status unconditionally, add tests rather than extra code.

**Verify**: existing failure/retry tests pass, plus the new claim test.

### Step 5: Update bot contract tests

In `src/bot/tests/test_client_lead_delivery.py`, update the bot to call the POST claim route before dispatch. Prefer no response-shape change: the bot should still receive the same `PendingClientLeadNotification` payload.

**Verify**: bot Delivery tests exit 0.

## Test Plan

- Backend API regression for read-only GET and double POST claim.
- Existing send success/failure retry behavior.
- Bot utils dispatch tests for unchanged payload contract.

## Done Criteria

- [ ] One pending Delivery row cannot be returned by two consecutive POST claim calls before acknowledgment.
- [ ] GET pending reads remain read-only or are no longer used for worker dispatch.
- [ ] Claimed rows still move to sent/delivered/failure through existing provider status endpoints.
- [ ] Failed dispatches still retry or fail according to max attempts.
- [ ] Backend Delivery tests exit 0.
- [ ] Bot Delivery tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- SQLModel/SQLite constraints make the claim non-atomic across the actual bot deployment topology.
- The bot depends on pending reads being idempotent for a documented reason.
- Adding the new status requires a migration broader than this plan's scope.

## Maintenance Notes

Review the deployed bot topology before rollout. If multiple bot processes are possible, this plan is a production safety fix. If only one bot process exists today, it still protects manual overlap and future scaling.
