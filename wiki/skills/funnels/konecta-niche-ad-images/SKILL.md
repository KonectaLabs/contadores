---
name: konecta-niche-ad-images
description: Generate three high-conversion GPT Image / GPT Image 2.0 ad prompts for a Konecta niche funnel after market research is available.
---

# Konecta Niche Ad Images

## Inputs Needed

- niche;
- buyer pain;
- desired outcome;
- service/offer;
- market/country;
- specific valuable case type or opportunity, when known;
- any visual reference from successful Contadores ads.

If market research is missing, use `konecta-niche-market-research` first.
If the task is about the offer angle, ad concept, or video-selling strategy, also use `konecta-frankie-video-offer`.

## Strategy

Create three distinct Meta ad image prompts:

1. **Specific profitable opportunity**
   - Show one exact case/opportunity the buyer wants.
   - Example: despidos, amparos, sucesiones, category 3 floods, braces patients.

2. **WhatsApp outcome**
   - Show the exact conversation/result the buyer wants.
   - Make the outcome concrete and inspection-friendly.

3. **Before/after filter**
   - Show the current bad state and the desired specific lead/ficha.
   - Tie relief to a valuable business outcome, not generic happiness.

## Prompt Requirements

Each prompt must include:

- square 1:1 ad format unless the user asks otherwise;
- clear Spanish headline copy;
- visible niche-specific object or work context;
- WhatsApp or lead-flow signal when relevant;
- one concrete synthetic example lead, form fill, CRM card, or case ficha;
- realistic, non-stock visual direction;
- no vague AI/automation imagery;
- no overloaded text.

Avoid generic "more leads" unless it is attached to a specific valuable lead type.

## Output Shape

For each variant:

- `Angle`
- `Prompt`
- `On-image text`
- `Why this tests something different`

End with:

```text
Next user action: genera estas 3 imagenes en GPT Image / GPT Image 2.0, subilas a Meta Ads y manteneme al tanto de cual queres usar para el funnel.
```
