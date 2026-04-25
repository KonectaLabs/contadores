---
name: konecta-auditor-db-forensics
description: Database forensics and persistence verification for the agnostic Konecta Auditor flow. Use after endpoint or Docker validation to prove DB consistency.
---

# Konecta Auditor DB Forensics

## Verify Persistence After E2E
Inspect sqlite state after substantial endpoint validation.

Database file:
- `/Users/fgoiriz/private/repos/konecta-auditor/data/database.sqlite`

Development schema rule:
- During local dev, do not create migrations; if schema changes, recreate `data/database.sqlite` before validation.

Primary tables:
- `companies`
- `contacts`
- `messages`

## Prove Required Invariants
For latest company, verify:
1. company row exists,
2. contact rows exist for that company,
3. inbound and outbound messages are both present,
4. message timestamps are monotonic per contact.

## Run Deterministic SQL Checks
Use `sqlite3` CLI when available:
```bash
sqlite3 data/database.sqlite "SELECT id,source_url,company_name,status,updated_at FROM companies ORDER BY updated_at DESC LIMIT 10;"
sqlite3 data/database.sqlite "SELECT company_id,type,value,COUNT(*) FROM contacts GROUP BY company_id,type,value ORDER BY company_id DESC LIMIT 20;"
sqlite3 data/database.sqlite "SELECT contact_id,id,from_me,text,timestamp FROM messages ORDER BY id DESC LIMIT 50;"
```

## Correlate API State With DB State
- Compare `GET /api/companies/{company_id}` contact/message counters with DB rows.
- Compare `GET /api/companies/{company_id}/contacts/{contact_id}/messages` with latest `messages` table rows.
- Treat mismatch as bug even when API returns 200.

## Include Forensics In Delivery Summary
Report exact `company_id` and row-level confirmation.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
