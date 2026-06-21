# Plan 106: Confirm Delivery Notification Retry Requeue

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: plans/018-make-delivery-status-transitions-monotonic.md
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DELIVERY-03

## Why This Matters

The Delivery Retry button POSTs a failed/blocked notification back into pending state. That makes the notification dispatchable again. Retrying is useful, but it can resend client lead alerts and should be an intentional operator action, especially after failures caused by wrong recipients or bad payloads.

## Current State

- The frontend retry handler is a direct POST:

```tsx
src/frontend/src/App.tsx:1176
async function retryClientLeadNotification(lead: ClientLead) {
```

```tsx
src/frontend/src/App.tsx:1182
await apiFetch(`/api/client-leads/${encodeURIComponent(lead.id)}/retry`, { method: "POST" });
```

- The Retry button calls it with one click:

```tsx
src/frontend/src/App.tsx:6045
{retryable ? (
```

```tsx
src/frontend/src/App.tsx:6050
onClick={() => onRetryLead(lead)}
```

- Backend retry accepts failed/blocked rows and requeues them:

```python
src/backend/endpoints/client_leads.py:1509
@client_leads_actions_router.post("/{delivery_id}/retry", response_model=ClientLeadDeliveryResponse)
```

```python
src/backend/endpoints/client_leads.py:1513
if item.delivery_status not in {ClientLeadDeliveryStatus.FAILED, ClientLeadDeliveryStatus.BLOCKED}:
```

```python
src/backend/endpoints/client_leads.py:1520
updated = ClientLeadDelivery.requeue_failed(item.id)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Retry UI scan | `rg -n "retryClientLeadNotification|onRetryLead|Retry|Confirm" src/frontend/src/App.tsx src/frontend/src/styles.css` | retry requeue requires confirmation |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Delivery retry tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -k retry -q` | exit 0 |

## Scope

**In scope**:
- Add confirmation before retrying a failed/blocked Delivery notification.
- Show enough context in the confirmation: source label, lead name/phone, recipient, and current failure state when available.
- Preserve current retry endpoint behavior.
- Keep retry disabled while another retry is in flight.

**Out of scope**:
- Status transition rules; plan 018 covers monotonic Delivery transitions.
- Unique external ids; plan 019 covers Delivery provider ids.
- Recipient identity safety; plans 066 and 105 cover config/routing writes.
- Requeue operator scripts; plan 078 covers mutation script live flags.

## Git Workflow

- Branch: `codex/confirm-delivery-retry`
- Commit message: `Confirm Delivery notification retry`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add retry confirmation state

Capture the target lead row before calling `retryClientLeadNotification`.

Use an existing confirmation pattern if the app has one after plan 070; otherwise add a small local confirmation dialog/panel.

### Step 2: Show resend context

Confirmation should identify:

- lead name or phone,
- source/recipient if present in the loaded UI state,
- current status and last error when available.

### Step 3: Execute the existing retry handler after confirmation

Keep `retryClientLeadNotification` as the mutation function. The button should open confirmation; confirmation should call the handler.

### Step 4: Verify

Run frontend build and focused Delivery retry tests.

## Test Plan

- Frontend build/typecheck.
- Delivery retry backend tests.
- Manual browser check that Retry opens confirmation and requeues only after confirm.

## Done Criteria

- [ ] Retry is not a one-click requeue.
- [ ] Confirmation makes resend impact visible.
- [ ] Existing retry endpoint and refresh behavior remain intact.

## STOP Conditions

- Operators explicitly require one-click retry for high-volume support.
- Existing confirmation infrastructure is not available and a new modal would collide with plan 070.
- Backend retry semantics change before this plan lands.

## Maintenance Notes

Retry is operationally closer to resend than refresh. Treat it like a live dispatch control.
