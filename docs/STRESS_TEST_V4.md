# Stress Test v4

`dev/stress-test-v4.py` is the capability-aware smoke/stress runner for Arena Unified Bridge.

It is designed to be safe across Windows, Linux, macOS, desktop, and headless machines:

- calls `/v1/capabilities`;
- treats unsupported backends as `SKIP`, not `FAIL`;
- keeps the default run non-persistent;
- only runs disruptive checks when explicitly requested.

## Basic non-mutating smoke

```bash
python dev/stress-test-v4.py \
  --url http://127.0.0.1:8765 \
  --token "$ARENA_TOKEN" \
  --timeout 45
```

Remote/Tailscale:

```bash
python dev/stress-test-v4.py \
  --url https://YOUR-MACHINE.tailnet.ts.net \
  --token "$ARENA_TOKEN" \
  --timeout 45
```

## Restart test

This is disruptive: it calls `POST /v1/restart` and waits for `/health` to return with a lower uptime.

```bash
python dev/stress-test-v4.py \
  --url https://YOUR-MACHINE.tailnet.ts.net \
  --token "$ARENA_TOKEN" \
  --timeout 45 \
  --restart
```

## Task roundtrip

This is mutating: it submits a tiny `echo stress-test-v4 noop` task and then lists tasks.

```bash
python dev/stress-test-v4.py \
  --url http://127.0.0.1:8765 \
  --token "$ARENA_TOKEN" \
  --task-roundtrip
```

## Expected platform behavior

### Windows core without desktop backend

Expected:

```text
PASS core/service/hardware/skills/CDP/capabilities
SKIP /v1/desktop/windows pending-win32
SKIP /v1/desktop/active_window pending-win32
SKIP /v1/desktop/screenshot pending-win32
```

### KDE Plasma Wayland

Expected:

```text
PASS /v1/desktop/windows        backend kwin_journal
PASS /v1/desktop/active_window
PASS /v1/desktop/screenshot     backend spectacle/grim
```

## Exit status

- `0`: no `FAIL` checks;
- `1`: at least one `FAIL` check.

`SKIP` is normal when `/v1/capabilities` says a backend is unavailable.
