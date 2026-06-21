# Plan 173: Replace Media Borders With Neutral Outlines

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

Uploaded media, WhatsApp media, campaign creatives, and generated photos are user/customer-visible assets. The current styling often relies on themed borders around image containers. `make-interfaces-feel-better` recommends neutral inset image outlines so media edges look clean on any surface.

## Current State

- CRM message media uses a layout border:

```css
src/frontend/src/styles.css:2458
#contadoresView .crm-message-media img,
#contadoresView .crm-message-media video {
  display: block;
  width: 100%;
  max-height: 360px;
  border: 1px solid var(--ct-line);
```

- Campaign media preview images/videos sit inside a bordered preview:

```css
src/frontend/src/styles.css:5367
#contadoresView .campaign-media-preview img,
#contadoresView .campaign-media-preview video {
  width: 100%;
  height: 100%;
```

- Workstation media/photo picker images use themed borders:

```css
src/frontend/src/styles.css:7088
#contadoresView .workstation-photo-picker-card img {
  width: 100%;
  aspect-ratio: 4 / 3;
  border: 1px solid var(--ct-line-soft);
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Outline scan | `rg -n "outline: 1px solid rgba\\(0, 0, 0, 0\\.1\\)|outline: 1px solid rgba\\(255, 255, 255, 0\\.1\\)" src/frontend/src/styles.css` | shows media outline rules |

## Scope

**In scope**:
- `src/frontend/src/styles.css`

**Out of scope**:
- Changing upload behavior.
- Changing media aspect ratios unless needed to prevent outline clipping.
- Adding image processing.

## Git Workflow

- Branch: `codex/ui-media-outlines`
- Commit message: `Use neutral outlines on media previews`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add neutral media outline rules

Apply these exact outline colors to actual media elements:

```css
outline: 1px solid rgba(0, 0, 0, 0.1);
outline-offset: -1px;
```

Use dark-surface variant only where the media sits on a dark preview:

```css
outline: 1px solid rgba(255, 255, 255, 0.1);
outline-offset: -1px;
```

Target at least:

- `.crm-message-media img`
- `.crm-message-media video`
- `.campaign-creative-asset-preview img`
- `.campaign-creative-asset-preview video`
- `.campaign-media-preview img`
- `.campaign-media-preview video`
- `.workstation-media-card img`
- `.workstation-photo-card img`
- `.workstation-photo-picker-card img`

**Verify**: outline scan shows rules using pure black/white rgba, not tinted palette colors.

### Step 2: Remove borders from actual image pixels where appropriate

If an actual `img`/`video` has `border: 1px solid var(--ct-line*)`, replace that with outline. Keep container borders when they are layout separators.

**Verify**: `git diff -- src/frontend/src/styles.css` shows image/video border removal only where the outline replaces it.

## Test Plan

- `cd src/frontend && npm run build`
- Manual visual check of CRM message media, Campaign creative/media cards, Workstation uploaded media, and photo picker selected state.

## Done Criteria

- [ ] Actual image/video elements use neutral inset outlines.
- [ ] Light surfaces use `rgba(0, 0, 0, 0.1)`.
- [ ] Dark preview surfaces use `rgba(255, 255, 255, 0.1)`.
- [ ] Container borders that serve layout separation remain intact.
- [ ] Frontend build exits 0.

## STOP Conditions

- An outline makes transparent media look worse or hides selected state.

## Maintenance Notes

Do not use tinted neutral outlines for media. The exact rgba values are intentional.
