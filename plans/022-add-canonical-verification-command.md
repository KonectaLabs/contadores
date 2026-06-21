# Plan 022: Add A Canonical Verification Command

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- README.md pyproject.toml src/frontend/package.json .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The repo is server-first and deploys from `main`, but verification is currently described as scattered commands across README sections and individual plans. A single local command reduces rollout variance and makes future executors less likely to skip backend or frontend checks.

## Current State

- README documents backend and frontend commands separately:

```bash
README.md:641
PYTHONPATH=src uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000

README.md:655
cd src/frontend
npm run build
```

- Rollout docs say a product change is not done until server deploy and verification:

```text
README.md:1613
ALWAYS_DEPLOY: un cambio de producto no esta terminado por compilar local,
pasar tests o estar pusheado.
```

- There is no `Makefile`, `justfile`, or task file in the repo root.

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| New verify command | `./scripts/verify_local.sh` or chosen equivalent | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |

## Scope

**In scope**:
- Add one canonical local verification command.
- Document when to use it.
- Update rollout skills if docs change.

**Out of scope**:
- CI provider setup.
- Production deploy automation changes.
- Running live server checks from the local verify command.

## Git Workflow

- Branch: `codex/canonical-local-verify`
- Commit message: `Add canonical local verification command`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose command shape

Pick one:

- `scripts/verify_local.sh`
- `make verify`
- `uv run python src/tools/verify_local.py`

Prefer the simplest shape already natural for the repo. If adding `scripts/`, keep it organized and include only this real script.

### Step 2: Include the minimum useful gates

The command should run:

- backend import smoke,
- focused or full backend tests depending on runtime cost,
- frontend build,
- optional `deptry` only if already reliable in this repo.

Until plan 024 lands, use `uv run --with pytest pytest ...` or another self-contained pytest invocation for test steps. After plan 024 lands, prefer the normal dev dependency path.

Do not include deploy or live server checks.

### Step 3: Document the command

Update:

- `README.md`,
- `.codex/skills/contadores-rollout/SKILL.md`,
- `wiki/skills/contadores-rollout/SKILL.md`.

Make it clear this is pre-deploy local verification, not the final server verification required by AGENTS.

### Step 4: Run the command

Run the new command from a clean shell and record the exact output summary in the commit message or PR notes.

## Test Plan

- New verify command exits 0.
- Frontend build exits 0 through the command.
- Backend smoke exits 0 through the command.

## Done Criteria

- [ ] One documented command exists for local pre-deploy verification.
- [ ] The command is executable and exits 0 locally.
- [ ] README and rollout skills agree on the command.
- [ ] Docs still distinguish local verification from real server verification.

## STOP Conditions

- Full backend tests are too slow or flaky for a default verify command; use a documented smoke plus focused tests instead.
- Adding a script would create a new unmaintained task surface; choose Makefile or docs-only if that better fits the repo.

## Maintenance Notes

Keep this boring. The goal is repeatability, not a custom build system.
