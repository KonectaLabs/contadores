# Plan 071: Add Bot Runtime Diagnostics Endpoint

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/main.py src/bot/utils.py src/bot/providers.py src/bot/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/039-add-compose-restart-and-bot-healthcheck.md
- **Category**: observability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OBS-01

## Why This Matters

The bot can keep running while degraded: backend startup may fail, AgentMail may be disabled, provider credentials may be missing, or the worker task may crash. The current `/health` endpoint always returns `{"status":"ok"}`, so operators and Compose health checks cannot distinguish healthy from degraded.

## Current State

- Startup logs backend readiness but continues when backend is not ready:

```python
src/bot/main.py:511
backend_ready = await wait_for_backend_ready(
```

- AgentMail startup failure disables email alerts and continues:

```python
src/bot/main.py:524
email_provider = AgentMailProvider()
```

- Worker task is stored in app state:

```python
src/bot/main.py:553
whatsapp_provider = WhatsAppProvider(app, on_whatsapp_inbound, on_whatsapp_status)
```

- Health always returns ok:

```python
src/bot/main.py:591
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Bot tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -q` | exit 0 |
| Bot import smoke | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run python -c "import main; print('bot-import-ok')"` | prints `bot-import-ok` |
| Diagnostics route scan | `rg -n "diagnostics|readiness|worker_task|/health" src/bot/main.py src/bot/tests` | route and tests are visible |

## Scope

**In scope**:
- Add a read-only bot diagnostics or readiness endpoint.
- Expose backend connectivity state, worker task state, provider configured/enabled state, last successful loop time, and last error summary.
- Decide whether `/health` remains liveness-only and a new `/ready` or `/diagnostics` carries readiness.
- Document the endpoint and Compose health usage.

**Out of scope**:
- Changing dispatch behavior.
- Reworking provider initialization.
- Replacing Compose health checks; plan 039/041 handle service wiring.

## Git Workflow

- Branch: `codex/bot-runtime-diagnostics`
- Commit message: `Add bot runtime diagnostics endpoint`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define liveness versus readiness

Keep `/health` as liveness if needed, but add an endpoint such as:

```text
GET /diagnostics
GET /ready
```

The response should avoid secrets and include only operational state.

### Step 2: Track worker loop state

Store a small diagnostics object in `app.state` or a dedicated runtime state dataclass:

- startup backend readiness,
- last backend issue,
- last successful worker cycle timestamp,
- last worker error,
- worker task done/cancelled status.

### Step 3: Include provider state

Report booleans such as:

- WhatsApp configured,
- AgentMail enabled,
- inbound inbox enabled,
- backend client present.

Do not include tokens, phone ids, or email API keys.

### Step 4: Add tests

Test healthy and degraded states without real provider calls.

### Step 5: Update docs

Explain which endpoint Compose should use for liveness and which endpoint operators should query when dispatch is degraded.

## Test Plan

- Bot tests pass.
- Bot import smoke passes.
- Manual local query returns degraded state when providers are disabled.

## Done Criteria

- [ ] Operators can distinguish bot liveness from readiness/degradation.
- [ ] Diagnostics expose no secrets.
- [ ] Worker task failure is visible.
- [ ] Tests and docs cover the endpoint.

## STOP Conditions

- The endpoint needs to call external services on every request.
- Diagnostics expose provider credentials or message payloads.
- Compose health behavior becomes stricter before plan 039/041 is ready.

## Maintenance Notes

Use diagnostics to shorten incident triage, not to restart services from the API.
