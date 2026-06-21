# Plan 156: Gate Cloudflare DNS And Zone Writes

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/cloudflare_registrar.py src/backend/tests/test_cloudflare_registrar.py README.md .env.example`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CLOUDFLARE-01

## Why This Matters

Cloudflare registrar/DNS automation can mutate real zones and DNS records. Domain registration has a dry-run and `--yes` path, but `create-zone`, `add-record`, and `upsert-record` execute immediately when credentials are configured.

DNS and zone writes should follow the same explicit live-write posture as other provider mutations: show the exact payload first, require confirmation, and verify the target zone/domain belongs to the intended client.

## Current State

- Registration has a dry-run path when `--yes` is absent:

```python
src/backend/cloudflare_registrar.py:450
if not yes:
    print_json(
        {
            "domain": normalize_domain(domain),
            "dry_run": True,
            "checked": domain_result,
            "next_step": "Rerun with --yes and --max-first-year-usd after approving this exact price.",
        }
    )
    return
```

- Zone creation writes immediately:

```python
src/backend/cloudflare_registrar.py:591
@app.command("create-zone")
def create_zone(
```

```python
src/backend/cloudflare_registrar.py:598
run_client_action(lambda client: print_json(client.create_zone(domain, zone_type=zone_type)))
```

- DNS record creation writes immediately:

```python
src/backend/cloudflare_registrar.py:601
@app.command("add-record")
```

```python
src/backend/cloudflare_registrar.py:622
client.create_dns_record(
```

- DNS record upsert writes immediately:

```python
src/backend/cloudflare_registrar.py:633
@app.command("upsert-record")
```

```python
src/backend/cloudflare_registrar.py:654
client.upsert_dns_record(
```

- README shows write commands without an approval flag:

```markdown
README.md:719
uv run python -m backend.cloudflare_registrar create-zone ejemplo-contable.com
```

```markdown
README.md:720
uv run python -m backend.cloudflare_registrar upsert-record --zone ejemplo-contable.com --type CNAME --name www --content contadores.fgoiriz.com --proxied
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Cloudflare write scan | `rg -n "create-zone|add-record|upsert-record|--yes|dry_run|create_zone|create_dns_record|upsert_dns_record" src/backend/cloudflare_registrar.py src/backend/tests/test_cloudflare_registrar.py README.md .env.example` | every Cloudflare write has a dry-run/confirm path |
| Cloudflare tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_cloudflare_registrar.py -q` | exit 0 |
| CLI help smoke | `PYTHONPATH=src uv run python -m backend.cloudflare_registrar --help >/dev/null` | exit 0 |

## Scope

**In scope**:
- Add dry-run output for `create-zone`, `add-record`, and `upsert-record`.
- Require `--yes` or another explicit confirmation flag for those writes.
- Print the exact normalized zone/record payload in dry-run mode.
- Add optional target allowlist or owner label check if current config has an approved-domain contract.
- Update README commands to show dry-run first and `--yes` for execution.
- Add tests proving write clients are not called without confirmation.

**Out of scope**:
- Domain registration price checks; existing registration flow already has a dry-run/price guard.
- Building a full DNS deployment system.
- Live Cloudflare API calls in tests.
- Changing Traefik routing; plans 044 and 100 own CRM host routing.

## Git Workflow

- Branch: `codex/gate-cloudflare-dns-zone-writes`
- Commit message: `Gate Cloudflare DNS and zone writes`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add confirmation flags

Add `yes: bool = typer.Option(False, help="Confirm the live Cloudflare write.")` to:

- `create-zone`,
- `add-record`,
- `upsert-record`.

Default to dry-run.

### Step 2: Build dry-run payloads

Before writing, normalize the zone name and DNS record payload exactly as the live command will send it.

When `--yes` is absent, print:

- `dry_run: true`,
- selected account id if safe,
- zone/domain,
- record payload,
- next command to run with `--yes`.

Do not print tokens or raw auth headers.

### Step 3: Require explicit target ownership

If `.env.example` or README already names an approved host/domain list, wire the command to that. Otherwise document the operator approval step and leave allowlist as a future extension rather than inventing a weak one.

### Step 4: Add tests

Use a fake client to assert:

- dry-run create-zone does not call `client.create_zone`,
- dry-run add/upsert do not call record writes,
- `--yes` performs the write with the normalized payload,
- invalid proxy flags still fail before dry-run output.

### Step 5: Update docs

README should show:

- dry-run command,
- review output,
- rerun with `--yes`,
- no live DNS mutation during verification.

## Test Plan

- Cloudflare registrar tests pass.
- CLI help smoke passes.
- Manual dry-run commands can be executed without credentials if code is structured to avoid loading config before printing local payload; if credentials remain required, document that dry-run still verifies against the configured account.

## Done Criteria

- [ ] Cloudflare zone and DNS record writes require explicit confirmation.
- [ ] Dry-run output shows the exact payload that would be sent.
- [ ] Tests prove dry-run does not call write methods.
- [ ] README no longer shows immediate DNS writes as the default path.

## STOP Conditions

- Operators intentionally need one-command emergency DNS writes and accept the risk.
- Dry-run requires a live account lookup that cannot be tested without credentials.
- Existing scripts call these commands non-interactively and cannot be updated in the same rollout.

## Maintenance Notes

Treat DNS writes like provider writes. Make the default path reviewable and boring.
