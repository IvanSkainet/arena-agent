# Arena Unified Bridge — Canonical Roadmap

Date: 2026-06-19
Validated baseline: `v3.4.1`

This file is the planning source of truth.

---

## 1. Current validated state

- Version: `3.4.1`
- Tests: `579 passed`
- MCP tools: `35`
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

## P1 — Safe editor with preview/confirm/rollback (`F4`)
Why:
- raises trust and reversibility for coding/automation workflows
- complements planner + memory nicely
- reduces fear of autonomous edits

Definition of done:
- preview mode
- confirmation gate
- rollback path for recent edits

---

## 4. Secondary priorities

### A2 / A3 — ReAct loop + Reflection
Critical for higher agent quality, and now easier to build because planner foundations exist.

### UI / Workspace surfaces
- memory browser
- lessons pane
- user profile pane
- recurring tasks/schedules view

### Model/provider abstraction
Important, but should be done cleanly rather than via fragile proxy hacks.

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

---

## 7. Order of execution I recommend

1. `F5` File Watchers
2. `F4` Safe editor with preview/confirm/rollback
3. `A2` / `A3` ReAct + Reflection
4. workspace UI surfaces (memory browser / notes / lessons)

If a low-risk cleanup slot is needed between major tasks, use it for stale-surface cleanup and doc consistency.
