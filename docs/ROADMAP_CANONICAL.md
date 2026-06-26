# Arena Unified Bridge — Canonical Roadmap

Date: 2026-06-26
Validated baseline: `v3.27.0`

This file is the planning source of truth.

---

## 1. Current validated state

- Version: `3.27.0`
- Tests: `633 passed`
- MCP tools: `68`
- Route objects in aiohttp app: `346`
- Distinct method/path routes excluding auto-HEAD: `232`

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
- mission composition and inspection v7 via REST + MCP (`mission.templates`, `mission.status`, `mission.report`, `mission.history`, `mission.lineage`, `mission.family`, `mission.catalog`, `mission.compose`, `mission.propose`, `mission.create`, `mission.run`, `mission.rerun`, `mission.recover`, `mission.followup`, `mission.iterate`, `mission.schedules`, `mission.schedule_state`, `mission.schedule_save`, `mission.schedule_delete`, `mission.schedule_tick`)
- workspace dashboard surface v5 with profile context, planner, ReAct/reflection, notes, lessons, recent activity, mission loop studio, schedule controls, and schedule worker state
- browser chat extension phase-4 UX scaffold with popup config, side panel, replayable execution history, stronger ChatGPT-oriented adapters, and insert-and-submit flows
- desktop OCR + text-target detection (`D1`) via REST and MCP
- `D2 / D3` desktop maturity: exact/phrase-first OCR ranking, click-by-text, OCR-to-window resolution, query-driven focus/window actions, display-aware placement, snap/tile placement, non-interactive KDE/Wayland window control, and high-level text workflows
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

## P1 — Continue deeper agent loops and mission composition
Why it stays in front now:
- `D2 / D3` is now complete enough to count as done for the current roadmap slice.
- The bridge now has the first real mission-composition layer, so the next leverage comes from making those missions richer, more stateful, and more agent-driven.

What is already in place for that next work:
- planner + bounded ReAct + reflection foundations
- mission templates / composition / creation / run surfaces
- OCR/text targeting
- query-driven focus/window actions
- display-aware placement and snaps
- workspace UI surfaces and memory profiles

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
- snap/tile-style placement helpers landed in `v3.12.0`
- OCR-to-window resolution, query-driven window targeting, and high-level text workflows landed in `v3.13.0` / `v3.13.1` / `v3.14.0`
- mission composition v1 landed in `v3.15.0`
- mission proposal/orchestration plus mission inspection/status/report surfaces landed in `v3.16.0` / `v3.17.0`
- mission history and mission rerun lifecycle surfaces landed in `v3.18.0`
- mission catalog and mission recovery lifecycle surfaces landed in `v3.19.0`
- mission follow-up and mission iteration loop surfaces landed in `v3.20.0`
- mission lineage plus workspace mission loop studio landed in `v3.21.0`
- mission family summaries and recurring mission schedules landed in `v3.22.0`
- automatic mission schedule worker and schedule-state surfaces landed in `v3.23.0`
- browser chat extension phase-1 backend foundation and MVP scaffold landed in `v3.24.0`
- browser chat extension phase-2 popup/config/adapter UX improvements landed in `v3.25.0`
- browser chat extension phase-3 side-panel/history/adapter insertion improvements landed in `v3.26.0`
- browser chat extension phase-4 replay/debug/insert-and-submit improvements landed in `v3.27.0`

---

## 7. Order of execution I recommend

1. deeper agent loops and mission composition
2. workspace UI surfaces v3 (user/profile panes, richer memory browser)
3. model/provider abstraction improvements
4. future desktop polish only if a concrete gap appears during real-world use

If a low-risk cleanup slot is needed between major tasks, use it for stale-surface cleanup and doc consistency.
