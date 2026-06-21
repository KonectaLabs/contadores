# Plan 024: Wire CI And Test Dependencies

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- pyproject.toml uv.lock src/bot/pyproject.toml src/bot/uv.lock src/frontend/package.json src/frontend/package-lock.json .github`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

Every implementation plan tells executors to run pytest and frontend build commands, but the project metadata does not currently declare pytest as a dev dependency and there is no GitHub workflow. That makes verification depend on whatever happens to be installed locally.

## Current State

- Root dev dependencies only include deptry:

```toml
pyproject.toml:55
[dependency-groups]
dev = [
    "deptry>=0.24.0",
]
```

- Bot dev dependencies also only include deptry:

```toml
src/bot/pyproject.toml:31
[dependency-groups]
dev = [
    "deptry>=0.24.0",
]
```

- No `.github` directory exists:

```text
find .github -maxdepth 3 -type f
find: .github: No such file or directory
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Update root lock | `uv lock` | lockfile updated cleanly |
| Update bot lock | `cd src/bot && uv lock` | bot lockfile updated cleanly |
| Backend tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -q` | exit 0 |
| Bot tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -q` | exit 0 |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Add explicit test dev dependencies.
- Add a minimal CI workflow for backend tests, bot tests, and frontend build.
- Reuse the canonical local verify command if plan 022 has landed; otherwise wire the explicit commands directly.

**Out of scope**:
- Production deploy from CI.
- Secrets, live Meta/WhatsApp tests, or server SSH from CI.
- Large lint/typecheck policy beyond existing build/tests.

## Git Workflow

- Branch: `codex/wire-ci-test-deps`
- Commit message: `Wire CI and test dependencies`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add explicit dev dependencies

Add `pytest` to the root and bot dev dependency groups.

If tests use additional plugins, add only the plugins actually needed by the current suite.

Run `uv lock` in root and `src/bot`.

### Step 2: Add the minimal workflow

Create `.github/workflows/verify.yml` with jobs for:

- backend tests on Python 3.13 with uv,
- bot tests on Python 3.13 with uv,
- frontend build on Node 22.

Keep the workflow small. Cache only if it is straightforward.

### Step 3: Preserve live-write safety

Set env in CI so tests cannot accidentally hit live providers:

- `AUTH_DISABLE=true` where needed,
- no real Meta/WhatsApp/OpenAI secrets,
- any existing test env toggles that force dry-run behavior.

### Step 4: Run the same commands locally

Run the backend tests, bot tests, and frontend build locally before closing.

## Test Plan

- Root backend test command exits 0.
- Bot test command exits 0.
- Frontend build exits 0.
- CI workflow syntax is valid YAML.

## Done Criteria

- [ ] Root and bot dev dependency groups include test dependencies.
- [ ] Lockfiles are updated consistently.
- [ ] `.github/workflows/verify.yml` runs backend, bot, and frontend checks.
- [ ] No live provider secrets or write operations are required in CI.
- [ ] Local verification commands exit 0.

## STOP Conditions

- Existing tests require local services or credentials not suitable for CI.
- Adding pytest exposes broad failures unrelated to the dependency/CI wiring; report them instead of weakening the workflow.

## Maintenance Notes

This plan encodes the verification baseline. It does not replace the repo rule that product changes must be deployed and verified on the real server when the user asks for shipped work.
