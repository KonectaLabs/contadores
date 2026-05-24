---
name: client-lead-delivery-flow
description: Use when Facu asks to create, edit, deploy, or verify a Client Lead Delivery flow from a Google Sheet plus one or more WhatsApp recipient numbers, without configuring it manually in the UI.
---

# Client Lead Delivery Flow

Use this skill in `/Users/fgoiriz/private/repos/contadores` when the request is
to add a client Delivery source from config files. This is not CRM funnel setup:
Delivery notifies a Konecta client that their own campaign sheet received a new
lead.

## Required Inputs

Get or infer:

- source id and label;
- Google Sheet URL and GID;
- one or more WhatsApp recipients: `{id, name, phone}`;
- whether first sync should notify existing rows;
- optional prefilled reply text;
- optional column mapping.

Default reply text:

```text
Hola {name}, vi tu consulta. Te escribo para entender mejor que necesitas y ver como te puedo ayudar.
```

Default template:

- name: `konecta_client_lead_alert_es_v1`
- language: `es`

## Config File

Preferred server file:

```text
/root/projects/contadores/data/client-lead-sources.json
```

Runtime env path:

```text
CLIENT_LEAD_SOURCES_CONFIG_PATH=data/client-lead-sources.json
```

Schema:

```json
{
  "version": 1,
  "sources": [
    {
      "id": "client-slug-ads",
      "label": "Client Ads",
      "enabled": false,
      "sheet_url": "https://docs.google.com/spreadsheets/d/...",
      "sheet_gid": "0",
      "sheet_poll_seconds": 30,
      "recipients": [
        {"id": "owner", "name": "Owner", "phone": "+5491122223333"}
      ],
      "template_name": "konecta_client_lead_alert_es_v1",
      "template_language": "es",
      "prefilled_reply_text": "Hola {name}, vi tu consulta. Te escribo para entender mejor que necesitas y ver como te puedo ayudar.",
      "column_mapping": {
        "source_id": "id",
        "created_time": "timestamp",
        "full_name": "name",
        "phone_number": "phone",
        "email": "email"
      }
    }
  ]
}
```

If the user gives multiple WhatsApp numbers, put them in `recipients`. The
backend expands them into one Delivery source per recipient.

Use `enabled: false` when the template is not approved yet or when historical
rows should not be notified until the user confirms.

## Workflow

1. Read `.codex/skills/contadores-spreadsheet/SKILL.md` and
   `.codex/skills/contadores-rollout/SKILL.md`.
2. Edit the server `data/client-lead-sources.json` for runtime-only client
   data, or `config/default-client-lead-sources.json` only for safe versioned
   defaults/examples.
3. Reload config:

```bash
curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources/config/reload
```

4. Verify the template:

```bash
uv run python src/scripts/whatsapp_templates.py check \
  --spec-file src/scripts/whatsapp_template_specs/konecta_client_lead_alert_es_v1.json \
  --fail-on-unapproved
```

5. If approved and the user wants it live, set `enabled: true`, reload config,
   run one manual sync, then inspect leads and pending notifications:

```bash
curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources/{source_id}/sync

curl -fsS -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-sources/{source_id}/leads

curl -fsS -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/client-lead-deliveries/pending
```

6. Deploy product code changes through the normal Contadores rollout. For a
   pure data-file flow on an already deployed build, editing the server data
   file plus config reload is enough.

## Safety Rules

- Do not put private client sheets or personal phone numbers in versioned files
  unless Facu explicitly asks for that.
- If the sheet is private, make sure the server has
  `CONTADORES_GOOGLE_SERVICE_ACCOUNT_FILE` or `GOOGLE_SERVICE_ACCOUNT_FILE` and
  that the sheet is shared with the service account.
- First sync queues existing valid rows. Keep the source disabled until Facu
  confirms historical rows should be sent.
