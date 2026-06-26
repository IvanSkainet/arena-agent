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

function normalizeModes(data) {
  const input = data || {};
  return {
    autoPreview: !!input.autoPreview,
    autoExecuteSafe: !!input.autoExecuteSafe,
    autoInsertResult: !!input.autoInsertResult,
    autoSubmitResult: !!input.autoSubmitResult,
  };
}

async function getConfig() {
  const data = await chrome.storage.sync.get(DEFAULTS);
  const merged = {...DEFAULTS, ...data};
  merged.modes = normalizeModes(merged.modes);
  return merged;
}

async function setConfig(data) {
  const next = {
    bridgeUrl: String(data?.bridgeUrl || DEFAULTS.bridgeUrl).trim() || DEFAULTS.bridgeUrl,
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
  await chrome.storage.local.set({[HISTORY_KEY]: []});
  return {ok: true};
}

function compactResult(result) {
  if (!result || typeof result !== 'object') return null;
  const summary = {ok: !!result.ok};
  if (result.summary) summary.summary = result.summary;
  if (Array.isArray(result.calls)) {
    summary.calls = result.calls.map((call) => ({
      id: call.id,
      tool: call.tool,
      ok: call.ok,
      risk: call.risk,
      result: call.result?.parsed || call.result?.text || call.result?.raw || null,
    }));
  }
  if (result.preview) summary.preview = result.preview;
  return summary;
}

async function pushHistory(kind, detail) {
  const current = await getHistory();
  const entry = typeof detail === 'string' ? {detail} : (detail || {});
  const items = [{at: new Date().toISOString(), kind, ...entry}, ...(current.items || [])].slice(0, HISTORY_LIMIT);
  await chrome.storage.local.set({[HISTORY_KEY]: items});
}

async function bridgeFetch(path, {method = 'GET', body} = {}) {
  const cfg = await getConfig();
  const headers = {'Content-Type': 'application/json'};
  if (cfg.bridgeToken) headers.Authorization = `Bearer ${cfg.bridgeToken}`;
  const res = await fetch(`${cfg.bridgeUrl}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let parsed;
  try { parsed = JSON.parse(text); } catch { parsed = {ok: false, raw: text}; }
  if (!res.ok) return {ok: false, status: res.status, ...parsed};
  return parsed;
}

async function testConnection() {
  const version = await bridgeFetch('/v1/version');
  if (!version.ok) return version;
  const policies = await bridgeFetch('/v1/extension/policies');
  return {ok: !!policies.ok, version, policies};
}

async function openSidePanel() {
  if (!chrome.sidePanel?.open || !chrome.tabs?.query) return {ok: false, error: 'side panel api unavailable'};
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  if (!tab?.id) return {ok: false, error: 'active tab not found'};
  await chrome.sidePanel.open({tabId: tab.id});
  return {ok: true, tabId: tab.id};
}

async function replayHistory(index, mode = 'execute') {
  const itemResult = await getHistoryItem(index);
  if (!itemResult.ok) return itemResult;
  const item = itemResult.item;
  if (!item.payload) return {ok: false, error: 'history item has no payload'};
  if (mode === 'preview') {
    return bridgeFetch('/v1/extension/preview', {method: 'POST', body: item.payload});
  }
  return bridgeFetch('/v1/extension/execute', {method: 'POST', body: {...item.payload, mode: {...(item.payload.mode || {}), approve: true}}});
}

chrome.runtime.onInstalled.addListener(async () => {
  const cfg = await chrome.storage.sync.get(DEFAULTS);
  await chrome.storage.sync.set({...DEFAULTS, ...cfg});
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
    if (message?.type === 'arena.detected') {
      await pushHistory('detected', message.body || {detail: 'arena-tool block'});
      return sendResponse({ok: true});
    }
    if (message?.type === 'arena.preview') {
      const result = await bridgeFetch('/v1/extension/preview', {method: 'POST', body: message.body});
      await pushHistory('preview', {
        detail: result.ok ? `${result.calls?.length || 0} call(s)` : `error: ${result.error || 'unknown'}`,
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
        detail: result.ok ? `${result.calls?.length || 0} call(s)` : `error: ${result.error || 'unknown'}`,
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
