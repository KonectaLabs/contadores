---
name: codex-cli-sdk
description: Use when explaining or deciding between Codex CLI, Codex SDKs, app-server, ChatGPT authentication, API-key authentication, or Python automation around Codex.
---

# Codex CLI And SDK

Use this skill when a task needs clarity about how Codex is run from terminal,
automated from Python, authenticated, or embedded in Contadores.

## Mental Model

Codex has two local control surfaces:

- CLI: terminal UX for humans and simple automation.
- SDK: programmatic control of the local app-server runtime.

The Python SDK is not the general OpenAI Python SDK. Keep this distinction clear:

```python
from openai import OpenAI                  # General OpenAI API SDK
from codex_app_server import AsyncCodex    # Codex app-server SDK
```

The SDK controls a local Codex/app-server process. It is not a pure cloud API
client.

## CLI

Use the CLI for humans, simple shell tasks, and cron-like automation:

```bash
codex
codex "Explain this repo"
codex exec "Run tests and summarize failures"
codex exec --json "Inspect the current git diff"
```

Rules:

- Use `codex exec --json` when scripts need structured-ish CLI output.
- Do not parse the visual interactive CLI output.
- Check ChatGPT auth without accidentally using API-key auth:

```bash
env -u OPENAI_API_KEY codex login status
env -u OPENAI_API_KEY codex login --device-auth
```

## Python SDK Shape

The official Python examples in `openai/codex/sdk/python/examples` show the
public shape. Prefer the async surface in server code:

```python
from codex_app_server import AppServerConfig, AsyncCodex, TextInput

config = AppServerConfig(codex_bin="/usr/local/bin/codex", cwd="/app", env=env)

async with AsyncCodex(config=config) as codex:
    thread = await codex.thread_start(
        model="gpt-5.5",
        config={"model_reasoning_effort": "medium"},
    )
    result = await thread.run(TextInput("Say hello in one sentence."))
    print(result.final_response)
```

Thread operations:

- `thread_start(...)`: create a new thread.
- `thread_resume(thread_id, ...)`: continue an existing persisted thread.
- `thread_list(...)`: list active or archived threads.
- `thread.read(include_turns=True)`: inspect persisted turns.
- `thread.set_name(name)`: name a thread.
- `thread.compact()`: compact a long thread.
- `thread_archive(thread_id)` / `thread_unarchive(thread_id)`: lifecycle.
- `thread_fork(thread_id, ...)`: branch a thread.

Turn operations:

```python
turn = await thread.turn(TextInput("Do the task."))
result = await turn.run()
```

Use `thread.run(...)` for the simple case. Use `thread.turn(...).stream()` when
you need an active turn handle for progress, usage, steer, or interrupt:

```python
turn = await thread.turn(TextInput("Count slowly."))

async for event in turn.stream():
    if event.method == "item/agentMessage/delta":
        print(event.payload.delta, end="")
```

Controls:

```python
await turn.steer(TextInput("Keep it shorter."))
await turn.interrupt()
```

## Inputs

Use typed input items. Do not smuggle everything as plain text when the SDK has a
structured item.

```python
from codex_app_server import ImageInput, LocalImageInput, MentionInput, SkillInput, TextInput

input_items = [
    TextInput("Use this skill and image."),
    SkillInput(name="workstation-solo-page", path="/repo/.codex/skills/workstation-solo-page/SKILL.md"),
    MentionInput(name="GitHub", path="app://connector_123"),
    LocalImageInput(path="/repo/data/client/media/photo.jpg"),
    ImageInput("https://example.com/reference.png"),
]
```

## Turn Params

Important turn-level params:

- `approval_policy`: usually `AskForApproval.model_validate("never")` for backend automation.
- `sandbox_policy`: `dangerFullAccess` for trusted internal automation, or `workspaceWrite` when writes must be constrained.
- `cwd`: set explicitly. In Contadores, page work runs from repo root so Codex can read templates and skills.
- `model`: Codex model, for example `gpt-5.5`.
- `effort`: `none`, `minimal`, `low`, `medium`, `high`, or `xhigh`.
- `service_tier`: `fast`, `flex`, or `None`.
- `output_schema`: JSON schema for structured output.
- `personality`: for example `Personality.pragmatic`.
- `summary`: for example `ReasoningSummary.model_validate("concise")`.

Example:

```python
from codex_app_server import AskForApproval, Personality, ReasoningEffort, ReasoningSummary

turn = await thread.turn(
    TextInput("Return JSON for the rollout plan."),
    approval_policy=AskForApproval.model_validate("never"),
    cwd="/repo",
    effort=ReasoningEffort("medium"),
    model="gpt-5.5",
    output_schema=OUTPUT_SCHEMA,
    personality=Personality.pragmatic,
    sandbox_policy=sandbox_policy,
    summary=ReasoningSummary.model_validate("concise"),
)
```

## Errors And Retry

Use SDK typed errors and retry only retryable failures:

```python
from codex_app_server import JsonRpcError, ServerBusyError, is_retryable_error
```

Retry overload/server-busy style errors with bounded exponential backoff. Do not
retry validation bugs, bad prompts, missing files, or product rule failures.

## Contadores Backend Pattern

Contadores uses only async Codex helpers in `src/backend/codex_utils.py`.

Primary helpers:

```python
from backend.codex_utils import CodexSkill, run_codex_with_context

result = await run_codex_with_context(
    "Create the client page.",
    thread_id=client.codex_workstation_thread_id,
    skills=[CodexSkill(name="workstation-solo-page", path="/repo/.codex/skills/workstation-solo-page/SKILL.md")],
    local_images=[photo_path],
    model="gpt-5.5",
    effort="medium",
    cwd=REPO_ROOT,
)
```

`CodexTurnResult` returns:

- `final_response`
- `thread_id`
- `turn_id`
- `status`
- `error`
- `items_count`
- `usage`
- `model`
- `effort`
- `service_tier`
- `cwd`

Persist thread IDs:

- `contadores_leads.codex_conversation_thread_id` for lead conversation turns.
- `workstation_clients.codex_workstation_thread_id` for converted client work.
- `agent_runs.codex_thread_id` and `agent_runs.codex_turn_id` for audit.

Rules:

- Backend code must not call sync Codex helper APIs. They were removed.
- Do not wrap Codex SDK calls in `asyncio.to_thread` or `run_in_threadpool`.
- Use `asyncio.run(...)` only in standalone CLI scripts or subprocess tool runners.
- Keep ChatGPT and API-key auth homes isolated:
  - `CONVERSATION_BOT_CODEX_CHATGPT_HOME`
  - `CONVERSATION_BOT_CODEX_API_KEY_HOME`
- Prefer ChatGPT auth first by removing `OPENAI_API_KEY` from the Codex child env.
- Fall back to API-key auth only when configured and when the ChatGPT run fails.

## Native Tools And Images

A local probe on 2026-04-28 showed that Codex SDK + app-server + ChatGPT login
can access native image generation in a Codex run and create a real JPEG. Treat
that as a Codex runtime capability, not as the OpenAI Images API.

For deterministic product code that must call a specific image model, use the
OpenAI Images API or Responses API image tool directly. For Contadores product
work, Codex image generation is used when the task needs Codex's native toolset
and file-system workflow.
