# Plan 158: Remove Internal IDs From Public Campaign Payloads

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PUBLIC-PAYLOAD-01

## Why This Matters

Public campaign form responses embed internal campaign UUIDs and return internal submission UUIDs to the browser. Opaque public slugs already exist, so public clients do not need database primary keys. Returning internal IDs expands the public identifier surface and couples browser behavior to database rows.

Public payloads should expose only the lead-facing contract plus an opaque event id when needed for Meta Pixel/CAPI deduplication.

## Current State

- Public submission receipt returns the database submission id:

```python
src/backend/endpoints/campaigns.py:1027
receipt["submission"] = {
    "id": submission.id,
    "created_at": format_timestamp_seconds(submission.created_at),
}
```

- Public campaign payload includes internal campaign id and status:

```python
src/backend/endpoints/campaigns.py:1103
return {
    "id": campaign.id,
    "status": campaign.status,
    "public_slug": campaign.public_slug,
```

- The full public payload is embedded into the public HTML:

```python
src/backend/endpoints/campaigns.py:2398
const campaign = {payload_json};
```

- The public Pixel code uses the returned submission id as `eventID`:

```javascript
src/backend/endpoints/campaigns.py:2429
window.fbq("track", metaTracking.event_name || "Lead", {}, { eventID: String(payload.submission.id) });
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Public payload scan | `rg -n "_public_campaign_payload|_public_submission_receipt|submission\\.id|eventID|public_slug|status|\\\"id\\\"" src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py README.md` | public payload has an explicit allowlist |
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -k "public or meta_tracking or submission" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Define an explicit public campaign payload allowlist.
- Remove campaign `id` and `status` from public form config.
- Return a separate opaque `event_id` for browser Pixel dedupe instead of exposing the DB submission id.
- Keep backend Meta CAPI using the same stable event id.
- Add tests proving public payloads omit internal ids and still support Pixel dedupe.

**Out of scope**:
- Changing internal operator campaign payloads.
- Changing public slug generation; existing opaque slug behavior remains.
- Public submission dedupe/retry; plans 016 and 017 own write semantics.
- Removing Meta Pixel.

## Git Workflow

- Branch: `codex/remove-public-campaign-internal-ids`
- Commit message: `Remove internal IDs from public campaign payloads`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define public campaign payload fields

Keep only:

- `public_slug`,
- `public_url` if the browser needs it,
- `form_schema`,
- thank-you copy,
- minimized Meta config.

Do not include campaign `id`, internal `status`, internal name, client id, source ids, or platform ids.

### Step 2: Add an opaque event id

For successful submissions, return `submission.event_id` or `meta_event_id` under a public name such as:

```json
{"event_id": "..."}
```

Do not name this field `submission.id`.

If the current `meta_event_id` equals the DB id, change the generator to a separate opaque value while preserving idempotent duplicate behavior.

### Step 3: Update browser Pixel code

Change the public HTML to use the public event id:

```javascript
payload.event_id
```

Keep duplicate behavior unchanged.

### Step 4: Add tests

Cover:

- public config endpoint and HTML do not include campaign `id` or `status`,
- submission receipt does not include DB `submission.id`,
- receipt includes a stable opaque event id,
- duplicate response returns the same event id,
- Pixel HTML references `payload.event_id` or equivalent.

## Test Plan

- Campaign public/meta tracking tests pass.
- Backend import smoke passes.
- Manual public HTML scan confirms internal ids are absent.

## Done Criteria

- [ ] Public campaign config omits internal campaign id and status.
- [ ] Public submission receipt omits DB submission id.
- [ ] Browser Pixel dedupe uses a stable opaque event id.
- [ ] Tests cover public payload minimization.

## STOP Conditions

- Existing frontend/public browser code requires campaign or submission database ids.
- Meta CAPI dedupe cannot be preserved without the current DB id.
- External integrations consume the public receipt shape and cannot migrate.

## Maintenance Notes

Opaque public slugs are already the public identifier. Keep database primary keys on authenticated/operator surfaces.
