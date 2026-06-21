---
name: contadores-spreadsheet
description: Use when working with the Contadores Google Sheet that stores leads and conversation state. Covers what the spreadsheet is for, how to connect from Python, the current schema, public read versus authenticated write, and how to use the sheet as the source of truth for WhatsApp follow-up workflows.
---

# Contadores Spreadsheet

Use this skill when the task touches the Google Sheet used by the `contadores` project.

## Credential Boundary

Do not use CleverApply/Alejandro resources for Contadores Sheets, Calendar, or
Google API work. Forbidden outside the CleverApply repo: `alejandro@cleverapply.com`,
any `@cleverapply.com` account, `cleverapply-gws-20260519`, CleverApply Google
Cloud/Workspace/OAuth/browser/1Password resources, quota projects, billing
projects, temporary fallbacks, and read-only probes.

Before using `gcloud`, a service account, OAuth credentials, or a connector,
confirm the active account/project is owned by Contadores/Konecta or the user's
personal scoped setup for this project. If not, stop and switch credentials.

This sheet is the operational source of truth for Meta lead-form intake.
Click-to-WhatsApp intake can bypass the sheet: the webhook `referral.source_id`
is matched against the funnel config and creates/reuses a `whatsapp_ctwa` lead.
Those matched funnel leads receive the `whatsapp_funnel` tag.
When a new Click-to-WhatsApp ad is published through
`execute_meta_publish_plan`, the returned Meta ad ID is persisted into the
funnel's `whatsapp_referral_source_ids` so the webhook route is ready.
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

- `client_lead_sources`: one sheet/API source plus recipient/template config.
- `client_lead_deliveries`: imported lead rows and WhatsApp notification state.

Each source can be configured through the API/UI or through file-backed config.
The file-backed path is preferred when Facu asks Codex to create a new client
Delivery flow without using the UI.
Meta instant-form publish plans must reference a ready source with
`destination.client_lead_source_id`; otherwise the Meta approval/preflight gate
must stay blocked because the leads would not have a delivery path.
Instant-form sources should store `meta_page_id` and `meta_lead_form_id` so
`POST /api/meta-leads/webhook` can resolve the Delivery source from the webhook
`form_id`. `POST` requires `X-Hub-Signature-256` signed with
`META_LEAD_WEBHOOK_APP_SECRET`. `META_LEAD_WEBHOOK_DEFAULT_SOURCE_ID` is only a
fallback for narrow single-source deployments.
When a Meta Lead Ads webhook only has `leadgen_id`, fetch and import it through
`fetch_meta_lead_form_to_delivery` or
`POST /api/client-lead-sources/{source_id}/meta-lead/fetch`. When the full
payload has already been retrieved, import it through
`import_meta_lead_form_to_delivery` or
`POST /api/client-lead-sources/{source_id}/meta-lead`. For historical form
leads, use `backfill_meta_lead_form_to_delivery` or
`POST /api/client-lead-sources/{source_id}/meta-leads/backfill`; do not create a
separate delivery table.

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
- `meta_page_id`, optional Page id used by Meta Lead Ads webhooks
- `meta_lead_form_id`, optional form id used to route webhook leads to this source
- `sheet_poll_seconds`, minimum 5
- `recipient_name`
- `recipient_phone`
- or `recipients`, a list of `{id, name, phone}` entries. Multiple recipients
  are expanded into one DB source per recipient using the same sheet config.
- `template_name`, default `konecta_delivery_lead_alert_es`
- `template_language`, default `es`
- `column_mapping` for `source_id`, `created_time`, `full_name`,
  `phone_number`, and `email`
- `context_field_mapping`, optional mapping of WhatsApp display label to sheet
  column, rendered as `label: value` in the Delivery alert. The UI/audit text
  can show multiple context lines; the Meta template receives one lead-data
  param joined with `; ` for safety.

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
or debugging can force one sync on the real server with the public CRM host:

```bash
curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  https://crm.fgoiriz.com/api/client-lead-sources/{source_id}/sync
```

Use `127.0.0.1:8000` only for local development or from an SSH session where
the command is intentionally targeting the backend inside the server context.

Sheet access order:

1. public CSV export using `sheet_tab_name` when present, otherwise `sheet_gid`;
2. public XLSX export;
3. Google Sheets API through a service account.

For private sheets, set `CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE` or
`GOOGLE_SERVICE_ACCOUNT_FILE`. The Contadores-specific env var has priority.
The service account only needs readonly Sheets access for Delivery import.
If Meta Lead Ads imports should append the new lead back into the connected
Sheet, the same service account needs Editor access. The backend appends only
new `leadgen_id` imports and writes a minimized export projection by default:
`id`, `leadgen_id`, `created_time`, visible ad/campaign names, `platform`,
`full_name`, `phone_number`, and `email`. Raw provider ids such as `form_id`,
`ad_id`, `adset_id`, and `campaign_id` stay in the app database unless they are
explicitly listed in `META_SHEET_APPEND_EXTRA_FIELDS`.

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
- `POST /api/client-lead-sources/{source_id}/meta-lead`
- `POST /api/client-lead-sources/{source_id}/meta-lead/fetch`
- `POST /api/client-lead-sources/{source_id}/meta-leads/backfill`
- `POST /api/meta-leads/forms`
- `POST /api/meta-leads/webhook-subscriptions`
- `GET /api/meta-leads/webhook`
- `POST /api/meta-leads/webhook`
- `GET /api/client-lead-sources/{source_id}/leads`
- `GET /api/client-leads/{delivery_id}/copy-all`
- `POST /api/client-leads/{delivery_id}/retry`
- `GET /api/client-lead-deliveries/pending`
- `PUT /api/client-lead-deliveries/{delivery_id}/delivery`
- `POST /api/client-lead-deliveries/{delivery_id}/delivery-failure`
- `PUT /api/client-lead-deliveries/delivery/by-external-id`

The default WhatsApp template spec is versioned at
`src/scripts/whatsapp_template_specs/konecta_delivery_lead_alert_es.json`.
It uses 3 positional params: campaign/source title, one lead-data block, and the
plain `https://wa.me/{phone}` chat link without a `text=` parameter.
Context-enabled sources use
`src/scripts/whatsapp_template_specs/konecta_delivery_lead_alert_context_es.json`
with the same 3-param shape. Context fields are appended inside the lead-data
block as `Nombre del campo: valor`; Meta receives that whole block as one
single positional parameter.

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

Treat the spreadsheet as intake/config input only:

- lead ingestion rows;
- source-specific contact fields;
- whether a row was already contacted before import;
- per-funnel sheet source configuration through `data/funnels.json` or
  `FUNNELS_CONFIG_PATH`.

Runtime state lives in backend persistence and the CRM/backoffice:

- message sequence, sent steps, delivery state, and retry/error state live in
  `contadores_messages`;
- lead stage, automation ownership, handoff state, and next-action decisions live
  in `contadores_leads`;
- runtime alerts live in `contadores_runtime_alerts` and alert delivery tables;
- scheduled sheet-sync cadence/failure state lives in backend sync-state rows;
- operators review and change state in the CRM/backoffice, not by editing
  operational sheet columns.

Operational rule:

- `ALWAYS_DEPLOY`: product work is complete only after the change is committed
  on `main`, pushed, deployed to the real server, and verified there.
- Product work is server-first by default; `localhost` is only for development, validation, git, push, and deploy.
- Enabled campaign funnels poll their configured sheet on a timer.
- New niche funnels should define their own sheet source in the funnel config.
  A future shared sheet can use `sheet_source_filter` to restrict rows by
  source/niche.

For the MVP:

- enabled campaign funnels poll their configured sheet cadence;
- eligible rows are imported into backend persistence;
- automation and outbound delivery run from backend state;
- the sheet remains intake/config input, not the runtime execution layer.

Do not mark a lead as contacted before the outbound message succeeds.
Do not add a runtime mode switch to avoid configuring the sheet source.

## Suggested Operational Pattern

Use the existing lead columns as input data. Do not add new `wa_*` runtime
columns for active automation. If an old sheet already has those columns, treat
them as legacy/historical hints only; do not make them authoritative without a
new product decision.

## Working Rules

- Keep code simple and skimmable.
- Prefer explicit column names over inferred positions.
- Normalize booleans and timestamps as strings that are easy to inspect in Sheets.
- Keep runtime state in backend tables and expose it through the CRM/backoffice.
- Do not reintroduce sheet-managed locks or runtime mode switches.

## When To Read References

Read [references/spreadsheet.md](references/spreadsheet.md) when you need:

- the exact current columns in the operational sheet;
- the business meaning of each field;
- the proposed state columns for WhatsApp automation;
- implementation notes for polling and idempotency.
