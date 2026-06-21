# Plan 145: Minimize Meta Lead Sheet Append Fields

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py README.md .codex/skills/contadores-spreadsheet/SKILL.md wiki/skills/contadores-spreadsheet/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/014-cover-duplicate-meta-backfill.md
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: META-SHEET-01

## Why This Matters

Meta Lead Ads imports can append rows to a connected Google Sheet. The current append helper derives headers from every key in the imported Meta row, including provider ids and every `field_data` name. That makes the Sheet schema expand based on provider payloads and can leak internal routing fields or unexpected lead-form fields into operator-facing spreadsheets.

The append contract should be explicit: default to a small allowlist of business fields, store provider ids in the application database, and only append extra fields when configuration deliberately opts into them.

## Current State

- Meta import rows include provider and campaign fields:

```python
src/backend/endpoints/client_leads.py:677
for key in [
    "created_time",
    "form_id",
    "ad_id",
    "ad_name",
    "adset_id",
    "adset_name",
    "campaign_id",
    "campaign_name",
    "platform",
]:
```

- Every Meta `field_data` name can become a row key:

```python
src/backend/endpoints/client_leads.py:691
for item in command.field_data:
```

```python
src/backend/endpoints/client_leads.py:701
row[name] = value
```

- Sheet headers are derived from all row keys:

```python
src/backend/endpoints/client_leads.py:1061
def meta_sheet_headers_for_record(row: dict[str, str]) -> list[str]:
```

- Existing Sheet headers are extended with any new row key:

```python
src/backend/endpoints/client_leads.py:1086
for header in meta_sheet_headers_for_record(row):
    if header not in headers:
        headers.append(header)
```

- The append writes every header value:

```python
src/backend/endpoints/client_leads.py:1100
body={"values": [[row.get(header, "") for header in headers]]},
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Meta append scan | `rg -n "meta_field_data_to_row|meta_sheet_headers_for_record|append_record_to_sheet|field_data|form_id|ad_id|campaign_id|META_SHEET" src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py README.md .codex/skills wiki/skills` | append field contract is visible |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -k "meta_lead or sheet" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Define a default Meta-to-Sheet append allowlist.
- Keep provider ids available to application logic without appending them by default.
- Add source-level or environment-level opt-in for extra appended fields only if operators need it.
- Prevent unknown Meta `field_data` keys from automatically extending connected Sheet headers.
- Update README and spreadsheet skills with the append contract.
- Add tests proving provider ids and unknown fields are omitted by default and included only by explicit configuration.

**Out of scope**:
- Changing local DB import/upsert fields unless needed to preserve provider ids.
- Meta backfill pagination; plan 134 owns that.
- Duplicate append behavior; plan 014 owns that.
- CSV formula neutralization; plan 143 owns spreadsheet formula handling.
- Live Google Sheets calls.

## Git Workflow

- Branch: `codex/minimize-meta-sheet-fields`
- Commit message: `Minimize Meta Sheet append fields`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define the default field contract

Choose a readable default such as:

- lead id / leadgen id,
- created time,
- name,
- phone,
- email,
- source/form display label if user-facing,
- any current operator-required business fields.

Do not include raw `form_id`, `ad_id`, `adset_id`, or `campaign_id` by default.

### Step 2: Split import row from append row

Keep `meta_field_data_to_row()` or an equivalent internal row rich enough for local import. Add a separate projection for Sheet append, for example `meta_sheet_append_row(row, source)`.

The append projection should only include allowlisted fields. Unknown `field_data` names should not automatically become headers unless the source explicitly allows them.

### Step 3: Preserve explicit opt-in

If there is already a config surface for source metadata, add a narrow list of extra Sheet append fields there. Otherwise, document a STOP condition rather than adding a broad config system.

The opt-in should be field-name based, not "append all raw Meta fields".

### Step 4: Add tests

Cover:

- default append omits `form_id`, `ad_id`, `adset_id`, and `campaign_id`,
- default append omits an unexpected `field_data` key,
- business fields still append in stable order,
- explicit extra field config includes only the named extra field,
- existing backfill/import tests still pass.

### Step 5: Update docs and skills

Update README and spreadsheet skill mirrors so operators know connected Sheets receive a minimized projection, not the raw Meta provider payload.

## Test Plan

- Targeted Delivery tests pass.
- Backend import smoke passes.
- No live Meta or Google Sheets request is performed.

## Done Criteria

- [ ] Connected Google Sheets no longer receive raw provider ids by default.
- [ ] Unknown Meta lead-form fields do not auto-expand Sheet headers by default.
- [ ] Explicitly configured extra fields still work.
- [ ] Docs describe the default append projection.

## STOP Conditions

- Operators rely on raw provider ids in connected Sheets for active operations.
- There is no safe place to configure explicit extra fields without broad config work.
- Existing Sheet schemas must be preserved exactly for a live client before rollout.

## Maintenance Notes

The application can keep provider identifiers internally while giving operators a cleaner Sheet. Treat Sheet append as an export boundary, not a dump of the provider payload.
