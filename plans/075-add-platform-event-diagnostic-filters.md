# Plan 075: Add Platform Event Diagnostic Filters

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/platform.py src/backend/tests README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OBS-05

## Why This Matters

`PlatformEvent` stores severity, source, event type, and correlation id, but the list endpoint can only filter by target and funnel. During incidents, operators have to fetch a recent window and hope the relevant warning/error is inside the limit.

## Current State

- Events store diagnostic fields:

```python
src/backend/database.py:3931
class PlatformEvent(SQLModel, table=True):
```

```python
src/backend/database.py:3942
severity: str = Field(default="info", index=True)
source: str = Field(default="", index=True)
```

- The list helper filters only by target and funnel:

```python
src/backend/database.py:4010
def list_recent(
```

- The API exposes only target/funnel filters:

```python
src/backend/endpoints/platform.py:955
@platform_router.get("/events", response_model=PlatformEventListResponse)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Platform tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "platform_event or platform" -q` | exit 0 |
| Event filter scan | `rg -n "severity|source|event_type|correlation_id|created_after|created_before" src/backend/database.py src/backend/endpoints/platform.py` | filters are wired end to end |
| API smoke | command from plan 028, if available | filtered event endpoint works on server after deploy |

## Scope

**In scope**:
- Add filters for severity, source, event_type, correlation_id, created_after, and created_before.
- Keep existing target/funnel filters.
- Add tests for combined filters and bounded limits.
- Document incident-triage examples.

**Out of scope**:
- Changing event write semantics.
- Adding full-text search.
- Building a new UI for events.

## Git Workflow

- Branch: `codex/platform-event-filters`
- Commit message: `Add platform event diagnostic filters`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extend `PlatformEvent.list_recent`

Add optional keyword parameters for:

- `event_type`,
- `severity`,
- `source`,
- `correlation_id`,
- `created_after`,
- `created_before`.

Keep the limit cap.

### Step 2: Extend the API endpoint

Add query parameters with validation. Use ISO timestamps for time filters.

### Step 3: Add tests

Create events with different severity/source/type/time and assert filters compose.

### Step 4: Document examples

Add concise examples such as:

```bash
curl "/api/platform/events?severity=error&source=meta&limit=50"
```

## Test Plan

- Platform event tests pass.
- Existing overview endpoint remains unchanged.
- Invalid timestamps return a clear 422 or 400.

## Done Criteria

- [ ] Operators can filter events by severity/source/event type.
- [ ] Time-range filtering works.
- [ ] Correlation id filtering works when present.
- [ ] Tests and docs cover common incident queries.

## STOP Conditions

- Existing clients depend on exact query parameter rejection behavior.
- Filtering requires a migration that conflicts with plan 020.
- Timezone parsing is ambiguous.

## Maintenance Notes

Use simple exact filters first. Avoid adding fuzzy search until operators actually need it.
