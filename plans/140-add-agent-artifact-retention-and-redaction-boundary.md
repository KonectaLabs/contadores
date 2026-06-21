# Plan 140: Add Agent Artifact Retention And Redaction Boundary

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/ai/codex_agent_runtime.py src/backend/ai/codex_agent_tools.py src/backend/database.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/123-centralize-runtime-log-and-operator-script-redaction.md
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: RETENTION-03

## Why This Matters

Autonomous agent runs write context, memory snapshots, tool manifests, final responses, and raw tool arguments/results. Those artifacts are valuable for audit, but they can also contain lead data, client notes, prompts, and operational details.

Agent artifacts need a retention and redaction boundary separate from ordinary logs.

## Current State

- Long-lived target memory is stored under `data/agent-memory`:

```python
src/backend/ai/codex_agent_runtime.py:68
def agent_memory_path(target_type: str, target_id: str) -> Path:
```

- Each agent run writes context artifacts under `data/agent-runs`:

```python
src/backend/ai/codex_agent_runtime.py:235
run_id = uuid.uuid4().hex
```

```python
src/backend/ai/codex_agent_runtime.py:237
context_path = context_dir / "context.md"
```

- DB rows persist run and tool-call audit data:

```python
src/backend/database.py:3701
class AgentRun(SQLModel, table=True):
```

```python
src/backend/database.py:3848
class AgentToolCall(SQLModel, table=True):
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Agent artifact scan | `rg -n "agent-runs|agent-memory|AgentRun|AgentToolCall|arguments_json|result_json|final_response|redact|retention" src/backend README.md` | agent artifacts have retention/reporting boundaries |
| Agent tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "agent" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Classify agent artifacts into audit metadata, sensitive context, and durable memory.
- Add a dry-run retention report for `agent-runs`, `agent-memory`, `agent_runs`, and `agent_tool_calls`.
- Prune or compact old completed/failed run context after a configurable window.
- Redact or summarize stored tool arguments/results where possible.
- Preserve active/stale diagnostics and required audit metadata.

**Out of scope**:
- Runtime log redaction; plan 123 owns general runtime/log output.
- Follow-up runner report retention; plan 096 owns runner report artifacts.
- Agent stale-run detection; plan 073 owns runtime diagnostics.

## Git Workflow

- Branch: `codex/agent-artifact-retention`
- Commit message: `Add agent artifact retention boundary`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define artifact classes

Document which fields/files are:

- required audit metadata,
- sensitive context that can expire,
- durable product memory,
- tool arguments/results that need redaction or compaction.

### Step 2: Add retention report

Add a dry-run command or helper that counts candidate files and DB rows by class, age, run status, and target.

Do not delete anything until the report is legible.

### Step 3: Prune or compact completed run context

For old completed/failed runs, remove or compact `context.md`, `memory.md`, and `tools.json` while preserving enough metadata to understand the run.

Never prune active run context.

### Step 4: Redact tool arguments/results

Apply the redaction helper from plan 123 where raw tool arguments/results are serialized or displayed.

Prefer compact summaries for old rows over full payload retention.

### Step 5: Add tests and docs

Test dry-run reporting, active preservation, old completed pruning, and redaction behavior.

Document retention defaults and operator override env vars.

## Test Plan

- Agent-focused tests pass.
- Backend import smoke passes.
- Dry-run report can be run locally without deleting files.

## Done Criteria

- [ ] Agent artifacts have documented retention classes.
- [ ] Dry-run retention report exists.
- [ ] Old completed run context can be pruned or compacted safely.
- [ ] Tool arguments/results use shared redaction where exposed or retained long term.

## STOP Conditions

- Product owner needs indefinite raw agent context retention.
- DB payload redaction would break required audit/debug workflows.
- Active run detection is unreliable.

## Maintenance Notes

Keep enough audit trail to understand what happened, but do not keep raw context forever by accident.
