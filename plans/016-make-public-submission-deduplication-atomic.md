# Plan 016: Make Public Submission Deduplication Atomic

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/020-add-migration-discipline-for-production-schema-changes.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Public form submissions can be retried by browsers, mobile networks, and users double-tapping submit. The current path checks idempotency and phone duplication before insertion, but those checks are not atomic with the insert. A concurrent duplicate can either raise an unhandled uniqueness error or create two submissions before the phone-dedupe read sees the other request.

## Current State

- The endpoint checks idempotency before writing:

```python
src/backend/endpoints/campaigns.py:2232
scoped_idempotency_key = _submission_idempotency_key(campaign, command.idempotency_key)
duplicate = LeadCaptureSubmission.get_by_idempotency_key(scoped_idempotency_key)
if duplicate is not None:
    return _public_submission_receipt(campaign=campaign, submission=duplicate, duplicate=True)
```

- Phone dedupe is also check-before-insert:

```python
src/backend/endpoints/campaigns.py:2247
phone_duplicate = LeadCaptureSubmission.get_latest_by_campaign_phone(campaign.id, phone)
if phone_duplicate is not None:
    return _public_submission_receipt(campaign=campaign, submission=phone_duplicate, duplicate=True)
```

- `idempotency_key` is unique, but `campaign_id + normalized_phone` is only indexed through separate columns:

```python
src/backend/database.py:3516
idempotency_key: str | None = Field(default=None, sa_column=Column(String, unique=True, index=True, nullable=True))
normalized_phone: str = Field(default="", index=True)
```

- `LeadCaptureSubmission.add()` performs another read in a separate session, then commits:

```python
src/backend/database.py:3591
clean_key = (idempotency_key or "").strip() or None
if clean_key:
    existing = cls.get_by_idempotency_key(clean_key)
    if existing is not None:
        return existing
...
session.add(row)
session.commit()
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/database.py`
- `src/backend/endpoints/campaigns.py`
- `src/backend/tests/test_campaigns.py`

**Out of scope**:
- Changing public receipt shape.
- Changing Delivery queueing side effects; plan 017 covers retry reconciliation.
- Adding a broad migration framework; plan 020 covers schema discipline and should land before any new public-submission index.

## Git Workflow

- Branch: `codex/atomic-public-submission-dedup`
- Commit message: `Make public submission deduplication atomic`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Make idempotency insert race-safe

Update `LeadCaptureSubmission.add()` so a concurrent insert with the same `idempotency_key` returns the existing row rather than surfacing an integrity failure.

Implementation shape:

- keep the fast pre-read for the common duplicate case,
- wrap `session.commit()` with `IntegrityError` handling,
- rollback,
- re-read by `idempotency_key`,
- return the existing row if found,
- re-raise if the integrity failure is unrelated.

Keep the code explicit and easy to read.

### Step 2: Decide and document phone uniqueness

Choose one of these and document the choice in the plan implementation notes or code comment:

- Stronger option: after plan 020 has landed, add a partial unique index for `(campaign_id, normalized_phone)` where `normalized_phone != ''` and the row is not a phone-missing placeholder.
- Safer first option: keep phone dedupe as best-effort and only harden idempotency now.

If plan 020 has not landed, choose the safer first option or stop. If choosing the stronger option, audit existing duplicate production rows before adding the index, and route ambiguous duplicates to a STOP condition.

### Step 3: Add tests for same-key concurrency behavior

Avoid brittle real threading if the test harness makes that noisy. It is acceptable to unit-test the database helper by monkeypatching the session commit path to raise an idempotency-key `IntegrityError`, then asserting the existing row is returned.

Also preserve the existing endpoint-level test:

```python
src/backend/tests/test_campaigns.py:959
def test_public_idempotency_is_campaign_scoped_and_phone_dedupes(...)
```

## Test Plan

- Existing campaign public submission tests.
- New duplicate idempotency insert race regression.
- Backend import smoke.

## Done Criteria

- [ ] Concurrent same-key insert resolves to the existing submission instead of a 500.
- [ ] Existing campaign-scoped idempotency behavior is preserved.
- [ ] Phone-dedupe uniqueness decision is explicit.
- [ ] Campaign tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- Existing production data contains duplicate `(campaign_id, normalized_phone)` rows and the selected implementation would fail startup/deploy.
- The only available fix requires changing public receipt semantics.

## Maintenance Notes

This plan is about atomic persistence. Do not mix in Delivery side-effect repair; that belongs in plan 017.
