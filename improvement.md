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

- Status: deployed.
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
- Final: committed as `eeaba32` (`Revoke auth sessions on logout`), pushed to
  `main`, included in the deployed server history, and verified after deploy.
  Production checks passed: `/health` ready, authenticated `/api/runtime`
  ready, authenticated `/api/funnels` returned `contadores`, `abogados`, and
  `general`, and a production auth smoke returned 200 before logout and 401
  for the same session after logout.

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

### 2026-05-03 19:05 - Final

- Status: deployed and verified on the real server.
- Validation:
  - `npm run build` passed in `src/frontend`.
  - Local backend render check passed with `AUTH_DISABLE=true`; the CRM detail header shows `Copy context` for a selected lead.
  - Production deploy completed after commit `dc0174d`.
  - Production `/health` returned `ready=true`.
  - Authenticated production `/api/runtime` returned `ready=true` with no readiness issues.
  - Production `/api/funnels` returned `contadores`, `abogados`, and `general`.
  - Production frontend bundle contains the `Copy context` action.
- Notes: local backend without `AUTH_DISABLE=true` still requires `auth.toml`; this is existing local auth behavior.

## 2026-05-03 18:59 - Codex runtime readiness

- Status: deployed and verified on the real server.
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

### 2026-05-03 19:18 - Final

- Pushed code commit `83ef16b` to `main`; the deployed server later advanced to `dc0174d`, which includes this commit.
- Deployed with `bash deploy_to_server.sh`; backend and bot containers came up healthy.
- Verified on the real backend: `/health` returned `ready=true`, `/api/runtime` returned `ready=true`, `sheet_configured=true`, `sheet_gid="0"`, and no readiness issues, and `/api/funnels` returned `contadores`, `abogados`, and `general`.

## 2026-05-03 18:59 - Codex backend/API lane

- Status: deployed and verified on the real server.
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
- Validation: in the clean `origin/main` worktree,
  `uv run --with pytest pytest src/backend/tests/test_contadores.py::test_contadores_lead_search_matches_message_text`
  passed, and `uv run --with pytest pytest src/backend/tests` passed with 98
  tests.
- Final: pushed code commit `146dc43` to `main`; the deployed server later
  advanced to `dc0174d` and then newer verification commits, all containing
  `146dc43`.
- Production verification: authenticated `/api/runtime` returned `ready=true`,
  `sheet_configured=true`, `sheet_gid="0"`, and no readiness issues;
  authenticated `/api/funnels` returned `contadores`, `abogados`, and
  `general`; a read-only authenticated lead search using a phrase from an
  inbound WhatsApp message, absent from lead fields, returned the expected lead
  with HTTP 200.

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

- Status: abandoned before code because another auth logout lane already owns
  `src/backend/auth.py` and `src/backend/tests/test_auth.py`.
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

## 2026-05-03 19:15 - Codex API cache safety lane

- Status: deployed and verified on the server.
- Improvement: add `Cache-Control: no-store` to backend `/api/*` responses so
  browser/proxy cache does not reuse stale or sensitive CRM API payloads.
- Planned files:
  - `src/backend/main.py`
  - `src/backend/tests/test_system_cache_headers.py`
  - `improvement.md`
- Guardrail: no edits to dirty frontend files, auth/session files, Contadores
  lead/runtime files, bot files, public image generation files, Workstation
  transcript files, funnel config, sheet ingestion helpers, Docker/deploy
  scripts, media, or persisted `data/`.
- During: added a small backend middleware in `src/backend/main.py` that sets
  `Cache-Control: no-store` only on `/api/*` responses.
- Validation: `uv run pytest src/backend/tests/test_system_cache_headers.py`
  passed with 2 tests.
- Final: committed and pushed as `e6f8343` (`Prevent API response caching`).
  Deployed on the real server; the server is now on newer `main` commit
  `4708d1e`, which includes this commit. Verified `/api/runtime` returned
  `ready=true` with `Cache-Control: no-store`, `/api/funnels` returned 3
  funnels with `Cache-Control: no-store`, and Traefik `/health` returned 200.

## 2026-05-03 19:01 - Codex bot worker lane

- Status: deployed and verified on the real server.
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

### 2026-05-03 19:21 - Final

- Pushed bot worker commit `3ed50c8` to `main`; the deployed server HEAD
  includes that commit.
- Deployed through the repo rollout path. A concurrent deploy left the bot
  stopped during verification, so I restarted the bot with
  `docker compose up -d --no-deps bot` after backend health was green.
- Verified on the real server: `/health` returned `ready=true`, authenticated
  `/api/runtime` returned `ready=True` and `enabled=True`, authenticated
  `/api/funnels` returned 3 funnels, backend was healthy, bot was running, and
  bot logs showed startup plus Contadores/Abogados sheet sync without errors.

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

- Status: deployed and verified on the server.
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
- Final: committed as `75f9013` (`Improve CRM browser shell metadata`), pushed
  to `main`, deployed on the real server, and verified from the backend
  container. Production checks passed: `/health` ready, authenticated
  `/api/runtime` ready with no readiness issues, authenticated `/api/funnels`
  returned 3 funnels, and the served authenticated HTML contains all four new
  metadata tags.

## 2026-05-03 19:00 - Codex date clarity lane

- Status: in progress.
- Improvement: make compact frontend dates include the year when the timestamp is outside the current year, so older chats, runner entries, and delivery history are not ambiguous.
- Planned files:
  - `src/frontend/src/format.ts`
  - `improvement.md`
- Guardrail: no edits to `src/frontend/src/App.tsx`, `src/frontend/src/styles.css`, `src/frontend/src/api.ts`, backend files, bot files, funnel runtime config, sheet ingestion helpers, deploy scripts, media, or persisted `data/`.
- During: `shortDate` now keeps the compact month/day/time format for current-year timestamps and adds the numeric year only for older or future-year timestamps; next step is frontend build verification.

## 2026-05-03 19:02 - Codex public image generation validation

- Status: deployed and verified on the server; see the 19:07 update below.
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

- Status: deployed and verified on the real server.
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
- Final: committed as `1df7cc5` (`Improve frontend API request resilience`),
  pushed to `main`, included in the deployed server history, and verified after
  deploy. Production checks passed: `/health` ready, authenticated
  `/api/runtime` ready with no readiness issues, and authenticated
  `/api/funnels` returned the configured funnels.

## 2026-05-03 19:06 - Codex frontend label polish lane

- Status: deployed.
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
- Final: committed as `b83ed78` (`Improve CRM label readability`), pushed to
  `main`, included in the deployed server history, and verified after deploy.
  Production checks passed: `/health` ready, `/api/runtime` ready with no
  readiness issues, and `/api/funnels` returned `contadores`, `abogados`, and
  `general`.

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

- Status: deployed and verified on the server.
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
- Final: committed as `a92cb6c` (`Validate public image generation output`),
  pushed to `main`, included in deployed server history, and verified after
  deploy. Production checks passed: `/health` returned `ready=true`,
  authenticated `/api/runtime` returned `ready=True` with no issues, and
  authenticated `/api/funnels` returned 3 funnels.

## 2026-05-03 19:07 - Codex root error boundary lane

- Status: deployed and verified on the server.
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
- Final: committed as `74c1a74` (`Add CRM root error boundary`), pushed to
  `main`, included in deployed server history, and verified after deploy.
  Production checks passed through Traefik: authenticated `/api/runtime`
  returned `ready=true`, authenticated `/api/funnels` returned 200, `/`
  redirects to `/login`, and the deployed frontend bundle contains
  `CRM could not load`.

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
- Validation: `uv run pytest src/backend/tests/test_workstation.py` passed with 2 tests; `uv run pytest src/backend/tests/test_contadores.py -k workstation` passed with 5 tests.
- Status: deployed and verified on the server.
- Final: committed as `7fa7b26` (`Improve Workstation media transcripts`), pushed to `main`, included in deployed server history, and verified after deploy. Production checks passed: authenticated `/api/runtime` returned `ready=true`, authenticated `/api/funnels` returned `contadores`, `abogados`, and `general`, and both backend and bot containers are running.
