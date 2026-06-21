# Plan 044: Align Traefik Websecure Routing For CRM

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- docker-compose.yml traefik/dynamic.yml README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: plans/041-harden-remote-deploy-required-services.md, plans/100-restrict-crm-public-host-ownership.md
- **Category**: deploy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: DEPLOY-05

## Why This Matters

Traefik exposes port 443, but the CRM and bot webhook routers are only bound to the `web` entrypoint. Direct origin HTTPS for `crm.fgoiriz.com` returned Traefik `404` during planning. If Cloudflare or webhook providers reach origin 443, CRM and `/webhook` are unrouted even when containers are healthy.

## Current State

- Compose exposes both HTTP and HTTPS:

```yaml
docker-compose.yml:12
- "--entrypoints.web.address=:80"
docker-compose.yml:13
- "--entrypoints.websecure.address=:443"
docker-compose.yml:16
- "443:443"
```

- Only `codex-approval` has a `websecure` router:

```yaml
traefik/dynamic.yml:15
codex-approval-secure:
  rule: "Host(`codex-approval.fgoiriz.com`)"
  entryPoints:
    - websecure
  tls: {}
```

- CRM and bot routers use only `web`:

```yaml
traefik/dynamic.yml:22
backend:
  rule: "(Host(`crm.fgoiriz.com`) || Host(`chatterface.fgoiriz.com`)) && PathPrefix(`/`)"
  entryPoints:
    - web
```

```yaml
traefik/dynamic.yml:28
bot:
  rule: "(Host(`crm.fgoiriz.com`) || Host(`chatterface.fgoiriz.com`)) && PathPrefix(`/webhook`)"
  entryPoints:
    - web
```

- Direct origin HTTPS check during planning:

```text
curl -k -I --resolve crm.fgoiriz.com:443:149.50.136.121 https://crm.fgoiriz.com/health
HTTP/2 404
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Compose config validation | `docker compose config` | exits 0 |
| Direct origin HTTPS health | `curl -k -fsS --resolve crm.fgoiriz.com:443:149.50.136.121 https://crm.fgoiriz.com/health` | exits 0 after backend is healthy |
| Direct origin HTTPS webhook path | `curl -k -I --resolve crm.fgoiriz.com:443:149.50.136.121 https://crm.fgoiriz.com/webhook/calendly` | reaches bot route, not Traefik 404 |

## Scope

**In scope**:
- Add `websecure` routing for CRM backend and bot webhook routers.
- Preserve router priority so `/webhook` reaches bot before backend.
- Use the approved CRM host list from plan 100.
- Decide whether to add HTTP-to-HTTPS redirect or leave Cloudflare responsible.
- Update deployment docs with origin HTTPS expectation.

**Out of scope**:
- Certificate management overhaul.
- Changing Cloudflare DNS or SSL mode.
- Changing app auth/cookie behavior.
- Changing webhook endpoint code.

## Git Workflow

- Branch: `codex/traefik-websecure-crm-routing`
- Commit message: `Align Traefik websecure routing for CRM`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add HTTPS routers for CRM and bot

Either add `websecure` to the existing backend/bot routers or add parallel secure routers.

Requirements:

- the approved CRM public hosts from plan 100 route to backend on `/`,
- `/webhook` routes to bot with higher priority,
- `tls: {}` is set on secure routers,
- HTTP behavior remains intentional and documented.

### Step 2: Preserve webhook priority

Confirm that HTTPS `/webhook/...` routes to the bot service, not backend.

Keep bot priority higher than backend priority for both HTTP and HTTPS.

### Step 3: Update server verification

Update docs so server verification includes direct-origin HTTPS when possible:

```bash
curl -k --resolve crm.fgoiriz.com:443:149.50.136.121 https://crm.fgoiriz.com/health
```

Do not require `-k` for normal public Cloudflare checks.

## Test Plan

- Run `docker compose config`.
- Deploy in a controlled window.
- Check direct origin HTTPS `/health`.
- Check Cloudflare/public HTTPS `/health`.
- Check `/webhook/...` routes to bot instead of Traefik 404.

## Done Criteria

- [ ] Origin HTTPS no longer returns Traefik 404 for CRM health.
- [ ] Origin HTTPS `/webhook` reaches the bot router.
- [ ] Router priorities are consistent between HTTP and HTTPS.
- [ ] README documents the expected HTTPS routing.

## STOP Conditions

- TLS termination is intentionally only handled by Cloudflare and origin 443 should not route CRM.
- Existing Traefik certificate behavior cannot serve the CRM host safely.
- Current dirty remote Traefik config differs from repo state and must be resolved first.

## Maintenance Notes

Treat this together with plan 042. Do not encode unreviewed server-only Traefik changes as the permanent fix.
