# Plan 009: Make Funnel Config Source Of Truth

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/funnel_config.py src/backend/tests/test_contadores.py src/backend/tests/test_funnels.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The repo rules say there is no Contadores mode switch: `CONTADORES_SHEET_URL` and `CONTADORES_SHEET_GID` configure the Contadores source, while new funnels carry their own `sheet_url` and `sheet_gid` in `data/funnels.json`. The current effective config builder only copies funnel values into the legacy singleton when singleton fields are blank/default. That can let a non-Contadores funnel inherit Contadores sheet, Calendly, Loom, or timing values and route work to the wrong client/funnel.

## Current State

- Funnel model owns per-funnel sheet and automation fields:

```python
src/backend/funnel_config.py:102
sheet_url: str | None = None
sheet_gid: str | None = None
sheet_poll_seconds: int = Field(default=30, ge=30)
...
loom_url: str = ""
calendly_base_url: str = ""
alert_emails: list[str] = Field(default_factory=list)
initial_reply_quiet_seconds: int = Field(default=30, ge=1)
post_loom_min_seconds: int = Field(default=600, ge=60)
post_loom_quiet_seconds: int = Field(default=30, ge=1)
```

- `apply_funnel_to_config()` only fills blanks/defaults:

```python
src/backend/endpoints/contadores.py:1003
def apply_funnel_to_config(config: ContadoresConfig, funnel, *, override_enabled: bool = True) -> ContadoresConfig:
    config.enabled = funnel.enabled if override_enabled else bool(config.enabled or funnel.enabled)
    if not config.sheet_url:
        config.sheet_url = funnel.sheet_url
    if not config.sheet_gid:
        config.sheet_gid = funnel.sheet_gid
    if config.sheet_poll_seconds == 30:
        config.sheet_poll_seconds = funnel.sheet_poll_seconds
```

- `get_effective_funnel_config()` uses override and seed funnels:

```python
src/backend/endpoints/contadores.py:1034
def get_effective_funnel_config(funnel_id: str | None = None) -> ContadoresConfig:
    config = ContadoresConfig.get()
    clean_funnel_id = (funnel_id or "contadores").strip() or "contadores"
    override_funnel = get_funnel_override(clean_funnel_id)
    if override_funnel is not None:
        return apply_funnel_to_config(config, override_funnel, override_enabled=True)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Contadores tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -q` | exit 0 |
| Funnel tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_funnels.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/contadores.py`
- `src/backend/tests/test_contadores.py`
- `src/backend/tests/test_funnels.py`
- `README.md` only if behavior wording needs a small clarification.

**Out of scope**:
- Reintroducing synthetic leads.
- Adding a runtime mode switch.
- Changing `data/funnels.json` layout.
- Using CleverApply/Alejandro credentials or fallback access.

## Git Workflow

- Branch: `codex/funnel-config-source-of-truth`
- Commit message: `Make funnel config source of truth`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a regression for cross-funnel isolation

In `src/backend/tests/test_contadores.py`, add a test that creates:

- a legacy `ContadoresConfig` with Contadores sheet/Calendly/Loom values,
- a file-backed `abogados` funnel with different `sheet_url`, `sheet_gid`, `calendly_base_url`, timings, and strategy weights.

Assert `get_effective_funnel_config("abogados")` returns Abogados values, not legacy Contadores values.

Also assert `get_effective_funnel_config("contadores")` keeps current backwards-compatible env/default behavior.

**Verify**: targeted test should fail before implementation.

### Step 2: Change explicit funnel overlay semantics

Update `apply_funnel_to_config()` so explicit file-backed funnel fields are copied unconditionally when an explicit funnel is present.

Expected for a file-backed funnel:

- `enabled = funnel.enabled`
- `sheet_url = funnel.sheet_url`
- `sheet_gid = funnel.sheet_gid`
- `sheet_poll_seconds = funnel.sheet_poll_seconds`
- `loom_url = funnel.loom_url`
- `calendly_base_url = funnel.calendly_base_url`
- `alert_emails_json = json.dumps(funnel.alert_emails)`
- timings copied from funnel
- `strategy_weights_json` built from funnel strategies

For the Contadores fallback path where no file-backed value exists, preserve compatibility with the singleton/env config.

Keep the function readable. If needed, split into `apply_funnel_as_source_of_truth()` and a legacy fallback helper.

**Verify**: Contadores and funnel tests exit 0.

### Step 3: Check runtime/readiness contracts

Run the existing runtime tests around sheet readiness. They should still enforce that enabled campaign funnels need both `sheet_url` and `sheet_gid`.

Do not change `/api/runtime` secret-hiding behavior.

**Verify**:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -q
```

Expected: exit 0.

## Test Plan

- New regression test for Abogados/funnel-specific effective config.
- Existing runtime readiness tests.
- Existing funnel endpoint tests.

## Done Criteria

- [ ] Explicit non-Contadores funnels never inherit singleton Contadores sheet/Calendly/Loom/timing fields.
- [ ] Contadores fallback behavior still works for env/singleton config.
- [ ] Runtime readiness still reports missing sheet URL/GID per funnel.
- [ ] Contadores tests exit 0.
- [ ] Funnel tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- Existing production data depends on non-Contadores funnels inheriting Contadores singleton fields.
- The fix requires changing the persisted funnel schema.
- Runtime tests reveal ambiguity between seed funnels and file-backed overrides that cannot be resolved from code.

## Maintenance Notes

This is a data isolation plan. Reviewers should be strict about not adding another mode branch. The right model is one effective funnel config per requested funnel.
