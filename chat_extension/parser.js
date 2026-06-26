const ARENA_BLOCK_PATTERNS = [
  {kind: 'arena-tool', re: /```arena-tool\s*([\s\S]*?)```/g},
  {kind: 'jsonl', re: /```jsonl\s*([\s\S]*?)```/g},
  {kind: 'json', re: /```json\s*([\s\S]*?)```/g},
];

function arenaParseJsonLines(text) {
  const rows = [];
  String(text || '').split(/\r?\n/).forEach((line) => {
    const raw = line.trim();
    if (!raw) return;
    try { rows.push(JSON.parse(raw)); } catch {}
  });
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

function parseArenaBlocks(text) {
  const out = [];
  const source = String(text || '');
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
