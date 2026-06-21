# Plan 012: Validate Public Form Fields Client-Side

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The public campaign form is a lead-capture surface. Client-side validation currently checks only whether required fields are non-empty. Phone and email validity are deferred to backend submit, so a lead can complete several steps and only then receive a generic failure. Backend validation must remain authoritative, but the form should prevent obvious invalid phone/email/select values before advancing.

## Current State

- Backend validates field types:

```python
src/backend/endpoints/campaigns.py:1458
if field_type == "phone" and clean_value and not normalize_phone(clean_value):
    raise HTTPException(status_code=400, detail=f"{field.get('label') or field.get('id')} is invalid.")
```

- Client form validation only checks required:

```javascript
src/backend/endpoints/campaigns.py:2504
function validCurrent() {
  const field = currentField();
  if (!field || !field.required) return true;
  return Boolean(currentValue());
}
```

- Public form HTML has existing tests for escaping and structure:

```python
src/backend/tests/test_campaigns.py:948
assert "<title>Consulta</title>" in html
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/campaigns.py`
- `src/backend/tests/test_campaigns.py`

**Out of scope**:
- Rewriting public form renderer into frontend build assets.
- Changing backend validation semantics.
- Changing form schema storage.

## Git Workflow

- Branch: `codex/public-form-client-validation`
- Commit message: `Validate public form fields client-side`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add field-aware validation helpers in the embedded script

Inside `render_public_form_html()`, add small JavaScript helpers near `validCurrent()`:

- `validEmail(value)` using a conservative simple check, not a complex RFC regex.
- `validPhone(value)` that strips common separators and requires a minimum digit count.
- select/multi-select checks that require selected values when field is required.

Keep backend validation authoritative. Client validation only improves UX.

**Verify**: backend import smoke prints `backend-import-ok`.

### Step 2: Return specific messages for current field type

Change `validCurrent()` to return an object:

```javascript
{ ok: true, message: "" }
```

or keep the boolean and add `currentValidationMessage()`. Use specific messages like:

- `Completa este dato para seguir.`
- `Revisa el WhatsApp.`
- `Revisa el email.`
- `Elegi una opcion.`

Use the existing `errorEl.textContent` paths in `goNext()` and submit.

**Verify**: campaign tests exit 0 after updating string assertions.

### Step 3: Update renderer tests

In `src/backend/tests/test_campaigns.py`, extend the public HTML test to assert the rendered HTML contains the new helper names or messages, for example:

- `validEmail`
- `validPhone`
- `Revisa el WhatsApp`
- `Revisa el email`

Do not add a browser test in this plan.

**Verify**: campaign tests exit 0.

## Test Plan

- Renderer string regression in `test_campaigns.py`.
- Existing public form submit backend tests remain unchanged.

## Done Criteria

- [ ] Required text, select, yes/no, and multi-select fields cannot advance empty.
- [ ] Obvious invalid phone/email values show field-specific client error before final submit.
- [ ] Backend validation remains unchanged and authoritative.
- [ ] Campaign tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- Field schema can include custom phone/email formats that make simple client checks too restrictive.
- Updating embedded JavaScript becomes too large to review safely in one plan.

## Maintenance Notes

The public form is embedded in Python today. Keep this change small and readable; do not start a renderer migration here.
