const ARENA_CONTENT_SCRIPT_VERSION = '0.12.7';
const processed = new Set();
const mountedControls = new Map();
const dismissedControls = new Set();
let scanTimer = null;
function arenaExtensionVersion() {
  try { return chrome.runtime.getManifest?.().version || ARENA_CONTENT_SCRIPT_VERSION; } catch (_e) { return ARENA_CONTENT_SCRIPT_VERSION; }
}
function versionSummary() {
  return `ext ${arenaExtensionVersion()}/content ${ARENA_CONTENT_SCRIPT_VERSION}`;
}
function hash(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  return `arena_${Math.abs(h)}`;
}
function formatInsertText(text) {
  const body = String(text || '').trim();
  if (!body) return '';
  return `\n\n\`\`\`json\n${body}\n\`\`\`\n`;
}
function resultToText(result) {
  if (!result) return '';
  if (!Array.isArray(result.calls)) return JSON.stringify(result, null, 2);
  return result.calls.map((call) => call?.result?.parsed ? JSON.stringify(call.result.parsed, null, 2) : (call?.result?.text ? String(call.result.text) : JSON.stringify(call, null, 2))).join('\n\n');
}
function makeButton(label, onClick, primary = false) {
  const btn = document.createElement('button');
  btn.textContent = label;
  const bg = primary ? '#2563eb' : 'rgba(15,23,42,.72)';
  const border = primary ? '#3b82f6' : 'rgba(148,163,184,.38)';
  btn.style.cssText = `padding:5px 10px;font-size:12px;cursor:pointer;border-radius:999px;border:1px solid ${border};background:${bg};color:#f8fafc;line-height:1.2;font-weight:600;`;
  // Keep the chat composer focused while clicking Arena controls. Gemini in
  // particular does expensive synchronous work on blur/focus churn, which made
  // Insert/Send feel ~1s slower after controls became clickable toolbar buttons.
  btn.addEventListener('pointerdown', (event) => event.preventDefault());
  btn.addEventListener('mousedown', (event) => event.preventDefault());
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
  return !node ? document.body : (node.tagName === 'CODE' ? (node.closest('pre') || node) : node);
}
function attachControls(host, bar) {
  const tag = String(host?.tagName || '').toUpperCase();
  bar.style.width = `${Math.max(280, Math.min(host.getBoundingClientRect?.().width || 680, 900))}px`;
  if ((tag === 'PRE' || tag === 'CODE') && host.parentNode) host.insertAdjacentElement('afterend', bar); else host.appendChild(bar);
}
function cleanupStaleControls() {
  document.querySelectorAll('[data-arena-tool-controls="1"]').forEach((bar) => bar.remove());
  document.querySelectorAll('[data-arena-tool-controls-mounted="1"]').forEach((node) => { node.dataset.arenaToolControlsMounted = ''; });
  mountedControls.clear();
}
function suppressCurrentControls() {
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: []};
  state.nodes.forEach((node) => parseArenaBlocks((typeof arenaDetectionText === 'function' ? arenaDetectionText(node, state.adapter) : (node.textContent || ''))).forEach((entry) => {
    const host = controlsHost(node);
    dismissedControls.add(typeof arenaMessageFingerprint === 'function' ? arenaMessageFingerprint(host, entry.payload, state.adapter) : hash((host.textContent || '') + JSON.stringify(entry.payload)));
  }));
}
function hostHasToolbar(host) {
  return !!(host?.dataset?.arenaToolControlsMounted === '1' && (host.nextElementSibling?.dataset?.arenaToolControls === '1' || host.querySelector?.('[data-arena-tool-controls="1"]')));
}
function buildRequest(payload, adapterName, fingerprint) {
  return {site: {origin: location.origin, url: location.href, adapter: adapterName}, message: {fingerprint}, payload, mode: {}};
}
function genericInsertIntoActiveField(text, strategy = 'auto') {
  const active = document.activeElement;
  if (active && (active.tagName === 'TEXTAREA' || (active.tagName === 'INPUT' && active.type === 'text'))) {
    const start = active.selectionStart ?? active.value.length;
    const end = active.selectionEnd ?? active.value.length;
    active.value = `${active.value.slice(0, start)}${text}${active.value.slice(end)}`;
    active.dispatchEvent(new Event('input', {bubbles: true}));
    return true;
  }
  if (active && active.isContentEditable) { return (typeof arenaInsertIntoEditable === 'function') ? arenaInsertIntoEditable(active, text, strategy) : (document.execCommand('insertText', false, text), true); }
  return false;
}
function attemptsSummary(timing) {
  const attempts = Array.isArray(timing?.attempts) ? timing.attempts : [];
  if (!attempts.length) return '';
  return ` Attempts: ${attempts.map((item) => `${item.strategy}:${item.settled ? 'ok' : (item.changed ? 'changed' : 'no-change')}`).join(', ')}.`;
}
function timingSummary(timing) {
  const strategy = timing?.strategy || timing?.method || 'unknown';
  const requested = timing?.requested_strategy;
  const prefix = requested === 'auto' && strategy !== 'auto' ? `Auto used ${strategy}` : `via ${strategy}`;
  const ms = timing?.total_ms ?? timing?.insert_ms ?? '?';
  const verify = timing?.verify_ms ? `, verified +${timing.verify_ms}ms` : '';
  return `${prefix} in ${ms}ms${verify} · ${versionSummary()}`;
}
function insertFailureSummary(strategy, timing) {
  const requested = timing?.requested_strategy || strategy;
  const settled = timing?.settled === false ? 'not settled in composer' : 'not inserted';
  const prefix = requested === 'auto' ? 'Auto insert failed' : `Could not insert via ${strategy}`;
  return `${prefix}: ${settled}; copy instead.${attemptsSummary(timing)}`;
}
async function currentInsertStrategy() {
  try {
    const cfg = await chrome.runtime.sendMessage({type: 'arena.getConfig'});
    return cfg?.modes?.insertStrategy || 'auto';
  } catch (_e) { return 'auto'; }
}
function previewSummary(result) {
  const calls = Array.isArray(result?.calls) ? result.calls : [];
  const tools = calls.map((call) => call.tool || call.name).filter(Boolean).slice(0, 3).join(', ');
  return `Dry run: ${calls.length} call(s)${tools ? ` · ${tools}` : ''} · approval=${!!result?.policy?.requires_approval}`;
}
function mountControls(host, payload, adapter) {
  host = controlsHost(host);
  const fingerprint = typeof arenaMessageFingerprint === 'function' ? arenaMessageFingerprint(host, payload, adapter) : hash((host.textContent || '') + JSON.stringify(payload));
  const existing = mountedControls.get(fingerprint);
  if (dismissedControls.has(fingerprint) || (existing?.bar?.isConnected) || hostHasToolbar(host)) return;
  const firstSeen = !processed.has(fingerprint);
  processed.add(fingerprint);
  host.dataset.arenaToolControlsMounted = '1'; host.dataset.arenaToolFingerprint = fingerprint;
  const request = buildRequest(payload, adapter.name, fingerprint);
  if (firstSeen) chrome.runtime.sendMessage({type: 'arena.detected', body: {detail: `detected block on ${location.hostname}`, site: location.origin, adapter: adapter.name, fingerprint, payload: request}});
  let lastExecutionText = '';
  const bar = document.createElement('div');
  bar.dataset.arenaToolControls = '1';
  bar.style.cssText = 'display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:8px 0 12px 0;padding:7px 9px;border:1px solid rgba(148,163,184,.34);border-radius:12px;background:rgba(15,23,42,.92);box-shadow:0 6px 18px rgba(15,23,42,.18);box-sizing:border-box;max-width:100%;clear:both;backdrop-filter:blur(8px);';
  const status = document.createElement('span');
  status.style.cssText = 'font-size:12px;color:#bfdbfe;font-weight:700;margin-right:2px;';
  status.textContent = `Arena · ${adapter.name}`;
  bar.appendChild(status);
  bar.appendChild(makeButton('Preview', async () => {
    status.textContent = 'Previewing...';
    const result = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
    status.textContent = result?.ok ? previewSummary(result) : `Preview error: ${resultErrorText(result)}`;
  }));
  bar.appendChild(makeButton('Run', async () => {
    status.textContent = 'Running...';
    const result = await chrome.runtime.sendMessage({type: 'arena.execute', body: {...request, mode: {approve: true}}});
    if (Array.isArray(result?.calls)) lastExecutionText = resultToText(result);
    status.textContent = result?.ok ? `Executed ${result.calls?.length || 0} call(s)` : `Run error: ${resultErrorText(result)}`;
  }, true));
  bar.appendChild(makeButton('Insert', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const insertText = formatInsertText(lastExecutionText);
    const strategy = await currentInsertStrategy();
    let ok = false;
    if (typeof arenaInsertResult === 'function') ok = await arenaInsertResult(insertText, adapter, strategy);
    else ok = genericInsertIntoActiveField(insertText, strategy);
    const timing = window.__arenaLastInsertTiming || {};
    status.textContent = ok ? `Inserted ${timingSummary(timing)}.` : insertFailureSummary(strategy, timing);
  }));
  bar.appendChild(makeButton('Send', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const strategy = await currentInsertStrategy();
    const state = typeof arenaInsertAndSubmit === 'function' ? await arenaInsertAndSubmit(formatInsertText(lastExecutionText), adapter, strategy) : {ok: false, inserted: false, submitted: false};
    status.textContent = state.ok ? (state.submitted ? `Inserted/submitted ${timingSummary(state)}.` : `Inserted ${timingSummary(state)}, submit not found.`) : `Insert & submit failed. ${insertFailureSummary(strategy, state)}`;
  }));
  bar.appendChild(makeButton('Copy', async () => {
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
  bar.appendChild(makeButton('×', () => { dismissedControls.add(fingerprint); bar.remove(); host.dataset.arenaToolControlsMounted = ''; mountedControls.delete(fingerprint); }));
  attachControls(host, bar);
  mountedControls.set(fingerprint, {host, bar});
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
  const insertText = formatInsertText(text);
  let state;
  if (modes.autoSubmitResult && typeof arenaInsertAndSubmit === 'function') {
    state = await arenaInsertAndSubmit(insertText, adapter, modes.insertStrategy || 'auto');
  } else if (typeof arenaInsertResult === 'function') {
    const ok = await arenaInsertResult(insertText, adapter, modes.insertStrategy || 'auto');
    state = {ok, ...(window.__arenaLastInsertTiming || {})};
  } else {
    state = {ok: genericInsertIntoActiveField(insertText, modes.insertStrategy || 'auto')};
  }
  status.textContent = state.ok ? (state.submitted ? `Auto inserted/submitted ${timingSummary(state)}.` : `Auto inserted ${timingSummary(state)}.`) : insertFailureSummary(modes.insertStrategy || 'auto', state);
}
function scan() {
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: [document.body]};
  state.nodes.forEach((node) => {
    const host = controlsHost(node);
    if (hostHasToolbar(host)) return;
    parseArenaBlocks((typeof arenaDetectionText === 'function' ? arenaDetectionText(node, state.adapter) : (node.textContent || ''))).forEach((entry) => mountControls(host, entry.payload, state.adapter));
  });
}

function scanPageDiagnostics() {
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: [document.body]};
  const samples = [];
  let parsedBlocks = 0;
  const tools = new Set();
  state.nodes.forEach((node, index) => {
    const text = typeof arenaDetectionText === 'function' ? arenaDetectionText(node, state.adapter) : (node.textContent || '');
    const entries = parseArenaBlocks(text);
    parsedBlocks += entries.length;
    entries.forEach((entry) => (entry.payload?.calls || []).forEach((call) => tools.add(call.tool)));
    if (samples.length < 5) samples.push({index, tag: node.tagName || '', text: String(text).slice(0, 240), parsed: entries.length, tools: entries.flatMap((entry) => (entry.payload?.calls || []).map((call) => call.tool))});
  });
  const selectorHits = typeof arenaSelectorDiagnostics === 'function' ? arenaSelectorDiagnostics() : [];
  const composer = typeof arenaComposerDiagnostics === 'function' ? arenaComposerDiagnostics(state.adapter) : null;
  return {ok: true, url: location.href, host: location.hostname, adapter: state.adapter?.name || 'generic', content_version: ARENA_CONTENT_SCRIPT_VERSION, manifest_version: arenaExtensionVersion(), insert_script_version: (typeof arenaInsertScriptVersion === 'function' ? arenaInsertScriptVersion() : 'unknown'), composer, candidate_nodes: state.nodes.length, parsed_blocks: parsedBlocks, mounted_controls: document.querySelectorAll('[data-arena-tool-controls="1"]').length, dismissed_controls: dismissedControls.size, tools: [...tools], selector_hits: selectorHits, samples};
}
function scheduleScan() {
  if (scanTimer) return;
  const run = () => { scanTimer = null; scan(); };
  scanTimer = setTimeout(() => {
    if (typeof requestIdleCallback === 'function') requestIdleCallback(run, {timeout: 800});
    else run();
  }, 500);
}
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === 'arena.clearPageControls') { suppressCurrentControls(); cleanupStaleControls(); sendResponse?.({ok: true, dismissed: dismissedControls.size}); return true; }
  if (message?.type === 'arena.showPageControls') { dismissedControls.clear(); cleanupStaleControls(); setTimeout(scan, 0); sendResponse?.({ok: true}); return true; }
  if (message?.type === 'arena.controlsModeChanged') { setTimeout(scan, 0); sendResponse?.({ok: true}); return true; }
  if (message?.type === 'arena.scanPage') { sendResponse?.(scanPageDiagnostics()); return true; }
  return false;
});
cleanupStaleControls();
const obs = new MutationObserver(() => scheduleScan());
obs.observe(document.documentElement, {childList: true, subtree: true});
scan();
