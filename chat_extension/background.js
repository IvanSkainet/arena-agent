const DEFAULTS = {
  bridgeUrl: 'http://127.0.0.1:8765',
  bridgeToken: '',
  modes: (typeof ARENA_MODE_DEFAULTS !== 'undefined' ? ARENA_MODE_DEFAULTS : {
    autoPreview: false,
    autoExecuteSafe: false,
    autoInsertResult: false,
    autoSubmitResult: false,
  }),
};
const HISTORY_KEY = 'arenaHistory';
const HISTORY_LIMIT = 160;
const DETECTED_DEDUPE_MS = 30000;
function normalizeModes(data) {
  const input = data || {};
  return {
    autoPreview: !!input.autoPreview,
    autoExecuteSafe: !!input.autoExecuteSafe,
    autoInsertResult: !!input.autoInsertResult,
    autoSubmitResult: !!input.autoSubmitResult,
  };
}
function normalizeBridgeUrl(value) {
  let url = String(value || DEFAULTS.bridgeUrl).trim() || DEFAULTS.bridgeUrl;
  if (!/^https?:\/\//i.test(url)) url = `http://${url}`;
  return url.replace(/\/+$/, '');
}
async function getConfig() {
  const data = await chrome.storage.sync.get(DEFAULTS);
  const merged = {...DEFAULTS, ...data};
  merged.modes = normalizeModes(merged.modes);
  return merged;
}
async function setConfig(data) {
  const next = {
    bridgeUrl: normalizeBridgeUrl(data?.bridgeUrl),
    bridgeToken: String(data?.bridgeToken || '').trim(),
    modes: normalizeModes(data?.modes),
  };
  await chrome.storage.sync.set(next);
  return {ok: true, config: next};
}
async function getHistory(filters = {}) {
  const data = await chrome.storage.local.get({[HISTORY_KEY]: []});
  const items = data[HISTORY_KEY] || [];
  const kind = String(filters.kind || '').trim();
  const site = String(filters.site || '').trim().toLowerCase();
  const adapter = String(filters.adapter || '').trim().toLowerCase();
  const limit = Math.max(1, Math.min(200, parseInt(filters.limit || items.length || 1, 10)));
  const filtered = items.filter((item) => {
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
function detectedDedupeKey(entry) {
  return [entry.fingerprint || '', entry.site || '', entry.adapter || '', entry.base_detail || entry.detail || ''].join('|');
}
function detectedBaseDetail(entry) {
  return String(entry.base_detail || entry.detail || 'detected block').replace(/ ×\d+$/, '');
}
async function pushHistory(kind, detail) {
  const current = await getHistory();
  const entry = typeof detail === 'string' ? {detail} : (detail || {});
  const now = new Date().toISOString();
  const existing = current.items || [];
  if (kind === 'detected') {
    entry.base_detail = detectedBaseDetail(entry);
    const key = detectedDedupeKey(entry);
    const index = existing.findIndex((item) => item.kind === 'detected'
      && detectedDedupeKey(item) === key
      && Date.parse(now) - Date.parse(item.at || 0) <= DETECTED_DEDUPE_MS);
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
  const cfg = await getConfig();
  const headers = {'Content-Type': 'application/json'};
  if (cfg.bridgeToken) headers.Authorization = `Bearer ${cfg.bridgeToken}`;
  const base = normalizeBridgeUrl(cfg.bridgeUrl);
  const url = `${base}${path}`;
  try {
    const res = await fetch(url, {method, headers, body: body ? JSON.stringify(body) : undefined});
    const text = await res.text();
    let parsed; try { parsed = JSON.parse(text); } catch { parsed = {ok: false, error: text || `HTTP ${res.status}`, raw: text}; }
    if (!res.ok) return {ok: false, status: res.status, error: parsed.error || parsed.raw || `HTTP ${res.status}`, bridge_url: base, path, ...parsed};
    return parsed;
  } catch (error) {
    return {ok: false, error: `${String(error)} while fetching ${url}`, bridge_url: base, path};
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
  if (!chrome.tabs?.query || !chrome.tabs?.sendMessage) return {ok: false, error: 'tabs api unavailable'};
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id) return {ok: false, error: 'active tab not found'};
  return new Promise((resolve) => chrome.tabs.sendMessage(tab.id, message, (response) => {
    const err = chrome.runtime.lastError; resolve(err ? {ok: false, error: err.message || String(err)} : (response || {ok: false, error: 'empty content response'}));
  }));
}
async function scanActivePage() {
  const result = await sendActiveTabMessage({type: 'arena.scanPage'});
  await pushHistory('scan', {detail: result.ok ? `${result.adapter || 'unknown'}: ${result.parsed_blocks || 0} block(s), ${result.candidate_nodes || 0} candidate(s)` : `error: ${result.error || 'unknown'}`, site: result.url || '', adapter: result.adapter || '', ok: !!result.ok, response: result});
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
  const cfg = await chrome.storage.sync.get(DEFAULTS); await chrome.storage.sync.set({...DEFAULTS, ...cfg});
  const local = await chrome.storage.local.get({[HISTORY_KEY]: []});
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
      return sendResponse(await bridgeFetch(`/v1/extension/instructions?format=${fmt}&style=${style}`));
    }
    return sendResponse({ok: false, error: 'unknown message type'});
  })().catch((error) => sendResponse({ok: false, error: String(error)}));
  return true;
});
