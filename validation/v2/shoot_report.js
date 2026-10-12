// Full-page screenshots of the report via sandboxed Snap Chromium (review aid only).
const { chromium } = require('/home/ubuntu/.nvm/versions/node/v22.19.0/lib/node_modules/playwright');
const pages = process.argv.slice(3);
const outDir = process.argv[2];
(async () => {
  const browser = await chromium.launch({ headless: true, chromiumSandbox: true, executablePath: '/snap/bin/chromium' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  for (const p of pages) {
    await page.goto('http://127.0.0.1:8766/report/' + p, { waitUntil: 'load' });
    const errors = await page.evaluate(() => [...document.images].filter(i => !i.complete || !i.naturalWidth).map(i => i.src));
    const name = p.replace(/\//g, '_').replace('.html', '.png');
    await page.screenshot({ path: `${outDir}/${name}`, fullPage: true });
    const h = await page.evaluate(() => document.body.scrollHeight);
    console.log(p, 'height', h, 'broken images', errors.length);
  }
  await browser.close();
})();
