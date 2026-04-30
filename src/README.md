# Source

Código de producto.

- `backend/`: API FastAPI y lógica de negocio.
- `frontend/`: backoffice React para operar Contadores y configurar funnels.
- `tools/`: scripts operativos que se ejecutan con `uv run python`.

Usar `PYTHONPATH=src` para ejecutar imports del paquete `backend`.

La capa `backend/funnel_config.py` expone funnels por nicho desde
`FUNNELS_CONFIG_PATH` o `data/funnels.json`; `contadores` sigue siendo el
primer funnel operativo.

`backend/endpoints/public_image_generation.py` expone
`POST /api/public/image-generation`, un endpoint sin autenticacion que recibe
`prompt` y `images` por multipart, llama a Codex y devuelve la imagen generada.
Si Codex falla, usa la OpenAI Images API como fallback con `OPENAI_API_KEY`.
