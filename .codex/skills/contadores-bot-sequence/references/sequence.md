# Sequence Reference

These are the built-in Contadores defaults. Runtime can override them through
the funnel definition file at `FUNNELS_CONFIG_PATH` or `data/funnels.json`.

## Message 1

Template opener:

`Hola! Buen día, te escribimos desde Konecta Labs por el formulario para contadores sobre cómo conseguir clientes empresariales con pagos mensuales. ¿Es correcto?`

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

## Calendly handoff

When classification says `wants_to_proceed`, send:

`Esperamos que haya quedado todo claro luego de ver el video.
Para avanzar, el único paso que falta de tu lado es elegir un horario en el calendario.
Elegí el horario que mejor te quede:`

Then send:

`CONTADORES_CALENDLY_BASE_URL`

## Human handoff

Anything ambiguous, hesitant, negative, objection-based, or question-heavy goes to `needs_human`.
