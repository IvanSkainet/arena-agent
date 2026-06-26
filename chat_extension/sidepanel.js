async function send(type, body) {
  return chrome.runtime.sendMessage({type, body});
}

function renderStatus(data) {
  const box = document.getElementById('statusBox');
  box.textContent = JSON.stringify(data, null, 2);
}

async function runHistoryAction(index, mode) {
  const result = await send('arena.replayHistory', {index, mode});
  renderStatus(result);
  await loadHistory();
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
    meta.textContent = `[${item.at || ''}] ${item.kind || 'event'}${item.site ? ' @ ' + item.site : ''}`;
    meta.style.cssText = 'font-size:12px;color:#cbd5e1;margin-bottom:4px;';
    const detail = document.createElement('div');
    detail.textContent = item.detail || '';
    detail.style.cssText = 'font-size:12px;color:#f8fafc;margin-bottom:6px;white-space:pre-wrap;';
    row.appendChild(meta);
    row.appendChild(detail);
    if (item.payload) {
      const actions = document.createElement('div');
      actions.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap;';
      const preview = document.createElement('button');
      preview.textContent = 'Replay Preview';
      preview.addEventListener('click', () => runHistoryAction(index, 'preview'));
      const execute = document.createElement('button');
      execute.textContent = 'Replay Execute';
      execute.addEventListener('click', () => runHistoryAction(index, 'execute'));
      actions.appendChild(preview);
      actions.appendChild(execute);
      row.appendChild(actions);
    }
    box.appendChild(row);
  });
}

async function loadHistory() {
  const result = await send('arena.getHistory');
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
refreshAll().catch((error) => {
  renderStatus({ok: false, error: String(error)});
});
