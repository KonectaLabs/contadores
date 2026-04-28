---
name: konecta-auditor-development-memory
description: Canonical persistent memory log for Konecta Auditor. Use as the single repository history of architectural decisions, stable patterns, and validation rules.
---

# Development Memory

## 2026-04-23

### Contadores Uses One Lead Source And Manual Filter Is Needs Answer/Answered (2026-04-24)
- Decision/rule:
  - Contadores no longer has alternate source modes in UI, API payloads, bot sync, or SQLite schema.
  - remove synthetic lead seed/reset controls and source-mode config fields.
  - manual triage uses only `manual_reply_status`:
    - `needs_reply` for leads where the latest lead inbound still needs an operator answer.
    - `answered` for leads already handled by outbound reply or `Mark answered`.
  - the manual reply filter belongs only to the Manual stage and should stay visually minimal.
- Reason:
  - one operational source avoids noise and reduces the risk of hiding real leads.
  - the only needed manual distinction is whether the operator needs to answer or the lead is already handled.
- Enforcement:
  - Contadores persistence:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`
  - Contadores API contract and `manual_reply_status` list filter:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - bot sheet sync always imports configured sheet rows:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
  - operator UI filter strip and cache-bust:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run --with pytest pytest tests/test_contadores_flow.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run python -m py_compile backend/database.py backend/endpoints/contadores.py bot/utils.py`

### Contadores Stage Metrics Ignore Stage Filter And Strategy Filters Compose With Stages (2026-04-23)
- Decision/rule:
  - Contadores pipeline counts must not be recalculated from the currently selected stage bucket.
  - `/api/contadores/leads` now applies search/source/platform/strategy filters first, computes pipeline metrics from that set, then applies the selected stage only to the visible lead list.
  - strategy filters use persisted `contadores_strategy_assignments`, so operators can select `Calendly sent` and then filter by the prior WhatsApp MP4 strategy.
  - lead summaries expose `strategy_assignments` for lightweight list tags and future operator UI filters without re-reading message timelines.
- Reason:
  - stage counts are navigation totals, not nested counts within the active bucket.
  - operators need to ask questions like "Calendly leads that came from the WhatsApp MP4 Loom strategy" without losing the broader stage context.
- Enforcement:
  - backend strategy filtering and independent metric/list separation:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - regression coverage:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_contadores.py`
  - operator strategy filter strip and lead strategy tags:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run python -m py_compile backend/database.py backend/endpoints/contadores.py backend/contadores_strategies/__init__.py`
  - local browser QA at `http://127.0.0.1:8023/?section=contadores`: strategy buttons render, desktop/mobile scroll width equals viewport.
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
  - reused pattern:
    - reused the simple URL-query-driven list filtering shape from Outbound, adapted by keeping Contadores metric aggregation explicitly separate from the active stage filter.

### Contadores Operator UI Is Flatter, Full-Width, And Mobile-Safe (2026-04-23)
- Decision/rule:
  - the Contadores standalone page should read as a dense operator console, not a decorative dashboard.
  - use a neutral/teal scoped palette, minimal shadows, small radii, and a single compact pipeline strip with inline counts.
  - preserve all existing DOM IDs and JS hooks when reshaping the interface.
  - mobile layouts must keep `documentElement.scrollWidth` equal to `window.innerWidth`; stack detail actions instead of letting buttons widen the page.
- Reason:
  - operators need fast scanning of stage counts, lead list, and the selected conversation without visual noise.
  - the prior card-heavy/purple treatment created unnecessary emphasis and mobile overflow risk.
- Enforcement:
  - Contadores cache-bust:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
  - scoped Contadores styling:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
  - shared Contadores filter refresh helper:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
  - local browser QA at `http://127.0.0.1:8023/?section=contadores`
  - desktop viewport `1440x1000`: `documentElement.scrollWidth === 1440`, browser console errors `0`
  - mobile viewport `390x900`: `documentElement.scrollWidth === 390`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/outbound/frontend/index.html`
  - reused pattern:
    - reused the lean single-page operator-shell idea from Outbound, adapted into the existing Contadores DOM by reducing visual containers instead of adding new components or hooks.

### Contadores Sequence Strategies Are Code-Weighted And Persist Assignments (2026-04-23)
- Decision/rule:
  - Contadores sequence steps now support code-defined strategies under `backend/contadores_strategies/`.
  - v1 now keeps the `loom` step on `loom_mp4`: local WhatsApp MP4 from `data/contadores/videos/loom_60_seconds_captions.mp4`.
  - current rollout is `loom_mp4` at 100%; the Loom-link strategy was removed from active config.
  - weights are code-only for now; operators can see stats but cannot edit rollout percentages in the UI.
  - every strategy choice is persisted in `contadores_strategy_assignments` and copied onto outbound messages for auditability.
  - strategy conversion stats count assignment, sent/delivered, reached Calendly, and booked milestones without rewriting old assignments when weights change.
- Reason:
  - the user wants one-shot experimentation between Loom-link and direct-MP4 delivery, plus a reusable structure for future sequence strategy additions.
  - persisting assignment before dispatch keeps conversion analysis stable even if messages are edited or weights later change.
- Enforcement:
  - strategy classes and weights:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/contadores_strategies/__init__.py`
  - assignment/message persistence and SQLite backfill:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`
  - backend strategy selection, pending media payload, and stats endpoint:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - bot media dispatch:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/providers.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
  - operator UI:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
  - future-agent skill:
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-contadores-strategies/SKILL.md`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run --with pytest pytest tests/test_contadores_flow.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run python -m py_compile backend/database.py backend/endpoints/contadores.py backend/contadores_strategies/__init__.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    - `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern:
    - reused Inmobot's simple persisted message direction/type shape and thin WhatsApp media wrapper, adapted by keeping strategy selection in backend orchestration and media provider calls in the stateless bot.

### Contadores Manual Reply Cues Are Needs Reply Or Answered, With Operator Clear (2026-04-23)
- Decision/rule:
  - manual Contadores leads must use unambiguous operator labels:
    - `Needs reply` when the lead has an inbound newer than both the latest outbound and the latest operator clear.
    - `Answered` when the operator/bot already replied, or when an operator marked the latest inbound as handled.
  - do not use ambiguous `Waiting` copy for this cue.
  - store operator clears in `contadores_leads.manual_reply_handled_at` so lightweight inbound reactions can be marked handled without sending another WhatsApp message.
  - a later inbound message must make the lead `Needs reply` again.
  - pending human-alert payloads must skip manual leads whose current cue is `Answered`.
- Reason:
  - WhatsApp reactions can be delivered as inbound messages and should not force an unnecessary follow-up.
  - operators need to know only whether they need to answer now or whether the lead is already handled.
- Enforcement:
  - persisted manual clear field + SQLite backfill:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`
  - backend manual reply status and quick action:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - regression coverage:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_contadores.py`
  - operator UI labels, `Mark answered` action, and cache-bust:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run python -m py_compile backend/database.py backend/endpoints/contadores.py`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && AUTH_DISABLE=true uv run python -c "from backend.main import app; print('backend-import-ok')"`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    - `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern:
    - kept Inmobot's simple `from_me` message direction as the base mental model, but added one Contadores-specific persisted operator-clear timestamp because plain latest inbound/outbound timestamps cannot distinguish a WhatsApp reaction from a real unanswered message.

### Contadores Calendly Is Now A Milestone Bucket And Manual Leads Show Reply Ownership (2026-04-23)
- Decision/rule:
  - the Contadores `Calendly` bucket must count any active live lead with `calendly_sent_at`, even if that lead later comes back to `needs_human`.
  - `Manual` remains the current handoff queue, so a lead may appear in both `Calendly` and `Manual` views when Calendly was sent and the lead replied afterwards.
  - manual leads should expose a fast visual ownership cue in the operator list:
    - `Reply now` when the latest message was inbound from the lead,
    - `Waiting` when the latest message was outbound from the operator/bot.
- Reason:
  - operators read `Calendly sent` as a milestone, not as a mutually exclusive current-stage lane.
  - without a per-lead reply-ownership cue, the manual queue is slower to triage because the operator has to open each chat to see whose turn it is.
- Enforcement:
  - Calendly milestone bucket logic:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - regression coverage:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_contadores.py`
  - manual queue visual ownership cues + cache-bust:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run python -m py_compile backend/endpoints/contadores.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no sibling repo exposed a directly reusable mixed milestone-plus-queue pattern for this Contadores operator panel
  - reused pattern:
    - kept the house Konecta approach: thin backend helpers for persisted bucket semantics and lightweight frontend rendering derived from existing timestamps instead of adding new stored flags

### Rejected CEO Audit Recipients Must Be Deleted And Must Not Stall Other Bot Jobs (2026-04-23)
- Decision/rule:
  - when CEO audit delivery hits a non-retryable recipient error, the stored `companies.ceo_email` must be cleared instead of being retried forever.
  - treat these as non-retryable:
    - syntactically invalid recipient emails,
    - provider rejections that explicitly say the recipient is blocked or bounced.
  - after clearing the email, mark the company as `missing_ceo_email` so audit delivery stays paused until a new recipient is set.
  - periodic bot jobs must be isolated: a failure in audit-delivery must not stop Contadores sheet sync in the same worker loop.
- Reason:
  - one rejected CEO recipient (`geoff@hubindustrial.com`) kept crashing the production bot loop before Contadores sheet sync ran, so new spreadsheet leads stopped importing even though the bot container was up.
  - deleting obviously bad recipients is safer and clearer than retrying the same impossible email forever.
- Enforcement:
  - audit-delivery recipient cleanup + non-retryable detection:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
  - worker-loop task isolation:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/main.py`
  - audit-delivery log wording:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/logging_utils.py`
  - regressions:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/tests/test_crm_flow.py`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run --with pytest pytest tests/test_crm_flow.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run python -m py_compile main.py utils.py logging_utils.py tests/test_crm_flow.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no direct sibling worker loop or audit-delivery implementation matched this exact failure mode closely enough to reuse verbatim
  - reused pattern:
    - kept the house Konecta shape: thin periodic orchestration in the loop, explicit backend state mutation helpers, and small deterministic failure classifiers instead of adding a new scheduler layer

## 2026-04-22

### Contadores Leads Can Now Be Closed And Reopened Back To Their Prior Stage (2026-04-22)
- Decision/rule:
  - Contadores leads now support a dedicated reversible `closed` state that is distinct from `archived`.
  - closing a lead must remember the prior effective stage so reopening restores that exact lane (`awaiting_initial_reply`, `awaiting_video_reply`, `calendly_sent`, `booked`, or `needs_human`).
  - closed leads must appear in their own operator count/filter bucket and must stay out of the automation tick while closed.
  - closed leads must not auto-reopen because of ambiguous WhatsApp routing or post-Calendly inbound replies; reopening is operator-only.
- Reason:
  - operators need a clean way to mark uninterested leads as no longer pending without deleting their conversation history.
  - restoring the previous stage keeps the pipeline numerically honest while still allowing a deliberate reopen later.
- Enforcement:
  - persisted closed-state fields and SQLite backfill:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`
  - Contadores stage derivation, quick actions, and inbound safeguards:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - operator regression tests:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_contadores.py`
  - Contadores operator UI count/filter/button wiring:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run python -m py_compile backend/database.py backend/endpoints/contadores.py`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && AUTH_DISABLE=true uv run python -c "from backend.main import app; print('backend-import-ok')"`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no direct sibling implementation matched this Contadores-specific reversible close state closely enough to reuse verbatim
  - reused pattern:
    - kept the house Konecta shape: thin endpoint actions over one persisted flow-state helper, explicit timeline events, and no extra orchestration layer

### Manual Calendly Sends Must Clear The Human Handoff Until A New Reply Arrives (2026-04-22)
- Decision/rule:
  - when an operator sends the Contadores `Calendly sequence` manually, the lead must return to `calendly_sent` instead of staying in `needs_human`.
  - that manual Calendly send must also clear `automation_paused` so the lead no longer looks stuck in the manual bucket.
  - if the lead sends any new inbound WhatsApp message after Calendly was sent, the lead must move back to `needs_human` and pause again for human follow-up.
  - `resume-automation` should infer `calendly_sent` from the persisted Calendly timestamp even after that temporary handoff.
- Reason:
  - operators often answer a question manually and then intentionally send Calendly to put the lead back on track.
  - keeping the raw state stuck in `needs_human` caused false manual backlog and broke the operator view of which leads truly still required intervention.
- Enforcement:
  - Contadores lead stage derivation + quick actions:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - alert/handoff reset support:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`
  - operator regression tests:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_contadores.py`
  - operator send modal copy:
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && node --check frontend/static/js/app.js`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no direct sibling implementation matched this Contadores-specific state transition closely enough to reuse verbatim
  - reused pattern:
    - kept the existing Konecta thin-endpoint pattern: update one persisted flow-state helper, emit timeline events at the endpoint boundary, and avoid introducing a new orchestration layer

### Repeatable Deploys Now Have A Dedicated Checklist Skill (2026-04-22)
- Decision/rule:
  - normal Konecta Auditor production releases should use the dedicated repeatable deploy skill:
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-repeatable-deploy/SKILL.md`
  - the deploy loop is now explicitly:
    - inspect local delta,
    - exclude `.cursor/hooks/state/*`,
    - run cheap sanity checks,
    - commit only intended files,
    - push `main`,
    - run `bash ./deploy_to_server.sh`,
    - verify server HEAD, `docker compose ps -a`, and backend `/health`.
  - if the SSH stream is interrupted and `bot` is left exited, rerun the canonical deploy instead of doing manual remote repair.
- Reason:
  - this repo now repeats the same VPS deploy workflow often enough that the steps should be codified as a checklist skill instead of relying on memory.
  - the repeated failure mode is not usually the code change itself; it is interrupted deploy verification or accidentally including local `.cursor` state files in commit scope.
- Enforcement:
  - skill path:
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-repeatable-deploy/SKILL.md`
  - guardrail reference:
    - `/Users/fgoiriz/private/repos/konecta-auditor/AGENTS.md`
- Validation:
  - check the skill file exists and is readable.
  - use it for the next production deploy request and verify:
    - server HEAD matches pushed commit,
    - backend is healthy,
    - bot is up.

### Contadores WhatsApp Video Sends Must Use Repo-Stored MP4 Assets Visible To The Bot (2026-04-22)
- Decision/rule:
  - Contadores may send a local MP4 asset instead of a Loom URL.
  - The configured asset path should live under `/Users/fgoiriz/private/repos/konecta-auditor/data/contadores/videos/`.
  - The bot service must mount `./data:/app/data` so WhatsApp media sends can read the same asset path in Docker.
  - Keep the backend transcript row as human-readable text and expose explicit media metadata in the pending delivery payload instead of storing provider-specific binary state in the DB.
  - If the source MP4 is too large for WhatsApp, create and configure a compressed `*_whatsapp.mp4` copy rather than changing the delivery code path.
- Reason:
  - The user wants Contadores to send an MP4 directly over WhatsApp, not a Loom link.
  - The original 83 MB source file was rejected by the provider with `(#100) Invalid parameter` and `Archivo demasiado grande`.
  - Mounting `/data` into the bot keeps the implementation thin and avoids adding a new internal file-serving endpoint just for local media dispatch.
- Enforcement:
  - config + pending-delivery payload:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/contadores.py`
  - bot media dispatch:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/providers.py`
  - Docker shared asset visibility:
    - `/Users/fgoiriz/private/repos/konecta-auditor/docker-compose.yml`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_contadores.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run --with pytest pytest tests/test_contadores_flow.py -q`
  - one-off real provider send accepted with a `wamid...` response after switching the config to `data/contadores/videos/loom_capcut_whatsapp.mp4`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern:
    - reused the same thin provider wrapper shape for `send_video`, keeping media transport logic in the WhatsApp provider instead of pushing file-send behavior into backend orchestration

### Automated Auditor Intake Is Now Disabled By Default In Deploy Config (2026-04-22)
- Decision/rule:
  - the production/default Docker Compose config must keep `AUTOMATED_AUDITOR_INTAKE_ENABLED=false`.
  - the bot runtime must not schedule the intake background task when that flag is off.
  - this applies to:
    - `/Users/fgoiriz/private/repos/konecta-auditor/docker-compose.yml`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/main.py`
- Reason:
  - the user explicitly wants the daily automated ingestion flow stopped, including on the VPS.
  - keeping the feature disabled in deploy config is the safest default, and skipping task creation makes the stopped state obvious in runtime behavior instead of relying on an immediately-returning background loop.
- Enforcement:
  - keep the compose flag set to `false` for the `bot` service.
  - gate intake task creation through a startup helper that returns `None` when the feature is disabled.
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest bot/tests/test_automated_auditor_intake.py -q`
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && docker compose config | rg "AUTOMATED_AUDITOR_INTAKE_ENABLED"`
  - deploy with `./deploy_to_server.sh`, then verify the live bot logs with `./server_logs.sh`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/main.py`
  - reused pattern:
    - kept the same simple lifespan-owned background task pattern, but made task startup explicitly optional so disabled automation is visible at startup and requires no extra orchestration layer

## 2026-04-13

### Generic Website Phone Numbers Must Not Auto-Become WhatsApp Contacts (2026-04-13)
- Decision/rule:
  - Stage 1 discovery may still output `phone`, but normal company scans must not persist generic `phone` contacts as conversation-automation channels.
  - Only explicit `whatsapp` contacts should be created for outbound WhatsApp automation.
  - Stage 1 prompt instructions must reserve `whatsapp` for explicit WhatsApp evidence such as `wa.me`, `api.whatsapp.com`, or a visible WhatsApp label/button.
  - `generate_first_message_for_contact` must stay compatible with the currently deployed `FirstMessageProgram` signature and must not pass `industry` until that program contract lands on `main`.
- Reason:
  - production was seeding WhatsApp outbounds to generic office phones, toll-free lines, and hotlines because discovery returned `phone` and persistence collapsed it into the WhatsApp channel.
  - the same production run also logged repeated `TypeError: FirstMessageProgram.aforward() got an unexpected keyword argument 'industry'`, which broke initial email draft generation.
- Enforcement:
  - skip generic `phone` contacts at persistence time in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`
  - clarify contact-type extraction rules in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage1_url_to_contacts.py`
  - lock the regression in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_company_scan_modes.py`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_company_scan_modes.py -q`
  - result at implementation time: `24 passed`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/outbound/backend/main.py`
  - reused pattern:
    - kept the thin outbound-style guardrail at the endpoint/persistence boundary so unsupported evidence is filtered before transport dispatch instead of patching provider runtime behavior

## 2026-04-10

### Automated Intake Research Now Uses Perplexity Pro Search Instead Of Deep Research (2026-04-10)
- Decision/rule:
  - the automated intake discovery program and the scan-time leadership-recipient research program must use Perplexity `pro_search`, not `deep_research`.
  - the automated intake daily quota default is now `5` companies per day.
  - this applies to:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/auditor_company_discovery.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/auditor_leadership_recipient.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/docker-compose.yml`
- Reason:
  - the production bot loop was healthy, but automated intake stalled because the discovery endpoint exhausted the Deep Research quota and returned repeated `500` responses from Perplexity `insufficient_quota`.
  - switching both research steps together avoids fixing discovery only to fail again during the normal scan gate.
- Enforcement:
  - import and call `pro_search` from `/Users/fgoiriz/private/repos/konecta-auditor/backend/deep_research.py` in both research programs.
  - keep the typed extraction and endpoint contracts unchanged; only the Perplexity preset changes.
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_auditor_research_programs.py backend/tests/test_company_scan_modes.py backend/tests/test_internal_bot_paths.py bot/tests/test_automated_auditor_intake.py -q`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/outbound/backend/deep_research.py`
  - reused pattern:
    - reused the existing shared Perplexity wrapper shape from `outbound` and kept the Konecta programs thin by swapping presets at the call site instead of adding new orchestration branches

## 2026-04-04

### AgentMail Conversation Email Now Reuses A Fixed Shared Inbox Pool (2026-04-05)
- Decision/rule:
  - conversation email delivery must reuse a fixed pool of existing AgentMail inboxes instead of creating one new inbox per contact.
  - the default shared pool is the three known inboxes:
    - `maximorodriguez@agentmail.to`
    - `rodrio@agentmail.to`
    - `jrazzler@agentmail.to`
  - the pool may be overridden with `AGENTMAIL_SHARED_INBOX_IDS`, but the runtime must still resolve only existing inboxes and must never create new contact inboxes.
  - within one company, the bot should assign inboxes as evenly as possible and avoid repeating an inbox until the pool is exhausted.
  - CRM replies may still use the explicitly configured CRM inbox, but if none is configured they should fall back to the first shared inbox instead of creating a new one.
  - inbound email polling fallback must accept AgentMail messages labeled `received` even when AgentMail already removed `unread`.
- Reason:
  - the AgentMail account has a hard inbox quota, and per-contact inbox creation caused outbound first-contact email to fail with `LimitExceededError: Inbox limit exceeded`.
  - the user wants a bounded reusable pool, not inbox proliferation.
  - keeping inbox reuse stable per contact and balanced per company preserves thread continuity while staying inside the provider quota.
- Enforcement:
  - shared inbox selection and webhook reuse:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/providers.py`
  - pending dispatch path that passes `company_id` into shared inbox selection:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
  - inbound metadata persistence fix for `email_inbox_address`:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`
  - focused regressions:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/tests/test_agentmail_provider.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_email_inbox_state.py`
- Validation:
  - bot focused regressions:
    - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run --with pytest python -m pytest tests/test_agentmail_provider.py tests/test_crm_flow.py tests/test_email_dispatch_spacing.py -q`
    - result at implementation time: `25 passed`
  - backend focused regression:
    - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest python -m pytest backend/tests/test_email_inbox_state.py -q`
    - result at implementation time: `1 passed`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/avatar/avatar.py`
    - `/Users/fgoiriz/private/repos/bogan/src/main.py`
    - `/Users/fgoiriz/private/repos/bogan/src/jobs.py`
  - reused pattern:
    - reused the fixed resource-pool idea from `simple-avatar`: load a bounded reusable pool once and keep reusing it instead of provisioning new resources per request
    - reused the shared singleton accessor idea from `bogan`: resolve shared runtime state once and keep it in process memory for later calls

### Leadership Recipient Is Now A Hard Gate Before Stage 1 Contact Discovery (2026-04-05)
- Decision/rule:
  - any company loaded through the normal scan pipeline must resolve a public leadership recipient email before Stage 1 contact discovery runs.
  - if no leadership recipient email is found, the company must be rejected and no company row, contacts, or downstream tasks should be created from that candidate.
  - daily auditor discovery must only return candidates that already include grounded leadership-recipient evidence, but the bot must still call the normal scan endpoint without passing a manual `ceo_email` override so backend gating remains authoritative.
  - the automated bot should retry discovery until it fills the remaining daily quota or exhausts a bounded attempt budget.
  - dev text scans are the only special case:
    - if `source_label` is a real website URL, they use the same leadership-recipient gate,
    - otherwise they require an explicit `ceo_email` and must reject when it is missing.
- Reason:
  - the audit only has commercial value if there is a senior recipient who can receive the final report.
  - running Stage 1 contact discovery for companies that can never receive the report wastes tokens and pollutes the queue with unusable audits.
  - keeping the backend scan endpoint as the final authority avoids bot-side bypasses and keeps the rejection rule consistent across manual scan, batch scan, rescan, and automated intake.
- Enforcement:
  - leadership-recipient research program:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/auditor_leadership_recipient.py`
  - scan gating and rejection paths:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`
  - automated retry loop and non-bypass bot scan payload:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
- Validation:
  - backend focused regressions:
    - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_company_scan_modes.py backend/tests/test_internal_bot_paths.py backend/tests/test_batch_scan.py -q`
    - result at implementation time: `43 passed`
  - bot focused regressions:
    - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run --with pytest pytest tests/test_automated_auditor_intake.py -q`
    - result at implementation time: `4 passed`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/main.py`
    - `/Users/fgoiriz/private/repos/outbound/backend/main.py`
  - reused pattern:
    - kept the existing `outbound`-style thin endpoint orchestration boundary so the new rejection rule lives at scan creation time rather than inside Stage 1
    - kept the `inmobot`-style bounded periodic retry loop for automated intake top-ups

## 2026-04-04

### Stage 2 Now Separates Strategy, Continue/Stop, And Writing While Keeping External `reply/done` Stable (2026-04-04)
- Decision/rule:
  - Stage 2 now takes `industry` as explicit context in addition to `conversation`, `objective`, and `company_context`.
  - Stage 2 internals must stay split into three typed mini-programs:
    - `ConversationStrategyProgram`,
    - `ConversationContinuationProgram`,
    - `ReplyGeneratorProgram`.
  - `ContactConversationProgram` remains a thin orchestrator that composes those programs and still returns only `ConversationTurnResult(reply, done)`.
  - the first freeform email opener must reuse the same strategic logic, but the WhatsApp intro template must remain unchanged and outside this Stage 2 planner flow.
  - the buyer must answer seller questions like "who are you" or "what do you need" before pushing a new ask, using vague human context and avoiding searchable invented facts.
- Reason:
  - the previous monolithic Stage 2 prompt mixed strategy, stop decisions, and copywriting, which made looping and bot-like insistence more likely.
  - separating planner vs continue/stop vs writer keeps the orchestration legible and lets prompt behavior evolve without adding Python heuristics.
  - passing `industry` into the planner makes question choice more realistic without hardcoded per-industry branches.
- Enforcement:
  - updated Stage 2 module:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage2_contact_to_conversation.py`
  - updated endpoint wiring:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`
  - updated docs/contracts:
    - `/Users/fgoiriz/private/repos/konecta-auditor/AGENTS.md`
    - `/Users/fgoiriz/private/repos/konecta-auditor/HOW_TO_DEVELOP.md`
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-stage-contracts/SKILL.md`
  - added focused tests:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_stage2_contact_to_conversation.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_message_backoff.py`
- Validation:
  - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests -q`
  - result at implementation time: `89 passed`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/ai.py`
    - `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
  - reused pattern:
    - kept `inmobot`'s objective-steering idea, but split it into typed planner/decision/writer stages for easier audit-specific control
    - kept `outbound`'s human-writing guardrail style as prompt-level guidance instead of Python cleanup

## 2026-04-04

### Automated Daily Auditor Intake Uses A DB-Free Discovery Endpoint Plus Bot-Orchestrated Normal Scans (2026-04-04)
- Decision/rule:
  - daily candidate sourcing for Konecta Auditor should be split into two steps:
    1. a backend discovery endpoint that uses Perplexity Pro Search and returns structured candidate companies without touching the DB,
    2. a bot-side daily intake loop that calls that endpoint, then loads companies through the normal backend scan endpoints.
  - the discovery step must not persist companies, contacts, or tasks.
  - duplicate avoidance should happen before and after discovery:
    - the bot fetches recent companies and passes existing names/URLs as exclusions to discovery,
    - the normal `POST /api/companies/scan` duplicate check on `normalized_source_url` remains the final guardrail.
  - the bot should tag each successful automated intake with a stable daily tag (`auto-intake:YYYY-MM-DD`) and only top up the missing daily quota instead of blindly re-running the full daily quota every loop.
  - if the automated intake creates companies on Saturday or Sunday, the bot should immediately set an exact `scheduled_send_at` for the next Monday at `20:00` local time by default.
- Reason:
  - the user wants the highest-judgment step to be company selection, not only URL ingestion.
  - keeping discovery DB-free preserves the backend contract cleanly and lets the bot stay responsible for orchestration.
  - daily tags let the bot remain stateless across normal loops while still knowing whether today's quota is already filled.
  - weekend-created audits should not default into Saturday/Sunday CEO delivery.
- Enforcement:
  - added backend discovery program and endpoint in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/auditor_company_discovery.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`
  - exposed the needed shared auth paths for bot + operator use in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/main.py`
  - added the bot-side daily intake loop and backend helpers in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/main.py`
  - enabled the daily intake env defaults in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/docker-compose.yml`
- Validation:
  - backend tests:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_company_scan_modes.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_internal_bot_paths.py`
  - bot tests:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/tests/test_automated_auditor_intake.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/main.py`
    - `/Users/fgoiriz/private/repos/inmobot/backend/scheduler.py`
    - `/Users/fgoiriz/private/repos/outbound/backend/main.py`
  - reused pattern:
    - reused `inmobot`'s dedicated periodic task pattern as the basis for a separate bot-side intake loop instead of hiding the logic inside the outbound dispatch tick
    - reused `outbound`'s thin “HTTP endpoint as async orchestration boundary” pattern for the DB-free discovery step

## 2026-03-28

### Candidate Intake And Audit Review Are Stable Operator Workflows And Need Dedicated Skills (2026-03-28)
- Decision/rule:
  - maintain a dedicated operator skill for sourcing and ingesting real candidate companies into Konecta Auditor.
  - maintain a dedicated operator skill for reviewing running/recent audits across transcripts, report artifacts, CEO delivery state, and CRM threads.
  - when a company is created on Saturday or Sunday and the user wants to avoid weekend report delivery, set an exact `scheduled_send_at` for the next Monday at `20:00` local time by default unless the user specifies another time.
  - intake should prefer real companies with public email/WhatsApp/contact paths and distinct industries rather than generic brand-name lists.
- Reason:
  - the user repeats these workflows and wants future agents to execute them without re-explaining the process each time.
  - weekend timing is commercially bad for unattended report delivery, so the safe default must be explicit and reusable.
  - audit review quality depends on reading the whole chain, not just the company row: transcripts, artifacts, delivery metadata, and CRM replies.
- Enforcement:
  - created skills:
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-icp-intake/SKILL.md`
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-audit-review/SKILL.md`
  - wired these workflows into:
    - `/Users/fgoiriz/private/repos/konecta-auditor/AGENTS.md`
    - `/Users/fgoiriz/private/repos/konecta-auditor/HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no sibling repo had an equivalent operator skill for candidate intake plus audit-review loops
    - repo-local workflow references reused:
      - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`
      - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`
      - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/crm.py`
      - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-endpoint-e2e/SKILL.md`
      - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-db-forensics/SKILL.md`

## 2026-03-27

### AgentMail Runtime Uses One Dedicated Inbox Per Email Contact Plus One Shared CRM Inbox (2026-03-27)
- Status:
  - superseded on `2026-04-05` by the fixed shared inbox pool rule above. Do not reintroduce per-contact inbox creation.
- Decision/rule:
  - conversation email contacts must each get their own persistent AgentMail inbox, keyed by contact id and reused across sends and inbound replies.
  - CEO audit delivery and manual CRM replies must share one stable CRM inbox, not one inbox per company.
  - the bot must persist `contacts.email_inbox_id` and `contacts.email_inbox_address` alongside existing email thread state so inbound resolution can match by inbox first.
  - outbound email messages should be marked `sent` when AgentMail accepts the send, then moved to `delivered` or `failed` from AgentMail webhook events.
  - inbound email processing must be webhook-first; no Gmail-style unread polling loop should remain in the bot runtime.
  - if `AGENTMAIL_WEBHOOK_URL` is absent, derive the public webhook URL from `WA_CALLBACK_URL` by swapping the path to `/webhooks/agentmail`.
- Reason:
  - one inbox per contact gives deterministic routing when a company exposes multiple email contacts; replies no longer depend on ambiguous sender-only matching.
  - a shared CRM inbox keeps the CEO-delivery loop simple while preserving thread continuity for manual follow-up.
  - AgentMail already emits received/delivered/bounced/rejected events, so webhook-driven state is cleaner and more accurate than polling unread inbox state.
- Enforcement:
  - backend contact persistence and inbound resolution were extended in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`
  - AgentMail provider/runtime wiring now lives in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/providers.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/main.py`
  - bot webhook ingress is:
    - `POST /webhooks/agentmail`
  - UI mail links must stay generic (`mailto:` or manual URLs), not Gmail thread URLs:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
- Validation:
  - bot runtime import check:
    - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run python - <<'PY' ... import main ... PY`
  - bot tests:
    - `cd /Users/fgoiriz/private/repos/konecta-auditor/bot && uv run --with pytest pytest tests`
    - result at implementation time: `49 passed`
  - backend regression tests:
    - `cd /Users/fgoiriz/private/repos/konecta-auditor && uv run --with pytest pytest backend/tests/test_message_backoff.py backend/tests/test_crm.py backend/tests/test_internal_bot_paths.py`
    - result at implementation time: `19 passed`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/webhooks.py`
  - reused pattern:
    - reused `simple-avatar`'s direct Svix verification pattern for webhook authentication
    - reused this repo's existing stateless bot queue plus backend delivery-status endpoints instead of introducing a new transport subsystem

### AgentMail Should Replace Gmail At The Provider Boundary, Not By Reworking Backend Contracts (2026-03-27)
- Decision/rule:
  - if this repo adopts AgentMail, the first integration step should be replacing `bot/providers.py::GmailProvider` behind the existing stateless `bot/` loop and backend endpoint contracts.
  - inbound delivery should prefer AgentMail webhooks over polling, but polling can remain as a fallback or recovery tool.
  - webhook signature verification should use `svix.webhooks.Webhook`; the reviewed Python SDK exposes webhook secrets and Svix header types but does not include a built-in verifier helper.
  - do not rely on AgentMail thread-mutation examples from the docs without checking the installed SDK version first; the reviewed Python SDK surface did not expose `client.inboxes.threads.update(...)`.
  - in this checkout, transport work still lives in `bot/`, even though older docs and skills mention `messenger/`.
- Reason:
  - the repo already has a clean provider boundary plus stateless backend polling/webhook orchestration. Reusing that boundary keeps the change narrow and preserves current stage and persistence contracts.
  - AgentMail provides stable message and thread IDs plus webhooks, which map cleanly onto the current delivery and inbound-registration endpoints.
  - the missing SDK thread-update surface makes local DB state or message-label state safer than designing follow-up logic around undocumented thread mutation.
- Enforcement:
  - prefer a new AgentMail provider under `/Users/fgoiriz/private/repos/konecta-auditor/bot/providers.py` over backend schema churn.
  - preserve current backend routes during the first integration pass:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/crm.py`
  - reuse Svix verification pattern from:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/webhooks.py`
  - new operational guidance was captured in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-agentmail-email/SKILL.md`
    - `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-agentmail-email/references/agentmail-operations.md`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/webhooks.py`
  - reused pattern:
    - reused `simple-avatar`'s direct `svix.webhooks.Webhook` verification pattern as the canonical webhook-signature approach for AgentMail events
    - reused this repo's existing stateless `bot/` provider boundary as the integration point instead of inventing a new transport architecture

## 2026-03-12

### Contact Objectives Must Flow End-To-End And Stage 2 Must End Threads Via Typed `done` (2026-03-12)
- Decision/rule:
  - every contact now owns its own `objective`; it is no longer enough to rely only on one company-level objective during conversation/report generation.
  - Stage 1 discovery must generate one simple, chat-resolvable objective per discovered contact.
  - manual contact creation must require an explicit objective from the operator.
  - Stage 2 no longer returns plain text only; it returns a typed `ConversationTurnResult(reply, done)`.
  - when Stage 2 returns `done=true`, the backend must still persist that final outbound message, then mark the contact as `conversation_done=true`, and never auto-reply again for that contact even if new inbound messages arrive later.
  - inbound messages after closure must still be stored as evidence; closure only stops further automation.
  - report, PDF, and CEO delivery email artifacts must all surface the per-contact objective and whether the seller achieved it.
- Reason:
  - the audit now evaluates sellers against a concrete task per contact instead of generic lead handling.
  - conversation closure must remain LLM-driven, not heuristic-driven, so the backend only obeys the typed `done` signal rather than semantically inferring the end of the thread in Python.
  - leadership artifacts are materially better when each thread shows the tested objective and outcome.
- Enforcement:
  - updated persistence in `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`:
    - `Contact.objective`
    - `Contact.conversation_done`
    - legacy SQLite files must be updated manually with a one-off `sqlite3` command; do not keep contact-column bootstraps persisted in Python
  - updated Stage 1 in `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage1_url_to_contacts.py`:
    - `DiscoveredContact.objective`
    - prompt rules for short, chat-only, evaluative objectives
  - updated Stage 2 in `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage2_contact_to_conversation.py`:
    - new `ConversationTurnResult`
    - prompt guardrails for human tone, objective steering, off-channel avoidance, bot-detection exits, and final-turn closure
  - updated Stage 3 in `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage3_company_to_report.py`:
    - `CompanyReport.contact_assessments`
    - explicit objective-achievement evaluation per contact
  - updated Stage 4 + PDF in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage4_report_to_html.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/report_pdf.py`
    - thread cards now include `objective_text`, and the first insight block must state the objective result
  - updated delivery/email/frontend in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/audit_delivery_email_content.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/index.html`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
    - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/css/style.css`
- Validation:
  - full backend test suite: `uv run pytest backend/tests -q`
  - result at implementation time: `76 passed`
  - additional PDF smoke render:
    - generated `/tmp/konecta-objective-smoke.pdf`
    - rendered `/tmp/konecta-objective-smoke.png`
    - visually confirmed the new objective line fits the existing thread header without redesigning the page
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/ai.py`
    - `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
  - reused pattern:
    - reused `inmobot`'s objective-driven conversation prompting as the closest precedent for steering a thread toward a concrete buyer goal without adding Python heuristics
    - reused `outbound`'s stronger human-writing/prompt-guardrail style as the basis for the new Stage 2 tone and off-channel controls

### Newer Inbound Must Replace Any Undelivered Draft And Reset Bot Delay On The New Message (2026-03-12)
- Decision/rule:
  - conversation contacts may have at most one current pending outbound draft: the latest undelivered outbound that is still the latest transcript turn.
  - if a new inbound arrives before that draft is sent, the backend must delete the stale undelivered draft, regenerate the reply from the updated transcript, and persist only the new draft.
  - stale inbound-processing tasks must not persist replies when a newer inbound already landed while they were generating.
  - `/api/messages/pending-delivery` must expose only the current draft per contact so the bot can stay stateless and restart its delay clock from the new `message_id`.
- Reason:
  - without draft replacement, multiple human messages arriving inside the bot delay window can leave obsolete replies queued for delivery even though the human never saw them.
  - the Stage 2 reply generator must not see unsent bot text in the transcript, otherwise it reasons over turns that never happened.
  - the bot already keys transient delay by `message_id`, so the cleanest design is to let the backend be the source of truth for which draft still exists.
- Enforcement:
  - updated `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/messages.py`:
    - inbound processing now deletes stale undelivered drafts before regeneration,
    - stale tasks skip outbound persistence when a newer inbound already exists.
  - updated `/Users/fgoiriz/private/repos/konecta-auditor/backend/database.py`:
    - added helpers for latest inbound lookup and undelivered-draft deletion,
    - `list_pending_delivery()` now returns only undelivered outbounds that are still the latest message for the contact.
  - updated `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/companies.py`:
    - contact pending-delivery summaries now reflect only the current latest draft.
  - updated tests:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/tests/test_message_backoff.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/bot/tests/test_email_dispatch_spacing.py`
  - documented in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no sibling repo had an equivalent pending-draft replacement loop
    - repo-local references reused:
      - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
      - `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/crm.py`
  - reused pattern:
    - reused the existing repo-local stateless bot design where backend polling decides which pending message still exists and the bot delay is keyed only by active `message_id`s.

### Audit Reports Must Critique Seller Behavior Only, Never Buyer/Bot Messages (2026-03-12)
- Decision/rule:
  - Stage 3 narrative audits and Stage 4 PDF-model editorial synthesis must evaluate seller-side commercial execution only.
  - buyer / potential-customer / bot-authored turns are evidence of the opportunity presented to the seller, not the object of critique.
  - report callouts, thread insights, hero summaries, and quoted evidence must never criticize, praise, score, or rewrite buyer/bot messages.
  - buyer messages in the PDF thread view should remain contextual transcript only; evaluative callouts belong only on seller messages.
  - quote cards must quote seller wording only; if no meaningful seller response exists, the quote should be omitted.
- Reason:
  - the report was surfacing editorial commentary attached to the audit bot's own lead messages, which makes the output look like it is grading the probe instead of diagnosing the vendor's commercial performance.
  - leadership-facing audit output is only useful when all judgment is anchored on what the seller did or failed to do with the inbound opportunity.
- Enforcement:
  - updated prompt instructions in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage3_company_to_report.py`
    - `/Users/fgoiriz/private/repos/konecta-auditor/backend/ai/stage4_report_to_html.py`
  - seller-only evaluation is now explicit in:
    - Stage 3 evidence rules, report structure, edge-case handling, and forbidden behaviors
    - Stage 4 hero synthesis, thread status semantics, message callout policy, insight policy, quote policy, and quality bar
- Pattern reuse log:
  - source repos searched:
    - not applicable; this was a repo-local editorial rule refinement, not a new subsystem
  - reused pattern:
    - reused the existing repo convention of fixing semantic behavior inside DSPy Signature instructions instead of Python-side filters or parsing.

### Conversational WhatsApp Dispatch Must Use A Real Bot Delay, Pinned To 45 Minutes By Default (2026-03-12)
- Decision/rule:
  - normal conversational WhatsApp outbound messages must always pass through the bot's transient dispatch delay gate before provider send.
  - the default WhatsApp dispatch delay is now `45m` (`2700s`), not a near-immediate seconds-scale wait.
  - bot runtime config must expose `WHATSAPP_DISPATCH_DELAY_MIN_SECONDS` and `WHATSAPP_DISPATCH_DELAY_MAX_SECONDS`, with production compose pinning both to `2700` for a deterministic wait.
- Reason:
  - inbound WhatsApp replies were being sent back almost immediately because the bot still had hardcoded `10s..180s` spacing, which is too short for the intended human-like cadence.
  - making the delay env-configurable keeps the email/WhatsApp runtime knobs aligned while ensuring the default production path actually waits.
- Enforcement:
  - updated `bot/utils.py`:
    - replaced hardcoded WhatsApp `10..180` second delay constants with env-backed delay bounds,
    - defaulted both bounds to `2700s`.
  - updated `docker-compose.yml`:
    - pinned `WHATSAPP_DISPATCH_DELAY_MIN_SECONDS=2700`
    - pinned `WHATSAPP_DISPATCH_DELAY_MAX_SECONDS=2700`
  - documented in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no sibling repo had an equivalent outbound WhatsApp delay configuration pattern
    - repo-local reference reused:
      - `/Users/fgoiriz/private/repos/konecta-auditor/bot/utils.py`
  - reused pattern:
    - reused the existing repo-local env-configured email delay pattern and adapted it to WhatsApp so both channels use the same runtime-configurable delay model.

### Sidebar DB Copilot Must Stay Stateless And Use Read-Only SQLite Tools (2026-03-12)
- Decision/rule:
  - the operator mini chat in the left sidebar must remain stateless on the backend.
  - the frontend may keep transcript state only in browser session storage and must send the full conversation on each turn.
  - backend answers must come from a DSPy `Program` using ReAct plus read-only SQLite tools, never by persisting assistant chat state in the server database.
  - the assistant may expose the tool trace back to the frontend so operators can inspect which SQL/schema tool calls were used.
- Reason:
  - the requested workflow is an operator convenience layer for ad hoc database questions, not a persisted product conversation.
  - keeping state in the browser avoids new backend persistence complexity while still allowing multi-turn follow-ups.
  - a read-only SQL tool keeps answers grounded in the current local DB snapshot and prevents accidental writes from agent tool use.
- Enforcement:
  - updated `backend/ai/react_agent.py`:
    - replaced the placeholder order-taking assistant with a sidebar database copilot,
    - added `describe_konecta_database` and `run_readonly_sql`,
    - kept the assistant stateless and limited to operator-facing reply generation.
  - updated `backend/endpoints/messages.py`:
    - added `POST /api/sidebar-assistant/reply`,
    - endpoint accepts full conversation plus optional selected company/contact IDs,
    - returns only `reply` for the stateless UI contract.
  - updated frontend:
    - `frontend/index.html`
    - `frontend/static/js/app.js`
    - `frontend/static/css/style.css`
    - sidebar now renders the mini chat, stores history in `sessionStorage`, and renders markdown only.
  - updated tests:
    - `backend/tests/test_sidebar_assistant.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
    - `/Users/fgoiriz/private/repos/outbound/backend/tools.py`
    - `/Users/fgoiriz/private/repos/inmobot/backend/ai.py`
    - `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
  - reused pattern:
    - reused the `outbound` ReAct `Program` + tool-builder structure for the assistant implementation,
    - reused the `inmobot` separation of agent composition vs tool builders, but skipped trajectory/tool-trace exposure because this sidebar flow does not persist assistant state.

## 2026-03-11

### Company Scans Must Normalize Source URLs And Skip Duplicate Companies Before Queueing (2026-03-11)
- Decision/rule:
  - company scan entrypoints must normalize company URLs before persistence and before duplicate checks.
  - duplicate detection must use a persisted `companies.normalized_source_url` key that ignores scheme differences (`http` vs `https`) plus cosmetic URL variants such as `www.`, query params, fragments, and trailing slashes.
  - single scans must return the existing `company_id` with a duplicate status instead of creating a second row or queueing a second scan.
  - batch scans must skip duplicate URLs both against existing companies and against earlier URLs in the same batch, queueing only novel companies.
- Reason:
  - operators were able to create duplicate companies for the same website through minor URL variations (`example.com`, `https://www.example.com/`, tracking params), which wasted scan capacity and polluted the company list.
  - deduping in endpoint glue keeps Stage 1 contracts untouched while making company identity stable at the persistence boundary.
- Enforcement:
  - updated `backend/database.py`:
    - added deterministic company URL normalization helpers,
    - added/backfilled `companies.normalized_source_url`,
    - added latest-company lookup by normalized source URL.
  - updated `backend/endpoints/companies.py`:
    - single scan now short-circuits duplicates,
    - batch scan now skips duplicate companies before queueing jobs,
    - scan responses now expose duplicate metadata.
  - updated `frontend/static/js/app.js`:
    - create-scan flows now handle duplicate responses without assuming a `task_id`.
  - updated tests:
    - `backend/tests/test_company_scan_modes.py`
    - `backend/tests/test_batch_scan.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no sibling repo had an equivalent company-URL dedupe pattern
    - internal reference reviewed: `/Users/fgoiriz/private/repos/konecta-auditor/backend/endpoints/crm.py`
  - reused pattern:
    - reused the existing repo-local `duplicate -> return existing entity without reprocessing` contract from CRM inbound dedupe, adapted here to normalized company URL scans.

### Batch Scan Reliability Must Prefer Same-Model Retries + Low Concurrency + Strict Email Guards (2026-03-11)
- Decision/rule:
  - Stage 1 company scans must not fallback from Grok contact extraction to GPT-5.2 in the normal URL scan path.
  - Instead, retry the same primary Grok model with bounded backoff and detailed per-attempt logs.
  - Firecrawl must also retry before direct-HTML fallback.
  - Default production batch concurrency should stay conservative (`3`) and company scan timeout should be generous enough for slow provider retries.
  - Batch parent tasks must fail when child company scans fail.
  - Incomplete email addresses must be rejected as invalid protocol data:
    - skip them during Stage 1 contact persistence,
    - do not keep them as CEO emails,
    - bot runtime must mark those outbound messages as `failed` instead of retrying Gmail forever.
- Reason:
  - Production batch autopsy on `2026-03-11` showed the dominant failure mix was:
    - Stage 1 fallback to GPT-5.2 hitting `insufficient_quota`,
    - `300s` scan timeout under heavy batch parallelism,
    - a smaller number of probe/DNS failures.
  - The same batch also surfaced SQLite lock pressure and one persisted invalid email contact (`info@automotoress`) that later caused Gmail `Invalid To header`.
- Enforcement:
  - updated `backend/ai/stage1_url_to_contacts.py`:
    - Grok-only extraction retries in Stage 1,
    - Firecrawl retries before HTML fallback,
    - detailed attempt logging and coarse error categorization.
  - updated `backend/endpoints/companies.py`:
    - default batch concurrency `3`,
    - company scan timeout `3000s`,
    - batch parent failure on partial child failure,
    - invalid discovered contacts skipped.
  - updated `backend/database.py`:
    - stricter email normalization/validation,
    - delete company also deletes task rows.
  - updated `bot/providers.py` + `bot/utils.py`:
    - invalid email recipients fail fast before Gmail send,
    - permanent invalid-recipient sends are marked `failed`.
  - documented in:
    - `/Users/fgoiriz/private/repos/konecta-auditor/BATCH_SCAN_AUTOPSY_2026-03-11.md`
    - `/Users/fgoiriz/private/repos/konecta-auditor/HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/bogan/src/ai/quote_bot.py`
  - reused pattern:
    - reused the explicit retry-loop-with-attempt-logging pattern from `bogan`, adapted here for Stage 1 provider retries and extraction retries.

### Company Tags Stay Operator-Only On `companies` And Bootstrap In Place (2026-03-11)
- Decision/rule:
  - freeform operator tags must persist only on `companies`, not on contacts, messages, or AI stage payloads.
  - scan forms may attach multiple tags to one company; batch scan applies the same tag set to every created company in that batch.
  - the audits home view must expose existing company tags for client-side filtering.
  - SQLite dev databases must auto-add `companies.tags_json` in place when that column is missing, without introducing migration files.
- Reason:
  - the requested feature is purely operator metadata and should not change Stage 1-4 contracts, LLM prompts, delivery logic, or transcript behavior.
  - keeping tags on the company row is the smallest safe persistence change and avoids coupling tags to any transport/runtime path.
  - older local SQLite files would otherwise fail on startup/selects once the new ORM column exists.
- Enforcement:
  - updated `backend/database.py`:
    - added normalized company-tag JSON storage on `Company`,
    - added `ensure_company_tags_column()` bootstrap during `init_db()`.
  - updated `backend/endpoints/companies.py`:
    - single scan, dev scan, batch scan, and company summary/detail payloads now accept/return `tags`.
  - updated frontend:
    - `frontend/index.html`
    - `frontend/static/js/app.js`
    - shared scan modal now accepts tags,
    - home filters now include existing-tag filtering,
    - company cards/detail show persisted tags.
  - updated tests:
    - `backend/tests/test_company_scan_modes.py`
    - `backend/tests/test_batch_scan.py`
    - `backend/tests/test_company_report_schedule.py`
    - `backend/tests/test_reportable_contacts.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - none with an equivalent operator-company tags pattern
  - reused pattern:
    - no sibling implementation matched; this repo now treats tags as company-local operator metadata with one lean JSON column and client-side filtering.

### Stage 1 Must Fallback From Firecrawl To Direct HTML With Explicit Credit/Quota Logs (2026-03-11)
- Decision/rule:
  - Stage 1 must treat Firecrawl as the primary crawl provider, but it must fallback to one direct `httpx` HTML fetch when Firecrawl fails or returns no extractable content.
  - The direct HTML fallback must pass raw HTML into the extractor without attempting JS rendering or HTML-to-markdown persistence.
  - Stage 1 must emit a strong fixed warning when Firecrawl fails, telling the operator to review Firecrawl credits/config/status, without trying to classify the provider error text in Python.
  - `website_markdown` must remain markdown-only; when the fallback path is used, it may stay empty while extraction proceeds from raw HTML only.
- Reason:
  - Firecrawl outages, missing API key, or exhausted credits should not fully block Stage 1 when the page HTML is still reachable with a normal request.
  - Operators need a loud backend signal telling them to recharge or inspect Firecrawl instead of silently getting a generic failed scan.
- Enforcement:
  - updated `backend/ai/stage1_url_to_contacts.py`:
    - added `crawl_with_firecrawl()` + `fetch_html_without_firecrawl()` recipe helpers,
    - falls back to direct `httpx.AsyncClient` HTML fetch,
    - accepts extraction content even when markdown is empty,
    - logs one fixed Firecrawl warning instead of analyzing provider messages.
  - updated `backend/tests/test_stage1_url_to_contacts.py`:
    - covers Firecrawl failure -> direct HTML fallback,
    - covers `aforward` continuing with raw HTML only.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/bogan`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/bogan/src/utils.py`
  - reused pattern:
    - reused the lean `httpx.AsyncClient` request + explicit exception logging pattern, adapted here as a single direct-HTML fallback without retries or semantic post-processing.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no sibling repo had a direct `Firecrawl -> raw httpx HTML` fallback; the Stage 1 provider fallback was implemented in-repo on top of the existing recipe-style orchestration.

## 2026-03-10

### CRM Frontend Uses Minimal Inbox Summary + Mobile List/Detail Split (2026-03-10)
- Decision/rule:
  - the CEO CRM frontend should keep the inbox summary intentionally small:
    - only a compact review card and one focus/latest card,
    - reduced thread metadata,
    - reduced per-message chrome.
  - on iPhone-width layouts, CRM must behave as two panes:
    - inbox list,
    - thread detail,
    - with an explicit back-to-inbox action instead of stacking list + detail + composer into one long page.
- Reason:
  - the previous CRM view surfaced too many counters, chips, and duplicated metadata, which made the operator workflow harder to scan.
  - on narrow screens, rendering the list and the full detail/composer together created an unnecessarily long page with weak hierarchy.
- Enforcement:
  - updated:
    - `frontend/index.html`
    - `frontend/static/js/app.js`
    - `frontend/static/css/style.css`
  - the CRM view now:
    - renders fewer overview cards,
    - uses condensed thread badges and simpler message headers,
    - toggles `crm-list-active` / `crm-detail-active` for mobile-only inbox/detail navigation.
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/outbound/frontend/index.html`
    - `/Users/fgoiriz/private/repos/outbound/frontend/static/css/style.css`
  - reused pattern:
    - reused the simpler operator-header plus focused content-area pattern from `outbound`, adapted into the Konecta CRM inbox while preserving the existing visual system and adding mobile pane switching.

## 2026-03-09

### Audit Delivery Root Emails Need Company-Specific Subject Refs To Avoid Gmail Thread Reuse (2026-03-09)
- Decision/rule:
  - CEO audit delivery root emails must include one stable company-specific subject reference.
  - deleting and recreating a company must produce a different audit-delivery root subject, even when company name, URL, and CEO email stay the same.
- Reason:
  - the backend delete path correctly removes `crm_threads` and `crm_email_messages`, but Gmail can still collapse a fresh root audit email into an older external conversation when the new send reuses the exact same subject and recipient.
  - when that happens, the new CRM seed receives the old provider `threadId`, so the recreated company appears to continue the previous thread instead of starting a new one.
- Enforcement:
  - updated `backend/audit_delivery_email_content.py`:
    - audit delivery subjects now append a short deterministic reference derived from `company_id`.
  - updated `backend/endpoints/companies.py`:
    - `/audit-delivery/email-content` now passes `company.id` into the subject builder.
  - updated tests:
    - `backend/tests/test_crm.py`
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - none with an equivalent Gmail root-thread anti-collision pattern
  - reused pattern:
    - no sibling implementation matched; this repo now treats the root email subject as part of the provider threading boundary and makes it company-instance-specific.

### Legacy `report_window_hours` Must Be Null For Sub-Hour Windows (2026-03-09)
- Decision/rule:
  - shared API payloads must expose `report_window_hours` only when `report_window_minutes` is an exact multiple of 60.
  - for `5m`, `7m`, `90m`, and any other non-whole-hour schedule, the legacy hour alias must be `null`.
- Reason:
  - the persisted legacy hour field rounds minute windows up (`5m -> 1h`, `90m -> 2h`) for backward compatibility, which can mislead the company view and any consumer that accidentally trusts the alias over the minute-precise schedule.
  - dev/test flows rely on very short report windows, so the UI must not appear to revert `5m` back to `1h`.
- Enforcement:
  - updated `backend/endpoints/companies.py`:
    - shared company summary/detail, update responses, report-schedule responses, and audit-delivery poll state now null out the legacy hour alias for non-whole-hour minute windows.
  - updated `frontend/static/js/app.js`:
    - normalized project state now derives the legacy hour alias from `report_window_minutes`, so stale backend values cannot reintroduce a fake `1h`.
  - updated docs:
    - `README.md`
    - `HOW_TO_DEVELOP.md`
  - updated tests:
    - `backend/tests/test_company_report_schedule.py`
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - none with an equivalent minute-vs-hour compatibility contract
  - reused pattern:
    - no sibling implementation matched; this repo now treats legacy aliases as response-shaping only and keeps minute-precise scheduling as the contract source of truth.

### Report Scheduling Uses Minute Precision + Persisted `scheduled_send_at` (2026-03-09)
- Decision/rule:
  - report scheduling must support exact minutes and exact date/time, not only whole hours.
  - `companies.report_scheduled_send_at` is the source of truth for report timing.
  - shared API payloads should expose `report_window_minutes` and `scheduled_send_at`; `report_window_hours` remains legacy compatibility only.
- Reason:
  - whole-hour-only scheduling blocked valid operator use cases such as `1h 30m`, `5m`, or a specific date/time.
  - keeping one persisted absolute schedule timestamp makes frontend editing, bot triggering, and CEO delivery timing agree on the same business gate.
- Enforcement:
  - updated `backend/database.py`:
    - added `Company.report_scheduled_send_at`,
    - normalized schedule persistence to UTC minute precision,
    - derived legacy hour values only for compatibility.
  - updated `backend/endpoints/companies.py`:
    - company summaries/details and poll-state now include `report_window_minutes` + `scheduled_send_at`,
    - `/report-schedule` accepts minute-precise duration or exact `scheduled_send_at`.
  - updated `frontend/index.html` and `frontend/static/js/app.js`:
    - schedule editor now supports hours + minutes and exact datetime,
    - create flow now sends `report_window_minutes`.
  - updated `bot/utils.py`:
    - full-audit triggering now prefers `scheduled_send_at`, then `report_window_minutes`, then legacy hours.
  - updated tests:
    - `backend/tests/test_company_report_schedule.py`
    - `backend/tests/test_batch_scan.py`
    - `backend/tests/test_crm.py`
    - `bot/tests/test_crm_flow.py`
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/tools.py`
  - reused pattern:
    - accept both relative-minute scheduling and exact run-at timestamps, adapted here from scheduled job tooling into company report-delivery timing.

### Production Deploy Uses Commit Push Main Plus Repo Scripts, Not SCP (2026-03-09)
- Decision/rule:
  - the canonical Konecta Auditor production deploy flow is:
    1. commit the intended change,
    2. push the deployable state to `main`,
    3. run `./deploy_to_server.sh`,
    4. inspect production with `./server_logs.sh`.
  - do not use `scp`, ad hoc remote file edits, or manual remote rebuilds as the default deploy path.
- Reason:
  - the repo already has a single deploy/log workflow wired to the VPS scripts, and bypassing it creates drift between local git state and the server checkout.
  - the remote deploy script always checks out `main` and pulls, so the deployable state must exist on `main` before release.
- Enforcement:
  - added `.cursor/skills/konecta-auditor-server-deploy/SKILL.md`
  - updated:
    - `AGENTS.md`
    - `.cursor/skills/konecta-development-method/SKILL.md`
    - `HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source of truth reviewed:
    - `./deploy_to_server.sh`
    - `./server_logs.sh`
    - remote `/root/deploy_konecta_auditor.sh`
  - reused pattern:
    - preserve the repo's existing scripted release path instead of adding a second manual deploy mechanism.

### CEO Audit Delivery Skips Transient Email Delay And Stays Restart-Safe (2026-03-09)
- Decision/rule:
  - once `created_at + report_window_hours` has elapsed and `companies.report_pdf_model_json` exists, CEO audit delivery must be sent immediately in the next bot audit cycle.
  - CEO audit delivery must not reuse the normal outbound email random-delay scheduler or any in-memory wait keys.
  - restarts must not add a new waiting period before sending an already-ready CEO audit email.
- Reason:
  - the bot had reused the transient email delay map for CEO audit delivery, so a restart could reintroduce a fresh 10-30 minute wait even after the report window had already elapsed and the PDF was ready.
  - that made production reports appear stuck as generated-but-not-sent despite having all required persisted state.
- Enforcement:
  - updated `bot/utils.py`:
    - removed audit-delivery use of transient email delay keys,
    - CEO audit delivery now sends as soon as the poll-state row is eligible and the PDF bytes are available,
    - normal conversation email spacing remains unchanged.
  - updated tests:
    - `bot/tests/test_crm_flow.py`
  - updated docs:
    - `README.md`
    - `HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern:
    - transport runtime should send immediately once the persisted business gate says the item is ready, adapted here so CEO audit delivery depends only on backend poll-state eligibility instead of bot-local transient delay state.

### WhatsApp Delivery Flow Persists `sent` Before Provider Confirmation And Treats `read` As Post-Delivery (2026-03-09)
- Decision/rule:
  - WhatsApp outbound dispatch must persist `sent` when Meta accepts the send request.
  - WhatsApp status callbacks must preserve provider intent:
    - `sent` -> backend `sent`
    - `delivered` -> backend `delivered`
    - `read` -> backend `delivered` while keeping `read` as a transport/logging-only state
    - `failed` -> backend `failed`
  - If Meta sends a delivery callback for an unknown `external_id`, the bot transport layer must ignore it instead of raising and logging a stack trace.
- Reason:
  - persisting `delivered` at send-accept time makes reportability and transcript state too optimistic before any provider confirmation exists.
  - collapsing `read` into `delivered` in logs makes one real delivery look like two separate delivery confirmations.
  - some webhook callbacks can arrive for messages the backend does not currently know about (for example after local DB resets or callback/send races), and treating those `404` responses as fatal polluted production logs without recovering any state.
- Enforcement:
  - updated `bot/utils.py`:
    - WhatsApp send acceptance now persists `status="sent"`,
    - WhatsApp webhook updates preserve `sent` vs `delivered` vs `failed`,
    - provider `read` is stored as backend `delivered` but returned to logging as `provider_status="read"`,
    - `process_whatsapp_message_status_event(...)` downgrades backend `404` lookups to an ignored outcome.
  - updated `bot/logging_utils.py`:
    - ignored WhatsApp status callbacks are debug-only, so production logs stay quiet,
    - `read` webhook events log as `read`, not as a second `delivered`.
  - updated tests:
    - `bot/tests/test_whatsapp_template_dispatch.py`
    - `bot/tests/test_logging_utils.py`
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern:
    - keep provider message IDs and webhook status handling inside the transport runtime boundary, adapted here so unknown provider callbacks are handled defensively in `bot/` and provider lifecycle states stay richer than the backend's shared message enum.

### Shared Contact Transcript Routes Accept Session Or Internal Token (2026-03-09)
- Decision/rule:
  - company contact transcript routes under `/api/companies/{company_id}/contacts/{contact_id}/messages...` are shared backend contracts, not bot-only routes.
  - operator-facing audit-delivery read routes under `/api/companies/{company_id}/audit-delivery/{ceo-email,email-content,pdf}` are also shared contracts, not bot-only routes.
  - these shared routes must accept either:
    - a valid operator session cookie, or
    - `X-Internal-Token` matching `INTERNAL_API_TOKEN`.
  - only true bot-only transport endpoints remain internal-token-only.
- Reason:
  - the auth middleware had classified the shared transcript routes as bot-only, so backoffice clicks on a contact chat triggered `401`, frontend redirected to `/login`, and operator context was lost.
  - the bot runtime also uses these same routes for inbound registration and delivery/text sync, so removing token support entirely would break transport flows.
- Enforcement:
  - updated `backend/main.py`:
    - moved company contact transcript routes out of the internal-only matcher,
    - moved audit-delivery read routes out of the internal-only matcher,
    - added a shared-route matcher that allows either operator session auth or valid internal token auth.
  - updated regression tests in `backend/tests/test_internal_bot_paths.py` to prove:
    - shared transcript routes are not treated as internal-only,
    - shared audit-delivery read routes are not treated as internal-only,
    - shared transcript routes accept internal token auth,
    - shared transcript routes also accept normal operator session auth,
    - shared audit PDF route accepts both normal operator session auth and internal token auth.
  - updated docs:
    - `README.md`
    - `HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/auth_dependencies.py`
  - reused pattern:
    - keep auth boundary classification explicit in one central backend gate, adapted here to split routes into internal-only vs shared session-or-token contracts.

## 2026-03-07

## 2026-03-08

### Internal Bot Routes Use Shared Header Token, Not Session Cookie (2026-03-08)
- Decision/rule:
  - bot-facing machine routes must not be exposed anonymously and must not depend on browser login cookies.
  - internal transport routes are protected by a shared header token: `X-Internal-Token` must match `INTERNAL_API_TOKEN`.
  - operator-facing backoffice routes continue using TOML user login + session cookie auth.
- Reason:
  - the first cookie-only global auth rollout blocked bot polling/delivery callbacks.
  - opening those routes anonymously would fix functionality but violates the intended trust boundary; they should stay private to backend/bot runtimes.
- Enforcement:
  - updated `backend/auth.py` with shared internal-token helpers and header constant.
  - updated `backend/main.py` middleware:
    - detect internal bot route set,
    - require valid `X-Internal-Token`,
    - reject cookie-only or anonymous access with `401 Internal authentication required.`
  - updated `bot/utils.py` so the shared backend client sends `X-Internal-Token` from `INTERNAL_API_TOKEN`.
  - updated `backend/tests/test_auth.py` to prove:
    - logged-in operator sessions still cannot use internal bot routes without the header,
    - internal routes work with the shared token.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/auth_dependencies.py`
  - reused pattern:
    - header-based machine/client authentication, simplified here into one shared internal token enforced at middleware level for transport-only routes.
- Affected components:
  - `backend/auth.py`
  - `backend/main.py`
  - `bot/utils.py`
  - `backend/tests/test_auth.py`
  - `README.md`
  - `HOW_TO_DEVELOP.md`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Primitive Backoffice Auth: TOML Accounts + Cookie Session Middleware (2026-03-08)
- Decision/rule:
  - Backoffice access is now gated by a primitive server-side auth layer: no frontend/static/backend API access without a valid login session cookie.
  - Admin credentials live in a TOML file (`auth.toml` by default, configurable via `AUTH_TOML`) instead of hardcoding users in Python.
  - Auth is fail-closed by default when enabled: startup fails if the credentials file is missing/invalid/empty.
  - `AUTH_DISABLE=true` remains an explicit bypass for tests/local bypass scenarios only.
- Reason:
  - operators needed a very simple admin-managed auth mechanism (user/password pairs) without external providers, DB auth tables, or migrations.
  - previous runtime exposed full frontend and API surfaces anonymously.
- Enforcement:
  - added `backend/auth.py`:
    - loads and validates TOML account config,
    - manages in-memory session tokens + expiry,
    - provides login page HTML for unauthenticated users.
  - added `backend/endpoints/auth.py`:
    - `POST /api/auth/login`
    - `POST /api/auth/logout`
    - `GET /api/auth/me`
  - updated `backend/main.py`:
    - startup loads auth config,
    - global middleware blocks non-public routes without a valid session,
    - unauthenticated non-API requests redirect to `/login`,
    - unauthenticated API requests return `401`.
  - updated frontend fetch flow in `frontend/static/js/app.js` to redirect to `/login` on `401`.
  - default credentials file is now `auth.toml` and is ignored in git.
  - added auth tests in `backend/tests/test_auth.py`.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/auth_dependencies.py`
  - reused pattern:
    - centralized backend auth helper + shared enforcement point, adapted from dependency-style auth into repo-level middleware + cookie-session gate for this simpler TOML-backed requirement.
  - result:
    - no sibling repo had an equivalent primitive TOML + cookie gate for static+API blocking, so this repo added the minimal dedicated auth module while preserving existing FastAPI/router conventions.
- Affected components:
  - `backend/auth.py`
  - `backend/endpoints/auth.py`
  - `backend/endpoints/__init__.py`
  - `backend/main.py`
  - `backend/tests/conftest.py`
  - `backend/tests/test_auth.py`
  - `frontend/static/js/app.js`
  - `frontend/index.html`
  - `.gitignore`
  - `auth.toml`
  - `README.md`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Batch Scan Endpoint Accepts JSON For Text-Only Callers (2026-03-08)
- Decision/rule:
  - `POST /api/companies/scan-batch` must accept both `multipart/form-data` and `application/json` for the shared text/settings fields.
  - File uploads remain `multipart/form-data` only, but text-only callers should not be forced through a form submission just to reach the same batch extractor pipeline.
  - Batch scan JSON intake should accept both `freeform_text` and `text` as equivalent input keys for backward-compatible text-only callers.
- Reason:
  - the route originally bound only `Form(...)` fields, so JSON callers hit the handler with empty defaults and got a misleading 422 (`Provide freeform text and/or at least one attachment.`) even when they had supplied valid batch text.
  - operators and auxiliary clients can legitimately send text-only batch input without files, and that should reuse the same endpoint contract instead of requiring a different route.
- Enforcement:
  - updated `backend/endpoints/companies.py`:
    - added typed `BatchScanRequest` parsing,
    - added `resolve_batch_scan_request(...)` to branch between multipart form intake and JSON intake,
    - kept the downstream bundle building and batch scheduling path unchanged.
  - updated tests:
    - `backend/tests/test_batch_scan.py` now posts JSON to `/api/companies/scan-batch` and asserts normal task creation.
  - updated docs:
    - `README.md`
    - `HOW_TO_DEVELOP.md`
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no sibling repo already exposed a closer mixed JSON/multipart endpoint contract for this flow, so the implementation reused the current repo's existing typed-request pattern and added a small `Request` parser branch locally.
- Affected components:
  - `backend/endpoints/companies.py`
  - `backend/tests/test_batch_scan.py`
  - `README.md`
  - `HOW_TO_DEVELOP.md`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Batch Company Scan Intake + Task-Aware Processing State (2026-03-08)
- Decision/rule:
  - Batch company intake is a separate pre-Stage-1 program: `bundled input text -> list[str]` unique company URLs.
  - Batch intake must treat operator freeform text and uploaded files identically after conversion: every source becomes text, every text block is labeled, then the blocks are concatenated into one bundle string.
  - Uploaded files must be converted to text through `attachments`, not ad hoc parser branches per extension inside the endpoint.
  - Semantic company-URL selection, exclusion, and deduplication belong in the batch extractor Signature instructions, not in Python pre/post-processing around the LLM call.
  - Batch execution must maintain a steady max concurrency of `20` company scans; do not process fixed chunks and wait for the whole chunk to finish before starting the next one.
  - Company API/frontend state must be task-aware: when a company still has queued/running scan work, surface it as `processing` and do not let `0 contacts` read as a finished result.
  - Startup recovery must fail stale queued/running company scan tasks and move their companies out of ambiguous "still processing" limbo.
- Reason:
  - operators need one backoffice flow that accepts pasted lead lists, CSV/PDF uploads, or both, without caring about file format-specific extraction logic in the UI.
  - chunked batch execution leaves capacity idle while waiting for the slowest task in a wave; a steady concurrency cap keeps throughput high and predictable.
  - the existing UI bug showed fresh companies as if discovery had already finished with zero contacts after a refresh, which is operationally misleading.
- Enforcement:
  - added `backend/ai/batch_input_to_company_urls.py`:
    - `BatchInputToCompanyUrlsProgram.aforward(bundled_input)` uses `grok_4_1_fast_reasoning`,
    - returns a typed `BatchCompanyUrlResult`,
    - keeps company-URL rules in Signature instructions instead of Python-side URL blacklists/canonicalizers/dedupers.
  - updated `backend/endpoints/companies.py`:
    - added `POST /api/companies/scan-batch`,
    - converts uploaded files to text with `attachments`,
    - builds the labeled bundle string,
    - creates one company + one tracked scan task per extracted URL,
    - runs scan execution behind a semaphore-limited async scheduler,
    - exposes `processing` on company summary/detail payloads.
  - updated `backend/database.py`:
    - `Company.create(...)` now accepts explicit initial status,
    - `Task.list_pending_task_types_for_resource(...)` exposes non-terminal task types for one company.
  - updated `backend/endpoints/tasks.py`:
    - restart recovery now marks stale `queued` and `running` tasks as failed,
    - associated company scan resources are marked failed too.
  - updated frontend:
    - scan modal now supports `single` and `batch` modes,
    - batch mode accepts freeform text plus multiple files,
    - home cards and company detail view show explicit processing state and keep core surfaces visually blocked until scan completion.
  - updated tests:
    - `backend/tests/test_batch_scan.py`
    - `backend/tests/test_company_report_schedule.py`
    - `backend/tests/test_company_scan_modes.py`
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/simple-avatar`
  - source files:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/documents.py`
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/ai/utils.py`
  - reused patterns:
    - file upload -> temp file -> `attachments` text extraction pipeline,
    - semaphore-limited async concurrency for keeping a bounded worker pool busy.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: `simple-avatar` had the closest proven patterns for both attachment-to-text intake and bounded async fan-out; sibling repos did not have a closer end-to-end company batch scan implementation.
- Affected components:
  - `backend/ai/batch_input_to_company_urls.py`
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/tasks.py`
  - `backend/tests/test_batch_scan.py`
  - `backend/tests/test_company_report_schedule.py`
  - `backend/tests/test_company_scan_modes.py`
  - `frontend/index.html`
  - `frontend/static/css/style.css`
  - `frontend/static/js/app.js`
  - `README.md`
  - `HOW_TO_DEVELOP.md`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Quiet Runtime Logging: Hide Access Noise, Aggregate Bot Wait States (2026-03-08)
- Decision/rule:
  - Backend and bot runtimes should suppress successful Uvicorn access logs and keep only failing HTTP access entries.
  - Bot delivery logs must be operator-facing: plain language, emoji-coded categories, and one summary for repeated wait states instead of one line per pending message on every poll tick.
  - Delay-based outbound holds must surface as aggregated queue summaries with human wait times, while successful sends, delivery confirmations, and failures remain explicit.
- Reason:
  - the previous runtime output was dominated by `/health`, polling endpoints, and per-message delay lines every 5 seconds, which buried the few events an operator actually cares about.
  - raw terms like `dispatch`, `deferred`, and error codes such as `whatsapp_delay_not_elapsed` were too implementation-centric for day-to-day monitoring.
- Enforcement:
  - added `bot/logging_utils.py`:
    - configures concise runtime logging,
    - filters Uvicorn access logs down to failing requests,
    - deduplicates repeated "still waiting" queue summaries,
    - renders human-readable bot/audit/inbound WhatsApp status messages.
  - updated `bot/main.py`:
    - replaced raw per-iteration counters with human summaries,
    - logs backend outage/recovery once per state change,
    - logs email inbound saves and WhatsApp webhook outcomes in plain language.
  - updated `bot/utils.py`:
    - removed per-message delay scheduling/info logs,
    - propagated `wait_seconds` and recipient context in `DispatchResult` so the logger can summarize queue state without spamming.
  - updated `backend/main.py`:
    - applies the same successful-access-log suppression pattern for backend HTTP noise.
  - updated tests:
    - `bot/tests/test_email_dispatch_spacing.py`
    - `bot/tests/test_whatsapp_template_dispatch.py`
    - `bot/tests/test_logging_utils.py`
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/simple-avatar`
  - source files:
    - `/Users/fgoiriz/private/repos/simple-avatar/backend/utils.py`
  - reused pattern: centralized clean logging configuration with noisy HTTP/library logs suppressed, adapted here into service-specific operator summaries and Uvicorn access filtering.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: `simple-avatar` had the closest proven "configure clean logging once" pattern; sibling repos did not already have a matching stateful queue-summary logger, so this repo-specific aggregation layer was added on top.
- Affected components:
  - `backend/main.py`
  - `bot/main.py`
  - `bot/providers.py`
  - `bot/utils.py`
  - `bot/logging_utils.py`
  - `bot/tests/test_email_dispatch_spacing.py`
  - `bot/tests/test_whatsapp_template_dispatch.py`
  - `bot/tests/test_logging_utils.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### PyWA Uses One Shared Client For Outbound + Inbound (2026-03-08)
- Decision/rule:
  - The bot should follow the `inmobot` PyWA shape: one `WhatsApp(...)` client bound to the FastAPI app handles outbound sends, template sends, inbound webhooks, and status webhooks.
  - Do not split PyWA into separate outbound and webhook clients in this repo unless there is a proven SDK limitation forcing that.
  - `WA_CALLBACK_URL` is optional for bootstrap; when omitted, route registration still works and callback registration can be handled manually.
  - `WA_VERIFY_TOKEN` remains mandatory because the shared PyWA client listens for incoming updates.
- Reason:
  - the split-client bootstrap drifted away from the proven sibling pattern in `inmobot` and created an avoidable startup bug around PyWA server initialization semantics.
  - `pywa_async.WhatsApp` treats a provided `server` kwarg as webhook mode, so the old split path was fragile and unnecessary for the actual send+receive runtime we want.
- Enforcement:
  - updated `bot/providers.py`:
    - collapsed the provider back to one shared `self._wa` client,
    - kept phone-scoped callback registration (`callback_url_scope=PHONE`) and status webhook forwarding,
    - made `WA_CALLBACK_URL` optional while keeping `WA_VERIFY_TOKEN` required.
  - updated `bot/tests/test_whatsapp_inbound_provider.py`:
    - asserts single-client bootstrap shape,
    - covers missing `WA_CALLBACK_URL` bootstrap.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source files:
    - `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: one FastAPI-bound PyWA client used for both sends and inbound handlers, adapted here with `PHONE` callback scope and delivery-status webhook handling.
- Affected components:
  - `bot/providers.py`
  - `bot/tests/test_whatsapp_inbound_provider.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Explicit UTC API Timestamps For Schedule Math + Frontend Naive-ISO Fallback (2026-03-08)
- Decision/rule:
  - Backend company/contact timestamp fields consumed by the frontend must be serialized as explicit UTC strings with a `Z` suffix, never as naive ISO datetimes.
  - Frontend date parsing must treat legacy naive backend ISO strings as UTC, not as browser-local time.
  - Report-schedule UI copy must refer to Florianopolis / GMT-3 so operators know which clock the schedule editor uses.
- Reason:
  - SQLite-backed naive datetimes serialized with plain `.isoformat()` were interpreted by browsers as local time, then shifted again by the report-schedule GMT-3 formatter, producing +3h drift in displayed deadlines and turning `1h` saves into `4h` server-side schedule resolutions.
- Enforcement:
  - updated `backend/endpoints/companies.py`:
    - reused `format_timestamp_seconds()` for `CompanySummary`, `ContactSummary`, `UpdateCompanyResponse`, and `UpdateCompanyReportScheduleResponse`.
  - updated `frontend/static/js/app.js`:
    - added `parseApiDateValue()` to coerce naive ISO strings to UTC before timestamp math/formatting.
  - updated `frontend/index.html`:
    - clarified schedule editor copy to `Florianopolis / GMT-3`,
    - bumped static asset cache-busting version.
  - updated `backend/tests/test_company_report_schedule.py`:
    - added a regression test covering naive company datetimes being serialized back to explicit UTC.
- Pattern reuse log:
  - source repo: current repo (`konecta-auditor`)
  - source files:
    - `backend/endpoints/companies.py`
    - `frontend/static/js/app.js`
  - reused pattern: existing repo-level `format_timestamp_seconds()` UTC serializer, extended from schedule responses into all company/contact payload timestamps and paired with a defensive frontend parser for legacy rows.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: sibling repos did not expose a safer browser-facing timestamp serialization pattern; the fix reused the current repo's explicit-UTC helper and widened its enforcement surface.
- Affected components:
  - `backend/endpoints/companies.py`
  - `backend/tests/test_company_report_schedule.py`
  - `frontend/static/js/app.js`
  - `frontend/index.html`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### WhatsApp Phone-Scoped Webhook Gating + Status-Confirmed Delivery Evidence (2026-03-07)
- Decision/rule:
  - WhatsApp outbound delivery must stay blocked unless the webhook client is also configured successfully.
  - WhatsApp webhook registration must use PyWA `PHONE` callback scope instead of `APP` scope to avoid unnecessary app-validation coupling during callback registration.
  - WhatsApp messages must transition `undelivered -> sent -> delivered/failed`; provider accept/`wamid` is not enough to mark a message as `delivered`.
  - Stage 3 reports and audit-delivery contact lines must include only contacts with at least one outbound message in `delivered` state.
  - Each worker iteration must log dispatch summaries plus every deferred/failed dispatch outcome.
- Reason:
  - the previous webhook registration used default `APP` scope, which can fail on Meta app validation even when phone-level webhook override is sufficient for this runtime.
  - the previous dispatch flow marked WhatsApp messages `delivered` immediately after provider send acceptance, even though final handset delivery should come from webhook status updates.
  - reports and CEO email copy were counting contacts with no confirmed delivery evidence, overstating coverage.
- Enforcement:
  - updated `bot/providers.py`:
    - uses one FastAPI-bound PyWA client for both outbound sends and inbound/status webhooks,
    - requires the shared client to initialize successfully for `configured=True`,
    - registers webhook with `callback_url_scope=PHONE`,
    - forwards WhatsApp message status webhooks into the bot runtime.
  - updated `bot/main.py`:
    - logs per-iteration dispatch totals,
    - logs every deferred/failed dispatch item with message/contact/channel/error context,
    - processes outbound WhatsApp message status webhook events.
  - updated `bot/utils.py`:
    - marks WhatsApp messages as `sent` after provider acceptance,
    - updates backend rows to `delivered`/`failed` via provider external id on webhook status events.
  - updated `backend/database.py`, `backend/endpoints/messages.py`, `backend/endpoints/companies.py`:
    - added `sent` and `failed` delivery states,
    - added backend update path by outbound `external_id`,
    - filtered reportable contacts and CEO email contact lines to delivery-confirmed contacts only.
  - updated tests:
    - `bot/tests/test_whatsapp_inbound_provider.py`
    - `bot/tests/test_whatsapp_template_dispatch.py`
    - `backend/tests/test_reportable_contacts.py`
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source files:
    - `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: lean PyWA bootstrap with optional callback URL, adapted here into phone-scoped webhook registration plus explicit delivery-state handling because no sibling repo already implemented WhatsApp status-confirmed transcript/report gating.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no sibling repo exposed an existing WhatsApp status-confirmed delivery pipeline; the final adaptation preserved the sibling bootstrap shape while adding the missing delivery-evidence pattern.

### Backoffice Project Header Stack + Canonical Schedule Save Payload (2026-03-07)
- Decision/rule:
  - The project header must collapse from a two-column layout to a single-column stack before the right action rail starts clipping or overlapping audit controls.
  - Header-side automation toggles and audit action buttons must size within the card width and never depend on flex overflow behavior.
  - The frontend report-schedule editor must send a canonical `/report-schedule` payload using `scheduled_send_at` only; `report_window_hours` remains a local synced display field and is resolved server-side from the scheduled timestamp.
- Reason:
  - the previous header composition overflowed around medium desktop widths (~1100px), cutting action buttons off-screen and making the project view feel broken.
  - sending both schedule fields from the frontend created avoidable 422 mismatches against the backend alignment contract when the UI fields drifted even slightly.
- Enforcement:
  - updated `frontend/static/css/style.css`:
    - switched `#projectView .view-head.project-head` to a responsive grid,
    - constrained `.head-actions` to an internal grid with full-width controls,
    - made CEO email row wrap safely,
    - moved report-schedule editor actions onto a dedicated row,
    - added a `1240px` stack breakpoint before medium-width overflow.
  - updated `frontend/static/js/app.js`:
    - changed `handleSaveProjectReportSchedule()` to send only `scheduled_send_at` to `/api/companies/{company_id}/report-schedule`.
  - updated `frontend/index.html`:
    - bumped CSS/JS cache-busting query versions.
  - validated in a real browser with Playwright at desktop (`1440x1200`, `1100x1000`) and mobile (`390x844`) against the existing `Konecta Labs` company data.
- Pattern reuse log:
  - source repo: current repo (`konecta-auditor`)
  - source files:
    - `frontend/static/css/style.css`
    - `frontend/static/js/app.js`
  - reused pattern: existing project-view breakpoint overrides and schedule-field synchronization logic, adapted into a canonical single-source save payload plus an earlier header stack breakpoint.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no sibling repo exposed a closer plain-HTML/CSS backoffice header pattern for this exact split header + schedule editor composition.
- Affected components:
  - `frontend/static/css/style.css`
  - `frontend/static/js/app.js`
  - `frontend/index.html`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-03-06

### Stage 1 Firecrawl Full-Page Crawl + `raw_html` Extraction Input (2026-03-06)
- Decision/rule:
  - Stage 1 Firecrawl crawl must always set `scrape_options.only_main_content=False`.
  - Stage 1 crawl must request both `markdown` and `raw_html` from Firecrawl.
  - Stage 1 must persist `website_markdown` as markdown-only to preserve downstream contract shape.
  - Stage 1 extractor input must concatenate `markdown + raw_html` into one string for maximum contact recall.
- Reason:
  - Firecrawl main-content filtering can drop footer/contact sections, causing Stage 1 to miss public emails and phones even when they exist on the website.
  - `raw_html` preserves additional evidence such as footer markup and structured metadata that markdown conversion may omit.
- Enforcement:
  - updated `backend/ai/stage1_url_to_contacts.py`:
    - added `CrawledWebsiteContent`,
    - forced Firecrawl `ScrapeOptions(formats=["markdown", "raw_html"], only_main_content=False)`,
    - built extractor input as `markdown + raw_html`,
    - kept `website_markdown` persisted as markdown-only.
  - updated `backend/tests/test_stage1_url_to_contacts.py`:
    - covers Firecrawl option wiring,
    - covers `aforward` extracting from combined content while persisting markdown-only.
  - manually validated with `.venv` Python because the workspace test runners are not currently aligned with the repo interpreter/wheels.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no direct sibling pattern for Firecrawl multi-format Stage 1 contact extraction was found; reused the existing repo's recipe-style `aforward` orchestration while adapting the crawl helper.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/tests/test_stage1_url_to_contacts.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Mobile Project View Main-First Layout (2026-03-06)
- Decision/rule:
  - On mobile/tablet widths, the project view must surface the main company workspace before sidebar context cards.
  - In project view mobile, the left sidebar brand block and redundant scan CTA must be hidden so contact review and chat stay above the fold.
  - In project view mobile with a selected contact, the chat panel must appear before the contact switcher.
  - The mobile contact switcher for an open thread must render as a horizontal scroll band, not a tall stacked sidebar.
  - Home view mobile keeps the branded sidebar first; only project view changes ordering.
  - Mobile project cards and chat surfaces must stay full-width without horizontal overflow.
- Reason:
  - the previous mobile layout placed the full sidebar ahead of the project workspace, forcing ~1 viewport of dead scrolling before the operator could reach contacts or chat.
- Enforcement:
  - updated `frontend/static/css/style.css`:
    - switched mobile `.app-shell` to flex-column,
    - used `body:has(#projectView:not(.hidden))` to reorder `.main` before `.sidebar` only in project view,
    - hid mobile project-view sidebar brand/scan CTA,
    - stacked home search + CTA vertically on narrow screens,
    - tightened mobile project header cards and reduced chat panel minimum height,
    - forced mobile project header internals to stretch/shrink correctly to prevent real horizontal overflow,
    - reordered mobile open-thread layout to `chat -> contact switcher -> sidebar context`,
    - converted the mobile open-thread contact switcher into a horizontal scroll band.
  - verified in a real browser with mobile viewport (`390x844`) and desktop viewport (`1440x1200`) against the existing `Konecta Labs` company data.
- Pattern reuse log:
  - source repo: current repo (`konecta-auditor`)
  - source files:
    - `frontend/static/css/style.css`
  - reused pattern: existing `:has(...)`-driven layout switching already used by the project split-view grid, extended here to make the mobile project experience main-first without adding JS-only view state logic.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no closer sibling implementation for this exact mobile split-view reorder pattern was found.
- Affected components:
  - `frontend/static/css/style.css`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Stage 1 HTML Preflight + `www` URL Fallback (2026-03-06)
- Decision/rule:
  - Stage 1 must preflight the exact user-provided URL with a simple HTML fetch before crawling.
  - If the provided URL returns HTML, Stage 1 must proceed with that URL and must not try the `www.` variant.
  - If the provided URL does not return HTML, Stage 1 may try exactly one fallback by prefixing the hostname with `www.` and proceed only when that variant returns HTML.
  - If neither the original URL nor the `www.` fallback returns HTML, Stage 1 must fail early instead of handing a dead URL to the crawler.
- Reason:
  - some domains are not reachable at the bare host but do resolve correctly under `www.`, and crawling the dead variant wastes time and hides the real recoverable path.
- Enforcement:
  - updated `backend/ai/stage1_url_to_contacts.py`:
    - added deterministic HTML preflight with `httpx.AsyncClient`,
    - added `www.` variant builder for bare domains,
    - resolved the crawl URL before Firecrawl execution,
    - kept `aforward` as recipe-style orchestration: normalize -> resolve working URL -> crawl -> extract.
  - added `backend/tests/test_stage1_url_to_contacts.py`:
    - covers "original works, do not try `www`",
    - covers "`www` fallback succeeds after original fails",
    - covers full failure when both variants fail,
    - covers `aforward` using the resolved crawl URL.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/bogan`
  - source files:
    - `/Users/fgoiriz/private/repos/bogan/src/utils.py`
  - reused pattern: lean `httpx.AsyncClient` request wrapper with straightforward exception handling and retry-free probe semantics, adapted here for Stage 1 HTML reachability preflight.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no direct sibling implementation for bare-domain -> `www.` fallback selection was found.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/tests/test_stage1_url_to_contacts.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-03-05

### Backoffice CEO Email Inline Copy + Edit Panel (2026-03-05)
- Decision/rule:
  - Company header must expose the current `ceo_email` value directly in the frontend.
  - The visible CEO email chip must copy the value on click.
  - Operators must be able to edit and save `ceo_email` inline from the company header without leaving the page.
  - UI state for inline CEO email editing must remain frontend-local and persist through the existing `PUT /api/companies/{company_id}` contract.
- Reason:
  - operators need to confirm and correct the final CEO audit recipient quickly while reviewing a company, especially close to the report delivery deadline.
- Enforcement:
  - updated `frontend/index.html`:
    - added a dedicated `projectCeoEmailPanel` in the company header with copy, edit, save, and cancel controls.
    - bumped static asset cache-busting version for CSS/JS.
  - updated `frontend/static/js/app.js`:
    - added local UI state for CEO email editing/saving,
    - rendered current `ceo_email` in the project header,
    - wired click-to-copy behavior,
    - wired inline save/cancel flow against `PUT /api/companies/{company_id}` with `ceo_email`.
  - updated `frontend/static/css/style.css`:
    - added header panel styling for readable/copyable email display and inline editor layout.
- Pattern reuse log:
  - source repo: current repo (`konecta-auditor`)
  - source files:
    - `frontend/static/js/app.js`
    - `frontend/static/css/style.css`
  - reused pattern: existing local click-to-copy feedback (`showCopiedEffect`) and inline edit/save interaction style already used for transcript message editing, adapted for company-level CEO email configuration.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no direct sibling implementation for this exact header-level editable email control was found.
- Affected components:
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Backoffice Audit Actions Simplified To Generate/View PDF (2026-03-05)
- Decision/rule:
  - Company header actions were reduced to exactly two audit actions: `Generate Audit` and `View Audit`.
  - `Generate Audit` must show an explicit confirmation when a PDF audit already exists, warning that regeneration will replace the current audit and that downloading the current one should use `View Audit`.
  - `View Audit` must download the audit PDF from `/api/companies/{company_id}/audit-delivery/pdf` and not rely on HTML/JSON artifact viewers.
  - Frontend artifact state must treat `artifact-pdf-model` as the availability source for enabling `View Audit`.
- Reason:
  - current product flow no longer uses HTML report artifacts; exposing JSON/HTML actions creates wrong operator affordances and confusion.
- Enforcement:
  - updated `frontend/index.html`:
    - removed `Refresh`, `Generate Full Report`, `Generate Report JSON`, `View Report JSON`, `Generate HTML`, `View Report HTML` buttons from company header actions,
    - added only `Generate Audit` and `View Audit`.
  - updated `frontend/static/js/app.js`:
    - replaced HTML/JSON action handlers with PDF download handler (`handleViewAudit`),
    - switched artifact discovery from `artifact-html` to `artifact-pdf-model`,
    - added regeneration confirmation guard (`shouldConfirmAuditRegeneration`) before audit rebuild,
    - kept generation pipeline as Stage 3 + Stage 4 (`prepare-report` + `build-report-pdf-model`),
    - guarded optional `refreshProjectBtn` event binding because the button is no longer present in the new UI.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/simple-avatar`
  - source files:
    - `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/[locale]/create-course/(creation)/[id]/slides/[lessonId]/page.tsx`
    - `/Users/fgoiriz/private/repos/simple-avatar/frontend/translations/es/slides.json`
  - reused pattern: explicit confirmation copy when regenerating an existing PDF artifact, with clear guidance to use a separate view/download action when regeneration is not needed.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
- Affected components:
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Scan Request CEO Email Override (2026-03-05)
- Decision/rule:
  - `POST /api/companies/scan` accepts optional `ceo_email`.
  - If `ceo_email` is provided in the scan request, scan persistence must keep that value as company `ceo_email`.
  - If `ceo_email` is missing/empty in the scan request, fallback to Stage 1 discovered `ceo_email`.
  - Do not modify Stage 1 program contract/logic for this behavior; resolve priority in endpoint glue.
- Reason:
  - operators need to set a known delivery recipient at creation time without waiting for extraction quality from URL discovery.
- Enforcement:
  - updated `backend/endpoints/companies.py`:
    - added `ScanCompanyRequest.ceo_email`,
    - passed `request_ceo_email` into `scan_company_core(...)`,
    - applied `request_ceo_email or stage1_ceo_email` precedence before `Company.update(..., update_ceo_email=True)`.
  - updated frontend scan modal/payload:
    - `frontend/index.html` adds `createCeoEmailInput`,
    - `frontend/static/js/app.js` sends `ceo_email` in `/api/companies/scan` payload.
  - updated `README.md` scan request contract with optional `ceo_email` and precedence rule.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no direct sibling pattern for this exact scan-time CEO email override was found; reused existing local pattern of request-level override in endpoint glue while keeping Programs unchanged.
- Affected components:
  - `backend/endpoints/companies.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `README.md`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### WhatsApp Self-Event Filtering + Stale Webhook Guard + Reply-Context Fix (2026-03-05)
- Decision/rule:
  - WhatsApp inbound processing must ignore self-authored webhook updates (messages sent by the business line) before backend registration.
  - WhatsApp inbound processing must ignore stale webhook updates older than a configurable window (`WA_INBOUND_MAX_AGE_SECONDS`, default `3600`, `0` disables).
  - `in_reply_to` extraction must use actual context ids (`reply_to_message.message_id` / reaction target id), never `message_id_to_reply` for text messages.
  - Inbound idempotency lookup must only match prior inbound rows (`from_me=False`), not outbound rows.
- Reason:
  - Meta/PyWA webhook updates can contain business-authored or delayed/replayed events; treating them as inbound creates false transcript turns and triggers hallucinated follow-up replies.
  - PyWA `message_id_to_reply` is not the replied message id for normal text events; using it breaks deterministic contact resolution by replied outbound id.
  - Duplicate detection against both directions can misclassify outbound rows as inbound duplicates.
- Enforcement:
  - updated `bot/providers.py`:
    - added `_is_self_authored_update(...)` based on sender id vs webhook metadata/business number normalization,
    - added `_is_stale_update(...)` with `WA_INBOUND_MAX_AGE_SECONDS`,
    - fixed reply-context extraction to use `reply_to_message.message_id`,
    - propagated callback reply context into `in_reply_to`.
  - updated `backend/database.py`:
    - `Message.get_by_external_id(...)` accepts optional `from_me` filter.
  - updated `backend/endpoints/messages.py`:
    - inbound duplicate lookup now enforces `from_me=False`.
  - updated `bot/tests/test_whatsapp_inbound_provider.py`:
    - added coverage for self-authored filtering, stale filtering, callback reply context, and inbound age parser.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/main.py`
  - reused pattern: inbound guardrail layer before agent processing (skip self-authored events and stale webhook messages).
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
- Affected components:
  - `bot/providers.py`
  - `bot/tests/test_whatsapp_inbound_provider.py`
  - `backend/database.py`
  - `backend/endpoints/messages.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Local WhatsApp Outbound Random Delay in Bot Runtime (2026-03-05)
- Decision/rule:
  - Outbound WhatsApp sends in `bot/` must use local in-memory randomized per-message delay before provider dispatch.
  - Delay range is fixed in code to `10s..180s` (no env toggle/override).
  - Delay applies to both WhatsApp intro templates and regular text outbound sends.
  - Backend contracts/endpoints remain unchanged; delay enforcement is bot-local only.
- Reason:
  - introduce human-like pacing for outbound WhatsApp without coupling timing policy to backend persistence contracts.
- Enforcement:
  - updated `bot/utils.py`:
    - added WhatsApp delay constants and key prefix (`wa-message:<message_id>`),
    - added WhatsApp delay state (`lock + due_by_key`) parallel to email delay state,
    - added `sample/build/prune/clear/get_wait/enforce` helpers for WhatsApp delay,
    - wired `dispatch_pending_messages(...)` to defer WhatsApp/phone dispatch with `error="whatsapp_delay_not_elapsed"` until delay elapses,
    - clears WhatsApp delay key only after successful delivery.
  - updated tests:
    - `bot/tests/test_email_dispatch_spacing.py`:
      - added `test_enforce_whatsapp_dispatch_spacing_requires_elapsed_delay`,
      - mocked WhatsApp delay enforcement in existing mixed email/whatsapp dispatch test.
    - `bot/tests/test_whatsapp_template_dispatch.py`:
      - mocked WhatsApp delay enforcement in existing dispatch test,
      - added `test_dispatch_pending_messages_defers_whatsapp_until_delay_elapsed`,
      - added `test_dispatch_pending_messages_applies_delay_to_intro_template_and_text`.
- Pattern reuse log:
  - source repo: current repo (`konecta-auditor`)
  - source file: `bot/utils.py`
  - reused pattern: existing email dispatch in-memory delay scheduler (`delay_key` + `monotonic` + prune/clear lifecycle) adapted 1:1 for WhatsApp channel.
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no closer sibling implementation for per-message outbound random delay in a stateless pending-dispatch bot loop.
- Affected components:
  - `bot/utils.py`
  - `bot/tests/test_email_dispatch_spacing.py`
  - `bot/tests/test_whatsapp_template_dispatch.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-03-04

### Stage 4 Adapter Override + WhatsApp App-ID Contract Fix (2026-03-04)
- Decision/rule:
  - Stage 4 must force `JSONAdapter` at call time (`dspy.context(adapter=JSONAdapter())`) when generating `ReportDocumentModel`.
  - Keep global `BAMLAdapter` configuration for other stages, but never rely on it for Stage 4 model emission.
  - WhatsApp provider must map `WA_APP_ID` -> `app_id`; never pass `WA_PHONE_ID` as `app_id`.
  - If WhatsApp client init fails (including Meta OAuthException 101 or callback registration failure), provider must degrade to disabled state instead of crashing bot startup.
- Reason:
  - `BAMLAdapter` raises false recursive-model errors on Stage 4 output schema (`ReportDocumentModel` has repeated nested model references), which blocks full-audit generation.
  - Passing `WA_PHONE_ID` as `app_id` produces invalid Meta app validation behavior and cascades into callback registration errors.
  - Bot runtime should remain resilient when external Meta credentials/state are temporarily invalid.
- Enforcement:
  - updated `backend/ai/stage4_report_to_html.py`:
    - import `JSONAdapter`,
    - instantiate per-program adapter,
    - wrap Stage 4 `generator.acall(...)` inside adapter-scoped DSPy context.
  - updated `bot/providers.py`:
    - read `WA_APP_ID`,
    - parse `WA_APP_ID` as optional integer and pass to PyWA `app_id`,
    - add safe parser for `WA_WEBHOOK_CHALLENGE_DELAY`,
    - catch init exceptions and keep provider disabled with explicit logs for OAuthException 101.
  - added/updated bot tests in `bot/tests/test_whatsapp_inbound_provider.py`:
    - env parsing helpers,
    - provider `configured` behavior tied to initialized PyWA client,
    - OAuthException 101 detection,
    - graceful disable path when PyWA init raises.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: map Meta credentials explicitly (`WA_APP_ID` as `app_id`) instead of inferring app identity from phone metadata.
  - source repos searched for adapter handling: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no sibling-level per-stage adapter override pattern found; Stage 4 JSONAdapter override implemented directly as targeted fix.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `bot/providers.py`
  - `bot/tests/test_whatsapp_inbound_provider.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### WhatsApp Inbound Disambiguation + Recipient Normalization + CEO Email Fallback (2026-03-04)
- Decision/rule:
  - WhatsApp inbound resolution must use replied outbound message id (`in_reply_to`) when available before falling back to phone-value matching.
  - WhatsApp outbound destination must be normalized to digits-only before sending templates/text to Cloud API (supports stored values like `+54...` or `https://wa.me/...`).
  - Scan pipeline must persist only the `ceo_email` chosen by Stage 1; no fallback candidate selection from discovered contacts.
  - Audit delivery endpoint must keep `company.ceo_email` unchanged, and when it is empty route delivery to operator fallback recipient `facundogoiriz@gmail.com`.
  - `missing_ceo_email` delivery blocks must be recoverable automatically once a valid CEO email is available.
  - WhatsApp contact resolution should avoid global active-contact scans; resolve by provider IDs/normalized keys first, then apply eligibility filters.
- Reason:
  - same phone number reused across multiple active companies produced ambiguous contact resolution (`409`) and inbound replies were ignored.
  - raw WhatsApp contact values stored as URL/format variants could fail outbound sends for some contacts while others worked.
  - missing `ceo_email` blocked full audit delivery; product decision changed to route these cases to operator inbox for manual forwarding.
- Enforcement:
  - updated `bot/providers.py`:
    - extended `WhatsAppInboundEvent` with `in_reply_to`,
    - extracted reply context id from inbound messages,
    - normalized outbound recipient with `_normalize_outbound_recipient(...)`.
  - updated `bot/utils.py`:
    - forwards `in_reply_to` into backend contact resolution and inbound registration.
  - updated `backend/database.py`:
    - added `Message.list_by_external_id(...)` helper for provider-id based matching.
  - updated `backend/endpoints/messages.py`:
    - added `resolve_whatsapp_contact_by_replied_message(...)`,
    - `resolve_whatsapp_contact(...)` now resolves by `in_reply_to` first, then phone.
    - simplified to use targeted lookups (`Message.list_by_external_id(...)`, `Contact.get_by_id(...)`, `Contact.list_by_normalized_value(...)`) instead of scanning all active contacts.
  - updated `backend/endpoints/companies.py`:
    - scan flow now saves Stage 1 `ceo_email` as-is (or `None`) without fallback inference,
    - audit-delivery ceo-email endpoint now returns operator fallback when DB `ceo_email` is empty and does not persist fallback into company row.
  - updated `backend/database.py`:
    - `Company.update(update_ceo_email=True)` now clears `missing_ceo_email` blocked state when a valid email is saved.
    - `Company.mark_ceo_delivery_delivered(...)` now clears blocked state on successful send.
  - updated `bot/utils.py`:
    - audit-delivery poll loop no longer permanently skips `missing_ceo_email` blocked rows (it still skips other blocked reasons).
  - tests:
    - extended `bot/tests/test_whatsapp_inbound_provider.py` for reply-context extraction and recipient normalization.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: normalize outbound WhatsApp recipient values before provider send and use provider message ids as deterministic correlation keys.
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/main.py`
  - reused pattern: message-id-centric inbound handling with direct id checks over broad contact scans.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/messages.py`
  - `backend/endpoints/companies.py`
  - `bot/providers.py`
  - `bot/utils.py`
  - `bot/tests/test_whatsapp_inbound_provider.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-03-03

### Configurable Audit Window Per Company (2026-03-03)
- Decision/rule:
  - Full-audit trigger window is now company-configurable via `report_window_hours` instead of fixed 48h business-hour logic.
  - `POST /api/companies/scan` must accept `report_window_hours` (default `24`) and persist it on company creation.
  - Bot audit loop must derive generation timing from backend company metadata (`created_at`, `report_window_hours`) rather than fixed constants.
- Reason:
  - allow operators to set the audit timeline per company at scan time and remove weekend/business-hour special cases.
- Enforcement:
  - added `Company.report_window_hours` plus deterministic normalization in `backend/database.py`.
  - applied one-off dev SQLite migration command:
    - `sqlite3 data/database.sqlite "PRAGMA table_info(companies);" | rg -q "report_window_hours" || sqlite3 data/database.sqlite "ALTER TABLE companies ADD COLUMN report_window_hours INTEGER NOT NULL DEFAULT 24;"`
  - extended backend contracts:
    - `ScanCompanyRequest.report_window_hours`,
    - `CompanySummary/Detail.report_window_hours`,
    - `UpdateCompanyRequest/Response.report_window_hours`,
    - audit poll-state payload includes `report_window_hours`.
  - removed business-day elapsed logic from audit eligibility and replaced with pure UTC elapsed-hours check against `company.report_window_hours`.
  - bot now computes trigger readiness from poll-state metadata (`created_at + report_window_hours`) through `should_trigger_full_audit(...)`.
  - CEO delivery email body now interpolates configured hours instead of hardcoded `48`.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/scheduler.py`
  - reused pattern: stateless poll iteration that decides execution only from persisted backend timestamps/metadata.
  - source repo: `/Users/fgoiriz/private/repos/outbound`
  - source file: `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
  - reused pattern: plain-JS modal form -> API payload -> optimistic local list update.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `backend/audit_delivery_email_content.py`
  - `bot/utils.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-03-02

### Scan Form Automation Flags + Company-Level Toggle Persistence (2026-03-02)
- Decision/rule:
  - `POST /api/companies/scan` must accept initial automation configuration and persist it at company creation time:
    - `conversation_automation_enabled: bool`
    - `ceo_delivery_enabled: bool`
  - The scan modal in frontend must expose both toggles so operators configure automation upfront, not only after creation.
  - Company view keeps live on/off toggles (via `PUT /api/companies/{company_id}`) as the mutable source of truth after scan.
- Reason:
  - remove manual post-scan configuration friction and ensure automation state is explicit from the first persisted company record.
- Enforcement:
  - extended `ScanCompanyRequest` contract with both flags and wired them into `Company.create(...)` in `scan_company`.
  - added `createConversationAutomationToggle` and `createCeoDeliveryToggle` to scan modal UI and wired payload serialization in `handleCreateProject`.
  - optimistic frontend company rows during scan now reflect selected automation values instead of hardcoded `false`.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/outbound`
  - source file: `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
  - reused pattern: plain-JS form state -> request payload -> optimistic local state update without framework store.
- Affected components:
  - `backend/endpoints/companies.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`

### CEO Audit Delivery Automation + Single CEO Email Contract (2026-03-02)
- Decision/rule:
  - Company-level automation split is now explicit:
    - `conversation_automation_enabled` controls conversation loop authorization.
    - `ceo_delivery_enabled` controls automatic audit PDF delivery flow.
  - Stage 1 leadership email contract changed from list to single value:
    - `founder_ceo_emails: list[str] | null` -> `ceo_email: str | null`.
    - Selection priority in extraction instructions: `CEO > Founder > Co-founder`.
  - Audit delivery flow is backend-state-driven and bot-stateless:
    - bot polls backend state,
    - triggers full audit generation when eligible,
    - delivers PDF once,
    - stores delivery thread metadata,
    - persists CEO replies by thread id.
  - Blocking behavior is terminal by design:
    - missing `ceo_email` at delivery time -> backend `ceo_delivery_blocked_reason` set,
    - no auto-unblock path.
- Reason:
  - enforce minimal, explicit state machine for audit generation + CEO delivery while keeping bot stateless.
  - simplify leadership recipient handling to one deterministic target email and reduce orchestration complexity.
- Enforcement:
  - `companies` schema now includes:
    - `ceo_email`,
    - `conversation_automation_enabled`,
    - `ceo_delivery_enabled`,
    - `ceo_delivery_sent_at/thread_id/external_id/rfc_message_id`,
    - `ceo_delivery_blocked_reason/blocked_at`.
  - new table `ceo_audit_replies` persists inbound CEO replies with idempotency on `gmail_message_id`.
  - new backend endpoints under `/api/companies/.../audit-delivery/...` plus:
    - `POST /api/audit-delivery/replies/inbound`
    - `GET /api/audit-delivery/tracked-senders`
  - bot runtime adds 60s audit-delivery polling loop and Gmail inbound fallback path for CEO-thread replies.
  - Gmail provider now supports explicit subject + attachments for audit PDF email.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/scheduler.py`
  - reused pattern: explicit idempotent polling loop that reads state, performs one step, and persists transition in backend.
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
  - reused pattern: provider id-based deduplication (`gmail_message_id`) for inbound idempotency.
  - source repo: `/Users/fgoiriz/private/repos/outbound`
  - source file: `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
  - reused pattern: simple polling/control toggles in plain JS with deterministic state updates.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/messages.py`
  - `bot/providers.py`
  - `bot/utils.py`
  - `bot/main.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`

## 2026-03-01

### Home Filters: Persisted Industry + Company Size + Button-Only UI Controls (2026-03-01)
- Decision/rule: Home filtering must support `language` (`en|es|all`), `industry` (dropdown from currently existing company values), and `company_size` (`small|medium|large|all`) without free-text inputs for these category filters.
- Reason: enable deterministic portfolio segmentation on the home grid using Stage 1 discovery tags already present in DB and remove manual typing friction for category filtering.
- Enforcement:
  - Persisted + normalized company tags in backend domain model:
    - added `Company.company_size` and `Company.industry` in `backend/database.py`,
    - added deterministic normalizers `normalize_company_size` and `normalize_company_industry`,
    - wired `Company.create/update` to normalize and persist these fields.
  - Scan glue now stores Stage 1 tags on company update:
    - `scan_company_core` passes `discovery.industry` and `discovery.company_size` into `Company.update(...)`.
  - Company API payloads now expose tags for home rendering/filtering:
    - `CompanySummary` includes `industry` and `company_size`,
    - list/detail responses include both fields.
  - Frontend home now renders category filters and applies combined filtering:
    - button chips for `language` and `company_size`,
    - dynamic industry dropdown options derived from current `state.projects`,
    - `getFilteredProjects()` now composes search + language + industry + company_size predicates.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/outbound`
  - source file: `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
  - reused pattern: plain JS state-driven render loop with event-bound filter controls (no framework state library), adapted to multi-filter home grid composition.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Stage 4 Typed Signature Cleanup: No Repair Signature, No JSON String Output (2026-03-01)
- Decision/rule: Stage 4 DSPy contract is now single-signature and fully typed: `report: CompanyReport -> pdf_model: ReportDocumentModel`.
- Reason: align Stage 4 with repository DSPy pattern (typed Pydantic fields in signatures) and remove brittle dual-signature JSON-string repair flow.
- Enforcement:
  - Removed `RepairPdfModelJsonSignature` and removed `valid_json: str` output path.
  - Replaced Stage 4 output field `pdf_model_json: str` with typed `pdf_model: ReportDocumentModel`.
  - Replaced Stage 4 input field `report_json: str` with typed `report: CompanyReport`.
  - Updated integration glue to call `stage4.aforward(report=report)` directly.
  - Tweaked stage instructions to reference typed `pdf_model` output instead of raw JSON-only wording.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/konecta-auditor`
  - source files:
    - `backend/ai/stage1_url_to_contacts.py`
    - `backend/ai/stage3_company_to_report.py`
  - reused pattern: use typed Pydantic fields directly in DSPy signatures and keep `aforward` as thin orchestration.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `backend/endpoints/companies.py`
  - `HOW_TO_DEVELOP.md`
  - `backend/ai/stage2_contact_to_conversation.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Stage 4 Simplification: Pure LLM Mapping (No Heuristic Code) (2026-03-01)
- Decision/rule: Stage 4 must not implement semantic transformation logic in Python (no regex parsers, no keyword heuristics, no hardcoded scoring thresholds, no manual callout/status/risk rule tables). Stage 4 now acts as a strict LLM-first transformer: `report_json -> ReportDocumentModel`.
- Reason: keep transformation logic centralized in the signature instructions and avoid brittle behavior drift from hardcoded rule tuning.
- Enforcement:
  - Replaced Stage 4 implementation with a minimal `ReportPdfModelProgram` that contains:
    - one signature with comprehensive transformation instructions,
    - one `aforward(report_json)` method,
    - strict `ReportDocumentModel` validation (`model_validate_json`) and hard failure on invalid model output.
  - Removed Python-side semantic mapping helpers for:
    - contact metadata classification,
    - message sanitization heuristics,
    - status/risk threshold scoring,
    - callout keyword patterning,
    - fallback editorial synthesis.
  - Updated endpoint glue to call `stage4.aforward(report_json=...)` without passing language separately.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no direct sibling pattern for this exact Stage 4 pure-LLM report-json -> Pydantic transformation; implemented directly in `backend/ai/stage4_report_to_html.py`.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `backend/endpoints/companies.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Stage 4 Contract Pivot: Report JSON -> PDF Pydantic Model (2026-03-01)
- Decision/rule: Stage 4 no longer renders HTML. Stage 4 now transforms Stage 3 `CompanyReport` JSON into a render-ready PDF content model (`ReportDocumentModel`) and persists that model JSON on `companies.report_pdf_model_json`.
- Reason: keep rendering deterministic/programmatic and avoid storing expensive binary artifacts in DB; persist only structured render data so PDF can be regenerated cheaply at any time.
- Enforcement:
  - Replaced `backend/ai/stage4_report_to_html.py` behavior with `ReportPdfModelProgram` (`Program.aforward`) that returns `ReportDocumentModel`.
  - Stage 4 now combines:
    - deterministic mapping (contacts/threads/status/timestamps/message sanitization),
    - constrained editorial planning via DSPy signature (`hero`, per-thread diagnostics, callouts, quote, 2-sentence conclusion),
    - strict Pydantic validation + deterministic fallback plan when LLM JSON is invalid.
  - Added company persistence support for PDF model JSON:
    - `Company.report_pdf_model_json`,
    - `Company.update_report_pdf_model(...)`,
    - `Company.get_report_pdf_model(...)`.
  - Applied one-off SQLite CLI change in local dev DB: `ALTER TABLE companies ADD COLUMN report_pdf_model_json TEXT`.
  - Updated company endpoints to build/store PDF model artifacts from report snapshot and expose `/artifact-pdf-model`.
  - Added Stage 4 module `__main__` demo path:
    - load Konecta report snapshot from DB,
    - run Stage 4 to produce `ReportDocumentModel`,
    - persist model JSON in DB,
    - render PDF through `backend.report_pdf.build_vector_pdf(...)`.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no direct reusable sibling pattern found for this exact report-json -> PDF-model stage contract; implemented locally.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `backend/endpoints/companies.py`
  - `backend/database.py`
  - `backend/ai/__init__.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-02-28

### Stage 1 Industry + Company Size Contract Extension (2026-02-28)
- Decision/rule: Stage 1 discovery output now includes `industry` and `company_size` as structured tags for downstream filtering.
- Reason: enable consistent frontend/company filtering by standardized industry label and coarse size bucket derived from website-only evidence.
- Enforcement:
  - Extended `ContactDiscoveryResult` with:
    - `industry: str` (default `unknown`)
    - `company_size: str` (allowed: `small|medium|large|unknown`, default `unknown`)
  - Extended Stage 1 `ContactDiscoverySignature` output fields with `industry` and `company_size`.
  - Added signature instructions to normalize industry using ISIC Rev.4 naming conventions and included canonical-label examples for common dataset segments (real estate, legal/accounting, insurance, software, marketing, logistics, etc.).
  - Added explicit size-bucket guidance in signature instructions:
    - `small` = 1-10
    - `medium` = 11-20
    - `large` = 20+
    - `unknown` when evidence is insufficient
  - Kept runtime glue unchanged (no DB or endpoint persistence changes in this iteration).
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no reusable sibling implementation for standardized industry taxonomy tagging was found; implemented directly in Stage 1 contract.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-02-27

### Stage 1 Founder/CEO Email Contract + Company Persistence (2026-02-27)
- Decision/rule: Stage 1 discovery now extracts nullable `founder_ceo_emails: list[str] | null` from website evidence, and company persistence stores this nullable list on `companies` for downstream stages/endpoints.
- Reason: founder/CEO direct emails are high-value audit context and must be preserved as structured data instead of being lost inside unstructured markdown.
- Enforcement:
  - Extended `ContactDiscoveryResult` and Stage 1 Signature output with `founder_ceo_emails` while keeping `UrlToContactsProgram.aforward` orchestration unchanged.
  - Added nullable `Company.founder_ceo_emails` (JSON list) and passed Stage 1 output through `Company.create/update` without extra normalization.
  - Wired `scan_company_core` to persist `discovery.founder_ceo_emails`.
  - Exposed field in company detail and update endpoint contracts.
  - Applied one-off SQLite CLI migration in terminal (`ALTER TABLE companies ADD COLUMN founder_ceo_emails TEXT`) and kept `init_db()` free of migration guards.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/scripts/migrate_templates.py`
  - reused pattern: keep schema evolution as explicit terminal-side SQLite commands outside backend runtime code.
  - source repo: `/Users/fgoiriz/private/repos/bogan`
  - source file: `/Users/fgoiriz/private/repos/bogan/src/ai/stock_analyzer.py`
  - reused pattern: keep semantic extraction as typed DSPy `OutputField` contract and keep `Program.aforward` as a simple composition recipe.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `README.md`
  - `HOW_TO_DEVELOP.md`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Stage 1 Crawl-First Markdown Contract + Deep-Research Removal (2026-02-27)
- Decision/rule: Stage 1 now follows a fixed recipe: normalize URL -> crawl website markdown -> extract `company_name`, `company_info`, `language`, and `contacts` from that markdown. `website_markdown` in `ContactDiscoveryResult` is sourced directly from crawl output, not from a Signature output field.
- Reason: simplify Stage 1 contract and remove redundant search/HTML evidence assembly paths that increased complexity without being required by the current flow.
- Enforcement:
  - Rewrote `UrlToContactsProgram` to keep only three core steps (`_normalize_url`, `crawl_website_markdown`, `extract_contacts`) and a lean `aforward(url)` orchestration.
  - Updated Stage 1 Signature to consume `website_markdown` as input and removed `website_markdown` as an output field.
  - Removed scan deep-research wiring end to end (`ScanCompanyRequest.deep_research_enabled`, `scan_company_core(..., deep_research_enabled)`, and frontend create-scan toggle/payload field).
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/simple-avatar`
  - source file: `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/api/[...path]/route.ts`
  - reused pattern: deterministic URL normalization by adding `https://` when scheme is missing.
  - source repo: `/Users/fgoiriz/private/repos/bogan`
  - source file: `/Users/fgoiriz/private/repos/bogan/src/ai/stock_analyzer.py`
  - reused pattern: keep `Program.aforward` as a short recipe over one typed DSPy extraction call plus deterministic result mapping.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/endpoints/companies.py`
  - `frontend/static/js/app.js`
  - `frontend/index.html`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-02-26

### WhatsApp PyWA Handling Aligned with Inmobot (2026-02-26)
- Decision/rule: WhatsApp webhook and callback registration follow inmobot: single `WA_CALLBACK_URL` passed into PyWA at init; no retry loop, no probe, no alias routes. Callback registration is PyWA’s one-shot when `WA_CALLBACK_URL` is set; if unset, log warning and skip.
- Reason: simplify bot runtime and avoid maintainability cost of custom registration loop/probe/aliases; inmobot pattern is sufficient and callback URL is configured manually or by deployer.
- Enforcement:
  - `WhatsAppProvider` passes `callback_url=self.callback_url` (from env or None) and `app_id`/`app_secret`/`verify_token` into `WhatsApp()` like inmobot `wa.py`; removed `webhook_endpoint`, `callback_url=None`, and all custom registration logic.
  - Removed: `ensure_callback_registration_loop`, `_probe_callback_url`, `_callback_registration_prerequisites_ready`, `_resolve_webhook_endpoint`, `_load_webhook_aliases`, `_register_webhook_aliases`, `_normalize_endpoint_path`; removed env vars `WA_CALLBACK_REGISTRATION_RETRY_SECONDS`, `WA_CALLBACK_PROBE_TIMEOUT_SECONDS`, `WA_WEBHOOK_CHALLENGE_DELAY_SECONDS`, `WA_WEBHOOK_FIELDS`, `WA_WEBHOOK_ENDPOINT_ALIASES`.
  - Inbound capture unchanged: `on_message()`, `on_callback_button()`, `on_callback_selection()` with typed `WhatsAppInboundEvent` and dispatch to backend.
  - Bot lifespan no longer starts a callback-registration task; only worker loop runs.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: init PyWA with `server`, `callback_url` (optional), `verify_token`, `app_id`, `app_secret`, `session`, `webhook_challenge_delay`; no custom loop or probe.
- Affected components:
  - `bot/providers.py`
  - `bot/main.py`
  - `bot/tests/test_whatsapp_inbound_provider.py` (removed test for deleted `_resolve_webhook_endpoint`)
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Server Deploy: Traefik + PyWA Webhook (2026-02-26)
- Decision/rule: production deploy uses Traefik (docker-compose) like inmobot; `/webhook` goes to bot (PyWA inbound), everything else to backend. `WA_CALLBACK_URL` must be the public URL where Meta can reach the webhook (HTTPS in production).
- Enforcement:
  - `docker-compose.yml`: service `traefik` (v3.3, port 80, Docker provider); `backend` and `bot` have Traefik labels. Router `bot` has `PathPrefix(\`/webhook\`)` and priority 10; router `backend` has `PathPrefix(\`/\`)` and priority 1 so `/webhook` hits the bot.
  - PyWA mounts the path from `WA_CALLBACK_URL` (e.g. `https://dominio.com/webhook/wa` → app route `/webhook/wa`). Set in `.env`: `WA_CALLBACK_URL=https://tu-dominio.com/webhook/wa` (or the host/path you expose). For HTTPS, put Traefik behind a reverse proxy (e.g. Cloudflare) or add Traefik entrypoint websecure with cert resolver.
- Pattern reuse: inmobot `docker-compose.yml` (Traefik + backend labels); konecta adds a second router for the bot so webhook and API share the same host.

### Stage 2 First Email Draft Contract Owns Subject (2026-02-26)
- Decision/rule: first outbound email subject must be generated by Stage 2 `FirstMessageProgram` as part of the typed output contract (`first_message`, `subject`); backend endpoint glue must not infer subject with regex/heuristics/trimming logic.
- Reason: subject generation is semantic content and belongs to the LLM stage contract, not to deterministic endpoint post-processing.
- Enforcement:
  - Added `FirstMessageDraft` model in Stage 2 and changed `FirstMessageProgram.aforward` to return structured output with `subject`.
  - Persisted `email_subject` on `Contact` and wired first-message seeding flow to save model-returned subject.
  - Removed manual subject-derivation logic from company endpoint glue; Gmail compose link now uses persisted `contact.email_subject`.
  - Added SQLite bootstrap column guard in `init_db()` for `contacts.email_subject` (no migration file).
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/ai.py`
  - reused pattern: keep semantic text artifacts as explicit DSPy `OutputField` contract fields and pass typed stage outputs through thin endpoint glue.
- Affected components:
  - `backend/ai/stage2_contact_to_conversation.py`
  - `backend/endpoints/companies.py`
  - `backend/database.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### WhatsApp Manual Name Assignment Must Exclude Already Used Names (2026-02-26)
- Decision/rule: when seeding first outbound WhatsApp messages, sender-name selection must be random and must exclude names already assigned to existing WhatsApp contacts in the same company while the pool has available options.
- Reason: manual contact creation was seeding with only the new contact list, causing repeated sender names (e.g., repeated "Sebastian") across contacts in one company.
- Enforcement:
  - Updated WhatsApp intro payload builder to inspect existing first outbound messages per contact, extract already-used sender names, and assign names for new contacts from the remaining pool.
  - Manual contact flow now seeds initial outbound using the full active company contact set (not only the newly created contact), so assignment context includes prior contacts.
  - Pending-delivery template payload now derives `whatsapp_template_client_name` from persisted first outbound text for that specific message, avoiding recomputation drift.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: provider template dispatch must be grounded on persisted message/template content to keep outbound params and stored transcript in sync.
- Affected components:
  - `backend/templates.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/messages.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Manual Contact Endpoint Must Auto-Seed First Outbound (2026-02-26)
- Decision/rule: `POST /api/companies/{company_id}/contacts` must auto-seed the first outbound message in the same endpoint flow for manual `email` and `whatsapp` contacts.
- Reason: manual-contact onboarding must behave consistently with discovery onboarding, so a newly added reachable contact starts with an initial outbound without requiring extra endpoint calls.
- Enforcement:
  - Added inline call from `create_manual_contact` to `seed_initial_outbound_messages_for_company(refreshed_company, active_contacts)`.
  - Kept channel behavior unified through the existing seeding orchestrator:
    - email -> Stage 2 first-message generation,
    - whatsapp -> intro template first outbound.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: keep first outbound dispatch/seed tied to contact onboarding path instead of requiring an extra manual trigger endpoint.
- Affected components:
  - `backend/endpoints/companies.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Stage 1 Predict-Only Extraction + gpt_5_2 Retry (2026-02-26)
- Decision/rule: Stage 1 contact extraction must use `dspy.Predict` (not `ChainOfThought`) and avoid output-shape instructions that can conflict with adapter expectations; on extraction failure, retry once with `gpt_5_2`.
- Reason: `ChainOfThought` introduced `reasoning/result` envelope expectations while the model returned direct structured fields, causing `AdapterParseError` and scan task failure.
- Enforcement:
  - Switched Stage 1 extractor from `dspy.ChainOfThought(ContactDiscoverySignature)` to `dspy.Predict(ContactDiscoverySignature)`.
  - Removed explicit output-contract instruction that told the model how to format output container fields.
  - Added one retry path in `extract_contacts`: first attempt on default configured LM, second attempt under `dspy.context(lm=gpt_5_2)`.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/ai.py`
  - reused pattern: use `dspy.Predict` for strict single-step structured generation where no explicit reasoning envelope is needed.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### Scan-Named Discovery Endpoint + Legacy First-Message Removal (2026-02-26)
- Decision/rule: discovery kickoff action is explicitly named `scan` via `POST /api/companies/scan`; dedicated first-message endpoints and scan alias compatibility route were removed.
- Reason: first outbound seeding already happens inside the scan task, so separate first-message trigger endpoints and compatibility aliases add unnecessary legacy surface.
- Enforcement:
  - Kept only `POST /api/companies/scan` as scan kickoff route.
  - Removed `POST /api/companies` alias route.
  - Removed legacy first-message trigger routes:
    - `POST /api/companies/{company_id}/first-messages`
    - `POST /api/companies/{company_id}/contacts/{contact_id}/first-message`
  - Updated frontend creation flow and labels to use scan naming and `/api/companies/scan`.
  - Updated docs/skills (`README.md`, `HOW_TO_DEVELOP.md`, `AGENTS.md`, endpoint/docker validation skills) to describe scan-driven first outbound behavior.
- Affected components:
  - `backend/endpoints/companies.py`
  - `frontend/static/js/app.js`
  - `frontend/index.html`
  - `README.md`
  - `HOW_TO_DEVELOP.md`
  - `AGENTS.md`
  - `.cursor/skills/konecta-auditor-endpoint-e2e/SKILL.md`
  - `.cursor/skills/konecta-auditor-docker-prod-validation/SKILL.md`

### Discovery-Driven Initial Outbound + Backend-Driven WhatsApp Template Payload (2026-02-26)
- Decision/rule: first outbound seeding now happens inside company discovery completion (`POST /api/companies/scan` task path), not from frontend. Email first outbound remains AI-generated; WhatsApp first outbound is template-first with backend-resolved template payload.
- Reason: WhatsApp first contact must be delivered via approved template, so frontend-triggered "generate first message" flows created wrong responsibility boundaries and inconsistent provider behavior.
- Enforcement:
  - Added deterministic backend intro-template resolution in `backend/templates.py` using v2 templates (`konecta_intro_es_v2`, `konecta_intro_en_v2`), language-aware name pools (10 ES + 10 EN), and per-company no-repeat-while-possible assignment.
  - `scan_company_core` now seeds first outbound after contact discovery:
    - email contacts: existing Stage 2 first-message program,
    - whatsapp contacts: persisted rendered template text as first outbound message.
  - Manual contact creation no longer auto-queues first-message generation.
  - Dedicated first-message endpoints were removed from backend.
  - Pending delivery payload now includes optional `whatsapp_template_*` fields for first outbound WhatsApp rows.
  - Bot dispatch now consumes backend template payload (`template_name`, `template_language`, `client_name`, `company_url`) when delivering first WhatsApp outbound.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file: `/Users/fgoiriz/private/repos/inmobot/backend/wa.py`
  - reused pattern: explicit provider template send contract (`template_name` + language + variables) with deterministic rendered-text consistency and provider-side dispatch using structured params.
- Affected components:
  - `backend/templates.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/messages.py`
  - `bot/providers.py`
  - `bot/utils.py`
  - `frontend/static/js/app.js`
  - `bot/tests/test_whatsapp_template_dispatch.py`

## 2026-02-24

### Stage 1 Full HTML Evidence + `website_markdown` Contract (2026-02-24)
- Decision/rule: Stage 1 no longer regex-parses HTML snippets for extraction; it now sends full fetched page HTML directly to the LLM and returns an explicit `website_markdown` field.
- Reason: preserve broader website evidence for contact + company-context extraction and let the same extraction Signature generate normalized markdown output from that evidence.
- Enforcement:
  - Removed regex-based contact snippet extraction and same-host script-regex scraping from Stage 1.
  - Removed runtime HTML-to-markdown parsing; no deterministic parser is used for `website_markdown`.
  - Added `website_markdown: str` to `ContactDiscoveryResult`.
  - Updated Stage 1 Signature instructions so `website_markdown` is produced by the LLM from raw HTML evidence input.
  - Added `website_markdown` persistence in `Company` and wired update path from `create_company_core`.
  - Exposed `website_markdown` in company detail/update endpoint contracts.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed: `/Users/fgoiriz/private/repos/simple-avatar/backend/utils.py`, `/Users/fgoiriz/private/repos/bogan/src/utils.py`, `/Users/fgoiriz/private/repos/outbound/backend/tools.py`
  - reused pattern: keep async HTTP collection simple (`httpx.AsyncClient` + `raise_for_status`) and keep orchestration legible with explicit `asyncio.gather` for independent I/O tasks.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/database.py`
  - `backend/endpoints/companies.py`

### Stage 1 Language Capture + Stage 2 Language Propagation Contract (2026-02-24)
- Decision/rule: Stage 1 discovery output now includes optional `language`; company persistence stores optional `language`; Stage 2 first-message and reply generation receive optional `target_language` and pass it directly to DSPy.
- Reason: keep outbound conversations aligned with the dominant company/contact language while preserving null-safe behavior when language is unknown.
- Enforcement:
  - Added `language: str | None` to `ContactDiscoveryResult`.
  - Updated Stage 1 extractor instructions with explicit language inference policy (set when clear, otherwise null).
  - Added `language` column/field in `Company` model and wired update path from `create_company_core`.
  - Added `target_language: str | None` input to Stage 2 signatures (`FirstMessageSignature`, `ReplyGeneratorSignature`) and passed through `aforward` orchestration without forced fallback.
  - Updated company/message endpoints to propagate `company.language` into first message and next-reply generation.
- Pattern reuse log:
  - source repos searched: `/Users/fgoiriz/private/repos/simple-avatar`, `/Users/fgoiriz/private/repos/bogan`, `/Users/fgoiriz/private/repos/inmobot`, `/Users/fgoiriz/private/repos/outbound`
  - result: no equivalent reusable language-propagation pattern found; applied direct minimal extension of existing stage contracts.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/ai/stage2_contact_to_conversation.py`
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/messages.py`

## 2026-02-23

### Stage 2 Meeting Gate + Conflict Priority Hardening (2026-02-23)
- Decision/rule: when prompt goals collide, Stage 2 must prioritize diagnostic evidence over meeting progression; live meetings are late-stage exceptions only.
- Reason: DCLATAM transcript forensics showed repeated early scheduling drift (call/agenda/invite chatter) that reduced signal density in buyer turns.
- Enforcement:
  - Added `objective_conflict_resolution` priority stack so "next step" defaults to async evidence, not scheduling.
  - Added `meeting_gate_protocol` with explicit acceptance conditions (late turn + written proof already provided + unresolved high-impact unknown).
  - Added `scheduling_minimization_when_unavoidable`, `evidence_before_coordination`, and `anti_drift_examples`.
  - Reinforced first-turn rule with `opening_priority_resolution` to keep opening progression evidence-first.
- Affected components:
  - `backend/ai/stage2_contact_to_conversation.py`

### Stage 2 Meta-Analysis Objectives Embedded in Signature Instructions (2026-02-23)
- Decision/rule: Stage 2 keeps its existing runtime contract and injects meta-analysis goals directly in signature docstrings (prompt instructions), not via new inputs/config paths.
- Reason: preserve simple stage interfaces while improving diagnostic behavior quality (coverage, progression, anti-loop control) through prompt-level guidance.
- Enforcement:
  - Expanded `ReplyGeneratorSignature` instructions with:
    - multi-dimension coverage targets,
    - anti-repetition/anti-loop constraints,
    - progression gating (reduce friction when seller performs well),
    - explicit defer/exit behavior for evasive or hostile seller patterns.
  - Expanded `FirstMessageSignature` opening policy to maximize early diagnostic value with one focused ask + one friction cue.
  - Removed additional Stage 2 complexity paths for this behavior (no extra input fields or env-driven meta-objective wiring).
- Affected components:
  - `backend/ai/stage2_contact_to_conversation.py`

### Stage 2 Long-Form Meta Context Expansion (2026-02-23)
- Decision/rule: Stage 2 signature instructions now include explicit long-form context about product intent, end-goal chain, and why each buyer message must optimize diagnostic signal for downstream leadership artifacts.
- Reason: short tactical rules alone were insufficient; richer meta framing improves consistency of message behavior and keeps generation aligned with final business output quality.
- Enforcement:
  - Expanded `ReplyGeneratorSignature` with long-form sections covering:
    - product context (diagnostic evidence generation),
    - end-goal context (leadership-grade commercial diagnosis),
    - message-quality rationale (signal density vs transcript noise),
    - pipeline awareness (Stage 2 -> Stage 3 -> Stage 4),
    - conversation economics, branching behavior, and outcome semantics.
  - Expanded `FirstMessageSignature` with long-form opening context covering:
    - why opener quality shapes whole diagnostic trajectory,
    - opening design principles for realistic high-signal starts,
    - explicit first-turn intent to force interpretable seller behavior.
  - Kept implementation strictly prompt-side (docstrings only), with no stage interface changes.
- Affected components:
  - `backend/ai/stage2_contact_to_conversation.py`

### Stage 2 Meeting-Logistics Drift Guardrail (2026-02-23)
- Decision/rule: buyer generation must avoid drifting into calendar/meeting coordination loops and prioritize written evidence extraction before any live-call openness.
- Reason: repeated call/agenda/timezone/invite chatter inflated transcript volume while reducing diagnostic signal quality for Stage 3/Stage 4 leadership analysis.
- Enforcement:
  - Added explicit `meeting_and_scheduling_control` guardrail in `ReplyGeneratorSignature`:
    - no proactive meeting asks in early/mid turns,
    - no logistics-heavy buyer messages (agenda, slotting, invites, timezone loops),
    - if seller proposes a call, require async clarity first and keep acceptance concise.
  - Added `async_evidence_first_policy`, `scope_guardrails`, and `anti_pattern_blocklist` to keep buyer turns focused on behavior-revealing evidence.
  - Added `opening_call_control` in `FirstMessageSignature` so first turn never starts with scheduling/admin intent.
- Affected components:
  - `backend/ai/stage2_contact_to_conversation.py`

### Stage 3 Internal Expert-Knowledge Synthesis (2026-02-23)
- Decision/rule: Stage 3 no longer fetches external expert knowledge via Perplexity; it now synthesizes `experts_knowledge` directly from typed `CompanyLLMInfo` input and returns it as a model output alongside `report_text`.
- Reason: reduce external dependency and latency while keeping one contract-faithful Stage 3 artifact (`company_info`, `language`, `experts_knowledge`, `report_text`).
- Enforcement:
  - Removed Stage 3 Perplexity query builder and `pro_search` call path.
  - Updated Stage 3 DSPy signature so `experts_knowledge` is an `OutputField` instead of an `InputField`.
  - Updated Stage 3 DSPy signature to consume `CompanyLLMInfo` directly (no JSON serialization/deserialization handoff).
  - Flattened Stage 3 implementation into one `CompanyReportProgram` with `self.extractor = dspy.ChainOfThought(ExpertCritiqueSignature)` and direct `acall` in `aforward` (no extra wrapper `Program` class).
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/bogan`
  - source files: `/Users/fgoiriz/private/repos/bogan/src/ai/stock_analyzer.py`, `/Users/fgoiriz/private/repos/bogan/src/base.py`
  - reused pattern: one typed DSPy call returning multiple output fields, then deterministic mapping in `aforward` to a Pydantic result used by outer orchestration.
- Affected components:
  - `backend/ai/stage3_company_to_report.py`

### Stage 4 No-Response Threads Must Show Inbound Chat Evidence (2026-02-23)
- Decision/rule: no-response threads must still render inbound buyer message bubbles as transcript evidence, not only a "no response" summary block.
- Reason: diagnosis is more credible when leadership sees exactly what the potential client asked before silence.
- Enforcement:
  - added explicit no-response rendering rules requiring verbatim inbound buyer message bubbles and at least the first inbound message.
  - added a forbidden rule that disallows summary-only no-response cards that hide inbound chat evidence.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`

### Stage 4 Top Identity Strip Requirement (2026-02-23)
- Decision/rule: the HTML report hero must start with a compact identity strip showing company name and source URL host above the main headline.
- Reason: cold-open relevance improves when the first line immediately proves the report is personalized to the audited company/domain.
- Enforcement:
  - Added `top_identity_strip_contract` in Stage 4 signature.
  - Added above-the-fold requirement to include the identity strip before headline lines.
  - Fallback rule: if company name is missing, derive display label from `source_url` host.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`

### Stage 3 Contact Stats Contract Trim to First-Response + Avg (2026-02-23)
- Decision/rule: `ContactConversationStats` now keeps `first_response_seconds` and `avg_response_seconds` for Stage 3/4 inputs.
- Reason: current HTML generation needs first-response and average-response timing, while `total_messages`, `total_outbound_messages`, `total_inbound_messages`, and `median_response_seconds` add payload noise with no rendering value.
- Enforcement:
  - trimmed `ContactConversationStats` model fields.
  - simplified `compute_contact_conversation_stats` to compute only first-response and average-response delays.
  - updated demo report generator to match the reduced contract.
- Affected components:
  - `backend/database.py`
  - `scripts/gen_demo_report.py`

### Parallel Gather Pattern for Stage1 Fetch + First-Messages Fanout (2026-02-23)
- Decision/rule: use `tasks + asyncio.gather(..., return_exceptions=True)` for independent I/O-heavy loops where partial success is acceptable.
- Reason: reduce wall-clock latency in two hot orchestrations without changing stage contracts or channel/runtime boundaries.
- Enforcement:
  - Stage 1 HTML page discovery now fetches candidate URLs concurrently, then filters successful deduped responses.
  - First-message generation for company contacts now runs per-contact generation concurrently and folds results deterministically.
  - Kept behavior robust to per-task failures by handling `Exception` items from gather results.
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/simple-avatar`
  - source files: `/Users/fgoiriz/private/repos/simple-avatar/backend/utils.py`, `/Users/fgoiriz/private/repos/simple-avatar/backend/ai/avatar/program.py`
  - reused pattern: explicit task list + `asyncio.gather` + per-result exception handling and index-stable result folding.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/endpoints/companies.py`

## 2026-02-22

### Good/Bad Canon Skill Added (2026-02-22)
- Decision/rule: add a dedicated skill that stores exhaustive good/bad preferences (including small UI/content details) gathered from iteration loops.
- Reason: avoid losing micro-insights across rapid report-design turns and prevent regression to rejected patterns.
- Enforcement:
  - Added `.cursor/skills/konecta-auditor-good-bad-canon/SKILL.md`.
  - Added a persistence protocol inside that skill requiring every future micro-insight to be logged explicitly.
  - Added the skill to `AGENTS.md` skill-pack order.
- Affected components:
  - `.cursor/skills/konecta-auditor-good-bad-canon/SKILL.md`
  - `AGENTS.md`

### Stage 4 V12 Contact Copy Lock + No-Response Compression Rule (2026-02-22)
- Decision/rule: lock right-panel contact rows to concise v6.1-style metadata and compress no-response threads to a simpler visual treatment without expert lens.
- Reason: extra diagnostic prose in contact rows increased clutter, and no-response threads were over-explained.
- Enforcement:
  - Added strict contact-meta patterns in Stage 4 signature (channel + short role/note only).
  - Added explicit v6.1 saturation values for risk strip colors in right-panel style contract.
  - Added no-response thread contract: short factual line + short business-impact line, no expert-lens block.
  - Added forbidden rules to prevent long contact meta and expert lens in no-response threads.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 V11 Hero Fidelity + Premium Callouts Rule (2026-02-22)
- Decision/rule: lock hero/panel styling closer to v6.1 values and refine inline error callouts to an Apple-like side-card style.
- Reason: v10 was strong, but typography/copy density and red alert styling still needed polish toward the preferred visual benchmark.
- Enforcement:
  - Added v6.1 visual anchors in Stage 4 signature for hero typography, colors, and right-panel contact styling (title weight/spacing, dotted separators, email emphasis).
  - Tightened hero text budgets (context <=30 words, authenticity <=14 words).
  - Updated chat palette guidance to keep modern blue/green bubbles with subtle contrast.
  - Updated error annotation guidance toward compact white side-callout cards with subtle red accent and neutral explanatory text.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 V10 Right-Panel Contacts + Side-Callout Rule (2026-02-22)
- Decision/rule: reintroduce a right-column "ANALYZED CONTACTS" panel (dotted contact list) and move seller error annotations to side-callouts instead of below-message blocks.
- Reason: collapsed contact chips and below-message red blocks created clutter and weak visual hierarchy.
- Enforcement:
  - Added explicit right-panel contacts contract in Stage 4 signature with reference HTML/CSS snippet:
    - title,
    - risk row + badge,
    - tri-color strip + 3 legend chips,
    - dotted-separated contact rows.
  - Added explicit side-callout HTML/CSS pattern for critical seller lines (`.msg-row.has-callout` + `.error-callout`).
  - Updated chat palette guidance to blue buyer bubbles + green employee bubbles.
  - Added conversation density budget to reduce header chip clutter.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 V9 Simplicity Rollback Rule (2026-02-22)
- Decision/rule: rollback from dense quantified hero to a dead-simple impact intro, and simplify conversation cards to reduce attention clash.
- Reason: the denser variant looked cluttered and weakened executive readability.
- Enforcement:
  - Hero now follows the proven style:
    - "Leads are replying."
    - "But the replies are breaking trust."
    - short diagnostic context paragraph + bold "Why this matters now" + short authenticity line.
  - Removed instruction pressure for summary bars/widgets in intro; replaced with identity-first contact trailer.
  - Added explicit conversation attention hierarchy (transcript primary, inline callouts secondary, one expert quote block tertiary).
  - Kept output diagnostic-only and conclusion as two-sentence closing frame.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 V7.2 Hero-Led Minimal Metrics Rule (2026-02-22)
- Decision/rule: Hero should follow the proven two-line quantified intro pattern, and conversation cards should avoid dashboard-style counters and urgency badges.
- Reason: CEO readability is highest with strong contextual hook + personal contact evidence, and lower with clutter metrics that do not improve decisions.
- Enforcement:
  - Updated Stage 4 signature to prioritize hero structure:
    - `<N> buyer conversations.`
    - `<M> potential clients at risk.`
    - short reality subhead + impact line + authenticity line.
  - Removed instruction pressure for urgency/counter UI (`contacts analyzed`, `messages captured`, `outbound/inbound`).
  - Added meaningful 3-color state-bar guidance tied to evidence (not decorative).
  - Added expert pull-quote formatting guidance with attribution when present.
  - Added calmer Apple-like bubble palette guidance (role/channel-aware).
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 V7.1 Conversation Card Polish Rule (2026-02-22)
- Decision/rule: conversation cards should use compact executive microcopy and keep chat as the primary visual area with a compact insight rail.
- Reason: scannability improves when diagnostics are near evidence but secondary to the transcript itself.
- Enforcement:
  - Added guidance for compact per-contact cards (typically 4-8 key turns).
  - Added microcopy rules to avoid jargony/repetitive labels and favor business labels.
  - Added explicit chat-to-insight split guidance (desktop split, mobile stacked).
  - Added whitespace normalization allowance for cleaner message rendering without changing meaning.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 V7 Conversation-Only Body Rule (2026-02-22)
- Decision/rule: the HTML body after the hero must contain only conversation evidence cards with inline diagnostics/expert cues, followed by a two-sentence conclusion.
- Reason: CEO readability and trust are higher when context is anchored in real chats instead of detached risk lists or extra sections.
- Enforcement:
  - Removed standalone top-risk style guidance above conversations.
  - Forbade standalone expert-cue sections below chats.
  - Added conversation visual differentiation guidance (buyer vs employee bubble colors, calm palette).
  - Locked final block to exactly two conclusion sentences with business-impact framing.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 Inline Error Mapping + No-MicroFunnel Rule (2026-02-22)
- Decision/rule: HTML diagnostics now map errors inline beside the exact problematic employee messages and avoid low-value funnel visual blocks.
- Reason: CEO readability improves when error attribution is immediate and local to message evidence.
- Enforcement:
  - Added headline contract to avoid internal jargon like "thread" and require punchy universal business language.
  - Added authenticity contract to state evidence is from real employee conversations over email/whatsapp.
  - Added balanced transcript curation guidance: verbatim key turns, lightly trimmed.
  - Added inline error annotation rules (red compact callouts adjacent to bad employee messages).
  - Removed micro-funnel as a required pattern and forbade standalone bottom-only "errors" section.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 Diagnostic-Only Premium Mode Rule (2026-02-22)
- Decision/rule: Stage 4 HTML is now explicitly diagnostic-only and visual-first (no remediation section).
- Reason: cold-open CEO readability improves when the report only makes errors obvious and avoids long advisory content.
- Enforcement:
  - Expanded `ReportHtmlSignature` with:
    - diagnostic-only mode (no "how to fix" blocks),
    - evidence-first layout (hero -> chats -> diagnostic atlas -> expert lens -> final error signals),
    - stricter brevity/word budgets,
    - mini-diagram guidance (severity strip, matrix, micro-funnel),
    - coarse metric labeling (`Fast`/`Watch`/`Critical`/`No reply`),
    - premium light-theme design contract.
  - Maintained chat rendering but enforced real contact identity labels for company-side turns.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`

### Stage 4 Minimal Premium Visual Rule (2026-02-22)
- Decision/rule: Stage 4 HTML should be minimal, evidence-first, and visually premium, with low text density and low numeric clutter.
- Reason: CEO cold-open readability drops when reports look verbose or overly technical.
- Enforcement:
  - Added display-selection policy: input fields can be used for reasoning without being rendered.
  - Removed expectation of visible long company-context blocks.
  - Added coarse timing display guidance (`Fast`, `Watch`, `Critical`, `No reply`) instead of precise decimal seconds.
  - Added text-density constraints (fewer sentences, high-impact wording).
  - Added hard chat labeling rule: use real audited contact identifier, never generic "Company rep/contact".
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Stage 4 Cold-Approach Brevity + Evidence-First Rule (2026-02-22)
- Decision/rule: Stage 4 HTML output must be concise, evidence-first, and optimized for CEO cold-open readability.
- Reason: long generic reports reduce trust in outbound contexts; first screen must prove relevance with real employee/contact evidence.
- Enforcement:
  - Updated `ReportHtmlSignature` to require above-the-fold block with:
    - what this is,
    - why it matters now,
    - analyzed contacts list,
    - urgency indicator.
  - Enforced section order to place conversation evidence before long analysis.
  - Added brevity budget and transcript key-turn filtering guidance.
  - Reduced expert quote count guidance from 3-6 to 2-4 for higher signal density.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### CEO-First HTML Rendering Guidance Rule (2026-02-22)
- Decision/rule: Stage 4 HTML signature now enforces CEO-first narrative and strict executive curation rules.
- Reason: generated HTML must be leadership-ready for weekly commercial tracking, with strong signal and no implementation noise.
- Enforcement:
  - Added explicit audience/product-intent contract in `ReportHtmlSignature`.
  - Added hard null policy (omit missing fields/blocks, never show placeholder text).
  - Added transcript curation constraints for signature/footer noise removal without semantic drift.
  - Added no-internal-disclaimer policy (no "rendered from JSON"/cleanup disclaimers in final output).
  - Strengthened required section order and quote-to-critique mapping rules.
- Affected components:
  - `backend/ai/stage4_report_to_html.py`

### CEO HTML Playbook Skill Added (2026-02-22)
- Decision/rule: add a dedicated skill describing the CEO-facing HTML quality bar and anti-patterns.
- Reason: keep rendering intent reusable and explicit for future prompt/UI iteration loops.
- Enforcement:
  - Added `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md` with:
    - product intent,
    - CEO lens,
    - required sections,
    - transcript curation policy,
    - anti-patterns and QA checklist.
- Affected components:
  - `.cursor/skills/konecta-auditor-ceo-html-report/SKILL.md`

### Split Report-vs-HTML Task Rule (2026-02-22)
- Decision/rule: report generation is split into two independent async tasks so HTML can be regenerated without recomputing structured report.
- Reason: trial-and-error on HTML prompt/style requires fast regeneration cycles using already persisted report snapshot.
- Enforcement:
  - `POST /api/companies/{company_id}/prepare-report` now persists only `report_snapshot_json` and clears stale `report_html`.
  - `POST /api/companies/{company_id}/build-report-html` renders `report_html` from persisted snapshot.
  - Added dedicated GETs:
    - `/api/companies/{company_id}/artifact-report`
    - `/api/companies/{company_id}/artifact-html`
  - Kept `/api/companies/{company_id}/artifact` as combined wrapper.
- Affected components:
  - `backend/endpoints/companies.py`
  - `frontend/static/js/app.js`
  - `README.md`
  - `HOW_TO_DEVELOP.md`

### Stage Renumbering + HTML Artifact Contract Rule (2026-02-22)
- Decision/rule: report pipeline is now renumbered as Stage 3 (structured report JSON) + Stage 4 (HTML renderer), and `prepare-report` executes both in one async task.
- Reason: simplify orchestration and expose one final artifact payload that serves both UI rendering and programmatic inspection.
- Enforcement:
  - Moved structured report logic from `backend/ai/stage4_evaluations_to_report_payload.py` to `backend/ai/stage3_company_to_report.py`.
  - Added new `backend/ai/stage4_report_to_html.py` with `ReportHtmlProgram`.
  - Removed legacy `backend/ai/stage3_conversation_to_feedback.py`.
  - `GET /api/companies/{company_id}/artifact` now returns `{ generated_at, html, report }`.
  - Removed deprecated `POST /api/companies/{company_id}/build-report`.
- Affected components:
  - `backend/ai/stage3_company_to_report.py`
  - `backend/ai/stage4_report_to_html.py`
  - `backend/endpoints/companies.py`
  - `frontend/static/js/app.js`
  - `backend/ai/__init__.py`
  - `README.md`
  - `HOW_TO_DEVELOP.md`

### Structured Report Field Naming Rule (2026-02-22)
- Decision/rule: structured report model is now `CompanyReport` and the final narrative field is `report_text` (not `report`).
- Reason: avoid ambiguous naming and reserve `report` for the full structured object in API payloads.
- Enforcement:
  - Renamed model `CompanyExpertReport` -> `CompanyReport`.
  - Renamed field `report` -> `report_text`.
  - Updated snapshot parsing in DB to validate against `CompanyReport`.
- Affected components:
  - `backend/ai/stage3_company_to_report.py`
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `scripts/gen_demo_report.py`
  - `backend/ai/__init__.py`

### Legacy Conversation Context Cleanup Rule (2026-02-22)
- Decision/rule: remove legacy simplified-conversation wrappers that are no longer consumed by the active stage pipeline.
- Reason: reduce dead code and keep a single source of truth for Stage 3 context (`to_llm_info`).
- Enforcement:
  - Removed `ContactConversation` model.
  - Removed `Company.get_contact_conversations(...)`.
  - Removed `Contact.to_conversation_context(...)`.
  - Kept `include_archived` path in `Company.to_llm_info(...)` as explicit API surface.
- Affected components:
  - `backend/database.py`

### Stage 4 Minimal Company-Centric Contract Rule (2026-02-22)
- Decision/rule: Stage 4 report generation is reduced to one company-centric context input plus language, and one final artifact output with four fields only.
- Reason: simplify Stage 4 surface, eliminate intermediate layered payload complexity, and keep one clear LLM pipeline for expert critique generation.
- Enforcement:
  - Added `Company.to_llm_info()` and `Contact.to_llm_info()` in `backend/database.py`.
  - Added deterministic per-contact `ContactConversationStats` (`classification`, message counts, response timings) to the LLM context.
  - Stage 4 now builds one `CompanyExpertReport` with:
    - `company_info`
    - `language`
    - `experts_knowledge`
    - `report`
  - Removed Stage 4 `industry` usage from API and internal orchestration.
- Affected components:
  - `backend/database.py`
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `backend/ai/__init__.py`
  - `scripts/gen_demo_report.py`

### Prepare-Report Task Polling Contract Rule (2026-02-22)
- Decision/rule: `POST /api/companies/{company_id}/prepare-report` now follows the same async task contract used by other long-running endpoints.
- Reason: report generation includes external research + LLM processing and should be polled rather than blocking request-response.
- Enforcement:
  - Endpoint now returns `{ task_id, company_id, status }`.
  - Core work moved to background task `prepare_company_audit_report_core(...)`.
  - Frontend now waits on `/api/tasks/{task_id}` before loading artifact.
- Affected components:
  - `backend/endpoints/companies.py`
  - `frontend/static/js/app.js`

### Stage 4 Expert Context Flattening Rule (2026-02-22)
- Decision/rule: Stage 4 intermediate expert-context contracts that are only consumed by downstream LLM calls are flattened to single-string fields, and removed structured subfields must be preserved as labeled sections inside that string.
- Reason: reduce schema overhead and contract surface while preserving semantic payload completeness for downstream prompting.
- Enforcement:
  - `IndustryContextSynthesisProgram` now outputs `industry_context: str` instead of a structured model.
  - Signature output contract explicitly requires labeled sections for the removed fields: `industry_overview`, `expert_opinions`, `risk_patterns`, `opportunity_patterns`, `recommended_focus`.
  - `ExpertResearchContext` now uses one field: `context_text`.
  - `ExpertPerspectiveLayer` now uses one field: `expert_perspective_text`.
  - Contact-audit prompt payload now passes `expert_perspective_text` directly.
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `backend/ai/__init__.py`

### Pattern Reuse Log (2026-02-22, Stage 4 Expert Context Flattening)
70. Source repo: `/Users/fgoiriz/private/repos/bogan`
    Source file(s): `/Users/fgoiriz/private/repos/bogan/src/ai/stock_analyzer.py`
    Reused pattern: single raw-context string IO for DSPy signatures with strict docstring output-contract instructions; adapted to Stage 4 `industry_context` and flattened expert context strings.
71. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: queue heavy endpoint operations via `Task.run_async(...)` and return task metadata for frontend polling; adapted to `prepare-report`.
72. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: model-level context builders that encapsulate persistence-to-LLM shaping in one place; adapted as `Company.to_llm_info()` and `Contact.to_llm_info()`.
73. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: one heavy async endpoint task orchestrates all downstream generation steps and persists final artifacts before completion; adapted to `prepare-report` running Stage 3 + Stage 4.
74. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: keep DB snapshot parsing anchored to one canonical Pydantic model import; adapted to `CompanyReport` parsing in `Company.get_report_snapshot`.
75. Source repo: `/Users/fgoiriz/private/repos/bogan`
    Source file(s): `/Users/fgoiriz/private/repos/bogan/src/ai/stock_analyzer.py`
    Reused pattern: one DSPy program consuming one JSON string context and returning one final string output; adapted to Stage 4 HTML rendering (`report_json` -> `html`).

## 2026-02-21

### Stage 4 Raw JSON Prompting Rule (2026-02-21)
- Decision/rule: Stage 4 LLM subprograms should prefer single raw JSON context inputs over heavily split/normalized prompt fields when the output contract does not require deterministic field-level preprocessing.
- Reason: reduce helper/formatting boilerplate and keep `AuditPayloadProgram` smaller without changing the final `CompanyAuditReport` contract.
- Enforcement:
  - `ContactAuditProgram` now receives one `context_json` input field and generates `audit`.
  - `build_contact_audit_context_json(...)` now passes `{language, industry, company, contact, metrics, expert_perspective}` as one JSON payload.
  - Removed Stage 4 helper layers that only reformatted text for LLM consumption (`sanitize_*`, language/industry normalization helpers, prompt render helpers).
  - `IndustryContextSynthesisProgram.aforward(...)` now returns model output directly without extra post-normalization.
  - Benchmark research prompt grounding now uses compact conversation JSON.
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`

### Stage 4 Contact Input Simplification Rule (2026-02-21)
- Decision/rule: `AuditPayloadInputContact` is removed from Stage 4 boundary; Stage 4 now receives DB-shaped `ContactConversation` records that already include simplified conversation turns.
- Reason: eliminate endpoint-level mapping glue while keeping Stage 4 input explicit (no hidden message fetches inside stage logic).
- Enforcement:
  - Added shared DB model `ContactConversation`.
  - Added `Contact.to_conversation_context()` and `Company.get_contact_conversations()`.
  - `AuditPayloadInput.contacts` now uses `list[ContactConversation]`.
  - `prepare_company_audit_report` passes `contacts=company.get_contact_conversations()` directly.
  - `get_conversation_messages()` legacy path removed in favor of `get_messages(simple=True)` as the single simplified transcript accessor.
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/messages.py`
  - `backend/database.py`
  - `backend/ai/__init__.py`

### Stage 4 Company Entrypoint Rule (2026-02-21)
- Decision/rule: Stage 4 exposes a single entrypoint `AuditPayloadProgram.aforward(...)` that accepts either explicit `AuditPayloadInput` or persisted `Company`; when `Company` is provided, Stage 4 derives `ContactConversation` input internally.
- Reason: keep endpoint orchestration minimal while preserving explicit Stage 4 contract for lab/isolated validation.
- Enforcement:
  - Removed `aforward_from_company(...)` and unified behavior in `aforward(...)`.
  - Added `resolve_input_data(...)` helper inside Stage 4 to normalize `Company | AuditPayloadInput` into one `AuditPayloadInput`.
  - Endpoint `prepare_company_audit_report` now calls `stage4.aforward(company, ...)` and maps `ValueError` to HTTP `409`.
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `backend/endpoints/companies.py`

### CEO-Safe Stage 4 Contract Naming Rule (2026-02-21)
- Decision/rule: Stage 4 JSON artifact renamed from technical `payload/raw/derived/expert` language to CEO-facing report contract: `report.source_evidence`, `report.audit_analysis`, `report.expert_perspective`.
- Reason: report artifact is now the direct preview surface for leadership, so internal/infra labels and machine metadata were creating noise and confusion.
- Enforcement:
  - Stage 4 top model changed to `CompanyAuditReport`.
  - `GET /api/companies/{company_id}/artifact` now returns `{ generated_at, report }` (no `payload` wrapper field).
  - Removed internal fields from report contract (e.g. company/contact IDs, automation flags, LLM provider/model metadata, response IDs, token usage).
  - Kept full business-relevant transcript evidence and evaluation outputs.
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `backend/endpoints/companies.py`
  - `backend/database.py`
  - `frontend/static/js/app.js`
  - `scripts/gen_demo_report.py`
  - `backend/ai/__init__.py`

### Conversation-Grounded Expert Research Rule (2026-02-21)
- Decision/rule: expert research prompt must include real audited conversation evidence, not run “blind” by objective/industry only.
- Reason: benchmark and critique quality improves when experts are selected and applied against concrete conversation behavior.
- Enforcement:
  - Added conversation-context extraction helper in companies endpoint glue.
  - `fetch_expert_research_context_for_company` now receives `conversation_context` and injects it into the Perplexity query.
  - Stored conversation excerpt inside `report.expert_perspective.external_research.conversation_context_excerpt`.
- Affected components:
  - `backend/endpoints/companies.py`
  - `backend/ai/stage4_evaluations_to_report_payload.py`

### Cross-Company Contact Deduplication Scope Rule (2026-02-21)
- Decision/rule: contact deduplication during discovery applies only within the same company, not across different companies.
- Reason: cross-company blocking caused under-discovery for repeated audits of the same domain (e.g. konectalabs.com showing 1 contact instead of discovered set).
- Enforcement:
  - Updated `should_create_contact_for_company` to check duplicates only for `company_id`-scoped contacts.
- Affected components:
  - `backend/endpoints/companies.py`

### Full Raw Evidence Coverage Rule (2026-02-21)
- Decision/rule: Stage 4 report `source_evidence` must include full per-contact transcript data for all active contacts, including message and contact persistence metadata from DB.
- Reason: the Stage 4 report is the single input for the future free-form HTML generator, so omitted raw evidence cannot be recovered downstream.
- Enforcement:
  - `source_evidence.contact_conversations[*].conversation[*]` includes the full transcript turns required for rendering (`speaker`, `text`, `timestamp`) for every active contact.
  - Contact-level evidence kept for rendering: `contact_label`, `contact_channel`, `notes`, `additional_context`.
  - Company-level evidence kept for rendering: `company_name`, `website`, `company_overview`, `audit_goal`, `report_language`, `report_industry`.
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `scripts/gen_demo_report.py`

### HTML-Input Relevance Trimming Rule (2026-02-21)
- Decision/rule: Stage 4 report must exclude raw fields that do not add rendering value for final CEO-facing HTML.
- Reason: downstream free-form HTML generator should receive complete but relevant context; excess transport/threading identifiers add noise.
- Enforcement:
  - Removed from report contract: `message_id`, `from_me`, `delivery_status`, `external_id`, `dispatch_after`, `email_thread_id`, `email_last_outbound_rfc_id`, `contact_value`, `normalized_value`, `contact_id`, `status`, `created_at`, `updated_at`, `company_id`, `search_prompt`, `conversation_context_excerpt`, `search_queries`, citation `snippet`.
  - Kept only content needed for HTML composition (narrative evidence + deterministic stats + expert synthesis + citation links).
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `scripts/gen_demo_report.py`

### Phase 4 Payload-First Contract Rule (2026-02-21)
- Decision/rule: Stage 4 now produces a layered JSON artifact and no longer renders HTML in backend for this interim phase. Initial names (`payload/raw/derived/expert`) were later renamed to CEO-facing `report/source_evidence/audit_analysis/expert_perspective`.
- Reason: unlock free-form HTML generation in a dedicated next phase by first stabilizing a complete data contract that includes persisted evidence, deterministic metrics, and expert research context.
- Enforcement:
  - Added Stage 4 program module `backend/ai/stage4_evaluations_to_report_payload.py` with `AuditPayloadProgram.aforward` and `IndustryContextSynthesisProgram.aforward`.
  - `POST /api/companies/{company_id}/prepare-report` now persists the structured Stage 4 report in `companies.report_snapshot_json`, clears `companies.report_html`, and marks company as `audited`.
  - `GET /api/companies/{company_id}/artifact` now returns structured report JSON.
  - `POST /api/companies/{company_id}/build-report` is temporarily deprecated and returns `410`.
  - Frontend now generates payload via `prepare-report` and opens pretty JSON on “View Report HTML”.
- Affected components:
  - `backend/ai/stage4_evaluations_to_report_payload.py`
  - `backend/endpoints/companies.py`
  - `backend/database.py`
  - `backend/main.py`
  - `backend/ai/__init__.py`
  - `frontend/static/js/app.js`
  - `scripts/gen_demo_report.py`
  - `README.md`
  - `HOW_TO_DEVELOP.md`
  - `AGENTS.md`

### Contact Channel Accessor Rule (2026-02-21)
- Decision/rule: when endpoint logic branches by persisted `Contact.type`, use model-level accessors (`contact.canonical_type`, `contact.is_email`, `contact.is_whatsapp`) instead of repeating `canonical_contact_type(contact.type)` at call sites.
- Reason: channel canonicalization is deterministic infrastructure logic and should be centralized on the model to reduce scattered normalization and avoid drift.
- Enforcement:
  - Added canonical channel accessors to `Contact`.
  - Updated companies/messages endpoint glue to consume contact accessors for branch conditions and response payload shaping.
  - Keep `canonical_contact_type(...)` for raw external inputs only (request params, Stage 1 outputs).
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/messages.py`

### Pattern Reuse Log (2026-02-21, Payload-First Stage 4)
64. Source repo: `/Users/fgoiriz/private/repos/bogan`
    Source file(s): `/Users/fgoiriz/private/repos/bogan/src/ai/quote_bot.py`
    Reused pattern: layered final result contract carrying both intermediate/raw evidence and processed outputs in one typed payload; adapted to `CompanyAuditPayload`.
65. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: persisted JSON payload storage discipline (`payload_json`) with typed read/parse boundaries; adapted to `companies.report_snapshot_json` parsing as `CompanyAuditPayload`.
66. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: explicit typed endpoint contracts and deliberate compatibility behavior for evolving endpoints; adapted to `build-report` temporary deprecation (`410`) while preserving route.
67. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: centralize deterministic normalization at model/persistence boundaries to avoid endpoint-level repetition; adapted to `Contact` canonical channel accessors consumed by endpoint glue.
68. Source repo: `/Users/fgoiriz/private/repos/bogan`
    Source file(s): `/Users/fgoiriz/private/repos/bogan/src/ai/stock_analyzer.py`
    Reused pattern: single-argument JSON context passed directly into a DSPy signature (`stock_json`) instead of decomposing into many synthetic prompt fields; adapted to Stage 4 `ContactAuditProgram.context_json`.
69. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/ai.py`
    Reused pattern: keep `Program.aforward` orchestration thin while letting model prompts consume broad context text directly; adapted to Stage 4 helper deletion and raw-context prompting flow.

## 2026-02-20

### Manual Contact Auto First-Message Queue Rule (2026-02-20)
- Decision/rule: `POST /api/companies/{company_id}/contacts` must auto-enqueue first-message generation for contacts without any transcript and return the queued task metadata.
- Reason: manual-contact first-message behavior must be guaranteed by backend contract, not by optional frontend follow-up calls.
- Enforcement:
  - Manual contact create endpoint now queues `generate_contact_first_message_core` using backend task orchestration when the contact has no messages.
  - Endpoint response now includes `first_message_task_id` and `first_message_task_status`.
  - Frontend manual-contact flow now consumes the returned task id and no longer issues a second `/first-message` call after contact creation.
- Affected components:
  - `backend/endpoints/companies.py`
  - `frontend/static/js/app.js`
  - `HOW_TO_DEVELOP.md`

### Pattern Reuse Log (2026-02-20, Manual Contact First-Message Queue)
63. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`, `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: endpoint-level background-task creation as part of write workflows, returning task metadata for polling; adapted to manual contact creation flow in this repo.

### Cinematic Premium Frontend Visual Contract Rule (2026-02-20)
- Decision/rule: frontend visual upgrades must preserve the exact backoffice UX flow and JS interaction hooks while allowing aggressive style-layer enhancement (atmosphere layers, stronger token system, richer motion).
- Reason: operators requested a major “next-level” visual uplift without any change to actions, navigation model, or backend/UI data contracts.
- Enforcement:
  - Keep existing DOM IDs and JS query hooks unchanged.
  - Restrict UI changes to visual-only layers and styling (`index.html`, `frontend/static/css/style.css`, `frontend/static/js/app.js` performance/motion internals only).
  - Add reduced-motion guardrails for heavy decorative animation and ambient canvas effects.
  - Keep backend endpoints and payload contracts unchanged.
- Affected components:
  - `frontend/index.html`
  - `frontend/static/css/style.css`
  - `frontend/static/js/app.js`

### Pattern Reuse Log (2026-02-20, Cinematic Premium Frontend)
54. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/static/css/style.css`
    Reused pattern: token-driven visual system and card elevation layering; adapted to teal-first cinematic glass surfaces and stronger hover/active depth in this repo.
55. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/styles/_variables.scss`, `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/styles/_keyframe-animations.scss`
    Reused pattern: transition/easing token discipline and centralized keyframe orchestration; adapted to staged entrance motion, reduced-motion fallbacks, and smoother premium interactions.

### Editorial Minimal Workspace/UI System Rule (2026-02-20)
- Decision/rule: second frontend uplift for backoffice operations must prioritize editorial minimal hierarchy (lower visual noise, stronger spacing rhythm, cleaner cards/forms) while preserving all existing UX flows and JS hooks.
- Reason: after the cinematic pass, operators requested a more modern and simplistic operational surface without losing the premium feel.
- Enforcement:
  - Apply style-only refinements to project workspace, sidebar context, and modal/form system.
  - Preserve all existing DOM ids/data attributes and event bindings.
  - Keep status semantics (`active`, `archived`, `pending`) visually clear but with lower saturation.
  - Maintain reduced-motion compliance for added transitions/animations.
- Affected components:
  - `frontend/static/css/style.css`
  - `frontend/index.html`

### Pattern Reuse Log (2026-02-20, Editorial Minimal UI #2)
56. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/static/css/style.css`
    Reused pattern: restrained card/surface elevation and cleaner spacing hierarchy for operational dashboards; adapted to project workspace, contacts list, and transcript panels.
57. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/styles/_variables.scss`, `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/styles/_keyframe-animations.scss`
    Reused pattern: transition token discipline and motion-light UI polish with explicit reduced-motion guardrails; adapted to subtle interaction feedback in workspace/sidebar/modal components.

### CEO-First Audit Report Contract Rule (2026-02-20)
- Decision/rule: Stage 4 report contract is now CEO-first and structured; executive page must prioritize decision signals (risk, coverage, critical rate, priority action) and move detailed transcript analysis to compact per-contact cards with expandable full transcript.
- Reason: legacy hero/indicator blocks included low-value vanity metrics and narrative fluff that diluted leadership usability.
- Enforcement:
  - Stage 3 output now includes structured rubric fields (`CompetencyScorecard`, `RiskFlag`, `ExecutiveFinding`, `KeyMomentEvidence`, `CoachingAction`) plus deterministic `opportunity_risk_index`.
  - Stage 4 no longer uses sales-question and median-response hero metrics as primary executive indicators.
  - Report generation now partitions active contacts into engaged vs non-responsive; non-responsive contacts are reported explicitly as critical coverage failures.
  - Audit generation no longer fails when there are zero engaged conversations; it produces a coverage-focused report.
- Affected components:
  - `backend/ai/stage3_conversation_to_feedback.py`
  - `backend/endpoints/companies.py`
  - `backend/html_renderer.py`
  - `scripts/gen_demo_report.py`
  - `README.md`

### Pattern Reuse Log (2026-02-20, CEO Audit Report Redesign)
58. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/static/css/style.css`
    Reused pattern: tokenized card/section hierarchy and restrained dashboard layout rhythm; adapted to CEO brief + compact scorecard report pages.
59. Source repo: `/Users/fgoiriz/private/repos/bogan`
    Source file(s): `/Users/fgoiriz/private/repos/bogan/src/base.py`
    Reused pattern: strict typed `Program` contract discipline with deterministic post-processing outside LLM free-form output; adapted to Stage 3 structured rubric normalization and risk-index computation.
60. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/base.py`
    Reused pattern: predictable contract-first orchestration style in stage code, separating extraction from deterministic normalization; adapted to Stage 3 evaluation result shaping.

### Company Hard-Cut + Persisted Snapshot Report Rule (2026-02-20)
- Decision/rule: domain naming is now hard-cut to `Company` across backend/frontend/bot/DB, and report generation is split into explicit `prepare-report` (slow, extraction) and `build-report` (fast, render-only).
- Reason: remove ambiguous audit naming and guarantee fast artifact rebuilds by persisting structured report state in DB.
- Enforcement:
  - Public API is now `/api/companies/...` only; `/api/audits/...` compatibility was removed.
  - Main entity/table renamed to `companies`, with FK `contacts.company_id`.
  - `companies.report_snapshot_json` stores one full `CompanyReportSnapshot`.
  - `companies.report_html` stores rendered HTML artifact.
  - `build-report` must only read persisted snapshot and render HTML (no Stage 3, no benchmark fetch).
  - `artifact` endpoint serves persisted DB HTML directly.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `backend/endpoints/messages.py`
  - `backend/html_renderer.py`
  - `backend/main.py`
  - `frontend/static/js/app.js`
  - `frontend/index.html`
  - `bot/utils.py`
  - `bot/simulation.py`
  - `README.md`
  - `HOW_TO_DEVELOP.md`

### Pattern Reuse Log (2026-02-20, Company Snapshot Hard-Cut)
61. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/base.py`
    Reused pattern: contract-first endpoint orchestration with explicit state transitions; adapted to `prepare-report`/`build-report` separation and persisted artifact flow.
62. Source repo: `/Users/fgoiriz/private/repos/bogan`
    Source file(s): `/Users/fgoiriz/private/repos/bogan/src/base.py`
    Reused pattern: strict typed contract boundaries for stage inputs/outputs; adapted to persisted `CompanyReportSnapshot` as Stage 4 render source.

## 2026-02-19

### Gmail Thread Context Reply Rule (2026-02-19)
- Decision/rule: outbound Gmail replies must preserve thread continuity by resolving subject and reply headers from live thread metadata when `thread_id` is available.
- Reason: deriving a fresh subject per outbound turn can split the recipient-side conversation into a new email, even when dispatch is marked delivered.
- Enforcement:
  - Gmail provider now loads thread metadata (`Subject`, latest `Message-ID`, `References`) before send when `thread_id` exists.
  - Outbound subject now prefers thread subject over message-text-derived subject.
  - Outbound `In-Reply-To` now prefers the latest thread message id.
  - Outbound `References` now merges thread references with explicit metadata without duplicates.
  - Added unit tests for reference merge ordering, reply-header resolution, and subject resolution.
- Affected components:
  - `bot/providers.py`
  - `bot/tests/test_email_reply_parsing.py`

### Gmail Subject Without Reply Prefix Rule (2026-02-19)
- Decision/rule: outbound Gmail subjects must never include automatic `Re:` / `Fw:` prefixes.
- Reason: first outbound contact emails should not look like replies, and threaded replies already rely on `thread_id` + RFC headers.
- Enforcement:
  - Default subject fallback changed to `Inquiry` (without `Re:`).
  - Subject normalization now removes leading `Re:`, `Fw:`, and `Fwd:` prefixes.
  - Thread-context subject resolution now sanitizes inherited subjects before send.
  - Added unit test coverage for reply/forward prefix removal.
- Affected components:
  - `bot/providers.py`
  - `bot/tests/test_email_reply_parsing.py`

### Shared Backend Contract vs Bot Capability Rule (2026-02-19)
- Decision/rule: shared backend endpoints must stay complete for frontend/backoffice contracts; bot capability limits must be handled in `bot/` layer filtering, not by narrowing backend responses.
- Reason: frontend and bot consume shared APIs, so hiding unsupported channels (for example `linkedin`) in backend to satisfy bot dispatch breaks frontend visibility and shared contract integrity.
- Enforcement:
  - Do not remove/filter shared endpoint payload fields or channel types because one provider runtime cannot dispatch them.
  - Bot worker must filter unsupported channels locally before dispatch.
  - Treat unsupported channels as bot-local skipped/deferred outcomes and keep backend API contract unchanged.
- Affected components:
  - `.cursor/skills/konecta-development-method/SKILL.md`
  - `.cursor/skills/konecta-auditor-delivery-outbox/SKILL.md`

### Gmail Thread Merge Change-Control Rule (2026-02-19)
- Decision/rule: thread-level merge of multiple unread Gmail messages into one inbound payload is not default behavior and requires explicit product approval before implementation.
- Reason: merging changes conversation granularity and may alter timing/intent semantics from the original provider events.
- Enforcement:
  - Keep one inbound event per provider message by default.
  - Any unread-per-thread merge strategy must be explicitly requested and validated before rollout.
- Affected components:
  - `.cursor/skills/konecta-auditor-delivery-outbox/SKILL.md`

### Instant Dispatch + Fast Bot Tick Rule (2026-02-19)
- Decision/rule: outbound replies generated from inbound messages now default to instant dispatch, and bot polling loop defaults to 5-second ticks.
- Reason: remove artificial delivery latency and reduce end-to-end time between backend draft creation and provider dispatch.
- Enforcement:
  - Added `EMAIL_REPLY_DELAY_SECONDS` env override with default `0` in backend message loop logic.
  - Set `BOT_TICK_SECONDS` default to `5` in bot runtime.
  - Updated Docker bot runtime env to `BOT_TICK_SECONDS=5`.
  - Updated docs to state the timing defaults.
- Affected components:
  - `backend/endpoints/messages.py`
  - `bot/utils.py`
  - `docker-compose.yml`
  - `README.md`

### Contact Type Canonicalization Rule (2026-02-19)
- Decision/rule: backend now canonicalizes all `phone` contacts to `whatsapp` at persistence and endpoint payload level.
- Reason: operationally, phone and WhatsApp were treated as the same channel and produced duplicate contacts for the same number.
- Enforcement:
  - Added canonical contact-type aliasing in persistence (`phone` -> `whatsapp`).
  - `Contact.create(...)` now always stores canonicalized types.
  - `Contact.create(...)` now reuses existing row for same `audit_id + canonical_type + normalized_value` instead of inserting duplicates.
  - Audit contact creation dedupes by canonical type + normalized value, so Stage 1 `phone` + `whatsapp` for one number persist as a single `whatsapp`.
  - Added unique DB constraint for `(audit_id, type, normalized_value)` so duplicates are rejected at storage level on fresh/recreated DBs.
  - Inbound channel normalization now aliases `channel=phone` to `whatsapp`.
  - Message/audit endpoint payloads now emit canonical contact type values.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/audits.py`
  - `backend/endpoints/messages.py`

### Gmail Inbound Scope Rule (2026-02-19)
- Decision/rule: bot Gmail polling must be scoped to active backend email contacts only.
- Reason: polling the full unread inbox generated noisy 404 resolve traffic and processed unrelated senders (delivery failures, workspace notices, system emails).
- Enforcement:
  - Added `GET /api/contacts/tracked-values?channel=email|whatsapp`.
  - Bot now fetches tracked email senders from backend each tick and passes them to Gmail polling.
  - Gmail provider uses sender query filtering and sender-level post-filtering before producing inbound events.
- Affected components:
  - `backend/endpoints/messages.py`
  - `bot/utils.py`
  - `bot/main.py`
  - `bot/providers.py`
  - `README.md`

### Audit-Scoped AI Automation Authorization Rule (2026-02-19)
- Decision/rule: each audit now owns `ai_automation_enabled` (default `false`), and bot-facing shared endpoints must only expose/process contacts from audits with this flag enabled.
- Reason: keep backend/frontend contracts shared while adding explicit per-audit authorization so automation is opt-in.
- Enforcement:
  - Added `Audit.ai_automation_enabled` in persistence with default `False`.
  - Added `PUT /api/audits/{audit_id}` for shared audit settings updates.
  - `GET /api/messages/pending-delivery`, `GET /api/contacts/tracked-values`, and `GET /api/contacts/resolve` now filter by enabled audits.
  - Frontend `projectView` header now includes `AI Automation` toggle wired to `PUT /api/audits/{audit_id}`.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/audits.py`
  - `backend/endpoints/messages.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`
  - `README.md`
  - `HOW_TO_DEVELOP.md`

### Pattern Reuse Log (2026-02-19, Contact Type Canonicalization)
45. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: centralized normalization at persistence boundaries (classmethod-centric DB writes) instead of scattering channel-shape fixes across endpoint handlers; adapted to contact type aliasing in this repo.
46. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/scheduler.py`
    Reused pattern: pre-filter execution candidates by persisted eligibility state before worker loop execution.
47. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/organizations.py`
    Reused pattern: safe default filtering by active/eligible state when optional filter is not explicitly provided.
48. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/scheduler.py`
    Reused pattern: tight async scheduler cadence (`poll_seconds`) with loop-level exception isolation; adapted to 5-second bot worker ticks for faster dispatch/read cycles.
49. Source repo: `/Users/fgoiriz/private/repos/konecta-auditor`
    Source file(s): `/Users/fgoiriz/private/repos/konecta-auditor/legacy-ignore/email_delivery.py`
    Reused pattern: deterministic RFC `References` merge with de-duplication and stable token order; adapted to bot Gmail reply-header resolution using live thread context.

### Manual Contact + Per-Contact First Message Rule (2026-02-19)
- Decision/rule: manual contact onboarding is a two-step explicit endpoint flow: create contact first, then trigger per-contact first-message generation through its dedicated endpoint.
- Reason: operators need a deterministic human-loop flow to inject one contact after audit creation, without running bulk generation.
- Enforcement:
  - Added `POST /api/audits/{audit_id}/contacts` for manual contact creation (`type`, `value`, `notes`, `additional_info`).
  - Added `POST /api/audits/{audit_id}/contacts/{contact_id}/first-message` for single-contact first draft generation trigger (with optional `force`).
  - Frontend exposes `Add Contact` in audit view and executes: create contact -> enqueue first-message task -> refresh/poll task.
- Affected components:
  - `backend/endpoints/audits.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`
  - `README.md`

### Pattern Reuse Log (2026-02-19, Manual Contact Flow)
50. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: explicit sequential endpoint workflow (resource creation endpoint followed by action endpoint) instead of overloading one endpoint; adapted to manual contact creation + per-contact first-message generation.
51. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/organizations.py`
    Reused pattern: endpoint-scoped request/response models colocated with route handlers for clear contracts; adapted to manual-contact and per-contact first-message endpoint payloads.

### Manual Contact First-Message Async Task Rule (2026-02-19)
- Decision/rule: per-contact first-message generation now runs as tracked background task and must not block manual-contact creation UX.
- Reason: operators need to return to the contacts grid immediately after contact creation while first-draft generation runs, and the chat for that contact must stay locked until completion.
- Enforcement:
  - `POST /api/audits/{audit_id}/contacts/{contact_id}/first-message` now enqueues `Task.run_async(...)` with explicit timeout and returns `{task_id, status}`.
  - First-message task core reuses `generate_first_message_for_contact(...)` so bulk/manual flows share one persistence path.
  - `POST /api/audits/{audit_id}/contacts/{contact_id}/messages/inbound` now rejects with `409` when that contact still has a queued/running first-message task.
  - Frontend manual-contact flow now does: create contact -> enqueue first-message task -> refresh audit detail -> poll `GET /api/tasks/{task_id}` in background.
  - Frontend keeps `pendingFirstMessageTasks[contact_id]` and disables inbound composer for that contact until task reaches terminal state.
- Affected components:
  - `backend/endpoints/audits.py`
  - `backend/endpoints/messages.py`
  - `backend/database.py`
  - `frontend/static/js/app.js`
  - `README.md`
  - `HOW_TO_DEVELOP.md`

### Pattern Reuse Log (2026-02-19, Manual Contact Async First Message)
52. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: action endpoint enqueues background work and returns `task_id`, with completion tracked via dedicated `/api/tasks/{task_id}` polling; adapted to per-contact first-message generation.
53. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/[locale]/avatars/[id]/page.tsx`
    Reused pattern: per-item async tracking keyed by resource id so only the affected UI element is blocked; adapted to `pendingFirstMessageTasks[contact_id]` composer locking.
## 2026-02-17

### Stateless Bot Runtime + Backend-Owned State Rule (2026-02-17)
- Decision/rule: external channel orchestration now runs in a standalone `bot/` service with `FastAPI + worker loop`, while business state remains fully owned by backend tables/endpoints.
- Reason: human frontend and bot must share the same source of truth (`delivered/undelivered`, contact resolution, threading metadata) with zero local bot state/caches.
- Enforcement:
  - Added independent `bot/` project (own `pyproject.toml`, `uv.lock`, Dockerfile).
  - Bot loop runs every `BOT_TICK_SECONDS` (default 60s):
    - fetch outbound `undelivered` due messages from backend,
    - dispatch by provider (Gmail/PyWA),
    - mark delivery via backend API.
  - Bot inbound handling:
    - Gmail polling (`UNREAD`) resolves contact via backend and posts inbound message requests.
    - WhatsApp webhook resolves contact by number and posts inbound message requests.
  - Bot keeps no business state; it only uses backend APIs + provider metadata.
- Affected components:
  - `bot/main.py`
  - `bot/utils.py`
  - `bot/providers.py`
  - `bot/pyproject.toml`
  - `bot/Dockerfile`
  - `docker-compose.yml`

### Provider Metadata + Contact Resolution Contract Rule (2026-02-17)
- Decision/rule: backend message/contact contracts now persist provider metadata needed for stateless idempotency and email thread continuity.
- Reason: email replies must target existing provider threads without storing bot-side conversation state; inbound dedupe must rely on provider IDs.
- Enforcement:
  - Added contact fields: `normalized_value`, `email_thread_id`, `email_last_outbound_rfc_id`.
  - Added message field: `dispatch_after` for due-based delivery dispatch.
  - Extended inbound endpoint payload to accept provider metadata (`external_id`, `channel`, `thread_id`, `in_reply_to`, `references`) with duplicate inbound guard by `external_id`.
  - Extended delivery update endpoint to accept send metadata (`external_id`, `thread_id`, `rfc_message_id`) and sync contact email threading fields.
  - Added generic endpoints:
    - `GET /api/contacts/resolve`
    - `GET /api/messages/pending-delivery`
  - Enforced global contact dedupe on creation by normalized contact value across audits.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/messages.py`
  - `backend/endpoints/audits.py`
  - `README.md`

### Pattern Reuse Log (2026-02-17, Stateless Bot + Provider Metadata)
41. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/scheduler.py`
    Reused pattern: lightweight perpetual async worker loop with bounded polling interval and per-iteration exception isolation.
42. Source repo: `/Users/fgoiriz/private/repos/konecta-auditor`
    Source file(s): `/Users/fgoiriz/private/repos/konecta-auditor/legacy-ignore/wa.py`
    Reused pattern: PyWA provider wrapper with FastAPI webhook binding, callback registration, and chunked WhatsApp outbound send when text exceeds provider limits.
43. Source repo: `/Users/fgoiriz/private/repos/konecta-auditor`
    Source file(s): `/Users/fgoiriz/private/repos/konecta-auditor/legacy-ignore/gmail.py`, `/Users/fgoiriz/private/repos/konecta-auditor/legacy-ignore/email_listener.py`
    Reused pattern: Gmail OAuth refresh, RFC header propagation (`Message-ID`, `In-Reply-To`, `References`), unread polling, and mark-as-read lifecycle after successful processing.
44. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: FastAPI lifespan orchestration for startup/shutdown resource wiring in a compact service entrypoint.

### Stage 1 Deep Research Toggle Rule (2026-02-17)
- Decision/rule: audit creation now supports `deep_research_enabled` to control Stage 1 discovery mode per new company.
- Reason: operators need explicit cost control (`$$$`) for Perplexity-based discovery while keeping a no-cost static fallback path.
- Enforcement:
  - `POST /api/audits` accepts `deep_research_enabled` (default `false`, i.e. static-only mode).
  - Stage 1 `UrlToContactsProgram.aforward(url, deep_research_enabled)` now gates Perplexity search:
    - `true`: current behavior (`pro_search` + static HTML evidence).
    - `false`: static HTML evidence only (no Perplexity call).
  - New Audit modal includes ON/OFF toggle with `$$$` cost indicator and explicit cost warning for Perplexity (`CON` recommended only for deep searches).
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/endpoints/audits.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`

### Manual Outbound Delivery Status Rule (2026-02-17)
- Decision/rule: outbound drafts now have explicit manual delivery lifecycle (`undelivered` -> `delivered`) and must never be auto-marked as delivered by opening chat/channel links.
- Reason: operator workflow is human-in-the-loop; sending happens outside the backoffice, so delivered state must be confirmed manually.
- Enforcement:
  - Added `MessageDeliveryStatus` enum and persisted `messages.delivery_status`.
  - `Message.add(...)` now defaults to `undelivered` for outbound (`from_me=True`) and `delivered` for inbound (`from_me=False`).
  - Added endpoint `PUT /api/audits/{audit_id}/contacts/{contact_id}/messages/{message_id}/delivery` with manual toggle payload.
  - Frontend transcript now shows per-outbound delivery chip and `Mark Delivered` action button.
  - Contact cards/sidebar now show red attention dot when pending outbound delivery exists.
  - Audit cards now show red numeric badge with count of active contacts needing delivery action.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/messages.py`
  - `backend/endpoints/audits.py`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`
  - `frontend/index.html`
  - `README.md`

### Dev Schema Evolution Rule (2026-02-17)
- Decision/rule: during local development, schema changes must not use migrations; recreate `data/database.sqlite` instead.
- Reason: this repo currently optimizes for fast iteration with simple SQLite recreation and avoids migration maintenance overhead in dev loops.
- Enforcement:
  - Added explicit no-migrations guidance to core skills and development guide.
  - When schema changes are introduced, validation runs should recreate the SQLite file before startup/tests.
- Affected components:
  - `.cursor/skills/konecta-development-method/SKILL.md`
  - `.cursor/skills/konecta-auditor-db-forensics/SKILL.md`
  - `HOW_TO_DEVELOP.md`

### Pattern Reuse Log (2026-02-17, Manual Delivery Status + Pending Badges)
38. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: directional message persistence (`from_me`) with lean classmethod updates; adapted by adding outbound-only manual delivery state updates on top of existing direction flag.
39. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`, `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
    Reused pattern: compact enum-based status model and badge-style pending visibility in list views; adapted to per-contact pending-delivery counters surfaced at audit-card level.
40. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`, `/Users/fgoiriz/private/repos/outbound/frontend/index.html`, `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
    Reused pattern: request-level research-depth control (`Create*Request` + UI input + JSON payload wiring) mapped into backend orchestration; adapted to boolean `deep_research_enabled` toggle in new-audit flow.

## 2026-02-15

### Contact Archive Status Rule (2026-02-15)
- Decision/rule: contacts now support lifecycle status (`active` / `archived`) and archived contacts are excluded from operational flows until explicitly unarchived.
- Reason: operators need a reversible way to remove low-value/invalid contacts from message relay and audit generation without deleting historical data.
- Enforcement:
  - Reused existing `contacts.status` as canonical lifecycle state, with `ContactStatus` enum and helper methods (`list_by_audit`, `count_by_audit`, `update_status`) filtered by state.
  - Added endpoint `PUT /api/audits/{audit_id}/contacts/{contact_id}/archive` with boolean toggle payload.
  - `GET /api/audits/{audit_id}` now supports `?archived=true` to list archived contacts separately.
  - Message endpoints (`transcript`, `inbound`, `message edit`, `email-thread-link`) now reject archived contacts with `409`.
  - First-message generation and audit generation now run only against active contacts.
  - Backoffice UI now includes `Archive`, `View Archived/View Active`, and `Unarchive` actions.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/audits.py`
  - `backend/endpoints/messages.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`
  - `README.md`

### Pattern Reuse Log (2026-02-15, Contact Archive Controls)
36. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/backend/database.py`
    Reused pattern: enum-backed lifecycle status (`active`/`inactive`) as query guard for operational entities; adapted to contact lifecycle (`active`/`archived`) with filtered list/count helpers.
37. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: lean classmethod persistence surface (`create/get/list/update`) with endpoint-level gating before async work; adapted to archive validation before transcript/inbound/audit flows.

### Task Timeout + Startup Recovery Rule (2026-02-15)
- Decision/rule: Stage 1 contact discovery and async task execution must fail fast instead of staying indefinitely in `RUNNING`.
- Reason: external provider latency/retries can leave `create_audit_core` tasks hanging, producing audits that appear with zero contacts while the task never completes.
- Enforcement:
  - Stage 1 search now runs with explicit timeout and one retry (`2` attempts total).
  - `Task.run_async` now supports `timeout_seconds`; timeout marks the task as `FAILED` with explicit timeout error.
  - Startup now marks stale `RUNNING` tasks as `FAILED` (same pattern used in `simple-avatar`).
  - Audit creation and inbound-reply task flows use explicit task timeouts to guarantee terminal task status.
  - Stage 1 normalizes URLs without scheme (e.g. `za-tek.com` -> `https://za-tek.com`) before HTTP evidence fetch.
  - If search provider fails after retries, Stage 1 continues with deterministic HTML evidence extraction (homepage + common contact/about/legal paths) instead of hard-failing immediately.
  - Stage 1 errors now raise explicit messages with attempt/timeout context so task failures are easy to diagnose.
  - `create_audit_core` now marks the audit itself as `FAILED` when discovery crashes, so UI status reflects the failure state.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`
  - `backend/database.py`
  - `backend/endpoints/tasks.py`
  - `backend/main.py`
  - `backend/endpoints/audits.py`

### Stage 2 XML Prompt + Plain String Contract Rule (2026-02-15)
- Decision/rule: Stage 2 message generation now uses plain string outputs and strict XML prompt sections for behavioral control.
- Reason: audit realism required low-intent buyer behavior with concise objections, no fake identities, and no formal email artifacts.
- Enforcement:
  - Removed single-field wrappers in Stage 2 (`ReplyDraft`, `FirstMessageDraft`, `ConversationTurnResult`).
  - `ReplyGeneratorProgram`, `FirstMessageProgram`, and `ContactConversationProgram` now return `str`.
  - Stage 2 signatures now include strict XML instruction blocks (`role`, `persona`, `objection_policy`, `name_capture_policy`, `anti_hallucination`, `forbidden`, `output_contract`).
- Affected components:
  - `backend/ai/stage2_contact_to_conversation.py`
  - `backend/endpoints/messages.py`
  - `backend/ai/__init__.py`

### Stage 3 Unified Evaluation + Structured Benchmarks Rule (2026-02-15)
- Decision/rule: Stage 3 is unified into one evaluation program that returns context and qualitative evaluation together, with structured benchmark references.
- Reason: current flow needed better end-product coherence (agent name in HTML, contextual language/industry extraction, and benchmark-backed recommendations) while avoiding redundant mini-wrappers.
- Enforcement:
  - `ConversationEvaluationProgram` now takes conversation + metadata and returns a single `ConversationEvaluationResult` including `report_language`, `industry`, `agent_name`, qualitative fields, structured benchmarks, and deterministic metrics.
  - `BenchmarkSynthesisProgram` now outputs `list[BenchmarkReference]` (`source`, `quote`, `tactic`, `relevance`) directly.
  - `/api/audits/{audit_id}/generate` always runs benchmark research+synthesis once per audit and reuses the output across all contact evaluations.
  - If benchmark research/synthesis fails, generation continues and Stage 3 receives `None` for benchmark references.
  - HTML renderer now displays structured benchmark cards (source, quote, tactic, relevance) and uses `evaluation.agent_name` for profile naming.
- Affected components:
  - `backend/ai/stage3_conversation_to_feedback.py`
  - `backend/endpoints/audits.py`
  - `backend/html_renderer.py`
  - `scripts/gen_demo_report.py`
  - `HOW_TO_DEVELOP.md`

### Pattern Reuse Log (2026-02-15, Stage 2/3 Refactor)
34. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
    Reused pattern: XML-section prompt structure with explicit operational blocks, guardrails, and output contract language for consistent behavioral control.
35. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/ai.py`
    Reused pattern: direct signature outputs (`str`/typed lists) and anti-hallucination-style constraints to avoid wrapper-heavy post-processing.

## 2026-02-14

### Transcript Inline Editing + Copy UX Rule (2026-02-14)
- Decision/rule: transcript messages in backoffice are interactive by default: click any message bubble to copy, and allow hover pencil editing with a minimal message-level `PUT` endpoint.
- Reason: relay operators need low-friction copy/send loops and quick correction of drafts/inbound text without regenerating full turns.
- Enforcement:
  - Frontend transcript messages are copyable and show an inline visual copied feedback.
  - Frontend shows a hover pencil per persisted message, opens inline editor, and saves with `PUT /api/audits/{audit_id}/contacts/{contact_id}/messages/{message_id}`.
  - Backend exposes a simple update path that validates audit/contact scope and updates only message text (+ contact `updated_at`).
  - "Copy Latest Draft" action is positioned in composer actions (bottom), not in chat header actions.
- Affected components:
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`
  - `backend/endpoints/messages.py`
  - `backend/database.py`

### Email Open-Flow Rule (2026-02-14)
- Decision/rule: `Open Email` has two phases for email contacts: first-turn `mailto` compose (with subject/body), then persisted inbox thread URL override.
- Reason: operators need one-click send for first outbound email, but subsequent follow-ups should reopen the real inbox thread when available.
- Enforcement:
  - `ContactSummary` now exposes `email_link`, `email_subject`, `email_thread_link`, and `requires_email_thread_link`.
  - Backend returns `mailto:` with first outbound body + derived subject only while conversation has the initial turn and no stored thread URL.
  - After additional turns without stored URL, `Open Email` is hidden and UI asks for thread URL.
  - Added endpoint `PUT /api/audits/{audit_id}/contacts/{contact_id}/email-thread-link` to store/clear the manual inbox thread URL.
- Affected components:
  - `backend/endpoints/audits.py`
  - `backend/endpoints/messages.py`
  - `backend/database.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`

### Non-Blocking Audit Creation UX Rule (2026-02-14)
- Decision/rule: creating an audit from the frontend must immediately close the modal and return to home, rendering the new audit card in `initializing` state while background tasks continue.
- Reason: blocking the UI with a modal/overlay during Stage 1 task polling hides operator context and makes long-running discovery feel frozen.
- Enforcement:
  - Frontend now closes the create modal and returns to home immediately on submit.
  - Frontend inserts a temporary optimistic audit card (`initializing`) before waiting for `POST /api/audits`.
  - Once `POST /api/audits` returns, the temporary card is replaced with the persisted `audit_id` card and task tracking is attached.
  - Stage 1 task polling and first-message generation run in background through a dedicated async finalizer.
  - Home cards derive visible status from pending task tracking (`pendingAuditTasks`) until backend refresh completes.
- Affected components:
  - `frontend/static/js/app.js`

### Pattern Reuse Log (2026-02-14, Non-Blocking Create Audit UX)
30. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`, `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: task-first async workflow (`create resource -> queue task -> poll task endpoint`) while keeping UI/API responsive.
31. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
    Reused pattern: status-forward cards in list views with asynchronous refresh after background task completion.
32. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/[locale]/avatars/[id]/page.tsx`
    Reused pattern: close dialog immediately, add optimistic temporary UI entity, then reconcile with the persisted backend entity.
33. Source repo: `/Users/fgoiriz/private/repos/konecta-auditor`
    Source file(s): `/Users/fgoiriz/private/repos/konecta-auditor/backend/html_renderer.py`
    Reused pattern: WhatsApp transcript visual language (`wa-*` shell, bubbles, metadata timing treatment) reused in live transcript before audit generation.

### Step 3 Single-File LLM-First Rule (2026-02-14)
- Decision/rule: Step 3 implementation is consolidated into one file with multiple programs: context extraction, benchmark synthesis, and conversation evaluation.
- Reason: reduce complexity and keep Stage 3 orchestration and contracts in one place.
- Enforcement:
  - Added `backend/ai/stage3_conversation_to_feedback.py` with all Step 3 models and programs.
  - Removed split files:
    - `backend/ai/stage3_context_extraction.py`
    - `backend/ai/stage3_benchmark_synthesis.py`
    - `backend/ai/stage3_conversation_to_rating.py`
  - Updated all imports to use `backend.ai.stage3_conversation_to_feedback`.
- Affected components:
  - `backend/ai/stage3_conversation_to_feedback.py`
  - `backend/ai/__init__.py`
  - `backend/endpoints/audits.py`
  - `backend/ai/stage4_rating_to_dashboard.py`
  - `messenger/audits.py`

### Stage 4 Renderer Placement Rule (2026-02-14)
- Decision/rule: HTML rendering is backend infrastructure, not an AI stage. Keep it outside `backend/ai` and expose it as plain functions, not a `Program`.
- Reason: Stage 4 currently uses deterministic rendering and file persistence only; no LLM behavior is involved.
- Enforcement:
  - Moved renderer module to `backend/html_renderer.py`.
  - Replaced `RatingToDashboardProgram` usage with `build_dashboard_artifact(...)`.
  - Updated endpoint/messenger/script imports to use `backend.html_renderer`.
- Affected components:
  - `backend/html_renderer.py`
  - `backend/endpoints/audits.py`
  - `messenger/audits.py`
  - `scripts/gen_demo_report.py`
  - `backend/ai/__init__.py`

### Step 3 Strict No-Defaults Contract Rule (2026-02-14)
- Decision/rule: Step 3 models expose required fields without implicit defaults, and LLM signatures are responsible for returning the final structured output directly.
- Reason: avoid hidden fallback behavior and keep contracts explicit.
- Enforcement:
  - Removed default values from Step 3 context/evaluation/benchmark models.
  - Removed Step 3 normalization/dedupe/truncation helpers.
  - Kept only deterministic protocol utilities: transcript formatting and timestamp-based metrics computation.
- Affected components:
  - `backend/ai/stage3_conversation_to_feedback.py`

### Pattern Reuse Log (2026-02-14, Step 3 Simplification)
28. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
    Reused pattern: thin `Program.aforward` orchestration with signature-driven output contracts and minimal deterministic post-processing.
29. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/ai.py` (`MessageGenerator`)
    Reused pattern: direct input-to-signature flow where output structure is defined in the signature/model instead of post-transforming generated content.

### Stage 2 Reply-Only Contract Rule (2026-02-14)
- Decision/rule: Stage 2 contract is now reply-only and context-aware:
  - `conversation + objective + company_context -> next reply`
  - `objective + company_context + contact_type -> first message`
- Reason: simplify runtime behavior, remove non-essential signal tracking, and keep `aforward` methods lego-like and easy to reason about.
- Enforcement:
  - Removed signal extraction/state from Stage 2, Stage 3 callers, and messenger contact runtime model.
  - Added `company_context` inputs to Stage 2 reply and first-message signatures and endpoint wiring.
  - Updated AGENTS/skills/docs/frontend embedded README to the reply-only contract.
- Affected components:
  - `backend/ai/stage2_contact_to_conversation.py`
  - `backend/ai/stage3_conversation_to_rating.py`
  - `backend/endpoints/messages.py`
  - `backend/endpoints/audits.py`
  - `messenger/audits.py`
  - `messenger/database.py`
  - `AGENTS.md`
  - `HOW_TO_DEVELOP.md`
  - `README.md`
  - `frontend/static/js/app.js`
  - `.cursor/skills/konecta-auditor-stage-contracts/SKILL.md`
  - `.cursor/skills/konecta-auditor-structured-extraction/SKILL.md`

### Pattern Reuse Log (2026-02-14, Stage 2 Reply-Only Refactor)
26. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
    Reused pattern: one focused program with thin `aforward` orchestration and signature-driven semantics.
27. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/ai.py` (`MessageGenerator`)
    Reused pattern: single-purpose message generation path with deterministic post-processing only for output sanitation.

## 2026-02-13

### Stage 1 Enriched Contact Evidence Rule (2026-02-13)
- Decision/rule: Stage 1 contact extraction input must include enriched evidence (`output_text` + citation snippets + fetched HTML contact fragments from cited URLs), not only the model narrative text.
- Reason: Perplexity narrative outputs can omit concrete contact links present in source HTML (`mailto`, `wa.me`, `api.whatsapp.com`, `tel`, LinkedIn URLs), causing false zero-contact results.
- Enforcement:
  - Build one enriched extraction payload inside `UrlToContactsProgram` before DSPy parsing.
  - Parse citation URLs from structured Perplexity response data and fetch a bounded set of pages.
  - Extract deterministic contact-bearing snippets from fetched HTML and feed them into the existing DSPy structured extractor.
- Affected components:
  - `backend/ai/stage1_url_to_contacts.py`

### Audit Contact Message Contract Rule (2026-02-13)
- Decision/rule: persistence and API contracts are now canonical `audit -> contact -> message`, with `tasks` kept as background job tracking.
- Reason: previous project/thread/conversation naming and metadata fields created duplicated state, unclear ownership, and endpoint clutter.
- Enforcement:
  - Replaced DB entities with `audits`, `contacts`, `messages`, `tasks`.
  - Removed persisted and API-exposed turn metadata fields for reasoning/signal tracking, and removed `StoredTurnMeta`.
  - Removed persisted report path fields from DB and switched audit artifact retrieval to deterministic file path per audit ID.
  - Renamed API routes to `/api/audits/*` and `/api/contacts/*`.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/backoffice.py`
  - `backend/endpoints/conversations.py`
  - `backend/endpoints/__init__.py`
  - `backend/main.py`
  - `frontend/static/js/app.js`
  - `frontend/index.html`
  - `README.md`

### Pattern Reuse Log (2026-02-13, Audit Contact Message Refactor)
21. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: minimal directional message persistence (`from_me`, contact-linked transcript, latest outbound lookup), adapted to `contacts` + `messages` tables and endpoint payloads.
22. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: lean SQLModel helper surface and env-first DB initialization; adapted to audit-focused helpers (`create/get/list/update/delete`) and startup task recovery.
23. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
    Reused pattern: keep DSPy `Program` orchestration minimal and push extraction behavior into signature-driven AI parsing; adapted in Stage 1 by preserving one structured extractor and only enriching its deterministic input context.

### Backoffice Frontend Operator UX Rule (2026-02-13)
- Decision/rule: the backoffice frontend must surface operational context directly in primary views (portfolio metrics, project/thread filtering, and keyboard-first actions) instead of relying on manual scanning.
- Reason: the prior interface was functional but forced excessive visual scanning and repeated clicks, which slows relay operations and increases handoff mistakes.
- Enforcement:
  - Added portfolio metric cards and filter controls in the home view.
  - Added thread-level search/status filters and clearer thread summary counts.
  - Added sidebar current-focus context and keyboard shortcuts (`N`, `R`, `Ctrl/Cmd + Enter`, `Esc`).
  - Added transcript summary, auto-resizing composer, and improved modal/toast accessibility attributes.
- Affected components:
  - `frontend/index.html`
  - `frontend/static/css/style.css`
  - `frontend/static/js/app.js`

### Conversation Endpoint Decoupling Rule (2026-02-13)
- Decision/rule: inbound message orchestration must live in a shared backend service, not inside endpoint handlers or by calling one endpoint function from another endpoint module.
- Reason: importing endpoint handlers across modules couples HTTP routing with business logic and makes `backoffice`/`conversations` harder to simplify and maintain.
- Enforcement:
  - Added `backend/services/contact_message_flow.py` with typed command/result models and shared async orchestration.
  - `backend/endpoints/conversations.py` now acts as thin HTTP mapping only and exposes canonical `/api/conversations/*` plus legacy `/api/contacts/*`.
  - `backend/endpoints/backoffice.py` now calls shared service directly and no longer imports `register_inbound_message` from endpoint modules.
  - Removed unused endpoint `GET /api/audits/{audit_id}/task`.
- Affected components:
  - `backend/services/contact_message_flow.py`
  - `backend/endpoints/conversations.py`
  - `backend/endpoints/backoffice.py`
  - `backend/endpoints/__init__.py`
  - `backend/main.py`

### Backoffice Router Slimming Rule (2026-02-13)
- Decision/rule: keep `backend/endpoints/backoffice.py` focused on HTTP contracts and thin orchestration, and move heavy bootstrap/rescan workflow logic to services.
- Reason: bootstrap/rescan stage orchestration mixed inside route modules made backoffice endpoint code congested and harder to maintain.
- Enforcement:
  - Added `backend/services/audit_bootstrap.py` for fallback company naming, contact seeding, bootstrap flow, and rescan flow.
  - `create_audit` now converts `contacts_override` to `DiscoveredContact` and delegates workflow to service.
  - `rescan_audit` now delegates task execution directly without redundant local variables.
- Affected components:
  - `backend/endpoints/backoffice.py`
  - `backend/services/audit_bootstrap.py`

### Pattern Reuse Log (2026-02-13, Conversation Endpoint Cleanup)
24. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/users.py`, `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/tasks.py`
    Reused pattern: keep endpoint modules thin and focused on request/response mapping while moving reusable orchestration out of route handlers; adapted by extracting shared contact inbound flow into `backend/services/contact_message_flow.py` and reusing it across backoffice and conversation routers.

25. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
    Reused pattern: keep router modules slim and place long-running orchestration in dedicated backend modules; adapted by moving audit bootstrap/rescan internals to `backend/services/audit_bootstrap.py`.

### Database Consistency Rule (2026-02-13)
- Decision/rule: backend persistence helpers must guarantee cleanup consistency for `project -> thread -> conversation -> messages` and recover stale `RUNNING` tasks on startup.
- Reason: deleting only project/thread rows leaves conversation/message/task orphans, and unclean shutdowns leave tasks indefinitely in `RUNNING`, which breaks operator task state.
- Enforcement:
  - `BackofficeProject.delete` now removes related `backoffice_threads`, `conversation_messages`, `conversation_sessions`, and `tasks` rows for the same project scope.
  - `BackofficeThread.count_completed` uses SQL `COUNT` queries instead of loading all rows in memory.
  - Startup `init_db` now calls `mark_running_tasks_as_failed`.
  - DB URL now follows env-first config (`DATABASE_URL`, fallback to local sqlite path).
- Affected components:
  - `backend/database.py`

### Pattern Reuse Log (2026-02-13, Frontend UX Refresh)
18. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/index.html`, `/Users/fgoiriz/private/repos/outbound/frontend/static/css/style.css`, `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
    Reused pattern: single-page sidebar plus detail-pane operator layout, status-forward cards, and lightweight async action wiring; adapted into Konecta with richer metrics, filtering, and keyboard-oriented relay interactions.
19. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: env-first DB configuration and startup reconciliation of stale `RUNNING` tasks; adapted into Konecta backend DB initialization while preserving existing backoffice/conversation contracts.
20. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: explicit directional conversation persistence lifecycle hygiene (conversation/message integrity); adapted into Konecta project deletion by cascading cleanup for thread-linked conversation/message rows.

## 2026-02-12

### Backoffice Project/Thread Contract Rule (2026-02-12)
- Decision/rule: implement backoffice state as explicit `project -> thread -> conversation` entities in backend persistence, while keeping Stage contracts untouched.
- Reason: operator workflow requires project list/detail, independent thread status (`active/completed`), and deterministic thread-level locking/reopen behavior without channel automation in core runtime.
- Enforcement:
  - Added backoffice tables and DB helpers: `backoffice_projects`, `backoffice_threads`.
  - Added backoffice API surface under `/api/backoffice/*` for project creation, thread transcript/inbound/status actions, and project audit generation/retrieval.
  - Backoffice thread inbound path reuses existing agnostic conversation ingestion (`register inbound -> persist inbound + generate/persist outbound`) and enforces completed-thread lock unless explicitly reopened.
  - Project audit endpoint composes Stage 3 per thread plus Stage 4 dashboard artifact generation.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/backoffice.py`
  - `backend/endpoints/__init__.py`
  - `backend/main.py`

### Backoffice Frontend Rule (2026-02-12)
- Decision/rule: root frontend should operate as a human-in-the-loop backoffice app (projects, threads, transcript relay, and audit preview/download), not only a lab payload runner.
- Reason: the production operating model now relies on manual send/receive with backend as transcript + draft source of truth.
- Enforcement:
  - Replaced frontend with backoffice UI including:
    - project portfolio + project detail,
    - per-thread transcript view,
    - copy latest draft,
    - inbound registration form,
    - WhatsApp quick action (`wa.me`) for WhatsApp contacts,
    - thread status toggle (`active`/`completed`),
    - project-level Stage 3 + Stage 4 audit preview/download panel.
- Affected components:
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`

### Skill Pack Alignment Rule (2026-02-12)
- Decision/rule: all repo skills under `.cursor/skills/` must align with the agnostic backend runtime and `messenger/` transport split.
- Reason: stale skill instructions reintroduced deprecated `/api/audits/*` and backend-bound delivery behavior.
- Enforcement:
  - Stage/validation skills now target `/api/lab/*` + `/api/conversations/*`.
  - Delivery/email skills now explicitly scope to `messenger/`.
  - Workflow/development-method skills now enforce backend channel-agnostic runtime separation.
- Affected components:
  - `.cursor/skills/konecta-development-method/SKILL.md`
  - `.cursor/skills/konecta-auditor-stage-contracts/SKILL.md`
  - `.cursor/skills/konecta-auditor-structured-extraction/SKILL.md`
  - `.cursor/skills/konecta-auditor-llm-first-extraction/SKILL.md`
  - `.cursor/skills/konecta-auditor-pattern-reuse/SKILL.md`
  - `.cursor/skills/konecta-auditor-endpoint-e2e/SKILL.md`
  - `.cursor/skills/konecta-auditor-docker-prod-validation/SKILL.md`
  - `.cursor/skills/konecta-auditor-db-forensics/SKILL.md`
  - `.cursor/skills/konecta-auditor-delivery-outbox/SKILL.md`
  - `.cursor/skills/konecta-auditor-email-delivery/SKILL.md`
  - `.cursor/skills/konecta-auditor-workflow/SKILL.md`

### New Skill: Backoffice Human Loop (2026-02-12)
- Decision/rule: add a dedicated skill documenting the manual operator workflow for backoffice conversation relay.
- Reason: architecture changed from channel-automated flow to human-in-the-loop operations, so future agents need one canonical workflow reference.
- Enforcement:
  - Added `.cursor/skills/konecta-auditor-backoffice-human-loop/SKILL.md`.
  - Added matching agent metadata at `.cursor/skills/konecta-auditor-backoffice-human-loop/agents/openai.yaml`.
- Affected components:
  - `.cursor/skills/konecta-auditor-backoffice-human-loop/SKILL.md`
  - `.cursor/skills/konecta-auditor-backoffice-human-loop/agents/openai.yaml`

### Backend Agnostic Split Rule (2026-02-12)
- Decision/rule: keep `backend/` strictly channel-agnostic (FastAPI + DB + DSPy stages), and move transport/orchestration integrations (Prefect, Gmail/SMTP, WhatsApp) to `messenger/`.
- Reason: channel runtime coupling made endpoint and startup logic heavy; transport concerns must be externalized so inbound/outbound channel IO can be controlled outside core audit logic.
- Enforcement:
  - Remove channel listeners and Prefect flow wiring from backend startup.
  - Replace audit-run transport endpoints with minimal agnostic conversation endpoints:
    - create conversation context,
    - register inbound contact message (save + generate + save),
    - fetch latest AI outbound message.
  - Keep stage lab endpoints as isolated stage validators.
- Affected components:
  - `backend/main.py`
  - `backend/endpoints/conversations.py`
  - `backend/endpoints/lab.py`
  - `backend/database.py`
  - `messenger/`
  - `docker-compose.yml`

### Stage 2 Contract Alignment Rule (2026-02-12)
- Decision/rule: Stage 2 output must be canonical with reply, completion, and metadata fields.
- Reason: this contract is required for clean handoff into Stage 3 and for storing transport-agnostic turn metadata in conversation persistence.
- Enforcement:
  - Update `ConversationTurnResult` to canonical fields.
  - Add LLM-first signal extraction mini-program in Stage 2 and deterministic signal normalization.
  - Persist Stage 2 metadata on outbound AI messages in DB.
- Affected components:
  - `backend/ai/models.py`
  - `backend/ai/stage2_contact_to_conversation.py`
  - `backend/endpoints/conversations.py`
  - `backend/database.py`

### Pattern Reuse Log (2026-02-12, Agnostic Refactor)
13. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`, `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: lean FastAPI startup + explicit DB model helper methods (`create`, `get_by_id`, list/get latest), adapted into the new minimal conversation session/message persistence and router wiring.
14. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: conversation history persisted as directional messages (`from_me`) with deterministic retrieval of latest outbound response; adapted for channel-agnostic `conversation_messages` + `latest-ai` endpoint.
15. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/index.html`, `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`, `/Users/fgoiriz/private/repos/outbound/frontend/static/css/style.css`
    Reused pattern: single-page backoffice layout with sidebar project navigation + detail panes + async polling/action wiring; adapted into Konecta’s project/thread relay UI and audit preview.
16. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: explicit directional message persistence and idempotent inbound handling conventions; adapted through thread-level inbound ingestion rules and transcript rendering metadata.
17. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
    Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/frontend/services/api/config.ts`
    Reused pattern: centralized base-URL-aware frontend API client wrapper; adapted to static backoffice `apiFetch` with normalized base URL and consistent error extraction.

## 2026-02-08

### Endpoint Contract Hygiene Rule (2026-02-08)
- Decision/rule: endpoint request models must not expose no-op controls that are ignored by the runtime stage pipeline.
- Reason: dead request fields create API/UI drift and add clutter without behavioral value.
- Enforcement:
  - Remove `max_pages` from Stage 1 lab request and audit run request when Stage 1 implementation does not consume it.
  - Keep frontend Stage 1 payload aligned with endpoint schema (send only `url`).
- Affected components:
  - `backend/endpoints/lab.py`
  - `backend/endpoints/audits.py`
  - `frontend/static/js/app.js`

### Database Slimming Rule (2026-02-08)
- Decision/rule: `contacts` should persist only minimum ongoing-conversation state (`ongoing_thread_ref`, `last_outbound_external_id`) and derive channel metadata in API state responses.
- Reason: duplicated channel/subject fields increased write paths without adding routing value, making DB code noisier and harder to maintain.
- Enforcement:
  - Remove redundant persisted fields: `ongoing_channel_type`, `ongoing_channel_value`, `ongoing_subject`, `last_inbound_external_id`.
  - Replace `update_progress` + `update_ongoing_channel` with one `Contact.update_state(...)`.
  - Remove unused research DB helpers (`Research.get_runs_output`, `Run.get_all`) to keep method surface tight.
  - Keep response contract stable by deriving `ongoing_channel_type/value` in `build_run_state`.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/audits.py`

### Stage 2 Zen Refactor Rule (2026-02-08)
- Decision/rule: Stage 2 must use one signature-driven mini-program to produce the conversation draft, while `ContactConversationProgram` keeps only deterministic protocol gates (`max_auditor_turns`, canonical completion stop reasons).
- Reason: keep Stage 2 small and context-proof by delegating semantic inference to typed LLM outputs and removing hand-written heuristic reply trees.
- Enforcement:
  - Use `ConversationTurnGeneratorProgram` as the only semantic extraction/generation path.
  - Keep deterministic logic limited to signal normalization/order and stop-condition protocol handling.
  - Validate with stage contract tests and endpoint E2E tests.
- Affected components:
  - `backend/lab/stage2_contact_to_conversation.py`
  - `tests/test_stage2_contact_to_conversation.py`

### Pattern Reuse Log (2026-02-08, Stage 2 Zen Refactor)
9. Source repo: `/Users/fgoiriz/private/repos/bogan`
   Source file(s): `/Users/fgoiriz/private/repos/bogan/src/ai/query_generator.py`
   Reused pattern: single `Program` with one DSPy signature returning a typed model (`ChainOfThought` + Pydantic output) and minimal orchestration glue in `aforward`; adapted to Stage 2 by replacing dual-path logic with one turn-draft mini-program.
10. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/ai.py`
    Reused pattern: concentrate behavioral instructions in signature prompts and keep runtime orchestration lean; adapted to Stage 2 by moving reply strategy into signature instructions and reducing manual branching in stage logic.
11. Source repo: `/Users/fgoiriz/private/repos/outbound`
    Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/database.py`
    Reused pattern: keep persistence modules narrow by retaining only methods exercised by endpoints and avoiding redundant data storage; adapted by removing unused research helpers and slimming `contacts` conversation metadata.
12. Source repo: `/Users/fgoiriz/private/repos/inmobot`
    Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
    Reused pattern: persist only provider IDs needed for deterministic dedupe/thread continuity; adapted by keeping just `ongoing_thread_ref` and `last_outbound_external_id` for channel routing state.

## 2026-02-07

### Email Loop Rule (2026-02-07)
- Decision/rule: for contacts with `channel_type=email`, the system must bootstrap the first outbound message immediately, persist email thread metadata as the ongoing channel in `contacts`, and continue the conversation through inbound email ingestion until completion.
- Reason: email contacts need parity with other channels in the production audit loop, with explicit DB state for listener routing and deterministic continuation.
- Enforcement:
  - Use `process_contact_turn()` for all message ingestion via unified `POST /api/audits/runs/{run_id}/contacts/{contact_id}/messages`.
  - Persist `ongoing_channel_type/value/thread_ref` plus last inbound/outbound external IDs on each turn.
  - Keep duplicate suppression by `external_id`.
  - Email listener (`backend/email_listener.py`) resolves contacts and calls `process_contact_turn` internally.
  - Validate with `tests/test_email_flow.py`.
- Affected components:
  - `backend/main.py`
  - `tests/test_email_flow.py`

### Pattern Reuse Log (2026-02-07, Email Loop)
8. Source repo: `/Users/fgoiriz/private/repos/inmobot`
   Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/main.py`, `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
   Reused pattern: idempotent inbound message processing using provider external IDs plus persisted conversation state before/after response generation; adapted for audit email ingestion (`message_id` dedupe), ongoing channel threading metadata, and outbound reply persistence in `messages`.

### Pattern Reuse Log (2026-02-07, Lab Frontend Harness)
7. Source repo: `/Users/fgoiriz/private/repos/outbound`
   Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`, `/Users/fgoiriz/private/repos/outbound/frontend/index.html`
   Reused pattern: FastAPI-served static frontend (`FRONTEND_DIR`, `/static` mount, root `FileResponse`) with a single-page request runner; adapted into a lab stage harness UI that exercises each `/api/lab/*` endpoint for isolated `Program.aforward` testing.

### Lab Frontend UX Rule (2026-02-07)
- Decision/rule: lab endpoint harness must be form-first (inputs, dropdowns, checkboxes, add/remove rows) and must not require raw JSON editing for normal stage validation.
- Reason: the lab UI is meant to accelerate stage-level experimentation, not to replicate manual API clients.
- Enforcement:
  - Keep generated JSON as read-only preview for debugging/auditability.
  - Keep dynamic editors for repeated structures (`conversation`, signal lists, Stage 4 profiles/evaluations).
- Affected components:
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `frontend/static/css/style.css`

## 2026-02-06

### Stable Architecture Rules
- Enforce stage-first architecture with explicit typed contracts.
- Keep Stage 3 independent from Stage 2 internals.
- Make later stages consume prior outputs as explicit fields, never by internal execution.
- Keep AI logic in `Program.aforward` stage modules and keep infrastructure adapters thin.

### Structured Extraction Rule
- Prefer DSPy signature-driven extraction and Pydantic outputs.
- Avoid regex/manual parsing for semantic extraction.
- Use small extraction mini-programs for field-level parsing tasks.

### E2E Validation Rule
- Run endpoint-based multi-turn audit E2E.
- Include manual completion control via `had_enough_override` and `reply_override`.
- Require run completion, evaluation persistence, report generation, and delivery status.

### Docker Validation Rule
- Validate against Docker Compose stack (backend + Traefik), not only local TestClient.
- Confirm artifacts persist to host `data/` mount.

### Delivery Rule
- Treat SMTP success and outbox fallback as valid delivery outcomes.
- Require delivery proof per run (`delivery_status` and outbox artifact when fallback is used).

### Forensics Rule
- Verify `audit_runs`, `contacts`, and `messages` after E2E.
- Correlate API state with persisted DB rows before closing tasks.

### Skill System Added
Created/updated reusable skills under `.cursor/skills`:
- `konecta-development-method`
- `konecta-auditor-stage-contracts`
- `konecta-auditor-structured-extraction`
- `konecta-auditor-pattern-reuse`
- `konecta-auditor-endpoint-e2e`
- `konecta-auditor-docker-prod-validation`
- `konecta-auditor-db-forensics`
- `konecta-auditor-delivery-outbox`
- `konecta-auditor-memory-persistence`
- `konecta-auditor-workflow`

### Pattern Reuse Anchors
- `outbound`: FastAPI + Docker Compose + Traefik baseline.
- `bogan`: DSPy base/program conventions.
- `inmobot`: channel/provider integration patterns.
- `simple-avatar`: migration/frontend organization references.

### New Rule: LLM-First Semantic Extraction
- Decision/rule: semantic inference (language, agent identity, industry, qualitative insight extraction) must use DSPy structured mini-programs, not manual keyword maps or regex heuristics.
- Reason: manual parsing is brittle and diverges from stage contract quality requirements.
- Enforcement:
  - Added skill `/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-llm-first-extraction/SKILL.md`.
  - Added this skill to `AGENTS.md` skill pack order.
  - Updated `HOW_TO_DEVELOP.md` non-negotiable rules.
- Affected components:
  - `backend/lab/stage3_context_extraction.py`
  - `backend/lab/stage3_benchmark_synthesis.py`
  - `backend/main.py` Stage 3 orchestration glue

### Pattern Reuse Log (2026-02-06)
1. Source repo: `/Users/fgoiriz/private/repos/outbound`
   Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/deep_research.py`, `/Users/fgoiriz/private/repos/outbound/backend/main.py`
   Reused pattern: provider-backed research call (`pro_search`) + structured response extraction in API glue; adapted for benchmark references that feed Stage 3 recommendations.
2. Source repo: `/Users/fgoiriz/private/repos/inmobot`
   Source file(s): `/Users/fgoiriz/private/repos/inmobot/backend/main.py`
   Reused pattern: prioritize human identity fields from conversation/channel context and propagate them to user-facing output; adapted through Stage 3 context mini-program for agent names.
3. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
   Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/backend/endpoints/core.py`
   Reused pattern: keep language as an explicit field through generation pipeline; adapted to pass `language` from context extraction into evaluation and dashboard rendering.

### Stage 4 Executive UI Rule (2026-02-06)
- Decision/rule: dashboard HTML must prioritize CEO recognition and agent-level accountability:
  - evaluated agents (real names + profile images) first,
  - per-agent review cards with channel-native transcript UI (WhatsApp/Gmail),
  - expert benchmark references embedded inside each agent review (not in a global block),
  - no numeric score/rating panels.
- Reason: leadership trust increases when identities are immediately recognizable and justification is attached to each individual assessment.
- Enforcement:
  - `backend/lab/stage4_rating_to_dashboard.py` renders per-agent expert basis blocks and channel-themed transcript shells.
  - `tests/test_stage4_rating_to_dashboard.py` asserts agent-by-agent order and expert basis presence.
- Affected components:
  - `backend/lab/stage4_rating_to_dashboard.py`
  - `tests/test_stage4_rating_to_dashboard.py`

### Pattern Reuse Log Addendum (2026-02-06)
4. Source repo: `/Users/fgoiriz/private/repos/outbound`
   Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/static/css/style.css`
   Reused pattern: citation/blockquote card treatment (clean bordered cards, subtle hover/elevation, compact metadata chips); adapted into per-agent expert reference cards in Stage 4.

### Stage 4 Consolidation Rule (2026-02-07)
- Decision/rule: keep a single Stage 4 HTML renderer and endpoint (`/api/lab/stage4`) as the canonical artifact path.
- Reason: remove duplicate HTML variants and simplify the pipeline surface so every flow generates one deterministic report type.
- Enforcement:
  - Remove alternate Stage 4 renderer/module and route.
  - Keep only `RatingToDashboardProgram` wired in pipeline and FastAPI.
  - Keep demo script writing one HTML artifact.
- Affected components:
  - `backend/lab/stage4_rating_to_dashboard.py`
  - `backend/lab/pipeline.py`
  - `backend/main.py`
  - `frontend/static/js/app.js`
  - `scripts/gen_demo_report.py`
  - `tests/test_frontend_lab_ui.py`

### Pattern Reuse Log Addendum (2026-02-07, Stage 4 Consolidation)
5. Source repo: `/Users/fgoiriz/private/repos/outbound`
   Source file(s): `/Users/fgoiriz/private/repos/outbound/frontend/static/js/app.js`
   Reused pattern: expose a single canonical workflow entry in frontend endpoint catalogs to avoid overlapping variants; adapted by removing the extra Stage 4 variant entry and keeping one Stage 4 route.

### Prod-Only Naming Rule (2026-02-06)
- Decision/rule: remove legacy test-oriented nomenclature from production audit flow. API, DB tables, statuses, and artifacts must use audit/prod naming.
- Reason: endpoint-level test injection is a harness, not a separate product path.
- Enforcement:
  - API routes moved from legacy run paths to `/api/audits/runs`.
  - SQL tables moved to `audit_runs`, `contacts`, and `messages`.
  - Delivery statuses normalized to `email_sent`, `outbox`, `outbox_fallback`.
  - Removed obsolete customer-flow skill folder.
- Affected components:
  - `backend/database.py`
  - `backend/main.py`
  - `tests/test_audit_e2e.py`
  - `.cursor/skills/konecta-auditor-endpoint-e2e/SKILL.md`
  - `.cursor/skills/konecta-auditor-db-forensics/SKILL.md`
  - `.cursor/skills/konecta-auditor-delivery-outbox/SKILL.md`
  - `AGENTS.md`

### Pattern Reuse Log Addendum (2026-02-06, Prod Naming)
6. Source repo: `/Users/fgoiriz/private/repos/outbound`
   Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`, `/Users/fgoiriz/private/repos/outbound/backend/database.py`
   Reused pattern: production-first endpoint/resource naming (`/api/.../runs`) and neutral persistence table names (`runs`) without legacy test-domain wording; adapted to `/api/audits/runs` + `audit_*` tables.

### Audits.py Simplification (2026-02-08)
- Decision/rule: keep `backend/endpoints/audits.py` as a single file with both endpoints and business logic, aggressively simplified to ~460 lines from ~830.
- Reason: zen-of-development "keep code small enough to fit in one head" + "prefer deletion over complexity accumulation".
- Techniques applied:
  - Inlined single-use functions: `complete_contact_if_needed`, `build_benchmark_query`, `dedupe_keep_order`, `build_overall_summary`, `build_contact_state`, `bootstrap_email_contact`.
  - Removed field-by-field copy in `finalize_audit_run` since `run_stage3` already returns `ConversationEvaluationResult`.
  - Merged duplicate fallback returns in `extract_contact_context`.
  - Compressed `parse_signals` to single return expression.
  - Compressed imports, reduced blank lines, removed section comments.
- Rule: do not re-introduce helper functions for logic that is only called once. Inline instead.
- Affected components:
  - `backend/endpoints/audits.py`

### Minimal Audit Flow Contract (2026-02-14)
- Decision/rule: simplify backend and frontend to a minimal 4-step operational flow:
  1) create audit from URL and persist contacts,
  2) explicit endpoint to generate first messages,
  3) single inbound endpoint to persist inbound + generate/persist next reply,
  4) generate report from current conversations without completion gating.
- Reason: reduce endpoint/API/UI complexity and remove dead controls that were adding friction (`contacts_override`, `max_contacts`, rescan, contact completion states, task polling, `had_enough`, `stop_reason`).
- Enforcement:
  - Backend routes reduced to audit-scoped endpoints only.
  - Frontend creation flow performs two explicit sequential requests (`POST /api/audits` then `POST /api/audits/{id}/first-messages`).
  - Stage 2 contract now excludes completion semantics and returns only a generated reply.
  - Docs/skills/AGENTS updated to match new contracts.
- Affected components:
  - `backend/endpoints/audits.py`
  - `backend/main.py`
  - `backend/endpoints/__init__.py`
  - `backend/ai/stage2_contact_to_conversation.py`
  - `backend/database.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `README.md`
  - `HOW_TO_DEVELOP.md`
  - `AGENTS.md`
  - `.cursor/skills/konecta-*/SKILL.md`

### Pattern Reuse Log Addendum (2026-02-14, Minimal Flow)
7. Source repo: `/Users/fgoiriz/private/repos/outbound`
   Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
   Reused pattern: split workflow into explicit sequential endpoints (resource creation first, follow-up execution endpoint second) instead of one overloaded endpoint with hidden background orchestration.

### Endpoint Module Split Rule (2026-02-14)
- Decision/rule: keep endpoint layer split into 2 files maximum for this backend:
  - `backend/endpoints/audits.py`: audit lifecycle (create/list/detail/delete, first-messages, generate, artifact),
  - `backend/endpoints/messages.py`: per-contact transcript retrieval and inbound message loop.
- Reason: preserve readability and ownership boundaries without spreading logic across many files.
- Enforcement:
  - `backend/endpoints/__init__.py` only re-exports routers.
  - `backend/main.py` mounts both routers.
- Affected components:
  - `backend/endpoints/audits.py`
  - `backend/endpoints/messages.py`
  - `backend/endpoints/__init__.py`
  - `backend/main.py`

### Inbound Async Task Polling (2026-02-14)
- Decision/rule: `POST /api/audits/{audit_id}/contacts/{contact_id}/messages/inbound` must enqueue reply generation and return `task_id`; completion must be checked through a dedicated poll endpoint.
- Reason: keep UI responsive and show "AI writing..." while Stage 2 is running, without blocking request/response on one long call.
- Enforcement:
  - Use `backend.database.Task.run_async(...)` for task scheduling/state tracking.
  - Persist task state in `tasks` table (`queued`, `running`, `completed`, `failed`) instead of in-memory maps.
  - Added general polling endpoint `GET /api/tasks/{task_id}` (implemented in `backend/endpoints/tasks.py`).
  - Frontend submits inbound, polls `/api/tasks/{task_id}`, then refreshes transcript via the existing messages endpoint when completed.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/messages.py`
  - `backend/endpoints/tasks.py`
  - `frontend/static/js/app.js`

### Pattern Reuse Log Addendum (2026-02-14, Inbound Async Poll)
8. Source repo: `/Users/fgoiriz/private/repos/outbound`
   Source file(s): `/Users/fgoiriz/private/repos/outbound/backend/main.py`
   Reused pattern: create-background-task endpoint returning `task_id` plus dedicated task-status polling endpoint; adapted to contact inbound message generation flow.

## 2026-02-14

### Stage 4 Profile Contract Simplification Rule (2026-02-14)
- Decision/rule: remove image URL concerns from Stage 4 profile contract; `EmployeeAuditProfile` now carries only identity/contact/evaluation data.
- Reason: avatar URL generation/fallback logic was unnecessary complexity for the current audit workflow.
- Enforcement:
  - Removed `profile_image_url` and `profile_image_fallback_url` from `EmployeeAuditProfile`.
  - Removed Gravatar/UI-avatar URL construction and fallback wiring from backend and messenger audit generation flows.
  - Dashboard avatar rendering now always uses initials fallback (no external image fetch).
- Affected components:
  - `backend/ai/stage4_rating_to_dashboard.py`
  - `backend/ai/stage3_context_extraction.py`
  - `backend/endpoints/audits.py`
  - `messenger/audits.py`
  - `scripts/gen_demo_report.py`

### Frontend Inbound Concurrency Rule (2026-02-14)
- Decision/rule: inbound reply generation state in the frontend must be tracked per contact/thread (`thread_id -> task_id`), never with a single global pending task flag.
- Reason: a global pending state blocks all contacts while one reply is generating, breaking operator parallel workflow.
- Enforcement:
  - Store pending inbound tasks in a per-thread map in frontend state.
  - Disable inbound composer only for the active thread when that thread has a pending task.
  - Run task polling in background per thread and refresh the project when each task completes.
- Affected components:
  - `frontend/static/js/app.js`

### Pattern Reuse Log Addendum (2026-02-14, Frontend Inbound Concurrency)
9. Source repo: `/Users/fgoiriz/private/repos/simple-avatar`
   Source file(s): `/Users/fgoiriz/private/repos/simple-avatar/frontend/app/[locale]/avatars/[id]/page.tsx`
   Reused pattern: per-item async tracking (`Set`/collection keyed by item id) so concurrent polling/generation can proceed independently; adapted to `thread_id -> task_id` map for contact-level inbound generation.

## 2026-03-08

### CRM Inbox Becomes First-Class Backend Aggregate + Top-Level Frontend Workspace (2026-03-08)
- Decision/rule:
  - CEO report-delivery follow-up must live in dedicated CRM persistence (`crm_threads`, `crm_email_messages`) and a top-level `CRM` frontend workspace, separate from audit contact transcripts.
  - Gmail inbound processing must resolve CRM threads first by `gmail_thread_id`, then fall back to the normal contact transcript flow only when CRM does not claim the message.
  - Opening a CRM thread must mark current inbound CRM messages as read and clear the global unread badge.
  - Manual CRM replies are created immediately as backend `pending` outbound rows and rendered optimistically in the frontend while the bot sends them on the next worker tick.
  - CRM inbox ordering must follow latest message activity, not `last_read_at` mutations.
- Reason:
  - the repo already had partial backend/bot CRM pieces, but the frontend workspace wiring was missing, unread/read behavior was incomplete in practice, and the inbox could reorder incorrectly after `mark-read`.
  - the real DB also showed audit deliveries that had not been backfilled into CRM yet, which meant the new inbox would appear empty despite real sent CEO report emails.
- Enforcement:
  - updated frontend:
    - `frontend/static/js/app.js` now loads `/api/crm/threads` and `/api/crm/threads/{id}`,
    - persists `section=audits|crm` plus `crm_thread=<id>` URL state,
    - renders the CRM inbox list/detail/composer,
    - marks threads read on open,
    - shows the global unread badge,
    - queues manual replies from the CRM composer.
  - updated backend:
    - `backend/endpoints/crm.py` now sorts inbox responses by latest message timestamp instead of raw thread `updated_at`.
  - updated bot:
    - `bot/utils.py` now correctly marks Gmail messages as read after CRM inbound persistence because the CRM-first branch no longer skips the final read-mark step.
  - updated tests:
    - `backend/tests/test_crm.py`
    - `bot/tests/test_crm_flow.py`
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source files:
    - `/Users/fgoiriz/private/repos/inmobot/backend/database.py`
  - reused pattern:
    - directional message history as first-class persistence, adapted here into `CrmThread` + `CrmEmailMessage` with explicit inbound/outbound CRM timeline semantics.
  - source repo: `/Users/fgoiriz/private/repos/outbound`
  - source files:
    - `/Users/fgoiriz/private/repos/outbound/frontend/index.html`
  - reused pattern:
    - explicit top-level workspace navigation instead of burying alternate flows inside one detail screen; adapted here into persistent `Audits | CRM` navigation with URL-driven section state.
- Affected components:
  - `backend/endpoints/crm.py`
  - `backend/tests/conftest.py`
  - `backend/tests/test_crm.py`
  - `bot/utils.py`
  - `bot/tests/test_crm_flow.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

### SQLite CLI CRM Backfill Rule: Use Stored Enum Names, Not API Values (2026-03-08)
- Decision/rule:
  - when backfilling `crm_email_messages` directly with `sqlite3`, enum columns must use the SQLAlchemy-stored enum member names (`OUTBOUND`, `INBOUND`, `REPORT_DELIVERY`, `MANUAL_REPLY`, `CEO_REPLY`, `PENDING`, `SENT`, `RECEIVED`) instead of the lowercase API payload values.
- Reason:
  - the ORM currently persists enum names in SQLite for these columns, so lowercase direct inserts cause runtime `LookupError` failures when SQLAlchemy reads the rows back.
- Enforcement:
  - for the current dev DB, the one-off SQLite backfill normalized backfilled CRM rows to enum member names before final verification.
  - future ad hoc SQLite CRM backfills must follow that storage format unless the model definitions are explicitly migrated to value-based enum storage.
- Affected components:
  - `data/database.sqlite`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`

## 2026-03-12

### WhatsApp Numbers Must Normalize To Canonical International Digits, Not Raw Local Formatting (2026-03-12)
- Decision/rule:
  - WhatsApp contact normalization must canonicalize local Argentina formats like `(011) 15 5702-2416` into international WhatsApp digits (`5491157022416`) before outbound send and inbound/contact resolution.
  - Backend resolution must not rely exclusively on persisted `contacts.normalized_value`, because older rows may still contain pre-canonical local digits.
- Reason:
  - Meta rejects local-format recipients with error `131009` (`The phone number is malformed`), and reply matching breaks if outbound send uses canonical `549...` while legacy contacts still store `01115...` in `normalized_value`.
- Enforcement:
  - `backend/database.py` canonicalizes WhatsApp-like values with phone parsing and falls back to canonical contact-value comparison when direct `normalized_value` lookups miss.
  - `backend/endpoints/messages.py` uses effective normalized values derived from the stored raw contact value for tracked-values and contact resolution.
  - `bot/providers.py` canonicalizes outbound recipients before calling `pywa`.
  - Regression tests:
    - `backend/tests/test_reportable_contacts.py`
    - `bot/tests/test_whatsapp_inbound_provider.py`
    - `bot/tests/test_whatsapp_template_dispatch.py`
- Pattern reuse log:
  - source repo: `/Users/fgoiriz/private/repos/inmobot`
  - source file(s):
    - `/Users/fgoiriz/private/repos/inmobot/scripts/test_templates.py`
  - reused pattern:
    - WhatsApp template sends should operate on canonical country-code digits (`549...` style), adapted here into backend+bot normalization instead of assuming discovered/stored local formatting is already provider-safe.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/messages.py`
  - `bot/providers.py`
  - `backend/tests/test_reportable_contacts.py`
  - `bot/tests/test_whatsapp_inbound_provider.py`

### Home Reply Filters Must Use Company Summary Booleans, Not Per-Card Detail Fetches (2026-03-12)
- Decision/rule:
  - the audits home view must filter "companies with reply" from a boolean included in the `/api/companies` summary payload, not by fetching each company detail just to inspect contacts/messages client-side.
  - a company counts as having a reply when any of its contacts has at least one inbound message (`from_me = false`), including archived contacts.
- Reason:
  - the home list endpoint did not expose enough message state to filter by replies, and adding N+1 detail fetches from the frontend would make the list slower and more complex.
  - summarizing reply presence in the backend keeps the home filter cheap, deterministic, and aligned with the existing client-side filter pattern.
- Enforcement:
  - updated `backend/database.py` with a deterministic distinct-contact inbound counter for one company.
  - updated `backend/endpoints/companies.py` so `CompanySummary` exposes `has_contact_reply`.
  - updated frontend:
    - `frontend/index.html`
    - `frontend/static/js/app.js`
    - home filters now include a `Replies -> With Reply` chip wired against `has_contact_reply`.
  - updated tests:
    - `backend/tests/test_company_report_schedule.py`
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no sibling repo had an equivalent company-home reply filter pattern
    - repo-local reference reused:
      - `/Users/fgoiriz/private/repos/konecta-auditor/frontend/static/js/app.js`
  - reused pattern:
    - reused the existing repo-local home-filter architecture (`state` + `syncFilterChipGroup` + `getFilteredProjects`) and adapted it to a backend-provided summary boolean instead of adding per-company detail requests.
- Affected components:
  - `backend/database.py`
  - `backend/endpoints/companies.py`
  - `frontend/index.html`
  - `frontend/static/js/app.js`
  - `backend/tests/test_company_report_schedule.py`

### Prompt-Fix-First Rule For LLM Program Behavior Changes (2026-03-12)
- Decision/rule:
  - when a request asks to change the behavior of an existing DSPy/LLM `Program`, the first implementation attempt must be a prompt-layer fix inside the owning Signature/docstring/field descriptions/examples.
  - do not start by modifying Python orchestration, adding semantic prefilters/post-filters, or bolting on heuristic correction logic.
- Reason:
  - most behavior requests are really instruction-quality issues, not architecture issues; fixing them in the Signature keeps stage contracts stable and avoids semantic logic leaking into Python.
  - this preserves the repo's stage-first and LLM-first model, where semantics live in typed contracts and prompt instructions instead of ad hoc glue.
- Enforcement:
  - added skill `.cursor/skills/konecta-auditor-prompt-fix-first/SKILL.md`.
  - registered the skill in `AGENTS.md` and `konecta-development-method` companion load order.
  - documented the repo-level rule in `HOW_TO_DEVELOP.md`.
- Pattern reuse log:
  - source repos searched:
    - `/Users/fgoiriz/private/repos/simple-avatar`
    - `/Users/fgoiriz/private/repos/bogan`
    - `/Users/fgoiriz/private/repos/inmobot`
    - `/Users/fgoiriz/private/repos/outbound`
  - source files reviewed:
    - no sibling repo had an equivalent prompt-fix-first skill or guardrail
    - repo-local references reused:
      - `.cursor/skills/konecta-auditor-llm-first-extraction/SKILL.md`
      - `.cursor/skills/konecta-development-method/SKILL.md`
  - reused pattern:
    - reused the existing repo-local skill structure and guardrail style, but specialized it for prompt-first behavioral fixes on LLM Programs.
- Affected components:
  - `.cursor/skills/konecta-auditor-prompt-fix-first/SKILL.md`
  - `.cursor/skills/konecta-auditor-prompt-fix-first/agents/openai.yaml`
  - `.cursor/skills/konecta-development-method/SKILL.md`
  - `.cursor/skills/konecta-auditor-development-memory/SKILL.md`
  - `AGENTS.md`
  - `HOW_TO_DEVELOP.md`
