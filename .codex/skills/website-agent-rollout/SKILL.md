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
5. Inspect every pending Alembic revision. Routine backward-compatible
   revisions run without an ad hoc per-deploy backup. A destructive or
   irreversible revision requires an explicit recovery plan and a consistent
   backup of both stores before rollout. Never treat a SQLite copy as a
   complete backup of Agent Runtime.
6. If `website-agent/data/gym.sqlite` exists, preserve it with every production
   backup. It is an annotation sidecar outside both Alembic histories; never
   delete or recreate it during an ordinary rollout.

## Deploy

On the server, update `agent-runtime` and `website-agent` to their approved
`main` SHAs with fast-forward-only pulls. From `/root/projects/website-agent`,
build a generic runtime image tagged with the approved runtime SHA. Then build
the concrete Website Agent image from that exact base:

```bash
RUNTIME_SHA=<approved-agent-runtime-sha>
docker build -t "agent-runtime:${RUNTIME_SHA}" /root/projects/agent-runtime
AGENT_RUNTIME_IMAGE="agent-runtime:${RUNTIME_SHA}" docker compose build
docker compose up -d postgres
docker compose run --rm --no-deps agent-server \
  uv run --no-sync alembic -c /runtime/alembic.ini upgrade head
docker compose run --rm --no-deps app \
  uv run --no-sync alembic -c /app/alembic.ini upgrade head
docker compose up -d
docker compose ps
```

Do not put migrations in container startup commands. A failed migration stops
the rollout before the application services are replaced. The initial
revisions are forward-only adoption revisions: they preserve extra legacy
tables or columns, and Agent Runtime refuses a partial owned PostgreSQL schema.

Never build `agent-server` from an unversioned sibling checkout. Record the
runtime image tag together with both repository SHAs.

Do not delete volumes. Do not replace `.env`. Do not borrow credentials from
another client or project.

## Automatic deployment

Each operational repo owns an independent GitHub Actions workflow triggered by
every push to `main`. Merging a pull request into `main` creates such a push and
therefore triggers the same automatic production deployment; no second manual
deploy is required. Both use the GitHub `production` environment and the secrets
`DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_SSH_PRIVATE_KEY` and
`DEPLOY_KNOWN_HOSTS`.

- Website Agent deploys its exact pushed SHA, builds `app` and the concrete
  `agent-server`, runs both Alembic histories, and reconciles the full Compose.
- Agent Runtime deploys its exact pushed SHA, builds the versioned generic
  runtime image, runs only its PostgreSQL Alembic history, and replaces only
  `agent-server`.

The repos do not dispatch each other's workflows. The server serializes both
pipelines with `/run/lock/website-agent-deploy.lock`. Confirmed release SHAs
live under `/root/projects/.deploy/`. A stale workflow that no longer matches
the fetched `origin/main` exits without rolling production backward.

Website Agent writes `website-agent.pending` immediately before replacing live
containers and removes it only after health and confirmed state. Agent Runtime
must refuse deployment while that marker exists; rerun or reconcile Website
Agent first. A checkout/state difference without the marker is safe because
Runtime builds the confirmed Website SHA from an immutable archive.

GitHub Actions must use strict host-key checking and an exact known-hosts
secret. Never use a third-party SSH action or put production application
secrets in GitHub; `.env` remains only on the server.

For the first activation, deploy Agent Runtime before Website Agent. The first
Website Agent revision that calls `/runtime/alembic.ini` requires the new
versioned runtime image to be confirmed first. After this bootstrap, the two
push workflows operate independently.

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
