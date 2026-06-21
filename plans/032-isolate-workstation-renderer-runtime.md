# Plan 032: Isolate Workstation Renderer Runtime

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/workstation.py src/backend/tests/test_workstation.py src/backend/tests/test_contadores.py README.md Dockerfile`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: architecture
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Workstation preview rendering uses Playwright Chromium and ffmpeg inside the same endpoint module that owns public pages, queueing, client state, Codex runs, and automation. Rendering failures should be isolated and reported with explicit diagnostics, not hidden as generic Workstation failures.

## Current State

- Renderer lives in `src/backend/endpoints/workstation.py`, a 4705-line module:

```python
src/backend/endpoints/workstation.py:1655
def render_landing_page_video_sync(*, index_path: Path, output_path: Path) -> None:
```

- It imports Playwright at runtime and launches Chromium:

```python
src/backend/endpoints/workstation.py:1658
from playwright.sync_api import sync_playwright

src/backend/endpoints/workstation.py:1665
browser = playwright.chromium.launch(headless=True)
```

- It shells out to ffmpeg:

```python
src/backend/endpoints/workstation.py:1711
command = [
    "ffmpeg",
```

- README documents the renderer behavior:

```text
README.md:1545
El preview principal se renderiza como MP4.
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Workstation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_workstation.py -q` | exit 0 |
| Contadores Workstation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k workstation -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Extract rendering code into a small renderer module/service.
- Add dependency checks for Playwright browser availability and ffmpeg.
- Return structured render errors to Workstation state.
- Preserve generated output paths and media contracts.

**Out of scope**:
- Moving rendering to a separate container.
- Changing generated page content.
- Changing Codex generation prompts.
- Removing Playwright from Docker.

## Git Workflow

- Branch: `codex/isolate-workstation-renderer`
- Commit message: `Isolate Workstation renderer runtime`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extract renderer module

Create a focused module such as `src/backend/workstation_renderer.py`.

Move:

- `render_landing_page_video_sync`,
- dependency probing helpers,
- renderer-specific exception type.

Keep endpoint imports one-way: endpoints can import renderer, renderer should not import endpoint state.

### Step 2: Add structured errors

Define a small result or exception shape with:

- stage: `playwright_import`, `browser_launch`, `record_video`, `ffmpeg`,
- message,
- stderr/stdout when safe.

Do not include secrets or local absolute paths in user-facing errors unless needed for server logs.

### Step 3: Add dependency check helper

Add a helper that can be used in tests or server smoke:

```python
check_workstation_renderer_dependencies() -> dict[str, Any]
```

It should report Playwright import and ffmpeg availability without rendering a page.

### Step 4: Preserve output contract

Existing generated preview path and media queue behavior must not change.

Tests that monkeypatch `workstation_endpoints.render_landing_page_video_sync` may need to patch the new import location or a wrapper retained for compatibility.

## Test Plan

- Workstation unit tests.
- Contadores Workstation tests.
- Backend import smoke.
- Optional manual render smoke if Playwright/ffmpeg are installed locally.

## Done Criteria

- [ ] Renderer code no longer lives directly in the endpoint module.
- [ ] Missing Playwright/ffmpeg errors identify the failing stage.
- [ ] Existing Workstation preview output contract is unchanged.
- [ ] Workstation tests exit 0.

## STOP Conditions

- Extracting renderer creates circular imports with Workstation endpoint state.
- Tests rely on monkeypatch paths that would make the change brittle; keep a compatibility wrapper.

## Maintenance Notes

This plan isolates runtime risk. A later plan can decide whether the renderer should run in a separate worker/container.
