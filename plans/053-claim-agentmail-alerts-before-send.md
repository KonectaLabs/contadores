# Plan 053: Claim AgentMail Alerts Before Send

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/tests/test_contadores_flow.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/047-add-data-volume-backup-restore-runbook.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-03

## Why This Matters

AgentMail alert emails are selected, sent, then marked. Overlapping loops or a crash after send but before marking can duplicate operator alert emails for the same lead/runtime alert.

## Current State

- Pending lead alerts are listed without a reservation:

```python
src/backend/endpoints/contadores.py:6025
for lead in ContadoresLead.list_needs_human_without_notification(funnel_id=funnel_id, limit=100):
```

- Pending runtime alerts are also listed:

```python
src/backend/endpoints/contadores.py:6049
for alert in ContadoresRuntimeAlert.list_pending(funnel_id=funnel_id, limit=100):
```

- Bot sends emails before mark:

```python
src/bot/utils.py:1074
for recipient in recipients:
    try:
        receipt = await email_provider.send_message(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Contadores alert tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "alert or email_reply or runtime_alert" -q` | exit 0 |
| Bot flow tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -q` | exit 0 |

## Scope

**In scope**:
- Add claim/reservation fields or status for lead alerts and runtime alerts.
- Claim alerts before AgentMail send.
- Release stale claims.
- Add tests for overlapping alert loops.

**Out of scope**:
- Changing alert email content.
- Changing WhatsApp reply handling from alert emails; plan 054 covers reply dedupe.
- Replacing AgentMail.

## Git Workflow

- Branch: `codex/claim-agentmail-alerts-before-send`
- Commit message: `Claim AgentMail alerts before send`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose alert claim model

For `ContadoresLead`, either add fields such as `alert_claimed_at` or reuse a clear alert state. For `ContadoresRuntimeAlert`, add a similar claim timestamp/status if missing.

Follow plan 020 for schema changes.

### Step 2: Replace list-only pending alert endpoint

Add a helper that claims alert candidates before returning them to the bot.

Claim should include:

- alert type,
- funnel,
- claimed timestamp,
- stale timeout.

### Step 3: Mark after send

Existing mark-notified behavior should clear the claim and record `notified_at`.

On send failure, clear the claim or set retry metadata so another loop can retry later.

### Step 4: Add tests

Cover:

- first claim returns alert,
- second immediate claim does not return same alert,
- stale claim recovers,
- successful send marks alert notified,
- failure does not permanently hide alert.

## Test Plan

- Run targeted Contadores alert tests.
- Run bot flow tests.
- Run backend import smoke.

## Done Criteria

- [ ] Overlapping bot loops cannot send duplicate alert emails for the same item.
- [ ] Stale claims recover.
- [ ] Send success/failure update claim state correctly.
- [ ] Tests cover lead alerts and runtime alerts.

## STOP Conditions

- Schema changes are needed but plan 020 has not landed.
- Existing alert rows are already duplicated and need manual cleanup first.
- Operator wants at-least-once duplicate alerts rather than possible delayed retry.

## Maintenance Notes

The alert queue is an outbound queue. Treat it with the same claim-before-send discipline as WhatsApp queues.
