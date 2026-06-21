# Plan 068: Scope Workstation Photo Job Polling To Client

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
- **Issue**: UI-09

## Why This Matters

Professional-photo job polling is tied to the job client, not the currently selected Workstation client. If client A's job completes after the operator switches to client B, the poller refreshes A's detail globally. The UI then filters detail by selected client, which can blank or stale the active detail while hiding the completed job.

## Current State

- Polling fetches the job by `professionalPhotoJob.client_id`:

```tsx
src/frontend/src/App.tsx:969
const payload = await apiFetch<WorkstationProfessionalPhotoJobResponse>(
```

- On completion it refreshes Workstation and loads the job client detail:

```tsx
src/frontend/src/App.tsx:976
if (payload.status === "completed") {
  await loadWorkstation();
  await loadWorkstationDetail(payload.client_id);
}
```

- The UI hides jobs that do not belong to the active client:

```tsx
src/frontend/src/App.tsx:6196
const currentProfessionalPhotoJob = professionalPhotoJob?.client_id === activeClient?.id ? professionalPhotoJob : null;
```

- Backend job polling is scoped by client id:

```python
src/backend/endpoints/workstation.py:4460
@workstation_router.post(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Photo job scan | `rg -n "professionalPhotoJob|loadWorkstationDetail\\(payload\\.client_id" src/frontend/src/App.tsx` | completion refresh is scoped safely |
| Frontend tests | command from plan 021, if available | exit 0 |

## Scope

**In scope**:
- Ensure a completed job refreshes the selected detail only when the job still belongs to the selected client.
- Preserve global list refresh so the completed client's summary updates.
- Keep job status visible or recoverable when the operator switches away.

**Out of scope**:
- Changing backend job status API.
- Persisting job state server-side.
- Changing image generation behavior.

## Git Workflow

- Branch: `codex/scope-photo-job-polling`
- Commit message: `Scope Workstation photo job polling to client`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Capture selected client at poll time

Track whether `payload.client_id` still equals the current selected client before calling `loadWorkstationDetail`.

Use a ref if needed to avoid stale closures.

### Step 2: Separate list refresh from detail refresh

On job completion:

- always refresh the Workstation list,
- refresh detail only for the active selected client,
- avoid clearing client B detail because client A completed.

### Step 3: Handle switched-away jobs

If a job completes for a non-selected client, keep enough state for the operator to see completion when they return to that client or clear only that job's busy indicator.

### Step 4: Add coverage if possible

If frontend tests exist, simulate job completion after selection changes and assert active detail remains on client B.

## Test Plan

- Frontend build passes.
- Frontend coverage or manual check for switching clients during a photo job.

## Done Criteria

- [ ] Completed photo jobs no longer overwrite unrelated selected-client detail.
- [ ] Workstation list still refreshes after job completion.
- [ ] Active job status remains understandable after navigation.
- [ ] Frontend build passes.

## STOP Conditions

- The UI cannot represent a completed job for a non-selected client without losing state.
- The polling logic requires a backend contract change.
- The change hides failed job errors from operators.

## Maintenance Notes

Keep this scoped to client-state ownership. Durable job storage is separate from this UI fix.
