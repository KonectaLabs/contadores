# Plan 104: Make Delivery Sheet Sync Explicit In Frontend

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DELIVERY-01

## Why This Matters

Opening a Delivery source editor currently starts an automatic POST loop against `/sync`. Syncing is not a read-only refresh: the backend can import new sheet rows and queue Delivery notifications. A hidden live-write loop behind navigation can surprise operators and make it hard to reason about when new client notifications became dispatchable.

Delivery sync should be an explicit operator action or clearly labeled auto-sync mode, not an invisible side effect of viewing the Delivery screen.

## Current State

- Entering the Delivery edit view enables an auto-sync effect:

```tsx
src/frontend/src/App.tsx:906
useEffect(() => {
```

```tsx
src/frontend/src/App.tsx:907
if (activeSection !== "delivery" || deliveryEditorMode !== "edit" || !selectedDeliverySourceId) {
```

- The effect POSTs sync for the selected source/contact group:

```tsx
src/frontend/src/App.tsx:914
const autoSyncDelivery = async () => {
```

```tsx
src/frontend/src/App.tsx:926
sourceIds.map((sourceId) => apiFetch(`/api/client-lead-sources/${encodeURIComponent(sourceId)}/sync`, { method: "POST" })),
```

- It runs on an interval and immediately on entry:

```tsx
src/frontend/src/App.tsx:949
const timer = window.setInterval(() => {
```

```tsx
src/frontend/src/App.tsx:953
autoSyncDelivery();
```

- Backend sync imports records and queues valid new notifications:

```python
src/backend/endpoints/client_leads.py:1155
def import_sheet_records(source: ClientLeadSource, records: list[dict[str, str]]) -> ClientLeadSyncResponse:
```

```python
src/backend/endpoints/client_leads.py:1316
@client_leads_router.post("/{source_id}/sync", response_model=ClientLeadSyncResponse)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Sync behavior scan | `rg -n "autoSyncDelivery|/sync|Sync|DELIVERY_AUTO_SYNC" src/frontend/src/App.tsx src/frontend/src/styles.css` | sync is explicit/labeled and not hidden behind view entry |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Delivery backend tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |

## Scope

**In scope**:
- Replace hidden immediate/interval sync with an explicit Sync action, or gate auto-sync behind a visible enabled state.
- Show sync status, last result, and errors in the Delivery UI.
- Keep read-only refreshes separate from POST `/sync`.
- Preserve existing source grouping behavior when syncing multiple source ids for one contact.
- Keep backend sync endpoint behavior unchanged.

**Out of scope**:
- Changing import/deduplication semantics; plans 016, 017, 018, and 019 cover Delivery data consistency.
- Changing recipient/source identity rules; plans 066 and 102 cover source edit contracts.
- Server-target runbook wording; plan 090 covers Delivery verification docs.

## Git Workflow

- Branch: `codex/explicit-delivery-sheet-sync`
- Commit message: `Make Delivery sheet sync explicit`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Split read refresh from write sync

Keep loading Delivery sources/leads/chats as read-only refreshes.

Remove or gate the automatic POST loop so selecting a Delivery source does not immediately import sheet rows.

### Step 2: Add an explicit Sync control

Add a compact Sync button near the Delivery source context. It should:

- be disabled while sync is in flight,
- show success/error state,
- identify when multiple grouped source ids are synced.

### Step 3: Decide auto-sync policy

If auto-sync remains needed, make it visible and controllable. For example:

- a toggle labeled as an active sync mode,
- a clear interval label,
- an obvious busy indicator.

Default should be conservative unless the product owner explicitly wants auto-sync on by default.

### Step 4: Preserve current grouping behavior

Use `deliveryContactSourceIdsFor(...)` so one contact group still syncs all associated sources when the operator asks for sync.

### Step 5: Verify

Run the frontend build and Delivery backend tests. If frontend test infrastructure exists from plan 021, add a focused regression that viewing a source does not POST `/sync` until the Sync action is triggered.

## Test Plan

- Frontend build/typecheck.
- Delivery backend tests.
- Manual browser check that entering Delivery edit view does not silently POST sync.

## Done Criteria

- [ ] Viewing or editing a Delivery source does not silently run a live sync.
- [ ] Operators have an explicit, visible way to sync sheet rows.
- [ ] Sync status/errors are visible in the Delivery UI.
- [ ] Backend sync behavior remains unchanged.

## STOP Conditions

- Product owner requires automatic sheet polling while the Delivery view is open.
- Removing auto-sync would break a documented operational workflow with no replacement control.
- Frontend state cannot distinguish read refresh from write sync without a broader refactor.

## Maintenance Notes

Treat POST `/sync` as a live mutation because it can queue notifications. Keep that distinction visible in the UI.
