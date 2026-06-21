# Plan 133: Durably Track Meta Creative Upload Attempts

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/meta_ads_publish.py src/backend/database.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/020-add-migration-discipline-for-production-schema-changes.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: META-02

## Why This Matters

Meta creative media upload is a live provider write that happens outside the publish operation list. If upload succeeds but the process crashes before local refs are persisted, retry can upload the same media again or execute with an unvalidated manually supplied creative id.

Creative upload should have the same durable attempt discipline as other provider writes.

## Current State

- Existing local provider refs short-circuit upload:

```python
src/backend/meta_ads_publish.py:933
if asset.image_hash or asset.video_id or asset.meta_creative_id:
```

- Live upload posts to Meta media endpoints:

```python
src/backend/meta_ads_publish.py:999
uploader = graph_upload or _default_graph_uploader(api_version=api_version, access_token=access_token)
```

```python
src/backend/meta_ads_publish.py:1000
path = f"/{clean_ad_account_id}/adimages" if provider_asset_type == "image" else f"/{clean_ad_account_id}/advideos"
```

- Returned refs are persisted only after provider success:

```python
src/backend/meta_ads_publish.py:1011
updated = PlatformCreativeAsset.update_meta_refs(
```

- A manually supplied creative id satisfies the provider-asset blocker:

```python
src/backend/meta_ads_publish.py:545
def _provider_creative_blockers(plan: dict[str, Any]) -> list[str]:
```

```python
src/backend/meta_ads_publish.py:557
has_provider_asset = any(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Creative upload scan | `rg -n "adimages|advideos|meta_creative_id|image_hash|video_id|update_meta_refs|creative_asset" src/backend/meta_ads_publish.py src/backend/database.py src/backend/tests/test_contadores.py` | provider creative uploads are durable and reusable |
| Meta creative tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "creative_upload or meta_publish" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add or reuse durable creative-upload attempt state keyed by asset id, ad account id, file checksum, file type, and upload params.
- Persist pending before live upload and success immediately after provider response.
- Reuse compatible successful attempts.
- Reject conflicting attempt keys.
- Validate supplied `meta_creative_id` against provider inventory or a live read when live publish requires it.

**Out of scope**:
- Publish operation provider-id persistence; plan 057 owns campaign/adset/ad operation state.
- Draft upload UI visibility; plan 127 owns frontend draft upload UX.
- Deleting duplicate provider media already uploaded before this fix.

## Git Workflow

- Branch: `codex/durable-meta-creative-uploads`
- Commit message: `Track Meta creative uploads durably`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose the durable attempt shape

Prefer a small table if existing `PlatformCreativeAsset` fields cannot represent pending, success, failure, conflict, and checksum safely.

If schema changes are needed, wait for plan 020 or follow its migration discipline.

### Step 2: Persist pending before upload

Before calling `/adimages` or `/advideos`, write a pending attempt with a redacted request summary.

If a compatible pending attempt exists and is fresh, return a clear in-progress response rather than submitting a duplicate live upload.

### Step 3: Persist success immediately

After Meta returns `image_hash` or `video_id`, persist the provider ref in the attempt and on the creative asset before emitting follow-up events.

### Step 4: Validate existing creative ids

When a staged ad provides `meta_creative_id`, verify that the selected ad account can read/use that creative before approval/execution.

Fail closed if inventory is required and the creative id cannot be proven.

### Step 5: Add crash-window tests

Use a fake uploader that returns a provider ref and then forces a local failure.

Retry should reuse the saved provider ref and should not call the uploader again.

## Test Plan

- Creative upload tests pass.
- Meta publish tests pass.
- Backend import smoke passes.
- Manual event/payload inspection confirms provider responses are redacted.

## Done Criteria

- [ ] Creative uploads have durable pending/success/failure state.
- [ ] Retry does not repeat a successful provider upload.
- [ ] Supplied provider creative ids are validated before live use.
- [ ] Tests cover duplicate, conflict, and crash-window behavior.

## STOP Conditions

- Meta upload responses cannot be safely keyed or reused.
- Schema changes are needed but migration discipline is not available.
- Existing production rows contain ambiguous provider refs that cannot be migrated safely.

## Maintenance Notes

Treat creative uploads as provider writes, not as a local file detail. Persist enough state to make retry safe.
