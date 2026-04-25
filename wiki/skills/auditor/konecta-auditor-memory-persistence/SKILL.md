---
name: konecta-auditor-memory-persistence
description: Persistent memory discipline for Konecta Auditor. Use whenever a better workflow, stable architecture rule, or repeated failure pattern is discovered so future agents inherit the improvement without re-explaining it.
---

# Konecta Auditor Memory Persistence

## Persist Process Improvements Immediately
Update all relevant memory surfaces whenever a stable insight is discovered:
- `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-development-memory/SKILL.md`
- `/Users/fgoiriz/private/repos/konecta-auditor/HOW_TO_DEVELOP.md`
- `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/.../SKILL.md`
- `/Users/fgoiriz/private/repos/konecta-auditor/AGENTS.md` when repository guardrails change

## Record High-Value Insights Only
Persist only durable rules such as:
- architecture contracts,
- validation gates,
- proven implementation patterns,
- recurring integration pitfalls,
- deterministic validation procedures.

Avoid noisy logs and one-off transient debugging details.

## Use Structured Memory Entries
For each new insight, capture:
1. decision/rule
2. reason
3. enforcement method (endpoint checks/scripts/files)
4. affected components

## Keep Skills As Primary Operational Memory
When a rule should be reusable across future tasks, place it in a dedicated skill rather than only in conversational notes.

## Enforce Memory Sync At End Of Substantial Work
Before ending major work, verify that skill docs and process docs reflect the latest stable method.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
