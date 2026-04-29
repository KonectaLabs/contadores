---
name: codex-cli-sdk
description: Use when explaining or deciding between Codex CLI, Codex SDKs, app-server, ChatGPT authentication, API-key authentication, or Python automation around Codex.
---

# Codex CLI And SDK

Use this skill when a task needs clarity about how Codex is run from terminal, automated from Python or TypeScript, or authenticated.

## Mental Model

Codex has two practical local control surfaces:

- CLI: a terminal interface for humans and simple automation.
- SDK: a programmatic interface for applications and scripts.

The CLI and SDK both control Codex, but they are not the same interface.

## CLI

The CLI is the normal terminal experience.

```text
human or script -> codex CLI -> Codex
```

Typical use:

```bash
codex
codex "Explain this repo"
codex exec "Run tests and summarize failures"
codex exec --json "Inspect the current git diff"
```

Important rules:

- The CLI does not need a GUI app.
- The CLI can be used interactively by a human.
- `codex exec` is the better CLI path for non-interactive scripts and CI.
- For very simple automation, calling `codex exec --json` from a script can be enough.
- Do not parse the visual interactive CLI output when structured output is needed.

## SDK

The SDK is the programmatic interface.

```text
Python or TypeScript code -> Codex SDK -> local app-server -> Codex
```

The Python SDK is official OpenAI Codex code, but it is experimental. It is not the same package as the general OpenAI Python API SDK.

Distinguish these clearly:

- General OpenAI Python SDK: `from openai import OpenAI`
- Codex Python SDK: `from codex_app_server import Codex`

The Codex SDK should be described as a controller for local Codex/app-server, not as a pure cloud API client.

## Native Tools In Codex Runs

The Codex SDK can expose the tools available to a Codex run through app-server. In a local probe on 2026-04-28 with:

- `codex-cli 0.125.0`;
- ChatGPT login, not `OPENAI_API_KEY`;
- Python SDK installed from the official `openai/codex` repo;

Codex reported that a native image generation tool was available and successfully created a real JPEG at `imagen.jpg`.

Interpret this carefully:

- The SDK can drive a Codex run that has native image generation available.
- This is not the same as calling the OpenAI Images API directly.
- The model used by the native image tool was not exposed through the SDK result.
- Do not claim it is specifically `gpt-image-2` unless the runtime or official docs expose that model name.
- For deterministic product code that must request `gpt-image-2`, use the OpenAI API image generation endpoints or Responses API image generation tool.

## Local Probe Evidence

This repo contains a concrete probe created on 2026-04-28:

- reusable helper: `src/backend/codex_utils.py`
- script: `scripts/probes/codex_sdk_image_probe.py`
- generated image: `imagen.jpg`
- captured result: `codex_sdk_image_probe_result.json`

Observed result:

```json
{
  "final_response": "`imagen.jpg` was created at `/Users/fgoiriz/private/repos/contadores/imagen.jpg`.\n\nI used the native image generation tool in this Codex run and converted the generated image to JPG in place.",
  "image_path": "/Users/fgoiriz/private/repos/contadores/imagen.jpg",
  "image_exists": true,
  "image_size_bytes": 243653,
  "items_count": 16
}
```

File verification:

```text
imagen.jpg: JPEG image data, JFIF standard 1.01, baseline, precision 8, 1536x1024, components 3
```

The image was a real generated JPEG matching the prompt about an Argentine accountant using a modern WhatsApp automation dashboard.

## Reproduce The SDK Probe

Use this recipe when testing whether the Codex SDK/app-server path can access native tools through ChatGPT authentication.

Check the installed CLI:

```bash
codex --version
codex app-server --help
```

If the installed CLI is too old and does not expose `app-server`, update it:

```bash
npm install -g @openai/codex@latest
```

Check ChatGPT authentication without falling back to API key:

```bash
env -u OPENAI_API_KEY codex login status
```

Expected output when the ChatGPT path is active:

```text
Logged in using ChatGPT
```

If it is not authenticated with ChatGPT, start login without `OPENAI_API_KEY`:

```bash
env -u OPENAI_API_KEY codex login
```

The SDK package was not available from the normal Python registry during the 2026-04-28 probe. Installing from the official repo worked:

```bash
uv run --with "openai-codex-app-server-sdk @ git+https://github.com/openai/codex.git#subdirectory=sdk/python" \
  python -c "from codex_app_server import Codex, AppServerConfig; print('ok')"
```

Run the local image probe:

```bash
uv run --with "openai-codex-app-server-sdk @ git+https://github.com/openai/codex.git#subdirectory=sdk/python" \
  python scripts/probes/codex_sdk_image_probe.py
```

The probe deliberately:

- removes `OPENAI_API_KEY` from the SDK child environment;
- points `AppServerConfig(codex_bin=...)` at `/opt/homebrew/bin/codex`;
- uses ChatGPT login state;
- asks Codex to use only a native image generation tool;
- forbids OpenAI API image calls, local drawing libraries, downloads, screenshots, and placeholders;
- writes a JSON result file with `image_exists`, `image_size_bytes`, and `final_response`.

The critical SDK shape used by the probe:

```python
from backend.codex_utils import ask_codex, run_codex

response = ask_codex("Reply with exactly: codex utils ok")
result = run_codex("Create or edit files as needed")
```

The helper wraps this lower-level shape:

```python
from codex_app_server import AppServerConfig, AskForApproval, Codex, SandboxPolicy
from codex_app_server.generated.v2_all import (
    AskForApprovalValue,
    DangerFullAccessSandboxPolicy,
)

config = AppServerConfig(codex_bin=codex_bin, cwd=str(cwd), env=env)

with Codex(config) as codex:
    thread = codex.thread_start(model=model)
    result = thread.run(
        prompt,
        approval_policy=AskForApproval(root=AskForApprovalValue.never),
        sandbox_policy=SandboxPolicy(
            root=DangerFullAccessSandboxPolicy(type="dangerFullAccess")
        ),
    )
```

By default, `backend.codex_utils`:

- removes `OPENAI_API_KEY` from the child environment to prefer ChatGPT login;
- uses `codex` from `CODEX_BIN`, `PATH`, or `/opt/homebrew/bin/codex`;
- uses model `gpt-5.5`;
- uses reasoning effort `medium`;
- never asks for approval;
- gives Codex `dangerFullAccess`;
- returns either plain text via `ask_codex` or metadata via `run_codex`.
- supports structured app mentions via `ask_codex_with_mentions` and `run_codex_with_mentions`.
- can list app/connectors via `list_codex_apps` and `find_codex_app`.

Codex SDK run-level configuration exposed by the helper:

```python
response = ask_codex(
    "Do the task",
    model="gpt-5.5",
    effort="medium",
    service_tier="fast",
)
```

Structured mention helper:

```python
from backend.codex_utils import (
    CodexMention,
    ask_codex_with_mentions,
    find_codex_app,
)

github = find_codex_app("GitHub")
if github is not None:
    response = ask_codex_with_mentions(
        "Read-only test. Do not use shell. Is GitHub usable?",
        [CodexMention(name=github.name, path=github.mention_path)],
    )
```

App discovery helper:

```python
from backend.codex_utils import list_codex_apps

apps = list_codex_apps(query="github")
for app in apps:
    print(app.name, app.mention_path, app.is_enabled, app.is_accessible)
```

Notes:

- `model` selects the Codex model.
- `effort` maps to the SDK `ReasoningEffort` enum: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`.
- The SDK does not expose a generic `speed` parameter.
- It does expose `service_tier`, currently `fast` or `flex`.
- Leave `service_tier=None` unless there is a concrete reason to force a tier.

## Interpretation Of Image Access

The probe established this local fact:

```text
Codex SDK + app-server + ChatGPT login can drive a Codex run that has native image generation available.
```

It did not establish:

```text
The native tool definitely used gpt-image-2.
```

Reason: the SDK result exposed the final response and thread items, but not the exact image model name used by the native tool.

Practical guidance:

- For internal Codex automation, it is reasonable to use the SDK/app-server path and ask Codex to generate image files when native image tools are available.
- For product code that must choose a specific model like `gpt-image-2`, use the OpenAI API directly.
- Keep wording precise: say "native image generation tool in this Codex run", not "GPT Image 2", unless a future runtime exposes the exact model.

## Plugin And Connector Probe

A second probe was added on 2026-04-28:

- script: `scripts/probes/codex_sdk_plugin_probe.py`
- captured result: `codex_sdk_plugin_probe_result.json`

The probe used Codex SDK through app-server with ChatGPT login, `OPENAI_API_KEY` removed from the child environment, model `gpt-5.5`, effort `medium`, `approval_policy=never`, `dangerFullAccess`, and read-only prompt rules.

It asked the SDK-launched Codex run whether it had access to plugin/app/connector discovery and whether GitHub or Cloudflare authenticated read-only tools were visible.

Observed final response:

```json
{
  "tool_discovery_available": false,
  "github_tools_visible": false,
  "github_authenticated_read_succeeded": null,
  "cloudflare_tools_visible": false,
  "cloudflare_authenticated_read_succeeded": null,
  "evidence": [
    "No plugin/app connector discovery tool such as tool_search is exposed in this run.",
    "No GitHub MCP/app tool namespace is visible among callable tools.",
    "No Cloudflare MCP/app tool namespace is visible among callable tools.",
    "No harmless authenticated read-only GitHub or Cloudflare connector check was available to call."
  ],
  "conclusion": "This Codex run does not expose usable GitHub or Cloudflare connector tools for authenticated read-only checks."
}
```

The SDK result contained only a user message, a reasoning item, and a final agent message. No tool call item appeared.

Interpretation:

- The Codex SDK/app-server run did not inherit this Codex Desktop thread's loaded app/plugin tools.
- Specifically, it did not see `tool_search`, GitHub connector tools, or Cloudflare connector tools.
- ChatGPT authentication alone was not enough to expose those account plugins inside the SDK-launched run.
- Native image generation being available does not imply app/plugin connectors are available.

Practical guidance:

- Do not assume Codex SDK has access to Codex Desktop plugins/apps/connectors.
- If a SDK-launched agent needs GitHub or Cloudflare, wire those capabilities explicitly through CLI tools, MCP config, API clients, or environment credentials.
- Keep plugin-sensitive workflows in the parent Codex session unless there is a verified SDK/MCP bridge for that specific plugin.

## CLI Plugins, MCPs, And Mentions

Follow-up CLI probes on 2026-04-28 showed a more nuanced picture.

Local CLI feature/config facts:

```bash
codex features list
codex mcp list
codex mcp get cloudflare-api
```

Observed:

- `plugins` feature was enabled.
- `apps` feature was enabled.
- `tool_search` feature was enabled.
- `cloudflare-api` existed as an enabled MCP server with OAuth auth.
- GitHub did not appear in `codex mcp list` as a local MCP server.
- Enabled plugins were visible in `~/.codex/config.toml`, including `github@openai-curated` and `cloudflare@openai-curated`.

Non-interactive CLI probe:

```bash
env -u OPENAI_API_KEY codex -a never exec --json -m gpt-5.5 \
  -s danger-full-access -C /Users/fgoiriz/private/repos/contadores \
  -o codex_cli_plugin_probe_result.json - < /tmp/codex_cli_tools_prompt.txt
```

Observed:

- The run saw plugin/skill context.
- It did not expose direct GitHub or Cloudflare connector/app tool namespaces as callable tools.
- It fell back to shell commands:
  - `gh auth status` succeeded.
  - `wrangler whoami` failed.
- The Cloudflare MCP attempted to start but failed with `TokenRefreshFailed("Failed to parse server response")`.

Mention syntax probe:

```text
@github @cloudflare
```

Observed final response:

```json
{
  "at_syntax_recognized": false,
  "github_native_tool_visible": false,
  "github_native_read_succeeded": false,
  "cloudflare_native_tool_visible": false,
  "cloudflare_native_read_succeeded": false,
  "conclusion": "Mentioning @github and @cloudflare did not make native GitHub or Cloudflare tools callable here."
}
```

Interpretation:

- Plain text `@github` or `@cloudflare` inside a CLI prompt did not activate native connector tools.
- CLI can load plugin configuration and skills, but that is not the same as getting a callable connector namespace.
- MCP servers are separate from ChatGPT connectors/apps. They need their own auth state.
- For Cloudflare MCP, re-auth can be started with:

```bash
codex mcp login cloudflare-api
```

This opens a browser OAuth URL. In the 2026-04-28 probe, the login was intentionally stopped before completion.

## SDK App List And Structured Mentions

The SDK/app-server can call lower-level app APIs directly through `AppServerClient.request`.

This worked:

```python
from codex_app_server import AppServerClient, AppServerConfig
from codex_app_server.generated.v2_all import AppsListResponse

client = AppServerClient(config)
client.start()
client.initialize()
response = client.request(
    "app/list",
    {"cursor": None, "limit": 100, "forceRefetch": True},
    response_model=AppsListResponse,
)
client.close()
```

Observed app-list matches:

```json
[
  {
    "id": "connector_76869538009648d5b282a4bb21c3d157",
    "name": "GitHub",
    "description": "Access repositories, issues, and pull requests. Required for some features such as Codex",
    "isAccessible": false,
    "isEnabled": true
  },
  {
    "id": "connector_2128aebfecb84f64a069897515042a44",
    "name": "Gmail",
    "isAccessible": false,
    "isEnabled": true
  },
  {
    "id": "connector_947e0d954944416db111db556030eea6",
    "name": "Google Calendar",
    "isAccessible": false,
    "isEnabled": true
  }
]
```

Structured mention input was also accepted by the SDK:

```python
from codex_app_server import MentionInput, TextInput

input_items = [
    TextInput("Read-only test. Do not use shell. Is GitHub usable?"),
    MentionInput(
        name="GitHub",
        path="app://connector_76869538009648d5b282a4bb21c3d157",
    ),
]

result = thread.run(input_items, ...)
```

Observed final response:

```json
{
  "usable": false,
  "reason": "No GitHub app connector tool is available in this session; shell use was disallowed."
}
```

Interpretation:

- There is a real SDK mechanism for app mentions: pass `MentionInput(name=..., path="app://...")`.
- This is different from writing `@github` as plain text.
- App list can show a connector as `isEnabled=true` but `isAccessible=false`.
- In this state, the SDK can mention the app but still cannot use it as an authenticated callable connector.

The repo helper now wraps this:

```python
from backend.codex_utils import CodexMention, ask_codex_with_mentions, list_codex_apps

github = list_codex_apps(query="github")[0]
response = ask_codex_with_mentions(
    "Read-only test. Do not use shell. Is this app usable?",
    [CodexMention(name=github.name, path=github.mention_path)],
)
```

Live helper test after adding the wrapper:

```text
apps [('GitHub', 'app://connector_76869538009648d5b282a4bb21c3d157', True, False)]
```

The follow-up run still did not make GitHub usable because the connector was not accessible.

## Sharing Auth With SDK

The SDK/app-server already shares the same local Codex home by default when using the same user and `CODEX_HOME`:

- ChatGPT auth is shared through local Codex auth state.
- CLI config is read from `~/.codex/config.toml`.
- MCP config is read from the same Codex config.
- Plugin/app marketplace metadata can be listed by app-server.

But this does not mean the SDK inherits the live parent Codex Desktop thread's tools.

What can be shared:

- Codex ChatGPT login.
- Local Codex config.
- MCP server definitions.
- Completed MCP OAuth credentials, if configured and valid for app-server/CLI.

What does not appear to be shared automatically:

- This exact conversation's loaded tool namespaces.
- Desktop-only connector tool handles.
- A connector that appears in `app/list` but is `isAccessible=false`.

Practical answer:

- There is no observed way to "pass this current parent session" wholesale into the SDK.
- The closest correct approach is to start the SDK app-server with the same `CODEX_HOME`, then explicitly list apps, pass structured `MentionInput`, and separately authenticate MCPs/connectors that are not accessible.
- For Cloudflare MCP specifically, use `codex mcp login cloudflare-api` and rerun the probe after OAuth completes.
- For GitHub, if the ChatGPT connector stays `isAccessible=false`, use `gh` CLI, GitHub MCP, or a dedicated API token instead of assuming the ChatGPT connector is available to SDK runs.

## App Server

The app-server is a local background process that exposes Codex through a structured JSON-RPC interface.

Plain explanation:

- The CLI is built for humans at a terminal.
- The SDK is built for code.
- The app-server is the local bridge that lets code control Codex without scraping terminal output.

Why the SDK uses app-server instead of wrapping the CLI:

- stable structured events;
- thread/session objects;
- cancellation and lifecycle control;
- typed errors and state;
- authentication state handled outside fragile terminal parsing;
- compatibility with apps, workers, notebooks, and services.

Do not describe app-server as a GUI. It is not a visual app.

## Authentication

Codex can authenticate through:

- ChatGPT/Codex login;
- API key.

Important distinction:

- Codex CLI/app-server/SDK can use the ChatGPT/Codex login flow when configured that way.
- The general OpenAI API SDK uses API keys and API billing; it does not consume a ChatGPT subscription as an API key.

If the user wants to use their ChatGPT Codex subscription, keep them in the Codex CLI/app-server/SDK path.

If the user wants direct API calls from Python with `openai-python`, explain that this is API-key billing, not ChatGPT subscription usage.

## When To Choose What

Use CLI when:

- a human is driving the session;
- the script only needs one-shot execution;
- `codex exec --json` returns enough structure;
- setup simplicity matters more than deep integration.

Use SDK when:

- Python or TypeScript needs to manage Codex as objects;
- the caller needs threads, runs, events, cancellation, or lifecycle control;
- terminal output parsing would be brittle;
- Codex is being embedded into another tool or service.

## Current Caveat

Codex SDK details can change. When giving implementation guidance, verify against official OpenAI Codex docs or the official `openai/codex` repository first.
