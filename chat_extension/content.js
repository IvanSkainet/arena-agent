const ARENA_CONTENT_SCRIPT_VERSION = '0.14.31';

const processed = new Set();
const mountedControls = new Map();
const mountedPayloadSemantics = new Set();
const mountedSemanticOwners = new Map();
const executionResults = new Map();
const dismissedControls = new Set();
const detectedPayloads = new Set();
let scanTimer = null;

// v0.14.2: diag ring buffer + late-submit poller live in diag.js.
const _arenaDiagPushEvent = (typeof window._arenaDiagPushEvent === 'function')
  ? window._arenaDiagPushEvent : function () {};
const _arenaDiagEvents = window._arenaDiagEvents || [];

// === Config cache (5s TTL, chrome.runtime round-trip skip) ===
let _contentConfigCache = null;
let _contentConfigCacheAt = 0;

function _arenaCurrentModes() {
  // v0.14.15: synchronous snapshot of the last-known modes so mount
  // decisions in the scan hot path do not have to await a
  // chrome.runtime round-trip. When the cache is cold (very first
  // mount after boot), we return the defaults from settings.js --
  // never null -- so callers can `.dedupSemantic !== false` freely.
  // v0.14.18 (v4.50.8): also honour the sync-storage pre-warm
  // (_prewarmedModes) so the user's saved dedup toggle takes effect
  // on the FIRST scan after page reload, not only after the async
  // chrome.runtime.sendMessage('arena.getConfig') round-trip has
  // resolved. Priority: full config cache > prewarm > defaults.
  if (_contentConfigCache && _contentConfigCache.modes) {
    return _contentConfigCache.modes;
  }
  if (_prewarmedModes) return _prewarmedModes;
  return (typeof arenaNormalizeModes === 'function')
    ? arenaNormalizeModes({})
    : {dedupSemantic: true};
}

// v0.14.18 (v4.50.8): read chrome.storage.sync at boot so
// `_arenaCurrentModes()` returns the operator's saved dedup toggle
// value on the FIRST mount, not the default TRUE. Without this the
// first ~5 mounts after reload always used dedup=true even when the
// checkbox was cleared, which Ivan observed as "dedup toggle не
// работает" on the v4.50.6 tour. Kept defensive: any storage error
// falls back to whatever `_arenaCurrentModes()` would have returned
// (defaults) so we never break sites where chrome.storage is absent.
let _prewarmedModes = null;
try {
  chrome.storage.sync.get({modes: null}).then((data) => {
    const raw = data && data.modes;
    if (raw && typeof arenaNormalizeModes === 'function') {
      _prewarmedModes = arenaNormalizeModes(raw);
    } else if (raw) {
      _prewarmedModes = raw;
    }
  }).catch(() => { /* ignore -- defaults are fine */ });
} catch (_e) { /* chrome.storage may not exist in some contexts */ }

async function getCachedConfig() {
  const now = Date.now();
  if (_contentConfigCache && (now - _contentConfigCacheAt) < 5000) {
    return _contentConfigCache;
  }
  try {
    _contentConfigCache = await chrome.runtime.sendMessage({type: 'arena.getConfig'});
    _contentConfigCacheAt = now;
  } catch (_e) { /* keep last known cache */ }
  return _contentConfigCache || {};
}

try {
  chrome.storage.onChanged.addListener((_c, area) => {
    if (area === 'sync' || area === 'local') _contentConfigCache = null;
  });
} catch (_e) { /* storage may not be available in some contexts */ }

// === Version helpers ===
function arenaExtensionVersion() {
  try {
    return chrome.runtime.getManifest?.().version || ARENA_CONTENT_SCRIPT_VERSION;
  } catch (_e) {
    return ARENA_CONTENT_SCRIPT_VERSION;
  }
}

function versionSummary() {
  return `ext ${arenaExtensionVersion()}/content ${ARENA_CONTENT_SCRIPT_VERSION}`;
}

// === Utilities ===
function hash(text) {
  let h = 0;
  for (let i = 0; i < text.length; i++) {
    h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  }
  return `arena_${Math.abs(h)}`;
}

function formatInsertText(text) {
  const body = String(text || '').trim();
  if (!body) return '';
  // v0.14.31 (v4.51.2): the v0.14.29 HTML-comment sentinel
  // (`<!-- arena:tool-result -->`) worked on ChatGPT/T3/OpenRouter
  // but failed on Gemini/Mistral/Kimi/Qwen/DeepSeek because those
  // sites run syntax-highlighting (shiki/prism/monaco) that
  // strips HTML comments during tokenization -- the sentinel
  // never made it into textContent, so collapseToolResultsInHistory
  // never fired. Replace with a VISIBLE-TEXT sentinel that
  // survives any highlighter: a distinctive first-line prefix.
  // Not pretty, but bulletproof.
  return `\n\n\`\`\`arena-tool-result\nARENA_RESULT_V1\n${body}\n\`\`\`\n`;
}

function resultToText(result) {
  if (!result) return '';
  if (!Array.isArray(result.calls)) return JSON.stringify(result, null, 2);
  // v0.14.22 (v4.50.12): render EVERY call including failures. Before
  // this, when the AI batched several tool calls and one returned an
  // error (e.g. 400 missing name parameter), the failed call still
  // rendered its raw JSON but subsequent OK calls sometimes lost
  // their timing metadata because the outer `result.ok` was false and
  // the runAutoModes early-returned. Now each call is a labelled
  // block with its own status header so partial failures never hide
  // successful results.
  return result.calls.map((call, idx) => {
    const id = String(call?.id || call?.call_id || (idx + 1));
    const tool = String(call?.tool || 'tool');
    const okFlag = call?.ok === false ? 'ERROR' : 'OK';
    const body = call?.result?.parsed
      ? JSON.stringify(call.result.parsed, null, 2)
      : (call?.result?.text
        ? String(call.result.text)
        : JSON.stringify(call, null, 2));
    return `# call ${id} · ${tool} · ${okFlag}\n${body}`;
  }).join('\n\n');
}

function makeButton(label, onClick, primary = false) {  // v4.48.0: shadow toolbar delegate + fallback
  if (typeof arenaShadowToolbarButton === 'function') {
    return arenaShadowToolbarButton(label, onClick, { primary });
  }
  const btn = document.createElement('button');
  btn.textContent = label;
  btn.className = 'arena-btn' + (primary ? ' arena-btn--primary' : '');
  btn.addEventListener('pointerdown', (event) => event.preventDefault());
  btn.addEventListener('mousedown', (event) => event.preventDefault());
  btn.addEventListener('click', onClick);
  return btn;
}

function resultErrorText(result) {
  if (!result) return 'empty response';
  if (result.error) return String(result.error);
  const failed = Array.isArray(result.calls)
    ? result.calls.find((call) => call && call.ok === false)
    : null;
  const parsed = failed?.result?.parsed;
  return parsed?.error
    || parsed?.message
    || (failed?.result?.text ? String(failed.result.text).slice(0, 220) : '')
    || result.summary
    || (result.status ? `HTTP ${result.status}` : 'unknown');
}

function controlsHost(node, adapter) {
  // v0.14.3/8: hoist wrappers (Qwen drift + DuckAI overflow-hidden + Qwen Monaco viewport).
  if (!node) return document.body;
  if (String(node.tagName || '').toUpperCase() === 'CODE') node = node.closest('pre') || node.parentElement || node;
  if (String(node.tagName || '').toUpperCase() === 'DIV') { const pre = node.querySelector('pre'); if (pre) node = pre; }
  const adapterName = adapter && adapter.name;
  if (adapterName === 'duckai') { const w = node.closest?.('.overflow-hidden'); if (w?.parentElement) return w.parentElement; }
  if (adapterName === 'qwen') { const pre = node.closest?.('pre.qwen-markdown-code, pre'); if (pre) return pre; }  // v0.14.9: anchor outer <pre>
  // v0.14.19 (v4.50.9): Kimi thinking-widget candidate is now handled
  // via arenaWhyUserAuthored -> matched=true so mountControls
  // silently dismisses it. The v0.14.18 attempt to re-anchor onto
  // the `.segment-assistant` sibling produced a huge empty toolbar
  // column in saved chats because the segment DIV spans the whole
  // message vertically. The sibling `.segment-content` PRE
  // (candidate[1] in Kimi scan-report) is a separate parsed node
  // that mountControls already visits on its own -- we just need
  // to get out of its way.
  // v0.14.19 (v4.50.9): z.ai renders the tool block as inline
  // syntax-highlighted DIVs/CODEs inside a `.markdown-prose`
  // container. The v0.14.18 walker keyed on Kimi-specific class
  // tokens (`.code-block` / `.syntax-highlighter` / `.segment-code`)
  // that don't exist on z.ai, so it returned null and the toolbar
  // stayed on the whole `.markdown-prose` (attached at the end of
  // the message). Live scan proves `code: raw=6` and text starts
  // with "Thought Process\njsonl\n{...}" so there IS a code element
  // containing the JSONL. Fix: walk breadth-first for the FIRST
  // <pre>/<code>/[class*="language-"]/[class*="hljs"] whose text
  // includes 'function_call_start' or 'function_call_end' so we
  // anchor exactly on the block, not the whole prose.
  if (adapterName === 'zai') {
    const isMarkdownProse = String(node.tagName || '').toUpperCase() === 'DIV'
      && node.className
      && String(node.className).includes('markdown-prose');
    if (isMarkdownProse) {
      const CODE_MARKERS = ['function_call_start', 'function_call_end'];
      const stack = [node];
      let target = null;
      let depth = 0;
      while (stack.length && depth < 300) {
        depth += 1;
        const cur = stack.shift();
        if (!cur || cur.nodeType !== 1) continue;
        const tag = String(cur.tagName || '').toUpperCase();
        const cls = String(cur.className || '');
        const looksCode = (tag === 'PRE') || (tag === 'CODE')
          || cls.includes('language-') || cls.includes('hljs')
          || cls.includes('code-block') || cls.includes('syntax-highlighter')
          || cls.includes('segment-code');
        if (looksCode) {
          const txt = cur.textContent || '';
          if (CODE_MARKERS.some((m) => txt.includes(m))) {
            target = cur;
            break;
          }
        }
        for (const child of Array.from(cur.children || [])) stack.push(child);
      }
      if (target) {
        // Prefer the enclosing block wrapper (parent) so the
        // toolbar sits under the whole code fence, not tight to
        // the last highlighted <code> span.
        return target.closest?.('pre, [class*="code"], [class*="language-"]') || target;
      }
    }
  }
  return node;
}

function attachControls(host, bar) {
  const tag = String(host?.tagName || '').toUpperCase();
  const width = Math.max(280, Math.min(host.getBoundingClientRect?.().width || 680, 900));
  bar.style.width = `${width}px`;
  // v0.14.25 (v4.50.15): T3 chat duplicate root cause -- when
  // mountControls runs twice for the same host (because the
  // dedup gate races on a hot streaming rescan), attachControls
  // called `insertAdjacentElement('afterend', bar)` twice, stacking
  // TWO shadow hosts as siblings AFTER the same PRE. The
  // mountedControls map holds only one entry but the DOM has both.
  // Before inserting the new bar, purge any prior arena tool bar
  // or shadow-host that is already a direct sibling of `host` so
  // duplicates never stack in the first place. Preserves the
  // v0.14.24 DOM sweep as a second line of defence.
  try {
    // Walk ALL following siblings (do not break on non-arena) and
    // remove any arena bar or shadow-host so duplicates never
    // stack. Stops at the newly-inserted `bar` if for some reason
    // it is already attached to the DOM here.
    const purge = [];
    let s = host.nextElementSibling;
    while (s) {
      if (s === bar) break;
      if (s.dataset?.arenaToolControls === '1'
          || s.dataset?.arenaShadowHost === '1') {
        purge.push(s);
      }
      s = s.nextElementSibling;
    }
    purge.forEach((el) => el.remove());
  } catch (_e) { /* detached hosts */ }
  if ((tag === 'PRE' || tag === 'CODE') && host.parentNode) {
    host.insertAdjacentElement('afterend', bar);
  } else {
    // Same guard for the appendChild branch: remove any prior
    // arena bar or shadow-host among direct children before append.
    try {
      Array.from(host.children || []).forEach((el) => {
        if (el === bar) return;
        if (el.dataset?.arenaToolControls === '1' || el.dataset?.arenaShadowHost === '1') el.remove();
      });
    } catch (_e) { /* ignore */ }
    host.appendChild(bar);
  }
}

function cleanupStaleControls() {
  document.querySelectorAll('[data-arena-tool-controls="1"]').forEach((bar) => bar.remove());
  document.querySelectorAll('[data-arena-tool-controls-mounted="1"]').forEach((node) => { node.dataset.arenaToolControlsMounted = ''; });
  mountedControls.clear();
  mountedPayloadSemantics.clear();
  mountedSemanticOwners.clear();
  executionResults.clear();
  detectedPayloads.clear();
}

function pruneMountedControls() {
  for (const [fingerprint, info] of [...mountedControls.entries()]) {
    if (info?.bar?.isConnected && info?.host?.isConnected) continue;
    // v0.14.27 (v4.50.17): T3 chat root-cause fix. When React
    // re-renders an assistant bubble during streaming, the old PRE
    // host becomes disconnected but our previously-attached shadow
    // host stays PARENTED TO THE NEW BUBBLE (React re-parents it
    // as an unknown child). The v0.14.24-25 prune only cleared the
    // map entry, leaving the orphan shadow host in the DOM.
    // Second mount attempt then goes to the new PRE, inserts a
    // second shadow-host sibling, and we end up with two toolbars.
    // Fix: explicitly remove the shadow-host / bar from the DOM
    // when we prune the map entry. Guarded by isConnected so we
    // never touch elements that were already GC'd.
    if (info?.shadowHost?.isConnected) info.shadowHost.remove();
    else if (info?.bar?.isConnected) info.bar.remove();
    if (info?.host?.dataset) info.host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(fingerprint);
    if (info?.semanticFingerprint) {
      mountedPayloadSemantics.delete(info.semanticFingerprint);
      mountedSemanticOwners.delete(info.semanticFingerprint);
    }
  }
}

// v0.14.23 (v4.50.13): post-scan sweep for duplicate toolbars that
// slipped past mountControls' dedup. T3 chat streaming can race two
// mount attempts through the semantic-dedup gate before either
// completes (both see `!mountedPayloadSemantics.has(...)` because
// neither has committed yet), producing TWO connected toolbars for
// one semantic fingerprint. Ivan observed this in new T3 chats: the
// duplicate persists until page reload. Also protects other
// adapters against the same class of race. Only runs when
// dedupSemantic is enabled. Groups live entries by semantic
// fingerprint and keeps the LATER-in-document one (matches the
// v4.50.10 tiebreaker policy).
function sweepDuplicateToolbars() {
  const modes = _arenaCurrentModes();
  if (modes?.dedupSemantic === false) return;
  // v0.14.24 (v4.50.14): DOM-based sweep. The v4.50.13 map-based
  // implementation missed T3-chat's persistent duplicate because
  // mountedControls.set(fp, ...) OVERWROTE the previous entry when
  // two mount attempts committed with the same message fingerprint
  // -- only ONE map entry existed but TWO shadow hosts were in the
  // DOM. Now we walk every element carrying
  // data-arena-tool-controls-mounted and group by
  // data-arena-semantic-fingerprint so duplicate shadow hosts are
  // caught regardless of what the map remembers.
  const bySem = new Map();
  const hosts = document.querySelectorAll('[data-arena-tool-controls-mounted="1"]');
  hosts.forEach((host) => {
    if (!host.isConnected) return;
    const sem = host.dataset?.arenaSemanticFingerprint || '';
    if (!sem) return;
    // Find the associated shadow/bar node: nextElementSibling first
    // (v4.48.0 pattern), then descendant fallback.
    const bar = host.nextElementSibling?.dataset?.arenaToolControls === '1'
      ? host.nextElementSibling
      : host.querySelector?.('[data-arena-tool-controls="1"]');
    if (!bar || !bar.isConnected) return;
    const fp = host.dataset?.arenaToolFingerprint || '';
    if (!bySem.has(sem)) { bySem.set(sem, [{fp, host, bar}]); return; }
    bySem.get(sem).push({fp, host, bar});
  });
  for (const [sem, mounts] of bySem.entries()) {
    if (mounts.length < 2) continue;
    // Keep the LATEST in document order; evict the rest.
    let keeper = mounts[0];
    for (const cand of mounts.slice(1)) {
      try {
        const rel = keeper.host.compareDocumentPosition(cand.host);
        if (rel & 4) keeper = cand;  // cand FOLLOWS keeper -> newer
      } catch (_e) { /* ignore */ }
    }
    for (const cand of mounts) {
      if (cand === keeper) continue;
      _arenaDiagPushEvent({
        kind: 'sweep_duplicate_evicted',
        fingerprint: cand.fp,
        kept: keeper.fp,
        semantic: sem,
      });
      // The shadow-host wrapper is the bar's parent when it lives
      // as a nextElementSibling; otherwise the bar itself is what
      // needs to go.
      const shadow = cand.bar.closest?.('[data-arena-shadow-host="1"]');
      if (shadow) shadow.remove();
      else cand.bar.remove();
      if (cand.host?.dataset) {
        cand.host.dataset.arenaToolControlsMounted = '';
        cand.host.dataset.arenaToolFingerprint = '';
        cand.host.dataset.arenaSemanticFingerprint = '';
      }
      // Best-effort cleanup of the map too (may be no-op if the
      // fingerprint was overwritten).
      if (cand.fp) mountedControls.delete(cand.fp);
    }
    // Re-anchor semantic owner on the survivor if the map still
    // has an entry.
    if (keeper.fp) mountedSemanticOwners.set(sem, keeper.fp);
  }

  // v0.14.27 (v4.50.17): orphan shadow-host sweep. When React
  // re-parents a shadow host to a NEW bubble during streaming (T3
  // chat scenario), the shadow host loses its `data-arena-tool-
  // controls-mounted` anchor sibling and is no longer covered by
  // the semantic-fingerprint sweep above. We walk every
  // `[data-arena-shadow-host="1"]` in the document; if the
  // previous element sibling isn't the original host (no
  // `data-arena-tool-controls-mounted`), the shadow is an orphan
  // and safe to remove. Also groups any remaining shadow-hosts
  // that share the same enclosing `[role="article"]` /
  // article ancestor -- if two shadows land in the same article
  // (same message), keep the LATER one.
  const shadows = document.querySelectorAll('[data-arena-shadow-host="1"]');
  const byArticle = new Map();
  shadows.forEach((sh) => {
    if (!sh.isConnected) return;
    // v0.14.31 (v4.51.2): FIXED orphan check. v0.14.27 required
    // `previousElementSibling` to carry `arenaToolControlsMounted`
    // but that breaks adapters like z.ai where `controlsHost`
    // returns a DIV and `attachControls` uses `appendChild`, so
    // the shadow host becomes a CHILD of the mounted host, not a
    // sibling. Now: shadow is anchored if EITHER prev-sibling is
    // a mounted host (v4.48.0 PRE pattern) OR parent element
    // carries the mounted-controls attribute (appendChild pattern).
    const prev = sh.previousElementSibling;
    const parent = sh.parentElement;
    const isAnchored = (
      (prev && prev.dataset?.arenaToolControlsMounted === '1')
      || (parent && parent.dataset?.arenaToolControlsMounted === '1')
    );
    if (!isAnchored) {
      _arenaDiagPushEvent({kind: 'sweep_orphan_shadow_removed'});
      sh.remove();
      return;
    }
    // Group by nearest article container so we can dedup two
    // shadows under one message.
    const art = sh.closest?.('[role="article"], article, [data-arena-tool-controls-mounted="1"]');
    const key = art || sh.parentElement;
    if (!key) return;
    if (!byArticle.has(key)) { byArticle.set(key, [sh]); return; }
    byArticle.get(key).push(sh);
  });
  for (const [_key, group] of byArticle.entries()) {
    if (group.length < 2) continue;
    let keeper = group[0];
    for (const cand of group.slice(1)) {
      try {
        const rel = keeper.compareDocumentPosition(cand);
        if (rel & 4) keeper = cand;
      } catch (_e) { /* ignore */ }
    }
    for (const cand of group) {
      if (cand === keeper) continue;
      _arenaDiagPushEvent({kind: 'sweep_article_duplicate_removed'});
      cand.remove();
    }
  }
}

function suppressCurrentControls() {
  const state = typeof arenaCandidateNodes === 'function'
    ? arenaCandidateNodes()
    : {adapter: {name: 'generic'}, nodes: []};
  state.nodes.forEach((node) => {
    const text = typeof arenaDetectionText === 'function'
      ? arenaDetectionText(node, state.adapter)
      : (node.textContent || '');
    parseArenaBlocks(text).forEach((entry) => {
      const host = controlsHost(node, state.adapter);
      const messageFp = typeof arenaMessageFingerprint === 'function'
        ? arenaMessageFingerprint(host, entry.payload, state.adapter)
        : hash((host.textContent || '') + JSON.stringify(entry.payload));
      const semanticFp = typeof arenaPayloadSemanticFingerprint === 'function'
        ? arenaPayloadSemanticFingerprint(entry.payload, state.adapter, host)
        : hash(JSON.stringify(entry.payload || {}));
      dismissedControls.add(messageFp);
      dismissedControls.add(semanticFp);
    });
  });
}

function hostHasToolbar(host) {
  if (host?.dataset?.arenaToolControlsMounted !== '1') return false;
  return !!(
    host.nextElementSibling?.dataset?.arenaToolControls === '1'
    || host.querySelector?.('[data-arena-tool-controls="1"]')
  );
}

function buildRequest(payload, adapterName, fingerprint) {
  return {
    site: {origin: location.origin, url: location.href, adapter: adapterName},
    message: {fingerprint},
    payload,
    mode: {},
  };
}

function payloadTools(payload) {
  return (payload?.calls || []).map((call) => call.tool).filter(Boolean);
}

function detectedDetail(payload, _adapter) {
  const tools = payloadTools(payload).slice(0, 4).join(', ') || 'tool block';
  return `detected ${tools} on ${location.hostname}`;
}

function genericInsertIntoActiveField(text, strategy = 'auto') {
  const active = document.activeElement;
  if (active && (active.tagName === 'TEXTAREA' || (active.tagName === 'INPUT' && active.type === 'text'))) {
    const start = active.selectionStart ?? active.value.length;
    const end = active.selectionEnd ?? active.value.length;
    active.value = `${active.value.slice(0, start)}${text}${active.value.slice(end)}`;
    active.dispatchEvent(new Event('input', {bubbles: true}));
    return true;
  }
  if (active && active.isContentEditable) {
    if (typeof arenaInsertIntoEditable === 'function') {
      return arenaInsertIntoEditable(active, text, strategy);
    }
    document.execCommand('insertText', false, text);
    return true;
  }
  return false;
}

function attemptsSummary(timing) {
  const attempts = Array.isArray(timing?.attempts) ? timing.attempts : [];
  if (!attempts.length) return '';
  const parts = attempts.map((item) => {
    const status = item.settled ? 'ok' : (item.changed ? 'changed' : 'no-change');
    return `${item.strategy}:${status}`;
  });
  return ` Attempts: ${parts.join(', ')}.`;
}

function timingSummary(timing) {
  const strategy = timing?.strategy || timing?.method || 'unknown';
  const requested = timing?.requested_strategy;
  const prefix = (requested === 'auto' && strategy !== 'auto')
    ? `Auto used ${strategy}`
    : `via ${strategy}`;
  const ms = timing?.total_ms ?? timing?.insert_ms ?? '?';
  const verify = timing?.verify_ms ? `, verified +${timing.verify_ms}ms` : '';
  const bridge = timing?.bridge_ms ? ` · bridge ${timing.bridge_ms}ms` : '';
  return `${prefix} in ${ms}ms${verify}${bridge} · ${versionSummary()}`;
}

function insertFailureSummary(strategy, timing) {
  const requested = timing?.requested_strategy || strategy;
  const settled = timing?.settled === false ? 'not settled in composer' : 'not inserted';
  const prefix = requested === 'auto' ? 'Auto insert failed' : `Could not insert via ${strategy}`;
  return `${prefix}: ${settled}; copy instead.${attemptsSummary(timing)}`;
}

async function currentInsertStrategy() {
  const cfg = await getCachedConfig();
  return cfg?.modes?.insertStrategy || 'auto';
}

function previewSummary(result) {
  const calls = Array.isArray(result?.calls) ? result.calls : [];
  const tools = calls.map((call) => call.tool || call.name).filter(Boolean).slice(0, 3).join(', ');
  return `Dry run: ${calls.length} call(s)${tools ? ` · ${tools}` : ''}`
    + ` · approval=${!!result?.policy?.requires_approval}`;
}

// === mountControls: attach toolbar with fingerprint dedup ===
function mountControls(host, payload, adapter) {
  // v0.14.4: generic adapter is passive -- never mount on unlisted sites.
  if (adapter && adapter.passive) return;
  // v0.14.27 (v4.50.17): passiveUnlessComposer -- generic adapter
  // opt-in for unlisted chat sites. Only mount when the page has
  // a discoverable composer AND the candidate is inside a
  // chat-like message container. This lets the extension work on
  // any Ollama/LibreChat/etc. clone without a per-site entry.
  //
  // v0.14.28 (v4.50.18): additionally gated behind the
  // `enableGenericAdapter` mode toggle (default FALSE). When the
  // operator hasn't opted in via Advanced/experimental, the
  // passiveUnlessComposer adapter behaves exactly like `passive`.
  // Eliminates any risk of false-positive mounts on sites the
  // operator hasn't explicitly opted into.
  if (adapter && adapter.passiveUnlessComposer) {
    const genericOn = _arenaCurrentModes()?.enableGenericAdapter === true;
    if (!genericOn) {
      _arenaDiagPushEvent({kind: 'skip_generic_toggle_off', adapter: adapter.name});
      return;
    }
    let hasComposer = false;
    try {
      for (const sel of adapter.composerSelectors || []) {
        const el = document.querySelector(sel);
        if (el && (el.isContentEditable || String(el.tagName || '').toUpperCase() === 'TEXTAREA' || String(el.tagName || '').toUpperCase() === 'INPUT')) {
          hasComposer = true;
          break;
        }
      }
    } catch (_e) { /* invalid selector */ }
    if (!hasComposer) {
      _arenaDiagPushEvent({kind: 'skip_generic_no_composer', adapter: adapter.name});
      return;
    }
    // strictJsonlFencing: block must be inside a chat-shaped
    // ancestor. Prevents mounting on random README PRE elements.
    if (adapter.strictJsonlFencing) {
      const chatAncestor = host?.closest?.(
        '[role="article"], article, [role="log"], [class*="message" i], [class*="chat" i], [class*="conversation" i], [class*="bubble" i]'
      );
      if (!chatAncestor) {
        _arenaDiagPushEvent({kind: 'skip_generic_not_in_chat', adapter: adapter.name, tag: host?.tagName || ''});
        return;
      }
    }
  }
  host = controlsHost(host, adapter);
  _arenaDiagPushEvent({kind: 'mount_entry', adapter: adapter.name, tag: host?.tagName || '', testid: host?.getAttribute?.('data-testid') || ''});  // v0.14.11: entry diag

  const fingerprint = typeof arenaMessageFingerprint === 'function'
    ? arenaMessageFingerprint(host, payload, adapter)
    : hash((host.textContent || '') + JSON.stringify(payload));
  const payloadFingerprint = typeof arenaPayloadFingerprint === 'function'
    ? arenaPayloadFingerprint(payload, adapter)
    : hash(JSON.stringify(payload || {}));
  const semanticFingerprint = typeof arenaPayloadSemanticFingerprint === 'function'
    ? arenaPayloadSemanticFingerprint(payload, adapter, host)
    : payloadFingerprint;
  const existing = mountedControls.get(fingerprint);  // v0.14.11: dismissed-check BEFORE evict (DuckAI thrash)
  if (dismissedControls.has(fingerprint)) { _arenaDiagPushEvent({kind: 'skip_dismissed_fp', adapter: adapter.name, fingerprint}); return; }
  if (dismissedControls.has(semanticFingerprint)) { _arenaDiagPushEvent({kind: 'skip_dismissed_semantic', adapter: adapter.name, fingerprint, semantic: semanticFingerprint}); return; }

  // v0.14.15: dedup strategy is now operator-controllable via the
  // Advanced/Experimental section of the popup (modes.dedupSemantic).
  //
  //   dedupSemantic === true  (default, preferred by the operator)
  //     Keep the pre-v0.14.14 behaviour: one toolbar per unique
  //     semantic tool block. Sibling duplicates are silently skipped
  //     when their previous owner is still alive in the DOM
  //     (skip_semantic_prev_alive), evicted-and-re-mounted only when
  //     the previous host is gone (SPA churn). Trade-off: some
  //     candidates never see a toolbar (Claude call_id 2/3 got
  //     hidden this way).
  //
  //   dedupSemantic === false  (v0.14.14 opt-in mode)
  //     Every candidate host gets its own toolbar. More visual
  //     feedback, useful when the operator cannot tell which copy
  //     the extension picked. Cost: two toolbars on legitimate
  //     duplicates, more real estate consumed.
  //
  // Per-host dedup (existing?.bar?.isConnected + hostHasToolbar)
  // is preserved in both modes -- that is idempotency of the scan
  // loop, not a policy choice.
  const _dedupSemantic = _arenaCurrentModes()?.dedupSemantic !== false;
  if (_dedupSemantic) {
    const semanticOwner = mountedSemanticOwners.get(semanticFingerprint);
    if (semanticOwner && semanticOwner !== fingerprint) {
      const previous = mountedControls.get(semanticOwner);
      const prevAlive = !!(previous?.host?.isConnected && previous?.bar?.isConnected);
      // v0.14.16 (v4.50.6): tie-breaker by call_id. When both hosts are
      // alive, the operator asked us to prefer the candidate with the
      // HIGHER numeric call_id. On Claude the model emits call_id 1..N
      // across turns; the latest one is the most useful copy to keep
      // visible. When call_ids are missing / non-numeric we fall back
      // to the v0.14.13 "prev-wins" behaviour so nothing regresses.
      const currentCid = (typeof arenaPayloadCallId === 'function') ? arenaPayloadCallId(payload) : NaN;
      const previousCid = (typeof arenaPayloadCallId === 'function') ? arenaPayloadCallId(previous?.payload) : NaN;
      const currentBigger = Number.isFinite(currentCid) && Number.isFinite(previousCid) && currentCid > previousCid;
      // v0.14.20 (v4.50.10): DOM-position tiebreaker for when the
      // model forgets to increment call_id (Ivan: "нет обработки в
      // том случае, если AI ставит тот же самый ID на tool call").
      // When both call_ids are equal (or both NaN), prefer the
      // candidate that appears LATER in the document -- the newest
      // rendered copy is almost always the one the user is looking
      // at. `compareDocumentPosition` returns FOLLOWING (0x04) when
      // `previous.host` is BEFORE the current host, i.e. the
      // current one is newer.
      let currentIsNewer = false;
      try {
        if (previous?.host && host && typeof previous.host.compareDocumentPosition === 'function') {
          const rel = previous.host.compareDocumentPosition(host);
          // Node.DOCUMENT_POSITION_FOLLOWING = 4
          currentIsNewer = !!(rel & 4);
        }
      } catch (_e) { /* detached nodes throw */ }
      const cidsEqualOrMissing = (!Number.isFinite(currentCid) || !Number.isFinite(previousCid) || currentCid === previousCid);
      if (!prevAlive) {
        _arenaDiagPushEvent({kind: 'evict_semantic_owner', adapter: adapter.name, fingerprint, previous_owner: semanticOwner, reason: 'prev-dead'});
        if (previous?.shadowHost) previous.shadowHost.remove();
        else previous?.bar?.remove();
        if (previous?.host?.dataset) previous.host.dataset.arenaToolControlsMounted = '';
        mountedControls.delete(semanticOwner);
        mountedPayloadSemantics.delete(semanticFingerprint);
        mountedSemanticOwners.delete(semanticFingerprint);
      } else if (currentBigger) {
        _arenaDiagPushEvent({kind: 'evict_semantic_owner', adapter: adapter.name, fingerprint, previous_owner: semanticOwner, reason: `higher-call-id:${currentCid}>${previousCid}`});
        if (previous?.shadowHost) previous.shadowHost.remove();
        else previous?.bar?.remove();
        if (previous?.host?.dataset) previous.host.dataset.arenaToolControlsMounted = '';
        mountedControls.delete(semanticOwner);
        mountedPayloadSemantics.delete(semanticFingerprint);
        mountedSemanticOwners.delete(semanticFingerprint);
      } else if (cidsEqualOrMissing && currentIsNewer) {
        _arenaDiagPushEvent({kind: 'evict_semantic_owner', adapter: adapter.name, fingerprint, previous_owner: semanticOwner, reason: 'later-in-document'});
        if (previous?.shadowHost) previous.shadowHost.remove();
        else previous?.bar?.remove();
        if (previous?.host?.dataset) previous.host.dataset.arenaToolControlsMounted = '';
        mountedControls.delete(semanticOwner);
        mountedPayloadSemantics.delete(semanticFingerprint);
        mountedSemanticOwners.delete(semanticFingerprint);
      } else {
        _arenaDiagPushEvent({kind: 'skip_semantic_prev_alive', adapter: adapter.name, fingerprint, previous_owner: semanticOwner, current_call_id: currentCid, previous_call_id: previousCid});
        return;
      }
    }
    if (mountedPayloadSemantics.has(semanticFingerprint)) {
      _arenaDiagPushEvent({kind: 'skip_semantic_already_mounted', adapter: adapter.name, fingerprint, semantic: semanticFingerprint});
      return;
    }
  }
  if (existing?.bar?.isConnected) { _arenaDiagPushEvent({kind: 'skip_existing_connected', adapter: adapter.name, fingerprint}); return; }
  if (hostHasToolbar(host)) { _arenaDiagPushEvent({kind: 'skip_host_has_toolbar', adapter: adapter.name, fingerprint}); return; }

  // v0.14.5/9: skip user-authored (fingerprint only; reason recorded for diag).
  const _wu = (typeof arenaWhyUserAuthored === 'function') ? arenaWhyUserAuthored(host, adapter) : {matched: false, reason: ''};
  if (_wu.matched) {  // v0.14.9: skip THIS fingerprint only (semantic-dup would kill the AI echo).
    dismissedControls.add(fingerprint);
    _arenaDiagPushEvent({kind: 'skip_user_authored', adapter: adapter.name, fingerprint, reason: _wu.reason});
    return;
  }

  const firstSeen = !processed.has(fingerprint);
  const firstPayloadSeen = !detectedPayloads.has(semanticFingerprint);
  processed.add(fingerprint);
  detectedPayloads.add(semanticFingerprint);
  // v0.14.18 (v4.50.8): only remember the semantic fingerprint in
  // the dedup Set when the toggle is ON. Otherwise a mid-session
  // toggle flip from ON->OFF would still leak old fingerprints and
  // block re-mounts of legitimate duplicates the operator wants to
  // see.
  if (_dedupSemantic) mountedPayloadSemantics.add(semanticFingerprint);
  host.dataset.arenaToolControlsMounted = '1';
  host.dataset.arenaToolFingerprint = fingerprint;
  // v0.14.24 (v4.50.14): stamp semantic fingerprint on the host so
  // sweepDuplicateToolbars can group by semantic even when two live
  // hosts share the same message fingerprint (Ivan's T3 chat scan
  // showed mountedControls only stored ONE map entry per fp, but
  // TWO shadow-hosts existed in the DOM -- the map-based sweep
  // couldn't see the second one to evict it).
  host.dataset.arenaSemanticFingerprint = semanticFingerprint;

  const request = buildRequest(payload, adapter.name, fingerprint);

  if (firstSeen && firstPayloadSeen) {
    chrome.runtime.sendMessage({
      type: 'arena.detected',
      body: {
        detail: detectedDetail(payload, adapter),
        site: location.origin,
        adapter: adapter.name,
        fingerprint,
        payload_fingerprint: semanticFingerprint,
        payload_instance_fingerprint: payloadFingerprint,
        tools: payloadTools(payload),
        payload: request,
      },
    });
  }

  let lastExecutionText = executionResults.get(semanticFingerprint) || '';

  // v4.48.0: Shadow DOM host isolates toolbar from page CSS.
  let shadowHost = null;
  let bar;
  if (typeof arenaCreateShadowToolbar === 'function') {
    const parts = arenaCreateShadowToolbar(host);
    shadowHost = parts.shadowHost;
    bar = parts.toolbar;
  } else {
    bar = document.createElement('div');
    bar.dataset.arenaToolControls = '1';
    bar.className = 'arena-toolbar';
  }

  const status = document.createElement('span');
  status.className = 'arena-toolbar-status';
  status.textContent = lastExecutionText
    ? `Arena · ${(typeof arenaAdapterLabel === 'function') ? arenaAdapterLabel(adapter) : adapter.name} · result ready`
    : `Arena · ${(typeof arenaAdapterLabel === 'function') ? arenaAdapterLabel(adapter) : adapter.name}`;
  bar.appendChild(status);

  bar.appendChild(makeButton('Preview', async () => {
    status.textContent = 'Previewing...';
    const result = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
    status.textContent = result?.ok
      ? previewSummary(result)
      : `Preview error: ${resultErrorText(result)}`;
  }));

  bar.appendChild(makeButton('Run', async () => {
    status.textContent = 'Running...';
    const runStarted = performance.now();
    const result = await chrome.runtime.sendMessage({
      type: 'arena.execute',
      body: {...request, mode: {approve: true}},
    });
    const runMs = Math.round(performance.now() - runStarted);
    const bridgeMs = result?.bridge_ms || 0;
    // v0.14.22 (v4.50.12): render text even on partial failure so the
    // operator can Insert the successful calls' output alongside the
    // failed call's error message. Also always show timing so the
    // per-call ms is never hidden behind a bare "Run error".
    if (Array.isArray(result?.calls)) {
      lastExecutionText = resultToText(result);
      if (lastExecutionText) executionResults.set(semanticFingerprint, lastExecutionText);
    }
    const timing = bridgeMs > 0 ? ` in ${runMs}ms (bridge ${bridgeMs}ms)` : ` in ${runMs}ms`;
    const total = result?.calls?.length || 0;
    const okCount = Array.isArray(result?.calls)
      ? result.calls.filter((c) => c?.ok !== false).length
      : 0;
    if (result?.ok) {
      status.textContent = `Executed ${total} call(s)${timing}`;
    } else if (Array.isArray(result?.calls) && result.calls.length) {
      status.textContent = `Executed ${okCount}/${total} call(s)${timing} · error: ${resultErrorText(result)}`;
    } else {
      status.textContent = `Run error: ${resultErrorText(result)}`;
    }
  }, true));

  bar.appendChild(makeButton('Insert', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const insertText = formatInsertText(lastExecutionText);
    const strategy = await currentInsertStrategy();
    let ok = false;
    if (typeof arenaInsertResult === 'function') {
      ok = await arenaInsertResult(insertText, adapter, strategy);
    } else {
      ok = genericInsertIntoActiveField(insertText, strategy);
    }
    const timing = {ok, ...(window.__arenaLastInsertTiming || {})};
    await arenaRecordInsertEvent('insert', request, adapter, timing, 'manual');
    status.textContent = ok
      ? `Inserted ${timingSummary(timing)}.`
      : insertFailureSummary(strategy, timing);
  }));

  bar.appendChild(makeButton('Send', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    const strategy = await currentInsertStrategy();
    const state = typeof arenaInsertAndSubmit === 'function'
      ? await arenaInsertAndSubmit(formatInsertText(lastExecutionText), adapter, strategy)
      : {ok: false, inserted: false, submitted: false};
    await arenaRecordInsertEvent(
      state.submitted ? 'submit' : 'insert', request, adapter, state, 'manual',
    );
    if (state.ok) {
      status.textContent = state.submitted
        ? `Inserted/submitted ${timingSummary(state)}.`
        : `Inserted ${timingSummary(state)}, submit not found.`;
    } else {
      status.textContent = `Insert & submit failed. ${insertFailureSummary(strategy, state)}`;
    }
  }));

  bar.appendChild(makeButton('Copy', async () => {
    if (!lastExecutionText) { status.textContent = 'No result yet. Run first.'; return; }
    try {
      await navigator.clipboard.writeText(lastExecutionText);
      status.textContent = 'Result copied.';
    } catch (e) {
      status.textContent = `Copy failed: ${e}`;
    }
  }));

  bar.appendChild(makeButton('Panel', async () => {
    const result = await chrome.runtime.sendMessage({type: 'arena.openSidePanel'});
    status.textContent = result?.ok
      ? 'Opened side panel.'
      : `Panel error: ${result?.error || 'unknown'}`;
  }));

  bar.appendChild(makeButton('×', () => {
    dismissedControls.add(fingerprint);
    dismissedControls.add(semanticFingerprint);
    // v4.48.0: remove shadow host (or bar in fallback path).
    if (shadowHost) {
      if (typeof arenaDestroyShadowToolbar === 'function') arenaDestroyShadowToolbar(shadowHost);
      else shadowHost.remove();
    } else {
      bar.remove();
    }
    host.dataset.arenaToolControlsMounted = '';
    mountedControls.delete(fingerprint);
    mountedPayloadSemantics.delete(semanticFingerprint);
    mountedSemanticOwners.delete(semanticFingerprint);
  }));

  // v4.48.0: position the shadow host (or bar on fallback).
  attachControls(host, shadowHost || bar);
    // Track shadowHost for semantic-eviction .remove(); `bar` kept for back-compat.
  mountedControls.set(fingerprint, {host, bar, shadowHost, semanticFingerprint, payload});
  mountedSemanticOwners.set(semanticFingerprint, fingerprint);
  _arenaDiagPushEvent({kind: 'mounted', adapter: adapter.name, fingerprint, tag: host?.tagName || ''});

  runAutoModes(request, adapter, status, semanticFingerprint, (text) => {
    lastExecutionText = text;
  });
}

// === Auto-preview / auto-execute / auto-insert / auto-submit modes. ===
async function runAutoModes(request, adapter, status, semanticFingerprint, setResultText) {
  const cfg = await getCachedConfig();
  const modes = typeof arenaNormalizeModes === 'function'
    ? arenaNormalizeModes(cfg?.modes)
    : (cfg?.modes || {});
  if (!modes.autoPreview && !modes.autoExecuteSafe) return;

  status.textContent = modes.autoExecuteSafe
    ? 'Auto previewing before safe execution...'
    : 'Auto previewing...';
  const preview = await chrome.runtime.sendMessage({type: 'arena.preview', body: request});
  if (!preview?.ok) {
    status.textContent = `Auto preview error: ${resultErrorText(preview)}`;
    return;
  }
  if (!modes.autoExecuteSafe || !preview.policy?.can_auto_run) {
    status.textContent = `Preview ready: approval=${!!preview.policy?.requires_approval}`;
    return;
  }

  status.textContent = 'Auto executing safe call(s)...';
  const result = await chrome.runtime.sendMessage({
    type: 'arena.execute',
    body: {...request, mode: {}},
  });
  // v0.14.22 (v4.50.12): preserve text output on partial failure so
  // autoInsertResult can still push successful calls' output to the
  // composer.
  const text = resultToText(result);
  if (text) executionResults.set(semanticFingerprint, text);
  setResultText(text);
  const total = result?.calls?.length || 0;
  const okCount = Array.isArray(result?.calls)
    ? result.calls.filter((c) => c?.ok !== false).length
    : 0;
  if (!result?.ok && !total) {
    status.textContent = `Auto run error: ${resultErrorText(result)}`;
    return;
  }
  status.textContent = result?.ok
    ? `Auto executed ${total} call(s)`
    : `Auto executed ${okCount}/${total} call(s) · error: ${resultErrorText(result)}`;

  if (!modes.autoInsertResult || !text) return;
  const insertText = formatInsertText(text);
  const strategy = modes.insertStrategy || 'auto';

  let state;
  if (modes.autoSubmitResult && typeof arenaInsertAndSubmit === 'function') {
    state = await arenaInsertAndSubmit(insertText, adapter, strategy);
  } else if (typeof arenaInsertResult === 'function') {
    const ok = await arenaInsertResult(insertText, adapter, strategy);
    state = {ok, ...(window.__arenaLastInsertTiming || {})};
  } else {
    state = {ok: genericInsertIntoActiveField(insertText, strategy)};
  }

  await arenaRecordInsertEvent(
    state.submitted ? 'submit' : 'insert', request, adapter, state, 'auto',
  );
  if (state.ok) {
    status.textContent = state.submitted
      ? `Auto inserted/submitted ${timingSummary(state)}.`
      : `Auto inserted ${timingSummary(state)}.`;
  } else {
    status.textContent = insertFailureSummary(strategy, state);
  }
}

// === Scan pipeline: MutationObserver → scheduleScan (throttled) → scan() ===
let _lastCandidateCount = -1;

function scan() {
  pruneMountedControls();
  const state = typeof arenaCandidateNodes === 'function'
    ? arenaCandidateNodes()
    : {adapter: {name: 'generic'}, nodes: [document.body]};

  // Fast path: same candidate count AND all already have toolbars → skip parse.
  const allMounted = state.nodes.every((node) => hostHasToolbar(controlsHost(node, state.adapter)));
  if (state.nodes.length === _lastCandidateCount && allMounted) return;
  _lastCandidateCount = state.nodes.length;

  state.nodes.forEach((node) => {
    // v0.14.20 (v4.50.10): multi-block per message. When a single
    // AI turn emits several tool JSONL blocks (Ivan observed 5-6
    // on OpenRouter/Arena.ai/openrouter routed to Hy3-free), the
    // previous scan() collapsed them all under the same
    // controlsHost so only ONE toolbar mounted per host. Now: for
    // every PRE inside the candidate that carries its own arena
    // tool block, mount a toolbar anchored on THAT PRE. Falls back
    // to the outer candidate when no per-block PRE is found so
    // adapters without <pre> code fences (z.ai .markdown-prose,
    // arena.ai future surfaces) still get a toolbar.
    const outerHost = controlsHost(node, state.adapter);
    const text = typeof arenaDetectionText === 'function'
      ? arenaDetectionText(node, state.adapter)
      : (node.textContent || '');
    const entries = parseArenaBlocks(text);
    if (!entries.length) return;
    // v0.14.23 (v4.50.13): per-entry text-based finder. The
    // v0.14.21 walker (querySelectorAll of code-fence selectors)
    // failed on OpenRouter when the AI emitted N tool blocks and
    // fewer than N containers had rendered with the expected class
    // by scan time -- e.g. 3 fs.view/mission.catalog blocks but
    // only 1 `.group/codeblock` was ready. The whole entries[]
    // then dumped onto single-host and the operator got 1 toolbar
    // for 3 tool calls.
    //
    // New strategy: for EACH parsed entry we compute a unique
    // fingerprint text (call_id + tool name from function_call_start)
    // and walk the candidate DIV depth-first for the *tightest*
    // element whose textContent contains that fingerprint. Falls
    // back to the outer candidate for entries we cannot pin down.
    const blockNodes = [];
    let matchedEntries = 0;
    try {
      const CODE_SEL = 'pre, code, [class*="group/codeblock"], [class*="code-block"], [class*="codeBlock"], [class*="syntax-highlighter"], [class*="markdown-fenced-code"], [class*="shiki"], [class*="hljs"], [class*="language-"]';
      const candidateBlocks = Array.from(node.querySelectorAll?.(CODE_SEL) || []);
      entries.forEach((entry) => {
        // Derive a signature that MUST appear inside the block's
        // rendered text. call_id + tool name is unique per turn.
        const call = (entry.payload?.calls || [])[0] || {};
        const callId = String(call.id || '');
        const tool = String(call.tool || '');
        const sigs = [];
        if (callId) sigs.push('"call_id":"' + callId + '"');
        if (tool) sigs.push('"name":"' + tool + '"');
        if (!sigs.length) { blockNodes.push(null); return; }
        // Find tightest element containing ALL sigs.
        let tightest = null;
        for (const el of candidateBlocks) {
          const txt = el.textContent || '';
          if (!sigs.every((s) => txt.includes(s))) continue;
          if (!tightest) { tightest = el; continue; }
          if (tightest.contains?.(el)) tightest = el;
        }
        if (tightest) matchedEntries++;
        blockNodes.push(tightest);
      });
    } catch (_e) { /* querySelectorAll can throw on detached nodes */ }

    // Multi-block path: mount ALL entries individually as long as
    // AT LEAST one entry pinned to a distinct sub-element. Entries
    // that didn't match still get a toolbar on outerHost so nothing
    // silently disappears.
    if (matchedEntries > 0 && entries.length > 1) {
      const usedHosts = new Set();
      let outerUsed = false;
      entries.forEach((entry, i) => {
        const anchor = blockNodes[i] || null;
        const targetHost = anchor
          ? controlsHost(anchor, state.adapter)
          : outerHost;
        if (!anchor) {
          if (outerUsed) return; // avoid double-mount on outerHost
          outerUsed = true;
        }
        if (hostHasToolbar(targetHost)) return;
        if (usedHosts.has(targetHost)) return;
        usedHosts.add(targetHost);
        mountControls(targetHost, entry.payload, state.adapter);
      });
      return;
    }
    // Single-block fallback: preserve v0.14.19 behaviour.
    if (hostHasToolbar(outerHost)) return;
    entries.forEach((entry) => mountControls(outerHost, entry.payload, state.adapter));
  });
  // v0.14.23 (v4.50.13): post-scan duplicate sweep. Catches T3
  // chat streaming race + any other adapter where two mount
  // attempts commit for the same semantic fingerprint before
  // either sees the other in mountedPayloadSemantics.
  sweepDuplicateToolbars();
  // v0.14.29 (v4.51.0): collapse inserted tool results in chat
  // history. After the user Inserts a tool result and sends the
  // message, the JSONL blob dominates the chat scrollback. We
  // wrap those blocks in a foldable <details> summary so the
  // history stays readable.
  collapseToolResultsInHistory();
}

// v0.14.29 (v4.51.0): find every PRE / code containing the
// `<!-- arena:tool-result -->` sentinel that `formatInsertText`
// stamped and replace it with a `<details>` wrapper. Idempotent:
// once wrapped, the sentinel PRE lives inside a details block
// that we mark with `data-arena-tool-collapsed="1"` so subsequent
// scans skip it. Preserves the original PRE inside the details so
// clicking "Expand" restores the full content. Also survives
// site rehydration -- if the site rebuilds the PRE, the sentinel
// is still there and we re-wrap on the next scan.
function collapseToolResultsInHistory() {
  if (_arenaCurrentModes()?.collapseToolResults === false) return;
  // v0.14.31 (v4.51.2): visible-text sentinel (survives every
  // syntax highlighter including shiki/prism/monaco). Also
  // supports the legacy HTML-comment sentinel for messages
  // already in the chat from v4.51.0/1.
  const SENTINEL = 'ARENA_RESULT_V1';
  const LEGACY_SENTINEL = '<!-- arena:tool-result -->';
  // Widened selector: Gemini uses <code-block> custom element,
  // Kimi uses `.language-jsonl`, Qwen uses `.qwen-markdown-code`,
  // Monaco viewport for Qwen live-render.
  const BLOCKS = document.querySelectorAll(
    'pre, code, code-block, [class*="code-block"], [class*="markdown-fenced-code"], '
    + '[class*="shiki"], [class*="hljs"], [class*="language-"], '
    + '[class*="qwen-markdown-code"], [class*="segment-code"], '
    + '[class*="formatted-code-block"]'
  );
  BLOCKS.forEach((block) => {
    if (!block.isConnected) return;
    if (block.closest?.('[data-arena-tool-collapsed="1"]')) return;
    const text = block.textContent || '';
    if (!text.includes(SENTINEL) && !text.includes(LEGACY_SENTINEL)) return;
    const lineCount = (text.match(/\n/g) || []).length + 1;
    if (lineCount < 4) return;
    // Composer-preview guard (unchanged from v4.51.0).
    const next = block.nextElementSibling;
    if (next?.dataset?.arenaToolControls === '1'
        || next?.dataset?.arenaShadowHost === '1') return;
    // v0.14.31: prefer the OUTER code-fence container as the
    // wrapping target so we don't leave the fence's chrome (copy
    // button, language label) outside the <details>. Walk up
    // until we hit something that looks like the fence root.
    let target = block;
    const fenceRoot = block.closest?.(
      'code-block, [class*="formatted-code-block"], [class*="code-block"], '
      + '[class*="markdown-fenced-code"], [class*="segment-code"]'
    );
    if (fenceRoot && fenceRoot !== block && fenceRoot.contains?.(block)) {
      target = fenceRoot;
    }
    // If ANOTHER block inside the same fence already carries the
    // sentinel, only wrap ONCE (per fence, not per inner block).
    if (target !== block && target.querySelector?.('[data-arena-tool-collapsed="1"]')) return;
    const callHeaders = (text.match(/# call \d+ ·/g) || []).length;
    const tools = new Set();
    for (const m of text.matchAll(/# call \d+ · ([\w.\-_]+) ·/g)) tools.add(m[1]);
    const summaryText = callHeaders > 0
      ? `▸ Arena tool result (${callHeaders} call${callHeaders !== 1 ? 's' : ''}: ${Array.from(tools).slice(0, 4).join(', ')}${tools.size > 4 ? '…' : ''}, ${lineCount} lines) — click to expand`
      : `▸ Arena tool result (${lineCount} lines) — click to expand`;
    try {
      const details = document.createElement('details');
      details.dataset.arenaToolCollapsed = '1';
      details.style.margin = '4px 0';
      details.style.padding = '4px 8px';
      details.style.background = 'rgba(120,120,120,0.08)';
      details.style.borderRadius = '4px';
      details.style.fontSize = '13px';
      const summary = document.createElement('summary');
      summary.textContent = summaryText;
      summary.style.cursor = 'pointer';
      summary.style.color = 'inherit';
      summary.style.fontWeight = '500';
      details.appendChild(summary);
      const parent = target.parentNode;
      if (!parent) return;
      parent.insertBefore(details, target);
      details.appendChild(target);
      _arenaDiagPushEvent({
        kind: 'tool_result_collapsed',
        tools: Array.from(tools),
        lines: lineCount,
        calls: callHeaders,
        target_tag: target.tagName || '',
      });
    } catch (_e) { /* DOM churn */ }
  });
}

function scanPageDiagnostics() {
  const state = typeof arenaCandidateNodes === 'function'
    ? arenaCandidateNodes()
    : {adapter: {name: 'generic'}, nodes: [document.body]};
  const samples = [];
  const candidateDiagnostics = [];  // v0.14.7 additive
  let parsedBlocks = 0;
  const tools = new Set();
  const semanticFingerprints = new Set();

  state.nodes.forEach((node, index) => {
    const text = typeof arenaDetectionText === 'function'
      ? arenaDetectionText(node, state.adapter)
      : (node.textContent || '');
    const entries = parseArenaBlocks(text);
    parsedBlocks += entries.length;
    entries.forEach((entry) => {
      (entry.payload?.calls || []).forEach((call) => tools.add(call.tool));
      const semanticFp = typeof arenaPayloadSemanticFingerprint === 'function'
        ? arenaPayloadSemanticFingerprint(entry.payload, state.adapter)
        : hash(JSON.stringify(entry.payload || {}));
      semanticFingerprints.add(semanticFp);
    });
    if (samples.length < 5) {
      samples.push({
        index,
        tag: node.tagName || '',
        text: String(text).slice(0, 240),
        parsed: entries.length,
        tools: entries.flatMap((entry) => (entry.payload?.calls || []).map((call) => call.tool)),
      });
    }
    // v0.14.7: bounded diag snapshot for each candidate (max 8).
    if (candidateDiagnostics.length < 8) {
      const snap = (typeof arenaDiagnosticSnapshot === 'function') ? arenaDiagnosticSnapshot(node) : null;
      if (snap) {
        candidateDiagnostics.push({
          index,
          parsed: entries.length,
          host_has_toolbar: hostHasToolbar(controlsHost(node, state.adapter)),
          mounted: (node.dataset?.arenaToolControlsMounted === '1') || !!controlsHost(node, state.adapter)?.dataset?.arenaToolControlsMounted,
          fingerprint: node.dataset?.arenaToolFingerprint || '',
          snapshot: snap,
        });
      }
    }
  });

  const selectorHits = (typeof arenaSelectorDiagnostics === 'function') ? arenaSelectorDiagnostics() : [];
  const composer = (typeof arenaComposerDiagnostics === 'function') ? arenaComposerDiagnostics(state.adapter) : null;
  const semanticDuplicateBlocks = Math.max(0, parsedBlocks - semanticFingerprints.size);
  const diagnosticSummary = [
    semanticFingerprints.size ? `${semanticFingerprints.size} unique block(s)` : '',
    semanticDuplicateBlocks ? `+${semanticDuplicateBlocks} duplicate(s)` : '',
    composer?.submit_phase ? `submit ${composer.submit_phase}` : '',
  ].filter(Boolean).join(' · ');

  // v0.14.7: mounted_diagnostics -- DOM snapshot for each mounted toolbar.
  const mountedDiagnostics = [];
  document.querySelectorAll('[data-arena-tool-controls="1"]').forEach((el) => {
    if (mountedDiagnostics.length >= 8) return;
    const snap = (typeof arenaDiagnosticSnapshot === 'function') ? arenaDiagnosticSnapshot(el) : null;
    if (snap) mountedDiagnostics.push({fingerprint: el.dataset?.arenaToolFingerprint || '', snapshot: snap});
  });

  return {
    ok: true,
    url: location.href,
    host: location.hostname,
    adapter: state.adapter?.name || 'generic',
    content_version: ARENA_CONTENT_SCRIPT_VERSION,
    manifest_version: arenaExtensionVersion(),
    insert_script_version: (typeof arenaInsertScriptVersion === 'function') ? arenaInsertScriptVersion() : 'unknown',
    composer,
    candidate_nodes: state.nodes.length,
    parsed_blocks: parsedBlocks,
    semantic_unique_blocks: semanticFingerprints.size,
    semantic_duplicate_blocks: semanticDuplicateBlocks,
    diagnostic_summary: diagnosticSummary,
    mounted_controls: document.querySelectorAll('[data-arena-tool-controls="1"]').length,
    dismissed_controls: dismissedControls.size,
    tools: [...tools],
    selector_hits: selectorHits,
    samples,
    candidate_diagnostics: candidateDiagnostics,  // v0.14.7 additive
    mounted_diagnostics: mountedDiagnostics,
    events_recent: _arenaDiagEvents.slice(),  // v0.14.2: last 20 skip/late-submit events
  };
}

// === scheduleScan: throttle + idle-callback coalescing (guards SPA DOM churn) ===
let _lastScanAt = 0;
const SCAN_THROTTLE_MS = 400;

function scheduleScan() {
  if (scanTimer) return;
  const elapsed = Date.now() - _lastScanAt;
  const delay = elapsed < SCAN_THROTTLE_MS ? (SCAN_THROTTLE_MS - elapsed) : 0;
  const run = () => {
    scanTimer = null;
    _lastScanAt = Date.now();
    scan();
  };
  scanTimer = setTimeout(() => {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(run, {timeout: 600});
    } else {
      run();
    }
  }, delay || 300);
}

// === Message router + boot ===
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === 'arena.clearPageControls') {
    suppressCurrentControls();
    cleanupStaleControls();
    sendResponse?.({ok: true, dismissed: dismissedControls.size});
    return true;
  }
  if (message?.type === 'arena.showPageControls') {
    dismissedControls.clear();
    cleanupStaleControls();
    setTimeout(scan, 0);
    sendResponse?.({ok: true});
    return true;
  }
  if (message?.type === 'arena.controlsModeChanged') {
    setTimeout(scan, 0);
    sendResponse?.({ok: true});
    return true;
  }
  if (message?.type === 'arena.scanPage') {
    sendResponse?.(scanPageDiagnostics());
    return true;
  }
  return false;
});

cleanupStaleControls();

const obs = new MutationObserver((mutations) => {
    // Ignore mutations inside our own toolbars — they must not trigger rescan.
  const relevant = mutations.some((m) => {
    if (m.target?.closest?.('[data-arena-tool-controls]')) return false;
    return m.addedNodes?.length || m.removedNodes?.length;
  });
  if (!relevant) return;
  if (typeof arenaInvalidateCandidateCache === 'function') {
    arenaInvalidateCandidateCache();
  }
  // v0.14.31 (v4.51.2): run collapseToolResultsInHistory EARLY,
  // outside the scan throttle, so the fold happens on the same
  // frame the sentinel-carrying block appears. Prior to this the
  // blob was visible for ~300-600ms (scan throttle delay) before
  // being wrapped -- Ivan called that "мерцание". The rest of
  // scan work still goes through scheduleScan for throttling.
  try { collapseToolResultsInHistory(); } catch (_e) { /* first-load race */ }
  scheduleScan();
});
obs.observe(document.documentElement, {childList: true, subtree: true});

scan();















