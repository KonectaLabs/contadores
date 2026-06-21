# Plan 059: Gate WhatsApp Webhook Auto Registration

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/providers.py src/bot/tests/test_whatsapp_inbound_provider.py README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: plans/040-require-whatsapp-app-secret-for-webhooks.md
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-09

## Why This Matters

WhatsApp provider startup passes `callback_url` and callback scope to PyWA when `WA_CALLBACK_URL` is configured. If PyWA registers or updates webhook settings as part of initialization, startup can mutate Meta webhook configuration without a separate bootstrap/live-write opt-in.

## Current State

- Missing callback URL only logs that automatic registration is skipped:

```python
src/bot/providers.py:1098
if not self.callback_url:
    logger.warning("WA_CALLBACK_URL is missing. Automatic webhook registration will be skipped.")
```

- Callback URL is passed into PyWA:

```python
src/bot/providers.py:1146
if self._callback_base_url:
    kwargs.update(
        {
            "callback_url": self._callback_base_url,
            "callback_url_scope": pywa_utils.CallbackURLScope.PHONE,
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| WhatsApp provider tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_whatsapp_inbound_provider.py -q` | exit 0 |
| Bot import smoke | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run python -c "import main; print('bot-import-ok')"` | prints `bot-import-ok` |

## Scope

**In scope**:
- Confirm whether PyWA performs webhook registration/update with `callback_url`.
- Add an explicit env gate for automatic webhook registration if it mutates Meta state.
- Keep webhook handling mounted locally even when registration writes are disabled.

**Out of scope**:
- Changing webhook signature validation; plan 040 covers that.
- Changing callback URL value.
- Replacing PyWA.

## Git Workflow

- Branch: `codex/gate-whatsapp-webhook-registration`
- Commit message: `Gate WhatsApp webhook auto registration`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Confirm PyWA behavior

Inspect PyWA docs or source for the installed version and verify whether passing `callback_url` triggers Meta API registration/update.

If it does not mutate provider state, document that and close the plan without code changes.

### Step 2: Add an explicit gate if needed

If it does mutate state, add an env var such as:

```text
WA_WEBHOOK_AUTO_REGISTER_ENABLED=false
```

Default false. Only pass `callback_url` and `callback_url_scope` to PyWA when the gate is true.

### Step 3: Preserve local route mounting

Make sure the local webhook endpoint still mounts and verifies incoming updates when auto-registration is disabled.

Do not break manual Meta webhook configuration.

### Step 4: Add tests and docs

Tests should assert:

- default startup does not pass callback registration kwargs,
- enabling gate passes callback kwargs,
- webhook endpoint path remains configured,
- missing `WA_APP_SECRET` still fails per plan 040.

README and `.env.example` should distinguish:

- webhook URL to configure manually,
- auto-registration write gate.

## Test Plan

- Run WhatsApp provider tests.
- Run bot import smoke.
- If PyWA source confirms no mutation, record that evidence in README instead of adding a gate.

## Done Criteria

- [ ] Startup webhook registration behavior is confirmed.
- [ ] External webhook registration writes require explicit opt-in if they exist.
- [ ] Local webhook handling still works.
- [ ] README documents manual versus automatic registration.

## STOP Conditions

- PyWA behavior cannot be confirmed from docs/source.
- The current production setup depends on auto-registration at every startup.
- Gating callback kwargs also prevents local route mounting.

## Maintenance Notes

As with AgentMail, credentials and callback URLs should not automatically mean provider configuration writes are approved.
