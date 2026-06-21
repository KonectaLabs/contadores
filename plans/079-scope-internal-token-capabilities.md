# Plan 079: Scope Internal Token Capabilities

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/endpoints/campaigns.py src/backend/endpoints/platform.py src/backend/endpoints/funnels.py src/backend/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTHZ-01

## Why This Matters

The single `X-Internal-Token` is intended for machine-to-machine bot calls, but middleware currently grants it across broad API prefixes. Some of those prefixes include high-impact operator/admin mutations such as campaign deletion, funnel writes, and live Meta publish approval/execution.

One leaked worker token should not have the same power as an authenticated operator session.

## Current State

- Broad path prefixes count as internal bot API paths:

```python
src/backend/main.py:91
def is_internal_bot_api_path(path: str) -> bool:
```

```python
src/backend/main.py:94
path.startswith("/api/contadores/")
```

```python
src/backend/main.py:98
or path.startswith("/api/campaigns")
```

```python
src/backend/main.py:101
or path.startswith("/api/platform/")
```

```python
src/backend/main.py:103
or path == "/api/funnels"
```

- A valid internal token bypasses browser session auth for those paths:

```python
src/backend/main.py:301
if is_internal_bot_api_path(path) and internal_token_valid:
```

- The bot client sends the same header on all backend requests:

```python
src/bot/utils.py:262
def build_backend_client() -> httpx.AsyncClient:
```

```python
src/bot/utils.py:264
headers = {INTERNAL_API_TOKEN_HEADER: INTERNAL_API_TOKEN} if INTERNAL_API_TOKEN else {}
```

- Admin mutations live under those broad prefixes:

```python
src/backend/endpoints/campaigns.py:1748
@campaigns_router.post("")
```

```python
src/backend/endpoints/campaigns.py:1882
@campaigns_router.delete("/{campaign_id}")
```

```python
src/backend/endpoints/platform.py:1420
@platform_router.post(
```

```python
src/backend/endpoints/platform.py:1452
@platform_router.post(
```

```python
src/backend/endpoints/funnels.py:38
@funnels_router.post("", response_model=FunnelDefinition)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Route scan | `rg -n "is_internal_bot_api_path|X-Internal-Token|@.*router\\.(post|put|patch|delete)" src/backend/main.py src/backend/endpoints` | only intended machine endpoints accept internal token |
| Auth tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "internal_token or auth or campaign or platform or funnel" -q` | exit 0 |
| Middleware smoke | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/main.py` | exit 0 |

## Scope

**In scope**:
- Replace broad prefix-based internal-token authorization with a method/path allowlist or route-level capability checks.
- Keep true machine endpoints available to the bot.
- Require browser session or CLI session auth for operator/admin writes.
- Add regression tests proving `X-Internal-Token` alone cannot create/delete campaigns, approve/execute Meta publish attempts, or write funnel config.

**Out of scope**:
- Rotating the token value.
- Replacing auth with OAuth.
- Locking down machine-only endpoints to token-only access; plan 080 covers the inverse boundary.

## Git Workflow

- Branch: `codex/scope-internal-token-capabilities`
- Commit message: `Scope internal token capabilities`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Inventory current machine calls

List every endpoint the bot, local runners, and CLI tools call with `X-Internal-Token`.

Keep the list explicit and small. Include HTTP method and path, not just path prefix.

### Step 2: Build the allowlist

In `main.py`, replace broad prefix authorization with a readable helper such as:

```python
def internal_token_can_access(method: str, path: str) -> bool:
    ...
```

Use exact paths or carefully bounded patterns for bot-only routes.

### Step 3: Deny internal token on admin writes

Ensure internal-token requests to campaign, platform, funnel, config, and operator mutations continue through normal session auth instead of being accepted as `internal-bot`.

Return the same 401 shape as other unauthenticated API requests.

### Step 4: Add regression tests

Cover at least:

- `POST /api/campaigns` with valid internal token is rejected without a session.
- `DELETE /api/campaigns/{id}` with valid internal token is rejected without a session.
- `POST /api/platform/meta-publish-attempts/{id}/approve` with valid internal token is rejected without a session.
- `POST /api/funnels` with valid internal token is rejected without a session.
- one legitimate machine endpoint still accepts the token.

## Test Plan

- Auth tests pass.
- Existing bot tests that rely on machine endpoints still pass.
- Manual `rg` confirms no broad admin prefix is authorized only by token.

## Done Criteria

- [ ] Internal token grants only explicit machine capabilities.
- [ ] Operator/admin writes require a browser or CLI session.
- [ ] Regression tests cover denied admin writes and allowed machine routes.
- [ ] No bot route loses required machine access.

## STOP Conditions

- The bot currently uses an admin route for normal runtime and no narrower route exists.
- Tests reveal the frontend depends on token-only access for operator writes.
- Middleware cannot distinguish route patterns cleanly without a broader auth refactor.

## Maintenance Notes

Future internal-token endpoints should be added one by one with method/path tests. Do not add new broad prefixes.
