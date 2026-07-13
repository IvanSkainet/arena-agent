# Arena Chat Bridge Extension

Current extension version: `0.13.7`.

Arena Chat Bridge Extension connects ordinary web chats to Arena Unified Bridge.
It detects structured tool-call blocks in assistant messages, sends them to the
local bridge for preview/execution, and can insert the result back into the chat
composer.

## Supported chat adapters

Baseline adapters currently cover:

- ChatGPT;
- Claude;
- Gemini Web;
- Google AI Studio;
- Grok;
- Perplexity;
- OpenRouter;
- DeepSeek;
- Kimi;
- Qwen;
- generic fallback.

Adapters are intentionally conservative: detection and insertion should be
verified with Scan Page diagnostics instead of guessing from site names alone.

## Main features

- detects fenced `arena-tool` payloads;
- accepts MCP SuperAssistant-style fenced `jsonl` function-call blocks;
- normalizes both formats into Arena's canonical extension payload;
- provides toolbar actions: Preview, Run, Insert, Send, Copy, Panel;
- supports multiple composer insertion strategies via `insert_strategies.js`;
- records command history in popup/sidepanel;
- side panel UI / Command Center shows detected/preview/execute/insert/submit lifecycle events;
- Scan Page diagnostics expose adapter, selector hits, composer type, and active script versions.

## Local bridge expectations

Default bridge URL:

```text
http://127.0.0.1:8765
```

The extension stores config in two places:

- `chrome.storage.sync` for `bridgeUrl`, mode flags, and insertion strategy;
- `chrome.storage.local` for `bridgeToken` so the secret stays device-local.

If the bridge URL points at a Tailnet / tunnel hostname and the fetch fails locally,
the extension retries against `http://127.0.0.1:8765` before surfacing a network error.

Bridge endpoints used by the extension:

- `GET /v1/extension/policies`;
- `GET /v1/extension/instructions`;
- `POST /v1/extension/preview`;
- `POST /v1/extension/execute`.

## Load for development

1. Open Chromium/Chrome `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the `chat_extension/` directory.
5. After changing content scripts, reload the extension and refresh chat tabs.

## Canonical payload format

````text
```arena-tool
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    {
      "id": "call_1",
      "tool": "sys.status",
      "arguments": {}
    }
  ]
}
```
````

## JSONL compatibility

````text
```jsonl
{"type":"function_call_start","name":"sys.status","call_id":"1"}
{"type":"function_call_end","call_id":"1"}
```
````

The parser normalizes this into the canonical Arena payload before preview or execution.

## Diagnostics checklist

When debugging a site:

1. Click **Scan Page** in the popup.
2. Check `adapter`, `candidate_nodes`, `parsed_blocks`, and `selector_hits`.
3. Check `composer.rich_textarea`, `composer.prose_mirror`, and `composer.auto_plan`.
4. Confirm `manifest_version`, `content_version`, and `insert_script_version` match the loaded extension.
5. If versions are stale, reload the extension and refresh the chat tab.

## Important files

- `manifest.json` — extension manifest and content-script order.
- `adapter_sites.js` — site adapter registry.
- `parser.js` — `arena-tool` and JSONL parser.
- `adapters.js` — DOM detection/fingerprinting helpers.
- `insert_strategies.js` — composer insertion strategies.
- `insert_history.js` — insert/submit history event recording.
- `content.js` — toolbar controls and page scanning.
- `background.js` — bridge communication, config, policies, history.
- `sidepanel.js` — Command Center history UI.
