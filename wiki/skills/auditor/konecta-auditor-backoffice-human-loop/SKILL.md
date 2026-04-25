---
name: konecta-auditor-backoffice-human-loop
description: Human-in-the-loop backoffice workflow for Konecta Auditor. Use when implementing or explaining the new manual-send/manual-receive operations where backend generates drafts and humans relay messages through real channels.
---

# Konecta Auditor Backoffice Human Loop

## Purpose
This skill defines the new operating flow:
- backend is channel-agnostic,
- the backoffice orchestrates conversations,
- a human operator sends and receives real WhatsApp/email messages externally,
- backend only stores messages and generates AI drafts.

## Core Flow (Canonical)
1. Create a new project from a company URL.
2. Discover contacts/channels from the URL (Stage 1).
3. Create one chat thread per contact.
4. Generate the first AI message for each contact thread.
5. Operator copies draft message from backoffice.
6. Operator sends it manually from real account (WhatsApp/email).
7. When contact replies, operator copies inbound text into backoffice chat.
8. Backoffice registers inbound message, backend stores it and generates next AI draft.
9. Repeat send/receive loop while needed by the operator.
10. When chats are ready, generate audit report (Stage 3 + Stage 4) and view/download HTML.

## Backoffice UX Requirements
- Project list + project detail view.
- Contact list per project with independent chat threads.
- One chat UI per contact thread with full transcript history.
- Clear copyable outbound draft block.
- Explicit input box for operator to paste inbound contact messages.
- WhatsApp quick action for WhatsApp contacts:
  - render clickable `wa.me` link (normalized phone number) for fast handoff.
- Audit action at project level:
  - `Generate Audit` button,
  - HTML preview,
  - HTML download.

## Backend Contract Expectations
The backoffice should rely on agnostic endpoints and stage contracts:
- discovery: Stage 1 (`URL -> contacts/channels`)
- conversation loop:
  - create conversation context
  - register inbound contact message (save + generate + save)
  - fetch latest AI message
- evaluation/report generation:
  - Stage 3 for evaluations
  - Stage 4 for HTML artifact

No channel send/receive automation should be required in backend core.

## Conversation Loop Rules
- Every inbound message from contact must be persisted before generating next draft.
- Every outbound AI draft must be persisted even if operator has not sent yet.
- Duplicate inbound provider IDs (when provided) should be idempotent.

## Human Operator Rules
- Operator is responsible for real send/receive in WhatsApp/email.
- Backoffice is the source of truth for transcript state.
- If operator forgets whether they sent a draft, verify transcript and outbound status before posting another message.

## Out Of Scope For Backend Core
- Webhook listeners for providers.
- Auto-sending WhatsApp messages.
- Auto-reading inboxes.
- Scheduler/Prefect orchestration in core runtime.

These belong in optional `messenger/` integration workflows.

## Implementation Guardrails
- Keep stage-first contracts intact.
- Keep backend channel-agnostic.
- Keep transport logic external.
- Keep every state transition explicit in DB + API payloads.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
