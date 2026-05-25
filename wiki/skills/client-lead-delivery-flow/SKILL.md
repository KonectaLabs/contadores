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
- optional column mapping.

Delivery sends a plain `https://wa.me/{phone}` chat link without a `text=`
parameter.

Default template:

- name: `konecta_client_lead_alert_es_v2`
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
      "sheet_poll_seconds": 10,
      "recipients": [
        {"id": "owner", "name": "Owner", "phone": "+5491122223333"}
      ],
      "template_name": "konecta_client_lead_alert_es_v2",
      "template_language": "es",
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

The Delivery UI hides source settings behind `Config`. The selected contact
auto-refreshes through the sync endpoint every 10 seconds, so do not add manual
sync controls to the main lead surface.

Delivery notification sends are visible in `Sent chat` with the exact
sent/snapshotted text, Meta `external_id`, status, timestamps, and errors. These
sends are Delivery audit data only; they must not pollute `contadores_messages`
or CRM conversation history. The CRM chat button appears only when the Delivery
recipient phone matches a CRM lead.

Reply links in templates must be direct plain `https://wa.me/{phone}` chat links
without a `text=` parameter.

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
  --spec-file src/scripts/whatsapp_template_specs/konecta_client_lead_alert_es_v2.json \
  --fail-on-unapproved
```

5. If approved and the user wants it live, set `enabled: true`, reload config,
   run one controlled API sync for verification, then inspect leads and pending notifications:

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
