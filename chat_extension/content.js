const ARENA_CONTENT_SCRIPT_VERSION = '0.14.1';

const processed = new Set();
const mountedControls = new Map();
const mountedPayloadSemantics = new Set();
const mountedSemanticOwners = new Map();
const executionResults = new Map();
const dismissedControls = new Set();
const detectedPayloads = new Set();
let scanTimer = null;

// ---------------------------------------------------------------------------
// Config cache (5s TTL). Avoids a chrome.runtime IPC round-trip on every
// Insert/Send click. Invalidated when either storage area changes.
// ---------------------------------------------------------------------------
let _contentConfigCache = null;
let _contentConfigCacheAt = 0;

async function getCachedConfig() {
  const now = Date.now();
  if (_contentConfigCache && (now - _contentConfigCacheAt) < 5000) {
    return _contentConfigCache;
  }
  try {
    _contentConfigCache = await chrome.runtime.sendMessage({type: 'arena.getConfig'});
    _contentConfigCacheAt = now;
  } catch (_e) { /* keep last known cache */ }
  return _contentConfigCache || {};
}

try {
  chrome.storage.onChanged.addListener((_c, area) => {
    if (area === 'sync' || area === 'local') _contentConfigCache = null;
  });
} catch (_e) { /* storage may not be available in some contexts */ }

// ---------------------------------------------------------------------------
// Version helpers
// ---------------------------------------------------------------------------
function arenaExtensionVersion() {
  try {
    return chrome.runtime.getManifest?.().version || ARENA_CONTENT_SCRIPT_VERSION;
  } catch (_e) {
    return ARENA_CONTENT_SCRIPT_VERSION;
  }
}

function versionSummary() {
  return `ext ${arenaExtensionVersion()}/content ${ARENA_CONTENT_SCRIPT_VERSION}`;
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------
function hash(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) {
    h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  }
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
  return result.calls.map((call) => {
    if (call?.result?.parsed) return JSON.stringify(call.result.parsed, null, 2);
    if (call?.result?.text) return String(call.result.text);
    return JSON.stringify(call, null, 2);
  }).join('\n\n');
}

function makeButton(label, onClick, primary = false) {
  // v4.48.0: delegates to arenaShadowToolbarButton (shadow_toolbar.js)
  // when available; the fallback keeps the extension usable if the
  // loader order was broken by a local mod.
  if (typeof arenaShadowToolbarButton === 'function') {
    return arenaShadowToolbarButton(label, onClick, { primary });
  }
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.className = 'arena-btn' + (primary ? ' arena-btn--primary' : '');
  btn.addEventListener('pointerdown', (event) => event.preventDefault());
  btn.addEventListener('mousedown', (event) => event.preventDefault());
  btn.addEventListener('click', onClick);
  return btn;
}

function resultErrorText(result) {
  if (!result) return 'empty response';
  if (result.error) return String(result.error);
  const failed = Array.isArray(result.calls)
    ? result.calls.find((call) => call && call.ok === false)
    : null;
  const parsed = failed?.result?.parsed;
  return parsed?.error
    || parsed?.message
    || (failed?.result?.text ? String(failed.result.text).slice(0, 220) : '')
    || result.summary
    || (result.status ? `HTTP ${result.status}` : 'unknown');
}

function controlsHost(node) {
  if (!node) return document.body;
  if (node.tagName === 'CODE') return node.closest('pre') || node;
  return node;
}

function attachControls(host, bar) {
  const tag = String(host?.tagName || '').toUpperCase();
  const width = Math.max(280, Math.min(host.getBoundingClientRect?.().width || 680, 900));
  bar.style.width = `${width}px`;
  if ((tag === 'PRE' || tag === 'CODE') && host.parentNode) {
    host.insertAdjacentElement('afterend', bar);
  } else {
    host.appendChild(bar);
  }
}

function cleanupStaleControls() {
  document.querySelectorAll('[data-arena-tool-controls="1"]').forEach((bar) => bar.remove());
  document.querySelectorAll('[data-arena-tool-controls-mounted="1"]').forEach((node) => {
    node.dataset.arenaToolControlsMounted = '';
  });
  mountedControls.clear();
  mountedPayloadSemantics.clear();
  mountedSemanticOwners.clear();
  executionResults.clear();
  detectedPayloads.clear();
}

function pruneMountedControls() {
  for (const [fingerprint, info] of [...mountedControls.entries()]) {
    if (info?.bar?.isConnected && info?.host?.isConnected) continue;
    if (info?.host?.dataset) info.host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(fingerprint);
    if (info?.semanticFingerprint) {
      mountedPayloadSemantics.delete(info.semanticFingerprint);
      mountedSemanticOwners.delete(info.semanticFingerprint);
    }
  }
}

function suppressCurrentControls() {
  const state = typeof arenaCandidateNodes === 'function'
    ? arenaCandidateNodes()
    : {adapter: {name: 'generic'}, nodes: []};
  state.nodes.forEach((node) => {
    const text = typeof arenaDetectionText === 'function'
      ? arenaDetectionText(node, state.adapter)
      : (node.textContent || '');
    parseArenaBlocks(text).forEach((entry) => {
      const host = controlsHost(node);
      const messageFp = typeof arenaMessageFingerprint === 'function'
        ? arenaMessageFingerprint(host, entry.payload, state.adapter)
        : hash((host.textContent || '') + JSON.stringify(entry.payload));
      const semanticFp = typeof arenaPayloadSemanticFingerprint === 'function'
        ? arenaPayloadSemanticFingerprint(entry.payload, state.adapter)
        : hash(JSON.stringify(entry.payload || {}));
      dismissedControls.add(messageFp);
      dismissedControls.add(semanticFp);
    });
  });
}

function hostHasToolbar(host) {
  if (host?.dataset?.arenaToolControlsMounted !== '1') return false;
  return !!(
    host.nextElementSibling?.dataset?.arenaToolControls === '1'
    || host.querySelector?.('[data-arena-tool-controls="1"]')
  );
}

function buildRequest(payload, adapterName, fingerprint) {
  return {
    site: {origin: location.origin, url: location.href, adapter: adapterName},
    message: {fingerprint},
    payload,
    mode: {},
  };
}

function payloadTools(payload) {
  return (payload?.calls || []).map((call) => call.tool).filter(Boolean);
}

function detectedDetail(payload, _adapter) {
  const tools = payloadTools(payload).slice(0, 4).join(', ') || 'tool block';
  return `detected ${tools} on ${location.hostname}`;
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
  if (active && active.isContentEditable) {
    if (typeof arenaInsertIntoEditable === 'function') {
      return arenaInsertIntoEditable(active, text, strategy);
    }
    document.execCommand('insertText', false, text);
    return true;
  }
  return false;
}

function attemptsSummary(timing) {
  const attempts = Array.isArray(timing?.attempts) ? timing.attempts : [];
  if (!attempts.length) return '';
  const parts = attempts.map((item) => {
    const status = item.settled ? 'ok' : (item.changed ? 'changed' : 'no-change');
    return `${item.strategy}:${status}`;
  });
  return ` Attempts: ${parts.join(', ')}.`;
}

function timingSummary(timing) {
  const strategy = timing?.strategy || timing?.method || 'unknown';
  const requested = timing?.requested_strategy;
  const prefix = (requested === 'auto' && strategy !== 'auto')
    ? `Auto used ${strategy}`
    : `via ${strategy}`;
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
  return `Dry run: ${calls.length} call(s)${tools ? ` · ${tools}` : ''}`
    + ` · approval=${!!result?.policy?.requires_approval}`;
}

// ---------------------------------------------------------------------------
// mountControls: attaches the toolbar (Preview/Run/Insert/Send/Copy/Panel/×)
// to a detected message block. Handles fingerprint bookkeeping so we do not
// remount the same toolbar across DOM churn.
// ---------------------------------------------------------------------------
function mountControls(host, payload, adapter) {
  host = controlsHost(host);

  const fingerprint = typeof arenaMessageFingerprint === 'function'
    ? arenaMessageFingerprint(host, payload, adapter)
    : hash((host.textContent || '') + JSON.stringify(payload));
  const payloadFingerprint = typeof arenaPayloadFingerprint === 'function'
    ? arenaPayloadFingerprint(payload, adapter)
    : hash(JSON.stringify(payload || {}));
  const semanticFingerprint = typeof arenaPayloadSemanticFingerprint === 'function'
    ? arenaPayloadSemanticFingerprint(payload, adapter)
    : payloadFingerprint;

  // If the same semantic payload was previously mounted on another host, evict it.
  const semanticOwner = mountedSemanticOwners.get(semanticFingerprint);
  if (semanticOwner && semanticOwner !== fingerprint) {
    const previous = mountedControls.get(semanticOwner);
    // v4.48.0: remove shadowHost (v4.48+) or bar (older mount).
    if (previous?.shadowHost) previous.shadowHost.remove();
    else previous?.bar?.remove();
    if (previous?.host?.dataset) previous.host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(semanticOwner);
    mountedPayloadSemantics.delete(semanticFingerprint);
    mountedSemanticOwners.delete(semanticFingerprint);
  }

  const existing = mountedControls.get(fingerprint);
  if (
    dismissedControls.has(fingerprint)
    || dismissedControls.has(semanticFingerprint)
    || mountedPayloadSemantics.has(semanticFingerprint)
    || existing?.bar?.isConnected
    || hostHasToolbar(host)
  ) return;

  const firstSeen = !processed.has(fingerprint);
  const firstPayloadSeen = !detectedPayloads.has(semanticFingerprint);
  processed.add(fingerprint);
  detectedPayloads.add(semanticFingerprint);
  mountedPayloadSemantics.add(semanticFingerprint);
  host.dataset.arenaToolControlsMounted = '1';
  host.dataset.arenaToolFingerprint = fingerprint;

  const request = buildRequest(payload, adapter.name, fingerprint);

  if (firstSeen && firstPayloadSeen) {
    chrome.runtime.sendMessage({
      type: 'arena.detected',
      body: {
        detail: detectedDetail(payload, adapter),
        site: location.origin,
        adapter: adapter.name,
        fingerprint,
        payload_fingerprint: semanticFingerprint,
        payload_instance_fingerprint: payloadFingerprint,
        tools: payloadTools(payload),
        payload: request,
      },
    });
  }

  let lastExecutionText = executionResults.get(semanticFingerprint) || '';

  // v4.48.0: mount toolbar in a Shadow DOM host so page CSS cannot
  // restyle it. shadowHost is positioned by attachControls(); bar
  // is the inner .arena-toolbar node inside the shadow root. The
  // fallback keeps a working toolbar when shadow_toolbar.js is
  // absent (mod / cached bundle / unit-test scope stub).
  let shadowHost = null;
  let bar;
  if (typeof arenaCreateShadowToolbar === 'function') {
    const parts = arenaCreateShadowToolbar(host);
    shadowHost = parts.shadowHost;
    bar = parts.toolbar;
  } else {
    bar = document.createElement('div');
    bar.dataset.arenaToolControls = '1';
    bar.className = 'arena-toolbar';
  }

  const status = document.createElement('span');
  status.className = 'arena-toolbar-status';
  status.textContent = lastExecutionText
    ? `Arena · ${adapter.name} · result ready`
    : `Arena · ${adapter.name}`;
  bar.appendChild(status);

  bar.appendChild(makeButton('Preview', async () => {
    status.textContent = 'Previewing...';
    const result = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
    status.textContent = result?.ok
      ? previewSummary(result)
      : `Preview error: ${resultErrorText(result)}`;
  }));

  bar.appendChild(makeButton('Run', async () => {
    status.textContent = 'Running...';
    const runStarted = performance.now();
    const result = await chrome.runtime.sendMessage({
      type: 'arena.execute',
      body: {...request, mode: {approve: true}},
    });
    const runMs = Math.round(performance.now() - runStarted);
    const bridgeMs = result?.bridge_ms || 0;
    if (Array.isArray(result?.calls)) {
      lastExecutionText = resultToText(result);
      if (lastExecutionText) executionResults.set(semanticFingerprint, lastExecutionText);
    }
    const timing = result?.ok
      ? (bridgeMs > 0 ? ` in ${runMs}ms (bridge ${bridgeMs}ms)` : ` in ${runMs}ms`)
      : '';
    status.textContent = result?.ok
      ? `Executed ${result.calls?.length || 0} call(s)${timing}`
      : `Run error: ${resultErrorText(result)}`;
  }, true));

  bar.appendChild(makeButton('Insert', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const insertText = formatInsertText(lastExecutionText);
    const strategy = await currentInsertStrategy();
    let ok = false;
    if (typeof arenaInsertResult === 'function') {
      ok = await arenaInsertResult(insertText, adapter, strategy);
    } else {
      ok = genericInsertIntoActiveField(insertText, strategy);
    }
    const timing = {ok, ...(window.__arenaLastInsertTiming || {})};
    await arenaRecordInsertEvent('insert', request, adapter, timing, 'manual');
    status.textContent = ok
      ? `Inserted ${timingSummary(timing)}.`
      : insertFailureSummary(strategy, timing);
  }));

  bar.appendChild(makeButton('Send', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const strategy = await currentInsertStrategy();
    const state = typeof arenaInsertAndSubmit === 'function'
      ? await arenaInsertAndSubmit(formatInsertText(lastExecutionText), adapter, strategy)
      : {ok: false, inserted: false, submitted: false};
    await arenaRecordInsertEvent(
      state.submitted ? 'submit' : 'insert', request, adapter, state, 'manual',
    );
    if (state.ok) {
      status.textContent = state.submitted
        ? `Inserted/submitted ${timingSummary(state)}.`
        : `Inserted ${timingSummary(state)}, submit not found.`;
    } else {
      status.textContent = `Insert & submit failed. ${insertFailureSummary(strategy, state)}`;
    }
  }));

  bar.appendChild(makeButton('Copy', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    try {
      await navigator.clipboard.writeText(lastExecutionText);
      status.textContent = 'Result copied.';
    } catch (e) {
      status.textContent = `Copy failed: ${e}`;
    }
  }));

  bar.appendChild(makeButton('Panel', async () => {
    const result = await chrome.runtime.sendMessage({type: 'arena.openSidePanel'});
    status.textContent = result?.ok
      ? 'Opened side panel.'
      : `Panel error: ${result?.error || 'unknown'}`;
  }));

  bar.appendChild(makeButton('×', () => {
    dismissedControls.add(fingerprint);
    dismissedControls.add(semanticFingerprint);
    // v4.48.0: remove the shadow host (owner) rather than the inner
    // .arena-toolbar node; fallback path removes bar directly.
    if (shadowHost) {
      if (typeof arenaDestroyShadowToolbar === 'function') arenaDestroyShadowToolbar(shadowHost);
      else shadowHost.remove();
    } else {
      bar.remove();
    }
    host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(fingerprint);
    mountedPayloadSemantics.delete(semanticFingerprint);
    mountedSemanticOwners.delete(semanticFingerprint);
  }));

  // v4.48.0: position the shadow host (or bar on fallback).
  attachControls(host, shadowHost || bar);
  // Track shadowHost too so semantic-eviction can call .remove() on
  // the correct node; `bar` is kept for back-compat.
  mountedControls.set(fingerprint, {host, bar, shadowHost, semanticFingerprint});
  mountedSemanticOwners.set(semanticFingerprint, fingerprint);

  runAutoModes(request, adapter, status, semanticFingerprint, (text) => {
    lastExecutionText = text;
  });
}

// ---------------------------------------------------------------------------
// Auto-preview / auto-execute / auto-insert / auto-submit modes.
// ---------------------------------------------------------------------------
async function runAutoModes(request, adapter, status, semanticFingerprint, setResultText) {
  const cfg = await getCachedConfig();
  const modes = typeof arenaNormalizeModes === 'function'
    ? arenaNormalizeModes(cfg?.modes)
    : (cfg?.modes || {});
  if (!modes.autoPreview && !modes.autoExecuteSafe) return;

  status.textContent = modes.autoExecuteSafe
    ? 'Auto previewing before safe execution...'
    : 'Auto previewing...';
  const preview = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
  if (!preview?.ok) {
    status.textContent = `Auto preview error: ${resultErrorText(preview)}`;
    return;
  }
  if (!modes.autoExecuteSafe || !preview.policy?.can_auto_run) {
    status.textContent = `Preview ready: approval=${!!preview.policy?.requires_approval}`;
    return;
  }

  status.textContent = 'Auto executing safe call(s)...';
  const result = await chrome.runtime.sendMessage({
    type: 'arena.execute',
    body: {...request, mode: {}},
  });
  if (!result?.ok) {
    status.textContent = `Auto run error: ${resultErrorText(result)}`;
    return;
  }
  const text = resultToText(result);
  if (text) executionResults.set(semanticFingerprint, text);
  setResultText(text);
  status.textContent = `Auto executed ${result.calls?.length || 0} call(s)`;

  if (!modes.autoInsertResult || !text) return;
  const insertText = formatInsertText(text);
  const strategy = modes.insertStrategy || 'auto';

  let state;
  if (modes.autoSubmitResult && typeof arenaInsertAndSubmit === 'function') {
    state = await arenaInsertAndSubmit(insertText, adapter, strategy);
  } else if (typeof arenaInsertResult === 'function') {
    const ok = await arenaInsertResult(insertText, adapter, strategy);
    state = {ok, ...(window.__arenaLastInsertTiming || {})};
  } else {
    state = {ok: genericInsertIntoActiveField(insertText, strategy)};
  }

  await arenaRecordInsertEvent(
    state.submitted ? 'submit' : 'insert', request, adapter, state, 'auto',
  );
  if (state.ok) {
    status.textContent = state.submitted
      ? `Auto inserted/submitted ${timingSummary(state)}.`
      : `Auto inserted ${timingSummary(state)}.`;
  } else {
    status.textContent = insertFailureSummary(strategy, state);
  }
}

// ---------------------------------------------------------------------------
// Scan pipeline: MutationObserver → scheduleScan (throttled) → scan()
// ---------------------------------------------------------------------------
let _lastCandidateCount = -1;

function scan() {
  pruneMountedControls();
  const state = typeof arenaCandidateNodes === 'function'
    ? arenaCandidateNodes()
    : {adapter: {name: 'generic'}, nodes: [document.body]};

  // Fast path: same candidate count AND all already have toolbars → skip parse.
  const allMounted = state.nodes.every((node) => hostHasToolbar(controlsHost(node)));
  if (state.nodes.length === _lastCandidateCount && allMounted) return;
  _lastCandidateCount = state.nodes.length;

  state.nodes.forEach((node) => {
    const host = controlsHost(node);
    if (hostHasToolbar(host)) return;
    const text = typeof arenaDetectionText === 'function'
      ? arenaDetectionText(node, state.adapter)
      : (node.textContent || '');
    parseArenaBlocks(text).forEach((entry) => mountControls(host, entry.payload, state.adapter));
  });
}

function scanPageDiagnostics() {
  const state = typeof arenaCandidateNodes === 'function'
    ? arenaCandidateNodes()
    : {adapter: {name: 'generic'}, nodes: [document.body]};
  const samples = [];
  let parsedBlocks = 0;
  const tools = new Set();
  const semanticFingerprints = new Set();

  state.nodes.forEach((node, index) => {
    const text = typeof arenaDetectionText === 'function'
      ? arenaDetectionText(node, state.adapter)
      : (node.textContent || '');
    const entries = parseArenaBlocks(text);
    parsedBlocks += entries.length;
    entries.forEach((entry) => {
      (entry.payload?.calls || []).forEach((call) => tools.add(call.tool));
      const semanticFp = typeof arenaPayloadSemanticFingerprint === 'function'
        ? arenaPayloadSemanticFingerprint(entry.payload, state.adapter)
        : hash(JSON.stringify(entry.payload || {}));
      semanticFingerprints.add(semanticFp);
    });
    if (samples.length < 5) {
      samples.push({
        index,
        tag: node.tagName || '',
        text: String(text).slice(0, 240),
        parsed: entries.length,
        tools: entries.flatMap((entry) => (entry.payload?.calls || []).map((call) => call.tool)),
      });
    }
  });

  const selectorHits = typeof arenaSelectorDiagnostics === 'function'
    ? arenaSelectorDiagnostics()
    : [];
  const composer = typeof arenaComposerDiagnostics === 'function'
    ? arenaComposerDiagnostics(state.adapter)
    : null;
  const semanticDuplicateBlocks = Math.max(0, parsedBlocks - semanticFingerprints.size);
  const diagnosticSummary = [
    semanticFingerprints.size ? `${semanticFingerprints.size} unique block(s)` : '',
    semanticDuplicateBlocks ? `+${semanticDuplicateBlocks} duplicate(s)` : '',
    composer?.submit_phase ? `submit ${composer.submit_phase}` : '',
  ].filter(Boolean).join(' · ');

  return {
    ok: true,
    url: location.href,
    host: location.hostname,
    adapter: state.adapter?.name || 'generic',
    content_version: ARENA_CONTENT_SCRIPT_VERSION,
    manifest_version: arenaExtensionVersion(),
    insert_script_version: typeof arenaInsertScriptVersion === 'function'
      ? arenaInsertScriptVersion() : 'unknown',
    composer,
    candidate_nodes: state.nodes.length,
    parsed_blocks: parsedBlocks,
    semantic_unique_blocks: semanticFingerprints.size,
    semantic_duplicate_blocks: semanticDuplicateBlocks,
    diagnostic_summary: diagnosticSummary,
    mounted_controls: document.querySelectorAll('[data-arena-tool-controls="1"]').length,
    dismissed_controls: dismissedControls.size,
    tools: [...tools],
    selector_hits: selectorHits,
    samples,
  };
}

// scheduleScan: throttle-based coalescing. Combines with the idle callback so
// heavy DOM churn on SPAs (ChatGPT/Claude/Gemini) does not pile up work.
let _lastScanAt = 0;
const SCAN_THROTTLE_MS = 400;

function scheduleScan() {
  if (scanTimer) return;
  const elapsed = Date.now() - _lastScanAt;
  const delay = elapsed < SCAN_THROTTLE_MS ? (SCAN_THROTTLE_MS - elapsed) : 0;
  const run = () => {
    scanTimer = null;
    _lastScanAt = Date.now();
    scan();
  };
  scanTimer = setTimeout(() => {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(run, {timeout: 600});
    } else {
      run();
    }
  }, delay || 300);
}

// ---------------------------------------------------------------------------
// Message router + boot
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === 'arena.clearPageControls') {
    suppressCurrentControls();
    cleanupStaleControls();
    sendResponse?.({ok: true, dismissed: dismissedControls.size});
    return true;
  }
  if (message?.type === 'arena.showPageControls') {
    dismissedControls.clear();
    cleanupStaleControls();
    setTimeout(scan, 0);
    sendResponse?.({ok: true});
    return true;
  }
  if (message?.type === 'arena.controlsModeChanged') {
    setTimeout(scan, 0);
    sendResponse?.({ok: true});
    return true;
  }
  if (message?.type === 'arena.scanPage') {
    sendResponse?.(scanPageDiagnostics());
    return true;
  }
  return false;
});

cleanupStaleControls();

const obs = new MutationObserver((mutations) => {
  // Ignore mutations that originate inside our own toolbars — they should not
  // trigger a rescan of the page.
  const relevant = mutations.some((m) => {
    if (m.target?.closest?.('[data-arena-tool-controls]')) return false;
    return m.addedNodes?.length || m.removedNodes?.length;
  });
  if (!relevant) return;
  if (typeof arenaInvalidateCandidateCache === 'function') {
    arenaInvalidateCandidateCache();
  }
  scheduleScan();
});
obs.observe(document.documentElement, {childList: true, subtree: true});

scan();
