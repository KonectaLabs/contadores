# Plan 126: Make Campaign Create Draft Lifecycle Explicit

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: FRONTEND-17

## Why This Matters

The campaign create view keeps draft state after canceling or navigating back to the campaign list. A later create attempt can reuse old client, budget, media, Delivery contacts, form fields, or targeting without the operator realizing it.

Campaign create should have an explicit draft lifecycle: preserve intentionally or reset deliberately.

## Current State

- Create-state hooks live in the campaign workspace:

```tsx
src/frontend/src/App.tsx:3445
const [campaignName, setCampaignName] = useState("");
```

- Opening create view prepares defaults but does not always reset old draft state:

```tsx
src/frontend/src/App.tsx:3716
function openCreateView() {
```

- Reset happens after successful create:

```tsx
src/frontend/src/App.tsx:4062
setCampaignName("");
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Draft lifecycle scan | `rg -n "openCreateView|closeCreateView|setCampaignName|campaignName|creativeAssets|deliveryCustomContacts" src/frontend/src/App.tsx` | create/cancel/reset behavior is explicit |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Add a clear reset function for campaign create draft state.
- Decide when cancel/back/new create resets versus preserves.
- Add a dirty draft confirmation if preserving unsaved work is important.
- Keep successful create reset behavior.

**Out of scope**:
- Draft creative upload persistence/cleanup; plan 127 covers uploaded creative side effects.
- Campaign status confirmation; plan 008 covers status changes.
- Full campaign editor redesign.

## Git Workflow

- Branch: `codex/campaign-create-draft-lifecycle`
- Commit message: `Make campaign create draft lifecycle explicit`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Centralize draft reset

Create one helper that resets every create-draft field, including media, targeting, form schema, Delivery contacts, and Meta options.

### Step 2: Wire cancel and new create

When the operator cancels or opens a new campaign, either reset immediately or confirm discard if the draft is dirty.

### Step 3: Add manual checks

Cancel a partially filled campaign, reopen create, and confirm fields are in the intended state.

## Test Plan

- Frontend build passes.
- Manual cancel/reopen flow no longer carries stale data unexpectedly.

## Done Criteria

- [ ] Campaign create draft reset is centralized.
- [ ] Cancel/back/new-create behavior is deliberate and visible.
- [ ] Old client/media/Delivery fields cannot silently carry into a new campaign.

## STOP Conditions

- Product wants persistent campaign drafts across navigation and needs storage first.
- Resetting draft state would orphan uploaded creative assets without plan 127 or equivalent cleanup.

## Maintenance Notes

Create flows with many fields need one lifecycle owner. Scattered resets are how stale draft bugs come back.
