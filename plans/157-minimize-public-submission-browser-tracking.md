# Plan 157: Minimize Public Submission Browser Tracking

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PUBLIC-TRACKING-01

## Why This Matters

Public campaign submissions persist browser tracking values. The current browser payload sends the full page URL and full referrer, and the backend stores both with only a length cap. Query strings and fragments can contain tokens, ad click parameters, emails, phone numbers, or other sensitive data.

The public form should store only the tracking fields the product needs, and URL-like tracking should be reduced to a safe origin/path shape without query or fragment.

## Current State

- Full URL and referrer are allowed tracking keys:

```python
src/backend/endpoints/campaigns.py:62
PUBLIC_ALLOWED_TRACKING_KEYS = {
    "href",
    "referrer",
    "fbp",
    "fbc",
```

- Tracking values are persisted after only normalization and a length cap:

```python
src/backend/endpoints/campaigns.py:1502
tracking[clean_key] = clean_value[:PUBLIC_MAX_TRACKING_TEXT]
```

- Public HTML sends full location and referrer:

```javascript
src/backend/endpoints/campaigns.py:2551
tracking: {
  href: window.location.href,
  referrer: document.referrer,
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Tracking scan | `rg -n "PUBLIC_ALLOWED_TRACKING_KEYS|href|referrer|window\\.location|document\\.referrer|_normalize_tracking|tracking" src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py README.md` | public tracking values are minimized |
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -k "public or tracking or submission" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Remove `href` and `referrer` from browser-submitted tracking, or sanitize them server-side to origin/path only.
- Keep explicit UTM fields and Meta browser ids (`fbp`, `fbc`) if Meta CAPI still needs them.
- Drop URL query strings and fragments before persistence.
- Add tests proving sensitive query/referrer values are not stored.
- Update README if public tracking fields are documented.

**Out of scope**:
- Submission dedupe/retry behavior; plans 016 and 017 own side-effect correctness.
- Public submission throttling; plan 037 owns abuse throttling.
- Meta CAPI event status/retry design.
- Removing all analytics.

## Git Workflow

- Branch: `codex/minimize-public-submission-tracking`
- Commit message: `Minimize public submission browser tracking`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define the tracking contract

Keep a small allowlist:

- UTM keys,
- `fbp`,
- `fbc`,
- optionally sanitized page/referrer origin/path if operators need attribution.

Do not store raw `window.location.href` or `document.referrer` with query or fragment.

### Step 2: Sanitize at the server boundary

Even if the browser stops sending raw values, make `_normalize_tracking()` resilient to malicious clients.

If `href` or `referrer` remain accepted, parse them and store only safe components such as scheme, host, and path.

### Step 3: Update public HTML

Remove raw `href` and `referrer` from the default browser payload or send already-sanitized values.

Do not add new third-party tracking scripts.

### Step 4: Add tests

Cover:

- submitted `href` with `?token=secret#fragment` does not persist the secret,
- submitted `referrer` with PII query params does not persist the query,
- UTM and `fbp`/`fbc` fields still persist as expected,
- unknown tracking keys are ignored.

## Test Plan

- Campaign public submission tests pass.
- Backend import smoke passes.
- Manual scan confirms raw browser URL/referrer are not persisted.

## Done Criteria

- [ ] Public submissions no longer persist raw full URL or referrer.
- [ ] Server-side tracking normalization strips query and fragment from URL-like fields.
- [ ] Needed attribution fields still work.
- [ ] Tests cover malicious URL/referrer values.

## STOP Conditions

- Operators rely on full referrer/query values for active attribution reports.
- Meta CAPI requires a raw field that would be removed and no safe replacement is available.
- Existing stored tracking data migration is required before changing the contract.

## Maintenance Notes

Browser-sent tracking is visitor-controlled and can carry secrets accidentally. Keep it explicit and minimal.
