# Plan 011: Cover Meta Pause Patch Failure

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/tests/test_campaigns.py src/backend/endpoints/campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Deleting a campaign already has a failure test proving local delete is blocked if Meta pause fails. Patching status to `paused` or `archived` has the same live-spend safety gate but lacks the corresponding failure test. A regression here could make the CRM hide or mark paused a campaign while Meta objects remain live.

## Current State

- Patch path blocks on Meta pause errors:

```python
src/backend/endpoints/campaigns.py:1976
if next_status in {"paused", "archived"} and next_status != current.status:
    try:
        pause_meta_objects_for_campaign(current, actor="operator", source="campaign_api")
    except MetaCampaignLifecycleError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
```

- Success path test exists:

```python
src/backend/tests/test_campaigns.py:239
def test_pausing_campaign_pauses_live_meta_objects_first(...)
```

- Delete failure path test exists:

```python
src/backend/tests/test_campaigns.py:296
def test_deleting_campaign_blocks_when_live_meta_pause_fails(...)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |

## Scope

**In scope**:
- `src/backend/tests/test_campaigns.py`
- `src/backend/endpoints/campaigns.py` only if the test exposes a real bug.

**Out of scope**:
- Changing Meta pause implementation unless required by failing test.
- Live Meta API calls.
- Frontend confirmation behavior from plan 008.

## Git Workflow

- Branch: `codex/test-meta-pause-patch-failure`
- Commit message: `Cover Meta pause patch failure`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add the failing patch test

In `src/backend/tests/test_campaigns.py`, model it after `test_deleting_campaign_blocks_when_live_meta_pause_fails`.

Flow:

1. Configure temp DB.
2. Set `META_MARKETING_LIVE_WRITES_ENABLED=true`, fake token, fake API version.
3. Monkeypatch `_default_graph_poster` to raise `RuntimeError("Meta rejected pause for ...")`.
4. Create an active campaign.
5. Set `meta_campaign_id` on the campaign.
6. `PATCH /api/campaigns/{id}` with `{"status": "paused"}`.
7. Assert status 409.
8. Assert campaign row still has original status.
9. Assert a `meta_campaign.pause_checked` event exists with `status == "failed"`.

**Verify**: campaign tests exit 0 or expose an implementation bug.

### Step 2: Fix only if the test exposes a real bug

If the new test fails because implementation mutates local status despite a pause error, fix `patch_campaign()` so local update happens only after successful pause. Keep the change as narrow as possible.

If the test passes immediately, commit only the regression test.

**Verify**: campaign tests exit 0.

## Test Plan

- One new patch failure regression.
- Existing delete failure and patch success tests remain green.

## Done Criteria

- [ ] Patch-to-paused Meta pause failure returns 409.
- [ ] Local campaign status remains unchanged on failure.
- [ ] Pause-check event is persisted.
- [ ] Campaign tests exit 0.

## STOP Conditions

- Existing implementation intentionally allows local pause after Meta failure, contradicting the current delete safety contract.
- Test requires real Meta credentials or network.

## Maintenance Notes

This plan is test-first. It protects the live-spend safety contract without changing behavior unless the test proves a gap.
