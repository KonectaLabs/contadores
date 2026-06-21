# Plan 171: Strengthen Primary Navigation Active States

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: frontend-ui
- **Planned at**: commit `bf8782e`, 2026-06-21

## Why This Matters

Operators move between CRM, Ads/Campaigns, Workstation, and Delivery. Active nav state currently shares styling with hover in key places, so location is not as clear as it should be. This plan separates hover from active and gives active state a stable visual marker without changing navigation behavior.

## Current State

- Primary operation switch uses active class:

```tsx
src/frontend/src/App.tsx:2021
<button
  type="button"
  className={isActive ? "active" : ""}
```

- Active and hover share a selector:

```css
src/frontend/src/styles.css:247
#contadoresView .ct-section-switch button.active,
#contadoresView .ct-section-switch button:hover {
  background: var(--ct-accent-soft);
  color: var(--ct-accent-strong);
}
```

- Funnel nav also shares active and hover:

```css
src/frontend/src/styles.css:300
#contadoresView .ct-nav-btn.active,
#contadoresView .ct-nav-btn:hover {
  background: var(--ct-surface-2);
  color: var(--ct-ink);
}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- `src/frontend/src/styles.css`
- `src/frontend/src/App.tsx` only if `aria-current` needs a tiny correction

**Out of scope**:
- Changing section names.
- Adding new nav items.
- Redesigning the topbar.

## Git Workflow

- Branch: `codex/ui-nav-active-state`
- Commit message: `Clarify active navigation states`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Split hover and active selectors

Keep hover subtle. Give `.active` a persistent marker such as:

- stronger background,
- inset shadow ring,
- small bottom/left marker using `::after`,
- or both color and shape changes.

Do this for `.ct-section-switch button` and `.ct-nav-btn`.

**Verify**: `rg -n "ct-section-switch button.active|ct-nav-btn.active|ct-section-switch button:hover|ct-nav-btn:hover" src/frontend/src/styles.css` shows split active/hover rules.

### Step 2: Preserve accessibility state

Keep existing `aria-current="page"` behavior in `App.tsx`. Do not replace semantic state with visual-only CSS.

**Verify**: `rg -n "aria-current=\\{isActive|aria-current=\\{isActiveFunnel" src/frontend/src/App.tsx` still finds both nav states.

### Step 3: Check compact mobile nav

Existing mobile rules collapse nav near `max-width: 760px` and `520px`. Make sure any active marker still fits there.

**Verify**: frontend build exits 0.

## Test Plan

- `cd src/frontend && npm run build`
- Manual visual check in desktop and mobile widths for primary operations and funnel nav.

## Done Criteria

- [ ] Hover and active states are visually distinct.
- [ ] Active state does not rely on color alone.
- [ ] `aria-current` remains in the nav buttons.
- [ ] Frontend build exits 0.

## STOP Conditions

- The active marker causes clipped text or horizontal overflow on mobile.

## Maintenance Notes

Keep this as topbar polish only. Do not start a navigation restructure here.
