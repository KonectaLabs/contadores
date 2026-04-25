---
name: konecta-auditor-delivery-outbox
description: Messenger-layer delivery verification rules for Konecta Auditor. Use only when validating optional `messenger/` email delivery flows.
---

# Konecta Auditor Delivery Outbox (Messenger Layer)

## Scope
This skill applies only to `messenger/` integrations (SMTP/Gmail/outbox), not backend core endpoints.

## Validate Delivery Outcomes
Accept only these delivery outcomes when messenger delivery is enabled:
- `email_sent`
- `outbox`
- `outbox_fallback`

Treat missing delivery status as failure.

## Validate SMTP Path When Configured
Expected env variables:
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_USE_TLS`

If SMTP works, expect `delivery_status=email_sent`.

## Validate Outbox Fallback Path
When SMTP/Gmail is unavailable or fails, require `.eml` artifact under:
- `/Users/fgoiriz/private/repos/konecta-auditor/data/outbox/`

Verify file exists and references expected report/content.

## Keep Fallback As First-Class Behavior
Treat fallback artifact as valid proof in environments without SMTP credentials.

## Bot Capability Filtering (Shared API Safe)
- Backend shared endpoints may include channels the bot cannot dispatch yet (for example `linkedin`), and that must not be used as a reason to change backend shared payload contracts.
- Apply dispatch capability filters in `bot/` runtime only, right before provider send logic.
- Unsupported channels should be reported as bot-local skipped/deferred outcomes, while frontend/backoffice visibility from backend APIs remains intact.

## Gmail Inbound Granularity (Default)
- Default behavior is one inbound provider message -> one backend inbound registration.
- Do not merge unread messages from the same Gmail thread into one payload unless explicitly requested and approved.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
