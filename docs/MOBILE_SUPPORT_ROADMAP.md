# Mobile Support Roadmap (Post-v3.0.0)

This document captures the planned Android/mobile direction for Arena Unified
Bridge after the stable `v3.0.0` modular desktop release. Mobile support is a
future expansion track and is **not** a blocker for the v3.0.0 stable release.

## Goals

- Let AI agents inspect and operate mobile devices with the same predictable
  REST/MCP style used for desktop automation.
- Keep mobile code modular from day one: no new monoliths and no platform logic
  buried in `unified_bridge.py`.
- Start with safe, owner-controlled local workflows before considering public or
  unattended mobile-control scenarios.
- Prefer explicit capability reporting so agents know what is available on a
  given host/device.

## Non-goals for v3.0.0 stable

- No Android automation endpoints are required for `v3.0.0`.
- No native Android application is required for `v3.0.0`.
- No iOS support is planned until Android/ADB support is stable and the security
  model is revisited.

## Phase 1: Android via ADB companion layer

The first mobile milestone should use Android Debug Bridge (ADB) from the
existing desktop bridge host. This is the lowest-friction path because it works
with a connected phone/tablet or a local emulator and does not require building a
native app first.

Proposed package layout:

```text
arena/mobile/
├── __init__.py
├── adb.py              # adb discovery, command runner, device listing
├── capabilities.py     # per-device feature/capability model
├── handlers.py         # REST handlers
├── schemas.py          # request/response normalization helpers
└── safety.py           # mobile-specific guardrails
```

Proposed route registry:

```text
arena/route_registry/mobile.py
```

Candidate REST endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/v1/mobile/devices` | List connected ADB devices/emulators and capability summaries |
| `GET` | `/v1/mobile/{id}/info` | Device model, Android version, screen size, battery, input support |
| `GET` | `/v1/mobile/{id}/screenshot` | Capture screenshot as PNG/JPEG/base64 |
| `POST` | `/v1/mobile/{id}/tap` | Tap coordinates |
| `POST` | `/v1/mobile/{id}/swipe` | Swipe/drag gesture |
| `POST` | `/v1/mobile/{id}/type` | Type text through ADB input methods |
| `POST` | `/v1/mobile/{id}/key` | Send Android key event (`HOME`, `BACK`, `ENTER`, etc.) |
| `POST` | `/v1/mobile/{id}/shell` | Restricted diagnostic shell commands |
| `GET` | `/v1/mobile/{id}/packages` | List installed packages (optional/authenticated) |

MCP tools can mirror these endpoints later, for example:

```text
mobile.devices
mobile.screenshot
mobile.tap
mobile.swipe
mobile.type
mobile.key
mobile.shell
```

## Phase 1 safety requirements

- Mobile endpoints must require Bearer auth; no public unauthenticated mobile
  control endpoints.
- ADB shell must have its own allowlist/denylist and must not reuse broad desktop
  `/v1/exec` behavior blindly.
- Input actions should be blocked when the existing control lease is paused or
  revoked.
- Screenshots should support downscaling/quality parameters like desktop
  screenshots to keep vision-agent payloads small.
- `/v1/capabilities` should expose mobile availability explicitly, e.g.:

```json
{
  "mobile": {
    "available": true,
    "backend": "adb",
    "devices": 1,
    "endpoints": ["devices", "screenshot", "tap", "type", "key"]
  }
}
```

## Phase 2: Termux bridge mode

After ADB support is reliable, add an optional Termux-hosted bridge mode for
Android devices that should expose local diagnostics or controlled automation
without a USB connection.

Possible scope:

- Termux installer script.
- Local Android `/health` and `/v1/mobile/self/*` endpoints.
- Tailscale-on-Android guidance for private remote access.
- Reduced command set by default because Android permissions and background
  limits are different from desktop Linux.

## Phase 3: Native Android companion app

A native app can provide a better long-term UX than raw ADB/Termux:

- Explicit user consent screen.
- Accessibility-service integration for UI automation, if the user enables it.
- MediaProjection screenshot/capture flow with Android permission prompts.
- Foreground service notification so the bridge is transparent and removable.
- Pairing/token flow with the desktop bridge.

This phase should happen only after the v3 desktop architecture is stable and
ADB support has clarified the API shape.

## Test strategy

- Unit tests for ADB output parsing and capability normalization.
- Emulator smoke tests for device listing, screenshot, tap/key/type.
- Real-device manual validation before beta release.
- Stress suite extension with capability-aware mobile skips when no device is
  connected.

## Release placement

Recommended version path:

```text
v3.0.0       stable modular desktop bridge
v3.1.0-alpha Android/ADB experimental endpoints
v3.1.0-beta  ADB validation on emulator + one real device
v3.1.0       stable ADB companion support
v3.2.x+      Termux/native companion experiments
```
