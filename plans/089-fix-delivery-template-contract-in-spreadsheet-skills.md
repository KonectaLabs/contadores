# Plan 089: Fix Delivery Template Contract In Spreadsheet Skills

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md src/scripts/whatsapp_template_specs/konecta_delivery_lead_alert_es.json src/backend/endpoints/client_leads.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 023
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DOCS-04

## Why This Matters

The current Delivery WhatsApp templates use three positional parameters, but the spreadsheet skill mirrors still describe an older five/six-parameter contract. Future agents following the skill could create or approve the wrong Meta template shape and cause runtime send failures.

## Current State

- The default spec uses three positional values:

```json
src/scripts/whatsapp_template_specs/konecta_delivery_lead_alert_es.json:8
"body": "Nuevo Lead: {{1}}.\n\ndatos del Lead:\n{{2}}\n\nPara abrir el chat:\n{{3}}\nPara abrir el chat entrar al link."
```

- Backend sends exactly three params:

```python
src/backend/endpoints/client_leads.py:636
def build_template_params(source: ClientLeadSource, item: ClientLeadDelivery) -> list[str]:
```

```python
src/backend/endpoints/client_leads.py:638
return [
```

- README documents the current three-param shape:

```markdown
README.md:960
con `konecta_delivery_lead_alert_es`. Ambos templates llevan 3 parametros:
```

- The spreadsheet skills still describe the stale shape:

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:227
It uses positional params: source label, lead name, lead phone, email, and the
```

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:231
with the same first five params plus a single-line context param.
```

The wiki mirror has the same text at the same section.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Stale phrase scan | `rg -n "same first five|lead name, lead phone|source label, lead name|lead phone, email" .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md README.md` | no stale Delivery template contract text remains |
| Current contract scan | `rg -n "3 parametros|three params|bloque unico|single.*lead data|konecta_delivery_lead_alert" .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md README.md src/backend/endpoints/client_leads.py` | both skill mirrors describe the three-param shape |
| Mirror diff | `diff -u .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md` | no unexpected drift in mirrored sections |

## Scope

**In scope**:
- Update both `.codex` and `wiki` spreadsheet skill mirrors.
- Describe the current three-parameter template shape.
- Clarify that context is included inside the single lead-data block, not as a fourth/sixth template param.

**Out of scope**:
- Changing template specs.
- Changing backend delivery params.
- Building a mechanical skill mirror checker; plan 023 covers general sync.

## Git Workflow

- Branch: `codex/fix-delivery-template-skill-contract`
- Commit message: `Fix Delivery template skill contract`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Update the default template paragraph

Replace the stale five-param description with:

- campaign/source title,
- one lead-data block,
- `https://wa.me/` chat link.

### Step 2: Update context-enabled wording

Clarify that context fields are appended into the lead-data block as `Nombre del campo: valor`, then joined for Meta as a single positional parameter.

### Step 3: Keep mirrors aligned

Apply the same text to `.codex/skills/contadores-spreadsheet/SKILL.md` and `wiki/skills/contadores-spreadsheet/SKILL.md`.

### Step 4: Run scans

Run the stale phrase and current contract scans. Do not stop at a visual edit.

## Test Plan

- Stale phrase scan returns no false contract text.
- Current contract scan finds the updated wording in both mirrors.
- No runtime tests are required because this is docs-only.

## Done Criteria

- [ ] Spreadsheet skills match the current three-param Delivery template.
- [ ] `.codex` and `wiki` mirrors are consistent.
- [ ] Stale five/six-param wording is gone.

## STOP Conditions

- Template specs changed after this plan and no longer use three params.
- Backend `build_template_params()` changed after this plan.
- Mirror files intentionally diverged for a reason documented elsewhere.

## Maintenance Notes

When template specs change, update README and skill mirrors in the same commit as the runtime/template change.
