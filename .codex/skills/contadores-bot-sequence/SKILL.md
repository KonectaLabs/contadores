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

1. Send opener as a WhatsApp template for sheet/testing leads.
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

## Runtime rule

- This flow can be deployed while the app is still in `testing`.
- `testing` means the flow is only exercised with the synthetic lead from `CONTADORES_TEST_PHONE`.
- `live` means the flow can start from sheet-imported leads.
- Strategy rollout weights live in Contadores config as `strategy_weights` and can be seeded with `CONTADORES_STRATEGY_WEIGHTS_JSON`.
- Funnel definitions live in `FUNNELS_CONFIG_PATH` or `data/funnels.json`.
  The UI and Codex edit the same file.
- Click-to-WhatsApp ad IDs live in each funnel as `whatsapp_referral_source_ids`.
  Contadores should stay empty when it has no real campaign; currently the real ad source belongs to Abogados.
- Inbound WhatsApp messages with no matching reply/referral are saved in the built-in `general` inbox, except the approved Abogados prefilled proposal text route.
- If Meta includes the sender WhatsApp profile name, the inbound handler stores it as the lead name for WhatsApp-created leads and fills existing phone-only leads without replacing sheet/operator names.

Read [references/sequence.md](references/sequence.md) for the exact messages and timing.
