---
name: konecta-auditor-stage-contracts
description: Hard architecture contracts for Konecta Auditor stages. Use when creating, refactoring, or reviewing stage programs to enforce independent pure stages, explicit handoffs, and typed IO boundaries.
---

# Konecta Auditor Stage Contracts

## Enforce Canonical Stage Chain
Implement and preserve this chain:
1. `URL -> contacts/channels`
2. `conversation + objective + company_context + industry -> next reply`
3. `conversation + metadata -> evaluation`
4. `evaluations + metadata -> layered audit payload (JSON)`
5. `layered audit payload -> PDF content model (Pydantic JSON)`
6. `PDF content model -> programmatic PDF binary`

## Enforce Runtime Separation
- `backend/` must stay channel-agnostic: FastAPI + DB + DSPy stages only.
- Channel transport/orchestration belongs in `messenger/`.
- Do not wire channel listeners/senders into backend startup.

## Enforce Stage Independence
- Keep each stage as an independent `Program` with `aforward`.
- Keep cross-stage contracts in shared models; stage-local models stay near owners.
- Keep orchestration in FastAPI endpoint glue (`backend/endpoints/companies.py` and lab harnesses when present).
- Do not import Stage N-1 internals inside Stage N implementation.
- Accept previous-stage outputs as explicit typed input fields.

## Enforce Typed Contracts
Define and preserve explicit Pydantic shapes:
- Stage 1 output: `ContactDiscoveryResult` with per-contact objectives
- Stage 2 output: `ConversationTurnResult`
- Stage 3 output: `CompanyReport`
- Stage 4 output: `ReportDocumentModel` (render-ready PDF content model)

## Stage-Specific Contract Rules
### Stage 1
- Input: `url` plus optional controls only when they are actively wired.
- Output: contact/channel payload required downstream.
- Each discovered contact should already include the simple chat objective that downstream conversation/report stages will use.

### Stage 2
- Input: conversation transcript + objective + optional company context + industry.
- Output: `ConversationTurnResult(reply, done)`.
- Keep the turn contract minimal and deterministic.
- Internal planner/continuation subprograms are allowed if the external Stage 2 handoff stays `reply` + `done`.
- Express closure, bot-detection exits, and objective completion inside the Signature contract, not in Python heuristics.

### Stage 3
- Input: company metadata + reportable contacts + transcripts + per-contact objectives/stats.
- Output: `CompanyReport(company_info, language, experts_knowledge, contact_assessments, report_text)`.
- Never execute Stage 2 inside Stage 3.

### Stage 4
- Input: persisted Stage 3 `CompanyReport` JSON (`company_info`, `language`, `experts_knowledge`, `contact_assessments`, `report_text`).
- Output: `ReportDocumentModel` JSON persisted as `companies.report_pdf_model_json`.
- Stage 4 should combine deterministic transcript mapping + constrained editorial synthesis under strict Pydantic validation.
- Thread payloads should carry `objective_text`, and the first thread insight should summarize the objective result.
- PDF binary rendering happens after Stage 4 from persisted model JSON and must remain deterministic/programmatic.

## Run Refactor Safety Checklist
1. Validate signatures and models after each change.
2. Verify no reverse stage dependencies were introduced.
3. Ensure no stale/no-op fields in stage and endpoint payloads.
4. Validate via stage endpoints and conversation endpoint E2E.
5. Verify glue code only maps between already-valid stage contracts.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
