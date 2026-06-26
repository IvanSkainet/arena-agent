async function send(type, body) {
  return chrome.runtime.sendMessage({type, body});
}

function renderStatus(data) {
  const box = document.getElementById('statusBox');
  box.textContent = JSON.stringify(data, null, 2);
}

function renderPayload(item) {
  const box = document.getElementById('payloadBox');
  if (!item || !item.payload) {
    box.textContent = 'Select a history entry to inspect its payload.';
    return;
  }
  box.textContent = JSON.stringify(item.payload, null, 2);
}

function renderResult(item) {
  const box = document.getElementById('resultBox');
  if (!item || !item.response) {
    box.textContent = 'Select a history entry to inspect its result.';
    return;
  }
  box.textContent = JSON.stringify(item.response, null, 2);
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

function renderHistory(items) {
  const box = document.getElementById('historyBox');
  box.innerHTML = '';
  if (!items || !items.length) {
    box.textContent = 'No history yet.';
    return;
  }
  items.forEach((item, index) => {
    const row = document.createElement('div');
    row.style.cssText = 'border-bottom:1px solid #334155;padding:8px 0;';
    const meta = document.createElement('div');
    const adapter = item.adapter ? ` / ${item.adapter}` : '';
    meta.textContent = `[${item.at || ''}] ${item.kind || 'event'}${item.site ? ' @ ' + item.site : ''}${adapter}`;
    meta.style.cssText = 'font-size:12px;color:#cbd5e1;margin-bottom:4px;';
    const detail = document.createElement('div');
    detail.textContent = item.detail || '';
    detail.style.cssText = 'font-size:12px;color:#f8fafc;margin-bottom:6px;white-space:pre-wrap;';
    row.appendChild(meta);
    row.appendChild(detail);
    const actions = document.createElement('div');
    actions.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
    actions.appendChild(makeActionButton('Inspect Payload', () => renderPayload(item)));
    actions.appendChild(makeActionButton('Inspect Result', () => renderResult(item)));
    if (item.payload) {
      actions.appendChild(makeActionButton('Replay Preview', () => runHistoryAction(index, 'preview')));
      actions.appendChild(makeActionButton('Replay Execute', () => runHistoryAction(index, 'execute')));
      actions.appendChild(makeActionButton('Copy Payload', async () => {
        await navigator.clipboard.writeText(JSON.stringify(item.payload, null, 2));
        renderStatus({ok: true, copied: true, kind: item.kind});
      }));
    }
    if (item.response) {
      actions.appendChild(makeActionButton('Copy Result', async () => {
        await navigator.clipboard.writeText(JSON.stringify(item.response, null, 2));
        renderStatus({ok: true, copied: true, result: true, kind: item.kind});
      }));
    }
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
  const result = await send('arena.testConnection');
  renderStatus(result);
}

async function loadPolicies() {
  renderStatus({loading: 'Loading policies...'});
  const result = await send('arena.policies');
  renderStatus(result);
}

async function clearHistory() {
  await send('arena.clearHistory');
  renderPayload(null);
  renderResult(null);
  await loadHistory();
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
refreshAll().catch((error) => {
  renderStatus({ok: false, error: String(error)});
});
