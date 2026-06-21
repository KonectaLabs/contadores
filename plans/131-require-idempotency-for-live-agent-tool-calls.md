# Plan 131: Require Idempotency For Live Agent Tool Calls

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/agent.py src/backend/agent_cli.py src/backend/ai/codex_agent_tools.py src/backend/tests/test_agent_api.py src/backend/tests/test_agent_cli.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/056-enforce-codex-agent-tool-idempotency-in-cli.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AGENT-01

## Why This Matters

The generic Agent API tool endpoint can execute side-effect tools with `dry_run` defaulting to false and no required idempotency key. A retry, duplicate CLI invocation, or agent loop can repeat live effects such as WhatsApp sends, follow-up scheduling, public-page links, or Meta publish actions.

Plan 056 makes duplicate detection work when a key is present. This plan closes the adjacent contract gap: live side-effect tool calls should not be accepted without an explicit idempotency/live-execution boundary.

## Current State

- Generic tool calls default to live execution, and the idempotency key is optional:

```python
src/backend/endpoints/agent.py:148
class AgentToolCallCommand(BaseModel):
```

```python
src/backend/endpoints/agent.py:152
dry_run: bool = False
```

```python
src/backend/endpoints/agent.py:153
idempotency_key: str | None = Field(default=None, max_length=240)
```

- Duplicate detection is bypassed when the request has no idempotency key:

```python
src/backend/endpoints/agent.py:691
duplicate = _idempotent_tool_call(
```

```python
src/backend/endpoints/agent.py:704
payload = call_tool(run_id=run_id, tool_name=clean_tool_name, arguments=arguments)
```

- The generic endpoint forwards whatever the caller supplied:

```python
src/backend/endpoints/agent.py:1103
@agent_router.post("/runs/{run_id}/tools/{tool_name}")
```

```python
src/backend/endpoints/agent.py:1111
if command.idempotency_key and not arguments.get("idempotency_key"):
```

- CLI commands expose optional idempotency keys while defaulting to live writes:

```python
src/backend/agent_cli.py:561
idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
```

```python
src/backend/agent_cli.py:562
dry_run: bool = typer.Option(False, "--dry-run"),
```

```python
src/backend/agent_cli.py:785
idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
```

- Current tests reject unknown tools but do not reject missing idempotency on live calls:

```python
src/backend/tests/test_agent_api.py:210
unknown_tool = client.post(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Agent tool contract scan | `rg -n "AgentToolCallCommand|dry_run: bool = False|idempotency_key|_call_tool_or_raise|runs/.*/tools|tool_specs" src/backend/endpoints/agent.py src/backend/agent_cli.py src/backend/ai/codex_agent_tools.py src/backend/tests` | live side-effect calls require an idempotency key or explicit safe classification |
| Agent API tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_api.py -q` | exit 0 |
| Agent CLI tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_cli.py -q` | exit 0 |

## Scope

**In scope**:
- Classify Agent API tools as read-only, dry-run-only, or live side-effect tools.
- Require an idempotency key for non-dry-run side-effect tool calls.
- Preserve read-only tool calls without unnecessary keys.
- Update CLI commands and help text so live side-effect commands generate or require stable keys.
- Add tests that live side-effect calls without keys fail before executing handlers.

**Out of scope**:
- Implementing duplicate enforcement itself; plan 056 owns the shared enforcement path.
- Replacing Agent API auth; plans 079 and 080 own auth boundaries.
- Changing Meta publish business rules; plans 057, 058, 084, 102, 105, 107, and 130 own those flows.

## Git Workflow

- Branch: `codex/require-agent-tool-idempotency`
- Commit message: `Require idempotency for live agent tool calls`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add tool effect metadata

Add a small readable map or metadata field that classifies every allowed Agent API tool by effect:

- `read`: no persisted or provider side effect,
- `side_effect`: writes local state, queues messages, writes files, or calls providers,
- `provider_write`: live external provider mutation.

Keep the metadata close to the tool manifest so future tools cannot be exposed without a classification.

### Step 2: Reject live side-effect calls without idempotency

In `_call_tool_or_raise`, before execution, require a non-empty idempotency key for non-dry-run `side_effect` and `provider_write` tools. Return a 400 with a concise message before the handler runs.

If a tool is classified `provider_write`, also require the existing live-write confirmation arguments that tool already expects; do not invent a parallel confirmation system.

### Step 3: Update direct Agent API wrappers

Review wrappers such as outbound message send, follow-up scheduling, notes, tags, and conversation updates. Either require caller-supplied idempotency keys for live side effects or derive stable keys from run id, target id, action, and content where retry semantics are clear.

Do not make non-repeatable content share the same derived key accidentally.

### Step 4: Update CLI behavior

Update CLI commands that can cause side effects so they either:

- require `--idempotency-key`, or
- generate and print a deterministic key when the command has enough stable inputs.

Keep `--dry-run` ergonomic for exploration.

### Step 5: Add regression tests

Add tests proving:

- generic live side-effect tool call without idempotency is rejected,
- generic live side-effect tool call with idempotency still works,
- read-only tool calls do not need a key,
- CLI request payloads include or require idempotency for side-effect commands.

## Test Plan

- Agent API tests pass.
- Agent CLI tests pass.
- Manual route scan shows no live side-effect tool path can execute without an idempotency key.

## Done Criteria

- [ ] Every exposed Agent API tool has an effect classification.
- [ ] Live side-effect tool calls require idempotency before execution.
- [ ] CLI side-effect commands provide a clear idempotency contract.
- [ ] Tests cover missing-key rejection and allowed read-only calls.

## STOP Conditions

- Plan 056 has not landed and duplicate enforcement still only works on one transport.
- A live side-effect tool cannot be retried safely even with an idempotency key.
- Tool metadata cannot be kept in sync with the actual allowed manifest without a broader registry refactor.

## Maintenance Notes

Agent-facing live actions need an execution contract as much as they need auth. When adding a new side-effect tool, add the idempotency rule and tests in the same change.
