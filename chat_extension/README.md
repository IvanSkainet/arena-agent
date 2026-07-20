# Arena Chat Bridge Extension

Current extension version: `0.14.40` (v4.52.6 bridge release —
Scan Now tab picker + auto-inject fallback for tabs open
before extension install/update).

Key changes in this release:

1. **Tab picker in Status → Scan chat tab.** Ivan's v4.52.5
   feedback: "неудобно с множеством вкладок". A dropdown now
   lists every supported chat tab open in any window, ordered
   by the same rank as the auto-picker (highest first, labeled
   "default"). The `↻` button re-lists on demand and the
   Refresh button re-lists as part of the general refresh
   cycle. Scan Now sends the selected `tabId` explicitly so
   the user has full control.

2. **Auto-inject fallback on `Receiving end does not exist`.**
   Ivan's v4.52.5 report showed arena.ai was picked (correctly)
   but the message failed because that tab was opened before
   the extension was installed / updated. Chrome only
   auto-injects content scripts on new navigations. Fix:
   when the sendMessage error class is "content script never
   loaded" AND the target is on a supported host, we now
   invoke `chrome.scripting.executeScript({files: [...9 files
   in the same order as manifest content_scripts...]})` and
   retry once. If it succeeds, the reply carries a
   `_auto_injected: true` flag and the sidepanel shows an
   "auto-injected" badge.

3. **`arena.listSupportedTabs` handler** — new message type
   the sidepanel uses for the picker. Returns
   `{ok, tabs: [{id, url, host, title, active, windowId,
   windowFocused}]}` sorted by ranker score.

4. **`arena.injectContentScripts` handler** — new message
   type for manual re-injection from external callers /
   future features.

5. **Test guard** —
   `test_background_content_script_files_match_manifest`
   asserts `ARENA_CONTENT_SCRIPT_FILES` list matches
   `manifest.json` `content_scripts[0].js` byte-for-byte so
   the auto-inject bundle can never drift from the manifest.

Everything else (adapters, parser, collapse) is unchanged
from v4.52.5.

The Chrome side panel still has five tabs (Status, Tools,
Instructions, History, Settings). Status now shows the tab
picker + `↻` reload + Scan Now buttons in a single row above
the pretty-print view.

Extension file architecture (unchanged since v0.14.29):

* `manifest.json` — MV3 manifest, content_scripts glob per
  chat site.
* Content scripts (order is test-locked in
  `tests/test_chat_extension_bootstrap_v0_14_29.py` AND now
  mirrored in `background.js::ARENA_CONTENT_SCRIPT_FILES`):
  `adapter_sites.js`, `parser.js`, `adapters.js`,
  `insert_strategies.js`, `settings.js`, `insert_history.js`,
  `shadow_toolbar.js`, `diag.js`, `content.js`.
* `background.js` — service worker: state relay, health check
  against the local bridge at `http://127.0.0.1:8765/health`,
  side panel UI host, tab resolver, auto-inject, tab picker.
  Persists the bridge token as a device-local secret via
  `chrome.storage.local` for the current session and mirrors
  select settings to `chrome.storage.sync` for cross-device
  use.
* `popup.js` / `popup.html` — action popup with quick status +
  Copy Instructions and an "Insert & Submit" (Send) shortcut
  for the active tab.
* `sidepanel.js` / `sidepanel.html` — side-panel UI with the
  five tabs described above. Shares `popup.css` for its
  styling.
* Tool calls are posted to `/v1/extension/execute` on the local
  bridge, which validates the arena envelope, executes the
  tool, and returns the result payload.
