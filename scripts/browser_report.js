const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');

async function main() {
  const root = process.env.ARENA_AGENT_HOME || path.join(process.env.HOME, 'arena-bridge');
  const outDir = path.join(root, 'reports');
  fs.mkdirSync(outDir, { recursive: true });
  const url = process.argv[2] || 'https://example.com';
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const exe = process.env.CHROMIUM_PATH || '/usr/bin/chromium';
  const headless = process.env.HEADLESS !== '0';
  const browser = await chromium.launch({ headless, executablePath: fs.existsSync(exe) ? exe : undefined, args: ['--no-first-run', '--disable-dev-shm-usage'] });
  const page = await browser.newPage({ viewport: { width: +(process.env.VIEWPORT_W || 1365), height: +(process.env.VIEWPORT_H || 768) } });
  const started = Date.now();
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForTimeout(1000);
  const data = await page.evaluate(() => ({
    title: document.title,
    url: location.href,
    text: document.body ? document.body.innerText.slice(0, 20000) : '',
    links: Array.from(document.links).slice(0, 200).map(a => ({ text: a.innerText.slice(0,120), href: a.href })),
    meta: Array.from(document.querySelectorAll('meta')).map(m => ({ name: m.getAttribute('name'), property: m.getAttribute('property'), content: m.getAttribute('content') })).filter(x => x.name || x.property || x.content).slice(0,200),
    navigator: { ua: navigator.userAgent, platform: navigator.platform, languages: navigator.languages, webdriver: navigator.webdriver, hw: navigator.hardwareConcurrency, mem: navigator.deviceMemory },
    screen: { w: screen.width, h: screen.height, aw: screen.availWidth, ah: screen.availHeight, dpr: devicePixelRatio }
  }));
  const png = path.join(outDir, `browser-report-${stamp}.png`);
  const jsonPath = path.join(outDir, `browser-report-${stamp}.json`);
  const mdPath = path.join(outDir, `browser-report-${stamp}.md`);
  await page.screenshot({ path: png, fullPage: true });
  await browser.close();
  const report = { ok: true, requested_url: url, elapsed_ms: Date.now()-started, headless, executablePath: exe, screenshot: png, data };
  fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2));
  fs.writeFileSync(mdPath, `# Browser report\n\n- Requested: ${url}\n- Final: ${data.url}\n- Title: ${data.title}\n- Screenshot: ${png}\n- JSON: ${jsonPath}\n\n## Navigator\n\n\`\`\`json\n${JSON.stringify(data.navigator, null, 2)}\n\`\`\`\n\n## Text preview\n\n${data.text.slice(0,4000)}\n`);
  console.log(JSON.stringify({ ok: true, screenshot: png, json: jsonPath, markdown: mdPath, title: data.title, final_url: data.url }, null, 2));
}
main().catch(err => { console.error(err); process.exit(1); });
