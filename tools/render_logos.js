// Render logos/*.svg to PNG files and a contact sheet.
// Usage: node tools/render_logos.js   (needs Playwright + Chromium)
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const dir = path.join(__dirname, '..', 'logos');
const names = {
  '01-nova': 'Nova', '02-orbit': 'Orbit J', '03-prism-x': 'Prism X', '04-constellation': 'Constellation',
  '05-liquid-drop': 'Liquid Drop', '06-hex-gate': 'Hex Gate', '07-ring-planet': 'Ring Planet',
  '08-comet': 'Comet', '09-shield-star': 'Shield Star', '10-spark-bloom': 'Spark Bloom',
};

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1024, height: 1024 }, deviceScaleFactor: 1 });
  fs.mkdirSync(path.join(dir, 'png'), { recursive: true });
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.svg')).sort();
  for (const f of files) {
    const svg = fs.readFileSync(path.join(dir, f), 'utf8');
    await page.setContent(`<html><body style="margin:0;background:transparent">${svg.replace('width="512" height="512"', 'width="1024" height="1024"')}</body></html>`);
    await page.screenshot({ path: path.join(dir, 'png', f.replace('.svg', '.png')), omitBackground: true, clip: { x: 0, y: 0, width: 1024, height: 1024 } });
  }
  // Contact sheet: dark row and light row, so each logo is checked on both.
  const tiles = Object.keys(names).map(k => {
    const svg = fs.readFileSync(path.join(dir, k + '.svg'), 'utf8').replace('width="512" height="512"', 'width="200" height="200"');
    return `<figure><div class="t">${svg}</div><div class="s"><span>${svg.replace(/id="/g, 'id="s' + k).replace(/url\(#/g, 'url(#s' + k)}</span></div><figcaption><b>${k.slice(0, 2)}</b> ${names[k]}</figcaption></figure>`;
  }).join('');
  const html = `<html><head><style>
    body{margin:0;background:#0d0620;font-family:'Inter','DejaVu Sans',sans-serif;color:#efe6ff;padding:48px 56px;width:1488px}
    h1{margin:0 0 6px;font-size:44px;letter-spacing:-.02em} p{margin:0 0 36px;color:#b9a7dc;font-size:20px}
    .g{display:grid;grid-template-columns:repeat(5,1fr);gap:28px}
    figure{margin:0;background:linear-gradient(160deg,#1c0b3a,#120626);border:1px solid #3a2466;border-radius:28px;padding:22px 18px 16px;display:flex;flex-direction:column;align-items:center;gap:12px}
    .t svg{display:block}
    .s{background:#f4effc;border-radius:16px;padding:8px 14px;display:flex;align-items:center;gap:10px}
    .s svg{width:44px;height:44px;display:block}
    figcaption{font-size:19px} figcaption b{color:#ff9f43;margin-right:6px}
  </style></head><body><h1>JStarx logo concepts</h1><p>10 concepts · purple and orange liquid glass · small tile shows each logo at 44 px on a light background</p><div class="g">${tiles}</div></body></html>`;
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.setContent(html);
  await page.screenshot({ path: path.join(dir, 'contact-sheet.png'), fullPage: true });
  await browser.close();
  console.log('rendered', files.length, 'logos + contact sheet');
})();
