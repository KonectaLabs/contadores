# Plan 047: Add Data Volume Backup And Restore Runbook

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md docker-compose.yml`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/020-add-migration-discipline-for-production-schema-changes.md
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-03

## Why This Matters

The real server persists critical state in ignored `data/`: SQLite database, WAL/SHM, bot webhook inbox, funnel overrides, media, Codex home, and generated Workstation artifacts. Plan 020 says schema changes need backups, but there is no first-class backup/restore command or runbook for this data volume.

## Current State

- Default database path is under `data/`:

```python
src/backend/database.py:33
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
src/backend/database.py:36
DEFAULT_DATABASE_URL = f"sqlite:///{DATA_DIR / 'database.sqlite'}"
```

- SQLite uses WAL:

```python
src/backend/database.py:59
if _is_sqlite_url(DATABASE_URL):
```

- Backend and bot share the same Docker data volume:

```yaml
docker-compose.yml:44
volumes:
  - ./data:/app/data
```

```yaml
docker-compose.yml:59
volumes:
  - ./data:/app/data
```

- README warns that DB and bot inbox live there:

```text
README.md:1601
local queda en `data/database.sqlite`, montada como volumen persistente
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Shell syntax | `bash -n scripts/backup_contadores_data.sh scripts/restore_contadores_data.sh` | exits 0 |
| Dry-run backup | `scripts/backup_contadores_data.sh --dry-run` | lists files without writing archive |
| Rollout doc check | `rg -n "backup|restore|data volume" README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md` | finds runbook refs |

## Scope

**In scope**:
- Add backup script for the server/local `data/` volume.
- Add restore runbook or script with explicit stop/restore/start steps.
- Include SQLite WAL/SHM awareness.
- Update rollout docs so migrations require a fresh backup.

**Out of scope**:
- Cloud/object storage automation.
- Encrypted backup storage.
- Postgres migration.
- Backing up secrets from `.env` or `auth.toml` in the data archive.

## Git Workflow

- Branch: `codex/data-volume-backup-runbook`
- Commit message: `Add data volume backup and restore runbook`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a backup command

Create a root or `scripts/` command that archives:

- `data/database.sqlite`,
- `data/database.sqlite-wal`,
- `data/database.sqlite-shm`,
- `data/bot-webhook-inbox.sqlite`,
- `data/funnels.json`,
- `data/client-lead-sources.json`,
- `data/contadores/`,
- `data/workstation/`,
- `data/platform/`,
- `data/agent-runs/`,
- `data/agent-memory/`,
- `data/codex-home/` if operator chooses to include it.

Use a timestamped archive under an operator-provided output directory. Do not write backups into the repo by default.

### Step 2: Make SQLite backup safe

Preferred options:

- stop backend and bot before archive for a cold backup,
- or use SQLite `.backup` for the DB and then archive non-DB files.

Document which mode the script uses. Avoid copying only `database.sqlite` while WAL is active.

### Step 3: Add restore guidance

Restore must be explicit:

1. stop backend and bot,
2. move current `data/` aside,
3. restore archive,
4. verify ownership/permissions,
5. start services,
6. run server smoke.

Require operator confirmation before overwriting existing data.

### Step 4: Wire into rollout docs

README and rollout skills should say schema-changing plans and deploys with data migrations require a fresh backup first.

## Test Plan

- Run shell syntax checks.
- Run dry-run backup.
- On a disposable copy, create an archive and restore it into an empty temp directory.
- Verify archive contains DB, WAL/SHM if present, bot inbox, config JSON, and media roots.

## Done Criteria

- [ ] Backup command/runbook exists.
- [ ] Restore command/runbook exists.
- [ ] SQLite WAL/SHM behavior is handled explicitly.
- [ ] Rollout docs require backup before schema/data migrations.
- [ ] Backup output does not include `.env` or `auth.toml` by default.

## STOP Conditions

- Operator requires encrypted/offsite backups before any script lands.
- Current server data layout differs from README/Compose assumptions.
- Backup command would write large archives into the git worktree by default.

## Maintenance Notes

This is operational safety work. Keep the scripts boring, explicit, and easy to run under pressure.
