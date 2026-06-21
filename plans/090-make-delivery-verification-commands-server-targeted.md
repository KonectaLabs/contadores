# Plan 090: Make Delivery Verification Commands Server Targeted

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- .codex/skills/client-lead-delivery-flow/SKILL.md wiki/skills/client-lead-delivery-flow/SKILL.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: 028
- **Category**: docs
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DOCS-05

## Why This Matters

The repo rule is server-first: product work is done only after deployment and real-server verification. Some Delivery runbooks still show `127.0.0.1:8000` for live verification commands. An executor can accidentally verify a local app and mark Delivery live when the server was never checked.

## Current State

- README says server verification is required:

```markdown
README.md:1613
`ALWAYS_DEPLOY`: un cambio de producto no esta terminado por compilar local,
```

```markdown
README.md:1622
4. Verificar `/api/runtime`, `/api/funnels`, la ingesta de sheet y el flujo de WhatsApp en el server.
```

- Client Lead Delivery skill reload/sync commands point at localhost:

```markdown
.codex/skills/client-lead-delivery-flow/SKILL.md:170
curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
```

```markdown
.codex/skills/client-lead-delivery-flow/SKILL.md:171
http://127.0.0.1:8000/api/client-lead-sources/config/reload
```

```markdown
.codex/skills/client-lead-delivery-flow/SKILL.md:195
http://127.0.0.1:8000/api/client-lead-sources/{source_id}/sync
```

- Rollout skill server verification also points at localhost:

```markdown
.codex/skills/contadores-rollout/SKILL.md:250
Server verification:
```

```markdown
.codex/skills/contadores-rollout/SKILL.md:254
http://127.0.0.1:8000/api/client-lead-sources
```

- Spreadsheet manual sync also points at localhost:

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:181
curl -fsS -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
```

```markdown
.codex/skills/contadores-spreadsheet/SKILL.md:182
http://127.0.0.1:8000/api/client-lead-sources/{source_id}/sync
```

The wiki mirrors contain the same localhost commands.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Delivery localhost scan | `rg -n "127\\.0\\.0\\.1:8000/api/client-lead|localhost:8000/api/client-lead" .codex/skills wiki/skills README.md` | no live Delivery verification command is ambiguous |
| Server-target scan | `rg -n "crm\\.fgoiriz\\.com|ssh .*contadores|docker compose exec|server real|real server|X-Internal-Token" .codex/skills/client-lead-delivery-flow/SKILL.md .codex/skills/contadores-rollout/SKILL.md .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/client-lead-delivery-flow/SKILL.md wiki/skills/contadores-rollout/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md` | runbooks explain where commands execute |
| Mirror diff | `diff -u .codex/skills/client-lead-delivery-flow/SKILL.md wiki/skills/client-lead-delivery-flow/SKILL.md && diff -u .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md && diff -u .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md` | no unexpected mirror drift |

## Scope

**In scope**:
- Update live Delivery verification commands to be explicitly server-targeted.
- Clarify when a localhost command is only for development inside a server SSH/container context.
- Keep `.codex` and `wiki` mirrors aligned.

**Out of scope**:
- Creating the server smoke wrapper; plan 028 covers that.
- Changing API routes or auth.
- Removing all README localhost development examples.

## Git Workflow

- Branch: `codex/server-target-delivery-verification-docs`
- Commit message: `Clarify Delivery server verification commands`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose the canonical server command style

Use the same style as the rollout docs expect after plan 028:

- production host URL with required headers, or
- SSH into the server and run curl from the server/container context.

Do not leave bare `127.0.0.1` under a heading called server verification.

### Step 2: Update Delivery flow skill

Clarify reload, sync, leads, and pending notification checks.

Mark local commands as local-only if they remain useful during development.

### Step 3: Update rollout and spreadsheet skills

Bring the same wording into `.codex/skills/contadores-rollout`, `wiki/skills/contadores-rollout`, `.codex/skills/contadores-spreadsheet`, and its wiki mirror.

### Step 4: Run scans

Run the localhost scan and confirm any remaining localhost Delivery commands are explicitly labeled local-only or server-SSH-local.

## Test Plan

- Documentation scans pass.
- No runtime tests are required because this is docs-only.
- Plan 028 can later replace these explicit examples with a canonical script.

## Done Criteria

- [ ] Live Delivery verification cannot be confused with local verification.
- [ ] Server-target commands include required auth/token context.
- [ ] `.codex` and `wiki` mirrors remain aligned.

## STOP Conditions

- The actual production verification endpoint or host is unknown.
- Plan 028 changes the canonical verification shape before this plan is started.
- Some localhost commands are intentionally server-side but cannot be described clearly.

## Maintenance Notes

Keep development localhost commands and server verification commands in separate labeled blocks.
