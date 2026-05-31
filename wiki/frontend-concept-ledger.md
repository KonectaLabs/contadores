# Contadores frontend concept ledger

## Concept

Contadores is an operations console, not a marketing site. The UI should feel
quiet, dense, and repeatable: one shell, five operations, clear ownership of
the next action, and no visible implementation state unless it helps an
operator decide what to do next.

Primary operations:

- Triage: what needs a human now.
- Sell: commercial conversation progress and conversion controls.
- Build: Workstation client work, media, notes, generated artifacts, and Codex.
- Deliver: client lead delivery, source health, recipient context, and retries.
- Observe: runners, blockers, platform events, Meta readiness, and raw logs.

State model:

- `pipeline_stage` is the commercial milestone.
- `queue_state` is who owns the next action.
- `terminal_state` is closed or archived overlay.
- `attention_state` is the urgency signal.
- Legacy `stage` remains a compatibility contract until every backend, bot,
  script, and external tool has moved to the split model.

## Research ledger

- Shopify Polaris empty states
  (https://polaris-react.shopify.com/components/layout-and-structure/empty-state):
  empty views should orient the user, use simple language, and point at one
  primary action.
- Shopify Polaris common actions
  (https://polaris-react.shopify.com/patterns/common-actions): add/edit/copy/delete
  actions should stay near the object they affect, avoid button clutter, and put
  destructive actions at the bottom of action lists.
- Salesforce Lightning data tables
  (https://developer.salesforce.com/docs/component-library/bundle/lightning-datatable/overview):
  record lists can use structured tables, but invalid/uncertain state needs to
  be explicit instead of silently rendering zero-value rows.
- Atlassian foundations (https://atlassian.design/foundations/): shared
  foundations should define tokens, primitives, and panel structure while domain
  surfaces keep contextual freedom.

## Coverage ledger

| Surface | Changed | Left alone intentionally | Verified | Remaining risk |
| --- | --- | --- | --- | --- |
| App shell/navigation | Five-operation shell retained; mobile nav overflow fixed in first state slice. | Existing section names in code remain `crm`, `workstation`, `delivery`, `ops` for compatibility. | Local Browser desktop and 390px mobile; server deploy healthy. | Topbar still needs a full density pass against Build/Deliver/Observe. |
| Triage/Sell states | Replaced visible `Booked` stage with `Converted`; filters now read from conceptual state query params; manual conversion calls `mark-converted`; backend now has canonical `/conversions/mark`, `converted=true`, `converted_at`, and canonical meeting/conversion metric aliases; CRM outbound is now blocked at enqueue time for converted/closed/archived leads while Workstation delivery remains allowed; Calendly webhook now records `meeting_scheduled_at` as a Meeting milestone instead of converting the lead; legacy `needs_human` filter now maps to a visible `Operator` queue view; send/manual copy now speaks operator/follow-up language instead of legacy/manual scheduling language. | Legacy `stage`, `raw_stage`, `booked_at`, `mark-booked`, `send-manual-booked`, `send-manual-ping`, and manual attention API names stay for storage/API compatibility. | `python -m compileall -q src/backend/database.py src/backend/endpoints/contadores.py`; `uv run pytest src/backend/tests/test_contadores.py -q`; `npm run build`; Browser desktop/mobile. | Some legacy scripts still have historical stage names, but active requeue paths now check milestone timestamps too. |
| Agent conversion tools | Codex agent toolbelt now exposes `mark_converted`; agent-facing stage editors reject legacy `booked` so conversions go through the canonical action while storage still preserves `stage=booked`/`booked_at`. | Legacy API aliases and DB enum remain for existing callers and historical rows. | `python -m compileall -q src/backend/ai/codex_agent_tools.py src/backend/tests/test_contadores.py`; `uv run pytest src/backend/tests/test_contadores.py -q`. | Other older scripts may still mention booked in documentation or historical strategy stats. |
| CRM view selector and chat | Stage views are now always visible in the queue bar instead of hidden behind `Views`; the message timeline now uses offset inbound/outbound cards, colored rails, and blue/warm role treatment instead of same-looking green/cream blocks. | Advanced strategy/tag filters stay behind `Filters` because they are secondary to daily triage. Message data, tabs, and send behavior are unchanged. | `npm run build`; Browser local desktop at 1366px with backend data, no horizontal overflow, no `Views` summary, message card rendered with blue outbound treatment. | Needs a second pass with richer inbound/outbound production conversations after deploy. |
| Lead list/detail | Lead rows and detail header now show conceptual labels; More menu uses `Mark converted` and the conceptual quick-action route. Converted lead details now block `Send` and show `Build` instead of asking the operator to convert an already-converted lead. | Strategy stats keep `booked_rate` field name because API/storage still use it. | Browser desktop/mobile; no console errors. | Lead card information hierarchy still needs a copy/density pass. |
| Backend lifecycle state | Added `pipeline_stage`, `queue_state`, `terminal_state`, `attention_state`, `conversion_type`, `meeting_scheduled_at`, metrics, and filters. The lifecycle projection fields are now persisted on `contadores_leads`, refreshed by flow updates, Workstation ownership changes, and message activity, with schema backfill for existing rows. Read-side list metrics, filtering, and summaries now derive the conceptual lifecycle from source milestones instead of trusting possibly stale persisted projection values. Queue-time outbound eligibility now shares the same converted/closed/archived lifecycle decision used by pending delivery. | No DB enum rename; legacy `stage`, `booked_at`, `mark-booked`, and strategy `booked_rate` names stay as compatibility contracts. | `python -m compileall -q src/backend/database.py src/backend/endpoints/contadores.py`; `uv run pytest src/backend/tests/test_contadores.py -q`; `npm run build` from `src/frontend`. | Followup/automation still has source-specific exclusions like Venezuela and opt-out; this slice kept them source-specific instead of blocking every operator path. |
| Setup/config surfaces | Setup now shows a blocker overview first and moves checklist/grid/copy/path into disclosure. Funnel editor keeps identity, enabled, sheet, primary offer, and meeting copy visible while pricing/templates/routing/weights stay behind `Funnel details`. Runtime config keeps only `Enabled` visible and moves meeting URL, alert emails, and strategy weights behind `Advanced controls`. | Config payloads and saved field names stay unchanged. Hidden advanced fields remain editable from the same drawer. | `npm run build`; Browser desktop Triage/Edit funnel/Runtime; Browser 390px drawer disclosure with no horizontal overflow; no console errors. | Setup banner copy still uses compact joined issue text; broader legacy CSS cleanup remains separate. |
| Send/bulk send modals | Closed-state guards now read `terminal_state` where available. Destructive confirmations now use the shared modal language instead of browser-native `window.confirm`, with shared focus/keyboard behavior. | Send option hierarchy still uses the existing modal structure. | `npm run build`; Browser desktop and 390px mobile confirm modal, focus trap, Escape close, no console errors. | Send option hierarchy and empty/error states still need a deeper pass. |
| Build | Client list now uses human Workstation states; client detail header shows identity, offer, media, and one primary action; Codex/notes/chat/copy/download/close moved into More; run internals moved behind closed Run details; stale/failed run alerts stay visible. | Media, photo, notes, and chat panels keep their current content structure. | `npm run build`, full backend tests, Browser desktop and 390px mobile Build checks with no console errors. | Generated artifact review and Workstation modals still need a deeper pass. |
| Deliver | Sheet rows now render as operational lead cards with mapped identity, delivery status, notification preview, and collapsed raw row fields. Retryable rows now surface in a compact Next actions section; full rows stay behind disclosure by default and healthy rows no longer show disabled Retry noise. Source/contact configuration moved out of the daily view into a drawer, and `Edit source` is disabled when no contact is selected. | Recipient chat structure unchanged. Delivery source API payload stays the same. | `npm run build`; Browser desktop Delivery drawer; Browser 390px mobile drawer with visible create action and no console errors; server deploy healthy. | Still needs recipient context with real lead rows on server data and a deeper save/error-state pass inside the drawer. |
| Observe | Ops hero now has explicit loading/no-data states; runner raw logs moved behind clearer technical disclosure. | Existing runner, Meta, event, and agent panels remain structurally intact. | `npm run build`, backend tests, Browser desktop technical disclosure and 390px mobile. | Needs full human-readable event pass and better grouping for platform deep details. |
| Reusable component language | State pills, action menu popovers, scoped tokens, mobile popovers, loading empties, technical disclosures, confirm modals, and Delivery source drawer sections improved. | Broad legacy CSS remains until a safe deletion pass. Only stale `booked` visual classes/tokens and the dead Delivery inline config panel styles were removed. | `git diff --check`, build, Browser desktop/mobile confirm checks. | Dead legacy CSS and repeated status/button patterns still need cleanup. |
