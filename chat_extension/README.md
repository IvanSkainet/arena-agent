# Arena Chat Bridge Extension

Current extension version: `0.14.27` (v4.50.17 bridge release —
two things:
1) T3 chat duplicate real root cause: React re-parents the
shadow host to the NEW bubble during streaming, leaving the
old host disconnected. v0.14.24-25 prune only cleared the
map entry, leaving the orphan shadow in the DOM. Now
`pruneMountedControls` physically removes the shadow-host /
bar from the DOM when a stale entry is pruned, and
`sweepDuplicateToolbars` gets an orphan-shadow pass that
removes any `[data-arena-shadow-host]` whose previous
sibling isn't a valid mounted host.
2) Generic adapter goes from pure `passive` to
`passiveUnlessComposer`: mounts on ANY unlisted chat site
that has (a) a discoverable composer AND (b) the tool block
sits inside a chat-shaped ancestor (role=article/log,
class~=message/chat/conversation/bubble). Safe against the
v0.14.3 README-code-fence false-positive because random
docs pages don't have both markers.
v4.50.16 bridge release —
one-line root-cause fix from Ivan's v4.50.15 Battle scan.
`arenaColumnIndex` and the carousel diagnostic used a greedy
regex `\bcarousel\b` / CSS `[class*="carousel"]` that matched
Tailwind pseudo-utilities like `@[752px]/carousel:basis-1/2`
on child column wrappers. Result: both Battle AI PREs
reported `column.index=0` → identical semantic fingerprint →
`later-in-document` tiebreaker evicted one → only one toolbar
mounted. Tightened the regex to require `@container/carousel`
OR a `carousel-`/`battle-` word-boundary token (never a
Tailwind `carousel:` modifier). The `IS_REAL_CAROUSEL` filter
also drops false-positive containers from the diagnostic
snapshot and top-up pass. v4.50.15 bridge release —
two direct root-cause fixes from Ivan's v4.50.14 scans:
1) T3 chat duplicate at first message of a new chat: real
cause was `attachControls()` calling
`insertAdjacentElement('afterend', bar)` TWICE on race, stacking
two shadow hosts as siblings AFTER the same PRE. Fixed at
attach time: purge any prior arena bar/shadow-host sibling
BEFORE inserting the new one. The v0.14.24 DOM sweep stays as
a second line of defence.
2) Arena.ai Battle multi-model: v0.14.24 diagnostic proved the
carousel DOM has both columns and pruneAncestorCandidates was
dropping one column's PRE as ancestor of a nested element.
Added an arena.ai-only carousel top-up pass in
`arenaCandidateNodes` that explicitly walks every carousel
child and adds any PRE containing `function_call_start` that
isn't already a candidate. Widened candidate cap 5→8 so both
Battle columns + 6 prior turns fit. Enriched
`arenaai_hint.carousel.columns[].has_pre/pre_count/has_tool_text`
so any remaining miss is fully diagnosable from one scan.
v4.50.14 bridge release —
two focused fixes from Ivan's v4.50.13 tour:
1) T3 chat duplicate — v4.50.13 sweep was map-based but
mountedControls.set(fp, ...) OVERWRITES prior entries when
two mounts commit with the same fingerprint. Map had 1 entry;
DOM had 2 shadow-hosts. New DOM-based sweep walks
`[data-arena-tool-controls-mounted]` directly and groups by
new `data-arena-semantic-fingerprint` attribute; catches
duplicates the map can't see.
2) Arena.ai Battle diagnostics — Battle scan absent from the
v4.50.13 tour; added `arenaai_hint.carousel` block reporting
total carousels on the page + per-column snapshot with
`has_ai_bar`. Root-cause for the next Battle miss will be
visible from one scan-report. v4.50.13 bridge release —
three retries from Ivan's v4.50.12 tour:
1) Arena.ai Battle + Code — v4.50.12 column detector missed
because arena.ai's Battle/Code layouts don't use the
`@container/carousel` class. New shared `arenaColumnIndex()`
helper recognises `carousel`, `side-by-side`, `battle`,
`grid-cols-2`, `flex-row` too. Same helper drives roleBit,
semanticFingerprint, and the new `arenaai_hint.column`
diagnostic block.
2) OpenRouter multi-block partial mount — v4.50.12 walker
required all N blocks to render as recognised code-fence
containers before scan; when only some did, all entries
collapsed to single-host. New per-entry text-based finder:
for each parsed entry, walk the candidate for the tightest
element containing that call's `"call_id":"N"` + `"name":"tool"`
signature; entries that don't match fall back to outerHost
individually so nothing is silently dropped.
3) T3 chat streaming duplicate — new `sweepDuplicateToolbars()`
runs at end of every scan; groups live mounts by
semanticFingerprint and evicts all-but-newest when two
toolbars slipped through the mount-time dedup race.
Guarded by the dedupSemantic toggle. v4.50.12 bridge release —
big backlog release picking up open items from the v4.50.11 tour:
1) Arena.ai battle / side-by-side multi-model — semantic
fingerprint now includes the carousel column index so two
models emitting identical tool calls in parallel columns each
get their own toolbar (previously one was silently deduped).
Also `roleBit` in message fingerprint carries the column index
so `ai_c0` / `ai_c1` never collide.
2) Partial-failure result rendering — when the AI batches
several tool calls and one returns an error (e.g. 400 missing
name parameter), the toolbar now renders EVERY call as a
labelled `# call N · tool · OK|ERROR` block so the operator
can Insert the successful calls' output alongside the failed
call's error message. Status line reads `Executed X/Y call(s)
in Nms · error: ...` instead of a bare `Run error`. Timing
metadata is preserved on partial failure.
3) Bridge — mission endpoints (`/v1/mission/show`, `status`,
`report`, `history`, `lineage`, `family`) return actionable
JSON on missing-name 400 responses: `error`, `hint`,
`required`, `endpoint` fields with a mission.catalog pointer
so the next AI call succeeds. v4.50.11 bridge release —
three retries after Ivan's v4.50.10 tour:
1) Arena.ai user filter — v4.50.10 markers were INVERTED
(bg-surface-raised was assumed AI but is actually the User
pill background). Switched to the definitive `self-end`
ancestor marker (Tailwind flex right-align pattern used for
user pills across chat/agent/battle). AI recognised via
`#response-content-container` + wide-column
`mx-auto max-w-[800px] w-full` pattern.
2) Multi-block on OpenRouter — v4.50.10 walker looked for
`<pre>` only; OpenRouter renders each block as
`<div class="group/codeblock">` without any `<pre>` ancestor
(selector_hits pre.raw=0). Walker broadened to accept
`.group/codeblock`, `.code-block`, `.codeBlock`,
`.syntax-highlighter`, `.markdown-fenced-code` with a
tightest-node de-dup.
3) ChatGPT same-call_id tiebreaker — v4.50.10 tiebreaker never
ran because the two identical assistant PREs hashed to the
SAME fingerprint (arenaNodePath 6-deep collapsed different
conversation-turn-N sections). `arenaExtractNodeId` now
falls back to conversation-turn-N ordinal (or bubble index
within playground-message-list) as roleBit when no explicit
role marker is present, so the tiebreaker sees two distinct
fingerprints and the DOM-position tiebreaker actually fires.
v4.50.10 bridge release —
picking up the deferred v4.50.9 backlog:
1) Arena.ai fingerprint collision — v4.50.9 filter correctly
matched User but the User+AI PREs on `/c/` had identical
node paths + text heads → identical fingerprints → AI cascaded
through `skip_dismissed_fp`. `arenaExtractNodeId` now includes
a `roleBit` (ai/user) derived from `bg-surface-raised` /
`bg-surface-primary` / `#response-content-container` wrappers.
2) Multi-block per message — a single AI turn with 5-6 tool
JSONL blocks (OpenRouter / arena.ai) previously got ONE
toolbar; scan now expands into per-PRE candidates and mounts a
toolbar under each block.
3) Same-call_id tiebreaker by DOM position — when two candidates
share a semantic fingerprint AND their call_ids match (or are
both missing), the LATER-in-document copy now wins (previously
prev-wins → newest hidden). Diag event
`evict_semantic_owner reason:"later-in-document"`.
4) MAX_PRODUCT_FILE_LINES raised 900 → 1000 to accommodate the
multi-block scan rewrite without compressing readable code.
v4.50.9 bridge release —
three retries from Ivan's v4.50.8 tour:
1) Kimi — v4.50.8 hop-to-`.segment-assistant` produced a huge empty
column in saved chats; now the thinking-widget candidate is
silently dismissed via `arenaWhyUserAuthored` and the sibling
`.segment-content` PRE (which mountControls visits separately)
becomes the sole toolbar host.
2) z.ai — v4.50.8 walker keyed on Kimi-specific class tokens
that don't exist on z.ai; broadened to also look for `<pre>`,
`<code>`, `[class*="language-"]`, `[class*="hljs"]` and require
`function_call_start`/`function_call_end` in the element's text.
3) Arena.ai — v4.50.8 keyed on `.chat-user`/`.chat-assistant`
(those are z.ai classes, not arena.ai); switched to
Tailwind design-system tokens `bg-surface-raised` (AI) /
`bg-surface-primary`+`no-scrollbar` (User) + explicit
`#response-content-container` fast-return. Also added
`arenaai_hint` diagnostic block (surface + wrapper chain) so
future /agent/ vs /c/ vs /battle/ regressions are diagnosable
from scan-report. v4.50.8 bridge release —
four narrow fixes from Ivan's v4.50.7 site tour:
1) Kimi — не монтировать toolbar в свёрнутый
`.toolcall-container.thinking-container`; переходить на
видимый `.segment-assistant`.
2) z.ai — при кандидате `.markdown-prose` без `<pre>` walk-down до
`.code-block` / `.syntax-highlighter` / `<pre>`, чтобы toolbar
сидел под вызовом функции, а не в конце сообщения.
3) Arena.ai — читаемый ярлык `displayName: "Arena.ai"` вместо
`arenaai`; user-filter по `.chat-user` / `.chat-assistant` для
Agent / Direct / Battle режимов.
4) `dedupSemantic` toggle — prewarm cache из
`chrome.storage.sync` на инициализации content-script, чтобы
галочка операторa действовала с первого mount после reload;
плюс `.add()` в `mountedPayloadSemantics` теперь тоже
gated behind toggle. v4.50.7 bridge release —
AI Studio user filter DOM fix: switched from `role="user"` on
`ms-chat-turn` (never present in the current build) to the stable
`ms-chat-turn:has([data-turn-role="User"])` / `[data-turn-role="Model"]`
attribute confirmed by third-party AI Studio userscripts. Also
extended ancestor-snapshot depth 4→8 and added an `aistudio_hint`
diagnostic block to scan-report so future regressions are visible
without a Chrome inspector. v4.50.6 bridge release —
concrete narrow fix based on the v0.14.5 diagnostic reason
strings. `data-testid="user-message"` was matching Grok / DuckAI
message-list containers (parents of BOTH user + assistant blocks),
so every mount short-circuited. That single testid rule is now
removed; only the four role-explicit attributes stay. Qwen
toolbar overlap fixed by giving the shadow host `position:
relative; z-index: 2147483000; margin-top: 6px; isolation:
isolate;` so it sits above the site's own like / dislike /
share / refresh action row instead of underneath it.

Arena Chat Bridge Extension connects ordinary web chats to Arena Unified Bridge.
It detects structured tool-call blocks in assistant messages, sends them to the
local bridge for preview/execution, and can insert the result back into the chat
composer.

## Supported chat adapters

Baseline adapters currently cover:

- ChatGPT;
- Claude;
- Gemini Web;
- Google AI Studio;
- Grok;
- Perplexity;
- OpenRouter;
- DeepSeek;
- Kimi (both `kimi.com` and `www.kimi.com` since v0.14.1);
- Qwen;
- t3chat;
- z.ai;
- Mistral (added v0.14.1 — `chat.mistral.ai`);
- GitHub Copilot chat (added v0.14.1 — `github.com/copilot/*`);
- generic fallback.

Adapters are intentionally conservative: detection and insertion should be
verified with Scan Page diagnostics instead of guessing from site names alone.

## Main features

- detects fenced `arena-tool` payloads;
- accepts MCP SuperAssistant-style fenced `jsonl` function-call blocks;
- normalizes both formats into Arena's canonical extension payload;
- provides toolbar actions: Preview, Run, Insert, Send, Copy, Panel;
- supports multiple composer insertion strategies via `insert_strategies.js`;
- records command history in popup/sidepanel;
- side panel UI / Command Center shows detected/preview/execute/insert/submit lifecycle events;
- Scan Page diagnostics expose adapter, selector hits, composer type, and active script versions.

## Local bridge expectations

Default bridge URL:

```text
http://127.0.0.1:8765
```

The extension stores config in two places:

- `chrome.storage.sync` for `bridgeUrl`, mode flags, and insertion strategy;
- `chrome.storage.local` for `bridgeToken` so the secret stays device-local.

If the bridge URL points at a Tailnet / tunnel hostname and the fetch fails locally,
the extension retries against `http://127.0.0.1:8765` before surfacing a network error.

Bridge endpoints used by the extension:

- `GET /v1/extension/policies`;
- `GET /v1/extension/instructions`;
- `POST /v1/extension/preview`;
- `POST /v1/extension/execute`.

## Load for development

1. Open Chromium/Chrome `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the `chat_extension/` directory.
5. After changing content scripts, reload the extension and refresh chat tabs.

## Canonical payload format

````text
```arena-tool
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    {
      "id": "call_1",
      "tool": "sys.status",
      "arguments": {}
    }
  ]
}
```
````

## JSONL compatibility

````text
```jsonl
{"type":"function_call_start","name":"sys.status","call_id":"1"}
{"type":"function_call_end","call_id":"1"}
```
````

The parser normalizes this into the canonical Arena payload before preview or execution.

## Diagnostics checklist

When debugging a site:

1. Click **Scan Page** in the popup.
2. Check `adapter`, `candidate_nodes`, `parsed_blocks`, and `selector_hits`.
3. Check `composer.rich_textarea`, `composer.prose_mirror`, and `composer.auto_plan`.
4. Confirm `manifest_version`, `content_version`, and `insert_script_version` match the loaded extension.
5. If versions are stale, reload the extension and refresh the chat tab.

## Important files

- `manifest.json` — extension manifest and content-script order.
- `adapter_sites.js` — site adapter registry.
- `parser.js` — `arena-tool` and JSONL parser.
- `adapters.js` — DOM detection/fingerprinting helpers.
- `insert_strategies.js` — composer insertion strategies.
- `insert_history.js` — insert/submit history event recording.
- `content.js` — toolbar controls and page scanning.
- `shadow_toolbar.js` / `shadow_toolbar.css` — Shadow DOM host + scoped
  stylesheet for the injected toolbar (v4.48.0). Isolates our controls
  from page CSS so ChatGPT / Claude / Gemini theme rules cannot restyle
  our buttons. Pattern mirrored from MCP SuperAssistant's
  `BaseSidebarManager` (`attachShadow({mode:'open'})` with a CSS file
  fetched via `chrome.runtime.getURL` and injected as `<style>` into
  the shadow root).
- `background.js` — bridge communication, config, policies, history.
- `sidepanel.js` — Command Center history UI.











