const HISTORY_KEY = 'arenaHistory';
const HISTORY_LIMIT = 160;
const HISTORY_AGGREGATE_MS = 30000;
const SYNC_DEFAULTS = {
  bridgeUrl: 'http://127.0.0.1:8765',
  modes: (typeof ARENA_MODE_DEFAULTS !== 'undefined' ? ARENA_MODE_DEFAULTS : {
    autoPreview: false,
    autoExecuteSafe: false,
    autoInsertResult: false,
    autoSubmitResult: false,
    insertStrategy: 'auto',
    dedupSemantic: true,
    // v0.14.28 (v4.50.18): generic-adapter opt-in. Default FALSE
    // matches settings.js so unlisted sites stay untouched.
    enableGenericAdapter: false,
    // v0.14.29 (v4.51.0): fold inserted tool-result blocks in
    // chat history. Default TRUE mirrors settings.js.
    collapseToolResults: true,
  }),
};
function normalizeModes(data) {
  const input = data || {};
  const allowed = ['auto', 'nativeInsertText', 'paragraphFallback', 'pasteOnly', 'directDomText', 'directDomBlocks', 'directDomPreWrap'];
  return {
    autoPreview: !!input.autoPreview,
    autoExecuteSafe: !!input.autoExecuteSafe,
    autoInsertResult: !!input.autoInsertResult,
    autoSubmitResult: !!input.autoSubmitResult,
    insertStrategy: allowed.includes(input.insertStrategy) ? input.insertStrategy : 'auto',
    // v0.14.15: mirror the settings.js default -- operator-controllable
    // toolbar dedup, default TRUE. Background needs its own normalizer
    // because settings.js is a content-script asset and background.js
    // cannot import it directly.
    dedupSemantic: input.dedupSemantic === undefined ? true : !!input.dedupSemantic,
    // v0.14.28 (v4.50.18): default FALSE. Explicit true required
    // for the generic adapter to attempt mounts on unlisted sites.
    enableGenericAdapter: !!input.enableGenericAdapter,
    // v0.14.29 (v4.51.0): default TRUE.
    collapseToolResults: input.collapseToolResults === undefined ? true : !!input.collapseToolResults,
  };
}
function normalizeBridgeUrl(value) {
  let url = String(value || SYNC_DEFAULTS.bridgeUrl).trim() || SYNC_DEFAULTS.bridgeUrl;
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`;
  return url.replace(/\/+$/, '');
}
function bridgeFallbackBase(base) {
  if (/^http:\/\/(127\.0\.0\.1|localhost):8765$/i.test(base)) return '';
  if (/\.ts\.net$/i.test(new URL(base).hostname) || /\.trycloudflare\.com$/i.test(new URL(base).hostname)) return 'http://127.0.0.1:8765';
  return '';
}
async function bridgeFetchOnce(base, path, headers, method, body) {
  const url = `${base}${path}`;
  const res = await fetch(url, {method, headers, body: body ? JSON.stringify(body) : undefined});
  const text = await res.text();
  let parsed; try { parsed = JSON.parse(text); } catch { parsed = {ok: false, error: text || `HTTP ${res.status}`, raw: text}; }
  if (!res.ok) return {ok: false, status: res.status, error: parsed.error || parsed.raw || `HTTP ${res.status}`, bridge_url: base, path, ...parsed};
  return {...parsed, bridge_url: base};
}
let _cachedConfig = null;
async function getConfig() {
  if (_cachedConfig) return _cachedConfig;
  const [syncData, localData] = await Promise.all([
    chrome.storage.sync.get({...SYNC_DEFAULTS, bridgeToken: ''}),
    chrome.storage.local.get({bridgeToken: ''}),
  ]);
  const bridgeToken = String(localData.bridgeToken || syncData.bridgeToken || '').trim();
  if (!localData.bridgeToken && bridgeToken) await chrome.storage.local.set({bridgeToken});
  if (syncData.bridgeToken) await chrome.storage.sync.remove('bridgeToken');
  _cachedConfig = {
    bridgeUrl: normalizeBridgeUrl(syncData.bridgeUrl),
    bridgeToken,
    modes: normalizeModes(syncData.modes),
  };
  return _cachedConfig;
}
function invalidateConfigCache() { _cachedConfig = null; }
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'sync' || area === 'local') invalidateConfigCache();
});
async function setConfig(data) {
  const next = {
    bridgeUrl: normalizeBridgeUrl(data?.bridgeUrl),
    bridgeToken: String(data?.bridgeToken || '').trim(),
    modes: normalizeModes(data?.modes),
  };
  await Promise.all([
    chrome.storage.sync.set({bridgeUrl: next.bridgeUrl, modes: next.modes}),
    chrome.storage.local.set({bridgeToken: next.bridgeToken}),
    chrome.storage.sync.remove('bridgeToken'),
  ]);
  invalidateConfigCache();
  return {ok: true, config: next};
}
async function getHistory(filters = {}) {
  const data = await chrome.storage.local.get({[HISTORY_KEY]: []});
  const items = data[HISTORY_KEY] || [];
  const kind = String(filters.kind || '').trim();
  const site = String(filters.site || '').trim().toLowerCase();
  const adapter = String(filters.adapter || '').trim().toLowerCase();
  const limit = Math.max(1, Math.min(200, parseInt(filters.limit || items.length || 1, 10)));
  const filtered = items.map((item, index) => ({...item, history_index: index})).filter((item) => {
    if (kind && item.kind !== kind) return false;
    if (site && !String(item.site || '').toLowerCase().includes(site)) return false;
    if (adapter && !String(item.adapter || '').toLowerCase().includes(adapter)) return false;
    return true;
  });
  return {ok: true, items: filtered.slice(0, limit), total: items.length, filtered: filtered.length};
}
async function getHistoryItem(index) {
  const current = await getHistory();
  const item = (current.items || [])[index];
  if (!item) return {ok: false, error: 'history item not found'};
  return {ok: true, item};
}
async function clearHistory() {
  await chrome.storage.local.set({[HISTORY_KEY]: []}); return {ok: true};
}
function compactResult(result) {
  if (!result || typeof result !== 'object') return null;
  const summary = {ok: !!result.ok};
  ['error', 'status', 'summary'].forEach((key) => { if (result[key]) summary[key] = result[key]; });
  if (Array.isArray(result.calls)) summary.calls = result.calls.map((call) => ({
    id: call.id, tool: call.tool, ok: call.ok, risk: call.risk,
    result: call.result?.parsed || call.result?.text || call.result?.raw || null,
  }));
  if (result.preview) summary.preview = result.preview;
  return summary;
}
function describeBridgeResult(result) {
  if (!result) return 'empty response';
  if (result.error) return String(result.error);
  const failed = Array.isArray(result.calls) ? result.calls.find((call) => call && call.ok === false) : null;
  const parsed = failed?.result?.parsed;
  return parsed?.error || parsed?.message || (failed?.result?.text ? String(failed.result.text).slice(0, 220) : '') || result.summary || (result.status ? `HTTP ${result.status}` : 'unknown');
}
function historyBaseDetail(entry, kind = '') {
  const tools = Array.isArray(entry.tools) && entry.tools.length ? `detected ${entry.tools.slice(0, 4).join(', ')}` : '';
  const fallback = kind === 'detected' ? 'detected block' : `${kind || 'event'} result`;
  return String(entry.base_detail || entry.detail || tools || fallback).replace(/ ×\d+$/, '');
}
function historyAggregateKey(entry, kind = '') {
  if (kind === 'detected') return [entry.payload_fingerprint || entry.fingerprint || '', entry.site || '', entry.adapter || '', entry.base_detail || entry.detail || ''].join('|');
  if (kind === 'scan') return [entry.site || '', entry.adapter || '', entry.base_detail || entry.detail || '', entry.ok === false ? 'error' : 'ok'].join('|');
  return '';
}
function isAggregatedHistoryKind(kind) {
  return kind === 'detected' || kind === 'scan';
}
async function pushHistory(kind, detail) {
  const current = await getHistory();
  const entry = typeof detail === 'string' ? {detail} : (detail || {});
  const now = new Date().toISOString();
  const existing = current.items || [];
  if (isAggregatedHistoryKind(kind)) {
    entry.base_detail = historyBaseDetail(entry, kind);
    const key = historyAggregateKey(entry, kind);
    const index = existing.findIndex((item) => item.kind === kind
      && historyAggregateKey(item, kind) === key
      && Date.parse(now) - Date.parse(item.at || 0) <= HISTORY_AGGREGATE_MS);
    if (index >= 0) {
      const previous = existing[index];
      const count = (parseInt(previous.count || 1, 10) || 1) + 1;
      const updated = {...previous, ...entry, at: now, kind, count, detail: `${entry.base_detail} ×${count}`};
      const items = [updated, ...existing.slice(0, index), ...existing.slice(index + 1)].slice(0, HISTORY_LIMIT);
      await chrome.storage.local.set({[HISTORY_KEY]: items});
      return;
    }
  }
  const items = [{at: now, kind, ...entry}, ...existing].slice(0, HISTORY_LIMIT);
  await chrome.storage.local.set({[HISTORY_KEY]: items});
}
async function bridgeFetch(path, {method = 'GET', body} = {}) {
  const started = Date.now();
  const cfg = await getConfig();
  const headers = {'Content-Type': 'application/json'};
  if (cfg.bridgeToken) headers.Authorization = `Bearer ${cfg.bridgeToken}`;
  const base = normalizeBridgeUrl(cfg.bridgeUrl);
  try {
    const result = await bridgeFetchOnce(base, path, headers, method, body);
    return {...result, bridge_ms: Date.now() - started};
  } catch (error) {
    const fallback = bridgeFallbackBase(base);
    if (fallback) {
      try {
        const result = await bridgeFetchOnce(fallback, path, headers, method, body);
        return {...result, bridge_url_primary: base, bridge_url_fallback: fallback, bridge_ms: Date.now() - started};
      } catch (_fallbackError) {}
    }
    return {ok: false, error: `${String(error)} while fetching ${base}${path}`, bridge_url: base, bridge_url_fallback: fallback || '', path, bridge_ms: Date.now() - started};
  }
}
async function testConnection() {
  const version = await bridgeFetch('/v1/version');
  if (!version.ok) return version;
  const policies = await bridgeFetch('/v1/extension/policies');
  return {ok: !!policies.ok, version, policies};
}
async function openSidePanel() {
  const url = chrome.runtime.getURL('sidepanel.html');
  try {
    if (chrome.sidePanel?.open && chrome.tabs?.query) {
      const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
      if (tab?.id) { await chrome.sidePanel.open({tabId: tab.id}); return {ok: true, tabId: tab.id, mode: 'sidePanel'}; }
    }
  } catch (error) {
    if (!chrome.tabs?.create) return {ok: false, error: String(error)};
    const tab = await chrome.tabs.create({url, active: true});
    return {ok: true, tabId: tab?.id, mode: 'tab', warning: String(error)};
  }
  if (!chrome.tabs?.create) return {ok: false, error: 'side panel api unavailable'};
  const tab = await chrome.tabs.create({url, active: true}); return {ok: true, tabId: tab?.id, mode: 'tab'};
}
async function sendActiveTabMessage(message) {
  // v0.14.37 (v4.52.3): sidepanel-safe tab resolver. Previous
  // implementation used `{active: true, currentWindow: true}`,
  // but when the caller is the side panel the sender window is
  // the panel itself, not the browser window with the chat tab.
  // Chrome returns the panel window as `currentWindow`, so the
  // query matched nothing and Scan Now silently returned
  // `active tab not found`. Fix by falling back through the
  // last-focused window and finally any active tab, and by
  // filtering out URLs where content scripts cannot run.
  if (!chrome.tabs?.query || !chrome.tabs?.sendMessage) return {ok: false, error: 'tabs api unavailable'};
  const _isChatUrl = (u) => {
    if (!u) return false;
    if (u.startsWith('chrome://') || u.startsWith('chrome-extension://')
        || u.startsWith('edge://') || u.startsWith('about:')
        || u.startsWith('file://')) return false;
    return u.startsWith('http://') || u.startsWith('https://');
  };
  let tab = null;
  // Preferred: the last-focused NORMAL window's active tab.
  try {
    const [t] = await chrome.tabs.query({active: true, lastFocusedWindow: true});
    if (t?.id && _isChatUrl(t.url)) tab = t;
  } catch (_e) { /* Chrome MV3 may reject in some contexts */ }
  // Fallback: current window (works from popup / content-script origins).
  if (!tab) {
    try {
      const [t] = await chrome.tabs.query({active: true, currentWindow: true});
      if (t?.id && _isChatUrl(t.url)) tab = t;
    } catch (_e) { /* keep looking */ }
  }
  // Last resort: first non-chrome:// active tab in any window.
  if (!tab) {
    try {
      const all = await chrome.tabs.query({active: true});
      tab = all.find((t) => t?.id && _isChatUrl(t.url)) || null;
    } catch (_e) { /* nothing else to try */ }
  }
  if (!tab?.id) return {ok: false, error: 'no active chat tab (open a supported chat site first)'};
  return new Promise((resolve) => chrome.tabs.sendMessage(tab.id, message, (response) => {
    const err = chrome.runtime.lastError;
    if (err) {
      // Classify the common "content script did not load" error
      // so the sidepanel can show something actionable instead
      // of the raw Chrome message.
      const raw = err.message || String(err);
      const friendly = /Receiving end does not exist|Could not establish/.test(raw)
        ? `${raw} — reload the tab so the extension can inject its content script`
        : raw;
      return resolve({ok: false, error: friendly, tab_url: tab.url || ''});
    }
    resolve(response || {ok: false, error: 'empty content response', tab_url: tab.url || ''});
  }));
}
function scanHistoryDetail(result) {
  if (!result?.ok) return `error: ${result?.error || 'unknown'}`;
  const summary = String(result.diagnostic_summary || '').trim();
  const tools = Array.isArray(result.tools) && result.tools.length ? `tools=${result.tools.join(', ')}` : '';
  const base = summary || `${result.parsed_blocks || 0} block(s), ${result.candidate_nodes || 0} candidate(s)`;
  return `${result.adapter || 'unknown'}: ${tools ? `${base} · ${tools}` : base}`;
}
async function scanActivePage() {
  const result = await sendActiveTabMessage({type: 'arena.scanPage'});
  const detail = scanHistoryDetail(result);
  await pushHistory('scan', {detail, base_detail: detail, site: result.url || '', adapter: result.adapter || '', ok: !!result.ok, response: result});
  return result;
}
async function replayHistory(index, mode = 'execute') {
  const itemResult = await getHistoryItem(index);
  if (!itemResult.ok) return itemResult;
  const item = itemResult.item;
  if (!item.payload) return {ok: false, error: 'history item has no payload'};
  if (mode === 'preview') return bridgeFetch('/v1/extension/preview', {method: 'POST', body: item.payload});
  return bridgeFetch('/v1/extension/execute', {method: 'POST', body: {...item.payload, mode: {...(item.payload.mode || {}), approve: true}}});
}
chrome.runtime.onInstalled.addListener(async () => {
  const cfg = await getConfig();
  await chrome.storage.sync.set({bridgeUrl: cfg.bridgeUrl, modes: cfg.modes});
  const local = await chrome.storage.local.get({[HISTORY_KEY]: [], bridgeToken: cfg.bridgeToken});
  if (!Array.isArray(local[HISTORY_KEY])) await chrome.storage.local.set({[HISTORY_KEY]: []});
});
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message?.type === 'arena.getConfig') return sendResponse(await getConfig());
    if (message?.type === 'arena.saveConfig') return sendResponse(await setConfig(message.body || {}));
    if (message?.type === 'arena.getHistory') return sendResponse(await getHistory(message.body || {}));
    if (message?.type === 'arena.getHistoryItem') return sendResponse(await getHistoryItem(message.body?.index));
    if (message?.type === 'arena.clearHistory') return sendResponse(await clearHistory());
    if (message?.type === 'arena.testConnection') return sendResponse(await testConnection());
    if (message?.type === 'arena.openSidePanel') return sendResponse(await openSidePanel());
    if (message?.type === 'arena.replayHistory') return sendResponse(await replayHistory(message.body?.index, message.body?.mode));
    if (message?.type === 'arena.scanPage') return sendResponse(await scanActivePage());
    if (message?.type === 'arena.detected') {
      await pushHistory('detected', message.body || {detail: 'arena-tool block'});
      return sendResponse({ok: true});
    }
    if (message?.type === 'arena.insertEvent') {
      const body = message.body || {};
      const kind = body.kind === 'submit' ? 'submit' : 'insert';
      await pushHistory(kind, {
        detail: body.detail || kind,
        site: body.site || '',
        adapter: body.adapter || '',
        fingerprint: body.fingerprint || '',
        ok: body.ok !== false,
        payload: body.payload || null,
        response: body.response || null,
      });
      return sendResponse({ok: true});
    }
    if (message?.type === 'arena.preview') {
      const result = await bridgeFetch('/v1/extension/preview', {method: 'POST', body: message.body});
      await pushHistory('preview', {
        detail: result.ok ? `${result.calls?.length || 0} call(s)` : `error: ${describeBridgeResult(result)}`,
        site: message.body?.site?.origin || '',
        adapter: message.body?.site?.adapter || '',
        fingerprint: message.body?.message?.fingerprint || '',
        ok: !!result.ok,
        payload: message.body,
        response: compactResult(result),
      });
      return sendResponse(result);
    }
    if (message?.type === 'arena.execute') {
      const result = await bridgeFetch('/v1/extension/execute', {method: 'POST', body: message.body});
      await pushHistory('execute', {
        detail: result.ok ? `${result.calls?.length || 0} call(s)` : `error: ${describeBridgeResult(result)}`,
        site: message.body?.site?.origin || '',
        adapter: message.body?.site?.adapter || '',
        fingerprint: message.body?.message?.fingerprint || '',
        ok: !!result.ok,
        payload: message.body,
        response: compactResult(result),
      });
      return sendResponse(result);
    }
    if (message?.type === 'arena.policies') return sendResponse(await bridgeFetch('/v1/extension/policies'));
    if (message?.type === 'arena.instructions') {
      const fmt = encodeURIComponent(message.body?.format || 'arena');
      const style = encodeURIComponent(message.body?.style || 'full');
      // v4.51.1: pass through optional catalog category so the
      // popup can request a full tool catalog scoped to a topic.
      const category = message.body?.category
        ? `&category=${encodeURIComponent(message.body.category)}`
        : '';
      return sendResponse(await bridgeFetch(`/v1/extension/instructions?format=${fmt}&style=${style}${category}`));
    }
    return sendResponse({ok: false, error: 'unknown message type'});
  })().catch((error) => sendResponse({ok: false, error: String(error)}));
  return true;
});



