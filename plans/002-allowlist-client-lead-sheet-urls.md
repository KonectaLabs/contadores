# Plan 002: Allowlist Client Lead Sheet Fetch URLs

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/client_leads.py src/backend/tests/test_client_lead_delivery.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Delivery source sync fetches operator-configured Google Sheets URLs. The current `public_csv_url()` accepts any URL containing `output=csv`, `format=csv`, or `tqx=out:csv` and passes it to `httpx`. That makes an authenticated config-writing path able to force backend requests to arbitrary hosts. Contadores should only fetch Google Sheets export URLs unless a separate trusted custom CSV mode is intentionally designed later.

## Current State

- `public_csv_url()` trusts marker substrings before parsing a spreadsheet id:

```python
src/backend/endpoints/client_leads.py:898
def public_csv_url(sheet_url: str, sheet_gid: str | None, sheet_tab_name: str | None = None) -> str:
    """Build a public CSV export URL for a Google Sheet."""
    if any(marker in sheet_url for marker in ["output=csv", "format=csv", "tqx=out:csv"]):
        return sheet_url
    spreadsheet_id, gid = parse_sheet_target(sheet_url, sheet_gid)
```

- `fetch_sheet_records()` fetches that URL directly:

```python
src/backend/endpoints/client_leads.py:1121
async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
    try:
        response = await client.get(public_csv_url(source.sheet_url, source.sheet_gid, source.sheet_tab_name))
```

- Existing sheet URL tests cover Google forms only:

```python
src/backend/tests/test_client_lead_delivery.py:766
def test_client_lead_sheet_helpers_parse_common_targets() -> None:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Targeted Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/client_leads.py`
- `src/backend/tests/test_client_lead_delivery.py`
- `README.md` if the accepted URL contract needs one sentence of clarification.

**Out of scope**:
- Adding custom CSV support.
- Changing service-account fallback behavior except where it depends on the same Google Sheet parser.
- Any live Google Sheets call.

## Git Workflow

- Branch: `codex/allowlist-client-lead-sheet-urls`
- Commit message: `Allowlist Delivery sheet fetch URLs`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add an explicit Google Sheets host check

In `src/backend/endpoints/client_leads.py`, add a helper:

```python
GOOGLE_SHEETS_HOSTS = {"docs.google.com", "spreadsheets.google.com"}
```

Add:

```python
def require_google_sheet_url(sheet_url: str) -> None:
    parsed = urlparse((sheet_url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Sheet URL must be a Google Sheets URL.")
    if parsed.netloc.lower() not in GOOGLE_SHEETS_HOSTS:
        raise ValueError("Sheet URL must use docs.google.com or spreadsheets.google.com.")
```

Use exact host equality, not suffix matching.

**Verify**: targeted tests should fail until they cover the new helper.

### Step 2: Normalize all public export URLs through the parser

Change `public_csv_url()` so it always validates and extracts the spreadsheet id before returning a URL. Do not return arbitrary raw URLs based on marker substrings.

Allowed output:

- For tab name: `https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&sheet=...`
- Otherwise: `https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid=...`

If the user already supplied a Google export URL, parse the spreadsheet id and gid from it, then rebuild the safe docs.google.com export URL.

**Verify**:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q
```

Expected: tests pass after update.

### Step 3: Add rejection tests

Extend `test_client_lead_sheet_helpers_parse_common_targets()` or add a nearby test covering:

- `https://evil.example/export?format=csv` raises `ValueError`.
- `http://169.254.169.254/latest/meta-data?format=csv` raises `ValueError`.
- A valid Google edit URL still resolves to docs.google.com export URL.
- A valid Google `gviz/tq?tqx=out:csv` URL still resolves safely.

Use `pytest.raises(ValueError)` and do not perform a network call.

**Verify**: targeted Delivery tests exit 0.

### Step 4: Keep endpoint errors operator-friendly

If `fetch_sheet_records()` receives the `ValueError`, keep the existing `/sync` behavior of returning a failed sync with a clear detail. Do not leak stack traces.

**Verify**: add or update one API test only if existing tests do not already assert sync failure behavior for invalid URLs.

## Test Plan

- Pure helper tests for URL acceptance/rejection.
- Existing Delivery sync/import tests must still pass.
- No network access is required.

## Done Criteria

- [ ] `public_csv_url()` never returns a non-Google URL.
- [ ] Malicious CSV-looking URLs are rejected before `httpx` sees them.
- [ ] Existing Google Sheet edit/export/tab-name flows still work.
- [ ] Targeted Delivery tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- Current production data intentionally uses non-Google CSV URLs for Delivery sources.
- The parser cannot recover spreadsheet id/gid from an existing documented Google URL variant without a broader compatibility discussion.
- The fix requires adding a new trusted custom CSV configuration mode.

## Maintenance Notes

Future custom CSV support should be a separate explicit feature with its own allowlist or credential boundary. Do not reintroduce marker-substring URL trust in Delivery sync paths.
