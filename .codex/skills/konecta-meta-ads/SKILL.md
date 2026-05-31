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
   `stage_meta_publish_plan`, run `sync_meta_inventory` to check existing
   account/Page/form/pixel/WhatsApp assets, and ask Facundo through
   `ask_human_question` for anything still missing; do not invent ad account
   IDs, Page IDs, WhatsApp phone number IDs, budgets, or special ad category
   decisions.
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

## The 10/10 Pattern

Use the Eliana v3 pattern:

- dominant visual problem;
- big buyer-language headline;
- outcome/relief line;
- tiny trust cue;
- tiny action cue;
- no name/logo/footer taking over the creative.

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
6. Save under `media/ads/<client-slug>/ads/<batch>/`.
7. Preserve prior batches. Never overwrite v1/v2/v3 unless asked.
8. Write `campaign-notes.md` explaining what changed and why.
9. If sending to Alan, send a short label by client and then images.

## Platform Publish Flow

Meta publishing is agent-native, but live writes are not allowed from creative
generation tools.

Use this order:

1. `extract_client_profile_from_meeting_transcript` when the transcript exists
   and no current `ClientProfile` has been saved.
2. `stage_ad_campaign` for objective, segments, angles, and budget guardrails.
3. `stage_creative_asset` for every generated or approved asset.
4. `stage_meta_publish_plan` for the typed Meta plan:
   `Campaign -> Ad Set -> Ad/Creative`, destination, budget, targeting,
   initial `PAUSED` status, and missing fields before live publish.
5. `sync_meta_inventory` to read available ad accounts, Pages, lead forms,
   pixels, WhatsApp numbers, and existing campaigns before asking for IDs.
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
- special ad category decision when applicable;
- one or more ad sets with budget, targeting, placement/start-stop policy, and
  at least one ad;
- approved creative refs, final primary text, headline, and CTA;
- a Meta-ready creative ID, image hash, or video ID; local file paths and
  `creative_asset_id` are staging references, not live-publishable Meta assets;
- operator approval, idempotency key, and rollback/disable order.

Published lead flow must be traceable back to the platform. For
Click-to-WhatsApp ads, keep `referral.source_id` mapped to the funnel. For lead
forms, make sure the export/webhook path feeds the same Sheets/client-delivery
loop instead of creating a side channel.

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
