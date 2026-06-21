# Plan 046: Require Data Root For Outbound WhatsApp Media

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/ai/codex_agent_tools.py src/bot/utils.py src/bot/providers.py src/bot/tests/test_client_lead_delivery.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DATA-02

## Why This Matters

Backend media-serving helpers constrain paths to known data/media roots, but the bot send path resolves outbound media from any existing absolute, cwd-relative, or parent-cwd file. A bad stored `media_path` from an agent tool, data edit, or future endpoint could make the bot send an unintended local file.

## Current State

- Message rows store raw media paths:

```python
src/backend/database.py:1970
media_type: str | None = None,
media_path: str | None = None,
```

- Agent tools can queue media paths:

```python
src/backend/ai/codex_agent_tools.py:2423
def send_whatsapp_media(arguments: dict[str, Any]) -> dict[str, Any]:
```

- Bot dispatch passes stored path to provider:

```python
src/bot/utils.py:1162
return await whatsapp_provider.send_video(
    to=to_phone,
    video_path=item.media_path or "",
```

- Provider resolves broad local candidates:

```python
src/bot/providers.py:1748
def _resolve_local_media_path(self, media_path: str) -> Path:
    """Resolve a repo/data media path from Docker or local bot cwd."""
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Bot delivery tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_client_lead_delivery.py -q` | exit 0 |
| Backend Contadores tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k media -q` | exit 0 |
| Bot import smoke | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run python -c "import main; print('bot-import-ok')"` | prints `bot-import-ok` |

## Scope

**In scope**:
- Constrain bot outbound media resolution to `DATA_DIR` and explicitly allowed bundled media roots.
- Validate queued media paths before dispatch.
- Add tests for absolute path rejection and valid `data/...` media.

**Out of scope**:
- Changing inbound media persistence.
- Changing public media serving.
- Migrating existing media files unless a small compatibility shim is needed.

## Git Workflow

- Branch: `codex/require-data-root-outbound-media`
- Commit message: `Require data-root outbound WhatsApp media`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define allowed outbound media roots

Use the same root idea as backend media helpers:

- shared `DATA_DIR`,
- versioned safe media templates if the repo intentionally sends them,
- no arbitrary absolute paths,
- no cwd-parent fallback.

If templates under `media/templates/` are allowed, make that explicit and read-only.

### Step 2: Update bot path resolution

Change `_resolve_local_media_path()` so it:

- strips and rejects empty paths,
- normalizes `data/...` under `DATA_DIR`,
- resolves paths and checks `relative_to(allowed_root)`,
- rejects absolute paths outside allowed roots,
- returns the resolved file only after root validation.

Raise a clear runtime error without printing sensitive absolute paths.

### Step 3: Add backend-side validation where media is queued

For agent/tool and manual enqueue paths, reject unsafe media paths before storing them when possible. Keep checks centralized so backend and bot do not drift.

### Step 4: Add tests

Cover:

- valid `data/contadores/outbound_media/...` sends,
- valid allowed template media sends if supported,
- `/etc/passwd` style absolute paths are rejected,
- `../` traversal paths are rejected,
- cwd-relative files outside data are rejected.

## Test Plan

- Run bot delivery tests.
- Run targeted backend media tests.
- Run bot import smoke.

## Done Criteria

- [ ] Bot outbound media resolution is root-constrained.
- [ ] Unsafe stored media paths fail before provider upload.
- [ ] Valid data-root media still dispatches.
- [ ] Tests cover absolute path, traversal, and valid paths.

## STOP Conditions

- Existing production rows contain media paths outside `data/` or approved templates.
- Operator wants to allow arbitrary local file sends from trusted tooling.
- PyWA upload API requires a path form incompatible with resolved data-root paths.

## Maintenance Notes

The bot is the last safety boundary before sending media externally. Keep it stricter than UI assumptions.
