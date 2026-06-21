# Plan 138: Delete CRM Lead Media Artifacts On Hard Delete

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py src/bot/providers.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/047-add-data-volume-backup-restore-runbook.md, plans/087-make-contadores-lead-deletion-fk-complete.md
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: RETENTION-01

## Why This Matters

Deleting a CRM lead removes database rows but can leave WhatsApp media files under the shared data volume. That is a privacy leak and makes hard-delete semantics misleading.

Lead hard-delete should account for inbound media, manual outbound media, and any Workstation mirrored copies before the database row disappears.

## Current State

- Inbound WhatsApp media is downloaded under the shared data volume:

```python
src/bot/providers.py:1442
async def _download_inbound_media(self, *, media_type: str, media: Any) -> str | None:
```

- Inbound images can be mirrored into Workstation media:

```python
src/backend/endpoints/contadores.py:2406
def mirror_workstation_inbound_image(
```

- Manual outbound media is persisted under the shared data volume:

```python
src/backend/endpoints/contadores.py:2507
async def save_manual_outbound_media_async(*, lead: ContadoresLead, upload: UploadFile) -> tuple[str, str, str, str | None]:
```

- Lead delete removes messages and the lead, but not filesystem artifacts:

```python
src/backend/endpoints/contadores.py:5109
@contadores_router.delete("/leads/{lead_id}", response_model=DeleteContadoresLeadResponse)
```

```python
src/backend/endpoints/contadores.py:5116
for message in session.exec(select(ContadoresMessage).where(ContadoresMessage.lead_id == lead_id)).all():
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Lead media delete scan | `rg -n "delete_contadores_lead|media_path|outbound_media|inbound_media|mirror_workstation_inbound_image|DATA_DIR" src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py src/bot/providers.py` | delete path collects and removes safe artifacts |
| Contadores delete tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "delete.*lead or media" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Collect media paths tied to a lead's messages before hard-delete.
- Resolve only files under `DATA_DIR`.
- Handle inbound media, outbound manual media, and Workstation mirrored assets tied to the deleted lead.
- Delete files after the database transaction succeeds.
- Add dry-run/block behavior when deletion would affect paid Workstation state that should not be erased.

**Out of scope**:
- Database FK completeness; plan 087 owns DB deletion relationships.
- Runtime media caps; plans 046, 077, and 098 own path and size safety.
- Workstation artifact pruning unrelated to CRM lead deletion; plan 048 owns general Workstation retention.

## Git Workflow

- Branch: `codex/delete-lead-media-artifacts`
- Commit message: `Delete lead media artifacts on hard delete`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a safe artifact collector

Collect candidate file paths from lead messages and linked/mirrored Workstation media.

Resolve paths against `DATA_DIR` and reject anything outside that root.

### Step 2: Decide paid Workstation behavior

If the lead is linked to a paid Workstation client, either block hard-delete with a clear message or require a separate explicit delete of Workstation assets.

Do not silently remove client delivery artifacts.

### Step 3: Delete after DB success

Perform database deletion first. After commit succeeds, delete collected files.

If a file is already missing, record that in the response but do not fail the whole delete.

### Step 4: Add tests

Cover:

- inbound media removed,
- outbound media removed,
- mirrored Workstation asset behavior,
- missing file tolerated,
- unsafe path rejected or skipped,
- DB rollback does not delete files.

## Test Plan

- Contadores delete/media tests pass.
- Backend import smoke passes.
- Manual `rg` confirms all lead hard-delete paths call the artifact collector.

## Done Criteria

- [ ] Lead hard-delete handles associated media artifacts.
- [ ] Unsafe paths outside `DATA_DIR` are never deleted.
- [ ] Paid Workstation-linked artifacts are blocked or explicitly handled.
- [ ] Tests cover success and safety edge cases.

## STOP Conditions

- Existing production relies on hard-delete preserving message files for audit.
- Media paths are not attributable enough to avoid deleting shared files.
- Plan 087 changes lead deletion semantics in a conflicting way.

## Maintenance Notes

Hard-delete should either delete private artifacts or refuse to proceed. Silent orphaned media is not acceptable.
