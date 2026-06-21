# Plan 082: Throttle Public Auth Login

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/auth.py src/backend/auth.py src/backend/tests .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTH-05

## Why This Matters

The login endpoint is intentionally public and backed by configured account passwords. Failed attempts have no app-level rate limit, lockout, or backoff. That leaves the public CRM login exposed to online guessing at whatever rate the network permits.

## Current State

- Login is public:

```python
src/backend/main.py:78
"/api/auth/login",
```

- The handler checks credentials and immediately creates a session:

```python
src/backend/endpoints/auth.py:51
@auth_router.post("/login", response_model=AuthStatusResponse)
```

```python
src/backend/endpoints/auth.py:59
normalized_user = auth_manager.authenticate(payload.user, payload.password)
```

```python
src/backend/endpoints/auth.py:66
session_token = auth_manager.create_session(normalized_user)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Auth endpoint scan | `rg -n "login|authenticate|Retry-After|rate|throttle|AUTH_LOGIN" src/backend/endpoints/auth.py src/backend/auth.py src/backend/tests .env.example README.md` | throttle behavior is visible |
| Auth tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "login or auth" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/endpoints/auth.py src/backend/auth.py` | exit 0 |

## Scope

**In scope**:
- Add a small in-memory per-IP and per-username login throttle.
- Use generic failure responses.
- Return `Retry-After` on throttled requests.
- Add conservative env knobs if needed and document them.
- Add focused tests with a fake clock or injectable now function.

**Out of scope**:
- Persistent distributed rate limiting.
- Replacing TOML-backed auth.
- Captcha or third-party identity providers.

## Git Workflow

- Branch: `codex/throttle-public-login`
- Commit message: `Throttle public auth login`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a readable limiter

Implement a small helper that tracks failed attempts by:

- normalized username,
- client IP or forwarded IP as already trusted by the app.

Keep the window and limits conservative. Avoid clever token-bucket code unless the repo already has one.

### Step 2: Apply before session creation

On every login:

- reject if the key is throttled,
- record failed attempts,
- clear or decay successful attempts.

Use the same generic invalid-credentials detail where possible.

### Step 3: Add tests

Cover:

- repeated bad password gets throttled,
- throttled response includes `Retry-After`,
- successful login still works,
- attempts for another username or IP are isolated as designed.

### Step 4: Document knobs

If env vars are added, update `.env.example` and README. Keep defaults usable without operator tuning.

## Test Plan

- Auth tests pass.
- Focused login throttle tests pass.
- Manual scan confirms public login is the only endpoint affected.

## Done Criteria

- [ ] Repeated failed login attempts are throttled.
- [ ] Successful login still issues the session cookie.
- [ ] Throttle behavior is covered by tests.
- [ ] Any env knobs are documented.

## STOP Conditions

- The deployment is behind a proxy that makes client IP unreliable and no trusted header strategy exists.
- Tests become time-sleep based instead of using an injectable clock.
- Operators need a different lockout policy before implementation.

## Maintenance Notes

This is an app-level friction layer, not a replacement for strong passwords and Cloudflare/firewall controls.
