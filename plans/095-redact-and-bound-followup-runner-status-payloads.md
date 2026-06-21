# Plan 095: Redact And Bound Follow-up Runner Status Payloads

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts/sync_contadores_crm_runner_status.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py README.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: 074
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OPS-04

## Why This Matters

The local runner status sync posts rich local artifacts back to the production server: latest summary Markdown, structured delta, active log tail, and launchd stdout/stderr tails. The backend stores those payloads under `data/reports` and returns them from the runner status API. These artifacts can contain lead names, phone numbers, message excerpts, local paths, exception text, and possibly secret-looking strings from logs.

The sync path should keep the useful operator signal while redacting sensitive values and bounding payload size.

## Current State

- The sync script sends full summary, delta, and log tails:

```python
scripts/sync_contadores_crm_runner_status.py:86
"latest_summary": read_text(latest_summary_path),
```

```python
scripts/sync_contadores_crm_runner_status.py:87
"runner_delta": read_json(latest_delta_path),
```

```python
scripts/sync_contadores_crm_runner_status.py:88
"latest_log_tail": read_tail(latest_log_path, tail_lines) if latest_log_path else "",
```

```python
scripts/sync_contadores_crm_runner_status.py:129
parser.add_argument("--tail-lines", type=int, default=220)
```

- The backend accepts unbounded status fields:

```python
src/backend/endpoints/contadores.py:4041
class ContadoresRunnerStatusSyncCommand(BaseModel):
```

```python
src/backend/endpoints/contadores.py:4051
latest_summary: str = ""
```

```python
src/backend/endpoints/contadores.py:4053
latest_log_tail: str = ""
```

- The backend writes the posted payload to durable files:

```python
src/backend/endpoints/contadores.py:2229
(reports_dir / "contadores-crm-followup-latest.md").write_text(summary, encoding="utf-8")
```

```python
src/backend/endpoints/contadores.py:2247
(reports_dir / f"contadores-crm-followup-remote-{timestamp}.log").write_text(log_text, encoding="utf-8")
```

```python
src/backend/endpoints/contadores.py:2258
(reports_dir / "contadores-crm-followup-remote-status.json").write_text(
```

- Current tests assert raw synced values are returned:

```python
src/backend/tests/test_contadores.py:3200
"latest_summary": "Synced summary",
```

```python
src/backend/tests/test_contadores.py:3202
"latest_log_tail": "synced tail",
```

```python
src/backend/tests/test_contadores.py:3227
assert synced_payload["launchd_out_tail"] == "synced stdout"
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| Payload field scan | `rg -n "latest_summary|runner_delta|latest_log_tail|launchd_out_tail|launchd_err_tail|remote-status|remote-.*\\.log|tail-lines|Field\\(" scripts/sync_contadores_crm_runner_status.py src/backend/endpoints/contadores.py src/backend/tests/test_contadores.py` | size/redaction rules are visible |
| Backend focused test | `PYTHONDONTWRITEBYTECODE=1 uv run pytest src/backend/tests/test_contadores.py::test_contadores_followup_runner_status_reads_local_artifacts -q` | exit 0 |
| Backend syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile src/backend/endpoints/contadores.py scripts/sync_contadores_crm_runner_status.py` | exit 0 |

## Scope

**In scope**:
- Add a shared redaction/truncation helper for runner status payloads.
- Mask obvious secret-bearing strings before sending and before persisting.
- Bound text fields by bytes or characters, including summary and log tails.
- Bound structured delta payload size and event counts.
- Add backend validation for oversized posted payloads or deterministic truncation.
- Update the existing runner status tests to cover redaction and size limits.

**Out of scope**:
- Changing who can call the status endpoint; plans 079 and 080 cover auth boundaries.
- Changing runner diagnostics semantics; plan 074 covers diagnostics.
- Changing target URL/transport; plan 093 covers runner server target config.
- Deleting old report artifacts; plan 096 covers retention.

## Git Workflow

- Branch: `codex/redact-runner-status-payloads`
- Commit message: `Redact runner status payloads`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Define field budgets

Choose conservative limits for:

- latest summary,
- latest log tail,
- launchd stdout/stderr tails,
- serialized delta JSON,
- events inside `runner_delta`.

Prefer small defaults that still support operator triage.

### Step 2: Redact sensitive strings

Mask:

- internal tokens and bearer-like tokens,
- emails if they are not needed for the status view,
- phone numbers except last few digits,
- obvious local secret file paths.

Keep lead labels useful enough for operator triage. If full phone/email is required for action, link operators to the authenticated CRM lead instead of embedding it in runner status.

### Step 3: Apply on both sides

Apply redaction/truncation in the local sync script before POST and in the backend before writing. The backend must not trust the local script.

### Step 4: Update tests

Extend the existing runner status test to post:

- a fake token-looking value,
- a long log tail,
- a lead phone/email in the delta.

Assert the response and stored files are redacted and bounded.

### Step 5: Document payload contract

README should state that remote runner status is a triage summary, not a full raw log archive.

## Test Plan

- Focused backend test passes.
- Syntax checks pass.
- Payload field scan confirms redaction/limits are applied at send and persist boundaries.
- No live runner status POST is needed for verification.

## Done Criteria

- [ ] Runner status sync redacts secret-like values.
- [ ] Text and JSON payload sizes are bounded.
- [ ] Backend persists only sanitized runner status artifacts.
- [ ] Existing status API still returns useful operator signal.

## STOP Conditions

- Operators require full raw logs in the deployed status API to run the workflow.
- Current production status payloads exceed the proposed limits and no migration/compatibility path is agreed.
- Redaction would make the runner status impossible to use without a replacement deep-link to CRM detail.

## Maintenance Notes

The full local logs can remain on the Mac under the retention policy. The production status sync should be a compact, sanitized operational summary.
