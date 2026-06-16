# AI Codebase Navigation Map

This document exists so future AI coding agents do not get lost in the v3.1
modular tree. Prefer editing the focused module that owns the feature instead of
adding compatibility glue or large new files.

## Entry points are wrappers

| Entry point | Real implementation |
|---|---|
| `unified_bridge.py` | `arena/cli.py`, `arena/app.py`, `arena/wiring/*` |
| `bin/agentctl` | `arena/agentctl_cli/*` |
| `scripts/inventory.py` | `arena/inventory/*` |
| `scripts/cdp_browser.py` | `arena/browser/cdp_client/*` |
| `scripts/skill_runner.py` | `arena/skills/cli*.py` |
| `scripts/mcp_stream_server.py` | `arena/mcp/standalone_*.py` |
| `scripts/mcp_ws_server.py` | `arena/mcp/ws_*.py` |
| `scripts/memory.py` | `arena/memory/cli*.py` |
| `bin/memory_recall.py` | `arena/memory/recall_*.py` |
| `scripts/desktop_manager.py` | `arena/desktop/cli/*` |
| `scripts/hwinfo.py` | `arena/system/hwinfo_*.py` |
| `scripts/agent_helpers.py` | `arena/agent_helpers/*` |
| `scripts/project_git.py` | `arena/project_cli/*` |
| `scripts/mission_manager.py` | `arena/missions_cli/*` |
| `bin/mcp_marketplace.py` | `arena/mcp_marketplace/*` |

## Runtime ownership

| Area | Modules |
|---|---|
| App creation | `arena/app.py`, `arena/lifecycle.py` |
| Routes | `arena/routes.py`, `arena/route_registry/*` |
| Context dataclasses | `arena/contexts/*` |
| Auth/users/tokens | `arena/auth/*`, `arena/admin/token.py` |
| Exec/safety | `arena/exec/*`, `arena/security_*.py` |
| Desktop | `arena/desktop/*` |
| Browser fetch/read | `arena/browser/fetch*.py`, `arena/browser/browse*.py` |
| CDP REST handlers | `arena/browser/cdp/*` |
| CDP low-level client | `arena/browser/cdp_client/*` |
| Hardware/inventory | `arena/inventory/*`, `arena/system/hwinfo_*.py` |
| Memory/recall | `arena/memory/*` |
| Tasks | `arena/tasks/*` |
| Skills | `arena/skills/*` |
| MCP | `arena/mcp/*` |
| GUI/dashboard | `arena/gui/*`, `dashboard/assets/*` |
| Observability | `arena/observability/*`, `arena/watchdog/*` |
| Service/restart/capabilities | `arena/service/*` |

## Dashboard layout

The dashboard is intentionally split:

- `/gui` serves `dashboard/index.html`.
- `/gui/assets/{path}` serves modular assets from `dashboard/assets/`.
- `body-*.html` files are tab/body fragments.
- numbered `*.js` files are loaded in order by the bootstrap in `dashboard/index.html`.

Do not rebuild a giant inline `dashboard/index.html`.

## Compatibility layer status

`arena/wiring/legacy_*` and `arena/legacy_imports/*` are transitional. They keep
old imports and route wiring stable while the modular runtime is being completed.
New features should not be added there unless the change is purely an adapter
for an already-modular implementation.

## Modularity guardrails

`tests/test_architecture_boundaries.py` and `tests/test_project_modularity.py`
protect against regressions:

- `unified_bridge.py` must stay thin.
- `arena/*` must not import `unified_bridge.py`.
- product files must stay below the 200-line line-count limit, excluding deployment
  installers that are validated by fresh install tests.
- wrapper entrypoints must stay thin.

If a file approaches the limit, split it by responsibility instead of increasing
the limit.
