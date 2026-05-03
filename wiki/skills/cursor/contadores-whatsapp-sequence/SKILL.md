---
name: contadores-whatsapp-sequence
description: >-
  Defines the canonical WhatsApp follow-up sequence for contadores leads from
  Konecta Labs. Use when implementing, reviewing, or updating the bot flow that
  sends message 1, waits for any inbound reply, waits 30 seconds, sends message
  2 and message 3 (WhatsApp MP4), waits, then sends the video check and
  either recaps the service after a simple watched-video confirmation or sends
  the Calendly handoff when classification says the lead wants to proceed.
---

# Secuencia WhatsApp de contadores

## Variables obligatorias

- Calendly fijo: `https://calendly.com/facundogoiriz/crecimiento`
- Funnel `loom_mp4.media_path`

## Reglas del flujo

1. Enviar el mensaje 1 para leads importados desde sheet.
2. Cualquier respuesta entrante al mensaje 1 dispara la secuencia.
3. Si el primer inbound viene de un anuncio Click-to-WhatsApp con `referral.source_id` configurado, crear/reusar el lead y saltear el mensaje 1. La frase aprobada de Abogados `Hola! Quiero mas informacion de su propuesta para abogados!` hace lo mismo cuando no hay reply/referral usable.
4. Esperar `30` segundos.
5. Enviar el mensaje 2.
6. Enviar enseguida el mensaje 3 como WhatsApp MP4.
7. Esperar la ventana configurada.
8. Enviar el video check si no hubo respuesta.
9. Clasificar las respuestas post-video con DSPy:
   `wants_to_proceed`, `watched_video_confirmation`, o `needs_human`.
10. Si la clasificacion dice `watched_video_confirmation`, generar con DSPy un
    recap del servicio adaptado al funnel y al pais inferido por telefono,
    encolado dentro del mismo paso `loom_intro`.
11. Si la clasificacion dice `wants_to_proceed`, enviar Calendly.
12. Si la clasificacion dice `needs_human`, pausar y pasar a Manual.

## Reglas de contenido

- El mensaje 2 no lleva link.
- El mensaje 3 debe ser el MP4 configurado, no un link de Loom.
- El mensaje 4 no lleva link.
- El recap post-video no lleva Calendly.
- El mensaje de link Calendly debe ser solo `https://calendly.com/facundogoiriz/crecimiento`.
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
  importantes: `131026` suele indicar numero no registrado en WhatsApp o
  destinatario que no puede recibir mensajes de empresa; `131047` indica ventana
  de 24 horas cerrada para mensajes no-template.
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
WhatsApp MP4 desde loom_mp4.media_path
```

### Mensaje 4

Enviar después de la espera post-Loom solo si no hubo respuesta.

```text
conseguiste ver el video?
```

### Recap post-video

Enviar solo cuando la clasificacion DSPy devuelve
`watched_video_confirmation`: el lead apenas confirmo que vio el video, sin
pregunta, objecion, fecha ni pedido claro de avanzar.

Esa clasificacion es interna del LLM. No crear una fase nueva del CRM ni
mostrarla como pipeline separado; el lead sigue en `awaiting_video_reply`.

El backend debe generar este mensaje con DSPy, no con regex ni match por texto.
Inputs obligatorios del generador:

- `funnel_id`;
- `funnel_label`;
- telefono del lead;
- batch de respuestas post-Loom.

El mensaje debe explicar nuevamente que Konecta ayuda a conseguir mas consultas
de potenciales clientes directo al WhatsApp, mediante pagina web moderna y
campanas publicitarias a medida. Debe adaptar el nicho segun el funnel
(`contadores`, `abogados`, `mecanicos`, negocio general, etc.) y adaptar el
pais si el codigo telefonico es claro. Cierra preguntando que dia de esta
semana le queda mejor para una llamada corta.

Ejemplo de forma:

```text
Perfecto.

Nosotros lo que hacemos es ayudarle a conseguir mas consultas de potenciales clientes en Bolivia, directo a su WhatsApp.

Para eso le armamos una pagina web moderna y profesional, y ademas campanas publicitarias enfocadas en personas de Bolivia que puedan necesitar sus servicios legales.

La idea es que usted tenga una presencia mucho mas fuerte y que le lleguen oportunidades reales de clientes, sin tener que estar buscando manualmente.

Para avanzar, lo mejor seria una llamada corta donde le explicamos como se aplicaria a su caso. Que dia le queda mejor esta semana?
```

### Calendly intro

Enviar cuando la clasificacion dice `wants_to_proceed`.

```text
Esperamos que haya quedado todo claro luego de ver el video.
Para avanzar, el unico paso que falta de tu lado es elegir un horario en el calendario.
Elegi el horario que mejor te quede:
```

### Calendly link

Enviar inmediatamente despues del Calendly intro.

```text
https://calendly.com/facundogoiriz/crecimiento
```

## Notas de implementación

- Usar el Calendly fijo compartido por todos los funnels.
- Guardar la secuencia como mensajes separados. El recap post-video usa el
  `sequence_step=loom_intro` existente y deja el lead en `awaiting_video_reply`.
- Para Click-to-WhatsApp, rutear por `referral.source_id` contra `whatsapp_referral_source_ids`. No agregar ruteo amplio por texto editable.
- Excepcion aprobada: si el texto normalizado es `Hola! Quiero mas informacion de su propuesta para abogados!`, rutear a `abogados`.
- Si el inbound no matchea reply/referral/frase aprobada, guardarlo en el buzon `general`.
- Si Meta envia `contacts.profile.name`, usar ese nombre de perfil de WhatsApp para leads creados por WhatsApp y para completar leads existentes que solo tenian telefono.
- El ping manual `contadores_manual_ping_es_v1` es solo una accion del CRM.
- Las acciones masivas del CRM nunca deben preseleccionar `Manual ping`; el operador tiene que elegir explicitamente ese template antes de mandarlo.
- `Manual ping` masivo requiere confirmacion explicita en backend y debe quedar auditado como batch.
- No se puede mandar ningun WhatsApp outbound a un lead `closed`; primero hay que reabrirlo.
- Marcar un lead como `booked` no envia WhatsApp. El alias legacy
  `send-manual-booked` solo marca `booked`.
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
