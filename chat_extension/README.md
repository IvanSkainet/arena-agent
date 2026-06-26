# Arena Chat Bridge MVP Extension

This is an early browser-extension scaffold for the Arena Chat Bridge idea.

## What it does today
- injects a generic content script into web pages
- detects fenced `arena-tool` blocks
- shows **Preview** and **Run** controls
- sends requests to a local Arena bridge via:
  - `GET /v1/extension/policies`
  - `POST /v1/extension/preview`
  - `POST /v1/extension/execute`

## What it does not do yet
- site-specific adapters
- reliable composer insertion
- side panel UI
- options/settings page
- auto-run policies in the extension UI
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

## Expected payload format

```text
```arena-tool
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    {
      "id": "call_1",
      "tool": "mission.lineage",
      "arguments": {"mission_id": "demo"}
    }
  ]
}
```
```

## Next planned steps
- per-site adapters
- side panel
- settings page
- result insertion strategies
- better dedupe and execution history
