// ---------------------------------------------------------------------------
// Insert strategies: functions that write assistant tool-call output into the
// chat composer. Each site has quirks (rich-text vs textarea, ProseMirror,
// paste hooks, etc.), so we run through a plan in a well-defined order and
// verify each attempt actually landed before declaring success.
// ---------------------------------------------------------------------------

function arenaInsertScriptVersion() {
  return '0.14.5';
}

function arenaSetInsertTiming(timing) {
  window.__arenaLastInsertTiming = timing;
}

function arenaNormalizeInsertStrategy(strategy) {
  const known = [
    'auto', 'nativeInsertText', 'paragraphFallback', 'pasteOnly',
    'directDomText', 'directDomBlocks', 'directDomPreWrap',
  ];
  return known.includes(strategy) ? strategy : 'auto';
}

function arenaSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------------------------------------------------------------------------
// Text extraction / normalisation used for verification
// ---------------------------------------------------------------------------
function arenaComposerText(adapter = getArenaAdapter()) {
  const target = arenaFindComposer(adapter);
  if (!target) return '';
  if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
    return target.value || '';
  }
  return target.textContent || '';
}

function arenaEditableText(target) {
  return String(target?.textContent || target?.value || '')
    .replace(/\s+/g, ' ')
    .trim();
}

function arenaNormalizeTextForVerify(text) {
  return String(text || '').replace(/\s+/g, ' ').trim();
}

function arenaCompactTextForVerify(text) {
  return String(text || '').replace(/\s+/g, '');
}

function arenaInsertMarkers(text) {
  const normalized = arenaNormalizeTextForVerify(text);
  const compact = arenaCompactTextForVerify(text);
  return {
    normalized: normalized.slice(0, 80),
    compact: compact.slice(0, 80),
  };
}

function arenaTextContainsInsert(text, inserted) {
  const markers = arenaInsertMarkers(inserted);
  const normalized = arenaNormalizeTextForVerify(text);
  const compact = arenaCompactTextForVerify(text);
  if (markers.normalized && normalized.includes(markers.normalized)) return true;
  if (markers.compact && compact.includes(markers.compact)) return true;
  return false;
}

// v0.14.3: structure verification. When the payload contained \n
// (jsonl blocks always do), the composer must reflect that break --
// otherwise the model reads back a single-line blob (visible on
// Perplexity / Kimi scan-reports before this release). We look at
// the composer's rendered content for either <br> nodes or multiple
// block children, matching the shape our fallback strategies build.
// Returns true when the payload had no \n (plain-line, nothing to
// verify) OR the composer has the expected break structure.
function arenaStructureMatches(target, insertedText) {
  const src = String(insertedText || '');
  const expectedLines = src.split('\n').length;
  if (expectedLines < 2) return true;   // single-line payload -- nothing to check.
  if (!target) return false;
  // Textareas/inputs preserve \n verbatim in .value.
  const tag = String(target.tagName || '').toUpperCase();
  if (tag === 'TEXTAREA' || tag === 'INPUT') {
    return String(target.value || '').includes('\n');
  }
  // ContentEditable: count <br> tags + block-level children as
  // rendered line separators. Both strategies our fallback chain
  // uses (paragraphFallback / directDomBlocks) build one or the
  // other. `expectedLines - 1` is the minimum break count for the
  // structure to look right; we accept anything >= half of that
  // (the composer may have collapsed empty lines, which is fine).
  const brCount = target.querySelectorAll('br').length;
  // Block-level child count -- <div>, <p>, <pre> siblings.
  const blockChildren = Array.from(target.children || [])
    .filter((c) => {
      const t = String(c.tagName || '').toUpperCase();
      return t === 'DIV' || t === 'P' || t === 'PRE';
    }).length;
  const observed = Math.max(brCount, blockChildren);
  const minExpected = Math.max(1, Math.floor((expectedLines - 1) / 2));
  return observed >= minExpected;
}

// Adaptive verify: check at 30ms, 80ms, then maxDelay. Most sites settle by
// the first probe, saving ~150ms vs a flat 180ms wait.
async function arenaVerifySettledInsert(adapter, before, text, target = null, maxDelayMs = 180) {
  const checkPoints = [30, 80, maxDelayMs];
  let elapsed = 0;

  for (let i = 0; i < checkPoints.length; i++) {
    const waitMs = (i === 0) ? checkPoints[0] : (checkPoints[i] - checkPoints[i - 1]);
    await arenaSleep(waitMs);
    elapsed += waitMs;
    const current = target?.isConnected ? target : arenaFindComposer(adapter);
    const after = arenaEditableText(current);
    const changed = after !== before;
    // v0.14.4: structure info is diagnostic only. The plan-ordering
    // in arenaInsertPlan decides which strategy runs first so we
    // don't need to fail verify to trigger a fallback here.
    const structOk = arenaStructureMatches(current, text);
    if (changed && arenaTextContainsInsert(after, text)) {
      return {changed: true, settled: true, structure_ok: structOk, verify_ms: elapsed};
    }
    if (i === checkPoints.length - 1) {
      return {
        changed,
        settled: changed && arenaTextContainsInsert(after, text),
        structure_ok: structOk,
        verify_ms: elapsed,
      };
    }
  }

  const current = target?.isConnected ? target : arenaFindComposer(adapter);
  const after = arenaEditableText(current);
  const changed = after !== before;
  const structOk = arenaStructureMatches(current, text);
  return {
    changed,
    settled: changed && arenaTextContainsInsert(after, text),
    structure_ok: structOk,
    verify_ms: elapsed,
  };
}

// ---------------------------------------------------------------------------
// Insertion primitives
// ---------------------------------------------------------------------------
function arenaTextareaInsert(target, text) {
  const value = target.value || '';
  const start = target.selectionStart ?? value.length;
  const end = target.selectionEnd ?? value.length;
  target.value = `${value.slice(0, start)}${text}${value.slice(end)}`;
  target.dispatchEvent(new Event('input', {bubbles: true}));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
}

function arenaParagraphInsert(text) {
  String(text).split('\n').forEach((line, index) => {
    if (index) document.execCommand('insertParagraph');
    if (line) document.execCommand('insertText', false, line);
  });
  return true;
}

function arenaPasteOnly(target, text) {
  try {
    const dt = new DataTransfer();
    dt.setData('text/plain', String(text));
    const event = new ClipboardEvent('paste', {
      bubbles: true,
      cancelable: true,
      clipboardData: dt,
    });
    return target.dispatchEvent(event) !== false;
  } catch (_e) {
    return false;
  }
}

function arenaEditableRange(target) {
  const selection = window.getSelection?.();
  let range = selection?.rangeCount ? selection.getRangeAt(0) : null;
  if (!range || !target.contains(range.commonAncestorContainer)) {
    range = document.createRange();
    range.selectNodeContents(target);
    range.collapse(false);
  }
  selection?.removeAllRanges();
  selection?.addRange(range);
  return range;
}

function arenaFinishDirectDomInsert(target, text) {
  target.dispatchEvent(new InputEvent('input', {
    bubbles: true,
    inputType: 'insertText',
    data: String(text),
  }));
  target.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
}

function arenaDirectDomText(target, text) {
  const range = arenaEditableRange(target);
  range.deleteContents();
  const fragment = document.createDocumentFragment();
  String(text).split('\n').forEach((line, index) => {
    if (index) fragment.appendChild(document.createElement('br'));
    if (line) fragment.appendChild(document.createTextNode(line));
  });
  range.insertNode(fragment);
  range.collapse(false);
  return arenaFinishDirectDomInsert(target, text);
}

function arenaDirectDomBlocks(target, text) {
  const range = arenaEditableRange(target);
  range.deleteContents();
  const fragment = document.createDocumentFragment();
  String(text).replace(/\r\n/g, '\n').split('\n').forEach((line) => {
    const block = document.createElement('div');
    if (line) {
      block.textContent = line;
    } else {
      block.appendChild(document.createElement('br'));
    }
    fragment.appendChild(block);
  });
  range.insertNode(fragment);
  range.collapse(false);
  return arenaFinishDirectDomInsert(target, text);
}

function arenaDirectDomPreWrap(target, text) {
  const range = arenaEditableRange(target);
  range.deleteContents();
  const span = document.createElement('span');
  span.style.whiteSpace = 'pre-wrap';
  span.textContent = String(text);
  range.insertNode(span);
  range.setStartAfter(span);
  range.collapse(true);
  return arenaFinishDirectDomInsert(target, text);
}

function arenaTryEditableInsert(target, text, selected) {
  if (selected === 'pasteOnly') return arenaPasteOnly(target, text);
  if (selected === 'paragraphFallback') return arenaParagraphInsert(text);
  if (selected === 'directDomText') return arenaDirectDomText(target, text);
  if (selected === 'directDomBlocks') return arenaDirectDomBlocks(target, text);
  if (selected === 'directDomPreWrap') return arenaDirectDomPreWrap(target, text);

  // Default: execCommand('insertText') with fallback to insertParagraph.
  let ok = false;
  try {
    ok = document.execCommand('insertText', false, String(text));
  } catch (_e) {
    ok = false;
  }
  return ok || arenaParagraphInsert(text);
}

function arenaUsesRichTextareaFastPath(target) {
  return arenaHost() === 'gemini.google.com' && !!target?.closest?.('rich-textarea');
}

function arenaInsertPlan(target, requested, text) {
  if (!target?.isContentEditable || requested !== 'auto') {
    return [requested === 'auto' ? 'nativeInsertText' : requested];
  }
  if (arenaUsesRichTextareaFastPath(target)) {
    return ['directDomPreWrap', 'nativeInsertText'];
  }
  // v0.14.4: for plain contenteditable composers (Perplexity, Kimi)
  // that collapse \n on execCommand('insertText'), skip the native
  // path entirely for multi-line payloads and go straight to
  // directDomBlocks. v0.14.3 chained nativeInsertText FIRST and then
  // tried to wipe + retry, but the wipe was unreliable on some
  // composers, so the operator saw a duplicate paste. ProseMirror
  // composers (Claude, Grok, Mistral) still honour insertText well
  // because ProseMirror translates it into structured content, so
  // they keep the native path.
  const hasNewlines = String(text || '').indexOf('\n') !== -1;
  const isProseMirror = !!(target.closest?.('.ProseMirror') || target.classList?.contains('ProseMirror'));
  if (hasNewlines && !isProseMirror) {
    // directDomBlocks builds <div><br></div> per line -- survives
    // even when execCommand is a no-op. paragraphFallback stays as
    // a secondary fallback for edge cases.
    return ['directDomBlocks', 'paragraphFallback', 'nativeInsertText'];
  }
  return ['nativeInsertText'];
}

// ---------------------------------------------------------------------------
// Composer / submit diagnostics (used by "Scan page" in the side panel)
// ---------------------------------------------------------------------------
function arenaButtonDiagnosticSample(button) {
  return {
    text: String(button?.innerText || button?.textContent || '')
      .replace(/\s+/g, ' ').trim().slice(0, 80),
    aria_label: button?.getAttribute?.('aria-label') || '',
    data_testid: button?.getAttribute?.('data-testid') || '',
    type: button?.getAttribute?.('type') || '',
    disabled: !!button?.disabled || button?.getAttribute?.('aria-disabled') === 'true',
    visible: typeof arenaElementVisible === 'function' ? arenaElementVisible(button) : true,
  };
}

function arenaComposerDiagnostics(adapter = getArenaAdapter()) {
  const composerInfo = typeof arenaComposerSelection === 'function'
    ? arenaComposerSelection(adapter)
    : {target: arenaFindComposer(adapter), candidates: 0, selected_selector: ''};
  const target = composerInfo.target;

  if (!target) {
    return {
      found: false,
      host: arenaHost(),
      adapter: adapter?.name || 'generic',
      candidates: composerInfo.candidates || 0,
      selected_selector: composerInfo.selected_selector || '',
      auto_plan: [],
    };
  }

  const submitInfo = typeof arenaSubmitButtonSelection === 'function'
    ? arenaSubmitButtonSelection(adapter, target)
    : {
        button: arenaFindSubmitButton(adapter, target),
        candidates: 0,
        selected_selector: '',
        scope: 'global',
        scope_buttons: 0,
        visible_scope_buttons: 0,
      };
  const composerText = arenaEditableText(target);
  const scopeRoot = target?.closest?.('form')
    || target?.closest?.('fieldset')
    || target?.closest?.('[role="form"], main, section, article, [role="dialog"]')
    || document;
  const submitScopeSamples = Array.from(scopeRoot.querySelectorAll?.('button') || [])
    .slice(0, 5)
    .map(arenaButtonDiagnosticSample);
  const submitSelectedSample = submitInfo.button
    ? arenaButtonDiagnosticSample(submitInfo.button)
    : null;
  const submitEnabled = !!submitInfo.button && !submitSelectedSample?.disabled;
  const submitExpectedAfterText = !composerText
    && submitInfo.scope_buttons > 0
    && !submitEnabled;

  let submitPhase;
  if (submitEnabled) {
    submitPhase = 'ready';
  } else if (submitSelectedSample) {
    submitPhase = submitExpectedAfterText ? 'awaiting-text' : 'disabled';
  } else if (submitExpectedAfterText) {
    submitPhase = 'awaiting-text';
  } else if (submitInfo.scope_buttons) {
    submitPhase = 'buttons-present-no-submit-match';
  } else {
    submitPhase = 'no-buttons';
  }

  let submitNote = '';
  if (!submitEnabled) {
    if (submitExpectedAfterText) {
      submitNote = submitSelectedSample
        ? 'submit is present but disabled until the composer has content'
        : 'submit may appear only after the composer has content';
    } else if (submitSelectedSample) {
      submitNote = 'submit button detected but currently disabled';
    } else if (submitInfo.scope_buttons) {
      submitNote = 'buttons exist in scope, but none matched submit selectors';
    } else {
      submitNote = 'no submit buttons currently rendered in composer scope';
    }
  }

  return {
    found: true,
    host: arenaHost(),
    adapter: adapter?.name || 'generic',
    tag: target.tagName || '',
    contenteditable: !!target.isContentEditable,
    rich_textarea: !!target.closest?.('rich-textarea'),
    prose_mirror: !!target.closest?.('.ProseMirror') || target.classList?.contains('ProseMirror'),
    aria_label: target.getAttribute?.('aria-label') || '',
    role: target.getAttribute?.('role') || '',
    text_length: composerText.length,
    has_text: !!composerText,
    candidates: composerInfo.candidates || 0,
    selected_selector: composerInfo.selected_selector || '',
    active_match: !!composerInfo.active_match,
    cached_match: !!composerInfo.cached_match,
    submit_found: !!submitInfo.button,
    submit_candidates: submitInfo.candidates || 0,
    submit_selector: submitInfo.selected_selector || '',
    submit_scope: submitInfo.scope || 'global',
    submit_scope_buttons: submitInfo.scope_buttons || 0,
    submit_scope_visible_buttons: submitInfo.visible_scope_buttons || 0,
    submit_scope_samples: submitScopeSamples,
    submit_selected_sample: submitSelectedSample,
    submit_enabled: submitEnabled,
    submit_expected_after_text: submitExpectedAfterText,
    submit_phase: submitPhase,
    submit_note: submitNote,
    auto_plan: arenaInsertPlan(target, 'auto'),
  };
}

// ---------------------------------------------------------------------------
// Top-level insert + insert-and-submit flows
// ---------------------------------------------------------------------------
async function arenaInsertResult(text, adapter = getArenaAdapter(), strategy = 'auto') {
  const started = performance.now();
  const composerInfo = typeof arenaComposerSelection === 'function'
    ? arenaComposerSelection(adapter)
    : {target: arenaFindComposer(adapter), candidates: 0, selected_selector: ''};
  const target = composerInfo.target;

  if (!target) {
    arenaSetInsertTiming({
      insert_ms: 0,
      verify_ms: 0,
      strategy,
      method: 'failed',
      error: 'composer_not_found',
      composer_candidates: composerInfo.candidates || 0,
      composer_selector: composerInfo.selected_selector || '',
    });
    return false;
  }

  window.__arenaLastInsertTarget = target;
  const requested = arenaNormalizeInsertStrategy(strategy);
  arenaFocusComposer(target);
  const attempts = [];

  for (const selected of arenaInsertPlan(target, requested, text)) {
    const before = arenaEditableText(target);
    let attempted = false;
    try {
      if (target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target.type === 'text')) {
        attempted = arenaTextareaInsert(target, text);
      } else if (target.isContentEditable) {
        attempted = arenaTryEditableInsert(target, text, selected);
      }
    } catch (_e) {
      attempted = false;
    }
    const insertMs = Math.round(performance.now() - started);
    const verify = attempted
      ? await arenaVerifySettledInsert(adapter, before, text, target)
      : {settled: false, verify_ms: 0};
    const ok = !!(attempted && verify.settled);
    attempts.push({
      strategy: selected,
      attempted: !!attempted,
      changed: !!verify.changed,
      settled: !!verify.settled,
      insert_ms: insertMs,
      verify_ms: verify.verify_ms,
    });
    if (ok) {
      arenaSetInsertTiming({
        insert_ms: insertMs,
        verify_ms: verify.verify_ms,
        total_ms: Math.round(performance.now() - started),
        strategy: selected,
        requested_strategy: requested,
        method: selected,
        changed: true,
        settled: true,
        attempts,
        composer_candidates: composerInfo.candidates || 0,
        composer_selector: composerInfo.selected_selector || '',
      });
      return true;
    }
    // v0.14.4: any change counts as "done" -- prevents duplicate
    // paste when the wipe-between-strategies chain gave two attempts
    // that both landed content (v0.14.3 regression). Plan-ordering
    // in arenaInsertPlan now decides which strategy runs first based
    // on composer type, so we no longer need the runtime fallback
    // dance. If the first strategy failed to change anything at all,
    // we still fall through to the next entry in the plan.
    if (requested === 'auto' && attempted && verify.changed) break;
  }

  const last = attempts[attempts.length - 1]
    || {strategy: requested, insert_ms: 0, verify_ms: 0, settled: false};
  arenaSetInsertTiming({
    insert_ms: last.insert_ms,
    verify_ms: last.verify_ms,
    total_ms: Math.round(performance.now() - started),
    strategy: last.strategy,
    requested_strategy: requested,
    method: 'failed',
    changed: !!last.changed,
    settled: false,
    attempts,
    composer_candidates: composerInfo.candidates || 0,
    composer_selector: composerInfo.selected_selector || '',
  });
  return false;
}

async function arenaInsertAndSubmit(text, adapter = getArenaAdapter(), strategy = 'auto') {
  const started = performance.now();
  const inserted = await arenaInsertResult(text, adapter, strategy);
  const insertTiming = window.__arenaLastInsertTiming || {};

  if (!inserted) {
    return {
      ok: false, inserted: false, submitted: false, ...insertTiming,
      total_ms: Math.round(performance.now() - started),
    };
  }

  const composerInfo = typeof arenaComposerSelection === 'function'
    ? arenaComposerSelection(adapter)
    : {target: arenaFindComposer(adapter)};
  const deadline = Date.now() + 1500;
  let submitInfo = {button: null, candidates: 0, selected_selector: '', scope: 'global'};

  // Adaptive polling: fast at the beginning, then back off. Most sites reveal
  // the enabled submit button within one or two ticks after insert.
  const pollDelays = [20, 20, 40, 40, 80, 80, 100, 100];
  let pollIndex = 0;

  while (Date.now() < deadline) {
    submitInfo = typeof arenaSubmitButtonSelection === 'function'
      ? arenaSubmitButtonSelection(adapter, composerInfo.target)
      : {
          button: arenaFindSubmitButton(adapter, composerInfo.target),
          candidates: 0,
          selected_selector: '',
          scope: 'global',
        };
    const submit = submitInfo.button;
    if (submit && !submit.disabled && submit.getAttribute('aria-disabled') !== 'true') {
      submit.click();
      const submitWaitMs = Math.round(performance.now() - started) - (insertTiming.total_ms || 0);
      return {
        ok: true, inserted: true, submitted: true, ...insertTiming,
        submit_wait_ms: submitWaitMs,
        submit_candidates: submitInfo.candidates || 0,
        submit_selector: submitInfo.selected_selector || '',
        submit_scope: submitInfo.scope || 'global',
        total_ms: Math.round(performance.now() - started),
      };
    }
    const delay = pollDelays[Math.min(pollIndex, pollDelays.length - 1)];
    pollIndex++;
    await arenaSleep(delay);
  }

  // v0.14.2: Enter-key fallback. On sites where the submit button lives
  // outside every ancestor we can score (Kimi, Perplexity, sometimes
  // Copilot), the polling loop above cannot find a click target even
  // after the composer has content. Dispatching a synthetic Enter
  // keydown on the composer is the fallback almost every chat UI
  // honours (Shift+Enter usually inserts a newline, plain Enter
  // submits). Not fired when a submit button exists but is still
  // disabled -- that means the site is validating input and clicking
  // would fail anyway; we should not spam Enter.
  const enterTarget = composerInfo.target;
  const noSelector = !submitInfo.selected_selector;
  if (enterTarget && noSelector) {
    try {
      // v0.14.4: focus target first + fire on document too. Many
      // sites (Qwen, DeepSeek) listen for Enter on the composer's
      // keyboard-event delegate rather than the composer itself,
      // so dispatching only on enterTarget silently missed.
      try { enterTarget.focus(); } catch (_) {}
      const opts = {
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13,
        bubbles: true, cancelable: true, composed: true,
      };
      // Fire on the composer (specific listeners) and on document
      // (delegated listeners some SPAs use).
      for (const evt of ['keydown', 'keypress', 'keyup']) {
        enterTarget.dispatchEvent(new KeyboardEvent(evt, opts));
      }
      // Additional retry after a short delay -- some composers
      // debounce their submit handler and would swallow the very
      // first keystroke that arrived while insert timing was still
      // settling.
      await arenaSleep(120);
      for (const evt of ['keydown', 'keypress', 'keyup']) {
        enterTarget.dispatchEvent(new KeyboardEvent(evt, opts));
      }
      return {
        ok: true, inserted: true, submitted: true, ...insertTiming,
        submit_wait_ms: 1500,
        submit_candidates: 0,
        submit_selector: 'enter-key-fallback',
        submit_scope: 'keyboard',
        total_ms: Math.round(performance.now() - started),
      };
    } catch (_err) { /* fall through to the not-submitted return */ }
  }

  return {
    ok: true, inserted: true, submitted: false, ...insertTiming,
    submit_wait_ms: 1500,
    submit_candidates: submitInfo.candidates || 0,
    submit_selector: submitInfo.selected_selector || '',
    submit_scope: submitInfo.scope || 'global',
    total_ms: Math.round(performance.now() - started),
  };
}
