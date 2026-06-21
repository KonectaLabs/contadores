# Plan 078: Require Explicit Live Flags For Operator Mutation Scripts

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/scripts/requeue_failed_contadores_messages.py src/scripts/contadores_one_time_requeue_20260424.py src/scripts/whatsapp_templates.py README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OPS-01

## Why This Matters

Several operator scripts can mutate production message queues or WhatsApp templates. Some newer one-off scripts default to preview mode and require `--live` or `--execute`, but older utilities still perform live writes unless the operator remembers to pass `--dry-run`.

This is easy to run wrong during an incident because the safer command and the live command differ only by omitting a flag. For Contadores, the blast radius is real WhatsApp sends or Meta template writes.

## Current State

- The historical failed-message requeue command defaults to live mutation:

```python
src/scripts/requeue_failed_contadores_messages.py:64
parser.add_argument("--dry-run", action="store_true")
```

```python
src/scripts/requeue_failed_contadores_messages.py:69
count = requeue_failed_messages(
```

```python
src/scripts/requeue_failed_contadores_messages.py:51
row = ContadoresMessage.requeue_failed_delivery(
```

- The April one-time requeue script also defaults to live mutation:

```python
src/scripts/contadores_one_time_requeue_20260424.py:158
parser.add_argument("--dry-run", action="store_true")
```

```python
src/scripts/contadores_one_time_requeue_20260424.py:161
retry_count = queue_failed_followup_retries(dry_run=args.dry_run)
```

```python
src/scripts/contadores_one_time_requeue_20260424.py:162
mp4_count = queue_loom_link_mp4_messages(dry_run=args.dry_run)
```

- The rollout docs currently show a dry-run command followed by the live command with no explicit live flag:

```markdown
README.md:1341
uv run python src/scripts/requeue_failed_contadores_messages.py --dry-run
```

```markdown
README.md:1342
uv run python src/scripts/requeue_failed_contadores_messages.py
```

```markdown
.codex/skills/contadores-rollout/SKILL.md:113
uv run python src/scripts/requeue_failed_contadores_messages.py --dry-run
```

```markdown
.codex/skills/contadores-rollout/SKILL.md:114
uv run python src/scripts/requeue_failed_contadores_messages.py
```

- The WhatsApp template helper uses `--dry-run`, but create/delete default to live external writes:

```python
src/scripts/whatsapp_templates.py:392
dry_run: bool = typer.Option(False, "--dry-run", help="Validate/prepare only."),
```

```python
src/scripts/whatsapp_templates.py:504
dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted."),
```

- Two newer one-off scripts already model the desired safer shape:

```python
src/scripts/contadores_followup_wave_20260502.py:742
parser.add_argument("--live", action="store_true", help="Actually queue messages. Default is dry-run.")
```

```python
src/scripts/contadores_promo_web_20260505.py:500
parser.add_argument("--execute", action="store_true", help="Queue real WhatsApp template messages.")
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| CLI default scan | `rg -n "dry-run|execute|live|requeue_failed_delivery|queue_failed_followup_retries|queue_loom_link_mp4_messages" src/scripts/requeue_failed_contadores_messages.py src/scripts/contadores_one_time_requeue_20260424.py src/scripts/whatsapp_templates.py README.md .codex/skills/contadores-rollout/SKILL.md wiki/skills/contadores-rollout/SKILL.md` | live mutation commands require explicit flags |
| Script syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/scripts/requeue_failed_contadores_messages.py src/scripts/contadores_one_time_requeue_20260424.py src/scripts/whatsapp_templates.py` | exit 0 |
| Requeue dry-run smoke | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run python src/scripts/requeue_failed_contadores_messages.py` | prints preview counts and does not requeue |
| Explicit live help smoke | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run python src/scripts/requeue_failed_contadores_messages.py --help` | help documents the live flag |
| Docs sync scan | `rg -n "requeue_failed_contadores_messages.py|whatsapp_templates.py create|whatsapp_templates.py delete" README.md .codex/skills wiki/skills` | docs show preview-first plus explicit live command |

## Scope

**In scope**:
- Change mutating operator scripts so the default command is read-only or preview-only.
- Add an explicit `--execute` or `--live` flag for queue/template mutations.
- Keep existing dry-run output available as the default preview.
- Update README and both Codex/wiki skill copies where they show these commands.
- Add focused CLI tests if an existing test harness can cover the command behavior cheaply.

**Out of scope**:
- Changing message status transition semantics; plan 052 covers that.
- Changing runtime dispatch claiming; plan 051 covers that.
- Changing WhatsApp provider credentials or webhook registration.
- Running any live script against production during this plan.

## Git Workflow

- Branch: `codex/explicit-live-operator-scripts`
- Commit message: `Require explicit live flags for operator scripts`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Pick one live flag convention

Use one readable convention across these scripts. Prefer `--execute` for one-shot external writes and `--live` only where the existing command already uses that word.

For the requeue scripts, either:

- make the default behavior dry-run and require `--execute`, or
- rename the write path to `--live` and keep dry-run as the default.

Do not keep a default live path.

### Step 2: Update failed-message requeue

In `requeue_failed_contadores_messages.py`:

- default to preview mode,
- require the live flag before calling `ContadoresMessage.requeue_failed_delivery`,
- print output that clearly distinguishes `candidate_failed_messages` from `requeued_failed_messages`,
- preserve `--opener-only` and `--keep-attempts`.

### Step 3: Update April one-time requeue

In `contadores_one_time_requeue_20260424.py`:

- default to preview mode,
- require the live flag before queueing retry or MP4 replacement rows,
- print candidate counts separately from queued counts,
- preserve the existing idempotency filters.

### Step 4: Tighten WhatsApp template create/delete

In `whatsapp_templates.py`, make `create` and `delete` preview-first:

- default to `dry_run=True`,
- require `--execute` for live Meta writes,
- keep `check` unchanged because it is read-only,
- make help text explicit that create/delete are previews unless `--execute` is present.

If Typer option naming makes `--execute` awkward alongside `--dry-run`, prefer the simplest readable interface and document it.

### Step 5: Sync operator docs and skills

Update all command examples that currently imply omission means live.

At minimum update:

- `README.md`,
- `.codex/skills/contadores-rollout/SKILL.md`,
- `wiki/skills/contadores-rollout/SKILL.md`.

The docs should show:

```bash
uv run python src/scripts/requeue_failed_contadores_messages.py
uv run python src/scripts/requeue_failed_contadores_messages.py --execute
```

and equivalent preview/live wording for template create/delete.

### Step 6: Verify no live writes are needed for tests

Run syntax checks and help/dry-run smoke commands only. Do not run any command with `--execute` against the real server or local production-like data during this plan.

If tests are added, mock the database and WhatsApp client.

## Test Plan

- Default requeue command previews only.
- Explicit live flag is required for `requeue_failed_delivery`.
- April one-time command previews only by default.
- WhatsApp template create/delete do not construct a live client unless `--execute` is present.
- README and Codex/wiki skill examples agree.

## Done Criteria

- [ ] No mutating operator script in scope writes by default.
- [ ] Live queue/template writes require an explicit flag.
- [ ] Operator output separates candidate counts from queued/deleted/created counts.
- [ ] README and rollout skills document preview-first usage.
- [ ] Verification commands pass without live external writes.

## STOP Conditions

- Existing automation calls these scripts without flags and relies on live mutation.
- Typer or argparse behavior would make old safe dry-run commands fail unexpectedly.
- A production operator needs backward-compatible live invocation during an active incident.

## Maintenance Notes

For future one-off scripts, copy the safer shape from `contadores_followup_wave_20260502.py` and `contadores_promo_web_20260505.py`: preview by default, explicit live flag, and an execution ledger when the command can queue or send many messages.
