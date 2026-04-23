import { readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = join(__dirname, 'Loom Script Reel.html');
const target = join(__dirname, 'deck-export-reel.html');

let html = readFileSync(source, 'utf8');

html = html.replace(
  '<title>Konecta Labs — Reel Script</title>',
  '<title>Konecta Labs — Reel export</title>'
);

if (!html.includes('.export-hidden{display:none!important;}')) {
  html = html.replace(
    'section{background:var(--paper);color:var(--ink);}',
    'section{background:var(--paper);color:var(--ink);}\n  .export-hidden{display:none!important;}'
  );
}

html = html.replace(
  '<deck-stage width="1080" height="1920">',
  '<deck-stage width="1080" height="1920" noscale>'
);

writeFileSync(target, html);
console.error('deck-export-reel.html ← Loom Script Reel.html');
