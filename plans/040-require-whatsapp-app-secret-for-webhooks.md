# Plan 040: Require WhatsApp App Secret For Webhooks

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/providers.py src/bot/tests/test_whatsapp_inbound_provider.py README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PUBLIC-04

## Why This Matters

WhatsApp inbound and status webhooks are public. The provider passes `validate_updates=bool(self.app_secret)` to PyWA, so webhook POST signature validation is disabled when `WA_APP_SECRET` is missing. The runtime still initializes when `WA_PHONE_ID`, `WA_ACCESS_TOKEN`, and `WA_VERIFY_TOKEN` are present, which can make a production webhook endpoint accept unsigned updates.

## Current State

- `WA_APP_SECRET` is optional in `.env.example`:

```text
.env.example:62
WA_APP_SECRET=
```

- The provider only requires phone id and access token as minimum credentials:

```python
src/bot/providers.py:1160
def _has_credentials(self) -> bool:
    """Return True when minimum WhatsApp credentials are present."""
    return bool(self.phone_id and self.access_token)
```

- PyWA validation is conditional:

```python
src/bot/providers.py:1135
kwargs: dict[str, Any] = {
    "phone_id": self.phone_id,
    "token": self.access_token,
    "session": self._session,
    "server": app,
    "webhook_endpoint": self.webhook_endpoint,
    "verify_token": self.verify_token,
    "app_secret": self.app_secret or None,
    "validate_updates": bool(self.app_secret),
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| WhatsApp provider tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_whatsapp_inbound_provider.py -q` | exit 0 |
| Bot tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -q` | exit 0 |
| Bot import smoke | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run python -c "import main; print('bot-import-ok')"` | prints `bot-import-ok` |

## Scope

**In scope**:
- `src/bot/providers.py`
- `src/bot/tests/test_whatsapp_inbound_provider.py`
- `.env.example`
- README webhook configuration notes.

**Out of scope**:
- Changing WhatsApp send payloads.
- Changing Meta lead ads webhook handling in the backend.
- Changing PyWA internals.
- Adding a temporary unsigned-production bypass.

## Git Workflow

- Branch: `codex/require-whatsapp-app-secret`
- Commit message: `Require WhatsApp app secret for webhooks`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Fail closed for public WhatsApp webhooks

When WhatsApp credentials are otherwise present but `WA_APP_SECRET` is missing, do not initialize the PyWA webhook client for production traffic.

Preferred behavior:

- log a clear error that `WA_APP_SECRET` is required for webhook validation,
- leave `self._wa` unset so `configured` is false,
- avoid registering inbound/status handlers with `validate_updates=false`.

Do not silently downgrade to unsigned webhook handling.

### Step 2: Keep validation always enabled when configured

When `WA_APP_SECRET` is present, pass:

```python
"app_secret": self.app_secret,
"validate_updates": True,
```

Avoid deriving `validate_updates` from a truthiness expression inside the kwargs after Step 1. By the time `_build_client()` runs, validation should be guaranteed.

### Step 3: Add tests

Add tests that cover:

- missing `WA_APP_SECRET` prevents webhook handler registration,
- missing `WA_APP_SECRET` leaves `provider.configured` false,
- configured `WA_APP_SECRET` still passes `app_secret` and `validate_updates=True` into PyWA,
- existing missing callback behavior remains unchanged if callback URL is intentionally absent.

Use existing test fakes. Do not call Meta.

### Step 4: Update env and README

Update `.env.example` to mark `WA_APP_SECRET` as required when WhatsApp webhooks are exposed.

Update README near the WhatsApp/webhook setup section:

- `WA_VERIFY_TOKEN` proves the setup challenge,
- `WA_APP_SECRET` validates webhook POST updates,
- production should not run unsigned WhatsApp webhooks.

## Test Plan

- Run the WhatsApp provider targeted tests.
- Run all bot tests.
- Run bot import smoke.
- Inspect startup logs and confirm missing `WA_APP_SECRET` is a hard configuration error for webhook handling.

## Done Criteria

- [ ] WhatsApp webhooks cannot initialize with unsigned POST validation.
- [ ] `validate_updates` is always true when PyWA is initialized.
- [ ] Tests cover missing and present `WA_APP_SECRET`.
- [ ] `.env.example` and README document the requirement.

## STOP Conditions

- Current production lacks `WA_APP_SECRET` and cannot provide it before deploy.
- PyWA requires a different secret field or validation configuration than the current code suggests.
- The change would disable outbound sends in a deployment where webhooks are intentionally not exposed.

## Maintenance Notes

`WA_VERIFY_TOKEN` is not a substitute for POST signature validation. Treat challenge verification and update validation as separate requirements.
