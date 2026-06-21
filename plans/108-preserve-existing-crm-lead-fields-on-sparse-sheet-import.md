# Plan 108: Preserve Existing CRM Lead Fields On Sparse Sheet Import

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/tests/test_contadores_flow.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: IMPORT-01

## Why This Matters

Legacy Contadores sheet import can receive sparse rows. The bot only requires `id` and `phone_number` before sending rows to the backend, while backend upsert overwrites existing lead name, email, platform, status, and sheet timestamp with blank-derived values. A later sparse poll can erase useful CRM lead data that was already captured from a richer sheet row or another inbound source.

Imports should update fields when new sheet values are present, not destructively clear known lead data because a later row is sparse.

## Current State

- Bot import filtering only requires id and phone:

```python
src/bot/utils.py:487
def keep_sheet_row_for_import(row: dict[str, str]) -> bool:
```

```python
src/bot/utils.py:489
has_id = bool(str(row.get("id") or "").strip())
```

```python
src/bot/utils.py:490
has_phone = bool(str(row.get("phone_number") or "").strip())
```

- Backend imports rows through `ContadoresLead.upsert`:

```python
src/backend/endpoints/contadores.py:4628
async def import_contadores_leads(
```

```python
src/backend/endpoints/contadores.py:4649
lead = ContadoresLead.upsert(
```

- Existing leads are overwritten with blank-derived values:

```python
src/backend/database.py:1542
item.full_name = (full_name or "").strip() or None
```

```python
src/backend/database.py:1543
item.email = (normalize_email(email) or None) if email else None
```

```python
src/backend/database.py:1544
item.platform = (platform or "").strip() or None
```

```python
src/backend/database.py:1545
item.lead_status = (lead_status or "").strip() or None
```

```python
src/backend/database.py:1548
item.sheet_created_time = sheet_created_time
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Sparse import scan | `rg -n "keep_sheet_row_for_import|import_contadores_leads|ContadoresLead\\.upsert|full_name =|lead_status|sheet_created_time" src/backend src/bot src/backend/tests src/bot/tests` | sparse updates preserve existing non-empty fields |
| Backend import tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "import or sheet" -q` | exit 0 |
| Bot flow tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k "import or sheet" -q` | exit 0 |

## Scope

**In scope**:
- Preserve existing non-empty `full_name`, `email`, `platform`, `lead_status`, and `sheet_created_time` when the incoming sheet value is blank or absent.
- Keep phone and normalized phone update behavior intentional and tested.
- Add regression tests for richer row followed by sparse row.
- Keep new lead creation behavior unchanged.

**Out of scope**:
- Multi-funnel external id redesign; plan 088 covers that.
- Funnel config source of truth; plan 009 covers that.
- Sendable phone strictness; plan 111 covers import phone validation.
- Sheet URL allowlisting; plan 002 covers that.

## Git Workflow

- Branch: `codex/preserve-lead-fields-on-sparse-import`
- Commit message: `Preserve lead fields on sparse imports`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a preservation helper

Prefer a small helper in the upsert path that chooses:

- incoming non-empty value when present,
- existing value when incoming is blank,
- explicit clear only if a future command supports it.

Keep the code easy to read.

### Step 2: Apply to sparse-prone fields

Apply the helper to:

- `full_name`,
- `email`,
- `platform`,
- `lead_status`,
- `sheet_created_time`.

Do not merge tags differently unless current tag behavior is directly implicated.

### Step 3: Add regression coverage

Create or extend tests proving:

- first import with rich data creates the lead,
- second import with only id/phone does not clear rich fields,
- genuinely new non-empty sheet values still update the lead.

### Step 4: Verify bot import shape

Confirm bot-side `build_importable_sheet_row` still sends nullable optional fields and does not need to invent values.

## Test Plan

- Backend Contadores import tests.
- Bot import/flow tests.

## Done Criteria

- [ ] Sparse sheet rows no longer clear useful existing lead fields.
- [ ] Non-empty updated sheet values still update existing leads.
- [ ] Tests cover rich-then-sparse import behavior.

## STOP Conditions

- Product owner expects blank sheet cells to intentionally clear CRM fields.
- Current sheet workflow uses blanks as explicit deletes and needs a separate delete marker.
- Preserving fields conflicts with a newer backend partial-update design.

## Maintenance Notes

Treat sheet import as additive unless a value is explicitly present. Silent data erasure is harder to recover than stale optional metadata.
