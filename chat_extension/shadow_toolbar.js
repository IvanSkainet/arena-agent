// Arena Chat Bridge — Shadow DOM toolbar helpers (v4.48.0).
//
// Before this release the injected toolbar was a light-DOM <div> with
// styles set through inline `bar.style.cssText = "..."` in content.js.
// That worked, but every chat site's own CSS could still influence
// (or accidentally match) our elements — ChatGPT's `!important`
// button reset, Gemini's font-inheritance rules, Claude's message-
// bubble padding — because we lived in the same DOM tree as the page.
//
// v4.48.0 moves the injected toolbar into a Shadow DOM host per
// message anchor. Same pattern as MCP SuperAssistant's
// BaseSidebarManager: create a light-DOM <div>, call attachShadow()
// on it, mount the toolbar inside the shadow root, and inject a
// stylesheet fetched from the extension package.
//
// This file exports three helpers into the global (content-script)
// scope so content.js can use them without ES modules (Manifest V3
// content scripts cannot import ES modules):
//
//   arenaCreateShadowToolbar(hostAnchor, {onClose})
//       Returns { shadowHost, shadowRoot, toolbar } where `toolbar`
//       is a bare <div class="arena-toolbar"> ready for buttons.
//       `hostAnchor` is the element the toolbar should sit next to —
//       used for width sizing only; positioning is done by the caller
//       (via attachControls()).
//
//   arenaDestroyShadowToolbar(shadowHost)
//       Removes the shadow host from the DOM. Safe to call on a
//       host that has already been detached.
//
//   arenaShadowToolbarButton(label, onClick, {primary})
//       Convenience factory for a <button class="arena-btn"> node
//       that carries the pointer-preserving event handlers the
//       previous content.js `makeButton()` helper set up.
//
// The css file (shadow_toolbar.css) is declared in
// manifest.json::web_accessible_resources so
// chrome.runtime.getURL('shadow_toolbar.css') can be fetched from
// the content-script context.

(function () {
  'use strict';

  // Fetched CSS text is cached across all toolbar mounts on a page.
  // The stylesheet is small (~100 lines) and never changes between
  // page loads, so we pay the network cost once per content-script
  // instance.
  let _cachedCssText = null;
  let _cssFetchPromise = null;

  async function _fetchToolbarCss() {
    if (_cachedCssText !== null) return _cachedCssText;
    if (_cssFetchPromise) return _cssFetchPromise;
    _cssFetchPromise = (async () => {
      try {
        const url = chrome.runtime.getURL('shadow_toolbar.css');
        const response = await fetch(url);
        if (!response.ok) {
          // Non-fatal: the toolbar will still work, just without any
          // styling. Log so a debugging operator sees the issue.
          console.warn('[arena] shadow_toolbar.css fetch failed:', response.status);
          _cachedCssText = '';
          return '';
        }
        _cachedCssText = await response.text();
        return _cachedCssText;
      } catch (err) {
        console.warn('[arena] shadow_toolbar.css fetch threw:', err);
        _cachedCssText = '';
        return '';
      }
    })();
    return _cssFetchPromise;
  }

  // Synchronous stylesheet injection using a synchronous XHR fallback
  // is deliberately avoided; the content script mounts toolbars
  // asynchronously anyway (arena.preview / arena.execute all round-
  // trip to background.js), so an extra microtask on first mount is
  // imperceptible.
  async function _injectStyles(shadowRoot) {
    const css = await _fetchToolbarCss();
    if (!css) return;   // Fetch failed; toolbar renders unstyled.
    const styleEl = document.createElement('style');
    styleEl.textContent = css;
    shadowRoot.appendChild(styleEl);
  }

  function arenaCreateShadowToolbar(hostAnchor, options) {
    options = options || {};

    // Shadow host is a plain block-level div in the light DOM. The
    // caller is responsible for placing it (see attachControls in
    // content.js). We mark it with the same data-attribute the
    // previous light-DOM toolbar used so cleanupStaleControls() +
    // MutationObserver ignore rules keep working without changes.
    const shadowHost = document.createElement('div');
    shadowHost.dataset.arenaToolControls = '1';
    // A second attribute makes it obvious in devtools that this host
    // is our shadow anchor (vs. some legacy light-DOM toolbar). The
    // MutationObserver in content.js already ignores anything under
    // [data-arena-tool-controls] so no observer changes are needed.
    shadowHost.dataset.arenaShadowHost = '1';

    // Match the width behaviour the pre-v4.48.0 toolbar had — the
    // caller (attachControls) also sets .width on the host based on
    // the anchor's bounding box, so this default only matters for
    // hosts that never get anchored (i.e. bugs).
    shadowHost.style.display = 'block';
    shadowHost.style.margin = '0';
    shadowHost.style.padding = '0';
    shadowHost.style.border = '0';

    // mode:'open' — same as MCP SuperAssistant's BaseSidebarManager.
    // 'closed' would prevent Scan Page diagnostics from reaching into
    // the shadow root for debugging, which we want to keep possible.
    const shadowRoot = shadowHost.attachShadow({ mode: 'open' });

    // Fire-and-forget style injection. The toolbar renders as a plain
    // (unstyled) row for the first paint on very slow networks — same
    // failure mode as the pre-v4.48.0 code, which also depended on
    // style.cssText being applied before the browser painted.
    _injectStyles(shadowRoot);

    const toolbar = document.createElement('div');
    toolbar.className = 'arena-toolbar';
    shadowRoot.appendChild(toolbar);

    return { shadowHost, shadowRoot, toolbar };
  }

  function arenaDestroyShadowToolbar(shadowHost) {
    if (!shadowHost) return;
    // Idempotent — safe to call twice.
    try {
      shadowHost.remove();
    } catch (_err) {
      // Node might already be detached; ignore.
    }
  }

  // v0.14.41 (v4.53.0): pretty-print the parsed tool call ABOVE
  // the toolbar so the user reads `sys.status(limit=5)` instead
  // of the raw `{"type":"function_call_start"...}` JSON. Adapted
  // from MCP SuperAssistant's function-block renderer
  // (github.com/srbhptl39/MCP-SuperAssistant/pages/content/src/
  // render_prescript/src/renderer/functionBlock.ts), simplified
  // for our shadow-DOM-per-anchor architecture. All markup lives
  // in a single <div class="arena-preview"> we insert at the top
  // of the shadow root so the light-DOM MutationObserver ignore
  // rules keep working unchanged.
  //
  // Idempotent: if a preview already exists in this shadow root
  // we replace it in place so payload changes during streaming
  // don't stack duplicates.
  function arenaShadowToolbarPreview(shadowRoot, opts) {
    if (!shadowRoot) return null;
    opts = opts || {};
    const calls = Array.isArray(opts.calls) ? opts.calls : [];
    let preview = shadowRoot.querySelector('.arena-preview');
    if (preview) preview.remove();
    preview = document.createElement('div');
    preview.className = 'arena-preview';
    if (!calls.length) {
      preview.textContent = '(no tool calls parsed)';
      shadowRoot.insertBefore(preview, shadowRoot.firstChild);
      return preview;
    }
    calls.forEach((call, idx) => {
      const card = document.createElement('div');
      card.className = 'arena-preview-card';
      // Header: risk badge + tool name + call id.
      const header = document.createElement('div');
      header.className = 'arena-preview-header';
      const risk = String(call.risk || 'unknown');
      const riskBadge = document.createElement('span');
      riskBadge.className = `arena-preview-risk arena-preview-risk--${risk}`;
      riskBadge.textContent = risk;
      header.appendChild(riskBadge);
      const nameEl = document.createElement('span');
      nameEl.className = 'arena-preview-name';
      nameEl.textContent = String(call.tool || call.name || 'unknown');
      header.appendChild(nameEl);
      const idEl = document.createElement('span');
      idEl.className = 'arena-preview-id';
      idEl.textContent = call.id ? `#${call.id}` : `#${idx + 1}`;
      header.appendChild(idEl);
      card.appendChild(header);
      // Description (if catalog gave us one).
      if (call.description) {
        const desc = document.createElement('div');
        desc.className = 'arena-preview-desc';
        desc.textContent = String(call.description).slice(0, 240);
        card.appendChild(desc);
      }
      // Parameters as name→value rows.
      const argEntries = Object.entries(call.arguments || {});
      if (argEntries.length) {
        const params = document.createElement('dl');
        params.className = 'arena-preview-params';
        argEntries.forEach(([k, v]) => {
          const dt = document.createElement('dt');
          dt.textContent = k;
          const dd = document.createElement('dd');
          let repr;
          try {
            repr = typeof v === 'string' ? v : JSON.stringify(v);
          } catch { repr = String(v); }
          if (repr && repr.length > 320) repr = repr.slice(0, 317) + '…';
          dd.textContent = repr;
          params.appendChild(dt);
          params.appendChild(dd);
        });
        card.appendChild(params);
      } else {
        const empty = document.createElement('div');
        empty.className = 'arena-preview-noargs';
        empty.textContent = '(no arguments)';
        card.appendChild(empty);
      }
      preview.appendChild(card);
    });
    shadowRoot.insertBefore(preview, shadowRoot.firstChild);
    return preview;
  }

  // v0.14.41 (v4.53.0): pretty result panel BELOW the toolbar.
  // Shows the executed tool result in a collapsible <details> so
  // long outputs don't dominate the message; Ivan's v4.51.x
  // request "чтобы результат не занимал полэкрана" is honoured
  // here without touching the collapse-in-history codepath.
  function arenaShadowToolbarResult(shadowRoot, opts) {
    if (!shadowRoot) return null;
    opts = opts || {};
    const text = typeof opts.text === 'string' ? opts.text : '';
    let panel = shadowRoot.querySelector('.arena-result');
    if (panel) panel.remove();
    if (!text) return null;
    panel = document.createElement('details');
    panel.className = 'arena-result';
    panel.open = !!opts.open;
    const summary = document.createElement('summary');
    const lines = (text.match(/\n/g) || []).length + 1;
    const calls = (text.match(/# call \d+ ·/g) || []).length;
    summary.textContent = calls > 0
      ? `▸ Result (${calls} call${calls === 1 ? '' : 's'}, ${lines} line${lines === 1 ? '' : 's'})`
      : `▸ Result (${lines} line${lines === 1 ? '' : 's'})`;
    panel.appendChild(summary);
    const pre = document.createElement('pre');
    pre.className = 'arena-result-body';
    pre.textContent = text;
    panel.appendChild(pre);
    shadowRoot.appendChild(panel);
    return panel;
  }

  function arenaShadowToolbarButton(label, onClick, options) {
    options = options || {};
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.className = 'arena-btn' + (options.primary ? ' arena-btn--primary' : '');
    // Keep the composer focused; blur/focus churn slows some chat
    // UIs. Same behaviour the previous light-DOM makeButton had.
    btn.addEventListener('pointerdown', function (event) { event.preventDefault(); });
    btn.addEventListener('mousedown', function (event) { event.preventDefault(); });
    btn.addEventListener('click', onClick);
    return btn;
  }

  // Expose helpers on the global scope so content.js can pick them
  // up without ES-module imports (MV3 content scripts cannot use
  // import statements today).
  window.arenaCreateShadowToolbar = arenaCreateShadowToolbar;
  window.arenaDestroyShadowToolbar = arenaDestroyShadowToolbar;
  window.arenaShadowToolbarButton = arenaShadowToolbarButton;
  window.arenaShadowToolbarPreview = arenaShadowToolbarPreview;
  window.arenaShadowToolbarResult = arenaShadowToolbarResult;
})();
