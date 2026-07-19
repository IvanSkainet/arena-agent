const ARENA_ADAPTERS = (typeof ARENA_SITE_ADAPTERS !== 'undefined' ? ARENA_SITE_ADAPTERS : []);

function arenaHost() {
  return (location.hostname || '').toLowerCase();
}

function arenaPath() {
  return (location.pathname || '').toLowerCase();
}

// ---------------------------------------------------------------------------
// Adapter selection (memoised: hostname does not change within a page).
// v0.14.2 adds an optional adapter.pathPrefix field. When set, the adapter
// only matches URLs whose pathname begins with that prefix. Without this
// the copilot adapter (hosts:['github.com']) fired on every github.com
// page and turned ordinary README code fences that quote MCP JSONL (like
// srbhptl39/MCP-SuperAssistant's own landing page) into false-positive
// tool-call detections. Adapters without pathPrefix behave as before.
// ---------------------------------------------------------------------------
let _cachedAdapter = null;

function getArenaAdapter() {
  if (_cachedAdapter) return _cachedAdapter;
  const host = arenaHost();
  const path = arenaPath();
  _cachedAdapter = ARENA_ADAPTERS.find((a) => {
    if (!a.hosts.includes(host)) return false;
    if (a.pathPrefix && !path.startsWith(String(a.pathPrefix).toLowerCase())) return false;
    return true;
  }) || ARENA_ADAPTERS[ARENA_ADAPTERS.length - 1];
  return _cachedAdapter;
}

// v0.14.4: user-authored node filter -- pared back after v0.14.2/3
// caused massive false-positive SKIPS on Grok / DuckAI where every
// chat block sits under a form/composer ancestor (see scan-report
// mounted_controls=0, dismissed_controls=2 with skip_user_authored
// events). We now only trust explicit user-role attributes and a
// very narrow class-substring set. Composer / form / textarea
// ancestor heuristics are gone -- they were too broad.
// v0.14.6: data-testid="user-message" removed after scan-reports on
// Grok / DuckAI / Arena.ai showed the sites use that testid on the
// message-list container (parent of BOTH user and assistant blocks),
// not just on user messages. That single attribute short-circuited
// every mount. The remaining four attributes are role-explicit and
// only ever appear on the actual user turn in every scanned site.
const _USER_AUTHOR_ATTRS = [
  ['data-message-author-role', 'user'],
  ['data-author-role', 'user'],
  ['data-role', 'user'],
  ['data-sender', 'user'],
];
const _USER_AUTHOR_CLASS_SUBSTRINGS = [
  'user-message', 'human-message', 'usermessage', 'humanmessage',
  'user-turn', 'user_turn',
];

// v0.14.5: return {matched: bool, reason: string} instead of bare bool
// so the caller can log WHY a block was skipped -- Grok / DuckAI still
// report skip_user_authored in scan-reports after the v0.14.4 narrowing,
// and without knowing which attr / class hit we cannot fix it without
// another guessing round. The bool-returning wrapper below preserves
// the existing call site.
//
// Matching is STRICT-equal for attributes (a container tag with class
// "user-name" or role="userlist" was matching includes('user') even
// though it had nothing to do with an authored user message). Class
// substrings stay case-insensitive substring match because the class
// tokens we look for (`user-message`, `human-message`, ...) are
// distinctive enough to be safe.
function arenaWhyUserAuthored(node, adapter) {
  if (!node) return {matched: false, reason: ''};
  // v0.14.8: per-adapter user marker for Grok. Scan-report shows
  // Grok wraps user turns in <div data-testid="user-message"
  // class="message-bubble"> and AI turns in <div
  // data-testid="assistant-message" class="message-bubble">.
  // Both share the same code-block child so global _USER_AUTHOR_ATTRS
  // (which was reverted in v0.14.6 because DuckAI puts the same
  // testid on the message-list container) cannot distinguish them.
  // Solving it per-adapter keeps DuckAI happy while unblocking Grok.
  const adapterName = adapter && adapter.name;
  // v0.14.9: per-adapter user-message check for Grok AND DuckAI.
  // Both sites tag user-turns with data-testid="user-message" on
  // the ACTUAL turn element (not the message-list container -- our
  // v4.48.6 interpretation was based on an older DuckAI DOM shape;
  // v4.49.0/1 candidate_diagnostics proved the testid lives on the
  // real user turn today). Keep it per-adapter so we don't ship a
  // global rule that any future site might regress on.
  if ((adapterName === 'grok' || adapterName === 'duckai') && node.closest) {
    const bubble = node.closest('[data-testid="user-message"]');
    if (bubble) return {matched: true, reason: `${adapterName}:user-message@DIV`};
  }
  // v0.14.13: t3chat has no data-testid on turns but marks the AI's
  // .prose container with role="article". Absence of that role AND
  // presence of a .prose ancestor is the User-turn signal.
  if (adapterName === 't3chat' && node.closest) {
    const prose = node.closest('.prose');
    if (prose && prose.getAttribute('role') !== 'article') {
      return {matched: true, reason: 't3chat:user-prose@DIV'};
    }
  }
  let el = node;
  for (let i = 0; el && i < 8; i++) {   // cap tightened 20 -> 8
    if (el.nodeType !== 1) { el = el.parentNode; continue; }
    for (const [attr, val] of _USER_AUTHOR_ATTRS) {
      const v = el.getAttribute && el.getAttribute(attr);
      if (!v) continue;
      const lv = String(v).toLowerCase();
      // Strict equal or space-separated token equal ("user assistant" -> tokens).
      if (lv === val) return {matched: true, reason: `attr:${attr}=${val}@${el.tagName}`};
      if (lv.split(/\s+/).indexOf(val) !== -1) return {matched: true, reason: `attr:${attr}~${val}@${el.tagName}`};
    }
    const cls = el.className;
    if (cls && typeof cls === 'string') {
      const lc = cls.toLowerCase();
      for (const needle of _USER_AUTHOR_CLASS_SUBSTRINGS) {
        if (lc.includes(needle)) return {matched: true, reason: `class:${needle}@${el.tagName}`};
      }
    }
    el = el.parentNode;
  }
  return {matched: false, reason: ''};
}

function arenaIsInUserAuthoredNode(node, adapter) {
  return arenaWhyUserAuthored(node, adapter).matched;
}

// ---------------------------------------------------------------------------
// Text extraction
// ---------------------------------------------------------------------------
function arenaNodeText(node) {
  return String(node?.innerText || node?.textContent || '').trim();
}

function arenaHasComposerChild(node, adapter) {
  return (adapter.composerSelectors || []).some((s) => {
    try {
      return !!node.querySelector?.(s);
    } catch (_e) {
      return false;
    }
  });
}

function arenaDetectionText(node, adapter = getArenaAdapter()) {
  if (!node) return '';
  if (arenaIsComposerNode(node, adapter)) return '';
  if (!arenaHasComposerChild(node, adapter)) return arenaNodeText(node);

  // Composer widgets can nest inside a message node (e.g. quoted replies).
  // Clone the node and strip composers before extracting text.
  const clone = node.cloneNode(true);
  (adapter.composerSelectors || []).forEach((selector) => {
    try {
      clone.querySelectorAll(selector).forEach((child) => child.remove());
    } catch (_e) { /* invalid selector — ignore */ }
  });
  return arenaNodeText(clone);
}

// ---------------------------------------------------------------------------
// Arena tool-block detection
// ---------------------------------------------------------------------------
const ARENA_TOOL_RE = /```(?:arena-tool|jsonl?)[\s\S]*?(?:function_call_start|arena_tool)[\s\S]*?```/m;

function arenaHasToolBlock(node, adapter = getArenaAdapter()) {
  const text = arenaDetectionText(node, adapter);
  if (ARENA_TOOL_RE.test(text)) return true;
  return text.includes('function_call_start') && text.includes('function_call_end');
}

function arenaHasArenaToolBlock(node) {
  return arenaHasToolBlock(node);
}

// ---------------------------------------------------------------------------
// Node path (for fingerprinting)
// ---------------------------------------------------------------------------
function arenaNodePath(node) {
  const parts = [];
  let cur = node;
  for (let depth = 0; cur && depth < 6; depth++) {
    const parent = cur.parentElement;
    const siblings = parent
      ? Array.from(parent.children).filter((c) => c.tagName === cur.tagName)
      : [];
    parts.unshift(`${cur.tagName || 'NODE'}:${siblings.indexOf(cur)}`);
    cur = parent;
  }
  return parts.join('/');
}

// v0.14.7: rich DOM snapshot for scan-report diagnostics. Additive
// only -- never called by mount/skip logic. The goal is to give the
// operator enough context to see WHY a toolbar landed where it did
// (or didn't) without having to open devtools. Produces:
//   * path -- 6-deep tag:index chain from arenaNodePath
//   * ancestors -- up to 4 ancestors with tag + testid + role +
//     data-message-author-role + top 2 class-tokens
//   * self -- tag + id + testid + role + author-role + class tokens
// Deliberately bounded so scan-report stays small.
function arenaDiagnosticSnapshot(node) {
  if (!node || !node.getAttribute) return null;
  const _attrs = (el) => {
    if (!el || !el.getAttribute) return null;
    const cls = String(el.className || '').split(/\s+/).filter(Boolean).slice(0, 2);
    return {
      tag: el.tagName || '',
      id: el.id || '',
      testid: el.getAttribute('data-testid') || '',
      role: el.getAttribute('role') || '',
      author_role: el.getAttribute('data-message-author-role')
        || el.getAttribute('data-author-role')
        || el.getAttribute('data-role')
        || el.getAttribute('data-sender')
        || '',
      classes: cls,
    };
  };
  const ancestors = [];
  let cur = node.parentElement;
  for (let i = 0; cur && i < 4; i++) {
    ancestors.push(_attrs(cur));
    cur = cur.parentElement;
  }
  // Additional useful signals -- do NOT change existing behaviour.
  const wu = (typeof arenaWhyUserAuthored === 'function')
    ? arenaWhyUserAuthored(node, (typeof getArenaAdapter === 'function') ? getArenaAdapter() : null)
    : {matched: false, reason: ''};
  return {
    path: arenaNodePath(node),
    self: _attrs(node),
    ancestors,
    text_head: (node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
    why_user_authored: wu,
    // v0.14.7: what is the *nearest* container that our fingerprint
    // uses as node-id? Same input arenaExtractNodeId consumes so it
    // matches the fingerprint.
    node_id_input: (typeof arenaExtractNodeId === 'function')
      ? arenaExtractNodeId(node) : '',
  };
}

function arenaMatchesAny(node, selectors) {
  return (selectors || []).some((s) => {
    try {
      return node?.matches?.(s) || !!node?.closest?.(s);
    } catch (_e) {
      return false;
    }
  });
}

function arenaIsComposerNode(node, adapter = getArenaAdapter()) {
  if (!node) return false;
  if (arenaMatchesAny(node, adapter.composerSelectors)) return true;
  if (node.isContentEditable && !node.closest?.('pre, code, message-content, model-response, article')) {
    return true;
  }
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
  // v0.14.12: include the nearest message-bubble ancestor's testid so
  // Grok's two identical code-block <pre> children (one under a
  // data-testid=user-message bubble, the other under data-testid=
  // assistant-message) get DIFFERENT fingerprints. Before this fix
  // both hoisted <pre> nodes had the same 6-deep tag:index path AND
  // the same 80-char text head, so they hashed to a single fp -- user
  // dismissed first, AI then inherited the dismissed state and never
  // mounted. arenaNodePath depth stays at 6 so we don't destabilise
  // other adapters' fingerprints.
  let bubbleId = '';
  try {
    const b = node.closest?.('[data-testid="user-message"], [data-testid="assistant-message"], [data-message-author-role]');
    if (b) {
      bubbleId = (b.getAttribute?.('data-testid') || '')
        + ':' + (b.getAttribute?.('data-message-author-role') || '');
    }
  } catch (_e) { /* closest can throw on detached nodes */ }
  return [
    adapter.name,
    node.getAttribute?.('data-testid') || '',
    node.getAttribute?.('data-message-author-role') || '',
    node.id || '',
    bubbleId,
    arenaNodePath(node),
    arenaNodeText(node).slice(0, 80),
  ].join('|');
}

// Recognise assistant-authored messages so we do not attach toolbars to the
// user's own composer bubble or historical user turns.
function arenaIsAssistantNode(node, adapter = getArenaAdapter()) {
  if (!node) return false;
  if (adapter.name === 'chatgpt') {
    return node.getAttribute('data-message-author-role') === 'assistant'
      || !!node.closest('[data-message-author-role="assistant"]');
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

// ---------------------------------------------------------------------------
// Fingerprints
// ---------------------------------------------------------------------------
function arenaStableHash(text, prefix = 'arena') {
  let h = 0;
  const s = String(text || '');
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0;
  }
  return `${prefix}_${Math.abs(h)}`;
}

function arenaPayloadFingerprint(payload, adapter = getArenaAdapter()) {
  const calls = Array.isArray(payload?.calls)
    ? payload.calls.map((call) => ({
        id: call.id || '',
        tool: call.tool || '',
        arguments: call.arguments || {},
      }))
    : [];
  return arenaStableHash(JSON.stringify({adapter: adapter.name, calls}), 'arena_payload');
}

function arenaPayloadSemanticFingerprint(payload, adapter = getArenaAdapter()) {
  // Semantic fingerprint deliberately drops per-instance call.id so that the
  // same tool call re-detected across DOM churn does not remount toolbars.
  const calls = Array.isArray(payload?.calls)
    ? payload.calls.map((call) => ({tool: call.tool || '', arguments: call.arguments || {}}))
    : [];
  return arenaStableHash(JSON.stringify({adapter: adapter.name, calls}), 'arena_payload_sem');
}

function arenaMessageFingerprint(node, payload, adapter = getArenaAdapter()) {
  return arenaStableHash(
    [adapter.name, arenaExtractNodeId(node, adapter), JSON.stringify(payload || {})].join('|'),
    'arena_msg',
  );
}

// ---------------------------------------------------------------------------
// Candidate-node cache — the scan hot path. Invalidated by MutationObserver.
// ---------------------------------------------------------------------------
let _cachedCandidateState = null;
let _candidateCacheDirty = true;

function arenaInvalidateCandidateCache() {
  _candidateCacheDirty = true;
}

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
  _cachedCandidateState = {
    adapter,
    nodes: arenaPruneAncestorCandidates(nodes).slice(-5),
  };
  _candidateCacheDirty = false;
  return _cachedCandidateState;
}

// ---------------------------------------------------------------------------
// Diagnostics (used by the side panel "Scan page" button)
// ---------------------------------------------------------------------------
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
    } catch (_e) { /* invalid selector */ }
    return {selector, raw, assistant, with_block: withBlock};
  });
}

function arenaLatestCandidateNodes() {
  const state = arenaCandidateNodes();
  return {adapter: state.adapter, nodes: state.nodes.slice(-2)};
}

// ---------------------------------------------------------------------------
// Composer discovery
// ---------------------------------------------------------------------------
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
    } catch (_e) { /* invalid selector */ }
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
    try {
      document.querySelectorAll(selector).forEach((node) => push(node, selector));
    } catch (_e) { /* invalid selector */ }
  }
  return candidates;
}

function arenaScoreComposerCandidate(node, active = document.activeElement) {
  let score = 0;
  const visible = arenaElementVisible(node);
  // v0.14.10: never prefer an invisible target even when it's the activeElement.
  // Qwen new-chat sometimes has a hidden sr-only textarea grabbing focus while
  // the real composer sits next to it -- insert would land in a ghost node and
  // arenaVerifySettledInsert reads back the ghost's textContent as "success".
  if (!visible) score -= 500;
  if (node === active || node.contains?.(active)) score += 100;
  if (node === window.__arenaLastComposerTarget) score += 35;
  if (visible) score += 20;
  if (node.closest?.('form')) score += 5;
  return score;
}

let _cachedComposerResult = null;
let _cachedComposerAt = 0;

function arenaInvalidateComposerCache() {
  _cachedComposerResult = null;
}

function arenaComposerSelection(adapter = getArenaAdapter()) {
  const now = Date.now();
  // v0.14.11: also invalidate the 2s cache when the cached target
  // became invisible. Qwen new-chat renders a hidden sr-only textarea
  // that used to grab the cache slot BEFORE we penalised invisibles
  // (v0.14.10 fix); the cache then returned the ghost target for 2s
  // no matter how the scorer felt about it. Insert landed in the
  // ghost, verify read back its textContent, status said 'Inserted
  // +30ms' while the visible composer stayed empty.
  const _cachedVisible = _cachedComposerResult?.target
    && (typeof arenaElementVisible === 'function')
    ? arenaElementVisible(_cachedComposerResult.target) : true;
  if (_cachedComposerResult
      && _cachedComposerResult.target?.isConnected
      && _cachedVisible
      && (now - _cachedComposerAt) < 2000) {
    return _cachedComposerResult;
  }

  // v0.14.5: also invalidate the "last composer target" hint when it
  // got detached from the DOM (Qwen re-renders the whole chat pane on
  // model switch; the cached selector then pointed at a floating node
  // that .isConnected=false and every insert missed).
  if (window.__arenaLastComposerTarget
      && !window.__arenaLastComposerTarget.isConnected) {
    window.__arenaLastComposerTarget = null;
  }
  const cached = window.__arenaLastComposerTarget;
  const ranked = arenaComposerCandidates(adapter)
    .map((item) => ({...item, score: arenaScoreComposerCandidate(item.node)}))
    .sort((a, b) => b.score - a.score);
  const selected = ranked[0] || null;
  if (selected?.node) window.__arenaLastComposerTarget = selected.node;

  const result = {
    target: selected?.node || null,
    candidates: ranked.length,
    selected_selector: selected?.selector || '',
    active_match: !!selected?.node && (
      selected.node === document.activeElement
      || selected.node.contains?.(document.activeElement)
    ),
    cached_match: !!selected?.node && selected.node === cached,
  };
  _cachedComposerResult = result;
  _cachedComposerAt = now;
  return result;
}

function arenaFindComposer(adapter = getArenaAdapter()) {
  return arenaComposerSelection(adapter).target;
}

// ---------------------------------------------------------------------------
// Submit-button discovery
// ---------------------------------------------------------------------------
function arenaButtonFromNode(node) {
  if (!node) return null;
  if (node.tagName === 'BUTTON') return node;
  return node.closest?.('button') || null;
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
    } catch (_e) { /* invalid selector */ }
  }
  return candidates;
}

function arenaDistanceBetweenRects(a, b) {
  const ax = a.left + (a.width / 2);
  const ay = a.top + (a.height / 2);
  const bx = b.left + (b.width / 2);
  const by = b.top + (b.height / 2);
  return Math.hypot(ax - bx, ay - by);
}

function arenaSubmitButtonSelection(adapter = getArenaAdapter(), composer = arenaFindComposer(adapter)) {
  const formRoot = composer?.closest?.('form');
  const fieldsetRoot = composer?.closest?.('fieldset');
  const scopeRoot = formRoot
    || fieldsetRoot
    || composer?.closest?.('[role="form"], main, section, article, [role="dialog"]');
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
  try {
    target.focus({preventScroll: true});
  } catch (_e) {
    target.focus();
  }
}
