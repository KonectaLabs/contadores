# Sequence Reference

These are the built-in Contadores defaults. Runtime can override them through
the funnel definition file at `FUNNELS_CONFIG_PATH` or `data/funnels.json`.

## Message 1

Template opener:

`Hola! Buen día, te escribimos desde Konecta Labs por el formulario para contadores sobre cómo conseguir clientes empresariales con pagos mensuales. ¿Es correcto?`

Click-to-WhatsApp exception:

If the first inbound WhatsApp webhook includes `referral.source_id` and that id
is configured in `whatsapp_referral_source_ids`, do not send the opener. Create
or reuse the lead with platform `whatsapp_ctwa`, store the inbound message, and
continue as if the lead already replied to message 1.

## Message 2

Sent 30 seconds after any reply:

`Perfecto. Te cuento rápido:
Los contadores que trabajan con nosotros reciben un flujo de prospectos y posibles clientes que les llega directo al WhatsApp de forma automática.
Te invito a que veas este video donde te explicamos la propuesta a detalle:`

## Message 3

Send immediately after message 2:

`CONTADORES_LOOM_URL`

## Message 4

If there is no reply 10 minutes after the Loom send:

`¿conseguiste ver el video?`

## Manual ping template

Operator-triggered only:

Template name: `contadores_manual_ping_es_v1`

`Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`

This ping is for reopening the WhatsApp 24-hour window from the CRM. It must not
be sent by automation ticks and must not replace the 24-hour opener follow-up.

The CRM also has an operator-only `send-manual-booked` action. It sends this
same template and marks the lead as `booked`.

## Calendly handoff

When classification says `wants_to_proceed`, send:

`Esperamos que haya quedado todo claro luego de ver el video.
Para avanzar, el único paso que falta de tu lado es elegir un horario en el calendario.
Elegí el horario que mejor te quede:`

Then send:

`CONTADORES_CALENDLY_BASE_URL`

Manual operators can also choose `send-calendly-link` from the CRM to send only
`CONTADORES_CALENDLY_BASE_URL`. That manual shortcut still marks the lead as
having reached Calendly, keeps the lead in Manual, and is not used by automation.

## Human handoff

Anything ambiguous, hesitant, negative, objection-based, or question-heavy goes to `needs_human`.

The backoffice Manual stage is the full manual queue. Leads with
`manual_reply_status=needs_reply` are mirrored in the `Needs answer` side column
until an operator replies or marks the lead answered.
