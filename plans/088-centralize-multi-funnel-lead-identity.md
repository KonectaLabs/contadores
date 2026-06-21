# Plan 088: Centralize Multi-Funnel Lead Identity

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/bot/utils.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 009, 020
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: FUNNEL-05

## Why This Matters

Multi-funnel imports protect normal sheet rows by prefixing non-default external ids at the endpoint. But the database helper itself still looks up only by global `external_lead_id` and can update a row's `funnel_id`. Another caller that passes an unscoped row id can silently move or overwrite a lead across funnels.

Lead identity should be centralized so every caller uses the same funnel-scoped external id rules.

## Current State

- `external_lead_id` is globally unique:

```python
src/backend/database.py:1076
external_lead_id: str = Field(sa_column=Column(String, unique=True, index=True, nullable=False))
```

- Lookup starts with `external_lead_id`:

```python
src/backend/database.py:1370
def get_by_external_lead_id(
```

```python
src/backend/database.py:1381
statement = select(cls).where(cls.external_lead_id == clean_external_lead_id).limit(1)
```

- `upsert()` also finds by `external_lead_id` only, then can update funnel id:

```python
src/backend/database.py:1513
statement = select(cls).where(cls.external_lead_id == external_lead_id).limit(1)
```

```python
src/backend/database.py:1540
item.funnel_id = (funnel_id or "").strip() or item.funnel_id or "contadores"
```

- The import endpoint prefixes non-default sheet row ids:

```python
src/backend/endpoints/contadores.py:4647
external_lead_id = row.id if funnel_id == "contadores" else f"{funnel_id}:{row.id}"
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Lead identity scan | `rg -n "external_lead_id|get_by_external_lead_id|ContadoresLead\\.upsert|build_ctwa_external_lead_id|funnel_id:" src/backend src/bot src/scripts src/backend/tests` | all callers use canonical identity helpers |
| Contadores import tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "import or external_lead_id or funnel" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/database.py src/backend/endpoints/contadores.py src/bot/utils.py` | exit 0 |

## Scope

**In scope**:
- Add a canonical helper for Contadores external lead identity.
- Make imports and direct helper calls use the same scoped id rules.
- Prevent accidental funnel mutation when a raw external id collides.
- Add tests proving the same raw sheet row id can exist in two funnels without mutation, if schema permits after plan 020.

**Out of scope**:
- Manual operator move between funnels; keep `move_to_funnel()` as an explicit action.
- Funnel config source-of-truth cleanup; plan 009 covers that.
- Broad schema migration framework; plan 020 covers migration discipline.

## Git Workflow

- Branch: `codex/centralize-multi-funnel-lead-identity`
- Commit message: `Centralize multi-funnel lead identity`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define canonical identity rules

Create one helper with a clear name, for example:

```python
build_contadores_external_lead_id(funnel_id=funnel_id, source_row_id=row.id)
```

The helper should encode the default funnel and non-default funnels consistently.

### Step 2: Update callers

Replace inline prefixing in import code and any direct callers that construct sheet ids.

Make direct `ContadoresLead.upsert()` calls harder to misuse by normalizing or validating the external id against `funnel_id`.

### Step 3: Prevent accidental funnel mutation

If `upsert()` finds an existing row whose funnel conflicts with the requested funnel, do not silently change `item.funnel_id`.

Either:

- treat it as a separate identity after plan 020 allows it, or
- raise a clear conflict instructing the caller to use the explicit move endpoint/tool.

### Step 4: Add schema support after plan 020

If the desired model is `(funnel_id, external_lead_id)` uniqueness instead of global external id uniqueness, implement it only after migration discipline exists and a production duplicate report is clean.

### Step 5: Add tests

Cover:

- default funnel keeps existing ids,
- non-default funnel ids are scoped consistently,
- same raw source id in two funnels does not mutate the first lead,
- explicit move endpoint still moves a lead intentionally.

## Test Plan

- Focused import/funnel tests pass.
- Existing Codex agent move-to-funnel tests still pass.
- Lead identity scan shows no ad hoc non-default prefixing outside the helper.

## Done Criteria

- [ ] External lead id construction is centralized.
- [ ] `upsert()` cannot silently move a lead across funnels due to raw id collision.
- [ ] Tests cover same raw source id across two funnels.
- [ ] Explicit manual/agent funnel move remains available.

## STOP Conditions

- Product decision is needed between global lead identity and per-funnel lead identity.
- Plan 020 has not landed and the chosen fix requires changing uniqueness constraints.
- Existing production data already contains mixed scoped and unscoped ids for non-default funnels.

## Maintenance Notes

Moving a lead to another funnel is a workflow action. Importing or upserting a row should not move lead ownership implicitly.
