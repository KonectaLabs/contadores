# Plan 097: Remove External CDN From Runner Dashboard

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving on. If anything in the STOP conditions section occurs, stop and report. Do not improvise.
>
> **Drift check (run first)**: `git diff --stat bf8782e..HEAD -- scripts/render_contadores_crm_runner_dashboard.py README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md`
>
> If any in-scope file changed since this plan was written, compare the Current State excerpts against live code before proceeding. On a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: MED
- **Depends on**: none
- **Category**: safety
- **Planned at**: commit `bf8782e`, 2026-06-16
- **Issue**: OPS-05

## Why This Matters

The local runner dashboard embeds CRM run summaries, history, and delta markdown, then loads `marked` from jsDelivr to render that content. Even though the dashboard is local HTML, the external script executes in the page that contains lead names, phones, message excerpts, local paths, and operator notes. It also makes the local dashboard depend on an internet CDN.

The dashboard should render sensitive local CRM reports without executing third-party JavaScript.

## Current State

- The dashboard reads sensitive local report artifacts:

```python
scripts/render_contadores_crm_runner_dashboard.py:198
latest_summary_path = reports_dir / "contadores-crm-followup-latest.md"
```

```python
scripts/render_contadores_crm_runner_dashboard.py:202
history_markdown = read_text(history_path) or latest_summary
```

```python
scripts/render_contadores_crm_runner_dashboard.py:206
delta_markdown = str(delta.get("markdown") or "No structured delta has been written yet.")
```

- It embeds those artifacts into the page context:

```python
scripts/render_contadores_crm_runner_dashboard.py:225
prompt_context = {
```

```python
scripts/render_contadores_crm_runner_dashboard.py:231
context_json = json.dumps(prompt_context, ensure_ascii=False).replace("</", "<\\/")
```

```html
scripts/render_contadores_crm_runner_dashboard.py:510
<script id="runner-context" type="application/json">{context_json}</script>
```

- It loads a third-party Markdown renderer:

```html
scripts/render_contadores_crm_runner_dashboard.py:301
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
```

- It renders the Markdown through client-side JavaScript:

```javascript
scripts/render_contadores_crm_runner_dashboard.py:515
function renderMarkdown(targetId, markdown) {{
```

```javascript
scripts/render_contadores_crm_runner_dashboard.py:518
target.innerHTML = window.marked.parse(escapeMarkdownHtml(neutralizeMarkdownImages(markdown || "")));
```

## Commands You Will Need

| Purpose | Command | Expected on success |
|---|---|---|
| External dependency scan | `rg -n "cdn\\.jsdelivr|marked\\.min|<script src=|window\\.marked|innerHTML" scripts/render_contadores_crm_runner_dashboard.py README.md .codex/skills/contadores-crm-followup-automation/SKILL.md wiki/skills/contadores-crm-followup-automation/SKILL.md` | no third-party CDN renderer remains |
| Python syntax | `PYTHONDONTWRITEBYTECODE=1 uv run python -m py_compile scripts/render_contadores_crm_runner_dashboard.py` | exit 0 |
| Render smoke | `PYTHONDONTWRITEBYTECODE=1 python3 scripts/render_contadores_crm_runner_dashboard.py --root "$PWD" --output data/reports/contadores-crm-followup-dashboard.html` | writes dashboard without network dependency |

## Scope

**In scope**:
- Remove the external jsDelivr script.
- Render Markdown without third-party runtime JavaScript.
- Prefer server-side Python rendering with a tiny local formatter, or show escaped Markdown in styled blocks if that is simpler and safer.
- Avoid introducing a bundled dependency solely for this dashboard unless the repo already uses it.
- Keep image neutralization or equivalent behavior so report Markdown cannot auto-load arbitrary images.
- Update docs if they mention the dashboard requiring network access.

**Out of scope**:
- Redacting or truncating report content; plan 095 covers payload redaction.
- Pruning old report files; plan 096 covers retention.
- Rebuilding the dashboard UI.
- Adding a deployed visual Runner tab; plan 091 keeps the dashboard local.

## Git Workflow

- Branch: `codex/remove-runner-dashboard-cdn`
- Commit message: `Remove external runner dashboard CDN`
- Do not push or deploy unless explicitly instructed.

## Steps

### Step 1: Pick the simplest local rendering strategy

Prefer one of:

- render Markdown to safe HTML in Python with a tiny local subset,
- render escaped Markdown as preformatted text,
- convert only headings, bullets, and inline code with a small audited helper.

Do not add broad Markdown/HTML complexity unless the dashboard really needs it.

### Step 2: Remove CDN and client renderer

Delete the `https://cdn.jsdelivr.net/npm/marked/marked.min.js` script and the `window.marked` branch.

If any `innerHTML` remains, it must receive only HTML generated and escaped by trusted local code.

### Step 3: Keep prompt copying intact

The "copy prompt" and "copy command" actions can still read the JSON context. Do not break the operator handoff workflow.

### Step 4: Verify offline behavior

Run the render smoke command and inspect the generated HTML for external scripts.

## Test Plan

- Python syntax passes.
- Render smoke writes the dashboard.
- `rg` scan finds no jsDelivr/marked dependency.
- Operator copy buttons still have the same context fields.

## Done Criteria

- [ ] Dashboard no longer loads third-party JavaScript.
- [ ] Sensitive runner Markdown remains readable enough for operator triage.
- [ ] Prompt-copy workflow still works.
- [ ] Verification does not require internet access.

## STOP Conditions

- Operators require full Markdown fidelity and no safe local renderer is acceptable.
- A future approved local dependency is chosen but cannot be pinned or audited.
- Dashboard content starts including trusted HTML that should not be escaped.

## Maintenance Notes

Local diagnostic dashboards that embed CRM content should be self-contained and offline-safe by default.
