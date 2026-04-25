---
name: konecta-niche-loom-video
description: Build the one-minute niche sales video assets for Konecta funnels: PPTX deck, speaker script, actor handoff, and captioned MP4 workflow.
---

# Konecta Niche Loom Video

## Canonical References

- 60s Contadores source:
  `/Users/fgoiriz/private/repos/contadores/media/presentations/loom-video-vender-a-contadores/Loom Script 60s.html`
- PPTX export skill:
  `/Users/fgoiriz/private/repos/contadores/wiki/skills/cursor/loom-deck-pptx/SKILL.md`
- Captions CLI:
  `/Users/fgoiriz/private/repos/tiktok-captions-cli`

## When Creating A New Deck

Use the one-minute deck structure, not the long 4-minute deck.

Create a new folder under:

```text
media/presentations/loom-video-vender-a-[niche-slug]/
```

Copy the 60-second deck workflow and adapt:

- niche-specific WhatsApp/example lead;
- pain/outcome;
- what Konecta builds;
- price/payment terms;
- next step;
- speaker notes/script.

## 60-Second Arc

1. **Outcome first**
   - Show what the buyer wants to see in WhatsApp or their pipeline.
2. **Why this matters**
   - Name the current pain in plain language.
3. **What Konecta does**
   - Explain the mechanism only after the outcome is clear.
4. **Investment**
   - State price with context.
5. **How to start**
   - Calendly, call, first payment/onboarding, and expected next action.

## After PPTX Is Ready

Tell Facundo:

```text
Next user action: mandale el PPTX y el script al actor/presenter. Que grabe pantalla + voz en un video de ~60 segundos. Cuando tengas el MP4 raw, pasame la ruta y le agrego captions.
```

## Captioning Command

When Facundo provides the raw MP4 path:

```bash
cd /Users/fgoiriz/private/repos/tiktok-captions-cli
uv run tiktok-captions-cli render /path/to/input.mp4 -o /path/to/output_captions.mp4 --language es --keep-files
```

Use the output MP4 as the WhatsApp MP4 strategy file for the funnel.

