# Website Agent Architecture

## Repositorios

- `Fakamoto/website-agent`: aplicación y skills del agente vendedor.
- `Fakamoto/agent-runtime`: ejecución durable compatible con LangGraph.

En producción ambos repos son hermanos bajo `/root/projects/`. Agent Runtime
mantiene una imagen genérica, sin agentes ni skills de un proyecto concreto.
`website-agent/Dockerfile.agent` es dueño de la imagen final de `agent-server`:
usa `../agent-runtime` como contexto de runtime y agrega el agente y las skills
de Website Agent.

## Servicios

```text
Internet
  |
  v
Traefik gateway :80/:443
  |
  +--> FastAPI app :8000
  |      - panel privado
  |      - WhatsApp webhook y entregas
  |      - publicaciones /p/
  |      - follow-ups y wakeups
  |      - actividad y costos
  |
  +--> Agent Runtime :2024
          - threads y runs
          - checkpoints y timers
          - filesystem virtual por usuario
          - skills y tools de Juan
          |
          v
       PostgreSQL 16
```

## Persistencia

`website-agent.sqlite` pertenece a FastAPI. Guarda usuarios, mensajes,
deduplicación de WhatsApp, entregas, wakeups y publicaciones.

PostgreSQL pertenece a Agent Runtime. Guarda threads, checkpoints, runs,
crons, archivos virtuales y usage ledger.

Ninguna base reemplaza a la otra. Backup, restauración y migraciones deben
tratar ambas como un conjunto compatible.

## Skills

El runtime carga seis skills centrales:

- `sales-flow`
- `service-policy`
- `website-build`
- `website-design`
- `image-workflow`
- `human-handoff`

Las skills Frankie Fihn y de marketing de este workspace son conocimiento para
Codex y operadores. No se cargan automáticamente dentro de Juan.

## Límites

El producto actual no usa el runtime histórico de la raíz. Sus referencias no
deben dirigir cambios ni rollouts actuales.
