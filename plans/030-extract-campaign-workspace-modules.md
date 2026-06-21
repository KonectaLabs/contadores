# Plan 030: Extract Campaign Workspace Modules

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/types.ts src/frontend/src/styles.css src/frontend/package.json src/frontend/package-lock.json`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/021-add-frontend-regression-coverage.md, plans/029-split-frontend-app-shell-by-workspace.md
- **Category**: architecture
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Ads/Campaigns workspace combines graph helpers, geo targeting, creative uploads, delivery contacts, public form fields, and publish controls. More Ads features will be expensive and risky until those concerns are separated into readable modules.

## Current State

- `CampaignsPanel` owns a large state surface:

```tsx
src/frontend/src/App.tsx:3436
function CampaignsPanel({ refreshSignal, onError }: { refreshSignal: number; onError: (message: string) => void }) {
  const [campaigns, setCampaigns] = useState<LeadCaptureCampaignItem[]>([]);
  const [clients, setClients] = useState<CampaignClientItem[]>([]);
  ...
```

- Creative upload/paste UI and form builder live in the same component:

```tsx
src/frontend/src/App.tsx:4760
onPaste={handleCampaignCreativePaste}

src/frontend/src/App.tsx:4844
<section className="campaign-create-section campaign-section-form">
```

- Geo search is nearby but not isolated from campaign creation:

```tsx
src/frontend/src/App.tsx:3402
function addFirstSuggestion(event: KeyboardEvent<HTMLInputElement>) {
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend tests | `cd src/frontend && npm test -- --run` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Extract campaign graph helpers.
- Extract geo targeting controls.
- Extract creative upload/media controls.
- Extract public form field builder.
- Extract delivery contact configuration.

**Out of scope**:
- Changing campaign API payloads.
- Redesigning the Ads workspace.
- Adding public presentation fields; plan 033 covers that.
- Changing Meta publish semantics.

## Git Workflow

- Branch: `codex/extract-campaign-workspace`
- Commit message: `Extract campaign workspace modules`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Move pure helpers first

Move pure campaign helper functions to a `campaigns` helper file and add targeted tests where plan 021 made that practical.

Do not move hooks or stateful UI in the same commit if the helper extraction is large.

### Step 2: Extract visual subcomponents

Extract components in this order:

1. Geo targeting section.
2. Creative media section.
3. Form field builder.
4. Delivery contacts section.
5. Meta graph editor.

Keep props explicit. If a prop list becomes too long, group related state into a small named object rather than passing everything individually.

### Step 3: Keep API calls centralized

Do not scatter `apiFetch` calls across many nested components unless they already own that behavior. Prefer passing actions down from the workspace container.

### Step 4: Verify after each extraction group

Run frontend tests and build after the pure helper extraction and after all component extraction.

## Test Plan

- Frontend regression tests.
- Frontend build.
- Manual Ads smoke: list campaigns, create draft, edit form fields, upload/remove media, geo search.

## Done Criteria

- [ ] Campaigns workspace is split into readable modules.
- [ ] API payloads and response shapes are unchanged.
- [ ] Public form fields, creative media, geo targeting, and delivery contacts still work.
- [ ] Frontend tests and build exit 0.

## STOP Conditions

- Existing campaign behavior is not covered enough to extract safely.
- Component extraction requires changing the campaign data model.

## Maintenance Notes

This plan should reduce future Ads feature risk. It is not a UI redesign.
