function arenaInsertScriptVersion() {
  return '0.13.24';
}
function arenaSetInsertTiming(timing) {
  window.__arenaLastInsertTiming = timing;
}
function arenaNormalizeInsertStrategy(strategy) {
  return ['auto', 'nativeInsertText', 'paragraphFallback', 'pasteOnly', 'directDomText', 'directDomBlocks', 'directDomPreWrap'].includes(strategy) ? strategy : 'auto';
}
function arenaSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
function arenaComposerText(adapter = getArenaAdapter()) {
  const target = arenaFindComposer(adapter);
  if (!target) return '';
  return (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') ? (target.value || '') : (target.textContent || '');
}
function arenaEditableText(target) {
  return String(target?.textContent || target?.value || '').replace(/\s+/g, ' ').trim();
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
  return {normalized: normalized.slice(0, 80), compact: compact.slice(0, 80)};
}
function arenaTextContainsInsert(text, inserted) {
  const markers = arenaInsertMarkers(inserted);
  const normalized = arenaNormalizeTextForVerify(text);
  const compact = arenaCompactTextForVerify(text);
  return (!!markers.normalized && normalized.includes(markers.normalized))
    || (!!markers.compact && compact.includes(markers.compact));
}
async function arenaVerifySettledInsert(adapter, before, text, target = null, maxDelayMs = 180) {
  // Adaptive: check early at 30ms, 80ms, then at maxDelay
  const checkPoints = [30, 80, maxDelayMs];
  let elapsed = 0;
  for (let i = 0; i < checkPoints.length; i++) {
    const waitMs = (i === 0) ? checkPoints[0] : (checkPoints[i] - checkPoints[i - 1]);
    await arenaSleep(waitMs);
    elapsed += waitMs;
    const current = target?.isConnected ? target : arenaFindComposer(adapter);
    const after = arenaEditableText(current);
    const changed = after !== before;
    if (changed && arenaTextContainsInsert(after, text)) {
      return {changed: true, settled: true, verify_ms: elapsed};
    }
    if (i === checkPoints.length - 1) {
      return {changed, settled: changed && arenaTextContainsInsert(after, text), verify_ms: elapsed};
    }
  }
  const current = target?.isConnected ? target : arenaFindComposer(adapter);
  const after = arenaEditableText(current);
  const changed = after !== before;
  return {changed, settled: changed && arenaTextContainsInsert(after, text), verify_ms: elapsed};
}
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
    return target.dispatchEvent(new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData: dt})) !== false;
  } catch (_e) { return false; }
}
function arenaEditableRange(target) {
  const selection = window.getSelection?.();
  let range = selection?.rangeCount ? selection.getRangeAt(0) : null;
  if (!range || !target.contains(range.commonAncestorContainer)) {
    range = document.createRange(); range.selectNodeContents(target); range.collapse(false);
  }
  selection?.removeAllRanges(); selection?.addRange(range);
  return range;
}
function arenaFinishDirectDomInsert(target, text) {
  target.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: String(text)}));
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
  range.insertNode(fragment); range.collapse(false);
  return arenaFinishDirectDomInsert(target, text);
}
function arenaDirectDomBlocks(target, text) {
  const range = arenaEditableRange(target);
  range.deleteContents();
  const fragment = document.createDocumentFragment();
  String(text).replace(/\r\n/g, '\n').split('\n').forEach((line) => {
    const block = document.createElement('div');
    if (line) block.textContent = line; else block.appendChild(document.createElement('br'));
    fragment.appendChild(block);
  });
  range.insertNode(fragment); range.collapse(false);
  return arenaFinishDirectDomInsert(target, text);
}
function arenaDirectDomPreWrap(target, text) {
  const range = arenaEditableRange(target);
  range.deleteContents();
  const span = document.createElement('span');
  span.style.whiteSpace = 'pre-wrap';
  span.textContent = String(text);
  range.insertNode(span); range.setStartAfter(span); range.collapse(true);
  return arenaFinishDirectDomInsert(target, text);
}
function arenaTryEditableInsert(target, text, selected) {
  if (selected === 'pasteOnly') return arenaPasteOnly(target, text);
  if (selected === 'paragraphFallback') return arenaParagraphInsert(text);
  if (selected === 'directDomText') return arenaDirectDomText(target, text);
  if (selected === 'directDomBlocks') return arenaDirectDomBlocks(target, text);
  if (selected === 'directDomPreWrap') return arenaDirectDomPreWrap(target, text);
  let ok = false;
  try { ok = document.execCommand('insertText', false, String(text)); } catch (_e) { ok = false; }
  return ok || arenaParagraphInsert(text);
}
function arenaUsesRichTextareaFastPath(target) {
  return arenaHost() === 'gemini.google.com' && !!target?.closest?.('rich-textarea');
}
function arenaInsertPlan(target, requested) {
  if (!target?.isContentEditable || requested !== 'auto') return [requested === 'auto' ? 'nativeInsertText' : requested];
  return arenaUsesRichTextareaFastPath(target) ? ['directDomPreWrap', 'nativeInsertText'] : ['nativeInsertText'];
}
function arenaButtonDiagnosticSample(button) {
  return {
    text: String(button?.innerText || button?.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80),
    aria_label: button?.getAttribute?.('aria-label') || '',
    data_testid: button?.getAttribute?.('data-testid') || '',
    type: button?.getAttribute?.('type') || '',
    disabled: !!button?.disabled || button?.getAttribute?.('aria-disabled') === 'true',
    visible: typeof arenaElementVisible === 'function' ? arenaElementVisible(button) : true,
  };
}
function arenaComposerDiagnostics(adapter = getArenaAdapter()) {
  const composerInfo = typeof arenaComposerSelection === 'function' ? arenaComposerSelection(adapter) : {target: arenaFindComposer(adapter), candidates: 0, selected_selector: ''};
  const target = composerInfo.target;
  if (!target) return {
    found: false,
    host: arenaHost(),
    adapter: adapter?.name || 'generic',
    candidates: composerInfo.candidates || 0,
    selected_selector: composerInfo.selected_selector || '',
    auto_plan: [],
  };
  const submitInfo = typeof arenaSubmitButtonSelection === 'function' ? arenaSubmitButtonSelection(adapter, target) : {button: arenaFindSubmitButton(adapter, target), candidates: 0, selected_selector: '', scope: 'global', scope_buttons: 0, visible_scope_buttons: 0};
  const composerText = arenaEditableText(target);
  const scopeRoot = target?.closest?.('form') || target?.closest?.('fieldset') || target?.closest?.('[role="form"], main, section, article, [role="dialog"]') || document;
  const submitScopeSamples = Array.from(scopeRoot.querySelectorAll?.('button') || []).slice(0, 5).map(arenaButtonDiagnosticSample);
  const submitSelectedSample = submitInfo.button ? arenaButtonDiagnosticSample(submitInfo.button) : null;
  const submitEnabled = !!submitInfo.button && !submitSelectedSample?.disabled;
  const submitExpectedAfterText = (!composerText && submitInfo.scope_buttons > 0 && !submitEnabled);
  const submitPhase = submitEnabled
    ? 'ready'
    : (submitSelectedSample
      ? (submitExpectedAfterText ? 'awaiting-text' : 'disabled')
      : (submitExpectedAfterText ? 'awaiting-text' : (submitInfo.scope_buttons ? 'buttons-present-no-submit-match' : 'no-buttons')));
  const submitNote = submitEnabled ? '' : (submitExpectedAfterText
    ? (submitSelectedSample ? 'submit is present but disabled until the composer has content' : 'submit may appear only after the composer has content')
    : (submitSelectedSample
      ? 'submit button detected but currently disabled'
      : (submitInfo.scope_buttons ? 'buttons exist in scope, but none matched submit selectors' : 'no submit buttons currently rendered in composer scope')));
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
async function arenaInsertResult(text, adapter = getArenaAdapter(), strategy = 'auto') {
  const started = performance.now();
  const composerInfo = typeof arenaComposerSelection === 'function' ? arenaComposerSelection(adapter) : {target: arenaFindComposer(adapter), candidates: 0, selected_selector: ''};
  const target = composerInfo.target;
  if (!target) {
    arenaSetInsertTiming({insert_ms: 0, verify_ms: 0, strategy, method: 'failed', error: 'composer_not_found', composer_candidates: composerInfo.candidates || 0, composer_selector: composerInfo.selected_selector || ''});
    return false;
  }
  const requested = arenaNormalizeInsertStrategy(strategy);
  arenaFocusComposer(target);
  const attempts = [];
  for (const selected of arenaInsertPlan(target, requested)) {
    const before = arenaEditableText(target);
    let attempted = false;
    try {
      attempted = (target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target.type === 'text'))
        ? arenaTextareaInsert(target, text)
        : (target.isContentEditable && arenaTryEditableInsert(target, text, selected));
    } catch (_e) { attempted = false; }
    const insertMs = Math.round(performance.now() - started);
    const verify = attempted ? await arenaVerifySettledInsert(adapter, before, text, target) : {settled: false, verify_ms: 0};
    const ok = !!(attempted && verify.settled);
    attempts.push({strategy: selected, attempted: !!attempted, changed: !!verify.changed, settled: !!verify.settled, insert_ms: insertMs, verify_ms: verify.verify_ms});
    if (ok) {
      arenaSetInsertTiming({insert_ms: insertMs, verify_ms: verify.verify_ms, total_ms: Math.round(performance.now() - started), strategy: selected, requested_strategy: requested, method: selected, changed: true, settled: true, attempts, composer_candidates: composerInfo.candidates || 0, composer_selector: composerInfo.selected_selector || ''});
      return true;
    }
    if (requested === 'auto' && attempted && verify.changed) break;
  }
  const last = attempts[attempts.length - 1] || {strategy: requested, insert_ms: 0, verify_ms: 0, settled: false};
  arenaSetInsertTiming({insert_ms: last.insert_ms, verify_ms: last.verify_ms, total_ms: Math.round(performance.now() - started), strategy: last.strategy, requested_strategy: requested, method: 'failed', changed: !!last.changed, settled: false, attempts, composer_candidates: composerInfo.candidates || 0, composer_selector: composerInfo.selected_selector || ''});
  return false;
}

async function arenaInsertAndSubmit(text, adapter = getArenaAdapter(), strategy = 'auto') {
  const started = performance.now();
  const inserted = await arenaInsertResult(text, adapter, strategy);
  const insertTiming = window.__arenaLastInsertTiming || {};
  if (!inserted) return {ok: false, inserted: false, submitted: false, ...insertTiming, total_ms: Math.round(performance.now() - started)};
  const composerInfo = typeof arenaComposerSelection === 'function' ? arenaComposerSelection(adapter) : {target: arenaFindComposer(adapter)};
  const deadline = Date.now() + 1500;
  let submitInfo = {button: null, candidates: 0, selected_selector: '', scope: 'global'};
  // Adaptive polling: 20ms, 20ms, 40ms, 40ms, 80ms, 80ms...
  const pollDelays = [20, 20, 40, 40, 80, 80, 100, 100];
  let pollIndex = 0;
  while (Date.now() < deadline) {
    submitInfo = typeof arenaSubmitButtonSelection === 'function' ? arenaSubmitButtonSelection(adapter, composerInfo.target) : {button: arenaFindSubmitButton(adapter, composerInfo.target), candidates: 0, selected_selector: '', scope: 'global'};
    const submit = submitInfo.button;
    if (submit && !submit.disabled && submit.getAttribute('aria-disabled') !== 'true') {
      submit.click();
      const submitWaitMs = Math.round(performance.now() - started) - (insertTiming.total_ms || 0);
      return {ok: true, inserted: true, submitted: true, ...insertTiming, submit_wait_ms: submitWaitMs, submit_candidates: submitInfo.candidates || 0, submit_selector: submitInfo.selected_selector || '', submit_scope: submitInfo.scope || 'global', total_ms: Math.round(performance.now() - started)};
    }
    const delay = pollDelays[Math.min(pollIndex, pollDelays.length - 1)];
    pollIndex++;
    await arenaSleep(delay);
  }
  return {ok: true, inserted: true, submitted: false, ...insertTiming, submit_wait_ms: 1500, submit_candidates: submitInfo.candidates || 0, submit_selector: submitInfo.selected_selector || '', submit_scope: submitInfo.scope || 'global', total_ms: Math.round(performance.now() - started)};
}
