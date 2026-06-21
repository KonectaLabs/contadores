# Plan 069: Protect Workstation Unsaved Notes On Navigation

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/backend/endpoints/workstation.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: frontend-correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: UI-10

## Why This Matters

Workstation notes are high-value operator artifacts. Today selection changes and some detail refreshes can replace or clear the notes draft from server state without checking whether the operator has unsaved edits.

## Current State

- Notes draft is a single app-level string:

```tsx
src/frontend/src/App.tsx:431
const [workstationNotesDraft, setWorkstationNotesDraft] = useState("");
```

- Detail load syncs notes from the server:

```tsx
src/frontend/src/App.tsx:675
if (syncNotes) {
  setWorkstationNotesDraft(payload.notes ?? "");
}
```

- Client selection clears the draft:

```tsx
src/frontend/src/App.tsx:2155
onSelectClient={(clientId) => {
```

```tsx
src/frontend/src/App.tsx:2160
setWorkstationNotesDraft("");
```

- The notes editor writes directly into that draft:

```tsx
src/frontend/src/App.tsx:6685
value={notesDraft}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Notes state scan | `rg -n "workstationNotesDraft|setWorkstationNotesDraft|syncNotes" src/frontend/src/App.tsx` | dirty-state protection is visible |
| Frontend tests | command from plan 021, if available | exit 0 |

## Scope

**In scope**:
- Track dirty state for Workstation notes.
- Prevent navigation or refresh from discarding unsaved notes without an explicit operator choice.
- Optionally store per-client note drafts so switching clients is safe.
- Preserve existing save endpoint behavior.

**Out of scope**:
- Adding autosave.
- Changing notes storage schema.
- Redesigning the Workstation details page.

## Git Workflow

- Branch: `codex/protect-workstation-unsaved-notes`
- Commit message: `Protect unsaved Workstation notes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Track original notes

Store the last synced notes value alongside the draft, scoped to the current client id.

Compute dirty state by comparing draft to the last synced value.

### Step 2: Protect selection changes

Before changing selected Workstation client, handle dirty notes:

- keep a per-client draft, or
- show a confirmation dialog with save/discard options.

Prefer per-client drafts if it keeps the operator flow faster.

### Step 3: Protect refresh sync

When `loadWorkstationDetail` refreshes the same client, do not overwrite a dirty draft unless the change came from a successful save or the operator chose to discard.

### Step 4: Update UI affordance

Show a subtle dirty state near the Save notes button and disable confusing actions only if needed.

### Step 5: Verify navigation

Manually test:

1. type unsaved notes for client A,
2. switch to client B,
3. return to client A,
4. confirm the draft is preserved or the discard was explicitly confirmed.

## Test Plan

- Frontend build passes.
- Frontend coverage if available.
- Manual browser verification for navigation and polling refresh.

## Done Criteria

- [ ] Unsaved Workstation notes cannot be silently overwritten by selection changes.
- [ ] Detail polling does not overwrite dirty notes.
- [ ] Successful save updates the clean baseline.
- [ ] Frontend build passes.

## STOP Conditions

- The current operator workflow intentionally treats notes as disposable scratch text.
- Dirty-state handling requires broad state-management refactor.
- Confirmation dialogs conflict with existing action-busy flow.

## Maintenance Notes

Prefer an explicit state model over scattered `setWorkstationNotesDraft("")` calls.
