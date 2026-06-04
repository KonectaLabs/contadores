# Agent API And CLI

This is the agent-facing contract for operating the CRM without the frontend.

## Quickstart

```bash
contadores-agent login https://crm.fgoiriz.com
contadores-agent queues needs-attention --limit 20
contadores-agent conversations get LEAD_ID
contadores-agent messages LEAD_ID
contadores-agent send LEAD_ID "..."
contadores-agent action LEAD_ID mark-answered
contadores-agent tool call get_lead_context --json '{"lead_id":"..."}'
```

Default CLI output is compact JSON. Add `--pretty` for human-readable JSON.

## Auth

The API lives under `/api/agent`.

Supported auth:

- `Authorization: Bearer <cli_session_token>` for CLI browser-login sessions.
- `X-Internal-Token: <INTERNAL_API_TOKEN>` for server automations.
- Browser cookie sessions only for the login bootstrap flow.

CLI login:

1. `contadores-agent login https://crm.fgoiriz.com` starts a localhost callback.
2. The browser opens `/api/agent/auth/cli/start`.
3. If needed, the site sends the browser through the normal login page.
4. The backend redirects to the localhost callback with a one-time code.
5. The CLI exchanges the code at `/api/agent/auth/cli/exchange`.
6. The signed session token is stored in `~/.config/contadores-agent/profiles.json` with mode `0600`.

Local callback URLs must use `localhost`, `127.0.0.1`, or `::1`. Login codes are short-lived and single-use.

Env fallback for agents or rollout verification:

```bash
CONTADORES_AGENT_BASE_URL=https://crm.fgoiriz.com
CONTADORES_AGENT_TOKEN=...
CONTADORES_AGENT_INTERNAL_TOKEN=...
CONTADORES_AGENT_CONFIG=~/.config/contadores-agent/profiles.json
```

## Core API

```text
GET  /api/agent/me
GET  /api/agent/capabilities
GET  /api/agent/tools
POST /api/agent/runs
GET  /api/agent/runs/{run_id}
POST /api/agent/runs/{run_id}/tools/{tool_name}
```

Tool calls are audited in `agent_runs`, `agent_tool_calls`, and `data/agent-runs/`.

## CRM API

```text
GET   /api/agent/queues
GET   /api/agent/queues/{queue_name}
GET   /api/agent/conversations
GET   /api/agent/conversations/{lead_id}
GET   /api/agent/conversations/{lead_id}/messages
POST  /api/agent/conversations/{lead_id}/messages
POST  /api/agent/conversations/{lead_id}/actions
POST  /api/agent/conversations/{lead_id}/notes
POST  /api/agent/conversations/{lead_id}/followups
PATCH /api/agent/conversations/{lead_id}
PUT   /api/agent/conversations/{lead_id}/tags
```

Filters:

```text
funnel_id
queue_state
attention_state
manual_reply_status
pipeline_stage
terminal_state
tag
platform
query
limit
messages_per_lead
include_archived
```

Useful queues include `needs-attention`, `operator`, `automation`, `paused`, `workstation`, `failed-delivery`, `converted`, `closed`, `archived`, and `all-open`.

## CLI Commands

```bash
contadores-agent status
contadores-agent logout
contadores-agent profile list
contadores-agent profile use default
contadores-agent profile remove default
contadores-agent queues list
contadores-agent queues needs-attention --limit 20
contadores-agent conversations list --attention-state needs_reply
contadores-agent conversations get LEAD_ID
contadores-agent messages LEAD_ID
contadores-agent send LEAD_ID "texto" --idempotency-key UNIQUE_KEY
contadores-agent action LEAD_ID mark-answered
contadores-agent tags set LEAD_ID caliente prioridad
contadores-agent tags append LEAD_ID llamar
contadores-agent note add LEAD_ID "Contexto para el proximo agente."
contadores-agent followup schedule LEAD_ID --minutes 60 --instruction "Revisar si respondio."
contadores-agent tool list
contadores-agent tool call get_lead_context --json '{"lead_id":"..."}'
```

Every mutating convenience endpoint accepts `dry_run`. Outbound message and follow-up paths accept `idempotency_key`.

## Safety

Writes do not insert messages or mutate lead lifecycle rows directly from the API handler unless wrapped by an audit row and an existing CRM helper. Normal sends go through `call_tool()` and `send_whatsapp_text`, which reuses `enqueue_lead_outbound` and preserves WhatsApp 24-hour window/template checks. Lead and Workstation tools keep `codex_enabled` enforcement through the existing tool guard.
