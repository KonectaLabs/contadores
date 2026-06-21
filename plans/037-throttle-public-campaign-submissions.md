# Plan 037: Throttle Public Campaign Submissions

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/016-make-public-submission-deduplication-atomic.md
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PUBLIC-03

## Why This Matters

Public campaign submissions are intentionally unauthenticated. A unique submission can create a lead-capture row, queue Delivery, and trigger Meta CAPI. Existing plans harden validation, dedupe, and retry behavior, but they do not stop high-volume unique submissions from creating side effects.

## Current State

- The auth middleware exempts all public campaign API routes:

```python
src/backend/main.py:291
if (
    path in PUBLIC_PATHS_WITHOUT_SESSION
    or path == "/p"
    or path.startswith("/p/")
    or path == "/c"
    or path.startswith("/c/")
    or path.startswith("/api/public/campaigns/")
):
```

- The public submission endpoint accepts and processes public POSTs:

```python
src/backend/endpoints/campaigns.py:2221
@public_campaigns_router.post("/api/public/campaigns/{public_slug}/submissions")
async def submit_public_campaign_form(
```

- Side effects happen after insert:

```python
src/backend/endpoints/campaigns.py:2265
deliveries = _queue_deliveries_for_submission(campaign=campaign, submission=submission)
...
src/backend/endpoints/campaigns.py:2272
submission = _track_meta_event(request=request, campaign=campaign, submission=submission)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/campaigns.py`
- `src/backend/tests/test_campaigns.py`
- `.env.example`
- README public campaign form notes.

**Out of scope**:
- CAPTCHA or external anti-abuse providers.
- Persistent cross-process rate-limit storage.
- Changing the public receipt contract for legitimate submissions.
- Changing Delivery or Meta side-effect internals.

## Git Workflow

- Branch: `codex/throttle-public-campaign-submissions`
- Commit message: `Throttle public campaign submissions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add small throttle settings

Add explicit env-backed settings with conservative defaults:

- `PUBLIC_SUBMISSION_THROTTLE_ENABLED=true`,
- `PUBLIC_SUBMISSION_IP_WINDOW_SECONDS=60`,
- `PUBLIC_SUBMISSION_IP_MAX=5`,
- `PUBLIC_SUBMISSION_CAMPAIGN_WINDOW_SECONDS=60`,
- `PUBLIC_SUBMISSION_CAMPAIGN_MAX=40`.

Keep parsing local to the campaigns endpoint or a small helper. Do not add a broad settings framework.

### Step 2: Add an in-process sliding-window helper

Add a small helper that tracks recent submission attempts by:

- campaign id,
- campaign id plus client IP key.

Use monotonic time for cleanup. Keep the data structure simple, such as a dict of deques with expired timestamps removed before each decision.

Client IP should use the safest source available in the current app:

- prefer `request.client.host`,
- only use forwarded headers if there is an existing trusted-proxy convention in the repo,
- otherwise leave a README note that proxy-aware IP extraction is a follow-up.

### Step 3: Preserve legitimate retries

Keep the idempotency duplicate check before the throttle decision:

1. load campaign,
2. return honeypot receipt for honeypot submissions,
3. compute scoped idempotency key,
4. return duplicate receipt if the idempotency key already exists,
5. validate answers and contact fields,
6. evaluate throttle,
7. only then insert, queue Delivery, and track Meta.

This order lets a browser retry with the same idempotency key without being blocked by the throttle.

### Step 4: Drop abuse before side effects

When the throttle says to drop:

- do not call `LeadCaptureSubmission.add()`,
- do not call `_queue_deliveries_for_submission()`,
- do not call `_track_meta_event()`,
- return a neutral accepted receipt with no submission payload.

Do not expose detailed throttle counters in the public response. If useful, log a concise server-side event or add a platform event without storing raw IP addresses.

### Step 5: Add tests

Add tests that prove:

- normal submission still creates one submission,
- same idempotency key retry still returns duplicate and does not count as abuse,
- exceeding campaign/IP limit returns accepted but creates no submission,
- throttled submissions do not queue Delivery,
- throttled submissions do not call Meta CAPI.

Keep tests deterministic by injecting a fake clock or by exposing a tiny reset helper for test setup.

## Test Plan

- Run the campaign test command.
- Run the backend import smoke.
- Manually inspect the public endpoint order and confirm the throttle happens before side effects.

## Done Criteria

- [ ] Public submissions have a server-side throttle before Delivery and Meta side effects.
- [ ] Idempotent retries still work.
- [ ] Throttled attempts do not create submissions, deliveries, or Meta CAPI events.
- [ ] Tests cover normal, duplicate, and throttled paths.
- [ ] `.env.example` and README document the throttle knobs.

## STOP Conditions

- Production runs multiple backend workers or nodes and requires a persistent/shared throttle before this can be meaningful.
- Existing proxy headers cannot be trusted and operator wants IP-specific enforcement before campaign-global throttling.
- The throttle would block known paid traffic volumes with the default limits.

## Maintenance Notes

This is a small first server-side control. It is not a replacement for upstream firewall rules, CAPTCHA, or persistent rate limiting if public ad traffic grows.
