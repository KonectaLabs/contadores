---
name: contadores-spreadsheet
description: Use when working with the Contadores Google Sheet that stores leads and conversation state. Covers what the spreadsheet is for, how to connect from Python, the current schema, public read versus authenticated write, and how to use the sheet as the source of truth for WhatsApp follow-up workflows.
---

# Contadores Spreadsheet

Use this skill when the task touches the Google Sheet used by the `contadores` project.

This sheet is the operational source of truth for lead intake.

Contadores is now one funnel in a multi-funnel platform. The built-in
Contadores sheet settings can still come from `CONTADORES_SHEET_URL` and
`CONTADORES_SHEET_GID`, while new funnels store their sheet URL/GID in the
shared funnel config file (`FUNNELS_CONFIG_PATH` or `data/funnels.json`).

The runtime rule is now explicit:

- `CONTADORES_SOURCE_MODE=testing` means do not poll the real sheet automatically; the bot imports only the synthetic lead from `CONTADORES_TEST_PHONE`.
- `CONTADORES_SOURCE_MODE=live` means the sheet is allowed to feed the workflow.

## What It Is For

- It stores inbound leads coming from Meta lead forms.
- It is the simplest shared state for the workflow.
- It can drive a poller that checks for new leads every 30 seconds.
- In this repo, the immediate need is read access for lead ingestion and testing the WhatsApp flow safely.

Read [references/spreadsheet.md](references/spreadsheet.md) when you need the exact columns, meanings, or the proposed operational fields.

## Current Connection Model

The project stores sheet config in `.env`.

Preferred keys:

- `CONTADORES_SHEET_URL`
- `CONTADORES_SHEET_GID`

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
- when the next action should happen;
- whether automation should stop and hand off to a human.

Operational rule:

- Product work is server-first by default; `localhost` is only for development, validation, git, push, and deploy.
- `testing` mode must work with `CONTADORES_TEST_PHONE` only and must not fetch the live sheet.
- `live` mode is the only mode allowed to poll this sheet on a timer.
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
Do not switch to `live` just because the code is deployed; the switch belongs in `.env`.

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

- the exact current columns in the live sheet;
- the business meaning of each field;
- the proposed state columns for WhatsApp automation;
- implementation notes for polling and idempotency.
