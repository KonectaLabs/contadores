---
name: contadores-bot-sequence
description: Use when working on the WhatsApp sequence, message copy, timing windows, template opener, Loom step, Calendly step, or human handoff behavior for Contadores.
---

# Contadores Bot Sequence

Use this skill when editing or reviewing the WhatsApp automation flow.

Contadores is now the first configured funnel in the multi-funnel platform.
Default copy, template names, video strategy definitions, and strategy weights
come from the funnel definition layer. If `data/funnels.json` exists, it can
override the built-in Contadores definition.

## Current sequence

1. Send opener as a WhatsApp template for sheet-imported leads.
   - Click-to-WhatsApp leads whose `referral.source_id` matches the funnel config skip this step because their first inbound message is already the reply.
   - Abogados leads whose first inbound text normalizes to `Hola! Quiero mas informacion de su propuesta para abogados!` also skip this step.
2. Wait for any reply.
3. Wait 30 seconds of silence.
4. Send the Loom intro text.
5. Send the configured Loom strategy:
   - `loom_mp4`: WhatsApp MP4 from `data/contadores/videos/loom_60_seconds_captions.mp4`.
6. Wait 10 minutes.
7. If there is still no reply, send `¿conseguiste ver el video?`
8. Once there are 30 seconds of silence after the post-Loom replies, classify:
   - `wants_to_proceed`
   - `needs_human`
9. If `wants_to_proceed`, send the Calendly text and then the Calendly URL.
10. If `needs_human`, stop automation and alert the operators.

## Manual-only template

Operators can send `contadores_manual_ping_es_v1` from the backoffice to reopen
the WhatsApp 24-hour window:

`Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`

This is not part of the automatic sequence and is not the 24-hour opener
follow-up. It is only queued by a manual operator action and pauses automation
for that lead.

Bulk CRM actions must never preselect `Manual ping`. The operator must
explicitly choose that template before it can be queued.

Marking a lead as `booked` must not send any WhatsApp message. The legacy
`send-manual-booked` action name is kept as a compatibility alias, but it only
marks the lead as `booked` and pauses automation.

## Manual Calendly actions

Operators have two backoffice actions:

- `send-calendly`: send the configured Calendly intro text and then the Calendly URL.
- `send-calendly-link`: send only the Calendly URL.

Both actions record `calendly_sent_at` and keep the lead in Manual.
Automation must keep using the full Calendly text + URL sequence.

## Manual reply ownership

The backoffice Manual stage shows every manual lead. The pipeline also has a
`Needs answer` bucket between Manual and Closed for leads whose current
`manual_reply_status` is `needs_reply`. Once an operator sends a reply or marks
the lead answered, the lead leaves `Needs answer` but remains visible in Manual.

Manual outbound can send text alone or text plus one or more operator-attached
media files. Operators can select files, drop them on the composer, or paste
clipboard images/files. Uploaded outbound files are stored under
`data/contadores/outbound_media/{lead_id}/`, recorded on the queued
`contadores_messages` row, shown in the CRM timeline, and dispatched by the bot
as WhatsApp image, video, audio, or document media.

Manual/custom outbound is only allowed while WhatsApp's 24-hour customer service
window is open. If `last_inbound_at` is older than 24 hours or missing, do not
queue non-template sends. The UI should block the custom composer and point the
operator to an approved template such as `Manual ping`.

## Runtime rule

- This flow runs from sheet-imported leads and Click-to-WhatsApp inbounds.
- Strategy rollout weights are stored in Contadores config as `strategy_weights` and can be seeded with `CONTADORES_STRATEGY_WEIGHTS_JSON`.
- Funnel definitions are stored in `FUNNELS_CONFIG_PATH` or `data/funnels.json`.
  The UI and Codex edit the same file.
- Click-to-WhatsApp ad IDs are stored in each funnel as `whatsapp_referral_source_ids`.
  Contadores should stay empty when it has no real campaign; currently the real ad source belongs to Abogados.
- Inbound WhatsApp messages with no matching reply/referral are saved in the built-in `general` inbox, except the approved Abogados prefilled proposal text route.
- If Meta includes the sender WhatsApp profile name, the inbound handler stores it as the lead name for WhatsApp-created leads and fills existing phone-only leads without replacing sheet/operator names.

Read [references/sequence.md](references/sequence.md) for the exact messages and timing.
