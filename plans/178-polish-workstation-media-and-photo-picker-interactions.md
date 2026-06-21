# Plan 178: Polish Workstation Media And Photo Picker Interactions

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/172-add-shared-button-press-states-and-hit-areas.md, plans/173-replace-media-borders-with-neutral-outlines.md
- **Category**: frontend-ui
- **Planned at**: commit `bf8782e`, 2026-06-21

## Why This Matters

Workstation handles client media, photo generation, and Codex actions. Media cards and photo picker selection should feel polished because operators inspect visual assets there. This plan improves media card surfaces, selected states, icon transitions, and responsive upload layout without changing Workstation behavior.

## Current State

- Workstation media cards use hard borders:

```css
src/frontend/src/styles.css:6832
#contadoresView .workstation-media-card {
  display: grid;
  gap: 10px;
  ...
  border: 1px solid var(--ct-line);
```

- Photo picker cards have selected styling but no transition:

```css
src/frontend/src/styles.css:7066
#contadoresView .workstation-photo-picker-card {
  display: grid;
  gap: 9px;
  ...
  cursor: pointer;
}
```

- Selected check icon is conditionally rendered:

```tsx
src/frontend/src/App.tsx:7242
<img src={asset.media_url} alt={asset.title || asset.original_filename} loading="lazy" />
```

The selected icon appears near this picker card block.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Transition scan | `rg -n "transition: all|scale\\(0\\.25\\)|blur\\(4px\\)|workstation-photo-picker" src/frontend/src/styles.css src/frontend/src/App.tsx` | no `transition: all`; picker transition exists if icon animation added |

## Scope

**In scope**:
- `src/frontend/src/App.tsx`
- `src/frontend/src/styles.css`

**Out of scope**:
- Changing media upload limits.
- Changing professional photo API calls.
- Adding a motion library.

## Git Workflow

- Branch: `codex/ui-workstation-media-polish`
- Commit message: `Polish Workstation media interactions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Soften Workstation media surfaces

Use the same card-depth approach as Delivery/Campaign cards: subtle shadow ring, preserved radius, and no extra nested-card look.

**Verify**: inspect `.workstation-media-card`, `.workstation-photo-card`, and `.workstation-photo-picker-card` CSS diff.

### Step 2: Improve photo picker selected state

Keep the selected state obvious without relying only on color. Add a stable check slot or selected marker that does not resize the card.

If animating the icon, use CSS-only transition with:

- opacity `0` to `1`
- scale `0.25` to `1`
- blur `4px` to `0`
- cubic-bezier `(0.2, 0, 0, 1)`

Do not add a dependency.

**Verify**: transition scan shows no `transition: all`.

### Step 3: Add an intermediate upload-grid breakpoint if needed

The Workstation upload grid currently uses `minmax(180px, 1fr) minmax(220px, 1fr) auto`. Add a tablet breakpoint to avoid cramped file/title/action rows before mobile.

**Verify**: frontend build exits 0.

## Test Plan

- `cd src/frontend && npm run build`
- Manual visual check of Workstation upload, media cards, professional photo modal, and photo picker selected/unselected states.

## Done Criteria

- [ ] Workstation media cards use polished depth without heavy borders.
- [ ] Photo picker selected state is stable, clear, and does not resize cards.
- [ ] Any icon animation uses opacity, scale, and blur with explicit transitions.
- [ ] Upload layout avoids tablet overflow.
- [ ] Frontend build exits 0.

## STOP Conditions

- Selected-state animation makes the checkbox/check marker inaccessible or unclear.
- Responsive upload changes reduce desktop density too much.

## Maintenance Notes

Keep the Workstation UI utilitarian. Visual polish should help asset inspection, not add decoration.
