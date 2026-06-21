# Plan 174: Polish Empty, Loading, And Error States

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/169-apply-frontend-font-smoothing-and-wrap-rules.md
- **Category**: frontend-ui
- **Planned at**: commit `bf8782e`, 2026-06-21

## Why This Matters

Empty and error states are repeated across CRM, Campaigns, Delivery, and Workstation. They should feel like part of the product, not dashed placeholders. This plan tightens the shared empty-state component and global error banners while keeping text and behavior unchanged.

## Current State

- The shared empty state is simple and reusable:

```tsx
src/frontend/src/App.tsx:237
<div className={`ct-empty-state ${compact ? "compact" : ""}`} role="status" aria-live="polite">
  {loading ? <SpinnerGap className="ct-empty-state-icon" size={18} weight="bold" aria-hidden="true" /> : null}
  <strong>{title}</strong>
```

- Empty state uses a dashed border:

```css
src/frontend/src/styles.css:2525
#contadoresView .ct-empty-state {
  align-self: stretch;
  display: grid;
  place-items: center;
  ...
  border: 1px dashed rgba(28, 38, 44, 0.18);
```

- Global errors use hard borders:

```css
src/frontend/src/styles.css:410
#contadoresView .ct-error {
  ...
  border: 1px solid rgba(178, 61, 61, 0.22);
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- `src/frontend/src/styles.css`
- `src/frontend/src/App.tsx` only if one extra existing icon/state class is needed

**Out of scope**:
- Rewriting empty-state copy.
- Adding skeleton loaders everywhere.
- Changing API error handling.

## Git Workflow

- Branch: `codex/ui-empty-error-polish`
- Commit message: `Polish empty and error states`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Replace dashed placeholder feel

For `.ct-empty-state`, prefer a soft shadow ring or subtle background over a dashed border. Use explicit `box-shadow` and keep the existing compact variant.

Do not make page sections into card piles; this is for the repeated empty-state component only.

**Verify**: `rg -n "ct-empty-state|ct-error" src/frontend/src/styles.css` shows updated shared state rules.

### Step 2: Keep loading motion scoped

The spinner animation is acceptable because it indicates active loading. Do not add entrance animations on page load.

If changing spinner styling, keep `animation` limited to the spinner icon.

**Verify**: frontend build exits 0.

### Step 3: Make error banners visually consistent

Use the existing semantic danger colors, but prefer softer surface/ring treatment and keep `role="alert"` behavior untouched.

**Verify**: `rg -n "role=\\\"alert\\\"" src/frontend/src/App.tsx` still finds global alert locations.

## Test Plan

- `cd src/frontend && npm run build`
- Manual visual check: one loading empty state, one plain empty state, and one global error banner.

## Done Criteria

- [ ] Empty states look intentional and not like unfinished placeholders.
- [ ] Loading spinner remains scoped and readable.
- [ ] Error banners keep alert semantics.
- [ ] Frontend build exits 0.

## STOP Conditions

- The empty-state change creates nested-card visuals inside already framed surfaces.

## Maintenance Notes

Keep empty states short and action-oriented. Do not use this plan to rewrite product copy.
