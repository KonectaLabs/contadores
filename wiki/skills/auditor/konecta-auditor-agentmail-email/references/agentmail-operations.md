# AgentMail Operations For Konecta Auditor

This file is the detailed playbook behind `konecta-auditor-agentmail-email`.

It was written from the `agentmail-python` SDK, its generated type surface, and the official AgentMail docs.

## What AgentMail gives us
- Hosted inboxes with stable inbox IDs, message IDs, and thread IDs
- Send, reply, reply-all, and forward operations from the SDK
- Inbound parsing with `extracted_text` and `extracted_html`
- Webhooks and websockets for inbound and delivery events
- Drafts with `send_at` for scheduled sends
- Message labels plus allow/block lists
- Metrics for sent, delivered, bounced, delayed, rejected, complained, and received events
- Pod/domain/inbox grouping for multi-inbox setups
- IMAP/SMTP compatibility if we need external-tool access

## What we currently do in this repo
- `bot/main.py` runs a stateless loop.
- `bot/utils.py` pulls pending outbound work from the backend, sends it, and writes provider IDs back.
- `bot/providers.py::GmailProvider` is the current email transport.
- `backend/endpoints/messages.py` owns contact-automation email persistence.
- `backend/endpoints/crm.py` owns CRM thread persistence for CEO delivery and manual replies.

## The right integration shape here
- Keep the existing backend endpoints.
- Replace `GmailProvider` with an `AgentMailProvider` behind the same bot flow.
- Prefer webhook-driven inbound and delivery status updates.
- Keep polling support for local debugging or recovery scans.
- Use one conversation inbox and one CRM inbox by default.
- Add a third inbox only if audit delivery must come from a different sender identity.
- Use one pod if the deployment owns multiple inboxes or custom domains.

## Fast mapping from current behavior to AgentMail

| Current need | Current code | AgentMail operation | Notes |
| --- | --- | --- | --- |
| Create sender mailbox | Gmail account setup | `client.inboxes.create(...)` or `client.pods.inboxes.create(...)` | Use pod-scoped create if you want grouped inboxes |
| Send first outbound contact email | `GmailProvider.send_message(...)` | `client.inboxes.messages.send(...)` | Store `message_id` and `thread_id` |
| Send reply in an existing thread | Gmail thread + RFC headers | `client.inboxes.messages.reply(...)` | Prefer reply by last known message ID |
| Send manual CRM reply | pending CRM outbound | `reply(...)` or `reply_all(...)` | Then call `/api/crm/messages/{message_id}/mark-sent` |
| Deliver CEO audit email | CRM send + PDF attachment | `send(...)` with attachment | Then call `/api/crm/report-delivery/sent` |
| Receive contact reply | Gmail polling | webhook `message.received` | Route to `/api/companies/.../messages/inbound` |
| Receive CEO reply | Gmail polling | webhook `message.received` | Route to `/api/crm/messages/inbound` |
| Track delivery | Gmail send confirmation only | webhook `message.sent` and `message.delivered` | Also handle bounce, complaint, reject |
| Poll inbox manually | Gmail unread list | `client.inboxes.messages.list(...)` | Use `labels=["unread"]` for recovery scans |
| Mark inbox items read | Gmail modify | `client.inboxes.messages.update(..., remove_labels=["unread"])` | Add `archived` if desired |
| Schedule follow-up | custom delay logic | `client.inboxes.drafts.create(..., send_at=...)` | Good for timed follow-up sends |
| Check delivery trends | none | `client.metrics.query(...)` | Useful for operations and debugging |

## Setup

### Install
```bash
uv add agentmail svix
```

### Required SDK environment
```bash
export AGENTMAIL_API_KEY="..."
```

### Recommended repo environment contract
```bash
export AGENTMAIL_API_KEY="..."
export AGENTMAIL_POD_ID="pod_..."
export AGENTMAIL_CONVERSATION_INBOX_ID="inbox_..."
export AGENTMAIL_CRM_INBOX_ID="inbox_..."
export AGENTMAIL_AUDIT_INBOX_ID="inbox_..."
export AGENTMAIL_WEBHOOK_SECRET="whsec_..."
```

Use `AGENTMAIL_AUDIT_INBOX_ID` only if audit delivery needs a dedicated sender.

### Client bootstrap
```python
import os

from agentmail import AgentMailEnvironment, AsyncAgentMail


def build_agentmail_client() -> AsyncAgentMail:
    return AsyncAgentMail(
        api_key=os.environ["AGENTMAIL_API_KEY"],
        environment=AgentMailEnvironment.PROD,
    )
```

## Pods, domains, and inboxes

### When to create a pod
- Create a pod if the deployment has multiple inboxes.
- Create a pod if you want pod-scoped webhooks, domains, or API keys.
- Skip pods only for the smallest single-inbox setup.

### Create a pod
```python
pod = await client.pods.create(name="konecta-auditor-prod")
```

### Create a custom domain
```python
domain = await client.domains.create(
    domain="mail.example.com",
    feedback_enabled=True,
)
```

### Get the DNS zone file
```python
zone_chunks = []
for chunk in client.domains.get_zone_file(domain.domain_id):
    zone_chunks.append(chunk)
zone_text = b"".join(zone_chunks).decode("utf-8")
```

### Verify a domain
```python
await client.domains.verify(domain.domain_id)
```

### Create an inbox without a pod
```python
from agentmail import CreateInboxRequest

conversation_inbox = await client.inboxes.create(
    request=CreateInboxRequest(
        username="auditor",
        domain="mail.example.com",
        display_name="Konecta Auditor",
        client_id="conversation-inbox",
    )
)
```

### Create an inbox inside a pod
```python
crm_inbox = await client.pods.inboxes.create(
    pod_id=os.environ["AGENTMAIL_POD_ID"],
    username="ceo-audit",
    domain="mail.example.com",
    display_name="Konecta Auditor Reports",
    client_id="crm-inbox",
)
```

### Recommended inbox layout for this repo
- `AGENTMAIL_CONVERSATION_INBOX_ID`
  - automated contact outreach and replies
- `AGENTMAIL_CRM_INBOX_ID`
  - CEO report delivery
  - inbound CEO replies
  - manual CRM follow-up replies
- `AGENTMAIL_AUDIT_INBOX_ID`
  - optional
  - only when report delivery must use a different sender identity

## Sending email

### Send the first outbound email in a thread
```python
response = await client.inboxes.messages.send(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    to=["lead@example.com"],
    subject="Quick question",
    text="Hi, I wanted to ask about your current response process.",
)

provider_message_id = response.message_id
provider_thread_id = response.thread_id
```

### Send HTML and attachments
```python
import base64

pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

response = await client.inboxes.messages.send(
    os.environ["AGENTMAIL_CRM_INBOX_ID"],
    to=["ceo@example.com"],
    subject=subject,
    text=body_text,
    html=body_html,
    attachments=[
        {
            "filename": "audit-report.pdf",
            "content_type": "application/pdf",
            "content": pdf_b64,
        }
    ],
)
```

### Reply in an existing thread
```python
response = await client.inboxes.messages.reply(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    message_id=last_message_id,
    text=reply_text,
)
```

### Reply all for CRM threads
```python
response = await client.inboxes.messages.reply_all(
    os.environ["AGENTMAIL_CRM_INBOX_ID"],
    message_id=last_inbound_message_id,
    text=body,
)
```

### Forward an email
```python
response = await client.inboxes.messages.forward(
    os.environ["AGENTMAIL_CRM_INBOX_ID"],
    message_id=message_id,
    to=["ops@example.com"],
    text="Forwarding for review.",
)
```

## How to map sent IDs back into this repo
- Treat AgentMail `message_id` as the provider external ID.
- Treat AgentMail `thread_id` as the backend email thread ID.
- If a backend path still depends on RFC `Message-ID`, fetch the sent message after sending and read its headers.
- Do not assume AgentMail `message_id` equals the RFC header.

### Fetch the sent message to read headers
```python
sent_message = await client.inboxes.messages.get(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    response.message_id,
)

rfc_message_id = None
headers = sent_message.headers or {}
if "Message-ID" in headers:
    rfc_message_id = headers["Message-ID"]
```

## Receiving email

### Preferred path: webhook-driven receive
- Create one webhook that subscribes to both inboxes, or one webhook per inbox.
- Filter by `inbox_ids` or `pod_ids`.
- Verify the Svix signature before trusting the payload.
- Route by inbox ID or by existing backend lookup rules.

### Create a webhook
```python
webhook = await client.webhooks.create(
    url="https://your-app.example.com/api/bot/agentmail/webhook",
    event_types=[
        "message.received",
        "message.sent",
        "message.delivered",
        "message.bounced",
        "message.complained",
        "message.rejected",
    ],
    inbox_ids=[
        os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
        os.environ["AGENTMAIL_CRM_INBOX_ID"],
    ],
    client_id="konecta-auditor-main-webhook",
)
```

Store `webhook.secret` in `AGENTMAIL_WEBHOOK_SECRET`.

### Verify webhook signatures
This SDK exposes webhook secrets and Svix header types, but it does not ship a Python helper that verifies the signature for you. Use `svix` directly.

Reusable pattern source: `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/webhooks.py`

```python
import json

from fastapi import HTTPException, Request
from svix.webhooks import Webhook


async def verify_agentmail_webhook(request: Request, secret: str) -> dict:
    body = await request.body()
    payload = body.decode("utf-8")
    headers = dict(request.headers)

    try:
        Webhook(secret).verify(payload, headers)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid AgentMail webhook signature: {exc}")

    return json.loads(payload)
```

### Minimal webhook router shape
```python
async def handle_agentmail_webhook(request: Request) -> dict:
    event = await verify_agentmail_webhook(request, os.environ["AGENTMAIL_WEBHOOK_SECRET"])
    event_type = event.get("event_type")

    if event_type == "message.received":
        return await handle_message_received(event)

    if event_type == "message.sent":
        return await handle_message_sent(event)

    if event_type == "message.delivered":
        return await handle_message_delivered(event)

    if event_type == "message.bounced":
        return await handle_message_bounced(event)

    if event_type == "message.complained":
        return await handle_message_complained(event)

    if event_type == "message.rejected":
        return await handle_message_rejected(event)

    return {"status": "ignored", "event_type": event_type}
```

### What to do on `message.received`
- Read `message.inbox_id` to decide which repo flow owns the email.
- Use `message.thread_id`, `message.message_id`, `message.in_reply_to`, and `message.references`.
- Use `message.extracted_text` first for AI conversation pipelines.
- Fall back to `message.text` if extraction is empty.

### Conversation inbox path
1. Resolve the contact.
2. Route to `/api/companies/{company_id}/contacts/{contact_id}/messages/inbound`.
3. Pass:
   - `message`
   - `external_id=message.message_id`
   - `channel="email"`
   - `thread_id=message.thread_id`
   - `in_reply_to=message.in_reply_to`
   - `references=message.references`

### CRM inbox path
1. Route to `/api/crm/messages/inbound`.
2. Pass:
   - `gmail_thread_id` equivalent = AgentMail `thread_id`
   - `gmail_message_id` equivalent = AgentMail `message_id`
   - `subject`
   - `body`
   - `from_email`
   - `in_reply_to`
   - `references`

The current CRM endpoint names are Gmail-shaped, but the payload can still carry AgentMail IDs if you preserve the meaning.

## Polling and checking emails

### Poll recent unread messages
```python
page = await client.inboxes.messages.list(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    labels=["unread"],
    limit=50,
)

for item in page.messages:
    full_message = await client.inboxes.messages.get(
        os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
        item.message_id,
    )
```

### Fetch a whole thread
```python
thread = await client.inboxes.threads.get(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    thread_id,
)
```

Use thread fetches when you need the full ordered conversation context or need the latest message in a thread before choosing `reply(...)`.

### Mark as read or archive
```python
updated = await client.inboxes.messages.update(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    message_id,
    remove_labels=["unread"],
    add_labels=["archived"],
)
```

### Download raw message or attachments
```python
raw = await client.inboxes.messages.get_raw(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    message_id,
)
```

```python
attachment = await client.inboxes.messages.get_attachment(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    message_id,
    attachment_id,
)
```

## Delivery events

### Why these matter here
- Conversation flow needs the provider external ID persisted for each outbound message.
- CRM flow needs sent status and thread continuity.
- CEO report delivery needs reliable sent-state recording.
- Operations need bounce, complaint, and rejection visibility.

### Event mapping
- `message.sent`
  - provider accepted the outbound send
  - good point to confirm sent state
- `message.delivered`
  - recipient delivery confirmed
  - use when you want a stronger delivered state
- `message.bounced`
  - mark failure and surface the bounce
- `message.complained`
  - stop future outreach to that address
- `message.rejected`
  - treat as send failure or policy failure

### Recommended backend handling
- Contact automation outbound:
  - update via `/api/messages/delivery/by-external-id`
- CRM outbound:
  - keep `/api/crm/messages/{message_id}/mark-sent` for the initial send confirmation
  - add failure handling around bounced or rejected CRM sends if we later need richer CRM state

## Follow-up

### Use drafts for scheduled sends
`client.inboxes.drafts.create(...)` accepts `send_at`, so it is the clean built-in way to schedule a later send.

```python
draft = await client.inboxes.drafts.create(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    to=["lead@example.com"],
    subject="Following up",
    text="Checking back in on this.",
    send_at="2026-03-28T15:00:00Z",
    client_id="followup-contact-123-2026-03-28",
)
```

### Send a draft immediately
```python
send_result = await client.inboxes.drafts.send(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    draft.draft_id,
)
```

### Update or delete a draft
```python
updated = await client.inboxes.drafts.update(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    draft.draft_id,
    text="New follow-up text",
    send_at="2026-03-29T15:00:00Z",
)
```

```python
await client.inboxes.drafts.delete(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    draft.draft_id,
)
```

### Conditional follow-up guidance for this repo
- Keep the condition in backend DB or app logic.
- Good conditions:
  - no inbound after N hours
  - report delivered but no CEO reply after N days
  - only one current active follow-up per thread
- Do not rely on thread labels unless the installed SDK actually exposes thread updates.
- If you need labeling today, use message labels or local DB state instead.

## Lists

Lists are allow/block rules for send, receive, or reply directions.

### Common uses here
- block addresses that bounced or complained
- allow internal testing domains
- stop reply attempts to specific domains

### Create an inbox-specific block
```python
entry = await client.inboxes.lists.create(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    direction="send",
    type="block",
    entry="do-not-contact@example.com",
    reason="complained",
)
```

### Create a top-level allow rule
```python
entry = await client.lists.create(
    direction="receive",
    type="allow",
    entry="important-customer.com",
    reason="trusted domain",
)
```

### Inspect list entries
```python
entries = await client.inboxes.lists.list(
    os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
    direction="send",
    type="block",
)
```

## API keys

### When to use scoped keys
- separate local development from production
- isolate webhook provisioning from runtime sending
- restrict read-only or send-only automations

### Create a limited top-level API key
```python
from agentmail import ApiKeyPermissions

key = await client.api_keys.create(
    name="konecta-auditor-runtime",
    permissions=ApiKeyPermissions(
        inbox_read=True,
        thread_read=True,
        message_read=True,
        message_send=True,
        message_update=True,
        draft_read=True,
        draft_create=True,
        draft_update=True,
        draft_delete=True,
        draft_send=True,
        webhook_read=True,
        webhook_create=True,
        webhook_update=True,
        metrics_read=True,
    ),
)
```

There are also inbox-scoped and pod-scoped API key endpoints in the SDK.

## Metrics

### Query useful delivery events
```python
metrics = await client.metrics.query(
    event_types=[
        "message.sent",
        "message.delivered",
        "message.bounced",
        "message.rejected",
        "message.complained",
        "message.received",
    ],
    start="2026-03-27T00:00:00Z",
    end="2026-03-28T00:00:00Z",
    period="hour",
)
```

Use metrics for operations dashboards, bounce debugging, and volume checks. Do not use them as the only source of truth for message state inside the app.

## Websockets

Websockets are useful for live monitoring or a local operator console. They are not the default ingestion path for this repo because webhooks fit the existing stateless backend better.

```python
from agentmail import Subscribe


async with client.websockets.connect() as socket:
    await socket.send_subscribe(
        Subscribe(
            type="subscribe",
            event_types=["message.received", "message.delivered"],
            inbox_ids=[
                os.environ["AGENTMAIL_CONVERSATION_INBOX_ID"],
                os.environ["AGENTMAIL_CRM_INBOX_ID"],
            ],
        )
    )

    async for event in socket:
        print(event)
```

## IMAP and SMTP

AgentMail also supports IMAP and SMTP.

Use this only when:
- a third-party email client must connect directly
- a manual smoke test is easier through a standard protocol
- an external tool cannot use the Python SDK

Prefer the SDK in repo code because the SDK gives us:
- typed message and thread IDs
- webhooks and websockets
- structured models
- metrics
- fewer manual protocol details

The official docs currently describe:
- IMAP host: `mail.agentmail.to`
- IMAP port: `993`
- SMTP host: `mail.agentmail.to`
- SMTP SSL port: `465`
- SMTP STARTTLS port: `587`
- username: inbox email address
- password: API key

## Known mismatches and caveats

### Thread update mismatch
- The official docs include examples that talk about thread mutation for follow-up labeling.
- The Python SDK reviewed here exposes thread list, get, attachment fetch, and delete.
- It does not expose `client.inboxes.threads.update(...)`.
- Before implementing a docs example that mutates threads, re-check the installed SDK version.

### Webhook verification helper gap
- The SDK exposes webhook secrets and Svix header types.
- It does not include a direct Python verification helper in the repo reviewed here.
- Use `svix.webhooks.Webhook` directly.

### Current repo naming mismatch
- Current CRM endpoints still use Gmail-shaped field names such as `gmail_thread_id`.
- If AgentMail replaces Gmail here, preserve meaning first.
- Rename fields only in a dedicated schema cleanup change.

## Recommended first implementation order in this repo
1. Add `AsyncAgentMail` client bootstrap and env config.
2. Add `AgentMailProvider` beside or in place of `GmailProvider`.
3. Make outbound contact sends work with `send(...)` and `reply(...)`.
4. Make outbound CRM sends work with `reply(...)` or `reply_all(...)`.
5. Add webhook endpoint with Svix verification.
6. Route `message.received` into existing backend inbound endpoints.
7. Route delivery events into existing delivery-status endpoints.
8. Add polling fallback for recovery and debugging.
9. Add draft-based follow-up only after base send/receive is stable.
