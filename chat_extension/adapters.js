const ARENA_ADAPTERS = (typeof ARENA_SITE_ADAPTERS !== 'undefined' ? ARENA_SITE_ADAPTERS : []);

function arenaHost() {
  return (location.hostname || '').toLowerCase();
}

let _cachedAdapter = null;
function getArenaAdapter() {
  if (_cachedAdapter) return _cachedAdapter;
  _cachedAdapter = ARENA_ADAPTERS.find((a) => a.hosts.includes(arenaHost())) || ARENA_ADAPTERS[ARENA_ADAPTERS.length - 1];
  return _cachedAdapter;
}

function arenaNodeText(node) {
  return String(node?.innerText || node?.textContent || '').trim();
}

function arenaHasComposerChild(node, adapter) {
  return (adapter.composerSelectors || []).some((s) => { try { return !!node.querySelector?.(s); } catch (_e) { return false; } });
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

const ARENA_TOOL_RE = /```(?:arena-tool|jsonl?)[\s\S]*?(?:function_call_start|arena_tool)[\s\S]*?```/m;
function arenaHasToolBlock(node, adapter = getArenaAdapter()) {
  const text = arenaDetectionText(node, adapter);
  return ARENA_TOOL_RE.test(text) || (text.includes('function_call_start') && text.includes('function_call_end'));
}

function arenaHasArenaToolBlock(node) {
  return arenaHasToolBlock(node);
}

function arenaNodePath(node) {
  const parts = []; let cur = node;
  for (let d = 0; cur && d < 6; d++) { const p = cur.parentElement; const s = p ? Array.from(p.children).filter((c) => c.tagName === cur.tagName) : []; parts.unshift(`${cur.tagName || 'NODE'}:${s.indexOf(cur)}`); cur = p; }
  return parts.join('/');
}

function arenaMatchesAny(node, selectors) {
  return (selectors || []).some((s) => { try { return node?.matches?.(s) || !!node?.closest?.(s); } catch (_e) { return false; } });
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
  return [adapter.name, node.getAttribute?.('data-testid') || '', node.getAttribute?.('data-message-author-role') || '', node.id || '', arenaNodePath(node), arenaNodeText(node).slice(0, 80)].join('|');
}

function arenaIsAssistantNode(node, adapter = getArenaAdapter()) {
  if (!node) return false;
  if (adapter.name === 'chatgpt') return node.getAttribute('data-message-author-role') === 'assistant' || !!node.closest('[data-message-author-role="assistant"]');
  if (adapter.name === 'claude') return !node.isContentEditable && !node.querySelector?.('[contenteditable="true"]') && !node.closest?.('[data-testid="user-message"], [data-testid="user-message-content"]') && !arenaNodeText(node).startsWith('You said:');
  return true;
}

function arenaStableHash(text, prefix = 'arena') {
  let h = 0;
  for (let i = 0; i < String(text || '').length; i++) h = ((h << 5) - h + String(text).charCodeAt(i)) | 0;
  return `${prefix}_${Math.abs(h)}`;
}
function arenaPayloadFingerprint(payload, adapter = getArenaAdapter()) {
  return arenaStableHash(JSON.stringify({adapter: adapter.name, calls: Array.isArray(payload?.calls) ? payload.calls.map((call) => ({id: call.id || '', tool: call.tool || '', arguments: call.arguments || {}})) : []}), 'arena_payload');
}
function arenaPayloadSemanticFingerprint(payload, adapter = getArenaAdapter()) {
  return arenaStableHash(JSON.stringify({adapter: adapter.name, calls: Array.isArray(payload?.calls) ? payload.calls.map((call) => ({tool: call.tool || '', arguments: call.arguments || {}})) : []}), 'arena_payload_sem');
}
function arenaMessageFingerprint(node, payload, adapter = getArenaAdapter()) {
  return arenaStableHash([adapter.name, arenaExtractNodeId(node, adapter), JSON.stringify(payload || {})].join('|'), 'arena_msg');
}

let _cachedCandidateState = null;
let _candidateCacheDirty = true;
function arenaInvalidateCandidateCache() { _candidateCacheDirty = true; }
function arenaCandidateNodes() {
  if (!_candidateCacheDirty && _cachedCandidateState) return _cachedCandidateState;
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
  _cachedCandidateState = {adapter, nodes: arenaPruneAncestorCandidates(nodes).slice(-5)};
  _candidateCacheDirty = false;
  return _cachedCandidateState;
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

function arenaElementVisible(node) {
  if (!node?.isConnected) return false;
  const style = window.getComputedStyle?.(node);
  if (!style || style.display === 'none' || style.visibility === 'hidden') return false;
  const rect = node.getBoundingClientRect?.();
  return !!rect && rect.width > 0 && rect.height > 0;
}

function arenaResolveComposerNode(node, adapter = getArenaAdapter()) {
  if (!node) return null;
  if (arenaMatchesAny(node, adapter.composerSelectors)) return node;
  for (const selector of adapter.composerSelectors || []) {
    try {
      const match = node.closest?.(selector);
      if (match) return match;
    } catch (_e) {}
  }
  if (node.isContentEditable && !node.closest?.('pre, code')) return node;
  return null;
}

function arenaComposerCandidates(adapter = getArenaAdapter()) {
  const seen = new Set();
  const candidates = [];
  const push = (node, selector = '') => {
    const target = arenaResolveComposerNode(node, adapter);
    if (!target || seen.has(target)) return;
    seen.add(target);
    candidates.push({node: target, selector});
  };
  push(document.activeElement, 'activeElement');
  push(window.__arenaLastComposerTarget, 'cachedComposer');
  for (const selector of adapter.composerSelectors || []) {
    try { document.querySelectorAll(selector).forEach((node) => push(node, selector)); } catch (_e) {}
  }
  return candidates;
}

function arenaScoreComposerCandidate(node, active = document.activeElement) {
  let score = 0;
  if (node === active || node.contains?.(active)) score += 100;
  if (node === window.__arenaLastComposerTarget) score += 35;
  if (arenaElementVisible(node)) score += 20;
  if (node.closest?.('form')) score += 5;
  return score;
}

function arenaComposerSelection(adapter = getArenaAdapter()) {
  const cached = window.__arenaLastComposerTarget;
  const ranked = arenaComposerCandidates(adapter)
    .map((item) => ({...item, score: arenaScoreComposerCandidate(item.node)}))
    .sort((a, b) => b.score - a.score);
  const selected = ranked[0] || null;
  if (selected?.node) window.__arenaLastComposerTarget = selected.node;
  return {
    target: selected?.node || null,
    candidates: ranked.length,
    selected_selector: selected?.selector || '',
    active_match: !!selected?.node && (selected.node === document.activeElement || selected.node.contains?.(document.activeElement)),
    cached_match: !!selected?.node && selected.node === cached,
  };
}

function arenaFindComposer(adapter = getArenaAdapter()) {
  return arenaComposerSelection(adapter).target;
}

function arenaButtonFromNode(node) {
  if (!node) return null;
  return node.tagName === 'BUTTON' ? node : (node.closest?.('button') || null);
}

function arenaSubmitCandidates(adapter = getArenaAdapter()) {
  const seen = new Set();
  const candidates = [];
  for (const selector of adapter.submitSelectors || []) {
    try {
      document.querySelectorAll(selector).forEach((node) => {
        const button = arenaButtonFromNode(node);
        if (!button || seen.has(button)) return;
        seen.add(button);
        candidates.push({button, selector});
      });
    } catch (_e) {}
  }
  return candidates;
}

function arenaDistanceBetweenRects(a, b) {
  const ax = a.left + (a.width / 2), ay = a.top + (a.height / 2);
  const bx = b.left + (b.width / 2), by = b.top + (b.height / 2);
  return Math.hypot(ax - bx, ay - by);
}

function arenaSubmitButtonSelection(adapter = getArenaAdapter(), composer = arenaFindComposer(adapter)) {
  const formRoot = composer?.closest?.('form');
  const fieldsetRoot = composer?.closest?.('fieldset');
  const scopeRoot = formRoot || fieldsetRoot || composer?.closest?.('[role="form"], main, section, article, [role="dialog"]');
  const composerRect = composer?.getBoundingClientRect?.();
  const scopeButtons = Array.from((scopeRoot || document).querySelectorAll?.('button') || []);
  const ranked = arenaSubmitCandidates(adapter)
    .map((item) => {
      let score = 0;
      if (arenaElementVisible(item.button)) score += 30;
      if (item.button.disabled || item.button.getAttribute('aria-disabled') === 'true') score -= 50;
      if (formRoot && formRoot.contains(item.button)) score += 60;
      else if (fieldsetRoot && fieldsetRoot.contains(item.button)) score += 40;
      else if (scopeRoot && scopeRoot.contains(item.button)) score += 20;
      if (composerRect && arenaElementVisible(item.button)) {
        const distance = arenaDistanceBetweenRects(composerRect, item.button.getBoundingClientRect());
        score += Math.max(0, 25 - Math.min(25, distance / 40));
      }
      return {...item, score};
    })
    .sort((a, b) => b.score - a.score);
  const selected = ranked[0] || null;
  return {
    button: selected?.button || null,
    candidates: ranked.length,
    selected_selector: selected?.selector || '',
    scope: formRoot ? 'form' : (fieldsetRoot ? 'fieldset' : (scopeRoot ? 'container' : 'global')),
    scope_buttons: scopeButtons.length,
    visible_scope_buttons: scopeButtons.filter((button) => arenaElementVisible(button)).length,
  };
}

function arenaFindSubmitButton(adapter = getArenaAdapter(), composer = null) {
  return arenaSubmitButtonSelection(adapter, composer || arenaFindComposer(adapter)).button;
}

function arenaFocusComposer(target) {
  if (!target) return;
  window.__arenaLastComposerTarget = target;
  const active = document.activeElement;
  if (active === target || target.contains?.(active)) return;
  try { target.focus({preventScroll: true}); } catch (_e) { target.focus(); }
}
