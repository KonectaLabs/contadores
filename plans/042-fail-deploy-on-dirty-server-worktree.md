# Plan 042: Fail Deploy On Dirty Server Worktree

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- deploy_to_server.sh README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DEPLOY-03

## Why This Matters

Repo policy says the operative branch is `main` and deploys should come from committed `main` state. The current server worktree is dirty for `docker-compose.yml` and `traefik/dynamic.yml`, so deploy can run uncommitted production infrastructure that is not reviewable from the repo.

## Current State

- Remote deploy checks out and pulls `main`:

```bash
/root/deploy_contadores.sh:3
cd /root/projects/contadores
/root/deploy_contadores.sh:4
git checkout main
/root/deploy_contadores.sh:5
git pull --ff-only
```

- Remote status during planning:

```text
 M docker-compose.yml
 M traefik/dynamic.yml
main
bf8782e
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Remote git status | `ssh -p 5389 root@149.50.136.121 'cd /root/projects/contadores && git status --short'` | empty before deploy |
| Remote deploy script | `ssh -p 5389 root@149.50.136.121 'nl -ba /root/deploy_contadores.sh | sed -n "1,80p"'` | shows dirty-check gate after implementation |

## Scope

**In scope**:
- Add a dirty-worktree guard before remote deploy mutates containers.
- Allow only explicitly ignored local runtime files such as `.env`, `auth.toml`, and `data/`.
- Document how to handle intentional server-only changes.

**Out of scope**:
- Reverting current dirty remote files automatically.
- Committing or pushing server changes without operator review.
- Changing local dirty files in this Codex run.

## Git Workflow

- Branch: `codex/fail-deploy-dirty-server-worktree`
- Commit message: `Fail deploy on dirty server worktree`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a pre-pull dirty check

Before `git checkout main` or `git pull --ff-only`, inspect the remote worktree:

```bash
git status --porcelain
```

If any tracked file is modified, added, deleted, renamed, or conflicted, print the status and exit non-zero.

### Step 2: Add a post-pull clean check

After pulling, run the same clean check again before `docker compose build`.

This catches generated tracked changes caused by scripts or hooks.

### Step 3: Document the operator path

README and rollout skills should say:

- inspect the remote diff,
- either commit the intended infra change to `main`,
- or move server-only config into `.env`, `auth.toml`, `data/`, or documented untracked files,
- never deploy with dirty tracked infra files.

## Test Plan

- On a safe server checkout, create a harmless tracked-file diff and confirm deploy exits before build.
- Restore the diff manually.
- Confirm deploy proceeds only with a clean worktree.

## Done Criteria

- [ ] Remote deploy refuses dirty tracked files.
- [ ] Failure output includes `git status --short`.
- [ ] README and rollout skills document how to resolve dirty server state.
- [ ] No automatic reset or checkout discards operator changes.

## STOP Conditions

- Current production intentionally depends on uncommitted tracked infra changes.
- The remote script is outside repo control and cannot be updated safely.
- There is no agreed path for preserving current dirty `docker-compose.yml` or `traefik/dynamic.yml`.

## Maintenance Notes

Never fix this with `git reset --hard` in the deploy script. The point is to stop and surface drift, not erase it.
