# Plan 170: Stabilize UI Counters With Tabular Numerals

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

The app refreshes CRM, Delivery, Campaign, and Workstation counts. Digits changing width makes dense dashboards feel jumpy. `make-interfaces-feel-better` calls for tabular numbers on dynamic counters; this plan applies that rule to the existing numeric UI.

## Current State

- Top operation badges render dynamic counts:

```tsx
src/frontend/src/App.tsx:2034
<span className="ct-section-badge">{compactNumber(badge)}</span>
```

- Lead filter cards render dynamic counts:

```tsx
src/frontend/src/App.tsx:2290
<span className="ct-lead-view-count">{compactNumber(count)}</span>
```

- Delivery card counts do not declare tabular numerals:

```css
src/frontend/src/styles.css:5651
#contadoresView .delivery-card-counts strong {
  color: var(--ct-ink);
  font: 800 14px/1 var(--font-sans);
}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Numeric CSS scan | `rg -n "tabular-nums|font-variant-numeric" src/frontend/src/styles.css src/frontend/src/App.tsx` | shows numeric rules |

## Scope

**In scope**:
- `src/frontend/src/styles.css`
- `src/frontend/src/App.tsx` only if a reusable `tabular-nums` class is clearer than selector-only CSS

**Out of scope**:
- Changing number formatting.
- Changing refresh intervals.
- Refactoring metrics components.

## Git Workflow

- Branch: `codex/ui-tabular-counters`
- Commit message: `Use tabular numerals for UI counters`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add one numeric utility or grouped selector

Prefer the smallest CSS-only change. Add `font-variant-numeric: tabular-nums;` to a grouped selector covering:

- `.ct-section-badge`
- `.ct-nav-badge`
- `.ct-lead-view-count`
- `.ct-simple-metrics strong`
- `.campaign-manager-metrics strong`
- `.campaign-detail-metrics strong`
- `.delivery-card-counts strong`
- `.delivery-summary-metrics strong`
- `.workstation-state-pill`
- `.workstation-photo-picker-head span` when it carries counts

**Verify**: numeric CSS scan shows the new rule.

### Step 2: Avoid phone/version numbers

Do not apply tabular numerals to phone numbers, URLs, version strings, or long raw IDs unless they already sit inside a metric/count class.

**Verify**: `git diff -- src/frontend/src/App.tsx src/frontend/src/styles.css` shows no broad phone/raw-value class changes.

## Test Plan

- `cd src/frontend && npm run build`
- Manual scan of CRM filters, Delivery cards, Campaign metrics, and Workstation counters.

## Done Criteria

- [ ] Dynamic counters/badges use tabular numerals.
- [ ] Phone numbers and raw IDs are not restyled as metrics.
- [ ] Frontend build exits 0.

## STOP Conditions

- The only way to target counters is broad enough to affect chat text or phone numbers.

## Maintenance Notes

If new live counters are added later, put them under the grouped numeric selector instead of hand-tuning one-off styles.
