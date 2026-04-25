---
name: konecta-development-method
description: Master operating system for Konecta Auditor engineering. Use for implementation/refactor/validation work to enforce stage-first development, structured DSPy IO, sibling-repo pattern reuse, agnostic endpoint E2E, Docker validation, and DB forensics.
---

# Konecta Development Method

## Load Companion Skills In Order
Load and follow these companion skills in this exact sequence:
1. `zen-of-development`
2. `konecta-auditor-stage-contracts`
3. `konecta-auditor-structured-extraction`
4. `konecta-auditor-llm-first-extraction`
5. `konecta-auditor-prompt-fix-first`
6. `konecta-auditor-pattern-reuse`
7. `konecta-auditor-endpoint-e2e`
8. `konecta-auditor-docker-prod-validation`
9. `konecta-auditor-db-forensics`
10. `konecta-auditor-delivery-outbox`
11. `konecta-auditor-memory-persistence`

Skip a companion skill only when the user explicitly asks to skip.
If the task touches messenger email delivery, also load `konecta-auditor-email-delivery`.
If the task involves production deploys, server log inspection, or validating whether a fix is live on the VPS, also load `konecta-auditor-server-deploy`.

## Execute Canonical Workflow
1. Define input and output contracts first.
2. Implement one stage at a time as a `Program` with `aforward`.
3. Validate each stage in isolation.
4. Pass prior-stage outputs as explicit inputs to the next stage.
5. Add FastAPI/DB glue only after stage contracts are stable.
6. Run endpoint E2E loops.
7. Run Dockerized E2E loops.
8. Verify DB state and persisted artifacts.

## Enforce Non-Negotiable Rules
- Keep stage logic pure and independent.
- Never make Stage N import and execute Stage N-1 internals.
- Prefer DSPy signatures plus Pydantic models over regex/manual parsing.
- For LLM-owned input/output, keep semantic policy in Signature instructions, not in Python-side prefilters, blacklists, dedupers, or output cleanup.
- When the requested change is behavioral rather than contractual, fix the Signature/prompt layer before touching Python orchestration.
- Remove dead parameters/fields as soon as they become no-ops.
- Keep stage contracts, pipeline wiring, API/UI payloads, and docs synchronized.
- Keep real-provider integration in `messenger/`; backend runtime must remain channel-agnostic.
- Keep shared backend endpoint contracts channel-complete for all consumers (frontend + bot); do not narrow backend payloads to current bot/provider capabilities.
- Enforce provider capability filtering in `bot/` or messenger runtime, not in shared backend endpoint payload shaping.
- In local development, do not add DB migrations; when schema changes, recreate SQLite (`data/database.sqlite`) instead.
- **Model Placement**: Define models used only by a single endpoint immediately above that endpoint. Keep shared models at the top of the file.
- **Simplicity**: Fewer lines, fewer files, fewer folders. Consolidate when possible without violating architectural boundaries.
- **Lego-like Composition**: Main functions (`aforward`, endpoints, orchestrators) must compose core functions/methods, not implement logic. They should read like a recipe: gather inputs, call methods, combine results, return output. All implementation logic belongs in the composed methods.
- **Readable Recipe First**: Keep straightforward orchestration visible in main functions (task lists, gathers, loops, direct combinations). Avoid single-use `build_*` wrappers that only rename trivial flow steps.

  **Example from `stage1_url_to_contacts.py`:**
  ```python
  async def aforward(self, url: str) -> ContactDiscoveryResult:
      """Forward the URL to the program and return the contact discovery result."""
      process_1 = self.process_search(url, pro_search)
      process_2 = self.get_html_relevant_parts(url)
      output_text, html_text = await asyncio.gather(process_1, process_2)
      content = output_text + html_text
      result = await self.extract_contacts(content)
      return result
  ```
  Notice: `aforward` composes three methods (`process_search`, `get_html_relevant_parts`, `extract_contacts`). All implementation logic lives in those methods, not in `aforward`.

## Use Approved Tooling Strategy
- Use `uv` for Python commands.
- Use parallel context gathering whenever subtasks are independent.
- Run subagents in parallel only for independent discovery tasks, then merge under one coordinator.
- For production deploys, do not use `scp` or manual remote file edits as the default path. The canonical workflow is: commit the intended change, push it to `main`, run `./deploy_to_server.sh`, then inspect the live runtime with `./server_logs.sh`.

## Apply Completion Gate Before Ending
Provide evidence for all items:
1. Stage endpoints validate contracts.
2. Conversation endpoint E2E passes (multi-turn + transcript checks).
3. Dockerized E2E passes.
4. DB rows confirm end-state consistency.

## Persist Improvements Immediately
When you discover a better process, update all of:
- `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-development-memory/SKILL.md`
- `/Users/fgoiriz/private/repos/konecta-auditor/HOW_TO_DEVELOP.md`
- relevant files under `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/`
- `/Users/fgoiriz/private/repos/konecta-auditor/AGENTS.md` when guardrails change

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep orchestration lean; do not add helper-heavy logic without a proven need.
- Prefer explicit typed contracts and clear `Program.aforward` boundaries.
- Delegate semantic extraction/inference to LLM signatures instead of manual regex/heuristics.
- Do not semantically reshape LLM inputs/outputs in Python when instructions can express the same rule.
- Keep deterministic logic for non-semantic normalization and protocol handling only.
- When contracts move, update pipeline, API, UI, tests, and docs in the same change.
- Only abstract into helpers when the logic is reusable or non-trivial; keep trivial orchestration inline for readability.
