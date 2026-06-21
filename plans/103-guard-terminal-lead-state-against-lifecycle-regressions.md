# Plan 103: Guard Terminal Lead State Against Lifecycle Regressions

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/database.py src/backend/endpoints/platform.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: none
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CRM-01

## Why This Matters

Closed leads are intentionally terminal until an operator reopens them. Existing tests cover closed leads staying out of automation and explicit reopen restoring the prior stage. However, external lifecycle callbacks and resume automation can still write a non-closed stage through `update_flow_state`, which clears `closed_at` and `stage_before_closed`.

A late Calendly webhook or a resume automation call should not implicitly reopen a lead that the operator already closed.

## Current State

- The explicit reopen action is a dedicated operator path:

```python
src/backend/endpoints/contadores.py:3660
elif normalized_action == "reopen":
```

```python
src/backend/endpoints/contadores.py:3663
stage=resolve_stage_after_reopening(lead),
```

- Closed leads are expected to stay out of automation until reopened:

```python
src/backend/tests/test_contadores.py:7005
def test_contadores_closed_lead_stays_out_of_automation_until_reopened(monkeypatch, tmp_path) -> None:
```

- The generic flow-state helper clears terminal state whenever a non-closed stage is written:

```python
src/backend/database.py:1791
if normalized_stage is not None and normalized_stage != ContadoresLeadStage.CLOSED:
```

```python
src/backend/database.py:1792
item.closed_at = None
```

```python
src/backend/database.py:1793
item.stage_before_closed = None
```

- Resume automation preserves archived leads but not closed leads:

```python
src/backend/endpoints/contadores.py:1550
def infer_resume_stage_from_timestamps(lead: ContadoresLead) -> ContadoresLeadStage:
```

```python
src/backend/endpoints/contadores.py:1552
if lead.stage == ContadoresLeadStage.ARCHIVED or lead.archived_at is not None:
```

```python
src/backend/endpoints/contadores.py:5335
updated = ContadoresLead.update_flow_state(
```

- Calendly webhook reconciliation writes a non-closed stage:

```python
src/backend/endpoints/contadores.py:6254
@contadores_router.post("/calendly/webhook", response_model=ContadoresLeadSummary)
```

```python
src/backend/endpoints/contadores.py:6265
updated = ContadoresLead.update_flow_state(
```

```python
src/backend/endpoints/contadores.py:6267
stage=ContadoresLeadStage.CALENDLY_SENT,
```

- Platform has a lifecycle event helper, but these Contadores lead lifecycle mutations do not emit comparable audit events:

```python
src/backend/endpoints/platform.py:911
def emit_lifecycle_event(
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Terminal state scan | `rg -n "register_contadores_calendly_event|resume_contadores_automation|update_flow_state\\(|closed_at|stage_before_closed|PlatformEvent\\.add|emit.*lead" src/backend/endpoints/contadores.py src/backend/database.py src/backend/tests/test_contadores.py` | terminal guards and audit events are visible |
| Contadores terminal tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "calendly_webhook or resume_after or close_and_reopen or closed_lead" -q` | exit 0 |
| Platform/lifecycle tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "platform_event or lifecycle" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Prevent external/provider lifecycle callbacks from implicitly reopening closed leads.
- Prevent `/resume-automation` from clearing `closed_at` or changing a closed lead's stage unless the operator uses explicit reopen.
- Add tests for late Calendly webhooks against closed leads.
- Add tests for resume automation against closed leads.
- Add lightweight audit events for close/reopen/archive/converted/resume/Calendly lifecycle changes if there is an established local event pattern to reuse.

**Out of scope**:
- Frontend confirmation for terminal actions; plan 070 covers operator confirmation.
- Message status monotonicity; plans 018 and 052 cover message statuses.
- Funnel identity and lead deletion cleanup; plans 087 and 088 cover those.
- Rewriting the full lead state machine.

## Git Workflow

- Branch: `codex/guard-terminal-lead-state`
- Commit message: `Guard terminal lead state transitions`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define the terminal guard

Choose one clear rule:

- only the explicit `reopen` action can clear `closed_at`, or
- helper calls must pass an explicit `allow_reopen=True` flag when they intentionally leave the closed bucket.

Prefer the smallest readable change. Avoid adding broad implicit behavior to `update_flow_state` unless tests prove every caller is safe.

### Step 2: Guard resume automation

When a lead is closed, `/resume-automation` should either:

- return a clear 409/400 explaining that the lead must be reopened first, or
- clear `automation_paused` without changing stage or terminal state only if product behavior requires that.

Do not silently convert a closed lead back to an inferred pipeline stage.

### Step 3: Guard Calendly webhook reconciliation

For closed leads, a late Calendly webhook should preserve terminal state.

It may still record `meeting_scheduled_at` if useful for history, but it must not clear `closed_at`, `stage_before_closed`, or restart automation.

### Step 4: Add audit events

If using `PlatformEvent.add` directly is the local pattern, add concise lifecycle events for:

- close,
- reopen,
- archive,
- mark converted,
- resume automation,
- Calendly scheduled reconciliation.

Use idempotency keys where callbacks can repeat.

### Step 5: Add tests

Add focused tests proving:

- closed lead plus Calendly webhook remains terminal,
- closed lead plus resume automation does not reopen,
- explicit reopen still works,
- audit events are emitted for the lifecycle transitions selected in scope.

## Test Plan

- Targeted Contadores terminal-state tests.
- Platform/lifecycle event tests if events are added.
- Backend import smoke.

## Done Criteria

- [ ] Closed leads cannot be reopened by late provider callbacks.
- [ ] `/resume-automation` cannot accidentally clear terminal state.
- [ ] Explicit reopen still restores the prior stage.
- [ ] Lifecycle mutations have an audit trail or a documented reason for not adding one in this pass.

## STOP Conditions

- Operators rely on Calendly webhooks to reopen closed leads automatically.
- Product owner wants resume automation to reopen closed leads without using the explicit reopen action.
- Adding audit events creates noisy duplicates without an idempotency key strategy.

## Maintenance Notes

Terminal state is an operator decision. Treat provider callbacks as historical signals unless an explicit operator action reopens the lead.
