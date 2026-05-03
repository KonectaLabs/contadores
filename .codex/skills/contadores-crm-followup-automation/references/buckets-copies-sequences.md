# Buckets, Copies, And Sequences

Use these rules for Contadores/Abogados CRM follow-up.

## Hard Exclusions

Do not send to:

- Venezuelans: `+58`, normalized `58...`, or local mobile forms `0412...`,
  `0414...`, `0416...`, `0424...`, `0426...`.
- Any lead present in `workstation_clients`.
- Guido Roberto Carrion Alvarado and Rodrigo Javier Monges Luces.
- Closed, booked, or archived leads.
- Leads with explicit opt-out, rejection, or Meta `131050`.
- Leads whose latest possible action would duplicate a message already sent
  recently.

## Action Buckets

### `booking_time_provided`

Use before every other bucket when the latest inbound gives a concrete day,
time, availability window, or email for coordinating a call. This is a
conversion moment, not a generic manual reply.

Action:

- If the day/time and email are both clear, first try to book the call in
  Facu's Calendly through a real available Calendly/API/browser capability.
- Current code only supports sending Calendly links and reconciling Calendly
  webhooks; it does not create bookings from a free-text day/time. If no real
  booking path is available, do not pretend the meeting is booked. Escalate
  immediately through the CRM:
  `PATCH /api/contadores/followup/leads/{lead_id}` with
  `stage="needs_human"`,
  `classification_label="booking_time_provided"`,
  `manual_reply_status="needs_reply"`,
  `automation_paused=true`,
  `automation_paused_reason="booking_time_provided"`, and a
  `classification_reason` that includes the requested day/time, timezone if
  known, email status, and the latest chat excerpt.
- This must trigger the existing needs-human alert email path to Facu. In the
  final summary, call it an urgent scheduling handoff and include exactly what
  Facu has to calendar.
- If the slot is clear but the email is missing and WhatsApp sending is allowed,
  ask for the email once. Still keep the lead in this bucket until the calendar
  handoff is resolved.
- If the date/time is ambiguous, ask one clarifying question and report it.

Email missing copy:

`Perfecto {name}. Que email queres que use para mandarte la invitacion?`

Ambiguous time copy:

`Perfecto {name}. Me decis el dia, horario y tu zona horaria asi lo dejamos coordinado?`

### `needs_answer_now`

Use when `last_inbound_at` is newer than `last_outbound_at`, or the CRM shows
the lead in Needs answer/Manual with an unanswered inbound.

Action:

- If the answer is obvious and inside the 24-hour window, send one manual custom
  reply.
- If ambiguous, report for human instead of guessing.

### `close_call`

Use when the lead is warm, asked about price/budget/details, showed intent, or
is close enough that a call is the correct next step.

Preferred copy:

`Hola {name}, le gustaria agendar una reunion corta de 15 minutos para conocernos y sacarse las ultimas dudas? Digame que dia y horario le queda bien y lo coordinamos.`

If price/budget was asked:

`La inversion es de 300 USD. Incluye pagina web y campana publicitaria para que le lleguen consultas a su WhatsApp. Si le sirve, hagamos una llamada corta de 15 minutos y le explico bien como seria en su caso. Que dia y horario le queda bien?`

### `retomar_video`

Use when the lead received the Loom/video context and went quiet.

Preferred copy:

`Hola {name}, pudiste ver el video? Queria saber si te interesa avanzar o si quedo alguna duda de la propuesta.`

If they answer positively after this, move to `close_call`.

### `proactive_value_followup`

Use when the lead is warm, already received our last outbound, has not replied
yet, and a stronger message would add real selling value instead of just
repeating "seguimos?". This is for leads that are already close enough that a
specific implementation thought can make the offer clearer.

Eligibility:

- latest outbound is `sent` or `delivered`, not failed;
- lead is not closed/booked/archived, Venezuelan, Workstation, opt-out, or
  provider-blocked;
- no similar value follow-up or video-demo follow-up was sent recently;
- lead previously showed intent, asked for info/price, watched/accepted video,
  or is in `close_call`/`retomar_video` with a clean delivered last outbound.

Do not use this bucket for cold leads who never replied, leads whose last
outbound failed, or leads who just received a message moments ago.

Window rule:

- If the 24-hour custom window is open, send the proactive custom copy when the
  lead is a good fit.
- If the 24-hour custom window is closed, do not send raw custom copy. Use an
  approved reopening template, usually `manual_ping_template`, to get a reply
  and reopen the conversation. Once they reply, continue with the proactive
  value copy or video/demo if still appropriate.
- In the summary, separate "custom proactive sent" from "template reopen sent".

Frankie framing:

- Do not say only "queria hacer seguimiento".
- Do not lead with "marketing", "IA", "web", "ads", "CRM", or generic "mas
  leads". Those are mechanisms, not the offer.
- Lead with a concrete outcome: more qualified WhatsApp inquiries, cases that
  leave honorarios, pymes looking for a contador, an ordered inquiry flow.
- Anchor the message to one buyer and one valuable opportunity. For abogados,
  prefer "sucesion con inmueble", "despido con telegrama", "amparo urgente", or
  "accidente con documentacion" when context supports it. For contadores,
  prefer pymes, monthly clients, and business owners looking for an accountant.
- Make it feel thought-through for that lead: "estaba pensando en como
  implementarlo para tu estudio".
- If price comes up, frame value received before the call ask: "USD 300, y por
  eso recibis pagina, campanas y el flujo para que las consultas entren
  ordenadas a tu WhatsApp."
- End with one call objective: ask what day/time works for 15 minutes.

Abogados copy:

`Hola {name}, estaba pensando en como se podria implementar para tu estudio. La idea no es solo hacer una pagina: es que te lleguen consultas de casos que dejan honorarios, como sucesiones, despidos o amparos, directo a tu WhatsApp y con datos mas ordenados. Si queres lo vemos 15 min, que dia y horario podes?`

Contadores copy:

`Hola {name}, estaba pensando en como se podria implementar para tu estudio. La idea no es solo hacer una pagina: es que cuando una pyme busque contador en tu ciudad, la consulta llegue a tu WhatsApp mas ordenada y con mas intencion. Si queres lo vemos 15 min, que dia y horario podes?`

Generic copy when the funnel is unclear:

`Hola {name}, estaba pensando en como se podria implementar esto para vos. La idea no es solo hacer una pagina, sino armar un flujo para que las consultas correctas lleguen a tu WhatsApp mas ordenadas. Si queres lo vemos 15 min, que dia y horario podes?`

### `page_demo_video`

Use when a warm lead would benefit from seeing the available video/demo because
it makes the offer more concrete. This is not a blast. Choose carefully.

Good candidates:

- asked "como funciona?", "no entiendo", "mandame info", "me interesa", or
  similar;
- has not already received the same Loom/video-demo recently;
- would benefit from seeing how the page + WhatsApp flow looks in practice;
- has a clean latest outbound delivery status.

Action:

- Prefer the existing `send-loom`/configured video action when that is the
  correct video for the funnel and it has not already been sent.
- If the 24-hour custom window is closed, do not send custom text/media yet.
  Send an approved reopening template first and wait for the lead's reply before
  sending the video/demo.
- Before sending a video, inspect the funnel config/snapshot and available media
  paths. The relevant source assets include the Abogados 60s video/deck under
  `abogados/media/presentations/loom-video-vender-a-abogados/` and the
  Contadores page/campaign/WhatsApp video/deck under
  `media/presentations/loom-video-vender-a-contadores/`.
- If a separate page-demo video file is available but the production action API
  cannot send that media safely, do not invent a path. Report the lead and the
  exact video/media action needed for human handling or a server-side script.
- Pair the video with one short Frankie-style context message only if the send
  path supports it and the 24-hour window is open.

Abogados video context:

`Te mando este video porque muestra como se podria ver tu pagina de abogado y el flujo para que las consultas lleguen a tu WhatsApp. Miralo y si tiene sentido, decime que dia y horario podes y lo vemos 15 min.`

Contadores video context:

`Te mando este video porque muestra como se podria ver tu pagina de contador y el flujo para que las consultas de pymes lleguen a tu WhatsApp. Miralo y si tiene sentido, decime que dia y horario podes y lo vemos 15 min.`

### `manual_ping_template`

Use when the WhatsApp 24-hour custom window is closed and the lead is still
worth reopening. This is the approved template path for warm leads where we
would like to send a stronger custom follow-up or demo video, but cannot yet
because the window is closed.

Template:

`Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`

This must be sent through the existing manual ping quick action/template.

After the lead replies, reassess the conversation. If they are still warm, move
to `proactive_value_followup`, `page_demo_video`, or `close_call` instead of
sending another generic ping.

### `opener_followup`

Use for cold or stale leads that never replied to the opener, when they are not
excluded and have not recently received this same follow-up.

Contadores:

`Queria compartirte informacion sobre como podes obtener clientes para tu estudio contable`

Abogados:

`Queria compartirte información sobre como podrías recibir consultas de personas que estan buscando abogado en las áreas que trabajas.`

Use the configured approved template names from the funnel config/backend, not a
raw custom message outside the 24-hour window.

### `repair_delivery`

Use when the lead appears unresponsive but our outbound message failed.

Action:

- Requeue only if the message is outbound, failed/undelivered, not excluded, and
  retry budget makes sense.
- Do not requeue after final provider failures such as opt-out or repeated
  invalid/undeliverable numbers.

## Copy Style

Match Facu's WhatsApp style:

- No opening question marks.
- Simple and direct.
- Light personalization with first name when useful.
- It is acceptable to omit some accents when the template/copy already does.
- Do not sound corporate.
- Do not over-explain in the first message.
- The objective is to get a reply or a call time.
- Strong follow-ups should sound like Facu actually thought about the lead's
  case, not like a generic reminder.
- Use Frankie notes when writing value follow-up: outcome first, one concrete
  example, mechanism second, one next action.
- For leads who watched or received the video, continue the same arc as the
  Loom: outcome, pain in plain language, short mechanism, value/investment, and
  how to start.

## Video And Offer References

Use these references before choosing a proactive value or page-demo video send:

- Frankie offer method:
  `.codex/skills/konecta-frankie-video-offer/SKILL.md`
- Contadores sequence/video behavior:
  `.codex/skills/contadores-bot-sequence/SKILL.md`
- Contadores 60s page/campaign/WhatsApp framing:
  `media/presentations/loom-video-vender-a-contadores/Loom Script 60s.html`
- Abogados offer framing:
  `abogados/skills/abogados-funnel-offer/SKILL.md`
- Abogados 60s video framing:
  `abogados/skills/abogados-loom-video/SKILL.md`
  and `abogados/media/presentations/loom-video-vender-a-abogados/Loom-Script-60s.txt`

## Hourly Sequence Rules

The hourly automation should not blast the whole CRM every hour. It should
continue conversations that changed since the last run or have a clearly due
next step. It should also review warm leads that already received a delivered
message and decide if a stronger proactive follow-up is useful.

### Positive reply after opener

If the lead says yes, asks for information, or otherwise accepts the opener:

- Usually do nothing manually. The bot should send Loom intro and video after
  the configured silence window.
- Verify that the bot sent `loom_intro` and `loom_video`.
- If the bot did not send them and the lead is eligible, report or repair the
  automation path rather than writing a new manual sequence by hand.

### Positive reply after video

If the lead watched/accepted the video or asks how to continue:

- Send `close_call` copy if inside the 24-hour window.
- If outside the window, use `manual_ping_template` first and wait for reply.

### Already messaged warm lead

If the lead is warm but did not answer our last delivered outbound:

- Check whether the last message was just a generic ping or a weak close.
- If the 24-hour custom window is still open and the lead has enough context,
  consider `proactive_value_followup` instead of passively waiting.
- If the 24-hour custom window is closed and the lead is worth another attempt,
  send an approved reopening template rather than skipping them.
- If the lead likely needs to see the offer, consider `page_demo_video`.
- Do not send if the last outbound was very recent, if the same idea was already
  sent, or if the lead is not meaningfully warmer than a cold opener.
- Always record in the summary whether the lead was sent, skipped as too soon,
  skipped as duplicate, sent a reopen template, or skipped because there is no
  approved template/action available.

### Price or budget objection

If the lead asks price, budget, or "que presupuesto tienen":

- Send the price/budget copy from `close_call`.
- Goal: get a day/time for a 15-minute call.

### "Later" or scheduled intent

If the lead says they will resume later, like "retomo lunes":

- Do not keep pushing hourly.
- Report it as a timed follow-up.
- If a task/reminder mechanism exists, schedule the follow-up. Otherwise include
  it in the run summary.

### Auto-response

If the reply is clearly an auto-response or office greeting:

- Do not answer as if a human showed intent.
- Keep or report as low-priority/manual review.

### Negative or opt-out

If the lead rejects the offer or asks not to be contacted:

- Do not send more.
- Close/archive only if the existing CRM action supports it and the meaning is
  explicit.

## Provider Error Handling

- `131026`: usually invalid/not on WhatsApp/cannot receive business messages.
  Do not keep retrying after retry budget.
- `131049`: Meta ecosystem engagement block. Do not spam retries.
- `131050`: opted out of marketing. Never retry marketing follow-up.
- `130472`: Meta experiment group. Not fixable by copy.
- `131047`: 24-hour customer-service window closed. Use an approved template
  instead of custom copy.

## Verification Checklist After Sending

- Count queued message ids.
- Count statuses for those ids: delivered/sent/failed/undelivered.
- Confirm `due_undelivered=0` before ending when retries are expected.
- Group errors by Meta code.
- Check recent inbound messages after the send.
- Check `docker compose ps`.
- Check `/health`.
- Grep bot/backend logs for `Traceback`, `ERROR`, `database is locked`,
  `template`, auth failures, and `131047`.
- Confirm Workstation and Venezuelan exclusions.
