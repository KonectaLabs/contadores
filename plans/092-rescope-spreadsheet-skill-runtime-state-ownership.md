# Plan 092: Rescope Spreadsheet Skill Runtime State Ownership

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 009, 023
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DOCS-07

## Why This Matters

The spreadsheet skill correctly says sheets are not where DB side effects run, but later describes the sheet as source of truth for conversation sequence, bot replies, audio handling, next action, and handoff state. Current runtime state lives in backend persistence and the CRM/backoffice. Stale spreadsheet-state guidance can reintroduce sheet-managed runtime state and runtime mode switches the repo explicitly avoids.

## Current State

- The skill says DB side effects are not run from the sheet:

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:46
The spreadsheet is not the execution layer for autonomous Codex tools. Agent
```

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:47
tool side effects are persisted in the backend database (`contadores_messages`,
```

- Later it treats the spreadsheet as runtime source of truth:

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:289
Treat the spreadsheet as the source of truth for:
```

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:293
- which message sequence the lead is in;
```

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:295
- whether the conversational bot already sent `ai_reply` or
```

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:301
- when the next action should happen;
```

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:327
Use the existing lead columns as input data and add operational columns in the same sheet.
```

- README describes backend/CRM runtime state for current flows:

```markdown
README.md:954
- Las filas importadas se guardan en tablas dedicadas:
```

```markdown
README.md:1089
- Luego del offer y de la ventana de silencio, el backend llama a
```

```markdown
README.md:1243
Vista Manual del backoffice:
```

The wiki spreadsheet skill mirrors the stale text.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runtime-state stale scan | `rg -n "source of truth for:|wa_sequence|wa_step|wa_next_action_at|operational columns|which message sequence|next action should happen" .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md README.md` | stale sheet-owned runtime state language is gone or clearly historical |
| Current ownership scan | `rg -n "sheet.*intake|sheet.*config|runtime state lives|backend persistence|CRM|backoffice|data/funnels" .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md README.md` | current ownership is explicit |
| Mirror diff | `diff -u .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md` | no unexpected mirror drift |

## Scope

**In scope**:
- Update both spreadsheet skill mirrors.
- State that sheets are intake/config input.
- State that runtime state lives in backend persistence and CRM/backoffice.
- Remove or clearly mark old operational-column advice as historical/deprecated.

**Out of scope**:
- Changing sheet polling behavior.
- Changing funnel config model; plan 009 covers funnel source of truth.
- Building a docs mirror checker; plan 023 covers skill sync.

## Git Workflow

- Branch: `codex/rescope-spreadsheet-runtime-state-docs`
- Commit message: `Clarify spreadsheet runtime ownership`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Rewrite ownership language

Replace the "spreadsheet as source of truth" section with the current model:

- sheet rows provide intake/contact/config input,
- backend DB owns message sequence, automation state, runtime alerts, and delivery status,
- CRM/backoffice is the operator surface.

### Step 2: Remove operational column guidance

Delete or deprecate recommended `wa_*` operational columns unless they are still actively used by current code.

If kept for historical import compatibility, label them explicitly as legacy.

### Step 3: Keep mirrors aligned

Apply the same edits to `.codex/skills/contadores-spreadsheet/SKILL.md` and `wiki/skills/contadores-spreadsheet/SKILL.md`.

### Step 4: Run scans

Run stale and current ownership scans. Confirm any remaining stale phrases are historical, not instructions.

## Test Plan

- Docs scans pass.
- No runtime tests are required because this is docs-only.
- Plan 023 can later enforce mirror sync mechanically.

## Done Criteria

- [ ] Spreadsheet skill no longer assigns runtime-state ownership to the sheet.
- [ ] Current DB/CRM ownership is explicit.
- [ ] `.codex` and `wiki` mirrors remain aligned.

## STOP Conditions

- Current code still reads any of the proposed deprecated `wa_*` columns as runtime state.
- Product decision changes back to sheet-managed runtime state.
- Mirror files intentionally diverge.

## Maintenance Notes

This repo should not reintroduce sheet-managed conversation state without an explicit product/design decision.
