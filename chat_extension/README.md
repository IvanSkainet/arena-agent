# Arena Chat Bridge Extension

Current extension version: `0.14.42` (v4.53.1 bridge release —
tool descriptions in preview cards + per-call Copy chip).

Two small MCP SuperAssistant-inspired polish items on top of
v4.53.0's pretty preview:

**1. Tool descriptions render under the invocation header.**
v4.53.0 had a `.arena-preview-desc` element wired but nothing
was populating it — the previous release only surfaced
descriptions when the caller passed one explicitly (never
happened in the mount path). Fixed by adding a second
once-per-page cache backed by
`/v1/extension/instructions?category=all` — every entry's
`name → description` mapping is memoised on first miss and
served synchronously (via a resolved Promise) on subsequent
lookups. `_arenaAnnotateCallsForPreview` now enriches every
call with the description in parallel with the risk lookup
(single-frame render, no extra latency).

Adapted from MCP SuperAssistant's `functionBlock.ts::
renderFunctionCall` which threads `jsonInfo.description`
into the card body. Their catalog and ours have the same
shape (the CSN redesign in v4.51.2 already added
`description` to every catalog entry), so the port was one
new cache + one new field.

**2. Per-call `Copy` chip in each preview card header.**
Little pill button in the top-right of every
`.arena-preview-card`. Copies **just that invocation** (not
the whole payload) to the clipboard, wrapped in an
`arena-tool` fenced block ready to paste back into a chat.
Multi-call payloads (Ivan sometimes gets these from
model-driven tool chains) can now be re-issued one at a
time for debugging without hand-editing JSON.

Visual feedback:

* Click → chip flips to `Copied ✓` with a green tint for
  1.2 s, then reverts.
* Clipboard failure → chip shows `Copy failed` for 1.5 s,
  then reverts.
* Chip has `pointerdown`/`mousedown` `preventDefault` so
  clicking it doesn't steal focus from the site's composer
  (same guard the toolbar buttons use).

Everything else (parser, adapters, insert strategies, Scan
Now, tab picker, auto-inject, preview mount, inline result
panel) is unchanged from v4.53.0.

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
