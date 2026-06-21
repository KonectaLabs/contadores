# Plan 139: Prune Delivered WhatsApp Inbound Inbox Payloads

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/webhook_inbox.py src/bot/main.py src/bot/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/117-add-whatsapp-inbound-inbox-backoff-and-dead-lettering.md
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: RETENTION-02

## Why This Matters

The durable WhatsApp inbound inbox stores full provider payloads so backend delivery can be retried. After delivery is complete, those payloads continue to contain phone numbers, text, profile names, referral data, and media metadata indefinitely.

Delivered and terminal rows should be pruned or compacted after a documented retention window.

## Current State

- Inbox payloads include personal message data:

```python
src/bot/webhook_inbox.py:92
def payload_for_event(event: WhatsAppInboundEvent) -> dict[str, Any]:
```

- Payload JSON is written to SQLite before backend processing:

```python
src/bot/webhook_inbox.py:125
def save_event(self, event: WhatsAppInboundEvent) -> str:
```

- Rows are only marked delivered:

```python
src/bot/webhook_inbox.py:162
def mark_delivered(self, event_key: str) -> None:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Inbox retention scan | `rg -n "payload_json|mark_delivered|dead|failed|prune|webhook_inbox" src/bot src/bot/tests` | delivered/terminal rows have bounded retention |
| Bot inbox tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -k "webhook_inbox or inbound" -q` | exit 0 |
| Bot syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/bot/webhook_inbox.py src/bot/main.py` | exit 0 |

## Scope

**In scope**:
- Define retention windows for delivered and terminal failed/dead-letter inbox rows.
- Add dry-run/count mode for pruning.
- Run pruning after successful replay or on startup/tick.
- Keep pending/processing rows until retry/dead-letter policy says otherwise.
- Document retention env knobs.

**Out of scope**:
- Retry/backoff/dead-letter semantics; plan 117 owns those.
- Media file retention; plan 098 and plan 138 cover media files.
- Backend DB message retention.

## Git Workflow

- Branch: `codex/prune-whatsapp-inbound-inbox`
- Commit message: `Prune delivered WhatsApp inbound inbox payloads`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add retention configuration

Read env vars such as `WHATSAPP_INBOUND_INBOX_DELIVERED_RETENTION_DAYS` and terminal retention days, with conservative defaults.

### Step 2: Add prune helpers

Add helpers such as:

- `count_prunable(...)`,
- `prune_delivered_before(...)`,
- `prune_terminal_before(...)`.

Keep pending and processing rows untouched.

### Step 3: Wire safe execution

Run pruning after successful replay or bot startup.

Log only counts, not payload content.

### Step 4: Add tests

Cover delivered prune, terminal prune, pending preservation, processing preservation, and dry-run count behavior.

## Test Plan

- Bot inbox tests pass.
- Bot syntax check passes.
- Manual SQLite inspection on a fixture confirms old delivered rows are removed.

## Done Criteria

- [ ] Delivered inbox payload retention is bounded.
- [ ] Terminal failed/dead-letter retention is bounded after plan 117 semantics exist.
- [ ] Pending/processing rows are preserved.
- [ ] Tests cover prune and dry-run behavior.

## STOP Conditions

- Operations require indefinite raw provider payload retention for compliance.
- Plan 117 changes status names in a conflicting way.
- The bot cannot safely prune while another process may be replaying rows.

## Maintenance Notes

Durability is for retry, not permanent storage of raw inbound payloads.
