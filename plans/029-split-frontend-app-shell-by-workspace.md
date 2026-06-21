# Plan 029: Split Frontend App Shell By Workspace

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/types.ts src/frontend/src/api.ts src/frontend/src/styles.css src/frontend/package.json src/frontend/package-lock.json`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/021-add-frontend-regression-coverage.md
- **Category**: architecture
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

`App.tsx` is almost ten thousand lines and owns the global shell, CRM, Campaigns, Workstation, and Delivery. Small UI changes now collide with unrelated state and callbacks. Splitting by workspace will make future product work safer, but only after there is a frontend regression harness.

## Current State

- `App.tsx` defines the app shell and most global state in one component:

```tsx
src/frontend/src/App.tsx:393
export function App() {
  const [activeSection, setActiveSection] = useState<ActiveSection>(readStoredActiveSection);
  const [runtime, setRuntime] = useState<RuntimeSettings | null>(null);
  ...
```

- Workspace navigation is hard-coded to four sections:

```tsx
src/frontend/src/App.tsx:91
type ActiveSection = "crm" | "campaigns" | "workstation" | "delivery";
```

- Workstation is a very large child surface with many props:

```tsx
src/frontend/src/App.tsx:6090
function WorkstationView({
  clients,
  detail,
  funnel,
  selectedClientId,
  ...
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend tests | `cd src/frontend && npm test -- --run` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Backend smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Extract shell/navigation layout.
- Extract CRM, Campaigns, Workstation, and Delivery workspace components into feature files.
- Move shared pure helpers to small files.
- Preserve visual behavior and API calls.

**Out of scope**:
- Redesigning the UI.
- Changing backend API shapes.
- Adding the Ops tab; plan 034 covers that.
- Refactoring campaign internals deeply; plan 030 covers that.

## Git Workflow

- Branch: `codex/split-frontend-app-shell`
- Commit message: `Split frontend app shell by workspace`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Establish a file structure

Use a shallow structure such as:

```text
src/frontend/src/app/
src/frontend/src/workspaces/crm/
src/frontend/src/workspaces/campaigns/
src/frontend/src/workspaces/workstation/
src/frontend/src/workspaces/delivery/
```

Do not create deep folders unless a file would otherwise become hard to scan.

### Step 2: Extract shell without behavior changes

Move topbar/nav/layout rendering and `ActiveSection` storage helpers first.

Keep `App` as the orchestrator during the first step so state behavior remains unchanged.

### Step 3: Extract one workspace at a time

Recommended order:

1. Delivery, because it is smaller than Campaigns/Workstation.
2. Workstation view component.
3. CRM workspace.
4. Campaigns workspace last.

Run frontend tests/build after each meaningful extraction if the diff is large.

### Step 4: Keep styles stable

Do not rename classes unless necessary. Keep `styles.css` changes minimal.

### Step 5: Verify

Run frontend tests and build. Use Browser only if the change becomes visual or interactive beyond moving files.

## Test Plan

- Existing frontend regression tests from plan 021.
- Frontend build.
- Manual smoke of all four existing workspace tabs.

## Done Criteria

- [ ] `App.tsx` no longer owns all workspace render trees.
- [ ] Four existing workspace sections still render and keep their stored active section behavior.
- [ ] API calls and response handling are unchanged.
- [ ] Frontend tests and build exit 0.

## STOP Conditions

- Missing frontend tests make behavior-preserving extraction too risky.
- Extraction starts requiring API or product behavior changes.

## Maintenance Notes

This is a behavior-preserving extraction. If a redesign is needed, do it after this split lands.
