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

function arenaHasComposerChild(node, adapter) {
  return (adapter.composerSelectors || []).some((selector) => {
    try { return !!node.querySelector?.(selector); } catch (_e) { return false; }
  });
}
function arenaDetectionText(node, adapter = getArenaAdapter()) {
  if (!node) return '';
  if (arenaIsComposerNode(node, adapter)) return '';
  if (!arenaHasComposerChild(node, adapter)) return arenaNodeText(node);
  const clone = node.cloneNode(true);
  (adapter.composerSelectors || []).forEach((selector) => {
    try { clone.querySelectorAll(selector).forEach((child) => child.remove()); } catch (_e) {}
  });
  return arenaNodeText(clone);
}

function arenaHasToolBlock(node, adapter = getArenaAdapter()) {
  const text = arenaDetectionText(node, adapter);
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

function arenaMatchesAny(node, selectors) {
  return (selectors || []).some((selector) => {
    try { return node?.matches?.(selector) || !!node?.closest?.(selector); } catch (_e) { return false; }
  });
}

function arenaIsComposerNode(node, adapter = getArenaAdapter()) {
  if (!node) return false;
  if (arenaMatchesAny(node, adapter.composerSelectors)) return true;
  if (node.isContentEditable && !node.closest?.('pre, code, message-content, model-response, article')) return true;
  return false;
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
    if (node.closest?.('[data-testid="user-message"], [data-testid="user-message-content"]')) return false;
    if (arenaNodeText(node).startsWith('You said:')) return false;
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
      if (arenaIsComposerNode(node, adapter)) return;
      if (!arenaHasToolBlock(node, adapter)) return;
      nodes.push(node);
    });
  });
  return {adapter, nodes: arenaPruneAncestorCandidates(nodes).slice(-5)};
}

function arenaSelectorDiagnostics() {
  const adapter = getArenaAdapter();
  return (adapter.messageSelectors || []).map((selector) => {
    let raw = 0, assistant = 0, withBlock = 0;
    try {
      document.querySelectorAll(selector).forEach((rawNode) => {
        const node = arenaCandidateHost(rawNode);
        raw++;
        if (!arenaIsAssistantNode(node, adapter)) return;
        if (arenaIsComposerNode(node, adapter)) return;
        assistant++;
        if (arenaHasToolBlock(node, adapter)) withBlock++;
      });
    } catch (_e) {}
    return {selector, raw, assistant, with_block: withBlock};
  });
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

function arenaFocusComposer(target) {
  if (!target) return;
  const active = document.activeElement;
  if (active === target || target.contains?.(active)) return;
  try { target.focus({preventScroll: true}); } catch (_e) { target.focus(); }
}

function arenaSetInsertTiming(timing) {
  window.__arenaLastInsertTiming = timing;
}
function arenaInsertResult(text, adapter = getArenaAdapter()) {
  const started = performance.now();
  const target = arenaFindComposer(adapter);
  if (!target) return false;
  arenaFocusComposer(target);
  if (target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target.type === 'text')) {
    const value = target.value || '';
    const start = target.selectionStart ?? value.length;
    const end = target.selectionEnd ?? value.length;
    target.value = `${value.slice(0, start)}${text}${value.slice(end)}`;
    target.dispatchEvent(new Event('input', {bubbles: true}));
    target.dispatchEvent(new Event('change', {bubbles: true}));
    arenaSetInsertTiming({insert_ms: Math.round(performance.now() - started), method: 'value'});
    return true;
  }
  if (target.isContentEditable) {
    return arenaInsertIntoEditable(target, text);
  }
  return false;
}

function arenaComposerText(adapter = getArenaAdapter()) {
  const target = arenaFindComposer(adapter);
  if (!target) return '';
  return (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') ? (target.value || '') : (target.textContent || '');
}

function arenaInsertIntoEditable(target, text) {
  const started = performance.now();
  arenaFocusComposer(target);
  // Single deterministic path: native insertText with embedded newlines.
  // Native insertText already fires composer input events; dispatching a second
  // synthetic InputEvent made Gemini rich-textarea re-process the same update.
  let ok = false;
  try { ok = document.execCommand('insertText', false, String(text)); } catch (_e) { ok = false; }
  if (!ok) {
    String(text).split('\n').forEach((line, index) => {
      if (index) document.execCommand('insertParagraph');
      if (line) document.execCommand('insertText', false, line);
    });
  }
  arenaSetInsertTiming({insert_ms: Math.round(performance.now() - started), method: ok ? 'insertText' : 'paragraphFallback'});
  return true;
}

async function arenaInsertAndSubmit(text, adapter = getArenaAdapter()) {
  const started = performance.now();
  const inserted = arenaInsertResult(text, adapter);
  if (!inserted) return {ok: false, inserted: false, submitted: false};
  const insertTiming = window.__arenaLastInsertTiming || {};
  const deadline = Date.now() + 1500;
  while (Date.now() < deadline) {
    const submit = arenaFindSubmitButton(adapter);
    if (submit && !submit.disabled && submit.getAttribute('aria-disabled') !== 'true') {
      submit.click();
      return {ok: true, inserted: true, submitted: true, ...insertTiming, total_ms: Math.round(performance.now() - started)};
    }
    await new Promise((resolve) => setTimeout(resolve, 40));
  }
  return {ok: true, inserted: true, submitted: false, ...insertTiming, total_ms: Math.round(performance.now() - started)};
}
