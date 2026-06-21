# Plan 154: Cap WhatsApp Conversation Prompt Text

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/ai/contadores_conversation_bot.py src/backend/tests/test_contadores.py .env.example README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: PROMPT-01

## Why This Matters

The WhatsApp conversation bot caps the number of messages in a prompt but not the size of each message or the total transcript. A lead can send very large text, and that text can be stored and included in Codex/agent prompts. Oversized prompt text increases cost, latency, failure risk, and accidental data exposure.

Prompt construction should have readable per-message and total character caps, with omission markers so the bot and operators know context was truncated.

## Current State

- Inbound text has no maximum length:

```python
src/backend/endpoints/contadores.py:4263
class ContadoresWhatsAppInboundCommand(BaseModel):
    phone: str = Field(min_length=1)
    text: str = Field(min_length=1)
```

- Conversation formatting caps message count but not text size:

```python
src/backend/endpoints/contadores.py:523
for message in messages[-30:]:
```

```python
src/backend/endpoints/contadores.py:525
text = (message.text or "").strip()
```

- The formatted conversation is sent into agent/Codex paths:

```python
src/backend/endpoints/contadores.py:3170
format_conversation_for_bot(messages)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Prompt text scan | `rg -n "format_conversation_for_bot|latest_inbound|conversation=|ContadoresWhatsAppInboundCommand|max_length|truncate|prompt" src/backend/endpoints/contadores.py src/backend/ai/contadores_conversation_bot.py src/backend/tests/test_contadores.py README.md .env.example` | prompt text caps are visible |
| Conversation prompt tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "conversation_bot or inbound or prompt or truncate" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Cap per-message prompt text length.
- Cap total rendered conversation prompt length.
- Cap latest inbound text passed to model paths if it is included separately from the transcript.
- Preserve clear omission markers.
- Route extreme payloads to human review if truncation would remove necessary context.
- Add tests for huge inbound text and large conversation histories.
- Document defaults if env vars are added.

**Out of scope**:
- Inbound media/audio caps; plan 098 owns media and transcription.
- CSV export redaction; plan 146 owns snapshot CSV defaults.
- Database storage limits unless prompt caps require a small validation adjustment.
- Changing message dispatch behavior.

## Git Workflow

- Branch: `codex/cap-whatsapp-conversation-prompt-text`
- Commit message: `Cap WhatsApp conversation prompt text`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define caps

Pick small, readable defaults for:

- per-message prompt characters,
- latest inbound prompt characters,
- total conversation transcript characters.

Use constants near `format_conversation_for_bot()` unless config needs runtime tuning.

### Step 2: Add truncation helper

Add a helper that truncates by characters and appends a marker such as `[truncated N chars]`.

Keep it deterministic and easy to test.

### Step 3: Apply before model invocation

Use the helper in:

- `format_conversation_for_bot()`,
- latest inbound prompt construction,
- any direct `conversation=` argument path.

If an inbound message is too large for safe automation even after truncation, hand off to human review with a clear reason.

### Step 4: Add tests

Cover:

- a very long latest inbound text is truncated,
- a long historical message is truncated,
- total transcript cap is respected,
- markers appear,
- ordinary messages are unchanged.

## Test Plan

- Conversation prompt tests pass.
- Backend import smoke passes.
- No live Codex/OpenAI call is made.

## Done Criteria

- [ ] Prompt text has per-message and total caps.
- [ ] Truncation markers preserve operator/model awareness.
- [ ] Large inbound text does not create unbounded model prompts.
- [ ] Tests cover large text cases.

## STOP Conditions

- Product wants exact full inbound text sent to the model for all cases.
- Truncation would hide required legal/accounting details and no human-review fallback is acceptable.
- Existing prompt tests require exact unbounded transcript strings.

## Maintenance Notes

Message-count caps are not enough. Bound the text that enters every model prompt.
