# Plan 096: Prune Follow-up Runner Report Artifacts

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts/run_contadores_crm_hourly_followup.sh scripts/sync_contadores_crm_runner_status.py scripts/render_contadores_crm_runner_dashboard.py src/backend/endpoints/contadores.py README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 047
- **Category**: data
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-04

## Why This Matters

The hourly CRM follow-up runner writes timestamped logs, snapshots, deltas, history, dashboard HTML, launchd stdout/stderr, and remote sync artifacts under `data/reports`. The snapshot endpoint can include up to 20,000 leads with 12 messages per lead. There is no retention policy, pruning command, or history cap, so sensitive local reports can grow without bound.

This is distinct from plan 048, which covers Workstation media artifacts. This plan is only for follow-up runner report artifacts.

## Current State

- The runner writes many timestamped and latest report files:

```bash
scripts/run_contadores_crm_hourly_followup.sh:19
REPORT_DIR="$ROOT_DIR/data/reports"
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:26
RUN_RECORD_DIR="$REPORT_DIR/contadores-crm-followup-runs"
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:29
SNAPSHOT_BEFORE_FILE="$RUN_RECORD_DIR/$RUN_ID-before.json"
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:35
DELTA_RUN_FILE="$RUN_RECORD_DIR/$RUN_ID-delta.json"
```

- The snapshot fetch can pull a very large payload:

```bash
scripts/run_contadores_crm_hourly_followup.sh:42
SNAPSHOT_URL="http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12"
```

- History is append-only:

```bash
scripts/run_contadores_crm_hourly_followup.sh:100
append_runner_history() {
```

```bash
scripts/run_contadores_crm_hourly_followup.sh:121
} >> "$HISTORY_FILE"
```

- Remote status sync also writes timestamped files on the server:

```python
src/backend/endpoints/contadores.py:2236
(reports_dir / f"contadores-crm-followup-delta-remote-{timestamp}.json").write_text(
```

```python
src/backend/endpoints/contadores.py:2247
(reports_dir / f"contadores-crm-followup-remote-{timestamp}.log").write_text(log_text, encoding="utf-8")
```

- The dashboard lists only recent logs, but it does not prune old files:

```python
scripts/render_contadores_crm_runner_dashboard.py:87
def latest_logs(reports_dir: Path, limit: int) -> list[Path]:
```

```python
scripts/render_contadores_crm_runner_dashboard.py:92
reports_dir.glob("contadores-crm-followup-*.log"),
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Runner artifact scan | `rg -n "data/reports|contadores-crm-followup|snapshot|delta|remote-|history|glob\\(|write_text|>>|data/tmp|mktemp|prune|retention" scripts src/backend/endpoints/contadores.py README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md` | retention policy and prune paths are visible |
| Shell syntax | `bash -n scripts/run_contadores_crm_hourly_followup.sh` | exit 0 |
| Python syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile scripts/sync_contadores_crm_runner_status.py scripts/render_contadores_crm_runner_dashboard.py src/backend/endpoints/contadores.py` | exit 0 |

## Scope

**In scope**:
- Define retention policy for local runner reports under `data/reports`.
- Define retention policy for server-side remote status artifacts.
- Preserve `latest`, `previous`, active-lock, and newest N run artifacts.
- Cap or rotate `contadores-crm-followup-history.md`.
- Clean stale `data/tmp/contadores-crm-runner.*.sh` copies left by killed runs.
- Add a dry-run prune command or script mode before deletion.
- Update README and follow-up automation skill mirrors.

**Out of scope**:
- Workstation media pruning; plan 048 covers it.
- Backup/restore design for all data; plan 047 covers it and should land first.
- Redacting runner payloads; plan 095 covers redaction and size bounds.
- Running the live hourly follow-up runner.

## Git Workflow

- Branch: `codex/prune-followup-runner-artifacts`
- Commit message: `Add follow-up runner artifact retention`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose retention limits

Pick readable defaults, for example:

- keep the newest 14 to 30 days of timestamped runner files,
- keep at least the newest 24 successful hourly runs,
- keep latest/previous snapshot files unconditionally,
- keep active run files while the lock is live.

Use env-configurable values only if operators actually need them.

### Step 2: Implement dry-run pruning

Add a small, readable pruning function or script that:

- lists candidates,
- separates local reports from server remote-sync artifacts,
- never deletes active/latest/previous files,
- defaults to dry-run unless called by the runner with an explicit safe mode.

### Step 3: Wire pruning into safe points

Run pruning at the start or end of the hourly wrapper after lock acquisition. Avoid pruning during active report writes.

For backend remote-sync artifacts, prune after writing the newest status files.

### Step 4: Cap history

Keep history useful but bounded. Prefer retaining recent entries and a short summary rather than unlimited Markdown.

### Step 5: Update docs

README and follow-up automation skill mirrors should describe:

- where runner artifacts live,
- how long they are retained,
- how to dry-run the prune,
- which files are preserved.

## Test Plan

- Unit-test the prune selector on a temporary report tree if a suitable test harness exists.
- Syntax checks pass.
- Artifact scan shows retention/prune code and docs.
- No live production runner cycle is started.

## Done Criteria

- [ ] Runner report artifacts have a documented retention policy.
- [ ] Pruning is dry-run visible before deletion.
- [ ] Latest/previous/active artifacts are preserved.
- [ ] Server remote-sync artifacts cannot grow unbounded.

## STOP Conditions

- Plan 047 has not landed and production backup/restore expectations are unclear.
- Operators need a longer legal/business retention policy than the proposed default.
- Existing artifacts have unknown value and no owner can approve pruning.

## Maintenance Notes

Ignored `data/` files are still operational data. Treat runner reports as sensitive CRM artifacts even though they are not committed.
