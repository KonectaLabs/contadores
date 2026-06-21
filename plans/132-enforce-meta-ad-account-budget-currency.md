# Plan 132: Enforce Meta Ad Account Budget Currency

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/meta_ads_publish.py src/backend/meta_ads_inventory.py src/backend/tests/test_contadores.py src/backend/agent_cli.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: META-01

## Why This Matters

The publish approval gate labels budget limits as USD, but Meta executes `daily_budget` and `lifetime_budget` in the selected ad account's currency. A non-USD ad account can pass a USD-looking cap while Meta interprets the same minor-unit values in another currency.

Live publish should fail closed unless the staged plan currency and selected ad account currency are explicitly compatible.

## Current State

- Inventory already reads ad account currency:

```python
src/backend/meta_ads_inventory.py:176
accounts_payload = _try_read(
```

```python
src/backend/meta_ads_inventory.py:179
params={"fields": "id,account_id,name,currency,account_status,timezone_name", "limit": clean_limit},
```

- Approval summarizes budgets as USD fields:

```python
src/backend/meta_ads_publish.py:486
def _plan_budget_summary(
```

```python
src/backend/meta_ads_publish.py:495
currency = _clean(plan.get("budget_currency")) or "USD"
```

- The budget gate only checks staged plan currency:

```python
src/backend/meta_ads_publish.py:566
def _budget_blockers(summary: MetaPublishBudgetSummary) -> list[str]:
```

```python
src/backend/meta_ads_publish.py:569
if summary.currency != "USD":
```

- Execution sends Meta budget minor units without an account-currency check:

```python
src/backend/meta_ads_publish.py:772
daily_budget = _money_to_minor_units(ad_set.get("budget_daily_usd"))
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Budget/currency scan | `rg -n "budget_currency|daily_budget|lifetime_budget|currency|selected_ad_account|max_daily_budget_usd" src/backend/meta_ads_publish.py src/backend/meta_ads_inventory.py src/backend/tests/test_contadores.py` | approval checks plan and account currency before live writes |
| Meta publish tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "meta_publish or inventory" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Resolve the selected ad account currency from the latest ready inventory snapshot.
- Fail approval/preflight when plan currency and account currency differ.
- Fail closed when a live publish approval cannot prove account currency.
- Rename or document budget caps so they are clearly USD-only until multi-currency support exists.
- Add tests for USD success, non-USD mismatch, missing currency, and stale/missing inventory behavior.

**Out of scope**:
- Currency conversion.
- Changing campaign graph budget fields across the frontend.
- Meta object creation/resume state; plan 057 owns publish operation persistence.

## Git Workflow

- Branch: `codex/meta-budget-account-currency`
- Commit message: `Enforce Meta budget account currency`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add account-currency extraction

Add a helper that reads the selected ad account currency from the ready inventory snapshot for the plan's `ad_account_id`.

Accept either `selected_ad_account.currency` or a matching entry in `ad_accounts`.

### Step 2: Extend budget blockers

Pass the resolved account currency into the approval/preflight gate.

Block when:

- inventory is required and currency is missing,
- plan currency is missing or not `USD`,
- account currency is not `USD`,
- plan currency and account currency differ.

Return operator-readable blocker strings such as `ad_account.currency=USD`.

### Step 3: Preserve current cap semantics

Keep the existing `max_daily_budget_usd`, `max_lifetime_budget_usd`, and estimated monthly USD cap names unless the whole API is renamed in the same change.

Document clearly that current live publish supports USD ad accounts only.

### Step 4: Add tests

Cover:

- ready USD inventory passes existing approvals,
- ready ARS/EUR inventory blocks,
- selected account missing currency blocks,
- plan currency mismatch blocks,
- missing inventory blocks only when `require_inventory_ready` is true.

## Test Plan

- Targeted Meta publish tests pass.
- Backend import smoke passes.
- Manual scan confirms no live `daily_budget` execution can bypass the account-currency gate.

## Done Criteria

- [ ] Approval/preflight compares staged plan currency with selected ad account currency.
- [ ] Non-USD or unknown account currency blocks live publish.
- [ ] Tests cover success and mismatch cases.
- [ ] Operator-facing response explains the blocker without exposing secrets.

## STOP Conditions

- Production intentionally uses a non-USD ad account and product owner accepts non-USD budget caps.
- Inventory cannot reliably expose selected account currency.
- Existing tests show account currency is unavailable before approval and no safe fail-closed path is acceptable.

## Maintenance Notes

Do not add currency conversion casually. Until multi-currency budgets are a product requirement, fail closed on non-USD live publish.
