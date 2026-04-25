## Backend

Este backend todavía es chico a propósito.

La parte importante que ya queda definida es el contrato de runtime:

- `CONTADORES_SOURCE_MODE=testing|live` decide si el sistema trabaja contra un número de prueba o contra la sheet real.
- `testing` usa `CONTADORES_TEST_PHONE`.
- `live` exige `CONTADORES_SHEET_URL`.
- `docker-compose.yml` lee estas variables desde `.env`.

Comandos útiles:

```bash
cd /Users/fgoiriz/private/repos/contadores
uv sync
PYTHONPATH=src uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Endpoints:

- `GET /health`
- `GET /api/runtime`
