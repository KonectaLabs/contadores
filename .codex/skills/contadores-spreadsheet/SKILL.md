---
name: contadores-spreadsheet
description: Use when working with the Contadores Google Sheet that stores leads and conversation state. Covers what the spreadsheet is for, how to connect from Python, the current schema, public read versus authenticated write, and how to use the sheet as the source of truth for WhatsApp follow-up workflows.
---

# Contadores Spreadsheet

Use this skill when the task touches the Google Sheet used by the `contadores` project.

This sheet is the operational source of truth for Meta lead-form intake.
Click-to-WhatsApp intake can bypass the sheet: the webhook `referral.source_id`
is matched against the funnel config and creates/reuses a `whatsapp_ctwa` lead.
Those matched funnel leads receive the `whatsapp_funnel` tag.
The approved Abogados prefilled proposal text also creates/reuses a funnel lead
when no reply/referral route is usable. Other unmatched inbound WhatsApp
messages are not discarded; they are saved in the built-in `general` inbox with
a `whatsapp` tag so an operator can route them.
When Meta includes the sender WhatsApp profile name in the webhook, the backend
uses it as the lead `full_name` for new WhatsApp-created leads and for existing
phone-only leads that do not yet have a name. Existing sheet/operator names are
preserved.

Contadores is now one funnel in a multi-funnel platform. The portable seed lives
in `config/default-funnels.json`, and per-server overrides live in
`FUNNELS_CONFIG_PATH` or `data/funnels.json`. Legacy scripts can still read
`CONTADORES_SHEET_URL` and `CONTADORES_SHEET_GID`.

There is no runtime source switch. Enabled campaign funnels poll their configured
sheet directly.

The spreadsheet is not the execution layer for autonomous Codex tools. Agent
tool side effects are persisted in the backend database (`contadores_messages`,
Workstation tables, `agent_runs`, `agent_tool_calls`, and
`scheduled_agent_tasks`) and may later be reflected in UI/status views. Do not
add spreadsheet columns as a substitute for the DB-backed tool audit.

## What It Is For

- It stores inbound leads coming from Meta lead forms.
- It is the simplest shared state for the workflow.
- It can drive a poller that checks for new leads every 30 seconds.
- In this repo, the immediate need is read access for lead ingestion and validating the WhatsApp flow safely.
- It is not required for Click-to-WhatsApp ads configured through `whatsapp_referral_source_ids`.

Read [references/spreadsheet.md](references/spreadsheet.md) when you need the exact columns, meanings, or the proposed operational fields.

## Current Connection Model

The project stores per-funnel sheet config in `config/default-funnels.json` and
the per-server override at `FUNNELS_CONFIG_PATH` or `data/funnels.json`. New
portable installs should put `sheet_url`, `sheet_gid`, and optional
`sheet_source_filter` on each funnel definition.

Backwards-compatible env keys for legacy Contadores scripts:

- `CONTADORES_SHEET_URL`
- `CONTADORES_SHEET_GID`

`/api/runtime` reports `ready=true` when at least one enabled `campaign` funnel
has both `sheet_url` and `sheet_gid`. The Contadores env keys are no longer the
only readiness path.

Backward-compatible aliases that still work in the reader script:

- `GOOGLE_SHEET_URL`
- `GOOGLE_SHEET_GID`

The repo already includes a reader script:

- [`src/tools/read_google_sheet.py`](/Users/fgoiriz/private/repos/contadores/src/tools/read_google_sheet.py)

That script:

- loads `.env` automatically;
- accepts either a full Google Sheets URL or a raw spreadsheet id;
- prefers `CONTADORES_*` env vars and falls back to `GOOGLE_*`;
- tries public CSV export first;
- falls back to the Google Sheets API if a service account file is provided.

## Client Lead Delivery Sources

Client Lead Delivery is separate from the funnel lead pipeline. It is used when
Konecta needs to notify a client that the client's own campaign sheet received a
new lead. Do not store this state in the normal Contadores lead tables or in the
campaign sheet operational columns.

Dedicated tables:

- `client_lead_sources`: one sheet source plus recipient/template config.
- `client_lead_deliveries`: imported sheet rows and WhatsApp notification state.

Each source can be configured through the API/UI or through file-backed config.
The file-backed path is preferred when Facu asks Codex to create a new client
Delivery flow without using the UI.

Config files:

- seed: `CLIENT_LEAD_SOURCES_SEED_CONFIG_PATH`, default
  `config/default-client-lead-sources.json`;
- server override: `CLIENT_LEAD_SOURCES_CONFIG_PATH`, default
  `data/client-lead-sources.json`;
- the backend imports those files into `client_lead_sources` on startup;
- after editing the server override without restarting, call
  `POST /api/client-lead-sources/config/reload`.

Each configured source supports:

- `label`
- `enabled`
- `sheet_url`
- `sheet_gid`
- `sheet_tab_name` when the desired tab is not the first tab or a gid is not known
- `sheets`, a list of `{id, label, sheet_url, sheet_gid, sheet_tab_name}` entries
  for multiple campaign sheets feeding the same client recipient. A sheet item
  can override part or all of `column_mapping` and `context_field_mapping` when
  that tab uses different column names. Omitted column mappings inherit from the
  parent source.
- `sheet_poll_seconds`, minimum 5
- `recipient_name`
- `recipient_phone`
- or `recipients`, a list of `{id, name, phone}` entries. Multiple recipients
  are expanded into one DB source per recipient using the same sheet config.
- `template_name`, default `konecta_client_lead_alert_es_v2`
- `template_language`, default `es`
- `column_mapping` for `source_id`, `created_time`, `full_name`,
  `phone_number`, and `email`
- `context_field_mapping`, optional mapping of WhatsApp display label to sheet
  column, rendered as `label = value` in the Delivery alert. The UI/audit text
  can show multiple context lines, but the sixth Meta template param must be a
  single line joined with `; `. Blank context values render as `-`.

Delivery stores each imported row's full sheet payload in `raw_row`. The
operator UI must render sheet leads by sheet/campaign and show those real
headers as columns, preserving the Google Sheet header order on newly synced
rows. Do not replace that view with a fixed summary table or hide campaign
columns behind a "raw fields" panel.

The first sync imports every non-empty row in the source sheet and immediately
queues valid new rows as `pending` notifications. If historical rows should not
notify the client, create the source disabled, use a clean tab, or remove old
rows before enabling it. Repeated syncs are idempotent: `source_id` is the
preferred row key, and rows without it use a stable row-number/hash key.

Polling should respect `sheet_poll_seconds` per enabled source. Manual rollout
or debugging can force one sync with:

```bash
curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources/{source_id}/sync
```

Sheet access order:

1. public CSV export using `sheet_tab_name` when present, otherwise `sheet_gid`;
2. public XLSX export;
3. Google Sheets API through a service account.

For private sheets, set `CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE` or
`GOOGLE_SERVICE_ACCOUNT_FILE`. The Contadores-specific env var has priority.
The service account only needs readonly Sheets access for Delivery import.

Delivery statuses are `pending`, `sent`, `delivered`, `failed`, `blocked`, and
`skipped`. Invalid lead phones or invalid recipient phones become `blocked`
instead of crashing the sync.

Endpoints:

- `GET /api/client-lead-sources`
- `POST /api/client-lead-sources/config/reload`
- `POST /api/client-lead-sources`
- `PUT /api/client-lead-sources/{source_id}`
- `DELETE /api/client-lead-sources/{source_id}`
- `POST /api/client-lead-sources/{source_id}/sync`
- `GET /api/client-lead-sources/{source_id}/leads`
- `GET /api/client-leads/{delivery_id}/copy-all`
- `POST /api/client-leads/{delivery_id}/retry`
- `GET /api/client-lead-deliveries/pending`
- `PUT /api/client-lead-deliveries/{delivery_id}/delivery`
- `POST /api/client-lead-deliveries/{delivery_id}/delivery-failure`
- `PUT /api/client-lead-deliveries/delivery/by-external-id`

The default WhatsApp template spec is versioned at
`src/scripts/whatsapp_template_specs/konecta_client_lead_alert_es_v2.json`.
It uses positional params: source label, lead name, lead phone, email, and the
plain `https://wa.me/{phone}` chat link without a `text=` parameter.
Context-enabled sources use
`src/scripts/whatsapp_template_specs/konecta_client_lead_alert_context_es_v1.json`
with the same first five params plus a single-line context param.

## Quick Start

Install dependencies:

```bash
cd /Users/fgoiriz/private/repos/contadores
uv sync
```

Read the current public sheet:

```bash
uv run python src/tools/read_google_sheet.py --as-records
```

Read a specific range:

```bash
uv run python src/tools/read_google_sheet.py --range "Hoja 1!A1:D20" --as-records
```

If the sheet is private again, provide authenticated access:

```bash
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json \
uv run python src/tools/read_google_sheet.py --as-records
```

Or with the Contadores-specific env name:

```bash
CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json \
uv run python src/tools/read_google_sheet.py --as-records
```

## Public Read Vs Authenticated Write

Use this rule:

- Public access is acceptable only for quick reads during development.
- Any production workflow with personal data should keep the sheet private.
- Any write path should use a Google service account with Editor access.

For writes:

1. Create a Google Cloud project.
2. Enable Google Sheets API.
3. Create a service account.
4. Download the JSON key.
5. Share the spreadsheet with that service account as `Editor`.
6. Store the JSON path in `GOOGLE_SERVICE_ACCOUNT_FILE`.

Do not rely on public spreadsheets for production contact workflows.

## How To Use The Sheet In This Project

Treat the spreadsheet as the source of truth for:

- lead ingestion;
- whether the lead was already contacted;
- which message sequence the lead is in;
- which step was already sent;
- whether the conversational bot already sent `ai_reply` or
  `scheduling_handoff_confirmation`;
- whether an inbound audio was transcribed into text or remained media-only for
  human review;
- whether Codex failed and the Grok/DSPy fallback answered, which should create
  a runtime alert without changing the lead stage;
- when the next action should happen;
- whether automation should stop and hand off to a human.

Operational rule:

- `ALWAYS_DEPLOY`: product work is complete only after the change is committed
  on `main`, pushed, deployed to the real server, and verified there.
- Product work is server-first by default; `localhost` is only for development, validation, git, push, and deploy.
- Enabled campaign funnels poll their configured sheet on a timer.
- New niche funnels should define their own sheet source in the funnel config.
  A future shared sheet can use `sheet_source_filter` to restrict rows by
  source/niche.

For the MVP:

- read rows every 30 seconds;
- find leads that are eligible for action;
- lock the row before sending;
- send the WhatsApp message;
- only after a successful send, update the sheet state.

Do not mark a lead as contacted before the outbound message succeeds.
Do not add a runtime mode switch to avoid configuring the sheet source.

## Suggested Operational Pattern

Use the existing lead columns as input data and add operational columns in the same sheet.

Recommended additional columns:

- `wa_status`
- `wa_sequence`
- `wa_step`
- `wa_last_outbound_at`
- `wa_last_inbound_at`
- `wa_next_action_at`
- `wa_message_id`
- `wa_error`
- `wa_lock_token`
- `wa_lock_until`
- `wa_human_handoff`
- `wa_notes`

These fields let the sheet replace local state in the first version.

## Working Rules

- Keep code simple and skimmable.
- Prefer explicit column names over inferred positions.
- Normalize booleans and timestamps as strings that are easy to inspect in Sheets.
- Avoid hidden state outside the sheet unless there is a clear operational reason.
- If multiple workers ever exist, use row locks in the sheet before sending messages.

## When To Read References

Read [references/spreadsheet.md](references/spreadsheet.md) when you need:

- the exact current columns in the operational sheet;
- the business meaning of each field;
- the proposed state columns for WhatsApp automation;
- implementation notes for polling and idempotency.
