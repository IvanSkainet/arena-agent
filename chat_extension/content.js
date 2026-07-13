const ARENA_CONTENT_SCRIPT_VERSION = '0.13.24';
const processed = new Set();
const mountedControls = new Map();
const mountedPayloadSemantics = new Set();
const mountedSemanticOwners = new Map();
const executionResults = new Map();
const dismissedControls = new Set();
const detectedPayloads = new Set();
let scanTimer = null;
let _contentConfigCache = null, _contentConfigCacheAt = 0;
async function getCachedConfig() {
  const now = Date.now();
  if (_contentConfigCache && (now - _contentConfigCacheAt) < 5000) return _contentConfigCache;
  try { _contentConfigCache = await chrome.runtime.sendMessage({type: 'arena.getConfig'}); _contentConfigCacheAt = now; } catch (_e) {}
  return _contentConfigCache || {};
}
try { chrome.storage.onChanged.addListener((_c, area) => { if (area === 'sync' || area === 'local') _contentConfigCache = null; }); } catch (_e) {}
function arenaExtensionVersion() {
  try { return chrome.runtime.getManifest?.().version || ARENA_CONTENT_SCRIPT_VERSION; } catch (_e) { return ARENA_CONTENT_SCRIPT_VERSION; }
}
function versionSummary() { return `ext ${arenaExtensionVersion()}/content ${ARENA_CONTENT_SCRIPT_VERSION}`; }
function hash(text) { let h = 0; for (let i = 0; i < text.length; i++) h = ((h << 5) - h + text.charCodeAt(i)) | 0; return `arena_${Math.abs(h)}`; }
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
  // Keep the composer focused; blur/focus churn slows some chat UIs.
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
  mountedControls.clear(); mountedPayloadSemantics.clear(); mountedSemanticOwners.clear(); executionResults.clear(); detectedPayloads.clear();
}
function pruneMountedControls() {
  [...mountedControls.entries()].forEach(([fingerprint, info]) => {
    if (info?.bar?.isConnected && info?.host?.isConnected) return;
    if (info?.host?.dataset) info.host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(fingerprint);
    if (info?.semanticFingerprint) { mountedPayloadSemantics.delete(info.semanticFingerprint); mountedSemanticOwners.delete(info.semanticFingerprint); }
  });
}
function suppressCurrentControls() {
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: []};
  state.nodes.forEach((node) => parseArenaBlocks((typeof arenaDetectionText === 'function' ? arenaDetectionText(node, state.adapter) : (node.textContent || ''))).forEach((entry) => {
    const host = controlsHost(node);
    dismissedControls.add(typeof arenaMessageFingerprint === 'function' ? arenaMessageFingerprint(host, entry.payload, state.adapter) : hash((host.textContent || '') + JSON.stringify(entry.payload)));
    dismissedControls.add(typeof arenaPayloadSemanticFingerprint === 'function' ? arenaPayloadSemanticFingerprint(entry.payload, state.adapter) : hash(JSON.stringify(entry.payload || {})));
  }));
}
function hostHasToolbar(host) {
  return !!(host?.dataset?.arenaToolControlsMounted === '1' && (host.nextElementSibling?.dataset?.arenaToolControls === '1' || host.querySelector?.('[data-arena-tool-controls="1"]')));
}
function buildRequest(payload, adapterName, fingerprint) {
  return {site: {origin: location.origin, url: location.href, adapter: adapterName}, message: {fingerprint}, payload, mode: {}};
}
function payloadTools(payload) { return (payload?.calls || []).map((call) => call.tool).filter(Boolean); }
function detectedDetail(payload, adapter) { return `detected ${payloadTools(payload).slice(0, 4).join(', ') || 'tool block'} on ${location.hostname}`; }
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
  const bridge = timing?.bridge_ms ? ` · bridge ${timing.bridge_ms}ms` : '';
  return `${prefix} in ${ms}ms${verify}${bridge} · ${versionSummary()}`;
}
function insertFailureSummary(strategy, timing) {
  const requested = timing?.requested_strategy || strategy;
  const settled = timing?.settled === false ? 'not settled in composer' : 'not inserted';
  const prefix = requested === 'auto' ? 'Auto insert failed' : `Could not insert via ${strategy}`;
  return `${prefix}: ${settled}; copy instead.${attemptsSummary(timing)}`;
}
async function currentInsertStrategy() {
  const cfg = await getCachedConfig();
  return cfg?.modes?.insertStrategy || 'auto';
}
function previewSummary(result) {
  const calls = Array.isArray(result?.calls) ? result.calls : [];
  const tools = calls.map((call) => call.tool || call.name).filter(Boolean).slice(0, 3).join(', ');
  return `Dry run: ${calls.length} call(s)${tools ? ` · ${tools}` : ''} · approval=${!!result?.policy?.requires_approval}`;
}
function mountControls(host, payload, adapter) {
  host = controlsHost(host);
  const fingerprint = typeof arenaMessageFingerprint === 'function' ? arenaMessageFingerprint(host, payload, adapter) : hash((host.textContent || '') + JSON.stringify(payload));
  const payloadFingerprint = typeof arenaPayloadFingerprint === 'function' ? arenaPayloadFingerprint(payload, adapter) : hash(JSON.stringify(payload || {}));
  const semanticFingerprint = typeof arenaPayloadSemanticFingerprint === 'function' ? arenaPayloadSemanticFingerprint(payload, adapter) : payloadFingerprint;
  const semanticOwner = mountedSemanticOwners.get(semanticFingerprint);
  if (semanticOwner && semanticOwner !== fingerprint) {
    const previous = mountedControls.get(semanticOwner);
    previous?.bar?.remove();
    if (previous?.host?.dataset) previous.host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(semanticOwner);
    mountedPayloadSemantics.delete(semanticFingerprint);
    mountedSemanticOwners.delete(semanticFingerprint);
  }
  const existing = mountedControls.get(fingerprint);
  if (dismissedControls.has(fingerprint) || dismissedControls.has(semanticFingerprint) || mountedPayloadSemantics.has(semanticFingerprint) || (existing?.bar?.isConnected) || hostHasToolbar(host)) return;
  const firstSeen = !processed.has(fingerprint);
  const firstPayloadSeen = !detectedPayloads.has(semanticFingerprint);
  processed.add(fingerprint); detectedPayloads.add(semanticFingerprint); mountedPayloadSemantics.add(semanticFingerprint);
  host.dataset.arenaToolControlsMounted = '1'; host.dataset.arenaToolFingerprint = fingerprint;
  const request = buildRequest(payload, adapter.name, fingerprint);
  if (firstSeen && firstPayloadSeen) chrome.runtime.sendMessage({type: 'arena.detected', body: {detail: detectedDetail(payload, adapter), site: location.origin, adapter: adapter.name, fingerprint, payload_fingerprint: semanticFingerprint, payload_instance_fingerprint: payloadFingerprint, tools: payloadTools(payload), payload: request}});
  let lastExecutionText = executionResults.get(semanticFingerprint) || '';
  const bar = document.createElement('div');
  bar.dataset.arenaToolControls = '1';
  bar.style.cssText = 'display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:8px 0 12px 0;padding:7px 9px;border:1px solid rgba(148,163,184,.34);border-radius:12px;background:rgba(15,23,42,.92);box-shadow:0 6px 18px rgba(15,23,42,.18);box-sizing:border-box;max-width:100%;clear:both;backdrop-filter:blur(8px);';
  const status = document.createElement('span');
  status.style.cssText = 'font-size:12px;color:#bfdbfe;font-weight:700;margin-right:2px;';
  status.textContent = lastExecutionText ? `Arena · ${adapter.name} · result ready` : `Arena · ${adapter.name}`;
  bar.appendChild(status);
  bar.appendChild(makeButton('Preview', async () => {
    status.textContent = 'Previewing...';
    const result = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
    status.textContent = result?.ok ? previewSummary(result) : `Preview error: ${resultErrorText(result)}`;
  }));
  bar.appendChild(makeButton('Run', async () => {
    status.textContent = 'Running...';
    const runStarted = performance.now();
    const result = await chrome.runtime.sendMessage({type: 'arena.execute', body: {...request, mode: {approve: true}}});
    const runMs = Math.round(performance.now() - runStarted);
    const bridgeMs = result?.bridge_ms || 0;
    if (Array.isArray(result?.calls)) {
      lastExecutionText = resultToText(result);
      if (lastExecutionText) executionResults.set(semanticFingerprint, lastExecutionText);
    }
    const timing = result?.ok ? ` in ${runMs}ms` : '';
    status.textContent = result?.ok ? `Executed ${result.calls?.length || 0} call(s)${timing}` : `Run error: ${resultErrorText(result)}`;
  }, true));
  bar.appendChild(makeButton('Insert', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const insertText = formatInsertText(lastExecutionText);
    const strategy = await currentInsertStrategy();
    let ok = false;
    if (typeof arenaInsertResult === 'function') ok = await arenaInsertResult(insertText, adapter, strategy);
    else ok = genericInsertIntoActiveField(insertText, strategy);
    const timing = {ok, ...(window.__arenaLastInsertTiming || {})};
    await arenaRecordInsertEvent('insert', request, adapter, timing, 'manual');
    status.textContent = ok ? `Inserted ${timingSummary(timing)}.` : insertFailureSummary(strategy, timing);
  }));
  bar.appendChild(makeButton('Send', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const strategy = await currentInsertStrategy();
    const state = typeof arenaInsertAndSubmit === 'function' ? await arenaInsertAndSubmit(formatInsertText(lastExecutionText), adapter, strategy) : {ok: false, inserted: false, submitted: false};
    await arenaRecordInsertEvent(state.submitted ? 'submit' : 'insert', request, adapter, state, 'manual');
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
  bar.appendChild(makeButton('×', () => { dismissedControls.add(fingerprint); dismissedControls.add(semanticFingerprint); bar.remove(); host.dataset.arenaToolControlsMounted = ''; mountedControls.delete(fingerprint); mountedPayloadSemantics.delete(semanticFingerprint); mountedSemanticOwners.delete(semanticFingerprint); }));
  attachControls(host, bar);
  mountedControls.set(fingerprint, {host, bar, semanticFingerprint});
  mountedSemanticOwners.set(semanticFingerprint, fingerprint);
  runAutoModes(request, adapter, status, semanticFingerprint, (text) => { lastExecutionText = text; });
}
async function runAutoModes(request, adapter, status, semanticFingerprint, setResultText) {
  const cfg = await getCachedConfig();
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
  if (text) executionResults.set(semanticFingerprint, text);
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
  await arenaRecordInsertEvent(state.submitted ? 'submit' : 'insert', request, adapter, state, 'auto');
  status.textContent = state.ok ? (state.submitted ? `Auto inserted/submitted ${timingSummary(state)}.` : `Auto inserted ${timingSummary(state)}.`) : insertFailureSummary(modes.insertStrategy || 'auto', state);
}
function scan() {
  pruneMountedControls();
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: [document.body]};
  state.nodes.forEach((node) => { const host = controlsHost(node); if (!hostHasToolbar(host)) parseArenaBlocks(typeof arenaDetectionText === 'function' ? arenaDetectionText(node, state.adapter) : (node.textContent || '')).forEach((entry) => mountControls(host, entry.payload, state.adapter)); });
}

function scanPageDiagnostics() {
  const state = typeof arenaCandidateNodes === 'function' ? arenaCandidateNodes() : {adapter: {name: 'generic'}, nodes: [document.body]};
  const samples = [];
  let parsedBlocks = 0;
  const tools = new Set();
  const semanticFingerprints = new Set();
  state.nodes.forEach((node, index) => {
    const text = typeof arenaDetectionText === 'function' ? arenaDetectionText(node, state.adapter) : (node.textContent || '');
    const entries = parseArenaBlocks(text);
    parsedBlocks += entries.length;
    entries.forEach((entry) => {
      (entry.payload?.calls || []).forEach((call) => tools.add(call.tool));
      const semanticFingerprint = typeof arenaPayloadSemanticFingerprint === 'function' ? arenaPayloadSemanticFingerprint(entry.payload, state.adapter) : hash(JSON.stringify(entry.payload || {}));
      semanticFingerprints.add(semanticFingerprint);
    });
    if (samples.length < 5) samples.push({index, tag: node.tagName || '', text: String(text).slice(0, 240), parsed: entries.length, tools: entries.flatMap((entry) => (entry.payload?.calls || []).map((call) => call.tool))});
  });
  const selectorHits = typeof arenaSelectorDiagnostics === 'function' ? arenaSelectorDiagnostics() : [];
  const composer = typeof arenaComposerDiagnostics === 'function' ? arenaComposerDiagnostics(state.adapter) : null;
  const semanticDuplicateBlocks = Math.max(0, parsedBlocks - semanticFingerprints.size);
  const diagnosticSummary = [semanticFingerprints.size ? `${semanticFingerprints.size} unique block(s)` : '', semanticDuplicateBlocks ? `+${semanticDuplicateBlocks} duplicate(s)` : '', composer?.submit_phase ? `submit ${composer.submit_phase}` : ''].filter(Boolean).join(' · ');
  return {ok: true, url: location.href, host: location.hostname, adapter: state.adapter?.name || 'generic', content_version: ARENA_CONTENT_SCRIPT_VERSION, manifest_version: arenaExtensionVersion(), insert_script_version: (typeof arenaInsertScriptVersion === 'function' ? arenaInsertScriptVersion() : 'unknown'), composer, candidate_nodes: state.nodes.length, parsed_blocks: parsedBlocks, semantic_unique_blocks: semanticFingerprints.size, semantic_duplicate_blocks: semanticDuplicateBlocks, diagnostic_summary: diagnosticSummary, mounted_controls: document.querySelectorAll('[data-arena-tool-controls="1"]').length, dismissed_controls: dismissedControls.size, tools: [...tools], selector_hits: selectorHits, samples};
}
let _lastScanAt = 0;
const SCAN_THROTTLE_MS = 400;
function scheduleScan() {
  if (scanTimer) return;
  const elapsed = Date.now() - _lastScanAt;
  const delay = elapsed < SCAN_THROTTLE_MS ? (SCAN_THROTTLE_MS - elapsed) : 0;
  const run = () => { scanTimer = null; _lastScanAt = Date.now(); scan(); };
  scanTimer = setTimeout(() => { typeof requestIdleCallback === 'function' ? requestIdleCallback(run, {timeout: 600}) : run(); }, delay || 300);
}
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === 'arena.clearPageControls') { suppressCurrentControls(); cleanupStaleControls(); sendResponse?.({ok: true, dismissed: dismissedControls.size}); return true; }
  if (message?.type === 'arena.showPageControls') { dismissedControls.clear(); cleanupStaleControls(); setTimeout(scan, 0); sendResponse?.({ok: true}); return true; }
  if (message?.type === 'arena.controlsModeChanged') { setTimeout(scan, 0); sendResponse?.({ok: true}); return true; }
  if (message?.type === 'arena.scanPage') { sendResponse?.(scanPageDiagnostics()); return true; }
  return false;
});
cleanupStaleControls();
const obs = new MutationObserver((mutations) => {
  const relevant = mutations.some((m) => !m.target?.closest?.('[data-arena-tool-controls]') && (m.addedNodes?.length || m.removedNodes?.length));
  if (relevant) scheduleScan();
});
obs.observe(document.documentElement, {childList: true, subtree: true});
scan();
