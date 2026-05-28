# Source

Código de producto.

- `backend/`: API FastAPI y lógica de negocio.
- `frontend/`: backoffice React para operar Contadores y configurar funnels.
- `tools/`: scripts operativos que se ejecutan con `uv run python`.

Usar `PYTHONPATH=src` para ejecutar imports del paquete `backend`.

La capa `backend/funnel_config.py` expone funnels por nicho desde
`config/default-funnels.json` y los overrides de `FUNNELS_CONFIG_PATH` o
`data/funnels.json`.

Client Lead Delivery vive en `backend/endpoints/client_leads.py` y persiste sus
fuentes/filas en tablas dedicadas, separadas del pipeline normal de
`contadores_leads`.

La automatizacion de Cloudflare Registrar/DNS vive en
`backend/cloudflare_registrar.py` y se ejecuta como modulo CLI con `uv run
python -m backend.cloudflare_registrar`.

El bot conversacional reclama cada batch inbound en SQLite antes de generar una
respuesta para evitar dobles `ai_reply`. Si no sabe responder una pregunta,
crea un ticket `unanswered_lead_question` por AgentMail; la respuesta del
operador al thread se manda por WhatsApp y se guarda en el playbook aprendido.
