---
name: konecta-auditor-llm-first-extraction
description: Hard guardrail for semantic extraction in Konecta Auditor. Use whenever language, industry, identity, intent, quality, or other semantic fields are inferred from text/conversation/HTML.
---

# Konecta Auditor LLM-First Extraction

## Core Rule (Non-Negotiable)
When semantic extraction is needed, use a DSPy mini-program with structured Pydantic output.
Do not implement semantic extraction through keyword maps, regex heuristics, or ad-hoc parsing.
Do not compensate for weak prompt instructions by adding Python-side semantic filters, blacklists, dedupers, or cleanup around the LLM call.

## Must Use LLM For
- language detection,
- agent name / identity extraction,
- industry/domain inference,
- qualitative weak-point discovery,
- normalization of long research output into actionable bullets.

## Allowed Non-LLM Parsing (Narrow Exceptions)
Use deterministic parsing only for non-semantic cleanup:
- trimming whitespace,
- JSON decoding,
- strict protocol formatting,
- hash-based derivations.

Never use these exceptions to infer meaning.
If a rule can be stated in Signature instructions, keep it there instead of adding pre/post-processing code.

## Required Implementation Pattern
1. Define a Pydantic model for target fields.
2. Define a DSPy Signature with explicit output constraints.
3. Wrap it in a `Program` with `aforward`.
4. Put semantic selection/exclusion/deduplication criteria inside Signature instructions.
5. Keep fallback behavior simple and neutral (safe defaults), not heuristic inference.
6. Pass extracted structured fields to downstream stages as explicit inputs.

## Refactor Trigger
If you see:
- language marker dictionaries,
- industry keyword dictionaries,
- placeholder-name regex rules,
- rule stacks for semantic classification,
- Python-side post-filters around LLM outputs that try to correct semantic mistakes,

replace them with a mini-program extraction stage.

## Validation Checklist
- Stage contracts still validate via `/api/lab/stage*`.
- Conversation endpoint E2E still works.
- No new semantic regex/manual parsing introduced.
- No new semantic pre/post-processing around LLM calls introduced.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
