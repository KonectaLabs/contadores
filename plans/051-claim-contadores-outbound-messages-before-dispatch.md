# Plan 051: Claim Contadores Outbound Messages Before Dispatch

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/tests/test_contadores_flow.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-01

## Why This Matters

Client Lead Delivery has a plan to claim rows before WhatsApp dispatch, but the core Contadores CRM outbound queue has the same shape. Pending messages are listed without reservation, sent by the bot, and only then updated. Overlapping bot loops or retries can send the same outbound WhatsApp message twice.

## Current State

- Pending messages are only listed:

```python
src/backend/database.py:2182
def list_pending_delivery(cls, *, limit: int = 100) -> list["ContadoresMessage"]:
    """List every pending outbound step that is due for dispatch."""
```

- Bot endpoint returns rows for dispatch:

```python
src/backend/endpoints/contadores.py:5351
rows = ContadoresMessage.list_pending_delivery(limit=limit)
```

- Bot sends before status is updated:

```python
src/bot/utils.py:1217
for item in pending:
    try:
        receipt = await dispatch_one_contadores_message(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Contadores tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "pending_delivery or dispatch" -q` | exit 0 |
| Bot flow tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add a claim/reservation step for due `ContadoresMessage` rows before dispatch.
- Preserve retry and failure behavior.
- Add tests for overlapping claims.
- Keep `GET /api/contadores/messages/pending-delivery` read-only for diagnostics and move worker reservation to an explicit POST claim route.

**Out of scope**:
- Client Lead Delivery rows; plan 004 covers that queue.
- Changing WhatsApp provider send payloads.
- Broad queue system replacement.

## Git Workflow

- Branch: `codex/claim-contadores-outbound-before-dispatch`
- Commit message: `Claim Contadores outbound messages before dispatch`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose claim state

Add the smallest clear reservation state for outbound messages. Options:

- add a `dispatch_claimed_at` column,
- add a `sending` delivery status,
- or reuse a status-plus-timestamp pattern if one already exists.

If schema changes are required, follow plan 020 migration discipline.

### Step 2: Add a POST claim endpoint for bot dispatch

Create a database helper that atomically selects due rows and marks them claimed before returning them.

Keep reads bounded by `limit`. Avoid returning rows already claimed inside a short timeout window.

Do not make `GET /api/contadores/messages/pending-delivery` claim rows. Add a dedicated worker route such as:

```http
POST /api/contadores/messages/pending-delivery/claim
```

The bot should use the POST claim route before sending. The GET route should remain read-only diagnostics or be removed from worker flow.

### Step 3: Release or finalize claims

When send succeeds, existing update-to-sent/delivered behavior should clear the claim.

When send fails and the row is requeued, clear the claim and set the next dispatch time. If the bot crashes, a claim timeout should make the row eligible again.

### Step 4: Add race tests

Add tests that call the POST claim route twice and prove the same message is not returned twice before timeout. Also test that GET pending reads do not mutate status.

Also test stale claim recovery.

## Test Plan

- Run targeted Contadores dispatch tests.
- Run bot flow tests.
- Run backend import smoke.

## Done Criteria

- [ ] Bot dispatch cannot retrieve the same due CRM message twice concurrently.
- [ ] GET pending-delivery remains read-only or is no longer used for worker dispatch.
- [ ] Successful send finalizes the message.
- [ ] Failed send requeues or fails according to retry budget.
- [ ] Stale claims recover.

## STOP Conditions

- Schema changes are needed but plan 020 has not landed.
- Current production has multiple bot workers and requires a stronger database lock than SQLite can provide.
- Existing statuses are consumed externally and adding a status would break consumers.

## Maintenance Notes

This is the ContadoresMessage equivalent of plan 004. Keep the two queue patterns consistent where possible.
