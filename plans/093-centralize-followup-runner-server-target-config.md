# Plan 093: Centralize Follow-up Runner Server Target Config

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts/run_contadores_crm_hourly_followup.sh scripts/sync_contadores_crm_runner_status.py README.md .env.example .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: 074, 090
- **Category**: operations
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OPS-02

## Why This Matters

The local hourly follow-up runner fetches snapshots and syncs status to production. Its target is hardcoded as raw HTTP to the server IP with a `Host: crm.fgoiriz.com` header while sending `X-Internal-Token`. If the server IP, routing, HTTPS policy, or host changes, the scheduled runner can silently fail or keep using a stale target while docs point somewhere else. The current default also sends the machine token over plain HTTP unless the network path is otherwise protected.

This is runtime behavior, not just runbook wording.

## Current State

- The shell runner hardcodes the snapshot URL:

```bash
scripts/run_contadores_crm_hourly_followup.sh:42
SNAPSHOT_URL="http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12"
```

- It hardcodes the Host header in curl:

```bash
scripts/run_contadores_crm_hourly_followup.sh:126
curl -fsS \
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:127
-H "Host: crm.fgoiriz.com" \
```

- The status sync script has its own hardcoded defaults:

```python
scripts/sync_contadores_crm_runner_status.py:15
DEFAULT_STATUS_URL = "http://149.50.136.121/api/contadores/followup/runner/status"
```

```python
scripts/sync_contadores_crm_runner_status.py:16
DEFAULT_HOST_HEADER = "crm.fgoiriz.com"
```

- The script only makes status URL/host configurable, not snapshot URL:

```python
scripts/sync_contadores_crm_runner_status.py:130
parser.add_argument("--url", default=os.getenv("CONTADORES_RUNNER_STATUS_URL", DEFAULT_STATUS_URL))
```

```python
scripts/sync_contadores_crm_runner_status.py:131
parser.add_argument("--host", default=os.getenv("CONTADORES_RUNNER_STATUS_HOST", DEFAULT_HOST_HEADER))
```

- README and skills repeat the raw IP pattern for runner snapshot access:

```markdown
README.md:733
curl -H "Host: crm.fgoiriz.com" \
```

```markdown
README.md:735
"http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12"
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runner target scan | `rg -n "149\\.50\\.136\\.121|http://149|CONTADORES_RUNNER|followup/snapshot|followup/runner/status|Host: crm\\.fgoiriz\\.com|ALLOW_INSECURE" scripts README.md .env.example .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md` | runner targets are centralized; raw HTTP is removed or explicitly gated |
| Shell syntax | `bash -n scripts/run_contadores_crm_hourly_followup.sh` | exit 0 |
| Python syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile scripts/sync_contadores_crm_runner_status.py scripts/render_contadores_crm_runner_dashboard.py` | exit 0 |

## Scope

**In scope**:
- Add env-configurable snapshot URL and Host header for `run_contadores_crm_hourly_followup.sh`.
- Reuse the same naming convention as `sync_contadores_crm_runner_status.py`.
- Prefer `https://crm.fgoiriz.com` URLs for token-bearing runner traffic.
- Fail closed on non-local `http://` runner URLs unless an explicit emergency env override is set and documented.
- Document all runner target env vars in `.env.example` and README.
- Update follow-up automation skill mirrors so runner endpoint examples match the canonical target variables.

**Out of scope**:
- Changing follow-up runner API diagnostics; plan 074 covers diagnostics.
- Building the canonical server smoke wrapper; plan 028 covers that.
- Changing Traefik/HTTPS routing; plan 044 covers CRM routing.
- Removing the local LaunchAgent.

## Git Workflow

- Branch: `codex/centralize-runner-server-target`
- Commit message: `Centralize follow-up runner server target`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define canonical env names

Use readable names, for example:

```bash
CONTADORES_RUNNER_SNAPSHOT_URL=
CONTADORES_RUNNER_STATUS_URL=
CONTADORES_RUNNER_SERVER_HOST=
CONTADORES_RUNNER_ALLOW_INSECURE_HTTP=
```

Prefer one host env var shared by snapshot fetch and status sync unless there is a real need to split them.

If HTTPS is available, make HTTPS the default. If raw IP plus Host header is still required before plan 044 lands, gate it behind a clearly named override and document it as temporary.

### Step 2: Update the shell runner

In `run_contadores_crm_hourly_followup.sh`:

- read snapshot URL from env with a documented default,
- read host header from env,
- print the target without leaking the internal token,
- fail clearly if required target values are empty.
- reject plain HTTP production targets unless the explicit insecure override is set.

### Step 3: Align status sync

In `sync_contadores_crm_runner_status.py`, align env names with the shell script.

Keep old env names as deprecated aliases only if they are already used on the Mac/server.

### Step 4: Update docs and skills

Update README and both follow-up automation skill mirrors.

Docs should explain whether the default is:

- public HTTPS host,
- raw server IP plus Host header,
- SSH/server-local command.

Do not leave unexplained raw IP examples. Token-bearing HTTP examples must be labeled as temporary/emergency only, not the normal path.

### Step 5: Verify without live calls

Run syntax checks and `rg` scans only. Do not run the hourly runner as part of this plan.

## Test Plan

- Shell and Python syntax checks pass.
- Target scan shows runner target configuration in one place.
- Token-bearing runner traffic defaults to HTTPS when the route is available.
- No secret value is printed by the runner.
- No live production call is made during verification.

## Done Criteria

- [ ] Snapshot fetch and status sync use the same documented target config.
- [ ] Raw IP/Host-header defaults are either removed or explicitly documented.
- [ ] Non-local plain HTTP is rejected or requires an explicit emergency override.
- [ ] README and follow-up automation skill mirrors match the scripts.
- [ ] Verification does not require running the live runner.

## STOP Conditions

- Existing launchd environment already sets the old env names and cannot be migrated safely.
- Production routing requires raw IP plus Host header and no HTTPS/public-host option works.
- Plan 090 changes the canonical server verification target before this plan starts.

## Maintenance Notes

Scheduled local automation should not hide production routing decisions in hardcoded script constants. Keep target config explicit and documented.
