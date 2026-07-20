// v0.14.34 (v4.52.0): sidepanel redesign with tabs.
// Studied MCP SuperAssistant sidebar
// (github.com/srbhptl39/MCP-SuperAssistant/pages/content/src/
// components/sidebar/) and adapted its 3-panel layout:
//   * Status (bridge health + policies)
//   * Tools  (searchable tool catalog with per-tool details)
//   * Instructions (Copy Instructions with live preview + category
//                   / format selector)
//   * History (unchanged from the v4.51.x sidepanel)
//
// This is a plain-JS port -- MCP SuperAssistant is React/Zustand;
// Arena extension has never carried a React runtime and Ivan
// prefers minimal deps.
async function send(type, body) {
  return chrome.runtime.sendMessage({type, body});
}

// ------------------------------------------------------------
// Utilities (shared between History + Tools tabs)
// ------------------------------------------------------------
function shortUrl(url) {
  try { const u = new URL(url); return `${u.hostname}${u.pathname === '/' ? '' : u.pathname}`.slice(0, 90); } catch (_e) { return String(url || '').slice(0, 90); }
}
function itemTools(item) {
  const calls = item.payload?.payload?.calls || item.payload?.calls || item.response?.calls || [];
  const tools = calls.map((call) => call.tool || call.name).filter(Boolean);
  if (Array.isArray(item.tools)) tools.push(...item.tools);
  return [...new Set(tools)].slice(0, 4);
}
function itemStatus(item) {
  if (item.ok === false) return 'error';
  if (item.kind === 'execute') return 'executed';
  if (item.kind === 'preview') return 'previewed';
  if (item.kind === 'scan') return item.response?.ok === false ? 'scan error' : 'scanned';
  if (item.kind === 'insert') return item.ok === false ? 'insert error' : 'inserted';
  if (item.kind === 'submit') return item.ok === false ? 'submit error' : 'submitted';
  return item.kind || 'event';
}
function scanDiagnostics(item) {
  if (item.kind !== 'scan' || !item.response) return [];
  const res = item.response || {};
  const parts = [];
  if (Number.isFinite(res.candidate_nodes)) parts.push(`${res.candidate_nodes} candidates`);
  if (Number.isFinite(res.parsed_blocks)) parts.push(`${res.parsed_blocks} blocks`);
  if (Number.isFinite(res.semantic_unique_blocks)) parts.push(`${res.semantic_unique_blocks} unique`);
  if (Number.isFinite(res.semantic_duplicate_blocks) && res.semantic_duplicate_blocks > 0) parts.push(`${res.semantic_duplicate_blocks} duplicates`);
  if (Number.isFinite(res.mounted_controls)) parts.push(`${res.mounted_controls} controls`);
  if (res.diagnostic_summary) parts.push(res.diagnostic_summary);
  const composer = res.composer || {};
  if (composer.found) {
    const editor = composer.rich_textarea ? 'rich-textarea' : (composer.prose_mirror ? 'ProseMirror' : (composer.contenteditable ? 'contenteditable' : composer.tag));
    if (editor) parts.push(`composer: ${editor}`);
    if (Array.isArray(composer.auto_plan) && composer.auto_plan.length) parts.push(`auto: ${composer.auto_plan.join(' → ')}`);
    if (composer.submit_phase) parts.push(`submit: ${composer.submit_phase}`);
    if (composer.submit_expected_after_text) parts.push('submit after text');
  } else if (composer && composer.found === false) {
    parts.push('composer: not found');
  }
  return parts;
}
function bridgeDiagnostics(item) {
  const res = item.response || {};
  return [res.bridge_url ? `bridge: ${shortUrl(res.bridge_url)}` : '', res.bridge_url_fallback ? 'bridge fallback' : ''].filter(Boolean);
}
function versionDiagnostics(item) {
  const res = item.response || {};
  return [
    res.manifest_version ? `manifest ${res.manifest_version}` : '',
    res.content_version ? `content ${res.content_version}` : '',
    res.insert_script_version ? `insert ${res.insert_script_version}` : '',
  ].filter(Boolean);
}
function insertionDiagnostics(item) {
  if (item.kind !== 'insert' && item.kind !== 'submit') return [];
  const res = item.response || {};
  return [
    res.strategy ? `strategy: ${res.strategy}` : '',
    Number.isFinite(res.total_ms) ? `${res.total_ms}ms` : '',
    Number.isFinite(res.verify_ms) ? `verify +${res.verify_ms}ms` : '',
    res.submitted ? 'submitted' : '',
  ].filter(Boolean);
}
function fingerprintDiagnostics(item) {
  const fp = item.payload_fingerprint || item.fingerprint;
  return fp ? [`fp ${String(fp).slice(0, 18)}`] : [];
}
function cardMetaParts(item) {
  const tools = itemTools(item).join(', ');
  return [
    item.adapter || '',
    shortUrl(item.site),
    tools ? `tools: ${tools}` : '',
    ...scanDiagnostics(item),
    ...insertionDiagnostics(item),
    ...bridgeDiagnostics(item),
    ...versionDiagnostics(item),
    ...fingerprintDiagnostics(item),
  ].filter(Boolean);
}
function commandKey(item) {
  if (!item || item.kind === 'scan') return '';
  const payloadCalls = item.payload?.payload?.calls || item.payload?.calls || [];
  const payloadSig = payloadCalls.length ? JSON.stringify(payloadCalls.map((call) => ({tool: call.tool || call.name || '', id: call.id || call.call_id || ''}))) : '';
  return item.fingerprint || item.payload_fingerprint || payloadSig || '';
}
function lifecycleLabel(kind) {
  if (kind === 'detected') return 'detected';
  if (kind === 'preview') return 'previewed';
  if (kind === 'execute') return 'executed';
  if (kind === 'insert') return 'inserted';
  if (kind === 'submit') return 'submitted';
  return kind || 'event';
}
function lifecycleKinds(events) {
  const order = ['detected', 'preview', 'execute', 'insert', 'submit'];
  const kinds = new Set((events || []).map((event) => event.kind).filter(Boolean));
  return order.filter((kind) => kinds.has(kind));
}
function lifecycleSummary(events) {
  // v4.51.x helper: joined arrow-flow label. Kept in v4.52.0
  // for tests/test_chat_extension_sidepanel_flow.py — the group
  // renderer inlines the same join but external consumers of
  // the helper (older tests, future sidepanel plugins) still
  // depend on the name.
  return lifecycleKinds(events).map((kind) => lifecycleLabel(kind)).join(' → ');
}
function latestEvent(events) {
  return (events || []).reduce((latest, item) => ((Date.parse(item.at || 0) || 0) >= (Date.parse(latest?.at || 0) || 0) ? item : latest), null);
}
function commandGroupFromEvents(key, events) {
  const kinds = lifecycleKinds(events);
  if (kinds.length < 2) return null;
  const latest = latestEvent(events) || events[0];
  const lifecycle = kinds.map((kind) => lifecycleLabel(kind)).join(' → ');
  return {...latest, group_key: key, events, lifecycle, event_count: events.length};
}
function groupCommandHistory(items) {
  const groups = new Map();
  const positions = new Map();
  const passthrough = [];
  (items || []).forEach((item, index) => {
    const key = commandKey(item);
    if (!key) { passthrough.push({index, item}); return; }
    if (!groups.has(key)) { groups.set(key, []); positions.set(key, index); }
    groups.get(key).push(item);
  });
  groups.forEach((events, key) => {
    const group = commandGroupFromEvents(key, events);
    if (group) passthrough.push({index: positions.get(key), item: group});
    else events.forEach((item) => passthrough.push({index: item.history_index ?? positions.get(key), item}));
  });
  return passthrough.sort((a, b) => a.index - b.index).map((entry) => entry.item);
}
function historyActionIndex(item, fallbackIndex) {
  return Number.isInteger(item?.history_index) ? item.history_index : fallbackIndex;
}
function groupEvents(item) { return Array.isArray(item?.events) ? item.events : [item].filter(Boolean); }
function latestMatchingEvent(item, predicate) { return latestEvent(groupEvents(item).filter((event) => predicate(event))); }
function payloadSourceItem(item) { return latestMatchingEvent(item, (event) => !!event?.payload) || item; }
function resultSourceItem(item) {
  return latestMatchingEvent(item, (event) => event?.kind === 'execute' && !!event?.response)
    || latestMatchingEvent(item, (event) => !!event?.response)
    || item;
}
function finalResultItem(item) { return latestMatchingEvent(item, (event) => !!event?.response) || item; }
function replaySourceItem(item) { return latestMatchingEvent(item, (event) => !!event?.payload && ['detected', 'preview', 'execute'].includes(event.kind)); }

function badge(text, tone = 'neutral') {
  const span = document.createElement('span');
  span.className = `arena-badge arena-badge-${tone}`;
  span.textContent = text;
  return span;
}

// ------------------------------------------------------------
// Tab switching
// ------------------------------------------------------------
const TAB_LOAD_HOOKS = {};      // name -> async fn, called on first activation
const TAB_LOADED = new Set();

function activateTab(name) {
  document.querySelectorAll('.arena-tab').forEach((el) => {
    el.classList.toggle('arena-tab-active', el.dataset.tab === name);
  });
  document.querySelectorAll('.arena-tab-panel').forEach((el) => {
    el.classList.toggle('arena-tab-panel-active', el.id === `tab-${name}`);
  });
  if (!TAB_LOADED.has(name) && typeof TAB_LOAD_HOOKS[name] === 'function') {
    TAB_LOADED.add(name);
    Promise.resolve(TAB_LOAD_HOOKS[name]()).catch((err) => {
      // Deliberately do not swallow silently -- surface in the
      // corresponding panel so the user can retry.
      console.warn(`[arena sidepanel] tab '${name}' loader threw:`, err);
    });
  }
}

// ------------------------------------------------------------
// Status tab
// ------------------------------------------------------------
function renderStatus(data) {
  const box = document.getElementById('statusBox');
  const version = data?.version?.version || data?.version || '';
  const policies = data?.policies?.ok ? 'policies ok' : (data?.policies ? 'policies error' : '');
  const status = data?.ok === false ? 'error' : 'ok';
  box.textContent = data?.loading || `Bridge ${status}${version ? ' · v' + version : ''}${policies ? ' · ' + policies : ''}`;
  box.dataset.raw = JSON.stringify(data, null, 2);
  // Update header connectivity badge.
  const badgeEl = document.getElementById('arena-conn-badge');
  if (badgeEl && !data?.loading) {
    badgeEl.textContent = data?.ok === false ? 'offline' : (version ? `v${version}` : 'ok');
    badgeEl.className = 'arena-badge ' + (data?.ok === false ? 'arena-badge-error' : 'arena-badge-ok');
    badgeEl.title = data?.ok === false ? (data?.error || 'bridge unreachable') : `bridge ok · v${version}`;
  }
}
async function testConnection() {
  renderStatus({loading: 'Testing bridge...'});
  renderStatus(await send('arena.testConnection'));
}
async function loadPolicies() {
  renderStatus({loading: 'Loading policies...'});
  const result = await send('arena.policies');
  renderStatus(result);
  renderResult({response: result});
}

// ------------------------------------------------------------
// Tools tab
// ------------------------------------------------------------
let TOOLS_CACHE = {category: null, catalog: [], loadedAt: 0};

async function loadTools(force = false) {
  const cat = document.getElementById('toolsCategory').value || 'safe';
  const summary = document.getElementById('toolsSummary');
  const list = document.getElementById('toolsList');
  if (!force && TOOLS_CACHE.category === cat && TOOLS_CACHE.catalog.length) {
    renderToolsList(TOOLS_CACHE.catalog);
    return;
  }
  summary.textContent = `Loading '${cat}' tools…`;
  list.innerHTML = '';
  try {
    const result = await send('arena.instructions', {format: 'arena', style: 'short', category: cat});
    if (result?.ok === false) {
      summary.textContent = `Error loading tools: ${result.error || 'unknown'}`;
      return;
    }
    const catalog = Array.isArray(result?.catalog) ? result.catalog : [];
    TOOLS_CACHE = {category: cat, catalog, loadedAt: Date.now()};
    renderToolsList(catalog);
  } catch (e) {
    summary.textContent = `Failed: ${String(e?.message || e)}`;
  }
}

function renderToolsList(catalog) {
  const list = document.getElementById('toolsList');
  const summary = document.getElementById('toolsSummary');
  const search = (document.getElementById('toolsSearch').value || '').trim().toLowerCase();
  list.innerHTML = '';
  const filtered = catalog.filter((entry) => {
    if (!search) return true;
    const hay = `${entry.name} ${entry.description || ''} ${entry.topic || ''}`.toLowerCase();
    return hay.includes(search);
  });
  summary.textContent = search
    ? `${filtered.length} of ${catalog.length} tool(s) match '${search}'`
    : `${catalog.length} tool(s)`;
  if (!filtered.length) {
    list.innerHTML = `<div style="color:#94a3b8;padding:12px;text-align:center">No tools match your filter.</div>`;
    return;
  }
  filtered.forEach((entry) => list.appendChild(renderToolCard(entry)));
}

function renderToolCard(entry) {
  const details = document.createElement('details');
  details.className = 'arena-tool-card';
  const summary = document.createElement('summary');
  const header = document.createElement('div');
  header.className = 'arena-tool-header';
  const nameEl = document.createElement('span');
  nameEl.className = 'arena-tool-name';
  nameEl.textContent = entry.name;
  header.appendChild(nameEl);
  const risk = String(entry.risk || 'safe');
  header.appendChild(badge(risk, `risk-${risk}`));
  if (entry.topic && entry.topic !== risk) header.appendChild(badge(entry.topic, 'kind'));
  const desc = document.createElement('span');
  desc.className = 'arena-tool-desc';
  desc.textContent = entry.description || '';
  desc.title = entry.description || '';
  header.appendChild(desc);
  summary.appendChild(header);
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'arena-tool-body';
  const dl = document.createElement('dl');
  const addRow = (dt, dd) => {
    const dtEl = document.createElement('dt'); dtEl.textContent = dt;
    const ddEl = document.createElement('dd');
    if (dd instanceof HTMLElement) ddEl.appendChild(dd); else ddEl.textContent = String(dd);
    dl.appendChild(dtEl); dl.appendChild(ddEl);
  };
  addRow('name', entry.name);
  addRow('risk', risk);
  if (entry.topic) addRow('topic', entry.topic);
  if (entry.description) addRow('description', entry.description);
  if (entry.csn) {
    const code = document.createElement('code'); code.textContent = entry.csn;
    addRow('schema (CSN)', code);
  }
  if (entry.input_schema) {
    const pre = document.createElement('pre');
    pre.style.margin = '0';
    pre.style.maxHeight = '160px';
    pre.textContent = JSON.stringify(entry.input_schema, null, 2);
    addRow('JSON Schema', pre);
  }
  if (entry.example_arguments) {
    const pre = document.createElement('pre');
    pre.style.margin = '0';
    pre.textContent = JSON.stringify(entry.example_arguments, null, 2);
    addRow('example args', pre);
  }
  body.appendChild(dl);

  const actions = document.createElement('div');
  actions.className = 'arena-tool-actions';
  actions.appendChild(makeActionButton('Copy call template', async () => {
    const template = {
      bridge: 'arena', version: 1,
      calls: [{id: 'call_1', tool: entry.name, arguments: entry.example_arguments || {}}],
    };
    await navigator.clipboard.writeText(
      '```arena-tool\n' + JSON.stringify(template, null, 2) + '\n```',
    );
  }));
  actions.appendChild(makeActionButton('Copy CSN line', async () => {
    await navigator.clipboard.writeText(`${entry.name} (${risk}) — ${entry.description || ''}\nschema: ${entry.csn || ''}`);
  }));
  body.appendChild(actions);
  details.appendChild(body);
  return details;
}

// ------------------------------------------------------------
// Instructions tab
// ------------------------------------------------------------
let INSTRUCTIONS_CACHE = null;

async function loadInstructions() {
  const cat = document.getElementById('instructionsCategory').value;
  const fmt = document.getElementById('instructionsFormat').value || 'arena';
  const preview = document.getElementById('instructionsPreview');
  const summary = document.getElementById('instructionsSummary');
  preview.textContent = 'Loading…';
  summary.textContent = '';
  try {
    const result = await send('arena.instructions', {format: fmt, style: 'full', category: cat});
    if (result?.ok === false) {
      preview.textContent = `Error: ${result.error || 'unknown'}`;
      return;
    }
    INSTRUCTIONS_CACHE = result;
    preview.textContent = result?.text || '(empty)';
    const bytes = (result?.text || '').length;
    const n = Array.isArray(result?.catalog) ? result.catalog.length : 0;
    summary.textContent = `${bytes.toLocaleString()} chars · ${n} tool(s) · fmt=${fmt}`;
  } catch (e) {
    preview.textContent = `Failed: ${String(e?.message || e)}`;
  }
}
async function copyInstructions() {
  if (!INSTRUCTIONS_CACHE?.text) await loadInstructions();
  if (!INSTRUCTIONS_CACHE?.text) return;
  await navigator.clipboard.writeText(INSTRUCTIONS_CACHE.text);
  const summary = document.getElementById('instructionsSummary');
  const prev = summary.textContent;
  summary.textContent = 'Copied to clipboard ✓';
  setTimeout(() => { summary.textContent = prev; }, 1500);
}

// ------------------------------------------------------------
// History tab (unchanged wiring; extracted verbatim from v4.51.x)
// ------------------------------------------------------------
function renderPayload(item) {
  const box = document.getElementById('payloadBox');
  box.textContent = item?.payload ? JSON.stringify(item.payload, null, 2) : 'Select a history entry to inspect its payload.';
}
function renderResult(item) {
  const box = document.getElementById('resultBox');
  box.textContent = item?.response ? JSON.stringify(item.response, null, 2) : 'Select a history entry to inspect its result.';
}
async function runHistoryAction(index, mode) {
  const result = await send('arena.replayHistory', {index, mode});
  renderStatus(result);
  await loadHistory();
}
function makeActionButton(label, onClick) {
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.addEventListener('click', onClick);
  return btn;
}
function renderCardHeader(row, item) {
  const header = document.createElement('div');
  header.className = 'arena-card-header';
  const left = document.createElement('div');
  left.className = 'arena-card-badges';
  if (item.group_key) {
    left.appendChild(badge('command', item.ok === false ? 'error' : 'kind'));
    if (item.lifecycle) left.appendChild(badge(item.lifecycle, 'flow'));
    if (item.event_count > 1) left.appendChild(badge(`${item.event_count} events`, 'count'));
  } else {
    left.appendChild(badge(item.kind || 'event', item.ok === false ? 'error' : 'kind'));
    left.appendChild(badge(itemStatus(item), item.ok === false ? 'error' : 'ok'));
    if (item.count) left.appendChild(badge(`×${item.count}`, 'count'));
  }
  const right = document.createElement('div');
  right.className = 'arena-card-time';
  right.textContent = item.at || '';
  header.appendChild(left); header.appendChild(right); row.appendChild(header);
}
function renderHistory(items) {
  const box = document.getElementById('historyBox');
  box.innerHTML = '';
  const visible = document.getElementById('kindFilter').value ? (items || []) : groupCommandHistory(items || []);
  if (!visible.length) { box.textContent = 'No history yet.'; return; }
  visible.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'arena-history-card';
    renderCardHeader(row, item);
    const title = document.createElement('div');
    title.className = 'arena-card-title';
    title.textContent = item.group_key ? (item.detail || 'command lifecycle') : (item.detail || '(no detail)');
    row.appendChild(title);
    const meta = document.createElement('div');
    meta.className = 'arena-card-meta';
    meta.textContent = cardMetaParts(item).join(' · ');
    row.appendChild(meta);
    const actions = document.createElement('div');
    actions.className = 'arena-card-actions';
    const payloadItem = payloadSourceItem(item);
    const resultItem = resultSourceItem(item);
    const latestResult = finalResultItem(item);
    const replayItem = replaySourceItem(item);
    actions.appendChild(makeActionButton('Inspect Payload', () => renderPayload(payloadItem)));
    actions.appendChild(makeActionButton('Inspect Result', () => renderResult(resultItem)));
    if (item.group_key && latestResult?.response && latestResult !== resultItem) {
      actions.appendChild(makeActionButton('Inspect Final Result', () => renderResult(latestResult)));
    }
    if (replayItem?.payload) {
      const actionIndex = historyActionIndex(replayItem, index);
      actions.appendChild(makeActionButton('Replay Preview', () => runHistoryAction(actionIndex, 'preview')));
      actions.appendChild(makeActionButton('Replay Execute', () => runHistoryAction(actionIndex, 'execute')));
      actions.appendChild(makeActionButton('Copy Payload', async () => {
        await navigator.clipboard.writeText(JSON.stringify(replayItem.payload, null, 2));
        renderStatus({ok: true, copied: true, kind: replayItem.kind});
      }));
    }
    if (resultItem?.response) actions.appendChild(makeActionButton('Copy Result', async () => {
      await navigator.clipboard.writeText(JSON.stringify(resultItem.response, null, 2));
      renderStatus({ok: true, copied: true, result: true, kind: resultItem.kind});
    }));
    row.appendChild(actions);
    box.appendChild(row);
  });
}
async function loadHistory() {
  const result = await send('arena.getHistory', {
    kind: document.getElementById('kindFilter').value,
    site: document.getElementById('siteFilter').value.trim(),
    adapter: document.getElementById('adapterFilter').value.trim(),
    limit: 100,
  });
  renderHistory(result.items || []);
}
async function clearHistory() {
  await send('arena.clearHistory');
  renderPayload(null); renderResult(null); await loadHistory();
}
async function refreshAll() {
  renderStatus({loading: 'Refreshing...'});
  await Promise.all([loadHistory(), testConnection()]);
}
let filterTimer = null;
function scheduleFilterReload() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(loadHistory, 180);
}

// ------------------------------------------------------------
// Settings tab (v0.14.35 / v4.52.1)
// ------------------------------------------------------------
// Config is stored in the background service worker
// (chrome.storage.local for the token, chrome.storage.sync for
// URL + modes). We mirror the same defaults the settings.js
// helpers use so a fresh browser profile shows sensible values.
const ARENA_SETTINGS_DEFAULTS = {
  autoPreview: false,
  autoExecuteSafe: false,
  autoInsertResult: false,
  autoSubmitResult: false,
  insertStrategy: 'auto',
  dedupSemantic: true,
  enableGenericAdapter: false,
  collapseToolResults: true,
};
const ARENA_TOGGLE_FIELDS = [
  ['mAutoPreview',          'autoPreview'],
  ['mAutoExecuteSafe',      'autoExecuteSafe'],
  ['mAutoInsertResult',     'autoInsertResult'],
  ['mAutoSubmitResult',     'autoSubmitResult'],
  ['mCollapseToolResults',  'collapseToolResults'],
  ['mDedupSemantic',        'dedupSemantic'],
  ['mEnableGenericAdapter', 'enableGenericAdapter'],
];

function _sidepanelModesFromForm() {
  const modes = {insertStrategy: document.getElementById('mInsertStrategy').value || 'auto'};
  ARENA_TOGGLE_FIELDS.forEach(([elId, modeKey]) => {
    modes[modeKey] = document.getElementById(elId).checked;
  });
  return modes;
}
function _sidepanelApplyModesToForm(modes) {
  const m = {...ARENA_SETTINGS_DEFAULTS, ...(modes || {})};
  ARENA_TOGGLE_FIELDS.forEach(([elId, modeKey]) => {
    document.getElementById(elId).checked = !!m[modeKey];
  });
  document.getElementById('mInsertStrategy').value = m.insertStrategy || 'auto';
  _sidepanelUpdateModesSummary(m);
}
function _sidepanelUpdateModesSummary(modes) {
  const parts = [];
  const toggleTrue = ARENA_TOGGLE_FIELDS.filter(([, k]) => !!modes?.[k]).map(([, k]) => k);
  if (toggleTrue.length) parts.push(toggleTrue.join(', '));
  if (modes?.insertStrategy && modes.insertStrategy !== 'auto') parts.push(`insertStrategy=${modes.insertStrategy}`);
  document.getElementById('mSummary').textContent = parts.length ? `Active: ${parts.join(' · ')}` : 'Active: manual-confirm (all defaults)';
}
async function loadSettings() {
  const cfg = await send('arena.getConfig');
  document.getElementById('cfgBridgeUrl').value = cfg?.bridgeUrl || '';
  document.getElementById('cfgBridgeToken').value = cfg?.bridgeToken || '';
  _sidepanelApplyModesToForm(cfg?.modes || ARENA_SETTINGS_DEFAULTS);
}
async function saveSettingsBridge() {
  const bridgeUrl = document.getElementById('cfgBridgeUrl').value.trim();
  const bridgeToken = document.getElementById('cfgBridgeToken').value.trim();
  const modes = _sidepanelModesFromForm();
  const result = await send('arena.saveConfig', {bridgeUrl, bridgeToken, modes});
  renderStatus(result);
  // Re-run health check so the header badge reflects the new
  // URL/token combination immediately.
  await testConnection();
}
async function saveSettingsModes() {
  const cfg = await send('arena.getConfig');
  const modes = _sidepanelModesFromForm();
  const result = await send('arena.saveConfig', {
    bridgeUrl: cfg?.bridgeUrl || '',
    bridgeToken: cfg?.bridgeToken || '',
    modes,
  });
  _sidepanelUpdateModesSummary(modes);
  renderStatus(result);
}
async function resetSettingsModes() {
  _sidepanelApplyModesToForm(ARENA_SETTINGS_DEFAULTS);
  await saveSettingsModes();
}
async function clearBridgeToken() {
  document.getElementById('cfgBridgeToken').value = '';
  await saveSettingsBridge();
}

// ------------------------------------------------------------
// Scan Now (Status tab)
// ------------------------------------------------------------
function _sidepanelScanSummaryParts(res) {
  const parts = [];
  if (!res) return ['(no response from active tab)'];
  if (res.adapter) parts.push(`adapter: <b>${res.adapter}</b>`);
  if (res.host) parts.push(`host: ${res.host}`);
  if (Number.isFinite(res.candidate_nodes)) parts.push(`${res.candidate_nodes} candidates`);
  if (Number.isFinite(res.parsed_blocks)) parts.push(`${res.parsed_blocks} blocks`);
  if (Number.isFinite(res.semantic_unique_blocks)) parts.push(`${res.semantic_unique_blocks} unique`);
  if (Number.isFinite(res.semantic_duplicate_blocks) && res.semantic_duplicate_blocks > 0) parts.push(`${res.semantic_duplicate_blocks} dup`);
  if (Number.isFinite(res.mounted_controls)) parts.push(`${res.mounted_controls} mounted`);
  if (Number.isFinite(res.dismissed_controls) && res.dismissed_controls > 0) parts.push(`${res.dismissed_controls} dismissed`);
  const composer = res.composer || {};
  if (composer.found === true) {
    const editor = composer.rich_textarea ? 'rich-textarea' : (composer.prose_mirror ? 'ProseMirror' : (composer.contenteditable ? 'contenteditable' : composer.tag));
    parts.push(`composer: ${editor} · ${composer.submit_phase || 'phase?'}`);
  } else if (composer.found === false) {
    parts.push('composer: not found');
  }
  if (Array.isArray(res.tools) && res.tools.length) parts.push(`tools: ${res.tools.join(', ')}`);
  if (res.diagnostic_summary) parts.push(res.diagnostic_summary);
  return parts;
}
function _sidepanelRenderScanEvents(events) {
  const box = document.getElementById('scanEvents');
  box.innerHTML = '';
  if (!Array.isArray(events) || !events.length) return;
  events.slice(-20).forEach((event) => {
    const div = document.createElement('div');
    div.className = 'arena-scan-event';
    const kind = document.createElement('span');
    kind.className = 'arena-scan-kind';
    kind.textContent = event.kind || '(event)';
    div.appendChild(kind);
    const rest = document.createElement('span');
    const meta = [];
    if (event.fingerprint) meta.push(`fp ${String(event.fingerprint).slice(0, 12)}`);
    if (event.previous_owner) meta.push(`prev ${String(event.previous_owner).slice(0, 12)}`);
    if (event.tag) meta.push(event.tag);
    if (event.target_kind) meta.push(event.target_kind);
    if (event.target_tag) meta.push(event.target_tag);
    if (Number.isFinite(event.lines)) meta.push(`${event.lines}l`);
    rest.textContent = meta.join(' · ');
    div.appendChild(rest);
    box.appendChild(div);
  });
}
async function runScanNow() {
  const summary = document.getElementById('scanSummary');
  const raw = document.getElementById('scanRawBox');
  const events = document.getElementById('scanEvents');
  summary.textContent = 'Scanning active tab…';
  events.innerHTML = '';
  raw.textContent = '(waiting for scan…)';
  document.getElementById('scanDetails').open = true;
  try {
    // v0.14.37 (v4.52.3): `arena.scanPage` returns the raw
    // Scan Page object directly (background just forwards
    // `scanPageDiagnostics()` from the active tab). On failure
    // the reply is `{ok: false, error, tab_url?}` -- our own
    // envelope from `sendActiveTabMessage`. Handle both.
    const res = await send('arena.scanPage');
    if (!res || res.ok === false) {
      const err = res?.error || 'no active chat tab (open a supported chat site first)';
      summary.innerHTML = `<b>Scan failed</b>: ${err}`;
      if (res?.tab_url) summary.innerHTML += `<br><small>active URL: ${res.tab_url}</small>`;
      raw.textContent = JSON.stringify(res ?? {}, null, 2);
      _sidepanelRenderScanEvents([]);
      return;
    }
    summary.innerHTML = _sidepanelScanSummaryParts(res).join(' · ');
    _sidepanelRenderScanEvents(res.events_recent || []);
    raw.textContent = JSON.stringify(res, null, 2);
  } catch (e) {
    summary.textContent = `Scan failed: ${String(e?.message || e)}`;
  }
}

// ------------------------------------------------------------
// Wire-up
// ------------------------------------------------------------
document.querySelectorAll('.arena-tab').forEach((tab) => {
  tab.addEventListener('click', () => activateTab(tab.dataset.tab));
});
TAB_LOAD_HOOKS.tools = () => loadTools(true);
TAB_LOAD_HOOKS.instructions = () => loadInstructions();
TAB_LOAD_HOOKS.history = () => loadHistory();
TAB_LOAD_HOOKS.settings = () => loadSettings();

document.getElementById('refreshBtn').addEventListener('click', refreshAll);
document.getElementById('testBtn').addEventListener('click', testConnection);
document.getElementById('policiesBtn').addEventListener('click', loadPolicies);
document.getElementById('clearBtn').addEventListener('click', clearHistory);
document.getElementById('applyFilterBtn').addEventListener('click', loadHistory);
document.getElementById('kindFilter').addEventListener('change', loadHistory);
['siteFilter', 'adapterFilter'].forEach((id) => {
  const input = document.getElementById(id);
  input.addEventListener('input', scheduleFilterReload);
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') loadHistory(); });
});

// Tools tab controls
document.getElementById('toolsCategory').addEventListener('change', () => loadTools(true));
document.getElementById('toolsReloadBtn').addEventListener('click', () => loadTools(true));
let toolsSearchTimer = null;
document.getElementById('toolsSearch').addEventListener('input', () => {
  clearTimeout(toolsSearchTimer);
  toolsSearchTimer = setTimeout(() => {
    if (TOOLS_CACHE.catalog.length) renderToolsList(TOOLS_CACHE.catalog);
    else loadTools(true);
  }, 140);
});

// Instructions tab controls
document.getElementById('instructionsCategory').addEventListener('change', loadInstructions);
document.getElementById('instructionsFormat').addEventListener('change', loadInstructions);
document.getElementById('instructionsCopyBtn').addEventListener('click', copyInstructions);
document.getElementById('instructionsRefreshBtn').addEventListener('click', loadInstructions);

// Settings tab controls
document.getElementById('cfgSaveBtn').addEventListener('click', saveSettingsBridge);
document.getElementById('cfgClearTokenBtn').addEventListener('click', clearBridgeToken);
document.getElementById('cfgRevealBtn').addEventListener('click', () => {
  const el = document.getElementById('cfgBridgeToken');
  el.type = el.type === 'password' ? 'text' : 'password';
});
document.getElementById('mSaveBtn').addEventListener('click', saveSettingsModes);
document.getElementById('mResetBtn').addEventListener('click', resetSettingsModes);
ARENA_TOGGLE_FIELDS.forEach(([elId]) => {
  document.getElementById(elId).addEventListener('change', () => {
    _sidepanelUpdateModesSummary(_sidepanelModesFromForm());
  });
});
document.getElementById('mInsertStrategy').addEventListener('change', () => {
  _sidepanelUpdateModesSummary(_sidepanelModesFromForm());
});

// Scan Now button (Status tab)
document.getElementById('scanNowBtn').addEventListener('click', runScanNow);

// Initial load: Status tab is active by default; also warm the
// bridge connection so the header badge is populated.
refreshAll().catch((error) => renderStatus({ok: false, error: String(error)}));
