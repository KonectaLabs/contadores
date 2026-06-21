# Plan 123: Centralize Runtime Log And Operator Script Redaction

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/audio_transcription.py src/backend/endpoints/contadores.py src/bot/logging_utils.py src/bot/scripts/whatsapp_template_echo_test.py src/bot/tests/test_logging_utils.py src/bot/tests/test_whatsapp_inbound_provider.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PRIVACY-02

## Why This Matters

Routine backend/bot logs and manual operator scripts can print phone numbers, profile names, referral IDs, media paths, database URLs, external message ids, and inbound text. Plan 095 redacts runner status payloads, but routine logs need their own redaction policy.

## Current State

- Database URL is logged raw:

```python
src/backend/database.py:7891
logger.info("Database initialized at %s", DATABASE_URL)
```

- Inbound logging includes phone, profile name, referral ids, and click ids:

```python
src/bot/logging_utils.py:132
"route=%s phone=%s profile_name=%s referral_source_id=%s ctwa_clid=%s"
```

- Audio transcription failure paths log media paths:

```python
src/backend/audio_transcription.py:136
logger.warning("Audio transcription failed for %s: %s", media_path, error)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Log redaction scan | `rg -n "Database initialized at|phone=%s|text=%r|media_path|external_id|ctwa_clid|profile_name|logger\\.|print\\(" src scripts --glob '!**/.venv/**'` | sensitive fields use redaction helpers or are intentionally justified |
| Bot log tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_logging_utils.py tests/test_whatsapp_inbound_provider.py -q` | exit 0 |

## Scope

**In scope**:
- Add small shared redaction helpers for phone, email, URLs, local paths, external ids, and free text.
- Apply helpers to high-volume runtime logs and operator script output.
- Keep enough suffix/prefix context to correlate events.
- Add tests for the helper and key log paths.

**Out of scope**:
- Runner status payload redaction; plan 095 covers that path.
- Removing explicit operator export tools.
- Redacting data in database rows or API payloads.

## Git Workflow

- Branch: `codex/runtime-log-redaction`
- Commit message: `Centralize runtime log redaction`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add redaction helpers

Keep helpers simple: phone numbers show last four digits, emails show minimal context, URLs drop query strings, paths show basename/root-relative path, and long text is summarized.

### Step 2: Apply to routine logs

Update backend and bot logs that print lead/provider identifiers. Avoid changing database/API behavior.

### Step 3: Update operator script output

For `whatsapp_template_echo_test.py`, redact inbound phone/text by default and add an explicit verbose flag only if needed.

### Step 4: Add tests

Cover helper output and at least one inbound logging path.

## Test Plan

- Bot logging tests pass.
- Log redaction scan shows known risky patterns either gone or passing through helpers.
- Manual script help documents any verbose/raw-output mode.

## Done Criteria

- [ ] Common sensitive values have one redaction helper path.
- [ ] Routine logs avoid raw phone numbers, local paths, and inbound free text.
- [ ] Operator script output is redacted by default.
- [ ] Tests prevent easy regression.

## STOP Conditions

- Current incident response depends on raw phone/text logs and no alternate lookup exists.
- Redaction helper would create circular imports.
- Provider support requires exact raw values in logs by default.

## Maintenance Notes

Make redaction easy to use. If every call site invents masking, future logs will drift back to raw identifiers.
