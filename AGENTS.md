# Arena Agent Codebase Guide for AI Maintainers

This repository is intentionally modular. Do not add new runtime logic to thin
compatibility entrypoints or large catch-all files.

## Hard rules

- Keep `unified_bridge.py` a thin compatibility/CLI entrypoint.
- Keep wrapper scripts in `scripts/` and `bin/` thin; real logic belongs under `arena/`.
- Product files must stay under the modularity limit enforced by
  `tests/test_project_modularity.py` (**currently 700 lines**). Runtime modules
  under `arena/` have an additional limit in
  `tests/test_architecture_boundaries.py` (**currently 600 lines**).
  Readable code beats squeezed code — if a file is close to the limit,
  split it by responsibility instead of collapsing whitespace.
- Do not import `unified_bridge.py` from `arena/*` modules.
- Every new module in `arena/admin/` (tunnels/network providers) must be
  cross-platform: `platform.system()` branches, no Linux-only assumptions,
  never invoke `sudo` directly.
- Every user-facing installer path (`install.sh`, `install.bat`) must
  **verify** after installing dependencies — never trust a silent
  `pip install ... 2>/dev/null || true`.
- Never store per-release scratch notes in the repository; use `/tmp/` when
  driving `gh release create --notes-file`.

## Where things live

Core:

- HTTP app and routes: `arena/app.py`, `arena/routes.py`, `arena/route_registry/`
- Request contexts: `arena/contexts/`
- Service lifecycle/status/restart: `arena/service/`
- Runtime composition wiring: `arena/wiring/*`
- Runtime dependency namespace for the facade: `arena/runtime_deps/*`

Domain modules:

- Admin / tunnels / auth: `arena/admin/`
  - `tunnels.py` — unified multi-provider facade
    (`tunnels_status`, `tunnels_active`, `tunnels_start`, `tunnels_stop`)
  - `tailscale.py` — Tailscale Funnel primitives
  - `cloudflared.py` — Cloudflare Quick Tunnel with platform-aware hints
  - `zerotier.py` — cross-platform ZeroTier (HTTP API + CLI fallback)
  - `browseract.py` — cross-platform BrowserAct CLI status
  - `sync_factories.py` — sync-callable factories for handler wiring
  - `handlers.py` — HTTP handlers for `/v1/{sys,tunnels,zerotier,cloudflared,tailscale}/…`
- Capabilities map: `arena/capabilities.py`, `arena/service/capabilities.py`
- Desktop automation: `arena/desktop/`
- Browser / CDP handlers: `arena/browser/cdp/`
- Low-level CDP client: `arena/browser/cdp_client/`
- Inventory / hardware probes: `arena/inventory/`
- Memory and recall: `arena/memory/`
- Skills registry: `arena/skills/`
- MCP transports/tools: `arena/mcp/`
- Dashboard handlers / templates: `arena/gui/`, `dashboard/assets/`
- CLI wrappers / implementations: `bin/*` wrappers and `arena/*_cli/` packages

Skill packages (vendored, cross-platform):

- `skills/superpowers/` — upstream mirror of
  [obra/superpowers](https://github.com/obra/superpowers) (single directory
  serves both Bridge `/v1/skills` and IDE plugin consumers; see
  `docs/SUPERPOWERS.md`)
- `skills/browseract/` — Arena wrapper around `browser-act-cli`
  (cross-platform Python `run.py` + legacy bash shim `run.sh`)

## Validation before pushing meaningful changes

```bash
python -m py_compile scripts/*.py bin/*.py arena/**/*.py
python -m ruff check . --select F821,F811
pytest -q
```

For live bridge changes, also run endpoint smoke and
`dev/stress-test-v4.py --restart`.

For remote-access / provider work, verify the live surface:

```bash
curl -sH "Authorization: Bearer $(cat token.txt)" \
  http://127.0.0.1:8765/v1/tunnels/status | jq
curl -sH "Authorization: Bearer $(cat token.txt)" \
  http://127.0.0.1:8765/v1/capabilities | jq '{network, browser}'
```
