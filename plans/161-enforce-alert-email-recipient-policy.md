# Plan 161: Enforce Alert Email Recipient Policy

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/funnel_config.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/backend/tests/test_funnels.py src/bot/utils.py src/bot/tests/test_contadores_flow.py .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AGENTMAIL-04

## Why This Matters

Alert emails can contain lead names, WhatsApp numbers, email addresses, latest inbound text, and recent conversation transcripts. Current alert recipient normalization checks email syntax only. A typo or malicious config write can send sensitive CRM alerts to any valid-looking address.

Alert recipients should be constrained by an explicit allowlist of addresses or domains, enforced both when configuration is saved and immediately before send.

## Current State

- Runtime config stores syntax-normalized alert emails:

```python
src/backend/database.py:1018
alert_emails: str | None = Field(default=None)
```

- Funnel config also normalizes alert emails:

```python
src/backend/funnel_config.py:170
alert_emails: list[str] = Field(default_factory=list)
```

- Pending alert payloads carry configured alert recipients:

```python
src/backend/endpoints/contadores.py:4618
alert_emails: list[str] = Field(default_factory=list)
```

- Bot sends sensitive alert email bodies to those recipients:

```python
src/bot/utils.py:959
recipients = [email for email in item.alert_emails if email]
```

```python
src/bot/utils.py:993
"Conversacion reciente:",
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Alert recipient scan | `rg -n "alert_emails|ALERT.*EMAIL|recipient|send_contadores_pending_alerts|normalize_email" src/backend src/bot .env.example README.md src/backend/tests src/bot/tests` | alert recipient policy is enforced |
| Backend alert tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py src/backend/tests/test_funnels.py -k "alert_emails or runtime_alert or funnel" -q` | exit 0 |
| Bot alert tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k "alert" -q` | exit 0 |

## Scope

**In scope**:
- Add a shared alert-recipient policy with explicit allowed addresses and/or domains.
- Enforce policy in runtime config writes and funnel config writes.
- Enforce policy again in `send_contadores_pending_alerts()` before provider send.
- Make disallowed recipients fail closed with clear operator errors.
- Document env/config policy in `.env.example` and README.
- Add tests for config endpoint, funnel upsert, and bot send defense-in-depth.

**Out of scope**:
- General email validation beyond alert recipients.
- AgentMail reply authorization; plan 160 owns inbound reply sender checks.
- Partial recipient retries; plan 162 owns per-recipient delivery state.
- Redacting alert body content; plans 123 and 153 own redaction boundaries.

## Git Workflow

- Branch: `codex/enforce-alert-email-recipient-policy`
- Commit message: `Enforce alert email recipient policy`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define policy configuration

Add readable config such as:

- `CONTADORES_ALERT_ALLOWED_EMAILS`,
- `CONTADORES_ALERT_ALLOWED_DOMAINS`.

Default should be fail closed in production when alert emails are configured but no policy exists. Allow local/test bypass only if the existing test setup needs it and the name is explicit.

### Step 2: Centralize validation

Create a helper that:

- normalizes email addresses,
- checks exact allowed addresses,
- checks allowed domains only when configured,
- returns a clear reason for rejection.

### Step 3: Enforce on config writes

Apply validation when:

- updating Contadores runtime config,
- writing funnel configs,
- any script/helper mutates alert emails.

Do not silently drop disallowed emails.

### Step 4: Enforce before send

Before AgentMail send, filter through the same policy and fail closed for disallowed recipients. This protects old stored config and direct data edits.

### Step 5: Add tests and docs

Tests should cover allowed exact address, allowed domain, disallowed address, and stale disallowed config blocked at send time.

## Test Plan

- Backend alert/funnel tests pass.
- Bot alert tests pass.
- Backend import smoke passes.
- No live AgentMail send is performed.

## Done Criteria

- [ ] Alert emails can only target approved recipients.
- [ ] Runtime and funnel config writes reject disallowed recipients.
- [ ] Bot send path blocks stale disallowed recipients.
- [ ] Docs describe the policy and fail-closed behavior.

## STOP Conditions

- Operators need to alert arbitrary client-provided emails as a product feature.
- There is no approved recipient/domain list available for production.
- Existing production config contains recipients that need owner review before enforcement.

## Maintenance Notes

Email syntax is not authorization. Treat alert recipients as a data-egress policy.
