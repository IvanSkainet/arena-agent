# Arena Agent Codebase Guide for AI Maintainers

This repository is intentionally modular. Do not add new runtime logic to thin
compatibility entrypoints or large catch-all files.

## Hard rules

- Keep `unified_bridge.py` a thin compatibility/CLI entrypoint.
- Keep wrapper scripts in `scripts/` and `bin/` thin; real logic belongs under `arena/`.
- Do not create new product files above the 200-line modularity limit enforced by
  `tests/test_project_modularity.py`. If a larger file is truly unavoidable, document why in the PR and prefer a narrow allowlist over raising the global limit.
- Do not import `unified_bridge.py` from `arena/*` modules.
- If a feature grows, split it by responsibility before committing.

## Where things live

- HTTP app and routes: `arena/app.py`, `arena/routes.py`, `arena/route_registry/`
- Request contexts: `arena/contexts/`
- Service lifecycle/status/restart: `arena/service/`
- Desktop automation: `arena/desktop/`
- Browser/CDP API handlers: `arena/browser/cdp/`
- Low-level CDP client: `arena/browser/cdp_client/`
- Inventory/hardware probes: `arena/inventory/`
- Memory and recall: `arena/memory/`
- Skills: `arena/skills/`
- MCP transports/tools: `arena/mcp/`
- Dashboard handlers/templates: `arena/gui/`, `dashboard/assets/`
- CLI wrappers/implementations: `bin/*` wrappers and `arena/*_cli/` packages
- Runtime composition wiring: `arena/wiring/*`
- Runtime dependency namespace for the facade: `arena/runtime_deps/*`

## Validation before pushing meaningful changes

```bash
python -m py_compile scripts/*.py bin/*.py arena/**/*.py
python -m ruff check . --select F821,F811
pytest -q
```

For live bridge changes, also run endpoint smoke and `dev/stress-test-v4.py --restart`.
