const ARENA_ADAPTERS = (typeof ARENA_SITE_ADAPTERS !== 'undefined' ? ARENA_SITE_ADAPTERS : []);

function arenaHost() {
  return (location.hostname || '').toLowerCase();
}

function arenaPath() {
  return (location.pathname || '').toLowerCase();
}

// v0.14.23 (v4.50.13): shared column-index helper. Returns -1 when
// `node` is NOT inside a recognised multi-column container, else the
// child index of the column that contains node. Recognised
// containers are the arena.ai Battle / Code / Side-by-side layouts
// exposed via any of: `@container/carousel`, plain `carousel`,
// `side-by-side`, `battle` in the class list, Tailwind
// `grid-cols-2`, or `flex flex-row` on the immediate parent.
// Kept host-agnostic in signature so it can also be reused by
// non-arena.ai adapters that use similar Tailwind multi-column
// patterns; callers gate on hostname themselves when needed.
function arenaColumnIndex(node) {
  if (!node || !node.parentElement) return -1;
  try {
    let cur = node.parentElement;
    for (let i = 0; cur && i < 20; i++) {
      const parent = cur.parentElement;
      if (!parent) break;
      const parentCls = String(parent.className || '');
      const isColumn = /@container\/carousel/.test(parentCls)
                    || /\bcarousel\b/.test(parentCls)
                    || /side-by-side/.test(parentCls)
                    || /\bbattle\b/.test(parentCls)
                    || /grid-cols-2/.test(parentCls)
                    || /flex-row/.test(parentCls);
      if (isColumn) {
        const sibs = Array.from(parent.children);
        return sibs.indexOf(cur);
      }
      cur = parent;
    }
  } catch (_e) { /* detached nodes */ }
  return -1;
}

// v0.14.18 (v4.50.8): human-readable label for the toolbar chip so
// UIs read "Arena · Arena.ai" instead of "Arena · arenaai". Adapters
// declare `displayName` in adapter_sites.js; falls back to the raw
// internal name when the field is absent so all existing adapters
// keep their labels unchanged.
function arenaAdapterLabel(adapter) {
  if (!adapter) return '';
  return adapter.displayName || adapter.name || '';
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
  // v0.14.19 (v4.50.9): Kimi renders every tool-call twice: once in
  // a collapsed `.toolcall-container.thinking-container` widget
  // (candidate[0]) and once in the visible `.segment-content`
  // stream (candidate[1]). Both share the same fingerprint. Treat
  // the thinking-widget copy as "already handled elsewhere" -- the
  // matching flow through arenaWhyUserAuthored means mountControls
  // silently dismisses it (dismissedControls.add + return) so the
  // visible sibling wins without any visual side-effects. Reason
  // string makes the skip visible in scan-report events_recent.
  if (adapterName === 'kimi' && node.closest) {
    if (node.closest('.toolcall-container, .thinking-container')) {
      return {matched: true, reason: 'kimi:thinking-widget@DIV'};
    }
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
  // v0.14.18 (v4.50.8): arena.ai has three visible surfaces:
  //   * Agent Mode /agent/<id>   -- turn container: <div class="chat-user"|"chat-assistant">
  //   * Direct Chat /c/<id>      -- same class markers
  //   * Battle Mode              -- same wrappers per column
  // Scan-reports show `.chat-user` on the user PRE ancestor path and
  // `.chat-assistant` on the AI PRE ancestor path (z.ai adapter picks
  // this up via _USER_AUTHOR_CLASS_SUBSTRINGS[='user-message'] on
  // .chat-user -- but arena.ai's chat-user class doesn't include the
  // 'user-message' token so the global rule misses). Handle
  // explicitly so BOTH surfaces get: toolbar mounts on assistant,
  // user skipped.
  if (adapterName === 'arenaai' && node.closest) {
    // v0.14.21 (v4.50.11): the v4.50.9/v4.50.10 attempts had the
    // markers INVERTED. Ivan's scans across chat/agent/battle show:
    //   User turn (right-aligned pill):
    //     ancestor with `self-end` in the class list
    //     -- e.g. `group flex max-w-[min(768px,100%)] flex-col gap-1 self-end`
    //     May also have `bg-surface-raised w-fit`, but that pattern
    //     also appears on some AI wrappers so `self-end` is the
    //     definitive marker (Tailwind: flex-align right).
    //   AI turn (wide, center-aligned):
    //     ancestor with `mx-auto max-w-[800px] w-full` AND
    //     `bg-surface-primary` -- the AI content sits in a
    //     document-width column that spans the whole surface.
    //   `#response-content-container` still appears on some /agent/
    //     surfaces so we keep it as a positive AI fast-return.
    // We MATCH USER FIRST (self-end is more specific), then negate
    // AI, then fall through when neither pattern is present so the
    // next global rule can try.
    if (node.closest('[class*="self-end"]')) {
      return {matched: true, reason: 'arenaai:self-end@DIV'};
    }
    if (node.closest('#response-content-container')) {
      return {matched: false, reason: ''};
    }
    // AI wide-column marker: mx-auto max-w-[800px] w-full. Only
    // treat as explicit not-user when we're clearly on that
    // full-width column (Tailwind pattern is `mx-auto max-w-[800px]
    // w-full`); the `bg-surface-primary` marker alone is too broad
    // because it appears on many wrapper shells across the app.
    const wideColumn = node.closest('.mx-auto');
    if (wideColumn && /\bmax-w-\[800px\]\b/.test(String(wideColumn.className || ''))
        && /\bw-full\b/.test(String(wideColumn.className || ''))) {
      return {matched: false, reason: ''};
    }
  }
  // v0.14.17 (v4.50.7): AI Studio (aistudio.google.com; shares gemini
  // adapter with gemini.google.com). Prior attempts:
  //   * v0.14.15 -> ms-chat-turn[role="user"] / ms-prompt-chunk
  //     [chunkrole="user"] + header-text prefix match.
  //   * v0.14.16 -> broadened to substring regex on
  //     mat-expansion-panel-header + positive-model-exclusion.
  // Both misfired on the current AI Studio build: the scan showed the
  // User's own PRE fingerprint mount and the AI's PRE skipping via
  // semantic-dedup, with why_user_authored={matched:false,reason:""}
  // on BOTH. Root cause: AI Studio's live DOM uses a
  // **`data-turn-role="User"` / `data-turn-role="Model"`** attribute
  // (Pascal case) on an element inside `ms-chat-turn`, NOT
  // `role="user"` on the custom-element itself. The stable selectors
  // (confirmed by third-party userscripts) are:
  //   ms-chat-turn:has([data-turn-role="User"])   -- user turn
  //   ms-chat-turn:has([data-turn-role="Model"])  -- model turn
  // The mat-expansion-panel-header text can be empty, localised, or
  // buried inside sticky-header structure so header substring is
  // fragile.
  //
  // New strategy: walk up through `ms-chat-turn` (any depth) and read
  // its inner `[data-turn-role]` element. If turn-role indicates
  // 'User' (case-insensitive; also cover 'system'/'user turn'
  // variants) treat as user-authored. If turn-role indicates
  // 'Model'/'Assistant' explicitly, DO NOT treat as user-authored (fast
  // return via {matched:false}). Fall back to the prior header-text
  // regex for older or in-transition AI Studio revisions.
  if (adapterName === 'gemini' && node.closest) {
    const isAiStudio = typeof location !== 'undefined' && /aistudio\.google\.com$/i.test(location.hostname || '');
    if (isAiStudio) {
      // 1) Stable turn-role attribute inside ms-chat-turn.
      const chatTurn = node.closest('ms-chat-turn');
      if (chatTurn) {
        const turnRoleEl = chatTurn.querySelector('[data-turn-role]');
        const turnRole = (turnRoleEl?.getAttribute?.('data-turn-role') || '').trim().toLowerCase();
        if (turnRole === 'user' || turnRole === 'system') {
          return {matched: true, reason: 'aistudio:turn-role=' + turnRole + '@MS-CHAT-TURN'};
        }
        if (turnRole === 'model' || turnRole === 'assistant') {
          // Positive AI marker -- fast negative, do not fall through
          // to the fragile header-text heuristic which used to
          // false-positive on Russian localisation.
          return {matched: false, reason: ''};
        }
        // Also accept the class-token form some revisions expose
        // ('user-turn' / 'model-turn') on the ms-chat-turn root.
        const clsTurn = (chatTurn.className || '').toLowerCase();
        if (/(?:^|\s|-)(user|system)-turn(?:\s|$|-)/i.test(clsTurn)) {
          return {matched: true, reason: 'aistudio:class-turn@MS-CHAT-TURN'};
        }
        if (/(?:^|\s|-)(model|assistant)-turn(?:\s|$|-)/i.test(clsTurn)) {
          return {matched: false, reason: ''};
        }
      }
      // 2) Legacy custom-element ancestor (older AI Studio revisions).
      const userTurn = node.closest('ms-chat-turn[role="user"], ms-prompt-chunk[chunkrole="user"]');
      if (userTurn) {
        return {matched: true, reason: 'aistudio:user-turn@' + (userTurn.tagName || 'CUSTOM')};
      }
      // 3) Fallback: mat-expansion-panel header substring match.
      //    Retained for old builds where turn-role is absent. Uses the
      //    v0.14.16 positive-model-exclusion so Russian localisation
      //    ('Модель') on the panel header does NOT get mistaken for
      //    user by the 'систем' regex.
      const panel = node.closest('mat-expansion-panel');
      if (panel) {
        const header = panel.querySelector('mat-expansion-panel-header');
        const headTxt = (header?.textContent || '').trim().toLowerCase();
        const headAria = (header?.getAttribute?.('aria-label') || '').toLowerCase();
        const isUser = /(?:^|\s)(user|пользоват|system|систем)/i.test(headTxt)
                    || /(?:^|\s)(user|пользоват|system|систем)/i.test(headAria);
        const isModel = /(?:^|\s)(model|assistant|ответ|модел)/i.test(headTxt)
                     || /(?:^|\s)(model|assistant|ответ|модел)/i.test(headAria);
        if (isUser && !isModel) {
          return {matched: true, reason: 'aistudio:user-panel@MAT-EXPANSION-PANEL'};
        }
      }
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
  // v0.14.17 (v4.50.7): extended ancestor depth 4 -> 8 so we can see
  // through AI Studio's mat-expansion-panel wrapper stack down to
  // <ms-chat-turn> (about 5-7 ancestors up on the current build).
  for (let i = 0; cur && i < 8; i++) {
    ancestors.push(_attrs(cur));
    cur = cur.parentElement;
  }
  // Additional useful signals -- do NOT change existing behaviour.
  const wu = (typeof arenaWhyUserAuthored === 'function')
    ? arenaWhyUserAuthored(node, (typeof getArenaAdapter === 'function') ? getArenaAdapter() : null)
    : {matched: false, reason: ''};
  // v0.14.17 (v4.50.7): AI-Studio-specific diagnostic hint. Surface the
  // nearest ms-chat-turn's data-turn-role attribute + panel header
  // text/aria so operators can see why the user filter did/didn't
  // fire without re-scanning. Additive; never influences mount logic.
  let aistudioHint = null;
  try {
    if (typeof location !== 'undefined' && /aistudio\.google\.com$/i.test(location.hostname || '')) {
      const chatTurn = node.closest?.('ms-chat-turn') || null;
      const turnRoleEl = chatTurn?.querySelector?.('[data-turn-role]') || null;
      const panel = node.closest?.('mat-expansion-panel') || null;
      const header = panel?.querySelector?.('mat-expansion-panel-header') || null;
      aistudioHint = {
        has_ms_chat_turn: !!chatTurn,
        chat_turn_class: (chatTurn?.className || '').slice(0, 120),
        chat_turn_attrs: chatTurn ? {
          role: chatTurn.getAttribute?.('role') || '',
          data_role: chatTurn.getAttribute?.('data-role') || '',
        } : null,
        data_turn_role: turnRoleEl?.getAttribute?.('data-turn-role') || '',
        panel_header_text: (header?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60),
        panel_header_aria: (header?.getAttribute?.('aria-label') || '').slice(0, 60),
      };
    }
  } catch (e) { aistudioHint = {error: String(e).slice(0, 80)}; }
  // v0.14.19 (v4.50.9): arena.ai has three surfaces (/agent/, /c/,
  // battle) with different DOM structures per surface. Expose all
  // wrapper classes and IDs seen along the ancestor chain so future
  // regressions can be diagnosed from scan-report alone.
  let arenaaiHint = null;
  try {
    if (typeof location !== 'undefined' && /(^|\.)arena\.ai$/i.test(location.hostname || '')) {
      const surface = /^\/agent\//.test(location.pathname) ? 'agent'
                    : /^\/c\//.test(location.pathname) ? 'chat'
                    : /^\/battle/.test(location.pathname) ? 'battle'
                    : 'other';
      const wrappers = [];
      let cur = node.parentElement;
      for (let i = 0; cur && i < 12; i++) {
        const cls = String(cur.className || '');
        const id = cur.id || '';
        if (cls || id) {
          wrappers.push({tag: cur.tagName || '', id: id.slice(0, 40), cls: cls.slice(0, 100)});
        }
        cur = cur.parentElement;
      }
      // v0.14.23 (v4.50.13): battle / code / side-by-side column
      // hint. Uses the shared arenaColumnIndex helper (same logic
      // that drives roleBit + semanticFingerprint) and additionally
      // reports the parent's class list so we can debug what
      // wrapper was detected as the multi-column container.
      let columnHint = null;
      try {
        const idx = (typeof arenaColumnIndex === 'function') ? arenaColumnIndex(node) : -1;
        if (idx >= 0) {
          // Walk again to grab the parent class for the report.
          let cur = node.parentElement;
          let parentCls = '';
          let colCls = '';
          for (let i = 0; cur && i < 20; i++) {
            const parent = cur.parentElement;
            if (!parent) break;
            const pCls = String(parent.className || '');
            if (/@container\/carousel|\bcarousel\b|side-by-side|\bbattle\b|grid-cols-2|flex-row/.test(pCls)) {
              parentCls = pCls;
              colCls = String(cur.className || '');
              break;
            }
            cur = parent;
          }
          columnHint = {
            found: true,
            index: idx,
            via_parent: parentCls.slice(0, 80),
            column_class: colCls.slice(0, 80),
          };
        } else {
          columnHint = {found: false};
        }
      } catch (_e) { /* ignore */ }
      // v0.14.24 (v4.50.14): battle-wide carousel snapshot so we
      // can debug when a Battle scan shows only one AI column while
      // the user swears both are visible. Reports total carousel
      // count on the page and total child-column count -- if child
      // count > 1 but only one candidate came through the scan,
      // the second column is likely lazy-mounted or scrolled off.
      let carouselSnapshot = null;
      try {
        const carousels = document.querySelectorAll(
          '[class*="@container/carousel"], [class*="carousel"], [class*="side-by-side"], [class*="battle"]'
        );
        const cols = [];
        carousels.forEach((cr) => {
          Array.from(cr.children || []).forEach((child, idx) => {
            // v0.14.25 (v4.50.15): richer per-column diag. When a
            // Battle column reports has_pre=true but
            // has_tool_text=false, the model's PRE exists but the
            // JSONL got stripped/replaced by rendered output --
            // that's a source-side issue (model didn't emit the
            // block or Arena.ai post-processed it), not an
            // extension mount bug. When has_pre=false the AI's
            // reply is entirely non-code (paragraphs only).
            const pres = child.querySelectorAll?.('pre') || [];
            let hasToolText = false;
            for (const p of pres) {
              const t = p.textContent || '';
              if (t.includes('function_call_start') || t.includes('function_call_end')) {
                hasToolText = true;
                break;
              }
            }
            cols.push({
              carousel_class: String(cr.className || '').slice(0, 60),
              index: idx,
              child_class: String(child.className || '').slice(0, 60),
              has_ai_bar: !!child.querySelector?.('[data-arena-tool-controls="1"]'),
              has_pre: pres.length > 0,
              pre_count: pres.length,
              has_tool_text: hasToolText,
            });
          });
        });
        carouselSnapshot = {carousels: carousels.length, columns: cols.slice(0, 8)};
      } catch (_e) { /* ignore */ }
      arenaaiHint = {
        surface,
        response_container_ancestor: !!node.closest?.('#response-content-container'),
        bg_surface_raised_ancestor: !!node.closest?.('[class*="bg-surface-raised"]'),
        bg_surface_primary_ancestor: !!node.closest?.('[class*="bg-surface-primary"]'),
        column: columnHint,
        carousel: carouselSnapshot,
        wrappers,
      };
    }
  } catch (e) { arenaaiHint = {error: String(e).slice(0, 80)}; }
  return {
    path: arenaNodePath(node),
    self: _attrs(node),
    ancestors,
    text_head: (node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 120),
    why_user_authored: wu,
    aistudio_hint: aistudioHint,
    arenaai_hint: arenaaiHint,
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
  // v0.14.20 (v4.50.10): role-bit derived from the nearest
  // arena.ai / z.ai / claude-style wrapper-class marker. Live scan
  // from Ivan's v4.50.9 arena.ai tour proved the User + AI PREs on
  // /c/ have IDENTICAL node paths + text heads (both echo the same
  // JSONL) so arenaExtractNodeId collapsed them into one
  // fingerprint. User skip cascaded into skip_dismissed_fp on AI
  // and toolbar never appeared. The bubbleId branch above only
  // covers `data-testid=...-message` attributes -- arena.ai doesn't
  // set those; it uses Tailwind wrapper classes. We add a compact
  // roleBit token derived from those wrappers so User and AI hash
  // to DIFFERENT fingerprints:
  //   arena.ai       -> bg-surface-raised (AI) / bg-surface-primary (User)
  //                     + #response-content-container (AI)
  //   z.ai           -> .chat-assistant / .chat-user (already
  //                     handled globally via class substring)
  // Purely additive to bubbleId; empty when none of the markers
  // are found so existing adapters see zero change in their
  // fingerprints.
  let roleBit = '';
  try {
    // v0.14.21 (v4.50.11): use `self-end` as the definitive user
    // marker on arena.ai (Tailwind flex right-align pattern used
    // for user pills). The prior v0.14.20 bg-surface-raised (AI)
    // rule was INVERTED -- Ivan's live scans proved
    // bg-surface-raised is actually the User pill background.
    if (node.closest?.('[class*="self-end"], [class*="chat-user"]')) {
      roleBit = 'user';
    } else if (node.closest?.('#response-content-container, [class*="chat-assistant"]')) {
      roleBit = 'ai';
    }
    // v0.14.22/23: Arena.ai battle / side-by-side / code column
    // ordinal. When two models generate the same tool call in
    // parallel columns their outer wrappers otherwise hash to the
    // same fingerprint. Use the shared arenaColumnIndex helper
    // which covers @container/carousel, carousel, side-by-side,
    // battle, grid-cols-2, and flex-row layouts. Kept host-gated
    // on arena.ai so no other adapter's fingerprint drifts.
    if (roleBit === 'ai') {
      try {
        const isArenaAi = typeof location !== 'undefined' && /(^|\.)arena\.ai$/i.test(location.hostname || '');
        if (isArenaAi) {
          const idx = (typeof arenaColumnIndex === 'function') ? arenaColumnIndex(node) : -1;
          if (idx >= 0) roleBit = 'ai_c' + idx;
        }
      } catch (_e) { /* ignore */ }
    }
    // v0.14.21 (v4.50.11): fallback: turn ordinal from
    // conversation-turn-N testid (ChatGPT + OpenRouter both expose
    // it). Even when a chat has many identical tool-echo blocks the
    // turn number differs, so the fingerprint splits.
    if (!roleBit) {
      const turn = node.closest?.('[data-testid^="conversation-turn-"]');
      if (turn) {
        const tid = turn.getAttribute?.('data-testid') || '';
        const m = tid.match(/^conversation-turn-(\d+)/);
        if (m) roleBit = 't' + m[1];
      }
    }
    // v0.14.21: last-resort message-anchor ordinal for OpenRouter
    // (playground-message-list child index) so identical AI echoes
    // in different turns get different fingerprints.
    if (!roleBit) {
      const bubble = node.closest?.('[data-testid="assistant-message"], [data-testid="user-message"]');
      const list = bubble?.closest?.('[data-testid="message-list-content"], [data-testid="playground-message-list"]');
      if (bubble && list) {
        const kids = Array.from(list.querySelectorAll('[data-testid="assistant-message"], [data-testid="user-message"]'));
        const idx = kids.indexOf(bubble);
        if (idx >= 0) roleBit = 'm' + idx;
      }
    }
  } catch (_e) { /* ignore */ }
  return [
    adapter.name,
    node.getAttribute?.('data-testid') || '',
    node.getAttribute?.('data-message-author-role') || '',
    node.id || '',
    bubbleId,
    roleBit,
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

function arenaPayloadCallId(payload) {
  // v0.14.16 (v4.50.6): operator-requested tie-breaker for dedup --
  // when two candidates share the same semantic fingerprint (same tool
  // + arguments), prefer the one with the highest numeric call_id.
  // Rationale: on Claude the model emits sys.status with call_id 1, 2,
  // 3, 4 across successive turns; earlier releases mounted the toolbar
  // on the smallest ID (top of chat) which was the least useful copy.
  // Returns a non-negative integer, or NaN when call_id is missing /
  // non-numeric (existing behaviour: no re-ordering happens).
  if (!payload || !Array.isArray(payload.calls) || !payload.calls.length) {
    return NaN;
  }
  // We compare the FIRST call's id -- payloads with multiple calls in
  // one block share the same id-set anyway (batch), and the smallest
  // among a batch is enough for a stable order.
  const raw = String(payload.calls[0]?.id || '').trim();
  if (!raw) return NaN;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? n : NaN;
}

function arenaPayloadSemanticFingerprint(payload, adapter = getArenaAdapter(), node = null) {
  // Semantic fingerprint deliberately drops per-instance call.id so that the
  // same tool call re-detected across DOM churn does not remount toolbars.
  // v0.14.22 (v4.50.12): accepts optional `node` so battle / side-by-side
  // surfaces (arena.ai) can include a column identifier in the semantic
  // fingerprint. Two models emitting identical tool calls in parallel
  // columns must each get their own toolbar -- previously both hashed to
  // the same fingerprint and one column was silently skipped as a
  // "duplicate".
  const calls = Array.isArray(payload?.calls)
    ? payload.calls.map((call) => ({tool: call.tool || '', arguments: call.arguments || {}}))
    : [];
  let column = '';
  try {
    if (node && typeof location !== 'undefined' && /(^|\.)arena\.ai$/i.test(location.hostname || '')) {
      // v0.14.23 (v4.50.13): use the shared arenaColumnIndex helper
      // so all multi-column layouts (@container/carousel, carousel,
      // side-by-side, battle, grid-cols-2, flex-row) split.
      const idx = (typeof arenaColumnIndex === 'function') ? arenaColumnIndex(node) : -1;
      if (idx >= 0) column = 'c' + idx;
    }
  } catch (_e) { /* ignore */ }
  return arenaStableHash(JSON.stringify({adapter: adapter.name, calls, column}), 'arena_payload_sem');
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
  let pruned = arenaPruneAncestorCandidates(nodes);
  // v0.14.25 (v4.50.15): Arena.ai Battle / Code multi-column
  // top-up. In Battle mode both carousel columns should
  // independently get a toolbar, but the regular selector pass
  // often misses one column when its PRE happens to be pruned as
  // an ancestor of a smaller nested element, or when the
  // arenaPruneAncestorCandidates policy drops it as a
  // "container". Explicitly walk every carousel column and add
  // any tool-bearing PRE inside it that isn't already in the
  // pruned candidate list. Kept host-gated on arena.ai so no
  // other adapter's candidate set changes.
  try {
    const isArenaAi = typeof location !== 'undefined' && /(^|\.)arena\.ai$/i.test(location.hostname || '');
    if (isArenaAi) {
      const carousels = document.querySelectorAll(
        '[class*="@container/carousel"], [class*="carousel"], [class*="side-by-side"], [class*="battle"]'
      );
      const already = new Set(pruned);
      carousels.forEach((cr) => {
        Array.from(cr.children || []).forEach((col) => {
          const pres = col.querySelectorAll?.('pre') || [];
          for (const pre of pres) {
            const txt = pre.textContent || '';
            if (!txt.includes('function_call_start')) continue;
            // Only include if not an ancestor of anything already
            // in the pruned list (and not descendant of one).
            let redundant = false;
            for (const existing of already) {
              if (existing === pre) { redundant = true; break; }
              if (existing.contains?.(pre)) { redundant = true; break; }
              if (pre.contains?.(existing)) { redundant = true; break; }
            }
            if (!redundant) {
              pruned.push(pre);
              already.add(pre);
            }
          }
        });
      });
    }
  } catch (_e) { /* detached nodes */ }
  _cachedCandidateState = {
    adapter,
    nodes: pruned.slice(-8),  // was -5, widened to fit Battle 2 cols + N history
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









