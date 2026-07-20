# Arena Chat Bridge Extension

Current extension version: `0.14.41` (v4.53.0 bridge release —
MCP SuperAssistant-style pretty function-call preview + inline
result panel in the shadow-DOM toolbar).

Key changes in this release:

**1. Pretty function-call preview** now renders ABOVE the
Preview/Run/Insert toolbar in every mounted shadow root.
Instead of just seeing a bare `Arena · adapter · N calls`
status line and a wall of raw `{"type":"function_call_start"…}`
JSON in the message body, the user gets a compact card:

* Risk badge — colored `safe` / `medium` / `dangerous` /
  `unknown` (looked up from `/v1/extension/policies` once per
  page and cached).
* Monospace tool name (`sys.status`, `fs.write`, …).
* Call id (`#call_1`).
* Optional one-line description (surfaced when the tool
  catalog provided one).
* Parameters as a two-column name → value grid; values > 320
  chars truncate to `…`.
* Multiple calls in one payload render as stacked cards
  divided by a dashed border.

Adapted from MCP SuperAssistant's function-block renderer
(`github.com/srbhptl39/MCP-SuperAssistant/pages/content/src/
render_prescript/src/renderer/functionBlock.ts`, MIT-licensed).
Their React/Zustand implementation is replaced with a vanilla
DOM factory (`arenaShadowToolbarPreview`) so we stay dependency-
free.

**2. Inline result panel** renders BELOW the toolbar after
Run (or auto-execute) finishes. A collapsible `<details>` with
a summary line (`▸ Result (N calls, M lines)`) and the full
tool output in a monospace `<pre>`. The user reads the result
right at the message without opening the side panel, and long
outputs stay compact until clicked. Re-runs replace the panel
in place (idempotent, no stacking).

Both new elements live inside the same Shadow DOM host as the
toolbar. Site CSS cannot leak in, `<details>` styling cannot
leak out — the two v4.52.x collapse bugs are structurally
prevented here.

New helpers in `chat_extension/shadow_toolbar.js`:

* `arenaShadowToolbarPreview(shadowRoot, {calls})` — inserts /
  replaces the preview card at the top of the shadow root.
* `arenaShadowToolbarResult(shadowRoot, {text, open?})` —
  inserts / replaces the result panel at the bottom.

`content.js` calls the preview on mount and the result panel
on every successful Run (manual + auto).

Risk lookup helpers in `content.js`:

* `_arenaRiskLookup(toolName)` — resolves a tool name to
  `safe` / `medium` / `dangerous` / `unknown` via a
  once-per-page cache of `/v1/extension/policies`.
* `_arenaAnnotateCallsForPreview(calls)` — returns a shallow
  clone of the payload calls with a `risk` field added, ready
  to hand to `arenaShadowToolbarPreview`.

Everything else — parser, adapters, insert strategies, Scan
Now, tab picker, auto-inject — is unchanged from v4.52.6.

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
  side panel UI host, tab resolver, auto-inject, tab picker.
  Persists the bridge token as a device-local secret via
  `chrome.storage.local` for the current session and mirrors
  select settings to `chrome.storage.sync` for cross-device use.
  Tool calls are posted to `/v1/extension/execute` on the local
  bridge. The action popup exposes a quick "Insert & Submit"
  (Send) shortcut for the active tab. Ivan-friendly side panel
  UI wraps the same primitives.
* `popup.js` / `popup.html` — action popup with quick status +
  Copy Instructions and an "Insert & Submit" (Send) shortcut
  for the active tab.
* `sidepanel.js` / `sidepanel.html` — side-panel UI with the
  five tabs described earlier. Shares `popup.css`.
* Tool calls are posted to `/v1/extension/execute` on the local
  bridge, which validates the arena envelope, executes the
  tool, and returns the result payload.
