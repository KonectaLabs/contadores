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

### `manual_ping_template`

Use only when the WhatsApp 24-hour custom window is closed and the lead is still
worth reopening.

Template:

`Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`

This must be sent through the existing manual ping quick action/template.

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

## Hourly Sequence Rules

The hourly automation should not blast the whole CRM every hour. It should
continue conversations that changed since the last run or have a clearly due
next step.

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

