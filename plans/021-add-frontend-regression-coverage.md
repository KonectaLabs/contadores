# Plan 021: Add Frontend Regression Coverage For Critical Operator Flows

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/package.json src/frontend/package-lock.json src/frontend/src/App.tsx src/frontend/src/api.ts src/frontend/src/types.ts`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/007-guard-frontend-delivery-request-state.md, plans/008-confirm-campaign-status-changes.md, plans/013-ignore-stale-campaign-geo-search.md
- **Category**: tests
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The frontend is operator-critical, but it currently has only build verification. Before splitting `App.tsx` or adding more Ads/Delivery behavior, the repo needs a small regression harness around the highest-risk flows.

## Current State

- Frontend scripts only include dev/build/preview:

```json
src/frontend/package.json:6
"scripts": {
  "dev": "vite --host 0.0.0.0",
  "build": "tsc -b && vite build",
  "preview": "vite preview --host 0.0.0.0"
}
```

- There are no frontend test dependencies:

```json
src/frontend/package.json:19
"devDependencies": {
  "@types/react": "^19.2.14",
  "@types/react-dom": "^19.2.3"
}
```

- `App.tsx` is currently 9962 lines and owns CRM, campaigns, Workstation, and Delivery.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Install deps | `cd src/frontend && npm install` | updates lockfile cleanly |
| Frontend tests | `cd src/frontend && npm test -- --run` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Add Vitest and React Testing Library or a similarly lightweight Vite-native runner.
- Add tests for critical UI state transitions.
- Keep test fixtures local and readable.

**Out of scope**:
- Full Playwright browser suite.
- Visual regression snapshots.
- Refactoring `App.tsx` broadly.

## Git Workflow

- Branch: `codex/frontend-regression-coverage`
- Commit message: `Add frontend regression coverage`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add test tooling

Install the smallest useful stack:

- `vitest`,
- `jsdom`,
- `@testing-library/react`,
- `@testing-library/user-event`,
- `@testing-library/jest-dom`.

Add scripts:

```json
"test": "vitest",
"test:run": "vitest run"
```

Use Vite/Vitest defaults where possible.

### Step 2: Extract only testable pure helpers if needed

Do not split the app broadly. If a behavior is impossible to test because it is buried in `App.tsx`, extract a tiny pure helper to a clearly named file.

Candidate helpers:

- campaign status label/intent,
- geo search stale result reducer,
- delivery list stale request reducer,
- public form field validation logic if shared with plan 012.

### Step 3: Add 3-5 focused tests

Cover:

- Delivery stale request cannot overwrite newer response state.
- Campaign status destructive actions require confirmation after plan 008 lands.
- Geo-search stale results are ignored after plan 013 lands.
- API error text remains readable through `apiFetch`.

If prerequisite plans have not landed, write tests only for helpers that exist after this plan's branch includes them.

### Step 4: Keep build as the final frontend gate

Run:

```bash
cd src/frontend && npm test -- --run
cd src/frontend && npm run build
```

## Test Plan

- New frontend tests.
- Existing frontend build.

## Done Criteria

- [ ] `npm test -- --run` exists and exits 0.
- [ ] At least three critical operator UI behaviors have regression coverage.
- [ ] `npm run build` still exits 0.
- [ ] Test files are small and easy to read.

## STOP Conditions

- Adding the test runner requires large framework churn.
- Tests require brittle full-app mocking that is harder to maintain than the behavior under test.

## Maintenance Notes

This plan intentionally precedes large frontend extraction. It gives future refactors a safety net without making testing infrastructure the main project.
