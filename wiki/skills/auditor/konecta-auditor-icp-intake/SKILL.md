---
name: konecta-auditor-icp-intake
description: Find real candidate companies for Konecta Auditor, verify public contact channels, ingest them through backend endpoints, and schedule report delivery safely around weekends and business days. Use when the user asks to create/load/source companies into the auditor system.
---

# Konecta Auditor ICP Intake

## Use This Skill When
- the user asks to find 5 candidate companies,
- the user asks to ingest companies into the system,
- the user wants candidates from different industries,
- the user wants safe report timing instead of weekend delivery.

## Outcome
Leave the repo with real companies loaded into the backend, each one verified enough to justify the scan, and each one scheduled with an explicit `scheduled_send_at`.

## Candidate Selection Rules
- Prefer real companies with an active sales or commercial motion.
- Prefer official sites with at least one public contact signal:
  - email,
  - WhatsApp,
  - clear contact page.
- Prefer companies where a buyer-style audit conversation makes sense:
  - software,
  - agency/services,
  - logistics,
  - real estate,
  - education,
  - coworking,
  - industrial/B2B.
- Use different industries. Do not load 5 near-identical agencies unless the user asks for one niche.
- Avoid giant brands with no reachable public sales channel.
- Avoid companies that already exist in the local DB unless the user explicitly wants duplicates or rescans.

## Search Workflow
1. Browse the web first. This is a recommendation/sourcing task, so do not rely on memory alone.
2. Shortlist more than 5 options.
3. Validate each option on the official site:
   - company is real,
   - industry is distinct enough from the others,
   - contact path is visible.
4. Keep the 5 best candidates for actual ingestion.
5. If a scan fails or produces 0 useful contacts, replace that candidate instead of pretending the batch succeeded.

## Canonical Ingest Flow
Prefer HTTP/API flow first.

1. Check duplicates:
   - `GET /api/companies`
   - or sqlite on `data/database.sqlite`
2. Create the company:
   - `POST /api/companies/scan`
3. Use an explicit payload shape:
   - `url`
   - `objective`
   - `tags`
   - `conversation_automation_enabled=true`
   - `ceo_delivery_enabled=true` unless the user explicitly wants delivery off
4. After creation, set the exact delivery time:
   - `PUT /api/companies/{company_id}/report-schedule`
   - prefer `scheduled_send_at` over only `report_window_minutes`
5. Verify:
   - `GET /api/companies/{company_id}`
   - check status, contacts, `scheduled_send_at`, `has_ceo_email`

## Weekend Scheduling Rule
- Always reason in the user's local timezone.
- Use exact dates/times in responses, not only "Monday evening".
- If the company is created on Saturday or Sunday and the user did not request another timing:
  - set `scheduled_send_at` to the next Monday at `20:00` local time.
- If the user says "7 or 8 pm", default to `20:00` local unless they clearly choose `19:00`.
- If the user gives an exact date/time, use that instead.

## Safe Default Objective
If the user does not give a tighter one, use:
- `Audit inbound sales handling from first response to next-step progression.`

## Recommended Tags
Use a small, readable tag set:
- one run marker,
- one timing marker,
- one industry marker.

Good examples:
- `codex-intake`
- `weekend-hold`
- `2026-03-28`
- `logistics`

## Fallback Path
If the official URL scan is unreliable but official contact-page text is clearly available:
- use `POST /api/dev/companies/scan`
- pass extracted official text
- set `source_label` to the canonical homepage/domain

Use this only as a fallback. Prefer the real URL scan path first.

## Verification Checklist
For every created company, confirm all of:
- one `company_id` exists,
- status is not `failed`,
- there is at least one active contact or clear evidence that the site truly exposed none,
- `scheduled_send_at` is the intended exact timestamp,
- `has_ceo_email` is reported correctly,
- if CEO email is missing, call that out because delivery will fall back later.

## Reporting Back To The User
For each company, state:
- company name,
- URL,
- industry,
- why it matched the ICP,
- `company_id`,
- exact `scheduled_send_at`,
- whether a CEO email exists or delivery would fall back.

Keep the summary skimmable. Do not hide failed scans.
