# Arena Unified Bridge v3 Modular Architecture

The v3 line keeps the public bridge API stable while replacing the historical
large `unified_bridge.py` implementation with focused domain packages.

## Current status

- `unified_bridge.py` is a thin compatibility/CLI entrypoint.
- Public routes, handler globals and legacy `import unified_bridge as ub` usage
  remain available through compatibility import/wiring layers.
- New development should happen in `arena/<domain>/...`, not in
  `unified_bridge.py`.

## Top-level flow

```text
unified_bridge.py
  └─ runtime dependency namespace from arena/runtime_deps
  └─ build_runtime_namespace(...) → build_bridge_runtime(...) → compatibility exports
       ├─ bootstrap/logging/executors/path constants
       ├─ auth + runtime wrappers
       ├─ app/lifecycle
       ├─ system/public/admin/service/browser/CDP/desktop/domain wiring
       └─ handler globals for route compatibility

arena/app.py
  └─ creates aiohttp app, installs middleware, registers routes

arena/routes.py
  └─ delegates to arena/route_registry/* route groups
```

## Domain map

```text
arena/
  app.py, routes.py, route_registry/  # app creation and route registration
  contexts/                           # handler dependency dataclasses
  wiring/                             # composition and compatibility wiring
  runtime_deps/                       # unified_bridge runtime dependency namespace

  admin/                              # token regeneration, Tailscale/cloudflared
  api_v2/                             # /v2 compatibility API
  auth/                               # users, auth runtime, auth handlers
  browser/                            # browser fetch/read/browse facade
  browser/cdp/                        # CDP runtime, handlers and diagnostics
  desktop/                            # desktop screenshots/input/windows/focus
  events/                             # WebSocket event stream
  exec/                               # command execution and process tracking
  files/                              # upload/download
  gateway/                            # web gateway and command whitelist
  grpc/                               # gRPC-style secondary interface
  inventory/                          # inventory runner + hardware normalization
  mcp/                                # MCP transports and tool dispatch
  memory/                             # SQLite memory store, recall, handlers
  observability/                      # metrics, audit, logs, alerts, tracing
  profiles/                           # browser session profiles
  resources/                          # missions/reports/hooks/agents/subagents
  sandbox/                            # sandboxed command execution
  service/                            # service info/status/restart/capabilities
  skills/                             # skill registry/cache/install/run
  system/                             # version/status/sysinfo/doctor/sound/hwinfo
  tasks/                              # task queue and async task runner
  tls/                                # TLS/Tailscale certificate helpers
  watchdog/                           # memory/CPU watchdog and restart safety
```

## Rules for future agents

1. Do not add new business logic to `unified_bridge.py`.
2. Preserve public endpoints and handler names unless a migration document says otherwise.
3. Put route registration in `arena/route_registry/*`.
4. Put handler dependency dataclasses in `arena/contexts/*` and re-export via
   `arena/handler_context.py` if legacy import compatibility is needed.
5. Keep handlers thin; put OS/subprocess/state logic in runtime/helper modules.
6. Avoid new mini-monoliths: split files by natural boundaries. The enforced
   limit lives in `tests/test_project_modularity.py` (currently 300 lines);
   decompose growing modules instead of compressing logic to fit it.
7. For meaningful changes, run:

```bash
pytest -q
python dev/stress-test-v4.py --url <bridge-url> --token <token> --timeout 45 --restart
```

## Compatibility layers

`arena/runtime_deps/*` and `arena/wiring/*` are transitional. They keep
legacy imports and globals stable while the rest of the project uses focused
modules. They should be simplified over time, but they should not accumulate new
domain logic.
