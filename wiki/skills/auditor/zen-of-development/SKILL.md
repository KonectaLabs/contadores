---
name: zen-of-development
description: General engineering doctrine for LLM-first product systems. Use when implementing, refactoring, reviewing, or documenting code to keep architecture contract-driven, code minimal, and semantics delegated to typed program signatures.
---

# Zen Of Development

## Prime Directives
1. Keep code small enough to fit in one head.
2. Define typed contracts before implementation.
3. Treat each stage or subsystem as an explicit boundary.
4. Implement boundary logic as `Program` + `aforward` whenever AI extraction is involved.
5. Delegate semantic inference to LLM signatures with structured outputs.
6. Keep deterministic code for non-semantic sanitation only.
7. Remove dead fields, dead arguments, and no-op knobs quickly.
8. Keep stage, pipeline, API, UI, validation harnesses, and docs synchronized.
9. Trust internal operators; add only necessary validation.
10. Prefer deletion over complexity accumulation.
11. **Less is better**: Fewer lines of code, fewer files, fewer folders. Consolidate when possible.
12. **Lego-like composition**: Main functions (`aforward`, endpoints, orchestrators) must compose core functions, not implement logic. They should read like a recipe: gather inputs, call methods, combine results, return output.
13. **Readable recipe over trivial wrappers**: keep simple orchestration steps visible in the main function (task lists, gathers, loops, direct combinations). Do not hide obvious one-liners behind `build_*`/`compose_*` wrappers unless the abstraction is reused or non-trivial.

## Architecture Rules
- Keep responsibilities narrow: orchestration in orchestrators, extraction in extractors, persistence in persistence layers.
- Never hide cross-stage dependencies; pass previous outputs explicitly.
- Avoid helper-function forests that encode fragile heuristics.
- Let infrastructure adapt to stable contracts, not the inverse.

## Code Organization Rules
- **Model Placement**: Models (Pydantic BaseModel classes) used only by a single endpoint must be defined immediately above that endpoint. Models used by multiple endpoints or imported by other modules should remain at the top of the file after imports and router definitions.
- Keep helper functions that are used by multiple endpoints near the top, after shared models.
- Group related models together when they're used by the same endpoint (e.g., Request and Response models for the same endpoint).
- **Simplicity First**: Prefer fewer files and folders. Consolidate related functionality when it doesn't violate separation of concerns. Avoid creating new files/folders unless there's a clear architectural boundary.
- **Lego-like Main Functions**: Main functions (`aforward`, endpoint handlers, orchestrators) must be abstracted and legolike. They should compose other core functions/methods, not implement logic directly. The main function should read like a recipe: gather inputs, call methods, combine results, return output. All implementation logic belongs in the composed methods, not in the main function.
- **No obfuscating helpers**: if a helper only renames a trivial operation and is used once, inline it in the main recipe. Reserve helpers for reusable logic or genuinely complex operations (regex, parsing, provider API calls, normalization rules, retries, etc.).

  **Example (good):**
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
  This `aforward` method composes `process_search()`, `get_html_relevant_parts()`, and `extract_contacts()` - all implementation logic lives in those methods, not here.

  **Example (bad):**
  ```python
  async def aforward(self, url: str) -> ContactDiscoveryResult:
      """Bad: implementing logic directly instead of composing methods."""
      # Bad: search logic inline
      prompt = CONTACT_DISCOVERY_PROMPT.format(url=url)
      response = await pro_search(prompt)
      output_text = response.output_text
      
      # Bad: HTML fetching and regex parsing inline
      html_snippets = ""
      with suppress(Exception):
          async with httpx.AsyncClient(timeout=8.0) as client:
              html_response = await client.get(url, follow_redirects=True)
              html = unescape(html_response.text)
              patterns = [
                  r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
                  r'mailto:[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
                  r'wa\.me/[+\d\w-]+',
                  # ... more regex patterns ...
              ]
              snippets = {
                  html[max(0, m.start() - 100):min(len(html), m.end() + 100)].strip()
                  for pattern in patterns
                  for m in re.finditer(pattern, html, re.IGNORECASE)
              }
              html_snippets = '\n\n'.join(filter(None, snippets))
      
      # Bad: extraction logic inline
      content = output_text + f"\n\n## Raw HTML Contact Evidence:\n{html_snippets}"
      result = (await self.extractor.acall(pro_search_output=content)).result
      return result
  ```
  This violates the lego-like principle: `aforward` contains implementation details (regex patterns, HTTP client setup, HTML parsing) that should be in composed methods.

## Extraction Rules
- For semantic fields, use typed DSPy signatures and Pydantic outputs.
- Avoid regex/manual parsing/keyword maps for meaning extraction.
- If deterministic post-processing is needed, keep it short and auditable.
- Do not re-parse what a typed output can represent directly.

## Drift Prevention
When a contract changes, update all affected surfaces in the same task:
1. stage program and models
2. pipeline/endpoint wiring
3. API request/response contracts
4. frontend payload/form expectations
5. validation harnesses
6. development docs and skills

## Complexity Smells
Refactor when you see these signals:
- many `normalize_*`/`resolve_*`/`dedupe_*` helpers compensating weak extraction
- transport machinery embedded inside semantic stages
- parameters kept in public contracts but ignored in runtime
- docs claiming behavior the code no longer performs
- `build_*`/`compose_*` helpers used once that hide straightforward step-by-step flow

## Preferred Validation
- Stage-level contract validation first.
- Endpoint E2E for integration truth.
- Docker and persistence checks for production-like confidence.
- Validation must be runnable; non-running checks are not evidence.
