---
name: konecta-auditor-repeatable-deploy
description: Repeatable Konecta Auditor deploy checklist. Use when the goal is to ship current local changes to the VPS quickly and safely with the same commit, push, deploy, and verification sequence every time.
---

# Konecta Auditor Repeatable Deploy

## Use This Skill When
- deploying the current local changes to production,
- wanting a simple exact checklist instead of re-thinking deploy steps,
- verifying whether the VPS is really on the intended commit,
- recovering from a half-finished deploy where the SSH stream or log tail was interrupted.

## Goal
Run the same minimal release loop every time:
1. confirm what should ship,
2. commit only that,
3. push `main`,
4. run the canonical VPS deploy script,
5. verify backend health and service state,
6. call out any remaining runtime issues separately from the deploy result.

## Preflight Checklist
Before committing:
- run `git status --short --branch`
- run `git diff --stat`
- exclude local tooling noise such as:
  - `.cursor/hooks/state/continual-learning.json`
  - `.cursor/hooks/state/continual-learning-index.json`
- sanity-check touched code with the cheapest relevant commands for the files involved

Good default checks:
- frontend-only:
  - `node --check frontend/static/js/app.js`
- touched Python files:
  - `uv run python -m py_compile path/to/file.py ...`
- backend wiring/import safety:
  - `AUTH_DISABLE=true uv run python -c "from backend.main import app; print('backend-import-ok')"`

Important note:
- do not block a deploy on imaginary test coverage.
- if `pytest` is not actually installed in the repo environment, say that clearly and continue with the available sanity checks.

## Commit Checklist
1. Stage only the intended repo files.
2. Re-check staged scope with:
   - `git diff --cached --stat`
3. Commit on `main`.
4. Push to `origin main`.

Rules:
- never include the `.cursor/hooks/state/*` files in the deploy commit.
- do not assume a local branch-only commit is deployable.
- the target commit must exist on `origin/main` before running the server deploy script.

## Canonical Deploy Commands
Run from repo root:

```bash
git push origin main
bash ./deploy_to_server.sh
```

Why:
- `deploy_to_server.sh` is the canonical path for this repo.
- it SSHes to the VPS and runs `/root/deploy_konecta_auditor.sh`.
- the remote script checks out `main`, pulls, rebuilds, and runs `docker compose up -d`.

## Post-Deploy Verification
Run these exact checks:

1. Server commit is correct:
```bash
ssh root@149.50.136.121 'cd /root/projects/konecta-auditor && git rev-parse --short HEAD && git status --short --branch'
```

2. Services are up:
```bash
ssh root@149.50.136.121 'cd /root/projects/konecta-auditor && docker compose ps -a'
```

3. Backend health is green:
```bash
ssh root@149.50.136.121 'cd /root/projects/konecta-auditor && docker compose exec -T backend python -c "import urllib.request; r=urllib.request.urlopen(\"http://127.0.0.1:8000/health\", timeout=5); print(r.status); print(r.read().decode())"'
```

4. Log pass:
```bash
bash ./server_logs.sh
```

If you want a bounded log read instead of an endless tail:
```bash
ssh root@149.50.136.121 'cd /root/projects/konecta-auditor && docker compose logs --tail=60 backend bot'
```

## How To Judge Success
Treat the deploy as successful when all are true:
- server HEAD matches the pushed commit,
- `git status` on the server is clean on `main`,
- `backend` is `healthy`,
- `bot` is `up`,
- backend `/health` returns `200` and `{"status":"ok"}`.

Important distinction:
- a pre-existing runtime issue in the bot logs does not necessarily mean the deploy failed.
- report it separately as an existing production problem unless the new change clearly caused it.

## Common Recovery Cases

### Case 1: `deploy_to_server.sh` says permission denied
Run:
```bash
bash ./deploy_to_server.sh
```

### Case 2: Backend is healthy but bot is exited because the deploy stream was interrupted
Cause:
- the local SSH session was cut before the remote `docker compose up -d` fully finished.

Fix:
- rerun the canonical deploy again:
```bash
bash ./deploy_to_server.sh
```
- then re-check:
  - `docker compose ps -a`
  - backend `/health`

### Case 3: first health check gets `connection refused`
Cause:
- you hit the backend during the restart window.

Fix:
- wait a few seconds,
- rerun:
  - `docker compose ps -a`
  - backend `/health`

### Case 4: repo moved warning during `git push`
Current behavior:
- Git may print that the repository moved from `Fakamoto/konecta-auditor` to `KonectaLabs/konecta-auditor`.

Rule:
- if the push still succeeds, continue the deploy.
- treat the message as informational unless push actually fails.

## Output Template
After deploy, summarize in this shape:
- commit shipped
- whether `.cursor` state files were excluded
- whether deploy script completed
- server HEAD
- backend health result
- service status result
- any separate pre-existing runtime issue seen in logs

## Non-Negotiable Constraints
- do not use `scp` or manual remote edits for normal deploys.
- do not rebuild containers manually outside the canonical script unless the user explicitly asks for emergency intervention.
- do not describe a deploy as complete until you verify the actual live server state.
