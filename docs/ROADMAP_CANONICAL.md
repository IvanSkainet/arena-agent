# Arena Unified Bridge — Canonical Roadmap

Date: 2026-06-21
Validated baseline: `v3.11.0`

This file is the planning source of truth.

---

## 1. Current validated state

- Version: `3.11.0`
- Tests: `612 passed`
- MCP tools: `46`
- Route objects in aiohttp app: `311`
- Distinct method/path routes excluding auto-HEAD: `207`

### Completed enough to count as done
- `fs.*` toolkit core: read/write/list/edit/view/create/search/grep/tree/diff
- MCP git tools: `git.status`, `git.diff`, `git.log`, `git.commit`
- memory export/import
- memory profiles (`M3`) across REST, MCP, runtime, and dashboard
- integration recipes (`DX2`) for Arena Agent Mode, Claude-style chats, Cursor, Cline, Windsurf, Open Interpreter, and local model stacks
- built-in planner (`A1`) via `POST /v1/plan` and MCP `plan.create`
- file watchers (`F5`) via `GET/POST/DELETE /v1/watch/files` and MCP `watch.files`
- safe editor foundation (`F4`) via preview/apply/rollback flow for REST and MCP file edits
- bounded ReAct + reflection foundation (`A2` / `A3`) via `/v1/react`, `/v1/reflect`, `react.run`, and `reflect.run`
- workspace dashboard surface v1 for profile context, planner, ReAct/reflection, and watcher management
- desktop OCR + text-target detection (`D1`) via REST and MCP
- workspace dashboard surface v2 with notes, lessons, and recent activity
- desktop semantic click-by-text + active-window-aware OCR ranking (`D2` slice)
- desktop display/output discovery and display-scoped OCR/text targeting (`D3` slice)
- filtered window catalog + safer focus resolution/dry-run + stronger KWin Wayland focus (`D3` slice)
- window actions for move/resize/minimize/maximize/restore/close/fullscreen (`D3` slice)
- display-aware placement actions like `center` and `move_to_display` (`D3` slice)
- OpenAPI partial coverage
- rate limiting exists
- release packaging and dual zip assets exist
- desktop KDE/Wayland regression fixes through `v3.2.11`
- rate limiter race-condition fix in `v3.2.12`

### Important caveat
Older roadmap files contain stale metrics and stale completion claims. Treat them as idea archives, not product truth.

---

## 2. Product direction

Arena should evolve toward a:

> self-hosted, agentic, companion-like automation workspace built on a strong local bridge core.

This means the priority is not only adding more endpoints. The priority is:
- scoped memory
- planning/reflection
- workspace UX
- trustworthy automation
- clean model/provider abstraction

---

## 3. Recommended next priorities

## P1 — Continue `D3` desktop maturity
What just landed:
- exact/phrase-first OCR ranking
- active-window-aware text targeting
- semantic `click_text` flows on top of OCR
- display/output discovery plus display-scoped screenshot/OCR targeting
- filtered window catalog and safer focus resolution/dry-run
- stronger non-interactive KWin Wayland focus for UUID-style windows
- actual window actions: move/resize/minimize/maximize/restore/close/fullscreen
- display-aware placement actions: `center`, `move_to_display`

What is still next:
- richer multi-monitor policies beyond the current placement helpers
- more semantic desktop actions beyond click-by-text
- stronger workflows that combine windows + OCR + actions as one operation

Definition of done:
- better window management affordances
- improved multi-monitor correctness
- practical OCR-assisted interaction flows that are reliable enough for daily agent use

---

## 4. Secondary priorities

### Workspace UI surfaces v3
The workspace tab now has profile notes, lessons, and activity; the next level is deeper user/profile panes, richer memory browsing, and more cross-linking between agentic runs and persistent context.

### Model/provider abstraction
Important, but should be done cleanly rather than via fragile proxy hacks.

### Additional workspace UI targets
- memory browser
- lessons pane
- user profile pane
- recurring tasks/schedules view

---

## 5. Reclassified items

### Experimental, not core roadmap
- Arena Agent Mode as browser/session-driven model proxy
- any fragile third-party frontend automation used as a hidden model backend

These belong in `docs/EXPERIMENTS.md`, not in the core delivery roadmap.

---

## 6. Cleanup items discovered during roadmap normalization

These are smaller correctness tasks:
- keep CLI/help/docs aligned with removed features
- keep test counts and version references current
- keep one canonical roadmap instead of multiple drifting ones

Status update:
- stale backup CLI/missions references were cleaned up in `v3.2.13`
- integration recipes were added in `v3.3.1`
- built-in planner (`A1`) landed in `v3.4.0`
- file watchers (`F5`) landed in `v3.4.1`
- safe editor foundation (`F4`) landed in `v3.4.2`
- bounded ReAct + reflection foundation (`A2` / `A3`) landed in `v3.5.0`
- workspace dashboard surface v1 landed in `v3.5.2`
- desktop OCR + text-target detection (`D1`) landed in `v3.6.0`
- workspace dashboard surface v2 landed in `v3.6.1`
- semantic click-by-text, stronger OCR ranking, and display-aware desktop targeting landed in `v3.7.0`
- filtered window catalog, safer focus resolution, stronger KWin Wayland focus, and initial window actions landed in `v3.8.0` / `v3.9.0`
- maximize/unmaximize/close and geometry-aware maximize verification landed in `v3.10.0`
- display-aware placement helpers landed in `v3.11.0`

---

## 7. Order of execution I recommend

1. continue `D3` desktop maturity (richer monitor/window semantics + composable desktop workflows)
2. deeper agent loops and mission composition
3. workspace UI surfaces v3 (user/profile panes, richer memory browser)
4. model/provider abstraction improvements

If a low-risk cleanup slot is needed between major tasks, use it for stale-surface cleanup and doc consistency.
