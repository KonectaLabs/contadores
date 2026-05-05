---
name: contadores-lead-reply-playbook
description: Use when drafting or sending WhatsApp replies to Contadores, Abogados, or Konecta CRM leads based on the current CRM context, previous bot/operator messages, lead stage, needs_reply status, objections, price/domain questions, video follow-ups, "lo analizo/te aviso" replies, booking intent, or when the user asks what to answer, to reply to needs attention leads, or to use proven past messages instead of invented copy.
---

# Contadores Lead Reply Playbook

Use this skill to answer live CRM leads with context-aware, proven copy.

The operating principle is: do not invent from memory. Inspect the CRM, find
similar conversations and previous operator messages, then adapt the smallest
useful version to the current lead.

## Related Skills

Read these when the task touches their area:

- `contadores-crm-followup-automation`: live CRM API, exclusions, send rules,
  `needs_reply`, production snapshot, and verification.
- `contadores-bot-sequence`: opener, Loom/video, conversational bot replies,
  scheduling handoff, manual Calendly actions, manual ping, 24-hour window, and
  human handoff behavior.
- `konecta-frankie-video-offer`: outcome-first offer framing. Use especially
  for price, value, and stronger follow-up copy.

For reusable copy examples, read [references/copy-bank.md](references/copy-bank.md).

## Non-Negotiables

- Treat the real production CRM as source of truth for live leads.
- When the user asks "que le respondo", draft only.
- Send only when the user explicitly says "responde", "mandalo", "responde a
  todos", or otherwise clearly asks for live action.
- When sending, use the production API from `contadores-crm-followup-automation`
  and verify message id plus delivery status.
- Never print `INTERNAL_API_TOKEN`.
- Do not send custom/free-text WhatsApp messages outside the 24-hour customer
  service window. Use allowed templates or report that the window is closed.
- Do not message closed, booked, archived, excluded, Venezuelan, or Workstation
  client leads unless the user explicitly asks to override and the system allows it.
- If the latest inbound is audio/media only and there is no transcript, do not
  guess the content. Ask for a transcript or inspect available media first.
- If the lead gives a concrete day/time for a call, treat it as booking intent.
  Do not send a generic follow-up or Calendly automatically. Ask only for the
  missing scheduling detail, usually email or timezone, and escalate once email,
  day, and time are available.

## Context Checklist

Before drafting or sending, inspect:

1. Funnel: `abogados`, `contadores`, or another niche.
2. Lead name, country, and tone used by the lead.
3. Current stage and `manual_reply_status`.
4. Latest inbound and latest outbound.
5. Last 10-30 messages, especially:
   - whether the video was sent;
   - whether the bot already sent `ai_reply` or
     `scheduling_handoff_confirmation`;
   - whether Calendly was already sent;
   - whether price, guarantee, page, domain, or objections were discussed;
   - whether an operator already sent a similar follow-up.
6. Delivery status of the latest outbound.
7. Whether the WhatsApp custom window is open.

Use the current production snapshot:

```bash
set -a
source .env >/dev/null 2>&1
set +a
curl -fsS \
  -H "Host: contadores.fgoiriz.com" \
  -H "X-Internal-Token: ${INTERNAL_API_TOKEN}" \
  "http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=30" \
  -o /tmp/contadores-followup-snapshot.json
```

List live attention leads:

```bash
jq -r '
  .leads[]
  | select(.manual_reply_status=="needs_reply")
  | "---\nlead_id=\(.id) funnel=\(.funnel_id) name=\(.full_name // "") stage=\(.stage)\nIN: \(.latest_inbound.text // "" | gsub("\n"; " / "))\nOUT: \(.latest_outbound.text // "" | gsub("\n"; " / "))"
' /tmp/contadores-followup-snapshot.json
```

Search old examples before choosing copy:

```bash
sqlite3 -header -csv data/snapshots/database-prod-2026-05-02.sqlite "
SELECT l.funnel_id, coalesce(l.full_name,'') AS name, m.created_at,
       replace(m.text,char(10),' / ') AS lead_text,
       replace((SELECT n.text
                FROM contadores_messages n
                WHERE n.lead_id=m.lead_id
                  AND n.from_me=1
                  AND n.created_at > m.created_at
                ORDER BY n.created_at
                LIMIT 1), char(10), ' / ') AS next_our_text
FROM contadores_messages m
JOIN contadores_leads l ON l.id=m.lead_id
WHERE m.from_me=0
  AND lower(m.text) LIKE '%precio%'
ORDER BY m.created_at DESC
LIMIT 40;
"
```

## Tone

- Match the lead. For formal lawyers in Bolivia/Paraguay, prefer `usted`,
  `le`, `su estudio`, `quedamos atentos`.
- For informal chats where the operator already used `tu`/`vos`, keep that tone.
- Keep messages WhatsApp-native: short paragraphs, direct language, no corporate
  polish.
- Do not write like a polished AI assistant. Match Facu/operator examples.
- Do not use inverted opening punctuation. Write `Que dia le queda?`, not
  `¿Que dia le queda?`.
- It is fine if the syntax is not perfectly formal. Prefer natural WhatsApp
  wording like `aca`, `campanas`, `reunion`, `Ok no hay problema`, and simple
  closing `?`.
- Avoid robotic filler such as `espero que se encuentre bien`,
  `con gusto le informo`, `quedo atento a sus comentarios`, or long corporate
  transitions.
- Prefer simple Spanish without overexplaining.
- Use the local house words unless the existing conversation differs:
  `pagina`, `campanas`, `reunion`, `WhatsApp`, `300 USD`.
- Avoid hype. Do not sound like a generic sales bot.

## Offer Framing

Use Frankie-style value order:

```text
La inversion es de 300 USD, pago unico.

A cambio usted recibe [beneficio concreto].

Eso lo logramos mediante [mecanismo/servicio].

[Siguiente paso concreto].
```

Do not lead with the service list:

```text
Malo: Por 300 USD hacemos pagina web y campanas.
Bueno: La inversion es de 300 USD. A cambio recibe mas oportunidades de clientes potenciales directo a su WhatsApp. Eso lo logramos mediante una pagina profesional y 3 campanas.
```

For Abogados, the benefit is not generic "marketing":

- more potential client inquiries direct to WhatsApp;
- more opportunities in the legal areas they want to prioritize;
- cases/consultas that fit the type of work they actually want.

For Contadores:

- more prospect/client inquiries direct to WhatsApp;
- opportunities for accounting services;
- avoid legal-area wording.

## Decision Patterns

### Conversational bot routing

The production bot should answer known questions and keep the lead in the same
stage. Price, inclusions, country, process, domain, existing page, guarantee,
"no vi el video", "lo analizo", and simple confirmations should not become
`needs_human` by default.

Use `needs_human` only when there is an uncovered situation, missing real data,
an exclusion, an explicit opt-out, audio/media without transcript, or complete
scheduling details that Facu must coordinate.

The bot does not book Google Calendar or Calendly in v1. It collects email, day,
time, and timezone when needed. Once those details are complete, it confirms by
WhatsApp that Facu will coordinate and the CRM alert must carry the details.

### Lead says "lo analizo", "consulto", "retornamos", "te aviso"

The user prefers not to answer only "ok". Add useful conversion context, then
move toward a short call.

Use this structure:

1. Acknowledge.
2. Add one concrete reason/value point.
3. Explain mechanism briefly.
4. Ask for a meeting or leave a clear next step.

Abogados shape:

```text
Perfecto {name}.

Para que lo tengan presente al analizarlo: la idea es hacerle una pagina web a medida para usted, que lo haga ver muy profesional, y campanas publicitarias para atraer exactamente al cliente ideal suyo, segun la rama del derecho que mas le interese trabajar.

Si todo queda claro y les interesa la propuesta, lo unico que queda es una reunion para conocernos y ver como empezar.

Cualquier consulta nos avisa.
```

If the lead is very formal:

```text
Ok entendido {name}, quedamos a la espera de su evaluacion.

Para que lo tenga presente, la idea es atraer consultas de potenciales clientes directo a su WhatsApp, mediante una pagina profesional y campanas enfocadas en las areas legales que usted quiera priorizar.

Cualquier consulta nos avisa.
```

### Lead has not watched the video yet

Do not over-sell before they watch it. Keep it light, but still frame value.
If the lead says they are driving, busy, or cannot watch right now, tell them
to watch later and also summarize the proposal by text. The user prefers this
because it keeps the conversation moving even before they watch the video.

```text
Ok no hay problema!

Cuando pueda mire el video, son 60 segundos donde explicamos la propuesta a detalle.

Cualquier duda aca estamos.
```

If it is Contadores:

```text
Ok perfecto, son 60 segundos donde intentamos explicar la propuesta a detalle.

Ante cualquier duda estamos a disposicion.
```

Driving/busy Abogados shape:

```text
Ok no hay problema!

Cuando pueda mire el video, son 60 segundos donde explicamos la propuesta a detalle.

Igual se lo resumo por aca: la idea es que usted reciba mas oportunidades de clientes potenciales directo a su WhatsApp.

Eso lo logramos mediante una pagina web profesional para su estudio y 3 campanas publicitarias enfocadas en las areas legales que usted quiera priorizar.

Cualquier duda aca estamos.
```

Driving/busy Contadores shape:

```text
Ok no hay problema!

Cuando pueda mire el video, son 60 segundos donde explicamos la propuesta a detalle.

Igual se lo resumo por aca: la idea es que usted reciba mas oportunidades de clientes potenciales directo a su WhatsApp.

Eso lo logramos mediante una pagina web profesional para su estudio contable y 3 campanas publicitarias enfocadas en los servicios que quiera vender.

Cualquier duda aca estamos.
```

### Lead watched or says "Ok" after video or AI reply

If they only confirm they watched, ask what they thought or move to the call.
If the bot already sent an AI reply and they ask a concrete question, answer the
question directly.

```text
Que le parecio? Esta interesado?
```

or:

```text
Para avanzar solo falta una reunion corta de 15 minutos, nos conocemos, vemos su caso y definimos los detalles. Que dia le queda mejor?
```

### Lead asks price

Use benefit-first framing.

Abogados:

```text
Si, la inversion es de 300 USD, pago unico.

A cambio usted recibe mas oportunidades de clientes potenciales directo a su WhatsApp.

Eso lo logramos mediante una pagina web profesional y personalizada para su estudio, y 3 campanas publicitarias enfocadas en las areas legales que usted quiera priorizar.

Para avanzar solo falta una reunion corta, nos conocemos, vemos su caso y definimos los detalles. Que dia le queda mejor?
```

If the exact lead message is "Cuanto cuesta?" after the video, answer directly
with the same benefit-first price frame:

```text
La inversion es de 300 USD, pago unico.

A cambio usted recibe mas oportunidades de clientes potenciales directo a su WhatsApp.

Eso lo logramos mediante una pagina web profesional y personalizada para su estudio, y 3 campanas publicitarias enfocadas en las areas legales que usted quiera priorizar.

Para avanzar solo falta una reunion corta, nos conocemos, vemos su caso y definimos los detalles. Que dia le queda mejor?
```

Contadores:

```text
Si, la inversion es de 300 USD, pago unico.

A cambio usted recibe mas oportunidades de clientes potenciales directo a su WhatsApp.

Eso lo logramos mediante una pagina web profesional y personalizada para su estudio contable, y 3 campanas publicitarias enfocadas en los servicios que quiera vender.

Para avanzar solo falta una reunion corta, nos conocemos, vemos su caso y definimos los detalles. Que dia le queda mejor?
```

### Lead asks "que incluye"

Answer price as value received, then specify inclusions.

```text
La inversion es de 300 USD, pago unico.

A cambio usted recibe mas oportunidades de clientes potenciales directo a su WhatsApp.

Eso incluye una pagina web profesional y personalizada, posicionamiento basico, y el armado y optimizacion de 3 publicidades.

La idea es que las consultas lleguen ordenadas a su WhatsApp. Para avanzar solo falta una reunion corta para ver su caso y definir detalles.
```

### Lead asks about domain

There were no strong historical domain replies in CRM. Use a safe answer:

```text
El dominio lo vemos con usted: si ya tiene uno, trabajamos sobre ese; y si no tiene, definimos cual conviene usar para su estudio y lo conectamos a la pagina.
```

Combine with price when they ask both:

```text
La inversion es de 300 USD, pago unico.

A cambio usted recibe mas oportunidades de clientes potenciales directo a su WhatsApp.

Eso lo logramos mediante una pagina web profesional y personalizada para su estudio, y 3 campanas publicitarias enfocadas en las areas legales que usted quiera priorizar.

El dominio lo vemos con usted: si ya tiene uno, trabajamos sobre ese; y si no tiene, definimos cual conviene usar para su estudio y lo conectamos a la pagina.

Para avanzar solo falta una reunion corta, nos conocemos, vemos su caso y definimos esos detalles. Que dia le queda mejor?
```

### Lead already has a page

Do not repeat "we build you a page" as if they do not have one. Offer to work on
or optimize the existing asset.

```text
Exacto, si ya la tiene creada nosotros trabajamos sobre optimizar eso.

Me pasaria su pagina web para verla?
```

If pushing to call:

```text
Podemos trabajar sobre su pagina actual, mejorarla, sumar SEO y hacer campanas.

Solo faltaria conocernos y definir metodo de pago. Cuando puede una llamada?
```

If they ask for cheaper because they already have a page, do not immediately
discount unless the user asks for that strategy. Prefer:

```text
Si, podemos evaluar su situacion y realizarle un plan personalizado. Le parece bien si agendamos una reunion y analizamos su caso? Cuando le seria conveniente?
```

### Lead asks "como funciona" or "proceso"

Use outcome first, then process:

```text
La idea es que le lleguen consultas de potenciales clientes directo a su WhatsApp.

Eso lo hacemos con una pagina web moderna y campanas publicitarias enfocadas en el tipo de cliente que usted quiere atraer.

Despues usted responde esas consultas, agenda llamadas y decide cuales tomar.

Para avanzar hacemos una reunion corta, vemos su caso, definimos metodo de pago y empezamos a trabajar.
```

### Lead says price is high or asks for guarantee

Use guarantee only when it fits the existing commercial copy and current policy.
Do not guarantee legal outcomes, revenue, rankings, or closed cases.

Allowed style:

```text
Tenga en cuenta que usted contaria con un sitio renovado o hecho de cero, y campanas enfocadas en atraer consultas a su WhatsApp.

Si no le traemos clientes interesados a su WhatsApp en 30 dias, le devolvemos el dinero.
```

If asking about budget:

```text
Cuanto estaria dispuesto a invertir? Seria diferente si se le permitiese el pago en cuotas?
```

### Lead asks if it is a scam or asks for trust

Use concrete proof, not defensiveness:

```text
Puede ver nuestra pagina aqui: https://www.konectalabs.com

Tambien puedo mostrarle trabajos que estamos haciendo para otros abogados.
```

If they ask about location:

```text
No tenemos oficinas en su ciudad, somos argentinos y trabajamos de forma remota, pero operamos sin problemas en toda latinoamerica.
```

### Lead says no, not candidate, or stop

Do not push. Acknowledge and stop.

```text
Entendido, muchas gracias.
```

If ambiguous "ahora no puedo":

```text
Perfecto, te entiendo.

Igual te pregunto algo rapido para no dejarlo tan en el aire: cuando decis que en este momento no podes, es por un tema de tiempos, presupuesto o porque ahora no estas buscando tomar mas casos?
```

## Sending Workflow

When the user asks to send:

1. Fetch a fresh snapshot.
2. Confirm the latest inbound still matches the message being answered.
3. Confirm `manual_reply_status=="needs_reply"` unless the user explicitly asks
   to message another lead.
4. Confirm exclusions are empty.
5. Send with the follow-up message endpoint.
6. Verify latest outbound id, text, and delivery status.

Send template:

```bash
jq -n --arg text "$TEXT" '{text:$text,dedupe_hours:24}' \
  | curl -fsS \
    -H "Host: contadores.fgoiriz.com" \
    -H "X-Internal-Token: ${INTERNAL_API_TOKEN}" \
    -H "Content-Type: application/json" \
    -X POST --data-binary @- \
    "http://149.50.136.121/api/contadores/followup/leads/${LEAD_ID}/messages"
```

Report back with:

- lead name;
- queued message id;
- delivery status;
- whether `needs_reply` cleared.
