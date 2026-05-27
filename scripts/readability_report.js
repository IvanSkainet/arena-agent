const { chromium } = require('playwright-core');
const { JSDOM } = require('jsdom');
const { Readability } = require('@mozilla/readability');
const TurndownService = require('turndown');
const fs = require('fs');
const path = require('path');
async function main(){
  const root=process.env.ARENA_AGENT_HOME || path.join(process.env.HOME, 'arena-bridge');
  const outDir=path.join(root,'reports'); fs.mkdirSync(outDir,{recursive:true});
  const url=process.argv[2] || 'https://example.com';
  const stamp=new Date().toISOString().replace(/[:.]/g,'-');
  const exe=process.env.CHROMIUM_PATH || '/usr/bin/chromium';
  const browser=await chromium.launch({headless: process.env.HEADLESS !== '0', executablePath: fs.existsSync(exe)?exe:undefined, args:['--no-first-run','--disable-dev-shm-usage']});
  const page=await browser.newPage({viewport:{width:1365,height:768}});
  await page.goto(url,{waitUntil:'domcontentloaded',timeout:90000}); await page.waitForTimeout(1000);
  const finalUrl=page.url(); const title=await page.title(); const html=await page.content(); await browser.close();
  const dom=new JSDOM(html,{url:finalUrl}); const article=new Readability(dom.window.document).parse(); const turndown=new TurndownService();
  const markdown=article && article.content ? turndown.turndown(article.content) : '';
  const base=path.join(outDir,`readability-${stamp}`);
  fs.writeFileSync(base+'.html', html); fs.writeFileSync(base+'.json', JSON.stringify({ok:true, requested_url:url, final_url:finalUrl, page_title:title, article}, null, 2));
  fs.writeFileSync(base+'.md', `# ${article?.title || title}\n\n- Requested: ${url}\n- Final: ${finalUrl}\n- Extracted length: ${markdown.length}\n\n${markdown}\n`);
  console.log(JSON.stringify({ok:true, markdown:base+'.md', json:base+'.json', html:base+'.html', title:article?.title || title, final_url:finalUrl}, null, 2));
}
main().catch(e=>{console.error(e); process.exit(1);});
