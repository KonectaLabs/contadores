# Agent API And CLI

This is the agent-facing contract for operating the CRM without the frontend.

## Quickstart

```bash
contadores-agent login
contadores-agent queues needs-attention --limit 20
contadores-agent conversations get LEAD_ID
contadores-agent messages LEAD_ID
contadores-agent send LEAD_ID "..."
contadores-agent action LEAD_ID mark-answered
contadores-agent clients create --name "Cliente" --whatsapp "+549..."
contadores-agent campaigns geo-search cordoba --country-code AR --kind city
contadores-agent campaigns create --name "Campaña" --client-id CLIENT_ID --status active --country-code AR --region "Buenos Aires" --city "Cordoba=OPTION_KEY"
contadores-agent campaigns get CAMPAIGN_ID
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

1. `contadores-agent login` starts a localhost callback against the default CRM origin.
2. The browser opens `/api/agent/auth/cli/start`.
3. If needed, the site sends the browser through the normal login page.
4. The backend redirects to the localhost callback with a one-time code.
5. The CLI exchanges the code at `/api/agent/auth/cli/exchange`.
6. The signed session token is stored in `~/.config/contadores-agent/profiles.json` with mode `0600`.

Local callback URLs must use `localhost`, `127.0.0.1`, or `::1`. Login codes are short-lived and single-use.
The CLI defaults to `https://crm.fgoiriz.com`; pass
`contadores-agent --base-url URL ...`, `contadores-agent login --base-url URL`,
or set `CONTADORES_AGENT_BASE_URL` only when intentionally targeting another
origin.

Env fallback for agents or rollout verification:

```bash
CONTADORES_AGENT_BASE_URL=https://crm.fgoiriz.com  # optional override
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

## Campaign And Capture API

CRM-owned campaigns let an agent create a converted client, attach a campaign to
that CRM user, publish a simple public form, and route submissions through the
normal Delivery pipeline.

```text
GET   /api/agent/clients
POST  /api/agent/clients/converted
GET   /api/agent/campaigns
POST  /api/agent/campaigns
GET   /api/agent/campaigns/{campaign_id}
PATCH /api/agent/campaigns/{campaign_id}
GET   /api/agent/campaigns/{campaign_id}/submissions
POST  /api/agent/campaigns/{campaign_id}/delivery-source
```

Meta readiness and inventory are direct agent endpoints:

```text
GET  /api/agent/meta/readiness
POST /api/agent/meta/inventory/sync
```

`/api/agent/meta/inventory/sync` is read-only against Meta and falls back to
configured server IDs. It persists the same audited inventory snapshot as the
`sync_meta_inventory` tool. Native Meta lead forms require Meta
`pages_manage_ads`; CRM-owned public forms do not.

The operator API exposes the same product surface under `/api/campaigns`.
Creative media uploaded from the Ads creator uses platform asset endpoints:

```text
POST /api/platform/creative-assets/upload
GET  /api/platform/creative-assets/{asset_id}/file
```

The upload endpoint accepts image/video `multipart/form-data`, stores the file
under `data/platform/creative-assets`, creates a `PlatformCreativeAsset`, and
returns `media_url` so the UI can preview it before creating the campaign.
Public lead capture is intentionally smaller:

```text
GET  /c/{public_slug}
GET  /api/public/campaigns/{public_slug}
POST /api/public/campaigns/{public_slug}/submissions
```

Converted client creation requires `name` and `whatsapp`; `email` and
`extra_info` are optional. Campaigns can link to an existing client with
`client_id` or create one inline with `client_name` and `client_whatsapp`.
Campaign geography uses structured `locations`. Each location can be a whole
country, country + regions/provinces, or country + cities. The UI uses
search-and-select controls, not persisted freeform text: the API first tries
Meta Targeting Search when credentials exist, then falls back to local
suggestions marked as `Local`. Whole-country locations are staged as Meta
`geo_locations.countries`; region/city locations are only sent as Meta
`regions`/`cities` when a Meta `key` is present, and they do not imply the
whole country. Use `contadores-agent campaigns geo-search ...` before CLI
creation; selected values can be passed as `--city "Name=KEY"` or
`--region "Name=KEY"`, or use `--geo-targeting-json` with `locations` for
multi-country campaigns. The CLI and API reject unsupported country codes,
duplicate geography values, more than 20 locations, more than 20 regions or
20 cities per location, and unsafe characters before creating the campaign.

Submissions dedupe on `idempotency_key`, record the raw answers, queue Client
Lead Delivery with existing helpers, and track Meta CAPI only when both the
campaign has `meta_events_enabled=true` and the existing
`META_MARKETING_LIVE_WRITES_ENABLED` gate allows live writes.

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
contadores-agent clients list --query Cliente
contadores-agent clients create --name "Cliente" --whatsapp "+549..." --email cliente@example.com
contadores-agent campaigns list --status active
contadores-agent campaigns get CAMPAIGN_ID
contadores-agent campaigns geo-search cordoba --country-code AR --kind city
contadores-agent campaigns create --name "Campaña" --client-id CLIENT_ID --status active --country-code AR --region "Buenos Aires" --city "Cordoba=OPTION_KEY"
contadores-agent campaigns submissions CAMPAIGN_ID --limit 20
contadores-agent campaigns delivery-source CAMPAIGN_ID
contadores-agent meta readiness
contadores-agent meta inventory --limit 20
contadores-agent tool list
contadores-agent tool call get_lead_context --json '{"lead_id":"..."}'
```

Every mutating convenience endpoint accepts `dry_run`. Outbound message and follow-up paths accept `idempotency_key`.

## Safety

Writes do not insert messages or mutate lead lifecycle rows directly from the API handler unless wrapped by an audit row and an existing CRM helper. Normal sends go through `call_tool()` and `send_whatsapp_text`, which reuses `enqueue_lead_outbound` and preserves WhatsApp 24-hour window/template checks.

Public campaign forms expose only active campaign form schema and thank-you
copy. They do not expose CRM notes, token material, Delivery config, Meta
credentials, or Workstation internals.
