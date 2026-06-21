# Plan 137: Replace Public Path Prefix Exemptions With Route Allowlist

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/endpoints/campaigns.py src/backend/endpoints/workstation.py src/backend/tests/test_auth.py src/backend/tests/test_campaigns.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTH-03

## Why This Matters

Auth bypass for public pages is currently prefix-based. That is easy to maintain today, but future routes under `/c/*`, `/p/*`, or `/api/public/campaigns/*` would become public by default even if they were meant for operators.

Public access should be tied to explicit route intent and method, not broad path prefixes.

## Current State

- Middleware bypasses broad public prefixes:

```python
src/backend/main.py:291
if (
```

```python
src/backend/main.py:294
or path.startswith("/p/")
```

```python
src/backend/main.py:296
or path.startswith("/c/")
```

```python
src/backend/main.py:297
or path.startswith("/api/public/campaigns/")
```

- Current campaign public routes are explicit:

```python
src/backend/endpoints/campaigns.py:2200
@public_campaigns_router.get("/c/{public_slug}")
```

```python
src/backend/endpoints/campaigns.py:2221
@public_campaigns_router.post("/api/public/campaigns/{public_slug}/submissions")
```

- Current Workstation public routes are explicit:

```python
src/backend/endpoints/workstation.py:4180
@public_workstation_router.get("/p/{public_token}")
```

```python
src/backend/endpoints/workstation.py:4195
@public_workstation_router.get("/p/{public_token}/{asset_path:path}")
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Public route scan | `rg -n "PUBLIC_PATHS_WITHOUT_SESSION|startswith\\(\"/p/\"|startswith\\(\"/c/\"|api/public/campaigns|public_.*router" src/backend/main.py src/backend/endpoints src/backend/tests` | public bypass uses explicit method/path patterns |
| Auth/public tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "public or auth or campaign or workstation" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Replace prefix checks with `is_public_route(method, path)` or equivalent explicit pattern allowlist.
- Include only intended methods for public campaign forms, public submissions, Workstation page HTML, and Workstation assets.
- Validate slug/token shape before bypassing auth where practical.
- Add regression tests for unexpected public-looking paths and methods.

**Out of scope**:
- Changing public page lifecycle; plan 045 covers Workstation public lifecycle.
- Public host ownership; plan 100 covers host allowlisting.
- Public form abuse throttling; plan 037 covers submission throttling.

## Git Workflow

- Branch: `codex/public-route-allowlist`
- Commit message: `Replace public prefix auth exemptions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define public route patterns

Create a readable helper that takes HTTP method and normalized path.

Allow only:

- GET `/c/{slug}` and `/c/{slug}/`,
- GET `/api/public/campaigns/{slug}`,
- POST `/api/public/campaigns/{slug}/submissions`,
- GET `/p/{token}`, `/p/{token}/`, and approved asset paths.

### Step 2: Validate shape before bypass

Apply conservative slug/token/path segment validation before auth bypass.

Reject or require auth for unexpected methods and admin-looking paths.

### Step 3: Add regression tests

Cover:

- current public paths still work unauthenticated,
- `/c/admin`, `/p/admin`, and unexpected subpaths do not bypass by accident,
- unexpected methods on public paths require auth unless explicitly allowed,
- public campaign submission remains public.

## Test Plan

- Auth/public tests pass.
- Backend import smoke passes.
- Manual public form and public Workstation page checks still work.

## Done Criteria

- [ ] Public auth bypass is method/path allowlisted.
- [ ] Future-looking public-prefix paths are not automatically public.
- [ ] Tests cover intended public routes and unexpected routes.

## STOP Conditions

- Workstation public asset paths cannot be safely distinguished before plan 112.
- Existing public URLs rely on path shapes broader than the allowlist.
- FastAPI routing order makes middleware-level pattern matching unreliable without a broader refactor.

## Maintenance Notes

Every new public route should be added deliberately with a test proving why it is public.
