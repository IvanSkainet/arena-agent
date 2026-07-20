# Arena Chat Bridge Extension

Current extension version: `0.14.39` (v4.52.5 bridge release —
Scan Now supported-host ranker; direct fix for Ivan's v4.52.4
diagnostic report showing the ranker picked YouTube over
DeepSeek).

Key change in this release:

**Scan Now ranker now scores supported chat hosts explicitly
above other http(s) tabs.** Ivan's v4.52.4 diagnostic dump
proved it: the ranker was picking the active leftmost http(s)
tab, which on his setup was `youtube.com/@i2hard/videos`,
causing `Receiving end does not exist` because the content
script never injects on unsupported hosts. After swapping tab
order manually, it correctly resolved to `chat.deepseek.com`.

Fix in `sendActiveTabMessage`:

* New `ARENA_SUPPORTED_CHAT_HOSTS` set covering every
  full-host adapter (16 hosts). Mirrors
  `chat_extension/adapter_sites.js` `hosts:` fields.
* New `ARENA_PATH_SCOPED_ADAPTERS` for adapters that only
  live at a path prefix (`github.com/copilot`,
  `duckduckgo.com/chat`) — those are matched against
  `URL(u).pathname.startsWith(prefix)` rather than the plain
  host set. This prevents the ranker from picking a random
  GitHub repo when Copilot is not open.
* Ranker weight `+1000` for supported hosts — dominates
  active/highlighted/window-focus signals so a background
  Qwen tab beats a foreground YouTube tab.
* If we end up picking an unsupported host (no supported
  tab is open anywhere), skip `chrome.tabs.sendMessage`
  entirely and return a friendly error naming the
  supported sites so the user knows what to open.
* Diagnostic dump now includes `supported_tabs_seen` and
  each `tabs_sample[i]` carries an `is_supported` flag.
* A pytest guard
  (`test_background_supported_hosts_match_adapter_sites`)
  compares the set against every `hosts:` block in
  `adapter_sites.js` so the two lists cannot drift.

Sidepanel:

* Summary line now shows
  `tabs seen: N total, M on http(s), K supported`.
* Sample-tabs list bolds supported hosts and drops the
  generic `chat` flag when a tab is already marked
  `supported`.

Everything else is unchanged from v4.52.4.

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
