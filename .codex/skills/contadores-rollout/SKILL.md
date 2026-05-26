---
name: contadores-rollout
description: Use when changing deployment flow, Docker Compose, .env handling, or server rollout for the Contadores project.
---

# Contadores Rollout

Use this skill when the task touches deploy, server config, `main`, Docker Compose, or `.env` handling.

## Canonical Rule

Contadores has no runtime mode switch. Do not reintroduce alternate runtime
branches, synthetic leads, or source-mode fields.

The multi-funnel config file stores funnel-specific sheet and WhatsApp routing:

- `FUNNELS_SEED_CONFIG_PATH`, usually `config/default-funnels.json`
- `FUNNELS_CONFIG_PATH`, usually `data/funnels.json`

The seed is versioned. The override stores funnel definitions added from the UI
or by Codex. Keep the override in the server data volume when it must persist
across deploys. Legacy `contadores` env vars are only backwards-compatible for
older scripts.
Click-to-WhatsApp routing also belongs there through
`whatsapp_referral_source_ids`; keep Contadores empty when it has no real
campaign source.
The approved Abogados prefilled proposal text can route to `abogados` when no
reply/referral route is usable. Other unmatched WhatsApp inbounds are saved in
the built-in `general` inbox. Inbox funnels do not run automation or sheet sync.
When Meta includes the sender profile name, the inbound flow stores it on the
lead when the lead came from WhatsApp or when an existing matched lead had no
name yet.

WhatsApp strategy videos should be referenced by `media_path` under the shared
`data` volume. The bot sends that configured file, and the frontend serves the
same path through one stable media URL. WhatsApp media sent by leads should also
be downloaded into `data/contadores/inbound_media` when available so operators
can inspect images, videos, audio, documents, and stickers from the CRM.
When a lead has a Workstation client, inbound user images must also be mirrored
into that client's `data/workstation/clients/.../media/` folder. If the lead is
converted after the image arrived, the conversion step mirrors existing
conversation images into the new workspace.
Inbound audio should be transcribed before the conversational bot runs. The
server image must include `ffmpeg` so WhatsApp `.ogg` audio can be converted for
OpenAI speech-to-text, and the env should keep
`OPENAI_AUDIO_TRANSCRIPTION_MODEL=gpt-4o-transcribe` unless deliberately
overridden.

The conversational bot never calls the Codex SDK unless
`CODEX_BACKEND_ENABLED=true` (default false: no Codex tokens, ChatGPT or API key).
With Codex on, use `CODEX_PREFER_CHATGPT_LOGIN=true` only if you want the
ChatGPT session path first; otherwise Codex uses `OPENAI_API_KEY` only, then
Grok/DSPy. Optional homes: `CONVERSATION_BOT_CODEX_CHATGPT_HOME`,
`CONVERSATION_BOT_CODEX_API_KEY_HOME`. ChatGPT Codex failures can still alert
with reauth hints when that path is enabled, but leads should not pause when a
safe fallback answered.

Autonomous Codex tools are rollout-gated. Keep
`CODEX_AGENT_TOOLS_ENABLED=false` by default until a controlled server test
passes. Enable Workstation first with `CODEX_AGENT_TOOLS_WORKSTATION_ENABLED`,
then conversation with `CODEX_AGENT_TOOLS_CONVERSATION_ENABLED`. Tool runs write
audits to `agent_runs`, `agent_tool_calls`, `scheduled_agent_tasks`, and
`data/agent-runs/`; deploy verification should inspect those records for the
first enabled lead/client.
Lead-level Codex is also gated by `contadores_leads.codex_enabled`; keep
`CONTADORES_LEAD_CODEX_ENABLED_DEFAULT=false` unless a rollout deliberately
turns Codex on by default for new leads. The UI switch is the source of truth
for enabling one lead.

Workstation solo-page Codex runs are also gated by `CODEX_BACKEND_ENABLED`.
When off, generation fails fast without calling the SDK. When on, optional
ChatGPT-first path matches `CODEX_PREFER_CHATGPT_LOGIN`, then API-key Codex.
If both fail, the Workstation client moves to `failed` with an operator-visible
alert; the UI should not hide those errors behind a generic request timeout.
Set `WORKSTATION_PUBLIC_PAGE_BASE_URL` on the server to the public origin served
by Traefik, without a trailing slash. Workstation uses that origin to build the
unguessable `/p/{token}/` trial URLs for solo-page clients. These are review
links inside the Contadores backend, not final custom-domain hosting.
Keep `WORKSTATION_CODEX_HEARTBEAT_ENABLED=true` and
`WORKSTATION_CODEX_HEARTBEAT_INTERVAL_HOURS=12` unless deliberately pausing
Workstation autonomy. The heartbeat creates DB-backed Codex wake-ups for active
solo-page clients and lets Codex choose a concrete action or no action.

Outbound WhatsApp send failures are persisted on `contadores_messages`. The bot
reports send exceptions to the backend, the backend requeues until
`CONTADORES_DELIVERY_MAX_ATTEMPTS`, and after the retry budget is exhausted the
CRM must show the failed message with the stored error. Operators can
acknowledge a failed message from the chat; acknowledged failures keep their
message-level error but no longer count toward the red lead-row alert.
Failed WhatsApp provider webhooks should preserve Meta error fields when
available (`code`, user-facing message, details) and the backend should
normalize common codes such as `130472` (recipient is in a Meta experiment
group), `131026` (likely invalid/not-on-WhatsApp recipient), and `131047`
(24-hour customer service window closed) into useful operator-facing
explanations.
Historical failed rows can be requeued with:

```bash
uv run python src/scripts/requeue_failed_contadores_messages.py --dry-run
uv run python src/scripts/requeue_failed_contadores_messages.py
```

## Branch And Deploy Rule

- `ALWAYS_DEPLOY`: product changes are not done until they are committed on
  `main`, pushed, deployed to the real server, and verified there.
- The project is server-first by default.
- Treat `localhost` only as the workbench for development, validation, git, push, and deploy.
- When the user asks for a product change or asks whether it is done, assume the expected end state is deployed on the real server unless they explicitly say local-only.
- If the user asks "quedo?", "esta listo?", or any equivalent status question,
  answer against the deployed server state, not the local checkout.
- `main` is the operational branch.
- If something is meant to run on the server, it should be committed on `main`.
- `docker-compose.yml` should read `.env`.
- `/api/runtime` should report `ready=true` when at least one enabled
  `campaign` funnel has both `sheet_url` and `sheet_gid`; incomplete funnels
  should appear as setup issues, not crash the app.
- While the project uses SQLite, keep the backend at one Uvicorn worker. SQLite
  lives in the persistent `data/` volume and the bot also writes to it, so extra
  backend workers can create avoidable `database is locked` failures.

## Rollout Rule

`ALWAYS_DEPLOY` sequence:

1. Commit the product change on `main`.
2. Push `main`.
3. Deploy the code to the real server.
4. Verify `/api/runtime` readiness on the server.
5. Verify `/api/funnels` on the server.
6. Verify sheet ingestion and WhatsApp flow on the real server when the change touches those surfaces.
   When the change touches the post-video sequence, include the conversational
   bot path that queues `ai_reply` and moves post-Loom conversations to Manual,
   the audio transcription path, runtime fallback alerts, plus the scheduling
   handoff path that queues `scheduling_handoff_confirmation`.

Use `./deploy_to_server.sh` and `./server_logs.sh`; both scripts connect to
`149.50.136.121` on SSH port `5389`.

For a new niche funnel, create/edit the funnel definition first, deploy code,
then verify that funnel against its configured sheet and WhatsApp routing.

## Client Lead Delivery Rollout

Client Lead Delivery rollout is separate from the funnel readiness check. It
uses dedicated tables (`client_lead_sources`, `client_lead_deliveries`). The
default template is `konecta_client_lead_alert_es_v2`; sources with
`context_field_mapping` use `konecta_client_lead_alert_context_es_v1`. Reply
URLs sent in those templates should be direct plain `https://wa.me/{phone}` chat
links without a `text=` parameter. The context template always needs 6 body
params, so blank context renders as `-`; sources without context must stay on
the default template.

Before enabling a live Delivery source:

1. Prefer a file-backed source when Facu provides sheet + WhatsApp recipients.
   Edit the server override at `CLIENT_LEAD_SOURCES_CONFIG_PATH`, usually
   `/root/projects/contadores/data/client-lead-sources.json`. The versioned
   seed is `config/default-client-lead-sources.json`.
2. Confirm the source has `sheet_url`, `sheet_gid`, recipient phone or
   `sheet_tab_name`, recipient phone or `recipients`, column mapping, optional
   context field mapping, template name, and template language. Multiple
   `recipients` are expanded into one DB source per recipient. Multiple
   `sheets` are expanded into one DB source per sheet/campaign.
3. Decide whether the first sync should notify historical rows. First sync
   imports all non-empty rows and queues valid new rows immediately.
4. If the sheet is private, set `CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE` or
   `GOOGLE_SERVICE_ACCOUNT_FILE` on the server and share the sheet with that
   service account.
5. Validate the template spec locally:

```bash
uv run python src/scripts/whatsapp_templates.py create \
  --spec-file src/scripts/whatsapp_template_specs/konecta_client_lead_alert_es_v2.json \
  --dry-run
```

6. On the server, check that the Meta template exists and is approved:

```bash
uv run python src/scripts/whatsapp_templates.py check \
  --spec-file src/scripts/whatsapp_template_specs/konecta_client_lead_alert_es_v2.json \
  --fail-on-unapproved
```

For context-enabled sources, also check:

```bash
uv run python src/scripts/whatsapp_templates.py check \
  --spec-file src/scripts/whatsapp_template_specs/konecta_client_lead_alert_context_es_v1.json \
  --fail-on-unapproved
```

Server verification:

```bash
curl -fsS -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources

curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources/config/reload

curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources/{source_id}/sync

curl -fsS -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources/{source_id}/leads

curl -fsS -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-deliveries/pending
```

After the bot sends a Delivery notification, verify that the provider callback
updates either `PUT /api/client-lead-deliveries/{delivery_id}/delivery` or
`PUT /api/client-lead-deliveries/delivery/by-external-id`. Failed sends should
flow through `POST /api/client-lead-deliveries/{delivery_id}/delivery-failure`
and should be retryable from `POST /api/client-leads/{delivery_id}/retry`.

Read [references/rollout.md](references/rollout.md) for the exact env variables and the recommended sequence.
