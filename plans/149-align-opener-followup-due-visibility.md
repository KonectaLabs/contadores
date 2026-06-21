# Plan 149: Align Opener Follow-up Due Visibility

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py scripts/build_contadores_crm_runner_delta.py README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: correctness
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: FOLLOWUP-05

## Why This Matters

The follow-up snapshot can mark a lead as needing `opener_followup` as soon as the opener was sent. The real automation waits for the configured delay and checks for duplicate sequence steps before sending. The dashboard/delta view can therefore show a next step too early, and the delta script currently does not include `opener_followup` in actionable buckets when it is actually due.

Operator visibility should use the same due logic as the sender.

## Current State

- Snapshot bucket logic adds `opener_followup` whenever the opener exists:

```python
src/backend/endpoints/contadores.py:1844
if effective_stage == ContadoresLeadStage.AWAITING_INITIAL_REPLY and lead.opener_sent_at is not None:
    buckets.append("opener_followup")
```

- Automation sender waits for the real due time and duplicate guard:

```python
src/backend/endpoints/contadores.py:5889
now >= opener_sent_at + OPENER_FOLLOWUP_DELAY
```

```python
src/backend/endpoints/contadores.py:5890
not ContadoresMessage.has_outbound_sequence_step(
```

- Runner delta does not list `opener_followup` as actionable:

```python
scripts/build_contadores_crm_runner_delta.py:24
DUE_BUCKETS = {
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Opener due scan | `rg -n "opener_followup|OPENER_FOLLOWUP_DELAY|OPENER_FOLLOWUP_SEQUENCE_STEP|DUE_BUCKETS|suggested_buckets" src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py scripts/build_contadores_crm_runner_delta.py README.md .codex/skills wiki/skills` | one shared due rule is visible |
| Snapshot/automation tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "opener_followup or followup_snapshot or automation_tick" -q` | exit 0 |
| Delta syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile scripts/build_contadores_crm_runner_delta.py` | exit 0 |

## Scope

**In scope**:
- Add a shared helper for opener-follow-up due logic.
- Use it in snapshot bucket generation.
- Keep the sender's duplicate and delay checks aligned with the helper.
- Include `opener_followup` in delta due-next-step logic when it is actually due.
- Add tests for not-yet-due, due, already-sent, and replied leads.

**Out of scope**:
- Changing the opener delay itself.
- Message claiming/status monotonicity; plans 051 and 052 own dispatch safety.
- Automation tick serialization; plan 010 owns duplicate tick prevention.
- Redesigning the runner dashboard.

## Git Workflow

- Branch: `codex/align-opener-followup-due-visibility`
- Commit message: `Align opener follow-up due visibility`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Extract the due helper

Create a small helper such as `is_opener_followup_due(lead, *, now)` that checks:

- stage is awaiting initial reply,
- first reply has not been received,
- opener timestamp exists,
- due delay has elapsed,
- no opener follow-up sequence step exists after opener send time.

Keep the helper close to existing follow-up logic unless there is already a better domain module.

### Step 2: Use the helper in snapshots and sender

Replace the broad snapshot bucket check with the helper.

Use the same helper in the automation sender if doing so keeps the code readable. If the sender keeps inline logic, add a test that proves it remains equivalent.

### Step 3: Update delta buckets

Add `opener_followup` to the runner delta actionable buckets once the snapshot only emits it when due.

### Step 4: Add tests

Cover:

- opener sent 1 hour ago does not show `opener_followup`,
- opener sent beyond delay does show it,
- lead with a first reply does not show it,
- lead with an existing follow-up sequence step does not show it,
- delta includes a due opener follow-up.

## Test Plan

- Targeted snapshot/automation tests pass.
- Delta script syntax passes.
- Do not run the live hourly runner.

## Done Criteria

- [ ] Snapshot `opener_followup` bucket matches actual send due logic.
- [ ] Delta script can surface due opener follow-ups.
- [ ] Tests cover early, due, replied, and already-sent cases.

## STOP Conditions

- Product wants dashboard buckets to mean "eventually needed" rather than "due now".
- Existing runner consumers depend on the old broad bucket behavior.
- The duplicate guard cannot be shared without creating slow snapshot queries.

## Maintenance Notes

Use one due rule for visibility and sending. Operators should not have to know which dashboard bucket is premature.
