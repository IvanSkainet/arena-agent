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
function arenaInsertMarker(text) {
  return String(text || '').replace(/\s+/g, ' ').trim().slice(0, 80);
}
function arenaTextContainsInsert(text, inserted) {
  const marker = arenaInsertMarker(inserted);
  const haystack = String(text || '').replace(/\s+/g, ' ').trim();
  return !!marker && haystack.includes(marker);
}
async function arenaVerifySettledInsert(adapter, before, text, delayMs = 180) {
  await arenaSleep(delayMs);
  const target = arenaFindComposer(adapter);
  const after = arenaEditableText(target);
  return {settled: after !== before && arenaTextContainsInsert(after, text), verify_ms: delayMs};
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
async function arenaInsertResult(text, adapter = getArenaAdapter(), strategy = 'auto') {
  const started = performance.now();
  const target = arenaFindComposer(adapter);
  if (!target) {
    arenaSetInsertTiming({insert_ms: 0, verify_ms: 0, strategy, method: 'failed', error: 'composer_not_found'});
    return false;
  }
  const requested = arenaNormalizeInsertStrategy(strategy);
  const selected = requested === 'auto' ? 'nativeInsertText' : requested;
  arenaFocusComposer(target);
  const before = arenaEditableText(target);
  let attempted = false;
  try {
    attempted = (target.tagName === 'TEXTAREA' || (target.tagName === 'INPUT' && target.type === 'text'))
      ? arenaTextareaInsert(target, text)
      : (target.isContentEditable && arenaTryEditableInsert(target, text, selected));
  } catch (_e) { attempted = false; }
  const insertMs = Math.round(performance.now() - started);
  const verify = attempted ? await arenaVerifySettledInsert(adapter, before, text) : {settled: false, verify_ms: 0};
  const ok = !!(attempted && verify.settled);
  arenaSetInsertTiming({
    insert_ms: insertMs,
    verify_ms: verify.verify_ms,
    total_ms: Math.round(performance.now() - started),
    strategy: selected,
    method: ok ? selected : 'failed',
    settled: !!verify.settled,
  });
  return ok;
}

async function arenaInsertAndSubmit(text, adapter = getArenaAdapter(), strategy = 'auto') {
  const started = performance.now();
  const inserted = await arenaInsertResult(text, adapter, strategy);
  const insertTiming = window.__arenaLastInsertTiming || {};
  if (!inserted) return {ok: false, inserted: false, submitted: false, ...insertTiming, total_ms: Math.round(performance.now() - started)};
  const deadline = Date.now() + 1500;
  while (Date.now() < deadline) {
    const submit = arenaFindSubmitButton(adapter);
    if (submit && !submit.disabled && submit.getAttribute('aria-disabled') !== 'true') {
      submit.click();
      return {ok: true, inserted: true, submitted: true, ...insertTiming, total_ms: Math.round(performance.now() - started)};
    }
    await arenaSleep(40);
  }
  return {ok: true, inserted: true, submitted: false, ...insertTiming, total_ms: Math.round(performance.now() - started)};
}
