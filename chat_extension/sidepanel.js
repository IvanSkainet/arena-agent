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
  if (item.kind === 'scan') return item.response?.ok === false ? 'scan error' : 'scanned';
  return item.kind || 'event';
}
function scanDiagnostics(item) {
  if (item.kind !== 'scan' || !item.response) return [];
  const res = item.response || {};
  const parts = [];
  if (Number.isFinite(res.candidate_nodes)) parts.push(`${res.candidate_nodes} candidates`);
  if (Number.isFinite(res.parsed_blocks)) parts.push(`${res.parsed_blocks} blocks`);
  if (Number.isFinite(res.mounted_controls)) parts.push(`${res.mounted_controls} controls`);
  const composer = res.composer || {};
  if (composer.found) {
    const editor = composer.rich_textarea ? 'rich-textarea' : (composer.prose_mirror ? 'ProseMirror' : (composer.contenteditable ? 'contenteditable' : composer.tag));
    if (editor) parts.push(`composer: ${editor}`);
    if (Array.isArray(composer.auto_plan) && composer.auto_plan.length) parts.push(`auto: ${composer.auto_plan.join(' → ')}`);
  } else if (composer && composer.found === false) {
    parts.push('composer: not found');
  }
  return parts;
}
function versionDiagnostics(item) {
  const res = item.response || {};
  return [
    res.manifest_version ? `manifest ${res.manifest_version}` : '',
    res.content_version ? `content ${res.content_version}` : '',
    res.insert_script_version ? `insert ${res.insert_script_version}` : '',
  ].filter(Boolean);
}
function fingerprintDiagnostics(item) {
  const fp = item.payload_fingerprint || item.fingerprint;
  return fp ? [`fp ${String(fp).slice(0, 18)}`] : [];
}
function cardMetaParts(item) {
  const tools = itemTools(item).join(', ');
  return [
    item.adapter || '',
    shortUrl(item.site),
    tools ? `tools: ${tools}` : '',
    ...scanDiagnostics(item),
    ...versionDiagnostics(item),
    ...fingerprintDiagnostics(item),
  ].filter(Boolean);
}
function commandKey(item) {
  if (!item || item.kind === 'scan') return '';
  const payloadCalls = item.payload?.payload?.calls || item.payload?.calls || [];
  const payloadSig = payloadCalls.length ? JSON.stringify(payloadCalls.map((call) => ({tool: call.tool || call.name || '', id: call.id || call.call_id || ''}))) : '';
  return item.fingerprint || item.payload_fingerprint || payloadSig || '';
}
function lifecycleLabel(kind) {
  if (kind === 'detected') return 'detected';
  if (kind === 'preview') return 'previewed';
  if (kind === 'execute') return 'executed';
  return kind || 'event';
}
function lifecycleSummary(events) {
  const order = ['detected', 'preview', 'execute'];
  const seen = new Map();
  (events || []).forEach((event) => {
    if (!seen.has(event.kind)) seen.set(event.kind, event);
  });
  return order.filter((kind) => seen.has(kind)).map((kind) => lifecycleLabel(kind)).join(' → ');
}
function groupCommandHistory(items) {
  const groups = new Map();
  const output = [];
  (items || []).forEach((item) => {
    const key = commandKey(item);
    if (!key) { output.push(item); return; }
    let group = groups.get(key);
    if (!group) {
      group = {...item, group_key: key, events: [], lifecycle: '', event_count: 0};
      groups.set(key, group);
      output.push(group);
    }
    group.events.push(item);
    group.event_count = group.events.length;
    group.lifecycle = lifecycleSummary(group.events);
    if ((Date.parse(item.at || 0) || 0) >= (Date.parse(group.at || 0) || 0)) {
      Object.assign(group, {...item, group_key: key, events: group.events, lifecycle: group.lifecycle, event_count: group.event_count});
    }
  });
  return output;
}
function historyActionIndex(item, fallbackIndex) {
  return Number.isInteger(item?.history_index) ? item.history_index : fallbackIndex;
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
  left.appendChild(badge(item.group_key ? 'command' : (item.kind || 'event'), item.ok === false ? 'error' : 'kind'));
  left.appendChild(badge(itemStatus(item), item.ok === false ? 'error' : 'ok'));
  if (item.lifecycle) left.appendChild(badge(item.lifecycle, 'flow'));
  if (item.event_count > 1) left.appendChild(badge(`${item.event_count} events`, 'count'));
  if (item.count) left.appendChild(badge(`×${item.count}`, 'count'));
  const right = document.createElement('div');
  right.className = 'arena-card-time';
  right.textContent = item.at || '';
  header.appendChild(left); header.appendChild(right); row.appendChild(header);
}
function renderHistory(items) {
  const box = document.getElementById('historyBox');
  box.innerHTML = '';
  const visible = document.getElementById('kindFilter').value ? (items || []) : groupCommandHistory(items || []);
  if (!visible.length) { box.textContent = 'No history yet.'; return; }
  visible.forEach((item, index) => {
    const row = document.createElement('div');
    row.className = 'arena-history-card';
    renderCardHeader(row, item);
    const title = document.createElement('div');
    title.className = 'arena-card-title';
    title.textContent = item.group_key ? (item.detail || 'command lifecycle') : (item.detail || '(no detail)');
    row.appendChild(title);
    const meta = document.createElement('div');
    meta.className = 'arena-card-meta';
    meta.textContent = cardMetaParts(item).join(' · ');
    row.appendChild(meta);
    const actions = document.createElement('div');
    actions.className = 'arena-card-actions';
    actions.appendChild(makeActionButton('Inspect Payload', () => renderPayload(item)));
    actions.appendChild(makeActionButton('Inspect Result', () => renderResult(item)));
    if (item.payload && (item.kind === 'preview' || item.kind === 'execute' || item.kind === 'detected')) {
      const actionIndex = historyActionIndex(item, index);
      actions.appendChild(makeActionButton('Replay Preview', () => runHistoryAction(actionIndex, 'preview')));
      actions.appendChild(makeActionButton('Replay Execute', () => runHistoryAction(actionIndex, 'execute')));
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
