---
name: codex-cli-sdk
description: Explain or evaluate Codex CLI, Codex SDKs, app-server, ChatGPT authentication, API-key authentication, and Python automation around Codex. Use for tool selection or external experiments, not as Website Agent runtime documentation.
---

# Codex CLI and SDK Reference

## Boundary

Website Agent currently uses Agent Runtime and Deep Agents. It does not use the
retired Codex backend integration from this workspace.
Treat this skill as a generic technology reference unless a current repo proves
a Codex integration exists.

## Mental model

- Codex CLI is an interactive/local command-line agent.
- Codex SDK or app-server wrappers control a Codex process programmatically.
- ChatGPT/Codex login and OpenAI API keys are different credential boundaries.
- A local app-server process is not a hosted cloud API.

Before recommending an SDK, inspect its current official documentation and the
installed package version. Verify supported inputs, streaming events, approval
behavior, cancellation, persistence and authentication from public APIs rather
than old project wrappers.

Use async APIs for server applications, set `cwd` explicitly, keep environment
variables minimal, bound retries and preserve the original provider error.
Never assume local filesystem or image tools are available in a remote runtime.

For Website Agent architecture and changes, use `website-agent-product`
instead.
