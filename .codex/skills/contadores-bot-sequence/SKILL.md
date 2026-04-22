---
name: contadores-bot-sequence
description: Use when working on the WhatsApp sequence, message copy, timing windows, template opener, Loom step, Calendly step, or human handoff behavior for Contadores.
---

# Contadores Bot Sequence

Use this skill when editing or reviewing the WhatsApp automation flow.

## Current sequence

1. Send opener as a WhatsApp template.
2. Wait for any reply.
3. Wait 30 seconds of silence.
4. Send the Loom intro text.
5. Send the Loom URL alone.
6. Wait 10 minutes.
7. If there is still no reply, send `¿Terminaste de ver el video?`
8. Once there are 30 seconds of silence after the post-Loom replies, classify:
   - `wants_to_proceed`
   - `needs_human`
9. If `wants_to_proceed`, send the Calendly text and then the Calendly URL.
10. If `needs_human`, stop automation and alert the operators.

## Runtime rule

- This flow can be deployed while the app is still in `testing`.
- `testing` means the flow is only exercised with `CONTADORES_TEST_PHONE`.
- `live` means the flow can start from sheet-imported leads.

Read [references/sequence.md](references/sequence.md) for the exact messages and timing.
