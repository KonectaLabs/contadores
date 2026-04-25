# Contadores

Repo de trabajo para el flujo de captación y seguimiento de `Contadores`.

## Estructura

- `src/`: código de producto.
- `wiki/`: documentación, skills y referencias de trabajo.
- `media/`: materiales audiovisuales, decks y archivos de soporte.
- `data/`: estado local persistente. No se commitea.

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

## Docker Compose

```bash
docker compose up --build
```

Compose lee `.env`. Si querés cambiar de `testing` a `live`, cambiás `.env` y reiniciás el servicio.

Servicios:

- `backend`: FastAPI con login, API de Contadores y frontend.
- `bot`: webhooks de WhatsApp/Calendly y worker de automatización.
- `traefik`: entrada HTTP para mantener el despliegue detrás de Traefik.

## Rollout recomendado

1. Trabajar y mergear directo a `main`.
2. Deployar el servidor con `.env` en `testing`.
3. Probar varias veces con tu número usando `CONTADORES_TEST_PHONE`.
4. Recién después cambiar `CONTADORES_SOURCE_MODE=live`.
