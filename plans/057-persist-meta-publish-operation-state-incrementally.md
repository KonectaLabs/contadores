# Plan 057: Persist Meta Publish Operation State Incrementally

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/meta_ads_publish.py src/backend/database.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/020-add-migration-discipline-for-production-schema-changes.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-07

## Why This Matters

Meta publish execution keeps provider object ids in memory until the whole operation finishes. If the process crashes after one successful Graph write but before final persistence, retry can create duplicate Meta campaigns/ad sets/ads because the already-created provider id was never saved.

## Current State

- Execution loops through operations:

```python
src/backend/meta_ads_publish.py:1333
for operation in operations:
```

- Provider id is added to in-memory state:

```python
src/backend/meta_ads_publish.py:1354
response = _sanitize_provider_payload(poster(operation.path, request_params))
src/backend/meta_ads_publish.py:1358
provider_ids[operation.local_ref] = provider_id
```

- Final state is persisted only after the loop:

```python
src/backend/meta_ads_publish.py:1423
updated_plan["live_execution_state"] = result.model_dump(mode="json")
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Meta publish tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "meta_publish" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Persist each successful provider id immediately after the Graph write.
- Resume from persisted operation state on retry.
- Add crash-window tests using a fake poster that raises after one success.

**Out of scope**:
- Changing approval gates.
- Changing Meta object creation order.
- Deleting duplicate Meta objects created before this fix.

## Git Workflow

- Branch: `codex/incremental-meta-publish-state`
- Commit message: `Persist Meta publish operation state incrementally`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add incremental persistence helper

Create a helper that updates the `PlatformMetaPublishAttempt` request payload after each successful operation with:

- provider id by local ref,
- operation result,
- timestamp,
- request params with secrets redacted.

Keep the existing final `live_execution_state` shape compatible.

### Step 2: Resume from persisted state

Before executing an operation, read the latest attempt payload and merge persisted provider ids into the in-memory state.

If a local ref already has a provider id, skip that operation and record `already_submitted`.

### Step 3: Add crash-window tests

Use a fake poster that:

1. returns an id for the first operation,
2. raises before the second operation completes.

Assert the first id is persisted and retry does not call the first operation again.

## Test Plan

- Run Meta publish tests.
- Run backend import smoke.
- Inspect saved payload shape for redaction and compatibility.

## Done Criteria

- [ ] Provider ids are persisted after each successful Meta operation.
- [ ] Retry resumes from persisted operation state.
- [ ] Crash-window test proves no duplicate first operation.
- [ ] Existing final execution payload remains compatible.

## STOP Conditions

- Persisting after each operation makes existing payload too large or incompatible.
- Current Meta plan execution assumes all-or-nothing state.
- Existing production attempt rows need migration before new state can be read.

## Maintenance Notes

For external writes, final persistence is too late. Save enough state to make retry safe after every provider success.
