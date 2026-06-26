const ARENA_ADAPTERS = (typeof ARENA_SITE_ADAPTERS !== 'undefined' ? ARENA_SITE_ADAPTERS : []);

function arenaHost() {
  return (location.hostname || '').toLowerCase();
}

function getArenaAdapter() {
  const host = arenaHost();
  return ARENA_ADAPTERS.find((adapter) => adapter.hosts.includes(host)) || ARENA_ADAPTERS[ARENA_ADAPTERS.length - 1];
}

function arenaNodeText(node) {
  return String(node?.innerText || node?.textContent || '').trim();
}

function arenaHasToolBlock(node) {
  const text = arenaNodeText(node);
  return /```arena-tool\s*[\s\S]*?```/m.test(text)
    || /```jsonl\s*[\s\S]*?function_call_start[\s\S]*?function_call_end[\s\S]*?```/m.test(text)
    || /```json\s*[\s\S]*?function_call_start[\s\S]*?function_call_end[\s\S]*?```/m.test(text)
    || (text.includes('function_call_start') && text.includes('function_call_end'));
}

function arenaHasArenaToolBlock(node) {
  return arenaHasToolBlock(node);
}

function arenaNodePath(node) {
  const parts = [];
  let cur = node;
  for (let depth = 0; cur && depth < 6; depth++) {
    const parent = cur.parentElement;
    const siblings = parent ? Array.from(parent.children).filter((child) => child.tagName === cur.tagName) : [];
    const idx = siblings.indexOf(cur);
    parts.unshift(`${cur.tagName || 'NODE'}:${idx}`);
    cur = parent;
  }
  return parts.join('/');
}

function arenaCandidateHost(node) {
  if (!node) return node;
  if (node.tagName === 'CODE') return node.closest('pre') || node;
  return node;
}

function arenaPruneAncestorCandidates(nodes) {
  return nodes.filter((node) => !nodes.some((other) => other !== node && node.contains(other)));
}

function arenaExtractNodeId(node, adapter = getArenaAdapter()) {
  if (!node) return '';
  return [
    adapter.name,
    node.getAttribute?.('data-testid') || '',
    node.getAttribute?.('data-message-author-role') || '',
    node.id || '',
    arenaNodePath(node),
    arenaNodeText(node).slice(0, 80),
  ].join('|');
}

function arenaIsAssistantNode(node, adapter = getArenaAdapter()) {
  if (!node) return false;
  if (adapter.name === 'chatgpt') {
    if (node.getAttribute('data-message-author-role') === 'assistant') return true;
    return !!node.closest('[data-message-author-role="assistant"]');
  }
  if (adapter.name === 'claude') {
    if (node.isContentEditable) return false;
    if (node.querySelector?.('[contenteditable="true"]')) return false;
    return true;
  }
  return true;
}

function arenaMessageFingerprint(node, payload, adapter = getArenaAdapter()) {
  const base = [
    adapter.name,
    arenaExtractNodeId(node, adapter),
    JSON.stringify(payload || {}),
  ].join('|');
  let h = 0;
  for (let i = 0; i < base.length; i++) h = ((h << 5) - h + base.charCodeAt(i)) | 0;
  return `arena_msg_${Math.abs(h)}`;
}

function arenaCandidateNodes() {
  const adapter = getArenaAdapter();
  const seen = new Set();
  const nodes = [];
  adapter.messageSelectors.forEach((selector) => {
    document.querySelectorAll(selector).forEach((rawNode) => {
      const node = arenaCandidateHost(rawNode);
      if (seen.has(node)) return;
      seen.add(node);
      if (!arenaIsAssistantNode(node, adapter)) return;
      if (!arenaHasToolBlock(node)) return;
      nodes.push(node);
    });
  });
  return {adapter, nodes: arenaPruneAncestorCandidates(nodes).slice(-5)};
}

function arenaLatestCandidateNodes() {
  const state = arenaCandidateNodes();
  return {adapter: state.adapter, nodes: state.nodes.slice(-2)};
}

function arenaFindComposer(adapter = getArenaAdapter()) {
  for (const selector of adapter.composerSelectors || []) {
    const node = document.querySelector(selector);
    if (node) return node;
  }
  return null;
}

function arenaFindSubmitButton(adapter = getArenaAdapter()) {
  for (const selector of adapter.submitSelectors || []) {
    const node = document.querySelector(selector);
    if (!node) continue;
    if (node.tagName === 'BUTTON') return node;
    const button = node.closest('button');
    if (button) return button;
  }
  return null;
}

function arenaInsertResult(text, adapter = getArenaAdapter()) {
  const target = arenaFindComposer(adapter);
  if (!target) return false;
  target.focus();
  if (target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target.type === 'text')) {
    const value = target.value || '';
    const start = target.selectionStart ?? value.length;
    const end = target.selectionEnd ?? value.length;
    target.value = `${value.slice(0, start)}${text}${value.slice(end)}`;
    target.dispatchEvent(new Event('input', {bubbles: true}));
    target.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  }
  if (target.isContentEditable) {
    const current = target.textContent || '';
    target.textContent = `${current}${text}`;
    target.dispatchEvent(new InputEvent('input', {bubbles: true, data: text, inputType: 'insertText'}));
    return true;
  }
  return false;
}

async function arenaInsertAndSubmit(text, adapter = getArenaAdapter()) {
  const inserted = arenaInsertResult(text, adapter);
  if (!inserted) return {ok: false, inserted: false, submitted: false};
  for (let i = 0; i < 10; i++) {
    await new Promise((resolve) => setTimeout(resolve, i ? 120 : 250));
    const submit = arenaFindSubmitButton(adapter);
    if (submit && !submit.disabled && submit.getAttribute('aria-disabled') !== 'true') {
      submit.click();
      return {ok: true, inserted: true, submitted: true};
    }
  }
  return {ok: true, inserted: true, submitted: false};
}
