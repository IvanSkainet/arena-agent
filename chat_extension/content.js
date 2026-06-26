const BLOCK_RE = /```arena-tool\s*([\s\S]*?)```/g;
const processed = new Set();

function hash(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  return `arena_${Math.abs(h)}`;
}

function parseArenaBlocks(text) {
  const out = [];
  for (const match of text.matchAll(BLOCK_RE)) {
    try {
      out.push({raw: match[0], payload: JSON.parse(match[1])});
    } catch {}
  }
  return out;
}

function makeButton(label, onClick) {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.style.cssText = 'margin-left:8px;padding:4px 8px;font-size:12px;cursor:pointer;border-radius:6px;border:1px solid #888;background:#111;color:#fff;';
  btn.addEventListener('click', onClick);
  return btn;
}

function buildRequest(payload) {
  return {
    site: {origin: location.origin, url: location.href, adapter: 'generic'},
    message: {fingerprint: hash(location.href + JSON.stringify(payload))},
    payload,
    mode: {},
  };
}

function mountControls(host, payload) {
  const key = hash(host.textContent + JSON.stringify(payload));
  if (processed.has(key)) return;
  processed.add(key);
  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;gap:8px;align-items:center;margin-top:8px;';
  const status = document.createElement('span');
  status.style.cssText = 'font-size:12px;color:#888;';
  status.textContent = 'Arena tool block detected';
  bar.appendChild(status);
  bar.appendChild(makeButton('Preview', async () => {
    status.textContent = 'Previewing...';
    const result = await chrome.runtime.sendMessage({type: 'arena.preview', body: buildRequest(payload)});
    status.textContent = result?.ok ? `Preview: ${result.calls?.length || 0} call(s), approval=${!!result.policy?.requires_approval}` : `Preview error: ${result?.error || 'unknown'}`;
  }));
  bar.appendChild(makeButton('Run', async () => {
    status.textContent = 'Running...';
    const result = await chrome.runtime.sendMessage({type: 'arena.execute', body: {...buildRequest(payload), mode: {approve: true}}});
    status.textContent = result?.ok ? `Executed ${result.calls?.length || 0} call(s)` : `Run error: ${result?.error || 'unknown'}`;
  }));
  host.appendChild(bar);
}

function scan() {
  document.querySelectorAll('pre, code, article, main').forEach((node) => {
    const blocks = parseArenaBlocks(node.textContent || '');
    blocks.forEach((entry) => mountControls(node, entry.payload));
  });
}

const obs = new MutationObserver(() => scan());
obs.observe(document.documentElement, {childList: true, subtree: true, characterData: true});
scan();
