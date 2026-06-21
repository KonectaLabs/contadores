# Plan 013: Ignore Stale Campaign Geo-Search Results

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Ads builder searches Meta-compatible regions by country and query. The component debounces requests but does not abort or sequence-check responses. If an operator changes country/query quickly, an older response can overwrite suggestions for the current country and lead to wrong targeting.

## Current State

- Geo-search component writes suggestions from any completed request:

```tsx
src/frontend/src/App.tsx:3378
useEffect(() => {
  const cleanQuery = query.trim();
  ...
  const timeout = window.setTimeout(async () => {
    try {
      const payload = await apiFetch<CampaignGeoSearchResponse>(
        `/api/campaigns/geo/search?country_code=${encodeURIComponent(countryCode)}&kind=region&q=${encodeURIComponent(cleanQuery)}&limit=12`,
      );
      setSuggestions(payload.suggestions ?? []);
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build/typecheck | `cd src/frontend && npm run build` | exit 0; creates ignored `dist/` |

## Scope

**In scope**:
- `src/frontend/src/App.tsx`

**Out of scope**:
- Backend geo-search behavior.
- Adding a frontend test framework.
- Changing country/region validation rules.

## Git Workflow

- Branch: `codex/ignore-stale-geo-search`
- Commit message: `Ignore stale campaign geo-search results`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a request sequence guard

Inside `CampaignProvinceSearch`, add:

```tsx
const searchRequestId = useRef(0);
```

Increment it inside the effect before starting the timeout:

```tsx
const requestId = searchRequestId.current + 1;
searchRequestId.current = requestId;
const requestedCountryCode = countryCode;
const requestedQuery = cleanQuery;
```

Only call `setSuggestions`, `setLoading(false)`, or `onError` if `searchRequestId.current === requestId`.

**Verify**: frontend build exits 0.

### Step 2: Clear stale suggestions on country/query changes

When `cleanQuery` is empty, keep current behavior. When country changes with a non-empty query, either clear suggestions immediately before loading or show loading with previous suggestions hidden. Use the smallest change that avoids showing a stale country list.

**Verify**: frontend build exits 0.

## Test Plan

- TypeScript build.
- Code review that every async completion checks the request id.

## Done Criteria

- [ ] Older geo-search responses cannot overwrite newer suggestions.
- [ ] Error/loading state from stale requests is ignored.
- [ ] `cd src/frontend && npm run build` exits 0.
- [ ] No backend changes are included.

## STOP Conditions

- Existing `apiFetch` already supports abort signals in a way that should be used instead.
- Adding request guards conflicts with a broader frontend request pattern introduced since this plan.

## Maintenance Notes

This should use the same general idea as plan 007, but scoped to one small component.
