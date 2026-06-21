# Plan 094: Scope Follow-up Runner Secrets And Execution Privileges

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts/run_contadores_crm_hourly_followup.sh scripts/launchd/com.konecta.contadores.crm-followup.plist .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: 079
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OPS-03

## Why This Matters

The hourly local LaunchAgent starts an autonomous `codex exec` session. Today the wrapper sources the full repo `.env`, exports every variable, and then launches Codex with inherited shell environment plus bypassed approvals and sandboxing. That gives the scheduled model run broad filesystem access and every local secret in `.env`, even if the actual task only needs a narrow CRM API token and runner context.

This is separate from plan 079. Plan 079 narrows what the internal token can do on the backend. This plan narrows what the local scheduled runner can see and execute.

## Current State

- The runner exports every `.env` value into the shell environment:

```bash
scripts/run_contadores_crm_hourly_followup.sh:76
if [ -f "$ROOT_DIR/.env" ]; then
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:77
set -a
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:79
source "$ROOT_DIR/.env"
```

- The runner launches Codex with approval/sandbox bypass and full inherited env:

```bash
scripts/run_contadores_crm_hourly_followup.sh:206
codex exec \
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:209
--dangerously-bypass-approvals-and-sandbox \
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:210
-c shell_environment_policy.inherit=all \
```

- The LaunchAgent fixes local paths and starts the wrapper hourly:

```xml
scripts/launchd/com.konecta.contadores.crm-followup.plist:16
<key>StartInterval</key>
```

```xml
scripts/launchd/com.konecta.contadores.crm-followup.plist:28
<key>EnvironmentVariables</key>
```

- Docs say the runner loads `.env` and operates against production:

```markdown
README.md:773
- Cada hora se crea una ejecucion nueva de `codex exec`, lee
```

```markdown
README.md:777
- Requiere `INTERNAL_API_TOKEN` en `.env` local o en el entorno. El runner carga
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runner privilege scan | `rg -n "source \"\\$ROOT_DIR/.env\"|set -a|dangerously-bypass|shell_environment_policy\\.inherit|INTERNAL_API_TOKEN|CONTADORES_CRM_FOLLOWUP_RUNNER" scripts README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md` | runner privilege model is explicit and least-privilege |
| Shell syntax | `bash -n scripts/run_contadores_crm_hourly_followup.sh` | exit 0 |
| LaunchAgent syntax visibility | `plutil -lint scripts/launchd/com.konecta.contadores.crm-followup.plist` | plist is valid |

## Scope

**In scope**:
- Stop passing the whole `.env` into the scheduled `codex exec` child.
- Build a minimal allowlisted environment for the Codex child process.
- Keep only variables needed for the runner, such as `HOME`, `CODEX_HOME`, `PATH`, `CONTADORES_CRM_FOLLOWUP_*`, and the narrow API token required after plan 079.
- Remove `shell_environment_policy.inherit=all` if Codex supports an explicit allowlist.
- If sandbox/approval bypass is still required for LaunchAgent operation, document why and reduce surrounding privileges.
- Update README and follow-up automation skill mirrors.

**Out of scope**:
- Changing backend token capabilities; plan 079 covers that.
- Changing which machine-only endpoints accept browser sessions; plan 080 covers that.
- Changing the runner target URL; plan 093 covers target config and HTTP/HTTPS policy.
- Removing the local LaunchAgent.

## Git Workflow

- Branch: `codex/scope-followup-runner-privileges`
- Commit message: `Scope follow-up runner privileges`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Inventory required variables

List the exact environment variables the runner needs before and during `codex exec`.

Separate:

- variables needed by the shell wrapper,
- variables needed by preflight/status sync scripts,
- variables needed by the Codex child.

### Step 2: Build a minimal child environment

Keep `.env` loading for the wrapper only if needed, but construct the Codex child environment explicitly.

Prefer a pattern that is easy to read, for example:

```bash
env -i \
  HOME="$HOME" \
  CODEX_HOME="$CODEX_HOME" \
  PATH="$PATH" \
  CONTADORES_CRM_FOLLOWUP_RUNNER=1 \
  INTERNAL_API_TOKEN="$INTERNAL_API_TOKEN" \
  codex exec ...
```

Use the final narrow token name from plan 079 if that plan has landed.

### Step 3: Reduce Codex execution flags

Try removing `--dangerously-bypass-approvals-and-sandbox` and `shell_environment_policy.inherit=all`.

If LaunchAgent execution fails without the bypass, keep the minimum required flag and add a short comment explaining the operational reason. Do not leave full env inheritance.

### Step 4: Update docs

README and both follow-up automation skills should state:

- which token the runner uses,
- which env vars are passed to Codex,
- that the child process must not receive unrelated provider credentials,
- how to inspect the LaunchAgent without printing secrets.

### Step 5: Verify without running a live hourly cycle

Run syntax checks and scans only. Do not kickstart the LaunchAgent during this plan.

## Test Plan

- Shell and plist syntax pass.
- `rg` scan confirms no full environment inheritance remains unless explicitly justified.
- Docs describe the runner privilege boundary.
- No production follow-up run is started during verification.

## Done Criteria

- [ ] Scheduled Codex child no longer inherits every `.env` value.
- [ ] Runner docs name the env/token boundary.
- [ ] Any remaining sandbox/approval bypass is justified and isolated.
- [ ] Verification does not send messages or run a live hourly cycle.

## STOP Conditions

- Codex CLI has no supported way to run under a minimal environment.
- The runner currently depends on provider credentials that are not documented as part of the follow-up automation contract.
- Plan 079 changes the internal-token model while this plan is being implemented.

## Maintenance Notes

Scheduled local agents should be treated as production workers. Keep their secret surface narrow, explicit, and documented.
