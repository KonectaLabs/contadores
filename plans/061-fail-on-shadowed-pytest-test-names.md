# Plan 061: Fail On Shadowed Pytest Test Names

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/tests src/backend/tests pyproject.toml src/bot/pyproject.toml`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: test-safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: TEST-02

## Why This Matters

Python overwrites same-file functions with duplicate names before pytest collection. A duplicated test name can silently remove coverage while the suite still reports green.

## Current State

- `src/bot/tests/test_contadores_flow.py` defines the same test name twice:

```python
src/bot/tests/test_contadores_flow.py:407
def test_dispatch_one_contadores_message_uses_template_body_params() -> None:
```

```python
src/bot/tests/test_contadores_flow.py:492
def test_dispatch_one_contadores_message_uses_template_body_params() -> None:
```

- A read-only duplicate-name scan found only that same-file duplicate.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Duplicate-name scan | `rg -n "^def test_|^async def test_" src/backend/tests src/bot/tests` | no same-file duplicate test names |
| Bot flow tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -q` | exit 0 |
| Guard test | command added by implementation | fails on an intentional same-file duplicate fixture in a temp file |

## Scope

**In scope**:
- Rename the shadowed bot test so both intended tests collect.
- Add a small guard that detects duplicate same-file test function names.
- Wire the guard into local verification or pytest collection without slowing the suite meaningfully.

**Out of scope**:
- Renaming unrelated tests.
- Changing production code.
- Reorganizing the test suite; plan 060 covers that separately.

## Git Workflow

- Branch: `codex/fail-shadowed-pytest-names`
- Commit message: `Fail on duplicate pytest test names`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Rename the duplicate test

Keep the first template test name for the opener/follow-up behavior and rename the campaign-template test to a specific name, for example:

```python
test_dispatch_one_contadores_message_uses_campaign_template_body_params
```

Do not change assertions.

### Step 2: Add a duplicate-name guard

Prefer a simple repository-local check over a complex pytest plugin. Good options:

- a small script under `scripts/` used by the canonical verification command,
- or a pytest collection hook in test support if it can inspect source definitions without importing every test twice.

The guard should fail only when the same file defines the same `test_*` function name more than once.

### Step 3: Add a guard regression test

Add a tiny test for the guard itself using a temporary file with two same-named `test_*` functions.

### Step 4: Update verification docs

If plan 022 has landed, add the guard to the canonical verification command. Otherwise document the command in the new guard test or README section touched by plan 022.

## Test Plan

- Run the duplicate-name guard.
- Run bot flow tests.
- Run backend and bot collection if the guard is part of collection.

## Done Criteria

- [ ] Both bot template tests collect under unique names.
- [ ] Same-file duplicate test names fail verification.
- [ ] The guard ignores same-named tests in different files.
- [ ] No production source files changed.

## STOP Conditions

- The guard needs to import test modules to find duplicates.
- Renaming the test changes behavior or assertions.
- The guard produces false positives for parametrized tests.

## Maintenance Notes

This should be a small tripwire before CI. Keep it source-based and predictable.
