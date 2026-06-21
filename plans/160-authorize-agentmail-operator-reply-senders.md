# Plan 160: Authorize AgentMail Operator Reply Senders

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/tests/test_contadores_flow.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/161-enforce-alert-email-recipient-policy.md
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AGENTMAIL-03

## Why This Matters

AgentMail operator replies can become WhatsApp messages to leads. The backend currently resolves the target runtime alert by email thread id and does not verify that `from_email` belongs to an authorized operator or original alert recipient.

AgentMail webhook verification proves the email provider delivered the message. It does not prove the sender is allowed to teach the bot or send a WhatsApp reply.

## Current State

- The reply command accepts sender and inbox fields:

```python
src/backend/endpoints/contadores.py:4561
class ContadoresAlertEmailReplyCommand(BaseModel):
    inbox_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    from_email: str
```

- The backend resolves only by unresolved thread id:

```python
src/backend/database.py:5513
def get_unresolved_by_email_thread(cls, *, thread_id: str) -> Optional["ContadoresRuntimeAlert"]:
```

- The handler queues the extracted body after finding the alert:

```python
src/backend/endpoints/contadores.py:6136
alert = ContadoresRuntimeAlert.get_unresolved_by_email_thread(
```

```python
src/backend/endpoints/contadores.py:6177
queued_rows = queue_ai_bot_message(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| AgentMail reply scan | `rg -n "email-reply|from_email|email_inbox_id|email_thread_id|get_unresolved_by_email_thread|extract_operator_whatsapp_reply|alert_emails" src/backend src/bot src/backend/tests src/bot/tests` | sender authorization is explicit |
| Runtime alert tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "email_reply or runtime_alert" -q` | exit 0 |
| Bot AgentMail tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k "agentmail or alert" -q` | exit 0 |

## Scope

**In scope**:
- Normalize and authorize `from_email` before processing a runtime-alert email reply.
- Require the reply `inbox_id` to match the inbox used to send the alert.
- Persist or derive the allowed sender set from the original alert recipients and configured alert policy.
- Reject unauthorized, forwarded, or mismatched-inbox replies without queueing WhatsApp messages.
- Add tests for authorized sender, unauthorized sender, alias behavior, and forwarded-thread mismatch.

**Out of scope**:
- Reply replay/idempotency; plan 054 owns duplicate webhook processing.
- Recipient allowlist definition; plan 161 owns outbound alert recipient policy.
- Per-recipient send state; plan 162 owns partial recipient retries.
- Parsing reply body content; plan 163 owns body extraction rules.

## Git Workflow

- Branch: `codex/authorize-agentmail-reply-senders`
- Commit message: `Authorize AgentMail reply senders`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define sender identity rules

Normalize emails with the repo's existing email normalization helper. Decide whether aliases are exact-address only or domain/alias based through the plan 161 policy.

Default to exact original recipient addresses unless a documented allowlist says otherwise.

### Step 2: Store or recover allowed senders

When marking an alert sent, persist enough metadata to validate replies later:

- alert inbox id/address,
- recipient addresses used,
- optional allowed reply domains if policy allows them.

If schema changes are needed, follow plan 020 migration discipline.

### Step 3: Enforce before extraction and queueing

In `/api/contadores/runtime-alerts/email-reply`, check:

- matching thread id,
- matching inbox id,
- authorized sender,
- unresolved and teachable alert type.

Return ignored/rejected status without calling `queue_ai_bot_message()` for unauthorized senders.

### Step 4: Add tests

Cover:

- original recipient can reply,
- unrelated sender on same thread is rejected,
- wrong inbox id is rejected,
- allowed alias/domain works only if explicitly configured,
- rejected reply does not resolve the alert or queue a message.

## Test Plan

- Runtime alert email-reply tests pass.
- Bot AgentMail tests pass.
- Backend import smoke passes.
- No live AgentMail call is made.

## Done Criteria

- [ ] AgentMail replies are sender-authorized before WhatsApp queueing.
- [ ] Inbox id must match the alert email inbox.
- [ ] Unauthorized replies are ignored or rejected without side effects.
- [ ] Tests cover authorized and unauthorized senders.

## STOP Conditions

- Real AgentMail webhook payloads do not provide reliable `from_email`.
- Current operators use forwarding workflows that cannot preserve sender identity.
- Required schema changes cannot proceed before plan 020.

## Maintenance Notes

Email threads are not access control. Authorize the person replying, not just the thread.
