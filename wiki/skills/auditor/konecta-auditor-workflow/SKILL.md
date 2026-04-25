---
name: konecta-auditor-workflow
description: Product workflow map for Konecta Auditor. Use when designing features spanning stage extraction, agnostic conversation processing, evaluation, and optional messenger integrations.
---

# Konecta Auditor Workflow

## Keep Business Flow Explicit
Implement features against this pipeline:
1. receive company URL or existing conversation context
2. discover contacts/channels (Stage 1 when needed)
3. ingest inbound contact messages through agnostic endpoint
4. generate/store AI outbound reply through Stage 2
5. evaluate conversation quality (Stage 3)
6. generate dashboard artifact (Stage 4)
7. optionally deliver through `messenger/` integrations

## Preserve Stage Architecture
Use stage contracts from `konecta-auditor-stage-contracts` and keep each stage independent.

## Runtime Separation
- `backend/`: stage execution + agnostic conversation persistence/API.
- `messenger/`: transport/provider orchestration (email/whatsapp/schedulers).

## Align Output With Sales Outcome
Prioritize outputs that help leadership act quickly:
- profile-level strengths/weaknesses,
- response-time metrics,
- concrete recommendations,
- clean HTML artifact.

## Keep Expansion Path Open
Design with future recurring training loops in mind:
- repeated surprise interactions,
- progress-over-time tracking,
- periodic executive updates.

Do not block current implementation on future channel features.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
