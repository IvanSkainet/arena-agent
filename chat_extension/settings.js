const ARENA_MODE_DEFAULTS = {
  autoPreview: false,
  autoExecuteSafe: false,
  autoInsertResult: false,
  autoSubmitResult: false,
};

function arenaNormalizeModes(data) {
  const input = data || {};
  return {
    autoPreview: !!input.autoPreview,
    autoExecuteSafe: !!input.autoExecuteSafe,
    autoInsertResult: !!input.autoInsertResult,
    autoSubmitResult: !!input.autoSubmitResult,
  };
}

function arenaModeSummary(modes) {
  const active = Object.entries(arenaNormalizeModes(modes)).filter((entry) => entry[1]).map((entry) => entry[0]);
  return active.length ? active.join(', ') : 'manual-confirm';
}
