# Plan 010: Serialize Contadores Automation Ticks

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**:

## Why This Matters

The Contadores automation tick queues outbound WhatsApp messages. If two cron/manual ticks overlap, both can evaluate the same stale lead state before `opener_sent_at`, `loom_sent_at`, or `video_check_sent_at` are updated. Workstation already protects its automation tick with a lock; Contadores should do the same or use an equivalent database-level claim.

## Current State

- Contadores tick has no endpoint-level lock:

```python
src/backend/endpoints/contadores.py:5670
@contadores_router.post("/automation/tick", response_model=ContadoresAutomationTickResponse)
async def run_contadores_automation_tick(
    funnel_id: str = Query(default="contadores"),
) -> ContadoresAutomationTickResponse:
    ...
    leads = ContadoresLead.list_recent(limit=1000, funnel_id=funnel_id, include_archived=False)
```

- Tick queues opener/loom directly from stale row state:

```python
src/backend/endpoints/contadores.py:5866
if (
    lead.stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY
    and lead.opener_sent_at is None
    and lead.first_reply_received_at is None
):
    send_opener_sequence(lead=lead)
```

- Workstation has a clear local precedent:

```python
src/backend/endpoints/workstation.py:1135
@workstation_router.post("/automation/tick", response_model=WorkstationAutomationTickResponse)
async def run_workstation_automation_tick() -> WorkstationAutomationTickResponse:
    if workstation_automation_tick_lock.locked():
        return WorkstationAutomationTickResponse(status="busy")
    async with workstation_automation_tick_lock:
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Contadores tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- `src/backend/endpoints/contadores.py`
- `src/backend/tests/test_contadores.py`

**Out of scope**:
- Rewriting the automation state machine.
- Changing WhatsApp template content.
- Changing bot worker scheduling.
- Adding distributed locking infrastructure.

## Git Workflow

- Branch: `codex/serialize-contadores-automation-ticks`
- Commit message: `Serialize Contadores automation ticks`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Add per-funnel async locks

In `src/backend/endpoints/contadores.py`, import `asyncio` if needed.

Add a module-level lock registry:

```python
contadores_automation_tick_locks: dict[str, asyncio.Lock] = {}
```

Add a helper:

```python
def get_contadores_automation_tick_lock(funnel_id: str) -> asyncio.Lock:
    ...
```

Keep it simple and readable. Use normalized funnel id.

**Verify**: backend import smoke prints `backend-import-ok`.

### Step 2: Guard the tick endpoint

In `run_contadores_automation_tick`, resolve the funnel first. Then:

- get the lock for that funnel,
- if locked, return `ContadoresAutomationTickResponse(status="busy")`,
- otherwise `async with lock:` around the existing tick body.

Do not share one global lock across all funnels unless per-funnel locking is impractical; independent funnels should not block each other.

**Verify**: existing Contadores tests exit 0.

### Step 3: Add a busy regression

Add a test in `src/backend/tests/test_contadores.py` that manually acquires the lock for `contadores`, calls `/api/contadores/automation/tick`, and asserts:

- status code 200,
- payload `status == "busy"`,
- no messages are queued.

If testing a live lock is awkward, monkeypatch `get_contadores_automation_tick_lock()` to return a pre-locked `asyncio.Lock`.

**Verify**: Contadores tests exit 0.

### Step 4: Keep duplicate-prevention tests green

Existing tests already call tick twice sequentially for several flows. Those should still pass. This plan prevents overlap, not legitimate later ticks.

**Verify**:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -q
```

## Test Plan

- Existing sequential tick tests remain unchanged.
- New busy-path test proves overlapping tick does not enter the send loop.

## Done Criteria

- [ ] Overlapping tick for the same funnel returns busy before scanning leads.
- [ ] Different funnel locks do not block each other unnecessarily.
- [ ] Existing sequential tick behavior is unchanged.
- [ ] Contadores tests exit 0.
- [ ] Backend import smoke prints `backend-import-ok`.

## STOP Conditions

- Multiple production processes run ticks in separate processes where in-memory locks are insufficient and no database-level claim exists.
- Existing automation caller treats any non-`ok` status as fatal and cannot tolerate `busy`.
- The fix requires changing bot worker scheduling or deploy topology.

## Maintenance Notes

If production can run more than one backend process, follow this plan with a database-level lead claim. The in-process lock still protects common cron/manual overlap and matches the current Workstation precedent.
