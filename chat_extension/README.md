# Arena Chat Bridge Extension

Current extension version: `0.14.36` (v4.52.2 bridge release —
collapse-tool-results is now **default OFF** and moved to
Advanced/experimental after Ivan's v4.52.1 test cycle showed
per-site rendering regressions; UI polish pass on tabs and
buttons).

Key changes in this release:

1. **`collapseToolResults` default: FALSE.** Prior versions
enabled it by default, but the `<details>` wrapper picked up
per-site CSS in ways we could not predict (Qwen bled a
pink-purple Tailwind highlight, Kimi showed a vertical rule
from `.user-content` styling, Gemini web double-collapsed
against its own `luminous-collapse-button`). The toggle
still exists — under **Settings → Advanced / experimental**
— but is off unless the operator explicitly opts in. The
old "undefined → TRUE" upgrade continuity is removed so
users who had it ON before will notice tool-results stop
collapsing after upgrade. That is the correct outcome
given the rendering bugs.

2. **Site-skip list.** When `location.hostname` is in
`ARENA_COLLAPSE_SKIP_HOSTS` the collapse function no-ops
even when the toggle is ON. `gemini.google.com` is on the
list because Gemini ships its own
`data-test-id="luminous-collapse-button"` on user-query
bubbles; wrapping again produces the visible double-
collapse.

3. **Minimal styling on the wrapper.** The `<details>` and
`<summary>` are now created with `all: revert; …` inline
`cssText` so per-site rules with lower specificity cannot
override us and we do not inherit weird colours. Summary is
a muted italic label; the block itself has no background,
border-radius, or padding. Site themes still colour the
inner text as they would for any other user message.

4. **UI polish (sidepanel).** Header shows a subtle
gradient dot next to the title. Tabs are now pill-shaped
inside a rounded container instead of the old flat
tab-strip. Buttons no longer turn blue on every hover;
they lift to a slightly lighter slate. Focus rings on
inputs/selects are the standard blue outline. Section
titles are uppercase-tracking labels for better hierarchy
in dense tabs.

The Chrome side panel still has five tabs:

1. **Status** — bridge health, policies, Scan Now viewer.
2. **Tools** — searchable tool catalog.
3. **Instructions** — Copy Instructions with live preview.
4. **History** — command lifecycle history.
5. **Settings** — bridge URL/token, automatic modes,
   insert strategy, UI polish, Advanced/experimental
   (collapseToolResults now lives here).

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
