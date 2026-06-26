# Arena Chat Bridge MVP Extension

This is an early browser-extension scaffold for the Arena Chat Bridge idea.
Current scaffold extension version: `0.3.0`.

## What it does today
- injects a generic content script into web pages
- uses a small adapter registry for ChatGPT / Claude / generic fallback
- detects fenced `arena-tool` blocks
- shows **Preview**, **Run**, **Insert Result**, **Insert & Submit**, **Copy Result**, and **Panel** controls
- provides a popup UI for bridge URL/token config, connection testing, policy viewing, side panel opening, clearing history, and recent execution history
- provides a side panel UI for richer history/debug viewing with replay actions
- sends requests to a local Arena bridge via:
  - `GET /v1/extension/policies`
  - `POST /v1/extension/preview`
  - `POST /v1/extension/execute`

## What it does not do yet
- site-specific high-fidelity composer insertion for every supported chat
- rich execution history filtering and search
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
