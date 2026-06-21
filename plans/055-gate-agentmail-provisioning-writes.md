# Plan 055: Gate AgentMail Provisioning Writes

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/main.py src/bot/providers.py src/bot/tests/test_agentmail_provider.py src/bot/tests/test_contadores_flow.py README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-05

## Why This Matters

Setting `AGENTMAIL_API_KEY` lets bot startup create/update AgentMail webhooks and update inbox display names. That is an external live mutation at process startup with no explicit provisioning/live-write gate. Startup should be able to run read-only unless an operator has opted into AgentMail provisioning writes.

## Current State

- Bot initializes AgentMail on startup:

```python
src/bot/main.py:524
email_provider = AgentMailProvider()
```

- Initialization restores webhook coverage:

```python
src/bot/providers.py:514
inbox_ids = set(await self._list_inbox_ids())
if inbox_ids:
    await self.ensure_webhook(inbox_ids)
```

- Webhook create/update happens during ensure:

```python
src/bot/providers.py:649
webhook = await self._client.webhooks.create(
```

```python
src/bot/providers.py:659
await self._client.webhooks.update(
```

- Inbox display names can be updated:

```python
src/bot/providers.py:947
if current_display_name != desired_display_name:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| AgentMail provider tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_agentmail_provider.py -q` | exit 0 |
| Bot flow tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -q` | exit 0 |
| Bot import smoke | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run python -c "import main; print('bot-import-ok')"` | prints `bot-import-ok` |

## Scope

**In scope**:
- Add explicit env gates for AgentMail provisioning writes.
- Let read/send/poll behavior remain available when safe.
- Document bootstrap sequence.

**Out of scope**:
- Removing AgentMail.
- Changing webhook signature validation.
- Changing alert email content.

## Git Workflow

- Branch: `codex/gate-agentmail-provisioning-writes`
- Commit message: `Gate AgentMail provisioning writes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add explicit gates

Add env vars such as:

- `AGENTMAIL_PROVISIONING_WRITES_ENABLED=false`,
- `AGENTMAIL_SYNC_INBOX_DISPLAY_NAMES=false`.

Default them to false.

### Step 2: Split read-only startup from provisioning

AgentMail initialization should be able to:

- construct the client,
- list existing inboxes if needed,
- send alerts using configured existing inboxes,
- verify incoming webhooks with configured secret,
- avoid creating/updating webhooks or inbox display names unless the gate is enabled.

### Step 3: Add provisioning command or mode

Document how an operator intentionally runs provisioning:

- set the gate,
- start bot once or run a dedicated command,
- confirm webhook and inbox state,
- turn the gate off if ongoing mutation is not needed.

### Step 4: Add tests

Cover:

- default startup does not create/update webhooks,
- default startup does not update display names,
- enabling gate permits webhook create/update,
- missing webhook secret still fails closed for inbound webhook verification.

## Test Plan

- Run AgentMail provider tests.
- Run bot flow tests.
- Run bot import smoke.

## Done Criteria

- [ ] AgentMail startup does not mutate external state by default.
- [ ] Provisioning writes require an explicit env gate.
- [ ] Existing alert sending still works with preconfigured inboxes.
- [ ] README and `.env.example` document the gate.

## STOP Conditions

- AgentMail cannot send alerts without startup webhook mutation in current setup.
- Operator wants managed webhook reconciliation on every startup.
- Tests need real AgentMail credentials.

## Maintenance Notes

Separate credentials-present from writes-approved. API keys alone should not imply provisioning mutation.
