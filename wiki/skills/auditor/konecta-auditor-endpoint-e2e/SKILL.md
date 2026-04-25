---
name: konecta-auditor-endpoint-e2e
description: Endpoint-based end-to-end validation for the agnostic Konecta Auditor backend. Use when proving URL scan/discovery, automatic first-outbound seeding, inbound processing, transcript persistence, and report generation through HTTP only.
---

# Konecta Auditor Endpoint E2E

## Validate Full Loop Through HTTP
Prove behavior through agnostic endpoints only:
1. scan company from URL
2. verify automatic first outbound seeding for discovered contacts
3. ingest multiple inbound contact messages
4. persist generated AI replies
5. verify transcript persistence
6. prepare layered report JSON
7. build PDF model JSON artifact
8. fetch persisted report artifact

## Use Required Endpoints
- `POST /api/companies/scan`
- `GET /api/companies/{company_id}`
- `POST /api/companies/{company_id}/contacts/{contact_id}/messages/inbound`
- `GET /api/companies/{company_id}/contacts/{contact_id}/messages`
- `POST /api/companies/{company_id}/prepare-report`
- `POST /api/companies/{company_id}/build-report-pdf-model`
- `GET /api/companies/{company_id}/artifact`

## Run Multi-Turn Protocol
1. Start scan with `POST /api/companies/scan`.
2. Wait task completion, then verify first outbound messages were auto-seeded in transcripts.
3. Send at least 3 inbound message requests for one contact.
4. Fetch transcript and verify the latest outbound message matches the latest generated reply.
5. Run `prepare-report`, run `build-report-pdf-model`, then call `artifact`.
6. When multiple inbound messages arrive before provider delivery, verify the previous undelivered draft disappears from the transcript/pending queue and only the latest regenerated draft remains pending.

For high-confidence validation, run one long transcript (6+ inbound turns).

## Assert End-State Invariants
Assert all of:
- company exists,
- transcript includes both inbound and outbound turns,
- message order is consistent,
- no stale undelivered outbound remains after a newer inbound turn for the same contact,
- report generation persists one layered report artifact.

## Recover From Failures
If ingestion fails:
1. verify company/contact exists,
2. inspect transcript for partial persistence,
3. inspect DB rows for missing inserts,
4. document exact failure point.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
