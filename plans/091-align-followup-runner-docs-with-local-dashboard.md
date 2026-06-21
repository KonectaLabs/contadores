# Plan 091: Align Follow-up Runner Docs With Local Dashboard

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md README.md src/frontend/src/App.tsx`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 074
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DOCS-06

## Why This Matters

README says the visual Runner dashboard is local HTML and the server exposes a status API, with no visual Runner view in the deployed backoffice. The follow-up automation skills still tell agents to use a visual Runner tab in the backoffice. That can make future operators look for a nonexistent UI and misreport verification.

## Current State

- README describes the local dashboard:

```markdown
README.md:804
- Vista visual local real de la Mac:
```

```markdown
README.md:807
scripts/render_contadores_crm_runner_dashboard.py
```

- README says the server has status API but no visual backoffice tab:

```markdown
README.md:818
- Estado remoto por API: `GET /api/contadores/followup/runner/status` devuelve
```

```markdown
README.md:821
publica. Ya no hay una vista visual de Runner en el backoffice.
```

- Frontend maps a stored `runner` section back to `crm`:

```tsx
src/frontend/src/App.tsx:263
if (value === "runner") {
```

```tsx
src/frontend/src/App.tsx:264
return "crm";
```

- Follow-up skills still describe a backoffice Runner tab:

```markdown
.codex/skills/contadores-crm-followup-automation/SKILL.md:324
The visual Runner tab in the backoffice reads
```

```markdown
.codex/skills/contadores-crm-followup-automation/SKILL.md:330
Runner tab human-first too: structured delta and action-needed leads first,
```

The wiki mirror has the same text.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runner stale scan | `rg -n "visual Runner tab|Runner tab|backoffice reads" .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md README.md src/frontend/src/App.tsx` | no docs claim a deployed visual Runner tab exists |
| Runner current scan | `rg -n "local.*dashboard|followup/runner/status|render_contadores_crm_runner_dashboard|no visual Runner|Ya no hay" .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md README.md` | docs describe local dashboard plus remote API |
| Mirror diff | `diff -u .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md` | no unexpected mirror drift |

## Scope

**In scope**:
- Update both follow-up automation skill mirrors.
- State that visual Runner is local HTML.
- State that the deployed server exposes status API, not a visual backoffice tab.
- Keep instructions for syncing local runner status to production.

**Out of scope**:
- Building a backoffice Runner UI.
- Changing follow-up runner API diagnostics; plan 074 covers endpoint diagnostics.
- Changing frontend section mapping.

## Git Workflow

- Branch: `codex/fix-runner-docs`
- Commit message: `Align follow-up Runner docs`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Replace backoffice tab wording

Remove wording that says a visual Runner tab exists in the deployed backoffice.

Use wording that matches README:

- local HTML dashboard,
- remote status API,
- local LaunchAgent sync.

### Step 2: Preserve verification instructions

Keep or add clear API verification for `GET /api/contadores/followup/runner/status`.

Do not imply the API response is the same as a full visual UI.

### Step 3: Keep mirrors aligned

Apply the same change to `.codex` and `wiki`.

## Test Plan

- Stale Runner tab scan returns no outdated docs.
- Current scan finds local dashboard plus API language.
- No runtime tests are required because this is docs-only.

## Done Criteria

- [ ] Skills no longer claim there is a deployed visual Runner tab.
- [ ] Skills describe the local dashboard and remote API accurately.
- [ ] `.codex` and `wiki` mirrors remain aligned.

## STOP Conditions

- A visual Runner UI is reintroduced before this plan starts.
- README changes to a new canonical Runner model.
- Mirror files intentionally diverge.

## Maintenance Notes

If a deployed Runner UI is built later, update README, frontend docs, and both skill mirrors in the same change.
