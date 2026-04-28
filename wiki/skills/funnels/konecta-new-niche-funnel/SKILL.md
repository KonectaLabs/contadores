---
name: konecta-new-niche-funnel
description: Orchestrate a new Konecta niche funnel from first idea to CRM configuration. Use when Facundo says he wants to start, add, replicate, or create a new funnel/niche such as abogados, real estate, inmobiliarias, medicos, contadores, or another industry.
---

# Konecta New Niche Funnel

## Read First

1. `../konecta-funnel-raw-memory/SKILL.md` for the original Facundo context.
2. `../konecta-niche-market-research/SKILL.md` before creating the research prompt.
3. `../konecta-frankie-video-offer/SKILL.md` before deciding the offer, ad angle, or Loom pitch.
4. `../konecta-niche-ad-images/SKILL.md` after Facundo returns the research.
5. `../konecta-niche-loom-video/SKILL.md` when building the one-minute video deck and script.
6. `../konecta-funnel-crm-config/SKILL.md` when configuring the app/backoffice.

If the niche is `abogados`, also read the trained niche skills under:

```text
/Users/fgoiriz/private/repos/contadores/abogados/skills/
```

## Operating Shape

Act as the funnel orchestrator. Do not jump to later assets before the prior input exists. Keep the user moving through explicit handoff points.

## Required Inputs

Ask only for missing items:

- niche name and country/market;
- offer or service Konecta will sell;
- price and payment terms;
- target client outcome;
- Calendly URL or whether to reuse the current one;
- spreadsheet URL/GID or whether the Meta form is not ready yet;
- video delivery preference: WhatsApp MP4 or external link.

If the user gives only the niche, start with market research and leave the rest for later.

## Step Sequence

1. **Market research prompt**
   - Output one prompt for the external market-research bot.
   - Tell Facundo to paste the research result back.
   - Stop there unless he already provided research.

2. **Research synthesis**
   - Convert the research into:
     - target buyer;
     - pain;
     - desired outcome;
     - offer angle;
     - risky/weak assumptions;
     - message hooks.

3. **Ad prompts**
   - Generate three GPT Image / GPT Image 2.0 prompts.
   - Each prompt should test a different angle but keep one clear pain/outcome.
   - Tell Facundo to generate the images externally and use them in Meta Ads.

4. **Video deck and script**
   - Use the 60-second Contadores deck as the base structure.
   - Build a niche-specific PPTX and speaker script.
   - Do not create the final video unless explicitly asked.
   - Tell Facundo to send the PPTX/script to the actor/presenter and return with the raw video path.

5. **Captions**
   - When Facundo provides a video path, run the TikTok Captions CLI.
   - Output the captioned MP4 path.

6. **WhatsApp templates and sequence**
   - Draft template-backed opener/follow-up texts.
   - Configure non-template messages after inbound reply.
   - Keep the initial opener template-approved.

7. **CRM funnel config**
   - Add or update the funnel in the CRM config.
   - Configure sheet source, messages, video strategy, Calendly, and alert emails.
   - Keep Contadores as one funnel, not special business logic.

8. **Server rollout**
   - Keep server-first rollout discipline.
   - Verify runtime readiness, the configured sheet, and the WhatsApp sequence on the server.

## Output Contract

At each stage, return:

- `Next user action`: exactly what Facundo should do next.
- `Agent output`: what you produced.
- `Waiting for`: the input needed to continue.

Avoid broad strategy essays. The funnel only advances when the next artifact exists.
