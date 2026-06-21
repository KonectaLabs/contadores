# Plan 007: Guard Frontend Delivery Request State

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/package.json src/frontend/package-lock.json`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Delivery UI can load rows and recipient chat for multiple sources that share a contact. The current request cancellation only prevents loading flags and errors from being committed after unmount; the async helpers still write `deliveryLeads` and `deliveryRecipientChat` from whichever request resolves last. A slow previous selection can briefly show another customer's leads or chat history in the active Delivery view.

## Current State

- `loadDeliveryLeadsForSources()` writes state unconditionally:

```tsx
src/frontend/src/App.tsx:628
const loadDeliveryLeadsForSources = useCallback(async (sourceIds: string[]) => {
  if (!sourceIds.length) {
    setDeliveryLeads([]);
    return;
  }
  const batches = await Promise.all(sourceIds.map((sourceId) => fetchDeliveryLeads(sourceId)));
  setDeliveryLeads(batches.flat().sort(compareClientLeads));
}, [fetchDeliveryLeads]);
```

- `loadDeliveryRecipientChat()` writes state unconditionally:

```tsx
src/frontend/src/App.tsx:637
const loadDeliveryRecipientChat = useCallback(async (sourceId: string) => {
  const payload = await apiFetch<ClientLeadRecipientChatResponse>(
    `/api/client-lead-sources/${encodeURIComponent(sourceId)}/recipient-chat`,
  );
  setDeliveryRecipientChat(payload);
}, []);
```

- The effect has a local cancellation flag, but it calls helpers that commit state internally:

```tsx
src/frontend/src/App.tsx:842
let cancelled = false;
...
Promise.all([
  loadDeliveryLeadsForSources(sourceIds),
  loadDeliveryRecipientChat(source.id),
])
```

- There is an existing request-id pattern for lead detail:

```tsx
src/frontend/src/App.tsx:644
const loadDetail = useCallback(async (leadId: string) => {
  const requestId = detailRequestId.current + 1;
  detailRequestId.current = requestId;
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build/typecheck | `cd src/frontend && npm run build` | exit 0; creates ignored `dist/` |
| Frontend source grep | `rg -n "deliveryRequestId|recipientChatRequestId|loadDeliveryLeadsForSources|loadDeliveryRecipientChat" src/frontend/src/App.tsx` | shows guarded helpers |

## Scope

**In scope**:
- `src/frontend/src/App.tsx`
- `src/frontend/package.json` and lockfile only if you add tests, but prefer no new test dependency in this plan.

**Out of scope**:
- Backend Delivery endpoints.
- Visual redesign of the Delivery panel.
- Adding frontend testing infrastructure. That is a separate plan, not this one.

## Git Workflow

- Branch: `codex/guard-frontend-delivery-requests`
- Commit message: `Guard frontend Delivery request state`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add Delivery request ids

Near the existing refs:

```tsx
const detailRequestId = useRef(0);
const dashboardRequestId = useRef(0);
...
const deliverySourcesRef = useRef<ClientLeadSource[]>([]);
```

add:

```tsx
const deliveryLeadsRequestId = useRef(0);
const deliveryRecipientChatRequestId = useRef(0);
```

**Verify**: `rg -n "deliveryLeadsRequestId|deliveryRecipientChatRequestId" src/frontend/src/App.tsx` shows the refs.

### Step 2: Guard Delivery leads state

In `loadDeliveryLeadsForSources`, increment the request id before any await. Capture the requested source ids as a stable signature, for example:

```tsx
const requestId = deliveryLeadsRequestId.current + 1;
deliveryLeadsRequestId.current = requestId;
const sourceKey = sourceIds.join("|");
```

Only call `setDeliveryLeads(...)` if:

- `deliveryLeadsRequestId.current === requestId`, and
- the current selected source/group still maps to the same `sourceKey`.

Keep the empty-source case guarded too: clearing `deliveryLeads` should only happen for the latest request.

Use the existing `deliverySourcesRef` and `selectedDeliverySourceId` carefully. If adding those dependencies makes the helper unstable, keep the guard request-id based and let the caller validate selection before calling.

**Verify**: frontend build exits 0.

### Step 3: Guard recipient chat state

Apply the same request-id pattern to `loadDeliveryRecipientChat(sourceId)`.

Only call `setDeliveryRecipientChat(payload)` if this is still the latest recipient-chat request and the selected source has not changed.

When changing selected source, clear `deliveryRecipientChat` before loading the next one so stale chat is not shown under a loading state.

**Verify**: frontend build exits 0.

### Step 4: Guard auto-sync refresh

The auto-sync effect calls:

```tsx
await Promise.all([
  loadDeliverySources(),
  loadDeliveryLeadsForSources(sourceIds),
  loadDeliveryRecipientChat(selectedDeliverySourceId),
]);
```

Make sure the new guards also protect this path. Do not add duplicate state writes in the effect.

**Verify**: frontend build exits 0.

## Test Plan

- Build/typecheck through `npm run build`.
- Manual code review of request-id guards against the existing `loadDetail()` pattern.
- No browser QA required for this plan unless the operator asks for implementation and verification together.

## Done Criteria

- [ ] Delivery leads cannot be overwritten by an older request after a source change.
- [ ] Delivery recipient chat cannot be overwritten by an older request after a source change.
- [ ] Loading/error behavior remains readable.
- [ ] `cd src/frontend && npm run build` exits 0.
- [ ] No unrelated UI refactor is included.

## STOP Conditions

- Guarding correctly requires splitting Delivery state into a new hook/module.
- The current `selectedDeliverySourceId` lifetime makes it impossible to compare selection reliably inside callbacks without a broader refactor.
- Frontend build reveals existing unrelated TypeScript failures.

## Maintenance Notes

This plan intentionally avoids adding a frontend test framework. A later plan should add regression tests for source switching, but this safety fix can be reviewed against the existing request-id pattern in `loadDetail()`.
