# Arena Chat Bridge Extension

Current extension version: `0.14.38` (v4.52.4 bridge release —
Scan Now diagnostic dump; MCP SuperAssistant sidebar-injection
study captured but not yet ported).

Key change in this release:

**Scan Now tab-resolver rewritten as a broad-query + rank +
diagnostic dump.** Ivan's v4.52.3 test still returned
"no active chat tab" from real chat sites. The v4.52.3
three-step heuristic (`lastFocusedWindow` → `currentWindow` →
any active) was still missing his tab. Rather than guess a
fourth heuristic, `sendActiveTabMessage` now:

1. Queries `chrome.tabs.query({})` — every tab in every
   window — and `chrome.windows.getAll` — every window with
   type/focused metadata.
2. Filters to `http(s)://` URLs (drops `chrome://`,
   `chrome-extension://`, `edge://`, `about:`, `file://`,
   `view-source:`).
3. Ranks candidates by: `active` (+100), `highlighted` (+20),
   window type `normal` (+50), window focused (+40). Picks
   the top.
4. **On failure, returns a rich diagnostic envelope** with a
   redacted dump of every tab Chrome reported plus every
   window Chrome reported. The side panel renders that dump
   inline so you can see exactly why the resolver did not
   find your chat tab (windows of type `panel`, tabs of
   status `unloaded`, no active + no highlighted, etc.).

URLs are redacted to `scheme://host` before being written
into the diagnostic (no full paths, no query strings, no
titles beyond 60 chars).

The `openSidePanel` helper still uses the popup-safe
`{active: true, currentWindow: true}` query because it is
only called from the popup itself, where `currentWindow`
resolves correctly.

Everything else is unchanged from v4.52.3.

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
* `sidepanel.js` / `sidepanel.html` — side-panel UI with the
  five tabs (Status, Tools, Instructions, History, Settings).
  Shares `popup.css` for its styling.
* Tool calls are posted to `/v1/extension/execute` on the local
  bridge, which validates the arena envelope, executes the
  tool, and returns the result payload.
