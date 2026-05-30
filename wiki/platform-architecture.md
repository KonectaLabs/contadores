# Konecta Platform Architecture

This repo is moving from a niche WhatsApp CRM into an end-to-end marketing
automation platform. The target lifecycle is:

1. Configure a funnel and import leads from Google Sheets or Click-to-WhatsApp.
2. Send the approved opener template.
3. After the lead replies, send the configured offer strategy.
4. Let AI answer questions, collect scheduling details, and escalate doubts.
5. Create/confirm the meeting, capture transcript, and convert the lead.
6. Build the client profile, objections, market, segmentation, ads, and assets.
7. Publish or stage Meta Ads with budget controls and approval gates.
8. Deliver generated leads to the client and send 24-hour campaign updates.
9. Keep an operator cockpit with events, retries, model/tool activity, and open
   questions.

## Current Baseline

The repo already has the right single-server base:

- FastAPI backend, React/Vite frontend, bot worker, Docker Compose, SQLite WAL,
  and a shared `data/` volume.
- File-backed funnels from `config/default-funnels.json` plus server overrides
  in `data/funnels.json`.
- Google Sheets lead import, WhatsApp Cloud API sends/webhooks, message retry
  state, CRM stages, media handling, audio transcription through OpenAI API,
  Codex agent runs/tool calls, scheduled agent tasks, Workstation clients, and
  Client Lead Delivery.
- Agent-native lifecycle records now exist for meetings, reviewed client
  profiles, ad campaigns, creative assets, staged Meta publish attempts, client
  updates, and human questions. They are exposed through `/api/platform/*` and
  audited Codex tools, so the UI is optional for configuration and workflow
  state.

The major missing pieces are the live external integrations and cockpit depth:
Google Calendar event creation, transcript ingestion from real calls,
review/approval UX, Meta Marketing API writes, WhatsApp delivery for Facundo
doubts, and richer event/metric views across the lifecycle.

## Research Decisions

- CRM shape: model the platform around domain objects and lifecycle events, not
  around one chatbot state machine. HubSpot's CRM API is object/property/
  association-centered, which fits the future `Lead`, `Client`, `Campaign`,
  `Delivery`, and `HumanQuestion` boundaries.
  Source: https://developers.hubspot.com/docs/api-reference/latest/crm/understanding-the-crm
- Sheets ingestion: keep the current pull/import path; the Sheets values API is
  a stable source for row values by spreadsheet ID and range.
  Source: https://developers.google.com/workspace/sheets/api/guides/values
- Scheduling: use Google Calendar `events.insert` for real event creation once
  credentials and attendee rules are available. Until then, keep the current
  detail collection and human handoff.
  Source: https://developers.google.com/workspace/calendar/api/guides/create-events
- WhatsApp: keep production on WhatsApp Cloud API/templates/webhooks, with
  `wacli` only as a local/operator fallback. External sends must stay
  outbox-first and idempotent.
  Source: https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/messages/template/
- Meta Ads: build campaign/adset/ad/creative state and approval gates before
  enabling live write calls. Meta's Marketing API campaign structure separates
  campaign, ad set, ad, and creative concepts, so the repo should mirror those
  boundaries instead of storing one blob.
  Source: https://developers.facebook.com/docs/marketing-api/campaign-structure
- DSPy: use it for reusable reasoning programs and evals: lead replies,
  transcript extraction, ad strategy/copy, client updates, and prompt/program
  optimization once reviewed examples exist.
  Sources: https://dspy.ai/ and https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/optimization/optimizers.md
- Codex SDK: use it for side-effectful execution workflows: agent threads,
  repo/file artifacts, Workstation/client work, image-generation orchestration,
  tool use, and long-running operator tasks.
  Sources: https://platform.openai.com/docs/guides/code-generation and https://pypi.org/project/openai-codex-sdk/
- Images: use OpenAI image generation/editing APIs for creative assets, with
  persisted prompts, source images, generated files, and review state.
  Source: https://platform.openai.com/docs/guides/image-generation
- Observability: start with an append-only `platform_events` table and add
  OpenTelemetry later for traces/metrics/log export. OpenTelemetry's signal
  model maps cleanly to events, logs, metrics, and traces once the platform is
  split into more workers.
  Source: https://opentelemetry.io/docs/concepts/signals/
- Queues: do not add RabbitMQ, Kafka, Celery, or Redis yet. The current scale is
  better served by SQLite plus DB-backed outbox/scheduled tasks. RabbitMQ is
  justified when durable multi-worker ack/retry queues are needed; Kafka is
  justified when event replay and multiple consumers become core requirements.
  Sources: https://www.rabbitmq.com/tutorials/tutorial-two-javascript and https://kafka.apache.org/documentation/

## AI Split

DSPy owns semantic programs:

- lead reply classification/generation;
- scheduling-detail extraction;
- transcript-to-client-profile extraction;
- market/objection/segmentation analysis;
- ad angle/copy generation;
- client update generation;
- eval datasets and optimizers after examples are reviewed.

Codex SDK owns execution:

- audited agent threads per lead/client/campaign;
- tool calls that queue WhatsApp messages, update CRM state, create files, or
  schedule follow-ups;
- Workstation and client artifact generation;
- repo edits and operator task execution;
- image-generation workflows and generated asset persistence.

Do not let either layer bypass idempotency, approval, or event logging. AI can
recommend actions; side effects must go through typed tools, outboxes, and
append-only events.

## Offer Strategy

The mission offer is text-first because there is no Loom video yet.

Default campaign funnels now use:

- `offer_price_usd=599`
- `offer_payment_model=monthly`
- `offer_includes_website=true`
- `default_campaign_count=3`
- strategy `text_offer_599` with `delivery=text` and `sequence_step=text_offer`

The reusable copy pattern comes from existing CRM/manual examples:

```text
Son 599 USD mensuales. A cambio recibis oportunidades de clientes potenciales directo a tu WhatsApp. Eso lo logramos con una pagina profesional y campanas enfocadas. Si te interesa, lo vemos en una llamada corta y revisamos si tiene sentido para tu caso.
```

Media strategies can still be configured per funnel later, but default readiness
must not require an MP4 for the new offer.

## Platform Domains

Add these domains incrementally:

- `PlatformEvent`: append-only event stream for sheet import, outbound queue,
  send result, inbound message, AI decision, tool call, scheduling, conversion,
  ad draft, publish attempt, delivery, client update, and human question.
- `Meeting`: collected scheduling details, Google Calendar event ID, attendees,
  timezone, status, transcript link/file, extracted profile status.
- `ClientProfile`: normalized business, offer, market, objections, target
  segments, locations, tone, proof, exclusions, and reviewed knowledge.
- `Campaign`: client, funnel, objective, budget plan, Meta campaign/adset/ad IDs,
  state, approval status, spend/leads summary.
- `CreativeAsset`: prompt, source media, generated file, dimensions, approval,
  Meta creative ID, and failure reason.
- `MetaPublishAttempt`: request payload, response payload, idempotency key,
  operator approval, status, and rollback/disable action.
- `ClientUpdate`: 24-hour summary, leads delivered, blockers, next action,
  WhatsApp delivery state.
- `HumanQuestion`: Facundo/operator doubt with exact question, options, timeout,
  default action, WhatsApp correlation, answer, and promoted knowledge.

## Milestones

1. Baseline cleanup and observability
   - Move production templates out of `tmp/`.
   - Ignore generated runtime artifacts.
   - Add `platform_events` and expose `/api/platform/events`.
   - Emit events for outbound WhatsApp queueing.
   - Expose agent-native config tools so funnels and delivery sources can be
     created without using the UI.
   - Add agent-native lifecycle records/tools for meeting, profile, ads, Meta
     staging, client update, and human question state.
   - Verify funnel, Contadores, frontend build.

2. Text-first mission offer
   - Centralize offer fields in funnel config and UI.
   - Default campaign funnels to `text_offer_599`.
   - Update prompt/playbook copy away from the old 300 USD one-time offer.
   - Keep video strategies supported only as optional overrides.

3. Operator cockpit
   - Add a `Today`/Ops view for needs reply, failed sends, due follow-ups,
     events, agent runs/tool calls, human questions, meetings, campaigns blocked,
     delivery failures, and client updates due.
   - Keep the cockpit read/write over the same lifecycle records agents use;
     do not create UI-only configuration state.

4. Google Calendar scheduling
   - Add a calendar interface with mock mode.
   - Store meeting records and event IDs.
   - Create events only when email, date/time, timezone, and attendee rules are
     clear.

5. Human doubt escalation
   - Connect `HumanQuestion` to WhatsApp delivery/correlation.
   - Send Facundo a correlated WhatsApp question when AI is blocked.
   - Wait four minutes, use default/fallback when possible, and promote answered
     facts to reviewed knowledge.

6. Transcript and client onboarding
   - Ingest transcript/audio/text after conversion.
   - Use DSPy extraction into reviewed `ClientProfile`.
   - Attach source snippets and unresolved questions.

7. Ads creation workspace
   - Add ad angles, copy variants, image prompts, generated assets, and approval
     states.
   - Use Codex SDK for asset workflows and OpenAI image APIs for images.

8. Meta Ads publishing
   - Add read-only Meta inventory first.
   - Stage campaign/adset/ad/creative payloads.
   - Require operator approval for live publish and budget changes.

9. Client updates and delivery loop
   - Generate 24-hour client updates from campaign and delivery events.
   - Send via WhatsApp outbox.
   - Track client questions and escalation.

10. Scale upgrade
   - Move SQLite to Postgres before multiple backend workers.
   - Add RabbitMQ/Redis/Celery only when DB-backed scheduled tasks become the
     bottleneck.
   - Add OpenTelemetry export when multiple services need trace correlation.

## Known Blockers

- No Google Calendar credentials or final attendee/calendar ownership policy.
- No Meta Marketing API credentials, ad account IDs, or publish approval policy.
- No current Loom for the $599 offer, so the default offer path is text-only.
- Production `data/funnels.json` may still override the versioned seed; rollout
  must inspect/update the server override before deployment.
- Old historical skills/reference files still contain examples from previous
  offers; runtime-critical prompts and mirrored primary skills must stay aligned
  with the active offer.
