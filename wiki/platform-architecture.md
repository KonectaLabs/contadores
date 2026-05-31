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
- Agent-native lifecycle records now exist for meetings, DSPy-extracted draft
  client profiles, reviewed client profiles, ad campaigns, creative assets,
  staged Meta publish attempts, client updates, and human questions. They are
  exposed through `/api/platform/*` and audited Codex tools, so the UI is
  optional for configuration and workflow state.
- Meta publishing now has staged plan, inventory, media upload, preflight,
  approval, live execution, and lead-routing readiness slices. Click-to-WhatsApp
  executions persist returned Meta ad IDs into the funnel config; instant forms
  must point at a ready Client Lead Delivery source.
- `/api/platform/overview` now provides the cockpit read model used by the
  frontend `Ops` tab: blockers, human questions, campaigns, Meta publish
  attempts, meetings, client updates, assets, agent runs/tool calls, and recent
  events.

The major missing pieces are live credentials plus cockpit depth: production
Google Calendar credentials/internal attendee ownership, transcript ingestion
from real calls into the meeting record, review/approval UX, Meta Marketing API
writes, WhatsApp delivery for Facundo doubts, and richer event/metric views
across the lifecycle.

## Research Decisions

- CRM shape: model the platform around domain objects and lifecycle events, not
  around one chatbot state machine. HubSpot's CRM API is object/property/
  association-centered, which fits the future `Lead`, `Client`, `Campaign`,
  `Delivery`, and `HumanQuestion` boundaries.
  Source: https://developers.hubspot.com/docs/api-reference/latest/crm/understanding-the-crm
- Sheets ingestion: keep the current pull/import path; the Sheets values API is
  a stable source for row values by spreadsheet ID and range.
  Source: https://developers.google.com/workspace/sheets/api/guides/values
- Scheduling: use Google Calendar `events.insert` with explicit attendees,
  start/end timezone, and send updates. Service-account attendee writes require
  delegated Workspace authority, so the platform keeps a dry-run gate when
  credentials are missing.
  Source: https://developers.google.com/workspace/calendar/api/v3/reference/events/insert
- WhatsApp: keep production on WhatsApp Cloud API/templates/webhooks, with
  `wacli` only as a local/operator fallback. External sends must stay
  outbox-first and idempotent.
  Source: https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/messages/template/
- Meta Ads: build campaign/adset/ad/creative state and approval gates before
  enabling live write calls. Meta's Marketing API campaign structure separates
  campaign, ad set, ad, and creative concepts, so the repo should mirror those
  boundaries instead of storing one blob.
  Source: https://developers.facebook.com/docs/marketing-api/campaign-structure
  The official Python Business SDK also confirms the account/access-token
  boundary: Marketing API work requires an app, access token permissions, and
  ad-account-scoped CRUD calls.
  Source: https://github.com/facebook/facebook-python-business-sdk
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
- `Meeting`: collected scheduling details, Google Calendar payload/result,
  event ID/link, attendees, timezone, status, transcript link/file, extracted
  profile status.
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

## Meeting Scheduling Flow

Scheduling is agent-native and does not depend on the legacy scheduling-link UI:

1. The WhatsApp bot collects email, day, time, and timezone after the offer.
2. `create_platform_meeting` records the handoff state and conversation context.
3. `schedule_platform_meeting` builds the Google Calendar event payload with
   start/end timezone, lead attendee, internal attendees, description context,
   and private platform IDs.
4. Dry-run is allowed without credentials and stores `calendar_ready` or
   `calendar_blocked` on the meeting.
5. Live event creation requires explicit `live_writes_requested=true`,
   `PLATFORM_MEETING_CALENDAR_ID`, internal attendees, a Google service account,
   and a delegated Workspace user because Calendar attendees require delegated
   authority for service-account writes.
6. Successful writes store `calendar_event_id`, `calendar_event_link`, provider
   response, and an event in `platform_events`.

## Meta Ads Platform Flow

Meta Ads is a first-class lifecycle, not a generic notes field. The platform
should mirror Meta's own hierarchy and keep every live write behind a staged,
audited, approved plan:

1. `extract_client_profile_from_meeting_transcript` turns the post-conversion
   transcript into a draft `ClientProfile` with client facts, offer, exclusions,
   market, objections, geography, proof, ad angles, and Meta planning gaps.
2. `PlatformAdCampaign` holds the campaign objective, budget guardrails,
   segments, angles, approval state, and eventually the Meta campaign ID.
3. `PlatformCreativeAsset` holds each generated image/video, prompt, source
   refs, approval state, and eventually the Meta creative ID or asset hash.
4. `sync_meta_inventory` stores read-only ad account, Page, lead form, pixel,
   WhatsApp number, and existing campaign snapshots when credentials exist; if
   credentials are missing, it stores the blocker explicitly.
5. `stage_meta_publish_plan` creates the canonical staged payload:
   `Campaign -> Ad Set -> Ad/Creative`, destination, targeting, budget,
   initial `PAUSED` status, lead-routing metadata, missing fields, and
   rollback/disable order. Click-to-WhatsApp plans carry `funnel_id` plus an
   optional existing `destination.whatsapp_referral_source_id`; instant-form
   plans carry `destination.client_lead_source_id`.
6. `preflight_meta_publish_plan` turns the staged payload into an ordered,
   persisted execution graph without live writes by default.
7. `approve_meta_publish_plan` applies the audited approval gate: budget caps,
   ready inventory, idempotency, and every new object starting `PAUSED` before
   a plan can become a live-write candidate.
8. `execute_meta_publish_plan` runs the approved operation graph only when live
   writes are explicitly requested and enabled, then persists returned Meta IDs
   so retries skip already-created Campaign, Ad Set, Creative, and Ad objects.
   For Click-to-WhatsApp ads, returned ad IDs are also appended to the funnel's
   `whatsapp_referral_source_ids` so inbound webhooks route back to the same
   funnel.
9. `PlatformMetaPublishAttempt` records the staged plan, execution state, Meta
   response, error, idempotency key, and operator approval status.
10. Lead delivery connects the published ad or lead form back into funnel routing:
   Click-to-WhatsApp `referral.source_id` for WhatsApp conversations; Meta lead
   forms through a configured `client_lead_source_id`, either Sheets intake or
   the API-native `import_meta_lead_form_to_delivery` path, then Client Lead
   Delivery to the client's WhatsApp.
11. Client updates summarize spend/leads/blockers from events, delivery records,
   and Meta publish status.

Live Meta writes stay disabled until the platform has:

- ad account ID and account currency;
- Page ID, and either WhatsApp phone number ID, lead form ID, or landing page;
- lead routing: mapped Click-to-WhatsApp source ID or new-ad ID persistence
  plan, and a ready Client Lead Delivery source for instant forms;
- special ad category decision when required;
- approved creative assets and final copy;
- a Meta-ready creative reference (`meta_creative_id`, `image_hash`, or
  `video_id`); local generated files are not enough for live publish until they
  have been uploaded to Meta;
- campaign/ad set budgets, targeting, placements, start/stop dates, and
  tracking parameters;
- operator approval for publish and any budget increase;
- an idempotency key and rollback plan that starts new objects as `PAUSED`.

Do not add RabbitMQ/Kafka just for Meta publishing yet. The first DB-backed
publisher slices are `sync_meta_inventory` and `preflight_meta_publish_plan`:
they read and persist readiness/inventory state, build ordered Meta operations,
and emit events. The live executor slice is `execute_meta_publish_plan`: it is
still gated by credentials, approval policy, budget controls, and
`META_MARKETING_LIVE_WRITES_ENABLED`, but it can now execute the approved graph
and persist provider IDs for idempotent retries.
The approval policy slice is `approve_meta_publish_plan`: it records operator
approval only when budget caps, inventory IDs, idempotency, and `PAUSED` start
state pass. It still performs no external writes.
The lead-routing slice now blocks unsafe instant-form plans, validates existing
Click-to-WhatsApp source IDs against the target funnel, and updates funnel
routing after successful live ad creation.
The first Meta instant-form intake slice now accepts retrieved Lead Ads payloads
through `POST /api/client-lead-sources/{source_id}/meta-lead` or the audited
`import_meta_lead_form_to_delivery` tool. It flattens `field_data`, dedupes by
`leadgen_id` within the selected Delivery source, and queues the same WhatsApp
client notification used by Google Sheets imports.

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
   - First pass shipped as the `Ops` tab backed by `/api/platform/overview`.

4. Google Calendar scheduling
   - Add a calendar interface with mock mode.
   - Store meeting records and event IDs.
   - Create events only when email, date/time, timezone, and attendee rules are
     clear.
   - First scheduling gate shipped as `schedule_platform_meeting` plus
     `/api/platform/meetings/{meeting_id}/calendar-event`: dry-run payload,
     credential blockers, and optional live Google Calendar create.

5. Human doubt escalation
   - Connect `HumanQuestion` to WhatsApp delivery/correlation.
   - Send Facundo a correlated WhatsApp question when AI is blocked.
   - Wait four minutes, use default/fallback when possible, and promote answered
     facts to reviewed knowledge.

6. Transcript and client onboarding
   - Ingest transcript/audio/text after conversion.
   - Use DSPy extraction into draft `ClientProfile`.
   - Attach source snippets, ad angles, Meta planning hints, and unresolved
     questions.
   - First pass shipped as `/api/platform/meetings/{meeting_id}/extract-client-profile`
     plus the `extract_client_profile_from_meeting_transcript` Codex tool.

7. Ads creation workspace
   - Add ad angles, copy variants, image prompts, generated assets, and approval
     states.
   - Use Codex SDK for asset workflows and OpenAI image APIs for images.

8. Meta Ads publishing
   - Add read-only Meta inventory first: ad accounts, pages, forms, pixels,
     WhatsApp numbers, existing campaigns, and creatives.
   - First read-only inventory slice shipped as `sync_meta_inventory`; it
     persists either provider inventory or explicit credential blockers.
   - Stage typed campaign/adset/ad/creative payloads with
     `stage_meta_publish_plan`.
   - First publisher slice shipped as `preflight_meta_publish_plan`, which
     builds and persists the ordered Meta operation graph without live writes by
     default.
   - Approval gate shipped as `approve_meta_publish_plan`; it requires ready
     inventory, `idempotency_key`, explicit operator approval, budget caps, and
     `PAUSED` creation state before `live_writes_allowed=true`.
   - First live executor slice shipped as `execute_meta_publish_plan`; it
     creates Meta objects in `PAUSED` state when live writes are explicitly
     requested/enabled, stores every returned ID, and keeps retries idempotent.
   - Lead-routing readiness shipped: instant forms require a ready
     `client_lead_source_id`; Click-to-WhatsApp source IDs are validated when
     known and returned ad IDs are persisted to funnel routing after live
     execution.
   - Meta instant-form intake shipped: retrieved `leadgen_id` payloads can be
     imported into Client Lead Delivery without using the UI.

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

- No Google Calendar credentials/internal attendee env on the production server.
- No Meta Marketing API credentials or confirmed production ad account IDs.
- No current Loom for the $599 offer, so the default offer path is text-only.
- Production `data/funnels.json` may still override the versioned seed; rollout
  must inspect/update the server override before deployment.
- Old historical skills/reference files still contain examples from previous
  offers; runtime-critical prompts and mirrored primary skills must stay aligned
  with the active offer.
