# Plan 054: Dedupe AgentMail Webhook Replies

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/main.py src/bot/providers.py src/bot/utils.py src/bot/tests/test_contadores_flow.py src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/053-claim-agentmail-alerts-before-send.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-04

## Why This Matters

AgentMail webhooks can be retried or delivered concurrently. The backend resolves operator replies by thread, not by inbound `message_id`, so duplicate webhooks can queue the same operator WhatsApp reply twice before the runtime alert is marked resolved.

## Current State

- Webhook is verified then converted to an event:

```python
src/bot/main.py:481
payload = email_provider.verify_webhook_payload(
```

- Event includes the AgentMail message id:

```python
src/bot/providers.py:755
def build_inbound_event(self, payload: dict[str, Any]) -> EmailInboundEvent | None:
```

- Bot forwards `message_id` to backend:

```python
src/bot/utils.py:918
response = await client.post(
```

- Backend resolves by thread:

```python
src/backend/endpoints/contadores.py:6136
alert = ContadoresRuntimeAlert.get_unresolved_by_email_thread(
```

- Backend queues WhatsApp reply before resolving alert:

```python
src/backend/endpoints/contadores.py:6177
queued_rows = queue_ai_bot_message(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runtime alert tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "email_reply or runtime_alert" -q` | exit 0 |
| Bot AgentMail tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k agentmail -q` | exit 0 |

## Scope

**In scope**:
- Persist inbound AgentMail reply idempotency by `message_id` and/or provider event id.
- Ensure duplicate/replayed webhook returns already-processed result without queuing another WhatsApp message.
- Add tests for concurrent or replayed webhooks.

**Out of scope**:
- Changing AgentMail signature verification.
- Changing email parsing rules.
- Changing learned-answer behavior except duplicate suppression.

## Git Workflow

- Branch: `codex/dedupe-agentmail-webhook-replies`
- Commit message: `Dedupe AgentMail webhook replies`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add reply idempotency key

Use the inbound `message_id` when present. If AgentMail exposes a separate webhook event id, support that too.

Store the processed id on the runtime alert, a new small table, or `PlatformEvent` with a unique idempotency key. Follow plan 020 if schema changes are needed.

### Step 2: Check idempotency before queueing

At the backend endpoint, before `queue_ai_bot_message()`, check whether the inbound reply id was already processed.

If yes, return a duplicate response with the previous queued ids if available, or a safe ignored duplicate status.

### Step 3: Mark idempotency atomically with queueing

Persist the idempotency marker and queued-message reference in the same transaction when possible.

Avoid a window where the WhatsApp reply queues but duplicate state is not written.

### Step 4: Add tests

Cover:

- first webhook queues one WhatsApp reply,
- replay with same `message_id` queues none,
- concurrent duplicate cannot queue twice,
- missing `message_id` falls back to a conservative thread/text/time key or returns a clear unsupported duplicate policy.

## Test Plan

- Run runtime alert tests.
- Run bot AgentMail tests.
- Run backend import smoke.

## Done Criteria

- [ ] Duplicate AgentMail reply webhooks do not queue duplicate WhatsApp messages.
- [ ] Tests cover replay and concurrency.
- [ ] Response shape clearly identifies duplicates.
- [ ] Missing message id behavior is explicit.

## STOP Conditions

- AgentMail does not provide a stable message/event id in real webhook payloads.
- Schema changes are needed but plan 020 has not landed.
- Existing alert resolution code cannot be made atomic without a broader refactor.

## Maintenance Notes

Email webhook retry behavior should be idempotent at the backend boundary, not only in bot memory.
