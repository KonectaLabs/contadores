---
name: loom-deck-pptx
description: >-
  Builds the Konecta Loom sales deck as a .pptx from HTML (Playwright screenshots
  + pptxgenjs). Covers the two HTML variants (17 vs 11 slides), deck-export
  sync, and npm commands. Use when generating or regenerating
  Konecta-Loom-Vender-a-Contadores-Final.pptx or when editing Loom Script.html
  in media/presentations/loom-video-vender-a-contadores.
  After ANY user-requested change to the loom HTML, styles, slides, or notes,
  run npm run pptx in the same turn so Konecta-Loom-Vender-a-Contadores-Final.pptx
  stays in sync; never end the task with HTML-only edits unless export failed
  and you reported the error.
---

# Loom deck → PPTX

## Canonical sources

All paths under `media/presentations/loom-video-vender-a-contadores/`.

| File | Slides | Role |
|------|--------|------|
| `Loom Script.html` | **17** | **Canónico** para el video Loom: incluye slides intermedios tipo `01 / 06`…`06 / 06` y el copy largo. Notas en `#speaker-notes` (17 entradas). |
| `Loom Script-print.html` | **11** | Versión recortada (sin intros de pregunta). No usar para el PPTX final si el objetivo es el deck del enlace/hosteado de 17 slides. |
| `deck-export.html` | — | **No editar a mano salvo urgencia.** Se genera desde `Loom Script.html` vía `sync-deck-export.mjs`: título de export, regla `.export-hidden`, atributo `noscale` en `<deck-stage>`. |

## Cómo se arma el PPTX

1. `sync-deck-export.mjs` copia el contenido de `Loom Script.html` a `deck-export.html` y aplica los tres ajustes de exportación.
2. `export-pptx.mjs` abre `deck-export.html` en Chromium (Playwright), viewport 1920×1080, `deviceScaleFactor: 2`, recorre cada slide con `deck-stage.goTo(i)`, captura PNG por slide.
3. pptxgenjs crea un deck 16:9 (`LAYOUT_WIDE`), una imagen full-bleed por slide y `slide.addNotes()` desde el JSON `#speaker-notes`.

Salida: `Konecta-Loom-Vender-a-Contadores-Final.pptx`.

## Comandos (desde esa carpeta)

Primera vez (o tras actualizar Playwright):

```bash
cd media/presentations/loom-video-vender-a-contadores
npm install
npx playwright install chromium
```

Regenerar el PPTX (sincroniza export + render):

```bash
npm run pptx
```

Solo reescribir `deck-export.html` sin render:

```bash
npm run sync-export
```

## Si cambia el HTML

- Editar **`Loom Script.html`** (estilos, slides, notas).
- Ejecutar **`npm run pptx`**; no hace falta tocar `deck-export.html` manualmente.

## Regla obligatoria (post-cambio)

Tras **cualquier** cambio que pida el usuario sobre este deck (HTML, CSS, copy, slides, notas): en **el mismo turno** ejecutar `npm run pptx` desde `media/presentations/loom-video-vender-a-contadores` y confirmar que `Konecta-Loom-Vender-a-Contadores-Final.pptx` quedó regenerado (o informar el error de export). No asumir que el usuario lo lanzará después; no dejar solo `Loom Script.html` / `deck-export.html` actualizados sin PPTX salvo que falle el render y se documente.

## Dependencias

- Node + npm en esa carpeta (`pptxgenjs`, `playwright`).
- Red la primera vez: fuentes Google en el HTML.
