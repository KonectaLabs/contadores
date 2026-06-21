# Plan 148: Preserve Live Follow-up Runner Locks

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts/run_contadores_crm_hourly_followup.sh scripts/launchd/com.konecta.contadores.crm-followup.plist scripts/sync_contadores_crm_runner_status.py README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/074-harden-followup-runner-status-diagnostics.md
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: RUNNER-08

## Why This Matters

The hourly CRM follow-up runner uses a lock directory to avoid overlapping Codex runs. Today an old lock is deleted after six hours even if the recorded PID is still alive. That can start a second runner while the first process is still executing.

Any live PID should be treated as active. Old-but-live locks should surface as stuck/overdue status, then a watchdog can terminate the process group in a bounded way.

## Current State

- The lock check only respects a live PID while the lock is younger than six hours:

```bash
scripts/run_contadores_crm_hourly_followup.sh:47
if [ -d "$LOCK_DIR" ]; then
  lock_age_seconds=$(( "$(date +%s)" - "$(stat -f %m "$LOCK_DIR" 2>/dev/null || echo 0)" ))
  lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
  if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null && [ "$lock_age_seconds" -lt 21600 ]; then
    echo "Another CRM follow-up run is still active under pid $lock_pid."
    exit 0
  fi
  rm -rf "$LOCK_DIR"
fi
```

- Launchd starts the job hourly:

```xml
scripts/launchd/com.konecta.contadores.crm-followup.plist:16
<key>StartInterval</key>
```

- The watchdog sends only `TERM` to the Codex process:

```bash
scripts/run_contadores_crm_hourly_followup.sh:215
kill "$codex_pid" 2>/dev/null || true
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runner lock scan | `rg -n "LOCK_DIR|lock_age|kill -0|watchdog|codex_pid|process group|StartInterval|stuck|overdue" scripts README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md` | live-lock and overdue behavior are explicit |
| Shell syntax | `bash -n scripts/run_contadores_crm_hourly_followup.sh` | exit 0 |
| Plist lint | `plutil -lint scripts/launchd/com.konecta.contadores.crm-followup.plist` | exit 0 |

## Scope

**In scope**:
- Treat any live lock PID as active regardless of age.
- Report old-but-live locks as stuck or overdue.
- Clear stale locks only when the recorded PID is absent or dead.
- Make watchdog shutdown bounded: TERM first, then KILL after a grace period if the process remains alive.
- Prefer terminating the process group if the script starts child processes that can outlive the main PID.
- Update docs and status wording.

**Out of scope**:
- Lock acquisition race safety; plan 121 owns the `mkdir` race, though both plans should be coordinated if implemented together.
- Payload redaction and report retention; plans 095 and 096 own those.
- Changing the hourly launch interval.
- Running the live hourly runner as verification.

## Git Workflow

- Branch: `codex/preserve-live-followup-runner-locks`
- Commit message: `Preserve live follow-up runner locks`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Fix stale-lock classification

Rewrite the lock check so:

- live PID means active, no matter the lock age,
- live and old PID exits 0 with an overdue/stuck message and status marker,
- dead or missing PID can be treated as stale and cleaned.

Avoid `rm -rf "$LOCK_DIR"` when `kill -0 "$lock_pid"` succeeds.

### Step 2: Add stuck status

Make skipped old-live runs visible in the local log/status flow. Keep the message short and redacted.

### Step 3: Harden watchdog shutdown

When the Codex run exceeds its wall-clock limit:

- send TERM,
- wait a small grace period,
- if still alive, send KILL,
- handle child process groups if the process model supports it safely.

Document the behavior in README and the follow-up automation skill mirrors.

### Step 4: Coordinate with plan 121

If plan 121 has not landed, keep this patch compatible with a future atomic `mkdir` fix. If plan 121 has landed, preserve its skipped/raced status behavior.

## Test Plan

- Shell syntax passes.
- Plist lint passes.
- Manual dry-run simulation with fake lock directories covers:
  - live young PID,
  - live old PID,
  - dead old PID,
  - missing PID.
- Do not invoke the live Codex runner against production data.

## Done Criteria

- [ ] Old-but-live runner locks no longer get deleted.
- [ ] Stuck live runs are visible in runner status/logs.
- [ ] Dead stale locks still clear safely.
- [ ] Watchdog termination is bounded.

## STOP Conditions

- macOS process group behavior makes safe child termination unclear.
- Existing operational runbooks intentionally delete old live locks manually and need review.
- Status sync cannot report skipped/stuck runs without exposing secrets.

## Maintenance Notes

Overlapping automation is worse than a skipped run. Prefer visible stuck status over deleting a live lock.
