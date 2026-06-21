# Plan 129: Confirm Review Workstation Live Codex Run Controls

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/frontend/src/App.tsx src/frontend/src/styles.css src/backend/endpoints/workstation.py src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: frontend
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: WORKSTATION-10

## Why This Matters

Workstation live Codex controls can start, stop, or steer real generation work. Start and steer use modals for input, but submission goes straight to backend. Stop is one click from a menu.

Operators should get a final review of client, prompt/message, and action before enqueueing or interrupting live Codex work.

## Current State

- Frontend start/stop/steer functions call backend live endpoints:

```tsx
src/frontend/src/App.tsx:1438
async function startSoloPageCodexWork(operatorPrompt: string) {
```

```tsx
src/frontend/src/App.tsx:1468
async function stopSoloPageCodexWork() {
```

```tsx
src/frontend/src/App.tsx:1488
async function steerSoloPageCodexWork(message: string) {
```

- Backend endpoints mutate live Workstation/Codex state:

```python
src/backend/endpoints/workstation.py:4353
async def start_workstation_solo_page_codex_work(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Live Codex control scan | `rg -n "startSoloPageCodexWork|stopSoloPageCodexWork|steerSoloPageCodexWork|solo-page/codex|ConfirmDialog" src/frontend/src/App.tsx src/backend/endpoints/workstation.py` | start/stop/steer have final review/confirmation |
| Frontend build | `cd src/frontend && npm run build` | exit 0 |
| Solo page tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py src/backend/tests/test_workstation.py -k "solo_page" -q` | exit 0 |

## Scope

**In scope**:
- Add final confirmation/review for start, stop, and steer actions.
- Show client identity and the prompt/message/action being sent.
- Disable duplicate submits while busy.
- Keep backend behavior unchanged unless tests need a small guard.

**Out of scope**:
- Durable Workstation claiming; plan 119 covers automation overlap.
- Professional-photo job persistence; plan 120 covers photo jobs.
- Redesigning Workstation build controls.

## Git Workflow

- Branch: `codex/confirm-workstation-live-codex-controls`
- Commit message: `Confirm Workstation live Codex controls`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Reuse confirmation pattern

Use the existing confirm dialog where possible. Keep text concrete: client name, action, prompt/message preview, and effect.

### Step 2: Guard stop action

Stop should not be one accidental click from a menu. Add confirmation and keep busy state visible.

### Step 3: Guard start and steer submission

After prompt entry, show a final review or include a confirmation step in the modal before sending.

### Step 4: Verify manually

Check start, steer, stop, cancel, and busy states.

## Test Plan

- Frontend build passes.
- Backend solo-page tests still pass.
- Manual browser check confirms no live Codex action fires without final operator confirmation.

## Done Criteria

- [ ] Start, stop, and steer require explicit final confirmation/review.
- [ ] Confirmation names the target client.
- [ ] Prompt/message preview is visible before action.
- [ ] Busy state prevents duplicate live requests.

## STOP Conditions

- Operators need single-click stop for safety and confirmation would slow emergency interruption.
- Existing modal architecture cannot support review without broader Workstation refactor.

## Maintenance Notes

Live model-control buttons should be treated like provider-write buttons: fast enough for operators, but hard to trigger accidentally.
