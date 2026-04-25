---
name: konecta-auditor-ceo-html-report
description: CEO-facing HTML audit playbook for Konecta Auditor. Use when writing Stage 4 HTML instructions, reviewing generated report HTML, or tuning executive-report style and content decisions.
---

# CEO HTML Audit Playbook

## When To Use
- Use this skill when working on:
  - `backend/ai/stage4_report_to_html.py`
  - HTML output review/critique loops
  - Artifact rendering quality for leadership audiences

## Product Intent
- This HTML is not a technical artifact. It is a leadership product.
- Primary reader: CEO/founder of the audited company.
- Job to be done:
  - make weaknesses obvious and undeniable,
  - connect weaknesses to revenue/pipeline risk,
  - make the evidence credible enough for recurring weekly tracking.
- Secondary business intent:
  - demonstrate enough clarity and value that leadership wants recurring audits and coaching.

## CEO Lens (What They Need Fast)
- In under 90 seconds, the CEO should understand:
  - what is broken,
  - how costly it is.
- Optimize for executive decisions, not technical completeness.
- Prefer signal over volume.
- Assume cold outreach context: first screen must prove this is about their real team, not a generic pitch.

## Above-The-Fold Contract
- Before scroll, show:
  - two-line impact hook in this style:
    - `Leads are replying.`
    - `But the replies are breaking trust.`
  - short context paragraph explaining this is a diagnostic snapshot with real buyer questions/replies,
  - one "Why this matters now" line,
  - one authenticity line (real conversations with your team + channels),
  - a right-side "ANALYZED CONTACTS" card with:
    - current risk row + badge,
    - tri-color strip + 3 legend chips,
    - contact list with dotted separators,
    - recognizable identities (email/whatsapp/name/brief notes).
- This first block must create trust and curiosity immediately.
- Do not spend above-the-fold space explaining company context the CEO already knows.
- Keep hero copy compressed:
  - context paragraph <= 30 words,
  - impact line <= 18 words,
  - authenticity line <= 14 words.
- In the right contacts panel, keep each contact meta line short (channel + role/note only), no diagnostics/timing prose.

## Non-Negotiable Output Principles
- Be faithful to provided evidence (`company_info`, stats, conversations, `experts_knowledge`, `report_text`).
- Never fabricate metrics, outcomes, quotes, or facts.
- Never expose internal process language ("rendered from JSON", "source artifact", etc.).
- Never show placeholder text (`None`, `null`, `N/A`, "Not provided in source data").
- If a value is missing:
  - omit only that field, or
  - omit that whole block if it has no value.
- Not all input fields must be shown. Display only CEO decision-relevant signal.

## Required Content Blocks
1. Executive hook (above the fold):
   - two-line impact headline
   - short context copy + bold impact line + authenticity line
   - right-side analyzed contacts card with dotted-list layout
   - no detached risk list here
2. Conversation evidence core:
   - show chat evidence early (before long analysis sections)
   - prioritize key turns that prove the critique
   - keep included turns verbatim
   - omit only clearly redundant/non-informative turns
3. Conversation enrichment (inside each chat card only):
   - short expert quote cues mapped to observed behavior
   - compact per-contact diagnostics (chips/strips)
   - inline red error notes attached to problematic employee messages
   - concise business microcopy labels (e.g., "What failed here", "Expert lens")
4. Contact diagnostics:
   - per contact in intro: identity + brief meta only
   - use color badges subtly, avoid metric-heavy rows
5. Inline error mapping:
   - place compact red error notes next to problematic employee messages
   - avoid isolated bottom error dump sections
6. Conclusion:
   - exactly two short sentences at the end
   - impact-focused, no remediation list

## Visual Density Rules
- Less sentences, more impact words.
- Prefer compact phrases, chips, and micro-visuals.
- Avoid cluttered number-heavy blocks unless strictly necessary.
- If charts are used, keep labels minimal; shape/size should carry the message.
- Avoid dashboard-like counters (`messages`, `outbound/inbound`, `captured totals`) in CEO view.
- Intro should feel like a trailer, not a dashboard.

## Diagnostic-Only Rule
- Focus on exposing errors and severity, not on prescribing fixes.
- Do not include long recommendation sections in this mode.
- No "what to fix this week" block unless explicitly requested by the user.
- No standalone post-chat sections besides a 2-sentence conclusion.

## Headline Rule
- Keep the large premium hero headline style.
- Use universally understandable wording (no internal terms like "thread").
- Headline should be punchy and business-relevant (lost clients, revenue risk, interactions).

## Research-Informed Craft Rules
- Use hierarchy through contrast, scale, and spacing before adding more text.
- Remove chartjunk/decorative noise; every visual element must earn its place.
- Prefer low-label diagrams:
  - severity strips,
  - compact matrices.
- Design for scan-first behavior:
  - reader should grasp "what this is" + "how severe" in ~10-20 seconds.

## Transcript Curation Rules
- Keep semantic meaning exact; improve readability aggressively.
- Remove or collapse repetitive email signature/footer noise:
  - repeated contact cards
  - markdown image/icon links
  - repeated `mailto:`/`tel:` blocks
  - decorative separators (`---`, table artifacts)
- Keep conversation body and critical tone markers.
- If a footer carries unique business meaning, keep only that meaningful part.
- Do not repeatedly announce cleanup actions inside the report.
- For long conversations, include only key turns needed to preserve interpretation.
- Balance:
  - not full raw dump,
  - not over-pruned abstraction.
- Show enough context around each critical mistake.

## Tone And Framing Rules
- Tone: executive, direct, commercial, pragmatic.
- Frame critique as controllable operational gaps, not personal attacks.
- Surface severe behavior clearly when needed, but avoid sensationalism.
- Replace insulting raw wording in analyst narrative with professional phrasing:
  - Good: "dismissive response damaged trust."
  - Avoid narrative slang/insults in section prose.

## Design And Structure Guidance
- Use a strong but clean executive layout:
  - clear heading hierarchy
  - short paragraphs
  - card-based blocks
  - visual status chips
- Keep CSS internal and simple to maintain.
- Mobile responsive by default.
- Avoid visual clutter and giant text walls.

## Anti-Patterns (Always Reject)
- Raw JSON dumps.
- Technical disclaimers to the CEO.
- Empty sections with filler copy.
- Repetition of the same caveat in multiple sections.
- Overly generic recommendations not tied to observed evidence.
- Overlong transcripts with obvious noise that hides the signal.
- Reports that feel like a sales brochure instead of an audit.
- Dense "data dump" panels full of precise metrics that do not improve decisions.

## Chat Rendering Rules
- Keep chat as a clean left/right bubble transcript.
- For company-side messages, show the actual contact identifier (email/whatsapp), not generic labels.
- Keep timestamps subtle and secondary.
- For critical employee lines, add compact red diagnosis as a side-callout (not as a new row below).
- Use clear color differentiation with premium calm palette:
  - buyer: soft light-blue tint,
  - employee: soft light-green tint.
- Keep each conversation compact (usually 4-8 key turns unless more context is essential).
- Keep chat as primary visual area and diagnostics as a compact side rail (stacked on mobile).
- Style error notes as side-callout cards (white card + subtle red left accent), not as stacked message-like blocks below.
- For no-response threads, skip expert lens and use a compact "no response" visual + short impact line.

## Expert Quote Style
- Render expert guidance as elegant pull quotes, not generic chip dumps.
- Preferred format:
  - short quote text
  - attribution line: `— Name, Source/Book` when available
  - one short mapping line to observed behavior.
- Never invent attributions that are not present in `experts_knowledge`.

## Conversation Attention Hierarchy
- Keep a strict visual order to reduce cognitive clash:
  - primary: chat transcript,
  - secondary: 1-2 inline error callouts,
  - tertiary: one compact expert quote block.
- If visual elements compete equally, remove the least valuable one.

## Final QA Checklist
- Is every major claim tied to observed evidence or expert knowledge?
- Are missing fields hidden cleanly?
- Are transcripts readable and de-noised?
- Are expert quotes mapped to specific failures?
- Are errors visible directly next to the problematic chat lines?
- Would a CEO grasp severity in under 20 seconds?
