const DEFAULTS = {
  bridgeUrl: 'http://127.0.0.1:8765',
  bridgeToken: '',
};
const HISTORY_KEY = 'arenaHistory';
const HISTORY_LIMIT = 50;

async function getConfig() {
  const data = await chrome.storage.sync.get(DEFAULTS);
  return {...DEFAULTS, ...data};
}

async function setConfig(data) {
  const next = {
    bridgeUrl: String(data?.bridgeUrl || DEFAULTS.bridgeUrl).trim() || DEFAULTS.bridgeUrl,
    bridgeToken: String(data?.bridgeToken || '').trim(),
  };
  await chrome.storage.sync.set(next);
  return {ok: true, config: next};
}

async function getHistory() {
  const data = await chrome.storage.local.get({[HISTORY_KEY]: []});
  return {ok: true, items: data[HISTORY_KEY] || []};
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
    if (message?.type === 'arena.getHistory') return sendResponse(await getHistory());
    if (message?.type === 'arena.testConnection') return sendResponse(await testConnection());
    if (message?.type === 'arena.openSidePanel') return sendResponse(await openSidePanel());
    if (message?.type === 'arena.detected') {
      await pushHistory('detected', message.body || {detail: 'arena-tool block'});
      return sendResponse({ok: true});
    }
    if (message?.type === 'arena.preview') {
      const result = await bridgeFetch('/v1/extension/preview', {method: 'POST', body: message.body});
      await pushHistory('preview', {detail: result.ok ? `${result.calls?.length || 0} call(s)` : `error: ${result.error || 'unknown'}`, site: message.body?.site?.origin || '', ok: !!result.ok});
      return sendResponse(result);
    }
    if (message?.type === 'arena.execute') {
      const result = await bridgeFetch('/v1/extension/execute', {method: 'POST', body: message.body});
      await pushHistory('execute', {detail: result.ok ? `${result.calls?.length || 0} call(s)` : `error: ${result.error || 'unknown'}`, site: message.body?.site?.origin || '', ok: !!result.ok});
      return sendResponse(result);
    }
    if (message?.type === 'arena.policies') return sendResponse(await bridgeFetch('/v1/extension/policies'));
    return sendResponse({ok: false, error: 'unknown message type'});
  })().catch((error) => sendResponse({ok: false, error: String(error)}));
  return true;
});
