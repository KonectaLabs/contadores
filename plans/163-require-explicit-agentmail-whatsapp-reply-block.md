# Plan 163: Require Explicit AgentMail WhatsApp Reply Block

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/providers.py src/bot/tests/test_contadores_flow.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/054-dedupe-agentmail-webhook-replies.md
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AGENTMAIL-06

## Why This Matters

Operator email replies are sent to leads over WhatsApp. The current parser accepts a `Respuesta:` label when present, but if no label exists it returns the whole email body. That can include signatures, quoted threads, disclaimers, or oversized text. The WhatsApp provider may split long text into multiple sends.

Teach-by-email should require an explicit reply block and reject ambiguous or oversized bodies before queueing a lead message.

## Current State

- The alert email says `Respuesta:` is optional:

```python
src/bot/utils.py:1014
"Si queres ser explicito, empeza con `Respuesta:`.",
```

- Parser falls back to the whole body:

```python
src/backend/endpoints/contadores.py:838
return clean_text
```

- Extracted text is queued directly:

```python
src/backend/endpoints/contadores.py:6177
queued_rows = queue_ai_bot_message(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Reply parser scan | `rg -n "extract_operator_whatsapp_reply|Respuesta:|quoted|signature|queue_ai_bot_message|split" src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py src/bot/utils.py src/bot/providers.py src/bot/tests` | explicit reply block and caps are enforced |
| Runtime alert reply tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "email_reply or operator_whatsapp_reply" -q` | exit 0 |
| Bot alert tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests/test_contadores_flow.py -k "alert" -q` | exit 0 |

## Scope

**In scope**:
- Require an explicit `Respuesta:` or equivalent label for email-to-WhatsApp replies.
- Stop extraction at common signature and quoted-thread markers.
- Enforce a conservative maximum WhatsApp reply length.
- Reject ambiguous, quoted-only, or oversized replies without queueing.
- Update alert email copy to say the label is required.
- Add tests for signatures, quoted text, missing label, and overlong text.

**Out of scope**:
- AgentMail webhook replay; plan 054 owns idempotency.
- Sender authorization; plan 160 owns who can reply.
- Model prompt text caps; plan 154 owns AI prompt size.
- WhatsApp provider chunking behavior for normal outbound messages.

## Git Workflow

- Branch: `codex/require-agentmail-reply-block`
- Commit message: `Require explicit AgentMail WhatsApp reply block`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Tighten parser behavior

Change `extract_operator_whatsapp_reply()` so it returns text only after an approved label such as `Respuesta:`.

If no label is present, return empty or a structured error reason.

### Step 2: Strip quoted and signature sections

Stop parsing at common markers such as:

- `-- `,
- `On ... wrote:`,
- `El ... escribio:`,
- `From:`,
- forwarded-message separators.

Keep this heuristic small and test-driven.

### Step 3: Add length guard

Cap the extracted text before queueing. If over the cap, reject with a clear status and do not rely on WhatsApp provider splitting.

### Step 4: Update email copy and tests

Alert emails should say that the operator must reply with `Respuesta:` followed by the exact WhatsApp text.

Tests should prove missing label, quoted thread, signature, and oversized body do not send.

## Test Plan

- Runtime alert reply parser tests pass.
- Bot alert tests pass.
- Backend import smoke passes.
- No live WhatsApp send is made.

## Done Criteria

- [ ] Email-to-WhatsApp replies require an explicit reply block.
- [ ] Quoted/signature text is not sent to leads.
- [ ] Oversized replies are rejected before queueing.
- [ ] Tests cover ambiguous and unsafe bodies.

## STOP Conditions

- Operators rely on free-form email replies without labels and cannot change workflow.
- Real email clients format replies in a way the parser cannot handle safely.
- Length cap conflicts with approved long-form reply templates.

## Maintenance Notes

Email bodies are messy. Only send the text the operator deliberately marks as the WhatsApp reply.
