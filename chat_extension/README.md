# Arena Chat Bridge Extension

Current extension version: `0.14.34` (v4.52.0 bridge release —
sidepanel UI redesign based on studying MCP SuperAssistant's
sidebar layout, MIT-licensed
github.com/srbhptl39/MCP-SuperAssistant/pages/content/src/components/sidebar/).

The Chrome side panel now has four tabs:

1. **Status** — bridge health check, policies dump, connectivity
   badge in the header. Same buttons as v4.51.x. A colored badge
   next to the title shows `v<version>` when the bridge is up
   and `offline` when unreachable.

2. **Tools** — searchable, category-filtered tool catalog fetched
   from `/v1/extension/instructions?category=…`. Each tool card
   shows name, risk badge (`safe` / `medium` / `dangerous`),
   topic, description, and expands into JSON Schema, CSN one-
   liner, and example arguments. Per-tool actions: **Copy call
   template** (paste-ready `arena-tool` fenced block with
   example args pre-filled) and **Copy CSN line**. Categories
   available: `safe`, `medium`, `dangerous`, `all`, plus the
   topical `fs`, `mission`, `memory`, `browser`, `desktop`,
   `git`, `system`.

3. **Instructions** — Copy Instructions with **live preview**.
   Selects for category (same list as Tools plus the "preamble
   only" mode) and format (`arena` / `jsonl` / `both`). Summary
   line shows `<N> chars · <M> tool(s) · fmt=…` so you can see
   the exact payload the model will get before pasting.

4. **History** — unchanged from v4.51.x. Full command lifecycle
   with `detected → preview → execute → insert → submit` groups,
   filters by kind / site / adapter, per-card inspect / replay
   / copy actions.

Tabs are lazy-loaded: Tools, Instructions, and History fetch
their data only on first activation, so opening the side panel
is instant even against a slow tunnel.

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
  four tabs described above. Shares `popup.css` for its
  styling.
* Tool calls are posted to `/v1/extension/execute` on the local
  bridge, which validates the arena envelope, executes the
  tool, and returns the result payload.
