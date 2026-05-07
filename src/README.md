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
