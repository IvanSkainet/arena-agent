# Changelog

## v3.51.0 - 2026-06-28

- Fixed Gemini regressions from v3.50.0: result insertion now uses a single deterministic insertText path, removing the paste+fallback combo that caused duplicate insertion on Gemini and a false insert status that blocked Send.
- Send no longer depends on an instant synchronous text check, so submit works on composers that apply edits asynchronously (Gemini rich-textarea).

## v3.50.0 - 2026-06-28

- Fixed duplicate result insertion in ChatGPT by detecting whether the synthetic paste already changed the composer before running the per-line fallback.
- Made contenteditable insertion report honest success based on actual composer content change instead of always returning true.
- Added more Gemini submit-button selectors so Send can find the send control after insertion.
- Raised the product-file modularity limit from 200 to 300 lines to keep helpers readable instead of artificially compressed.

## v3.49.0 - 2026-06-28

- Fixed multiline result insertion into contenteditable composers (ChatGPT/Gemini) by dispatching a paste event with plain text, with a per-line insertParagraph fallback, so JSON keeps its structure instead of collapsing.

## v3.48.0 - 2026-06-28

- Fixed JSONL parsing for ChatGPT, which renders tool blocks on a single line with a glued language label and no newlines.
- Made Clear Page Controls hide controls only for the current page life; reload or a new chat restores them, plus a new Show Page Controls action restores them without reload.
- Inserted tool results as fenced code blocks so ChatGPT and other contenteditable composers keep JSON structure instead of collapsing to one line.

## v3.47.0 - 2026-06-28

- Fixed inline close controls so `×` dismisses a detected block instead of being immediately remounted by the mutation observer.
- Made `Clear Page Controls` suppress currently visible tool blocks until reload or new block fingerprints appear.
- Added `dismissed_controls` to Scan Page diagnostics for clearer adapter debugging.

## v3.46.0 - 2026-06-28

- Stabilized Gemini Web extension detection by filtering composer/user-input nodes before parsing tool blocks.
- Added adapter-side detection text extraction that removes nested composer fields from broad candidates.
- Made controls remount tolerant to Gemini DOM re-renders without duplicating history detections.
- Clarified inline Preview status as a dry-run/approval summary with tool names.

## v3.45.0 - 2026-06-26

### Added
- **Scan Page diagnostics** — popup can ask the active chat page for adapter, candidate node count, parsed tool block count, mounted controls, detected tools, and text snippets.
- **Scan history entries** — Scan Page results are stored in extension history so adapter/debug state can be inspected in the side panel.

### Improved
- **Alpha example cleanup** — chat extension README examples now use stable `sys.status` instead of `mission.lineage demo` for empty installs.

### Tests
- Expanded extension asset and adapter regressions for Scan Page diagnostics.

## v3.44.0 - 2026-06-26

### Changed
- **Simplified alpha UX** — removed the unstable latest-only/floating toolbar path from the user-facing popup and kept inline controls as the primary alpha workflow.
- **Manual page cleanup** — added `Clear Page Controls` so users can clear inline toolbars on the current chat page without relying on fragile virtualized-DOM heuristics.

### Fixed
- **Avoided confusing latest-only behavior** — AI Studio virtualization no longer drives a half-magic latest-only mode that could look inconsistent after reloads or history remounts.

### Tests
- Updated extension regressions for inline controls plus manual page cleanup.

## v3.43.0 - 2026-06-26

### Changed
- **Latest-only mode is now floating** — when `Show controls only for latest visible block` is enabled, the extension renders one fixed toolbar for the latest detected block instead of inserting inline controls into AI Studio's virtualized chat DOM.

### Fixed
- **Latest-only duplicate/strange layout** — floating latest controls avoid duplicate inline toolbars and layout drift caused by AI Studio history virtualization.

### Tests
- Expanded extension asset regressions for floating latest-only toolbar behavior.

## v3.42.0 - 2026-06-26

### Fixed
- **Latest-only reload behavior** — when latest-only mode is already enabled at page load, the content script now selects the visually latest candidate before mounting controls instead of mounting all controls and pruning afterward.
- **Initial scan cleanup** — stale toolbars are cleared around the selected host during latest-only scans, reducing duplicate controls after AI Studio reloads or virtualized history remounts.

### Tests
- Expanded extension asset regressions for pre-mount latest-only candidate selection.

## v3.41.0 - 2026-06-26

### Fixed
- **Latest-only stale controls** — content script now cleans orphaned toolbars from previous loads and enforces latest-only mode on every scan.
- **Live mode switching** — saving popup settings notifies the active tab so controls mode changes apply immediately without requiring a page refresh.

### Improved
- **Toolbar polish** — result copy is shortened to `Copy`, and each toolbar has a compact close action for manual cleanup.

### Tests
- Expanded extension regressions for stale toolbar cleanup and live controls-mode notifications.

## v3.40.0 - 2026-06-26

### Improved
- **Latest-only controls mode** — the chat extension now keeps the visually lowest visible toolbar instead of the last toolbar mounted by AI Studio's virtualized DOM lifecycle.
- **Toolbar polish** — inline controls use a compact product-style toolbar with pill buttons, a primary Run action, shorter status text, and `Send` instead of the debug-like `Insert & Submit` label.

### Tests
- Expanded extension asset regressions for visual latest-only pruning and polished toolbar labels.

## v3.39.0 - 2026-06-26

### Fixed
- **Controls placement runtime bug** — content script now actually uses the `attachControls()` placement helper, so AI Studio controls are inserted after rendered code blocks instead of appended into arbitrary containers.
- **Insert & Submit timing** — submit now waits briefly and retries while AI Studio enables the send button after insertion.

### Added
- **Controls visibility mode** — popup settings now include `Show controls only for latest visible block`, allowing users to keep only the newest visible toolbar or keep controls on all visible blocks.

### Improved
- **Inline toolbar styling** — controls now size to the detected code block width and use a cleaner compact dark toolbar style.

### Tests
- Expanded extension regressions for latest-only controls mode, async insert-and-submit, and real `attachControls()` usage.

## v3.38.0 - 2026-06-26

### Fixed
- **AI Studio rendered-block regression** — candidate scanning now normalizes `code` nodes to their nearest `pre` and prunes ancestor containers, so controls attach to concrete rendered JSONL blocks instead of drifting into large page containers.
- **Repeated identical tool blocks** — message fingerprints now include a compact DOM path, preventing identical JSONL payloads in separate AI Studio responses from being collapsed as already processed.
- **Bridge URL diagnostics** — extension bridge URLs are normalized when users enter `127.0.0.1:8765` without a scheme, and fetch/HTTP failures now surface concrete errors instead of `unknown`.
- **Policy smoke example** — extension policy examples now use stable `sys.status` instead of `mission.lineage demo` on empty installs.

### Tests
- Expanded extension asset and adapter regressions for rendered-code host pruning, DOM-path fingerprints, URL normalization, and `sys.status` policy examples.

## v3.37.0 - 2026-06-26

### Fixed
- **Mission HTTP error bodies** — MCP mission tools now preserve JSON error bodies from bridge endpoints, so `mission.lineage` on a missing mission returns structured `mission not found` data instead of a bare `HTTPError`.
- **Tool-call success semantics** — extension execution now treats parsed tool results with `ok: false` as failed calls while keeping the structured result available for copy/insert.
- **AI Studio control placement** — nested selector matches now converge to the nearest rendered `pre` / `code` block before mounting controls, reducing duplicate detections and misplaced buttons.

### Improved
- **Stable smoke instructions** — copied extension instructions now use `sys.status` as the default JSONL/Arena example because it works on empty installations; mission tools remain listed for real mission IDs.

### Tests
- Expanded backend and extension regressions for structured HTTP errors, stable smoke instructions, and rendered code-block placement.

## v3.36.0 - 2026-06-26

### Fixed
- **Execution error visibility** — the browser extension now surfaces failed tool-call results instead of showing `error: unknown` when the bridge returns `ok: false` with per-call output.
- **Rendered code-block controls** — inline controls are attached after rendered `pre` / `code` blocks instead of being appended inside code-block UI.
- **Panel fallback** — if Chrome refuses `sidePanel.open()` because of user-gesture restrictions, the extension opens `sidepanel.html` in a regular extension tab.

### Improved
- **Result handling** — failed executions with structured tool output can still be copied/inserted for diagnosis, such as `mission not found` responses.

### Tests
- Expanded extension asset regressions for error summarization and panel fallback behavior.

## v3.35.0 - 2026-06-26

### Fixed
- **Rendered/raw JSONL code blocks** — the browser chat extension now detects MCP SuperAssistant-style `function_call_start` / `function_call_end` JSONL even when AI Studio renders it as a pretty code block without literal triple backticks in the DOM.

### Improved
- **AI Studio selectors** — Gemini / Google AI Studio scanning now includes rendered `pre`, `code`, and code-like nodes so copied JSONL instructions can produce inline Arena controls on real chat pages.
- **Parser fallback** — JSONL parsing now accepts raw inline JSONL text after fenced `arena-tool`, `json`, and `jsonl` formats are checked.

### Tests
- Expanded extension asset and adapter-flow regressions for raw JSONL detection and AI Studio rendered-code selectors.

## v3.34.0 - 2026-06-26

### Fixed
- **JSONL detection pre-filter** — the browser chat extension adapter layer now treats MCP SuperAssistant-style fenced `jsonl` / `json` function-call blocks as executable candidates instead of filtering them out before the parser can run.

### Improved
- **AI Studio JSONL workflow** — models that follow the copied JSONL instructions should now trigger inline extension controls when they emit `function_call_start` / `function_call_end` blocks.

### Tests
- Expanded adapter-flow regressions to cover JSONL/function-call candidate detection.

## v3.33.0 - 2026-06-26

### Fixed
- **Popup save/load reliability** — the browser chat extension popup now uses callback-compatible runtime messaging with explicit `chrome.runtime.lastError` handling, avoiding indefinite `Loading...` states in browsers where promise-style `sendMessage` is unreliable.
- **Configuration save verification** — saving bridge URL, token, and execution modes now immediately reloads stored config to confirm persistence and show a clear status.

### Improved
- **Popup diagnostics** — config/history load failures now render actionable error messages instead of leaving the popup stuck.

### Tests
- Expanded popup asset regressions for callback-compatible messaging and explicit save/load error states.

## v3.32.0 - 2026-06-26

### Added
- **Extension instruction generator endpoint** — added `GET /v1/extension/instructions?format=arena|jsonl|both&style=full|short` so chat sites can receive stable Arena tool-use instructions without hand-written prompts.
- **Popup instruction copy actions** — the browser chat extension popup now includes Copy Arena Instructions and Copy JSONL Instructions actions for quick setup in AI Studio, ChatGPT, Kimi, Qwen, and other web chats.

### Improved
- **End-to-end chat workflow is more practical** — users can now configure the extension, copy the right prompt, ask the AI to emit a tool block, run it through Arena, and insert the result back into the chat.
- **MCP SuperAssistant parity path is stronger** — JSONL-compatible instructions explicitly tell the model to emit `function_call_start` / `parameter` / `function_call_end` blocks and wait for extension-provided results.

### Tests
- Added extension instruction runtime and route regressions plus popup asset coverage for instruction copy actions.

## v3.31.0 - 2026-06-26

### Added
- **MCP SuperAssistant-style JSONL compatibility foundation** — the browser chat extension now detects fenced `jsonl` function-call blocks and normalizes them into canonical Arena `arena-tool` payloads before preview/execute.
- **Expanded chat adapter site registry** — split site definitions into a modular registry and added first-class host coverage for Gemini / AI Studio, Perplexity, Grok, OpenRouter, DeepSeek, Kimi, Qwen, and generic fallback flows.
- **Extension execution mode settings** — the popup now exposes auto-preview, safe auto-execute, auto-insert, and auto-submit toggles, while defaulting to manual confirmation.

### Improved
- **Browser-chat execution parity path is clearer** — Arena keeps bridge-native execution while accepting MCP SuperAssistant-compatible JSONL as an input format.
- **Extension code remains modular** — parser, site registry, settings, adapter helpers, and content flow are split to stay under project modularity guardrails.

### Tests
- Expanded chat extension scaffold and adapter-flow regressions for JSONL parsing, expanded site coverage, and execution mode settings.

### Validation
- Local targeted `pytest -q tests/test_chat_extension_assets.py tests/test_chat_extension_adapter_flow.py tests/test_chat_extension_sidepanel_flow.py tests/test_extension_bridge.py tests/test_project_modularity.py`: PASS, 17 tests.
- Local `node --check` for chat extension JavaScript assets: PASS.

## v3.30.0 - 2026-06-26

### Added
- **Side-panel result inspector** — the browser chat extension side panel can now inspect stored execution results separately from payloads.
- **History filtering by adapter** — the side panel now filters history not only by kind/site but also by adapter, making multi-site debugging more practical.
- **Richer history metadata** — preview and execute entries now persist adapter, fingerprint, payload, and compact response data for later inspection and replay.

### Improved
- **ChatGPT-oriented adapter flow is stronger again** — the adapter layer now exposes latest-candidate helpers, node-id extraction, and tighter assistant-container filtering for better large-chat behavior.
- **Side-panel debugging loop is more complete** — payload inspection, result inspection, payload/result copy, filtering, replay, and clear-history controls now work together in one surface.
- **Browser-chat execution remains bridge-native** — no separate executor was introduced; the extension still uses the local Arena bridge execution model.

### Tests
- Added side-panel flow regressions for payload/result inspection and adapter-filter behavior.
- Total: **637 tests pass**.

### Validation
- Local `pytest -q`: PASS, 637 tests.
- Local `pytest --collect-only`: PASS, 637 tests collected.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.29.0 - 2026-06-26

### Added
- **Side-panel payload inspector** — the browser chat extension side panel can now inspect stored payloads from history and replay them directly as preview or execute actions.
- **ChatGPT-oriented message filtering** — the extension adapter layer now fingerprints assistant messages, filters candidate nodes by actual `arena-tool` presence, and limits detection to relevant assistant-side containers.

### Improved
- **Extension debugging loop is stronger** — popup and side panel can now clear history, filter history, inspect payloads, and replay actions without leaving the browser.
- **Adapter-aware insert-and-submit is more practical** — submit-button discovery and composer-aware insertion now support a stronger ChatGPT / ChatGPT.com path and a clearer fallback chain.
- **Browser-chat execution remains bridge-native** — these improvements keep using the Arena bridge rather than introducing a separate local executor process.

### Tests
- Added side-panel flow and adapter-flow regressions for payload inspection, filtering, and stronger adapter helpers.
- Total: **637 tests pass**.

### Validation
- Local `pytest -q`: PASS, 637 tests.
- Local `pytest --collect-only`: PASS, 637 tests collected.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.28.0 - 2026-06-26

### Added
- **ChatGPT-oriented detection helpers** — the extension now fingerprints assistant messages, filters candidate nodes by `arena-tool` presence, and limits detection to more relevant assistant-side containers.
- **Insert & Submit adapter path** — the adapter layer now includes submit-button discovery and adapter-aware insert-and-submit helpers, with a stronger first path for ChatGPT/ChatGPT.com.
- **Extension replay/debug controls expanded** — side-panel history actions and richer structured history flows are now part of the extension scaffold instead of a passive log-only view.

### Improved
- **Detection is less noisy on large chat DOMs** — the content script now throttles scans, filters nodes earlier, and avoids re-instrumenting already-handled assistant blocks.
- **Chat extension UX is more practical for repeated workflows** — popup + side panel + replay + insert/submit now form a more realistic loop for browser-chat execution.
- **Browser-chat execution remains bridge-native** — all of this still runs through the local Arena bridge rather than a separate local executor process.

### Tests
- Added chat extension adapter-flow regressions and expanded asset checks.
- Total: **635 tests pass**.

### Validation
- Local `pytest -q`: PASS, 635 tests.
- Local `pytest --collect-only`: PASS, 635 tests collected.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.27.0 - 2026-06-26

### Added
- **Extension history replay controls** — the browser chat extension side panel can now replay saved preview/execute items from structured history.
- **Insert & Submit workflow** — the content script now exposes an `Insert & Submit` action that uses adapter-aware composer and submit-button discovery before falling back to generic insertion behavior.

### Improved
- **Side panel is now more than passive status text** — it can refresh state, clear history, and replay stored tool payloads for debugging and repeated execution.
- **ChatGPT-focused adapter behavior is more practical** — the adapter layer now includes submit-button selectors and stronger composer-aware helpers for ChatGPT/ChatGPT.com.
- **Browser-chat execution remains bridge-native** — these replay/debug improvements still build on the local Arena bridge rather than introducing a separate executor layer.

### Tests
- Expanded chat extension scaffold regressions for replay controls, side-panel actions, and insert-and-submit adapter helpers.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.26.0 - 2026-06-26

### Added
- **Extension side panel scaffold** — added side-panel assets for richer bridge status and execution history viewing directly inside the browser extension.
- **Adapter-aware insertion helpers** — the extension now includes composer-aware adapter utilities, with a first stronger ChatGPT/ChatGPT.com path and generic fallback insertion logic.

### Improved
- **Extension UX is deeper than a popup-only shell** — the popup can now open the side panel, while the background tracks detections, previews, and executions as structured history entries.
- **Result handling is more practical in real chats** — the content script now supports adapter-aware insertion before falling back to generic active-field insertion, plus a side-panel shortcut from detected blocks.
- **Browser-chat execution continues to stay bridge-native** — these UX improvements build directly on the local Arena bridge rather than introducing a separate executor layer.

### Tests
- Expanded chat extension scaffold regressions for side-panel assets, adapter helpers, and panel/open interactions.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.25.0 - 2026-06-26

### Added
- **Extension popup UI** — added popup assets for bridge URL/token configuration, connection testing, policy inspection, and recent extension execution history.
- **Extension adapter scaffold** — added `chat_extension/adapters.js` with the first adapter registry and host-aware candidate node selection for ChatGPT, Claude, and generic fallback flows.

### Improved
- **Extension UX is now minimally usable without editing files by hand** — users can configure the local bridge and inspect connectivity directly from the extension popup.
- **Result handling is more practical** — the content script now supports result copy and best-effort insertion back into active text inputs/contenteditable fields after execution.
- **Browser-chat execution remains bridge-native** — the extension UX improvements build directly on the `v3.24.0` backend foundation without introducing a separate local executor layer.

### Tests
- Expanded chat extension scaffold regressions for popup/config/history/adapter assets.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.24.0 - 2026-06-26

### Added
- **Browser chat extension bridge endpoints** — added `GET /v1/extension/policies`, `POST /v1/extension/preview`, and `POST /v1/extension/execute` for extension-facing validation and execution of structured Arena tool payloads.
- **Extension execution policy layer** — added site policy snapshots, tool risk classification, approval gating, and normalized batched tool execution for browser-originated tool blocks.
- **Browser extension MVP scaffold** — added `chat_extension/` with a Manifest V3 prototype, generic `arena-tool` fenced-block detector, localhost bridge calls, and a lightweight background/content-script flow.

### Improved
- **Arena can now grow beyond chats with native MCP/code execution** — the bridge has a first execution protocol layer specifically for ordinary browser chats.
- **The extension roadmap now has concrete code, not just planning** — `docs/CHAT_BRIDGE_EXTENSION_PLAN.md` is no longer just aspirational; Phase 1 bridge groundwork is implemented.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added extension bridge regressions and browser extension scaffold checks.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/26-workspace-v3.js`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.23.0 - 2026-06-23

### Added
- **Automatic mission schedule worker** — added a background recurring mission scheduler that executes due mission schedules without requiring manual ticks.
- **Schedule worker state surface** — added `GET /v1/mission/schedules/state` and MCP `mission.schedule_state`, exposing worker state, last tick, totals, and last execution status.

### Improved
- **Recurring mission orchestration is now bridge-managed** — schedule definitions are no longer just stored objects; the bridge now runs them in the background and tracks worker state.
- **Workspace schedule view is richer** — the Workspace mission loop studio now loads both mission schedules and schedule worker state together.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission schedule worker regressions and lifecycle coverage updates.
- Total: **629 tests pass**.

### Validation
- Local `pytest -q`: PASS, 629 tests.
- Local `pytest --collect-only`: PASS, 629 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/26-workspace-v3.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 229.

## v3.22.0 - 2026-06-23

### Added
- **Mission family surfaces** — added `GET /v1/mission/family` and MCP `mission.family`, so agents can inspect whole mission families rooted at a lineage chain, including branch summaries, leaves, and family-level stats.
- **Mission schedules v1** — added `GET/POST/DELETE /v1/mission/schedules` plus `POST /v1/mission/schedules/tick`, and MCP tools `mission.schedules`, `mission.schedule_save`, `mission.schedule_delete`, and `mission.schedule_tick` for recurring mission orchestration.
- **Workspace schedule/family controls** — the Workspace mission loop studio now includes family inspection plus schedule listing, saving, and ticking surfaces.

### Improved
- **Recurring orchestration now exists on top of mission lifecycle state** — agents can move from lineage/family inspection into recurring schedule definitions and due-run execution without rebuilding orchestration state manually.
- **Mission families now expose branch-level summaries** — roots, members, leaves, branch paths, and family stats are available as first-class bridge data.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission family, mission schedule, and mission lifecycle handler regressions.
- Total: **626 tests pass**.

### Validation
- Local `pytest -q`: PASS, 626 tests.
- Local `pytest --collect-only`: PASS, 626 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/26-workspace-v3.js`: PASS.
- MCP tools: 67.
- Distinct non-HEAD routes: 228.

## v3.21.0 - 2026-06-23

### Added
- **Mission lineage surfaces** — added `GET /v1/mission/lineage` and MCP `mission.lineage`, so persisted missions expose parents, roots, ancestors, children, descendants, and sibling context as first-class lifecycle data.
- **Workspace mission loop studio** — the Workspace tab now includes a mission loop surface for recent mission catalog summaries, lineage inspection, and direct follow-up / iterate actions.

### Improved
- **Mission families now persist provenance** — follow-up and iteration flows now write lineage metadata into persisted mission artifacts, including origin, parent, root, ancestor chain, and recovery hints.
- **Deeper agent loops now span multiple missions, not just one run** — agents can carry recovery context forward into explicit mission families and iteration chains.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission lineage, lineage persistence, and workspace v3 regressions.
- Total: **625 tests pass**.

### Validation
- Local `pytest -q`: PASS, 625 tests.
- Local `pytest --collect-only`: PASS, 625 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- MCP tools: 62.
- Distinct non-HEAD routes: 223.

## v3.20.0 - 2026-06-23

### Added
- **Mission follow-up bundles** — added `POST /v1/mission/followup` and MCP `mission.followup`, so agents can derive a next mission from persisted mission artifacts instead of restarting from a raw prompt.
- **Mission iteration loops** — added `POST /v1/mission/iterate` and MCP `mission.iterate`, combining recovery analysis with optional follow-up mission composition/creation/run in one bridge-native loop.

### Improved
- **Deeper agent loops now chain mission state back into agentic planning** — mission history, failed-step summaries, report excerpts, ReAct observations, reflection, and follow-up mission composition now work as one iteration surface instead of isolated endpoints.
- **Mission lifecycle v4 is now materially loop-shaped** — agents can move from inspect/recover into follow-up mission drafting and optional execution without rebuilding context by hand.
- **Desktop maturity remains preserved** — this release stays out of the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission follow-up and mission iteration regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- MCP tools: 61.
- Distinct non-HEAD routes: 222.

## v3.19.0 - 2026-06-23

### Added
- **Mission catalog surfaces** — added `GET /v1/mission/catalog` and MCP `mission.catalog` so agents can filter persisted missions by query, state, template, and report presence instead of scraping the raw missions list.
- **Mission recovery bundles** — added `POST /v1/mission/recover` and MCP `mission.recover` so agents can inspect a failed mission, derive a rerun recommendation, and optionally compose/create a follow-up mission from the recovery context.

### Improved
- **Deeper agent loops now bridge mission state back into planning** — mission recovery can turn stored history, failed-step summaries, and report excerpts into a structured next action instead of leaving the agent to reconstruct state manually.
- **Mission lifecycle v3 is more operational** — agents can now move from catalog → inspect → recover → rerun/follow-up within bridge-native REST and MCP surfaces.
- **Desktop maturity remains preserved** — this mission/orchestration expansion does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission catalog and mission recovery regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.18.0 - 2026-06-22

### Added
- **Mission lifecycle/inspection v2** — added `GET /v1/mission/history` and `POST /v1/mission/rerun`, plus MCP `mission.history` and `mission.rerun`, so missions can be inspected and iterated instead of only composed and launched.

### Improved
- **Mission artifacts are now first-class runtime objects** — persisted missions expose structured status, report retrieval, run history, step-log summaries, and rerun flows.
- **Deeper agent loops keep getting more practical** — agents can now compose a mission, run it, inspect outcomes, and rerun the failed step or the whole mission through bridge-native surfaces.
- **The post-desktop roadmap block is maturing** — mission composition has moved beyond initial CRUD and proposal flows into real lifecycle management.

### Tests
- Added mission history/rerun regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.17.0 - 2026-06-22

### Added
- **Mission lifecycle/inspection surfaces** — added structured mission status and report inspection through `GET /v1/mission/status` and `GET /v1/mission/report`.
- **MCP mission inspection tools** — added `mission.status` and `mission.report` so agent frontends can inspect persisted mission state and reports without custom REST glue.

### Improved
- **Mission composition is more usable in practice** — missions are no longer just creatable/runnable; they are now inspectable as first-class artifacts with structured state and report retrieval.
- **The mission/orchestration block keeps deepening** — Arena now has template listing, composition, proposal/orchestration, creation, run, status, and report surfaces across REST and MCP.
- **Mission runner validation is stronger** — the release includes explicit regression coverage for hook-helper imports, mission status, and mission report access.

### Tests
- Added mission status/report regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.16.0 - 2026-06-22

### Added
- **Mission proposal/orchestration flow** — added `POST /v1/mission/propose`, which runs a bounded agentic proposal loop, reflects on it, and returns a planner-backed mission bundle with optional mission creation and run.
- **MCP `mission.propose`** — the same proposal/orchestration flow is now available through MCP.

### Improved
- **Mission composition is no longer just CRUD** — Arena can now go from goal → bounded observe/reflect → mission draft → optional persisted mission → optional mission run in one agent-facing flow.
- **The post-desktop roadmap block is now materially underway** — this is the first real bridge between the agentic runtime (`react` / `reflect`) and reusable mission artifacts.

### Tests
- Added mission proposal regressions.
- Total: **623 tests pass**.

### Validation
- Local `pytest -q`: PASS, 623 tests.
- Local `pytest --collect-only`: PASS, 623 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live validation: PASS for mission template listing, mission compose, mission create, and mission run. Mission propose is implemented and covered locally in the same release cycle.

## v3.15.0 - 2026-06-22

### Added
- **Mission composition surfaces** — added `GET /v1/mission/templates`, `POST /v1/mission/compose`, `POST /v1/mission/create`, and `POST /v1/mission/run`, giving the bridge first-party mission composition and execution APIs instead of leaving missions as a CLI-only side surface.
- **MCP mission tools** — added `mission.templates`, `mission.compose`, `mission.create`, and `mission.run` so agent frontends can compose and launch reusable missions without custom REST wiring.

### Improved
- **The next big roadmap block has started** — Arena now has the first real implementation slice of deeper agent loops / mission composition on top of the already-shipped planner, ReAct, reflection, memory, tasks, and desktop stack.
- **Mission drafts are planner-backed** — mission composition now turns a goal into a reusable mission draft with a selected template, planner steps, required tools, risks, and a suggested memory profile.
- **Mission execution is no longer hidden behind the CLI** — agents can now create a mission artifact and trigger the built-in mission manager through API and MCP.

### Fixed
- **Mission runner hook helpers restored** — the built-in mission manager now imports its pre/post mission hook helpers explicitly, so `mission.run` no longer crashes with `NameError: _fire_mission_hook`.

### Tests
- Added mission composition/runtime/handler regressions.
- Total: **622 tests pass**.

### Validation
- Local `pytest -q`: PASS, 622 tests.
- Local `pytest --collect-only`: PASS, 622 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.14.0 - 2026-06-21

### Added
- **High-level text-driven desktop workflow (`D3`)** — added `POST /v1/desktop/text_action`, a composable OCR → window-target → desktop-action flow that can resolve, focus, click, or apply semantic window actions from visible text.
- **MCP `desktop.text_action`** — the same high-level text-driven desktop workflow is now available via MCP.

### Improved
- **`D2 / D3` desktop maturity is now complete enough to count as done** — Arena now has exact/phrase-first OCR ranking, click-by-text, OCR-to-window resolution, query-driven focus/window actions, display-aware placement, snap/tile-style placement, stronger non-interactive KWin Wayland focus, and richer multi-monitor semantics.
- **Roadmap priority shifts forward** — with the desktop maturity slice completed enough to count, the next recommended focus moves to deeper agent loops / mission composition and workspace UI v3 rather than more foundational desktop plumbing.
- **Desktop actions are more composable** — OCR, display-aware targeting, window resolution, focus, click, and window actions can now be chained through one workflow surface instead of being manually orchestrated by every client.

### Tests
- Added text-driven workflow regressions.
- Total: **619 tests pass**.

### Validation
- Local `pytest -q`: PASS, 619 tests.
- Local `pytest --collect-only`: PASS, 619 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `resolve_text_target`, query-driven `focus` dry-run, query-driven `window_action` dry-run / center, and `snap_right`.

## v3.13.1 - 2026-06-21

### Improved
- **OCR-to-window resolution is more practical on KDE/Wayland** — `resolve_text_target`, query-driven `desktop.focus`, and query-driven `desktop.window_action` can now crop OCR work to the active window, which reduces noisy full-screen scans and makes text-to-window targeting much more usable on the live bridge.
- **Text-aware desktop workflows are more reliable** — the new query-driven flows now compose OCR, window resolution, and desktop actions with less timeout risk when the relevant text is already on the active window.

### Tests
- Added active-window crop coverage for OCR-to-window targeting.
- Total: **617 tests pass**.

### Validation
- Local `pytest -q`: PASS, 617 tests.
- Local `pytest --collect-only`: PASS, 617 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `resolve_text_target`, query-driven `focus` dry-run, query-driven `window_action` dry-run / center, and `snap_right`.

## v3.13.0 - 2026-06-21

### Added
- **OCR-to-window resolution (`D3`)** — added `POST /v1/desktop/resolve_text_target`, which resolves recognized text into both a click target and the containing desktop window.
- **MCP `desktop.resolve_text_target`** — text-to-window resolution is now available through the MCP surface.

### Improved
- **`desktop.focus` can now use OCR text queries** — agents can focus the window containing visible text instead of relying only on ids/titles/classes.
- **`desktop.window_action` can now use OCR text queries** — semantic window actions can target the window containing visible text, not just windows resolved by metadata filters.
- **Desktop workflows are more composable** — windows, OCR, display-awareness, and semantic actions now interlock more directly instead of living as separate primitives.

### Tests
- Added OCR-to-window target resolution and query-driven focus/window-action regressions.
- Total: **617 tests pass**.

### Validation
- Local `pytest -q`: PASS, 617 tests.
- Local `pytest --collect-only`: PASS, 617 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `resolve_text_target`, query-driven `focus` dry-run, and query-driven `window_action` dry-run / center on a real helper window.

## v3.12.0 - 2026-06-21

### Added
- **Snap/tile-style placement actions (`D3`)** — `desktop.window_action` now supports `snap_left`, `snap_right`, `snap_top`, `snap_bottom`, `snap_top_left`, `snap_top_right`, `snap_bottom_left`, and `snap_bottom_right`.

### Improved
- **Display-aware planning now covers tiling semantics** — window-action planning can now translate higher-level placement intents into deterministic geometry on the resolved display instead of requiring raw coordinates.
- **Display-aware dry-runs are richer again** — semantic placement actions like `snap_right` now preview the exact geometry that will be applied before the action runs.
- **Desktop maturity advanced from placement to layout policies** — the bridge now has the beginnings of monitor-aware tiling behavior on top of raw move/resize primitives.

### Tests
- Added snap-placement planning regressions.
- Total: **613 tests pass**.

### Validation
- Local `pytest -q`: PASS, 613 tests.
- Local `pytest --collect-only`: PASS, 613 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `snap_right`; multi-display placement remains validated through unit coverage when only one live display is exposed.

## v3.11.0 - 2026-06-21

### Added
- **Higher-level display-aware window actions (`D3`)** — `desktop.window_action` now supports `center` and `move_to_display`, building semantic multi-monitor behavior on top of the earlier low-level move/resize actions.

### Improved
- **Window-action dry-runs are more informative** — when the action is display-aware (`center` / `move_to_display`), dry-run responses now include planned geometry plus source/target display info.
- **Display-aware planning is reusable** — window action geometry planning now lives in a dedicated helper, making desktop policies easier to extend without growing the execution backend into another monolith.
- **Desktop roadmap advanced again** — the bridge now has not just primitive window movement but actual display-aware placement semantics.

### Tests
- Added centered-placement and move-to-display planning regressions.
- Total: **612 tests pass**.

### Validation
- Local `pytest -q`: PASS, 612 tests.
- Local `pytest --collect-only`: PASS, 612 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `center`; `move_to_display` remains unit-validated because the current live machine exposes only one active display.

## v3.10.0 - 2026-06-21

### Added
- **More complete window actions (`D3`)** — `desktop.window_action` now supports `maximize`, `unmaximize`, and `close` in addition to the previously added move/resize/minimize/restore/fullscreen operations.

### Improved
- **KWin/Wayland maximize and close flows validated live** — non-interactive KWin window actions now cover maximize/unmaximize/close on UUID-style Wayland windows without reintroducing focus-stealing behavior.
- **Maximize verification is geometry-aware** — when KWin expands a window geometrically but does not expose maximized flags in the listing payload, verification now still succeeds by comparing before/after geometry growth.
- **Desktop docs updated again** — release notes and roadmap state now reflect that the desktop window-action surface has moved beyond the initial move/resize slice.

### Tests
- Added maximize-by-geometry regression coverage.
- Total: **609 tests pass**.

### Validation
- Local `pytest -q`: PASS, 609 tests.
- Local `pytest --collect-only`: PASS, 609 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `maximize`, `unmaximize`, and `close` on a real helper window.

## v3.9.1 - 2026-06-21

### Fixed
- **KWin window-action result metadata** — the non-interactive KWin window-action helper no longer returns a stale `error: "window_not_found"` field on successful actions like move/resize/minimize/restore.

### Validation
- Local `pytest -q`: PASS, 607 tests.
- Local `pytest --collect-only`: PASS, 607 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.9.0 - 2026-06-21

### Added
- **Window actions (`D3` slice)** — added `POST /v1/desktop/window_action`, supporting semantic target resolution plus actions like `move`, `resize`, `move_resize`, `minimize`, `restore`, `fullscreen`, and `unfullscreen`.
- **MCP `desktop.window_action`** — window manipulation is now available through the MCP tool surface in addition to REST.

### Improved
- **Semantic target resolution is now reusable across desktop controls** — focus and window actions both reuse the same filtered window-catalog resolution path (`id`, `title`, `class`, `desktop_file`, `resource_name`, `pid`, `display`).
- **KWin/Wayland window actions stay non-interactive** — UUID-style Wayland windows can now be manipulated through a temporary journal-reporting KWin script path without reintroducing interactive focus-stealing behavior.
- **Desktop docs updated again** — README, OpenAPI, prompt docs, and canonical roadmap now reflect display-aware windows, focus dry-runs, and the new window-action surface.

### Tests
- Added KWin window-action, action verification, semantic dry-run, and MCP/handler regressions.
- Total: **607 tests pass**.

### Validation
- Local `pytest -q`: PASS, 607 tests.
- Local `pytest --collect-only`: PASS, 607 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.8.0 - 2026-06-21

### Added
- **Window-management targeting (`D3` slice)** — `/v1/desktop/windows` now supports semantic filtering by title, class, desktop file, resource name, pid, display, and active-only state, with optional display metadata in the response.
- **Focus dry-run resolution** — `POST /v1/desktop/focus` now supports `dry_run: true`, so agents can resolve the target window and inspect candidates before actually stealing focus.
- **MCP `desktop.windows` and `desktop.focus`** — richer desktop window inspection and focus control are now available through the MCP surface.

### Improved
- **KWin/Wayland focus path is stronger and still non-interactive** — focus can now use a temporary journal-reporting KWin script for UUID-style Wayland window ids instead of relying only on numeric/X11-style activation paths.
- **Window metadata is now display-aware** — window listings annotate the owning display/output, which compounds with the new `/v1/desktop/displays` surface for multi-monitor correctness.
- **Desktop API docs are fuller** — OpenAPI and prompt docs now describe display discovery, filtered window listing, and safer focus-resolution workflows.

### Tests
- Added display-aware window catalog, focus dry-run, KWin focus helper, and filtered window-list regressions.
- Total: **604 tests pass**.

### Validation
- Local `pytest -q`: PASS, 604 tests.
- Local `pytest --collect-only`: PASS, 604 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.7.0 - 2026-06-21

### Added
- **Desktop semantic click-by-text (`D2`)** — added `POST /v1/desktop/click_text`, which runs OCR, ranks the best text match, and clicks it in one step with optional `dry_run`, active-window preference, target edge selection, and click offsets.
- **Desktop display/output discovery (`D3` slice)** — added `GET /v1/desktop/displays`, returning output geometry and active-display metadata for multi-monitor aware automation.
- **MCP `desktop.click_text` and `desktop.displays`** — semantic desktop targeting and display discovery are now available over the MCP tool surface in addition to REST.

### Improved
- **OCR match ranking is now exact/phrase-first** — `desktop.find_text` and OCR-backed desktop targeting now prioritize exact and phrase matches over weak substring noise, fixing the live-class issue where a query like `Google` could degrade to a one-letter best match.
- **Active-window-aware text targeting** — OCR text matching can now prefer or constrain matches to the current active window, improving desktop targeting correctness on busy multi-window setups without reintroducing interactive KWin focus-stealing behavior.
- **Display-scoped screenshot/OCR targeting** — desktop screenshot, OCR, text-find, and click-by-text flows can now be restricted to a named display/output, improving multi-monitor correctness.
- **OpenAPI / prompt docs updated** — the public API spec and AI prompt template now document the new semantic desktop targeting and display-aware flow.

### Tests
- Added ranking, active-window scoping, semantic click handler, display discovery, display scoping, route, and MCP regressions for the new desktop maturity slice.
- Total: **600 tests pass**.

### Validation
- Local `pytest -q`: PASS, 600 tests.
- Local `pytest --collect-only`: PASS, 600 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.6.1 - 2026-06-21

### Added
- **Workspace dashboard v2** — the Workspace tab now includes profile notes, important lessons, and recent activity panels on top of the existing profile context, planner, ReAct/reflection, and file watcher surfaces.
- **Workspace v2 dashboard regressions** — added checks that the new asset bundle and workspace v2 surface are wired into the dashboard bootstrap.

### Validation
- Local `pytest -q`: PASS, 593 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/25-workspace-v2.js`: PASS.

## v3.6.0 - 2026-06-21

### Added
- **Desktop OCR + text-target detection (`D1`)** — added `POST /v1/desktop/ocr` and `POST /v1/desktop/find_text`, returning recognized words, full text, confidence, bounding boxes, and click-ready center coordinates.
- **MCP desktop OCR tools** — added `desktop.ocr` and `desktop.find_text` for OCR and text-target detection through Arena's MCP layer.
- **Tesseract TSV parsing and matching helpers** — OCR now groups recognized words into lines, exposes bounding boxes, and supports multi-word text matching with aggregated coordinates.

### Improved
- **OpenAPI updated** — OCR/text-target detection endpoints are now documented in the public API spec.
- **Prompt/template docs updated** — `docs/AI_PROMPT_TEMPLATE.md` now documents OCR and text-target detection for desktop automation.
- **Desktop API surface expanded** — desktop automation now includes OCR and semantic text targeting in addition to screenshots, windows, input, and focus APIs.

### Tests
- Added desktop OCR parsing, handler, runtime reexport, MCP, and route regressions.
- Total: **592 tests pass**.

### Validation
- Local `pytest -q`: PASS, 592 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.5.2 - 2026-06-21

### Added
- **Workspace dashboard surface v1** — the dashboard now has a dedicated **Workspace** tab that brings companion-style UI around the new backend foundations: active profile context, planner output, bounded ReAct runs, reflection, and file watcher management.
- **Workspace dashboard regressions** — added tests ensuring the new dashboard tab and assets are wired into the bootstrap shell.

### Improved
- **Dashboard navigation updated** — `/gui` now exposes the Workspace tab alongside Overview, Memory, Recall, Tasks, Control, and the rest of the operational UI.
- **README / README.ru dashboard docs updated** — tab counts and descriptions now reflect the Workspace and Control surfaces.
- **Canonical roadmap advanced** — after shipping planner, watchers, safe editing, and ReAct/reflection, the roadmap now points at workspace UI surfaces as the primary next layer of product polish.

### Validation
- Local `pytest -q`: PASS, 588 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/24-workspace.js`: PASS.

## v3.5.1 - 2026-06-21

### Fixed
- **ReAct/reflection live runtime fix** — agentic endpoints now read app config through the shared aiohttp `AppKey` instead of the old raw string key, so `/v1/react`, `/v1/reflect`, `react.run`, and `reflect.run` work correctly on the installed bridge after the `v3.5.0` modular AppKey migration.

### Validation
- Local `pytest -q`: PASS, 586 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.5.0 - 2026-06-20

### Added
- **Bounded ReAct loop foundation (`A2`)** — added `POST /v1/react`, which runs a safe reason → act → observe loop derived from the built-in planner and executes bounded observation steps such as memory recall, bridge status, doctor/sysinfo, task listing, file watcher listing, and optional browser HEAD checks.
- **Reflection endpoint (`A3`)** — added `POST /v1/reflect`, which critiques a prior run and returns positives, concerns, missing evidence, confidence, and suggested next steps.
- **MCP `react.run` and `reflect.run`** — the same agentic surfaces are now available through Arena's MCP tool layer.
- **OpenAPI updated** — `/v1/react` and `/v1/reflect` are now documented in the public API spec.

### Improved
- **Canonical roadmap advanced** — `A1` was already complete; `A2/A3` now have an implementation foundation, and the next practical priority shifts toward workspace UI surfaces and deeper agent loops rather than basic planning plumbing.
- **Agentic runtime reuses existing foundations** — planner, memory profiles, task queue state, file watchers, bridge status, and browser HEAD checks now feed into a unified bounded loop instead of staying isolated features.

### Tests
- Added agentic runtime, handler, route, and MCP regressions.
- Total: **586 tests pass**.

### Validation
- Local `pytest -q`: PASS, 586 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.4.2 - 2026-06-20

### Added
- **Safe editor foundation (`F4`)** — `PATCH /v1/fs/edit` now supports `preview: true` for a non-destructive preview/confirm workflow.
- **Edit confirmation endpoint** — added `POST /v1/fs/edit/apply` to apply a previously previewed edit by `preview_id`.
- **Rollback endpoint** — added `POST /v1/fs/edit/rollback` to restore the pre-edit contents using `rollback_id`.
- **MCP safe editor support** — added `fs.edit_apply` and `fs.edit_rollback`, while `fs.edit` now supports `preview=true`.

### Improved
- **Safe edit conflict protection** — applying a preview now refuses to write if the target file changed after the preview was generated.
- **Rollback conflict protection** — rollback refuses to overwrite a file that changed again after apply unless explicitly forced.
- **AI prompt template updated** — the prompt now documents the preview/apply/rollback edit workflow.
- **OpenAPI updated** — safe editor endpoints and preview semantics are now documented.

### Tests
- Added safe-editor regressions covering preview, apply, rollback, conflict detection, new routes, and MCP schemas.
- Total: **582 tests pass**.

### Validation
- Local `pytest -q`: PASS, 582 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.4.0 - 2026-06-20

### Added
- **Built-in Planner (`A1`)** — added `POST /v1/plan`, a first-party planner endpoint that turns a goal into a structured execution plan with steps, risks, required tools, next action, and a suggested Memory Profile.
- **MCP `plan.create`** — the planner is now available through Arena's MCP surface, so coding/agent frontends can request plans without custom REST wiring.
- **Planner heuristics** — the first planner infers likely domains (code, browser, desktop, system, task queue), suggests a memory profile, and marks higher-risk steps as requiring confirmation.

### Improved
- **OpenAPI docs updated** with `/v1/plan`.
- **Canonical roadmap advanced** — `A1` is now complete, and the recommended next step moves to `F5` File Watchers.

### Tests
- Added planner logic, handler, route, and MCP regressions.
- Total: **579 tests pass**.

### Validation
- Local `pytest -q`: PASS, 579 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.3.1 - 2026-06-20

### Added
- **DX2 integration recipe set** — added `docs/INTEGRATIONS.md` plus concrete recipe docs for Arena Agent Mode, Claude-style chats, Cursor, Cline, Windsurf, Open Interpreter, and local model backends.
- **Integration doc regression tests** — added coverage ensuring the recipe index exists, the expected recipe files are present, and they mention profile-aware memory usage.

### Improved
- **AI prompt template refreshed for Memory Profiles.** `docs/AI_PROMPT_TEMPLATE.md` now teaches agents to use scoped profiles like `projects/<name>`, `personal`, `code`, and `browser` instead of dumping everything into one memory bucket.
- **README / README.ru now point at the integration recipe index**, making the new documentation easier to discover.
- **Canonical roadmap updated** — `DX2` is now considered complete and the recommended next step shifts to `A1` Built-in Planner.

### Validation
- Local `pytest -q`: PASS, 569 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.3.0 - 2026-06-19

### Added
- **Memory Profiles (`M3`)** — memory is now scoped by profile across REST, MCP, runtime, and dashboard flows. Facts may live in spaces like `default`, `personal`, `projects/<name>`, `code`, `browser`, or custom profile ids.
- **Profile-aware REST memory API** — `/v1/memory`, `/v1/recall`, and `/v1/recall/digest` now accept `profile`, and `/v1/memory` responses include `profile` plus discovered `profiles`.
- **Profile-aware MCP memory tools** — `mem.set`, `mem.get`, `memory.recall`, `memory.digest`, `memory.export`, and `memory.import` now understand profiles.
- **Memory schema migration** — existing single-profile SQLite memory stores are migrated automatically into the `default` profile without data loss.
- **Dashboard profile controls** — Memory and Recall tabs now let the user choose the active memory profile and keep it synced locally.

### Changed
- **Memory DB schema upgraded** from `PRIMARY KEY(key)` to `PRIMARY KEY(profile, key)`, allowing the same key to exist independently in multiple profiles.
- **`agentctl` memory commands** now understand `--profile`, and CLI recall output is aligned with the profile-aware API.
- **OpenAPI memory docs** now document profile-aware memory and recall usage.

### Tests
- Added coverage for memory schema migration, cross-profile key isolation, profile-scoped CRUD/recall handlers, MCP profile support, and export/import round-trips with profile preservation.
- Total: **566 tests pass**.

### Validation
- Local `pytest -q`: PASS, 566 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.14 - 2026-06-19

### Removed
- **Dead release scratch files removed from the repository.** Old `release_v*.md` note files and the obsolete `bump_v323.py` helper were deleted because they were not part of the runtime product and only added noise to the tree and release zip.

### Improved
- **Release hygiene guardrail.** `.gitignore` now ignores future `release_v*.md` and `bump_v*.py` scratch files so they do not accumulate again.
- **Release process docs clarified.** `RELEASE.md` now explicitly tells maintainers to use a temporary/untracked notes file for GitHub releases instead of committing per-release scratch markdown into the repository.

### Validation
- Local `pytest -q`: PASS, 558 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.13 - 2026-06-19

### Fixed
- **Stale backup surface removed from the CLI/workflow layer.** `agentctl backup run` no longer tries to call the long-removed `/v1/backup` API and now prints an explicit deprecation notice instead.
- **Mission templates no longer reference removed backup commands.** `cli-agent-core` and `recovery-drill` were updated to use existing audit/status checks instead of dead `backup ls` steps.
- **`agentctl` version string now follows the canonical bridge version.** The CLI no longer advertises a stale hard-coded `2.0.0` while the bridge is on a newer release.

### Documentation
- Added `docs/ROADMAP_CANONICAL.md` as the planning source of truth.
- Added `docs/PRODUCT_DIRECTION.md` to capture the "Arena Companion Mode" product direction.
- Added `docs/EXPERIMENTS.md` to isolate risky ideas like browser/session-driven model proxies from the core roadmap.

### Tests
- Added regressions covering the removed-backup CLI notice, canonical `agentctl` version wiring, and mission templates no longer emitting backup commands.
- Total: **558 tests pass**.

### Validation
- Local `pytest -q`: PASS, 558 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.12 - 2026-06-19

### Fixed
- **Race condition in the v2 rate limiter removed.** `arena/rate_limit.py::check_rate_limit_v2()` now performs endpoint-store cleanup while still holding `_rl_v2_lock`, instead of mutating `_rl_v2_store[user_id]` after releasing the lock.

### Tests
- Added a regression test that wraps `_rl_v2_store` in a lock-aware dictionary and fails if shared rate-limit state is touched outside the lock.
- Total: **553 tests pass**.

### Validation
- Local `pytest -q`: PASS, 553 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.11 - 2026-06-19

### Fixed
- **Removed the interactive KWin query that was stealing desktop focus/cursor.** `/v1/desktop/active_window` no longer calls `org.kde.KWin.queryWindowInfo`, which on the live Plasma session could trigger a crosshair-style window picker and repeatedly steal focus from the user.
- **KWin script loading no longer rejects valid `loadScript=0` responses.** `/v1/desktop/windows` and native active-window discovery now treat the DBus call itself as success and rely on journal output to determine whether the script actually ran, matching observed Plasma behavior.
- **Active-window discovery now prefers native KWin journal data.** On KDE/Wayland, `/v1/desktop/active_window` now uses the same non-interactive native KWin listing path as `/v1/desktop/windows`, returning the active entry from that list before falling back to X11 tools.
- **Capability map updated to match runtime reality.** `/v1/capabilities` now reports `kwin_journal` for both window listing and active-window discovery on KDE/Wayland.

### Tests
- Reworked desktop runtime tests around the non-interactive KWin journal path and added regression coverage for `loadScript` returning `0` while the script still executes correctly.
- Total: **552 tests pass**.

### Validation
- Local `pytest -q`: PASS, 552 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.10 - 2026-06-19

### Fixed
- **KDE active-window fallback now uses native KWin window data when direct DBus lookup is cancelled.** When `org.kde.KWin.queryWindowInfo` returns `org.kde.KWin.Error.UserCancel` or otherwise yields no usable data, `/v1/desktop/active_window` now tries the already-working KWin journal-based window listing and returns the active entry from there before falling back to `xdotool`.

### Tests
- Added regression coverage for the `queryWindowInfo` cancellation path to ensure `_get_active_window()` reuses the native KWin window list instead of jumping straight to `xdotool`.
- Total: **552 tests pass** (no regressions; test suite currently collects 552 tests).

### Validation
- Local `pytest -q`: PASS, 552 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.9 - 2026-06-19

### Fixed
- **KWin active-window lookup now retries briefly before giving up.** `/v1/desktop/active_window` now retries `org.kde.KWin.queryWindowInfo` up to three times with a tiny delay before falling back to `xdotool`, smoothing out the intermittent empty-response case seen on the live Plasma/Wayland session.

### Tests
- Added regression coverage for the KWin retry path when the first DBus active-window query returns an empty payload.
- Total: **552 tests pass** (was 551, +1 new).

### Validation
- Local `pytest -q`: PASS, 552 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.8 - 2026-06-19

### Fixed
- **KWin active-window detection is more stable on helper windows/panels.** `/v1/desktop/active_window` now accepts any non-empty `queryWindowInfo` payload from KWin instead of requiring a `caption` or `uuid`, so Plasma-managed focus proxies and other minimal windows no longer force a fallback to `xdotool` just because KWin omitted those two fields.

### Tests
- Added regression coverage for KWin active-window payloads that expose only `resourceClass` / `resourceName` plus geometry.
- Total: **551 tests pass** (was 550, +1 new).

### Validation
- Local `pytest -q`: PASS, 551 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.7 - 2026-06-19

### Fixed
- **Native KDE window listing now actually works.** The temporary KWin script used by `/v1/desktop/windows` no longer tries to unload itself via `callDBus(...)` from inside the script body — that line caused `loadScript` to return `0` on the live Plasma session, so the bridge always fell back to `xdotool`. Unloading is handled purely from Python now.
- **Capability map now distinguishes KWin backends correctly.** `/v1/capabilities` reports `windows.backend = kwin_journal` and `active_window.backend = kwin_dbus` on KDE/Wayland instead of claiming the same backend for both operations.

### Tests
- Added regression coverage proving the KWin helper unload still happens from Python and that KDE/Wayland capabilities report separate backends for window listing vs active-window discovery.
- Total: **550 tests pass** (was 549, +1 new).

### Validation
- Local `pytest -q`: PASS, 550 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.6 - 2026-06-19

### Fixed
- **KDE/Wayland active window detection restored.** `/v1/desktop/active_window` now uses `org.kde.KWin.queryWindowInfo` instead of outdated DBus calls that no longer worked on modern Plasma, so Wayland sessions can report the focused window again.
- **KWin window listing no longer depends on missing desktop env vars.** `/v1/desktop/windows` now probes KWin directly over DBus before loading the temporary scripting helper, fixing live installs where `WAYLAND_DISPLAY` existed but `XDG_CURRENT_DESKTOP` / `XDG_SESSION_TYPE` were absent in the bridge service environment.
- **Session bootstrap now self-heals desktop metadata.** `ensure_session_env()` now infers `XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`, and `DESKTOP_SESSION` when possible, including KDE detection via KWin DBus, so `/v1/capabilities` and desktop helpers report a more accurate runtime picture.
- **aiohttp `NotAppKeyWarning` removed from the bridge runtime/tests.** Shared app state (`cfg`, MCP sessions, lifecycle tasks) now uses proper `aiohttp.web.AppKey` definitions instead of raw string keys.

### Improved
- **Linux systemd installer now preserves desktop session metadata.** `install.sh` writes `XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`, and `DESKTOP_SESSION` into the user service when those values are available at install time.
- **Capability reporting is more accurate.** `/v1/capabilities` now prefers the detected desktop/session metadata instead of reading only raw environment variables.
- **README counts refreshed.** Route and desktop endpoint counts were updated to match the modular v3.2.x surface more closely and avoid stale hard-coded numbers.

### Tests
- Added regression coverage for desktop session bootstrap inference, KWin active-window parsing, KWin window-list probing without desktop env vars, and installer export of desktop session metadata.
- Total: **549 tests pass** (was 545, +4 new).

### Validation
- Local `pytest -q`: PASS, 549 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.5 - 2026-06-19

### Added
- **MCP `git.status`** — show working tree status
- **MCP `git.diff`** — show staged/unstaged changes
- **MCP `git.log`** — show recent commits
- **MCP `git.commit`** — stage all + commit

### F6 Git Integration: COMPLETE
### Tests: 545 passed (+17 new)

## v3.2.4 - 2026-06-19

### Added
- **MCP `fs.tree`** — directory tree with ├──/└── connectors, file sizes, max_depth, glob filter, show_files toggle.
- **MCP `fs.diff`** — unified diff between two files (difflib format).
- **MCP `memory.export`** — export all memory facts as JSONL text.
- **MCP `memory.import`** — import memory facts from JSONL (upsert, overwrite mode, error reporting).

### fs.* toolkit complete
The fs.* family now has **10 tools**: read, write, list, edit, view, create, search, grep, tree, diff.

### Memory tools
Memory now has **4 tools**: mem.set, mem.get, memory.recall, memory.digest + **memory.export** + **memory.import** (new).

### Tests
- tests/test_fs_tree_diff.py — 17 tests
- tests/test_memory_export_import.py — 13 tests (incl. roundtrip: export→import)

Total: **528 tests pass** (was 498, +30 new).

## v3.2.3 - 2026-06-19

### Added
- **MCP `fs.search` tool** — search file contents by regex pattern. Supports glob filter, context lines, case-insensitive mode, max_results limit. Skips sensitive files, hidden directories, and binary files.
- **MCP `fs.grep` tool** — alias for fs.search (familiar name for grep users).

### Security
- Path must be inside home directory (path traversal blocked)
- SENSITIVE_FILE_BASENAMES skipped (token.txt, .env, SSH keys, etc.)
- Hidden directories skipped (.git, __pycache__, node_modules, .venv)
- File size limit: 512KB per file; max 500 files scanned; max 200 results

### Tests
- tests/test_fs_search.py — 17 tests (basic search, directory search, no matches, errors, glob filter, ignore_case, context lines, max_results, blocked files, hidden dirs, grep alias, registry schema)

Total: **498 tests pass** (was 481, +17 new).

### Validation
- 498 tests pass (no regressions)
- py_compile OK
- Bridge /v1/doctor: 10/10

## v3.2.2 - 2026-06-18

### Added
- **REST `POST /v1/fs/view`** — HTTP equivalent of MCP `fs.view`. Read file with optional `view_range=[start, end]`. Returns JSON with content, line range, and total lines.
- **REST `POST /v1/fs/create`** — HTTP equivalent of MCP `fs.create`. Create new file (fails if exists). Creates parent directories.
- **OpenAPI spec** — `/api-docs` now includes `/v1/fs/view` and `/v1/fs/create` with request/response schemas.
- **DuckDuckGo search tests** — 10 formal tests for the DDG lite HTML parser (no network, mock HTML). Covers: result parsing, n parameter, empty results, HTML tag stripping, URL decoding, User-Agent header.

### Refactored
- **Sensitive file blocklist deduplicated** — `SENSITIVE_FILE_BASENAMES` (frozenset) in `arena/files/sandbox.py` is now the single source of truth. `_MCP_BLOCKED_FILES` in `tool_fs.py` and `_EDIT_BLOCKED_BASENAMES` are aliases of the same object. Adding a new sensitive file now requires editing one place, not two.

### Documentation
- **README "What's new"** updated from v3.1.5/v3.1.6 to v3.2.1 (both EN and RU).

### Tests
- `tests/test_fs_rest_view_create.py` — 26 tests (sandbox validators + handler behavior + route registration + auth)
- `tests/test_ddg_search.py` — 10 tests (mock HTML parsing, no network)
- Total: **481 tests pass** (was 445, +36 new since v3.2.1).

### Files changed
- `arena/files/sandbox.py` — +validate_view_target, +validate_create_target, SENSITIVE_FILE_BASENAMES
- `arena/files/fs_view_create.py` — new module, FsViewCreateHandlers + factory
- `arena/mcp/tool_fs.py` — import SENSITIVE_FILE_BASENAMES from sandbox (dedup)
- `arena/runtime_deps/core.py` — import make_fs_view_create_handlers
- `arena/wiring/observability_registries.py` — handler mappings for view/create
- `arena/route_registry/core.py` — POST /v1/fs/view + POST /v1/fs/create routes
- `arena/public/openapi.py` — OpenAPI spec for fs/view + fs/create
- `tests/test_fs_rest_view_create.py` — new, 26 tests
- `tests/test_ddg_search.py` — new, 10 tests
- `README.md` + `README.ru.md` — "What's new" updated
- `arena/constants.py` + `pyproject.toml` — version bump
- `CHANGELOG.md` — this entry

### Validation
- 481 tests pass (no regressions)
- py_compile OK for all changed files
- Bridge `/v1/doctor`: 10/10 checks pass

## v3.2.1 - 2026-06-18

### Added
- **MCP `fs.view` tool** — view file contents with line numbers. Optional `view_range=[start, end]` for reading a specific line range (1-indexed, inclusive). Returns line-numbered output matching Anthropic's `str_replace_editor` format.
- **MCP `fs.create` tool** — create a new text file. Fails if file already exists (use `fs.edit` to modify). Creates parent directories if needed. Both tools reuse `_validate_home_path` for path traversal + blocked file protection.
- **OpenAPI spec updated** — `/api-docs` now includes `POST /v1/upload`, `GET /v1/download`, and `PATCH /v1/fs/edit` with request/response schemas. New "Files" tag added.

### Tests
- **`tests/test_fs_edit.py`** (18 tests): MCP `fs.edit` success/replace_all/not_found/multiple_matches/empty/blocked/noop, `validate_edit_target` traversal/bridge/sensitive_files/not_found, REST route registration, schema validation.
- **`tests/test_fs_view_create.py`** (14 tests): `fs.view` full/range/not_found/invalid_range/blocked, `fs.create` success/exists/empty/parent_dirs/blocked, registry schema validation.

Total: **445 tests pass** (was 431, +14 new for view/create; +18 new for edit = +32 total since v3.2.0).

### str_replace_editor parity complete
The `fs.*` tool family now has full parity with Anthropic's `str_replace_editor`:
  - `fs.read` — read file (existing)
  - `fs.write` — write file (existing)
  - `fs.list` — list directory (existing)
  - `fs.view` — view with line numbers + range (new)
  - `fs.create` — create new file (new)
  - `fs.edit` — find-and-replace (added in v3.2.0)

AI coding agents (Claude Code, Cline, Cursor) can now use Arena's MCP server as a complete filesystem tool backend.

### Validation
- 445 tests pass (no regressions).
- py_compile OK for all changed files.
- Bridge `/v1/doctor`: 10/10 checks pass.

### Files changed
- `arena/mcp/tool_fs.py` — +`_handle_fs_view`, +`_handle_fs_create`, dispatch for fs.view/fs.create
- `arena/mcp/tool_registry.py` — +fs.view, +fs.create in MCP_TOOLS
- `arena/public/openapi.py` — +upload, +download, +fs/edit, +Files tag
- `tests/test_fs_edit.py` — new, 18 tests
- `tests/test_fs_view_create.py` — new, 14 tests
- `arena/constants.py` — version bump
- `pyproject.toml` — version bump
- `CHANGELOG.md` — this entry

## v3.2.0 - 2026-06-18

### Added
- **MCP `fs.edit` tool** — find-and-replace in text files, mirroring Anthropic's `str_replace_editor` semantics. AI coding agents (Claude Code, Cline, Cursor) can now do surgical file edits via MCP without re-uploading the whole file. Supports `replace_all` for multi-occurrence replacement. Reuses `_validate_home_path` + `_MCP_BLOCKED_FILES` for security (path traversal protection, blocks `token.txt`, `.env`, SSH keys, etc.).
- **REST `PATCH /v1/fs/edit` endpoint** — HTTP equivalent of the MCP tool. Same find-and-replace semantics, same security model. Enables AI agents without MCP support (like popbob's Local API pattern, or simple curl scripts) to do surgical edits. Body: `{"path": "...", "old_text": "...", "new_text": "...", "replace_all": false}`. Returns `{"ok": true, "path": "...", "replacements": N, "bytes": N}`.
- **Arena Agent Mode integration** — new documentation section explaining how to use Arena Unified Bridge as the tool backend for Arena.ai's free frontier models (Claude Opus, GPT-5, Grok). Paste the system prompt from `docs/AI_PROMPT_TEMPLATE.md` with your URL and token, and any Arena AI can drive your computer.
- **"Similar Projects" section in README** — honest comparison with 10 other open-source projects in the AI agent / computer-use space: Bytebot, OpenClaw, Open Interpreter, Agent S, Anthropic Computer Use, Cline, Desktop Commander MCP, MCP servers, awesome-mcp-servers, browser-use. Each entry includes stars, language, what it does, and how Arena differs. Includes disclaimer that Arena is independent and not affiliated with any listed project.

### Fixed
- **`/v1/browser/search` no longer returns 0 results** — DuckDuckGo's `html.duckduckgo.com/html/` endpoint stopped returning `result__a` CSS class names, breaking the parser. Switched to `lite.duckduckgo.com/lite/` which still works and uses `result-link` / `result-snippet` classes. Also fixed: in lite HTML, `href` attribute comes before `class` (opposite order from the html endpoint), so the regex was reordered. Used triple-quoted raw strings (`r'''...'''`) to avoid quoting conflicts.

### Security
- New `_EDIT_BLOCKED_BASENAMES` set in `arena/files/sandbox.py`: `token.txt`, `users.json`, `.env`, `id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa`, `.netrc`, `.ssh_config`. These files cannot be edited via `fs.edit` or `PATCH /v1/fs/edit`, even if they are inside the user's home directory.
- `fs.edit` and `PATCH /v1/fs/edit` cannot edit the bridge itself (`unified_bridge.py`).
- All file edit operations are audit-logged: `{"type": "file_edit", "path": "...", "replacements": N, "bytes": N}`.

### Validation
- 413 existing tests pass (no regressions).
- MCP `fs.edit` tested with 6 error cases: multiple matches, replace_all, not found, file not found, empty old_text, blocked file — all correct.
- REST `PATCH /v1/fs/edit` compile OK, pytest pass, logic identical to MCP tool.
- DDG search tested: `browser_search("python programming", 3)` returns 3 results with correct title, URL, snippet.
- Bridge `/v1/doctor`: 10/10 checks pass.

### Files changed
- `arena/mcp/tool_fs.py` — added `fs.edit` handler + `_handle_fs_edit` function
- `arena/mcp/tool_registry.py` — added `fs.edit` to `MCP_TOOLS` list
- `arena/files/sandbox.py` — added `validate_edit_target` + `_EDIT_BLOCKED_BASENAMES`
- `arena/files/handlers.py` — added `handle_v1_fs_edit` handler + `fs_edit` field
- `arena/route_registry/core.py` — added `PATCH /v1/fs/edit` route
- `arena/wiring/observability_registries.py` — added `handle_v1_fs_edit` mapping
- `arena/browser/fetch.py` — switched DDG to lite endpoint, updated CSS selectors
- `README.md` — File Operations table, Similar Projects section, Arena Agent Mode note
- `README.ru.md` — mirror all changes in Russian
- `docs/AI_PROMPT_TEMPLATE.md` — added fs.edit and PATCH /v1/fs/edit
- `arena/constants.py` — version bump
- `pyproject.toml` — version bump
- `CHANGELOG.md` — this entry

## v3.1.7 - 2026-06-17

### Fixed
- **Windows installer no longer crashes with "Непредвиденное появление: .."** The v3.1.6 `install.bat` used `^(...^)`, `^&^&`, and `\(...\)` to escape special characters inside `if (...)` blocks, but cmd does not honor `^` inside if-blocks - so the unescaped parens broke block balance and the parser died immediately after `Bridge v!VERSION!`.
- **Root cause:** the Soft version-check block used `curl ... | %PYTHON% -c "...d.get(\"tag_name\",\"\")..."` - the `\"` escapes inside a `for /f` single-quoted string broke the cmd parser.
- **Fix (install.bat v2.1.2):**
  - Replaced `curl | python -c` with a direct `python -c "import urllib.request,json; ..."` call that uses single-quoted Python strings (no `\"` escapes anywhere).
  - Rewrote the if/else cascade as a flat `if not defined ... () else if ... () else ()` so no nested parens inside if-blocks.
  - Replaced all `^(...^)` inside if-block echo lines with plain text using dashes.
  - Replaced `^&^&` in echo lines with the word "and" / commas.
  - Replaced `\(...\)` (backslash-parens) with plain text - cmd does not honor `\(` either.
  - Expanded inline `if errorlevel 1 (echo X) else (echo Y)` into multi-line if-blocks so parens do not collide with the surrounding block.
  - Used `!VAR!` (delayed expansion) consistently for variables set inside if-blocks (`TS_INSTALL_CONFIRM`, `CAM_CONFIRM`) - `%VAR%` would have been expanded to empty at parse time, breaking the Y comparison.

### Validated on Windows 10 LTSC 2021 (build 19044)
- `install.bat` runs cleanly through all 6 steps without parser errors.
- Soft version-check prints `[OK] You are on the latest release.` when v3.1.7 is current.
- Optional component prompts work: Tailscale, cloudflared, SuperPowers, BrowserAct, Camoufox.
- Bridge starts as Scheduled Task (wscript + start_hidden.vbs) and `/health` returns v3.1.7.
- `stress-test-v4.py --task-roundtrip`: **15 PASS / 3 SKIP / 0 FAIL**.
- `/v1/doctor`: 10/10 checks pass.
- `/v1/metrics`: 0% error rate over 541 requests.
- `/v1/memory` (set/get/delete), `/v1/exec` (whoami), `/v1/browser/fetch` (example.com), `/v1/sys/funnel` (Tailscale Funnel active) - all pass.

### Known limitations on Windows (not regressions)
- `/v1/desktop/*` endpoints return `"Windows desktop backend is not implemented yet"` - the win32 desktop automation backend is `pending-win32` in the roadmap. The bridge correctly reports this via `/v1/capabilities` and `stress-test-v4` SKIPs these endpoints.
- Russian (CP866) text in `nssm_service.raw` and `scheduled_task.raw` fields of `/v1/capabilities` may render as mojibake when decoded as UTF-8 - cosmetic only.

### No behavioral change on Linux/macOS
- `install.sh` is untouched in this release.
- The installer logic is identical to v3.1.6 on systems where the old `install.bat` worked - only the cmd escaping and the version-check implementation changed.

## v3.1.6 — 2026-06-17

### Fixed
- **Installer no longer silently downgrades existing installations.** `install.sh` (Linux/macOS) now reads the locally-installed version, fetches only the *current* branch from origin (never switches branches), compares local vs. remote versions semver-aware, and asks before updating. Updates use `git merge --ff-only` so local commits are never discarded. The destructive `git checkout -B <branch> FETCH_HEAD` pattern is gone.
- **Installer no longer defaults to the stale `v3-modular-core` branch.** Fresh installs now pull `master` (the current stable release branch). Override with `ARENA_BRANCH=<name>`.
- **`install.bat` (Windows) now informs about newer GitHub releases.** Soft version-check via the GitHub releases API prints an `[INFO]` line when a newer version exists. It never auto-updates and never switches branches - just informs the user.
- **Shipped `webhooks.json` no longer contains a dead debug URL.** Previous releases inherited `http://127.0.0.1:9999/webhook` from the repo, causing every fresh install to spam a non-existent endpoint (the v3.1.5 circuit breaker correctly backed off, but the config noise should not exist in the first place). Default is now `{urls: [], events: ["*"]}`.

### Refactored
- Replaced `asyncio.get_event_loop()` with `asyncio.get_running_loop()` across 18 files (43 call sites). All calls are inside async functions that immediately `await loop.run_in_executor(...)`, so the new API returns the same loop without the `DeprecationWarning` Python 3.12+ emits for `get_event_loop()` outside a running loop. No behavioral change.

### Tests
- Added `tests/test_installer_version_safety.py` (7 tests) guarding the installer fix: default branch is `master`, no destructive `git checkout -B`, fast-forward-only updates, `_arena_version_lt()` passes 12 semver cases (equal, v-prefix, double-digit patch, pre-release suffix, short versions), `install.bat` has soft version-check and does not git-pull/checkout the bridge itself.

### Documentation
- `README.md`: replaced the static `version-v3.1.5-blue` badge with a dynamic `shields.io/github/v/release/...` badge that auto-updates on every release - no more manual README edits just to bump the version number.
- `README.md`: added a new "### 3. Updating an existing installation" section documenting the safe-update behavior.

### Validation
- Local `pytest -q`: PASS, 413 tests (406 prior + 7 new installer guardrails).
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across all changed files: PASS.
- Live `install.sh` smoke test on a test clone: correctly reports `Local version: v3.1.6 / Remote version: v3.1.6 / Already up to date` and does not switch branches.
- Bridge `/v1/doctor`: 10/10 checks pass.

## v3.1.5 — 2026-06-17

### Fixed
- Added per-URL webhook circuit breaker/backoff so dead webhook targets are not retried and logged on every event.
- Webhook failure/recovery is now logged on state changes instead of flooding `bridge.log` continuously.

### Tests
- Added `tests/test_webhooks_backoff.py` covering threshold, cooldown, exponential retry, recovery, event filtering, and internal error logging.

### Validation
- Local `pytest -q`: PASS, 413 tests.
- Local critical ruff and py_compile: PASS.

## v3.1.4 — 2026-06-17

### Fixed
- Fixed a JavaScript syntax error in dashboard slash-command definitions that prevented slash suggestions and normal Terminal Run handling from working.
- Fixed `bin/agentctl` wrapper import path so GUI terminal commands such as `agentctl sys status` run successfully from the installed bridge directory.
- Simplified sidebar icons to one consistent icon per navigation item.

### Guardrails
- Added dashboard JavaScript syntax validation with `node --check` when Node.js is available.

### Validation
- Local `node --check dashboard/assets/*.js`: PASS.
- Local `pytest -q`: PASS, 408 tests.
- Local critical ruff and py_compile: PASS.
- CachyOS live validation required before publication.

## v3.1.3 — 2026-06-17

### Fixed
- Fixed GUI terminal `agentctl ...` commands by resolving them to the installed bridge bin path instead of relying on service PATH.
- Fixed GUI Quick Commands to render API results inside the terminal session instead of writing to a removed `termOutput` element.
- Fixed GUI memory deletion by using `DELETE /v1/memory` instead of the removed `/v1/memory/delete` route.
- Fixed GUI skill execution payload by sending `{name, args}` instead of `{skill}`.
- Fixed Control pause cancellation: pressing Cancel in the prompt no longer pauses control.
- Fixed modular inventory runtime/package/browser/env probes by restoring extracted constants (`RUNTIMES`, `PACKAGE_MANAGERS`, `BROWSERS`, `ENV_KEYS_OF_INTEREST`, platform browser paths).
- Fixed stale CDP client imports and MCP marketplace helper imports found by installed-wrapper smoke tests.

### Validation
- Local `pytest -q`: PASS, 407 tests.
- Local critical ruff and py_compile: PASS.
- Installed-wrapper smoke added/used for scripts/bin entrypoints.
- CachyOS live install, GUI BrowserAct smoke, endpoint smoke and stress are required before publication.

## v3.1.2 — 2026-06-16

### Fixed
- Fixed the modular dashboard layout regression introduced by the asset split: body fragments now replace the bootstrap root so `.sidebar` and `.main` are again direct flex children of `body`, matching the pre-split DOM layout.
- Fixed `scripts/cdp_browser.py` and `arena/browser/cdp_client/*` stale imports that still referenced the removed `cdp_browser_modules` package.
- Fixed `bin/mcp_marketplace.py list` after modularization by importing underscored registry helpers explicitly instead of relying on star imports.
- Added dashboard bootstrap and wrapper import regression tests so these failures cannot pass unnoticed again.

### Validation
- Local `pytest -q`: PASS, 407 tests.
- Local critical ruff and py_compile: PASS.
- CachyOS source pytest/ruff/py_compile: PASS.
- CachyOS installed wrapper smoke found the stale import bugs above and passed after fixes.
- CachyOS live install, GUI BrowserAct smoke and stress are required before release publication.

## v3.1.1 — 2026-06-16

### Fixed
- Dashboard modular assets now use versioned cache-busting query strings and `Cache-Control: no-store` for `/gui/assets/*`, preventing stale cached JS/HTML fragments after upgrading from earlier modular builds.

### Validation
- BrowserAct live dashboard smoke on CachyOS: `/gui` booted, Overview rendered real data, Memory tab switch worked, `/gui/assets/*` served correctly.
- Local/CachyOS `pytest -q`: PASS, 404 tests.
- Local/CachyOS critical ruff and py_compile: PASS.

## v3.1.0 — 2026-06-16

### Milestone
- Full modularity stabilization release after `v3.0.0`.
- Moves secondary monoliths out of `scripts/`, `bin/`, dashboard, CDP, inventory and helper tooling into focused `arena/*` packages.
- Runtime composition now uses an isolated runtime namespace; `unified_bridge.py` only exports compatibility names at the boundary.

### Changed
- Split `bin/agentctl` into `arena/agentctl_cli/*`.
- Split `scripts/inventory.py` into `arena/inventory/*`.
- Moved low-level CDP client/runtime from `scripts/cdp_browser.py` into `arena/browser/cdp_client/*`.
- Split helper CLIs into modular packages: `arena/skills/cli*.py`, `arena/memory/cli*.py`, `arena/memory/recall_*.py`, `arena/desktop/cli/*`, `arena/agent_helpers/*`, `arena/project_cli/*`, `arena/missions_cli/*`, `arena/mcp_marketplace/*`.
- Split dashboard assets into modular HTML/CSS/JS files under `dashboard/assets/`; `/gui/assets/{path}` serves them.
- Renamed internal wiring modules from `legacy_*` names to domain-oriented runtime/composition names.
- Replaced hidden `globals().update(g)` wiring with explicit `RuntimeEnv` access.
- Separated `arena/runtime_deps/*` from boundary-only `arena/compat_surface/*`.

### Guardrails
- Added `AGENTS.md` and `docs/AI_CODEBASE_NAVIGATION.md` for future AI maintainers.
- Added project-wide modularity tests: product files must stay under 200 lines, wrappers must stay thin, wiring cannot reintroduce hidden globals mutation, and `unified_bridge.py` must use an isolated runtime namespace.

### Validation
- Local `python -m py_compile scripts/*.py bin/*.py arena/**/*.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.
- Local `pytest -q`: PASS, 404 tests.
- CachyOS source `pytest -q`: PASS, 404 tests.
- CachyOS source ruff/py_compile: PASS.

## v3.0.0 — 2026-06-16

### Milestone
- Stable modular Arena Unified Bridge v3 release.
- `master` is promoted to the modular v3 code line; `v2.12.0` remains available as the old monolith tag/release.
- `unified_bridge.py` remains a 98-line compatibility/CLI entrypoint; implementation lives in focused `arena/*` modules.

### Added
- `docs/MOBILE_SUPPORT_ROADMAP.md` for post-v3.0 Android/mobile planning.

### Fixed
- Windows installer stale SCM/NSSM service cleanup when Scheduled Task mode is active.
- Linux installer local-source install path and v3 branch defaulting.
- Windows ZIP skill installation handle locking around temporary ZIP files.
- Cross-platform test portability issues found during Windows RC validation.

### Validation
- Linux/CachyOS fresh install from `v3.0.0-rc.1` release ZIP: PASS.
- Linux/CachyOS source `pytest -q`: PASS, 400 tests.
- Linux/CachyOS endpoint smoke: PASS, including KDE/Wayland desktop windows, active window and screenshot.
- Linux/CachyOS stress v4 with restart: PASS=18.
- Windows fresh install from `v3.0.0-rc.1` release ZIP: PASS.
- Windows source `pytest -q`: PASS, 400 tests.
- Windows endpoint smoke: PASS.
- Windows stress v4 with restart: PASS=15 SKIP=3 (`pending-win32` desktop backend skips expected).

## v3.0.0-rc.1 — 2026-06-16

### Milestone
- Release candidate for the stable modular `v3.0.0` line.
- v3 remains API-compatible with the v2 bridge surface while replacing the old monolith with focused modules.

### Changed
- Version metadata updated from `3.0.0-beta.2` to `3.0.0-rc.1`.
- README now describes the RC stabilization state and the current 98-line `unified_bridge.py` compatibility entrypoint.
- Added a mobile/Android support roadmap for post-`v3.0.0` planning without making mobile work a stable-release blocker.

### Fixed
- Windows ZIP skill installation no longer trips over `NamedTemporaryFile` handle locking.
- Windows test coverage now uses shell-portable Python commands instead of POSIX-only quoting/tools.
- Memory tests now force garbage collection before temporary directory cleanup to avoid lingering SQLite handles on Windows.

### Validation target
- Local `pytest -q` must pass before tagging.
- Fresh release-zip install checks are required on CachyOS/Linux and Windows before promoting this RC to stable.
- Expected stress gates: CachyOS `PASS=18`; Windows `PASS=15 SKIP=3` with `pending-win32` desktop skips documented.

## v3.0.0-beta.2 — 2026-06-16

### Fixed
- Windows installer removes stale `ArenaUnifiedBridge` SCM/NSSM services when falling back to Scheduled Task mode.
- Windows uninstaller removes stale SCM service entries even when NSSM is not installed.
- Windows installer Funnel summary now falls back to checking the public `/health` endpoint when `tailscale funnel status` output is unavailable to the installer context.

### Validation
- Windows 10 fresh install/reinstall smoke: PASS.
- Windows 10 stress v4 with restart: PASS=15 SKIP=3 (`pending-win32` desktop backend skips are expected).
- Linux/CachyOS fresh install from beta zip: PASS.
- Linux/CachyOS stress v4 with restart: PASS=18.

## v3.0.0-beta.1 — 2026-06-16

### Milestone
- First beta of the modular v3 bridge line.
- Linux/CachyOS and Windows 10 validation both pass on the modular architecture.

### Fixed
- Windows installer no longer prints the broken `Bridge is healthyHEALTH_VERSION` message.
- Windows installer no longer fails on repeated installs with a missing `cloudflared_done` label.
- Linux/macOS installer now defaults to the v3 modular branch and supports local-source installs, avoiding accidental v2.12 installs from `master` during v3 testing.
- Linux/macOS uninstaller now stops Cloudflared quick tunnel processes and removes bundled `cloudflared` binaries when present.

### Improved
- Windows and Linux installers now report/verify optional component status more clearly: cloudflared, SuperPowers, BrowserAct, Camoufox and Tailscale Funnel.
- Added architecture boundary tests and unified bridge compatibility surface tests.
- Added `docs/MODULE_MAP.md`, `docs/V3_RELEASE_CHECKLIST.md`, and `docs/V3_STABILIZATION_AUDIT.md`.

### Validation
- Local `pytest -q`: PASS, 400 tests.
- Live CachyOS/KDE `pytest -q`: PASS, 400 tests.
- Live CachyOS/KDE stress v4 with restart: PASS=18.
- Windows 10 stress v4 with restart: PASS=15 SKIP=3 (desktop backend intentionally pending-win32).

## v3.0.0-alpha.1 — 2026-06-16

### Milestone
- First modular Arena Unified Bridge release.
- `unified_bridge.py` reduced from the old monolithic implementation to a thin compatibility/CLI entrypoint (~165 lines).
- Public REST, MCP, WebSocket, dashboard, gateway and installer behavior remain compatibility-preserving.

### Changed
- Split the bridge into focused `arena/*` domain packages: app factory, route registry, contexts, wiring, browser/CDP, desktop, service, system, memory, skills, tasks, observability, admin, MCP, TLS, sandbox and cluster modules.
- Added `arena/legacy_imports/*` and `arena/wiring/legacy_*` compatibility layers so existing `import unified_bridge as ub` integrations continue to work during the v3 transition.
- Updated README project layout and contribution guidance for the modular architecture.

### Validation
- Full local and live `pytest -q` pass.
- Live CachyOS/KDE `dev/stress-test-v4.py --restart` pass with `Summary: PASS=18`.

## v2.12.0 — 2026-06-10

### Milestone
- Stable monolith baseline before the planned v3 modularization work.
- Windows and CachyOS/KDE have both passed the capability-aware v4 stress suite, including restart lifecycle checks.

### Changed
- `dev/stress-test-v4.py` is now non-persistent by default: it lists tasks but does not submit queue tasks unless `--task-roundtrip` is explicitly requested.
- Task roundtrip now uses `echo stress-test-v4 noop`, which is valid on Windows cmd and POSIX shells.

### Added
- Added `docs/STRESS_TEST_V4.md` with local/remote, restart, and task-roundtrip usage.

## v2.11.6 — 2026-06-10

### Fixed
- Linux `/v1/restart` now prefers a transient `systemd-run --user` unit, so the restart helper survives `arena-bridge.service` cgroup cleanup and can reliably restart the bridge.

### Notes
- The previous detached shell helper remains as fallback for non-systemd Linux environments.

## v2.11.5 — 2026-06-10

### Fixed
- `install.sh` no longer references an unset `$PYTHON` variable before Python discovery while reading the bridge version; it now uses a local `VERSION_PY` probe.

### Improved
- `install.sh` re-executes itself under `bash` when invoked as `sh install.sh`, matching the script's intended shell and avoiding shell-mismatch failures.

## v2.11.4 — 2026-06-10

### Fixed
- Windows `/v1/restart` now uses the SCM/NSSM restart path only when the Windows service is actually running. Stale stopped services no longer block Scheduled Task relaunch.
- The Windows Scheduled Task restart helper now force-kills the previous bridge PID before relaunching the task, preventing orphaned `python.exe` bridge processes.

### Added
- Added `dev/stress-test-v4.py`, a capability-aware cross-platform smoke/stress test runner for REST/core/hardware/service/skills/tasks/CDP/desktop/restart checks.

## v2.11.3 — 2026-06-10

### Added
- Added `/v1/capabilities`, a stable agent-facing map of available OS/service/browser/desktop/hardware capabilities and selected backends.

### Improved
- Windows installer version detection now uses `_arena_helper.py` / `arena/constants.py`, fixing `Bridge vunknown` after the version constant moved out of `unified_bridge.py`.
- Windows install health verification now prints the actual `/health.version`.
- Windows CIM/PowerShell inventory probes force UTF-8 output and normalize common CIM date formats.
- Windows service/status endpoints distinguish stale stopped services from active Scheduled Tasks and include command lines for bridge-related Python processes.

### Tests
- Added regression coverage for installer helper version detection and `/v1/capabilities` route registration.

## v2.11.2 — 2026-06-10

### Fixed
- `/v1/skills/uninstall` now accepts safe third-party skill basenames beginning with `_`, so it can remove every safe `third_party/<name>` entry that `/v1/skills` can list while still rejecting traversal and core/category skills.

### Tests
- Added regression coverage for underscore-prefixed third-party skill names.

## v2.11.1 — 2026-06-10

### Improved
- `/v1/hardware` now exposes additional read-only device context: physical/block storage devices, PCI/PNP devices, USB devices, and thermal/sensor facts where available.
- KDE Plasma Wayland window discovery no longer depends on `QFile` inside KWin scripting. The script now prints tokenized JSON to the user journal, which the bridge reads back, and still falls back to `wmctrl`/`xdotool`.

### Fixed
- `/v1/skills/uninstall` now accepts the same third-party names returned by `/v1/skills` (`third_party/<name>`) as well as bare third-party names, while rejecting core/category skills and path traversal.

### Removed
- Removed the broken test-only `skills/third_party/weather` skill from the production tree.

### Tests
- Added regression coverage for hardware device sections and third-party skill-name normalization.

## v2.11.0 — 2026-06-10

### Added
- Added `/v1/hardware` as the canonical rich hardware/system inventory endpoint. It is backed by `scripts/inventory.py`, returns normalized JSON for agents and GUI consumers, and keeps `/v1/hwinfo` as a backward-compatible alias.
- Added short `/v1/cdp/*` aliases for the existing `/v1/browser/cdp/*` endpoints to reduce agent/tool 404s when shorter CDP paths are inferred from docs.

### Improved
- Unified the old split hardware collectors: motherboard/BIOS, CPU, memory modules, GPU/NVIDIA telemetry, disks, network, displays, runtimes, package managers, and browsers now come from one inventory source.
- `/v1/desktop/windows` now tries native KDE/KWin scripting on Plasma Wayland before falling back to `wmctrl` and `xdotool`, improving Wayland window discovery without requiring `kdotool`.
- `/v1/browser/cdp/session/check` now returns HTTP 200 with `connected: false` and actionable details when CDP is disconnected, instead of treating the normal disconnected state as a malformed request.
- Runtime version probing is quieter for tools such as `lua` and partial `dotnet` installs.

### Fixed
- Fixed Windows CIM inventory collection: `_get_cim_json()` no longer calls `_run(..., shell=True)` on a helper that did not support `shell`, which previously caused Windows hardware sections to silently return empty data.
- Fixed Windows display inventory (`screens` was referenced before assignment) and expanded Windows logical disk/GPU/RAM CIM property selection.

### Tests
- Added regression coverage for the inventory runner, noisy version filtering, and hardware normalization/NVIDIA merge path.

## v2.10.3 — 2026-06-08

### Security
- Hardened `arena/security.py::_validate_url` against SSRF bypasses in browser fetch endpoints (`/v1/browser/read`, `/dump`, `/fetch`, `/head`).
- Blocked obfuscated internal hosts including `127.1`, octal IPv4 (`0177.0.0.1`), decimal integer IPv4 (`2130706433`), hex IPv4 (`0x7f000001`), IPv4-mapped IPv6 loopback, and `localhost.localdomain`.
- Blocked metadata/internal hostnames such as `metadata.google.internal`, bare `metadata`, `.internal`, and `.local` names.
- Added DNS resolution defense-in-depth: every A/AAAA result is checked for private, loopback, link-local, reserved, multicast, or unspecified addresses before fetch.

### Tests
- Added regression tests for the reported SSRF bypass payloads.

## v2.10.2 — 2026-06-08

First release built with CI, an expanded test suite, and safe-by-construction
release packaging. No runtime feature changes — focused on correctness,
security of the release process, and developer experience.

### Fixed
- `scripts/mcp_stream_server.py`: added missing `import shutil` — the browser
  screenshot tool called `shutil.which()` without importing it, which would
  raise `NameError` when invoked (found by the new lint pass).
- `unified_bridge.py`: import `Dict`/`Optional` from `typing` (referenced in
  annotations but never imported) and removed a redundant local `urlparse`
  import.

### Security
- **Release packaging is now safe by construction.** `scripts/pack_release.py`
  previously could include `token.txt`, `users.json`, `audit.jsonl`,
  `requests.jsonl`, and root-level `bridge.log` in the public release archive.
  It now ships only git-tracked files (sensitive files are git-ignored) plus an
  explicit `cloudflared` bundle and runtime-dir placeholders, and asserts the
  archive contains no sensitive names before finishing.

### Tests / CI
- Added GitHub Actions CI: pytest on Python 3.10–3.13 plus a ruff lint pass
  (critical correctness rules enforced as blocking; full rule set informational).
- Added `tests/test_security.py` (60 tests) covering the safety-critical
  surface: command blocklist, desktop-input-injection guard, SSRF validation,
  audit redaction, token generation, and Bearer auth.

### Developer experience / repository hygiene
- Removed the bundled ~39 MB `cloudflared` binary from version control; the
  installers now fetch the platform-correct binary on demand.
- Added `requirements.txt` and `pyproject.toml` (explicit dependencies, ruff &
  pytest configuration); installers install dependencies from `requirements.txt`.
- Added `.editorconfig` and `CONTRIBUTING.md`.
- Moved `AI_PROMPT_TEMPLATE.md` to `docs/` and `stress-test-v3.sh` to `dev/`;
  corrected the README structure section to match the real layout.

## v2.10.1 — 2026-06-08

### Installer transparency / anti-false-positive
- `install.bat` and `install.sh` now show a prominent background-service transparency notice before registering/updating any background service, scheduled task, systemd unit, or launchd agent.
- Installers now require explicit confirmation before service registration. Use `ARENA_ACCEPT_BACKGROUND=1` or `ARENA_ASSUME_YES=1` for unattended automation.
- README documents expected background processes and legacy helper names (`local_bridge.py`, `mcp_ws_server.py`, `web_gateway.py`, `agentctl task-watch`), plus PowerShell/Linux/macOS inspection and cleanup commands.
- Runtime bridge version bumped to `2.10.1` so `/health` and `/v1/version` identify this release.

## v2.10.0 — 2026-06-08

### Fixed
- Closed the control-lease bypass where `/v1/exec` could still inject desktop input while control was paused/revoked by blocking input-injection tools (`ydotool`, `xdotool` key/mouse/type, `wtype`, `dotool`, etc.) under a paused/revoked lease while keeping non-input shell diagnostics available.
- Made `/v1/desktop/screenshot` honor `format`, `scale`, `max_width`, and `quality` parameters. The endpoint can now return JPEG/WebP/downscaled images instead of always returning full-size PNG.
- Hardened `/v1/exec` safety patterns against obvious secret reads and reverse-shell payloads (`~/.ssh/id_*`, `.netrc`, `.git-credentials`, `.aws/credentials`, `token.txt`, `/etc/shadow`, `/dev/tcp`, `nc -e`, etc.).
- Made `/v1/desktop/type` more reliable on KDE/Wayland with `ensure_latin` (default `true`), switching the keyboard layout to the first/Latin layout before typing to avoid RU/other-layout keycode corruption.
- Added `/openapi.json` as an OpenAPI alias to improve API discoverability, and documented the new desktop screenshot/type parameters.

### Documentation / transparency
- Added a prominent README section explaining expected background processes, Windows scheduled tasks/services, legacy helper names, and manual cleanup commands so the project is not mistaken for malware.
- `install.bat` and `install.sh` now show an explicit background-service transparency notice and require confirmation before installing/updating the service. Set `ARENA_ACCEPT_BACKGROUND=1` or `ARENA_ASSUME_YES=1` for unattended automation.

### Notes
- `owner-shell` remains a trusted/local-owner profile; these safety patterns reduce common foot-guns but are not a substitute for a sandbox or least-privilege deployment.
- For vision agents, recommended screenshot parameters are now `format=jpeg&scale=0.5&quality=80` or `format=jpeg&max_width=1280&quality=80`.
