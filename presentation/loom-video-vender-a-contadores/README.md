# Loom — vender a contadores (HTML + PPTX)

## Dos versiones de deck

| Archivo | Slides | Cuándo usarlo |
|---------|--------|----------------|
| **`Loom Script.html`** | 17 | Deck completo del Loom (intros `01/06` … `06/06`). **Base canónica.** |
| **`Loom Script-print.html`** | 11 | Versión corta; útil si solo querés PDF/impresión sin intros. **No** es la fuente del PPTX final de 17 slides. |

El PPTX final se genera siempre desde una copia exportable de **`Loom Script.html`**, no desde el print.

## Generar el PowerPoint

```bash
cd presentation/loom-video-vender-a-contadores
npm install
npx playwright install chromium   # solo la primera vez (o si falla el browser)
npm run pptx
```

Esto:

1. Ejecuta `sync-deck-export.mjs`: escribe `deck-export.html` a partir de `Loom Script.html` (título export, CSS `.export-hidden`, `noscale` en el stage).
2. Ejecuta `export-pptx.mjs`: Chromium captura cada slide 1920×1080 y arma **`Konecta-Loom-Vender-a-Contadores-Final.pptx`** con notas del speaker desde el `<script id="speaker-notes">` del HTML.

Solo regenerar `deck-export.html` sin PPTX:

```bash
npm run sync-export
```

## Editar contenido

1. Modificá **`Loom Script.html`** (y el JSON de notas si aplica).
2. Corré **`npm run pptx`**.

No mantengas cambios solo en `deck-export.html`: se pisan al correr `sync-export` / `pptx`.

## Skill del repo

Instrucciones para el agente: `.cursor/skills/loom-deck-pptx/SKILL.md`.
