const processed = new Set();
const mountedControls = new Map();
let scanTimer = null;

function hash(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  return `arena_${Math.abs(h)}`;
}

function resultToText(result) {
  if (!result) return '';
  if (!Array.isArray(result.calls)) return JSON.stringify(result, null, 2);
  return result.calls.map((call) => {
    const parsed = call?.result?.parsed;
    if (parsed) return JSON.stringify(parsed, null, 2);
    if (call?.result?.text) return String(call.result.text);
    return JSON.stringify(call, null, 2);
  }).join('\n\n');
}

function makeButton(label, onClick) {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.style.cssText = 'padding:5px 9px;font-size:12px;cursor:pointer;border-radius:7px;border:1px solid #475569;background:#0f172a;color:#f8fafc;line-height:1.2;';
  btn.addEventListener('click', onClick);
  return btn;
}

function resultErrorText(result) {
  if (!result) return 'empty response';
  if (result.error) return String(result.error);
  const failed = Array.isArray(result.calls) ? result.calls.find((call) => call && call.ok === false) : null;
  const parsed = failed?.result?.parsed;
  return parsed?.error || parsed?.message || (failed?.result?.text ? String(failed.result.text).slice(0, 220) : '') || result.summary || (result.status ? `HTTP ${result.status}` : 'unknown');
}

function controlsHost(node) {
  if (!node) return document.body;
  if (node.tagName === 'CODE') return node.closest('pre') || node;
  return node;
}

function attachControls(host, bar) {
  const tag = String(host?.tagName || '').toUpperCase();
  bar.style.width = `${Math.max(280, Math.min(host.getBoundingClientRect?.().width || 680, 900))}px`;
  if ((tag === 'PRE' || tag === 'CODE') && host.parentNode) host.insertAdjacentElement('afterend', bar);
  else host.appendChild(bar);
}

function removeOldControls(keepFingerprint) {
  mountedControls.forEach((item, key) => {
    if (key === keepFingerprint) return;
    item.bar?.remove();
    if (item.host?.dataset) item.host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(key);
  });
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
  host = controlsHost(host);
  const fingerprint = host.dataset.arenaToolFingerprint || (typeof arenaMessageFingerprint === 'function' ? arenaMessageFingerprint(host, payload, adapter) : hash((host.textContent || '') + JSON.stringify(payload)));
  if (processed.has(fingerprint) || host.dataset.arenaToolControlsMounted === '1') return;
  processed.add(fingerprint);
  host.dataset.arenaToolControlsMounted = '1'; host.dataset.arenaToolFingerprint = fingerprint;
  const request = buildRequest(payload, adapter.name, fingerprint);
  chrome.runtime.sendMessage({type: 'arena.detected', body: {detail: `detected block on ${location.hostname}`, site: location.origin, adapter: adapter.name, fingerprint, payload: request}});
  let lastExecutionText = '';
  const bar = document.createElement('div');
  bar.dataset.arenaToolControls = '1';
  bar.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:8px 0 12px 0;padding:8px 10px;border:1px solid rgba(148,163,184,.45);border-radius:10px;background:linear-gradient(135deg,rgba(15,23,42,.96),rgba(30,41,59,.94));box-shadow:0 8px 24px rgba(15,23,42,.22);box-sizing:border-box;max-width:100%;clear:both;';
  const status = document.createElement('span');
  status.style.cssText = 'font-size:12px;color:#cbd5e1;font-weight:600;';
  status.textContent = `Arena tool block detected (${adapter.name})`;
  bar.appendChild(status);
  bar.appendChild(makeButton('Preview', async () => {
    status.textContent = 'Previewing...';
    const result = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
    status.textContent = result?.ok ? `Preview: ${result.calls?.length || 0} call(s), approval=${!!result.policy?.requires_approval}` : `Preview error: ${resultErrorText(result)}`;
  }));
  bar.appendChild(makeButton('Run', async () => {
    status.textContent = 'Running...';
    const result = await chrome.runtime.sendMessage({type: 'arena.execute', body: {...request, mode: {approve: true}}});
    if (Array.isArray(result?.calls)) lastExecutionText = resultToText(result);
    status.textContent = result?.ok ? `Executed ${result.calls?.length || 0} call(s)` : `Run error: ${resultErrorText(result)}`;
  }));
  bar.appendChild(makeButton('Insert Result', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const ok = (typeof arenaInsertResult === 'function' && arenaInsertResult(`\n${lastExecutionText}\n`, adapter)) || genericInsertIntoActiveField(`\n${lastExecutionText}\n`);
    status.textContent = ok ? 'Inserted into input.' : 'Could not insert; copy instead.';
  }));
  bar.appendChild(makeButton('Insert & Submit', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const state = typeof arenaInsertAndSubmit === 'function' ? await arenaInsertAndSubmit(`\n${lastExecutionText}\n`, adapter) : {ok: false, inserted: false, submitted: false};
    status.textContent = state.ok ? (state.submitted ? 'Inserted and submitted.' : 'Inserted, but submit button not found.') : 'Insert & submit failed.';
  }));
  bar.appendChild(makeButton('Copy Result', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    try {
      await navigator.clipboard.writeText(lastExecutionText);
      status.textContent = 'Result copied.';
    } catch (e) { status.textContent = `Copy failed: ${e}`; }
  }));
  bar.appendChild(makeButton('Panel', async () => {
    const result = await chrome.runtime.sendMessage({type: 'arena.openSidePanel'});
    status.textContent = result?.ok ? 'Opened side panel.' : `Panel error: ${result?.error || 'unknown'}`;
  }));
  attachControls(host, bar);
  mountedControls.set(fingerprint, {host, bar});
  chrome.runtime.sendMessage({type: 'arena.getConfig'}, (cfg) => {
    const modes = typeof arenaNormalizeModes === 'function' ? arenaNormalizeModes(cfg?.modes) : (cfg?.modes || {});
    if (modes.controlsLatestOnly) removeOldControls(fingerprint);
  });
  runAutoModes(request, adapter, status, (text) => { lastExecutionText = text; });
}

async function runAutoModes(request, adapter, status, setResultText) {
  const cfg = await chrome.runtime.sendMessage({type: 'arena.getConfig'});
  const modes = typeof arenaNormalizeModes === 'function' ? arenaNormalizeModes(cfg?.modes) : (cfg?.modes || {});
  if (!modes.autoPreview && !modes.autoExecuteSafe) return;
  status.textContent = modes.autoExecuteSafe ? 'Auto previewing before safe execution...' : 'Auto previewing...';
  const preview = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
  if (!preview?.ok) { status.textContent = `Auto preview error: ${resultErrorText(preview)}`; return; }
  if (!modes.autoExecuteSafe || !preview.policy?.can_auto_run) {
    status.textContent = `Preview ready: approval=${!!preview.policy?.requires_approval}`;
    return;
  }
  status.textContent = 'Auto executing safe call(s)...';
  const result = await chrome.runtime.sendMessage({type: 'arena.execute', body: {...request, mode: {}}});
  if (!result?.ok) { status.textContent = `Auto run error: ${resultErrorText(result)}`; return; }
  const text = resultToText(result);
  setResultText(text);
  status.textContent = `Auto executed ${result.calls?.length || 0} call(s)`;
  if (!modes.autoInsertResult || !text) return;
  const insertText = `\n${text}\n`;
  const state = modes.autoSubmitResult && typeof arenaInsertAndSubmit === 'function'
    ? await arenaInsertAndSubmit(insertText, adapter)
    : {ok: (typeof arenaInsertResult === 'function' && arenaInsertResult(insertText, adapter)) || genericInsertIntoActiveField(insertText)};
  status.textContent = state.ok ? (state.submitted ? 'Auto inserted and submitted.' : 'Auto inserted result.') : 'Auto insert failed.';
}

function scan() {
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: [document.body]};
  state.nodes.forEach((node) => {
    const host = controlsHost(node);
    if (host.dataset?.arenaToolControlsMounted === '1') return;
    if (host.querySelector?.('[data-arena-tool-controls="1"]')) return;
    const blocks = parseArenaBlocks((typeof arenaNodeText === 'function' ? arenaNodeText(node) : (node.textContent || '')));
    blocks.forEach((entry) => mountControls(host, entry.payload, state.adapter));
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
