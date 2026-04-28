# AGENTS

## Runtime

- No existe switch de modo para Contadores.
- La fuente de leads se configura directamente con `CONTADORES_SHEET_URL` y `CONTADORES_SHEET_GID`.
- Los funnels nuevos usan su propia `sheet_url` y `sheet_gid` en `data/funnels.json`.
- No reintroducir leads sintéticos ni ramas de runtime alternativas.

## Deploy

- Este repo se trabaja pensando siempre en el server real.
- `localhost` es solo una herramienta para desarrollar, verificar, mover git, pushear y deployar.
- Si el usuario pide un cambio de producto o pregunta si ya quedó, asumir que debe quedar deployado en el server, no solo funcionando local.
- La rama operativa es `main`.
- Si algo se va a deployar, debe quedar committeado en `main`.
- `docker-compose.yml` debe leer `.env`.
- El rollout es único: validar localmente, pushear `main`, deployar y verificar el server real.

## Documentación

- Mantener sincronizados:
  - `README.md`
  - `.env.example`
  - `.codex/skills/*`
  - `wiki/skills/*`
- Si cambia el flujo o el rollout, actualizar la skill del spreadsheet y la skill de rollout en el mismo cambio.

## Organización

- `src/` contiene el código fuente.
- `wiki/` contiene documentación, skills y referencias.
- `media/` contiene presentaciones, videos, imágenes y materiales exportados.
- `data/` contiene estado persistente local y no se commitea.
