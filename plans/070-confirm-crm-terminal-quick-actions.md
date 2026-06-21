# Plan 070: Confirm CRM Terminal Quick Actions

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: operator-safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: UI-11

## Why This Matters

Several CRM quick actions are one-click mutations with reporting and automation impact: mark converted, pause automation, send to operator review, close/reopen, and delete. Campaign status changes already have a separate confirmation plan, but these lead-level terminal actions need the same operator-safety treatment.

## Current State

- Quick actions call the backend directly:

```tsx
src/frontend/src/App.tsx:1594
async function runAction(action: QuickActionName) {
```

- The lead action menu exposes terminal or automation-pausing buttons:

```tsx
src/frontend/src/App.tsx:8015
<button ... onClick={onMarkConverted}>
```

```tsx
src/frontend/src/App.tsx:8025
<button ... onClick={onPauseAutomation}>
```

```tsx
src/frontend/src/App.tsx:8053
<div className="ct-action-menu-group">
```

- Backend actions mutate lead lifecycle:

```python
src/backend/endpoints/contadores.py:3593
elif normalized_action in CONVERSION_ACTIONS:
```

```python
src/backend/endpoints/contadores.py:3652
elif normalized_action == "close":
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Contadores action tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "mark_converted or close_and_reopen or pause_automation" -q` | exit 0 |
| Quick-action scan | `rg -n "onMarkConverted|onPauseAutomation|onManualHandoff|onToggleClosed|runAction" src/frontend/src/App.tsx` | terminal actions use confirmation |

## Scope

**In scope**:
- Add confirmation for terminal or automation-impacting CRM quick actions.
- Keep low-risk utility actions, such as copy context, one-click.
- Use existing `ConfirmDialogState` patterns.

**Out of scope**:
- Changing backend action semantics.
- Adding multi-step approval workflows.
- Campaign status confirmation; plan 008 covers campaign status.

## Git Workflow

- Branch: `codex/confirm-crm-terminal-actions`
- Commit message: `Confirm CRM terminal quick actions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Classify actions

Require confirmation for:

- mark converted,
- pause automation,
- operator review/manual handoff,
- close lead,
- reopen lead if it restarts automation-relevant state,
- delete lead.

Leave copy/read-only actions unconfirmed.

### Step 2: Reuse the existing confirm dialog

Use concise messages that name the selected lead and the state change.

Keep busy labels tied to `actionBusy`.

### Step 3: Preserve action handlers

The confirmation should call the existing action handler. Do not duplicate backend request logic in multiple button callbacks.

### Step 4: Verify no double-submit path

Ensure action buttons and dialog buttons are disabled while `actionBusy` is set.

## Test Plan

- Frontend build passes.
- Existing backend action tests pass.
- Manual browser check that terminal buttons open confirmation and only mutate after confirm.

## Done Criteria

- [ ] Terminal CRM quick actions require confirmation.
- [ ] Utility actions remain efficient.
- [ ] Busy states prevent double submit.
- [ ] Frontend build passes.

## STOP Conditions

- Operators explicitly require one-click terminal actions for this CRM.
- Existing confirmation dialog cannot support the needed busy state.
- The delete action already has a separate confirmation path not visible in the scanned code.

## Maintenance Notes

Keep confirmation text short and action-specific. Do not add instructional copy to the main UI.
