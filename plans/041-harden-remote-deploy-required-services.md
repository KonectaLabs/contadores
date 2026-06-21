# Plan 041: Harden Remote Deploy Required Services

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- deploy_to_server.sh README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/039-add-compose-restart-and-bot-healthcheck.md
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DEPLOY-02

## Why This Matters

The repo policy says product changes are not done until the real server is deployed and verified. The current remote deploy script can finish after `docker compose up -d` even when required services are exited or unrouted. During this audit, only Traefik was running and `https://crm.fgoiriz.com/health` returned `502`.

## Current State

- Local deploy only delegates to the remote script:

```bash
deploy_to_server.sh:3
ssh -p 5389 root@149.50.136.121 'bash /root/deploy_contadores.sh'
```

- Remote deploy currently ends with build/up/ps:

```bash
/root/deploy_contadores.sh:12
docker compose build
/root/deploy_contadores.sh:13
docker compose up -d
/root/deploy_contadores.sh:14
docker compose ps
```

- Real-server check during planning:

```text
curl -I https://crm.fgoiriz.com/health
HTTP/2 502
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Inspect remote deploy | `ssh -p 5389 root@149.50.136.121 'nl -ba /root/deploy_contadores.sh | sed -n "1,120p"'` | prints deploy script |
| Remote service status | `ssh -p 5389 root@149.50.136.121 'cd /root/projects/contadores && docker compose ps'` | backend, bot, and traefik are running |
| Public health | `curl -fsS https://crm.fgoiriz.com/health` | exits 0 after deploy |

## Scope

**In scope**:
- Add required-service checks to the remote deploy flow.
- Fail the deploy when `backend`, `bot`, or `traefik` are missing, exited, unhealthy, or unrouted.
- Update local rollout docs and skills with the fail-closed behavior.

**Out of scope**:
- Changing application code.
- Changing Traefik routing; plan 044 covers HTTPS routing.
- Adding live WhatsApp or Meta checks.
- Masking service failures by restarting in a loop without reporting the failure.

## Git Workflow

- Branch: `codex/harden-remote-deploy-required-services`
- Commit message: `Harden remote deploy required service checks`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add required service assertions

Update the remote deploy script or add a repo-owned script it calls so deploy fails unless these services exist and are running:

- `backend`,
- `bot`,
- `traefik`.

Use `docker compose ps --format json` if available, or a small readable shell fallback. Avoid parsing pretty table columns if Compose JSON is available.

### Step 2: Add health and route checks

After `docker compose up -d`, check:

- backend container health if plan 039 has landed,
- bot container health if plan 039 has landed,
- `http://backend:8000/health` from the Docker network or host,
- public `https://crm.fgoiriz.com/health` after Traefik routing is expected to work.

If HTTPS routing is not fixed yet, make that check conditional and clearly print `blocked by plan 044` rather than silently passing.

### Step 3: Print actionable failure output

On failure, print:

- `docker compose ps`,
- recent backend logs,
- recent bot logs,
- the exact failed check.

Do not print `.env`, tokens, auth files, or full environment dumps.

### Step 4: Update rollout docs

Update README and rollout skills so deploy is considered failed when required services are not running and healthy.

## Test Plan

- Run the remote deploy in a controlled deploy window.
- Confirm it exits non-zero when a required service is stopped.
- Confirm it exits zero only when required services are up and health checks pass.

## Done Criteria

- [ ] Remote deploy fails closed if backend, bot, or Traefik are down.
- [ ] Failure output names the failed service/check.
- [ ] Public health is checked or explicitly blocked behind plan 044.
- [ ] README and rollout skills document the required-service gate.

## STOP Conditions

- Remote deploy script cannot be changed safely from the repo.
- Current server is intentionally partial and should not require bot.
- Docker Compose version lacks the needed output format and no safe fallback is chosen.

## Maintenance Notes

This plan turns deploy verification into an enforceable gate. Plan 028 can still provide broader post-deploy smoke checks.
