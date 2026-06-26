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

async function loadConfig() {
  const cfg = await send('arena.getConfig');
  document.getElementById('bridgeUrl').value = cfg.bridgeUrl || '';
  document.getElementById('bridgeToken').value = cfg.bridgeToken || '';
}

async function loadHistory() {
  const result = await send('arena.getHistory');
  renderHistory(result.items || []);
}

async function saveConfig() {
  const status = document.getElementById('statusBox');
  status.textContent = 'Saving...';
  const result = await send('arena.saveConfig', {
    bridgeUrl: document.getElementById('bridgeUrl').value.trim(),
    bridgeToken: document.getElementById('bridgeToken').value.trim(),
  });
  status.textContent = result.ok ? 'Saved.' : `Error: ${result.error || 'unknown'}`;
}

async function testConnection() {
  const status = document.getElementById('statusBox');
  status.textContent = 'Testing bridge...';
  const result = await send('arena.testConnection');
  status.textContent = JSON.stringify(result, null, 2);
}

async function loadPolicies() {
  const status = document.getElementById('statusBox');
  status.textContent = 'Loading policies...';
  const result = await send('arena.policies');
  status.textContent = JSON.stringify(result, null, 2);
}

document.getElementById('saveBtn').addEventListener('click', saveConfig);
document.getElementById('testBtn').addEventListener('click', testConnection);
document.getElementById('policyBtn').addEventListener('click', loadPolicies);

loadConfig().then(loadHistory).catch((error) => {
  document.getElementById('statusBox').textContent = String(error);
});
