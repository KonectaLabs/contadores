# Plan 114: Remove External Google Fonts From Served CRM CSS

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/styles.css src/frontend/package.json src/frontend/package-lock.json Dockerfile README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: STATIC-03

## Why This Matters

The deployed CRM frontend imports Google Fonts from external URLs. That makes authenticated CRM sessions depend on a third-party font host and can leak operator browser metadata to Google whenever the CRM loads. It also creates an avoidable external dependency for a private operational tool.

Plan 097 removes a CDN dependency from the local runner dashboard. This plan applies the same principle to the deployed CRM frontend bundle.

## Current State

- Source CSS imports Google Fonts:

```css
src/frontend/src/styles.css:1
@import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap");
```

- The built CSS in `dist` includes the same external import:

```css
src/frontend/dist/assets/index-CeLCHLNU.css:1
@import url("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap");
```

- The Docker image serves the built frontend directory:

```dockerfile
Dockerfile:27
COPY --from=frontend-build /app/src/frontend/dist ./src/frontend/dist
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| External CSS scan | `rg -n "fonts.googleapis|fonts.gstatic|@import url\\(\"https?://" src/frontend Dockerfile README.md` | no external font import remains in source or built CSS |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Built asset scan | `rg -n "fonts.googleapis|fonts.gstatic|@import url\\(\"https?://" src/frontend/dist` | no external font import remains in generated assets |

## Scope

**In scope**:
- Remove the external Google Fonts import from CRM source CSS.
- Use local system font stacks, or add self-hosted font files only if they are already approved and vendored intentionally.
- Rebuild the frontend so `src/frontend/dist` no longer references Google Fonts.
- Keep typography readable and close enough to current sizing/layout.

**Out of scope**:
- Full visual redesign.
- Changing application text, spacing system, or layout structure.
- Removing unrelated external network calls.
- Runner dashboard CDN removal; plan 097 covers that separate local artifact.

## Git Workflow

- Branch: `codex/remove-crm-google-fonts`
- Commit message: `Remove external Google Fonts from CRM CSS`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Replace font variables

Update `--font-sans` and `--font-mono` to use local/system fonts only.

Prefer a conservative stack such as:

```css
--font-sans: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
--font-mono: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
```

If Inter is not installed locally, the browser will fall through to system UI fonts.

### Step 2: Remove the external import

Delete the Google Fonts `@import` from source CSS.

Do not replace it with another external stylesheet.

### Step 3: Rebuild the frontend

Run the frontend build so the committed `dist` bundle matches the source change.

### Step 4: Scan for external font references

Use `rg` on both source and `dist` to ensure no `fonts.googleapis` or `fonts.gstatic` references remain.

## Test Plan

- Frontend build passes.
- External CSS scan passes.
- Manual browser check confirms typography remains readable and no layout overflow appears in primary CRM screens.

## Done Criteria

- [ ] Source CSS has no external font imports.
- [ ] Built frontend assets have no external font imports.
- [ ] The production Docker-served bundle reflects the source change.
- [ ] CRM remains readable with system font fallbacks.

## STOP Conditions

- Brand requirements explicitly require these Google-hosted fonts and self-hosting is not approved.
- Font removal causes measurable layout breakage in critical CRM workflows.
- The repo stops committing `src/frontend/dist`, requiring rollout instructions to change first.

## Maintenance Notes

Private CRM surfaces should default to local assets. If a future visual refresh needs custom typography, self-host it deliberately and document the license/source.
