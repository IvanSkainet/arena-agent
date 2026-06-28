# Arena Chat Bridge MVP Extension

This is an early browser-extension scaffold for the Arena Chat Bridge idea.
Current scaffold extension version: `0.11.8`.

## What it does today
- injects a generic content script into web pages
- uses a small adapter registry for ChatGPT, Claude, Gemini, Perplexity, Grok, OpenRouter, DeepSeek, Kimi, Qwen, and generic fallback
- detects fenced `arena-tool` blocks and MCP SuperAssistant-style fenced `jsonl` function-call blocks
- shows **Preview**, **Run**, **Insert Result**, **Insert & Submit**, **Copy Result**, and **Panel** controls
- provides a popup UI for bridge URL/token config, connection testing, instruction copying, policy viewing, side panel opening, clearing history, and recent execution history
- provides a side panel UI for richer history/debug viewing with replay actions, payload inspection, and simple filtering
- sends requests to a local Arena bridge via:
  - `GET /v1/extension/policies`
  - `GET /v1/extension/instructions`
  - `POST /v1/extension/preview`
  - `POST /v1/extension/execute`

## What it does not do yet
- site-specific high-fidelity composer insertion for every supported chat
- rich execution history search beyond basic filters
- per-site auto-run policy controls in the extension UI
- native messaging hardening

## Local bridge expectations
Default local bridge URL:
- `http://127.0.0.1:8765`

The extension reads config from `chrome.storage.sync`:
- `bridgeUrl`
- `bridgeToken`

## Load for development
1. Open Chrome/Chromium `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select the `chat_extension/` directory

## Expected payload formats

```text
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
```

## MCP SuperAssistant-style JSONL compatibility

The MVP parser also accepts a compatible JSONL block:

```text
```jsonl
{"type":"function_call_start","name":"sys.status","call_id":"1"}
{"type":"function_call_end","call_id":"1"}
```
```

It is normalized into the canonical Arena payload before preview/execute.

## Next planned steps
- Gemini Web and ChatGPT smoke tests using Scan Page diagnostics
- stronger Claude-specific adapter behavior
- richer payload/result inspection and page diagnostics UI
- better cross-site composer strategies
- eventual native messaging hardening if needed
