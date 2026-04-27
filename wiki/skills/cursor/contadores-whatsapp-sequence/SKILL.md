---
name: contadores-whatsapp-sequence
description: >-
  Defines the canonical WhatsApp follow-up sequence for contadores leads from
  Konecta Labs. Use when implementing, reviewing, or updating the bot flow that
  sends message 1, waits for any inbound reply, waits 30 seconds, sends message
  2 and message 3 (Loom URL only), waits 3 minutes, then sends message 4 and
  message 5 (Calendly URL only). Use env vars CONTADORES_LOOM_URL and
  CONTADORES_CALENDLY_URL instead of hardcoding links.
---

# Secuencia WhatsApp de contadores

## Variables obligatorias

- `CONTADORES_LOOM_URL`
- `CONTADORES_CALENDLY_URL`

Si faltan, no hardcodear links. La implementación debe fallar explícitamente o
dejar claro que falta configuración.

## Reglas del flujo

1. Enviar el mensaje 1 para leads de sheet/testing.
2. Cualquier respuesta entrante al mensaje 1 dispara la secuencia.
3. Si el primer inbound viene de un anuncio Click-to-WhatsApp con `referral.source_id` configurado, crear/reusar el lead y saltear el mensaje 1.
4. Esperar `30` segundos.
5. Enviar el mensaje 2.
6. Enviar enseguida el mensaje 3.
7. Esperar `3` minutos.
8. Enviar el mensaje 4.
9. Enviar enseguida el mensaje 5.

## Reglas de contenido

- El mensaje 2 no lleva link.
- El mensaje 3 debe ser solo la URL de `CONTADORES_LOOM_URL`.
- El mensaje 4 no lleva link.
- El mensaje 5 debe ser solo la URL de `CONTADORES_CALENDLY_URL`.
- No mezclar el texto del mensaje 2 con el link del Loom.
- No mezclar el texto del mensaje 4 con el link del Calendly.
- El trigger es mecánico: cualquier respuesta sirve; no hace falta clasificar intención.

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
{CONTADORES_LOOM_URL}
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
- Para Click-to-WhatsApp, rutear por `referral.source_id` contra `whatsapp_referral_source_ids`, no por el texto editable que envia el usuario.
- El ping manual `contadores_manual_ping_es_v1` es solo una accion del CRM.
- La accion CRM `send-manual-booked` envia ese ping manual y marca el lead como
  `booked`; no debe ejecutarse desde ticks automaticos.
- Modelar los delays como `30 s` y `3 min`, no aproximarlos en texto libre.
- Si más adelante cambia el copy, mantener esta skill como fuente canónica del orden
  y de la separación entre texto y URL.
