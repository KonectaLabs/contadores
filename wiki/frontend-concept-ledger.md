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
| Triage/Sell states | Replaced visible `Booked` stage with `Converted`; filters now read from conceptual state query params; manual conversion calls `mark-converted`; legacy `needs_human` filter now maps to a visible `Operator` queue view; send/manual copy now speaks operator/follow-up language instead of legacy/manual scheduling language. | Legacy `stage`, `raw_stage`, `booked_at`, `mark-booked`, `send-manual-booked`, `send-manual-ping`, and manual attention API names stay for storage/API compatibility. | `npm run build`, `test_contadores.py`, Browser desktop/mobile; Browser desktop Views disclosure showed `Operator` as a visible queue filter. | Backend writes still mutate legacy `stage`; transition engine is not centralized yet. |
| Lead list/detail | Lead rows and detail header now show conceptual labels; More menu uses `Mark converted` and the conceptual quick-action route. | Strategy stats keep `booked_rate` field name because API/storage still use it. | Browser desktop/mobile; no console errors. | Lead card information hierarchy still needs a copy/density pass. |
| Backend lifecycle state | Added `pipeline_stage`, `queue_state`, `terminal_state`, `attention_state`, `conversion_type`, metrics, and filters. The four lifecycle fields are now persisted on `contadores_leads`, refreshed by flow updates, Workstation ownership changes, and message activity, with schema backfill for existing rows. | No DB enum rename; legacy `stage`, `booked_at`, `mark-booked`, and strategy `booked_rate` names stay as compatibility contracts. | `python -m compileall -q src/backend/database.py src/backend/endpoints/contadores.py`; `uv run pytest src/backend/tests/test_contadores.py -q`; `npm run build` from `src/frontend`; server deploy healthy with runtime ready/enabled and lifecycle columns present. | Some external scripts may still speak legacy `booked`, but the durable DB model now carries the frontend concept directly. |
| Setup/config surfaces | Setup callout/token bug fixed while touching CSS. | Funnel editor behavior unchanged. | Build and mobile CSS build checks. | Drawer/forms still need full component-language pass. |
| Send/bulk send modals | Closed-state guards now read `terminal_state` where available. Destructive confirmations now use the shared modal language instead of browser-native `window.confirm`, with shared focus/keyboard behavior. | Send option hierarchy still uses the existing modal structure. | `npm run build`; Browser desktop and 390px mobile confirm modal, focus trap, Escape close, no console errors. | Send option hierarchy and empty/error states still need a deeper pass. |
| Build | Client list now uses human Workstation states; client detail header shows identity, offer, media, and one primary action; Codex/notes/chat/copy/download/close moved into More; run internals moved behind closed Run details; stale/failed run alerts stay visible. | Media, photo, notes, and chat panels keep their current content structure. | `npm run build`, full backend tests, Browser desktop and 390px mobile Build checks with no console errors. | Generated artifact review and Workstation modals still need a deeper pass. |
| Deliver | Sheet rows now render as operational lead cards with mapped identity, delivery status, notification preview, and collapsed raw row fields. Retryable rows now surface in a compact Next actions section; full rows stay behind disclosure by default and healthy rows no longer show disabled Retry noise. Source/contact configuration moved out of the daily view into a drawer, and `Edit source` is disabled when no contact is selected. | Recipient chat structure unchanged. Delivery source API payload stays the same. | `npm run build`; Browser desktop Delivery drawer; Browser 390px mobile drawer with visible create action and no console errors; server deploy healthy. | Still needs recipient context with real lead rows on server data and a deeper save/error-state pass inside the drawer. |
| Observe | Ops hero now has explicit loading/no-data states; runner raw logs moved behind clearer technical disclosure. | Existing runner, Meta, event, and agent panels remain structurally intact. | `npm run build`, backend tests, Browser desktop technical disclosure and 390px mobile. | Needs full human-readable event pass and better grouping for platform deep details. |
| Reusable component language | State pills, action menu popovers, scoped tokens, mobile popovers, loading empties, technical disclosures, confirm modals, and Delivery source drawer sections improved. | Broad legacy CSS remains until a safe deletion pass. Only stale `booked` visual classes/tokens and the dead Delivery inline config panel styles were removed. | `git diff --check`, build, Browser desktop/mobile confirm checks. | Dead legacy CSS and repeated status/button patterns still need cleanup. |
