---
name: konecta-funnel-crm-config
description: Configure the Contadores/Konecta CRM as a multi-funnel platform. Use when adding a niche to the app, editing funnel config files, wiring spreadsheet sources, WhatsApp messages, text offer strategies, Meeting, or rollout.
---

# Konecta Funnel CRM Config

## Goal

The app should treat Contadores as one configured funnel, not the only product. New funnels should be addable from the UI and from a config file that Codex can edit.
The seed plus override files are the source of truth for portable installs: a new user can start from `config/default-funnels.json`, then add a campaign visually or by writing `FUNNELS_CONFIG_PATH` / `data/funnels.json`.

## Funnel Config Fields

Each funnel needs:

- `id`: stable slug such as `contadores` or `abogados`;
- `label`: operator-facing name;
- `kind`: `campaign` for normal funnels or `inbox` for the built-in general inbox;
- `enabled`;
- `sheet_url`, `sheet_gid`, and optional `sheet_source_filter`;
- `sheet_poll_seconds`;
- `opener_text`;
- `opener_template_name`;
- `opener_followup_text`;
- `opener_followup_template_name`;
- `manual_ping_text`;
- `manual_ping_template_name`;
- `loom_intro_text`;
- `video_check_text`;
- `calendly_intro_text`;
- `calendly_base_url`: booking URL owned by this funnel config;
- `alert_emails`: real operator/admin recipients for this server; keep the portable seed empty until a client/team owns the install;
- `whatsapp_referral_source_ids`: Meta Click-to-WhatsApp `referral.source_id` values that should create/reuse leads in this funnel;
- wait windows:
  - `initial_reply_quiet_seconds`;
  - `post_loom_min_seconds`;
  - `post_loom_quiet_seconds`;
- strategies:
  - text offer strategy;
  - rollout weights.

## UI Rule

The visual editor and Codex must write to the same config source. Do not create one hidden UI state and another code-only state.

## Agent-Native Rule

Do not require the UI when an agent can configure the platform directly. Use the
audited tool runner first:

```bash
uv run python -m backend.ai.codex_agent_runtime call --run-id RUN_ID --tool read_platform_config --arguments-json '{"include_schema":true}'
uv run python -m backend.ai.codex_agent_runtime call --run-id RUN_ID --tool configure_text_offer_funnel --arguments-json 'JSON_OBJECT'
uv run python -m backend.ai.codex_agent_runtime call --run-id RUN_ID --tool upsert_client_lead_delivery_source --arguments-json 'JSON_OBJECT'
uv run python -m backend.ai.codex_agent_runtime call --run-id RUN_ID --tool validate_platform_config --arguments-json '{"include_disabled":true}'
```

Use `configure_text_offer_funnel` for normal mission-offer funnels and
`upsert_funnel_config` only when exact full-schema control is needed. Use
`upsert_client_lead_delivery_source` for client-owned lead delivery. Leave
`enabled=false` until templates, sheets/routing, alert emails, and offer copy
are known.

The same agent-native rule applies after conversion: use
`create_platform_meeting`, `attach_meeting_transcript`,
`extract_client_profile_from_meeting_transcript`, `upsert_client_profile`,
`stage_ad_campaign`, `stage_creative_asset`,
`stage_meta_publish_plan`, `preflight_meta_publish_plan`,
`stage_meta_publish_attempt`,
`create_client_update`, `ask_human_question`, and `answer_human_question`
instead of creating hidden state in the UI.

## Runtime Rule

Keep backwards compatibility with Contadores env names:

- `CONTADORES_SHEET_URL`
- `CONTADORES_SHEET_GID`

For all new funnels, use explicit funnel config. `config/default-funnels.json` is a neutral first-run seed with no personal admin emails, private calendars, client sheets, or real ad IDs. `data/funnels.json` overrides it per server. `/api/runtime` is ready when at least one enabled campaign has both `sheet_url` and `sheet_gid`; incomplete funnels should not break the app.

Use the generator when a file-first setup is faster than the UI:

```bash
uv run python src/scripts/funnel_config_template.py dentistas --label "Dentistas" --output data/funnels.json
```

Click-to-WhatsApp ads should route by webhook referral metadata. Put each ad/post `referral.source_id` into the target funnel's `whatsapp_referral_source_ids`. Keep Contadores empty when it has no real campaign. There is one approved text fallback: the normalized message `Hola! Quiero mas informacion de su propuesta para abogados!` routes to `abogados` when no reply/referral route is usable. Other unmatched WhatsApp messages go to the built-in `general` inbox. If Meta sends `contacts.profile.name`, store that WhatsApp profile name on WhatsApp-created leads and use it to fill matched phone-only leads.

## Rollout Rule

Use the current server-first rollout discipline:

1. Deploy code to the real server.
2. Verify runtime readiness and configured funnels.
3. Verify sheet ingestion and WhatsApp routing on the server.

## WhatsApp Template Rule

Initial outbound contact, no-reply follow-ups, and operator-triggered manual pings can be WhatsApp templates. Reply-triggered messages can be regular WhatsApp messages or media. Manual pings are CRM actions only; do not wire them into automation ticks.

Use:

```bash
uv run python src/scripts/whatsapp_templates.py
```

for template operations.
