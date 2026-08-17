# MUST READ — estructura operativa de Contadores

Este archivo se debe leer antes de ejecutar cualquier cambio dentro de
`/root/projects`.

## Definición del producto

**Contadores significa únicamente Website Agent.**

No existe un CRM, bot, funnel de Sheets, workstation ni backend alternativo
activo bajo el nombre Contadores. Las referencias históricas a esos sistemas
no describen el producto actual y no deben usarse para operar o desplegar.

## Estructura canónica del server

```text
/root/projects/
├── MUST_READ.md                 # este documento; lectura obligatoria
├── README.md                    # entrada corta a este documento
├── AGENTS.md                    # reglas obligatorias para agentes
├── .codex/
│   └── skills/                  # skills operativas de proyecto, ventas y marketing
├── website-agent/               # repo del producto Website Agent
│   ├── backend/                 # FastAPI, WhatsApp, panel y publicación
│   ├── frontend/                # interfaz del panel
│   ├── data/
│   │   ├── website-agent.sqlite # estado del producto/control plane
│   │   └── gym.sqlite           # snapshot y anotaciones privadas de /gym/
│   ├── skills/                  # skills de runtime de Juan
│   ├── docker-compose.yml       # stack completo del producto
│   └── .env                     # secretos; nunca imprimir ni reemplazar
└── agent-runtime/               # repo separado del runtime durable del agente
```

`website-agent/` y `agent-runtime/` son repos Git distintos. No asumir que un
commit del primero incluye cambios del segundo. Antes de operar, leer en cada
repo su branch, `HEAD`, remoto y estado del worktree.

El repo de conocimiento local `contadores` mantiene documentación y skills
operativas, pero no está clonado en el server y no es el código desplegable.

## Responsabilidad de cada repo

### `website-agent/`

Es el producto activo. Contiene:

- panel web autenticado;
- ingreso y salida de WhatsApp;
- cola, deduplicación y entregas al agente;
- follow-ups y wakeups automáticos;
- publicación y descarga de páginas estáticas;
- proxy de actividad y costos de IA;
- Compose, gateway, configuración y skills que recibe Juan.
- `Dockerfile.agent`, que extiende la imagen genérica versionada del runtime con
  el agente y las skills concretas de Website Agent.

### `agent-runtime/`

Es el runtime durable genérico usado por `website-agent`. Contiene el servidor
del agente y la persistencia de threads, checkpoints, runs, crons/timers,
archivos virtuales por usuario y ledger de uso. No contiene ni instala skills
de Website Agent; el producto las agrega en su propia imagen final.

## Stack en ejecución

```text
Internet
  -> Traefik gateway (:80/:443)
      -> Website Agent / FastAPI (127.0.0.1:8000)
      -> Agent Runtime (127.0.0.1:2024)
          -> PostgreSQL 16
```

El dominio público es `https://chatterface.fgoiriz.com`.

El stack se opera desde `/root/projects/website-agent/docker-compose.yml` y
debe tener cuatro servicios sanos: `gateway`, `app`, `agent-server` y
`postgres`.

## Persistencia: nunca confundir stores y sidecars

### SQLite

`/root/projects/website-agent/data/website-agent.sqlite` guarda estado del
producto/control plane, incluyendo usuarios, mensajes, deduplicación de
WhatsApp, entregas al agente, wakeups y el mapeo estable de sitios publicados.

`/root/projects/website-agent/data/gym.sqlite` es un sidecar aislado con el
snapshot y las anotaciones humanas de `/gym/`. Juan y Agent Runtime no lo leen.
Su snapshot se congela al primer acceso, no incorpora conversaciones nuevas y
mantiene progreso y anotaciones independientes por administrador. Su esquema
auxiliar no pertenece al historial Alembic del control plane.

### PostgreSQL

El volumen Docker `website-agent_agent-runtime-postgres` guarda el estado
durable del Agent Runtime: threads, checkpoints, runs, crons/timers, archivos
virtuales por usuario y uso.

Un backup válido del producto debe incluir **`website-agent.sqlite` y
PostgreSQL**. Si existe `gym.sqlite`, también debe preservarlo para no perder el
evalset humano. No borrar, recrear ni reemplazar el volumen de PostgreSQL ni
ninguno de estos SQLite como parte de un rollout ordinario.

Los cambios de esquema propios usan dos historiales Alembic independientes:
Website Agent para SQLite y Agent Runtime para sus tablas en el schema
`agent_runtime`. El deploy ejecuta ambos `upgrade head` antes de levantar los
servicios; los procesos sólo validan el head. Las migraciones compatibles no
requieren un backup ad hoc por rollout. Una migración destructiva requiere un
recovery plan y un backup consistente de ambos stores.
El sidecar `gym.sqlite` queda fuera de esos historiales y no requiere un
`upgrade head`.

## Dos clases de skills

### Skills operativas de Codex

Ruta: `/root/projects/.codex/skills/`

Incluyen la definición del producto, rollout, conocimiento Frankie Fihn,
marketing, intake y recursos de clientes. Sirven para que Codex y otros
operadores entiendan y administren el proyecto.

Lectura mínima para cualquier operación del producto:

1. `/root/projects/MUST_READ.md`
2. `/root/projects/.codex/skills/website-agent-product/SKILL.md`
3. `/root/projects/.codex/skills/website-agent-rollout/SKILL.md` si se toca el server
4. la skill específica de negocio, marketing o cliente cuando corresponda

### Skills de runtime de Juan

Ruta: `/root/projects/website-agent/skills/`

Son las únicas skills que el contenedor `agent-server` carga para el agente:

- `sales-flow`
- `service-policy`
- `website-build`
- `website-design`
- `image-workflow`
- `human-handoff`

No copiar automáticamente las skills operativas, de Frankie, marketing o
clientes dentro de `website-agent/skills/`. Cambiar una skill operativa no
cambia el comportamiento de Juan; cambiar una skill de Juan exige validar y
desplegar el runtime correspondiente.

## Reglas Git y rollout

- La rama operativa es `main` en ambos repos.
- No usar force-push, reset destructivo ni worktrees/release directories viejos.
- Mantener limpios los dos worktrees del server.
- Validar localmente antes de pushear.
- Pushear cada repo por separado y registrar sus dos SHAs compatibles.
- En el server, actualizar sólo a SHAs aprobados y usar fast-forward.
- Construir la imagen genérica de Agent Runtime con su SHA aprobado y pasar ese
  tag exacto como `AGENT_RUNTIME_IMAGE` al build de Website Agent.
- Ejecutar Alembic para PostgreSQL y SQLite antes de levantar los servicios.
- Reservar el backup obligatorio para migraciones destructivas o un recovery
  plan explícito, no para cada revisión compatible.
- Construir y levantar desde `/root/projects/website-agent`.
- Verificar Compose, `127.0.0.1:8000/health`, Agent Runtime en `:2024`, dominio
  público, panel, webhook de WhatsApp y publicación de páginas según el cambio.

Código local, commit, push, deploy, health técnico y QA funcional son gates
distintos. No afirmar que algo está en producción sólo porque está pusheado o
porque un healthcheck responde.

## Deploy automático desde GitHub

`website-agent` y `agent-runtime` tienen workflows independientes para cada
push a `main`, incluidos los pushes creados al mergear PRs en `main`. No se
ejecuta un segundo deploy manual. No existe un repo coordinador. Ambos serializan cambios con
`/run/lock/website-agent-deploy.lock` porque Website Agent conserva el único
Compose del producto.

- Website Agent construye y reconcilia el producto completo y ejecuta las dos
  migraciones Alembic.
- Agent Runtime construye su base versionada, migra PostgreSQL y reemplaza sólo
  `agent-server`.

Los SHAs confirmados viven en `/root/projects/.deploy/website-agent.sha` y
`/root/projects/.deploy/agent-runtime.sha`. No editar estos archivos antes de
que terminen build, migraciones y healthchecks. Un workflow viejo debe salir
sin hacer rollback si su SHA ya no coincide con `origin/main`.

Website Agent crea `website-agent.pending` justo antes de reemplazar
contenedores y lo elimina sólo después de confirmar salud y estado. Agent
Runtime debe rechazar un deploy mientras ese marcador exista; primero se
reintenta o reconcilia el rollout de Website Agent.

En la primera activación de estos workflows, desplegar Agent Runtime antes que
Website Agent. Después del bootstrap, ambos repos despliegan de forma
independiente.

## Credenciales y límites

- Los secretos activos viven en `/root/projects/website-agent/.env`.
- No imprimir, commitear, copiar sobre ni inventar secretos.
- No usar credenciales, proyectos, cuentas ni recursos de CleverApply o de
  otros clientes, ni siquiera para una prueba temporal o read-only.
- No tocar datos persistentes ni repos ajenos al alcance del cambio.

## Fuentes de verdad

Para decidir el estado actual, el orden es:

1. estado vivo del server y sus dos repos;
2. código y README actuales de `website-agent` y `agent-runtime`;
3. este documento y las skills operativas;
4. documentación histórica, sólo como contexto no operativo.

Si una referencia menciona CRM, funnels de Sheets, workstation, un bot viejo,
`src/` del antiguo repo Contadores o directorios `agent-runtime-release-*`, se
considera obsoleta para el producto actual.
