# Plan 099: Make AI Provider Config Lazy And Import-Safe

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/config.py src/backend/audio_transcription.py src/backend/ai/contadores_post_loom_classifier.py src/backend/ai/client_profile_extractor.py src/backend/ai/contadores_conversation_bot.py src/backend/ai/codex_agent_runtime.py src/backend/endpoints/workstation.py src/backend/tests/test_contadores_post_loom_classifier.py src/backend/tests/test_audio_transcription.py src/backend/tests/test_contadores_conversation_bot.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: architecture
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AI-01

## Why This Matters

`backend.config` currently constructs several DSPy/OpenAI/OpenRouter model clients and configures DSPy global state at import time. Many modules import that file only for plain settings such as `OPENAI_API_KEY` or transcription model names, so simple imports can freeze environment-driven AI settings, initialize optional provider clients, and mutate global DSPy config before the actual runtime path knows which model it needs.

That makes tests and worker startup harder to reason about. It also hides provider-readiness failures behind unrelated imports.

## Current State

- `backend.config` reads env values and immediately constructs model clients:

```python
src/backend/config.py:188
gpt_5_mini = get_gpt_5_mini(reasoning_effort=REASONING_EFFORT, verbosity=VERBOSITY)
```

```python
src/backend/config.py:189
gpt_5_4_mini = get_gpt_5_4_mini(reasoning_effort="medium", verbosity="low")
```

```python
src/backend/config.py:190
grok_4_3 = get_grok_4_3()
```

```python
src/backend/config.py:191
gpt_5_2 = get_gpt_5_2(reasoning_effort="high", verbosity="high")
```

- More provider clients are created at module import:

```python
src/backend/config.py:195
gemini_pro_3_1 = dspy.LM(
```

```python
src/backend/config.py:202
kimi_2_5 = dspy.LM(
```

```python
src/backend/config.py:209
grok_4_1_fast_non_reasoning = dspy.LM(
```

```python
src/backend/config.py:217
grok_4_1_fast_reasoning = dspy.LM(
```

- Global model selection and DSPy configuration also happen at import:

```python
src/backend/config.py:232
FAST_MODEL = grok_4_1_fast_reasoning
```

```python
src/backend/config.py:233
SMART_MODEL = gpt_5_2
```

```python
src/backend/config.py:239
dspy.configure(lm=FAST_MODEL, adapter=adapter)
```

- Modules that only need constants import the same side-effect-heavy file:

```python
src/backend/audio_transcription.py:14
from backend.config import (
```

```python
src/backend/ai/codex_agent_runtime.py:13
from backend.config import (
```

- AI programs bind default model objects from import-time globals:

```python
src/backend/ai/contadores_post_loom_classifier.py:15
from backend.config import gpt_5_4_mini
```

```python
src/backend/ai/client_profile_extractor.py:12
from backend.config import SMART_MODEL
```

```python
src/backend/ai/contadores_conversation_bot.py:21
from backend.config import (
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Import scan | `rg -n "from backend\\.config|FAST_MODEL|SMART_MODEL|CONVERSATION_BOT_MODEL|dspy\\.configure|gpt_5_4_mini|grok_4_3" src/backend src/bot src/scripts` | no eager model globals remain outside a small lazy config API |
| Backend import smoke without provider keys | `env -u OPENAI_API_KEY -u OPENROUTER_API_KEY -u GEMINI_API_KEY AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |
| Conversation bot tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores_conversation_bot.py src/backend/tests/test_contadores_post_loom_classifier.py -q` | exit 0 |
| Audio tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_audio_transcription.py -q` | exit 0 |
| Codex/workstation focused tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_agent_cli.py src/backend/tests/test_contadores.py -k "Codex or codex or OPENAI_API_KEY or workstation" -q` | exit 0 |

## Scope

**In scope**:
- Split plain env constants from AI provider/model factories.
- Replace import-time DSPy model objects with lazy functions or cached accessors.
- Configure DSPy only when a DSPy program is actually constructed or invoked.
- Keep current model names, default reasoning settings, cache behavior, and fallback selection unless a test documents the preserved behavior.
- Update tests that monkeypatch import-time globals so they patch lazy accessors instead.

**Out of scope**:
- Changing model providers, prompts, or reasoning settings.
- Changing Codex runtime execution behavior.
- Changing audio transcription model defaults.
- Adding live provider integration tests.
- Moving all AI modules into a new package; keep the first diff narrow.

## Git Workflow

- Branch: `codex/lazy-ai-provider-config`
- Commit message: `Make AI provider config lazy`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Separate plain settings from model factories

Keep simple environment values cheap to import. One readable option:

- leave plain constants such as `OPENAI_API_KEY`, `AUDIO_TRANSCRIPTION_MODEL`, and Codex flags in `backend.config`, or
- move them to a new small settings module if that reduces import cycles.

Do not instantiate `dspy.LM` objects while importing constants.

### Step 2: Add lazy model accessors

Replace eager globals with functions such as:

```python
def get_fast_model() -> dspy.LM:
    ...

def get_smart_model() -> dspy.LM:
    ...

def get_conversation_bot_model() -> dspy.LM:
    ...
```

If caching is useful, use a tiny explicit cache or `functools.lru_cache`. Make the cache resettable in tests without reaching into private DSPy state.

### Step 3: Move DSPy global configuration behind an explicit call

Create one small helper such as `configure_dspy_if_needed()` and call it from DSPy program constructors before they need DSPy defaults.

Avoid configuring DSPy during backend import, `/health`, `/api/runtime`, auth, or non-AI endpoint imports.

### Step 4: Update AI consumers

Update consumers to request models at construction time:

- `contadores_post_loom_classifier.py`,
- `client_profile_extractor.py`,
- `contadores_conversation_bot.py`,
- any Workstation/Codex path that imports model globals.

Preserve constructor injection so tests can still pass fake `lm` objects.

### Step 5: Add import-safety tests

Add a test that imports `backend.main` with provider key env vars absent and verifies no model factory is called.

Add a focused test that constructing one AI program obtains exactly the expected default model.

## Test Plan

- Import smoke passes without provider keys.
- Existing AI program tests pass.
- Audio transcription tests still patch OpenAI behavior without initializing unrelated model clients.
- Focused Codex/workstation tests preserve existing API-key fallback behavior.

## Done Criteria

- [ ] Importing non-AI backend modules does not instantiate DSPy/OpenAI/OpenRouter model clients.
- [ ] DSPy global configuration happens only through an explicit lazy helper.
- [ ] Existing model defaults and fallback selection are preserved.
- [ ] Tests can reset lazy model caches without relying on global import order.

## STOP Conditions

- Lazy accessors create circular imports with endpoint modules.
- DSPy requires global configuration at import for current program classes and cannot be moved safely in a narrow diff.
- Provider behavior changes in production paths that are not covered by focused tests.

## Maintenance Notes

Keep this as a readability refactor. The goal is not to redesign AI routing; it is to make imports boring, deterministic, and cheap.
