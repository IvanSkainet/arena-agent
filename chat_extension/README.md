# Arena Chat Bridge Extension

Current extension version: `0.14.33` (v4.51.4 bridge release —
universal collapse fix based on real DOM data from Gemini web /
Mistral / Kimi / Qwen / DeepSeek / z.ai):

1. **`collapseToolResultsInHistory` fully rewritten via
`TreeWalker`.** Ivan's v4.51.3 test cycle produced
`outerHTML` snapshots for every affected site and they all
showed the same pattern: the pasted tool-result is rendered
by the site's own markdown pipeline into ordinary text nodes
(no `<pre>`/`<code>`/`code-block`). Old strategy (query for
code-like elements, look inside `.textContent`) could not
reach any of them.

   New strategy:
   * `TreeWalker` over `NodeFilter.SHOW_TEXT` finds every
     text node containing `ARENA_RESULT_V1` or the legacy
     `<!-- arena:tool-result -->` sentinel.
   * From that text node, walk up to the nearest known
     user-message container (per-site allow-list — Gemini
     `span.user-query-bubble-with-background`, Qwen
     `div.chat-user-message`, Kimi `div.user-content`,
     DeepSeek `div.rounded-xl.p-3.bg-*`, z.ai `div.chat-user`,
     Mistral `[data-message-part-type="user"]`, plus
     ChatGPT/OpenRouter/T3 `[data-message-author-role="user"]`).
   * If no user-message container, fall back to the classic
     code-fence root (assistant echo case).
   * Wrap the found container in a `<details>` with an
     `arena-tool-collapsed="1"` guard for idempotency.

2. **Legacy path preserved.** Messages already in the chat
that contain the pre-v4.51.2 HTML-comment sentinel still
collapse.

3. **Idempotent.** Repeated calls produce exactly one
`<details>` per tool result (verified in jsdom).

4. **Diagnostics.** Every collapse pushes
`{kind: "tool_result_collapsed", target_tag, target_kind}`
into the events ring so Ivan's Scan Page report shows
whether the wrap hit `user-message` or `code-fence`.

Not addressed in this release:

* **Mistral duplicate-mount loop.** The v4.51.3 Scan Page
report showed a repeating `mount_entry → skip_semantic_prev_alive`
cycle. Ivan said explicitly at v4.50.17: "про Mistral можешь
забыть, я там не могу воспроизвести сценарий" — deferred.
* **MCP SuperAssistant UI port** (sidebar with tool browser).
Still planned as a v4.52.x arc.

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
* Tool calls are posted to `/v1/extension/execute` on the local
  bridge, which validates the arena envelope, executes the
  tool, and returns the result payload.
