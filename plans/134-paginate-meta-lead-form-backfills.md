# Plan 134: Paginate Meta Lead Form Backfills

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/meta_lead_ads.py src/backend/endpoints/client_leads.py src/backend/ai/codex_agent_tools.py src/backend/tests/test_client_lead_delivery.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/014-cover-duplicate-meta-backfill.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: META-03

## Why This Matters

Meta lead-form backfill fetches one Graph page and then marks the sync as `ok`. If a form has more leads than the first page, operators see a successful backfill even though older leads were never imported.

Backfill should paginate with explicit caps and report when results are partial.

## Current State

- Fetch uses one limit-capped Graph request:

```python
src/backend/meta_lead_ads.py:137
params = {
```

```python
src/backend/meta_lead_ads.py:142
payload = getter(f"{clean_form_id}/leads", params)
```

- The function returns only `payload["data"]` and ignores cursors:

```python
src/backend/meta_lead_ads.py:150
data = payload.get("data", [])
```

- Backfill records `status="ok"` based only on that page:

```python
src/backend/endpoints/client_leads.py:783
def fetch_and_import_meta_lead_form_records(
```

```python
src/backend/endpoints/client_leads.py:826
source = ClientLeadSource.mark_sync(source.id, status="ok", note=note) or source
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Backfill scan | `rg -n "fetch_meta_form_leads|paging|next|cursor|backfill|meta_form" src/backend/meta_lead_ads.py src/backend/endpoints/client_leads.py src/backend/ai/codex_agent_tools.py src/backend/tests/test_client_lead_delivery.py` | backfill paginates or reports truncation |
| Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add cursor-aware Graph pagination for form leads.
- Add explicit `max_pages`, `max_leads`, and optional date-window controls.
- Return summary metadata such as `pages_fetched`, `truncated`, `next_cursor`, and `complete`.
- Surface partial/truncated status in source sync notes and API responses.
- Preserve duplicate-import behavior from plan 014.

**Out of scope**:
- Changing Meta webhook ingestion.
- Live Google Sheet append behavior except preserving no duplicate rows.
- Long-running background jobs for very large historical imports.

## Git Workflow

- Branch: `codex/paginate-meta-lead-backfill`
- Commit message: `Paginate Meta lead form backfills`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Return a structured fetch result

Change `fetch_meta_form_leads()` or add a new wrapper so callers receive both payloads and pagination metadata.

Keep a compatibility helper if existing tests/tools expect a list.

### Step 2: Follow Graph paging safely

Use Graph cursors or next-page URLs through the configured getter, bounded by `max_pages` and `max_leads`.

Do not fetch unbounded history by default.

### Step 3: Report partial results

When caps stop pagination or provider paging errors occur after some pages, return a partial/truncated status instead of plain `ok`.

Include enough metadata for an operator to rerun a narrower backfill.

### Step 4: Add tests

Cover:

- two-page success,
- cap truncation,
- provider error after first page,
- repeated paginated backfill does not duplicate rows,
- response/source note exposes partial status.

## Test Plan

- Delivery tests pass.
- Backend import smoke passes.
- Manual scan confirms no caller treats a truncated backfill as fully complete.

## Done Criteria

- [ ] Backfill follows Meta paging within explicit caps.
- [ ] Partial/truncated imports are visible in API response and source sync state.
- [ ] Duplicate-row behavior remains covered.
- [ ] Tests cover pagination and truncation.

## STOP Conditions

- Current Graph getter cannot safely follow cursors without a broader HTTP client refactor.
- Product owner wants only first-page backfills by design.
- Response model changes would break deployed bot/agent clients without a compatibility path.

## Maintenance Notes

Backfill status should say what actually happened: full import, partial import, or blocked. Do not mark unknown history as complete.
