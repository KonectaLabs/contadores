# Plan 115: Source Campaign Delivery Presets From Server Config

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py src/frontend/src/App.tsx src/frontend/src/types.ts .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: config
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CONFIG-01

## Why This Matters

Campaign Delivery recipient presets are hard-coded in both backend and frontend source. That ships personal operator phone numbers in the built CRM bundle, makes recipient changes require a code deploy, and risks frontend/backend drift if one list changes without the other.

Delivery recipient presets should be server-owned configuration. The frontend should render presets returned by the authenticated API and should not embed private operator phone numbers as static source constants.

## Current State

- Backend owns a hard-coded preset map:

```python
src/backend/endpoints/campaigns.py:159
CAMPAIGN_DELIVERY_PRESETS = {
```

```python
src/backend/endpoints/campaigns.py:160
"alan": {"id": "alan", "label": "Alan", "phone": "393716506381", "kind": "preset"},
```

- Backend normalization accepts only ids from that hard-coded map:

```python
src/backend/endpoints/campaigns.py:798
if raw_id in CAMPAIGN_DELIVERY_PRESETS:
```

```python
src/backend/endpoints/campaigns.py:799
return dict(CAMPAIGN_DELIVERY_PRESETS[raw_id])
```

- Frontend ships the same presets and phone numbers:

```tsx
src/frontend/src/App.tsx:2794
const campaignDeliveryPresets: CampaignDeliveryContact[] = [
```

```tsx
src/frontend/src/App.tsx:2796
{ id: "mathi", label: "Mathi", phone: "5491138033159", kind: "preset" },
```

- Frontend default/suggestions use those static constants:

```tsx
src/frontend/src/App.tsx:2836
return { enabled: true, contacts: [campaignDeliveryPresets[0]] };
```

```tsx
src/frontend/src/App.tsx:2859
const suggestions = [campaignClientDeliveryContact(client), ...campaignDeliveryPresets.filter((contact) => contact.id !== "client")];
```

- Tests currently assert hard-coded preset labels and phone behavior:

```python
src/backend/tests/test_campaigns.py:419
def test_campaign_delivery_keeps_facu_preset_when_client_uses_same_phone(monkeypatch, tmp_path) -> None:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Preset scan | `rg -n "CAMPAIGN_DELIVERY_PRESETS|campaignDeliveryPresets|5491138033159|5491153484587|393716506381|delivery preset|delivery_presets" src/backend src/frontend src/backend/tests .env.example README.md` | personal preset numbers are not duplicated in frontend source or built assets |
| Campaign tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -k "delivery" -q` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Move campaign Delivery preset definitions to server-side config.
- Expose the authenticated preset list through an existing campaign/runtime API or a narrow new endpoint.
- Update frontend create/detail flows to use API-provided presets instead of source constants.
- Keep the special `client` contact option as a frontend/backend concept without a personal phone constant.
- Update tests and docs/env examples for the new config source.
- Ensure built frontend assets no longer contain the personal preset phone numbers.

**Out of scope**:
- Confirmation or staging for Delivery config mutations; plan 105 covers live-write UX safety.
- Sendable phone semantics; plan 111 covers strict WhatsApp destination validation.
- Changing campaign public form behavior.
- Replacing all operator names in docs or historical tests.

## Git Workflow

- Branch: `codex/server-config-campaign-delivery-presets`
- Commit message: `Source campaign delivery presets from server config`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose the config source

Prefer a readable server-owned config path, such as:

- `data/funnels.json` if presets are funnel-specific,
- a new env JSON variable if deployment wants simple server-only config,
- a small server config file if operators need structured editing.

Do not put personal numbers back into frontend source.

### Step 2: Centralize backend preset resolution

Replace the module constant with a loader that validates:

- preset id,
- label,
- phone,
- uniqueness by id,
- sendable phone once plan 111 has landed, or existing `normalize_phone` until then.

Keep a clear startup/runtime error when presets are malformed.

### Step 3: Return presets to the frontend

Expose presets only to authenticated CRM sessions. The existing `/api/campaigns/meta/defaults` or `/api/runtime` pattern may be acceptable, but keep the response non-secret and scoped.

The frontend should store presets in state from the API and fall back to only the `client` contact if presets are unavailable.

### Step 4: Update create/detail flows

Update:

- create-campaign default Delivery contact selection,
- create form preset suggestions,
- detail preset suggestions,
- payload serialization.

Avoid duplicated hard-coded lists.

### Step 5: Add regression checks

Test that:

- configured presets are accepted by id,
- missing/malformed presets do not silently route to a wrong recipient,
- frontend build output no longer contains the old hard-coded numbers.

## Test Plan

- Campaign Delivery tests pass.
- Frontend build passes.
- `rg` scan confirms personal preset numbers are not duplicated in frontend source or built assets.
- Manual browser check confirms campaign create/detail screens still show configured preset recipients.

## Done Criteria

- [ ] Campaign Delivery presets have one server-owned source of truth.
- [ ] Frontend no longer ships personal preset phone numbers as source constants.
- [ ] Backend and frontend cannot drift on preset ids.
- [ ] Tests cover configured preset resolution and malformed config behavior.

## STOP Conditions

- Operators need presets available before any authenticated API load and no safe bootstrap payload exists.
- Current deploy process has no acceptable server-owned config location for these recipients.
- Removing source defaults would leave active campaigns without their existing stored Delivery contacts.

## Maintenance Notes

Keep saved campaign Delivery contacts self-contained once selected, but keep available preset choices configurable. That lets historical campaigns preserve their routing while future campaigns use the current server-owned recipient list.
