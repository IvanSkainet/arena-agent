function send(type, body) {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage({type, body}, (response) => {
        const err = chrome.runtime.lastError;
        if (err) return resolve({ok: false, error: err.message || String(err)});
        resolve(response || {ok: false, error: 'empty background response'});
      });
    } catch (error) {
      resolve({ok: false, error: String(error)});
    }
  });
}

function statusText(text) {
  document.getElementById('statusBox').textContent = text;
}

function statusJson(data) {
  document.getElementById('statusBox').textContent = JSON.stringify(data, null, 2);
}

function currentModes() {
  return {
    autoPreview: document.getElementById('autoPreview').checked,
    autoExecuteSafe: document.getElementById('autoExecuteSafe').checked,
    autoInsertResult: document.getElementById('autoInsertResult').checked,
    autoSubmitResult: document.getElementById('autoSubmitResult').checked,
  };
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
  if (!cfg || cfg.ok === false) {
    statusText(`Config load error: ${cfg?.error || 'unknown'}`);
    return false;
  }
  document.getElementById('bridgeUrl').value = cfg.bridgeUrl || '';
  document.getElementById('bridgeToken').value = cfg.bridgeToken || '';
  const modes = cfg.modes || {};
  ['autoPreview', 'autoExecuteSafe', 'autoInsertResult', 'autoSubmitResult'].forEach((id) => {
    document.getElementById(id).checked = !!modes[id];
  });
  statusText(`Loaded config. Modes: ${arenaModeSummary(modes)}`);
  return true;
}

async function loadHistory() {
  const result = await send('arena.getHistory');
  if (!result || result.ok === false) {
    renderHistory([]);
    statusText(`History load error: ${result?.error || 'unknown'}`);
    return false;
  }
  renderHistory(result.items || []);
  return true;
}

async function notifyActiveTab(message) {
  try {
    const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
    if (tab?.id) chrome.tabs.sendMessage(tab.id, message, () => void chrome.runtime.lastError);
  } catch {}
}

async function saveConfig() {
  statusText('Saving...');
  const payload = {
    bridgeUrl: document.getElementById('bridgeUrl').value.trim(),
    bridgeToken: document.getElementById('bridgeToken').value.trim(),
    modes: currentModes(),
  };
  const result = await send('arena.saveConfig', payload);
  if (!result?.ok) {
    statusText(`Save error: ${result?.error || 'unknown'}`);
    return;
  }
  const verify = await send('arena.getConfig');
  if (!verify || verify.ok === false) {
    statusText(`Saved, but verify failed: ${verify?.error || 'unknown'}`);
    return;
  }
  document.getElementById('bridgeUrl').value = verify.bridgeUrl || '';
  document.getElementById('bridgeToken').value = verify.bridgeToken || '';
  statusText(`Saved. Modes: ${arenaModeSummary(verify.modes)}`);
  await notifyActiveTab({type: 'arena.controlsModeChanged'});
}

async function testConnection() {
  statusText('Testing bridge...');
  const result = await send('arena.testConnection');
  statusJson(result);
}

async function loadPolicies() {
  statusText('Loading policies...');
  const result = await send('arena.policies');
  statusJson(result);
}

async function copyInstructions(format) {
  statusText(`Loading ${format} instructions...`);
  const result = await send('arena.instructions', {format, style: 'full'});
  if (!result.ok) {
    statusText(`Instructions error: ${result.error || 'unknown'}`);
    return;
  }
  await navigator.clipboard.writeText(result.text || '');
  statusText(`Copied ${format} instructions (${(result.text || '').length} chars).`);
}


async function scanPage() {
  statusText('Scanning active page...');
  const result = await send('arena.scanPage');
  statusJson(result);
  await loadHistory();
}

async function openPanel() {
  const result = await send('arena.openSidePanel');
  statusText(result.ok ? 'Opened side panel.' : `Panel error: ${result.error || 'unknown'}`);
}


async function clearPageControls() {
  await notifyActiveTab({type: 'arena.clearPageControls'});
  statusText('Page controls cleared. New tool blocks will be detected again.');
}

async function clearHistory() {
  const result = await send('arena.clearHistory');
  statusText(result.ok ? 'History cleared.' : `Error: ${result.error || 'unknown'}`);
  await loadHistory();
}

document.getElementById('saveBtn').addEventListener('click', saveConfig);
document.getElementById('testBtn').addEventListener('click', testConnection);
document.getElementById('policyBtn').addEventListener('click', loadPolicies);
document.getElementById('arenaInstructionsBtn').addEventListener('click', () => copyInstructions('arena'));
document.getElementById('jsonlInstructionsBtn').addEventListener('click', () => copyInstructions('jsonl'));
document.getElementById('panelBtn').addEventListener('click', openPanel);
document.getElementById('scanBtn').addEventListener('click', scanPage);
document.getElementById('pageControlsBtn').addEventListener('click', clearPageControls);
document.getElementById('clearBtn').addEventListener('click', clearHistory);

(async () => {
  statusText('Loading config...');
  const ok = await loadConfig();
  if (ok) await loadHistory();
})().catch((error) => {
  statusText(`Popup error: ${String(error)}`);
});
