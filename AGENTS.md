# AGENTS

## Límite del proyecto

- `Contadores` significa únicamente Website Agent.
- El producto activo no vive en `src/`. Vive en dos repos independientes:
  - `website-agent/`: aplicación, WhatsApp, páginas publicadas y skills de Juan.
  - `../agent-runtime`: runtime, checkpoints, archivos virtuales y uso de IA.
- `website-agent/` conserva su propio `.git` y está ignorado por este repo.
- El código histórico bajo `src/`, `scripts/`, `plans/`, `config/` y `traefik/`
  no es fuente de verdad. No inspeccionarlo ni modificarlo salvo pedido explícito.
- No usar el runtime histórico de la raíz como evidencia del producto actual.

## Runtime actual

- `website-agent` usa `gateway`, `app`, `agent-server` y `postgres`.
- `app` guarda el control del producto en
  `website-agent/data/website-agent.sqlite`.
- Agent Runtime guarda threads, checkpoints, runs, crons, archivos virtuales y
  usage ledger en PostgreSQL.
- Las skills runtime canónicas viven en `website-agent/skills/`.
- El dominio público es `https://chatterface.fgoiriz.com`.

## Credenciales

- En Contadores/Konecta nunca usar recursos de CleverApply, Alejandro, `@cleverapply.com`, `cleverapply-gws-20260519` ni ningun proyecto/cuenta/credential que contenga `cleverapply` o `clever-apply`.
- Esto aplica tambien a quota project, billing project, OAuth client, browser profile, gcloud account, 1Password item, test user, fallback temporal y pruebas read-only.
- Si falta permiso, pedir o crear credenciales propias de Contadores/Konecta. No tomar prestado acceso de otro cliente.

## Deploy

- El server real usa `/root/projects/website-agent` y
  `/root/projects/agent-runtime`.
- Cada repo operativo usa `main` y debe quedar limpio, committeado y pusheado.
- Validar los SHAs compatibles de ambos repos antes del rollout.
- `website-agent/docker-compose.yml` lee `website-agent/.env` y es el único
  Compose del producto.
- Verificar los cuatro servicios, salud interna y
  `https://chatterface.fgoiriz.com/health` después del deploy.
- Un backup de producción debe incluir SQLite y el volumen PostgreSQL.
- Nunca ejecutar scripts de despliegue del runtime histórico.

## Documentación

- Mantener sincronizados:
  - `README.md`
  - `.codex/skills/*`
  - `wiki/skills/*`
  - `server-workspace/*` con los documentos raíz de `/root/projects/`
- Si cambian las skills operativas o la estructura, sincronizar
  `.codex/skills/` y `server-workspace/` al server sin tocar
  `website-agent/skills/`.
- La configuración ejecutable vive en `website-agent/.env.example`.
- Si cambia el rollout, actualizar `website-agent-rollout` en ambos catálogos.
- Si cambia el comportamiento de Juan, actualizar la skill correspondiente
  dentro de `website-agent/skills/` y validar el runtime.

## Organización

- `website-agent/`: repo ejecutable separado del producto.
- `wiki/`: conocimiento, skills y referencias.
- `media/` y `abogados/`: materiales de clientes, presentaciones y marketing.
- `data/`: estado histórico/local no commiteado; no confundir con producción.
- `.codex/skills/`: skills activas para operar este workspace.
