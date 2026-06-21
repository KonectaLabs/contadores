# Plan 117: Add WhatsApp Inbound Inbox Backoff And Dead Lettering

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/webhook_inbox.py src/bot/main.py src/bot/tests/test_contadores_flow.py .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WORKER-02

## Why This Matters

The bot durably stores inbound WhatsApp events, but failed events remain retryable forever. A poison event or persistent backend rejection can replay every worker loop, creating noise and hiding the item that needs attention.

Retry should use backoff, a max-attempt boundary, and a dead-letter state.

## Current State

- Failure increments attempts:

```python
src/bot/webhook_inbox.py:175
attempts = attempts + 1,
```

- Failed rows are always retryable:

```python
src/bot/webhook_inbox.py:192
WHERE status IN ('pending', 'failed')
```

- The worker replays inbound events every loop:

```python
src/bot/main.py:404
for saved_event in whatsapp_inbound_inbox.list_retryable(limit=25):
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Inbound inbox scan | `rg -n "WhatsAppInboundInbox|attempts|failed|dead|backoff|list_retryable|mark_failed" src/bot src/bot/tests .env.example README.md` | retry and dead-letter rules are explicit |
| Inbound tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k "inbound" -q` | exit 0 |

## Scope

**In scope**:
- Add configurable max attempts and backoff timing for inbound inbox replay.
- Add a dead-letter status or equivalent terminal failure state.
- Log concise dead-letter diagnostics.
- Document new env knobs if added.

**Out of scope**:
- Status callback buffering; plan 116 covers provider status callbacks.
- Changing WhatsApp inbound parsing/classification.
- Adding a full UI for dead-letter management.

## Git Workflow

- Branch: `codex/inbound-inbox-backoff-dead-letter`
- Commit message: `Add inbound inbox backoff and dead lettering`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define retry policy

Use readable defaults for max attempts, base retry delay, and max retry delay.

### Step 2: Store next retry timing

Extend inbox state so failed rows are selected only when due.

### Step 3: Add dead-letter transition

When max attempts is reached, mark the row dead-lettered and preserve last error plus timestamps.

### Step 4: Update replay tests

Cover first failure, retry after due time, max attempts, and delivered-row exclusion.

## Test Plan

- Bot inbound tests pass.
- `rg` scan shows no forever-retry query for `failed` rows without due/attempt checks.

## Done Criteria

- [ ] Failed inbound events use bounded retry/backoff.
- [ ] Poison events stop looping forever.
- [ ] Dead-letter diagnostics are visible.
- [ ] Env/docs describe the retry policy if configurable.

## STOP Conditions

- Existing production failed rows need migration and the migration path is unclear.
- Provider webhook acknowledgment semantics require immediate in-process retry.
- A dead-letter state would hide critical inbound messages without inspection.

## Maintenance Notes

Durable inboxes need both replay and a terminal state. Otherwise reliability code becomes permanent noise under bad payloads.
