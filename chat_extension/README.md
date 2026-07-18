# Arena Chat Bridge Extension

Current extension version: `0.14.11` (v4.49.4 bridge release —
concrete narrow fix based on the v0.14.5 diagnostic reason
strings. `data-testid="user-message"` was matching Grok / DuckAI
message-list containers (parents of BOTH user + assistant blocks),
so every mount short-circuited. That single testid rule is now
removed; only the four role-explicit attributes stay. Qwen
toolbar overlap fixed by giving the shadow host `position:
relative; z-index: 2147483000; margin-top: 6px; isolation:
isolate;` so it sits above the site's own like / dislike /
share / refresh action row instead of underneath it.

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
- Kimi (both `kimi.com` and `www.kimi.com` since v0.14.1);
- Qwen;
- t3chat;
- z.ai;
- Mistral (added v0.14.1 — `chat.mistral.ai`);
- GitHub Copilot chat (added v0.14.1 — `github.com/copilot/*`);
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
- `shadow_toolbar.js` / `shadow_toolbar.css` — Shadow DOM host + scoped
  stylesheet for the injected toolbar (v4.48.0). Isolates our controls
  from page CSS so ChatGPT / Claude / Gemini theme rules cannot restyle
  our buttons. Pattern mirrored from MCP SuperAssistant's
  `BaseSidebarManager` (`attachShadow({mode:'open'})` with a CSS file
  fetched via `chrome.runtime.getURL` and injected as `<style>` into
  the shadow root).
- `background.js` — bridge communication, config, policies, history.
- `sidepanel.js` — Command Center history UI.
