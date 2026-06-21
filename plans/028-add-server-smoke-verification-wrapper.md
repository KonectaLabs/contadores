# Plan 028: Add Server Smoke Verification Wrapper

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- deploy_to_server.sh server_logs.sh README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/022-add-canonical-verification-command.md
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Repo policy says product changes are only done after deploy and real-server verification. Today there are scripts to deploy and tail logs, but no one-command server smoke wrapper that checks the deployed app state after the deploy script completes.

## Current State

- Deploy script only delegates to the remote deploy script:

```bash
deploy_to_server.sh:3
ssh -p 5389 root@149.50.136.121 'bash /root/deploy_contadores.sh'
```

- Logs script only delegates to the remote logs script:

```bash
server_logs.sh:3
ssh -p 5389 root@149.50.136.121 'bash /root/logs_contadores.sh'
```

- README rollout says to verify runtime, funnels, sheet ingestion, and WhatsApp flow:

```text
README.md:1622
Verificar `/api/runtime`, `/api/funnels`, la ingesta de sheet y el flujo de WhatsApp en el server.
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Existing deploy | `./deploy_to_server.sh` | exits 0 |
| Existing logs | `./server_logs.sh` | prints backend/bot logs |
| New smoke wrapper | chosen by executor | exits 0 or reports concrete failed check |

## Scope

**In scope**:
- Add a server smoke verification command or script.
- Check deployed commit, container status, `/health`, `/api/runtime`, `/api/funnels`, and relevant logs.
- Document exactly when to run it.

**Out of scope**:
- Changing remote deploy script internals unless necessary.
- Live WhatsApp sends.
- Live Meta writes.
- Replacing manual product-flow verification.

## Git Workflow

- Branch: `codex/server-smoke-verification`
- Commit message: `Add server smoke verification wrapper`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose wrapper shape

Prefer a simple root script such as:

```bash
./verify_server.sh
```

It can SSH to the same host as `deploy_to_server.sh`.

### Step 2: Implement safe read-only checks

Checks should be read-only:

- remote git commit/branch,
- `docker compose ps`,
- backend `/health`,
- backend `/api/runtime`,
- backend `/api/funnels`,
- tail backend and bot logs for recent obvious errors.

If auth blocks public API calls, use local container networking or documented internal token handling without printing secrets.

### Step 3: Keep product-flow checks manual

Document that this wrapper does not prove:

- sheet ingestion imported a real new lead,
- WhatsApp delivery sent,
- Meta live objects changed.

Those remain plan-specific verification steps.

### Step 4: Update rollout docs

Update README and rollout skills so the sequence is:

1. local verify,
2. commit on `main`,
3. push,
4. deploy,
5. server smoke wrapper,
6. plan-specific live checks.

## Test Plan

- Run wrapper against the current server if credentials are available.
- If not available, shell-check the script and document the blocked live run.
- Existing deploy/log scripts still work.

## Done Criteria

- [ ] A documented server smoke command exists.
- [ ] It is read-only and does not print secrets.
- [ ] README and rollout skills include it in the server-first workflow.
- [ ] Failure output names the failing check clearly.

## STOP Conditions

- SSH/server access is not available during implementation and the script cannot be safely tested.
- The remote server layout differs from assumptions and needs user confirmation.

## Maintenance Notes

This complements plan 022. Plan 022 is local pre-deploy verification; this plan is real-server smoke verification after deploy.
