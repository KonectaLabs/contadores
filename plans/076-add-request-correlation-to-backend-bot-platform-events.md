# Plan 076: Add Request Correlation To Backend, Bot, And Platform Events

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/database.py src/backend/endpoints src/bot/main.py src/bot/logging_utils.py src/bot/tests src/backend/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans/075-add-platform-event-diagnostic-filters.md
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OBS-06

## Why This Matters

Production investigations currently require manual stitching across backend logs, bot logs, platform events, and agent runs. `PlatformEvent` already has a `correlation_id` column, but requests and logs do not consistently generate, preserve, or propagate a request id.

## Current State

- Backend logging has no request id in the format:

```python
src/backend/main.py:55
def configure_backend_logging() -> None:
```

- Backend middleware does not assign request ids:

```python
src/backend/main.py:253
@app.middleware("http")
async def force_public_https(request: Request, call_next):
```

- Platform events can store a correlation id:

```python
src/backend/database.py:3948
correlation_id: str | None = Field(default=None, index=True)
```

- Bot logging also has no correlation field:

```python
src/bot/logging_utils.py:39
def configure_runtime_logging() -> logging.Logger:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -q` | exit 0 |
| Bot tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -q` | exit 0 |
| Correlation scan | `rg -n "X-Request-ID|correlation_id|request_id|contextvars" src/backend src/bot` | request id path is visible |
| Event filter tests | tests from plan 075 | exit 0 |

## Scope

**In scope**:
- Preserve incoming `X-Request-ID` when safe, otherwise generate one.
- Add `X-Request-ID` to backend and bot HTTP responses.
- Include request/correlation id in backend and bot logs.
- Propagate correlation id into `PlatformEvent.add` where a request context exists.
- Avoid logging sensitive payloads.

**Out of scope**:
- Distributed tracing infrastructure.
- Vendor observability integration.
- Correlating historical events.

## Git Workflow

- Branch: `codex/request-correlation`
- Commit message: `Add request correlation IDs`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add request-id middleware

In backend and bot FastAPI apps:

- read `X-Request-ID`,
- validate length/characters,
- generate a compact id when missing,
- store it on `request.state`,
- return it in the response header.

### Step 2: Add logging context

Use a small `contextvars` helper or logging filter so log lines include request id without passing it through every function.

Keep log format readable.

### Step 3: Propagate to platform events

Add a helper to read the current correlation id and use it in event creation paths where available.

Do not require every call site to change in the first pass; start with endpoint-originated events.

### Step 4: Propagate bot-to-backend requests

When the bot handles a webhook or worker cycle, send an `X-Request-ID` to backend calls so related backend logs/events can be connected.

### Step 5: Add tests

Test:

- incoming request id is preserved,
- missing id is generated,
- response header is set,
- platform events can receive the id,
- invalid oversized ids are replaced.

## Test Plan

- Backend tests pass.
- Bot tests pass.
- Event filter tests from plan 075 pass.
- Manual request shows `X-Request-ID` in response and logs.

## Done Criteria

- [ ] Backend responses include request ids.
- [ ] Bot responses include request ids.
- [ ] Logs include request/correlation id.
- [ ] Platform events created during requests can carry correlation ids.
- [ ] Tests cover generated, preserved, and rejected ids.

## STOP Conditions

- Logging context leaks request ids between concurrent requests.
- Correlation ids can include unbounded or unsafe user input.
- Propagation requires adding sensitive payloads to logs or events.

## Maintenance Notes

Start with a simple request-id system. Full tracing can come later if needed.
