# Plan 153: Redact Provider Errors Before Persistence

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/ai/contadores_conversation_bot.py src/backend/database.py src/backend/endpoints/contadores.py src/bot/utils.py src/backend/tests src/bot/tests README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: plans/123-centralize-runtime-log-and-operator-script-redaction.md
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PROVIDER-ERROR-01

## Why This Matters

Provider exception text can contain tokens, URLs with query strings, local paths, account identifiers, emails, phones, or raw snippets. Current runtime fallback stores and emails raw provider errors through database alerts, API payloads, and AgentMail notifications.

Redaction needs to happen before provider errors cross durable or external boundaries, not only in logs.

## Current State

- Conversation fallback builds raw runtime error text:

```python
src/backend/ai/contadores_conversation_bot.py:780
chatgpt_error_text = f"{chatgpt_error.__class__.__name__}: {chatgpt_error}"
```

- Runtime alerts persist a normalized but unredacted error string:

```python
src/backend/database.py:5425
error=" ".join(str(error or "").split()).strip()[:2000],
```

- Pending alert payload exposes provider error:

```python
src/backend/endpoints/contadores.py:6087
codex_error=alert.error,
```

- Bot email notifications include it:

```python
src/bot/utils.py:1055
"Error Codex",
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Provider error scan | `rg -n "runtime_error|codex_error|provider.*error|chatgpt_error|fallback_error|alert.error|Error Codex|ContadoresRuntimeAlert" src/backend src/bot src/backend/tests src/bot/tests README.md` | provider-error redaction boundary is visible |
| Redaction tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests src/bot/tests -k "redact or runtime_alert or provider_error or codex_error" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add or reuse a provider-error redaction helper.
- Redact tokens, auth headers, URL query strings, local absolute paths, emails, phones, and very long free text.
- Apply before storing runtime errors in conversation results and runtime alerts.
- Ensure API and email payloads only receive redacted error text.
- Add tests for representative provider exception strings.

**Out of scope**:
- Routine log redaction; plan 123 owns logs and operator script output.
- Agent artifact retention/redaction; plan 140 owns stored artifacts.
- Config readiness redaction; plan 122 owns readiness payloads.
- Hiding the fact that a provider failed.

## Git Workflow

- Branch: `codex/redact-provider-errors`
- Commit message: `Redact provider errors before persistence`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Reuse or add the helper

If plan 123 has landed a shared redaction module, add provider-error rules there.

If plan 123 has not landed, add the smallest local helper that can later move cleanly.

### Step 2: Redact at the boundary

Apply redaction before:

- `ContadoresConversationBotResult.runtime_error`,
- `ContadoresRuntimeAlert.error`,
- pending alert `codex_error` payloads,
- bot email fields.

Prefer storing redacted errors; do not store raw errors and hope serializers clean them later.

### Step 3: Add tests

Cover errors containing:

- bearer/API tokens,
- URLs with query strings,
- local absolute paths,
- email/phone identifiers,
- long provider traces.

Assert stored/API/email-visible text is redacted and bounded.

## Test Plan

- Redaction/runtime-alert tests pass.
- Backend import smoke passes.
- No live provider call is made.

## Done Criteria

- [ ] Provider errors are redacted before database persistence.
- [ ] API and email alert payloads do not contain raw tokens, query strings, local paths, phones, or emails.
- [ ] Tests cover provider error redaction.

## STOP Conditions

- Incident response requires exact raw provider error text and no secure alternative is available.
- Redaction helper placement would create circular imports.
- Existing tests assert exact raw provider error strings and product owner wants that behavior.

## Maintenance Notes

Provider errors are untrusted text. Treat them like external payloads before they enter durable alerts or outbound emails.
