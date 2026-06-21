# Plan 125: Guard Campaign Submissions Request State

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: FRONTEND-16

## Why This Matters

Campaign detail submissions load asynchronously. A slow response for campaign A can arrive after the operator selects campaign B and overwrite the visible submission detail state.

Campaign submission requests need the same stale-response guard pattern used elsewhere in the app.

## Current State

- Submission loads set state directly:

```tsx
src/frontend/src/App.tsx:3542
async function loadCampaignSubmissions(campaignId: string) {
```

```tsx
src/frontend/src/App.tsx:3545
setCampaignSubmissions(payload);
```

- Campaign selection triggers detail loading:

```tsx
src/frontend/src/App.tsx:3704
async function selectCampaign(campaignId: string) {
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Request guard scan | `rg -n "loadCampaignSubmissions|campaignSubmissionsRequest|requestId|setCampaignSubmissions|selectCampaign" src/frontend/src/App.tsx` | submissions load has stale-response guard |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Add a request id or selected-campaign guard to campaign submissions loading.
- Clear or preserve submission state deliberately while switching campaigns.
- Keep loading/error UI coherent.

**Out of scope**:
- Campaign list request guards.
- Backend pagination/query changes.
- Full frontend regression suite; plan 021 covers broader coverage.

## Git Workflow

- Branch: `codex/guard-campaign-submissions-request-state`
- Commit message: `Guard campaign submissions request state`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add request identity

Use a `useRef` counter or selected campaign id check around `loadCampaignSubmissions`.

### Step 2: Handle loading state

Ensure an old request cannot clear loading/error state for a newer request.

### Step 3: Manual verify

Throttle network, select campaign A, quickly select campaign B, and confirm A's submissions never render under B.

## Test Plan

- Frontend build passes.
- Manual throttled browser check passes.

## Done Criteria

- [ ] Stale campaign submissions responses are ignored.
- [ ] Loading state belongs to the current request.
- [ ] Submission detail does not visually mix campaign contexts.

## STOP Conditions

- Campaign submissions state is intentionally global and multiple campaign panels can render at once.
- Fixing this requires a broader campaign state refactor.

## Maintenance Notes

Any async detail request keyed by a selected item needs a stale-response guard. Reuse the local pattern rather than inventing a new abstraction.
