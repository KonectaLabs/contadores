# Frontend Mission

## Codex goal prompt: completion-based elegant CRM/platform redesign

Copy this into Codex Goal mode when you want the frontend sprint to run:

```text
/goal Work on the Contadores frontend/UI until the new frontend concept has been applied end-to-end across the platform. Make it elegant, calm, uncluttered, and easier to operate. The goal is not "more UI"; it is fewer visible main operations, each done very well: CRM, Build, Deliver, and Observe. First research how excellent CRM and productivity products are designed, then define the Contadores frontend concept and apply it to every visible surface and reusable component. This is completion-based, not time-boxed: keep working until the app shell, navigation, primary views, setup/config surfaces, repeated component patterns, states, logs, drawers, modals, tables, forms, mobile layouts, and all four operations have received a deliberate pass under the new concept. Stop only after the app is stable, verified, and reported with a clear component coverage ledger.
```

## Non-negotiable direction

- Do not create a feature wall.
- Do not expose 40 functions at once.
- Do not add information just because the backend has it.
- Do not get inspiration from yourself. Research first, cite what influenced the work, then design.
- The app should feel like an elegant operating system for the agency, not a random admin panel.
- The default view should show only the important few things: what needs attention, what is running, what is blocked, and the next action.
- Everything else should be available through clear expansion, details, drawers, tabs, or drill-downs.
- Logs should be readable by a human first. Raw logs can exist, but they should be secondary and collapsed.

## Main operations

Design around four main operations maximum:

1. `CRM`: leads, replies, WhatsApp conversation state, sequence progress, manual attention, urgency, next best action, meeting path, and conversion controls.
2. `Build`: Workstation clients, assets, notes, Codex work, delivery artifacts.
3. `Deliver`: client lead sheets, WhatsApp delivery, retries, copy/audit.
4. `Observe`: Ops, Runner, blockers, agents, Meta readiness, human-readable logs.

The current code may still use `crm`, `workstation`, `delivery`, `ops`, and `runner`, but the UI should feel like these four understandable operations.

## Completion boundary

This mission is not done because a timer expired. It is done only when the new frontend concept has been carried through the whole product.

Before broad edits, define the concept in plain terms:

- operating model: what the four operations are and how an operator moves through them
- visual system: type, spacing, color roles, icons, density, surface rules, and motion rules
- component language: how buttons, tabs, pills, tables, panels, drawers, modals, forms, logs, empty states, loading states, and error states should look and behave
- mobile model: how the same concept reflows without horizontal overflow, clipped controls, or hidden primary actions

Then apply that concept across all current frontend surfaces:

- app shell, navigation, section headers, command/action areas, and global error/status presentation
- CRM: lead queues, lead cards/rows, chat timeline, message states, conversion controls, Workstation handoff, and sequence/follow-up context
- Build: Workstation client list, client detail, assets/media, notes, generated artifacts, Codex actions, professional photo flow, solo-page/photo modals, drawers, and CRM/Delivery links
- Deliver: delivery contact groups, source editor, sheet lead tables, delivery status pills, copy controls, retry/audit context, and recipient chat context
- Observe: action queue, Runner panel, Meta readiness, blockers, campaigns, inventory, agent activity, meetings, client updates, assets, event stream, and raw log disclosure
- setup/config and send surfaces: setup view/banner, funnel editor drawer, runtime config drawer, send modal, and bulk send modal
- reusable patterns and states: buttons, icon buttons, forms, filters, tabs, tables, timelines, panels, status pills, empty/loading/error/selected/disabled/focus/hover/active states

Keep a component coverage ledger while working. Every row should say what changed, what was intentionally left alone, what was verified, and what still carries risk.

## Research requirement

Before coding, do a real research pass and write a short research ledger in the thread.

Research at least:

- 10 CRM or relationship-management products:
  - Attio: https://attio.com
  - Folk: https://www.folk.app
  - Pipedrive: https://www.pipedrive.com
  - Close: https://www.close.com
  - HubSpot Sales Hub: https://www.hubspot.com/products/sales
  - Copper: https://www.copper.com
  - Affinity: https://www.affinity.co
  - Salesforce Sales Cloud: https://www.salesforce.com/sales/
  - Monday CRM: https://monday.com/crm
  - Zoho CRM: https://www.zoho.com/crm/
- Review sources for what users praise or hate:
  - G2: https://www.g2.com/categories/crm
  - Capterra: https://www.capterra.com/customer-relationship-management-software/
  - Product Hunt when relevant: https://www.producthunt.com
- High-taste product/design references:
  - Apple Human Interface Guidelines: https://developer.apple.com/design/human-interface-guidelines/
  - Apple Icons: https://developer.apple.com/design/human-interface-guidelines/icons
  - Linear Method: https://linear.app/method
  - Dieter Rams principles: https://www.vitsoe.com/us/about/good-design
  - Nielsen Norman Group heuristics: https://www.nngroup.com/articles/ten-usability-heuristics/
  - NN/g progressive disclosure: https://www.nngroup.com/articles/progressive-disclosure/
  - Material Design: https://m3.material.io/
  - Adobe Spectrum: https://spectrum.adobe.com/
  - Shopify Polaris: https://polaris.shopify.com/
  - Atlassian Design System: https://atlassian.design/
- Codex/frontend guidance:
  - OpenAI Codex prompting/goals docs.
  - OpenAI Codex frontend/Figma workflow docs.
  - Local `design-taste-frontend` skill.
  - Local `build-web-apps:frontend-app-builder` skill.
  - Local `build-web-apps:frontend-testing-debugging` skill.
  - Local `build-web-apps:react-best-practices` skill.
  - Local `browser:control-in-app-browser` skill.

The research ledger must answer:

- What do the best CRMs hide by default?
- What do they make instantly visible?
- How do they show activity and logs without overwhelming the user?
- How do they use color, icon, shape, and spacing instead of text?
- What do reviews complain is cluttered, slow, confusing, or too complex?
- Which patterns are worth copying for Contadores?
- Which patterns should be avoided because they are enterprise bloat?

Known research leads to include:

- Attio: object/list/view model and compact record pages; good reference for flexible CRM data without visible clutter.
- Linear: not a CRM, but a strong reference for command menus, fast ops UX, peek previews, lists, keyboard-driven work, and quiet hierarchy.
- Close: daily work inbox, follow-ups, tasks, missed messages, calling/SMS context, and lead timeline.
- Pipedrive: pipeline-first clarity, stage visualization, activity reminders.
- Folk: lightweight contact-first CRM, groups, tags, table/pipeline views.
- Affinity: relationship intelligence and automatic activity capture.
- Copper/Streak: useful only for Google/Gmail-native workflow patterns.
- HubSpot/Salesforce/Monday/Zoho: study for power and as anti-patterns for feature sprawl, setup burden, reporting complexity, and enterprise clutter.

Known CRM patterns worth considering:

- One main work queue: "needs action now" before charts.
- Saved views over raw tables.
- Compact record summary plus human timeline.
- Side panels and peek previews instead of forced full navigation.
- Always show next action, last touch, status, source, owner/system, stale risk.
- Opinionated defaults first; customization only after the default path works.
- Automatic activity capture where possible.
- Human event log lines instead of raw JSON, stack traces, or payload dumps.

Known CRM review pitfalls to avoid:

- Complicated UI.
- Ineffective reporting.
- Too many setup steps.
- Poor integrations.
- Slow performance.
- Feature sprawl.
- Flexible systems that become "build your own CRM" work.
- Pipeline simplicity that becomes too shallow for later operations.

## Design mental framework

Use these filters before every UI change:

- `Less, but better`: remove or collapse anything that does not help the current decision.
- `Progressive disclosure`: show the main path first; reveal expert controls only when needed.
- `Recognition over recall`: users should not have to remember where things are or what a status means.
- `One screen, one job`: every surface needs one dominant job and one obvious next action.
- `Information scent`: icons, labels, color, and placement should make the next click predictable.
- `Human logs`: logs should read like a concise operating narrative, not terminal noise.
- `Calm hierarchy`: important items should stand out because everything else is quiet.
- `Operational elegance`: this is a work tool, so beauty must make repeated use faster, not just prettier.

Use validation frameworks:

- Opportunity Solution Tree: desired outcome -> user/operator opportunities -> possible UI solutions -> assumption tests.
- HEART/GSM: define the UX goal, signal, and metric before claiming the redesign is better.
- RICE or value/effort only after evidence exists; lower confidence when a change is taste-only.
- Browser QA: screenshot, console health, interaction proof, desktop/mobile viewports, mismatch ledger.

## Logs and observability

Replace noisy log presentation with human-readable event summaries wherever possible.

Good log rows answer:

- what happened
- why it matters
- current state
- next action
- owner or system
- time

Default log views should show:

- priority events
- blockers
- recent successful milestones
- current running process
- next recommended action

Raw logs, markdown history, payloads, traces, and full error bodies should be behind disclosure.

## UI rules

- Top-level navigation should have no more than four primary operations.
- Default views should not start with more than five major blocks.
- Prefer icon buttons with tooltips for familiar actions.
- Use words only where words reduce ambiguity.
- Use color semantically and consistently: ok, warning, danger, active, waiting, running, muted.
- Never rely on color alone.
- Prefer rows, rails, timelines, command bars, split panes, and tables over generic card grids.
- Avoid nested cards.
- Keep the important action visually dominant.
- Keep secondary actions quieter or grouped behind a menu.
- Keep forms calm: label above input, helper/error below, clear focus state.
- Empty states should tell the operator what to do next, not explain the whole product.
- Loading states should match the layout shape, not generic spinners everywhere.
- Mobile must reflow without horizontal overflow or clipped controls.

## Source files to inspect

- `AGENTS.md`
- `FRONTEND_MISSION.md`
- `MISSION.md`
- `README.md`
- `src/frontend/package.json`
- `src/frontend/src/App.tsx`
- `src/frontend/src/styles.css`
- `src/frontend/src/types.ts`
- `src/frontend/src/api.ts`
- `src/frontend/src/format.ts`
- `src/backend/main.py`
- `src/backend/endpoints/contadores.py`
- `src/backend/endpoints/workstation.py`
- `src/backend/endpoints/client_leads.py`
- `src/backend/endpoints/platform.py`
- `.codex/skills/*`
- `wiki/skills/*`

## Work loop

1. Research first and write the research ledger.
2. Inspect the current frontend live and in code.
3. Capture baseline screenshots for CRM, Build, Deliver, Observe, setup/config drawers, send/bulk send modals, Workstation modals, and mobile.
4. Audit clutter: too many visible controls, duplicated actions, weak hierarchy, noisy copy, raw logs, unhelpful metrics, card overuse, text clipping, mobile overflow.
5. Define the design system before broad edits: type, spacing, color roles, icon rules, buttons, status, tables, drawers, modals, empty states, log rows.
6. Improve the app shell and top-level operation model first.
7. Improve the four operations in priority order: CRM, Build, Deliver, Observe, then setup/config and send surfaces.
8. After each covered surface, run the app, inspect in Browser, click the relevant flow, capture evidence, and fix visible issues before moving on.
9. Keep a progress ledger: focus, source inspiration, change shipped, screenshot/command evidence, remaining risk.
10. Keep iterating until the component coverage ledger shows that every current frontend surface and reusable pattern received a deliberate pass under the new concept.
11. Finish only from a stable state: build passes, changed flows are verified in Browser, desktop/mobile layouts are checked, console health is reviewed, and the final report explains what changed and what remains risky.

## Success criteria

- The platform has four or fewer visible main operations.
- Each operation has one clear job and one obvious next action.
- Default screens show less information but more meaning.
- Important information is visible; secondary information is expandable.
- Logs are readable in human language by default.
- Raw logs and technical details are still available but hidden behind disclosure.
- CRM, Build, Deliver, Observe, shared shell, drawers, modals, tables, timelines, forms, and responsive layouts share one visual system.
- App shell, navigation, primary views, repeated component patterns, and UI states share the same frontend concept.
- Every current frontend surface has a component coverage ledger entry.
- Text is shorter and more operational.
- Icons, color, shape, and spacing communicate more of the UI.
- No visible overlap, clipped controls, awkward wrapping, or mobile horizontal overflow.
- All covered surfaces have loading, empty, error, selected, disabled, focus, hover, and active states where applicable.
- Browser QA covers desktop and mobile for every covered primary surface.
- Console has no relevant unexplained errors.
- `cd src/frontend && npm run build` passes.
- If this becomes a product change, commit on `main`, push, deploy, and verify the real server according to repo policy.

## Verification commands

```bash
cd /Users/fgoiriz/private/repos/contadores
rtk git status
cd src/frontend && npm run build
```

For local rendered QA:

```bash
cd /Users/fgoiriz/private/repos/contadores
PYTHONPATH=src uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
cd src/frontend && npm run dev
```

Then use the in-app Browser for screenshots, console health, interaction proof, and desktop/mobile checks.

## Stop or escalate

Ask Facundo only when continuing would be risky:

- credentials are missing
- a live production write needs explicit approval
- a destructive migration or data deletion is required
- an unclear business decision affects product behavior
- real WhatsApp, Meta, or Google side effects are needed for verification

Otherwise make a reasonable assumption, write it down, and keep moving.

## Final report

The final report must include:

- research sources used and what was copied/adapted
- the frontend concept that guided the pass
- the component coverage ledger for every primary surface and reusable pattern
- what changed for each primary operation
- what was removed, hidden, or simplified
- how logs became more human-readable
- screenshots or clear Browser verification notes
- commands run
- browser/device viewports checked
- console health
- core interactions verified
- deploy status and server verification when applicable
- remaining risks or next slices
