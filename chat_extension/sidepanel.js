async function send(type, body) {
  return chrome.runtime.sendMessage({type, body});
}

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
  return item.kind || 'event';
}
function badge(text, tone = 'neutral') {
  const span = document.createElement('span');
  span.className = `arena-badge arena-badge-${tone}`;
  span.textContent = text;
  return span;
}
function renderStatus(data) {
  const box = document.getElementById('statusBox');
  const version = data?.version?.version || data?.version || '';
  const policies = data?.policies?.ok ? 'policies ok' : (data?.policies ? 'policies error' : '');
  const status = data?.ok === false ? 'error' : 'ok';
  box.textContent = data?.loading || `Bridge ${status}${version ? ' · v' + version : ''}${policies ? ' · ' + policies : ''}`;
  box.dataset.raw = JSON.stringify(data, null, 2);
}
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
  left.appendChild(badge(item.kind || 'event', item.ok === false ? 'error' : 'kind'));
  left.appendChild(badge(itemStatus(item), item.ok === false ? 'error' : 'ok'));
  if (item.count) left.appendChild(badge(`×${item.count}`, 'count'));
  const right = document.createElement('div');
  right.className = 'arena-card-time';
  right.textContent = item.at || '';
  header.appendChild(left); header.appendChild(right); row.appendChild(header);
}
function renderHistory(items) {
  const box = document.getElementById('historyBox');
  box.innerHTML = '';
  if (!items || !items.length) { box.textContent = 'No history yet.'; return; }
  items.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'arena-history-card';
    renderCardHeader(row, item);
    const title = document.createElement('div');
    title.className = 'arena-card-title';
    title.textContent = item.detail || '(no detail)';
    row.appendChild(title);
    const meta = document.createElement('div');
    meta.className = 'arena-card-meta';
    const tools = itemTools(item).join(', ');
    meta.textContent = [item.adapter || '', shortUrl(item.site), tools ? `tools: ${tools}` : ''].filter(Boolean).join(' · ');
    row.appendChild(meta);
    const actions = document.createElement('div');
    actions.className = 'arena-card-actions';
    actions.appendChild(makeActionButton('Inspect Payload', () => renderPayload(item)));
    actions.appendChild(makeActionButton('Inspect Result', () => renderResult(item)));
    if (item.payload && (item.kind === 'preview' || item.kind === 'execute' || item.kind === 'detected')) {
      actions.appendChild(makeActionButton('Replay Preview', () => runHistoryAction(index, 'preview')));
      actions.appendChild(makeActionButton('Replay Execute', () => runHistoryAction(index, 'execute')));
      actions.appendChild(makeActionButton('Copy Payload', async () => {
        await navigator.clipboard.writeText(JSON.stringify(item.payload, null, 2));
        renderStatus({ok: true, copied: true, kind: item.kind});
      }));
    }
    if (item.response) actions.appendChild(makeActionButton('Copy Result', async () => {
      await navigator.clipboard.writeText(JSON.stringify(item.response, null, 2));
      renderStatus({ok: true, copied: true, result: true, kind: item.kind});
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
async function clearHistory() {
  await send('arena.clearHistory');
  renderPayload(null); renderResult(null); await loadHistory();
}
async function refreshAll() {
  renderStatus({loading: 'Refreshing...'});
  await Promise.all([loadHistory(), testConnection()]);
}
document.getElementById('refreshBtn').addEventListener('click', refreshAll);
document.getElementById('testBtn').addEventListener('click', testConnection);
document.getElementById('policiesBtn').addEventListener('click', loadPolicies);
document.getElementById('clearBtn').addEventListener('click', clearHistory);
document.getElementById('applyFilterBtn').addEventListener('click', loadHistory);
refreshAll().catch((error) => renderStatus({ok: false, error: String(error)}));
