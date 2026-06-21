# Plan 005: Aggregate Delivery Counts In SQL

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: perf
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Delivery source list and sync responses call `ClientLeadDelivery.count_by_status_for_sources()`. Today that helper selects every Delivery row and counts in Python. As public campaign submissions and Meta lead imports accumulate, every Delivery source view and sync response becomes proportional to the entire delivery table. SQL can aggregate the same shape cheaply.

## Current State

- Count helper scans all rows:

```python
src/backend/database.py:2797
def count_by_status_for_sources(cls) -> dict[str, dict[str, int]]:
    """Return per-source delivery status counts."""
    with Session(engine) as session:
        rows = session.exec(select(cls.source_id, cls.delivery_status)).all()
    counts: dict[str, dict[str, int]] = {}
    for source_id, status in rows:
```

- Source list uses the helper for every load:

```python
src/backend/endpoints/client_leads.py:1269
@client_leads_router.get("", response_model=ClientLeadSourceListResponse)
async def list_client_lead_sources() -> ClientLeadSourceListResponse:
    counts = ClientLeadDelivery.count_by_status_for_sources()
```

- Existing tests assert the response shape:

```python
src/backend/tests/test_client_lead_delivery.py:93
assert sync_payload["source"]["counts"] == {"pending": 1, "blocked": 1, "total": 2}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/database.py`
- `src/backend/tests/test_client_lead_delivery.py`

**Out of scope**:
- Changing response JSON shape.
- Adding pagination or filters to Delivery source list.
- Campaign/submission hydration changes from plan 006.

## Git Workflow

- Branch: `codex/sql-delivery-counts`
- Commit message: `Aggregate Delivery counts in SQL`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Replace Python counting with grouped SQL

In `src/backend/database.py`, import `func` from SQLAlchemy if not already present:

```python
from sqlalchemy import ..., func
```

Change `count_by_status_for_sources()` to run:

```python
select(cls.source_id, cls.delivery_status, func.count()).group_by(cls.source_id, cls.delivery_status)
```

Keep the returned nested dict identical:

```python
{
    "source-id": {
        "pending": 1,
        "blocked": 1,
        "total": 2,
    }
}
```

Normalize enum/string status exactly as before.

**Verify**: Delivery tests exit 0.

### Step 2: Add a focused regression if needed

If existing tests already fail on shape drift, do not add more. Otherwise add a small test that creates one source with pending, blocked, and sent rows, then asserts `count_by_status_for_sources()` includes per-status and total counts.

Use existing helpers in `src/backend/tests/test_client_lead_delivery.py`.

**Verify**: Delivery tests exit 0.

## Test Plan

- Existing source sync/list tests verify response shape.
- Optional helper-level test verifies mixed statuses.

## Done Criteria

- [ ] `count_by_status_for_sources()` uses SQL grouping instead of selecting every row.
- [ ] Response count shape is unchanged.
- [ ] Delivery tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- SQLModel returns enum values differently under grouped select in a way that breaks portable normalization.
- The helper is relied on for row-order side effects, which would indicate an unexpected hidden contract.

## Maintenance Notes

This is a low-risk performance helper. Reviewers should check that total counts are accumulated per source and that empty sources still receive `{}` through `build_source_response()` as before.
