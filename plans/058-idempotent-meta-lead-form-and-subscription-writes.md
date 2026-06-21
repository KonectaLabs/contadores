# Plan 058: Idempotent Meta Lead Form And Subscription Writes

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/meta_lead_forms.py src/backend/tests/test_contadores.py src/backend/database.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/057-persist-meta-publish-operation-state-incrementally.md
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: LIVE-08

## Why This Matters

Meta lead form creation and webhook subscription writes record idempotent events after the provider call. Repeated tool calls or a crash after Graph success can recreate forms or resubscribe webhooks without consulting a durable pre-call attempt record.

## Current State

- Lead form creation calls Graph:

```python
src/backend/meta_lead_forms.py:196
response_payload = poster(f"{page_id}/leadgen_forms", params)
```

- Success event idempotency is recorded after success:

```python
src/backend/meta_lead_forms.py:231
PlatformEvent.add(
```

- Subscription calls Graph:

```python
src/backend/meta_lead_forms.py:287
response_payload = poster(f"{page_id}/subscribed_apps", params)
```

- Subscription event is also recorded after success:

```python
src/backend/meta_lead_forms.py:299
PlatformEvent.add(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Meta lead write tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "meta_lead_form or webhook_sub" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add durable idempotency before live Meta lead form/subscription writes.
- Reuse existing linked `ClientLeadSource` metadata where possible.
- Add tests for duplicate and crash-window behavior.

**Out of scope**:
- Changing Meta lead webhook signature verification.
- Changing form question schema.
- Deleting duplicate forms already created.

## Git Workflow

- Branch: `codex/idempotent-meta-lead-writes`
- Commit message: `Make Meta lead writes idempotent`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define write idempotency keys

Use stable keys based on:

- page id,
- form name or client lead source id,
- requested questions/privacy/thank-you config for forms,
- page id plus subscribed fields for webhook subscriptions.

Reject conflicting same-key payloads rather than silently reusing wrong objects.

### Step 2: Persist attempt before provider call

Use a table or existing event/attempt model that can record:

- requested payload,
- status `pending`,
- provider id once available,
- error if failed.

Follow plan 020 if schema changes are needed.

### Step 3: Reuse successful attempts

Before Graph call, check for an existing successful attempt with same payload.

If found, return the existing provider id/result and do not call Graph.

### Step 4: Add crash-window tests

Use fake Graph posters to prove:

- duplicate call with same key returns existing result,
- conflict with same key and different payload is rejected,
- provider success is persisted before linked source update/event work can fail.

## Test Plan

- Run Meta lead write tests.
- Run backend import smoke.
- Inspect event/attempt payloads for secret redaction.

## Done Criteria

- [ ] Repeated form create requests do not recreate forms.
- [ ] Repeated subscription requests do not repeat provider writes unnecessarily.
- [ ] Conflicting same-key payloads are rejected.
- [ ] Tests cover duplicate and crash-window behavior.

## STOP Conditions

- Meta API already dedupes these calls in a way the repo can reliably query and reuse.
- Schema changes are needed but plan 020 has not landed.
- Existing tools do not provide stable idempotency inputs.

## Maintenance Notes

Post-success events are useful audit logs, but they are not enough to make external writes idempotent.
