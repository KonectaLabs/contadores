# Plan 128: Protect Delivery Source Drawer Unsaved Edits

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/066-lock-delivery-source-identity-on-edit.md
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: FRONTEND-19

## Why This Matters

Delivery source edits can change sheet URL, recipient, template, column mapping, Meta routing, and sync behavior. The drawer can be closed or overwritten by selection changes without a dirty-state guard.

Unsaved Delivery source edits need the same protection as other high-impact operator drafts.

## Current State

- Delivery source drawer renders editable config:

```tsx
src/frontend/src/App.tsx:5705
function DeliverySourceEditorDrawer(
```

- Drawer close/cancel paths do not check dirtiness:

```tsx
src/frontend/src/App.tsx:5755
<button className="ct-drawer-overlay" type="button" onClick={onClose}
```

- Draft state syncs from selected source:

```tsx
src/frontend/src/App.tsx:5393
setDeliverySourceDraft(deliverySourceDraftFromSource(source));
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Delivery drawer scan | `rg -n "deliverySourceDraft|DeliverySourceEditorDrawer|setConfigOpen|dirty|onClose|selectedDeliverySourceId" src/frontend/src/App.tsx` | dirty-close and selection-change guards are visible |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Track dirty state for Delivery source drawer edits.
- Confirm before closing, switching source, or overwriting draft state.
- Preserve current save flow and validation.
- Keep the guard focused to Delivery source editing.

**Out of scope**:
- Delivery source identity locking; plan 066 covers identity fields.
- Hidden Delivery sync writes; plan 104 covers sheet sync side effects.
- Campaign Delivery contact config; plan 105 covers campaign recipient writes.

## Git Workflow

- Branch: `codex/protect-delivery-drawer-unsaved-edits`
- Commit message: `Protect Delivery source drawer unsaved edits`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define dirty comparison

Compare normalized draft payload to the selected source payload. Avoid false positives from formatting-only differences.

### Step 2: Guard close and selection changes

When dirty, ask the operator to discard or stay. Use the existing confirmation dialog pattern where possible.

### Step 3: Prevent background overwrites

If source data refreshes while the drawer is dirty, do not blindly overwrite the draft.

### Step 4: Manual verify

Edit a field, close via overlay, switch source, and trigger a refresh. The draft should not disappear without confirmation.

## Test Plan

- Frontend build passes.
- Manual dirty-close and dirty-switch checks pass.

## Done Criteria

- [ ] Dirty Delivery source edits cannot be lost silently.
- [ ] Save still updates the source normally.
- [ ] Background refresh does not overwrite dirty draft state.
- [ ] Confirmation text names the affected source.

## STOP Conditions

- Current drawer architecture makes dirty comparison unreliable without a broader form refactor.
- Operators prefer auto-discard behavior for Delivery source edits.

## Maintenance Notes

High-impact config drawers should protect unsaved edits by default, especially when background refreshes can replace the selected object.
