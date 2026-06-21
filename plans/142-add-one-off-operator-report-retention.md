# Plan 142: Add One-Off Operator Report Retention

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/scripts/contadores_promo_web_20260505.py src/scripts/contadores_followup_wave_20260502.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/096-prune-followup-runner-report-artifacts.md
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: RETENTION-05

## Why This Matters

One-off operator scripts can write CSV previews and ledgers containing lead names, IDs, countries, professions, template parameters, and rendered message text. These artifacts are outside the hourly follow-up runner report names covered by plan 096.

They need a shared retention policy and redacted default output.

## Current State

- Promo preview CSV includes lead and rendered-message data:

```python
src/scripts/contadores_promo_web_20260505.py:384
def write_preview(path: Path, candidates: list[CampaignCandidate]) -> None:
```

```python
src/scripts/contadores_promo_web_20260505.py:397
"template_params_json",
```

```python
src/scripts/contadores_promo_web_20260505.py:398
"rendered_text",
```

- Promo execution ledger persists campaign/send details:

```python
src/scripts/contadores_promo_web_20260505.py:442
def write_ledger(path: Path, *, queued_message_ids: list[int], candidates: list[CampaignCandidate]) -> None:
```

- Older follow-up wave preview stores resolved send plans:

```python
src/scripts/contadores_followup_wave_20260502.py:641
def write_preview(plans: list[PlannedSend], path: Path) -> None:
```

- README documents the promo preview artifact path:

```markdown
README.md:1361
El modo default es dry-run: genera `data/reports/promo-web-profesional-2026-05-05-preview.csv`
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Operator report scan | `rg -n "write_preview|write_ledger|data/reports|data/contadores|rendered_text|template_params|include-sensitive|retention" src/scripts README.md` | one-off reports have retention and redaction controls |
| Script syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/scripts/contadores_promo_web_20260505.py src/scripts/contadores_followup_wave_20260502.py` | exit 0 |
| Report dry-run | `uv run python src/scripts/contadores_promo_web_20260505.py --help` | help mentions sensitive output controls if CLI changes |

## Scope

**In scope**:
- Define a shared retention helper or documented pattern for one-off CSV/JSON reports.
- Default previews to redacted fields where practical.
- Add `--include-sensitive` or equivalent for full rendered text/params.
- Add dry-run prune/list command for known one-off report prefixes.
- Update README with retention and owner guidance.

**Out of scope**:
- Hourly CRM follow-up runner reports; plan 096 owns those.
- Changing queued message content.
- Deleting existing reports without owner approval.

## Git Workflow

- Branch: `codex/operator-report-retention`
- Commit message: `Add operator report retention controls`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Inventory one-off report outputs

List current script paths, file prefixes, and fields that contain lead-identifying or message content.

### Step 2: Add redacted defaults

Where scripts write previews, default to omitting or summarizing rendered message text and template parameters.

Allow full output only with an explicit flag.

### Step 3: Add retention helper

Add a small helper or script mode that can list and prune known report prefixes after a retention window.

Default to dry-run.

### Step 4: Update docs

Document where one-off reports are written, what is sensitive, and who can approve deletion.

## Test Plan

- Script syntax passes.
- Help output documents sensitive-output flags if CLI changes.
- Manual dry-run report list shows targets without deleting.

## Done Criteria

- [ ] One-off reports have retention guidance.
- [ ] Sensitive preview fields are redacted by default or require an explicit flag.
- [ ] Dry-run prune/list exists for known prefixes.
- [ ] README documents the policy.

## STOP Conditions

- Operators rely on full rendered text in default previews for approval.
- Existing reports must be preserved indefinitely for audit.
- Script changes would alter live queued message behavior.

## Maintenance Notes

One-off scripts age into operational history quickly. Keep their outputs bounded and deliberate.
