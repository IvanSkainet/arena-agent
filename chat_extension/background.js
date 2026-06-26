const DEFAULTS = {
  bridgeUrl: 'http://127.0.0.1:8765',
  bridgeToken: '',
};

async function getConfig() {
  const data = await chrome.storage.sync.get(DEFAULTS);
  return {...DEFAULTS, ...data};
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

chrome.runtime.onInstalled.addListener(async () => {
  const cfg = await chrome.storage.sync.get(DEFAULTS);
  await chrome.storage.sync.set({...DEFAULTS, ...cfg});
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message?.type === 'arena.preview') {
      return sendResponse(await bridgeFetch('/v1/extension/preview', {method: 'POST', body: message.body}));
    }
    if (message?.type === 'arena.execute') {
      return sendResponse(await bridgeFetch('/v1/extension/execute', {method: 'POST', body: message.body}));
    }
    if (message?.type === 'arena.policies') {
      return sendResponse(await bridgeFetch('/v1/extension/policies'));
    }
    return sendResponse({ok: false, error: 'unknown message type'});
  })().catch((error) => sendResponse({ok: false, error: String(error)}));
  return true;
});
