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
    const site = item.site ? ` @ ${item.site}` : '';
    return `[${ts}] ${kind}${site}${detail ? ' — ' + detail : ''}`;
  }).join('\n');
}

async function loadConfig() {
  const cfg = await send('arena.getConfig');
  document.getElementById('bridgeUrl').value = cfg.bridgeUrl || '';
  document.getElementById('bridgeToken').value = cfg.bridgeToken || '';
  const modes = cfg.modes || {};
  ['autoPreview', 'autoExecuteSafe', 'autoInsertResult', 'autoSubmitResult'].forEach((id) => {
    document.getElementById(id).checked = !!modes[id];
  });
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
    modes: {
      autoPreview: document.getElementById('autoPreview').checked,
      autoExecuteSafe: document.getElementById('autoExecuteSafe').checked,
      autoInsertResult: document.getElementById('autoInsertResult').checked,
      autoSubmitResult: document.getElementById('autoSubmitResult').checked,
    },
  });
  status.textContent = result.ok ? `Saved. Modes: ${arenaModeSummary(result.config?.modes)}` : `Error: ${result.error || 'unknown'}`;
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


async function copyInstructions(format) {
  const status = document.getElementById('statusBox');
  status.textContent = `Loading ${format} instructions...`;
  const result = await send('arena.instructions', {format, style: 'full'});
  if (!result.ok) {
    status.textContent = `Instructions error: ${result.error || 'unknown'}`;
    return;
  }
  await navigator.clipboard.writeText(result.text || '');
  status.textContent = `Copied ${format} instructions (${(result.text || '').length} chars).`;
}

async function openPanel() {
  const status = document.getElementById('statusBox');
  const result = await send('arena.openSidePanel');
  status.textContent = result.ok ? 'Opened side panel.' : `Panel error: ${result.error || 'unknown'}`;
}

async function clearHistory() {
  const status = document.getElementById('statusBox');
  const result = await send('arena.clearHistory');
  status.textContent = result.ok ? 'History cleared.' : `Error: ${result.error || 'unknown'}`;
  await loadHistory();
}

document.getElementById('saveBtn').addEventListener('click', saveConfig);
document.getElementById('testBtn').addEventListener('click', testConnection);
document.getElementById('policyBtn').addEventListener('click', loadPolicies);
document.getElementById('arenaInstructionsBtn').addEventListener('click', () => copyInstructions('arena'));
document.getElementById('jsonlInstructionsBtn').addEventListener('click', () => copyInstructions('jsonl'));
document.getElementById('panelBtn').addEventListener('click', openPanel);
document.getElementById('clearBtn').addEventListener('click', clearHistory);

loadConfig().then(loadHistory).catch((error) => {
  document.getElementById('statusBox').textContent = String(error);
});
