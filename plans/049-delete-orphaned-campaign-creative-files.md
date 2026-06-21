# Plan 049: Delete Orphaned Campaign Creative Files

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/platform.py src/backend/database.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/047-add-data-volume-backup-restore-runbook.md
- **Category**: reliability
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-05

## Why This Matters

Uploaded campaign creative files live in ignored persistent storage. Campaign hard-delete removes `PlatformCreativeAsset` rows but does not unlink the files, creating privacy residue and backup bloat.

## Current State

- Upload writes a file under `data/platform/creative-assets`:

```python
src/backend/endpoints/platform.py:1285
target_path = creative_asset_root() / stored_filename
src/backend/endpoints/platform.py:1286
target_path.write_bytes(contents)
```

- The DB row stores only the file path reference:

```python
src/backend/endpoints/platform.py:1288
row = PlatformCreativeAsset.add(
```

- Campaign delete removes creative asset rows:

```python
src/backend/database.py:3461
counts["platform_creative_assets"] = delete_count(
    session, delete(PlatformCreativeAsset).where(PlatformCreativeAsset.campaign_id.in_(campaign_refs))
)
```

- The campaign delete commits without unlinking files:

```python
src/backend/database.py:3491
session.delete(row)
src/backend/database.py:3493
session.commit()
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Platform/campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "creative_asset or campaign" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Track creative file paths before deleting DB rows.
- Unlink files that are safely under `DATA_DIR`.
- Add a dry-run orphan scanner for old files if simple.
- Add tests for campaign delete cleanup.

**Out of scope**:
- Deleting files outside `DATA_DIR`.
- Deleting files shared by another live asset.
- Automatically scanning the full data volume on every request.
- Changing upload semantics.

## Git Workflow

- Branch: `codex/delete-orphaned-campaign-creative-files`
- Commit message: `Delete orphaned campaign creative files`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Resolve file paths safely

Add a helper that converts `PlatformCreativeAsset.file_path` to a resolved path under `DATA_DIR`.

Reject or skip:

- empty paths,
- absolute paths outside `DATA_DIR`,
- traversal paths,
- files still referenced by other asset rows.

### Step 2: Capture file paths before DB delete

Before deleting `PlatformCreativeAsset` rows, collect their file paths and check whether any are shared.

Do not unlink until after DB transaction succeeds, or design a clear rollback-safe ordering with tests.

### Step 3: Unlink safely

After successful delete, unlink files that are:

- under `DATA_DIR`,
- not referenced by remaining DB rows,
- regular files.

Log skipped paths without printing sensitive full paths.

### Step 4: Add tests

Cover:

- campaign delete removes DB row and file,
- shared file path is not deleted while another row references it,
- unsafe path is skipped,
- missing file does not fail campaign delete.

## Test Plan

- Run targeted platform/campaign tests.
- Run backend import smoke.
- If adding a scanner, run it in dry-run mode against local data.

## Done Criteria

- [ ] Campaign delete unlinks safe orphaned creative files.
- [ ] Shared or unsafe files are not deleted.
- [ ] Tests cover delete, shared path, unsafe path, and missing file.
- [ ] README documents cleanup behavior if user-facing.

## STOP Conditions

- Asset files are intentionally retained after campaign delete for audit/legal reasons.
- Existing rows have ambiguous shared paths that need manual review.
- Backup plan 047 has not landed and destructive cleanup is being implemented.

## Maintenance Notes

Database delete and file delete are different failure domains. Keep the code explicit and conservative.
