# Plan 127: Make Draft Creative Uploads Visible And Reversible

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/backend/endpoints/platform.py src/backend/database.py src/backend/tests/test_contadores.py src/backend/tests/test_campaigns.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/049-delete-orphaned-campaign-creative-files.md
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: FRONTEND-18

## Why This Matters

Campaign creative uploads in the create draft immediately persist files through the backend. Removing an uploaded asset from the draft only detaches local UI state, and canceling campaign creation does not undo the upload.

Draft upload side effects need to be explicit and reversible.

## Current State

- Uploading creative calls the backend immediately:

```tsx
src/frontend/src/App.tsx:3554
async function uploadCampaignCreativeFile(file: File) {
```

- Drag/drop and paste trigger upload:

```tsx
src/frontend/src/App.tsx:3633
void uploadCampaignCreativeFiles(files);
```

```tsx
src/frontend/src/App.tsx:3654
void uploadCampaignCreativeFiles(pastedFiles);
```

- Plan 049 explicitly leaves upload semantics out of scope.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Creative upload scan | `rg -n "uploadCampaignCreativeFile|removeCampaignCreativeAsset|creativeAssets|creative-assets" src/frontend/src/App.tsx src/backend/endpoints/platform.py src/backend/tests` | draft upload side effects and cleanup path are visible |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Backend creative tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_campaigns.py src/backend/tests/test_contadores.py -k "creative or campaign" -q` | exit 0 |

## Scope

**In scope**:
- Make the UI indicate that creative upload stores a draft asset.
- Add a delete/discard path for draft creative assets, or mark them as temporary for cleanup.
- Ensure canceling campaign creation handles uploaded draft assets deliberately.
- Add backend cleanup endpoint/state only if needed.

**Out of scope**:
- Orphan cleanup for existing campaign assets; plan 049 covers retention/cleanup.
- Upload MIME safety; plan 112 covers media serving safety.
- Full media library redesign.

## Git Workflow

- Branch: `codex/reversible-draft-creative-uploads`
- Commit message: `Make draft creative uploads reversible`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose side-effect model

Pick temporary draft assets promoted on campaign create, explicit delete on remove/cancel, or a visible uploaded asset library with delete action.

### Step 2: Update UI labels and actions

Make uploaded state visible. Removing an asset should either delete/discard the persisted asset or explicitly say it only detaches it.

### Step 3: Add cleanup behavior

If adding deletion, ensure only draft/unattached assets can be deleted from this flow.

### Step 4: Add tests or manual verification

Cover upload/remove/cancel behavior and ensure no campaign keeps a deleted asset reference.

## Test Plan

- Frontend build passes.
- Backend creative/campaign tests pass if backend changes.
- Manual create-cancel flow does not leave unexplained uploaded draft assets.

## Done Criteria

- [ ] Draft creative upload side effects are visible.
- [ ] Operators can reverse/discard draft uploads.
- [ ] Canceling campaign creation has deliberate asset behavior.
- [ ] Cleanup cannot delete assets already attached to saved campaigns.

## STOP Conditions

- Platform creative asset model cannot distinguish draft/unattached assets.
- Current campaigns depend on sharing one uploaded creative asset across drafts.
- Deleting files requires a data-retention policy decision outside this plan.

## Maintenance Notes

Any create flow that persists files before final save needs an explicit draft asset lifecycle.
