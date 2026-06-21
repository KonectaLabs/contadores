# Plan 006: Batch Campaign List And Submission Hydration

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/005-aggregate-delivery-counts-in-sql.md
- **Category**: perf
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Ads campaign list and submissions view are operator-critical. Today their serializers open repeated sessions and run table-wide or per-row lookups. At low volume this is invisible; with hundreds of campaigns and thousands of submissions, list pages can become slow exactly when operators need to inspect live campaign and Delivery state.

## Current State

- Campaign serializer opens fresh queries for each campaign:

```python
src/backend/endpoints/campaigns.py:1044
def _campaign_payload(...):
    client = WorkstationClient.get_by_id(campaign.client_id) if campaign.client_id else None
    source = ClientLeadSource.get_by_id(campaign.client_lead_source_id) if campaign.client_lead_source_id else None
    delivery_sources = ClientLeadSource.list_by_id_prefix(_campaign_delivery_source_prefix(campaign))
    counts = LeadCaptureSubmission.count_by_campaign()
```

- The list endpoint maps that serializer over up to 500 campaigns:

```python
src/backend/endpoints/campaigns.py:1732
@campaigns_router.get("")
async def list_campaigns(... limit: int = Query(default=100, ge=1, le=500)):
    rows = LeadCaptureCampaign.list_recent(...)
    return {"campaigns": [_campaign_payload(row, request=request) for row in rows]}
```

- Submission serializer queries delivery rows and sources per submission:

```python
src/backend/endpoints/campaigns.py:965
def _submission_payload(submission: LeadCaptureSubmission) -> dict[str, Any]:
    delivery_prefix = f"campaign-submission:{submission.id}"
    deliveries = ClientLeadDelivery.list_by_source_row_key_prefix(delivery_prefix)
    ...
    for delivery in deliveries:
        source = ClientLeadSource.get_by_id(delivery.source_id)
```

- The submissions endpoint applies it to up to 1000 submissions:

```python
src/backend/endpoints/campaigns.py:2128
@campaigns_router.get("/{campaign_id}/submissions")
async def list_campaign_submissions(... limit: int = Query(default=500, ge=1, le=1000)):
    submissions = LeadCaptureSubmission.list_by_campaign(campaign.id, limit=limit)
    return {"submissions": [_submission_payload(item) for item in submissions]}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/database.py`
- `src/backend/endpoints/campaigns.py`
- `src/backend/tests/test_campaigns.py`

**Out of scope**:
- Changing campaign response shape.
- Changing public form submission behavior.
- Changing Delivery send/claim behavior from plan 004.
- Frontend UI changes.

## Git Workflow

- Branch: `codex/batch-campaign-read-hydration`
- Commit message: `Batch campaign read hydration`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add campaign-scoped submission counts

Replace or extend `LeadCaptureSubmission.count_by_campaign()` so it can accept an optional `campaign_ids: Iterable[str] | None`.

Use grouped SQL:

```python
select(cls.campaign_id, func.count()).group_by(cls.campaign_id)
```

When `campaign_ids` is supplied, filter to those ids. Preserve existing no-argument behavior for any caller outside this plan.

**Verify**: campaign tests exit 0.

### Step 2: Add batch lookups for campaign payload context

In `src/backend/database.py`, add minimal batch helpers only if existing helpers cannot do this cleanly:

- `WorkstationClient.get_by_ids(ids: Iterable[str]) -> dict[str, WorkstationClient]`
- `ClientLeadSource.get_by_ids(ids: Iterable[str]) -> dict[str, ClientLeadSource]`
- `ClientLeadSource.list_by_id_prefixes(prefixes: Iterable[str]) -> dict[str, list[ClientLeadSource]]`

Keep helpers easy to read. Use one session per helper. Return detached rows like existing get/list helpers.

**Verify**: backend import smoke prints `backend-import-ok`.

### Step 3: Pass hydrated context into `_campaign_payload`

Extend `_campaign_payload()` with optional keyword arguments:

- `client_by_id`
- `source_by_id`
- `delivery_sources_by_prefix`
- `submission_counts`

When provided, use those maps. When omitted, fall back to current per-row behavior so existing call sites stay simple.

Update `list_campaigns()` to build maps once from the listed rows and pass them into the serializer.

**Verify**: campaign tests exit 0.

### Step 4: Batch submission delivery status hydration

Add a helper that loads all deliveries for a set of submission ids by matching `source_row_key == campaign-submission:{id}` or `LIKE campaign-submission:{id}:%`.

Prefer a database helper that takes explicit submission ids and returns:

```python
dict[str, list[ClientLeadDelivery]]
```

Then collect all source ids from those deliveries and use `ClientLeadSource.get_by_ids()`.

Extend `_submission_payload()` with optional `deliveries_by_submission_id` and `source_by_id` maps, with fallback behavior preserved for single-call use.

Update `list_campaign_submissions()` to hydrate deliveries and sources once.

**Verify**: campaign tests exit 0.

### Step 5: Add regression around multi-contact submissions

The existing `test_public_submission_queues_delivery_for_each_campaign_contact` already exercises three Delivery rows and response `delivery_statuses`. If this test still covers the batched path through `/submissions`, no new test is needed. If not, add one assertion there that `GET /api/campaigns/{campaign_id}/submissions` returns all three recipients and statuses.

**Verify**: campaign tests exit 0.

## Test Plan

- Existing campaign creation/submission/delete tests.
- Existing multi-contact Delivery submission test.
- Delivery tests to catch shared helper shape regressions.

## Done Criteria

- [ ] `GET /api/campaigns` does not call `LeadCaptureSubmission.count_by_campaign()` once per campaign.
- [ ] `GET /api/campaigns/{campaign_id}/submissions` does not query Delivery source metadata once per delivery row.
- [ ] Response JSON shape remains unchanged.
- [ ] Campaign tests exit 0.
- [ ] Delivery tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- SQLModel query helpers become harder to read than the current implementation; keep this plan simple.
- Existing tests reveal response ordering changes in submissions or delivery statuses.
- The batched delivery lookup cannot express the row-key prefix contract without unsafe broad matching.

## Maintenance Notes

Reviewers should focus on preserving the old payload shape. Performance wins are secondary to avoiding a subtle operator UI regression in Ads and Delivery.
