---
name: konecta-niche-ad-images
description: Generate high-conversion GPT Image / GPT Image 2.0 Meta ad concept batches for a Konecta niche funnel after market research is available.
---

# Konecta Niche Ad Images

Read `konecta-meta-ads` before generating or revising Meta ad images. It is the
source of truth for problem-first visual hierarchy, tiny trust/action cues, and
the Eliana v3 prompt pattern.

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

Create three distinct Meta ad concepts, then write 10 variant prompts per
concept by default so Meta can test real creative diversity.

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
- a dominant literal visual of the buyer's problem that can be understood while scrolling quickly;
- WhatsApp or lead-flow signal when relevant;
- one concrete synthetic example lead, form fill, CRM card, or case ficha;
- realistic, non-stock visual direction;
- no vague AI/automation imagery;
- no overloaded text.

Avoid generic "more leads" unless it is attached to a specific valuable lead type.

Avoid provider-first branding by default:

- Do not put the professional's name, initials, logo, or "Soy [nombre]" in the image unless the user explicitly asks for brand awareness.
- Do not spend bottom/footer space on the provider's identity in direct-response ads.
- The ad should first show the buyer's problem and desired outcome: crashed car and insurance money, injured worker and ART payment, divorce/family paperwork and an ordered next step, tax alert and a plan, etc.
- The image should communicate "this is my problem" before the viewer reads any small text.
- After the problem/outcome is clear, include a small conversion cue when useful: `Abogada`, a small legal/balance icon, or a WhatsApp-style contact icon. This cue should be compact and secondary, not a logo-first layout.

## Output Shape

For each concept:

- `Angle`
- `10 variant prompts`
- `On-image text`
- `Why this tests something different`

End with:

```text
Next user action: genera 10 variantes por concepto en GPT Image / GPT Image 2.0, subilas a Meta Ads como ads separados dentro del mismo test, y deja que Meta encuentre las ganadoras.
```
