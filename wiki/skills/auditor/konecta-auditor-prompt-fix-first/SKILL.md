---
name: konecta-auditor-prompt-fix-first
description: Guardrail for behavior changes in Konecta Auditor DSPy/LLM Programs. Use when a request asks an existing Program or Signature to change tone, selection, exclusion, deduplication, ordering, grounding, strictness, or output format. Prefer fixing Signature instructions, docstrings, field descriptions, or examples before modifying Python code.
---

# Konecta Auditor Prompt Fix First

## Core Rule
When the request is "make this Program behave differently", fix the prompt layer first:
- Signature instructions,
- Signature docstring,
- output field descriptions,
- existing few-shot examples.

Do not start with Python-side heuristics, prefilters, post-filters, fallback branches, or orchestration rewrites.

## Default Workflow
1. Identify the exact `Program` and `Signature` that own the behavior.
2. Keep `aforward` orchestration unchanged unless there is a real contract or runtime bug.
3. Translate the requested behavior into prompt-layer rules:
   - inclusion/exclusion,
   - ranking/order,
   - deduplication,
   - tone/style,
   - strict formatting,
   - grounding/evidence limits,
   - language behavior,
   - safe-default behavior.
4. Validate on the narrowest path first:
   - stage lab endpoint,
   - targeted endpoint flow,
   - focused regression test.
5. Escalate to Python changes only if the requirement cannot be expressed reliably in the prompt/output contract.

## Prefer Prompt Fixes For
- "Be stricter."
- "Ignore this kind of evidence."
- "Return fewer, sharper bullets."
- "Do not repeat the same idea."
- "Sound more executive."
- "Only use grounded claims from the transcript."
- "Change output ordering or emphasis."
- "Do not include transport noise, signatures, or irrelevant context."

## Do Not Fix These In Python
- semantic blacklists or keyword maps used to override the model,
- output cleanup that removes/rewrites meaning after generation,
- input preprocessing that semantically hides or reclassifies evidence before the call,
- rule stacks that try to "correct" the Program after weak instructions,
- helper branches that switch behavior without first tightening the Signature.

## Allow Code Changes Only When
- the IO contract must change,
- a new field must be added or removed,
- a deterministic protocol/parsing step is required outside the model,
- there is a provider/runtime/storage bug,
- repeated prompt-only attempts were insufficient and the limitation is explicit.

When code changes are needed, document why prompt-only was not enough.

## Good / Bad Examples
Good:
- tighten the Signature to say "exclude signatures, disclaimers, and footer noise unless they change business meaning."
- add an output field description that requires concise CEO-facing language.
- refine instructions so the Program returns only the top evidence-backed issues.

Bad:
- add regex cleanup after generation to delete unwanted semantic content,
- add `if/else` overrides to force classifications the Signature should own,
- add Python dedupe layers because the prompt did not specify deduplication clearly.

## Validation Gate
- Prompt/Signature change is the first attempted fix.
- No new semantic Python cleanup is introduced.
- `aforward` stays recipe-like and minimal.
- Stage contract remains unchanged unless the user actually requested a contract change.
- Validation runs at the narrowest practical scope before broader integration checks.

## Companion Skills
Use alongside:
- `konecta-auditor-llm-first-extraction`
- `konecta-auditor-stage-contracts`
- `konecta-development-method`
