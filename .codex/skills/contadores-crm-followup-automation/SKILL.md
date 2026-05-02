---
name: contadores-crm-followup-automation
description: Use when analyzing or operating the Contadores/Abogados CRM follow-up workflow, especially lead segmentation, WhatsApp follow-up waves, hourly CRM automations, copy selection, delivery-error review, and next-step planning to convert leads into sales calls.
---

# Contadores CRM Follow-Up Automation

Use this skill for CRM follow-up work across the `contadores` and `abogados`
funnels. The business goal is not "send more messages"; the goal is to get
qualified leads into short sales calls so Facu can close them.

Also read these skills when relevant:

- `contadores-bot-sequence`: current WhatsApp sequence, manual ping, Loom,
  Calendly, and human handoff rules.
- `contadores-rollout`: server-first deploy and verification rules.
- `contadores-spreadsheet`: sheet/lead-source rules when intake or lead source
  state matters.
- `konecta-stack-and-zen`: repo style and simple code preferences.

## Non-Negotiables

- Operate against the real server for live CRM actions:
  `root@149.50.136.121:/root/projects/contadores`.
- If a standalone Codex cron reports `Operation not permitted` before SSH
  authentication, treat the run as blocked by the automation sandbox. Do not use
  localhost as fallback. Pause that cron and use a thread heartbeat or another
  runtime with real production SSH access.
- Exclude Venezuelans completely. Block `+58`, normalized `58...`, and local
  Venezuelan mobile forms like `0412...`, `0414...`, `0416...`, `0424...`,
  `0426...`.
- Exclude Workstation clients completely. As of the 2026-05-02 wave, this means
  the paid clients Guido Roberto Carrion Alvarado and Rodrigo Javier Monges
  Luces, plus any lead present in `workstation_clients`.
- Exclude closed, booked, and archived leads.
- Always inspect message delivery status before deciding that a lead ignored us.
  If our last outbound failed, the next action is delivery repair or exclusion,
  not "the lead did not answer".
- Respect Meta/provider failures. Do not blindly requeue opt-out, invalid,
  undeliverable, or ecosystem-blocked numbers after retry budget is exhausted.
- For close/warm leads, prefer asking for a day and time for a 15-minute call.
  Do not rely only on Calendly.
- Use approved templates when the 24-hour WhatsApp customer-service window is
  closed. Custom manual copy is only valid inside the open window.
- Send at most one intentional follow-up per lead per automation run, unless the
  built-in bot sequence itself sends its paired Loom intro/video messages.

## Operating Loop

1. Read recent CRM state from the server database and logs.
2. Segment leads using the buckets in
   [references/buckets-copies-sequences.md](references/buckets-copies-sequences.md).
3. Build a dry-run plan before sending: lead id, funnel, bucket, chosen copy or
   template, reason, and skip reason.
4. Execute live only for clear, eligible actions. Use existing backend helpers
   or one small script with constants, preview output, and a ledger.
5. Verify after sending: message statuses, retry state, provider errors, recent
   inbound replies, container health, and bot/backend logs.
6. Report what was sent, what failed, what is waiting, what needs human action,
   and which leads are closest to converting.

## References

- Read [references/wave-2026-05-02.md](references/wave-2026-05-02.md) for the
  exact CRM analysis/wave that created this skill: user instructions, buckets,
  script design, deploy, live results, and verification.
- Read [references/buckets-copies-sequences.md](references/buckets-copies-sequences.md)
  for the action buckets, copy rules, and next-message sequences.
- Read [references/automation-prompt.md](references/automation-prompt.md) when
  creating or updating the hourly Codex automation.
