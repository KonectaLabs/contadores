# Plan 080: Make Machine Callback Routes Internal Only

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/endpoints/client_leads.py src/backend/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: 079
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTHZ-02

## Why This Matters

Several bot/worker endpoints mutate runtime state or expose pending dispatch work, but they rely on middleware prefix auth and do not explicitly require the internal machine token in the handler. That means an authenticated browser session can call endpoints intended for workers and bypass normal UI affordances, confirmations, or sequencing.

Plan 079 limits what the internal token can do. This plan handles the opposite boundary: machine endpoints should not also be general browser-session endpoints unless the UI truly needs them.

## Current State

- Follow-up runner endpoints show the explicit pattern:

```python
src/backend/endpoints/contadores.py:227
def require_internal_api_token(request: Request) -> None:
```

```python
src/backend/endpoints/contadores.py:4701
require_internal_api_token(request)
```

- Other machine-facing endpoints do not call it:

```python
src/backend/endpoints/contadores.py:5346
@contadores_router.get("/messages/pending-delivery", response_model=PendingContadoresDeliveryResponse)
```

```python
src/backend/endpoints/contadores.py:5514
@contadores_router.post("/whatsapp/inbound", response_model=ContadoresWhatsAppInboundResponse)
```

```python
src/backend/endpoints/contadores.py:5670
@contadores_router.post("/automation/tick", response_model=ContadoresAutomationTickResponse)
```

```python
src/backend/endpoints/contadores.py:6018
@contadores_router.get("/alerts/pending", response_model=PendingContadoresAlertsResponse)
```

```python
src/backend/endpoints/contadores.py:6131
@contadores_router.post("/runtime-alerts/email-reply")
```

```python
src/backend/endpoints/client_leads.py:1526
@client_lead_deliveries_router.get("/pending", response_model=ClientLeadPendingNotificationResponse)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Machine route scan | `rg -n "pending-delivery|whatsapp/inbound|automation/tick|alerts/pending|email-reply|client-lead-deliveries.*pending|require_internal_api_token" src/backend/endpoints src/backend/tests` | machine routes call explicit auth or are intentionally browser-safe |
| Backend tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py src/backend/tests/test_client_lead_delivery.py -k "pending or inbound or automation or alert or internal" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/endpoints/contadores.py src/backend/endpoints/client_leads.py` | exit 0 |

## Scope

**In scope**:
- Identify which endpoints are worker-only.
- Add explicit internal-token checks to worker-only endpoints.
- Keep browser-safe read endpoints separate if the UI needs them.
- Add tests for both valid token access and browser-session rejection where appropriate.

**Out of scope**:
- Signature validation for external provider webhooks; plans 001, 036, and 040 cover webhook signatures/secrets.
- Changing dispatch claiming; plans 004 and 051 cover claim-before-dispatch.
- Changing admin route access; plan 079 covers broad internal-token capabilities.

## Git Workflow

- Branch: `codex/internal-only-machine-routes`
- Commit message: `Require internal token on machine routes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Classify each route

For each candidate endpoint, decide whether it is:

- worker-only,
- browser-safe read,
- browser operator action,
- external provider callback.

Do not add token-only checks to an endpoint the frontend legitimately uses.

### Step 2: Add explicit checks

For worker-only routes, accept `Request` in the handler and call `require_internal_api_token(request)` at the top.

Prefer explicit checks in handlers over relying only on middleware behavior.

### Step 3: Split routes if needed

If the UI and bot need similar data, keep the bot endpoint token-only and add or reuse a separate session-protected UI endpoint with a narrower response.

### Step 4: Add tests

For each route changed:

- request with valid internal token succeeds,
- request with browser session but no internal token is rejected,
- unauthenticated request is rejected.

## Test Plan

- Focused backend tests pass.
- Existing bot flow tests still pass.
- No frontend build is required unless a browser route is split or renamed.

## Done Criteria

- [ ] Worker-only endpoints explicitly require `X-Internal-Token`.
- [ ] Browser sessions cannot call bot-only mutation/callback routes.
- [ ] UI routes still work through normal session auth.
- [ ] Tests prove both accepted and rejected auth paths.

## STOP Conditions

- A route is used by both frontend and bot and cannot be split without broader API design.
- Calendly or another provider calls a backend route directly and needs signature validation instead of internal-token auth.
- Existing deployment has no internal token configured.

## Maintenance Notes

When adding a worker endpoint, put the auth requirement in the handler even if middleware already protects the path.
