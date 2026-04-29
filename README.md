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
- Ambas acciones registran `calendly_sent_at` y mantienen el lead en Manual. La automatizacion sigue usando siempre texto previo + link y puede dejar el lead fuera de Manual.

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
