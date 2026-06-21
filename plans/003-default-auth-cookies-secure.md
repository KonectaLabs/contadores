# Plan 003: Default Auth Cookies To Secure

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/auth.py src/backend/endpoints/auth.py src/backend/tests/test_auth.py .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Auth is enforced for the backoffice, and production is public HTTPS. Today `AUTH_COOKIE_SECURE` defaults to false, so session cookies are set without the browser's Secure attribute unless the server env explicitly opts in. Redirects and HSTS reduce risk after the first protected request, but the cookie should be secure by default in production and opt out only for local development.

## Current State

- Auth config defaults secure cookies off:

```python
src/backend/auth.py:277
session_hours = _parse_session_hours(os.getenv("AUTH_SESSION_HOURS", "24"))
cookie_secure = _parse_bool_env("AUTH_COOKIE_SECURE", default=False)
```

- Login writes the cookie using that value:

```python
src/backend/endpoints/auth.py:27
def apply_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        ...
        secure=auth_manager.cookie_secure,
        path="/",
    )
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Auth tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_auth.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/auth.py`
- `src/backend/tests/test_auth.py`
- `.env.example`
- `README.md`

**Out of scope**:
- Replacing primitive auth.
- Changing session token format.
- Changing public path exemptions.
- Changing HSTS or Cloudflare redirect behavior.

## Git Workflow

- Branch: `codex/default-auth-cookies-secure`
- Commit message: `Default auth cookies to secure`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Change the default

In `PrimitiveAuthManager.reload_from_env()`, change:

```python
cookie_secure = _parse_bool_env("AUTH_COOKIE_SECURE", default=False)
```

to:

```python
cookie_secure = _parse_bool_env("AUTH_COOKIE_SECURE", default=True)
```

Keep `AUTH_DISABLE=true` behavior unchanged.

**Verify**: backend import smoke prints `backend-import-ok`.

### Step 2: Add or update tests

In `src/backend/tests/test_auth.py`, cover:

- When auth is enabled and `AUTH_COOKIE_SECURE` is unset, login response has a Secure cookie.
- When `AUTH_COOKIE_SECURE=false`, login response omits Secure for local development.
- Existing login/logout/session tests still pass.

Use the existing auth fixture/helper style in that file.

**Verify**: auth tests exit 0.

### Step 3: Document the local override

In `.env.example`, set or document:

```env
AUTH_COOKIE_SECURE=true
```

Add a short README note: production should leave secure cookies enabled; local HTTP-only development can set `AUTH_COOKIE_SECURE=false`.

**Verify**:

```bash
rg -n "AUTH_COOKIE_SECURE" .env.example README.md src/backend/auth.py src/backend/tests/test_auth.py
```

Expected: config, docs, implementation, and tests all reference the env var.

## Test Plan

- Unit/API tests in `src/backend/tests/test_auth.py`.
- Existing auth manager behavior around disabled auth and session expiry should remain unchanged.

## Done Criteria

- [ ] Secure cookie default is true when auth is enabled.
- [ ] Explicit `AUTH_COOKIE_SECURE=false` still works for local HTTP development.
- [ ] Auth tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.
- [ ] README/.env.example tell operators how to override locally.

## STOP Conditions

- Production currently terminates TLS in a way that requires non-secure cookies to function.
- Tests reveal TestClient cannot inspect Secure reliably with existing helpers.
- The change requires touching unrelated auth/session semantics.

## Maintenance Notes

Reviewers should check the real server `.env` after deploy. If it currently sets `AUTH_COOKIE_SECURE=false`, that must be removed or explicitly justified before calling the rollout complete.
