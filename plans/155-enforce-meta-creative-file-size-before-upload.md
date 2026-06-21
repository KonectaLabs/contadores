# Plan 155: Enforce Meta Creative File Size Before Upload

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/ai/codex_agent_tools.py src/backend/meta_ads_publish.py src/backend/endpoints/platform.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: META-CREATIVE-03

## Why This Matters

The platform upload endpoint rejects oversized creative files, but agent-staged creative assets can reference an existing repo/data path. Meta publish validates type and existence before Graph upload, but it does not enforce the same file-size cap. An agent-staged oversized file can therefore bypass the operator upload boundary and reach the live provider upload path.

Every resolved creative path should be size-checked before Meta Graph upload.

## Current State

- Platform upload has a max byte constant:

```python
src/backend/endpoints/platform.py:43
CREATIVE_ASSET_MAX_UPLOAD_BYTES = 250 * 1024 * 1024
```

- The upload endpoint rejects oversized files:

```python
src/backend/endpoints/platform.py:1274
if len(contents) > CREATIVE_ASSET_MAX_UPLOAD_BYTES:
    raise HTTPException(status_code=400, detail="Creative media is too large.")
```

- Agent staged creative args accept arbitrary file paths:

```python
src/backend/ai/codex_agent_tools.py:384
class StageCreativeAssetArgs(BaseModel):
```

```python
src/backend/ai/codex_agent_tools.py:390
file_path: str = ""
```

- Meta publish checks type/existence before upload, not size:

```python
src/backend/meta_ads_publish.py:953
elif not file_path.exists():
    blocked.append("asset.file_path.exists")
```

```python
src/backend/meta_ads_publish.py:999
uploader = graph_upload or _default_graph_uploader(api_version=api_version, access_token=access_token)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Creative cap scan | `rg -n "CREATIVE_ASSET_MAX_UPLOAD_BYTES|StageCreativeAssetArgs|file_path|asset.file_path|adimages|advideos|stat\\(|st_size" src/backend src/backend/tests README.md` | all creative upload paths enforce the same cap |
| Meta creative tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "creative_upload or meta_publish or creative_asset" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Move or duplicate the creative max-byte constant into a backend-neutral location.
- Enforce the same max size for resolved creative paths before Meta upload.
- Include file size in redacted events/results where useful.
- Block oversized agent-staged files before any provider call.
- Add tests with mocked file sizes or tiny fixtures.

**Out of scope**:
- Durable upload attempt state; plan 133 owns retry/crash windows.
- Manual CRM media upload caps; plan 077 owns that boundary.
- Workstation media retention; plan 048 owns pruning.
- Changing Meta provider limits beyond the app cap.

## Git Workflow

- Branch: `codex/enforce-meta-creative-file-size`
- Commit message: `Enforce Meta creative file size before upload`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Centralize the cap

Avoid importing endpoint modules from provider code. Move `CREATIVE_ASSET_MAX_UPLOAD_BYTES` to a small shared constants module or duplicate with a clear comment if moving would create churn.

### Step 2: Check resolved files

In `meta_ads_publish.py`, after resolving and type-checking the file path, check `stat().st_size`.

If over the cap:

- add a blocked reason,
- persist `upload_blocked` failure reason as today,
- do not call the Graph uploader.

### Step 3: Reflect size in results

Add `file_size_bytes` to upload result/events if the result model supports it cleanly. Keep this numeric and non-sensitive.

### Step 4: Add tests

Use a fake uploader and a patched size or small fixture to prove:

- oversized files are blocked,
- uploader is not called,
- valid files still upload,
- blocked reason is operator-readable.

## Test Plan

- Meta creative tests pass.
- Backend import smoke passes.
- No live Meta call is made.

## Done Criteria

- [ ] Agent-staged creative files cannot bypass the platform upload byte cap.
- [ ] Oversized files are blocked before Graph upload.
- [ ] Events/results include enough size context to diagnose the block.
- [ ] Tests prove the uploader is not called for oversized files.

## STOP Conditions

- Meta provider accepts larger files than the platform cap and operators intentionally rely on agent-staged large files.
- Moving the shared cap would create circular imports.
- Existing tests depend on uploading fixture files larger than the cap.

## Maintenance Notes

Provider-write validation belongs at the provider boundary too. Do not assume every creative file entered through the browser upload endpoint.
