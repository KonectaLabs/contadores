# Plan 169: Apply Frontend Font Smoothing And Wrapping Rules

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/styles.css`
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

The CRM is a dense operator tool, so typography has to stay crisp and predictable. The current CSS does not apply root font smoothing, and several short headings/body blocks have no `text-wrap` guidance. This plan applies the `make-interfaces-feel-better` typography rules without changing copy or layout structure.

## Current State

- Root styles do not smooth text:

```css
src/frontend/src/styles.css:7
body {
  margin: 0;
  min-width: 0;
  min-height: 100dvh;
}
```

- The app root sets fonts but no wrapping defaults:

```css
src/frontend/src/styles.css:45
#contadoresView {
  ...
  font-family: var(--font-sans);
}
```

- Setup hero heading and body copy are short text blocks:

```css
src/frontend/src/styles.css:447
#contadoresView .ct-funnel-hero h2 {
  margin: 6px 0 8px;
  color: var(--ct-ink);
  font: 700 26px/1.1 var(--font-sans);
}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Check CSS for broad wrapping | `rg -n "text-wrap: balance|text-wrap: pretty|font-smoothing" src/frontend/src/styles.css` | shows targeted rules |

## Scope

**In scope**:
- `src/frontend/src/styles.css`

**Out of scope**:
- Changing app text.
- Reworking font families. Plan 114 owns external Google Font removal.
- Applying `text-wrap: balance` to long paragraphs or log/output blocks.

## Git Workflow

- Branch: `codex/ui-font-smoothing-wrap`
- Commit message: `Apply frontend typography polish`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add root font smoothing

Add font smoothing once near the root:

```css
html {
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
```

Do not repeat it per element.

**Verify**: `rg -n "font-smoothing|moz-osx-font-smoothing" src/frontend/src/styles.css` shows one root rule.

### Step 2: Add targeted heading wrapping

Add `text-wrap: balance` to short heading selectors, including:

- `.ct-funnel-hero h2`
- `.ct-drawer-head h3`
- `.ct-modal-head h3`
- `.ct-empty-state strong`
- campaign preview question headings
- Workstation/funnel setup short headings where present

Avoid long technical logs, `pre`, tables, chat messages, and code blocks.

**Verify**: `rg -n "text-wrap: balance" src/frontend/src/styles.css` shows targeted selectors.

### Step 3: Add targeted body wrapping

Add `text-wrap: pretty` to short helper/caption/body selectors, including:

- `.ct-funnel-hero p`
- `.ct-drawer-note`
- `.ct-modal-subtitle`
- `.ct-empty-state span`
- `.ct-field-hint`
- campaign preview body/options copy

Keep `overflow-wrap: anywhere` where it protects long URLs, IDs, filenames, or raw values.

**Verify**: `rg -n "text-wrap: pretty" src/frontend/src/styles.css` shows targeted selectors.

## Test Plan

- `cd src/frontend && npm run build`
- Manual visual check on one desktop and one mobile viewport for setup view, modal/drawer headings, and empty states.

## Done Criteria

- [ ] Root font smoothing is applied once.
- [ ] Short headings use `text-wrap: balance`.
- [ ] Short body/helper text uses `text-wrap: pretty`.
- [ ] Long logs, tables, and code/preformatted text are not given balance wrapping.
- [ ] Frontend build exits 0.

## STOP Conditions

- The CSS has drifted so the cited selectors no longer exist.
- Wrapping changes cause clipped controls or horizontal overflow.

## Maintenance Notes

This is typography polish only. Keep it CSS-only and boring.
