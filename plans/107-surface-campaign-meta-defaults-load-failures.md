# Plan 107: Surface Campaign Meta Defaults Load Failures

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: ADS-01

## Why This Matters

The Ads workspace loads Meta tracking defaults to tell operators whether Meta events are configured. If the defaults endpoint fails, the frontend silently substitutes an empty defaults object. That makes a server/config error look like normal "Meta unavailable" state and can hide why Pixel/CAPI tracking is not visible before a campaign is published.

## Current State

- Campaign loading fetches campaigns, clients, and Meta defaults together:

```tsx
src/frontend/src/App.tsx:3674
const [campaignPayload, clientPayload, metaDefaultsPayload] = await Promise.all([
```

- The Meta defaults request swallows every failure:

```tsx
src/frontend/src/App.tsx:3677
apiFetch<CampaignMetaDefaults>("/api/campaigns/meta/defaults").catch(() => emptyCampaignMetaDefaults),
```

- Backend has a dedicated defaults endpoint:

```python
src/backend/endpoints/campaigns.py:1694
@campaigns_router.get("/meta/defaults", response_model=CampaignMetaDefaultsResponse)
```

```python
src/backend/endpoints/campaigns.py:1697
pixel_id, source = _default_meta_pixel_id()
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Meta defaults scan | `rg -n "meta/defaults|emptyCampaignMetaDefaults|metaDefaults|setMetaDefaults|onError" src/frontend/src/App.tsx src/backend/endpoints/campaigns.py` | load failures are surfaced instead of silently replaced |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -k "meta_defaults or meta" -q` | exit 0 or no tests selected if none exist |

## Scope

**In scope**:
- Surface Meta defaults load failures in the Ads UI.
- Keep campaign and client list loading resilient if only defaults fail.
- Distinguish "defaults loaded and Meta not configured" from "defaults failed to load".
- Preserve the backend endpoint response shape.

**Out of scope**:
- Changing Meta Pixel/CAPI default resolution.
- Campaign publish gating; plans 057 and 058 cover publish/provider writes.
- Campaign Delivery confirmations; plan 105 covers Delivery routing writes.

## Git Workflow

- Branch: `codex/surface-meta-defaults-errors`
- Commit message: `Surface Meta defaults load failures`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Track defaults load status

Add local state for defaults loading/error, or include an error marker alongside `metaDefaults`.

Do not collapse failed load into the same object used for a successful empty config.

### Step 2: Keep Ads list usable

If `/api/campaigns/meta/defaults` fails, still show campaigns and clients when those requests succeed.

Show a compact warning near Meta tracking controls or the Ads workspace header.

### Step 3: Preserve successful empty state

When the endpoint succeeds with `meta_events_available=false`, keep the current unavailable behavior. That is different from a failed request.

### Step 4: Verify

Run frontend build and focused campaign tests.

## Test Plan

- Frontend build/typecheck.
- Focused campaign tests if existing tests cover Meta defaults.
- Manual browser check by temporarily forcing the defaults request to fail in a dev environment.

## Done Criteria

- [ ] Failed Meta defaults loads produce visible operator feedback.
- [ ] Successful "Meta not configured" state remains distinct from request failure.
- [ ] Campaign list loading still works when only defaults fail.

## STOP Conditions

- Product owner wants Ads to stay silent when Meta defaults fail.
- The frontend cannot surface partial-load errors without changing shared loading architecture broadly.
- Backend endpoint semantics change before this plan lands.

## Maintenance Notes

Do not make this a blocking publish gate unless a separate product decision says missing tracking defaults should prevent publish.
