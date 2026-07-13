const ARENA_BLOCK_PATTERNS = [
  {kind: 'arena-tool', re: /```arena-tool\s*([\s\S]*?)```/g},
  {kind: 'jsonl', re: /```jsonl\s*([\s\S]*?)```/g},
  {kind: 'json', re: /```json\s*([\s\S]*?)```/g},
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
  } catch {}
  return null;
}
function arenaLooksLikeBridgeInstructions(text) {
  const source = String(text || '');
  return source.includes('You can request local tool execution through the Arena Chat Bridge browser extension.')
    || source.includes('Only emit a tool block when you need the local Arena bridge to run a tool.');
}

function parseArenaBlocks(text) {
  const out = [];
  const source = String(text || '');
  if (arenaLooksLikeBridgeInstructions(source)) return out;
  ARENA_BLOCK_PATTERNS.forEach(({kind, re}) => {
    re.lastIndex = 0;
    for (const match of source.matchAll(re)) {
      const body = match[1];
      const payload = kind === 'arena-tool' || kind === 'json' ? arenaPayloadFromJson(body) : arenaPayloadFromJsonl(body);
      if (payload) out.push({raw: match[0], payload, kind});
    }
  });
  if (!out.length && source.includes('function_call_start') && source.includes('function_call_end')) {
    const payload = arenaPayloadFromJsonl(source) || arenaPayloadFromJson(source);
    if (payload) out.push({raw: source, payload, kind: 'jsonl-inline'});
  }
  return out;
}
