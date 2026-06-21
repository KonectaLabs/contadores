# Plan 056: Enforce Codex Agent Tool Idempotency In CLI

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/agent.py src/backend/ai/codex_agent_runtime.py src/backend/ai/codex_agent_tools.py src/backend/tests/test_agent_api.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/031-modularize-agent-tool-registry.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-06

## Why This Matters

HTTP agent tool calls dedupe by `idempotency_key`, but autonomous Codex CLI tool calls go directly to `call_tool()`. If a CLI run retries or repeats a tool with the same idempotency key, it can duplicate queued WhatsApp messages, Workstation public page links, or other side effects.

## Current State

- HTTP endpoint checks idempotency first:

```python
src/backend/endpoints/agent.py:691
duplicate = _idempotent_tool_call(
```

- CLI runtime calls the tool directly:

```python
src/backend/ai/codex_agent_runtime.py:341
from backend.ai.codex_agent_tools import call_tool
```

- `call_tool()` reads the idempotency key but does not enforce the HTTP duplicate guard:

```python
src/backend/ai/codex_agent_tools.py:3157
idempotency_key = str(arguments.get("idempotency_key") or "").strip() or None
```

- Side-effect tools queue WhatsApp and Workstation actions:

```python
src/backend/ai/codex_agent_tools.py:2409
def send_whatsapp_text(arguments: dict[str, Any]) -> dict[str, Any]:
```

```python
src/backend/ai/codex_agent_tools.py:2967
def send_workstation_public_page_link(arguments: dict[str, Any]) -> dict[str, Any]:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Agent API tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_api.py -q` | exit 0 |
| Contadores tool tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "codex_agent_tool or workstation_public_page_link" -q` | exit 0 |

## Scope

**In scope**:
- Move idempotency enforcement into a shared tool-call layer used by HTTP and CLI.
- Preserve existing audit rows.
- Add tests for duplicate CLI tool calls.

**Out of scope**:
- Changing tool schemas.
- Removing HTTP idempotency behavior.
- Broad tool registry refactor beyond plan 031.

## Git Workflow

- Branch: `codex/codex-cli-tool-idempotency`
- Commit message: `Enforce Codex CLI tool idempotency`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extract shared duplicate lookup

Move the HTTP duplicate detection into a helper that can be used before any side-effect tool call, regardless of transport.

Keep return shape compatible with HTTP responses.

### Step 2: Enforce inside `call_tool()`

When `arguments.idempotency_key` is present, `call_tool()` should return the existing successful or in-progress tool-call audit instead of executing the handler again.

Be careful with failed attempts: decide whether retries should re-run failed tool calls or return the failure. Document with tests.

### Step 3: Preserve audit semantics

The duplicate response should still be auditable and should not create misleading new side-effect rows.

Do not hide duplicates from logs; mark them as duplicate.

### Step 4: Add tests

Cover:

- HTTP duplicate still works,
- CLI duplicate does not queue a second WhatsApp text,
- CLI duplicate does not queue a second Workstation public page link,
- failed tool-call retry behavior matches the documented choice.

## Test Plan

- Run Agent API tests.
- Run targeted Contadores tool tests.
- Run backend import smoke.

## Done Criteria

- [ ] HTTP and CLI tool calls share idempotency enforcement.
- [ ] Duplicate CLI side-effect tool calls do not repeat side effects.
- [ ] Tests cover WhatsApp and Workstation side effects.
- [ ] Failure retry behavior is explicit.

## STOP Conditions

- Existing autonomous Codex runs rely on repeating same-key tools.
- Tool-call audit schema cannot represent duplicates clearly.
- Plan 031 changes the tool-call path in a conflicting way.

## Maintenance Notes

Idempotency must live at the side-effect boundary, not only at one HTTP route.
