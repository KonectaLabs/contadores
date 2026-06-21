# Plan 020: Add Migration Discipline For Production Schema Changes

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py src/backend/database.py README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: none
- **Category**: architecture
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The real server uses SQLite in a persistent `data/` volume. Startup currently creates tables and runs many ad hoc schema changes on every boot. That is convenient for early development, but risky for production because destructive or long-running changes execute as part of app startup rather than a visible rollout step.

## Current State

- FastAPI startup runs `init_db()`:

```python
src/backend/main.py:170
init_db()
```

- `init_db()` calls `create_all()` and many schema mutation helpers:

```python
src/backend/database.py:7857
def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)
    ensure_client_lead_source_prefilled_reply_text_column()
    drop_legacy_contadores_events_table()
    ...
```

- One startup helper is destructive:

```python
src/backend/database.py:7894
def drop_legacy_contadores_events_table() -> None:
    ...
    connection.exec_driver_sql("DROP TABLE contadores_events")
```

- No `migrations/`, `alembic/`, or `alembic.ini` path was found with:

```bash
rg --files | rg '(^|/)(migrations|alembic|alembic\.ini)(/|$)'
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |
| Local startup smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run uvicorn backend.main:app --host 127.0.0.1 --port 8011` | starts cleanly, stop manually |

## Scope

**In scope**:
- Introduce a small migration ledger or Alembic-style path.
- Move destructive schema changes behind explicit migrations.
- Keep first implementation compatible with SQLite.
- Document rollout behavior.

**Out of scope**:
- Migrating to Postgres.
- Rewriting all existing `ensure_*` helpers in one PR.
- Changing product tables without a separate feature plan.

## Git Workflow

- Branch: `codex/schema-migration-discipline`
- Commit message: `Add migration discipline for schema changes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose the migration style

Pick one:

- Lightweight ledger: a `schema_migrations` table plus Python migration functions.
- Alembic: standard migration files and env setup.

For this repo, the lightweight ledger may be the safer first step because SQLModel and SQLite are already in use and the immediate goal is to make startup behavior explicit.

Document the choice in `README.md`.

### Step 2: Add a migration ledger

If using the lightweight approach, add a `schema_migrations` table with:

- `id`,
- `name`,
- `applied_at`,
- optional `details_json`.

Add helper functions:

- list applied migrations,
- run one migration once,
- record success after commit.

Keep this code near `init_db()` or in a small `backend/migrations.py` module.

### Step 3: Move destructive work out of normal startup

Move `drop_legacy_contadores_events_table()` behind a named one-time migration.

Startup may still call the migration runner, but it should be clear from logs which migration ran and it must not rerun after recording success.

### Step 4: Add schema verification mode

Add an env-controlled or CLI-callable path that verifies expected tables/indexes without mutating broadly.

Recommended shape:

```bash
PYTHONPATH=src uv run python -m backend.database verify-schema
```

If a full CLI is too broad, add a documented helper function and a smoke test.

### Step 5: Add tests

Add focused tests for:

- migration runs once,
- migration records success,
- destructive migration is not called again on second startup,
- startup still initializes a clean temporary DB.

## Test Plan

- New migration ledger tests.
- Full backend test suite.
- Backend import smoke.
- Manual startup smoke against a temporary DB.

## Done Criteria

- [ ] Destructive schema changes are one-time named migrations.
- [ ] Startup logs applied migrations clearly.
- [ ] Running startup twice does not rerun completed migrations.
- [ ] Existing clean DB startup still works.
- [ ] README documents the migration rule.
- [ ] Backend tests exit 0.

## STOP Conditions

- Production DB needs a manual backup or inspection before the first migration runner deploy.
- Existing startup helpers rely on ordering that cannot be preserved safely.
- Alembic or ledger setup introduces more complexity than the current repo can maintain.

## Maintenance Notes

Do this in stages. The first PR should create the migration discipline and move only the riskiest destructive helper. Later PRs can move other `ensure_*` helpers.
