# Plan 034: Add Ops Action Queue Surface

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/platform.py src/frontend/src/App.tsx src/frontend/src/types.ts src/frontend/src/api.ts src/frontend/src/styles.css README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/021-add-frontend-regression-coverage.md, plans/029-split-frontend-app-shell-by-workspace.md
- **Category**: product
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The backend already exposes a platform overview read model, and README says the UI Ops tab reads it. The frontend currently has no `ops` section, so blockers and next actions remain scattered across CRM, Ads, Workstation, Delivery, logs, and agent runs.

## Current State

- README documents Ops:

```text
README.md:412
Todas esas llamadas quedan auditadas...
`Ops` lee `/api/platform/overview`
```

- Backend returns overview counts and lists:

```python
src/backend/endpoints/platform.py:972
@platform_router.get("/overview", response_model=PlatformOverviewResponse)

src/backend/endpoints/platform.py:997
return PlatformOverviewResponse(
```

- The frontend only knows four sections:

```tsx
src/frontend/src/App.tsx:91
type ActiveSection = "crm" | "campaigns" | "workstation" | "delivery";
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend tests | `cd src/frontend && npm test -- --run` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Backend platform tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k platform -q` | exit 0 or no tests selected if none exist |

## Scope

**In scope**:
- Add read-only `ops` section to the app shell.
- Add frontend types for `/api/platform/overview`.
- Render active blockers, human questions, blocked Meta attempts, failed agent runs/tool calls, pending campaigns, and recent events.
- Link back to existing CRM/Campaigns/Workstation surfaces when ids are available.

**Out of scope**:
- Mutation buttons.
- Answering human questions from Ops.
- Publishing or pausing campaigns from Ops.
- Changing backend overview response shape unless a small missing field blocks links.

## Git Workflow

- Branch: `codex/add-ops-action-queue`
- Commit message: `Add Ops action queue surface`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add frontend types and loader

Add `PlatformOverviewResponse` and related item types to `src/frontend/src/types.ts`.

Add a loader using `apiFetch("/api/platform/overview")`.

### Step 2: Add `ops` to navigation

Extend `ActiveSection` and stored-section parsing to include `ops`.

Add an Ops navigation item with a concise label and blocker count when loaded.

### Step 3: Build read-only panels

Show:

- active blocker summary,
- open human questions,
- blocked Meta attempts/inventory,
- failed agent runs and tool calls,
- pending campaigns,
- recent platform events.

Use compact tables/lists; this is an operational cockpit, not a landing page.

### Step 4: Link to existing surfaces

Where possible:

- campaign id -> Campaigns tab with selected campaign,
- lead id -> CRM detail,
- workstation client id -> Workstation detail.

If deep-link state is not ready, use plain ids and leave mutation/navigation for a later plan.

### Step 5: Verify

Run frontend tests/build and backend platform tests if present.

## Test Plan

- Frontend regression test for `ops` navigation parsing.
- Frontend build.
- Manual Browser smoke of `/api/platform/overview` rendering.

## Done Criteria

- [ ] `ops` is a first-class read-only app section.
- [ ] `/api/platform/overview` data renders without mutation controls.
- [ ] Existing four sections still work.
- [ ] Frontend tests and build exit 0.

## STOP Conditions

- Backend overview shape lacks required identifiers and adding them would broaden the backend contract.
- Product owner wants Ops to be actionable with mutation controls in the first pass.

## Maintenance Notes

Keep the first Ops surface read-only. It should make operational truth visible before it becomes a control plane.
