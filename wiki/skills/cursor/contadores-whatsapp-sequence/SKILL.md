---
name: contadores-whatsapp-sequence
description: >-
  Defines the canonical WhatsApp follow-up sequence for contadores leads from
  Konecta Labs. Use when implementing, reviewing, or updating the bot flow that
  sends message 1, waits for any inbound reply, waits 30 seconds, sends message
  2 and message 3 (text offer), waits, then sends the video check and
  runs the conversational bot to answer known questions, collect scheduling
  details, or hand off only when human action is truly needed.
---

# Secuencia WhatsApp de contadores

## Variables obligatorias

- Calendly sale de `calendly_base_url` del funnel activo.
- Funnel `text_offer_599.message_text`

## Reglas del flujo

1. Enviar el mensaje 1 para leads importados desde sheet.
2. Cualquier respuesta entrante al mensaje 1 dispara la secuencia.
3. Si el primer inbound viene de un anuncio Click-to-WhatsApp con `referral.source_id` configurado, crear/reusar el lead y saltear el mensaje 1. La frase aprobada de Abogados `Hola! Quiero mas informacion de su propuesta para abogados!` hace lo mismo cuando no hay reply/referral usable.
4. Esperar `30` segundos.
5. Enviar el mensaje 2.
6. Enviar enseguida el mensaje 3 como text offer.
7. Esperar la ventana configurada.
8. Enviar el video check si no hubo respuesta.
9. Ejecutar el bot conversacional con DSPy usando historial completo, funnel,
   stage, ultimos mensajes, pais/timezone inferidos cuando sea claro y reglas
   comerciales.
10. Si el bot responde una duda conocida, encolar `sequence_step=ai_reply` y
    mantener el lead en su stage actual.
    El copy debe sonar como Facu/operador por WhatsApp: natural, corto, no
    robotizado, y sin signos de apertura como `¿` o `¡`.
11. Si faltan datos de llamada, pedir solo email, dia, horario o timezone
    faltante con `sequence_step=ai_reply`.
12. Si ya estan email, dia y horario, confirmar por WhatsApp con
    `sequence_step=scheduling_handoff_confirmation`, pausar en `needs_human` con
    `automation_paused_reason=booking_details_collected` y alertar a Facu.
13. Si llega audio con `media_path`, guardar primero el audio reproducible y
    despues el transcript como inbound subsiguiente con
    `sequence_step=audio_transcript`.
14. Si falta informacion real para responder, hay audio/media sin transcript,
    exclusion, opt-out o caso no cubierto, pausar en `needs_human`.

## Reglas de contenido

- El mensaje 2 no lleva link.
- El mensaje 3 debe ser el MP4 configurado, no un link de Loom.
- El mensaje 4 no lleva link.
- Las respuestas del bot no llevan Calendly.
- El mensaje de link Calendly debe ser solo el `calendly_base_url` del funnel activo y solo se usa en acciones manuales.
- No mezclar el texto del mensaje 2 con el MP4.
- No mezclar el texto previo de Calendly con el link del Calendly.
- El trigger inicial hacia Loom es mecanico: cualquier respuesta al opener
  sirve; la clasificacion DSPy aplica despues del video.
- Todo envio fallido debe persistir error en `contadores_messages`, reintentarse
  hasta `CONTADORES_DELIVERY_MAX_ATTEMPTS`, y quedar visible en el CRM con alerta
  roja cuando se agotan los intentos. Si el operador marca el error como visto,
  el mensaje conserva el detalle del fallo, pero deja de contar para la alerta
  roja del chat.
- Si Meta manda `status=failed`, preservar los campos de error del webhook
  (`code`, mensaje y detalles) y mostrar una explicacion accionable. Casos
  importantes: `130472` indica destinatario bloqueado por un experimento de
  Meta; `131026` suele indicar numero no registrado en WhatsApp o destinatario
  que no puede recibir mensajes de empresa; `131047` indica ventana de 24 horas
  cerrada para mensajes no-template.
- Los envios no-template solo se pueden encolar dentro de las 24 horas desde el
  ultimo inbound del lead. Si la ventana esta cerrada, bloquear custom/media y
  pedir usar template aprobado, por ejemplo `Manual ping`.

## Copy canónico

### Mensaje 1

```text
Hola! Buen día, te escribimos desde Konecta Labs por el formulario para contadores sobre cómo conseguir clientes empresariales con pagos mensuales. ¿Es correcto?
```

### Mensaje 2

Enviar `30` segundos después de cualquier respuesta al mensaje 1.

```text
Perfecto. Te cuento rápido:
Los contadores que trabajan con nosotros reciben un flujo de prospectos y posibles clientes que les llega directo al WhatsApp de forma automática.
Te invito a que veas este video donde te explicamos la propuesta a detalle:
```

### Mensaje 3

Enviar inmediatamente después del mensaje 2.

```text
text offer desde text_offer_599.message_text
```

### Mensaje 4

Enviar después de la espera post-offer solo si no hubo respuesta.

```text
conseguiste ver el video?
```

### Bot conversacional post-offer

Despues de la quiet window, el backend debe llamar al bot conversacional con
DSPy, no con regex ni match por texto. Inputs obligatorios:

- `funnel_id`;
- `funnel_label`;
- telefono del lead;
- stage actual;
- historial completo;
- batch de respuestas post-offer;
- timezone inferida cuando el telefono lo permita.

Acciones permitidas: `send_reply`, `ask_scheduling_details`, `handoff_human`,
`handoff_scheduling`, `close_lead` y `no_action`.

El bot debe contestar dudas conocidas y mantener el stage: precio, que incluye,
pais/cobertura, garantia, proceso, dominio, pagina existente, no vio el video,
esta ocupado, lo analiza/consulta, y confirmaciones simples.

Las respuestas deben seguir estilo WhatsApp real: frases simples, no demasiado
perfectas, sin tono de asistente AI y sin signos de apertura. Usar `Que dia le
queda?`, no `¿Que dia le queda?`.

Cuando conviene avanzar a reunion, el bot pide email, dia, horario y timezone
solo si falta. La llamada default es de 15 minutos. Cuando los datos estan
completos, confirma que Facu coordina la llamada y pasa a `needs_human` para que
se agende manualmente.

Ejemplo de forma:

```text
Perfecto.

Nosotros lo que hacemos es ayudarle a conseguir mas consultas de potenciales clientes en Bolivia, directo a su WhatsApp.

Para eso le armamos una pagina web moderna y profesional, y ademas campanas publicitarias enfocadas en personas de Bolivia que puedan necesitar sus servicios legales.

La idea es que usted tenga una presencia mucho mas fuerte y que le lleguen oportunidades reales de clientes, sin tener que estar buscando manualmente.

Para avanzar, lo mejor seria una llamada corta donde le explicamos como se aplicaria a su caso. Que dia le queda mejor esta semana?
```

### Scheduling handoff

Enviar cuando el lead ya dio email, dia y horario:

```text
Perfecto, gracias.

Le paso estos datos a Facu para coordinar la llamada y le confirmamos por aca.
```

Despues marcar `needs_human`, guardar `booking_details_collected` y dejar email,
dia, horario, timezone y ultimo mensaje en la razon de clasificacion para el
email de alerta.

### Calendly manual

```text
{calendly_base_url del funnel activo}
```

## Notas de implementación

- Usar el `calendly_base_url` del funnel activo solo para acciones manuales.
- Guardar las respuestas del bot como `sequence_step=ai_reply`; el handoff de
  agenda usa `sequence_step=scheduling_handoff_confirmation`.
- Para Click-to-WhatsApp, rutear por `referral.source_id` contra `whatsapp_referral_source_ids`. No agregar ruteo amplio por texto editable.
- Excepcion aprobada: si el texto normalizado es `Hola! Quiero mas informacion de su propuesta para abogados!`, rutear a `abogados`.
- Si el inbound no matchea reply/referral/frase aprobada, guardarlo en el buzon `general`.
- Si Meta envia `contacts.profile.name`, usar ese nombre de perfil de WhatsApp para leads creados por WhatsApp y para completar leads existentes que solo tenian telefono.
- El ping manual `contadores_manual_ping_es_v1` es solo una accion del CRM.
- Las acciones masivas del CRM nunca deben preseleccionar `Manual ping`; el operador tiene que elegir explicitamente ese template antes de mandarlo.
- `Manual ping` masivo requiere confirmacion explicita en backend y debe quedar auditado como batch.
- No se puede mandar ningun WhatsApp outbound a un lead `closed`; primero hay que reabrirlo.
- La vista CRM muestra el hito como `Converted`. Storage/API todavia conservan
  `booked_at` y el alias legacy `send-manual-booked`; marcar `Converted`
  no envia WhatsApp y solo pausa automatizacion.
- La vista CRM `Manual` muestra todos los manuales; el pipeline tiene un bloque
  `Needs answer` entre Manual y Closed para los manuales cuyo
  `manual_reply_status` sigue en `needs_reply`.
- `Manual outbound` permite texto y uno o mas adjuntos. El operador puede
  elegir, arrastrar o pegar imagenes/archivos; el backend los guarda en
  `data/contadores/outbound_media/{lead_id}/` y el bot los envia como imagen,
  video, audio o documento de WhatsApp.
- Modelar los delays como `30 s` y `3 min`, no aproximarlos en texto libre.
- Si más adelante cambia el copy, mantener esta skill como fuente canónica del orden
  y de la separación entre texto y URL.
