# Plan 060: Split Contadores Backend Test Suite By Domain

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/tests/test_contadores.py src/backend/tests/conftest.py pyproject.toml`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/024-wire-ci-and-test-dependencies.md, plans/062-extract-backend-test-support-fixtures.md
- **Category**: test-maintenance
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: TEST-01

## Why This Matters

`src/backend/tests/test_contadores.py` has become the catch-all regression file for Contadores, platform, Meta, Workstation, media, and Codex-agent behavior. It is now large enough that a narrow executor has to load unrelated domains before editing or debugging one feature. Splitting it by behavior domain will make future correctness plans safer because each executor can run and inspect the relevant slice without hiding unrelated test setup.

## Current State

- The file imports modules from several product domains in one place:

```python
src/backend/tests/test_contadores.py:18
import backend.ai.contadores_conversation_bot as contadores_conversation_bot_module
...
src/backend/tests/test_contadores.py:23
import backend.meta_ads_publish as meta_ads_publish_module
...
src/backend/tests/test_contadores.py:66
from backend.ai.codex_agent_tools import call_tool
```

- Shared database setup and fake profile helpers live inside the catch-all file:

```python
src/backend/tests/test_contadores.py:75
def configure_contadores_db(monkeypatch, tmp_path) -> None:
    """Point database and Contadores router state at a temporary SQLite file."""
```

- The same file contains unrelated regions:

```text
src/backend/tests/test_contadores.py:171   codex agent tool tests begin
src/backend/tests/test_contadores.py:450   Meta publish tests begin
src/backend/tests/test_contadores.py:1557  platform meeting and lifecycle tests begin
src/backend/tests/test_contadores.py:2592  Contadores runtime and delivery tests begin
src/backend/tests/test_contadores.py:4902  automation/conversation tests begin
src/backend/tests/test_contadores.py:5874  inbound/media tests begin
src/backend/tests/test_contadores.py:7395  Workstation tests begin
```

- Backend pytest currently has only minimal global setup in `conftest.py`:

```python
src/backend/tests/conftest.py:21
@pytest.fixture(autouse=True)
def reset_auth_manager_state() -> None:
    """Keep auth state aligned with env changes between tests."""
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Baseline collection | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py --collect-only -q` | records current collected test ids |
| Refactored collection | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests --collect-only -q` | all moved test ids still collect |
| Targeted Contadores tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores_*.py -q` | exit 0 |
| Workstation slice | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_workstation*.py -q` | exit 0 |
| Backend smoke | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -q` | exit 0 |

## Scope

**In scope**:
- Move shared Contadores test helpers into a small fixture/helper module under `src/backend/tests/`.
- Split `test_contadores.py` into domain files while preserving test bodies and assertions.
- Keep imports direct and readable.
- Preserve all current test ids where practical, or record the old-to-new mapping in the PR description.

**Out of scope**:
- Changing production code.
- Changing test assertions or broadening behavior coverage.
- Introducing markers, test-order dependencies, or hidden runtime services.
- Rewriting tests into a new style.

## Git Workflow

- Branch: `codex/split-contadores-backend-tests`
- Commit message: `Split Contadores backend tests by domain`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Capture the baseline

Run the baseline collection command and save the count in the PR notes. Do not commit generated collection output.

Also run:

```bash
wc -l src/backend/tests/test_contadores.py
```

Use the number only as a before/after sanity check.

### Step 2: Extract shared helpers

Move shared setup helpers into a readable module, for example:

```text
src/backend/tests/contadores_test_helpers.py
```

Start with:

- `now_utc`,
- `configure_contadores_db`,
- `fake_profile_extraction`,
- tiny repeated fake classes or response builders that are used by multiple new files.

Keep domain-specific helper functions near the tests that use them.

### Step 3: Split by domain

Create small domain files in this shape:

```text
src/backend/tests/test_contadores_agent_tools.py
src/backend/tests/test_contadores_meta_publish.py
src/backend/tests/test_contadores_platform_lifecycle.py
src/backend/tests/test_contadores_runtime.py
src/backend/tests/test_contadores_conversation_flow.py
src/backend/tests/test_contadores_inbound_media.py
src/backend/tests/test_workstation_contadores_flow.py
```

Use the existing test order as the starting map:

- lines 171-417: agent tools,
- lines 450-1101: Meta publish, inventory, lead forms,
- lines 1557-2538: platform lifecycle and Codex runtime harness,
- lines 2592-4880: Contadores runtime, delivery, strategy, manual actions,
- lines 4902-5792: automation tick and conversation bot behavior,
- lines 5874-7372: inbound routing, media, Calendly, tags, lead filters,
- lines 7395-9692: Workstation conversion, public pages, Codex work, photo jobs.

Keep `test_drop_legacy_contadores_events_table` with runtime/database tests.

### Step 4: Remove the catch-all file

After every test has moved and collection matches the baseline, delete or reduce `test_contadores.py` to nothing. Do not leave a compatibility wrapper that imports tests from the new files.

### Step 5: Verify selection commands

Run the refactored collection command and compare the collected count to the baseline.

Then run the targeted commands. If one domain slice is too slow, report the slow slice and exact test name before broadening the scope.

### Step 6: Update plan references if needed

Several existing plans use `src/backend/tests/test_contadores.py -k ...` commands. If this split lands before those plans execute, update affected plan commands to target the new files.

Do not rewrite every old plan opportunistically unless the target file path is now wrong.

## Test Plan

- Baseline collection before moving tests.
- Refactored collection after moving tests.
- Domain test files pass individually.
- Full backend tests pass once after the split.

## Done Criteria

- [ ] No production source files changed.
- [ ] `test_contadores.py` is no longer a catch-all test file.
- [ ] Shared setup is in one obvious helper/fixture module.
- [ ] The collected backend test count matches the baseline.
- [ ] Existing targeted test commands are updated only where the old file path would break.

## STOP Conditions

- Baseline collection fails before any edits.
- Moving helpers requires production code changes.
- Test collection count changes and the missing/added tests cannot be explained.
- A moved test starts depending on execution order.

## Maintenance Notes

This is a safety refactor for future work. Keep it mechanical, reviewable, and boring.
