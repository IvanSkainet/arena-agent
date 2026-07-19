const ARENA_MODE_DEFAULTS = {
  autoPreview: false,
  autoExecuteSafe: false,
  autoInsertResult: false,
  autoSubmitResult: false,
  insertStrategy: 'auto',
  // v0.14.15 (v4.50.5): operator-controllable toolbar dedup toggle.
  // Default `true` restores the pre-v0.14.14 behaviour Ivan preferred:
  // one toolbar per unique semantic tool block, sibling duplicates
  // silently skipped. Setting this to `false` reverts to the "one
  // toolbar per host" behaviour that shipped in v0.14.14, useful for
  // sites where the operator explicitly wants to see every candidate
  // (Claude with call_id 1..N, Mistral echoes).
  dedupSemantic: true,
  // v0.14.28 (v4.50.18): opt-in for the generic-adapter active
  // mode. When FALSE (default) the generic adapter stays
  // effectively passive on unlisted sites -- eliminates any risk
  // of false-positive mounts on documentation/README pages.
  // Operator can flip this ON via Advanced / experimental when
  // they want to try the extension on an unlisted chat site.
  enableGenericAdapter: false,
  // v0.14.29 (v4.51.0): fold inserted tool-result blocks in chat
  // history into a `<details>` summary so the scrollback stays
  // readable. Default TRUE. Turn OFF via Advanced/experimental
  // if the site's own CSS clashes with `<details>` styling.
  collapseToolResults: true,
};

function arenaNormalizeModes(data) {
  const input = data || {};
  const allowed = ['auto', 'nativeInsertText', 'paragraphFallback', 'pasteOnly', 'directDomText', 'directDomBlocks', 'directDomPreWrap'];
  return {
    autoPreview: !!input.autoPreview,
    autoExecuteSafe: !!input.autoExecuteSafe,
    autoInsertResult: !!input.autoInsertResult,
    autoSubmitResult: !!input.autoSubmitResult,
    insertStrategy: allowed.includes(input.insertStrategy) ? input.insertStrategy : 'auto',
    // v0.14.15: default TRUE, treat any explicit `false` as off.
    dedupSemantic: input.dedupSemantic === undefined ? true : !!input.dedupSemantic,
    // v0.14.28 (v4.50.18): default FALSE. Explicit true required.
    enableGenericAdapter: !!input.enableGenericAdapter,
    // v0.14.29 (v4.51.0): default TRUE, undefined -> TRUE for
    // upgrade continuity.
    collapseToolResults: input.collapseToolResults === undefined ? true : !!input.collapseToolResults,
  };
}

function arenaModeSummary(modes) {
  const normalized = arenaNormalizeModes(modes);
  const active = Object.entries(normalized).filter((entry) => entry[0] !== 'insertStrategy' && entry[1]).map((entry) => entry[0]);
  if (normalized.insertStrategy !== 'auto') active.push(`insertStrategy=${normalized.insertStrategy}`);
  return active.length ? active.join(', ') : 'manual-confirm';
}


