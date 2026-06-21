# Plan 025: Audit And Sync Env Contracts

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- .env.example README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md src/backend/auth.py src/bot/providers.py src/scripts/whatsapp_templates.py scripts/sync_contadores_crm_runner_status.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/003-default-auth-cookies-secure.md
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Contadores deploys from `.env` through Docker Compose. If `.env.example` names stale keys or omits active runtime knobs, server setup and future rollouts can silently use defaults that do not match operator expectations.

## Current State

- `.env.example` documents an auth path key that the loader does not read:

```text
.env.example:46
AUTH_TOML_PATH=auth.toml
```

- Auth reads `AUTH_TOML` or `AUTH_USERS_TOML`:

```python
src/backend/auth.py:272
auth_path = Path(
    os.getenv("AUTH_TOML", os.getenv("AUTH_USERS_TOML", str(DEFAULT_AUTH_FILE)))
).expanduser()
```

- Runner status script reads env keys that are not in `.env.example`:

```python
scripts/sync_contadores_crm_runner_status.py:130
parser.add_argument("--url", default=os.getenv("CONTADORES_RUNNER_STATUS_URL", DEFAULT_STATUS_URL))
parser.add_argument("--host", default=os.getenv("CONTADORES_RUNNER_STATUS_HOST", DEFAULT_HOST_HEADER))
```

- WhatsApp tooling and provider read keys absent or inconsistently named in the example:

```python
src/scripts/whatsapp_templates.py:37
business_account_id = business_account_id or os.getenv("WA_BUSINESS_ID")

src/bot/providers.py:1077
os.getenv("WA_WEBHOOK_CHALLENGE_DELAY", "").strip()
src/bot/providers.py:1080
os.getenv("WA_INBOUND_MAX_AGE_SECONDS", "").strip()
src/bot/providers.py:1087
os.getenv("WA_TEMPLATE_SOURCE_URL_FALLBACK", "https://example.com").strip()
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Env grep | `rg -n "os\\.getenv|os\\.environ|envvar=" src scripts` | inspect output |
| Auth tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_auth.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Audit runtime env usage across `src/` and `scripts/`.
- Update `.env.example`.
- Update README and rollout skills when env setup behavior changes.
- Add a lightweight env matrix doc if `.env.example` becomes too dense.

**Out of scope**:
- Changing secret values.
- Reading live 1Password or server `.env`.
- Renaming env vars in code unless the old key is clearly wrong and aliases are preserved.

## Git Workflow

- Branch: `codex/sync-env-contracts`
- Commit message: `Audit and sync env contracts`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Generate a local env inventory

Use `rg` to find env reads:

```bash
rg -n "os\.getenv|os\.environ|envvar=" src scripts
```

Classify keys:

- required server secrets,
- optional runtime tuning,
- legacy aliases,
- local-only/operator script keys.

Do not commit a generated dump unless converted into a maintained doc.

### Step 2: Fix known auth drift

Update `.env.example` to use `AUTH_TOML=auth.toml`.

If backwards compatibility matters, document `AUTH_USERS_TOML` as a legacy alias. Do not keep `AUTH_TOML_PATH` unless code also reads it.

### Step 3: Add missing active keys

At minimum, document:

- `CONTADORES_RUNNER_STATUS_URL`,
- `CONTADORES_RUNNER_STATUS_HOST`,
- `WA_BUSINESS_ID` or reconcile it with `WA_BUSINESS_ACCOUNT_ID`,
- `WA_WEBHOOK_CHALLENGE_DELAY`,
- `WA_INBOUND_MAX_AGE_SECONDS`,
- `WA_TEMPLATE_SOURCE_URL_FALLBACK`,
- `AUTH_COOKIE_SECURE` if plan 003 changes its default.

Group them under clear comments so the example remains skimmable.

### Step 4: Add or update env validation notes

If the repo already has runtime readiness for some env keys, reference that instead of duplicating logic.

For keys not covered by readiness, document how an operator notices a missing value.

### Step 5: Verify

Run auth tests and backend import smoke.

## Test Plan

- Auth tests for env auth path behavior.
- Backend import smoke.
- Manual review that `.env.example` has no known stale key names.

## Done Criteria

- [ ] `.env.example` documents active auth keys.
- [ ] Active script/provider env knobs are represented or intentionally classified as internal.
- [ ] README/rollout skill agree with `.env.example`.
- [ ] No secrets or local values are committed.
- [ ] Auth tests exit 0.

## STOP Conditions

- Server currently depends on `AUTH_TOML_PATH`; add code alias support before removing docs.
- Env inventory reveals conflicting keys where changing docs could break production setup.

## Maintenance Notes

This plan is contract hygiene. Keep it docs-first unless a missing alias is required to avoid breaking the current server.
