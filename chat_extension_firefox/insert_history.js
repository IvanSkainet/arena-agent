function arenaInsertHistoryContentVersion() {
  try { return (typeof ARENA_CONTENT_SCRIPT_VERSION !== 'undefined' ? ARENA_CONTENT_SCRIPT_VERSION : chrome.runtime.getManifest?.().version) || 'unknown'; } catch (_e) { return 'unknown'; }
}
function arenaInsertEventTiming(state) {
  const timing = state || {};
  return {
    ok: !!timing.ok,
    strategy: timing.strategy || timing.method || '',
    requested_strategy: timing.requested_strategy || '',
    total_ms: timing.total_ms ?? timing.insert_ms ?? null,
    verify_ms: timing.verify_ms ?? null,
    submitted: !!timing.submitted,
    manifest_version: (typeof arenaExtensionVersion === 'function' ? arenaExtensionVersion() : chrome.runtime.getManifest?.().version || 'unknown'),
    content_version: arenaInsertHistoryContentVersion(),
    insert_script_version: (typeof arenaInsertScriptVersion === 'function' ? arenaInsertScriptVersion() : 'unknown'),
  };
}
function arenaInsertEventDetail(kind, state, mode = 'manual') {
  const timing = arenaInsertEventTiming(state);
  const strategy = timing.strategy || timing.requested_strategy || 'unknown';
  const ms = Number.isFinite(timing.total_ms) ? ` in ${timing.total_ms}ms` : '';
  const prefix = mode === 'auto' ? 'auto ' : '';
  if (!timing.ok) return `${prefix}${kind} failed via ${strategy}`;
  if (kind === 'submit') return `${prefix}submitted via ${strategy}${ms}`;
  return `${prefix}inserted via ${strategy}${ms}`;
}
async function arenaRecordInsertEvent(kind, request, adapter, state, mode = 'manual') {
  try {
    await chrome.runtime.sendMessage({type: 'arena.insertEvent', body: {
      kind,
      detail: arenaInsertEventDetail(kind, state, mode),
      site: request?.site?.origin || location.origin,
      adapter: adapter?.name || request?.site?.adapter || 'generic',
      fingerprint: request?.message?.fingerprint || '',
      ok: !!state?.ok,
      payload: request,
      response: arenaInsertEventTiming(state),
    }});
  } catch (_e) { /* history recording must not break insertion */ }
}
