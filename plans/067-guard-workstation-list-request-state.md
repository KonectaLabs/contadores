# Plan 067: Guard Workstation List Request State

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/backend/endpoints/workstation.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: frontend-correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: UI-08

## Why This Matters

Workstation detail requests have request-id guards, but list/search loads do not. A slow response from an older funnel or search query can overwrite the current client list and selected client after the operator has already changed filters.

## Current State

- Workstation list loading has no request id:

```tsx
src/frontend/src/App.tsx:581
const loadWorkstation = useCallback(async () => {
```

- The response writes list and selected client immediately:

```tsx
src/frontend/src/App.tsx:592
const payload = await apiFetch<WorkstationClientListResponse>(`/api/workstation/clients?${params.toString()}`);
setWorkstationList(payload);
```

- Detail loading already has a guard:

```tsx
src/frontend/src/App.tsx:660
const loadWorkstationDetail = useCallback(async (clientId: string, options: LoadWorkstationDetailOptions = {}) => {
```

- The backend list endpoint supports funnel and query filters:

```python
src/backend/endpoints/workstation.py:4204
@workstation_router.get("/clients", response_model=WorkstationClientListResponse)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Request guard scan | `rg -n "workstation.*RequestId|loadWorkstation" src/frontend/src/App.tsx` | list and detail loads are guarded |
| Frontend tests | command from plan 021, if available | exit 0 |

## Scope

**In scope**:
- Add a request-id or abort-controller guard to Workstation list loading.
- Only write `workstationList`, `selectedWorkstationClientId`, and loading state from the newest request.
- Preserve polling behavior for the active filter.

**Out of scope**:
- Changing backend query behavior.
- Changing Workstation list UI layout.
- Changing CRM dashboard request guards.

## Git Workflow

- Branch: `codex/guard-workstation-list-requests`
- Commit message: `Guard Workstation list request state`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a list request ref

Use a `useRef` similar to `workstationDetailRequestId`.

Increment it at the start of `loadWorkstation`.

### Step 2: Guard all writes

Before writing list, selected client, or loading state, confirm the request id is still current.

### Step 3: Preserve selection logic

Keep the existing selected-client preservation rule, but apply it only for the current response.

### Step 4: Verify with delayed responses

If frontend tests exist, add a test where an older request resolves after a newer one and confirm the newer list remains visible.

## Test Plan

- Frontend build passes.
- Frontend test if available.
- Manual browser check: rapidly change Workstation search/funnel and confirm old results do not reappear.

## Done Criteria

- [ ] Slow old Workstation list responses cannot overwrite current state.
- [ ] Detail request guard still works.
- [ ] Poll refresh still updates the active list.
- [ ] Frontend build passes.

## STOP Conditions

- The change breaks automatic Workstation polling.
- The selected-client fallback becomes inconsistent with current filters.
- No reliable manual or automated verification is possible.

## Maintenance Notes

Keep this consistent with the existing dashboard/detail request-id pattern.
