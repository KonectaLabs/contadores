# Plan 177: Polish Delivery Cards And Row Actions

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: plans/170-stabilize-ui-counters-with-tabular-numerals.md, plans/172-add-shared-button-press-states-and-hit-areas.md
- **Category**: frontend-ui
- **Planned at**: commit `bf8782e`, 2026-06-21

## Why This Matters

Delivery is a daily operational surface. Its contact/source cards and lead row actions need to be dense, readable, and easy to hit. This plan applies surface depth, wrapping, numeric stability, and hit-area polish to Delivery without changing any Delivery behavior.

## Current State

- Delivery cards use hard borders and hover shadow:

```css
src/frontend/src/styles.css:5568
#contadoresView .delivery-contact-card:hover,
#contadoresView .delivery-contact-card.active,
#contadoresView .delivery-sheet-card:hover {
  border-color: rgba(15, 118, 110, 0.32);
```

- Delivery card titles are single-line ellipsis:

```css
src/frontend/src/styles.css:5615
#contadoresView .delivery-card-title strong {
  min-width: 0;
  overflow: hidden;
  ...
  white-space: nowrap;
}
```

- Delivery row actions include compact buttons and menus:

```tsx
src/frontend/src/App.tsx:6018
<a className="ct-btn ct-btn-ghost delivery-action-link" href={waLink} target="_blank" rel="noreferrer">
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- `src/frontend/src/styles.css`
- `src/frontend/src/App.tsx` only if a class is needed for row action targeting

**Out of scope**:
- Delivery source validation.
- Delivery API changes.
- Changing retry/copy behavior.

## Git Workflow

- Branch: `codex/ui-delivery-polish`
- Commit message: `Polish Delivery cards and actions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Soften card depth

Use a shadow ring or existing `--ct-shadow-soft` for Delivery cards instead of relying only on hard borders. Keep status tone visible, especially top-color danger/warn/success indicators.

**Verify**: inspect diff for `.delivery-contact-card` and `.delivery-sheet-card`.

### Step 2: Improve Delivery title/body wrapping

Allow important delivery names to use a two-line clamp or balanced wrapping instead of immediate single-line truncation. Keep dense card height reasonable.

Add `text-wrap: pretty` to short card body/help text.

**Verify**: `rg -n "delivery-card-title|text-wrap: pretty|-webkit-line-clamp" src/frontend/src/styles.css` shows targeted changes.

### Step 3: Confirm row action hit areas

Ensure row action buttons and `More` summaries meet the 40px hit area rule from plan 172 in Delivery rows.

**Verify**: inspect `.delivery-row-actions`, `.delivery-action-link`, and `.delivery-row-menu` rules.

## Test Plan

- `cd src/frontend && npm run build`
- Manual visual check of Delivery contacts view, sheet lead rows, row menu, copy/chat/retry actions.

## Done Criteria

- [ ] Delivery cards feel lighter but still show status tone.
- [ ] Long Delivery names preserve more useful context without breaking layout.
- [ ] Delivery row actions are easy to hit.
- [ ] Frontend build exits 0.

## STOP Conditions

- Card wrapping creates uneven dense lists that are harder to scan.
- Hit-area changes overlap row menu/action controls.

## Maintenance Notes

Delivery should stay work-focused. Avoid decorative card expansion.
