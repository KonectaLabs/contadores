# Media

Materiales que no forman parte del runtime de la app.

- `presentations/`: decks, scripts, screenshots y exports de presentaciones.
- `templates/`: assets fuente reutilizables por Workstation/Codex.
- `examples/`: referencias historicas o ejemplos aprobados.

Antes de commitear binarios nuevos, actualiza `media/MANIFEST.md`. Generated
client work, screenshots temporales, Playwright captures, uploads crudos y
exports de prueba deben vivir en `data/`, `output/` o `tmp/`, no en `media/`.
