# Arena Unified Bridge — Roadmap to Dynamic Harness

Date: 2026-07-29

## North-star alignment

Arena Unified Bridge is the onboard computer / flight computer for AI agents. The goal is not to accumulate tools, releases, or green CI. The goal is that the human observer sees the AI act on a real machine safely, coherently, and autonomously.

Code Workbench is not an IDE for its own sake. It is one subsystem of a self-extending harness: the agent should be able to discover a missing capability, install or author the needed runtime/tool, test it, promote it into a reusable tool/MCP/scenario, and keep the observer informed about what works, what failed, and why.

## Completed foundation as of v4.117.x

- `code.run`: multi-file workspaces, argv, stdin, artifacts, run_id.
- Windows AppContainer fenced Python execution.
- `runtime.probe`, `runtime.install` with managed Go.
- `code_project.*`: persistent projects, project-level dependency cache.
- `code_matrix.run`: up to 8 Code Workbench runs in one call.
- `code_run.info`, `code_artifact.read`, REST artifact downloads.
- `deps.python`, `deps.npm`, `deps.go` scratch-local dependency modes.
- `code_session.*`: Python long-running host/off session MVP, project cwd + project deps support.
- MCP external call timeout containment.
- BrowserAct/CDP structured diagnostics.

Known limits:

- Node in Windows AppContainer is blocked by Node probing `C:\` and receiving `EPERM`.
- Go in Windows AppContainer is blocked by Go opening the Windows `NUL` device during compilation.
- Rust compiler can be installed, but Windows linker/toolchain is incomplete without MSVC/MinGW/w64devkit.
- BrowserAct auth/list works, but BrowserAct local CDP proxy does not expose `/json/version` for the remote stealth browser.
- CDP/headless Edge from Windows service can fail due to session/desktop/elevation isolation.

## Phase 1 — Visibility / Map

### v4.118.0 — Workbench Status ✅ completed

Add `workbench.status` MCP tool.

Should aggregate:

- current autonomy posture and risk;
- runtime probe;
- project list;
- live code sessions;
- recent Code Workbench runs/artifact store;
- known limits;
- recommended next actions.

Purpose: give the pilot/observer a single Workbench panel before adding more power.

### v4.119.0 — Ship Status / Preflight ✅ completed

Add `ship.status` / `ship.preflight`.

Should aggregate:

- bridge version/system;
- posture;
- tunnels/transports;
- MCP servers;
- BrowserAct/CDP;
- ScreenPilot/DesktopCommander;
- Code Workbench;
- mobile/ADB;
- recent failures and suggested repairs.

## Phase 2 — Tool Foundry

### v4.120.0 — Tool Foundry v1 ✅ completed

Add:

- `tool_foundry.create`
- `tool_foundry.test`
- `tool_foundry.publish`
- `tool_foundry.list`
- `tool_foundry.remove`

Agent writes code + manifest + tests. Bridge validates, tests, registers as a callable MCP/custom tool.

### v4.121.0 — Promote Project/Run to Tool ✅ completed

Add:

- `code_project.promote_tool`
- `code_run.promote_tool`

Successful experiments become persistent tools.

## Phase 3 — Better Sandboxes

### v4.122.0 — AppContainer Project Deps ✅ completed

Allow `code_project.run(use_project_deps=true)` in AppContainer by granting only project dependency cache read/execute plus scratch write.

### v4.123.0 — Runtime Compatibility Registry ✅ completed

Add:

- `runtime.compat`
- `runtime.explain`
- `platform.sandbox_capabilities`

Bridge should know and explain runtime/fence combinations.

### v4.124.0 — WASM Runtime ✅ completed

Add managed Wasmtime runtime and `code.run lang=wasm`.

## Phase 4 — Sessions v2

### v4.125.0 — Session Files / Artifacts

Add:

- `code_session.read_file`
- `code_session.write_file`
- `code_session.artifact`
- `code_session.log`

### v4.126.0 — Session Lifecycle Hardening ✅ completed

Add idle timeout, max age, stop-on-HALT, persistent logs, dashboard/status visibility.

### v4.127.0 — AppContainer Sessions Prototype ✅ completed

Long-lived lowbox process with durable handles and lifecycle cleanup.

## Phase 5 — Dependency Locking ✅ completed

### v4.128.0 — Python Lock/Audit

`code_project.deps_lock`, `code_project.deps_audit` for Python.

### v4.129.0 — Node Lock/Audit

`package-lock`, `npm list/audit` integration.

### v4.130.0 — Go Module Audit

`go.sum`, `go list -m all` integration.

## Phase 6 — Runtime Expansion 🚧 in progress

### v4.131.0 — More Managed Runtimes

Add managed install for python312, node, deno, zig, lua, wasmtime.

### v4.132.0 — Rust Toolchain Completion

Finish Rust on Windows with MSVC/MinGW/w64devkit or another linker path, then prove compilation.

## Phase 7 — MCP Authoring

### v4.133.0 — MCP Server Foundry ✅ completed

Add:

- `mcp_server.create`
- `mcp_server.test`
- `mcp_server.install`

Agent writes a full MCP server, bridge tests tools/list and tools/call, then installs it as external MCP.

## Phase 8 — Scenario Promotion

### v4.134.0 — Scenario Promotion ✅ completed

Add:

- `scenario.promote_from_run`
- `scenario.promote_from_history`

Successful behavior becomes reusable scenario.

## Phase 9 — Real machine coverage

### v4.135.0 — Android/POCO Preflight ✅ completed

Add `mobile.preflight`, `mobile.reconnect`, `mobile.observe`.

### v4.136.0 — CachyOS/Linux Flight Check ✅ completed

Install/test bridge on CachyOS:

- systemd-run sandbox;
- Wayland/KDE desktop;
- ADB;
- browser/CDP;
- Tailscale;
- runtime install.

## Immediate next action

v4.118.0 Workbench Status through v4.137.0 Real Machine Smoke Matrix are complete. Continue with post-update smoke automation or the next highest-leverage real-machine hardening slice; keep using the maps before adding power.

## Beyond original roadmap — Flight Records

### v4.137.0 — Real Machine Smoke Matrix ✅ completed

Add `ship.smoke` and `ship.smoke_history` so the bridge can prove the real machine still works after updates and before missions.
