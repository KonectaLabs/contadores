---
name: konecta-auditor-server-deploy
description: Canonical production deploy and log-check workflow for Konecta Auditor. Use when the task involves deploying to the VPS, checking production runtime logs, or validating server-side state after a release.
---

# Konecta Auditor Server Deploy

## Use This Skill When
- deploying Konecta Auditor to the VPS,
- checking production logs after a deploy,
- validating whether a production fix is really live on the server.

## Canonical Deploy Workflow
1. Make the intended code changes locally.
2. Commit only the intended files.
3. Push the deployable state to `main`.
4. Run `./deploy_to_server.sh` from the repo root.
5. Run `./server_logs.sh` to watch the live server logs.
6. Verify the production end state through logs, API checks, and DB state when relevant.

## Non-Negotiable Rule
- Do not deploy Konecta Auditor by `scp`, ad hoc remote file edits, or manual container rebuilds unless the user explicitly asks for an emergency/manual server intervention.
- The normal deploy path is always:
  - commit,
  - push to `main`,
  - `./deploy_to_server.sh`,
  - `./server_logs.sh`.

## Important Repository Detail
- `deploy_to_server.sh` SSHes to the server and runs `/root/deploy_konecta_auditor.sh`.
- The remote deploy script does:
  - `cd /root/projects/konecta-auditor`
  - `git checkout main`
  - `git pull`
  - `docker compose build`
  - `docker compose up -d`
- Because of that, a branch-only local commit is not enough. The change must be present on `main` before running the deploy script.

## Required Validation After Deploy
- confirm the target container is up,
- watch `./server_logs.sh` for startup/runtime errors,
- verify the specific user-facing fix on the live server,
- when the task affects persisted flows, inspect live DB/API state too.

## Zen Alignment
Apply `zen-of-development` while executing this skill:
- Keep the deploy path simple and repeatable.
- Prefer one canonical release workflow over clever manual shortcuts.
- Validate the real production behavior after deployment, not just the build output.
