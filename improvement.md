# Improvement Coordination Log

## 2026-05-03 19:03 - Codex API error UX lane

- Status: abandoned before commit.
- Improvement: make frontend API error messages readable when FastAPI/Pydantic
  returns structured validation details, avoiding `[object Object]` in CRM
  banners and modal failures.
- Planned files:
  - `src/frontend/src/api.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, backend runtime/API files, bot worker files,
  funnel runtime config, sheet ingestion helpers, Docker/deploy scripts, or
  persisted `data/`.
- Final note: abandoned because other models concurrently reserved
  `src/frontend/src/api.ts`. I removed my local formatter change and moved to
  the auth lane below.

## 2026-05-03 19:08 - Codex auth logout lane

- Status: local validation passed; preparing commit, push, deploy, and server
  verification.
- Improvement: make logout revoke the current signed session token server-side
  for the rest of its lifetime, instead of relying only on deleting the browser
  cookie.
- Planned files:
  - `src/backend/auth.py`
  - `src/backend/tests/test_auth.py`
  - `improvement.md`
- Guardrail: no edits to frontend files, Contadores lead APIs, runtime
  readiness files, bot worker files, public image generation, funnel config,
  sheet ingestion helpers, Docker/deploy scripts, or persisted `data/`.
- During: implemented in-memory session-token revocation in
  `src/backend/auth.py` and added focused tests in
  `src/backend/tests/test_auth.py`.
- During: added a random signed session id so consecutive logins do not reuse
  the same token when created within the same second.
- Validation: `uv run pytest src/backend/tests/test_auth.py` passed with 2
  tests. `npm run build` in `src/frontend` passed.

## 2026-05-03 18:59 - Codex

- Status: in progress.
- Improvement: add a one-click "copy lead context" action in the CRM detail header so operators can quickly share or reuse the selected lead's phone, email, funnel, status, tags, WhatsApp window, last activity, and latest delivery error.
- Planned files:
  - `src/frontend/src/App.tsx`
  - `src/frontend/src/styles.css`
  - `improvement.md`
- Guardrail: no backend contracts, automation behavior, funnel runtime, sheet ingestion, or deploy scripts.

### 2026-05-03 19:03 - During

- Added the CRM detail header action and clipboard text builder in `src/frontend/src/App.tsx`.
- Added responsive copy-status styling in `src/frontend/src/styles.css`.
- Next: run frontend build, inspect diff, then commit/push/deploy if clean.

## 2026-05-03 18:59 - Codex runtime readiness

- Status: in progress.
- Improvement: make `/api/runtime` and `/health` report not-ready when `CONTADORES_SHEET_GID` is missing, matching the documented required lead source config.
- Planned files:
  - `src/backend/runtime_settings.py`
  - `src/backend/tests/test_contadores.py`
  - `README.md`
  - `.env.example`
  - `.codex/skills/contadores-spreadsheet/SKILL.md`
  - `.codex/skills/contadores-spreadsheet/references/spreadsheet.md`
  - `.codex/skills/contadores-rollout/SKILL.md`
  - `.codex/skills/contadores-rollout/references/rollout.md`
  - `improvement.md`
- Guardrail: no frontend CRM edits, no funnel JSON behavior changes, no WhatsApp automation changes, no deploy script changes.
- During: implemented the runtime GID readiness check, updated the focused runtime tests, and documented the requirement in README, `.env.example`, and the local rollout/spreadsheet skills.
- Validation: `uv run pytest src/backend/tests/test_contadores.py -k runtime` passed with 2 tests.

## 2026-05-03 18:59 - Codex backend/API lane

- Status: validation passed locally.
- Improvement: extend the existing CRM lead search so it also matches stored
  WhatsApp/message text, letting operators find a lead by phrases from the chat.
- Planned files:
  - `src/backend/endpoints/contadores.py`
  - `src/backend/tests/test_contadores.py`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, bot flows, funnel runtime config, sheet
  ingestion, Docker/deploy scripts, or persisted `data/`.
- During: added a readable backend helper that searches lead fields first and
  then the stored chat timeline for the existing lead-list `query` parameter.
- Validation: `uv run pytest src/backend/tests/test_contadores.py::test_contadores_lead_search_matches_message_text`
  passed, and `uv run pytest src/backend/tests/test_contadores.py
  src/backend/tests/test_funnels.py src/backend/tests/test_codex_utils.py
  src/backend/tests/test_contadores_post_loom_classifier.py` passed with 85
  tests.
- Note: full `uv run pytest src/backend/tests` currently has unrelated failures
  in the concurrently edited `test_public_image_generation.py` lane.

## 2026-05-03 19:03 - Codex API client lane

- Status: abandoned before commit because parallel API client lanes claimed the
  same `src/frontend/src/api.ts` file.
- Improvement: make the frontend HTTP client handle empty successful responses
  and rate-limit retry hints cleanly, so operator actions fail less noisily
  during transient backend pressure.
- Planned files:
  - `src/frontend/src/api.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, backend contracts, bot flows, funnel runtime
  config, sheet ingestion, Docker/deploy scripts, or persisted `data/`.
- Progress: implemented the retry/empty-response handling in
  `src/frontend/src/api.ts`; next step is validation and then final status.
- During: frontend copy-context work is still reserved above; this backend/API
  change stays in the lead-list query path and adds regression coverage.

## 2026-05-03 19:10 - Codex auth logout lane

- Status: in progress.
- Improvement: make logout revoke the current signed session server-side, so a
  copied/stale `contadores_session` token cannot keep using the CRM until its
  normal expiry.
- Planned files:
  - `src/backend/auth.py`
  - `src/backend/tests/test_auth.py`
  - `improvement.md`
- Guardrail: no edits to frontend files, Contadores runtime/API files, bot
  files, funnel config, sheet ingestion helpers, Docker/deploy scripts, media,
  or persisted `data/`.

## 2026-05-03 19:01 - Codex bot worker lane

- Status: local validation passed; preparing commit, push, deploy, and server
  verification.
- Improvement: make the bot worker dispatch path more resilient by keeping
  pending WhatsApp delivery dispatch independent from the active funnel list and
  by reusing one `/api/funnels` read per loop cycle.
- Planned files:
  - `src/bot/main.py`
  - focused bot tests under `src/bot/tests/`
  - `improvement.md`
- Guardrail: no edits to the frontend files claimed above, backend/API lane
  files, funnel runtime config, sheet ingestion helpers, deploy scripts, or
  persisted `data/`.
- During: updated `src/bot/main.py` so the worker loop fetches funnels once per
  cycle and `run_worker_iteration` still dispatches pending messages when the
  provided funnel list is empty. Added `src/bot/tests/test_worker_loop.py` to
  lock this behavior.
- Validation: `uv run --project src/bot --with pytest pytest src/bot/tests`
  passed with 49 tests. Focused rerun of `test_worker_loop.py` and
  `test_contadores_flow.py` passed with 12 tests.

## 2026-05-03 19:04 - Codex frontend format lane

- Status: abandoned before code.
- Improvement: make high-volume CRM timestamps cheaper and steadier to render by
  reusing formatter instances and normalizing near-now future clock skew to
  "now" instead of confusing operators with tiny "in N seconds" labels.
- Planned files:
  - `src/frontend/src/format.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, backend/API files, bot worker files, funnel
  runtime config, sheet ingestion helpers, deploy scripts, or persisted `data/`.
- During: stopped before editing because `src/frontend/src/format.ts` already
  had uncommitted changes from another worker.

## 2026-05-03 19:06 - Codex frontend API client lane

- Status: abandoned before code.
- Improvement: make the frontend API client more resilient for operators by
  retrying rate-limit responses with `Retry-After`, accepting empty successful
  responses, and surfacing plain-text/non-JSON error bodies cleanly instead of
  failing with a parser error.
- Planned files:
  - `src/frontend/src/api.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, `src/frontend/src/format.ts`, backend/API
  endpoint files, bot worker files, funnel runtime config, sheet ingestion
  helpers, deploy scripts, or persisted `data/`.
- During: stopped before editing because `src/frontend/src/api.ts` already had
  uncommitted changes from another worker.

## 2026-05-03 19:09 - Codex browser shell lane

- Status: local validation passed; preparing commit, push, deploy, and server
  verification.
- Improvement: improve the app's browser shell metadata so mobile and desktop
  browsers get the correct CRM name, description, color scheme, and theme color
  before the React app loads.
- Planned files:
  - `src/frontend/index.html`
  - `improvement.md`
- Guardrail: no edits to dirty frontend source files, backend/API files, bot
  worker files, docs/rollout changes, funnel runtime config, sheet ingestion
  helpers, deploy scripts, or persisted `data/`.
- During: added `application-name`, `description`, `theme-color`, and
  `color-scheme` metadata in `src/frontend/index.html`.
- Validation: `npm run build` passed in `src/frontend`.

## 2026-05-03 19:00 - Codex date clarity lane

- Status: in progress.
- Improvement: make compact frontend dates include the year when the timestamp is outside the current year, so older chats, runner entries, and delivery history are not ambiguous.
- Planned files:
  - `src/frontend/src/format.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`, `src/frontend/src/styles.css`, `src/frontend/src/api.ts`, backend files, bot files, funnel runtime config, sheet ingestion helpers, deploy scripts, media, or persisted `data/`.
- During: `shortDate` now keeps the compact month/day/time format for current-year timestamps and adds the numeric year only for older or future-year timestamps; next step is frontend build verification.

## 2026-05-03 19:02 - Codex public image generation validation

- Status: in progress.
- Improvement: make `/api/public/image-generation` reject or fall back from
  empty/non-PNG generated output instead of returning a broken file as
  `image/png`.
- Planned files:
  - `src/backend/endpoints/public_image_generation.py`
  - `src/backend/tests/test_public_image_generation.py`
  - `improvement.md`
- Guardrail: no edits to the frontend files, runtime readiness files,
  Contadores lead search files, bot worker files, deploy scripts, funnel source
  config, or persisted `data/`.
- During: starting with focused endpoint/tests only.

## 2026-05-03 19:02 - Codex frontend API resilience lane

- Status: validation passed locally.
- Improvement: add a client-side request timeout to the shared frontend API
  helper so a stalled backend request fails with a clear operator-facing error
  instead of leaving the CRM loading forever.
- Planned files:
  - `src/frontend/src/api.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, backend endpoints, bot flows, runtime settings,
  Docker/deploy scripts, or persisted `data/`.
- During: switched away from the backend search idea because it is already
  reserved by the backend/API lane above.
- During: found concurrent `api.ts` improvements for `429 Retry-After` and
  empty responses; kept those changes and added per-attempt request timeout on
  top of the current file.
- Validation: `npm run build` in `src/frontend` passed.
- Final: this lane is ready to commit; only the timeout portion of `api.ts`
  should be considered owned by this lane because other API-client changes were
  already present concurrently.

## 2026-05-03 19:06 - Codex frontend label polish lane

- Status: in progress.
- Improvement: make raw CRM labels easier for operators to scan by expanding
  common pause reasons, WhatsApp sequence steps, platforms, and tags in the
  shared formatter.
- Planned files:
  - `src/frontend/src/format.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, `src/frontend/src/api.ts`, backend endpoints,
  bot worker files, runtime settings, deploy scripts, or persisted `data/`.
- During: using only the shared label helper so the already-claimed frontend
  component/API lanes stay untouched.
- During: updated `src/frontend/src/format.ts` with explicit labels for common
  CRM pause reasons, WhatsApp sequence steps, platforms, and tags.
- Validation: `npm run build` passed in `src/frontend`.
- Status: local validation passed; preparing commit, push, deploy, and server
  verification.

## 2026-05-03 19:05 - Codex timestamp readability lane

- Status: abandoned before code edits because `src/frontend/src/format.ts` was
  already reserved by the date clarity/format lanes above.
- Improvement: make the shared frontend timestamp formatter clearer for
  operators by showing a year for dates outside the current year and keeping
  current-year timestamps compact.
- Planned files:
  - `src/frontend/src/format.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, `src/frontend/src/api.ts`, backend endpoints,
  runtime settings, bot flows, funnel config, deploy scripts, or persisted
  `data/`.
- During: choosing a formatter-only change because UI, backend, API client, and
  bot worker lanes are already reserved by parallel agents.

## 2026-05-03 19:07 - Codex public image generation validation update

- Status: validation passed locally.
- Files touched for this lane:
  - `src/backend/endpoints/public_image_generation.py`
  - `src/backend/tests/test_public_image_generation.py`
  - `improvement.md`
- During: added PNG signature validation after Codex output and after OpenAI
  Images fallback output. If Codex writes a non-PNG, the endpoint falls back; if
  fallback writes a non-PNG, the endpoint returns `502` instead of serving a
  broken image.
- Validation: `uv run pytest src/backend/tests/test_public_image_generation.py`
  passed with 7 tests.
- Next: staging only the public image generation validation files and this
  coordination log, then committing/pushing from `main` before server deploy.

## 2026-05-03 19:07 - Codex root error boundary lane

- Status: in progress.
- Improvement: add a root React error boundary so an unexpected CRM render
  failure shows a clear reloadable fallback instead of a blank app shell.
- Planned files:
  - `src/frontend/src/main.tsx`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`,
  `src/frontend/src/styles.css`, `src/frontend/src/api.ts`,
  `src/frontend/src/format.ts`, backend files, bot files, funnel config,
  deploy scripts, media, or persisted `data/`.
- During: implementing this in the React entrypoint only, then validating with
  the frontend build.
- During: added `RootErrorBoundary` in `src/frontend/src/main.tsx` with a
  reloadable fallback for unexpected render crashes.
- During: `npm run build` passed in `src/frontend`.

## 2026-05-03 19:00 - Codex date clarity lane stop

- Status: stopped before commit.
- Note: dropped the `src/frontend/src/format.ts` date clarity lane because parallel format/timestamp lanes claimed the same file and a near-identical improvement.

## 2026-05-03 19:00 - Codex Workstation transcript lane

- Status: in progress.
- Improvement: make Workstation copy-all transcripts preserve useful media context when a WhatsApp/media message has no text body, so Codex/client handoff exports do not show blank conversation lines.
- Planned files:
  - `src/backend/endpoints/workstation.py`
  - `src/backend/tests/test_workstation.py`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`, `src/frontend/src/styles.css`, `src/frontend/src/api.ts`, `src/frontend/src/format.ts`, Contadores runtime/search files, bot worker files, public image generation files, deploy scripts, media, or persisted `data/`.
- During: added transcript media fallback logic and focused tests for media-only Workstation messages; next step is running that test file.
