# Plan 152: Persist Codex Run Usage And Budgets

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/codex_utils.py src/backend/ai/codex_agent_runtime.py src/backend/database.py src/backend/endpoints/platform.py src/backend/tests .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/020-add-migration-discipline-for-production-schema-changes.md
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CODEX-RUNTIME-02

## Why This Matters

Codex turn usage is collected from stream notifications but is not persisted on agent runs or exposed to operators. Without usage and budget visibility, live agent runs can become expensive without a dashboard signal, alert, or durable audit trail.

Agent runs should keep compact usage metadata and compare it against soft/hard budget thresholds.

## Current State

- Usage is collected during stream processing:

```python
src/backend/codex_utils.py:522
if isinstance(payload, sdk["ThreadTokenUsageUpdatedNotification"]) and payload.turn_id == turn.id:
    usage = payload.token_usage
```

- Usage is returned in the Codex turn result:

```python
src/backend/codex_utils.py:541
"usage": usage,
```

- Agent runs finish without persisting usage:

```python
src/backend/ai/codex_agent_runtime.py:304
AgentRun.finish(
```

- `AgentRun` has no usage/cost fields:

```python
src/backend/database.py:3701
class AgentRun(SQLModel, table=True):
```

- Platform run responses expose no usage:

```python
src/backend/endpoints/platform.py:72
class PlatformAgentRunResponse(BaseModel):
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Usage scan | `rg -n "token_usage|usage|AgentRun|PlatformAgentRunResponse|budget|cost|codex_result" src/backend src/backend/tests .env.example README.md` | usage persistence and budget checks are visible |
| Platform/agent tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "agent_run or platform or token_usage or budget" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Persist compact Codex usage JSON on `AgentRun`.
- Expose usage and estimated cost/threshold status in platform/API responses.
- Add configurable soft and hard run-budget thresholds.
- Alert or fail closed when a run crosses hard budget if the provider supplies usable usage data early enough.
- Keep usage payload redacted and bounded.
- Add tests with fake usage objects.

**Out of scope**:
- Wall-clock timeouts; plan 150 owns hanging stream behavior.
- Provider billing reconciliation outside Codex usage notifications.
- Agent artifact retention; plan 140 owns retention.
- Schema changes before migration discipline; wait for plan 020 if fields/table changes are needed.

## Git Workflow

- Branch: `codex/persist-codex-run-usage`
- Commit message: `Persist Codex run usage and budgets`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose storage shape

Prefer a small bounded JSON field such as `usage_json` plus optional normalized numeric fields if the schema/migration plan allows it.

Store only token counts, model/provider identifiers, and computed budget status. Do not store prompts or responses in usage metadata.

### Step 2: Persist usage on finish/failure

Update `AgentRun.finish()` and failure paths so successful and failed runs persist any available usage.

If no usage is available, expose that as absent rather than zero.

### Step 3: Add budget thresholds

Add soft/hard env configuration with documented defaults. Start with alert-only soft budget.

If a hard budget can be checked before or during a turn, fail closed with a redacted error. If usage only arrives after completion, record hard-budget breach and alert.

### Step 4: Expose to operators

Update platform serializers and frontend-visible responses with compact usage and budget status. Keep previews bounded.

### Step 5: Add tests

Use fake Codex result usage to prove:

- usage persists,
- API response includes usage status,
- soft threshold produces an alert/status,
- hard threshold behavior is explicit.

## Test Plan

- Platform/agent tests pass.
- Backend import smoke passes.
- No live Codex call is made.

## Done Criteria

- [ ] Agent runs persist bounded usage metadata.
- [ ] Operators can see usage and budget status for runs.
- [ ] Budget thresholds are documented and tested.
- [ ] Usage metadata does not include prompt or raw tool payloads.

## STOP Conditions

- Plan 020 migration discipline has not landed and this needs a schema change.
- Codex usage notification shape is unstable and cannot be normalized safely.
- Product owner needs exact billing cost but model pricing cannot be verified.

## Maintenance Notes

Usage observability should be compact and durable. It is an operational budget signal, not another artifact dump.
