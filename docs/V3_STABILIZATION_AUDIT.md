# v3 Modular Stabilization Audit

Date: 2026-06-16
Branch: `v3-modular-core`
Baseline release candidate: `v3.0.0-rc.1`

## Summary

The v3 modularization is functionally complete:

- `unified_bridge.py` is a thin compatibility/CLI entrypoint (98 lines at RC prep).
- Runtime code lives under focused `arena/*` packages.
- Route registration, handler contexts and compatibility wiring are split into domain modules.
- Public API compatibility is preserved through `arena/legacy_imports/*` and `arena/wiring/legacy_*`.

## Current architecture strengths

- Domain packages own their handlers and runtime helpers.
- `arena/app.py` and `arena/routes.py` isolate app creation and route registration.
- `arena/route_registry/*` groups routes by area: core, CDP, desktop, domain, compatibility.
- `arena/contexts/*` groups handler dependency dataclasses by domain.
- `arena/wiring/*` contains transitional composition code instead of burying wiring inside the entrypoint.
- `arena/legacy_imports/*` keeps old `import unified_bridge as ub` integrations working.

## Transitional modules

These modules are compatibility layers and should be simplified over time, but
must not accumulate new domain logic:

```text
arena/legacy_imports/*
arena/wiring/legacy_*
arena/handler_context.py
unified_bridge.py
```

Rules:

1. Keep them mostly declarative/compositional.
2. Move new behavior into domain packages.
3. Keep each transitional file below the mini-monolith threshold where possible.

## Files above normal threshold

Allowed:

```text
arena/gui/templates.py — HTML dashboard template/data, not runtime control flow.
```

Watch list:

```text
arena/browser/cdp/intercept.py
arena/browser/cdp/cookie_manager.py
arena/tls/handlers.py
arena/exec/handlers.py
arena/browser/cdp/tabs.py
arena/browser/cdp/runtime_watcher.py
arena/mcp/handlers.py
```

These files are currently focused and under ~220 lines. Revisit only if new
features make them grow.

## Release blockers for stable v3.0.0

- Fresh install from the `v3.0.0-rc.1` release ZIP on CachyOS/Linux.
- Fresh install from the `v3.0.0-rc.1` release ZIP on Windows.
- Stress v4 with restart on both platforms after the RC install.
- Fast-forward/merge modular v3 into `master` only after RC validation.
- Optional: add CI matrix for Linux/Windows Python versions if release process allows.

## Non-blocking improvements after v3 stable

- Gradually replace `arena/wiring/legacy_*` with typed composition roots.
- Add route snapshot tests if endpoint churn becomes a risk.
- Improve Windows desktop automation backend coverage.
- Add richer diagnostics to installer failures and service detection errors.

## Validation history

At `v3.0.0-alpha.1`:

- Local `pytest -q`: PASS, 392 tests.
- Live CachyOS/KDE `pytest -q`: PASS, 392 tests.
- Live stress v4 with restart: PASS=18.
- Live `/health`, `/v1/version`, `/v1/status`, `/api-docs`, `/v1/capabilities`, `/gateway/tools`, `/v1/cdp/status` smoke: PASS.


At `v3.0.0-beta.1`/`v3.0.0-beta.2` stabilization:

- Local/live `pytest -q`: PASS, 400 tests.
- CachyOS/KDE stress v4 with restart: PASS=18.
- Windows stress v4 with restart: PASS=15 SKIP=3 (`pending-win32` desktop backend skips expected).
- Windows installer stale SCM/NSSM service cleanup validated with Scheduled Task fallback.
