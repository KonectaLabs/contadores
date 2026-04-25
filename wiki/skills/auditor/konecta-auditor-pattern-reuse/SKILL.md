---
name: konecta-auditor-pattern-reuse
description: Mandatory sibling-repository pattern scan for Konecta Auditor. Use before implementing non-trivial features to reuse proven architecture, DSPy structure, endpoint contracts, and container conventions.
---

# Konecta Auditor Pattern Reuse

## Scan Sibling Repos Before Coding
Always inspect these repos first:
- `/Users/fgoiriz/private/repos/simple-avatar`
- `/Users/fgoiriz/private/repos/bogan`
- `/Users/fgoiriz/private/repos/inmobot`
- `/Users/fgoiriz/private/repos/outbound`

## Map Each Repo To Pattern Source
- `simple-avatar`: migration/frontend organization patterns.
- `bogan`: DSPy `Program` base patterns and async service structure.
- `inmobot`: inbound/outbound directional message persistence patterns.
- `outbound`: lean FastAPI lifespan + DB helper conventions and uv-first setup.

## Execute Quick Lookup Workflow
1. List candidate files (`find`/`rg`).
2. Read the closest equivalent implementation.
3. Reuse naming/layout/paradigm unless mismatch is clear.
4. Document reuse in summary and memory notes.

## Enforce Reuse Decision Log
Record three items in `.cursor/skills/konecta-auditor-development-memory/SKILL.md` after non-trivial change:
1. source repo
2. source file(s)
3. reused pattern and adaptation

## Avoid Reinventing Core Infrastructure
Do not redesign from scratch when sibling repos already implement:
- FastAPI startup/config conventions,
- concise DB helper methods,
- DSPy base class patterns,
- message history persistence conventions.

## Runtime Separation Reminder
Reuse channel/provider code only under `messenger/`.
Do not reintroduce channel orchestration into `backend/` runtime.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
