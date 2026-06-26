async function send(type, body) {
  return chrome.runtime.sendMessage({type, body});
}

function renderHistory(items) {
  const box = document.getElementById('historyBox');
  if (!items || !items.length) {
    box.textContent = 'No history yet.';
    return;
  }
  box.textContent = items.map((item) => {
    const ts = item.at || '';
    const kind = item.kind || 'event';
    const detail = item.detail || '';
    return `[${ts}] ${kind}${detail ? ' — ' + detail : ''}`;
  }).join('\n');
}

async function loadHistory() {
  const result = await send('arena.getHistory');
  renderHistory(result.items || []);
}

async function testConnection() {
  const box = document.getElementById('statusBox');
  box.textContent = 'Testing bridge...';
  const result = await send('arena.testConnection');
  box.textContent = JSON.stringify(result, null, 2);
}

async function loadPolicies() {
  const box = document.getElementById('statusBox');
  box.textContent = 'Loading policies...';
  const result = await send('arena.policies');
  box.textContent = JSON.stringify(result, null, 2);
}

async function refreshAll() {
  document.getElementById('statusBox').textContent = 'Refreshing...';
  await Promise.all([loadHistory(), testConnection()]);
}

document.getElementById('refreshBtn').addEventListener('click', refreshAll);
document.getElementById('testBtn').addEventListener('click', testConnection);
document.getElementById('policiesBtn').addEventListener('click', loadPolicies);
refreshAll().catch((error) => {
  document.getElementById('statusBox').textContent = String(error);
});
