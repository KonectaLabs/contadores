# Source

Código de producto.

- `backend/`: API FastAPI y lógica de negocio.
- `frontend/`: backoffice React para operar Contadores y configurar funnels.
- `tools/`: scripts operativos que se ejecutan con `uv run python`.

Usar `PYTHONPATH=src` para ejecutar imports del paquete `backend`.

La capa `backend/funnel_config.py` expone funnels por nicho desde
`FUNNELS_CONFIG_PATH` o `data/funnels.json`; `contadores` sigue siendo el
primer funnel operativo.

El bot conversacional reclama cada batch inbound en SQLite antes de generar una
respuesta para evitar dobles `ai_reply`. Si no sabe responder una pregunta,
crea un ticket `unanswered_lead_question` por AgentMail; la respuesta del
operador al thread se manda por WhatsApp y se guarda en el playbook aprendido.

`backend/endpoints/public_image_generation.py` expone
`POST /api/public/image-generation`, un endpoint sin autenticacion que recibe
`prompt` y `images` por multipart, llama a Codex y devuelve la imagen generada.
Si Codex falla, usa la OpenAI Images API como fallback con `OPENAI_API_KEY`,
limitado a 10 usos en memoria por proceso.
