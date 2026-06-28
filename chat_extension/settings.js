const ARENA_MODE_DEFAULTS = {
  autoPreview: false,
  autoExecuteSafe: false,
  autoInsertResult: false,
  autoSubmitResult: false,
  insertStrategy: 'auto',
};

function arenaNormalizeModes(data) {
  const input = data || {};
  const allowed = ['auto', 'nativeInsertText', 'paragraphFallback', 'pasteOnly', 'directDomText'];
  return {
    autoPreview: !!input.autoPreview,
    autoExecuteSafe: !!input.autoExecuteSafe,
    autoInsertResult: !!input.autoInsertResult,
    autoSubmitResult: !!input.autoSubmitResult,
    insertStrategy: allowed.includes(input.insertStrategy) ? input.insertStrategy : 'auto',
  };
}

function arenaModeSummary(modes) {
  const normalized = arenaNormalizeModes(modes);
  const active = Object.entries(normalized).filter((entry) => entry[0] !== 'insertStrategy' && entry[1]).map((entry) => entry[0]);
  if (normalized.insertStrategy !== 'auto') active.push(`insertStrategy=${normalized.insertStrategy}`);
  return active.length ? active.join(', ') : 'manual-confirm';
}
