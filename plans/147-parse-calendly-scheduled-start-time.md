# Plan 147: Parse Calendly Scheduled Start Time

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/main.py src/bot/tests src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/036-require-calendly-webhook-signatures.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CALENDLY-02

## Why This Matters

Calendly webhook reconciliation currently stores the webhook occurrence timestamp as `meeting_scheduled_at`. That is the time Calendly emitted or recorded the event, not necessarily the appointment start time. This can make lead state, follow-up timing, and operator reporting show a meeting as happening at the wrong time.

The webhook command should carry the scheduled meeting start explicitly and should fail closed or leave the meeting time unset when Calendly does not provide a parseable start time.

## Current State

- The backend command only accepts the webhook occurrence time:

```python
src/backend/endpoints/contadores.py:4589
class ContadoresCalendlyWebhookCommand(BaseModel):
    """Bot-delivered Calendly webhook payload reduced to tracking token."""

    token: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    occurred_at: datetime | None = None
```

- The event handler stores occurrence time as the meeting time:

```python
src/backend/endpoints/contadores.py:6254
scheduled_at = command.occurred_at or now_utc()
```

```python
src/backend/endpoints/contadores.py:6258
meeting_scheduled_at=scheduled_at,
```

- Platform calendar scheduling uses the real appointment start:

```python
src/backend/calendar_events.py:383
scheduled_start=start,
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Calendly scan | `rg -n "Calendly|calendly|occurred_at|scheduled_at|meeting_scheduled_at|start_time|invitee" src/bot src/backend README.md` | webhook start-time mapping is visible |
| Bot Calendly tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/bot/tests -k "calendly" -q` | exit 0 |
| Contadores Calendly tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "calendly or meeting" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add an explicit scheduled-start field to the backend Calendly command.
- Parse the real meeting start from the bot webhook payload.
- Store the parsed scheduled start in `meeting_scheduled_at`.
- Avoid falling back from missing start time to `occurred_at` for meeting time.
- Add tests where `occurred_at` and appointment start differ.
- Update README if Calendly payload semantics are documented.

**Out of scope**:
- Signature verification; plan 036 owns public webhook trust.
- Terminal-state protection; plan 103 owns regression of terminal lead states.
- Calendar event creation; existing platform scheduling code owns that path.
- Changing follow-up automation delays.

## Git Workflow

- Branch: `codex/parse-calendly-scheduled-start`
- Commit message: `Parse Calendly scheduled start time`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add command fields

Extend `ContadoresCalendlyWebhookCommand` with a field such as `scheduled_start_at: datetime | None`.

Keep `occurred_at` for audit/event ordering only.

### Step 2: Parse the Calendly payload in the bot

In the public bot webhook handler, extract the scheduled start from the actual Calendly payload shape. Prefer explicit event/invitee start fields over derived text.

If multiple candidate fields exist, keep parsing code small and tested.

### Step 3: Store only real scheduled time

Change backend reconciliation so `meeting_scheduled_at` receives `scheduled_start_at`.

If the event says a meeting was scheduled but no scheduled start is available, return a clear error or preserve the current stage without setting a fake meeting timestamp. Do not silently use `now_utc()`.

### Step 4: Add regression tests

Cover:

- webhook `occurred_at` differs from meeting start and backend stores meeting start,
- missing scheduled start does not store `occurred_at`,
- existing valid reconciliation still pauses automation and records the meeting milestone.

## Test Plan

- Bot Calendly tests pass.
- Contadores Calendly/meeting tests pass.
- Backend import smoke passes.
- No live Calendly call is made.

## Done Criteria

- [ ] Calendly reconciliation stores appointment start time, not webhook occurrence time.
- [ ] Missing scheduled start is explicit and tested.
- [ ] Tests cover differing occurrence and appointment timestamps.
- [ ] README docs do not describe `occurred_at` as meeting time.

## STOP Conditions

- Current webhook samples do not include any reliable scheduled start field.
- Production bot payloads differ from the test fixture and no live sample is available.
- Downstream consumers intentionally use `meeting_scheduled_at` as event-received time.

## Maintenance Notes

Keep event time and meeting time as separate concepts. `occurred_at` is useful for webhook audit; it is not the appointment timestamp.
