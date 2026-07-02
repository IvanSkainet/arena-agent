# Arena v3 Module Map

Use this map when changing the modular bridge. New implementation code should go
into the relevant `arena/<domain>/` package, not into `unified_bridge.py`.

## Entrypoint and composition

| Need to change... | Start here |
|---|---|
| CLI / `serve` / token command | `unified_bridge.py`, `arena/cli.py` |
| aiohttp app construction | `arena/app.py` |
| Route registration | `arena/routes.py`, `arena/route_registry/*` |
| Handler dependency dataclasses | `arena/contexts/*`, re-exported by `arena/handler_context.py` |
| Runtime composition wiring | `arena/wiring/*_registries.py`, `arena/wiring/*_runtime.py`, `arena/wiring/bridge_runtime.py` |
| Runtime dependency namespace / facade surface | `arena/runtime_deps/*`, `arena/compat_surface/*` |

## Core domains

| Domain | Files/directories |
|---|---|
| HTTP/CORS helpers | `arena/http.py` |
| Error middleware | `arena/errors.py` |
| Auth/users | `arena/auth/*` |
| Rate limiting | `arena/rate_limit.py`, `arena/observability/ratelimit_handlers.py` |
| Exec/processes | `arena/exec/runner.py`, `arena/exec/handlers.py` |
| Upload/download | `arena/files/handlers.py` |
| Public index/health/OpenAPI | `arena/public/*` |
| System status/doctor/sound | `arena/system/*` |
| Service status/restart/capabilities | `arena/service/*` |
| Inventory/hardware | `arena/inventory/*`, `arena/system/hwinfo_*` |

## Browser, CDP and desktop

| Need to change... | Start here |
|---|---|
| Browser search/read/fetch/head | `arena/browser/fetch.py`, `arena/browser/fetch_handlers.py` |
| High-level `/v1/browser/browse` | `arena/browser/browse_handlers.py`, `browse_cdp.py`, `browse_browseract.py` |
| CDP status/diag | `arena/browser/cdp/handlers.py` |
| CDP session connect/disconnect | `arena/browser/cdp/session*.py` |
| CDP page actions | `arena/browser/cdp/page*.py` |
| CDP tabs | `arena/browser/cdp/tabs.py` |
| CDP cookies/profiles | `arena/browser/cdp/cookies.py`, `cookie_crud.py`, `cookie_profiles.py`, `cookie_manager.py` |
| CDP network/intercept | `arena/browser/cdp/network.py`, `intercept.py` |
| CDP launch/raw diagnostics | `arena/browser/cdp/raw_info*.py`, `test_launch*.py`, `test_ws*.py` |
| CDP runtime/watcher | `arena/browser/cdp/runtime*.py`, `state.py`, `loader.py` |
| Desktop screenshots | `arena/desktop/screenshot.py`, `screenshot_handler.py` |
| Desktop input | `arena/desktop/input.py`, `input_handlers.py` |
| Desktop windows/active/focus | `arena/desktop/window_handlers.py`, `active_window.py`, `focus.py`, `kwin.py` |
| Control lease | `arena/control.py`, `arena/control_handlers.py` |

## Agent-facing domains

| Domain | Files/directories |
|---|---|
| Memory / recall | `arena/memory/*` |
| Tasks | `arena/tasks/*` |
| Skills | `arena/skills/*` |
| Resources: missions/reports/hooks/agents/subagents | `arena/resources/*` |
| Browser session profiles | `arena/profiles/*` |
| MCP transports and tools | `arena/mcp/*` |
| Web gateway | `arena/gateway/*` |

## Observability and operations

| Domain | Files/directories |
|---|---|
| Metrics | `arena/observability/metrics.py`, `metrics_handler.py`, `prometheus_handler.py` |
| Logs and audit | `arena/observability/audit*.py`, `logs_handler.py`, `request_log.py` |
| Webhooks | `arena/observability/webhooks.py` |
| Alerts/watchdog | `arena/observability/alerts.py`, `arena/watchdog/*` |
| OpenTelemetry-style tracing | `arena/observability/tracing*.py` |
| Admin tunnels/token | `arena/admin/*` |
| TLS | `arena/tls/handlers.py` |
| Sandbox | `arena/sandbox/*` |
| Cluster/HA | `arena/cluster/*` |
| gRPC-style interface | `arena/grpc/*` |

## Development rules

1. Do not add business logic to `unified_bridge.py`.
2. Keep handlers thin; move IO/subprocess/state logic into runtime/helper modules.
3. Keep product files under the modularity limit enforced by
   `tests/test_project_modularity.py` (currently 300 lines). Prefer decomposing
   a growing module along natural boundaries over compressing logic to fit.
4. Preserve public route paths and legacy compatibility names unless a migration doc explicitly changes them.
5. Run `pytest -q` and the v4 stress gate before release-impacting changes.
