# Plan 146: Redact Follow-up Snapshot CSV By Default

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/143-neutralize-spreadsheet-formulas-in-csv-exports.md
- **Category**: privacy
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: CSV-PII-01

## Why This Matters

The follow-up snapshot CSV endpoint is useful for automation analysis, but its default export includes raw email, phone, normalized phone, message bodies, delivery errors, and recent transcripts. It allows up to 20,000 leads and 30 messages per lead.

That is a high-volume PII and conversation export. The default CSV should be safe for routine diagnostics, with a deliberate full mode for automation that truly needs raw contact details and message text.

## Current State

- CSV fields include contact details and message text:

```python
src/backend/endpoints/contadores.py:1958
def build_followup_snapshot_csv(snapshots: list[ContadoresFollowupLeadSnapshot]) -> str:
```

```python
src/backend/endpoints/contadores.py:1961
fieldnames = [
    "lead_id",
    "funnel_id",
    "full_name",
    "email",
    "phone",
    "normalized_phone",
```

```python
src/backend/endpoints/contadores.py:1988
"latest_inbound_text",
"latest_outbound_text",
"latest_outbound_error",
"recent_transcript",
```

- Rows write raw contact details and conversation content:

```python
src/backend/endpoints/contadores.py:2013
"email": snapshot.email or "",
"phone": snapshot.phone,
"normalized_phone": snapshot.normalized_phone,
```

```python
src/backend/endpoints/contadores.py:2031
"latest_inbound_text": snapshot.latest_inbound.text if snapshot.latest_inbound else "",
```

- The endpoint can return a very large CSV:

```python
src/backend/endpoints/contadores.py:4710
@contadores_router.get("/followup/snapshot.csv")
```

```python
src/backend/endpoints/contadores.py:4713
limit: int = Query(default=5000, ge=1, le=20000),
messages_per_lead: int = Query(default=8, ge=1, le=30),
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Snapshot CSV scan | `rg -n "build_followup_snapshot_csv|snapshot\\.csv|messages_per_lead|recent_transcript|latest_inbound_text|latest_outbound_text|normalized_phone|include_sensitive|profile" src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py README.md .codex/skills wiki/skills` | default/full CSV contract is visible |
| Snapshot CSV tests | `PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 uv run --with pytest pytest -p no:cacheprovider src/backend/tests/test_contadores.py -k "snapshot_csv or followup_snapshot" -q` | exit 0 |
| Backend import smoke | `AUTH_DISABLE=true PYTHONPATH=src uv run python -c "from backend.main import app; print('backend-import-ok')"` | prints `backend-import-ok` |

## Scope

**In scope**:
- Add a `profile=summary|full` or `include_sensitive=false|true` contract to the CSV endpoint.
- Make the default CSV omit or mask raw contact details and conversation bodies.
- Keep a full mode for existing automation that genuinely needs raw text.
- Ensure full mode still uses the formula neutralizer from plan 143.
- Document the privacy difference between summary and full exports.
- Add tests for default redaction and explicit full export.

**Out of scope**:
- JSON snapshot redaction unless the same helper makes it trivial.
- Runner artifact retention; plan 096 owns hourly runner retention.
- One-off operator report retention; plan 142 owns those files.
- CSV formula neutralization; plan 143 owns spreadsheet formula safety.
- Changing the internal token auth boundary.

## Git Workflow

- Branch: `codex/redact-followup-snapshot-csv`
- Commit message: `Redact follow-up snapshot CSV by default`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define the summary profile

Choose fields that let operators analyze state without raw PII:

- lead id,
- funnel id,
- stage and raw stage,
- exclusion reasons and suggested buckets,
- message timestamps,
- message status and error code,
- booleans such as automation paused,
- masked email/phone if useful.

Omit `latest_inbound_text`, `latest_outbound_text`, `recent_transcript`, and raw delivery error text in summary mode.

### Step 2: Add an explicit full mode

Accept either:

- `profile=summary|full`, or
- `include_sensitive=false|true`.

Default to summary. If the hourly follow-up runner depends on raw text, update that caller to request full mode explicitly and document why.

### Step 3: Preserve CSV safety

Apply the formula-neutralization helper from plan 143 to both summary and full profiles. Redaction should not accidentally skip formula protection.

### Step 4: Add tests

Cover:

- default endpoint response does not include raw email, phone, latest message text, or transcript body,
- explicit full mode includes the legacy raw fields,
- formula-looking values remain neutralized in full mode,
- invalid profile values return a clear 422 or equivalent validation error.

### Step 5: Update docs and skills

Update README and follow-up automation skill mirrors with:

- default summary behavior,
- how to request full CSV,
- when full CSV is appropriate,
- reminder that exported files are sensitive CRM artifacts.

## Test Plan

- Snapshot CSV tests pass.
- Backend import smoke passes.
- Manual scan shows endpoint docs and skills mention summary/full behavior.
- Do not run the live hourly follow-up runner.

## Done Criteria

- [ ] `/api/contadores/followup/snapshot.csv` defaults to a redacted summary export.
- [ ] Existing full-data automation can opt in explicitly.
- [ ] Full mode keeps formula-neutralization protection.
- [ ] Tests prove default redaction and explicit full export.

## STOP Conditions

- The hourly follow-up runner cannot function without full raw text and cannot be updated in the same change.
- Operators require raw message text in default downloads for daily workflow.
- Existing downstream consumers cannot add a full-mode query parameter before rollout.

## Maintenance Notes

Internal-token endpoints can still leak broadly once downloaded. Make routine exports safe by default and require an intentional signal for high-sensitivity CSVs.
