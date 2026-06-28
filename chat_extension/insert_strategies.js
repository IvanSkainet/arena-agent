function arenaSetInsertTiming(timing) {
  window.__arenaLastInsertTiming = timing;
}
function arenaNormalizeInsertStrategy(strategy) {
  return ['auto', 'nativeInsertText', 'paragraphFallback', 'pasteOnly', 'directDomText', 'directDomBlocks'].includes(strategy) ? strategy : 'auto';
}
function arenaEditableText(target) {
  return String(target?.textContent || '').replace(/\s+/g, ' ').trim();
}
function arenaEditableChanged(before, target, text) {
  const after = arenaEditableText(target);
  if (after === before) return false;
  const marker = String(text || '').replace(/\s+/g, ' ').trim().slice(0, 80);
  return !marker || after.includes(marker) || after.length > before.length;
}
function arenaInsertResult(text, adapter = getArenaAdapter(), strategy = 'auto') {
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
  if (target.isContentEditable) return arenaInsertIntoEditable(target, text, strategy);
  return false;
}

function arenaComposerText(adapter = getArenaAdapter()) {
  const target = arenaFindComposer(adapter);
  if (!target) return '';
  return (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') ? (target.value || '') : (target.textContent || '');
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
function arenaInsertIntoEditable(target, text, strategy = 'auto') {
  const started = performance.now();
  const requested = arenaNormalizeInsertStrategy(strategy);
  const selected = requested === 'auto' ? 'nativeInsertText' : requested;
  arenaFocusComposer(target);
  const before = arenaEditableText(target);
  let ok = false;
  if (selected === 'pasteOnly') ok = arenaPasteOnly(target, text);
  else if (selected === 'paragraphFallback') ok = arenaParagraphInsert(text);
  else if (selected === 'directDomText') {
    try { ok = arenaDirectDomText(target, text); } catch (_e) { ok = false; }
  } else if (selected === 'directDomBlocks') {
    try { ok = arenaDirectDomBlocks(target, text); } catch (_e) { ok = false; }
  } else {
    try { ok = document.execCommand('insertText', false, String(text)); } catch (_e) { ok = false; }
    if (!ok) ok = arenaParagraphInsert(text);
  }
  ok = ok && arenaEditableChanged(before, target, text);
  arenaSetInsertTiming({insert_ms: Math.round(performance.now() - started), strategy: selected, method: ok ? selected : 'failed'});
  return ok;
}

async function arenaInsertAndSubmit(text, adapter = getArenaAdapter(), strategy = 'auto') {
  const started = performance.now();
  const inserted = arenaInsertResult(text, adapter, strategy);
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
