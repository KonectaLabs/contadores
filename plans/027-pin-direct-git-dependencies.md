# Plan 027: Pin Direct Git Dependencies

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- pyproject.toml uv.lock Dockerfile README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: reproducibility
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Docker build runs `uv sync --frozen`, and `uv.lock` currently pins the Codex SDK to a commit. But `pyproject.toml` still declares a moving Git dependency. The next lock regeneration can silently move the dependency, changing the app-server SDK surface in production.

## Current State

- Interface dependency is floating:

```toml
pyproject.toml:17
"openai-codex-app-server-sdk @ git+https://github.com/openai/codex.git#subdirectory=sdk/python",
```

- Lockfile currently resolves a concrete commit:

```toml
uv.lock:1891
source = { git = "https://github.com/openai/codex.git?subdirectory=sdk%2Fpython#5e6cbbadf79671b7ff8e592ca4aad05f8d22a499" }
```

- Docker installs from the frozen lock:

```dockerfile
Dockerfile:21
RUN uv sync --frozen --no-dev
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Lock update | `uv lock` | lockfile remains consistent |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |
| Agent API tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_api.py -q` | exit 0 |

## Scope

**In scope**:
- Pin the direct Git reference in `pyproject.toml` to the commit already in `uv.lock`, or to a deliberate newer commit.
- Document the upgrade path.
- Verify lock consistency.

**Out of scope**:
- Upgrading Codex SDK behavior.
- Changing Docker's global `@openai/codex` npm version.
- Replacing the SDK dependency with a package registry release unless one is intentionally selected.

## Git Workflow

- Branch: `codex/pin-direct-git-dependency`
- Commit message: `Pin direct Codex SDK dependency`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Pin the Git URL

Update `pyproject.toml` to include the locked commit:

```toml
"openai-codex-app-server-sdk @ git+https://github.com/openai/codex.git@5e6cbbadf79671b7ff8e592ca4aad05f8d22a499#subdirectory=sdk/python",
```

Use the exact syntax accepted by uv. If uv normalizes it differently, accept the uv-supported form.

### Step 2: Regenerate or verify the lock

Run `uv lock`.

Confirm `uv.lock` still points at the same commit unless deliberately upgraded.

### Step 3: Document upgrade procedure

Add a short note to README or rollout skill:

- direct Git SDK deps must include a commit,
- upgrade by editing `pyproject.toml`, running `uv lock`, running agent/API tests and backend smoke.

### Step 4: Verify

Run backend import smoke and `test_agent_api.py`.

## Test Plan

- `uv lock` exits 0.
- Agent API tests exit 0.
- Backend import smoke exits 0.

## Done Criteria

- [ ] `pyproject.toml` direct Git dependency includes a commit pin.
- [ ] `uv.lock` is consistent with the pin.
- [ ] Upgrade path is documented.
- [ ] Agent API tests exit 0.

## STOP Conditions

- uv does not accept a pinned subdirectory Git reference in `pyproject.toml`.
- The pinned commit is known broken and needs a deliberate upgrade decision.

## Maintenance Notes

This keeps reproducibility explicit at the dependency interface, not just in the lockfile.
