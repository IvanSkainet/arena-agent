const { chromium } = require("playwright-core");
const fs = require("fs");
const path = require("path");

async function main() {
  const root = process.env.ARENA_AGENT_HOME || path.join(process.env.HOME, "arena-bridge");
  const outDir = path.join(root, "reports");
  fs.mkdirSync(outDir, { recursive: true });
  const url = process.argv[2] || "https://example.com";
  const headless = process.env.HEADLESS !== "0";
  const executablePath = process.env.CHROMIUM_PATH || "/usr/bin/chromium";
  const browser = await chromium.launch({
    headless,
    executablePath: fs.existsSync(executablePath) ? executablePath : undefined,
    args: ["--no-first-run", "--disable-dev-shm-usage"]
  });
  const page = await browser.newPage({ viewport: { width: 1365, height: 768 } });
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  const data = await page.evaluate(() => ({
    title: document.title,
    url: location.href,
    ua: navigator.userAgent,
    platform: navigator.platform,
    languages: navigator.languages,
    webdriver: navigator.webdriver,
    hw: navigator.hardwareConcurrency,
    mem: navigator.deviceMemory,
    screen: { w: screen.width, h: screen.height, aw: screen.availWidth, ah: screen.availHeight, dpr: devicePixelRatio }
  }));
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const png = path.join(outDir, `browser-smoke-${stamp}.png`);
  await page.screenshot({ path: png, fullPage: true });
  await browser.close();
  console.log(JSON.stringify({ ok: true, headless, executablePath, screenshot: png, data }, null, 2));
}
main().catch(err => { console.error(err); process.exit(1); });
