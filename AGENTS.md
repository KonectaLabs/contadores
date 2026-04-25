# AGENTS

## Runtime

- El modo canónico sale del entorno, no del código ni de una base local.
- Usar siempre `CONTADORES_SOURCE_MODE=testing|live`.
- `testing` usa `CONTADORES_TEST_PHONE`.
- `live` usa `CONTADORES_SHEET_URL` y `CONTADORES_SHEET_GID`.

## Deploy

- La rama operativa es `main`.
- Si algo se va a deployar, debe quedar committeado en `main`.
- `docker-compose.yml` debe leer `.env`.
- El rollout seguro siempre es `testing` primero y `live` después.

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
