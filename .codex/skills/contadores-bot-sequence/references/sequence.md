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

## Post-video service recap

After the lead replies post-Loom and the quiet window passes, DSPy classifies
the reply batch. The classifier can return:

- `wants_to_proceed`
- `watched_video_confirmation`
- `needs_human`

When it returns `watched_video_confirmation`, the automation sends one generated
WhatsApp message with `sequence_step=post_loom_service_recap` and keeps the lead
in `awaiting_video_reply`. This label is only for a plain confirmation that the
lead watched the video, with no question, objection, scheduling date, or clear
request to proceed.

The recap generator receives:

- funnel id;
- funnel label;
- lead phone number;
- post-Loom reply batch.

It must adapt the niche from the funnel and the country from the phone number
when the country code is clear. The message should restate the service in text:
Konecta helps the lead get more potential client inquiries directly to WhatsApp,
using a modern professional website and tailored ad campaigns. It ends by asking
what day this week works for a short call. It must not include the Calendly URL.

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

## Calendly handoff

When classification says `wants_to_proceed`, send:

`Esperamos que haya quedado todo claro luego de ver el video.
Para avanzar, el único paso que falta de tu lado es elegir un horario en el calendario.
Elegí el horario que mejor te quede:`

Then send:

`https://calendly.com/facundogoiriz/crecimiento`

Manual operators can also choose `send-calendly-link` from the CRM to send only
`https://calendly.com/facundogoiriz/crecimiento`. That manual shortcut still marks the lead as
having reached Calendly, keeps the lead in Manual, and is not used by automation.

## Human handoff

Anything ambiguous, hesitant, negative, objection-based, or question-heavy goes to `needs_human`.

The backoffice Manual stage is the full manual queue. The pipeline also has a
`Needs answer` bucket between Manual and Closed for leads with
`manual_reply_status=needs_reply`, until an operator replies or marks the lead
answered.

Manual outbound supports text plus one or more media/file attachments. The
operator can choose files, drag them into the composer, or paste clipboard
images/files. The backend stores these under
`data/contadores/outbound_media/{lead_id}/`; the bot sends them as WhatsApp
image, video, audio, or document media.
