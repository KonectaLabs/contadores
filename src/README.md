# Source

Código de producto.

- `backend/`: API FastAPI y lógica de negocio.
- `frontend/`: backoffice React para operar Contadores y configurar funnels.
- `tools/`: scripts operativos que se ejecutan con `uv run python`.

Usar `PYTHONPATH=src` para ejecutar imports del paquete `backend`.

La capa `backend/funnel_config.py` expone funnels por nicho desde
`FUNNELS_CONFIG_PATH` o `data/funnels.json`; `contadores` sigue siendo el
primer funnel operativo.
