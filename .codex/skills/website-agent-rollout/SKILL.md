---
name: website-agent-rollout
description: Deploy, verify, back up, recover, or inspect Website Agent on the real server. Use for production changes, Docker Compose, server health, release SHAs, SQLite or PostgreSQL safety, logs, rollback planning, and deciding whether a Contadores change is truly live.
---

# Website Agent Rollout

## Boundary

Production uses:

```text
/root/projects/website-agent
/root/projects/agent-runtime
https://chatterface.fgoiriz.com
```

Use only the paths and public origin above. Never use historical root deploy
scripts.

## Preflight

1. Inspect both local repos and both server repos.
2. Require `main`, expected SHAs and clean tracked worktrees.
3. Verify `website-agent/.env` exists without printing secrets.
4. Run the tests documented in each repo. The current commands are:
   - Website Agent: `docker compose run --rm --no-deps app uv run --no-sync pytest`.
   - Agent Runtime contract against a running local runtime:
     `RUNTIME_URL=http://127.0.0.1:8000 uv run pytest`.
5. If data or schema can change, back up both stores before building:
   - `website-agent/data/website-agent.sqlite` with SQLite's online backup;
   - PostgreSQL `agent_runtime` in volume
     `website-agent_agent-runtime-postgres`, with `pg_dump` from the
     `postgres` container.

Never treat a SQLite copy as a complete backup of Agent Runtime.

## Deploy

On the server, update `agent-runtime` and `website-agent` to their approved
`main` SHAs with fast-forward-only pulls. From `/root/projects/website-agent`,
run:

```bash
docker compose build
docker compose up -d
docker compose ps
```

Do not delete volumes. Do not replace `.env`. Do not borrow credentials from
another client or project.

## Verification

Require all four services to be running. Require PostgreSQL and Agent Runtime
to be healthy. Then verify:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:2024/health
curl -fsS https://chatterface.fgoiriz.com/health
```

Inspect recent `app`, `agent-server`, `postgres` and `gateway` logs for new
errors. For behavior changes, verify the exact affected WhatsApp, admin,
publication, activity or cost flow. Health alone is not product QA.

Report repository commit, deploy, container health, public health and product
QA as separate gates.
