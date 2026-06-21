# Plan 116: Durably Buffer WhatsApp Delivery Status Callbacks

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/main.py src/bot/utils.py src/bot/webhook_inbox.py src/bot/tests/test_contadores_flow.py src/bot/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/052-make-contadores-message-status-transitions-monotonic.md, plans/085-enforce-contadores-whatsapp-external-id-uniqueness.md
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WORKER-01

## Why This Matters

WhatsApp delivery-status callbacks are currently processed best-effort. If the backend is unavailable, or if a provider callback arrives before the outbound external id is persisted, the status can be logged and lost.

Status callbacks should be durably buffered and replayed until they are applied or intentionally dead-lettered.

## Current State

- Status callback failures are only logged:

```python
src/bot/main.py:544
async def on_whatsapp_status(event: WhatsAppMessageStatusEvent) -> None:
```

```python
src/bot/main.py:550
logger.exception("Failed to process a WhatsApp delivery update.")
```

- Contadores outbound external ids are persisted after provider send returns:

```python
src/bot/utils.py:576
await mark_backend_contadores_message_sent(
```

- Unknown external ids are ignored:

```python
src/bot/utils.py:841
"reason": "external_id_not_found",
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Status callback scan | `rg -n "handle_whatsapp_status|WhatsAppMessageStatusEvent|external_id_not_found|webhook_inbox|delivery status" src/bot src/bot/tests` | callbacks persist/retry before they can be lost |
| Bot delivery tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py tests/test_client_lead_delivery.py -k "status or delivery" -q` | exit 0 |

## Scope

**In scope**:
- Add durable storage for WhatsApp delivery-status callback payloads.
- Retry backend status updates when the backend is down.
- Treat early `external_id_not_found` as retryable for a bounded window.
- Add dead-letter diagnostics for callbacks that never match a known outbound message.

**Out of scope**:
- Status ordering rules; plan 052 covers monotonic transitions.
- External-id uniqueness; plan 085 covers database uniqueness.
- Inbound message event retry policy; plan 117 covers that.

## Git Workflow

- Branch: `codex/buffer-whatsapp-status-callbacks`
- Commit message: `Buffer WhatsApp status callbacks`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a status callback store

Persist provider external id, provider status, error fields, received timestamp, attempts, and last error.

### Step 2: Save before processing

In `on_whatsapp_status`, write the callback before calling `handle_whatsapp_status`. Mark delivered only after the backend confirms the update was applied.

### Step 3: Replay retryable statuses

Add a bounded replay pass beside the inbound replay loop. Retry `external_id_not_found` briefly because send-accepted persistence can race the provider callback.

### Step 4: Dead-letter intentionally

After max age or attempts, mark the status callback dead-lettered with a concise reason.

### Step 5: Add tests

Cover backend-down replay, early unknown external id that later matches, permanent unknown external id, and provider failure payload replay.

## Test Plan

- Bot delivery/status tests pass.
- Manual log scan shows no unbounded payload dumps.
- Shared inbox tests still pass if shared code is touched.

## Done Criteria

- [ ] Status callbacks are durably saved before backend processing.
- [ ] Retryable failures replay automatically.
- [ ] Early external-id races no longer lose provider state.
- [ ] Permanent unknown callbacks become visible dead-letter diagnostics.

## STOP Conditions

- Provider webhook delivery lacks any stable event identity and local buffering would duplicate updates.
- Existing data root cannot safely store another small SQLite/table file.
- Plan 052 or 085 changes the delivery-status API contract while this plan is being implemented.

## Maintenance Notes

Treat provider callbacks like inbound messages: acknowledge only after there is a durable path to finish processing them.
