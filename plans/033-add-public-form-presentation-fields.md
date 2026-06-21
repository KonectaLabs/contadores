# Plan 033: Add Public Form Presentation Fields

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/campaigns.py src/backend/database.py src/backend/tests/test_campaigns.py src/frontend/src/App.tsx src/frontend/src/types.ts`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/012-validate-public-form-fields-client-side.md
- **Category**: product
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Public campaign forms intentionally hide internal campaign names, but their lead-facing copy and styling are currently hardcoded in a backend f-string. Campaign operators need a small safe presentation schema for headline, eyebrow, submit copy, trust cue, and theme without exposing internal names.

## Current State

- Public HTML is rendered in Python:

```python
src/backend/endpoints/campaigns.py:2303
def render_public_form_html(campaign: dict[str, Any]) -> str:
```

- The HTML hardcodes title and eyebrow:

```html
src/backend/endpoints/campaigns.py:2313
<title>Consulta</title>

src/backend/endpoints/campaigns.py:2378
<p class="eyebrow">Consulta</p>
```

- Client-side validation is currently minimal and separate from presentation:

```javascript
src/backend/endpoints/campaigns.py:2504
function validCurrent() {
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add a small `public_presentation` or `presentation` object in campaign info.
- Safely render lead-facing title/eyebrow/submit copy/trust cue/theme.
- Add API/frontend fields only if operators need to edit them in Ads.
- Preserve hidden internal campaign name behavior.

**Out of scope**:
- Full landing page builder.
- Arbitrary CSS injection.
- Exposing internal campaign/client names on public pages.
- Changing backend validation authority.

## Git Workflow

- Branch: `codex/public-form-presentation-fields`
- Commit message: `Add public form presentation fields`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define a tiny schema

Use safe text fields:

- `title`,
- `eyebrow`,
- `subtitle` or `trust_cue`,
- `submit_label`,
- `theme` from a small allowlist.

Normalize length and strip markup. Do not accept raw HTML or CSS.

### Step 2: Store and serve presentation

Store under `campaign_info` or a dedicated column only if a column is already justified.

Expose it in operator campaign payloads and public payloads. Confirm public payload still omits `name`.

### Step 3: Render safely

Use escaped text in `render_public_form_html()`.

Keep defaults equivalent to today:

- title/eyebrow: `Consulta`,
- submit label: `Enviar`.

### Step 4: Add tests

Tests should assert:

- public payload does not include internal `name`,
- custom presentation text appears escaped in HTML,
- raw HTML/script is escaped,
- unknown theme falls back to default.

## Test Plan

- Campaign tests.
- Frontend build if operator UI changes.
- Backend import smoke.

## Done Criteria

- [ ] Operators can configure safe public presentation fields.
- [ ] Internal campaign names remain hidden from public payload and HTML.
- [ ] Presentation values are escaped and length-limited.
- [ ] Campaign tests exit 0.

## STOP Conditions

- Product owner wants a full customizable landing page instead of small safe fields.
- Required presentation data overlaps with funnel-level branding decisions not in this repo yet.

## Maintenance Notes

This plan is about safe lead-facing copy, not a form-builder redesign.
