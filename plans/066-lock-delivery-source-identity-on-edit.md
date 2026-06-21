# Plan 066: Lock Delivery Source Identity On Edit

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DELIVERY-05

## Why This Matters

Editing a Delivery source should update the original source. Today the frontend chooses POST versus PUT by looking for the edited draft id in the current source list. If the operator edits the source id, saving can create a new source instead of updating the original, duplicating polling and delivery setup.

## Current State

- Save builds a payload from the editable draft id:

```tsx
src/frontend/src/App.tsx:1074
const payload = clientLeadSourcePayloadFromDraft(deliverySourceDraft);
```

- Existing-source detection uses the edited id:

```tsx
src/frontend/src/App.tsx:1075
const existingSource = deliverySources.find((source) => source.id === payload.id);
const method = existingSource && deliveryEditorMode === "edit" ? "PUT" : "POST";
```

- The draft id is editable and slugified:

```tsx
src/frontend/src/App.tsx:9006
function clientLeadSourcePayloadFromDraft(draft: ClientLeadSourceDraft): ClientLeadSourceMutationPayload {
```

- Backend PUT ignores `command.id` and updates the URL source id:

```python
src/backend/endpoints/client_leads.py:1297
@client_leads_router.put("/{source_id}", response_model=ClientLeadSourceResponse)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Source save scan | `rg -n "saveDeliverySource|deliveryDraftSourceId|clientLeadSourcePayloadFromDraft" src/frontend/src/App.tsx` | edit identity is anchored to the original source |

## Scope

**In scope**:
- Use the originally selected source id when saving in edit mode.
- Decide whether source ids are immutable in the UI or require a separate explicit rename flow.
- Add a backend/frontend test for edit mode with a changed draft id.

**Out of scope**:
- Changing Delivery polling behavior.
- Migrating existing duplicated sources.
- Reworking source config storage.

## Git Workflow

- Branch: `codex/lock-delivery-source-identity`
- Commit message: `Lock Delivery source identity on edit`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Anchor edit saves to the opened source

Use `deliveryDraftSourceId.current` or `selectedDeliverySourceId` as the source id for PUT when `deliveryEditorMode === "edit"`.

Do not choose POST just because the draft id changed.

### Step 2: Make id editing explicit

Prefer disabling the source id input in edit mode. If renaming source ids is needed, make it a separate confirmed action because it affects imported rows and polling identity.

### Step 3: Add a regression test

Add coverage that:

- opens an existing source,
- changes the draft id,
- saves,
- sends `PUT /api/client-lead-sources/{original_id}` or blocks id changes,
- does not create a second source.

### Step 4: Preserve create mode

Create mode should still POST with the draft id or slugified label.

## Test Plan

- Frontend build passes.
- Delivery backend tests pass.
- New frontend or component-level coverage passes if available.

## Done Criteria

- [ ] Edit mode cannot accidentally create a duplicate source by changing the id.
- [ ] Create mode still creates new sources.
- [ ] The UI communicates source-id immutability or explicit rename semantics.
- [ ] Verification commands pass.

## STOP Conditions

- Existing production workflow depends on editing ids inside the normal edit form.
- Imported leads cannot be associated correctly after id immutability.
- The backend needs a schema migration to support the chosen behavior.

## Maintenance Notes

Treat Delivery source id as an integration identity, not a display field.
