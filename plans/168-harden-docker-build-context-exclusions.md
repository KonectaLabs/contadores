# Plan 168: Harden Docker Build Context Exclusions

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- .dockerignore .gitignore docker-compose.yml Dockerfile src/bot/Dockerfile README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: HIGH
- **Depends on**: none
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DEPLOY-07

## Why This Matters

Both production images build with repository root as the Docker context. The repo's runtime state and secrets live in ignored local files such as `data/`, `auth.toml`, Google credential JSON files, and token pickles. `.dockerignore` currently excludes `.env` and some generated folders, but it does not mirror the credential and runtime-state exclusions from `.gitignore`.

Dockerfiles do not copy most of those paths today, but Docker still receives the build context before evaluating `COPY` instructions. On the real server that can send CRM data, auth config, and provider credentials into the Docker builder boundary unnecessarily.

## Current State

- Backend and bot builds use repository root as build context:

```yaml
docker-compose.yml:22
backend:
docker-compose.yml:23
  build: .
docker-compose.yml:49
bot:
docker-compose.yml:50
  build:
docker-compose.yml:51
    context: .
```

- Runtime state and auth files are mounted at runtime:

```yaml
docker-compose.yml:45
  - ./data:/app/data
docker-compose.yml:46
  - ./auth.toml:/app/auth.toml:ro
docker-compose.yml:60
  - ./data:/app/data
```

- `.gitignore` excludes local runtime state and credential files:

```gitignore
.gitignore:9
auth.toml
.gitignore:39
data/
.gitignore:48
client_secret*.json
.gitignore:49
credentials*.json
.gitignore:50
token*.json
.gitignore:51
*.pickle
.gitignore:52
service-account*.json
```

- `.dockerignore` does not exclude those same classes:

```gitignore
.dockerignore:21
.env
.dockerignore:22
.env.*
.dockerignore:23
!.env.example
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Ignore parity scan | `git check-ignore -v data/funnels.json auth.toml client_secret-demo.json credentials-demo.json token-demo.json service-account-demo.json session.pickle .env` | every path is ignored by `.dockerignore` or `.gitignore` as intended |
| Docker context rules scan | `sed -n '1,120p' .dockerignore` | excludes `data/`, `auth.toml`, local credential JSON/token files, cache/output folders, and keeps required allowlisted files |
| Compose build config | `docker compose config --quiet` | exit 0 |
| Backend image build | `docker compose build backend` | exit 0 |
| Bot image build | `docker compose build bot` | exit 0 |

## Scope

**In scope**:
- Add `.dockerignore` exclusions for `data/`, `auth.toml`, credential JSON/token files, pickles, test/browser output, and local-only files already excluded from git.
- Preserve existing allowlists for `.codex/skills` and `media/templates`.
- Document the Docker context rule in README near the deploy/runtime section.
- Verify backend and bot images still build.

**Out of scope**:
- Changing runtime volume mounts.
- Moving production data or credentials.
- Reworking Dockerfile `COPY` structure beyond what is required for ignore rules.
- Pruning existing runtime artifacts; plans 047, 048, 096, and 140 own retention and backup behavior.

## Git Workflow

- Branch: `codex/harden-docker-build-context-exclusions`
- Commit message: `Harden Docker build context exclusions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Mirror runtime and credential exclusions

Update `.dockerignore` so Docker never receives local runtime state or secrets:

- `data/`
- `auth.toml`
- `client_secret*.json`
- `credentials*.json`
- `token*.json`
- `service-account*.json`
- `*.pickle`
- local report/test/browser output folders if missing.

Keep `.env.example` allowed, and keep `.codex/skills/**` and `media/templates/**` allowed because Dockerfile copies them intentionally.

### Step 2: Document the contract

In README's Docker/deploy/runtime section, state:

- Docker build context must not include `data/`, `auth.toml`, or credentials.
- Runtime state enters containers only through documented volume mounts and environment files.
- Any new local state folder must be added to both `.gitignore` and `.dockerignore`.

### Step 3: Verify builds and context rules

Run the commands above. If image build is too slow locally, at minimum run `docker compose config --quiet` and `git check-ignore -v ...`, then mark build verification as pending before rollout.

## Test Plan

- `.dockerignore` contains the same local runtime and credential classes as `.gitignore`.
- `git check-ignore -v` proves representative sensitive paths are ignored.
- `docker compose config --quiet` passes.
- Backend and bot image builds still pass.

## Done Criteria

- [ ] Docker build context excludes `data/`, `auth.toml`, credential JSON/token files, and pickles.
- [ ] Required build inputs remain available.
- [ ] README documents the build-context boundary.
- [ ] Backend and bot builds pass or are explicitly deferred with a reason.

## STOP Conditions

- Dockerfile currently depends on copying a path that would become ignored.
- The server build process uses a different context than `docker-compose.yml`.
- Production requires a local credential file inside the image instead of a runtime secret or volume.

## Maintenance Notes

Treat `.dockerignore` as a deploy security boundary, not just a build-speed optimization. Every new local state path should be reviewed against `.gitignore`, `.dockerignore`, and runtime volume mounts together.
