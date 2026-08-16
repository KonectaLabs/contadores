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
├── MUST_READ.md
├── README.md
├── AGENTS.md
├── .codex/skills/
├── website-agent/
└── agent-runtime/
```

Los documentos raíz del server se versionan como templates en
[`server-workspace/`](server-workspace/). `MUST_READ.md` define la estructura,
los stores, los repos y el orden de lectura obligatorio. Las skills operativas
se sincronizan desde `.codex/skills/`; las skills de Juan permanecen dentro de
`website-agent/skills/`.

Website Agent levanta un único proyecto Docker Compose:

- `gateway`: Traefik en `80/443`;
- `app`: FastAPI en `127.0.0.1:8000`;
- `agent-server`: Agent Runtime en `127.0.0.1:2024`;
- `postgres`: PostgreSQL 16.

`agent-runtime` produce una imagen genérica versionada.
`website-agent/Dockerfile.agent` extiende esa imagen y es dueño de la imagen
concreta de `agent-server`, donde agrega `agent.py`, `langgraph.json` y las
skills de Juan. El runtime no conoce la implementación de Website Agent.

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

Cada store tiene su propio historial Alembic. Los rollouts ejecutan primero el
`upgrade head` de Agent Runtime sobre PostgreSQL y después el de Website Agent
sobre SQLite; los procesos sólo validan el head al iniciar. Las migraciones
backward-compatible no generan un backup ad hoc en cada push. Las destructivas
requieren un recovery plan y un backup consistente de ambos stores.

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
4. desplegar ambos SHAs compatibles en `/root/projects/`, usando el SHA de
   Agent Runtime como tag de la imagen base de `agent-server`;
5. verificar contenedores, salud interna y
   `https://chatterface.fgoiriz.com/health`.

No usar artefactos, comandos ni configuración del runtime histórico de la raíz.

## Deploy automático

Cada repo operativo tiene su propio workflow y despliega únicamente cuando un
push llega a `main`:

- `website-agent`: prueba su código, actualiza su SHA exacto, construye `app` y
  la imagen concreta de `agent-server`, ejecuta ambos historiales Alembic y
  levanta el Compose completo.
- `agent-runtime`: prueba y construye la imagen genérica, actualiza su SHA
  exacto, ejecuta sólo Alembic de PostgreSQL y reemplaza sólo `agent-server`.

Los workflows no se llaman entre sí ni dependen de un tercer repo. En el server
comparten `/run/lock/website-agent-deploy.lock` porque ambos consumen el mismo
Compose. Los SHAs desplegados se registran en `/root/projects/.deploy/`; así un
deploy de Website Agent usa la última imagen de runtime confirmada y un deploy
de Agent Runtime usa la última versión confirmada de Website Agent.

Cada repo usa un environment de GitHub llamado `production` con estos secrets:
`DEPLOY_HOST`, `DEPLOY_PORT`, `DEPLOY_USER`, `DEPLOY_SSH_PRIVATE_KEY` y
`DEPLOY_KNOWN_HOSTS`. El SSH no acepta hosts desconocidos y los workflows nunca
imprimen secretos.
