# Plan 065: Scope CRM Manual Drafts By Lead

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/package.json`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: UI-07

## Why This Matters

Manual CRM messages and attachments are operator-written content. Today the same draft state is shared by the selected lead dock, the single-send modal, and the bulk-send modal. If the selected lead changes after refresh/filtering, a draft intended for one lead can be sent to another lead or to a bulk selection.

## Current State

- Draft text and files are app-level state:

```tsx
src/frontend/src/App.tsx:423
const [manualText, setManualText] = useState("");
const [manualFiles, setManualFiles] = useState<File[]>([]);
```

- Lead refresh can auto-select a different visible lead:

```tsx
src/frontend/src/App.tsx:572
setSelectedLeadId((current) => {
```

- The selected lead dock uses the shared draft:

```tsx
src/frontend/src/App.tsx:2453
<details className="ct-manual-disclosure" open={Boolean(manualText.trim() || manualFiles.length)}>
```

- The single-send and bulk-send modals also use the same draft:

```tsx
src/frontend/src/App.tsx:2492
{showSendModal ? (
```

```tsx
src/frontend/src/App.tsx:2506
{showBulkSendModal ? (
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Manual state scan | `rg -n "manualText|manualFiles|showSendModal|showBulkSendModal" src/frontend/src/App.tsx` | draft ownership is explicit |
| Frontend tests | command from plan 021, if available | exit 0 |

## Scope

**In scope**:
- Scope manual draft text and file attachments to their intended lead or modal context.
- Clear or preserve drafts deliberately when selection changes.
- Prevent bulk send from reusing a single-lead draft by accident.
- Keep the UI obvious about which lead or selection a draft belongs to.

**Out of scope**:
- Changing backend send endpoints.
- Changing WhatsApp templates.
- Redesigning the CRM layout.

## Git Workflow

- Branch: `codex/scope-crm-manual-drafts`
- Commit message: `Scope CRM manual drafts by lead`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Separate draft owners

Replace the single `manualText`/`manualFiles` pair with one of these simple patterns:

- a per-lead draft map keyed by `lead.id`, plus separate modal drafts,
- or explicit `dockDraft`, `singleSendDraft`, and `bulkSendDraft` state.

Prefer the option that makes the send handlers easiest to read.

### Step 2: Guard selected-lead changes

When `selectedLeadId` changes because the previous lead is no longer visible, do not silently send the old lead's draft through the new lead's dock.

Either keep the old draft stored under the old lead id or clear the dock draft with an operator-visible empty state.

### Step 3: Separate modal state

The single-send modal should initialize from the current lead draft only when opened deliberately.

The bulk-send modal should never inherit attachments from the selected-lead dock.

### Step 4: Reset only after successful sends

Clear the exact draft owner only after the related send succeeds. Failed sends should preserve the draft.

### Step 5: Verify manually if frontend tests are absent

In a local browser:

1. Type a dock draft for lead A.
2. Change filters so lead B is selected.
3. Confirm lead A's draft is not sent to lead B.
4. Open the bulk modal and confirm it does not inherit lead A's files.

## Test Plan

- Frontend build passes.
- Add focused frontend coverage if plan 021 has landed.
- Manual browser verification covers lead selection, single send, and bulk send.

## Done Criteria

- [ ] Manual dock drafts cannot move silently between leads.
- [ ] Single-send and bulk-send modals have separate draft ownership.
- [ ] Failed sends preserve the correct draft.
- [ ] Frontend build passes.

## STOP Conditions

- The current UX intentionally relies on shared draft state across selected lead and bulk modal.
- File attachment handling cannot be scoped without replacing the upload/send contract.
- The frontend cannot be built locally.

## Maintenance Notes

This is a correctness fix, not a messaging redesign.
