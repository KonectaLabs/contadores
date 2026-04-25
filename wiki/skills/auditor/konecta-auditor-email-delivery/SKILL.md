---
name: konecta-auditor-email-delivery
description: Messenger-layer email delivery guidance for Konecta Auditor using Gmail API, SMTP, and outbox fallback. Use when configuring, debugging, or extending email sending under `messenger/`.
---

# Konecta Auditor Email Delivery (Messenger Layer)

## Scope
This skill applies to `messenger/` integration code only.
Backend core endpoints remain channel-agnostic and should not perform delivery.

## Delivery Stack
`messenger/email_delivery.py` uses a 3-tier fallback:
1. Gmail API (`messenger/gmail.py`)
2. SMTP
3. outbox `.eml` files in `data/outbox/`

## Key Modules
- `messenger/email_delivery.py`
- `messenger/gmail.py`
- `messenger/email_listener.py`
- `messenger/scripts/send_email.py`

## Gmail API Configuration
Required env vars:
- `GMAIL_CLIENT_ID`
- `GMAIL_CLIENT_SECRET`
- `GMAIL_REFRESH_TOKEN`
- optional: `GMAIL_FROM`

Token cache path is managed in `messenger/gmail.py`.

## SMTP Configuration
Required env vars:
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `SMTP_USE_TLS`

## Expected Delivery Outcomes
- `email_sent`
- `outbox`
- `outbox_fallback`

Treat missing delivery status as failure when messenger delivery is enabled.

## Validation Checklist
1. Confirm messenger config is present.
2. Send one message via messenger path.
3. Verify delivery outcome and any outbox artifact.
4. Verify persisted delivery metadata in messenger DB layer.

## Integration Rule
Do not move these delivery mechanics back into `backend/` runtime.
If backend needs delivery info, pass it as explicit metadata from external orchestrators.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
