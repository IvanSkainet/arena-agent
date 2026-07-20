# Arena Chat Bridge Extension

Current extension version: `0.14.35` (v4.52.1 bridge release —
fifth Settings tab and a Scan Now viewer for live DOM
diagnostics; UI-only, no adapter/parser changes on top of
v4.52.0).

The Chrome side panel now has **five tabs**:

1. **Status** — bridge health check, policies dump,
   connectivity badge in the header. **Scan Now** button runs
   the same Scan Page report the popup exposes and pretty-prints
   the summary (adapter, host, candidates, blocks, mounted
   controls, composer state, tools) plus the last 20
   diagnostic events (mounted, skip_semantic_prev_alive,
   tool_result_collapsed, etc.). The raw JSON stays in a
   collapsible `<pre>` for copy/paste into a bug report.

2. **Tools** — unchanged from v4.52.0.

3. **Instructions** — unchanged from v4.52.0.

4. **History** — unchanged from v4.51.x / v4.52.0.

5. **Settings** — brand-new tab consolidating everything that
   was scattered between the popup and `chrome.storage`:
   * **Bridge connection** — URL input (synced across
     Chrome profiles) + token input (device-local, stored in
     `chrome.storage.local` only, never synced), Reveal
     button, Save, and Clear-token (danger).
   * **Automatic modes** — four opt-in toggles:
     auto-preview, auto-execute safe calls, auto-insert
     result, auto-submit composer. All default OFF.
   * **Insert strategy** — dropdown with `auto` (default) and
     six manual escape hatches for debugging.
   * **UI polish** — collapseToolResults, dedupSemantic
     (both default ON).
   * **Advanced / experimental** — enableGenericAdapter
     (default OFF; opt in only when trying the extension on
     an unlisted chat site).
   * Save Modes / Reset to defaults buttons; live
     "Active: …" summary showing the current mode set.

Tabs remain **lazy-loaded** — Settings only queries
`arena.getConfig` on first activation.

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
