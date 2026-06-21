# Plan 150: Add Codex Turn Wall-clock Timeouts

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/codex_utils.py src/backend/ai/contadores_conversation_bot.py src/backend/ai/codex_agent_runtime.py src/backend/endpoints/workstation.py src/backend/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CODEX-RUNTIME-01

## Why This Matters

Codex SDK runs are used for WhatsApp conversation decisions, autonomous agent work, and Workstation media generation. The shared stream collection code waits for the turn to finish without a wall-clock deadline. If the SDK stream hangs or the provider never returns a completion event, backend jobs can stay running indefinitely and block follow-up paths.

Every Codex turn should have a configurable timeout and a cancellation/failure path that callers can surface safely.

## Current State

- `run_codex_with_context()` limits retries but has no per-turn timeout:

```python
src/backend/codex_utils.py:224
max_attempts: int = 3,
```

- Stream collection waits until completion:

```python
src/backend/codex_utils.py:517
async for event in turn.stream():
```

- Conversation bot calls it without a timeout override:

```python
src/backend/ai/contadores_conversation_bot.py:656
result = await run_codex_with_context(
```

- Autonomous agent runtime calls it without a timeout override:

```python
src/backend/ai/codex_agent_runtime.py:205
return await run_codex_with_context(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Codex timeout scan | `rg -n "run_codex_with_context|_collect_turn_result|turn.stream|wait_for|timeout|CodexTurnResult|CODEX_.*TIMEOUT" src/backend src/backend/tests .env.example README.md` | Codex timeout contract is visible |
| Codex utility tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "codex and timeout" -q` | exit 0 after tests exist |
| Conversation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "conversation_bot or codex" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add a configurable Codex turn timeout with a safe default.
- Wrap turn stream collection in a cancellable wall-clock deadline.
- Ensure timeout errors are recognizable by conversation fallback and agent runtime.
- Mark agent runs failed with a redacted timeout reason.
- Return clear Workstation job/operator errors when generation times out.
- Document env vars and defaults.

**Out of scope**:
- Operator confirmation for live Workstation controls; plan 129 owns that.
- Token/cost budget visibility; plan 152 owns usage persistence and budget alerts.
- Agent artifact retention; plan 140 owns retention/redaction of generated artifacts.
- Changing Codex model or authentication strategy.

## Git Workflow

- Branch: `codex/codex-turn-timeouts`
- Commit message: `Add Codex turn timeouts`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add timeout configuration

Add a helper to read a default timeout such as `CODEX_TURN_TIMEOUT_SECONDS`, with a conservative value and validation.

Allow callers to override when a path legitimately needs a different limit.

### Step 2: Wrap stream collection

Use `asyncio.wait_for()` or an equivalent cancellation boundary around `_collect_turn_result()`.

When timeout occurs:

- cancel or close the SDK turn if the SDK exposes a safe method,
- raise a typed or clearly identifiable timeout error,
- avoid leaking prompt content in the error message.

### Step 3: Update callers

Conversation bot should treat timeout like a Codex failure and continue to fallback behavior.

Autonomous agent runs should finish as failed with a redacted timeout message.

Workstation generation should mark the job failed and remove partial output directories where appropriate.

### Step 4: Add tests

Use fake stream/turn objects to simulate a stream that never completes.

Cover:

- timeout raises the expected error,
- conversation fallback fires on timeout,
- agent run is marked failed,
- no raw prompt text is stored in timeout messages.

### Step 5: Update docs

Document timeout env vars, defaults, and operational meaning in README and `.env.example` if env vars are added.

## Test Plan

- Codex utility timeout tests pass.
- Conversation bot timeout/fallback tests pass.
- Backend import smoke passes.
- No live Codex call is made in tests.

## Done Criteria

- [ ] Every shared Codex SDK turn has a wall-clock timeout.
- [ ] Timeout errors are redacted and caller-visible.
- [ ] Conversation fallback and agent failure paths handle timeout explicitly.
- [ ] Tests cover a hanging stream.

## STOP Conditions

- Codex SDK does not allow safe cancellation and hanging streams leave orphaned work.
- Existing long-running Workstation jobs need a longer timeout than can be chosen safely.
- Timeout config would conflict with the launchd runner watchdog and needs operator input.

## Maintenance Notes

Retries are not a timeout. A stuck stream must have its own deadline.
