# Media Manifest

Tracked binary media is intentional only when this manifest classifies it. New
generated outputs, client exports, screenshots, uploads, and professional photos
should stay in `data/`, `output/`, or `tmp/` unless owner review approves
versioning here.

## Classifications

- `template`: reusable production source asset used by app or Codex workflows.
- `reference`: historical or design reference kept for comparison/review.
- `public`: safe marketing/presentation material intended to be shared.
- `client-private`: client-specific material; do not reuse outside its context.
- `generated`: model/browser/export output; do not add more without review.

## Manifest

| Path | Classification | Owner/source | Why versioned | Retention/removal |
|---|---|---|---|---|
| `media/templates/workstation/**` | `template`, `public` | Konecta/Contadores | Base Workstation static templates and videos used to generate client work. | Keep while referenced by Workstation flows; generated client variants belong in `data/`. |
| `media/examples/page-example-videos/*` | `reference`, `public` | Konecta examples | Stable page-example videos and thumbnails used for CRM/demo review. | Keep as examples; replace only with approved better examples. |
| `media/examples/workstation/marielis-workstation-test/preview*.mp4` | `reference`, `generated`, `client-private` | Workstation test output | Historical generated Workstation preview output for visual comparison. | Owner review before reuse, removal, or replacement. |
| `media/examples/workstation/marielis-workstation-test/professional-photo.jpg` | `reference`, `generated`, `client-private` | Workstation test output | Historical generated professional-photo example. | Owner review before reuse, removal, or replacement. |
| `media/examples/workstation/mmb-contable-local/assets/*` | `reference`, `generated`, `client-private` | MMB local Workstation example | Client-specific local page example assets. | Keep only as reviewed example assets; new client assets belong in `data/`. |
| `media/ads/*/ads/v*/*.png` | `reference`, `generated`, `client-private` | Client ad creative batches | Versioned ad creative artifacts and campaign review history. | Keep for campaign audit; owner review before deletion or public reuse. |
| `media/ads/*/ads/v*/campaign-notes.md` | `reference`, `client-private` | Client ad creative batches | Notes explaining the corresponding versioned ad images. | Keep aligned with image batches. |
| `media/ads/konecta-newsletter/ads/**/*.png` | `reference`, `generated` | Konecta internal newsletter example | Internal before/after creative reference. | Keep as reference unless superseded. |
| `media/presentations/loom-video-vender-a-contadores/**/*.html`, `*.txt`, `*.mjs`, `package*.json`, `README.md` | `public`, `reference` | Konecta presentation source | Source and build scripts for the Contadores Loom presentation. | Keep while presentation is maintained. |
| `media/presentations/loom-video-vender-a-contadores/*.pptx` | `public`, `generated` | Presentation export | Reproducible deck export for sharing. | May be regenerated from source; keep current approved export. |
| `media/presentations/loom-video-vender-a-contadores/*.zip` | `reference`, `generated`, `client-private` | Presentation export/source bundle | Historical export bundle. | Flag for owner review before keeping long term. Prefer regenerated exports in `output/`. |
| `media/presentations/loom-video-vender-a-contadores/screenshots/*.png` | `reference`, `generated` | Presentation screenshots | Slide screenshot references used during deck iteration. | Keep only if useful for deck review; new throwaway screenshots belong in `output/`. |
| `media/presentations/loom-video-vender-a-contadores/uploads/*` | `reference`, `client-private` | Raw presentation upload | Raw WhatsApp/source upload used by the deck. | Owner review before reuse or deletion; do not add more raw uploads without manifest update. |
| `media/presentations/loom-video-vender-a-negocios/**` | `public`, `reference` | Konecta presentation source/export | Source and approved export for the 60s negocios Loom deck. | Keep while presentation is maintained. |
| `abogados/media/presentations/loom-video-vender-a-abogados/**` | `public`, `reference`, `generated` | Abogados presentation source/export | Abogados counterpart presentation and screenshots. | Keep while Abogados funnel material is maintained. |
| `abogados/media/videos/loom_captions_abogados.mp4` | `public`, `template` | Abogados funnel media | Versioned outbound video asset. | Keep while referenced by Abogados funnel config. |
| `guido*.png`, `mmb-logo*.png` | `reference`, `generated`, `client-private` | Local browser/logo review screenshots | Root-level legacy screenshots retained for review history. | Owner review before deletion; future screenshots must go under `output/` or `data/`. |

## Risk Scan

Run this before committing media changes:

```bash
git ls-files media abogados/media '*.png' '*.jpg' '*.jpeg' '*.webp' '*.mp4' '*.mov' '*.pdf' '*.zip' |
  rg -n 'uploads|WhatsApp Image|preview|screenshots|professional-photo|\.zip$|\.mov$|\.mp4$|\.jpe?g$|\.png$'
```

Every hit must match a manifest row above or be moved to `data/`, `output/`, or
`tmp/` before commit.
