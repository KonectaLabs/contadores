# Contadores

Repo de trabajo para el flujo de captación y seguimiento de `Contadores`.
El producto esta migrando a una plataforma de funnels por nicho: `contadores`
es el primer funnel operativo, y otros nichos se configuran desde la UI o desde
un archivo JSON persistente.

## Estructura

- `src/`: código de producto.
- `wiki/`: documentación, skills y referencias de trabajo.
- `media/`: materiales audiovisuales, decks y archivos de soporte.
- `abogados/`: materiales, presentaciones y skills entrenadas del funnel de abogados.
- `data/`: estado local persistente. No se commitea.

## Funnels por nicho

El backend siempre expone `contadores` y un buzon `general` para WhatsApp sin
referral reconocido. Los nichos de campaña, como `abogados`, se editan desde la
UI o desde el mismo JSON persistente.

Los funnels agregados desde la UI se guardan en:

- `FUNNELS_CONFIG_PATH`, si esta definido.
- `data/funnels.json`, si no esta definido.

Ese archivo es compartido por la UI y por Codex: un operador puede crear o
editar un funnel visualmente y Codex puede editar el mismo JSON cuando se le
pide agregar un nicho como `abogados`.

Ver funnels configurados:

```bash
curl http://127.0.0.1:8000/api/funnels
```

Cada funnel contiene:

- nombre e id del nicho;
- sheet URL/GID y filtro opcional;
- opener/template inicial;
- follow-up template;
- ping template manual para reabrir la ventana de WhatsApp;
- IDs de anuncios Click-to-WhatsApp (`whatsapp_referral_source_ids`);
- texto del video;
- estrategia WhatsApp MP4 (`loom_mp4`);
- bot conversacional Codex post-video/post-Calendly para responder dudas y pedir datos de llamada;
- `kind=campaign|inbox`, donde `inbox` no corre fases ni automatizacion;
- Calendly solo como accion manual;
- acciones manuales de Calendly: con mensaje previo o solo link;
- emails de alerta;
- ventanas de espera.

## Fuente de leads

Contadores ya no tiene switch de runtime. No existe un modo alternativo ni lead
sintético. El bot importa siempre desde la sheet configurada para el funnel.

Variables mínimas:

- `CONTADORES_SHEET_URL=...`
- `CONTADORES_SHEET_GID=...`

`docker-compose.yml` lee `.env` y `/api/runtime` muestra readiness sin exponer
secretos. El runtime queda `ready=false` hasta que la URL y el GID de la sheet
esten configurados.

## Desarrollo local

Instalar dependencias:

```bash
cd /Users/fgoiriz/private/repos/contadores
uv sync
```

Leer la sheet:

```bash
uv run python src/tools/read_google_sheet.py --as-records
```

Levantar el backend:

```bash
PYTHONPATH=src uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Desarrollar el frontend:

```bash
cd src/frontend
npm install
npm run dev
```

Compilar el frontend que sirve FastAPI:

```bash
cd src/frontend
npm run build
```

Verificar runtime:

```bash
curl http://127.0.0.1:8000/api/runtime
```

Verificar API de Contadores:

```bash
curl http://127.0.0.1:8000/api/contadores/config
```

Ejecutar un tick interno de Workstation desde el worker o localmente:

```bash
curl -X POST -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  http://127.0.0.1:8000/api/workstation/automation/tick
```

Snapshot read-only para automations de follow-up:

```bash
curl -H "Host: contadores.fgoiriz.com" \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  "http://149.50.136.121/api/contadores/followup/snapshot?limit=20000&messages_per_lead=12"
```

Export CSV del mismo snapshot:

```bash
curl -H "Host: contadores.fgoiriz.com" \
  -H "X-Internal-Token: $INTERNAL_API_TOKEN" \
  "http://149.50.136.121/api/contadores/followup/snapshot.csv?limit=20000&messages_per_lead=12"
```

Estos endpoints de snapshot no mandan mensajes ni mutan la base. Exponen todos
los chats recientes de `contadores` y `abogados`, ultimos mensajes, estado de
delivery, exclusiones fuertes y buckets sugeridos para que una automation pueda
analizar el CRM sin depender de SSH. Usar `include_all_funnels=true` si se quiere
incluir tambien inboxes/funnels fuera de Contadores y Abogados.

Acciones internas para automations de follow-up:

- `POST /api/contadores/followup/leads/{lead_id}/messages` con
  `{"text":"...", "dedupe_hours":24}` encola un mensaje manual si la ventana de
  WhatsApp esta abierta.
- `POST /api/contadores/followup/leads/{lead_id}/actions` con
  `{"action":"send-manual-ping"}` corre una accion existente del CRM.
- `PATCH /api/contadores/followup/leads/{lead_id}` cambia stage,
  clasificacion, tags o estado manual. No envia WhatsApp.

Runner horario de follow-up:

- El seguimiento horario activo corre como LaunchAgent local en la Mac, no como
  cron de Codex App. El cron de Codex App quedo pausado porque ese runtime puede
  no tener red hacia `149.50.136.121`, aunque esta maquina si la tenga.
- Cada hora se crea una ejecucion nueva de `codex exec`, lee
  `.codex/skills/contadores-crm-followup-automation/SKILL.md`, consulta la API
  de produccion y opera solo mediante endpoints internos aprobados o SSH al
  server real cuando hace falta debug.
- Requiere `INTERNAL_API_TOKEN` en `.env` local o en el entorno. El runner carga
  `.env`, pero nunca imprime el token.
- Instalar o actualizar el LaunchAgent:

```bash
scripts/install_contadores_crm_launchd.sh
```

- Ver estado:

```bash
launchctl print gui/$(id -u)/com.konecta.contadores.crm-followup
```

- Correrlo ahora:

```bash
launchctl kickstart -k gui/$(id -u)/com.konecta.contadores.crm-followup
```

- Logs y ultimo resumen:

```bash
ls -lt data/reports/contadores-crm-followup-*.log | head
cat data/reports/contadores-crm-followup-latest.md
```

- Vista visual local real de la Mac:

```bash
scripts/render_contadores_crm_runner_dashboard.py
open data/reports/contadores-crm-followup-dashboard.html
```

  El HTML se regenera en cada corrida del LaunchAgent y lee directamente
  `launchctl`, `data/reports/`, `data/locks/` y los logs locales de la Mac.
  La pantalla prioriza el delta contra la corrida anterior: nuevos replies,
  cambios de estado, cambios de delivery, proximos pasos que quedaron due y
  acciones humanas. Despues muestra el ultimo run, historial acumulado como
  Markdown renderizado, timeline y un panel para copiar un prompt o comando
  `codex exec` con el contexto del run.
- Vista visual remota: entrar al backoffice y abrir la seccion `Runner`. La UI lee
  `GET /api/contadores/followup/runner/status` y muestra primero el delta
  estructurado, despues el ultimo resumen, historial acumulado y timeline.
  Los logs/stdout quedan colapsados como detalles tecnicos. Esta ruta
  queda protegida por sesion o `X-Internal-Token`; no es publica.
- El LaunchAgent local tambien sincroniza su ultimo estado al server real con
  `POST /api/contadores/followup/runner/status`, usando `INTERNAL_API_TOKEN`.
  Asi el backoffice desplegado puede mostrar el ultimo resumen/log tail aunque
  la ejecucion haya corrido en la Mac.

Verificar API de funnels:

```bash
curl http://127.0.0.1:8000/api/funnels
```

Configurar pesos de estrategias:

- `CONTADORES_STRATEGY_WEIGHTS_JSON='{"loom":{"loom_mp4":100}}'`
- También se puede cambiar desde `Settings` en el backoffice.
- Los pesos son porcentajes de rollout por paso. Cambiarlos afecta nuevas asignaciones; las asignaciones ya guardadas no se reescriben.

Template manual de ping:

- Nombre default: `contadores_manual_ping_es_v1`.
- Texto default: `Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`.
- Se envia solo desde la accion manual del backoffice; no participa del tick automatico ni del follow-up de 24 horas.
- Las acciones masivas del CRM no deben preseleccionar `Manual ping`; el operador tiene que elegir ese template explicitamente.
- `Manual ping` en bulk requiere confirmacion explicita en el payload/UI y queda auditado como batch.
- No se puede mandar ningun WhatsApp outbound a un lead `closed`; primero hay que reabrirlo.
- Marcar un lead como `booked` no envia WhatsApp. El alias legacy `send-manual-booked` queda soportado, pero solo marca `booked`.

Entrada Click-to-WhatsApp:

- Cada funnel puede declarar `whatsapp_referral_source_ids` en `data/funnels.json`.
- Contadores no debe tener IDs cargados si no tiene campaña real. Hoy el source_id real queda en `abogados`.
- Cuando Meta envia un webhook con `referral.source_id` configurado, el backend crea o reutiliza un lead `whatsapp_ctwa`.
- Si el webhook trae el nombre de perfil de WhatsApp, se guarda como `full_name` para leads nuevos de WhatsApp y para leads existentes que todavia no tenian nombre.
- Ese lead queda como si ya hubiese respondido al opener: no se encola el template inicial y el tick automatico pasa al Loom despues de `initial_reply_quiet_seconds`.
- Por defecto no se usa el texto prellenado del anuncio para rutear porque el usuario puede editarlo antes de enviarlo.
- Excepcion aprobada: el texto normalizado `Hola! Quiero mas informacion de su propuesta para abogados!` rutea directo a `abogados` cuando no hay reply/referral usable.
- Si no hay `referral.source_id`, ni frase aprobada, ni match de funnel, el mensaje se guarda como lead en el buzon `general`.
- El servicio `bot` guarda cada webhook inbound de WhatsApp en
  `BOT_WEBHOOK_INBOX_PATH` antes de llamar al backend. Si el backend esta caido,
  el evento queda en ese SQLite y se reintenta en el worker hasta que
  `/api/contadores/whatsapp/inbound` lo acepte.
- El backend trata `external_id`/`wamid` inbound como idempotente. Si Meta
  reintenta un webhook ya guardado, devuelve `processed` sin duplicar el mensaje.

Buzon General:

- `general` es un inbox, no una campaña: no tiene pipeline de fases ni sheet sync.
- Los chats que entran por WhatsApp sin formulario pueden mostrar el nombre de perfil de WhatsApp si Meta lo envia en el webhook.
- Permite chatear, mandar el mensaje inicial o el ping general.
- Desde la UI se puede mover un chat a una campaña existente y elegir la fase inicial.

Tags:

- Los leads tienen tags libres de operador y filtro por tag.
- Los importados desde formulario reciben el tag `form`.
- Los creados desde un funnel Click-to-WhatsApp reciben el tag `whatsapp_funnel`.
- Los creados desde WhatsApp sin funnel matcheado reciben el tag `whatsapp`.
- La UI muestra tags en el detalle como solo lectura; para cambiarlos hay que seleccionar leads y usar la accion batch `Set tags`.
- El filtro por tag se combina con las fases, busqueda y estrategia.

Bot conversacional post-video y post-Calendly:

- Luego del Loom/video y de la ventana de silencio, el backend llama a
  `ContadoresConversationBotProgram` con historial completo, funnel, stage,
  ultimos mensajes y timezone inferida por telefono cuando sea claro.
- La ventana de silencio funciona como backoff real: el backend bloquea el
  procesamiento conversacional por lead, relee el batch actual antes de correr
  la AI y vuelve a validarlo antes de encolar. Si entra otro inbound mientras la
  AI genera, descarta esa respuesta vieja y espera la proxima ventana quieta.
- El runtime principal es Codex SDK con `CONVERSATION_BOT_CODEX_MODEL`
  (`gpt-5.5` por defecto) y `CONVERSATION_BOT_CODEX_EFFORT=medium`, usando las
  skills `contadores-bot-sequence` y `contadores-lead-reply-playbook` como
  contexto estructurado.
  Puede inspeccionar archivos del repo y usar herramientas read-only para
  resolver dudas de source of truth; no debe modificar archivos ni estado
  externo durante una decision runtime.
- Orden de fallback: primero ChatGPT Codex, despues Codex autenticado con API
  key, y recien despues DSPy/Grok. Si falla ChatGPT Codex, el lead no se pausa
  por eso: se crea una alerta runtime por email con link/comando para
  reautenticar y se responde con el siguiente fallback disponible. El fallback usa
  `OPENROUTER_GROK_4_3_MODEL=openrouter/x-ai/grok-4.3` cuando hay
  `OPENROUTER_API_KEY`; si no, usa `gpt-5.4-mini`. Si todos fallan, ahi si
  pasa a `needs_human`.
- El bot devuelve una accion estructurada:
  `send_reply`, `ask_scheduling_details`, `handoff_human`,
  `handoff_scheduling`, `close_lead` o `no_action`.
- Preguntas conocidas de precio, pais/cobertura, garantia, proceso, dominio,
  pagina existente, "no vi el video", "lo analizo" o confirmaciones simples se
  responden con `sequence_step=ai_reply` y, si vienen del post-Loom, mueven el
  lead a `needs_human`/Manual con
  `automation_paused_reason=ai_reply_conversation`. Como la AI ya contesto, el
  `manual_reply_status` queda `answered`.
- Si el lead rechaza el servicio o dice que no quiere avanzar, el bot envia
  exactamente `1) Muy caros los 300 dolares`, `2) No me sirve la pagina web +
  publicidades`, `3) No es mi momento para invertir`, `4) Otro motivo`, con
  `sequence_step=ai_rejection_survey`, y cierra el lead para no responder mas.
- El origen/identidad de Konecta no se infiere del pais del lead. El prompt y
  un guardrail post-modelo usan el source of truth del repo `konecta-labs`:
  Konecta Labs, trade name de Octopy LLC, equipo founder-led de IA aplicada,
  fundado por Facundo Goiriz y Alan Kravchuk. Ese mismo bloque tambien fija la
  operacion completa del funnel: ICP por Contadores/Abogados, objetivo,
  mecanismo, entrega remota, precio, garantia, limites de promesa, paises,
  scheduling y cosas que no se pueden inventar. Para `De donde son?` la
  respuesta canonica es `Escribo desde Argentina. Somos Konecta Labs y
  trabajamos remoto para toda Latinoamerica.` Nunca debe contestar `Somos de
  Ecuador` ni copiar el pais del lead como origen nuestro.
- El copy del bot debe sonar a WhatsApp real de Facu/operador: natural, corto,
  no robotizado, sin signos de apertura como `¿` o `¡`, y sin frases
  corporativas de asistente AI.
- El bot no debe repetir la pregunta del lead como encabezado ni arrancar con
  frases tipo `Para estar claros:`. Si el lead pregunta que cuenta como
  consulta/prospecto, responde que es una oportunidad real que llega a WhatsApp,
  no un cliente cerrado, y no pide email/dia/horario en ese mismo mensaje.
- Si falta email, dia, horario o zona horaria para una llamada, el bot pide solo
  el dato faltante. La llamada default es de 15 minutos.
- Cuando ya tiene email, dia y horario, confirma por WhatsApp con
  `sequence_step=scheduling_handoff_confirmation`, pausa el lead en
  `needs_human`, guarda `automation_paused_reason=booking_details_collected` y
  deja email/dia/horario/timezone en `last_classification_reason` para la alerta
  por email.
- Los audios inbound se transcriben antes de llegar al bot con
  `OPENAI_AUDIO_TRANSCRIPTION_MODEL=gpt-4o-transcribe` por defecto. Si WhatsApp
  entrega `.ogg`, Docker incluye `ffmpeg` para convertirlo a un formato aceptado
  por OpenAI. Si sale bien, el audio queda como mensaje reproducible y el
  transcript se guarda como el siguiente inbound con
  `sequence_step=audio_transcript`. Si descarga/transcripcion falla, se conserva
  el audio reproducible y recien ahi pasa como media sin transcript.
- El bot no inventa audio/media sin transcript. Imagen, video, documento,
  sticker o audio fallido sin texto pasan a humano.
- Cerrados, booked, archivados, excluidos, Venezuela y Workstation siguen
  bloqueados por los guards existentes.

Acciones manuales de Calendly:

- `Calendly with intro` encola el texto previo y despues el link de Calendly.
- `Calendly link only` encola solo el link de Calendly.
- El link de Calendly es siempre `https://calendly.com/facundogoiriz/crecimiento`, para Contadores, Abogados y cualquier otro funnel.
- Ambas acciones registran `calendly_sent_at` y mantienen el lead en Manual.
- La automatizacion nueva no manda Calendly automaticamente. Para avanzar, el
  bot pide email, dia y horario para que Facu coordine la llamada manualmente.
- Hoy el codigo no crea eventos de Google Calendar ni Calendly desde texto
  libre; cuando junta los datos, marca `booking_details_collected`, pausa en
  `needs_human` y dispara la alerta por email.

Promo solo pagina:

- Si un lead responde positivamente a la promo de pagina barata, el bot manda
  automaticamente un video de ejemplo reutilizable segun funnel:
  `data/contadores/videos/cliente-pagina.mp4` para contadores o
  `data/contadores/videos/pagina-abogado.mp4` para abogados.
- Si el lead vuelve a responder con interes despues del ejemplo, se crea un
  `WorkstationClient` idempotente con `work_type=solo_pagina`,
  `status=pending_payment`, `automation_status=intake` y el precio fijo de la
  promo en `offer_price_usd`.
- Para leads que quedaron en Manual por manejo humano, la UI muestra una accion
  `Solo page`. Esa accion crea el mismo Workstation `solo_pagina`: si el chat
  viejo ya trae datos utiles del estudio/servicios, Workstation genera el
  boceto directamente; si solo trae interes generico, primero manda el intake.
- El CRM queda pausado con
  `automation_paused_reason=workstation_solo_page_started`; desde ese punto
  responde el tick de Workstation, no el bot comercial.
- Los pasos nuevos de secuencia son
  `auto_accountant_page_example_video`, `auto_lawyer_page_example_video`,
  `workstation_intake`, `workstation_preview_video`,
  `workstation_revision_video`, `workstation_ping_1`,
  `workstation_ping_2` y `workstation_handoff`.

Vista Manual del backoffice:

- `Manual` muestra todos los leads manuales.
- `Needs answer` aparece como un bloque del pipeline entre `Manual` y `Closed`.
- Al marcarlos como respondidos, salen de `Needs answer` y siguen quedando en `Manual`.
- `Manual outbound` permite enviar texto, media o archivos. Uno o mas adjuntos se
  pueden seleccionar, arrastrar sobre el composer, o pegar desde el
  portapapeles; enviar algo desde ahi pausa la automatizacion del lead.

Media en WhatsApp:

- La media que envian los leads se descarga y se muestra en el backoffice
  cuando el proveedor la entrega.
- Los audios inbound se guardan con `media_type/media_path` para poder
  reproducirlos y, si la transcripcion sale bien, el transcript queda como un
  mensaje inbound subsiguiente con `sequence_step=audio_transcript`, para que el
  operador lea el chat sin escuchar el audio y el bot siga como texto normal.
- La media o archivos que envia el operador desde `Manual outbound` se guardan
  en `data/contadores/outbound_media/{lead_id}/`, se muestran en el chat y el
  bot los despacha por WhatsApp como imagen, video, audio o documento.
- Si un lead envia solo media sin texto, se guarda un placeholder textual como `[image]` o `[video]`.
- Los videos salientes de estrategia usan el `media_path` configurado, por ejemplo `data/contadores/videos/loom_60_seconds_captions.mp4`.
- El frontend sirve esos videos desde una URL estable basada en `media_path`, asi el mismo archivo se reutiliza para todos los leads que recibieron ese video.

## Workstation de clientes convertidos

La UI tiene dos superficies: `CRM` para captar y conversar con leads, y
`Workstation` para trabajar con clientes que ya pagaron.

Desde el detalle de un lead se puede usar `Convert` para crear un cliente de
Workstation. La conversion es idempotente: si el lead ya fue convertido, la UI
muestra `Open Workstation` y conserva el link al chat original del CRM.

Al convertir:

- se crea un registro en `workstation_clients`;
- se marca el lead como `booked` si todavia no lo estaba;
- se pausa la automatizacion del lead;
- se registra el evento `workstation_client_created`;
- la media subida en Workstation se puede renombrar desde la UI sin cambiar el
  archivo fisico guardado en `data/workstation/clients/.../media/`.
- si la conversion viene de la promo solo pagina, el precio sorteado queda
  fijo en el cliente de Workstation para saber cuanto cobrar.
- la accion `Solo page` desde Manual usa `work_type=solo_pagina`,
  `status=pending_payment` y `automation_status=intake`, y pausa el lead con
  `automation_paused_reason=manual_workstation_solo_page_conversion`.
- el summary del CRM expone `workstation_client_id`.

Cada cliente de Workstation tiene notas editables, media subida manualmente con
titulo, copia de notas, copia de todo el contexto, foto profesional generada
desde fotos fuente, y export ZIP. La media se puede subir con el selector de
archivo, arrastrando un archivo sobre el panel `Media`, o pegando una imagen o
archivo desde el portapapeles mientras ese panel esta activo.

La foto profesional se dispara desde el boton `Actions` del cliente. La accion
`Hacer foto profesional` abre un modal para seleccionar imagenes de `media/`,
arranca un job async en el backend y la UI hace polling hasta mostrar el
resultado o el error.

## WhatsApp delivery failures

El bot registra cada error de envio en el backend. Un mensaje saliente fallido
se reintenta hasta `CONTADORES_DELIVERY_MAX_ATTEMPTS` veces, esperando
`CONTADORES_DELIVERY_RETRY_DELAY_SECONDS` entre intentos. Cuando se agotan los
intentos, el mensaje queda en `failed`, el lead se marca con una alerta roja en
el CRM, y el detalle del chat muestra el error expandible junto al mensaje. Los
errores de Meta se normalizan antes de mostrarse: por ejemplo, el codigo
`130472` se muestra como destinatario bloqueado por un experimento de Meta,
`131026` como posible numero no registrado en WhatsApp o destinatario que no
puede recibir mensajes de empresa, y `131047` como ventana de 24 horas cerrada.
El operador puede tocar el mensaje fallido o el boton `Seen` para
guardar `delivery_error_acknowledged_at`; desde ese momento el error sigue
visible en el chat, pero deja de contar para la alerta roja del lead.

Los mensajes no-template solo se pueden encolar si el ultimo inbound del lead
esta dentro de la ventana de 24 horas de WhatsApp. Si la ventana esta cerrada,
el backend rechaza custom/media/Calendly/Loom no-template antes de llegar a
Meta, y la UI bloquea el composer custom indicando que hay que usar un template
aprobado como `Manual ping`.

Para reencolar mensajes historicos que ya quedaron en `failed`:

```bash
uv run python src/scripts/requeue_failed_contadores_messages.py --dry-run
uv run python src/scripts/requeue_failed_contadores_messages.py
```

## Promo web profesional mayo 2026

Template Meta:

- Nombre: `konecta_promo_web_profesional_es_v1`
- Categoria: `MARKETING`
- Parametros posicionales: nombre corto, profesion, pais, precio.
- Spec versionado: `src/scripts/whatsapp_template_specs/konecta_promo_web_profesional_es_v1.json`.

Script one-off:

```bash
uv run python src/scripts/contadores_promo_web_20260505.py
uv run python src/scripts/contadores_promo_web_20260505.py --execute
```

El modo default es dry-run: genera `data/reports/promo-web-profesional-2026-05-05-preview.csv`
y `data/contadores/promo-web-profesional-2026-05-05-aliases.csv`.
El script excluye convertidos, Workstation, booked, closed, archived, opt-outs
de marketing y, salvo que se pase `--include-provider-failures`, leads cuyo
ultimo outbound ya fallo en Meta. Los precios `19/29/49/99` se eligen de forma
deterministica por lead y pais, con mayor peso a precios bajos en Venezuela,
Bolivia y mercados similares. Al ejecutar, encola el template con sus variables
en `contadores_messages`. Las respuestas posteriores entran por la ruta de
oferta activa (`promo_`/`offer_`), pero esta promo tiene un atajo
deterministico: primer interes manda el video de ejemplo y el segundo interes
crea Workstation de `solo_pagina` para intake y boceto.

La carpeta canonica por cliente queda en:

```text
data/workstation/clients/{client_id_corto}-{nombre-slug}/
```

Dentro de esa carpeta se refrescan estos archivos:

- `profile.json`: datos del cliente, lead, precio de oferta y media.
- `notes.txt`: notas de reunion.
- `conversation.txt`: transcript del chat CRM.
- `media/`: archivos subidos desde Workstation y copias de artefactos
  generados que conviene ver rapido desde la UI.
- `professional-photo/vNNN/`: versiones generadas por Codex para la foto
  profesional del cliente.
- `landing-page/vNNN/`: bocetos estaticos generados por Codex para la promo
  solo pagina, con `index.html`, `styles.css`, `script.js`, `assets/`,
  `preview.mp4` y `metadata.json`.

La foto profesional se crea desde imagenes seleccionadas en `media/` y se guarda
siempre con versionado determinista:

```text
professional-photo/v001/professional-photo.jpg
professional-photo/v001/metadata.json
```

Las modificaciones desde la UI crean `v002`, `v003`, etc. Nunca se sobrescriben
las fotos fuente ni las versiones anteriores.

El backend usa el Codex SDK para Workstation, generacion de imagenes y el bot
conversacional. En Docker, la imagen instala `@openai/codex` y usa
`CODEX_HOME=/app/data/codex-home` por defecto para que la autenticacion de Codex
pueda persistir en el volumen `data/`. Si
`CODEX_PREFER_CHATGPT_LOGIN=true`, el backend remueve `OPENAI_API_KEY` antes de
lanzar Codex para priorizar el login ChatGPT/Codex. Si se configura en `false`,
el proceso Codex conserva `OPENAI_API_KEY`.

La automatizacion Workstation solo pagina usa `run_codex_with_context` con
`gpt-5.5`, `medium`, la skill `.codex/skills/workstation-solo-page/SKILL.md` y
un write scope limitado al folder del cliente. Si Codex falla o no genera los
archivos esperados, se marca `automation_status=failed` y se crea una alerta por
email con el error y el comando/link de reauth.

El preview que recibe el cliente es solo MP4. El backend renderiza el HTML
estatico con Playwright en desktop `1440x900`, graba un scroll y normaliza el
archivo con `ffmpeg` a H.264. El scroll usa una animacion lineal y continua
para evitar saltos en paginas largas. No se manda link temporal al cliente.

Cuando la ventana de WhatsApp esta cerrada, Workstation solo usa templates Meta
aprobados. Los nombres son configurables por `.env`:

- `WORKSTATION_PING_TEMPLATE_1_NAME=konecta_workstation_ping_1_es_v1`
- `WORKSTATION_PING_TEMPLATE_2_NAME=konecta_workstation_ping_2_es_v1`
- `WORKSTATION_HANDOFF_TEMPLATE_NAME=konecta_workstation_handoff_es_v1`

La cadencia es 24h, 48h y 72h desde el ultimo preview. Si faltan templates o
falla WhatsApp/Codex, se alerta por email y no se manda texto custom fuera de la
ventana de 24 horas.

El backend tambien expone un endpoint publico, sin cookie ni token, para generar
una imagen con Codex desde un prompt y referencias visuales opcionales:

```bash
curl -X POST http://127.0.0.1:8000/api/public/image-generation \
  -F 'prompt=Crear una imagen usando estas referencias' \
  -F 'images=@referencia-1.png' \
  -F 'images=@referencia-2.jpg' \
  -o generated-image.png
```

Cada request guarda sus inputs, metadata y `generated-image.png` en
`data/public-image-generations/{job_id}/`. El response devuelve directamente la
imagen generada. El camino principal usa Codex con el login ChatGPT guardado en
`CODEX_HOME`; si Codex falla o no crea el archivo esperado, el backend hace
fallback a la OpenAI Images API con `OPENAI_API_KEY`. El modelo de fallback se
configura con `OPENAI_IMAGE_FALLBACK_MODEL` y por defecto usa `gpt-image-1.5`,
que es el modelo GPT Image recomendado en la documentacion actual de OpenAI.
El fallback por API tiene un limite simple en memoria de 10 usos por proceso;
Codex no tiene limite en este endpoint.

El ZIP se descarga desde:

```bash
curl -L http://127.0.0.1:8000/api/workstation/clients/{client_id}/zip -o client.zip
```

Codex debe usar esa carpeta como fuente de verdad para trabajos manuales futuros
como landing pages, imagenes o materiales de entrega. No se llama a GPT Image por
API desde esta V1.

## Docker Compose

```bash
docker compose up --build
```

Compose lee `.env`. Para cambiar la fuente de leads, editás la sheet configurada
y reiniciás el servicio.

Servicios:

- `backend`: FastAPI con login, API de Contadores y frontend.
- `bot`: webhooks de WhatsApp/Calendly y worker de automatización.
- `traefik`: entrada HTTP para mantener el despliegue detrás de Traefik.

El backend corre con un solo worker de Uvicorn mientras use SQLite. La base
local queda en `data/database.sqlite`, montada como volumen persistente, y el
engine activa WAL + busy timeout para reducir locks entre el backend y el bot.
No subir `--workers` sin migrar a Postgres o definir otra estrategia de
concurrencia.

El bot tambien usa el volumen persistente `data/` para
`bot-webhook-inbox.sqlite`. Ese inbox es el buffer antifallos de inbound
WhatsApp entre Meta y el backend; no borrarlo durante deploys o limpiezas.

## Rollout recomendado

`ALWAYS_DEPLOY`: un cambio de producto no esta terminado por compilar local,
pasar tests o estar pusheado. Esta terminado cuando `main` fue deployado en el
server real y se verifico ahi.

Este repo se trabaja server-first: `localhost` sirve para desarrollar, verificar, mover git, pushear y deployar. Un cambio de producto se considera terminado cuando está en el server real, salvo que explícitamente se pida local-only.

1. Trabajar y mergear directo a `main`.
2. Pushear `main`.
3. Deployar el servidor desde `main`.
4. Verificar `/api/runtime`, `/api/funnels`, la ingesta de sheet y el flujo de WhatsApp en el server.

Deploy remoto:

```bash
./deploy_to_server.sh
```

Logs remotos:

```bash
./server_logs.sh
```
