# Plan 008: Confirm Campaign Status Changes

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The campaign detail screen can Activate or Pause a campaign with one click. Backend pause/archive status changes can call Meta pause safety logic, and active status makes a public form live. These are production-sensitive actions. The UI already has a confirmation dialog pattern for destructive or high-risk actions; status changes should use it too.

## Current State

- Activate and Pause call `patchCampaignStatus()` directly:

```tsx
src/frontend/src/App.tsx:5091
<button ... onClick={() => void patchCampaignStatus(selectedCampaign, "active")}>Activate</button>
<button ... onClick={() => void patchCampaignStatus(selectedCampaign, "paused")}>Pause</button>
```

- Backend pause can trigger Meta lifecycle behavior:

```python
src/backend/endpoints/campaigns.py:1976
if next_status in {"paused", "archived"} and next_status != current.status:
    try:
        pause_meta_objects_for_campaign(current, actor="operator", source="campaign_api")
```

- `deleteCampaign()` already uses a confirmation dialog in the same component. Follow that local style instead of inventing a new modal.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build/typecheck | `cd src/frontend && npm run build` | exit 0; creates ignored `dist/` |
| Code search | `rg -n "confirm.*Campaign|patchCampaignStatus|setConfirmDialog" src/frontend/src/App.tsx` | shows status changes routed through confirmation |

## Scope

**In scope**:
- `src/frontend/src/App.tsx`
- `src/frontend/src/styles.css` only if existing confirmation styles need a small reusable tweak.

**Out of scope**:
- Backend campaign status semantics.
- Meta pause API behavior.
- Campaign publish/preflight flow.
- Any visual redesign beyond existing confirmation dialog copy.

## Git Workflow

- Branch: `codex/confirm-campaign-status-changes`
- Commit message: `Confirm campaign status changes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a status confirmation helper

Inside `CampaignsPanel`, add a helper such as:

```tsx
function confirmCampaignStatusChange(campaign: LeadCaptureCampaignItem, nextStatus: string) {
  ...
}
```

Use the existing `setConfirmDialog` pattern in this component. The helper should show:

- campaign name,
- current status,
- next status,
- a note for `active`: public form becomes active,
- a note for `paused`: backend may pause known Meta objects and block if Meta cannot confirm.

The confirm action should call `patchCampaignStatus(campaign, nextStatus)`.

**Verify**: code search shows the helper and `setConfirmDialog`.

### Step 2: Route Activate and Pause buttons through confirmation

Change:

```tsx
onClick={() => void patchCampaignStatus(selectedCampaign, "active")}
onClick={() => void patchCampaignStatus(selectedCampaign, "paused")}
```

to call the confirmation helper instead.

Preserve button disabled logic.

**Verify**: frontend build exits 0.

### Step 3: Surface backend blocking errors clearly

`patchCampaignStatus()` likely already catches and passes backend errors through `onError` or local error state. Verify that a 409 from backend pause failure shows a readable message. If not, minimally update the existing error handling inside `patchCampaignStatus()` to surface `reason.message`.

Do not add a new toast system.

**Verify**: frontend build exits 0.

## Test Plan

- `npm run build` for TypeScript.
- Manual code review that direct status mutation buttons are gone.
- Existing delete confirmation pattern remains unchanged.

## Done Criteria

- [ ] Activate requires confirmation.
- [ ] Pause requires confirmation and explains Meta pause blocking behavior.
- [ ] Direct button calls to `patchCampaignStatus(..., "active"|"paused")` are removed.
- [ ] Backend 409 errors remain visible to the operator.
- [ ] `cd src/frontend && npm run build` exits 0.

## STOP Conditions

- `CampaignsPanel` does not own `setConfirmDialog` in the live code anymore.
- Status change confirmation requires a broader campaign lifecycle redesign.
- Frontend build has unrelated TypeScript failures.

## Maintenance Notes

This is deliberately a UI safety confirmation, not a backend permission model. Reviewers should still rely on backend Meta pause blocking for actual spend safety.
