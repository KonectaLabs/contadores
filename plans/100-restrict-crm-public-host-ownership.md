# Plan 100: Restrict CRM Public Host Ownership

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/main.py traefik/dynamic.yml .env.example README.md plans/044-align-traefik-websecure-routing-for-crm.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DEPLOY-06

## Why This Matters

The active Contadores docs consistently present `crm.fgoiriz.com` as the public CRM origin. The backend HTTPS-force default and Traefik CRM routers also include `chatterface.fgoiriz.com`. If that host belongs to another project or legacy service, the Contadores backend can answer for an unrelated domain and plan 044 can accidentally make that broader routing permanent on HTTPS too.

Public host ownership should be explicit before changing Traefik routing.

## Current State

- The backend default HTTPS host list includes both CRM and Chatterface:

```python
src/backend/main.py:83
PUBLIC_HTTPS_HOSTS = {
```

```python
src/backend/main.py:85
for host in os.getenv("PUBLIC_HTTPS_HOSTS", "crm.fgoiriz.com,chatterface.fgoiriz.com").split(",")
```

- The middleware applies redirect/HSTS behavior for every host in that list:

```python
src/backend/main.py:256
if public_request_host(request) in PUBLIC_HTTPS_HOSTS:
```

- Traefik routes both hosts to the Contadores backend:

```yaml
traefik/dynamic.yml:23
rule: "(Host(`crm.fgoiriz.com`) || Host(`chatterface.fgoiriz.com`)) && PathPrefix(`/`)"
```

- Traefik routes both hosts' webhook paths to the Contadores bot:

```yaml
traefik/dynamic.yml:29
rule: "(Host(`crm.fgoiriz.com`) || Host(`chatterface.fgoiriz.com`)) && PathPrefix(`/webhook`)"
```

- `.env.example` documents both hosts for HTTPS forcing:

```text
.env.example:159
PUBLIC_HTTPS_HOSTS=crm.fgoiriz.com,chatterface.fgoiriz.com
```

- Workstation and review docs use only the CRM origin:

```markdown
README.md:1563
- `WORKSTATION_PUBLIC_PAGE_BASE_URL=https://crm.fgoiriz.com`
```

```markdown
README.md:1564
- `CONTADORES_REVIEW_BASE_URL=https://crm.fgoiriz.com`
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Host ownership scan | `rg -n "chatterface|crm\\.fgoiriz|PUBLIC_HTTPS_HOSTS|Host\\(" src/backend/main.py traefik/dynamic.yml .env.example README.md plans/044-align-traefik-websecure-routing-for-crm.md` | only approved CRM-owned hosts remain, or legacy hosts are explicitly documented |
| Compose config validation | `docker compose config` | exits 0 |
| CRM host smoke | `curl -fsS https://crm.fgoiriz.com/health` | exits 0 after deploy |
| Removed host smoke | command chosen after ownership decision | removed host no longer reaches Contadores, or intentionally still does |

## Scope

**In scope**:
- Decide whether `chatterface.fgoiriz.com` is an approved Contadores/Konecta public host.
- If it is not approved, remove it from backend defaults, `.env.example`, and Traefik CRM/bot router rules.
- If it is approved, document why it exists and where operators should verify it.
- Update plan 044 so HTTPS routing uses the approved host list.

**Out of scope**:
- DNS changes outside this repo.
- Cloudflare account changes.
- Adding new public domains.
- Changing public campaign or Workstation URL generation beyond host defaults.

## Git Workflow

- Branch: `codex/restrict-crm-public-hosts`
- Commit message: `Restrict CRM public host ownership`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Confirm ownership

Use repo evidence first. If there is no Contadores/Konecta documentation for `chatterface.fgoiriz.com`, treat it as unapproved unless the operator explicitly says it is still a CRM alias.

Do not infer ownership from the current Traefik rule alone.

### Step 2: Narrow backend host defaults

If the host is unapproved, change the backend default:

```python
os.getenv("PUBLIC_HTTPS_HOSTS", "crm.fgoiriz.com")
```

Keep the env var capable of accepting multiple hosts for future approved aliases.

### Step 3: Narrow Traefik routers

If the host is unapproved, remove it from backend and bot router rules in `traefik/dynamic.yml`.

Keep `/webhook` priority higher than `/`.

### Step 4: Align docs and plan 044

Update `.env.example`, README, and plan 044 so the HTTPS-routing plan does not preserve unapproved hosts.

If `chatterface.fgoiriz.com` remains approved, add a short explicit note explaining that it is a CRM alias, not a borrowed project route.

### Step 5: Verify routing intent

Run `docker compose config` locally.

After deploy, verify:

- `crm.fgoiriz.com` reaches the CRM,
- removed hosts do not route to Contadores, or approved aliases still route intentionally,
- `/webhook` still routes to the bot on approved hosts.

## Test Plan

- Compose config validation.
- Backend unit or smoke test for `PUBLIC_HTTPS_HOSTS` default if one exists or is easy to add.
- Server smoke after the deploy window.

## Done Criteria

- [ ] The repo has one explicit approved CRM host list.
- [ ] Backend HTTPS forcing and Traefik routing use the same approved list.
- [ ] Unapproved unrelated hosts no longer route to Contadores.
- [ ] Plan 044 no longer instructs executors to preserve unapproved hosts.

## STOP Conditions

- The operator confirms `chatterface.fgoiriz.com` is intentionally still a Contadores CRM alias.
- DNS or Cloudflare currently depends on the broad host rule and there is no approved replacement route.
- The server's dirty Traefik config differs from repo state and must be reconciled before changing host rules.

## Maintenance Notes

Host ownership is part of the product boundary. Keep aliases explicit and reviewed, especially before adding HTTPS routes.
