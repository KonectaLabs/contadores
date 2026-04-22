# Contadores

Repo de trabajo para el flujo de captación y seguimiento de `Contadores`.

## Regla operativa importante

El modo del sistema no se decide en código ni en estado persistido.

Se decide con entorno:

- `CONTADORES_SOURCE_MODE=testing`
- `CONTADORES_SOURCE_MODE=live`

`docker-compose.yml` toma ese valor desde `.env`. Ese es el switch canónico.

## Cómo usar los modos

### `testing`

Usa un solo número de prueba.

Variables mínimas:

- `CONTADORES_SOURCE_MODE=testing`
- `CONTADORES_TEST_PHONE=...`
- `CONTADORES_LOOM_URL=...`

En este modo no se debe consumir la sheet real de forma automática.

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
uv run python read_google_sheet.py --as-records
```

Levantar el backend:

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Verificar runtime:

```bash
curl http://127.0.0.1:8000/api/runtime
```

## Docker Compose

```bash
docker compose up --build
```

Compose lee `.env`. Si querés cambiar de `testing` a `live`, cambiás `.env` y reiniciás el servicio.

## Rollout recomendado

1. Trabajar y mergear directo a `main`.
2. Deployar el servidor con `.env` en `testing`.
3. Probar varias veces con tu número usando `CONTADORES_TEST_PHONE`.
4. Recién después cambiar `CONTADORES_SOURCE_MODE=live`.
