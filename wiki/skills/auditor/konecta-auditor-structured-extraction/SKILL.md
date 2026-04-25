---
name: konecta-auditor-structured-extraction
description: Structured extraction and normalization rules for Konecta Auditor. Use when converting raw text/HTML/conversation into machine-usable fields and favor typed DSPy signatures with Pydantic outputs.
---

# Konecta Auditor Structured Extraction

## Prefer Signature-Driven Extraction
Use DSPy mini-programs with typed outputs instead of brittle text parsing.
For semantic fields (language, identity, industry, qualitative analysis), treat manual keyword maps/regex heuristics as disallowed unless explicitly requested.

Execution pattern:
1. Define a Pydantic output model for the target structure.
2. Define a DSPy signature with explicit output fields.
3. Run extraction through a dedicated mini-program.
4. Put semantic selection, exclusion, and deduplication rules in Signature instructions, not Python glue.
5. Apply deterministic post-processing only for strict non-semantic protocol/boundary requirements.
6. Return typed model to downstream stages/endpoints.

## Avoid Regex-Heavy Parsing
Do not use regex/manual parsing for semantic extraction when a signature can express the target fields.

Use regex only for narrow deterministic cleanup tasks:
- static formatting cleanup,
- protocol delimiters,
- non-semantic sanitation.

## Prompt-First Input/Output Hygiene
- Pass raw unstructured context to the LLM whenever the prompt can explain what matters.
- Do not pre-filter, blacklist, trim down, or reshape semantic LLM input in Python unless adapter/protocol constraints force it.
- Do not post-filter, blacklist, normalize, or dedupe semantic LLM output in Python when the Signature instructions can express that rule.

## Keep Deterministic Logic Narrow
Use deterministic logic only for non-semantic boundaries such as:
- protocol formatting,
- adapter-required bundling/wrapping,
- transport-safe sanitation,
- rejecting obviously malformed values required by a downstream API.

## Apply Run-Proven Patterns
- Contact/channel discovery: return channel schema directly from signature output.
- Conversation turn generation: return a single typed `reply` result and keep orchestration thin.
- Evaluation synthesis: consume prior typed outputs directly; avoid hidden re-parsing.

## Enforce Refactor Checklist
1. Replace ad-hoc parsers with mini-program signatures.
2. Place models in shared or stage-local modules by ownership.
3. Add deterministic normalization only when a strict downstream boundary requires it.
4. Validate through `/api/lab/stage*` and conversation endpoint E2E.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
