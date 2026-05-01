---
name: konecta-funnel-raw-memory
description: Raw Facundo context for the Konecta niche-funnel system. Use when reconstructing the original intent behind reusable funnels, niche research, Meta ads, Loom videos, WhatsApp sequences, CRM configuration, or cross-repo Konecta work.
---

# Konecta Funnel Raw Memory

## Source

- Date captured: 2026-04-25
- Speaker: Facundo Goiriz
- Repo context: `/Users/fgoiriz/private/repos/contadores`
- Related repos must be treated as one connected "super repo", especially:
  - `/Users/fgoiriz/private/repos/contadores`
  - `/Users/fgoiriz/private/repos/konecta-labs`
  - `/Users/fgoiriz/private/repos/tiktok-captions-cli`

## Raw Memory

Facundo explained that Konecta first chose a niche based on the technical abilities of the team. The team are programmers, so they looked for industries where automation, LLMs, documents, text workflows, websites, SEO, and ads can create leverage. The initial candidate industries were real estate, lawyers, and accountants.

The first implemented niche was accountants. The research and offer thinking came from the Frankie Finn material and Konecta notes in this repo and in the connected Konecta repos. The first move was to research the industry: biggest pains, desired outcomes, and what would feel valuable to that niche. That research was done with the Bien / Frank Team market-research bot.

After research, Konecta creates ad images with GPT Image 2.0. For the accounting funnel, the successful ad targeted accountants who depend too much on word of mouth and referrals, and who want more clients, especially monthly-retainer clients from businesses and individuals. The images are published through Meta Ads. Interested leads fill a Meta form.

The Meta form responses appear in a spreadsheet. Facundo has access to that spreadsheet. The current Contadores system reads rows from that spreadsheet into the server database. The app is a CRM/backoffice that sends an initial WhatsApp template. Once the lead replies, the flow sends service information and a short video. The video is important because the team follows Frankie Finn's Loom strategy: do not sell the service by listing tasks; sell the benefits, show how the service works, explain the price, explain what the client gets back, and give a concrete next step to start working together.

To replicate this for another industry, the full process must be repeatable:

1. Create market research for the niche.
2. Create two or three ad images and test them.
3. Configure the Meta lead form manually.
4. Integrate the spreadsheet into the CRM.
5. Configure the WhatsApp steps and message sequence for the new funnel.
6. Create new WhatsApp templates for opener and follow-ups.
7. Create a one-minute video pitch for the niche.
8. Caption the finished video with the local TikTok captions CLI.
9. Configure the final Calendly step.
10. Keep the CRM able to run several niches, for example contadores and abogados.

Facundo wants the agent to help run that sequence in future chats. Example trigger: "quiero empezar un nuevo funnel de abogados." The agent should know the step-by-step process. It should first generate a market research prompt for the external market-research bot and then wait for Facundo to paste the research result back. After receiving the research, the agent should generate three strong ad image prompts, using the Frankie strategy and the successful Contadores ad as reference.

For the one-minute video, the agent should not directly generate the final video. It should create the PPTX presentation and the script. The presentation should copy the structure and visual logic from the existing one-minute Contadores deck, not the long four-minute version. The niche-specific content, service, benefits, price, and next step should change based on what Facundo provides. After the deck and script are ready, Facundo sends them to a voice actor or presenter. That person records the screen while presenting the deck and creates the one-minute video.

After Facundo downloads the raw one-minute video, he gives the file path to the agent. The agent should run the local TikTok Captions CLI to add burned-in captions. The relevant repo is `/Users/fgoiriz/private/repos/tiktok-captions-cli`.

After the video exists, the CRM sequence can be configured: initial template, reply-triggered pitch text, video send strategy, follow-up, Calendly message, human handoff rules, and any follow-up templates.

Facundo also wants the codebase to stop being only "Contadores". The platform should become generic enough to add another niche/funnel visually through the UI and also through a config file that Codex can edit. The UI should have an add-funnel flow where the operator can define:

- funnel or niche name, for example `abogados`;
- spreadsheet link or spreadsheet filtering logic;
- opener template and text;
- pitch/video intro message;
- whether the video is a link or an uploaded MP4;
- Calendly message; URL is fixed as `https://calendly.com/facundogoiriz/crecimiento`;
- follow-up messages and template-backed follow-ups;
- strategy/sequence settings.

The visual UI should write to the same config file that Codex can edit, so a human can configure funnels visually and Codex can configure them from code/config when asked.

The CRM should keep the same operator experience that exists now for Contadores, but split by funnel/section. Contadores should become one configured section, not the only hardcoded product.

Facundo wants documentation first. The raw memory must be preserved so future agents can reread the original business intent and improve the structured process later. Then the raw memory should be transformed into segmented skills that describe the intention, process, media generation, ad strategy, video creation, CRM configuration, WhatsApp templates, and the orchestration skill for starting a new niche funnel.

## Existing Artifacts To Reuse

- Contadores funnel skill:
  `/Users/fgoiriz/private/repos/konecta-labs/skills/konecta-contadores-meta-whatsapp-funnel/SKILL.md`
- Frankie source stack:
  `/Users/fgoiriz/private/repos/konecta-labs/frankie-sales/`
- One-minute Contadores deck:
  `/Users/fgoiriz/private/repos/contadores/media/presentations/loom-video-vender-a-contadores/Loom Script 60s.html`
- PPTX export workflow:
  `/Users/fgoiriz/private/repos/contadores/wiki/skills/cursor/loom-deck-pptx/SKILL.md`
- WhatsApp template CLI:
  `/Users/fgoiriz/private/repos/contadores/src/scripts/whatsapp_templates.py`
- Captions CLI:
  `/Users/fgoiriz/private/repos/tiktok-captions-cli`
