# Plan 062: Extract Backend Test Support Fixtures

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/tests/test_contadores.py src/backend/tests/test_campaigns.py src/backend/tests/test_agent_api.py src/backend/tests/test_client_lead_delivery.py src/backend/tests/conftest.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: test-maintenance
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: TEST-03

## Why This Matters

Several backend test modules import infrastructure from `test_contadores.py`. That makes a large behavior test file part of the setup contract for unrelated suites and makes future test-suite splitting riskier.

## Current State

- Shared DB setup lives in the catch-all test file:

```python
src/backend/tests/test_contadores.py:75
def configure_contadores_db(monkeypatch, tmp_path) -> None:
```

- Other suites import that test module for setup:

```python
src/backend/tests/test_campaigns.py:24
from backend.tests.test_contadores import configure_contadores_db
```

```python
src/backend/tests/test_agent_api.py:20
from backend.tests.test_contadores import add_recent_inbound, configure_contadores_db
```

- Delivery tests have a similar helper with separate implementation:

```python
src/backend/tests/test_client_lead_delivery.py:18
def configure_delivery_db(monkeypatch, tmp_path) -> None:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Import dependency scan | `rg -n "from backend\\.tests\\.test_contadores import|import backend\\.tests\\.test_contadores" src/backend/tests` | no results |
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Agent API tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_api.py -q` | exit 0 |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Contadores collection | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py --collect-only -q` | exit 0 |

## Scope

**In scope**:
- Move shared backend test helpers into a small support module, for example `src/backend/tests/support.py`.
- Update imports in backend tests to use that support module.
- Consolidate duplicated temporary SQLite setup where the behavior is equivalent.

**Out of scope**:
- Splitting `test_contadores.py` into domain files; plan 060 covers that.
- Adding new behavior coverage.
- Moving production code.

## Git Workflow

- Branch: `codex/extract-backend-test-support`
- Commit message: `Extract backend test support helpers`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Create the support module

Move `configure_contadores_db`, `now_utc`, and any helpers imported by other files into one obvious module.

Keep imports explicit. Do not make a wildcard fixture namespace.

### Step 2: Replace test-module imports

Update `test_campaigns.py` and `test_agent_api.py` so they no longer import `backend.tests.test_contadores`.

### Step 3: Consolidate DB helper shape

Compare `configure_delivery_db` with the shared DB setup. If a single helper can cover both without hiding endpoint-specific monkeypatching, consolidate it. If not, leave Delivery setup local and document why in a short comment.

### Step 4: Verify collection stability

Run the import dependency scan and targeted tests.

## Test Plan

- No imports from `test_contadores.py` remain.
- Campaign, Agent API, Delivery, and Contadores collection all pass.

## Done Criteria

- [ ] Behavior test files are not imported as setup infrastructure.
- [ ] Shared setup has one clear home.
- [ ] Targeted tests pass.
- [ ] No production source files changed.

## STOP Conditions

- Extracting helpers forces broad test rewrites.
- Shared helpers need to import app modules in a way that changes collection order.
- Consolidating Delivery setup changes test database behavior.

## Maintenance Notes

This should land before plan 060 so the domain split is mostly file movement.
