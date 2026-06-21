# Plan 038: Move Agent Tool Domains Into Modules

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/ai/codex_agent_tools.py src/backend/endpoints/agent.py src/backend/tests/test_agent_api.py src/backend/tests/test_client_lead_delivery.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/031-modularize-agent-tool-registry.md
- **Category**: architecture
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: ARCH-04B

## Why This Matters

Plan 031 only introduces the registration object in the existing file. Once that compatibility layer exists, the repo can move one tool domain at a time into small modules without changing the endpoint contract or audit behavior.

## Current State

- Tool specs currently live in one long function:

```python
src/backend/ai/codex_agent_tools.py:671
def tool_specs() -> list[CodexAgentToolSpec]:
    """Return the toolbelt exposed to Codex."""
```

- Handlers and audit targets are also centralized:

```python
src/backend/ai/codex_agent_tools.py:3029
TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
```

```python
src/backend/ai/codex_agent_tools.py:3089
def _audit_target_for_tool(tool_name: str, arguments: dict[str, Any]) -> tuple[str, str]:
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
- Move one registered tool domain into a new module.
- Preserve manifest output, handlers, run-aware behavior, and audit targets.
- Add compatibility tests around the moved domain.

**Out of scope**:
- Moving every domain in one PR.
- Adding or removing tools.
- Changing argument schemas.
- Changing `/api/agent/tools` response shape.
- Changing agent run or audit persistence.

## Git Workflow

- Branch: `codex/move-agent-tool-domain-modules`
- Commit message: `Move one agent tool domain into a module`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Confirm plan 031 landed cleanly

Before moving files, confirm the registration object exists and the manifest compatibility tests pass.

If plan 031 was skipped or only partially landed, stop. Do not combine both refactors.

### Step 2: Pick one low-risk domain

Start with the domain converted in plan 031 if it is still the smallest one. Prefer a domain that:

- has few handlers,
- has no endpoint imports,
- has simple audit targets,
- has existing tests.

Do not start with Workstation, campaigns, or Meta publish tools unless they are already isolated by prior work.

### Step 3: Create one clear module boundary

Create a small module under a clear package such as `src/backend/ai/tools/`.

The module should export one registration list or builder. Keep imports one-way:

- domain module imports shared registration types,
- `codex_agent_tools.py` imports domain registrations,
- endpoint modules do not import domain modules.

### Step 4: Preserve manifest and call behavior

Add or update tests that assert:

- the moved tool names are present,
- the argument schemas are unchanged,
- handlers are callable through `call_tool()`,
- audit targets are unchanged for representative arguments,
- `/api/agent/tools` output shape is unchanged.

### Step 5: Leave the next domain explicit

At the end of the PR, document the next safest domain to move in a comment or follow-up issue. Do not opportunistically move a second domain unless the diff remains very small.

## Test Plan

- Run Agent API tests.
- Run Campaign tests.
- Run Delivery tests.
- Run backend import smoke.
- Inspect imports for circular dependency risk.

## Done Criteria

- [ ] One low-risk tool domain lives outside `codex_agent_tools.py`.
- [ ] `codex_agent_tools.py` still owns the public `tool_specs()` and `call_tool()` entrypoints.
- [ ] Manifest and audit-target behavior are preserved by tests.
- [ ] No endpoint module imports the new tool domain directly.

## STOP Conditions

- Moving the domain creates circular imports.
- Manifest order or schemas change unexpectedly.
- The selected domain needs broad endpoint or database import changes.
- The diff starts moving multiple unrelated domains.

## Maintenance Notes

Move one domain per review. The point is to make future tool additions safer, not to land a large architecture diff.
