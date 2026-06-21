# Plan 101: Remove Unused AI Dependencies From Bot Runtime

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/bot/pyproject.toml src/bot/uv.lock src/bot/main.py src/bot/utils.py src/bot/providers.py src/bot/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: build
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: BUILD-01

## Why This Matters

The bot service is the public webhook and dispatch runtime. Its package declares `dspy-ai`, which pulls AI/OpenAI dependencies into the bot lock even though the bot code does not import DSPy or OpenAI. That widens the dependency surface of the webhook process, makes bot image builds heavier, and can confuse audits about which service is allowed to initialize AI providers.

The backend owns conversation AI, Codex, audio transcription, and Workstation generation. The bot should only carry channel/provider dependencies it actually uses.

## Current State

- The bot package declares DSPy:

```toml
src/bot/pyproject.toml:7
"dspy-ai>=3.0.4",
```

- The bot lock includes `dspy-ai`:

```text
src/bot/uv.lock:343
{ name = "dspy-ai" },
```

```text
src/bot/uv.lock:364
{ name = "dspy-ai", specifier = ">=3.0.4" },
```

- The bot lock also includes DSPy and OpenAI via that dependency path:

```text
src/bot/uv.lock:495
name = "dspy"
```

```text
src/bot/uv.lock:1431
sdist = { url = "https://files.pythonhosted.org/packages/.../openai-2.21.0.tar.gz",
```

- Actual bot imports are channel/provider/runtime imports, not AI model imports:

```python
src/bot/main.py:13
import httpx
```

```python
src/bot/utils.py:15
import httpx
```

```python
src/bot/providers.py:20
from agentmail import AsyncAgentMail, AgentMailEnvironment
```

```python
src/bot/providers.py:27
from pywa.types.templates import BodyText, TemplateLanguage
```

- A direct search found no bot code importing DSPy or OpenAI:

```bash
rg -n "\\bdspy\\b|OpenAI|from openai|import openai" src/bot src/bot/tests
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Confirm unused AI imports | `rg -n "\\bdspy\\b|OpenAI|from openai|import openai|dspy-ai" src/bot src/bot/pyproject.toml src/bot/uv.lock src/bot/tests` | after the change, no bot code/package/lock dependency on DSPy/OpenAI remains unless intentionally justified |
| Regenerate bot lock | `cd src/bot && uv lock` | exits 0 and updates only the bot lock for dependency removal |
| Frozen bot sync | `cd src/bot && uv sync --frozen --no-dev` | exits 0 |
| Bot tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -q` | exit 0 |
| Bot image build | `docker compose build bot` | exits 0 |

## Scope

**In scope**:
- Remove `dspy-ai` from `src/bot/pyproject.toml` if no bot import needs it.
- Regenerate `src/bot/uv.lock`.
- Confirm `openai` and DSPy disappear from the bot lock unless another real bot dependency requires them.
- Keep required bot dependencies such as FastAPI, httpx, pywa, AgentMail, Svix, Google APIs, unquotemail, and openpyxl.

**Out of scope**:
- Changing backend AI dependencies.
- Changing conversation bot or Codex behavior.
- Removing provider dependencies that the bot imports directly.
- Splitting bot tests or CI; plans 024 and 064 cover test dependency/guard work.

## Git Workflow

- Branch: `codex/remove-unused-bot-ai-dependencies`
- Commit message: `Remove unused AI dependencies from bot runtime`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Reconfirm imports

Run the import scan and confirm `src/bot` has no real DSPy/OpenAI import.

If a new bot AI import exists, stop and classify whether it belongs in backend instead of keeping DSPy in the bot.

### Step 2: Remove the unused dependency

Edit `src/bot/pyproject.toml` to remove only `dspy-ai`.

Do not reorganize unrelated dependencies.

### Step 3: Regenerate the bot lock

Run:

```bash
cd src/bot && uv lock
```

Review the diff so removed packages are limited to DSPy/OpenAI and transitive packages that existed solely for DSPy.

### Step 4: Verify bot runtime

Run the frozen sync, bot tests, and bot image build.

The bot should still import and start with WhatsApp, AgentMail, Google, Svix, openpyxl, and unquotemail available.

### Step 5: Document only if needed

No README change is needed unless operators currently expect AI dependencies inside the bot container. If docs mention bot-owned AI, update that language to say the backend owns AI decisioning.

## Test Plan

- Bot import/dependency scan.
- Bot unit tests.
- Frozen bot dependency sync.
- Bot Docker build.

## Done Criteria

- [ ] `src/bot/pyproject.toml` no longer declares unused AI dependencies.
- [ ] `src/bot/uv.lock` no longer carries DSPy/OpenAI solely for the bot runtime.
- [ ] Bot tests pass.
- [ ] Bot image builds from the frozen lock.

## STOP Conditions

- A real bot code path imports DSPy/OpenAI after drift check.
- Removing DSPy removes a transitive package that the bot imports without declaring directly.
- `uv lock` changes unrelated dependency families unexpectedly.

## Maintenance Notes

Keep the public webhook process boring. Provider SDKs belong in the bot; AI model clients belong in the backend unless a future design explicitly moves decisioning into the bot.
