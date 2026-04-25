import { readFileSync, mkdirSync, rmSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import { chromium } from 'playwright';
import pptxgen from 'pptxgenjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const W = 1920;
const H = 1080;
const htmlPath = join(__dirname, 'deck-export.html');
const outPptx = join(__dirname, 'Konecta-Loom-Vender-a-Contadores-Final.pptx');
const tmpDir = join(__dirname, '.pptx-build');

function loadSpeakerNotes() {
  const html = readFileSync(htmlPath, 'utf8');
  const m = html.match(
    /<script type="application\/json" id="speaker-notes">\s*([\s\S]*?)\s*<\/script>/
  );
  if (!m) return [];
  try {
    const arr = JSON.parse(m[1]);
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

rmSync(tmpDir, { recursive: true, force: true });
mkdirSync(tmpDir, { recursive: true });

const notes = loadSpeakerNotes();
const fileUrl = `file://${htmlPath}`;

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: W, height: H },
  deviceScaleFactor: 2,
});
await page.goto(fileUrl, { waitUntil: 'networkidle' });
await page.evaluate(async () => {
  if (document.fonts?.ready) await document.fonts.ready;
});
await page.waitForTimeout(600);

const total = await page.evaluate(() => {
  const el = document.querySelector('deck-stage');
  return el ? el.length : 0;
});

const paths = [];
for (let i = 0; i < total; i++) {
  await page.evaluate((idx) => {
    document.querySelector('deck-stage').goTo(idx);
  }, i);
  await page.waitForTimeout(450);
  const png = join(tmpDir, `slide-${String(i + 1).padStart(2, '0')}.png`);
  await page.screenshot({
    path: png,
    clip: { x: 0, y: 0, width: W, height: H },
    type: 'png',
  });
  paths.push(png);
}

await browser.close();

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'Konecta Labs';
pptx.title = 'Loom — Vender a contadores';

for (let i = 0; i < paths.length; i++) {
  const slide = pptx.addSlide();
  slide.addImage({ path: paths[i], x: 0, y: 0, w: '100%', h: '100%' });
  const n = notes[i];
  if (n && typeof n === 'string') {
    slide.addNotes(n);
  }
}

await pptx.writeFile({ fileName: outPptx });
rmSync(tmpDir, { recursive: true, force: true });

console.log(outPptx);
