# Contadores

`Contadores` es el workspace de negocio y operación de **Website Agent**.
Ya no identifica al CRM de funnels, Sheets, campañas y Workstation que existía
antes.

## Producto activo

El producto ejecutable vive en dos repos Git independientes:

- `website-agent/` (`Fakamoto/website-agent`): panel, WhatsApp, publicaciones,
  cola de mensajes, follow-ups, actividad y costos.
- `../agent-runtime` (`Fakamoto/agent-runtime`): threads, runs, checkpoints,
  timers, filesystem virtual y ledger de uso.

`website-agent/` está ignorado por este repo porque conserva su propio `.git`.
Los cambios de producto se hacen, validan, committean y pushean en ese repo,
no en el índice Git de `KonectaLabs/contadores`.

La referencia técnica canónica es
[`website-agent/README.md`](website-agent/README.md).

## Producción

El server real usa esta estructura:

```text
/root/projects/
├── website-agent/
└── agent-runtime/
```

Website Agent levanta un único proyecto Docker Compose:

- `gateway`: Traefik en `80/443`;
- `app`: FastAPI en `127.0.0.1:8000`;
- `agent-server`: Agent Runtime en `127.0.0.1:2024`;
- `postgres`: PostgreSQL 16.

El origen público es <https://chatterface.fgoiriz.com>.

## Persistencia

- `website-agent/data/website-agent.sqlite`: usuarios, mensajes, deduplicación
  de WhatsApp, entregas del agente, wakeups y publicaciones.
- volumen PostgreSQL `website-agent_agent-runtime-postgres`: threads,
  checkpoints, runs, crons, archivos virtuales y uso de modelos.
- `data/` en este repo: datos históricos o materiales locales. No es la base
  de producción de Website Agent y no se commitea.

Un backup válido de producción debe cubrir SQLite y PostgreSQL. Respaldar sólo
uno de los dos deja el producto incompleto.

## Skills

Hay dos grupos distintos:

1. `website-agent/skills/`: comportamiento que Juan carga dentro del runtime.
   Las seis skills canónicas son `sales-flow`, `service-policy`,
   `website-build`, `website-design`, `image-workflow` y `human-handoff`.
2. `.codex/skills/` y `wiki/skills/`: conocimiento de operación, clientes,
   Frankie Fihn, marketing, anuncios, research, videos y materiales de Konecta.

Las skills de marketing no describen el runtime. No deben llamar endpoints,
tools, tablas ni scripts del CRM anterior.

## Contenido preservado

Se conservan:

- datos y documentos de clientes;
- materiales de Contadores y Abogados como nichos;
- Frankie Fihn;
- research, ofertas, anuncios, imágenes, Looms y video;
- decks, media y evidencia comercial.

El código histórico bajo `src/`, `scripts/`, `plans/`, `config/` y `traefik/`
no forma parte del producto activo. No usarlo para explicar, desarrollar,
probar o desplegar Website Agent.

## Regla operativa

Para cualquier cambio de producto:

1. trabajar en `website-agent/` o `../agent-runtime` según la responsabilidad;
2. validar el repo modificado;
3. dejar el cambio en `main` y pushearlo;
4. desplegar ambos SHAs compatibles en `/root/projects/`;
5. verificar contenedores, salud interna y
   `https://chatterface.fgoiriz.com/health`.

No usar artefactos, comandos ni configuración del runtime histórico de la raíz.
