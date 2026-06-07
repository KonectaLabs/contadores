---
name: konecta-meta-ads
description: Use before creating, revising, reviewing, or sending Meta/Facebook/Instagram ad images for Konecta clients. This is the required source for problem-first ad creatives, GPT Image prompts, buyer-side visual hierarchy, small trust/contact cues, and campaign asset organization.
---

# Konecta Meta Ads

## Non-Negotiable Rule

A direct-response ad is not a brand poster. The first thing the buyer sees must be their own problem and the outcome they want.

Before generating any ad, answer:

1. What exact problem is the buyer dealing with right now?
2. What object/scene proves that problem visually?
3. What outcome do they want from us?
4. What tiny cue tells them who can help and how to act?

If the ad first says who the professional is, it is wrong.

## Platform Source Of Truth

When the Contadores platform has a post-conversion transcript, use the
agent-native flow first:

1. Attach the transcript to the meeting.
2. Run `extract_client_profile_from_meeting_transcript`.
3. Use the saved `ClientProfile` summaries, `knowledge.ad_angles`,
   `knowledge.meta_planning`, source snippets, and unresolved questions before
   drafting creatives or a Meta publish plan.
4. If required Meta fields are missing, stage the plan with
   `contadores-agent campaigns graph stage-meta-plan` for CRM-owned campaign
   workspaces, or `stage_meta_publish_plan` for lower-level raw plans. Then run
   `sync_meta_inventory` to check existing account/Page/form/pixel/WhatsApp
   assets, and ask Facundo through `ask_human_question` for anything still
   missing; do not invent ad account IDs, Page IDs, WhatsApp phone number IDs,
   budgets, or special ad category decisions.
5. After staging and inventory sync, run `preflight_meta_publish_plan` to
   persist the ordered campaign, ad-set, creative, and ad operations. Live
   writes stay blocked unless the platform has explicit approval, credentials,
   and budget policy.
6. If a creative only has a local file path, run `upload_meta_creative_asset`
   before approval. It uploads media only, stores `image_hash` or `video_id`,
   and links the staged plan; it does not create Campaign, Ad Set, Creative, or
   Ad objects.
7. When Facundo/operator explicitly approves, run `approve_meta_publish_plan`
   with budget caps and the approval note before any future live publish.
8. Only after approval, credentials, and `META_MARKETING_LIVE_WRITES_ENABLED`,
   run `execute_meta_publish_plan` with `live_writes_requested=true`. It stores
   each Meta provider ID so retries skip already-created objects.

CRM-owned Ads workspace rule:

- Treat the CRM campaign as a workspace with one owned public form and a
  versioned `meta_plan_graph` in the shape `Campaigns -> Ad Sets -> Ads`.
- No prompt parsing lives in the platform. External agents should build JSON
  and use `contadores-agent campaigns create --graph-json`,
  `campaigns graph set`, `campaigns graph duplicate`, and
  `campaigns graph stage-meta-plan`.
- Campaign nodes own budget/objective. Ad-set nodes own audience, destination
  (`form`, `website`, `whatsapp`), Page/Instagram IDs, and optimization goal.
  Ad nodes own media, primary text, headline, description, CTA, and URL.
- Destination `form` means the CRM public form URL, not a native Meta instant
  form. It stages as `landing_page` so browser Pixel + server CAPI can optimize
  for the owned form submit event `Lead`.
- Public form slugs must stay opaque backend IDs. Do not set readable slugs from
  the client name, campaign name, niche, or creative concept.
- Public campaign surfaces must not expose internal campaign names. A campaign
  can only be `active` or `published` when the owned form has at least one
  public question; drafts can remain incomplete. Reserved answer keys such as
  `campaign_name`, `id`, or `phone_number` must be stored as `answer_<key>` so
  delivery metadata remains trustworthy.
- Once Meta provider IDs exist, pausing, archiving, or deleting the CRM campaign
  must pause the Meta Campaign/Ad Set/Ad objects first (`status=PAUSED`). If
  Meta cannot confirm, leave the CRM campaign visible instead of hiding possible
  live spend.

Validated local Meta defaults for Contadores/Konecta as of 2026-05-31:

- API version: `v25.0`
- Ad account: `act_396900435976478`
- Business: `1017654719078489`
- Page: `100444969619229`
- WhatsApp phone number: `881994095003323`
- WABA: `1873936066568522`

Keep the access token only in local secrets (`.env`, bashrc, or 1Password). Do not
write it in tracked docs or prompts. These IDs are defaults for the validated
Konecta setup, not permission to invent IDs for another client/funnel.

Credential boundary: never use CleverApply/Alejandro resources for Meta,
Google, OAuth, browser-login, or quota/billing work in Konecta. If the active
account/project/resource contains `cleverapply`, `clever-apply`,
`alejandro@cleverapply.com`, or `cleverapply-gws-20260519`, stop and switch to
Konecta/Contadores-owned credentials before making any external call.

## The 10/10 Pattern

Use the Eliana v3 pattern:

- dominant visual problem;
- big buyer-language headline;
- outcome/relief line;
- tiny trust cue;
- tiny action cue;
- no name/logo/footer taking over the creative.

Facundo's current benchmark is the Eliana v3 batch, especially
`media/ads/eliana-garcia/ads/v3/01-abogada-te-ayudo-a-cobrar.png`: a damaged
car shot from behind, a stressed person in the scene, a huge buyer-problem
headline, and small legal/WhatsApp cues. Future autonomous ad work should treat
that as the reference shape unless Facundo gives a newer winner.

Examples:

- car crash image + `TE CHOCARON?` + `Abogada: te ayudo a cobrar` + WhatsApp;
- injured worker + `ACCIDENTE LABORAL?` + `La ART no te pago?` + `Abogada: te ayudo a reclamar` + WhatsApp;
- family conflict papers + `DIVORCIO O CUOTA?` + `Abogada: ordena el proceso` + WhatsApp.

## Visual Hierarchy

The ad must pass the blur test: if small text is blurred, the buyer should still understand the problem.

Make the problem object dominate:

- crashed car, broken bumper, stressed driver;
- injured arm, hard hat, medical certificate;
- divorce papers, visitation calendar, child-support notes;
- tax alert, debt notice, blocked account, messy receipts;
- unpaid invoice, promissory note, overdue message;
- official-looking but generic notice or form.

Do not lead with:

- the client name;
- initials;
- a logo;
- a big footer;
- a portrait;
- `Soy [nombre]`;
- `Estudio juridico` or `Estudio contable` as the main message;
- a service list.

## Tiny Trust And Action Cues

Do include enough context to make the buyer trust and act. Keep it small.

Good cues:

- `Abogada`;
- `Abogado penal`;
- `Contadora`;
- `Contador`;
- `Reclamo legal`;
- a small balance-of-law icon;
- a small calculator/document icon;
- a WhatsApp-style contact icon or small `WhatsApp` button.

Bad cues:

- large logo lockup;
- brand footer occupying the bottom of the ad;
- big professional name;
- client initials as a decorative monogram;
- generic scales of justice as the main visual.

## Copy Formula

Use at most three reads:

1. Problem headline: `TE CHOCARON?`, `ACCIDENTE LABORAL?`, `AVISO DEL SRI?`, `TE LLEGO UN AVISO?`
2. Desired outcome or next step: `Te ayudo a cobrar`, `Mandanos la captura`, `Ordena el proceso`, `Plan de accion`.
3. Tiny trust/action cue: `Abogada`, `Contadora`, `WhatsApp`.

Use the buyer's words, not the provider's category.

Prefer:

- `La ART no te pago?`
- `Reclama a la aseguradora`
- `Mandanos la captura`
- `IIBB te marea?`
- `No improvises el proximo paso`
- `Manda el documento`

Avoid:

- `servicios profesionales integrales`;
- `soluciones legales completas`;
- `asesoramiento contable de excelencia`;
- `marketing para abogados`;
- long explanations;
- guarantees such as `cobro garantizado`, `ganamos tu juicio`, `resuelto en 24h`.

## Prompt Template

Use one image generation call per ad. Do not generate a background and add text later.

```text
Use case: ads-marketing
Asset type: square 1:1 Meta/Facebook/Instagram direct-response ad.
Primary request: Create a high-impact Spanish ad for [buyer] who [problem] and wants [outcome].
Core rule: Problem-first visual. Do not include client name, firm name, initials, portrait, or brand footer. Include only a SMALL trust/action cue: [Abogada/Contadora/etc.] and a small WhatsApp-style contact icon/button. These cues must be secondary and compact.
Scene: [specific dominant visual problem scene]. No official logos, no exact official UI replicas, no irrelevant branding.
Visual hierarchy: [problem object] dominates; headline is huge and readable; trust/action cue is small.
Exact on-image text:
[LINE 1 PROBLEM]
[LINE 2 OUTCOME/NEXT STEP]
[LINE 3 SMALL TRUST CUE]
WhatsApp
Composition: 1:1, mobile-first, realistic, high contrast, urgent but professional, not stock-photo, no institutional branding.
Constraints: no guarantees, no official seals, no watermark, no provider name.
```

## Source Workflow

Before choosing angles:

1. Use the saved `ClientProfile` when the platform has one, especially
   `knowledge.ad_angles`, `knowledge.meta_planning`, source snippets, and
   unresolved questions.
2. If the profile is missing but a meeting transcript exists, run
   `extract_client_profile_from_meeting_transcript` before drafting ads.
3. If transcript is missing, use Workstation notes, landing page copy, CRM/WhatsApp evidence, prior campaign notes, and current page assets.
4. Extract the valuable case types, buyer language, geography, and cases to avoid.
5. Pick three distinct problem-first tests.
6. Generate a testing batch, not a single final: default to 3 concepts x 10
   image variants per concept unless budget, policy, or user instruction says
   otherwise.
7. Save under `media/ads/<client-slug>/ads/<batch>/`.
8. Preserve prior batches. Never overwrite v1/v2/v3 unless asked.
9. Write `campaign-notes.md` explaining what changed and why.
10. If sending to Alan, send a short label by client and then images.

## Creative Volume Rule

The platform should not try to guess one perfect image. It should create enough
strong variations for Meta delivery to find winners:

- 3 core concepts from the client profile or transcript;
- 10 variants per concept by default;
- one complete image-generation prompt per variant;
- one staged `CreativeAsset` per generated image;
- one Meta ad per approved creative variant when publishing;
- keep variants in the same simple campaign/ad-set structure when targeting and
  destination are the same, so Meta can optimize delivery instead of splitting
  learning across tiny fragmented tests.

Variation should change the visual proof and composition more than the strategy:
rear angle vs side angle of a crash, person closer/farther, document visible or
not, color emphasis, headline placement, and WhatsApp cue placement. Do not make
10 copies that only change one adjective.

## Platform Publish Flow

Meta publishing is agent-native, but live writes are not allowed from creative
generation tools.

Use this order:

1. `extract_client_profile_from_meeting_transcript` when the transcript exists
   and no current `ClientProfile` has been saved.
2. `stage_ad_campaign` for objective, segments, angles, and budget guardrails.
   Include `creative_benchmark` with the Eliana v3 reference assets and
   `creative_testing` with `variations_per_concept=10` unless there is a reason
   to override.
3. `stage_creative_asset` for every generated or approved asset.
4. `stage_meta_publish_plan` for the typed Meta plan:
   `Campaign -> Ad Set -> Ad/Creative`, destination, budget, targeting,
   initial `PAUSED` status, lead-routing contract, and missing fields before
   live publish. For Click-to-WhatsApp, include the funnel and any existing
   `destination.whatsapp_referral_source_id`; for instant forms, include
   `destination.client_lead_source_id`. Owned campaign landing-page plans inherit
   `creative_testing.meta_optimization` from the `PlatformAdCampaign`; when it is
   enabled, the Ad Set must use `optimization_goal=OFFSITE_CONVERSIONS`,
   `billing_event=IMPRESSIONS`, and `promoted_object.pixel_id` +
   `custom_event_type=LEAD`.
5. `sync_meta_inventory` to read available ad accounts, Pages, lead forms,
   pixels, WhatsApp numbers, and existing campaigns before asking for IDs. Call
   it even without arguments; it falls back to configured server Meta IDs. If
   Page lead forms return 403, the missing Meta permission is usually
   `pages_manage_ads`.
6. `upload_meta_creative_asset` for each generated image/video that only has a
   local file path. This writes only to Meta media storage, stores `image_hash`
   or `video_id`, and links the staged publish plan. It still requires
   `live_writes_requested=true`, credentials, and live-write enablement.
7. `preflight_meta_publish_plan` to build and save the ordered provider
   operation graph.
8. `approve_meta_publish_plan` only after explicit operator approval. It must
   pass ready inventory, budget caps, idempotency, and `PAUSED` start checks.
9. `execute_meta_publish_plan` only after approval and live-write enablement;
   it executes the ordered graph and persists returned Meta IDs for retries.
10. `ask_human_question` when account/page/destination/category/budget details
   are missing. Do not invent Meta IDs.
11. `stage_meta_publish_attempt` only for raw payloads, provider responses, or
   manual publisher records.

Before any future live publish, the plan must have:

- ad account ID and account currency;
- Page ID plus WhatsApp phone number ID, lead form ID, or landing page URL;
- for Click-to-WhatsApp, either an existing `whatsapp_referral_source_id` mapped
  to the same funnel or a new-ad execution plan that will persist returned Meta
  ad IDs into the funnel after live publish;
- for instant forms, a ready `client_lead_source_id` whose Sheet, recipient,
  template, `meta_page_id`, `meta_lead_form_id`, and polling config feed Client
  Lead Delivery;
- special ad category decision when applicable;
- one or more ad sets with budget, targeting, placement/start-stop policy, and
  at least one ad;
- approved creative refs, final primary text, headline, and CTA;
- a Meta-ready creative ID, image hash, or video ID; local file paths and
  `creative_asset_id` are staging references, not live-publishable Meta assets;
- operator approval, idempotency key, and rollback/disable order.

Published lead flow must be traceable back to the platform. Use
`create_meta_lead_form` to create an instant form and optionally bind the
returned `lead_form_id` to `client_lead_source_id`; use
`subscribe_meta_lead_webhook` to subscribe the Page to `leadgen`. Both are live
writes and require explicit `live_writes_requested=true` plus
`META_MARKETING_LIVE_WRITES_ENABLED=true`. For
Click-to-WhatsApp ads, keep `referral.source_id` mapped to the funnel; new ads
created through `execute_meta_publish_plan` should persist returned Meta ad IDs
as `whatsapp_referral_source_ids`. For lead forms, use
`destination.client_lead_source_id` so the export/webhook path feeds Client
Lead Delivery instead of creating a side channel. When a webhook gives only
`leadgen_id`, call `fetch_meta_lead_form_to_delivery` so the platform retrieves
`field_data` from Graph API and queues Delivery. When the full Lead Ads payload
has already been retrieved from Meta, call `import_meta_lead_form_to_delivery`
with the `leadgen_id`, metadata, and `field_data`; both tools dedupe by
`leadgen_id`, append new imports to the connected Google Sheet when the service
account is configured, and queue the same WhatsApp delivery used by Sheets
imports. Use `backfill_meta_lead_form_to_delivery` to import recent historical
form leads after webhook setup or migration.

## Angle Selection

For each client, choose the three most concrete buyer-side triggers.

Good legal triggers:

- citation, hearing, police/court paper;
- car crash;
- workplace injury/ART;
- divorce, cuota, visits;
- unpaid debt or promissory note.

Good accounting/tax triggers:

- tax alert;
- embargo/debt notice;
- unfiled declaration deadline;
- online sales/marketplace tax mismatch;
- IIBB/AGIP/ARBA/SRI confusion;
- inspection/requerimiento.

Do not choose broad categories like `civil`, `laboral`, `contable`, or `familia` unless the image turns them into a concrete problem.

## Review Checklist

Before accepting an image:

- Is the problem visible before reading the copy?
- Is the headline readable on mobile?
- Is the trust cue small but present?
- Is there a clear action cue, usually WhatsApp?
- Did we avoid name/logo/footer dominance?
- Did we avoid official logos or exact government/platform UI?
- Did we avoid guaranteed legal/financial outcomes?
- Would the buyer think `esto es lo que me paso`?
- Would the buyer understand `aca me ayudan a conseguir la solucion`?

If not, regenerate a new batch and keep the old one.
