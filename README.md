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

El backend siempre expone un funnel default `contadores`.

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
- modo `testing|live`;
- telefono sintetico de prueba;
- sheet URL/GID y filtro opcional;
- opener/template inicial;
- follow-up template;
- ping template manual para reabrir la ventana de WhatsApp;
- texto del video;
- estrategia `loom_link` o `loom_mp4`;
- Calendly;
- emails de alerta;
- ventanas de espera.

## Regla operativa importante

El modo del sistema no se decide en código ni en estado persistido.

Se decide con entorno:

- `CONTADORES_SOURCE_MODE=testing`
- `CONTADORES_SOURCE_MODE=live`

`docker-compose.yml` toma ese valor desde `.env`. Ese es el switch canónico.
El endpoint `/api/runtime` muestra el modo activo sin exponer secretos.

## Cómo usar los modos

### `testing`

Usa un solo número de prueba.

Variables mínimas:

- `CONTADORES_SOURCE_MODE=testing`
- `CONTADORES_TEST_PHONE=...`
- `CONTADORES_LOOM_URL=...`

En este modo no se debe consumir la sheet real de forma automática.
El bot crea o actualiza un lead sintético con `CONTADORES_TEST_PHONE`.

### `live`

Habilita lectura de la sheet real.

Variables mínimas:

- `CONTADORES_SOURCE_MODE=live`
- `CONTADORES_SHEET_URL=...`
- `CONTADORES_SHEET_GID=...`
- `CONTADORES_LOOM_URL=...`

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

- `CONTADORES_STRATEGY_WEIGHTS_JSON='{"loom":{"loom_link":0,"loom_mp4":100}}'`
- También se puede cambiar desde `Settings` en el backoffice.
- Los pesos son porcentajes de rollout por paso. Cambiarlos afecta nuevas asignaciones; las asignaciones ya guardadas no se reescriben.

Template manual de ping:

- Nombre default: `contadores_manual_ping_es_v1`.
- Texto default: `Hola, queria saber en que situacion quedamos y si queres que retomemos la conversacion`.
- Se envia solo desde la accion manual del backoffice; no participa del tick automatico ni del follow-up de 24 horas.

Media en WhatsApp:

- La media que envian los leads no se descarga ni se muestra en el backoffice.
- Si un lead envia solo media sin texto, se guarda un placeholder textual como `[image]` o `[video]`.
- Los videos salientes de estrategia usan el `media_path` configurado, por ejemplo `data/contadores/videos/loom_60_seconds_captions.mp4`.
- El frontend sirve esos videos desde una URL estable basada en `media_path`, asi el mismo archivo se reutiliza para todos los leads que recibieron ese video.

## Docker Compose

```bash
docker compose up --build
```

Compose lee `.env`. Si querés cambiar de `testing` a `live`, cambiás `.env` y reiniciás el servicio.

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

Este repo se trabaja server-first: `localhost` sirve para desarrollar, verificar, mover git, pushear y deployar. Un cambio de producto se considera terminado cuando está en el server real, salvo que explícitamente se pida local-only.

1. Trabajar y mergear directo a `main`.
2. Pushear `main`.
3. Deployar el servidor con `.env` en `testing`.
4. Probar varias veces con tu número usando `CONTADORES_TEST_PHONE`.
5. Recién después cambiar `CONTADORES_SOURCE_MODE=live`.

Deploy remoto:

```bash
./deploy_to_server.sh
```

Logs remotos:

```bash
./server_logs.sh
```
