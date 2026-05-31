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
| Triage/Sell states | Replaced visible `Booked` stage with `Converted`; filters now read from conceptual state query params. | Legacy `stage`, `raw_stage`, `booked_at`, and `mark-booked` stay for storage/API compatibility. | `npm run build`, `test_contadores.py`, Browser desktop/mobile. | Backend writes still mutate legacy `stage`; transition engine is not centralized yet. |
| Lead list/detail | Lead rows and detail header now show conceptual labels; More menu uses `Mark converted`. | Strategy stats keep `booked_rate` field name because API/storage still use it. | Browser desktop/mobile; no console errors. | Lead card information hierarchy still needs a copy/density pass. |
| Backend API state projection | Added `pipeline_stage`, `queue_state`, `terminal_state`, `attention_state`, `conversion_type`, metrics, and filters. | No DB enum rename; SQLite stores enum names and legacy tests depend on them. | Full `src/backend/tests/test_contadores.py` passed locally; server API returns new fields. | DB does not persist v2 lifecycle columns yet; projection can still drift if future writes bypass helpers. |
| Setup/config surfaces | Setup callout/token bug fixed while touching CSS. | Funnel editor behavior unchanged. | Build and mobile CSS build checks. | Drawer/forms still need full component-language pass. |
| Send/bulk send modals | Closed-state guards now read `terminal_state` where available. | Modal structure unchanged. | TypeScript build. | Send option hierarchy and empty/error states still need Browser coverage. |
| Build | Client list now distinguishes loading from a true empty converted-client state. | Workstation detail panels, media, notes, Codex controls, and action grouping are unchanged. | `npm run build`, backend tests, Browser desktop and 390px mobile. | Needs dedicated pass for detail panels, artifacts, media, notes, Codex controls, and mobile. |
| Deliver | Sheet rows now render as operational lead cards with mapped identity, delivery status, notification preview, actions, and collapsed raw row fields. | Source editor still stays inline instead of a drawer. Recipient chat structure unchanged. | `npm run build`, backend tests, Browser desktop and 390px mobile empty-contact state. | Needs source editor drawer pass and recipient context with real lead rows on server data. |
| Observe | Ops hero now has explicit loading/no-data states; runner raw logs moved behind clearer technical disclosure. | Existing runner, Meta, event, and agent panels remain structurally intact. | `npm run build`, backend tests, Browser desktop technical disclosure and 390px mobile. | Needs full human-readable event pass and better grouping for platform deep details. |
| Reusable component language | State pills, action menu popovers, scoped tokens, mobile popovers, loading empties, and technical disclosures improved. | Broad legacy CSS remains until a safe deletion pass. Only stale `booked` visual classes/tokens were removed. | `git diff --check`, build, Browser. | Dead legacy CSS and repeated status/button patterns still need cleanup. |
