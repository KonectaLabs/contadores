---
name: contadores-whatsapp-sequence
description: >-
  Defines the canonical WhatsApp follow-up sequence for contadores leads from
  Konecta Labs. Use when implementing, reviewing, or updating the bot flow that
  sends message 1, waits for any inbound reply, waits 30 seconds, sends message
  2 and message 3 (WhatsApp MP4), waits, then sends the video check and
  Calendly handoff when classification says the lead wants to proceed.
---

# Secuencia WhatsApp de contadores

## Variables obligatorias

- `CONTADORES_CALENDLY_URL` or `CONTADORES_CALENDLY_BASE_URL`
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
9. Si la clasificacion dice `wants_to_proceed`, enviar Calendly.

## Reglas de contenido

- El mensaje 2 no lleva link.
- El mensaje 3 debe ser el MP4 configurado, no un link de Loom.
- El mensaje 4 no lleva link.
- El mensaje 5 debe ser solo la URL de `CONTADORES_CALENDLY_URL`.
- No mezclar el texto del mensaje 2 con el MP4.
- No mezclar el texto del mensaje 4 con el link del Calendly.
- El trigger es mecánico: cualquier respuesta sirve; no hace falta clasificar intención.
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

Enviar `3` minutos después del mensaje 3.

```text
Esperamos que haya quedado todo claro luego de ver el video.
Para avanzar, el único paso que falta de tu lado es elegir un horario en el calendario y venir a la llamada con las dudas que te hayan quedado y un medio de pago listo para coordinar el pago de los USD 300.
Elige el horario que mejor te quede:
```

### Mensaje 5

Enviar inmediatamente después del mensaje 4.

```text
{CONTADORES_CALENDLY_URL}
```

## Notas de implementación

- Leer los links desde la capa de configuración.
- Guardar la secuencia como cinco mensajes separados.
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
