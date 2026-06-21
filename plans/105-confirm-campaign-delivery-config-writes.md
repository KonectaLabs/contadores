# Plan 105: Confirm Campaign Delivery Config Writes

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css src/backend/endpoints/campaigns.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/066-lock-delivery-source-identity-on-edit.md
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DELIVERY-02

## Why This Matters

Campaign detail Delivery controls can immediately change live recipient routing for public campaign submissions. Toggling Delivery, removing a contact, adding a preset contact, adding a custom contact, or refreshing the campaign Delivery source all mutate backend state. When the campaign is active, the backend can create/update enabled `ClientLeadSource` rows that route future lead alerts.

Wrong-recipient Delivery routing is a production-impacting mistake. These controls need confirmation or a staged review step.

## Current State

- The frontend PATCHes campaign `delivery_config` directly:

```tsx
src/frontend/src/App.tsx:3839
async function updateCampaignDeliveryConfig(campaign: LeadCaptureCampaignItem, nextConfig: CampaignDeliveryConfig) {
```

```tsx
src/frontend/src/App.tsx:3846
body: JSON.stringify({ delivery_config: campaignDeliveryConfigPayload(nextConfig) }),
```

- The active campaign Delivery toggle writes immediately:

```tsx
src/frontend/src/App.tsx:5171
<input
```

```tsx
src/frontend/src/App.tsx:5175
onChange={(event) => void updateCampaignDeliveryConfig(selectedCampaign, { ...selectedCampaignDelivery, enabled: event.target.checked })}
```

- Contact removal writes immediately:

```tsx
src/frontend/src/App.tsx:5200
onClick={() => removeCampaignDeliveryContact(selectedCampaign, contact.id)}
```

- Preset/custom contact additions write immediately:

```tsx
src/frontend/src/App.tsx:5215
<button type="button" key={contact.id} disabled={saving} onClick={() => addCampaignDeliveryPresetContact(selectedCampaign, contact)}>
```

```tsx
src/frontend/src/App.tsx:5231
<button type="button" className="ct-btn ct-btn-ghost" disabled={saving} onClick={() => addDetailDeliveryCustomContact(selectedCampaign)}>
```

- Refreshing the campaign Delivery source is a one-click POST:

```tsx
src/frontend/src/App.tsx:4156
async function refreshDeliverySource(campaign: LeadCaptureCampaignItem) {
```

```tsx
src/frontend/src/App.tsx:4159
await apiFetch(`/api/campaigns/${encodeURIComponent(campaign.id)}/delivery-source`, { method: "POST" });
```

- Backend creates/updates Delivery sources and enables them for active/published campaigns:

```python
src/backend/endpoints/campaigns.py:1318
def ensure_campaign_delivery_sources(campaign: LeadCaptureCampaign) -> list[ClientLeadSource]:
```

```python
src/backend/endpoints/campaigns.py:1340
enabled=campaign.status in {"active", "published"},
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Campaign Delivery scan | `rg -n "updateCampaignDeliveryConfig|refreshDeliverySource|delivery_config|campaign-delivery" src/frontend/src/App.tsx src/frontend/src/styles.css src/backend/endpoints/campaigns.py` | live Delivery config writes require confirmation or staged apply |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Campaign Delivery tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py -k "delivery_config or delivery_source" -q` | exit 0 |

## Scope

**In scope**:
- Add confirmation for campaign Delivery enable/disable.
- Add confirmation for removing recipients and adding new recipients.
- Add confirmation for Delivery source refresh when the campaign is active or published.
- Make the confirmation show the campaign name and affected recipient(s).
- Preserve existing backend endpoint contracts.

**Out of scope**:
- Delivery source edit identity; plan 066 covers source identity safety.
- Meta form routing uniqueness; plans 084 and 102 cover Meta source fields.
- Campaign status confirmation; plan 008 covers activate/pause/archive.
- Full Delivery source editor redesign.

## Git Workflow

- Branch: `codex/confirm-campaign-delivery-config`
- Commit message: `Confirm campaign Delivery config writes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Identify mutation paths

Cover every UI path that calls:

- `updateCampaignDeliveryConfig`,
- `refreshDeliverySource`,
- helper functions that call the update function.

### Step 2: Add a focused confirmation state

Use the app's existing confirmation pattern if one exists. Otherwise add a compact modal/panel state that records:

- action type,
- campaign id/name,
- current recipients,
- next recipients or enabled state.

### Step 3: Confirm high-risk writes

Require confirmation before:

- toggling Delivery on/off,
- removing a contact,
- adding a preset/custom contact,
- refreshing campaign Delivery source while active/published.

Avoid confirmation for pure UI panel open/close or draft typing.

### Step 4: Keep errors visible

Existing backend errors should still surface through `onError`. Do not swallow backend validation errors.

### Step 5: Verify

Run frontend build and focused campaign tests. If plan 021 has landed, add a frontend regression for one confirmation path.

## Test Plan

- Frontend build/typecheck.
- Focused backend campaign Delivery tests.
- Manual browser check that Delivery config writes only happen after confirm.

## Done Criteria

- [ ] Campaign Delivery recipient/config writes are no longer one-click live writes.
- [ ] Confirmation copy identifies the affected campaign and recipient/routing impact.
- [ ] Refreshing an active campaign Delivery source requires confirmation.
- [ ] Backend Delivery source behavior remains unchanged.

## STOP Conditions

- Operators explicitly require one-click campaign Delivery edits during live support.
- Existing UI lacks any shared confirmation pattern and adding one would become a broad design task.
- Backend starts returning a staged diff/preview that changes the frontend flow.

## Maintenance Notes

Campaign Delivery routing is a production recipient contract. Make the final write intentional.
