# Plan 136: Add Browser Session Role Capabilities

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/auth.py src/backend/main.py src/backend/endpoints src/backend/tests/test_auth.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/079-scope-internal-token-capabilities.md
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AUTH-02

## Why This Matters

Once a browser session is authenticated, every user has the same power. That includes lead deletion, campaign deletion, Meta publish approval/execution, funnel/config writes, and Workstation live Codex runs.

Operator sessions should fail closed unless the user has the capability needed for the requested mutation.

## Current State

- Auth config loads user/password pairs only:

```python
src/backend/auth.py:212
def _extract_toml_users(raw: dict[str, Any]) -> list[tuple[str, str]]:
```

- Session tokens contain user, expiry, and sid, but no role/capability:

```python
src/backend/auth.py:305
payload = {
```

- Middleware stores only user and auth source:

```python
src/backend/main.py:314
request.state.authenticated_user = session_user
```

- Destructive/provider-write routes do not check user capability:

```python
src/backend/endpoints/campaigns.py:1882
@campaigns_router.delete("/{campaign_id}")
```

```python
src/backend/endpoints/platform.py:1452
@platform_router.post(
```

```python
src/backend/endpoints/workstation.py:4353
@workstation_router.post(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Capability scan | `rg -n "authenticated_user|auth_source|delete\\(|meta-publish|solo-page/work|config|require_capability|auth.toml" src/backend src/backend/tests README.md` | high-impact routes require explicit capabilities |
| Auth/capability tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "auth or capability or campaign or meta_publish or workstation" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Extend auth TOML account entries with roles or explicit capabilities.
- Add `require_capability(request, capability)` or equivalent dependency.
- Define a small capability matrix for config, leads, campaigns, Meta publish, Delivery, and Workstation live actions.
- Add tests for low-privilege denial and admin success.
- Document the auth TOML shape.

**Out of scope**:
- OAuth or external identity providers.
- Per-client multi-tenant authorization.
- Internal-token scoping; plan 079 owns machine token capabilities.

## Git Workflow

- Branch: `codex/browser-session-capabilities`
- Commit message: `Add browser session capabilities`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extend auth account parsing

Support both existing simple `[users]` password maps and richer account tables with role/capability metadata.

Default existing simple users to `admin` only if that preserves current production behavior and is documented.

### Step 2: Attach capabilities to request state

Resolve capabilities after session validation and make them available through request state or a helper.

Do not trust frontend-provided role/capability data.

### Step 3: Gate high-impact routes first

Add explicit capability checks to:

- lead deletion and bulk terminal mutations,
- campaign create/delete and Delivery routing changes,
- Meta publish approve/execute,
- runtime/funnel config writes,
- Workstation live Codex run triggers.

Keep read-only dashboard routes available to lower roles only if product needs that role.

### Step 4: Add tests and docs

Add auth fixture users for `viewer` and `admin`.

Test that viewer cannot execute high-impact mutations and admin can.

Update README/auth docs with the new account shape.

## Test Plan

- Auth/capability tests pass.
- Backend import smoke passes.
- Manual login with an admin account still reaches existing screens.

## Done Criteria

- [ ] Browser sessions carry server-resolved capabilities.
- [ ] High-impact mutations require explicit capabilities.
- [ ] Existing simple auth TOML migration path is documented.
- [ ] Tests prove deny/allow behavior.

## STOP Conditions

- Product owner wants all authenticated users to remain full admins.
- Current auth TOML format cannot be extended without breaking deployment and no migration path is acceptable.
- Required route classification becomes too broad for this plan.

## Maintenance Notes

Do not add new high-impact routes without a capability decision. A session is identity, not authorization.
