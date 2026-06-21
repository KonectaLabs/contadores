# Plan 039: Add Compose Restart Policies And Bot Healthcheck

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- docker-compose.yml src/bot/main.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DEPLOY-01

## Why This Matters

The repo is operated against the real server, and the bot handles WhatsApp webhooks, Calendly webhooks, and dispatch loops. `docker-compose.yml` has no restart policy, and only the backend has a healthcheck. If the bot process exits after deploy, Compose will not mark the bot unhealthy or restart it unless the remote runtime adds policy outside the repo.

## Current State

- Backend has a healthcheck:

```yaml
docker-compose.yml:32
healthcheck:
  test:
    [
      "CMD",
      "python",
      "-c",
      "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://localhost:8000/health', timeout=2).status == 200 else sys.exit(1)",
    ]
```

- Bot depends on backend health but has no healthcheck of its own:

```yaml
docker-compose.yml:68
depends_on:
  backend:
    condition: service_healthy
```

- The bot already exposes `/health`:

```python
src/bot/main.py:591
@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
```

- README documents the services but not restart or bot health behavior:

```text
README.md:1595
Servicios:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Compose config validation | `docker compose config` | exits 0 and renders restart/healthcheck settings |
| Backend image build | `docker compose build backend` | exits 0 |
| Bot image build | `docker compose build bot` | exits 0 |

## Scope

**In scope**:
- `docker-compose.yml`
- README deployment section.
- A bot healthcheck that uses the existing `/health` endpoint.

**Out of scope**:
- Changing Traefik routing.
- Changing backend `/health` readiness semantics.
- Changing bot startup or dispatch loop behavior.
- Changing remote deploy scripts.
- Migrating away from SQLite or one backend worker.

## Git Workflow

- Branch: `codex/compose-restart-bot-healthcheck`
- Commit message: `Add Compose restart policies and bot healthcheck`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add restart policies

Add an explicit restart policy to each long-running service:

```yaml
restart: unless-stopped
```

Apply it to:

- `traefik`,
- `backend`,
- `bot`.

Keep indentation consistent and run `docker compose config` after editing.

### Step 2: Add a bot healthcheck

Add a healthcheck to the `bot` service using Python stdlib, matching the backend style:

```yaml
healthcheck:
  test:
    [
      "CMD",
      "python",
      "-c",
      "import urllib.request,sys; sys.exit(0) if urllib.request.urlopen('http://localhost:8100/health', timeout=2).status == 200 else sys.exit(1)",
    ]
  interval: 10s
  timeout: 3s
  retries: 12
  start_period: 10s
```

Do not add curl or wget just for healthchecks.

### Step 3: Keep backend health as liveness

Do not make the backend container healthcheck fail when `/health` returns `ready=false`. Existing tests document that `/health` can be 200 while runtime readiness is false. Server smoke/readiness belongs in plan 028.

### Step 4: Update README

In the Docker deployment section, document:

- Compose uses `restart: unless-stopped`,
- backend and bot expose healthchecks,
- backend readiness still needs `/api/runtime` or the server smoke wrapper,
- the bot stores inbound webhook buffer state under `data/`.

## Test Plan

- Run `docker compose config`.
- Build backend and bot images.
- If safe on the target machine, run `docker compose up -d backend bot` and confirm `docker compose ps` reports healthy services.

## Done Criteria

- [ ] Long-running services have explicit restart policies.
- [ ] Bot has a Docker healthcheck using `/health`.
- [ ] Backend healthcheck remains liveness, not readiness.
- [ ] README explains restart and healthcheck behavior.
- [ ] Compose config validation passes.

## STOP Conditions

- Remote server uses a supervisor that conflicts with Compose restart policies.
- Bot `/health` is not reachable from inside the bot container.
- `docker compose config` changes service wiring outside restart/health settings.

## Maintenance Notes

This plan improves process resilience only. It does not prove business readiness; continue using `/api/runtime` and the plan 028 server smoke wrapper after deploy.
