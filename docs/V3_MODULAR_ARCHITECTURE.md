# v3 Modular Architecture Plan

This branch (`v3-modular-core`) keeps the public API compatible while gradually
turning `unified_bridge.py` into a thin entrypoint/router/wiring layer.

## Rules

1. **Do not break public endpoints.** Existing `/v1/*`, MCP, dashboard, and gateway paths remain stable.
2. **Extract one domain at a time.** Every extraction must pass `pytest` and `dev/stress-test-v4.py`.
3. **Prefer pure modules first.** Subprocess/OS-specific logic belongs in runtime modules; HTTP handlers should be thin.
4. **Use explicit context injection for handlers.** Handler modules must not import `unified_bridge.py`.
5. **Keep compatibility shims during migration.** Old internal import paths may re-export from new package paths until v3 stabilizes.

## Current package layout

```text
arena/
  constants.py
  control.py
  security.py
  util.py
  http.py
  capabilities.py
  handler_context.py

  service/
    runtime.py

  inventory/
    runner.py
    hardware.py

  handlers/
    hardware.py
    service.py
```

Compatibility shims currently exist for:

```text
arena/service_runtime.py -> arena.service.runtime
arena/hardware.py        -> arena.inventory.hardware
arena/inventory_runner.py -> arena.inventory.runner
```

## Extraction order

Done:

1. `arena/service/runtime.py` — service/process/restart runtime helpers.
2. `arena/capabilities.py` — capability map builder.
3. `arena/inventory/hardware.py` — `/v1/hardware` normalization.
4. `arena/inventory/runner.py` — `scripts/inventory.py` subprocess runner.
5. `arena/http.py` — CORS JSON response helpers.
6. `arena/handlers/hardware.py` — `/v1/inventory`, `/v1/hardware`, `/v1/hwinfo` handlers.
7. `arena/handlers/service.py` — `/v1/service/info`, `/v1/sys/svc`, `/v1/capabilities`, `/v1/restart` handlers.

Next candidates:

1. `arena/tasks/queue.py` and `arena/handlers/tasks.py`.
2. `arena/skills/*` and `arena/handlers/skills.py`.
3. `arena/desktop/*` and `arena/handlers/desktop.py`.
4. `arena/browser/*` and browser/CDP handlers.
5. `arena/app.py` / `arena/routes.py` after enough handlers are extracted.

## Validation gate

Before pushing meaningful extraction commits:

```bash
pytest -q
python dev/stress-test-v4.py --url https://MACHINE.tail.ts.net --token TOKEN --timeout 45 --restart
```

`SKIP` is acceptable only when `/v1/capabilities` reports a backend unavailable.
`FAIL` blocks the extraction.
