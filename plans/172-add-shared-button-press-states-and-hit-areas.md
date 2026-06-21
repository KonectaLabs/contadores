# Plan 172: Add Shared Button Press States And Hit Areas

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
- **Category**: frontend-ui
- **Planned at**: commit `bf8782e`, 2026-06-21

## Why This Matters

Buttons are the main operator controls. Shared buttons currently have hover styling, but no consistent tactile press state. Several compact remove/action buttons are below the practical 40px hit target. This plan adds the `scale(0.96)` press feedback required by `make-interfaces-feel-better` and raises small action hit areas without changing behavior.

## Current State

- Base buttons have no transition or active scale:

```css
src/frontend/src/styles.css:2740
#contadoresView .ct-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  height: 36px;
```

- Icon buttons have hover styling but no press state:

```css
src/frontend/src/styles.css:370
#contadoresView .ct-icon-btn {
  display: inline-flex;
  ...
}
```

- Manual file-chip remove buttons are only 24px:

```css
src/frontend/src/styles.css:2728
#contadoresView .ct-manual-file-chip button {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Transition scan | `rg -n "transition: all|scale\\(0\\.9|scale\\(0\\.98|scale\\(0\\.96" src/frontend/src/styles.css` | no broad `transition: all`; active scale is 0.96 |

## Scope

**In scope**:
- `src/frontend/src/styles.css`
- `src/frontend/src/App.tsx` only if a small button needs a class to avoid broad CSS

**Out of scope**:
- Adding new button components.
- Replacing Phosphor icons.
- Changing action behavior.

## Git Workflow

- Branch: `codex/ui-button-press-hit-area`
- Commit message: `Add shared button press feedback`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add explicit shared transitions

Add exact transition properties to shared controls:

- `.ct-btn`
- `.ct-icon-btn`
- `.ct-nav-btn`
- `.ct-section-switch button`
- `.ct-strategy-filter-btn`
- compact action buttons where they are not covered

Use explicit properties such as `transform`, `background-color`, `border-color`, `color`, `box-shadow`, `opacity`. Do not use `transition: all`.

**Verify**: transition scan shows no `transition: all`.

### Step 2: Add press scale

Add `:active:not(:disabled) { transform: scale(0.96); }` for shared buttons and compact action controls.

Do not apply scale to layout containers or controls whose transform is already used for drag positioning.

**Verify**: transition scan shows `scale(0.96)` and no smaller exaggerated press scale.

### Step 3: Raise small hit areas

For small controls, get the hit area to at least 40px:

- `.ct-manual-file-chip button`
- `.campaign-media-open`
- `.delivery-small-btn`
- Delivery row compact action buttons
- Workstation modal close

If visual size must stay compact, use non-overlapping padding or a constrained pseudo-element. Do not let hit areas overlap adjacent controls.

**Verify**: inspect CSS diff and ensure small action selectors have `min-width`/`min-height` or safe pseudo-element hit areas.

## Test Plan

- `cd src/frontend && npm run build`
- Manual click check for topbar buttons, primary buttons, manual file removal, Delivery row actions, and modal close.

## Done Criteria

- [ ] Shared buttons use explicit transitions.
- [ ] Press feedback uses `scale(0.96)`.
- [ ] No `transition: all` is introduced.
- [ ] Frequent small controls have at least a 40px hit area or a safe expanded hit target.
- [ ] Frontend build exits 0.

## STOP Conditions

- Hit-area expansion overlaps adjacent controls.
- Press transforms break a control that already depends on `transform`.

## Maintenance Notes

Future buttons should inherit the shared rule instead of adding one-off active scales.
