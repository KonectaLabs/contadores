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

1. Send opener as a WhatsApp template.
2. Wait for any reply.
3. Wait 30 seconds of silence.
4. Send the Loom intro text.
5. Send the configured Loom strategy:
   - `loom_link`: Loom URL alone.
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

## Manual Calendly actions

Operators have two backoffice actions:

- `send-calendly`: send the configured Calendly intro text and then the Calendly URL.
- `send-calendly-link`: send only the Calendly URL.

Both actions move the lead to `calendly_sent` and clear the manual handoff.
Automation must keep using the full Calendly text + URL sequence.

## Runtime rule

- This flow can be deployed while the app is still in `testing`.
- `testing` means the flow is only exercised with the synthetic lead from `CONTADORES_TEST_PHONE`.
- `live` means the flow can start from sheet-imported leads.
- Strategy rollout weights live in Contadores config as `strategy_weights` and can be seeded with `CONTADORES_STRATEGY_WEIGHTS_JSON`.
- Funnel definitions live in `FUNNELS_CONFIG_PATH` or `data/funnels.json`.
  The UI and Codex edit the same file.

Read [references/sequence.md](references/sequence.md) for the exact messages and timing.
