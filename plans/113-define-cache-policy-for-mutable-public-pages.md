# Plan 113: Define Cache Policy For Mutable Public Pages

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/endpoints/campaigns.py src/backend/endpoints/workstation.py src/backend/tests/test_system_cache_headers.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: public-serving
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: STATIC-02

## Why This Matters

Public campaign forms and Workstation public trial pages are mutable. Operators can change campaign form copy, deactivate slugs, or publish a new Workstation page version. Today only `/api/` responses get an explicit no-store cache policy; public HTML/static public-page routes rely on defaults.

That can leave stale public pages in browser or proxy caches after a campaign is changed or deactivated.

## Current State

- Cache prevention only applies to API routes:

```python
src/backend/main.py:317
async def prevent_api_response_caching(request: Request, call_next):
```

```python
src/backend/main.py:321
if request.url.path.startswith("/api/"):
```

- The cache-header test intentionally allows non-API responses to omit cache headers:

```python
src/backend/tests/test_system_cache_headers.py:16
def test_health_response_keeps_default_cache_headers() -> None:
```

- Public campaign HTML returns without route-level cache headers:

```python
src/backend/endpoints/campaigns.py:2207
async def serve_public_campaign_form(request: Request, public_slug: str) -> HTMLResponse:
```

```python
src/backend/endpoints/campaigns.py:2211
return HTMLResponse(render_public_form_html(payload))
```

- Public Workstation pages and generated assets return without route-level cache headers:

```python
src/backend/endpoints/workstation.py:4187
async def serve_public_workstation_page(public_token: str) -> FileResponse:
```

```python
src/backend/endpoints/workstation.py:4201
return FileResponse(path, media_type=media_type, content_disposition_type="inline")
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Public cache scan | `rg -n "Cache-Control|no-store|public_slug|public_token|serve_public_campaign_form|serve_public_workstation_page" src/backend src/backend/tests` | mutable public routes set explicit cache policy |
| Header tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_system_cache_headers.py -q` | exit 0 |

## Scope

**In scope**:
- Define a cache policy for mutable public campaign and Workstation pages.
- Add route or middleware coverage for `/c/{slug}/`, slash redirects if needed, `/p/{token}/`, and `/p/{token}/{asset_path}`.
- Keep `/health` and immutable frontend build assets on their current behavior unless intentionally changed.
- Add tests that assert the selected policy.

**Out of scope**:
- Public Workstation page lifecycle/deactivation mechanics; plan 045 covers lifecycle.
- Public campaign submission dedupe/throttle; plans 016, 017, and 037 cover writes.
- CDN configuration outside the app.
- Hashing generated Workstation assets for immutable caching.

## Git Workflow

- Branch: `codex/cache-policy-public-pages`
- Commit message: `Define cache policy for mutable public pages`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Pick the explicit policy

Use `Cache-Control: no-store` for mutable public HTML. For generated Workstation assets, use either:

- `no-store` for all public page assets, simplest and safest, or
- a short private max-age only if the product explicitly needs browser caching.

Document the choice in the test names and comments.

### Step 2: Apply policy consistently

Set headers in the route responses or in middleware that targets `/c/` and `/p/` public routes.

Avoid broad middleware changes that accidentally make frontend app assets uncached.

### Step 3: Add route tests

Add TestClient checks for:

- `/c/{public_slug}/`,
- `/p/{public_token}/`,
- `/p/{public_token}/styles.css` or an equivalent generated asset,
- existing `/health` behavior if it should remain unchanged.

### Step 4: Keep redirects sane

Decide whether slashless redirects also need explicit no-store. If redirects remain cacheable, document why.

## Test Plan

- System header tests pass.
- Public campaign form response includes the selected cache policy.
- Public Workstation page and asset responses include the selected cache policy.

## Done Criteria

- [ ] Mutable public HTML responses have explicit cache headers.
- [ ] Public Workstation generated assets have an intentional cache policy.
- [ ] Tests protect the policy from drifting.
- [ ] Unrelated health/frontend behavior is not changed by accident.

## STOP Conditions

- A reverse proxy or CDN already enforces a stronger public-route cache policy and the app should not override it.
- Product wants long-lived caching for Workstation assets but generated asset filenames are not content-addressed.
- Test setup cannot create a realistic public Workstation page without broader fixture work.

## Maintenance Notes

When a public route can be deactivated or republished under the same URL, default to freshness over cache efficiency.
