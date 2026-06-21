# Plan 135: Add Browser Session CSRF Origin Gate

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/auth.py src/backend/endpoints/auth.py src/backend/tests/test_auth.py src/frontend/src/api.ts`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/003-default-auth-cookies-secure.md
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTH-01

## Why This Matters

Browser sessions can perform destructive and provider-write mutations using only the session cookie. The cookie is `SameSite=Strict`, which reduces classic cross-site form CSRF, but the app has enough high-impact same-origin browser writes that unsafe methods should also require an explicit browser-origin and CSRF-token contract.

This gives the backend a deliberate boundary between browser sessions, machine tokens, public webhooks, and public form submissions.

## Current State

- Middleware accepts a valid browser session cookie for protected API routes:

```python
src/backend/main.py:306
session_user = auth_manager.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))
```

- Auth cookies are HttpOnly and SameSite Strict, but no CSRF token is issued:

```python
src/backend/endpoints/auth.py:27
def apply_session_cookie(response: Response, token: str) -> None:
```

```python
src/backend/endpoints/auth.py:34
samesite="strict",
```

- Frontend requests send same-origin credentials but no anti-CSRF header:

```ts
src/frontend/src/api.ts:55
function buildRequestOptions(options: ApiFetchOptions): RequestInit {
```

```ts
src/frontend/src/api.ts:65
credentials: "same-origin",
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Auth boundary scan | `rg -n "SESSION_COOKIE_NAME|samesite|csrf|Origin|Referer|Sec-Fetch-Site|credentials|apiFetch" src/backend src/frontend/src/api.ts src/backend/tests` | unsafe browser writes require origin and token checks |
| Auth tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_auth.py -q` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Issue a session-bound CSRF token on login and/or `/api/auth/me`.
- Require an `X-CSRF-Token` header for unsafe methods authenticated by browser session.
- Check same-origin `Origin`/`Referer` or Fetch Metadata for browser-session unsafe methods.
- Exempt internal-token routes, signed public webhooks, and intended public form submissions deliberately.
- Update `apiFetch` to attach the token for non-GET requests.

**Out of scope**:
- Replacing primitive auth.
- Adding user roles; plan 136 covers browser-session capabilities.
- Changing public route shape; plan 137 covers explicit public route allowlisting.

## Git Workflow

- Branch: `codex/browser-session-csrf-origin-gate`
- Commit message: `Add browser session CSRF origin gate`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose token shape

Use a session-bound signed token or a double-submit cookie/header pattern that does not expose the session cookie itself.

Keep the token non-secret in JS if using double-submit, but bind it to the session so random cross-site values fail.

### Step 2: Add unsafe-method middleware

For browser-session requests using POST, PUT, PATCH, or DELETE:

- require same-origin `Origin` or valid `Referer`,
- accept Fetch Metadata only as an additional signal, not the only check,
- require valid `X-CSRF-Token`.

Return 403 with a concise message before handlers run.

### Step 3: Wire frontend token handling

Expose the token from `/api/auth/me` or a small auth bootstrap response.

Update `apiFetch` so unsafe same-origin requests include `X-CSRF-Token` automatically.

### Step 4: Add tests

Cover:

- same-origin unsafe request with valid token succeeds,
- missing token fails,
- cross-origin `Origin` fails,
- internal-token worker route remains usable,
- public campaign submission remains public by explicit exemption.

## Test Plan

- Auth tests pass.
- Frontend build passes.
- Manual browser login and one harmless mutation work locally.

## Done Criteria

- [ ] Browser-session unsafe methods require CSRF token and same-origin evidence.
- [ ] Internal-token and public provider/public form routes are deliberately exempted.
- [ ] Frontend sends the token automatically.
- [ ] Tests cover accepted and rejected paths.

## STOP Conditions

- The real deployment strips `Origin`, `Referer`, and Fetch Metadata headers in a way that cannot be fixed.
- Token bootstrapping requires a broader frontend auth flow rewrite.
- Public provider callbacks cannot be cleanly distinguished before plan 137.

## Maintenance Notes

SameSite helps, but do not rely on cookie policy as the only mutation boundary for the backoffice.
