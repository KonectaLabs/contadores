# Plan 144: Allowlist Legacy Contadores Sheet Sync URLs

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/utils.py src/bot/main.py src/bot/tests README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/002-allowlist-client-lead-sheet-urls.md
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: SHEET-LEGACY-01

## Why This Matters

The legacy Contadores bot still fetches operator-configured sheet URLs. Its CSV builder accepts arbitrary URLs that contain CSV-looking markers or appends `output=csv` to any URL. That keeps an SSRF/source-trust gap open even after Delivery sheet sync is hardened.

Legacy funnel sync should use the same strict Google Sheets URL contract as Delivery sync: exact approved Google hosts, parse spreadsheet id/gid, rebuild the export URL, and reject arbitrary CSV endpoints unless a future explicit trusted custom-CSV mode is designed.

## Current State

- Legacy sync accepts raw CSV-looking URLs:

```python
src/bot/utils.py:371
def build_contadores_sheet_csv_url(config: ContadoresConfigPayload) -> str | None:
```

```python
src/bot/utils.py:376
if any(marker in base_url for marker in ["output=csv", "format=csv", "tqx=out:csv"]):
    return base_url
```

- Non-CSV URLs get `output=csv` appended without host validation:

```python
src/bot/utils.py:381
if gid and "gid=" not in base_url:
    return f"{base_url}{separator}gid={gid}&output=csv"
```

- The bot fetches that URL with redirects enabled and parses the text body directly:

```python
src/bot/utils.py:449
async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
    response = await client.get(csv_url)
```

```python
src/bot/utils.py:452
reader = csv.DictReader(StringIO(response.text))
```

- The worker calls this path for enabled campaign funnels on a loop:

```python
src/bot/main.py:280
await sync_contadores_sheet_to_backend(config=config, client=client)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| URL helper scan | `rg -n "build_contadores_sheet_csv_url|build_contadores_sheet_xlsx_url|fetch_contadores_sheet_rows|format=csv|output=csv|tqx=out:csv|follow_redirects" src/bot src/backend README.md` | legacy and Delivery URL contracts are visible |
| Bot tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/bot/tests -q` | exit 0 if bot tests exist |
| Bot import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from bot.utils import build_contadores_sheet_csv_url; print('bot-import-ok')"` | prints `bot-import-ok` |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Reuse the strict Google Sheets URL parser/normalizer from plan 002, or add an equivalent bot-local helper if sharing would create a poor dependency.
- Validate exact hosts: `docs.google.com` and `spreadsheets.google.com`.
- Rebuild CSV and XLSX export URLs from parsed spreadsheet id/gid instead of returning raw operator input.
- Cap downloaded response size before parsing if the current `httpx` path does not already do so.
- Decode CSV bytes with `utf-8-sig` so BOM-prefixed exports remain readable.
- Add tests for malicious CSV-looking URLs and valid Google edit/export URLs.

**Out of scope**:
- Adding custom CSV support.
- Changing funnel source-of-truth semantics; plan 009 owns that.
- Changing import merge semantics; plans 108 and 110 own sparse-row and identity behavior.
- Running the live bot loop.

## Git Workflow

- Branch: `codex/allowlist-legacy-contadores-sheet-sync`
- Commit message: `Allowlist legacy Contadores sheet sync URLs`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Decide helper ownership

If plan 002 has already added a reusable parser under a backend-neutral module, import and use it. If it stayed local to `client_leads.py`, add a small bot-local helper with the same exact contract instead of creating a broad refactor.

Do not leave two subtly different allowlists if sharing is easy.

### Step 2: Normalize CSV and XLSX URLs

Update `build_contadores_sheet_csv_url()` and `build_contadores_sheet_xlsx_url()` so they:

- strip input,
- require `http` or `https`,
- require exact approved Google host,
- parse the spreadsheet id from `/spreadsheets/d/{id}`,
- prefer configured `sheet_gid` when present,
- rebuild the export URL on `https://docs.google.com`.

Do not return raw URLs because they already contain `format=csv`, `output=csv`, or `tqx=out:csv`.

### Step 3: Bound fetch and parse behavior

In `fetch_contadores_sheet_rows()`:

- keep the timeout,
- reject oversized CSV/XLSX responses before parsing,
- parse CSV from bytes decoded as `utf-8-sig`,
- return a clear sync failure to the caller rather than leaking a stack trace if the configured URL is invalid.

Choose a readable size cap and document it if operators might hit it.

### Step 4: Add tests

Add or extend bot utility tests for:

- `https://evil.example/export?format=csv` rejected,
- `http://169.254.169.254/latest/meta-data?format=csv` rejected,
- `https://docs.google.com.evil/spreadsheets/d/abc/export?format=csv` rejected,
- a valid Google edit URL resolves to a docs.google.com CSV export,
- a valid Google export URL is parsed and rebuilt safely,
- XLSX fallback URL uses the same host validation.

Use pure helper tests where possible. Do not perform network calls.

## Test Plan

- Bot utility tests cover URL acceptance/rejection and export URL rebuilding.
- Bot import smoke passes.
- Backend import smoke passes if shared helpers moved.
- No live sheet, bot loop, or production sync is started.

## Done Criteria

- [ ] Legacy Contadores sheet sync cannot fetch non-Google URLs.
- [ ] CSV marker substrings no longer bypass parsing.
- [ ] Valid Google Sheet edit/export URLs still work.
- [ ] Oversized responses are rejected before CSV/XLSX parsing.
- [ ] Tests cover malicious hosts and valid Google variants.

## STOP Conditions

- Current production legacy funnels intentionally use non-Google CSV URLs.
- URL helper sharing would require a large cross-package refactor.
- The bot has no practical test harness and adding one would exceed this plan's scope.

## Maintenance Notes

Plan 002 hardens Delivery sheet sync. This plan is the legacy Contadores bot counterpart. Keep their accepted URL contract aligned so future spreadsheet docs do not describe two different safety models.
