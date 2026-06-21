# Plan 035: Restrict Workstation Public Page Assets

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/tests/test_workstation.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PUBLIC-01

## Why This Matters

The public Workstation route serves any file under the generated page version directory. That directory also receives generation metadata. Anyone with a valid public trial URL can likely request files such as `metadata.json` and read internal generation context that should stay operator-only.

## Current State

- Workstation writes sensitive metadata beside public files:

```python
src/backend/endpoints/workstation.py:2668
metadata = {
    "created_at": datetime.now(timezone.utc).isoformat(),
    "operation": "revision" if revision else "draft",
    "client_id": client.id,
    "lead_id": lead.id,
    "codex_response": result.final_response,
    "source_messages": [message.id for message in replies],
    "operator_prompt": operator_prompt.strip(),
    "preview_path": relative_data_path(preview_path),
    "preview_message": preview_message,
}
```

- The public asset resolver only blocks traversal, not internal filenames:

```python
src/backend/endpoints/workstation.py:4166
def resolve_public_page_file(public_page: WorkstationPublicPage, asset_path: str | None) -> Path:
    """Resolve a public page asset without allowing directory traversal."""
    version_dir = resolve_public_page_version_dir(public_page)
    clean_path = (asset_path or "index.html").strip() or "index.html"
    candidate = (version_dir / Path(clean_path)).resolve()
```

- The route serves the resolved file inline:

```python
src/backend/endpoints/workstation.py:4195
@public_workstation_router.get("/p/{public_token}/{asset_path:path}")
async def serve_public_workstation_page_asset(public_token: str, asset_path: str) -> FileResponse:
    """Serve one static asset from the current public trial page version."""
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Workstation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_workstation.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/workstation.py`
- `src/backend/tests/test_workstation.py`
- README notes for public Workstation links if needed.

**Out of scope**:
- Changing public token generation.
- Changing generated page HTML/CSS/JS semantics beyond asset placement required by this fix.
- Changing authenticated Workstation download, preview, or metadata endpoints.
- Deleting existing metadata files.

## Git Workflow

- Branch: `codex/restrict-workstation-public-assets`
- Commit message: `Restrict Workstation public page assets`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add an explicit public asset allowlist

In `src/backend/endpoints/workstation.py`, add a small helper near `resolve_public_page_file()`.

Suggested behavior:

- allow root `index.html`,
- allow root `styles.css`,
- allow root `script.js`,
- allow files below `assets/`,
- reject dotfiles,
- reject `metadata.json`,
- reject `preview-message.txt`,
- reject `outbound-messages.json`,
- reject `preview.mp4` and other generated videos,
- reject any other root file by default.

Keep this as an allowlist, not a denylist. If a generated public page needs more public files, move those files under `assets/` or add a narrowly named safe root file after inspecting its contents.

### Step 2: Route all public file resolution through the allowlist

Update `resolve_public_page_file()` so traversal protection and allowlist validation both run before returning a `Path`.

Implementation shape:

- normalize the requested path,
- reject absolute paths,
- reject `..` path parts,
- reject paths with empty or hidden path parts except the root fallback,
- call the allowlist helper,
- only then resolve and check `candidate.relative_to(version_dir)`.

Keep the existing 404 behavior. Do not return 403 for blocked internal filenames, because that leaks which files exist.

### Step 3: Add tests for internal file blocking

Create or extend Workstation tests so a generated version directory includes:

- `index.html`,
- `styles.css`,
- `script.js`,
- `assets/logo.png`,
- `metadata.json`,
- `preview-message.txt`,
- `outbound-messages.json`,
- `preview.mp4`.

Assert:

- `/p/{token}/` serves HTML,
- `/p/{token}/styles.css` serves CSS,
- `/p/{token}/script.js` serves JS,
- `/p/{token}/assets/logo.png` serves the asset,
- `/p/{token}/metadata.json` returns 404,
- `/p/{token}/preview-message.txt` returns 404,
- `/p/{token}/outbound-messages.json` returns 404,
- `/p/{token}/preview.mp4` returns 404,
- traversal attempts still return 404.

### Step 4: Document the public file contract

If README already explains public Workstation links, add one short sentence: public `/p/{token}` routes serve only page assets, while metadata and previews stay operator-only.

## Test Plan

- Run the Workstation test command.
- Run the backend import smoke.
- Manually inspect the new helper and confirm it is an allowlist.

## Done Criteria

- [ ] Public Workstation routes cannot serve `metadata.json`.
- [ ] Public Workstation routes cannot serve preview or outbound-message files.
- [ ] Required page assets still load.
- [ ] Tests cover allowed assets, blocked internal files, and traversal attempts.

## STOP Conditions

- Generated pages currently reference required root files other than `index.html`, `styles.css`, or `script.js`.
- The fix requires changing Codex generation prompts broadly.
- Tests reveal an existing production public page would become blank without a separate migration plan.

## Maintenance Notes

Treat the public page directory as mixed-sensitivity. New internal artifacts should never become public just because they are written beside `index.html`.
