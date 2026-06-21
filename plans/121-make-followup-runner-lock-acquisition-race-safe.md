# Plan 121: Make Follow-Up Runner Lock Acquisition Race Safe

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts/run_contadores_crm_hourly_followup.sh scripts/launchd/com.konecta.contadores.crm-followup.plist README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/074-harden-followup-runner-status-diagnostics.md
- **Category**: ops
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: RUNNER-07

## Why This Matters

The local follow-up runner uses a lock directory, but the race where two runs both pass the stale-lock check and one loses `mkdir` is not handled. Under `set -e`, the losing run can exit before status sync and dashboard reporting are initialized.

Skipped or raced runs should be reported clearly instead of disappearing.

## Current State

- Stale/active lock check runs before lock creation:

```bash
scripts/run_contadores_crm_hourly_followup.sh:47
if [ -d "$LOCK_DIR" ]; then
```

- Lock creation is a bare `mkdir` under `set -e`:

```bash
scripts/run_contadores_crm_hourly_followup.sh:64
mkdir "$LOCK_DIR"
```

- Status sync helpers are defined later:

```bash
scripts/run_contadores_crm_hourly_followup.sh:83
sync_runner_status() {
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runner lock scan | `rg -n "LOCK_DIR|mkdir|flock|sync_runner_status|Another CRM follow-up run" scripts/run_contadores_crm_hourly_followup.sh README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md` | raced/skipped run behavior is explicit |
| Shell syntax | `bash -n scripts/run_contadores_crm_hourly_followup.sh` | exit 0 |
| Launchd plist lint | `plutil -lint scripts/launchd/com.konecta.contadores.crm-followup.plist` | exit 0 |

## Scope

**In scope**:
- Make lock acquisition atomic and race-safe.
- Ensure skipped/raced runs write a concise status or log line.
- Keep stale lock cleanup behavior.
- Update docs if runner status labels change.

**Out of scope**:
- Runner target URL/security; plans 093 and 094 cover target and privilege scope.
- Runner payload redaction/retention; plans 095 and 096 cover those.
- Changing launch interval.

## Git Workflow

- Branch: `codex/runner-lock-race-safe`
- Commit message: `Make follow-up runner lock race safe`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Make acquisition atomic

Use guarded `mkdir "$LOCK_DIR"` or `flock` if the platform supports it reliably. The losing process should exit 0 with a clear skipped reason.

### Step 2: Report skipped runs

Move minimal status/log setup early enough that a skipped run can be observed, or write a small skipped marker before exit.

### Step 3: Preserve stale lock handling

Keep active-pid and stale-age behavior, but avoid deleting a lock that a concurrent run just created.

### Step 4: Verify shell behavior

Run syntax/lint commands and, if safe, manually launch two dry runs to verify one wins and one reports skipped.

## Test Plan

- Shell syntax passes.
- Plist lint passes.
- Manual concurrent invocation shows one active run and one skipped/raced report.

## Done Criteria

- [ ] Concurrent runner starts cannot fail silently at `mkdir`.
- [ ] Skipped/raced runs are visible in logs or runner status.
- [ ] Stale lock cleanup remains safe.
- [ ] No secret values are printed.

## STOP Conditions

- The script runs where the chosen lock primitive is unavailable.
- Status sync cannot run before `.env` loading and would require exposing secrets.
- Existing launchd behavior depends on silent skipped runs.

## Maintenance Notes

Locking code should make the losing path boring and observable. A skipped run is fine; an unexplained missing run is not.
