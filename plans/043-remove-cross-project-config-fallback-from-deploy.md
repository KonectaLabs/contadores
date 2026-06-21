# Plan 043: Remove Cross-Project Config Fallback From Deploy

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- deploy_to_server.sh README.md .env.example .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: plans/025-audit-and-sync-env-contracts.md
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DEPLOY-04

## Why This Matters

Contadores/Konecta must not borrow credentials or config from other projects. The remote deploy script currently copies `.env` and `auth.toml` from `/root/projects/konecta-auditor` when local files are missing, which can boot the CRM with wrong users, sheets, webhook config, and secrets instead of failing provisioning clearly.

## Current State

Remote deploy fallback during planning:

```bash
/root/deploy_contadores.sh:6
if [ ! -f .env ] && [ -f /root/projects/konecta-auditor/.env ]; then
/root/deploy_contadores.sh:7
  cp /root/projects/konecta-auditor/.env .env
/root/deploy_contadores.sh:9
if [ ! -f auth.toml ] && [ -f /root/projects/konecta-auditor/auth.toml ]; then
/root/deploy_contadores.sh:10
  cp /root/projects/konecta-auditor/auth.toml auth.toml
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Inspect remote script | `ssh -p 5389 root@149.50.136.121 'nl -ba /root/deploy_contadores.sh | sed -n "1,80p"'` | no cross-project fallback after implementation |
| Check required local config | `ssh -p 5389 root@149.50.136.121 'cd /root/projects/contadores && test -f .env && test -f auth.toml'` | exits 0 |

## Scope

**In scope**:
- Remove fallback copying from `konecta-auditor` or any non-Contadores project.
- Add fail-closed checks for required `.env` and `auth.toml`.
- Document first-server provisioning requirements.

**Out of scope**:
- Printing secret values.
- Creating new credentials automatically.
- Reusing CleverApply, Alejandro, `cleverapply`, or other client credentials.

## Git Workflow

- Branch: `codex/remove-cross-project-config-fallback`
- Commit message: `Remove cross-project config fallback from deploy`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Replace fallback copy with required-file checks

The remote deploy should fail when `.env` or `auth.toml` is missing:

```bash
if [ ! -f .env ]; then
  echo "Missing /root/projects/contadores/.env. Provision Contadores credentials before deploy." >&2
  exit 1
fi
if [ ! -f auth.toml ]; then
  echo "Missing /root/projects/contadores/auth.toml. Provision Contadores auth before deploy." >&2
  exit 1
fi
```

Do not print file contents.

### Step 2: Add a config-origin check

Add a lightweight grep guard that fails if `.env`, auth files, deploy scripts, or docs mention forbidden credential origins:

- `cleverapply`,
- `clever-apply`,
- `konecta-auditor` as a fallback source,
- unrelated project paths.

Keep it scoped to preventing obvious cross-project fallback, not validating every secret.

### Step 3: Update provisioning docs

README and rollout skills should describe:

- `.env` is created for Contadores/Konecta only,
- `auth.toml` is created for Contadores/Konecta only,
- missing config blocks deploy,
- no temporary fallback to another client is allowed.

## Test Plan

- On a safe copy or staging server, rename `.env` and confirm deploy exits before build.
- Restore `.env`, rename `auth.toml`, and confirm deploy exits before build.
- Restore both and confirm deploy reaches the normal service checks.

## Done Criteria

- [ ] Remote deploy no longer copies config from another project.
- [ ] Missing `.env` fails with a clear provisioning message.
- [ ] Missing `auth.toml` fails with a clear provisioning message.
- [ ] Docs state that Contadores/Konecta credentials must be first-party.

## STOP Conditions

- The current production server actually depends on copied cross-project config and no Contadores config exists.
- Operator cannot confirm the correct Contadores `.env` or `auth.toml` source.
- A proposed fix would print or commit secrets.

## Maintenance Notes

This is a client-boundary fix. Convenience fallback is not acceptable for credentials or auth config.
