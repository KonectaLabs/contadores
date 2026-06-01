---
name: contadores-crm-followup-automation
description: Use when analyzing or operating the Contadores/Abogados CRM follow-up workflow, especially lead segmentation, WhatsApp follow-up waves, hourly CRM automations, copy selection, delivery-error review, and next-step planning to convert leads into sales calls.
---

# Contadores CRM Follow-Up Automation

Use this skill for CRM follow-up work across the `contadores` and `abogados`
funnels. The business goal is not "send more messages"; the goal is to get
qualified leads into short sales calls so Facu can close them.

This skill is the source of truth for the hourly automation. The runner prompt
should only say to read this skill and run it; do not duplicate the runbook
inside the scheduled job prompt.

Also read these skills when relevant:

- `contadores-bot-sequence`: current WhatsApp sequence, manual ping, Loom,
  Meeting, and human handoff rules.
- `konecta-frankie-video-offer`: Frankie-style offer framing for stronger
  follow-ups that show a concrete outcome instead of just "checking in".
- `konecta-niche-loom-video` and `konecta-funnel-raw-memory` when the follow-up
  depends on the offer sales arc or raw funnel memory.
- `abogados/skills/abogados-funnel-offer/SKILL.md` and
  `abogados/skills/abogados-loom-video/SKILL.md` when writing Abogados-specific
  proactive follow-up or video-demo copy.
- `contadores-rollout`: server-first deploy and verification rules.
- `contadores-spreadsheet`: sheet/lead-source rules when intake or lead source
  state matters.
- `konecta-stack-and-zen`: repo style and simple code preferences.

## Non-Negotiables

- Operate against the real server for live CRM actions:
  `root@149.50.136.121:/root/projects/contadores`.
- Load `INTERNAL_API_TOKEN` from the environment or local `.env`. Never print it
  in logs or summaries.
- The active hourly runner is the local macOS LaunchAgent
  `com.konecta.contadores.crm-followup`. It starts a fresh `codex exec`
  session each hour, so runs do not depend on this chat thread.
- When `CONTADORES_CRM_FOLLOWUP_RUNNER=1`, you are already inside the active
  scheduled runner. The lock at `CONTADORES_CRM_FOLLOWUP_LOCK_DIR` and the
  running LaunchAgent process are expected and belong to this run. Do not treat
  them as a duplicate or stale automation; the wrapper owns overlap protection.
  Proceed with the production snapshot/API workflow.
- The previous Codex App cron is paused because that runtime can fail to reach
  production HTTP/SSH even when this machine can. Do not treat that as a server
  outage unless the local runner or direct shell checks also fail.
- For read-only hourly analysis, prefer the production snapshot endpoint over
  SSH. Fetch all Contadores/Abogados chats, not only attention-needed chats:
  `GET http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12`.
  Send `Host: crm.fgoiriz.com` and `X-Internal-Token`.
- For spreadsheet-style analysis, use
  `GET http://149.50.136.121/api/contadores/followup/snapshot.csv?limit=20000&messages_per_lead=12`
  with the same headers.
- In snapshot payloads, treat `stage=converted` as the operator-facing converted
  state. Use `raw_stage` only for historical legacy debugging.
- If a standalone Codex cron reports `Operation not permitted` before SSH
  authentication, treat SSH as unavailable in that runtime. Do not use localhost
  as fallback. Use the production HTTP APIs for CRM state and approved actions.
- Exclude Venezuelans completely. Block `+58`, normalized `58...`, and local
  Venezuelan mobile forms like `0412...`, `0414...`, `0416...`, `0424...`,
  `0426...`.
- Exclude Workstation clients completely. As of the 2026-05-02 wave, this means
  the paid clients Guido Roberto Carrion Alvarado and Rodrigo Javier Monges
  Luces, plus any lead present in `workstation_clients`.
- Exclude closed, converted/legacy booked, and archived leads. The backend
  enqueue guard rejects CRM outbound for these states; do not try to requeue or
  bypass it with direct message inserts.
- Exclude any lead with `codex_enabled=false` or `codex_disabled` in
  `exclusion_reasons`. Do not send messages, mutate state, schedule follow-ups,
  or try to route around that switch.
- Always inspect message delivery status before deciding that a lead ignored us.
  If our last outbound failed, the next action is delivery repair or exclusion,
  not "the lead did not answer".
- WhatsApp inbound webhooks are first written by the `bot` service to the
  durable SQLite inbox at `BOT_WEBHOOK_INBOX_PATH` and then replayed into
  `/api/contadores/whatsapp/inbound`. When debugging missing replies, inspect
  both `contadores_messages` and the bot inbox before assuming the lead was
  silent.
- Respect Meta/provider failures. Do not blindly requeue opt-out, invalid,
  undeliverable, or ecosystem-blocked numbers after retry budget is exhausted.
- If a lead answers with a concrete day/time for a call, treat it as urgent
  booking intent before every other bucket. Do not send another generic
  follow-up. If the lead's email and requested slot are clear, try to book the
  call in Facu's Meeting only through a real available Meeting/API/browser
  capability. If the system does not currently support actual Meeting booking,
  immediately mark the lead `needs_human` with
  `classification_label="booking_time_provided"`, pause automation with
  `automation_paused_reason="booking_time_provided"`, and make sure the
  existing alert email path notifies Facu. If email is missing, ask for the
  email in WhatsApp when the send path is allowed, and still surface the
  scheduling handoff in the final summary. This is not optional.
- For close/warm leads, prefer asking for a day and time for a 15-minute call.
  Do not rely only on Meeting.
- Use approved templates when the 24-hour WhatsApp customer-service window is
  closed. Custom manual copy is only valid inside the open window.
- Send at most one intentional follow-up per lead per automation run, unless the
  built-in bot sequence itself sends its paired Loom intro/video messages.
- The built-in bot can answer known post-offer questions with
  `sequence_step=ai_reply`. After a post-offer AI reply, the lead moves to
  Manual (`needs_human`) with `automation_paused_reason=ai_reply_conversation`
  and `manual_reply_status=answered`, because there is already a conversation.
  Do not duplicate an AI reply manually in the same run; wait for the next lead
  reply or handle the lead as a manual close if it needs human judgment.
- Do not only wait for replies. Each run should also inspect leads that already
  received our last message and decide whether a stronger, non-duplicative
  follow-up would increase conversion. This is only allowed when the delivery
  status is clean and the lead is warm enough to justify it. If the 24-hour
  custom window is open, use custom copy/media when appropriate. If the window
  is closed, use an approved template to reopen the conversation first; do not
  skip a warm lead only because the custom window is closed.
- Stronger follow-up should use Frankie-style outcome framing: show that we
  thought about how this would work for the lead's actual practice/studio, lead
  with the concrete result they want, and then ask for a short call time.

## Production API Contract

Every request below must include:

- `Host: crm.fgoiriz.com`
- `X-Internal-Token: <INTERNAL_API_TOKEN>`

Read current CRM state:

```text
GET http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12
GET http://149.50.136.121/api/contadores/followup/snapshot.csv?limit=20000&messages_per_lead=12
```

Queue one custom message inside the open WhatsApp 24-hour window:

```text
POST http://149.50.136.121/api/contadores/followup/leads/{lead_id}/messages
{"text":"...", "dedupe_hours":24}
```

Run an existing CRM action:

```text
POST http://149.50.136.121/api/contadores/followup/leads/{lead_id}/actions
{"action":"send-manual-ping"}
```

Allowed action values are the existing quick actions, including
`send-manual-ping`, `send-opener`, `send-loom`, `send-video-check`,
`send-calendly`, `send-calendly-link`, `mark-converted`,
`mark-booked` (legacy alias for marking `Converted`), `mark-answered`, `close`,
`reopen`, `archive`, and `unarchive`.

Update one lead's classification/stage:

```text
PATCH http://149.50.136.121/api/contadores/followup/leads/{lead_id}
{"stage":"needs_human", "classification_label":"needs_human", "classification_reason":"...", "manual_reply_status":"answered"}
```

Use `PATCH` for classification/stage/tag updates, not for sending messages.
Use the send/action endpoints for outbound WhatsApp.

## Operating Loop

1. Read previous run state before deciding what to do:
   `data/reports/contadores-crm-followup-delta-current.md`,
   `data/reports/contadores-crm-followup-latest.md`,
   `data/reports/contadores-crm-followup-history.md`, and, when useful,
   `GET /api/contadores/followup/runner/status`.
2. Read current CRM state from the production snapshot endpoint. Use SSH/database
   access only when debugging server internals.
3. Compare current CRM state against the previous run state first. Identify new
   inbound messages, changed stages/manual statuses, new or changed delivery
   failures, newly queued/sent messages, newly excluded leads, and leads whose
   next-step timing became due since the previous run.
4. Work from that delta before doing any generic follow-up scan. Leads with new
   events or changed state take priority over broad stale-lead follow-up.
5. Segment eligible delta leads using the buckets in
   [references/buckets-copies-sequences.md](references/buckets-copies-sequences.md).
6. Build a dry-run plan before sending: lead id, funnel, bucket, chosen copy or
   template, reason, and skip reason.
7. Execute live only for clear, eligible actions through the production APIs.
   The queued message rows are the ledger; include queued ids in the summary.
8. Verify after sending: message statuses, retry state, provider errors, recent
   inbound replies, container health, and bot/backend logs.
9. Report what was sent, what failed, what is waiting, what needs human action,
   and which leads are closest to converting.

## Hourly Run Prompt

For each hourly run:

1. Read this skill, then read
   [references/buckets-copies-sequences.md](references/buckets-copies-sequences.md).
2. Read previous run artifacts first:
   `data/reports/contadores-crm-followup-delta-current.md`,
   `data/reports/contadores-crm-followup-latest.md`,
   `data/reports/contadores-crm-followup-history.md`, and, when useful,
   `GET /api/contadores/followup/runner/status`.
3. Fetch the current JSON snapshot and, when useful for tabular reasoning, the CSV
   snapshot.
4. Build or read the delta between the previous run and the current state.
   Prioritize: new inbound messages, stage/manual-status changes,
   delivery-status changes, new provider errors, messages queued or delivered
   since the previous run, leads newly entering or leaving exclusion rules, and
   leads whose next step became due since the previous run.
5. Work the delta first. Only after all new or changed events are handled should
   you do a generic follow-up pass for stale but still-eligible leads.
6. Apply hard exclusions before any send.
7. Check delivery status before interpreting silence. If our last outbound
   failed, classify as delivery repair/provider failure, not no-reply.
8. Detect `booking_time_provided` before ordinary manual/close buckets. If a
   lead gave a slot, either book it with a real supported Meeting path or
   escalate it as an urgent scheduling handoff through the CRM alert path.
9. Segment eligible leads into the buckets from the reference file, including
   proactive/value-follow-up buckets for already-touched leads.
10. Choose the exact approved copy/template. Ask for a day/time for a 15-minute
   call on warm/close leads. For proactive value follow-up, use the Frankie
   notes: outcome first, concrete implementation thought, then one next step.
   If the 24-hour custom window is closed, send an approved reopening template
   first and wait for the lead to reply before sending custom value copy/media.
11. Send at most one intentional outbound per lead in this run. Do not resend a
   similar follow-up if one was sent recently.
12. If the action is ambiguous, do not guess; report it for human handling.
13. After any live action, verify message statuses, retries, provider error
    codes, recent inbound replies, container health, and logs when available.

Final summary must include:

- Delta since previous run: new replies, changed stages/manual statuses, new or
  changed delivery failures, newly queued/sent/delivered messages, new
  exclusions, and due-next-step changes.
- What was handled from the delta before generic follow-up.
- State checkpoint for the next run: the timestamp/source of the current
  snapshot and any assumptions used when comparing against the previous run.
- Messages sent, grouped by bucket and copy/template.
- Proactive follow-up candidates reviewed, sent, and skipped, with the exact
  reason for each skip.
- Leads closest to converting and the exact next human action.
- Urgent booking handoffs: lead, requested day/time, email status, whether the
  lead converted/meeting was scheduled, and whether Facu was alerted.
- New replies that arrived and what happened next.
- Delivery failures grouped by Meta code.
- System errors found/fixed.
- Anything intentionally skipped and why.

## Local LaunchAgent Runner

Install or refresh the hourly runner from the repo:

```bash
scripts/install_contadores_crm_launchd.sh
```

Inspect its status:

```bash
launchctl print gui/$(id -u)/com.konecta.contadores.crm-followup
```

Run it immediately:

```bash
launchctl kickstart -k gui/$(id -u)/com.konecta.contadores.crm-followup
```

The runner script is
`scripts/run_contadores_crm_hourly_followup.sh`. It loads `.env`, preflights
the production snapshot endpoint, extracts the prompt from
`references/automation-prompt.md`, runs `codex exec` in a new session, writes
timestamped logs under `data/reports/`, writes the latest final summary to
`data/reports/contadores-crm-followup-latest.md`, and uses a lock under
`data/locks/` so hourly runs do not overlap. At startup it copies itself to
`data/tmp/` and executes the copy, so a repo edit during a long run cannot
change the already-running shell script.

The real local Mac dashboard is
`data/reports/contadores-crm-followup-dashboard.html`. Generate or refresh it
with `scripts/render_contadores_crm_runner_dashboard.py`, then open it with
`open data/reports/contadores-crm-followup-dashboard.html`. The runner refreshes
that HTML on every `running`, `failed`, and `completed` status update. It reads
the local LaunchAgent, local lock, local logs, latest local summary, and
`data/reports/contadores-crm-followup-history.md`. The dashboard should stay
human-first and delta-first: show what changed since the previous run, what now
needs action, latest run Markdown, accumulated notes, and a recent-run timeline.
Keep stdout/log tails behind technical details.
It also provides a Codex handoff prompt/command that includes the latest run and
history so Facu can ask follow-up questions or request a corrected next action.

The visual Runner tab in the backoffice reads
`GET /api/contadores/followup/runner/status`. The local LaunchAgent also syncs
its latest summary/log tail back to production through
`POST /api/contadores/followup/runner/status` via
`scripts/sync_contadores_crm_runner_status.py`, using `INTERNAL_API_TOKEN`.
That lets the deployed backoffice show the latest local runner result. Keep the
Runner tab human-first too: structured delta and action-needed leads first,
latest Markdown and timeline second, accumulated Markdown history and technical
tails collapsed.

Avoid editing or reinstalling the runner while it is executing. The stable copy
protects the active shell process, but changing scheduler files mid-run makes
logs and verification harder to reason about.

## References

- Read [references/wave-2026-05-02.md](references/wave-2026-05-02.md) for the
  exact CRM analysis/wave that created this skill: user instructions, buckets,
  script design, deploy, live results, and verification.
- Read [references/buckets-copies-sequences.md](references/buckets-copies-sequences.md)
  for the action buckets, copy rules, and next-message sequences.
- Read [references/automation-prompt.md](references/automation-prompt.md) when
  creating or updating the hourly runner prompt.
