# Plan 175: Smooth Drawer, Modal, And Destructive Confirmation UI

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/172-add-shared-button-press-states-and-hit-areas.md
- **Category**: frontend-ui
- **Planned at**: commit `bf8782e`, 2026-06-21

## Why This Matters

Drawers and modals are high-attention UI. The app already has custom modal/drawer shells and a `ConfirmDialog`, but panels appear abruptly and one campaign delete path still uses the native browser confirm. This plan makes those flows feel cohesive without adding a motion library.

## Current State

- Drawer/modal shells are fixed overlays with no enter/exit transition:

```css
src/frontend/src/styles.css:2817
#contadoresView .ct-drawer,
#contadoresView .ct-modal {
  position: fixed;
  inset: 0;
  z-index: 60;
}
```

- Drawer panel has static placement:

```css
src/frontend/src/styles.css:2833
#contadoresView .ct-drawer-panel {
  position: absolute;
  top: 0;
  right: 0;
```

- Campaign delete still uses native confirm:

```tsx
src/frontend/src/App.tsx:4133
async function deleteCampaign(campaign: LeadCaptureCampaignItem) {
```

- A custom confirmation dialog exists:

```tsx
src/frontend/src/App.tsx:6980
function ConfirmDialog({
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Native confirm scan | `rg -n "window\\.confirm|confirm\\(" src/frontend/src/App.tsx` | no campaign delete `window.confirm` remains |
| Transition scan | `rg -n "transition: all" src/frontend/src/styles.css` | no matches |

## Scope

**In scope**:
- `src/frontend/src/App.tsx`
- `src/frontend/src/styles.css`

**Out of scope**:
- Adding Framer Motion or any motion dependency.
- Rewriting modal focus management.
- Changing delete API behavior.

## Git Workflow

- Branch: `codex/ui-modal-drawer-polish`
- Commit message: `Polish modal and drawer interactions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Replace campaign native confirm

Route campaign delete through the existing `ConfirmDialogState` pattern. Use danger tone and keep the existing delete API call unchanged.

**Verify**: native confirm scan no longer finds campaign deletion using `window.confirm`.

### Step 2: Add CSS-only enter polish

Add overlay/panel transitions using exact properties:

- overlay: `opacity`
- modal panel: `opacity`, `transform` with small `translateY(8px)`
- drawer panel: `opacity`, `transform` with small `translateX(16px)`

Use `cubic-bezier(0.2, 0, 0, 1)` or existing local timing. Do not use `transition: all`.

**Verify**: transition scan has no matches.

### Step 3: Keep exit simple unless state already supports it

Because most modals/drawers conditionally unmount, do not build a large mounted/closing state machine. If exit animation requires broad state changes, stop after enter/interruption polish and report that true exit animation needs a later focused plan.

**Verify**: frontend build exits 0.

## Test Plan

- `cd src/frontend && npm run build`
- Manual check: Delivery source drawer, Funnel editor drawer, Send modal, Workstation modal, campaign delete confirm.

## Done Criteria

- [ ] Campaign delete uses the existing custom confirmation UI.
- [ ] Drawer/modal overlays and panels have subtle CSS transitions.
- [ ] No new motion dependency is added.
- [ ] No `transition: all` is introduced.
- [ ] Frontend build exits 0.

## STOP Conditions

- Replacing native confirm requires changing campaign delete API behavior.
- True exit animation requires broad modal lifecycle rewrites.

## Maintenance Notes

CSS-only enter polish is enough here. Do not create a modal framework.
