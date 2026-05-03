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
- `kind=campaign|inbox`, donde `inbox` no corre fases ni automatizacion;
- Calendly;
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
secretos.

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

- Vista visual: entrar al backoffice y abrir la seccion `Runner`. La UI lee
  `GET /api/contadores/followup/runner/status` y muestra estado del lock,
  ultimo resumen, logs timestamped y stdout/stderr del LaunchAgent. Esta ruta
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

Acciones manuales de Calendly:

- `Calendly with intro` encola el texto previo y despues el link de Calendly.
- `Calendly link only` encola solo el link de Calendly.
- El link de Calendly es siempre `https://calendly.com/facundogoiriz/crecimiento`, para Contadores, Abogados y cualquier otro funnel.
- Ambas acciones registran `calendly_sent_at` y mantienen el lead en Manual. La automatizacion sigue usando siempre texto previo + link y puede dejar el lead fuera de Manual.
- Si un lead responde con dia y horario concreto para una llamada, la
  automation debe intentar reservarlo solo si existe una via real de booking de
  Calendly. Hoy el codigo no crea eventos de Calendly desde texto libre; en ese
  caso marca `booking_time_provided`, pausa el lead en `needs_human` y dispara
  la alerta urgente por email para que Facu lo agende.

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
`131026` se muestra como posible numero no registrado en WhatsApp o destinatario
que no puede recibir mensajes de empresa, y `131047` como ventana de 24 horas
cerrada. El operador puede tocar el mensaje fallido o el boton `Seen` para
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

La carpeta canonica por cliente queda en:

```text
data/workstation/clients/{client_id_corto}-{nombre-slug}/
```

Dentro de esa carpeta se refrescan estos archivos:

- `profile.json`: datos del cliente, lead y media.
- `notes.txt`: notas de reunion.
- `conversation.txt`: transcript del chat CRM.
- `media/`: archivos subidos desde Workstation.
- `professional-photo/vNNN/`: versiones generadas por Codex para la foto
  profesional del cliente.

La foto profesional se crea desde imagenes seleccionadas en `media/` y se guarda
siempre con versionado determinista:

```text
professional-photo/v001/professional-photo.jpg
professional-photo/v001/metadata.json
```

Las modificaciones desde la UI crean `v002`, `v003`, etc. Nunca se sobrescriben
las fotos fuente ni las versiones anteriores.

Esta funcion usa el Codex SDK desde el backend. En Docker, la imagen instala
`@openai/codex` y usa `CODEX_HOME=/app/data/codex-home` por defecto para que la
autenticacion de Codex pueda persistir en el volumen `data/`. Si
`CODEX_PREFER_CHATGPT_LOGIN=true`, el backend remueve `OPENAI_API_KEY` antes de
lanzar Codex para priorizar el login ChatGPT/Codex. Si se configura en `false`,
el proceso Codex conserva `OPENAI_API_KEY`.

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
