# Plan 167: Enforce Platform Logical Identity Constraints

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/tests/test_contadores.py src/backend/tests/test_campaigns.py src/backend/tests/test_platform.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/020-add-migration-discipline-for-production-schema-changes.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PLATFORM-IDEMPOTENCY-01

## Why This Matters

Several platform tables implement idempotency or one-row logical identity with read-before-insert checks but only plain indexes. Concurrent calls can still insert duplicates. Those duplicates can make event streams, meetings, ad campaign staging, and client profiles inconsistent.

Logical identity should be enforced by database constraints, with helpers catching integrity races and returning compatible existing rows.

## Current State

- Platform events dedupe by read-before-insert:

```python
src/backend/database.py:3970
existing = cls.get_by_idempotency_key(clean_key)
```

- Platform meetings use the same pattern:

```python
src/backend/database.py:4161
existing = cls.get_by_idempotency_key(clean_key)
```

- Platform ad campaigns use the same pattern:

```python
src/backend/database.py:4460
existing = cls.get_by_idempotency_key(clean_key)
```

- Client profiles upsert by `client_id` without a unique constraint:

```python
src/backend/database.py:4368
row = session.exec(select(cls).where(cls.client_id == clean_client_id)).first()
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Platform identity scan | `rg -n "PlatformEvent|PlatformMeeting|PlatformAdCampaign|PlatformClientProfile|idempotency_key|client_id|IntegrityError|unique" src/backend/database.py src/backend/tests` | logical identities have constraints and race-safe helpers |
| Platform tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "PlatformEvent or PlatformMeeting or PlatformAdCampaign or PlatformClientProfile or idempotency" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Run duplicate reports before adding constraints.
- Add migration-backed uniqueness for non-empty idempotency keys on platform event, meeting, and ad campaign tables.
- Add unique logical identity for `PlatformClientProfile.client_id`.
- Update add/upsert helpers to catch integrity conflicts, re-read, and return compatible existing rows.
- Add tests for duplicate/race-compatible behavior.

**Out of scope**:
- Public submission idempotency; plan 016 owns that table.
- Delivery/WhatsApp/provider id uniqueness; plans 019, 084, and 085 own those.
- Scheduled task idempotency; plan 086 owns scheduled agent tasks.
- Broad migration framework; plan 020 owns migration discipline.

## Git Workflow

- Branch: `codex/platform-logical-identity-constraints`
- Commit message: `Enforce platform logical identity constraints`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add duplicate reports

Before schema changes, add or run read-only reports for duplicate:

- `PlatformEvent.idempotency_key`,
- `PlatformMeeting.idempotency_key`,
- `PlatformAdCampaign.idempotency_key`,
- `PlatformClientProfile.client_id`.

Ignore blank/null idempotency keys for partial uniqueness.

### Step 2: Add constraints through migration discipline

Use plan 020's migration path. For SQLite, use partial unique indexes for non-empty idempotency keys if supported.

### Step 3: Make helpers race-safe

Catch `IntegrityError` on insert/upsert, rollback, and re-read the existing row.

Return the existing row only when payloads are compatible. If conflicting payloads share a key, fail with a clear error.

### Step 4: Add tests

Cover duplicate add calls and simulated integrity conflict for each table family.

For client profiles, assert repeated upsert updates one row, not two.

## Test Plan

- Platform/idempotency tests pass.
- Backend import smoke passes.
- Duplicate reports show no production blockers before deploy.

## Done Criteria

- [ ] Platform logical idempotency keys are database-enforced.
- [ ] Client profiles are unique by client id.
- [ ] Helpers handle insert races by returning compatible existing rows.
- [ ] Tests cover duplicate/race behavior.

## STOP Conditions

- Duplicate production rows already exist and need owner-approved cleanup.
- Plan 020 has not landed and production schema changes are not allowed.
- Partial unique indexes are not portable enough for current deployment.

## Maintenance Notes

Read-before-insert is a convenience, not a concurrency guarantee. Put logical identity in the database.
