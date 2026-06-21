# Arena Unified Bridge — Canonical Roadmap

Date: 2026-06-19
Validated baseline: `v3.5.2`

This file is the planning source of truth.

---

## 1. Current validated state

- Version: `3.5.2`
- Tests: `588 passed`
- MCP tools: `37`
- Route objects in aiohttp app: `296`
- Distinct method/path routes excluding auto-HEAD: `194`

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

## P1 — D1 OCR + element detection
Why:
- now that planner, memory profiles, safe editing, agentic loops, and file watchers exist, OCR/element detection becomes the most natural next leap in practical computer-use capability.
- it opens the path from coordinate-driven desktop automation to semantic desktop automation.

Definition of done:
- text extraction from screenshots
- stable target detection pipeline
- usable coordinate output for click/type workflows

---

## 4. Secondary priorities

### Workspace UI surfaces v2
The first Workspace tab is now present; the next layer is deeper notes/lessons/profile affordances and more live state presentation.

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

---

## 7. Order of execution I recommend

1. `D1` OCR + element detection
2. deeper agent loops and mission composition
3. workspace UI surfaces v2 (notes / lessons / profile panes)
4. model/provider abstraction improvements

If a low-risk cleanup slot is needed between major tasks, use it for stale-surface cleanup and doc consistency.
