# Plan 064: Add No-Network Test Guard And External Service Markers

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/tests/conftest.py src/bot/tests/conftest.py src/backend/tests/test_campaigns.py src/backend/tests/test_audio_transcription.py pyproject.toml src/bot/pyproject.toml`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/024-wire-ci-and-test-dependencies.md
- **Category**: test-safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: TEST-05

## Why This Matters

Tests patch external providers ad hoc. If a provider secret leaks into the environment or a patch is missed, CI or local verification could hit Meta, OpenAI, Google, AgentMail, or WhatsApp unintentionally.

## Current State

- Backend conftest only resets auth state and stubs Firecrawl imports:

```python
src/backend/tests/conftest.py:21
@pytest.fixture(autouse=True)
def reset_auth_manager_state() -> None:
```

- Bot conftest stubs provider modules but does not block sockets or outgoing HTTP:

```python
src/bot/tests/conftest.py:13
if "agentmail" not in sys.modules:
```

- External calls are patched case by case:

```python
src/backend/tests/test_campaigns.py:859
def fake_get(url: str, *, params: dict[str, object], timeout: int):
```

```python
src/backend/tests/test_audio_transcription.py:37
class FakeOpenAI:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Backend tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -q` | exit 0 |
| Bot tests | `cd src/bot && PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider tests -q` | exit 0 |
| Marker scan | `rg -n "pytest\\.mark\\.(network|external)" src/backend/tests src/bot/tests` | only intentionally external tests are marked |
| Secret env scan | command added by implementation | provider env vars are cleared or guarded during tests |

## Scope

**In scope**:
- Add a default no-network guard for backend and bot tests.
- Add an explicit marker policy for tests that intentionally exercise external networking.
- Clear or neutralize provider secret env vars during tests.
- Update docs or verification commands to explain how to run marked external tests deliberately.

**Out of scope**:
- Replacing provider clients.
- Removing all mock transports.
- Adding live integration tests.

## Git Workflow

- Branch: `codex/no-network-test-guard`
- Commit message: `Guard tests against accidental external network`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Choose the guard

Use a small, understandable approach:

- block raw sockets by default, or
- add a lightweight dependency if plan 024 has already declared it.

Allow localhost only if needed for TestClient internals. Do not block in-process FastAPI testing.

### Step 2: Add explicit opt-in

Define a marker such as `@pytest.mark.network` or `@pytest.mark.external`.

Default local and CI runs should skip or fail unapproved external network.

### Step 3: Clear provider secrets

In test setup, clear env vars for Meta, OpenAI, Google, AgentMail, WhatsApp, and any other provider whose SDK might auto-discover credentials.

Do not clear env vars inside production code.

### Step 4: Update mocked tests where needed

Tests that use `httpx.MockTransport`, monkeypatched `httpx.get`, or fake OpenAI clients should continue passing without the network marker.

### Step 5: Document deliberate external runs

If any external integration tests exist or are added later, document a command that explicitly enables them.

## Test Plan

- Backend tests pass with no provider credentials in env.
- Bot tests pass with no provider credentials in env.
- A deliberate unmocked request in a temporary guard test fails unless marked/allowed.

## Done Criteria

- [ ] Test runs fail closed against accidental external calls.
- [ ] Provider secrets are not consumed during normal tests.
- [ ] Mocked provider tests still pass.
- [ ] External network opt-in is documented.

## STOP Conditions

- The guard blocks FastAPI TestClient or localhost-only test behavior and cannot be narrowly allowed.
- Provider SDK imports require real credentials just to import.
- The marker policy becomes ambiguous about what is allowed in CI.

## Maintenance Notes

This is a CI safety net. It should make tests less surprising, not create a separate integration-test framework.
