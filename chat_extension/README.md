# Arena Chat Bridge Extension

Current extension version: `0.14.37` (v4.52.3 bridge release —
Scan Now regression fix from the side panel + ZeroTier Central
URL actualisation).

Key fixes in this release:

1. **Scan Now (Settings tab → Status) now works from the side
   panel.** Prior versions asked `chrome.tabs.query({active:
   true, currentWindow: true})` from the sidepanel context, but
   from the side panel Chrome resolves `currentWindow` as the
   panel window (not the browser window that has the chat tab
   open). The query matched nothing and Scan Now silently
   returned `active tab not found`. `sendActiveTabMessage` now
   walks a three-step fallback: `lastFocusedWindow` first
   (correct pick for sidepanel callers), then `currentWindow`
   (correct pick for popup / content-script callers), then any
   active tab in any window. URLs that cannot host a content
   script (`chrome://`, `chrome-extension://`, `edge://`,
   `about:`, `file://`) are filtered out.

2. **Actionable error messages.** When the content script is
   not injected on the active tab (fresh browser start, first
   navigation to a chat site after installing the extension),
   Chrome returns `Receiving end does not exist`. We now
   classify that error and append "reload the tab so the
   extension can inject its content script" so the operator
   knows what to do. When no chat tab is open at all, we say
   so plainly.

3. **Side panel Scan Now handler simplified.** The unwrap
   logic that assumed background wrapped the reply in
   `{ok, response, ...}` was wrong — `arena.scanPage` returns
   the raw Scan Page JSON directly on success and a
   `{ok: false, error, tab_url}` envelope on failure. Handler
   now maps both correctly and surfaces `tab_url` in the
   error line so you can see which page failed.

4. **ZeroTier Central URL actualised.** ZeroTier launched a
   new Central UI in November 2025 at `central.zerotier.com`
   and made `my.zerotier.com/account` the legacy fallback.
   Dashboard body-18-zerotier.html now links to the new UI
   and the backend error hint in `arena/admin/zerotier_central.py`
   points to `central.zerotier.com/` first with the legacy URL
   as a compatibility footnote.

The Chrome side panel still has five tabs (Status, Tools,
Instructions, History, Settings). Everything else is
byte-identical to v4.52.2 — no parser, adapter, or collapse
changes.

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
  five tabs described above. Shares `popup.css` for its
  styling.
* Tool calls are posted to `/v1/extension/execute` on the local
  bridge, which validates the arena envelope, executes the
  tool, and returns the result payload.
