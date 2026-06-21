# Plan 143: Neutralize Spreadsheet Formulas In CSV Exports

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/endpoints/client_leads.py src/scripts/contadores_promo_web_20260505.py src/scripts/contadores_followup_wave_20260502.py src/backend/tests/test_contadores.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CSV-01

## Why This Matters

CRM snapshots and operator report CSVs include lead names, email, phone, message text, template params, and recent transcripts. If any user-controlled value starts with spreadsheet formula markers, opening the CSV in Excel, Numbers, or Google Sheets can evaluate it as a formula.

CSV exports should neutralize formula-looking cells while preserving readable values.

## Current State

- Follow-up snapshot CSV writes lead/message text directly:

```python
src/backend/endpoints/contadores.py:1958
def build_followup_snapshot_csv(snapshots: list[ContadoresFollowupLeadSnapshot]) -> str:
```

```python
src/backend/endpoints/contadores.py:1995
writer = csv.DictWriter(output, fieldnames=fieldnames)
```

```python
src/backend/endpoints/contadores.py:2000
f"{'me' if message.from_me else 'lead'}: {message.text}"
```

- Snapshot CSV is downloadable:

```python
src/backend/endpoints/contadores.py:4710
@contadores_router.get("/followup/snapshot.csv")
```

- One-off report previews write rendered text and params directly:

```python
src/scripts/contadores_promo_web_20260505.py:384
def write_preview(path: Path, candidates: list[CampaignCandidate]) -> None:
```

```python
src/scripts/contadores_followup_wave_20260502.py:641
def write_preview(plans: list[PlannedSend], path: Path) -> None:
```

- Google Sheets append uses `valueInputOption="RAW"`, which is safer than user-entered formula parsing but should be covered by tests/documentation:

```python
src/backend/endpoints/client_leads.py:1103
valueInputOption="RAW",
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| CSV writer scan | `rg -n "csv\\.DictWriter|writerow|text/csv|snapshot\\.csv|valueInputOption|rendered_text|recent_transcript" src/backend src/scripts src/backend/tests` | exported CSV cells are formula-neutralized |
| Contadores CSV tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "snapshot_csv or followup_snapshot" -q` | exit 0 |
| Delivery sheet tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -k "sheet or meta_lead" -q` | exit 0 |
| Script syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/scripts/contadores_promo_web_20260505.py src/scripts/contadores_followup_wave_20260502.py` | exit 0 |

## Scope

**In scope**:
- Add a shared helper to neutralize spreadsheet formulas in CSV/download contexts.
- Apply it to follow-up snapshot CSV cells and one-off script CSV previews/ledgers.
- Cover common formula prefixes after leading whitespace: `=`, `+`, `-`, `@`, tab, carriage return, and newline.
- Preserve machine IDs and numeric-looking values where safe, or document intentional escaping.
- Add tests for formula-looking lead names, emails, phone-like values, and message text.

**Out of scope**:
- Redacting sensitive CSV fields; plan 142 owns redacted default reports.
- Retention of generated report files; plan 142 owns one-off report retention.
- Changing Google Sheets append behavior unless tests show `RAW` is insufficient.

## Git Workflow

- Branch: `codex/neutralize-csv-formulas`
- Commit message: `Neutralize spreadsheet formulas in CSV exports`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add a shared neutralizer

Create a small helper such as `neutralize_spreadsheet_formula(value: object) -> str`.

For strings whose first non-space character is a formula marker, prefix a single quote or another documented neutralizer.

Keep empty values empty.

### Step 2: Apply to CSV export rows

Use the helper in:

- follow-up snapshot CSV row construction,
- promo preview/ledger CSV fields,
- follow-up wave preview CSV fields,
- any other `csv.DictWriter` path found by the scan.

### Step 3: Verify Google Sheets append assumptions

Add or update tests confirming appended Meta lead rows use `valueInputOption="RAW"`.

If RAW still allows formula execution in the target workflow, apply the same neutralizer before appending user-controlled values.

### Step 4: Add regression tests

Cover formula-looking values in lead fields and message text. Assert the exported CSV contains neutralized cell values and still parses with `csv.DictReader`.

## Test Plan

- Contadores CSV tests pass.
- Delivery sheet tests pass.
- Script syntax checks pass.
- Manual scan shows no remaining raw `csv.DictWriter` path with user-controlled fields.

## Done Criteria

- [ ] CSV exports neutralize formula-looking cells.
- [ ] One-off report CSVs use the same helper or documented equivalent.
- [ ] Google Sheets append is verified as safe or neutralized.
- [ ] Tests cover formula-looking user input.

## STOP Conditions

- Operators require exact unmodified CSV values and accept spreadsheet formula risk.
- A downstream automation depends on leading `=` values as data and cannot handle neutralization.
- Shared helper placement would require a broader package refactor.

## Maintenance Notes

CSV quoting is not formula protection. Treat spreadsheet-opening behavior as part of the export surface.
