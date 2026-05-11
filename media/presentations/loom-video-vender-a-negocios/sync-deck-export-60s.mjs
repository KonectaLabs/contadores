import { readFileSync, writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = join(__dirname, 'Loom Script 60s.html');
const target = join(__dirname, 'deck-export-60s.html');

let html = readFileSync(source, 'utf8');

html = html.replace(
  '<title>Konecta Labs — Loom Script 60s Negocios</title>',
  '<title>Konecta Labs — Deck export 60s Negocios</title>'
);

if (!html.includes('.export-hidden{display:none!important;}')) {
  html = html.replace(
    'section{background:var(--paper);color:var(--ink);}',
    'section{background:var(--paper);color:var(--ink);}\n  .export-hidden{display:none!important;}'
  );
}

html = html.replace(
  '<deck-stage width="1920" height="1080">',
  '<deck-stage width="1920" height="1080" noscale>'
);

writeFileSync(target, html);
console.error('deck-export-60s.html ← Loom Script 60s.html');
