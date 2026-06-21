# Plan 122: Classify And Redact Config Readiness Payloads

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/runtime_settings.py src/backend/endpoints/agent.py src/backend/ai/codex_agent_tools.py src/backend/tests/test_agent_api.py src/backend/tests/test_contadores.py README.md wiki/agent-api-cli.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PRIVACY-01

## Why This Matters

Authenticated readiness/config payloads expose operational identifiers, local paths, alert emails, sheet metadata, Meta account ids, and Delivery recipient configuration. These are not raw secrets, but they still need a field-level sensitivity policy.

Auth boundaries are covered by plans 079 and 080. This plan defines what authenticated payloads should reveal.

## Current State

- Runtime settings expose sheet gid, alert emails, and local config path:

```python
src/backend/runtime_settings.py:147
"sheet_gid": self.sheet_gid or (first_ready_funnel.sheet_gid if first_ready_funnel else ""),
```

```python
src/backend/runtime_settings.py:151
"alert_emails": self.alert_emails,
```

- Meta readiness returns configured account/resource ids:

```python
src/backend/endpoints/agent.py:337
"ad_account_id": os.getenv("META_AD_ACCOUNT_ID", "").strip(),
```

- Agent config tools dump config paths and file-backed Delivery sources:

```python
src/backend/ai/codex_agent_tools.py:1050
"file_backed_delivery_sources": [entry.model_dump(mode="json") for entry in delivery_entries],
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Sensitive payload scan | `rg -n "sheet_gid|alert_emails|funnel_config_path|ad_account_id|business_id|whatsapp_phone_number|file_backed_delivery_sources|sheet_url|recipient_phone" src/backend src/backend/tests README.md wiki/agent-api-cli.md` | exposed fields are classified, redacted, or intentionally documented |
| Config payload tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_api.py src/backend/tests/test_contadores.py -k "runtime_endpoint or meta_readiness or read_platform_config" -q` | exit 0 |

## Scope

**In scope**:
- Define which config/readiness fields are UI-safe, operator-only, agent-only, or redacted.
- Redact or replace full identifiers with booleans, labels, or last-four summaries where full values are not needed.
- Keep troubleshooting useful without dumping full sheet URLs, recipient phones, local paths, or provider account IDs by default.
- Update tests and docs for the payload contract.

**Out of scope**:
- Route authentication; plans 079 and 080 cover auth boundaries.
- Env contract inventory; plan 025 covers env docs.
- Runner status payload redaction; plan 095 covers runner status sync.

## Git Workflow

- Branch: `codex/redact-config-readiness-payloads`
- Commit message: `Redact config readiness payloads`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Classify fields

Create a small table in docs or comments for safe booleans, short labels, partial identifiers, and sensitive operational details.

### Step 2: Redact runtime payloads

Adjust `/api/runtime` to avoid full local paths and unnecessary recipient/email/sheet details unless the UI depends on them.

### Step 3: Redact Meta readiness and agent config output

Keep readiness useful by reporting configured/missing state and partial labels.

### Step 4: Add regression tests

Tests should assert that known fake full identifiers are not returned in default readiness/config responses.

## Test Plan

- Config payload tests pass.
- Manual frontend smoke confirms runtime readiness still renders.
- `rg` scan confirms full fake identifiers do not appear in tested responses.

## Done Criteria

- [ ] Config/readiness payloads have an explicit field sensitivity policy.
- [ ] Default payloads avoid full operational identifiers where possible.
- [ ] Tests prevent accidental re-exposure.
- [ ] Docs explain where operators can inspect full config when needed.

## STOP Conditions

- Frontend or agent workflows require exact full values and no narrower endpoint exists.
- Existing operators rely on copying full identifiers from `/api/runtime`.
- Redaction would hide a currently critical deployment diagnosis with no replacement signal.

## Maintenance Notes

Not every identifier is a secret, but identifiers still deserve minimization. Default payloads should answer "is it configured?" before "what exact value is it?"
