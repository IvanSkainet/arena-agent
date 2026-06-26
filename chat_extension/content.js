const BLOCK_RE = /```arena-tool\s*([\s\S]*?)```/g;
const processed = new Set();
let scanTimer = null;

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

function resultToText(result) {
  if (!result) return '';
  if (Array.isArray(result.calls)) {
    return result.calls.map((call) => {
      const parsed = call?.result?.parsed;
      if (parsed) return JSON.stringify(parsed, null, 2);
      if (call?.result?.text) return String(call.result.text);
      return JSON.stringify(call, null, 2);
    }).join('\n\n');
  }
  return JSON.stringify(result, null, 2);
}

function makeButton(label, onClick) {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.style.cssText = 'padding:4px 8px;font-size:12px;cursor:pointer;border-radius:6px;border:1px solid #888;background:#111;color:#fff;';
  btn.addEventListener('click', onClick);
  return btn;
}

function buildRequest(payload, adapterName, fingerprint) {
  return {
    site: {origin: location.origin, url: location.href, adapter: adapterName},
    message: {fingerprint},
    payload,
    mode: {},
  };
}

function genericInsertIntoActiveField(text) {
  const active = document.activeElement;
  if (active && (active.tagName === 'TEXTAREA' || (active.tagName === 'INPUT' && active.type === 'text'))) {
    const start = active.selectionStart ?? active.value.length;
    const end = active.selectionEnd ?? active.value.length;
    active.value = `${active.value.slice(0, start)}${text}${active.value.slice(end)}`;
    active.dispatchEvent(new Event('input', {bubbles: true}));
    return true;
  }
  if (active && active.isContentEditable) {
    document.execCommand('insertText', false, text);
    return true;
  }
  return false;
}

function mountControls(host, payload, adapter) {
  const fingerprint = typeof arenaMessageFingerprint === 'function' ? arenaMessageFingerprint(host, payload, adapter) : hash((host.textContent || '') + JSON.stringify(payload));
  if (processed.has(fingerprint)) return;
  processed.add(fingerprint);
  const request = buildRequest(payload, adapter.name, fingerprint);
  chrome.runtime.sendMessage({type: 'arena.detected', body: {detail: `detected block on ${location.hostname}`, site: location.origin, adapter: adapter.name, fingerprint, payload: request}});
  let lastExecutionText = '';
  const bar = document.createElement('div');
  bar.dataset.arenaToolControls = '1';
  bar.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;padding:6px 0;';
  const status = document.createElement('span');
  status.style.cssText = 'font-size:12px;color:#888;';
  status.textContent = `Arena tool block detected (${adapter.name})`;
  bar.appendChild(status);
  bar.appendChild(makeButton('Preview', async () => {
    status.textContent = 'Previewing...';
    const result = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
    status.textContent = result?.ok ? `Preview: ${result.calls?.length || 0} call(s), approval=${!!result.policy?.requires_approval}` : `Preview error: ${result?.error || 'unknown'}`;
  }));
  bar.appendChild(makeButton('Run', async () => {
    status.textContent = 'Running...';
    const result = await chrome.runtime.sendMessage({type: 'arena.execute', body: {...request, mode: {approve: true}}});
    if (result?.ok) {
      lastExecutionText = resultToText(result);
      status.textContent = `Executed ${result.calls?.length || 0} call(s)`;
    } else {
      status.textContent = `Run error: ${result?.error || 'unknown'}`;
    }
  }));
  bar.appendChild(makeButton('Insert Result', async () => {
    if (!lastExecutionText) {
      status.textContent = 'No result yet. Run first.';
      return;
    }
    const ok = (typeof arenaInsertResult === 'function' && arenaInsertResult(`\n${lastExecutionText}\n`, adapter)) || genericInsertIntoActiveField(`\n${lastExecutionText}\n`);
    status.textContent = ok ? 'Inserted into input.' : 'Could not insert; copy instead.';
  }));
  bar.appendChild(makeButton('Insert & Submit', async () => {
    if (!lastExecutionText) {
      status.textContent = 'No result yet. Run first.';
      return;
    }
    const state = (typeof arenaInsertAndSubmit === 'function' && arenaInsertAndSubmit(`\n${lastExecutionText}\n`, adapter)) || {ok: false, inserted: false, submitted: false};
    status.textContent = state.ok ? (state.submitted ? 'Inserted and submitted.' : 'Inserted, but submit button not found.') : 'Insert & submit failed.';
  }));
  bar.appendChild(makeButton('Copy Result', async () => {
    if (!lastExecutionText) {
      status.textContent = 'No result yet. Run first.';
      return;
    }
    try {
      await navigator.clipboard.writeText(lastExecutionText);
      status.textContent = 'Result copied.';
    } catch (e) {
      status.textContent = `Copy failed: ${e}`;
    }
  }));
  bar.appendChild(makeButton('Panel', async () => {
    const result = await chrome.runtime.sendMessage({type: 'arena.openSidePanel'});
    status.textContent = result?.ok ? 'Opened side panel.' : `Panel error: ${result?.error || 'unknown'}`;
  }));
  host.appendChild(bar);
}

function scan() {
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: [document.body]};
  state.nodes.forEach((node) => {
    if (node.querySelector?.('[data-arena-tool-controls="1"]')) return;
    const blocks = parseArenaBlocks((typeof arenaNodeText === 'function' ? arenaNodeText(node) : (node.textContent || '')));
    blocks.forEach((entry) => mountControls(node, entry.payload, state.adapter));
  });
}

function scheduleScan() {
  if (scanTimer) return;
  scanTimer = setTimeout(() => {
    scanTimer = null;
    scan();
  }, 250);
}

const obs = new MutationObserver(() => scheduleScan());
obs.observe(document.documentElement, {childList: true, subtree: true, characterData: true});
scan();
