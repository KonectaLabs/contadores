# Plan 162: Track AgentMail Alert Delivery Per Recipient

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/tests/test_contadores_flow.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/053-claim-agentmail-alerts-before-send.md, plans/161-enforce-alert-email-recipient-policy.md
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AGENTMAIL-05

## Why This Matters

When an alert has multiple recipients, a failure for one recipient is only stored in the in-memory outcome. If at least one recipient succeeds, the alert is marked sent/notified and the failed recipient is not retried.

The alert delivery contract should be per-recipient so partial failures are visible and retried instead of becoming silent misses.

## Current State

- Bot records failed recipients locally:

```python
src/bot/utils.py:1073
failed_recipients: list[str] = []
```

- A first successful receipt is enough to mark the alert sent:

```python
src/bot/utils.py:1097
if runtime_alert and item.runtime_alert_id is not None:
    await mark_backend_contadores_runtime_alert_sent(
```

- Outcome includes failed recipients but no durable retry state:

```python
src/bot/utils.py:1108
"failed_recipients": failed_recipients,
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Alert delivery scan | `rg -n "failed_recipients|first_receipt|mark.*alert.*sent|alert_email|email_message_id|recipient" src/backend src/bot src/backend/tests src/bot/tests` | per-recipient state is durable |
| Backend alert tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "alert or runtime_alert" -q` | exit 0 |
| Bot alert tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k "alert" -q` | exit 0 |

## Scope

**In scope**:
- Add durable per-recipient alert delivery state.
- Retry failed recipients with bounded backoff.
- Define when an alert is complete: all required recipients delivered, or policy-approved quorum.
- Keep item-level claim/idempotency behavior from plan 053.
- Add tests for one success/one failure, retry success, and all-failed behavior.

**Out of scope**:
- Recipient authorization policy; plan 161 owns allowed recipients.
- AgentMail reply authorization; plan 160 owns inbound sender checks.
- Reply body parsing; plan 163 owns operator reply content.
- Replacing AgentMail.

## Git Workflow

- Branch: `codex/agentmail-alert-recipient-state`
- Commit message: `Track AgentMail alert delivery per recipient`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose state model

Prefer a small table keyed by alert kind/id and normalized recipient. If schema changes are needed, follow plan 020.

State should include:

- recipient,
- status,
- last attempt time,
- next attempt time,
- last error,
- provider message/thread ids.

### Step 2: Update pending selection

Pending alerts should include only recipients due for send. Avoid resending to recipients already delivered.

### Step 3: Mark recipient outcomes

After each send attempt, persist success or failure for that recipient.

Only mark the parent alert as complete when the recipient policy is satisfied.

### Step 4: Add tests

Cover:

- two recipients where one fails stays partially pending,
- retry sends only the failed recipient,
- second success marks parent complete,
- all failed does not mark parent sent,
- stale claims from plan 053 still recover.

## Test Plan

- Backend alert tests pass.
- Bot alert tests pass.
- Backend import smoke passes.
- No live AgentMail send is performed.

## Done Criteria

- [ ] Partial AgentMail recipient failures are durable.
- [ ] Failed recipients retry without resending successful recipients.
- [ ] Parent alert completion reflects recipient policy.
- [ ] Tests cover partial success and retry.

## STOP Conditions

- Schema changes are needed but plan 020 has not landed.
- Operators decide one successful recipient is enough and failed recipients should not retry.
- AgentMail provider cannot return stable enough recipient/message status.

## Maintenance Notes

Multi-recipient email is a small fan-out queue. Track each recipient like a delivery target, not as a side note.
