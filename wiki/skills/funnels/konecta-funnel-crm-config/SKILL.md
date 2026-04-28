---
name: konecta-funnel-crm-config
description: Configure the Contadores/Konecta CRM as a multi-funnel platform. Use when adding a niche to the app, editing funnel config files, wiring spreadsheet sources, WhatsApp messages, video strategies, Calendly, or testing/live rollout.
---

# Konecta Funnel CRM Config

## Goal

The app should treat Contadores as one configured funnel, not the only product. New funnels should be addable from the UI and from a config file that Codex can edit.

## Funnel Config Fields

Each funnel needs:

- `id`: stable slug such as `contadores` or `abogados`;
- `label`: operator-facing name;
- `kind`: `campaign` for normal funnels or `inbox` for the built-in general inbox;
- `enabled`;
- `source_mode`: `testing` or `live`;
- `test_phone` and `test_name`;
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
- `calendly_base_url`;
- `alert_emails`;
- `whatsapp_referral_source_ids`: Meta Click-to-WhatsApp `referral.source_id` values that should create/reuse leads in this funnel;
- wait windows:
  - `initial_reply_quiet_seconds`;
  - `post_loom_min_seconds`;
  - `post_loom_quiet_seconds`;
- strategies:
  - WhatsApp MP4 strategy;
  - rollout weights.

## UI Rule

The visual editor and Codex must write to the same config source. Do not create one hidden UI state and another code-only state.

## Runtime Rule

Keep backwards compatibility with Contadores env names:

- `CONTADORES_SOURCE_MODE`
- `CONTADORES_TEST_PHONE`
- `CONTADORES_SHEET_URL`
- `CONTADORES_SHEET_GID`

For new funnels, prefer explicit funnel config. Env can seed defaults, but the app should read configured funnel definitions at runtime.

Click-to-WhatsApp ads should route by webhook referral metadata. Put each ad/post `referral.source_id` into the target funnel's `whatsapp_referral_source_ids`. Keep Contadores empty when it has no real campaign. There is one approved text fallback: the normalized message `Hola! Quiero mas informacion de su propuesta para abogados!` routes to `abogados` when no reply/referral route is usable. Other unmatched WhatsApp messages go to the built-in `general` inbox. If Meta sends `contacts.profile.name`, store that WhatsApp profile name on WhatsApp-created leads and use it to fill matched phone-only leads.

## Testing/Live Rule

Use the current safe rollout discipline:

1. Deploy code to the real server.
2. Keep the funnel in `testing`.
3. Test with the synthetic lead phone.
4. Only then switch that funnel to `live`.

## WhatsApp Template Rule

Initial outbound contact, no-reply follow-ups, and operator-triggered manual pings can be WhatsApp templates. Reply-triggered messages can be regular WhatsApp messages or media. Manual pings are CRM actions only; do not wire them into automation ticks.

Use:

```bash
uv run python src/scripts/whatsapp_templates.py
```

for template operations.
