# Plan 130: Stage Confirm Runtime And Funnel Config Writes

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css src/backend/endpoints/contadores.py src/backend/endpoints/funnels.py src/backend/tests/test_funnels.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/009-make-funnel-config-source-of-truth.md, plans/025-audit-and-sync-env-contracts.md
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CONFIG-02

## Why This Matters

Runtime controls and funnel config edits can change automation enablement, sheet config, templates, strategy weights, alert emails, and CRM behavior. Today the frontend saves these persisted configs directly, with no diff/review and no dirty-close protection.

Operators need a review step for high-impact config writes and protection against losing unsaved edits.

## Current State

- Runtime config save writes directly:

```tsx
src/frontend/src/App.tsx:1879
async function saveConfig(nextConfig: Partial<ContadoresConfig>) {
```

- Runtime drawer submit sends the draft:

```tsx
src/frontend/src/App.tsx:8566
async function handleSubmit(event: FormEvent<HTMLFormElement>) {
```

- Funnel save writes directly:

```tsx
src/frontend/src/App.tsx:1895
async function saveFunnel(nextFunnel: FunnelDefinition) {
```

- Backend endpoints persist those changes:

```python
src/backend/endpoints/contadores.py:4605
async def update_contadores_config(
```

```python
src/backend/endpoints/funnels.py:38
async def upsert_funnel(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Config write scan | `rg -n "saveConfig|saveFunnel|RuntimeConfigDrawer|FunnelEditorDrawer|update_contadores_config|upsert_funnel|dirty|ConfirmDialog" src/frontend/src/App.tsx src/backend/endpoints` | config writes have review/dirty guards |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Config/funnel tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_funnels.py src/backend/tests/test_contadores.py -k "config or funnel" -q` | exit 0 |

## Scope

**In scope**:
- Add dirty-state protection to runtime and funnel config drawers.
- Add a review/diff confirmation before persisting high-impact config changes.
- Highlight changes to enablement, sheet URL/GID, templates, alert emails, and strategy weights.
- Preserve current backend save endpoints.

**Out of scope**:
- Moving config source of truth; plan 009 covers that.
- Env contract audit; plan 025 covers env docs.
- Delivery source drawer dirty state; plan 128 covers Delivery source edits.

## Git Workflow

- Branch: `codex/confirm-runtime-funnel-config-writes`
- Commit message: `Confirm runtime and funnel config writes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add dirty comparison helpers

Normalize runtime/funnel drafts and compare them with the loaded config. Avoid false positives from whitespace where the backend normalizes values.

### Step 2: Guard drawer close

If dirty, ask the operator to discard or continue editing.

### Step 3: Add save review

Before saving, show a compact diff summary with old/new values and operational effect. Summarize or redact sensitive values.

### Step 4: Preserve save semantics

After confirmation, call the existing save endpoint and refresh state as today.

### Step 5: Manual verify

Check dirty close, save confirm, cancel confirm, and successful save clearing dirty state.

## Test Plan

- Frontend build passes.
- Backend config/funnel tests still pass.
- Manual browser checks cover dirty-close and save-review flows.

## Done Criteria

- [ ] Runtime config writes require review/confirmation.
- [ ] Funnel config writes require review/confirmation.
- [ ] Dirty edits cannot be lost silently.
- [ ] Sensitive values in diffs are summarized or redacted.

## STOP Conditions

- Operators need one-click emergency enable/disable and confirmation would be unsafe.
- Config values include secrets that should not be shown in frontend diffs.
- Draft comparison requires a broader form-state refactor.

## Maintenance Notes

Config writes are production behavior changes. The UI should make the exact change legible before it persists.
