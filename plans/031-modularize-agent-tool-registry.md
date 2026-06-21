# Plan 031: Introduce Agent Tool Registration Object

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/ai/codex_agent_tools.py src/backend/endpoints/agent.py src/backend/tests/test_agent_api.py src/backend/tests/test_client_lead_delivery.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/024-wire-ci-and-test-dependencies.md
- **Category**: architecture
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The autonomous agent tool registry is a 3208-line module. Specs, argument models, handlers, audit target mapping, platform tools, Meta tools, lead tools, and Workstation tools are coupled in one file. The safest first step is to introduce one cohesive registration object in the existing file before moving code across module boundaries.

## Current State

- Tool specs are one long list:

```python
src/backend/ai/codex_agent_tools.py:671
def tool_specs() -> list[CodexAgentToolSpec]:
    """Return the toolbelt exposed to Codex."""
    specs: list[tuple[str, str, type[BaseModel]]] = [
```

- Handlers are a separate long dictionary:

```python
src/backend/ai/codex_agent_tools.py:3029
TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
```

- Audit target mapping is another long conditional:

```python
src/backend/ai/codex_agent_tools.py:3089
def _audit_target_for_tool(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str]:
```

- `/api/agent/tools` consumes `tool_specs()` directly:

```python
src/backend/endpoints/agent.py:274
def _tool_manifest() -> list[dict[str, Any]]:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Agent API tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_api.py -q` | exit 0 |
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Introduce a same-file registration object that pairs specs, handlers, run-awareness, and audit target resolvers.
- Convert one small domain first, then only convert additional same-file entries if the diff stays easy to review.
- Preserve `tool_specs()` and `call_tool()` public behavior.
- Add tests that compare manifest names before/after the registration object.

**Out of scope**:
- Adding or removing tools.
- Changing argument schemas.
- Changing audit row shape.
- Changing agent endpoint routes.
- Moving tool domains into new modules; plan 038 covers that follow-up.

## Git Workflow

- Branch: `codex/agent-tool-registration-object`
- Commit message: `Introduce agent tool registration object`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a registry object

Introduce a small internal structure such as:

```python
@dataclass(frozen=True)
class ToolRegistration:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[..., dict[str, Any]]
    audit_target: Callable[[dict[str, Any]], tuple[str, str]] | None = None
    run_aware: bool = False
```

Keep it in the existing file at first to reduce import churn.

### Step 2: Convert one small domain

Convert a small domain first, such as platform config tools. Keep the conversion in `src/backend/ai/codex_agent_tools.py`.

Confirm:

- `tool_specs()` returns the same names and schemas,
- `TOOL_HANDLERS` lookup still works or is replaced by the registration map,
- run-aware tools stay run-aware.

Do not keep expanding if the diff becomes hard to review. Leave the remaining legacy entries intact and document the next safe domain to convert.

### Step 3: Preserve legacy compatibility

If not every tool is converted, keep a compatibility path that combines registered tools with existing specs and handlers. The manifest order should stay stable unless a test explicitly documents the new order.

### Step 4: Add compatibility tests

Add tests that assert:

- expected tool names are present,
- each registered tool has a handler,
- each registered tool has an audit target fallback,
- `/api/agent/tools` output shape is unchanged.

## Test Plan

- Agent API tests.
- Campaign and Delivery tests for tool-backed flows.
- Backend import smoke.

## Done Criteria

- [ ] At least one low-risk tool domain uses cohesive registrations for specs, handlers, run-aware flags, and audit targets.
- [ ] `/api/agent/tools` response shape is unchanged.
- [ ] Existing tool call behavior is unchanged.
- [ ] Agent API, campaign, and Delivery tests exit 0.

## STOP Conditions

- The registration object requires broad endpoint imports or creates circular imports.
- Tool schemas change as a side effect of the refactor.
- Audit target defaults become less specific.

## Maintenance Notes

This is a preservation refactor. The safest first review is a before/after manifest diff. Do not move domains into new files until plan 038.
