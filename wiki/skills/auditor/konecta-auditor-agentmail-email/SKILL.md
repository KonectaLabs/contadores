---
name: konecta-auditor-agentmail-email
description: AgentMail integration guide for Konecta Auditor email operations. Use when replacing Gmail with AgentMail, creating inboxes/domains/pods/webhooks, or wiring send, receive, follow-up, and delivery tracking into the existing bot and backend contracts.
---

# Konecta Auditor AgentMail Email

## Use this skill when
- replacing `bot/providers.py::GmailProvider`
- creating AgentMail pods, domains, inboxes, webhooks, lists, or scoped API keys
- wiring inbound email, CRM inbox flows, report delivery, follow-ups, or delivery events into the current `bot/` runtime

## Repo fit
- Keep `backend/` channel-agnostic.
- In this checkout, keep transport work in `bot/`, because that is where the current email runtime lives.
- Preserve existing backend contracts first.
- Replace the provider layer and event ingress before changing persistence or endpoint shapes.

## First reads
- `references/agentmail-operations.md`
- `/Users/fgoiriz/private/repos/konecta-auditor/bot/providers.py`
- `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
- `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`
- `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/crm.py`

## Default shape
- Use `AsyncAgentMail` in runtime code.
- Use one inbox for automated contact conversations and one inbox for CRM/report-delivery unless sender identities must differ.
- Use one pod when the deployment owns multiple inboxes or custom domains.
- Prefer webhooks for inbound and delivery events.
- Use polling only as fallback, backfill, or local debugging.
- Use drafts with `send_at` for scheduled follow-ups.
- Keep conditional follow-up state in backend DB or app logic. Do not depend on `threads.update`; the Python SDK version reviewed here does not expose it.

## Implementation rules
- Install with `uv add agentmail svix`.
- SDK requirement: `AGENTMAIL_API_KEY`
- Recommended repo env contract:
  - `AGENTMAIL_API_KEY`
  - `AGENTMAIL_POD_ID`
  - `AGENTMAIL_CONVERSATION_INBOX_ID`
  - `AGENTMAIL_CRM_INBOX_ID`
  - `AGENTMAIL_AUDIT_INBOX_ID` only if audit delivery needs a different sender
  - `AGENTMAIL_WEBHOOK_SECRET`
- Map AgentMail identifiers carefully:
  - AgentMail `thread_id` -> backend email thread id
  - AgentMail `message_id` -> provider external id
  - webhook `message.in_reply_to` and `message.references` -> preserve on inbound registration
  - if code still needs RFC `Message-ID`, fetch the sent message and read it from headers; do not assume AgentMail `message_id` is the RFC header value

## Event handling
- Verify webhook signatures with `svix.webhooks.Webhook`.
- Handle at least:
  - `message.received`
  - `message.sent`
  - `message.delivered`
  - `message.bounced`
  - `message.complained`
  - `message.rejected`
- Use `message.extracted_text` for the latest reply body when feeding the AI conversation pipeline.
- Use `message.text` or `message.html` when you need full-message evidence or debugging.

## Current repo mapping
- Contact automation outbound:
  - `client.inboxes.messages.send(...)` for first outbound
  - `client.inboxes.messages.reply(...)` for an existing thread
- Contact automation inbound:
  - webhook `message.received` -> `/api/companies/{company_id}/contacts/{contact_id}/messages/inbound`
- CRM inbound:
  - webhook `message.received` -> `/api/crm/messages/inbound`
- Report delivery:
  - send from CRM or audit inbox, then seed `/api/crm/report-delivery/sent`
- Manual CRM reply:
  - pending CRM row -> `reply(...)` or `reply_all(...)` -> `/api/crm/messages/{message_id}/mark-sent`
- Delivery outcomes:
  - webhook delivery events -> backend delivery update by external id, plus CRM status handling

## Known edges
- AgentMail docs currently show follow-up patterns that rely on mutating threads. Recheck the installed SDK before using docs examples that need `threads.update`.
- The SDK exposes webhook secrets and Svix header types, but not a built-in Python verifier helper. Use `svix` directly.
- Prefer the SDK over IMAP/SMTP inside the bot. Use IMAP/SMTP only for compatibility with third-party tools or manual smoke tests.

## Sources checked
- [agentmail-python](https://github.com/agentmail-to/agentmail-python)
- [docs.agentmail.to](https://docs.agentmail.to)
