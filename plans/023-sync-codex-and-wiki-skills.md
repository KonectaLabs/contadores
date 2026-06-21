# Plan 023: Sync Codex And Wiki Skills

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- .codex/skills wiki/skills README.md AGENTS.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

AGENTS says `README.md`, `.env.example`, `.codex/skills/*`, and `wiki/skills/*` must stay synchronized when flow or rollout changes. Today `.codex/skills` contains active skills that do not have a matching `wiki/skills` mirror, which makes future repo work depend on which source an agent happens to read.

## Current State

- AGENTS requires skill sync:

```text
AGENTS.md:28
Mantener sincronizados:
  - README.md
  - .env.example
  - .codex/skills/*
  - wiki/skills/*
```

- `wiki/skills/README.md` says `.codex/skills` contains active auto-discovered skills:

```text
wiki/skills/README.md:13
- `.codex/skills/`: skills activas que Codex descubre automáticamente para este repo.
```

- Current mismatch examples from the read-only audit:

```text
.codex/skills/konecta-new-niche-funnel/SKILL.md exists
wiki/skills/konecta-new-niche-funnel/SKILL.md is not present at the root mirror

.codex/skills/konecta-niche-market-research/SKILL.md exists
wiki/skills/konecta-niche-market-research/SKILL.md is not present at the root mirror
```

Some related copies may exist under `wiki/skills/funnels/`; the plan must decide whether the mirror should be exact at root, grouped, or indexed.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| List Codex skills | `find .codex/skills -maxdepth 2 -type f | sort` | inspect output |
| List wiki skills | `find wiki/skills -maxdepth 3 -type f | sort` | inspect output |
| Sync check | `python` or shell script chosen by executor | reports no unexpected drift |

## Scope

**In scope**:
- Define the expected mirror rule.
- Add missing wiki mirrors or index entries.
- Add a lightweight sync check command if useful.
- Update README if the rule changes.

**Out of scope**:
- Rewriting skill content.
- Deleting historical auditor/cursor skills.
- Moving active `.codex/skills` paths unless the user explicitly asks.

## Git Workflow

- Branch: `codex/sync-skills-docs`
- Commit message: `Sync Codex and wiki skills`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define the mirror contract

Choose and document one contract:

- exact root mirror: every `.codex/skills/<name>/SKILL.md` has `wiki/skills/<name>/SKILL.md`;
- grouped mirror: funnel skills live under `wiki/skills/funnels/` but `wiki/skills/README.md` maps the active `.codex` name to that path;
- index-only mirror: wiki records active skill names and canonical `.codex` paths.

Prefer grouped mirror if it preserves existing organization and avoids duplicating files unnecessarily.

### Step 2: Produce a drift report

Create a short checklist in the implementation PR notes:

- active `.codex` skill count,
- wiki mirror/index count,
- missing wiki entries,
- intentionally historical wiki-only entries.

Do not commit generated reports unless they are intended documentation.

### Step 3: Add or update mirrors

For each active skill without a mirror/index, either:

- add a wiki copy,
- or update `wiki/skills/README.md` to point to the grouped copy.

Keep content synchronized for rollout/spreadsheet skills if their flow changed.

### Step 4: Add a sync check if it stays simple

If a short script is useful, add it under an existing tools/scripts location and document a follow-up to include it in the canonical verify command after plan 022 exists.

The script should report missing mirrors, not auto-copy files.

## Test Plan

- Manual diff of representative paired skills.
- Sync check reports only documented exceptions.
- Markdown links in `wiki/skills/README.md` point to real files.

## Done Criteria

- [ ] The skill mirror/index rule is documented.
- [ ] Active `.codex/skills` entries have a wiki mirror or explicit wiki index entry.
- [ ] Rollout and spreadsheet skills remain synchronized.
- [ ] No generated drift report is committed unless intentionally documented.

## STOP Conditions

- Skill content has intentionally diverged and needs product-owner review.
- The sync rule would require moving many historical wiki skills unrelated to Contadores.

## Maintenance Notes

This is docs hygiene for future agent reliability. Keep it mechanical and avoid editing skill behavior unless a flow actually changed.
