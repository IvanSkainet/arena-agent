const { chromium } = require('playwright-core');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const cp = require('child_process');

function stamp() { return new Date().toISOString().replace(/[:.]/g, '-'); }
function sha256(s) { return crypto.createHash('sha256').update(String(s)).digest('hex'); }
function cliChromium(cmd, url, outDir, exe) {
  const st = stamp();
  if (cmd === 'screenshot') {
    const png = path.join(outDir, `screenshot-cli-${st}.png`);
    try {
      cp.execFileSync(exe, ['--headless','--no-sandbox','--disable-gpu',`--screenshot=${png}`,url], {stdio:['ignore','pipe','pipe'], timeout:90000});
      return {ok:true, cmd, fallback:'chromium-cli', requested_url:url, screenshot:png};
    } catch (e) {
      let title = 'Screenshot unavailable';
      try {
        const html = cp.execFileSync(exe, ['--headless','--no-sandbox','--disable-gpu','--dump-dom',url], {encoding:'utf8', timeout:90000});
        title = (html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)||[])[1] || title;
        fs.writeFileSync(png + '.html', html);
      } catch {}
      try {
        cp.execFileSync('magick', ['-size','1365x768','xc:#f8f8f8','-fill','#111111','-pointsize','24','-annotate','+30+60',`Browser screenshot fallback\n${url}\n${title}`, png], {stdio:'ignore', timeout:30_000});
      } catch { fs.writeFileSync(png + '.txt', `Browser screenshot fallback\n${url}\n${title}\n${e.message}`); }
      return {ok:true, cmd, fallback:'placeholder-after-cli-failure', requested_url:url, screenshot:fs.existsSync(png)?png:null, note:String(e.message).slice(0,300)};
    }
  }
  if (cmd === 'dump' || cmd === 'metadata') {
    const html = cp.execFileSync(exe, ['--headless','--no-sandbox','--disable-gpu','--dump-dom',url], {encoding:'utf8', timeout:90000});
    const base = path.join(outDir, `page-dump-cli-${st}`);
    fs.writeFileSync(base+'.html', html); fs.writeFileSync(base+'.txt', html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim());
    const title = (html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)||[])[1] || '';
    const json = {ok:true, cmd, fallback:'chromium-cli', requested_url:url, title, html:base+'.html', text:base+'.txt'};
    fs.writeFileSync(base+'.json', JSON.stringify(json,null,2)); return json;
  }
  return {ok:false, cmd, fallback:'chromium-cli', error:'no CLI fallback for this command'};
}
async function launch() {
  const exe = process.env.CHROMIUM_PATH || '/usr/bin/chromium';
  const headless = process.env.HEADLESS !== '0';
  const browser = await chromium.launch({ headless, executablePath: fs.existsSync(exe) ? exe : undefined, args: ['--no-first-run','--disable-dev-shm-usage','--disable-gpu'] });
  const page = await browser.newPage({ viewport: { width: +(process.env.VIEWPORT_W || 1365), height: +(process.env.VIEWPORT_H || 768) } });
  return { browser, page, exe, headless };
}
async function goto(page, url) { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: +(process.env.PAGE_TIMEOUT || 90000) }); await page.waitForTimeout(+(process.env.PAGE_SETTLE_MS || 1000)); }
async function collectPage(page) { return await page.evaluate(() => ({title:document.title,url:location.href,lang:document.documentElement.lang||null,charset:document.characterSet,text:document.body?document.body.innerText.slice(0,50000):'',metas:Array.from(document.querySelectorAll('meta')).map(m=>({name:m.getAttribute('name'),property:m.getAttribute('property'),content:m.getAttribute('content')})).slice(0,300),links:Array.from(document.links).map(a=>({text:(a.innerText||'').trim().slice(0,160),href:a.href,rel:a.rel||''})).slice(0,1000),scripts:Array.from(document.scripts).map(s=>s.src||'[inline]').slice(0,500),stylesheets:Array.from(document.querySelectorAll('link[rel~="stylesheet"]')).map(l=>l.href).slice(0,200)})); }
async function collectFingerprint(page) { return await page.evaluate(async () => {
  function h(str){let x=2166136261; for(let i=0;i<str.length;i++){x^=str.charCodeAt(i); x=Math.imul(x,16777619);} return ('00000000'+(x>>>0).toString(16)).slice(-8)}
  let canvas=null; try{const c=document.createElement('canvas'); c.width=240; c.height=60; const ctx=c.getContext('2d'); ctx.font='16px Arial'; ctx.fillText('ArenaFingerprint 🧪',12,12); canvas={dataHash:h(c.toDataURL())}}catch(e){canvas={error:String(e)}}
  let webgl=null; try{const c=document.createElement('canvas'); const gl=c.getContext('webgl')||c.getContext('experimental-webgl'); if(gl){const dbg=gl.getExtension('WEBGL_debug_renderer_info'); webgl={vendor:dbg?gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL):gl.getParameter(gl.VENDOR),renderer:dbg?gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER),version:gl.getParameter(gl.VERSION),extensions:gl.getSupportedExtensions()||[]}}}catch(e){webgl={error:String(e)}}
  let battery=null; try{if(navigator.getBattery){const b=await navigator.getBattery(); battery={charging:b.charging,level:b.level,chargingTime:b.chargingTime,dischargingTime:b.dischargingTime}}}catch(e){battery={error:String(e)}}
  return {navigator:{userAgent:navigator.userAgent,platform:navigator.platform,languages:navigator.languages,language:navigator.language,webdriver:navigator.webdriver,hardwareConcurrency:navigator.hardwareConcurrency,deviceMemory:navigator.deviceMemory,maxTouchPoints:navigator.maxTouchPoints,cookieEnabled:navigator.cookieEnabled,pdfViewerEnabled:navigator.pdfViewerEnabled,plugins:Array.from(navigator.plugins||[]).map(p=>p.name),mimeTypes:Array.from(navigator.mimeTypes||[]).map(m=>m.type)},screen:{width:screen.width,height:screen.height,availWidth:screen.availWidth,availHeight:screen.availHeight,colorDepth:screen.colorDepth,pixelDepth:screen.pixelDepth,dpr:devicePixelRatio,innerWidth,innerHeight,outerWidth,outerHeight},intl:{timeZone:Intl.DateTimeFormat().resolvedOptions().timeZone,locale:Intl.DateTimeFormat().resolvedOptions().locale},features:{share:!!navigator.share,webgpu:!!navigator.gpu,bluetooth:!!navigator.bluetooth,mediaDevices:!!navigator.mediaDevices},battery,canvas,webgl};
});}
async function main() {
  const cmd = process.argv[2] || 'help'; const url = process.argv[3] || 'https://example.com';
  const root = process.env.ARENA_AGENT_HOME || path.join(process.env.HOME, 'arena-bridge'); const outDir = path.join(root, 'reports'); fs.mkdirSync(outDir,{recursive:true});
  if (cmd === 'help') { console.log('Usage: browser_lab.js {screenshot|dump|fingerprint|metadata} URL'); return; }
  const exe = process.env.CHROMIUM_PATH || '/usr/bin/chromium';
  let browser, page, headless=true;
  try { ({browser,page,exe:dummy,headless}=await launch()); await goto(page,url); } catch(e) { console.error('Playwright launch failed, using Chromium CLI fallback:', e.message); console.log(JSON.stringify(cliChromium(cmd,url,outDir,exe), null, 2)); return; }
  const st=stamp(); let result={ok:true,cmd,requested_url:url,final_url:page.url(),headless,executablePath:exe};
  if(cmd==='screenshot'){const png=path.join(outDir,`screenshot-${st}.png`); await page.screenshot({path:png,fullPage:true}); result.screenshot=png;}
  else if(cmd==='dump'||cmd==='metadata'){const data=await collectPage(page); const html=await page.content(); const base=path.join(outDir,`page-dump-${st}`); fs.writeFileSync(base+'.html',html); fs.writeFileSync(base+'.json',JSON.stringify({...result,data},null,2)); fs.writeFileSync(base+'.txt',data.text); result={...result,html:base+'.html',json:base+'.json',text:base+'.txt',title:data.title,links:data.links.length,scripts:data.scripts.length};}
  else if(cmd==='fingerprint'){const fp=await collectFingerprint(page); const jp=path.join(outDir,`fingerprint-${st}.json`); fs.writeFileSync(jp,JSON.stringify({...result,fingerprint:fp},null,2)); result={...result,json:jp,fingerprint:fp,fingerprint_sha256:sha256(JSON.stringify(fp))};}
  else throw new Error('unknown command '+cmd);
  await browser.close(); console.log(JSON.stringify(result,null,2));
}
main().catch(e=>{console.error(e);process.exit(1);});
