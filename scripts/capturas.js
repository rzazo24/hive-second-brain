#!/usr/bin/env node
// Capturas de la app para revisar un cambio de interfaz antes de publicarlo.
//   node scripts/capturas.js [carpeta-de-salida] [url-base]
// Saca cada vista en PC (1280×800) y móvil (390×844), en claro y oscuro, en español y en inglés.
// Por defecto lee la app de http://127.0.0.1:8765 y guarda los PNG en /tmp/capturas.
// Necesita Playwright con Chromium; se busca en ~/.local/share/hive-shots (o en NODE_PATH).
const path = require('path');
const os = require('os');
const fs = require('fs');

let chromium;
try { ({ chromium } = require('playwright')); }
catch { ({ chromium } = require(path.join(os.homedir(), '.local/share/hive-shots/node_modules/playwright'))); }

const out = process.argv[2] || '/tmp/capturas';
const base = (process.argv[3] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const VIEWS = [['inicio', '#/'], ['explorar', '#/explorar'], ['ayuda', '#/ayuda'], ['anadir', '#/nueva'], ['pagina', '#/p/index']];
const DEVICES = { pc: { viewport: { width: 1280, height: 800 } }, movil: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 } };

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  const errors = [];
  for (const [dev, opts] of Object.entries(DEVICES)) {
    for (const theme of ['light', 'dark']) {
      for (const lang of ['es', 'en']) {
        // Sin service worker: así se ve siempre la versión del disco, no una copia guardada
        const ctx = await browser.newContext({ ...opts, colorScheme: theme, serviceWorkers: 'block' });
        await ctx.addInitScript(([l]) => { try { localStorage.setItem('lang', l); } catch {} }, [lang]);
        const page = await ctx.newPage();
        page.on('pageerror', e => errors.push(`${dev}/${theme}/${lang}: ${e.message}`));
        for (const [name, hash] of VIEWS) {
          await page.goto(`${base}/${hash}`, { waitUntil: 'networkidle' });
          await page.waitForTimeout(300);
          const file = path.join(out, `${dev}-${name}-${theme}-${lang}.png`);
          await page.screenshot({ path: file, fullPage: false });
        }
        await ctx.close();
      }
    }
  }
  await browser.close();
  console.log(`Capturas en ${out}`);
  if (errors.length) { console.log('Errores de JavaScript:\n' + errors.join('\n')); process.exitCode = 1; }
})().catch(e => { console.error(e.message); process.exit(2); });
