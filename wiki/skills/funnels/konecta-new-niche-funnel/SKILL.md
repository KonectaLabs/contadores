---
name: konecta-new-niche-funnel
description: Orchestrate research and marketing assets for a new Konecta niche such as lawyers, real estate, doctors, or accountants. Use for market research, offer framing, Meta ad concepts, Loom assets, and captions; do not configure Website Agent or another runtime.
---

# Konecta New Niche Marketing Flow

Read only the next required skill:

1. `konecta-funnel-raw-memory` for original business intent.
2. `konecta-niche-market-research` for research.
3. `konecta-frankie-video-offer` for offer and message.
4. `konecta-niche-ad-images` for creative tests.
5. `konecta-niche-loom-video` for deck and script.
6. `konecta-video-model-prompting` only for model-generated video.

## Sequence

1. Define niche, market and current offer.
2. Produce the research prompt and wait for evidence.
3. Synthesize buyer, pain, desired outcome, language and risky assumptions.
4. Create three distinct ad concepts.
5. Build the short Loom deck and script when requested.
6. Caption the returned raw video when a file exists.
7. Package approved assets and source notes under `media/`.

Stop at real handoff points. Do not invent current price, guarantees, Meta
configuration, spreadsheet intake, WhatsApp templates or deployment state.

Website Agent is a separate product for selling and building static sites. A
new marketing niche does not become Website Agent configuration unless the user
explicitly asks for a product change in the `website-agent` repo.
