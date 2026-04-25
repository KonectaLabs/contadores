---
name: konecta-auditor-good-bad-canon
description: Exhaustive canon of user-approved and user-rejected patterns for Konecta Auditor (pipeline + CEO HTML). Use before changing Stage 3/4 contracts, HTML instructions, or report presentation.
---

# Konecta Auditor Good/Bad Canon

## Purpose
- Persist every durable insight from feedback loops, including small visual/content details.
- Provide a single source of truth for what is considered good vs bad in this project.
- Prevent regressions when iterating quickly on Stage 4 HTML output.

## Scope
- System and pipeline simplification decisions.
- Stage 3 structured report contract.
- Stage 4 HTML instruction quality bar.
- CEO-facing report style, structure, and anti-patterns.

## Core Audience
- Primary viewer is the audited company CEO/founder.
- Cold-open context is assumed: first screen must prove this report is real and personal to their team.

## Canonical Good (System Flow)
- Use company-centric input (`Company.to_llm_info`) as the main semantic source.
- Propagate `language` end to end and keep it explicit in artifacts.
- Keep Stage 3 and Stage 4 separated:
  - Stage 3: structured report JSON.
  - Stage 4: HTML rendering from persisted Stage 3 report.
- Keep report generation async with task polling.
- Keep HTML generation as separate async task endpoint for rapid iteration.
- Remove `industry` from contracts.
- Keep output contract minimal and explicit.
- Keep semantic selection/exclusion/deduplication rules inside LLM instructions instead of Python cleanup around the call.

## Canonical Bad (System Flow)
- Legacy layered payload naming and over-structured intermediary transport fields.
- Defensive/fallback-heavy glue (`x or "..."`, broad try/except for content defaults) where None is acceptable.
- Citations in final output or citation-heavy program inputs for this workflow.
- Sync-only regenerate-everything loops when only HTML needs iteration.
- Reintroducing removed legacy categories (for example, redundant contact classifications that add no value).
- Python-side semantic prefilters/post-filters around LLM calls (blacklists, heuristic dedupe, “fixup” cleanup) when the rule can live in the prompt/output contract.

## Canonical Good (Data/Prompt Hygiene)
- Hide null/missing fields in user-facing HTML.
- Use strict input-grounded claims only.
- Keep transcripts factual and verbatim for selected turns.
- Remove footer/signature transport noise while preserving meaning.

## Canonical Bad (Data/Prompt Hygiene)
- Showing placeholders like `None`, `null`, `Not provided in source data`.
- Dumping raw JSON or process disclaimers in final report.
- Over-explaining internal processing in the CEO-facing artifact.

## CEO HTML Product Intent
- Evidence first, instantly legible, no fluff.
- Design target: premium minimal product narrative.
- Report should create conviction quickly:
  - "This is about my team."
  - "This is real evidence."
  - "This has business impact."

## Hero Section (What Good Looks Like)
- Two-line impact hook style:
  - `Leads are replying.`
  - `But the replies are breaking trust.`
- One short context sentence.
- One bold impact sentence (`Why this matters now`).
- One short authenticity sentence about real conversations/channels.
- Keep copy compressed and readable without scrolling.

## Hero Section (What Bad Looks Like)
- Overloaded with counters/chips/metrics competing for attention.
- Generic copy that could belong to any company.
- Heavy technical or analytical text blocks above the fold.

## Contacts Panel (What Good Looks Like)
- Right-side `ANALYZED CONTACTS` card.
- Dotted separators between contacts.
- Contact rows are clean and short:
  - line 1: contact value (email/whatsapp).
  - line 2: channel plus concise role/note.
- Includes current risk row + badge.
- Includes tri-color strip + 3 legend chips with meaningful labels.
- Uses v6.1-like visual anchors:
  - panel title uppercase with tracking,
  - stronger email weight,
  - subtle gray meta line,
  - clear but elegant dotted separators.

## Contacts Panel (What Bad Looks Like)
- Collapsed round identity bubbles that compress readability.
- Long diagnostic prose inside contact meta lines.
- Clutter fields:
  - `Urgency: High`
  - `Contacts analyzed: N`
  - `Channel: ...`
  - message/outbound/inbound counters.
- Decorative strip without semantic meaning.

## Risk Strip Color Guidance (Locked Style)
- Do not mute strip colors; use vivid semantic saturation close to:
  - good: `rgba(22,163,74,.75)`
  - warn: `rgba(245,158,11,.85)`
  - bad: `rgba(220,38,38,.82)`

## Conversation Section (What Good Looks Like)
- Evidence cards with selected key turns only.
- Real participant identity labels (not generic rep labels).
- Buyer/employee differentiation via clean blue/green bubble system.
- Error callouts as side notes, attached to the exact problematic seller message.
- Expert cue near relevant thread when useful.

## Conversation Section (What Bad Looks Like)
- Long transcript dumps including signature noise.
- Standalone bottom "errors made visible" blocks.
- Error callouts rendered like additional chat messages.
- Too many header chips and dense metric rows.
- Detached global sections that steal attention from evidence.

## No-Response Thread Rule (Critical)
- If there is no employee reply:
  - show compact "No response" visual state,
  - one factual sentence + one short business-impact sentence,
  - skip expert lens for that thread.

## Expert Lens Rule
- Use concise quote + attribution + one observed mismatch.
- Keep it contextual and near the conversation.
- Avoid forcing expert lens where evidence type is "no response only".

## Conclusion Rule
- Exactly two short sentences.
- Sharp commercial framing.
- No remediation checklist.

## Strong Headline Examples (Use As Inspiration)
- `Leads are replying. But the replies are breaking trust.`
- `Buyers are engaging. The conversations are pushing them out.`
- `Interest is real. Execution is leaking revenue.`
- `Prospects start warm. Replies end the deal.`
- `Inbound demand is alive. Trust is collapsing in-thread.`

## Weak Headline Examples (Avoid)
- `3 Threads. 3 Stalled Outcomes.`
- `Micro Funnel Analysis`
- Internal/jargony wording that a CEO would not naturally use.

## Micro-Insights That Must Not Be Lost
- First screen should feel personal and real, not salesy.
- Recognizable contact identities are key curiosity anchors.
- Minimal text beats maximal explanation.
- Visual hierarchy must avoid attention clashes.
- "Less sentences, more impact words" is a stable preference.
- If a data point does not improve CEO decisions, it is likely clutter.
- Keep elegance over raw density.

## Anti-Pattern Checklist (Hard Fail)
- Standalone top-risk slab above conversations.
- Dashboard-like clutter metrics.
- Null placeholders.
- Generic "company context" exposition for CEO.
- Verbose per-contact meta diagnostics.
- Overly muted strip colors when semantic emphasis is intended.
- Message-level red alerts that look like chat bubbles.

## Persistence Protocol (Do This Every Iteration)
- Every meaningful feedback item, even tiny UI details, must be appended as a new log entry in this skill.
- Entry format:
  - Date
  - Area (`hero`, `contacts panel`, `chat`, `callouts`, `conclusion`, `pipeline`, etc.)
  - Verdict (`good` or `bad`)
  - Concrete detail
  - Why it matters
  - Action taken
- Do not collapse micro-insights into generic summaries.
- Keep contradictory iterations visible with final resolved preference marked.

## Living Insight Ledger (Seed)
- 2026-02-22 | hero | good | two-line impact hook style accepted | fast comprehension | locked.
- 2026-02-22 | contacts panel | good | right-side analyzed contacts with dotted separators | clear scan | locked.
- 2026-02-22 | contacts panel | bad | long diagnostic meta text in contact rows | clutter | removed.
- 2026-02-22 | risk strip | good | vivid v6.1-like saturation | clearer signal | locked.
- 2026-02-22 | top area | bad | urgency/count/channel chips | scammy/cluttered feel | removed.
- 2026-02-22 | chat | good | blue/green clean bubbles | modern clarity | kept.
- 2026-02-22 | error notes | bad | red alerts below message as pseudo-message | noisy | replaced with side-callouts.
- 2026-02-22 | no-response thread | good | compact no-response treatment | concise impact | kept.
- 2026-02-22 | no-response thread | bad | forced expert lens on no-response | unnecessary | removed.
- 2026-02-22 | conclusion | good | two-sentence close | decisive ending | locked.
