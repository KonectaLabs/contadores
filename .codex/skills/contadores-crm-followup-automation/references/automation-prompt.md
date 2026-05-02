# Hourly Automation Prompt

Use this prompt for the recurring Codex automation that checks and continues
CRM conversations.

Runtime note: a standalone Codex cron can run in a sandbox that blocks outbound
SSH before authentication. Do not make SSH the only way to inspect CRM state.
Use the production snapshot endpoint for read-only analysis, and stop before
live actions unless an approved production action endpoint exists.

```text
Run the hourly Contadores/Abogados CRM follow-up.

Workspace: /Users/fgoiriz/private/repos/contadores.

Before doing anything, read and follow:
- AGENTS.md in the workspace.
- .codex/skills/contadores-crm-followup-automation/SKILL.md
- .codex/skills/contadores-crm-followup-automation/references/buckets-copies-sequences.md
- .codex/skills/contadores-bot-sequence/SKILL.md
- .codex/skills/contadores-rollout/SKILL.md
- .codex/skills/contadores-spreadsheet/SKILL.md when sheet/lead-source state matters.
- /Users/fgoiriz/.codex/skills/konecta-stack-and-zen/SKILL.md if writing or editing code.

Goal: get qualified Contadores and Abogados leads into short sales calls. Do not optimize for message volume.

Operate against the real server, not localhost.

First read state through the production snapshot endpoint:
GET http://149.50.136.121/api/contadores/followup/snapshot?limit=1000&messages_per_lead=12
Header: Host: contadores.fgoiriz.com
Header: X-Internal-Token: <INTERNAL_API_TOKEN>

Use SSH only for server debugging, deploy verification, or live actions that do
not yet have an approved endpoint:
ssh root@149.50.136.121
cd /root/projects/contadores

If SSH fails with "Operation not permitted" before authentication, continue only
with endpoint-based read-only analysis. Do not inspect localhost, send messages,
mutate the database, or create a send ledger through a local fallback.

Every run:
1. Inspect current CRM state from the snapshot endpoint. Use server logs only if SSH is available or another approved log endpoint exists.
2. Find leads with new inbound messages, unresolved Needs answer/Manual state, failed outbound delivery, or a clearly due next step.
3. Apply hard exclusions: Venezuelans, Workstation clients, Guido, Rodrigo Javier Monges Luces, closed, booked, archived, opt-out, invalid/unreachable after retry budget.
4. Check delivery status before interpreting silence. If our last outbound failed, classify as delivery repair/provider failure, not no-reply.
5. Segment eligible leads into the buckets from contadores-crm-followup-automation: needs_answer_now, close_call, retomar_video, manual_ping_template, opener_followup, repair_delivery.
6. For each send candidate, choose the exact approved copy/template from the skill. Ask for a day/time for a 15-minute call on warm/close leads.
7. Send at most one intentional outbound per lead in this run. Do not resend the same follow-up if a similar message was sent recently. Let the built-in bot send Loom intro/video when the normal sequence applies.
8. If the action is ambiguous, do not guess; put it in the run summary for human handling.
9. If sending live, use an approved production action endpoint or a server-side script with a preview/ledger under data/contadores or data/reports. Do not send from localhost.
10. After sending, verify message statuses, retries, provider error codes, recent inbound replies, container health, and logs. Fix system errors before ending. Do not retry final provider failures blindly.

In the final run summary, include:
- Messages sent, grouped by bucket and copy/template.
- Leads closest to converting and the exact next human action.
- New replies that arrived and what happened next.
- Delivery failures grouped by Meta code.
- Any system errors found/fixed.
- Anything intentionally skipped and why.
```
