# Arena Chat Bridge Extension

Current extension version: `0.14.32` (v4.51.3 bridge release —
two fixes on top of v4.51.2):

1) **Parser tolerates bare envelopes.** Some models emit the
Arena tool call as a bare `{"bridge":"arena","version":1,
"calls":[…]}` JSON object without any surrounding code fence.
v4.51.2 required a `arena-tool` / `json` / `jsonl` fence to
detect the call at all; v4.51.3 adds two fallbacks:
   * An unlabeled ``` fence is now scanned as `arena-tool`
     first and JSONL second.
   * If NO fenced block is captured anywhere in the message,
     the parser scans the whole message for bare balanced-brace
     JSON objects that look like the Arena envelope and picks
     the first valid one. Fenced blocks are still preferred.
   Also normalises a `{"tool":"…","arguments":{…}}` single-call
   variant into the full envelope so both call shapes work.

2) **SYSTEM prompt made STRICT.** The old preamble said "wrap
in fenced code block ```arena-tool ...```" but did not
prohibit bare JSON, and did not enumerate common mistakes (XML
`<function_calls>`, ```json fence, multiple blocks per
response). v4.51.3 restructures the preamble with:
   * "How the Arena bridge works" (4-step call-and-wait loop)
   * "STRICT — Function Call Format" (fence tag MUST be
     `arena-tool`, worked example inline)
   * "DO NOT — common mistakes to avoid" (bare JSON, ```json,
     XML tags, multiple blocks) — every failure Ivan reported
     in the v4.51.2 test cycle is called out by name here.
   * "Fallback — MCP-compatible JSONL format" clearly labeled
     as fallback, not preferred.
   * "Response format" with explicit STOP.

Collapse-of-tool-results support on Gemini web / Mistral /
Kimi / Qwen / DeepSeek remains **partially working** — v4.51.3
does NOT touch collapse code; a v4.51.4 pass will follow once
Ivan sends the Scan Page JSON + outerHTML snapshots for those
sites.

Extension file architecture (unchanged since v0.14.29):

* `manifest.json` — MV3 manifest, content_scripts glob per
  chat site.
* Content scripts (order is test-locked in
  `tests/test_chat_extension_bootstrap_v0_14_29.py`):
  `adapter_sites.js`, `parser.js`, `adapters.js`,
  `insert_strategies.js`, `settings.js`, `insert_history.js`,
  `shadow_toolbar.js`, `diag.js`, `content.js`.
* `background.js` — service worker: state relay, health check
  against the local bridge at `http://127.0.0.1:8765/health`,
  side panel UI host. Persists the bridge token as a
  device-local secret via `chrome.storage.local` for the
  current session and mirrors select settings to
  `chrome.storage.sync` for cross-device use.
* `popup.js` / `popup.html` — action popup with quick status +
  Copy Instructions and an "Insert & Submit" (Send) shortcut
  for the active tab.
* Tool calls are posted to `/v1/extension/execute` on the local
  bridge, which validates the arena envelope, executes the
  tool, and returns the result payload.
