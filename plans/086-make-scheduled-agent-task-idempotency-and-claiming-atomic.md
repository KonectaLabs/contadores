# Plan 086: Make Scheduled Agent Task Idempotency And Claiming Atomic

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/database.py src/backend/endpoints/contadores.py src/backend/endpoints/workstation.py src/backend/tests`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: HIGH
- **Depends on**: 020
- **Category**: data-integrity
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: AGENT-07

## Why This Matters

Scheduled agent tasks can trigger WhatsApp sends, Workstation links, and agent side effects. Idempotency is currently read-before-insert, and due tasks are listed before being marked running. Overlapping ticks can create duplicate tasks or run the same pending task twice.

## Current State

- `idempotency_key` is indexed, not unique:

```python
src/backend/database.py:5216
idempotency_key: str | None = Field(default=None, index=True)
```

- `create()` checks for an existing row before insert:

```python
src/backend/database.py:5235
clean_key = (idempotency_key or "").strip() or None
```

```python
src/backend/database.py:5237
existing = cls.get_by_idempotency_key(clean_key)
```

- Due tasks are listed without claiming:

```python
src/backend/database.py:5272
def list_due(cls, *, now: datetime, limit: int = 20) -> list["ScheduledAgentTask"]:
```

```python
src/backend/database.py:5279
.where(cls.status == "pending", cls.due_at <= now)
```

- Contadores and Workstation ticks mark running only after listing:

```python
src/backend/endpoints/contadores.py:5704
for task in ScheduledAgentTask.list_due(now=now, limit=20):
```

```python
src/backend/endpoints/workstation.py:1145
for task in ScheduledAgentTask.list_due(now=now, limit=20):
```

```python
src/backend/endpoints/workstation.py:1148
ScheduledAgentTask.mark_status(task.id, status="running", timestamp=now)
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Task scan | `rg -n "ScheduledAgentTask|idempotency_key|list_due|claim_due|mark_status" src/backend src/backend/tests` | atomic create/claim paths are explicit |
| Agent task tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests -k "ScheduledAgentTask or scheduled_agent or automation_tick or workstation" -q` | exit 0 |
| Syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/database.py src/backend/endpoints/contadores.py src/backend/endpoints/workstation.py` | exit 0 |

## Scope

**In scope**:
- Add a duplicate report for non-empty scheduled task idempotency keys.
- Enforce unique non-empty idempotency keys.
- Replace `list_due()` worker usage with an atomic `claim_due()` transition from `pending` to `running`.
- Add stale-running recovery rules.
- Add concurrency-style tests with two sessions or repeated claim calls.

**Out of scope**:
- Codex tool-call idempotency; plan 056 covers tool-call duplicate enforcement.
- Contadores automation tick serialization; plan 010 covers tick-level locking.
- Outbound dispatch claiming; plans 004, 051, and 053 cover dispatch/alert claims.

## Git Workflow

- Branch: `codex/atomic-scheduled-agent-tasks`
- Commit message: `Make scheduled agent tasks atomic`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Report duplicates

Add a read-only duplicate report for non-empty `idempotency_key` values.

Stop before adding uniqueness if production has unresolved duplicates.

### Step 2: Make creation race-safe

After plan 020, add a unique constraint or partial unique index for non-empty idempotency keys.

Catch insert races and return the existing row for the same key.

### Step 3: Add atomic claiming

Implement a method such as:

```python
ScheduledAgentTask.claim_due(now=now, limit=20, target_type="lead")
```

It should transition selected rows from `pending` to `running` inside one transaction before returning them.

### Step 4: Update workers

Update Contadores and Workstation automation ticks to call `claim_due()` instead of `list_due()` plus `mark_status("running")`.

Keep target-type filtering inside the claim query when possible.

### Step 5: Add stale-running recovery

Define conservative behavior for tasks stuck in `running`, for example retry after a configured age or mark failed for operator review.

Do not re-run tasks blindly without an age threshold.

## Test Plan

- Two claim calls cannot return the same task.
- Duplicate idempotency key creation returns the existing row or fails idempotently.
- Stale-running recovery does not affect freshly claimed tasks.
- Existing automation tick tests pass.

## Done Criteria

- [ ] Scheduled task idempotency keys are race-safe.
- [ ] Due tasks are claimed atomically before work starts.
- [ ] Stale running tasks have a documented recovery path.
- [ ] Tests cover duplicate create and double-claim behavior.

## STOP Conditions

- Plan 020 has not landed and uniqueness requires schema migration.
- SQLite locking semantics make the proposed claim query unreliable without broader job-runner design.
- Existing workers intentionally need to inspect due tasks without claiming them.

## Maintenance Notes

`list_due()` can remain as a read-only diagnostic helper, but workers should use `claim_due()`.
