# Plan 081: Fail Closed When Auth Is Disabled In Production

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/auth.py src/backend/main.py docker-compose.yml .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: 025
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTH-04

## Why This Matters

`AUTH_DISABLE=true` disables auth globally. That is useful for tests or local development, but in production one stale env var can make operator and mutation endpoints public.

The repo is server-first, so disabled auth needs an explicit local/test-only guard.

## Current State

- Auth disables itself directly from `AUTH_DISABLE`:

```python
src/backend/auth.py:260
def reload_from_env(self) -> None:
```

```python
src/backend/auth.py:262
if _parse_bool_env("AUTH_DISABLE", default=False):
```

- Middleware skips all auth when disabled:

```python
src/backend/main.py:270
if not auth_manager.enabled:
```

```python
src/backend/main.py:271
return await call_next(request)
```

- Compose loads `.env` into the public backend service:

```yaml
docker-compose.yml:22
backend:
```

```yaml
docker-compose.yml:29
env_file: .env
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Auth env scan | `rg -n "AUTH_DISABLE|AUTH_COOKIE_SECURE|AUTH_TOML|APP_ENV|ENVIRONMENT|PUBLIC_HTTPS_HOSTS" src/backend .env.example README.md docker-compose.yml` | production guard is documented |
| Auth tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "auth_disable or auth or login" -q` | exit 0 |
| Startup smoke | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/auth.py src/backend/main.py` | exit 0 |

## Scope

**In scope**:
- Add a fail-closed guard that refuses disabled auth in public/server runtime.
- Provide an explicit local/test override name if tests need disabled auth.
- Update `.env.example` and README to document the safe usage.
- Add tests for allowed local/test disabled auth and rejected production disabled auth.

**Out of scope**:
- Replacing the auth system.
- Cookie security defaults; plan 003 covers secure cookies.
- Full env contract audit; plan 025 covers broader env drift.

## Git Workflow

- Branch: `codex/fail-closed-auth-disable`
- Commit message: `Fail closed on disabled production auth`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define runtime detection

Use an explicit env such as `APP_ENV`, `ENVIRONMENT`, or a repo-existing runtime flag if one already exists.

Production/public runtime should reject `AUTH_DISABLE=true` unless a clearly named local/test override is also present.

### Step 2: Fail early

Fail during auth configuration or app startup, not after serving requests.

The failure message should name the unsafe variable and the local/test-only override.

### Step 3: Preserve tests

Update tests that intentionally disable auth to use the new local/test-only override.

Do not loosen production behavior to keep tests easy.

### Step 4: Document the contract

Update `.env.example` and README with:

- `AUTH_DISABLE` is local/test only,
- production startup fails if it is enabled,
- the safe local override for tests or isolated development.

## Test Plan

- Auth tests pass.
- A unit test proves production-like env plus `AUTH_DISABLE=true` fails.
- A unit test proves local/test override still allows disabled auth.

## Done Criteria

- [ ] Public/server runtime cannot start with auth disabled accidentally.
- [ ] Local/test disabled auth still has an explicit path.
- [ ] Env docs reflect the guard.
- [ ] Tests cover both sides of the guard.

## STOP Conditions

- The real server currently uses `AUTH_DISABLE=true`.
- There is no reliable env signal to distinguish production/server runtime.
- Existing test setup depends on importing the app before env setup can happen.

## Maintenance Notes

Disabled auth should be treated like a test fixture, not a production configuration option.
