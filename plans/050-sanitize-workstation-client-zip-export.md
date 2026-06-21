# Plan 050: Sanitize Workstation Client Zip Export

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/035-restrict-workstation-public-page-assets.md
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-06

## Why This Matters

Authenticated Workstation ZIP export recursively zips the whole client folder. That folder includes a nested git repo, generated prompts/metadata, profile/contact data, conversation text, media, and page artifacts. Plan 035 protects public page assets, but authenticated ZIP export still needs a deliberate allowlist.

## Current State

- ZIP builder zips every file except the zip itself:

```python
src/backend/endpoints/workstation.py:603
def build_client_zip(client: WorkstationClient) -> Path:
    """Refresh files and return a zip archive path for one client."""
```

```python
src/backend/endpoints/workstation.py:608
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(folder.rglob("*")):
```

- Client folder can contain a nested git repo:

```python
src/backend/endpoints/workstation.py:1607
def ensure_client_git_project(client: WorkstationClient) -> None:
```

- Profile and conversation files include lead/contact details:

```python
src/backend/endpoints/workstation.py:552
profile = {
```

- README exposes the ZIP endpoint:

```text
README.md:1576
El ZIP se descarga desde:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Workstation zip tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "zip or workstation_notes_media" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Replace recursive zip-all behavior with an explicit export allowlist.
- Exclude `.git`, internal metadata, prompt artifacts, progress logs, and private profile fields by default.
- Add tests for excluded and included files.
- Update README to define ZIP contents.

**Out of scope**:
- Changing public `/p/{token}` serving.
- Deleting files from client folders.
- Building a role-based export UI.
- Exporting secrets or Codex auth state.

## Git Workflow

- Branch: `codex/sanitize-workstation-client-zip`
- Commit message: `Sanitize Workstation client zip export`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define export contents

Choose a small default allowlist:

- current `index.html`, `styles.css`, `script.js`, and `assets/` for current public page,
- selected media assets intended for client handoff,
- `notes.txt` only if operator-facing export still requires it,
- a redacted `profile.json` if needed.

Exclude by default:

- `.git/`,
- `metadata.json`,
- `preview-message.txt`,
- `outbound-messages.json`,
- raw `conversation.txt`,
- progress logs,
- Codex prompt/context files,
- generated zip files.

### Step 2: Implement an export manifest helper

Create a helper that returns `(source_path, archive_name)` pairs. Keep it easy to review and test.

Do not rely on `folder.rglob("*")` without filters.

### Step 3: Add tests

Construct a client folder with:

- allowed page files,
- `.git/config`,
- `metadata.json`,
- `conversation.txt`,
- generated zip file,
- media asset.

Assert the ZIP includes only allowlisted files and never includes `.git` or metadata.

### Step 4: Update README

Document ZIP export contents and note that internal generation metadata stays server-side.

## Test Plan

- Run targeted Workstation zip tests.
- Run backend import smoke.
- Manually inspect one generated ZIP from a local test client.

## Done Criteria

- [ ] ZIP export uses an explicit allowlist.
- [ ] `.git/` and generation metadata are excluded.
- [ ] Tests cover included and excluded files.
- [ ] README describes the export contract.

## STOP Conditions

- Operators currently depend on ZIP including full conversation or metadata.
- A client handoff legally requires raw artifacts that the plan would exclude.
- The export allowlist cannot identify the current page version reliably.

## Maintenance Notes

Authenticated does not mean everything in the working folder is safe to export. Keep the ZIP contract explicit.
