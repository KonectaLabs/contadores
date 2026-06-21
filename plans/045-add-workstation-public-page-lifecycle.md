# Plan 045: Add Workstation Public Page Lifecycle

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/workstation.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/035-restrict-workstation-public-page-assets.md
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-01

## Why This Matters

Plan 035 limits which files a public Workstation URL can serve, but not how long the URL remains live. Public trial URLs are stable, unauthenticated, and stored as active. Closed, archived, handed-off, or expired clients can keep public trial pages online indefinitely unless lifecycle rules deactivate them.

## Current State

- `/p/` is unauthenticated:

```python
src/backend/main.py:291
if (
    path in PUBLIC_PATHS_WITHOUT_SESSION
    or path == "/p"
    or path.startswith("/p/")
```

- Public page rows default to active:

```python
src/backend/database.py:5944
status: str = Field(default="active", index=True)
```

- Public route only checks the active status:

```python
src/backend/database.py:5963
def get_active_by_token(cls, public_token: str) -> Optional["WorkstationPublicPage"]:
```

- README documents stable unauthenticated URLs:

```text
README.md:1458
Cada cliente `solo_pagina` con una version generada tiene una URL publica de
prueba estable, no autenticada e indescifrable
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Workstation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k workstation_public_page -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add explicit public page statuses or lifecycle timestamps.
- Deactivate public pages when Workstation/client/lead state should no longer be public.
- Add tests for closed lead, manual Workstation close, and stale/expired pages.
- Update README public URL semantics.

**Out of scope**:
- Changing token generation.
- Deleting generated files.
- Changing authenticated Workstation zip or file downloads.
- Building a full sharing-permissions UI.

## Git Workflow

- Branch: `codex/workstation-public-page-lifecycle`
- Commit message: `Add Workstation public page lifecycle`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define lifecycle rules

Choose explicit rules and document them in code/tests:

- public page is active while the client is in active review,
- manual Workstation close deactivates the page,
- linked CRM lead closed/archived deactivates the page,
- approval/handoff can either keep active for a short configured window or deactivate immediately,
- optional expiration can use an env var such as `WORKSTATION_PUBLIC_PAGE_TTL_DAYS`.

Keep the first version simple and conservative.

### Step 2: Add database helpers

Add helpers such as:

- `WorkstationPublicPage.deactivate_for_client(client_id, reason=...)`,
- `WorkstationPublicPage.is_active(...)` if needed.

If new columns are added, follow plan 020 migration discipline.

### Step 3: Wire lifecycle transitions

Call the helper from:

- manual Workstation close,
- `close_workstation_for_closed_lead()`,
- any existing close/archive path that touches linked Workstation leads.

Do not deactivate pages when a new version is created; that should keep the same stable token active.

### Step 4: Add tests

Cover:

- active token serves page,
- closed Workstation client returns 404 for same token,
- CRM-closed linked lead returns 404 after Workstation tick/close handling,
- creating a new version for an active client keeps the token live.

## Test Plan

- Run targeted Workstation public-page tests.
- Run backend import smoke.
- If schema changes are included, run the migration verification from plan 020.

## Done Criteria

- [ ] Public Workstation pages have explicit lifecycle rules.
- [ ] Closed or archived client/lead states no longer serve public pages.
- [ ] Active clients still keep stable public URLs between versions.
- [ ] README explains when public links stop working.

## STOP Conditions

- Operator wants public trial pages to remain available indefinitely after close/handoff.
- Schema changes are needed but plan 020 has not landed.
- Existing client communication relies on old public links staying live.

## Maintenance Notes

Unguesseable is not a lifecycle policy. Public links need explicit expiration or deactivation semantics.
