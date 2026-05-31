---
name: konecta-frankie-ad-campaign
description: Use when creating, revising, or documenting Meta/Facebook/Instagram ad campaigns for a Konecta client from a sales call, Read AI transcript, Workstation notes, or client brief. Covers extracting the buyer's real pain, applying Frankie-style outcome-first offer logic, generating three ad image concepts, using image generation, and saving campaign assets under media/ads.
---

# Konecta Frankie Ad Campaign

## Core Rule

Sell the outcome the buyer wants, not the service the client provides.

Do not start from:

- who the professional is;
- the professional's name, initials, logo, or personal brand;
- a list of services;
- "we do ads";
- "we do accounting/legal/marketing";
- an institutional brand brochure.

Start from:

- the scary, expensive, or urgent moment the buyer recognizes;
- a visual scene that can be understood while scrolling quickly;
- the exact artifact the buyer receives or sees;
- the concrete next step that moves them out of the problem.

For direct-to-consumer service ads, especially legal or professional-service
ads, do not spend ad space saying who the provider is. The first screen should
not say "Soy Eliana Garcia", show the lawyer's name, or lean on a logo. The
buyer does not care yet. The ad must first communicate two things: "I recognize
the exact problem you have" and "I can help you get the outcome you want."
After that, add only a minimal trust/action cue when useful: a small legal
symbol, a small `Abogada` label, or a WhatsApp/contact cue. This should support
conversion, not become the headline or a brand block.

For example, for MMB Contable the stronger direction was not "orden fiscal profesional".
It was: a person receives an AFIP/ARCA alert, feels the pressure, sends the screenshot
by WhatsApp, and receives a clear plan of action.

## Skills To Read

Read the smallest useful set:

1. `konecta-meta-ads`
2. `konecta-frankie-video-offer`
3. `konecta-niche-ad-images`
4. `konecta-funnel-raw-memory`
5. `imagegen`

Also read these when relevant:

- `konecta-niche-market-research` if the niche/market is not understood yet.
- `konecta-new-niche-funnel` if this is part of a new funnel, not a one-off client.
- `workstation-client-delivery` if the client lives inside Workstation and has media/notes there.

If the user asks to create or update this skill, also use `skill-creator`.

## Source Gathering

Use the real source of truth before inventing angles.

1. If the client exists in the Contadores platform and a conversion transcript
   is already attached, use `extract_client_profile_from_meeting_transcript`
   first and treat the saved `ClientProfile` as the campaign brief.
2. Search Read AI first when the user mentions a client call or meeting.
   - Use the Read AI meeting list/search tools.
   - Find the meeting by title, participant, client name, or date.
   - Fetch `summary`, `topics`, `action_items`, `key_questions`, and especially `transcript`.
3. If Read AI has no transcript, use available summaries and ask only for the missing business facts that block ad creation.
4. If the client is in Workstation, inspect the client notes, transcript, uploaded media, page copy, and current public URL.
5. If legal, tax, platform, medical, financial, or ad-policy claims matter, verify current official sources before locking copy.

Extract:

- buyer segments the client actually wants;
- valuable cases or problems;
- words the client uses for those problems;
- geography/city/market;
- brand constraints and names to avoid;
- proof artifacts the buyer recognizes;
- services or areas explicitly de-prioritized.

## Frankie Translation

Translate the client's service into a buyer-visible outcome.

Use this sequence:

1. Choose one narrow buyer.
2. Choose one painful and valuable problem.
3. Show the visible trigger: message, alert, form, document, call, request, invoice, blocked account, booking, or lead.
4. Show the desired output: WhatsApp answer, checklist, plan, qualified inquiry, booked call, CRM card, document list, next-step map.
5. Make the ad text direct enough that the right person thinks "that is my problem".

Good ad concepts feel like:

- "When this arrives, send it here."
- "This is the kind of lead/case/message you will receive."
- "This is the first clean next step out of the mess."
- "This is the problem I have right now, and this ad is about it."

Avoid generic concepts:

- more clients;
- better marketing;
- professional service;
- trust/trajectory;
- AI automation;
- "we solve everything";
- agency or mechanism language.

## Image Strategy

Create three distinct 1:1 Meta ad concepts, then generate a real testing batch
with 10 variants per concept by default. Facundo's current benchmark is the
Eliana v3 batch, especially the traffic accident ad with the car hit from
behind, a person in distress, and huge problem-first text.

1. **Specific urgent problem**
   - Show the painful event already happening.
   - Example: tax alert, embargo notice, accident claim, lawsuit message, missed-call stack.
   - Make the problem object or scene dominate the image: crashed car, broken arm, warning notice, court paper, unpaid invoice, or messy document pile.

2. **WhatsApp outcome**
   - Show the exact message or artifact the buyer sends and the response they get.
   - Make the result inspectable, not abstract.

3. **Before/after filter**
   - Show the messy current state beside the clean next-step artifact.
   - Tie relief to one valuable business outcome.

For every variant define:

- target buyer;
- target city/region type;
- buyer pain;
- desired outcome;
- visual artifact;
- on-image text;
- prompt;
- why it tests a different hypothesis;
- claim/policy risks.

Visual hierarchy rule:

- The first thing a fast scroller sees must be the problem, not the provider.
- Use big, literal imagery: damaged car, injured arm, family document, official-looking generic notice, phone message, or the exact object the buyer is worried about.
- Do not reserve a footer for the client name, initials, legal scales, or logo unless the user explicitly asks for brand awareness.
- Keep any provider identity out of the image by default. If legal disclosure is required, put it outside the creative or in campaign copy, not as the main visual.
- It is acceptable, and often useful, to include a small trust/action cue such as `Abogada`, a small balance-of-law symbol, or a WhatsApp-style contact icon. Keep it secondary and compact.
- The image should pass this test: if all small text were blurred, would the buyer still understand the problem being advertised?

## Copy Rules

Keep on-image copy large, short, and mobile-readable.

Prefer:

- `Mandanos la captura`
- `Plan de accion en 24h`
- `Te dejamos claro el proximo paso`
- `Recibi consultas de [case type] con datos clave`
- `Cuando llega este aviso, no lo enfrentes solo`

Avoid:

- guarantees such as `resuelto en 24h`;
- direct personal-attribute accusations like `te embargaron`;
- provider-first lines such as `Soy [nombre]`, `[Nombre] Abogada`, `Estudio juridico`, or logo/initial footer treatments;
- hiding the legal/contact context completely when the buyer may need a trust cue before acting;
- claims that imply official status;
- exact government, court, or platform UI impersonation;
- logos for Meta, ARCA/AFIP, Mercado Libre, courts, insurers, or banks unless the user owns/has rights and the policy allows it;
- long explanations.

If the user asks for a stronger promise, make the fast deliverable the promise, not the final outcome:

- Use `plan de accion en 24h`.
- Avoid `te solucionamos el embargo en 24h`.

## Generation Workflow

1. Write the campaign plan before generating:
   - thesis;
   - three angles;
   - segmentation;
   - transcript evidence;
   - risk guardrails.
2. Stage the campaign with:
   - `creative_benchmark.name = "eliana_v3"` unless a newer winner exists;
   - Eliana v3 reference asset paths;
   - `creative_testing.concept_count = 3`;
   - `creative_testing.variations_per_concept = 10`;
   - `creative_testing.selection_strategy = "publish variants in Meta and let delivery optimize to winners"`.
3. Generate 10 images per angle with `imagegen`.
   - The imagegen prompt must describe the complete final ad: scene, subject,
     headline text, text placement, colors, hierarchy, and composition.
   - Do not generate a background and then add headline text, badges, CTA, or
     layout programmatically with PIL, ImageMagick, SVG, canvas, HTML, or CSS.
4. Inspect whether each result follows the idea:
   - problem is visible;
   - artifact is recognizable;
   - text is readable;
   - no forbidden logos/official impersonation;
   - outcome is clear.
5. Stage every accepted generated image as a `CreativeAsset`.
6. Publish approved variants as separate ads inside the simplest matching Meta
   ad-set structure so Meta delivery can allocate spend to the winners.
7. If the first batch is too institutional, create a new batch and keep the old one.
8. Do not delete prior usable versions unless the user explicitly asks.

## Folder Convention

Save campaign assets under:

```text
media/ads/<client-slug>/ads/<batch-slug>/
```

Use client slugs like:

- `mmb-contable`
- `estudio-manual`
- `barbitta-seguros`

Use batch slugs like:

- `v1`
- `v2`
- `meta-test-2026-05-18`

Name files by angle, not by random image id:

```text
01-embargo-plan-accion.png
02-ventas-online-alerta.png
03-agip-arba-claridad.png
```

Keep generated originals in `$CODEX_HOME/generated_images`; copy selected outputs into the repo folder.

## MMB Example

For the MMB Contable call:

- source meeting: Read AI `Diseño web y pauta para MMB`;
- client brand: `MMB Contable`;
- avoid leading with `Mariana Barbitta` because of homonym confusion;
- priority: tax/impositive problems, not generic accounting;
- strongest buyer pains: AFIP/ARCA alerts, embargos, inspections, Mercado Libre/online sales, AGIP/ARBA/IIBB confusion;
- stronger batch: `media/ads/mmb-contable/ads/v2/`;
- weaker first batch: useful but too institutional; keep as `media/ads/mmb-contable/ads/v1/`.

The key correction from the user: the ad should feel more like the service recipient's side of the story. Show the thing they fear, the message they can send, and the concrete relief/next step they get.

## Output Contract

Return:

- the source meeting or notes used;
- the campaign thesis;
- the three ad plans;
- the saved asset paths;
- inline image previews when available;
- any claims that were softened for policy or truthfulness.

Keep the answer concise. The assets and paths matter more than a long strategy essay.
