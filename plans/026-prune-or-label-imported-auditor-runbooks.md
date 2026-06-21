# Plan 026: Prune Or Label Imported Auditor Runbooks

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- wiki/skills/README.md wiki/skills/auditor`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/023-sync-codex-and-wiki-skills.md
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Contadores wiki contains imported Konecta Auditor skills. Some are valuable historical references, but several still look operational and contain hard-coded paths and commands for `/Users/fgoiriz/private/repos/konecta-auditor`. That can mislead future agents into running old repo commands while working in Contadores.

## Current State

- Imported memory points at the old repo:

```text
wiki/skills/auditor/konecta-auditor-development-memory/SKILL.md:329
/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-repeatable-deploy/SKILL.md
```

- Development method references old repo files:

```text
wiki/skills/auditor/konecta-development-method/SKILL.md:81
/Users/fgoiriz/private/repos/konecta-auditor/.cursor/skills/konecta-auditor-development-memory/SKILL.md
```

- One validation block uses old repo layout commands:

```bash
wiki/skills/auditor/konecta-auditor-contadores-strategies/SKILL.md:52
uv run --with pytest pytest backend/tests/test_contadores.py -q
cd bot && uv run --with pytest pytest tests/test_contadores_flow.py -q
node --check frontend/static/js/app.js
```

- A broad grep finds many `konecta-auditor` references under `wiki/skills/auditor`.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Find old repo refs | `rg -n "/Users/fgoiriz/private/repos/konecta-auditor|konecta-auditor" wiki/skills/auditor` | reviewed list |
| Markdown list | `find wiki/skills/auditor -maxdepth 2 -type f | sort` | reviewed list |

## Scope

**In scope**:
- Clearly label imported auditor skills as archival or adapt only the ones intentionally active for Contadores.
- Update `wiki/skills/README.md` so future agents know how to treat `wiki/skills/auditor`.
- Fix obviously stale validation commands only when the skill is active for Contadores.

**Out of scope**:
- Deleting historical knowledge wholesale.
- Editing `.codex/skills` active skill behavior.
- Migrating all auditor patterns into Contadores-specific skills.

## Git Workflow

- Branch: `codex/label-imported-auditor-runbooks`
- Commit message: `Label imported auditor runbooks`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Classify auditor files

Create a short classification:

- active Contadores guidance,
- historical reference,
- stale and should not be used.

Do this by reading filenames and top sections, not by mass editing every memory entry.

### Step 2: Add a clear wiki index warning

Update `wiki/skills/README.md` under the `auditor/` bullet:

- imported from old Konecta Auditor repo,
- not auto-discovered active Contadores skills,
- old repo paths are historical unless a file explicitly says it was adapted.

### Step 3: Label high-risk files

For the small set of files that contain operational deploy or validation commands, add a top warning such as:

```markdown
> Historical import: this file references the old konecta-auditor repo. Do not run its commands in Contadores unless they have been adapted below.
```

Do not insert warnings into thousands of memory lines. Focus on entrypoint-style files.

### Step 4: Adapt only active commands

If a file is still meant to guide Contadores work, replace stale paths with current Contadores commands:

- `PYTHONPATH=src uv run --with pytest pytest ...`,
- `cd src/bot && uv run --with pytest pytest ...`,
- `cd src/frontend && npm run build`.

If not active, leave the old commands but label them historical.

## Test Plan

- `rg` still may find old repo references, but they should be under clearly labeled archival files.
- `wiki/skills/README.md` explains the boundary.
- No source code changes.

## Done Criteria

- [ ] Auditor wiki directory is clearly labeled as imported/historical unless adapted.
- [ ] Active-looking deploy/validation entrypoints have a warning or current Contadores commands.
- [ ] Future agents are not directed to run old repo commands by default.

## STOP Conditions

- User wants the old auditor memory preserved byte-for-byte without labels.
- A runbook appears active but requires product owner judgment to adapt safely.

## Maintenance Notes

This is documentation safety work. Do not delete large historical memories just because they mention the old repo.
