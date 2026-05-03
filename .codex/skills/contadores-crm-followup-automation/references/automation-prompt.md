# Hourly Automation Prompt

Use this as the entire prompt for the local hourly `codex exec` runner:

```text
In /Users/fgoiriz/private/repos/contadores, read .codex/skills/contadores-crm-followup-automation/SKILL.md and run the hourly Contadores/Abogados CRM follow-up exactly as that skill instructs. If CONTADORES_CRM_FOLLOWUP_RUNNER=1, you are inside the active scheduled runner; ignore the runner's own lock/LaunchAgent process as a duplicate and proceed. Start by reading the current delta artifact, comparing current CRM and runner state against the previous run artifacts, handling the delta/new events first, and only then performing any generic follow-up scan. The skill is the source of truth for endpoints, exclusions, send rules, verification, and the final summary.
```
