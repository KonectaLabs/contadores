# Plan 083: Persist Session Revocation Or Token Epoch

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/auth.py src/backend/endpoints/auth.py src/backend/tests .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 047
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTH-06

## Why This Matters

Sessions are signed self-contained tokens. Logout revokes only the current process memory. After a backend restart, an unexpired logged-out token can become valid again because the in-memory revocation map is cleared.

Production deploys and restarts are normal in this repo, so logout should survive restart for the token lifetime.

## Current State

- Session tokens carry a `sid` and expiry:

```python
src/backend/auth.py:299
def create_session(self, user: str) -> str:
```

```python
src/backend/auth.py:308
"sid": secrets.token_urlsafe(16),
```

- Revocations are in memory:

```python
src/backend/auth.py:242
self._revoked_sessions: dict[str, datetime] = {}
```

```python
src/backend/auth.py:335
def revoke_session(self, session_token: str | None) -> None:
```

- Reload clears revocations:

```python
src/backend/auth.py:269
self._revoked_sessions = {}
```

```python
src/backend/auth.py:286
self._revoked_sessions = {}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Session scan | `rg -n "revoked|sid|create_session|resolve_session|revoke_session|AUTH_SESSION" src/backend/auth.py src/backend/endpoints/auth.py src/backend/tests .env.example README.md` | persistence path is visible |
| Auth tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "session or logout or auth" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/auth.py src/backend/endpoints/auth.py` | exit 0 |

## Scope

**In scope**:
- Persist logout revocations under the repo data root, or add a persisted token epoch/key-version mechanism.
- Store hashes, not raw session tokens, if using a revocation list.
- Prune expired revocations.
- Add restart/reload regression tests.

**Out of scope**:
- Changing the cookie format unless needed for token epoch.
- Full server-side session store.
- Account management UI.

## Git Workflow

- Branch: `codex/persist-session-revocation`
- Commit message: `Persist session revocations`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose the simpler persistence model

Prefer the smallest readable design:

- token-hash revocation file under `data/`, or
- persisted session epoch/key version if that is easier to validate.

Use plan 047's data backup/restore runbook before relying on persistent auth state in production.

### Step 2: Avoid storing raw tokens

If using revocation entries, hash the signed token or `sid` with a stable server-side key. Store expiry so old entries can be pruned.

### Step 3: Load and prune on reload

`reload_from_env()` should reload persisted revocation state instead of clearing it silently.

Prune expired entries without requiring manual cleanup.

### Step 4: Add restart tests

Test that:

- logout revokes the current token,
- a simulated reload/recreated manager keeps the token revoked,
- expired revocations are ignored or pruned,
- normal unrevoked sessions still work.

## Test Plan

- Auth/session tests pass.
- No raw token appears in persisted data during tests.
- Existing login/logout behavior remains unchanged from the browser perspective.

## Done Criteria

- [ ] Logout remains effective after backend reload/restart.
- [ ] Persisted auth state does not store raw session tokens.
- [ ] Expired revocations are pruned.
- [ ] Tests cover reload behavior.

## STOP Conditions

- Data root semantics are not settled yet; complete plan 047 first.
- The auth signing key rotates on every deploy, making session persistence behavior different than expected.
- A persistent revocation list would grow without reliable pruning.

## Maintenance Notes

Keep the session lifetime unchanged. This plan only makes logout durable for the existing lifetime.
