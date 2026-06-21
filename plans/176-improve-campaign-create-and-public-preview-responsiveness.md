# Plan 176: Improve Campaign Create And Public Preview Responsiveness

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/169-apply-frontend-font-smoothing-and-wrap-rules.md
- **Category**: frontend-ui
- **Planned at**: commit `bf8782e`, 2026-06-21

## Why This Matters

Campaign creation is one of the most complex UI flows. It includes long labels, media upload, delivery contacts, and a public form preview. Some grids stay rigid until small mobile breakpoints, so tablet/mid-width layouts can feel cramped. This plan improves responsive behavior and preview text wrapping without changing campaign data.

## Current State

- Campaign create uses a two-column studio with a fixed-ish preview side:

```css
src/frontend/src/styles.css:3563
#contadoresView .campaign-create-studio {
  grid-template-columns: minmax(0, 1fr) minmax(320px, 390px);
```

- Sticky create actions are a high-value control:

```css
src/frontend/src/styles.css:3572
#contadoresView .campaign-create-sticky-actions {
  position: sticky;
  top: 0;
```

- Mobile rules collapse some campaign grids later:

```css
src/frontend/src/styles.css:7429
#contadoresView .campaign-manager-head {
  grid-template-columns: 1fr;
}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- `src/frontend/src/styles.css`
- `src/frontend/src/App.tsx` only if adding one class improves selector clarity

**Out of scope**:
- Changing campaign create form fields.
- Changing backend campaign APIs.
- Adding new validation; plan 012 owns public form validation.

## Git Workflow

- Branch: `codex/ui-campaign-responsive-polish`
- Commit message: `Polish campaign create responsiveness`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add an intermediate breakpoint

Add a tablet/mid-width breakpoint before the current mobile collapse. Collapse or soften:

- `.campaign-create-studio`
- `.campaign-form-shell`
- `.campaign-field-editor`
- `.workstation-upload` only if shared overflow appears in the same breakpoint

Prefer `minmax(0, 1fr)` and wrapping action rows over fixed minimums.

**Verify**: frontend build exits 0.

### Step 2: Improve public preview wrapping

For campaign preview:

- allow long preview titles to wrap where appropriate,
- add `text-wrap: balance` to preview question headings,
- add `text-wrap: pretty` to option/help/footer copy,
- keep `overflow-wrap: anywhere` for long custom tokens.

**Verify**: `rg -n "campaign-preview.*text-wrap|text-wrap: balance|text-wrap: pretty" src/frontend/src/styles.css` shows targeted preview wrapping.

### Step 3: Preserve sticky submit visibility

Do not hide or move the create submit button out of the sticky action area. Existing history says keeping campaign create submit visible matters.

**Verify**: `rg -n "campaign-create-sticky-actions|campaign-create-primary" src/frontend/src/styles.css src/frontend/src/App.tsx` still finds the sticky action rules and submit.

## Test Plan

- `cd src/frontend && npm run build`
- Manual visual check at desktop, tablet around 900-1100px, and mobile around 390px for Campaign create and public preview.

## Done Criteria

- [ ] Campaign create avoids horizontal overflow at tablet widths.
- [ ] Public preview text wraps cleanly without clipped controls.
- [ ] Sticky create actions remain visible.
- [ ] Frontend build exits 0.

## STOP Conditions

- Responsive changes reduce desktop operator density too much.
- Any change requires altering campaign data or form semantics.

## Maintenance Notes

This is layout polish. Keep campaign behavior unchanged.
