const ARENA_BLOCK_PATTERNS = [
  {kind: 'arena-tool', re: /```arena-tool\s*([\s\S]*?)```/g},
  {kind: 'jsonl', re: /```jsonl\s*([\s\S]*?)```/g},
  {kind: 'json', re: /```json\s*([\s\S]*?)```/g},
  // v0.14.32 (v4.51.3): some sites strip our custom `arena-tool`
  // language tag and the model falls back to a plain ``` fence.
  // Accept an unlabeled fence and let arenaPayloadFromJson /
  // arenaPayloadFromJsonl figure out the flavor.
  {kind: 'fence', re: /```\s*\n([\s\S]*?)```/g},
];

function arenaSplitJsonObjects(text) {
  const out = [];
  const src = String(text || '');
  let depth = 0;
  let start = -1;
  let inStr = false;
  let esc = false;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (inStr) {
      if (esc) { esc = false; }
      else if (ch === '\\') { esc = true; }
      else if (ch === '"') { inStr = false; }
      continue;
    }
    if (ch === '"') { inStr = true; continue; }
    if (ch === '{') { if (depth === 0) start = i; depth++; }
    else if (ch === '}') { depth--; if (depth === 0 && start >= 0) { out.push(src.slice(start, i + 1)); start = -1; } }
  }
  return out;
}

function arenaParseJsonLines(text) {
  const cleaned = String(text || '').replace(/^\s*(json|jsonl)\b/i, '');
  const rows = [];
  cleaned.split(/\r?\n/).forEach((line) => {
    const raw = line.trim();
    if (!raw) return;
    try { rows.push(JSON.parse(raw)); return; } catch {}
    arenaSplitJsonObjects(raw).forEach((chunk) => { try { rows.push(JSON.parse(chunk)); } catch {} });
  });
  if (!rows.length) arenaSplitJsonObjects(cleaned).forEach((chunk) => { try { rows.push(JSON.parse(chunk)); } catch {} });
  return rows;
}

function arenaPayloadFromJsonl(text) {
  const rows = arenaParseJsonLines(text);
  const calls = [];
  let current = null;
  rows.forEach((row) => {
    const type = String(row?.type || '').trim();
    if (type === 'function_call_start') {
      current = {
        id: String(row.call_id || row.id || `call_${calls.length + 1}`),
        tool: String(row.name || row.tool || '').trim(),
        arguments: {},
        source_format: 'mcp-superassistant-jsonl',
      };
      // v0.14.2: some models emit arguments inline on the start
      // event (a valid MCP SuperAssistant variant). Previously the
      // parser only listened for separate `type:"parameter"` rows
      // and silently dropped inline args, which surfaced as
      // "ERROR: missing 'path' argument" from the bridge when the
      // caller thought they had passed one.
      if (row.arguments && typeof row.arguments === 'object' && !Array.isArray(row.arguments)) {
        for (const [k, v] of Object.entries(row.arguments)) {
          current.arguments[k] = v;
        }
      }
      // Same story for a top-level `params` alias -- some models
      // emit that shape too. Treated as merge-in, so an explicit
      // `parameter` row later still wins.
      if (row.params && typeof row.params === 'object' && !Array.isArray(row.params)) {
        for (const [k, v] of Object.entries(row.params)) {
          if (!(k in current.arguments)) current.arguments[k] = v;
        }
      }
      return;
    }
    if (!current) return;
    if (type === 'description') {
      current.description = String(row.text || row.description || '');
      return;
    }
    if (type === 'parameter') {
      const key = String(row.key || row.name || '').trim();
      if (key) current.arguments[key] = row.value;
      return;
    }
    if (type === 'function_call_end') {
      if (current.tool) calls.push(current);
      current = null;
    }
  });
  return calls.length ? {bridge: 'arena', version: 1, calls} : null;
}

function arenaPayloadFromJson(text) {
  try {
    const parsed = JSON.parse(text);
    if (parsed?.bridge === 'arena' && Array.isArray(parsed.calls)) return parsed;
    if (parsed?.type === 'function_call_start') return arenaPayloadFromJsonl(text);
    // v0.14.32 (v4.51.3): normalize a single-call variant that
    // some models emit -- `{"tool": "...", "arguments": {...}}`
    // without the outer envelope. Also accepts `name` / `params`
    // aliases (mirrors arenaPayloadFromJsonl parameter handling).
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const toolName = String(parsed.tool || parsed.name || parsed.function || '').trim();
      if (toolName) {
        const args = (parsed.arguments && typeof parsed.arguments === 'object' && !Array.isArray(parsed.arguments))
          ? parsed.arguments
          : (parsed.params && typeof parsed.params === 'object' && !Array.isArray(parsed.params))
            ? parsed.params
            : {};
        const id = String(parsed.id || parsed.call_id || 'call_1');
        return {bridge: 'arena', version: 1, calls: [{id, tool: toolName, arguments: args, source_format: 'arena-single'}]};
      }
    }
  } catch {}
  return null;
}
function arenaLooksLikeBridgeInstructions(text) {
  const source = String(text || '');
  return source.includes('You can request local tool execution through the Arena Chat Bridge browser extension.')
    || source.includes('Only emit a tool block when you need the local Arena bridge to run a tool.')
    // v0.14.32 (v4.51.3): the v4.51.2/3 catalog preamble uses this
    // canonical <SYSTEM> block header -- treat the AI echoing the
    // instructions as documentation, not a real call.
    || source.includes('You are connected to a local Arena Chat Bridge that can execute tools')
    || source.includes('Function Call Structure — Arena format');
}

// v0.14.32 (v4.51.3): scan the whole source for bare
// `{"bridge":"arena", ...}` envelopes that the model emitted
// WITHOUT any surrounding code fence. Ivan verbatim from the
// v4.51.2 test report: `{"bridge":"arena","version":1,"calls":[...]}`
// pasted straight into chat by the model. Fenced blocks were
// already handled above; this catches the "no fence at all"
// regression. Also merges any bare JSONL sequence in the same
// message so both formats coexist.
function _scanBareArenaEnvelopes(source) {
  const found = [];
  const chunks = arenaSplitJsonObjects(source);
  chunks.forEach((chunk) => {
    // STRICT prefilter to avoid false positives on arbitrary JSON
    // the model happens to paste. Accept only if the chunk looks
    // unmistakably like an Arena call:
    //   * outer envelope: contains `"bridge"` and `"arena"` and `"calls"`
    //   * MCP jsonl variant: contains `"function_call_start"`
    //   * single-call arena shape: contains BOTH `"tool"` (or
    //     `"function"`) AND `"arguments"` (or `"params"`)
    const isEnvelope = /\"bridge\"\s*:\s*\"arena\"/.test(chunk) && /\"calls\"\s*:/.test(chunk);
    const isJsonlStart = /\"type\"\s*:\s*\"function_call_start\"/.test(chunk);
    const isSingleCall = /\"(tool|function)\"\s*:/.test(chunk) && /\"(arguments|params)\"\s*:/.test(chunk);
    if (!isEnvelope && !isJsonlStart && !isSingleCall) return;
    const payload = arenaPayloadFromJson(chunk);
    if (payload && Array.isArray(payload.calls) && payload.calls.length) {
      // Extra guard for single-call shape: the tool name must at
      // minimum contain a dot (`sys.status`, `fs.read`, ...) so we
      // don't grab arbitrary `{"tool":"foo"}` prose. Envelope and
      // jsonl variants are already unambiguous.
      if (!isEnvelope && !isJsonlStart) {
        const bad = payload.calls.find((c) => !c.tool || !c.tool.includes('.'));
        if (bad) return;
      }
      found.push({raw: chunk, payload, kind: 'bare-envelope'});
    }
  });
  return found;
}

function parseArenaBlocks(text) {
  const out = [];
  const source = String(text || '');
  if (arenaLooksLikeBridgeInstructions(source)) return out;
  const seenRawStart = new Set();
  ARENA_BLOCK_PATTERNS.forEach(({kind, re}) => {
    re.lastIndex = 0;
    for (const match of source.matchAll(re)) {
      const body = match[1];
      // For unlabeled fences, try JSON first, then JSONL.
      let payload = null;
      if (kind === 'arena-tool' || kind === 'json') {
        payload = arenaPayloadFromJson(body);
      } else if (kind === 'jsonl') {
        payload = arenaPayloadFromJsonl(body);
      } else if (kind === 'fence') {
        payload = arenaPayloadFromJson(body) || arenaPayloadFromJsonl(body);
      }
      if (payload) {
        out.push({raw: match[0], payload, kind});
        seenRawStart.add(match.index);
      }
    }
  });
  if (!out.length && source.includes('function_call_start') && source.includes('function_call_end')) {
    const payload = arenaPayloadFromJsonl(source) || arenaPayloadFromJson(source);
    if (payload) out.push({raw: source, payload, kind: 'jsonl-inline'});
  }
  // v0.14.32 (v4.51.3): bare-envelope fallback. Only invoked if
  // NOTHING was captured above -- fenced blocks are always
  // preferred (they include the site's own copy/paste framing).
  if (!out.length) {
    const bare = _scanBareArenaEnvelopes(source);
    bare.forEach((entry) => out.push(entry));
  }
  return out;
}
