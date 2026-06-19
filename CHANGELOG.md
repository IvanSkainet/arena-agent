# Changelog

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
