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

1. Read the client meeting transcript when available.
2. If transcript is missing, use Workstation notes, landing page copy, CRM/WhatsApp evidence, prior campaign notes, and current page assets.
3. Extract the valuable case types, buyer language, geography, and cases to avoid.
4. Pick three distinct problem-first tests.
5. Save under `media/ads/<client-slug>/ads/<batch>/`.
6. Preserve prior batches. Never overwrite v1/v2/v3 unless asked.
7. Write `campaign-notes.md` explaining what changed and why.
8. If sending to Alan, send a short label by client and then images.

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
