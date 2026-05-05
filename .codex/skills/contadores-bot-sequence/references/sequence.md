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
If Meta includes `contacts.profile.name`, use that WhatsApp profile name as the
lead name for WhatsApp-created leads, and fill existing matched leads only when
they still have no name.

Approved Abogados text fallback:

If the webhook has no usable reply/referral route but the inbound text
normalizes to `Hola! Quiero mas informacion de su propuesta para abogados!`,
create or reuse the lead in the `abogados` funnel, store the inbound message,
and continue as if the lead already replied to message 1.

If the webhook has no referral, its `source_id` does not match any configured
campaign, and no approved text fallback matches, store the message in the
built-in `general` inbox with the `whatsapp` tag. The general inbox has chats
and presets only; an operator can move a lead to a campaign and choose its phase
manually.

## Message 2

Sent 30 seconds after any reply:

`Perfecto. Te cuento rápido:
Los contadores que trabajan con nosotros reciben un flujo de prospectos y posibles clientes que les llega directo al WhatsApp de forma automática.
Te invito a que veas este video donde te explicamos la propuesta a detalle:`

## Message 3

Send immediately after message 2:

WhatsApp MP4 from the configured `loom_mp4.media_path`.

## Message 4

If there is no reply 10 minutes after the Loom send:

`¿conseguiste ver el video?`

## Conversational bot after video

After the lead replies post-Loom and the quiet window passes, DSPy runs the
conversational bot. The bot receives:

- funnel id;
- funnel label;
- lead phone number;
- current stage;
- full conversation history;
- latest inbound batch;
- inferred timezone when the phone country is clear.

The bot must return one of:

- `send_reply`
- `ask_scheduling_details`
- `handoff_human`
- `handoff_scheduling`
- `close_lead`
- `no_action`

Known questions stay in the current stage and are queued as
`sequence_step=ai_reply`: price, inclusions, country/coverage, guarantee,
process, domain, existing page, not having watched the video, being busy,
analyzing/consulting, and simple confirmations.

If the lead wants a meeting, the bot asks only for missing scheduling details:
email, day, time, and timezone when it cannot infer one confidently. The default
call duration is 15 minutes. When email, day, and time are all present, queue
`sequence_step=scheduling_handoff_confirmation`, move the lead to
`needs_human`, set `automation_paused_reason=booking_details_collected`, and
store the scheduling details in `last_classification_reason` for the alert
email.

The automation must not include the Calendly URL in AI replies. Audio, image,
video, document, or sticker-only inbound messages without transcript go to
`needs_human`; the bot must not guess their content.

Example shape for an Abogados lead with a Bolivia number:

```text
Perfecto.

Nosotros lo que hacemos es ayudarle a conseguir mas consultas de potenciales clientes en Bolivia, directo a su WhatsApp.

Para eso le armamos una pagina web moderna y profesional, y ademas campanas publicitarias enfocadas en personas de Bolivia que puedan necesitar sus servicios legales.

La idea es que usted tenga una presencia mucho mas fuerte y que le lleguen oportunidades reales de clientes, sin tener que estar buscando manualmente.

Para avanzar, lo mejor seria una llamada corta donde le explicamos como se aplicaria a su caso. Que dia le queda mejor esta semana?
```

## Manual ping template

Operator-triggered only:

Template name: `contadores_manual_ping_es_v1`

`Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`

This ping is for reopening the WhatsApp 24-hour window from the CRM. It must not
be sent by automation ticks and must not replace the 24-hour opener follow-up.

Marking a lead as `booked` must not send any WhatsApp message. The legacy
`send-manual-booked` action name is kept as a compatibility alias, but it only
marks the lead as `booked`.

## Scheduling handoff

When the lead gives complete scheduling details, send a short confirmation:

```text
Perfecto, gracias.

Le paso estos datos a Facu para coordinar la llamada y le confirmamos por aca.
```

Then pause in `needs_human` with `automation_paused_reason=booking_details_collected`.
The alert email must include lead, funnel, email, day, time, inferred timezone,
latest inbound message, and the direct CRM link.

Manual operators can also choose `send-calendly-link` from the CRM to send only
`https://calendly.com/facundogoiriz/crecimiento`. That manual shortcut still marks the lead as
having reached Calendly, keeps the lead in Manual, and is not used by automation.

## Human handoff

Only uncovered situations, missing real data, exclusions, explicit opt-out,
audio/media without transcript, and complete scheduling handoffs should go to
`needs_human`. Normal questions should be answered by the bot.

The backoffice Manual stage is the full manual queue. The pipeline also has a
`Needs answer` bucket between Manual and Closed for leads with
`manual_reply_status=needs_reply`, until an operator replies or marks the lead
answered.

Manual outbound supports text plus one or more media/file attachments. The
operator can choose files, drag them into the composer, or paste clipboard
images/files. The backend stores these under
`data/contadores/outbound_media/{lead_id}/`; the bot sends them as WhatsApp
image, video, audio, or document media.
