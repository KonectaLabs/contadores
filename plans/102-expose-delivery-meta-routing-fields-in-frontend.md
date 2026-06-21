# Plan 102: Expose Delivery Meta Routing Fields In Frontend

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/types.ts src/frontend/src/App.tsx src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py plans/084-enforce-unique-meta-lead-form-routing.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/084-enforce-unique-meta-lead-form-routing.md
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: API-01

## Why This Matters

Delivery sources can route Meta lead form webhooks through `meta_page_id` and `meta_lead_form_id`, and plan 084 hardens uniqueness for that routing. The backend already accepts and returns those fields, but the frontend Delivery source type, draft, editor, and mutation payload omit them.

That means an operator editing a Delivery source in the CRM can save the source without preserving the Meta routing ids, silently breaking lead form webhook routing for that recipient.

## Current State

- Backend accepts the routing fields on source mutations:

```python
src/backend/endpoints/client_leads.py:76
class ClientLeadSourceCommand(BaseModel):
```

```python
src/backend/endpoints/client_leads.py:85
meta_page_id: str | None = None
```

```python
src/backend/endpoints/client_leads.py:86
meta_lead_form_id: str | None = None
```

- Backend returns them in source responses:

```python
src/backend/endpoints/client_leads.py:96
class ClientLeadSourceResponse(BaseModel):
```

```python
src/backend/endpoints/client_leads.py:105
meta_page_id: str
```

```python
src/backend/endpoints/client_leads.py:106
meta_lead_form_id: str
```

- The serializer includes them:

```python
src/backend/endpoints/client_leads.py:332
meta_page_id=source.meta_page_id,
```

```python
src/backend/endpoints/client_leads.py:333
meta_lead_form_id=source.meta_lead_form_id,
```

- The database stores the form id as indexed routing state:

```python
src/backend/database.py:2446
meta_page_id: str = Field(default="")
```

```python
src/backend/database.py:2447
meta_lead_form_id: str = Field(default="", index=True)
```

- Frontend source types omit both fields:

```ts
src/frontend/src/types.ts:440
export interface ClientLeadSource {
```

- Frontend draft and mutation payload omit both fields:

```ts
src/frontend/src/App.tsx:117
type ClientLeadSourceDraft = {
```

```ts
src/frontend/src/App.tsx:139
type ClientLeadSourceMutationPayload = {
```

- Editing an existing source does not preserve the routing ids:

```ts
src/frontend/src/App.tsx:8988
function clientLeadSourceToDraft(source: ClientLeadSource): ClientLeadSourceDraft {
```

```ts
src/frontend/src/App.tsx:9006
function clientLeadSourcePayloadFromDraft(draft: ClientLeadSourceDraft): ClientLeadSourceMutationPayload {
```

- The editor drawer has contact/sheet/template/mapping inputs, but no Meta routing inputs:

```tsx
src/frontend/src/App.tsx:5762
<form className="ct-drawer-panel wide delivery-source-drawer-panel"
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Contract scan | `rg -n "meta_page_id|meta_lead_form_id|ClientLeadSourceDraft|clientLeadSourcePayloadFromDraft" src/frontend/src src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py` | frontend type, draft, payload, UI, and tests preserve Meta routing fields |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |

## Scope

**In scope**:
- Add `meta_page_id` and `meta_lead_form_id` to the frontend `ClientLeadSource` interface.
- Add both fields to `ClientLeadSourceDraft` and `ClientLeadSourceMutationPayload`.
- Preserve existing backend values when opening and saving an existing source.
- Add compact editor inputs for Meta Page ID and Lead Form ID in the Delivery source drawer.
- Keep empty fields as `null` or empty values consistent with the backend command normalization.
- Add or update a focused backend/frontend-adjacent regression if existing test structure can catch source update preservation.

**Out of scope**:
- Enforcing duplicate `meta_lead_form_id`; plan 084 covers uniqueness and routing conflicts.
- Creating or subscribing Meta forms; plans 057 and 058 cover external-write idempotency.
- Redesigning the Delivery source editor layout.
- Changing the public Meta lead webhook endpoint.

## Git Workflow

- Branch: `codex/expose-delivery-meta-routing-fields`
- Commit message: `Expose Delivery Meta routing fields in frontend`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extend TypeScript contracts

Update `ClientLeadSource`, `ClientLeadSourceDraft`, and `ClientLeadSourceMutationPayload` with:

- `meta_page_id`,
- `meta_lead_form_id`.

Use nullable or string types that match the existing `sheet_*` handling pattern.

### Step 2: Preserve values through draft conversion

Update:

- `buildBlankClientLeadSourceDraft`,
- `clientLeadSourceToDraft`,
- `clientLeadSourcePayloadFromDraft`.

Existing source values must round-trip when the operator edits unrelated fields.

### Step 3: Add editor controls

Add two inputs in the Delivery source drawer, probably near the source/sheet section:

- Meta Page ID,
- Meta Lead Form ID.

Keep the UI compact and operational. Do not add explanatory marketing text.

### Step 4: Add validation only if needed

Trim whitespace. Do not over-validate ids unless backend or Meta docs already enforce a simple local rule.

If plan 084 has landed, surface duplicate-form errors returned by the backend through the existing drawer error path.

### Step 5: Verify preservation

Run the contract scan and frontend build.

Run Delivery backend tests so the existing backend contract still accepts and returns the fields.

## Test Plan

- Frontend build/typecheck.
- Delivery backend tests.
- Manual browser check after implementation if the executor changes drawer layout substantially.

## Done Criteria

- [ ] The frontend source type includes Meta routing ids.
- [ ] Existing Meta routing ids are preserved on source edit/save.
- [ ] Operators can view and edit Meta Page ID and Lead Form ID in the Delivery source drawer.
- [ ] Plan 084 uniqueness errors, if present, surface through the existing save error path.

## STOP Conditions

- Product owner does not want operators editing Meta routing ids manually.
- Backend source update semantics overwrite missing fields in a way that requires a backend partial-update redesign.
- Plan 084 changes field names or validation shape before this plan is executed.

## Maintenance Notes

This is contract preservation, not a Meta workflow redesign. Keep the change small and aligned with plan 084.
