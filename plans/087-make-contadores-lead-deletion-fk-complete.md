# Plan 087: Make Contadores Lead Deletion FK Complete

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-08

## Why This Matters

The CRM has a hard-delete endpoint for Contadores leads. SQLite foreign keys are enabled, and several tables reference `contadores_leads`, but the endpoint deletes only messages before deleting the lead. A lead with strategy assignments, runtime alerts, or Workstation state can fail deletion with FK errors or leave inconsistent state if a tool runs without FK enforcement.

## Current State

- Foreign keys are enabled:

```python
src/backend/database.py:61
cursor.execute("PRAGMA foreign_keys=ON")
```

- Lead children include strategy assignments, messages, runtime alerts, and Workstation clients:

```python
src/backend/database.py:1858
lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
```

```python
src/backend/database.py:1913
lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
```

```python
src/backend/database.py:5385
lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
```

```python
src/backend/database.py:5647
lead_id: str = Field(foreign_key="contadores_leads.id", index=True)
```

- The delete endpoint deletes only messages first:

```python
src/backend/endpoints/contadores.py:5109
@contadores_router.delete("/leads/{lead_id}", response_model=DeleteContadoresLeadResponse)
```

```python
src/backend/endpoints/contadores.py:5116
for message in session.exec(select(ContadoresMessage).where(ContadoresMessage.lead_id == lead_id)).all():
```

```python
src/backend/endpoints/contadores.py:5118
session.delete(lead)
```

- Existing test covers only lead plus messages:

```python
src/backend/tests/test_contadores.py:7372
def test_contadores_delete_lead_removes_messages(monkeypatch, tmp_path) -> None:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| FK scan | `rg -n "foreign_key=\"contadores_leads.id\"|delete_contadores_lead|DeleteContadoresLead" src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py` | all child tables are accounted for |
| Delete tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "delete_lead or workstation or runtime_alert or strategy_assignment" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/database.py src/backend/endpoints/contadores.py` | exit 0 |

## Scope

**In scope**:
- Decide whether the endpoint should hard-delete or soft-delete leads with dependent state.
- If hard-delete remains, delete all FK children in a safe dependency order.
- Add tests for messages, strategy assignments, runtime alerts, and Workstation clients.
- Return a clear conflict if a lead should not be hard-deleted because it has paid/client work attached.

**Out of scope**:
- Frontend confirmation UX; plan 070 covers destructive action confirmation.
- Data backup/runbook; plan 047 covers backup and restore.
- General cascade-delete migration design.

## Git Workflow

- Branch: `codex/fk-complete-contadores-lead-delete`
- Commit message: `Complete Contadores lead deletion cleanup`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose hard delete versus soft delete

For ordinary CRM leads, hard delete may be acceptable. For paid Workstation clients, a conflict or soft-delete is likely safer.

Make the behavior explicit before changing code.

### Step 2: Inventory all FK children

Search for every `foreign_key="contadores_leads.id"` and decide for each table:

- delete with lead,
- block deletion,
- detach or archive.

### Step 3: Implement one transaction

Keep deletion in one database session and one transaction.

Delete dependent rows in dependency order or return a conflict before mutating.

### Step 4: Add tests

Cover:

- lead with messages deletes cleanly,
- lead with strategy assignments deletes or blocks as designed,
- lead with runtime alerts deletes or blocks as designed,
- lead with Workstation client blocks or handles dependent state as designed,
- not-found still returns 404.

## Test Plan

- Focused delete tests pass.
- FK enforcement remains enabled in tests.
- No broad cascade behavior deletes paid client data accidentally.

## Done Criteria

- [ ] Delete behavior is explicit for every current lead child table.
- [ ] Endpoint no longer fails with unhandled FK errors for known child types.
- [ ] Tests cover FK-complete behavior.
- [ ] Operator-facing response is clear when deletion is blocked.

## STOP Conditions

- Product owner needs to decide whether paid Workstation clients can ever be hard-deleted.
- Additional child tables are discovered and ownership is unclear.
- Backup/runbook work is required before destructive cleanup is safe.

## Maintenance Notes

Prefer explicit delete/block logic over relying on implicit cascades. Destructive CRM behavior should be visible in code and tests.
