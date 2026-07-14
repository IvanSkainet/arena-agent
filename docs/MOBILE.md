# Arena Mobile Bridge — REST cheat sheet

The `/v1/mobile/*` domain exposes Android automation over the same
bridge that hosts every other Arena capability. Auth is Bearer-token,
CORS-enabled, and identical to the rest of the surface.

**Prerequisites on the bridge host**
* `adb` on `PATH` (or under `ARENA_ADB_PATH`).
* Optional but recommended: `apksigner` (for /apk/prepare signature
  verify). Bridge works fine without it — signature check just returns
  `available: false`.

**Prerequisites on the phone**
* Developer options + USB debugging enabled.
* First plug: tap "Allow USB debugging" on the phone.
* For wireless: `Wireless debugging` toggle on.

## Env

```bash
export ARENA_BRIDGE_URL="https://your-host.tail328f18.ts.net"
export ARENA_BRIDGE_TOKEN="…"
export CURL='curl -sSf -H "Authorization: Bearer $ARENA_BRIDGE_TOKEN"'
```

## Discovery + info

```bash
# List devices reachable via ADB.
$CURL "$ARENA_BRIDGE_URL/v1/mobile/devices"

# Deep device info: 12 probe sections including sensors summary.
$CURL "$ARENA_BRIDGE_URL/v1/mobile/{serial}/info"

# Live sensor readings (accelerometer XYZ, ambient light lux, etc.).
$CURL "$ARENA_BRIDGE_URL/v1/mobile/{serial}/sensors?events_per_sensor=3"
```

## Screenshots

```bash
# Fast path (raw framebuffer, ~1.3s on POCO F7 Pro).
$CURL -o /tmp/phone.webp \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/screenshot?max_size=720&format=webp&quality=82"

# A/B compare: force the slower PNG-source path.
$CURL -o /tmp/phone-png-path.webp \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/screenshot?max_size=720&format=webp&force_png_source=1"

# Headers reveal the latency breakdown:
#   X-Arena-Mobile-Capture-Ms   time inside `adb exec-out screencap`
#   X-Arena-Mobile-Encode-Ms    time inside Pillow
#   X-Arena-Mobile-Capture-Mode raw | png
#   X-Arena-Mobile-Source-{Width,Height}   native rotated pixels
#   X-Arena-Mobile-Secure-Frame 1 if the phone marked screen FLAG_SECURE
```

## Input primitives

```bash
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"x":720,"y":1500}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/tap"

$CURL -X POST -H "Content-Type: application/json" \
  -d '{"x1":720,"y1":2000,"x2":720,"y2":500,"duration_ms":300}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/swipe"

$CURL -X POST -H "Content-Type: application/json" \
  -d '{"x":720,"y":1500,"vscroll":2}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/scroll"

$CURL -X POST -H "Content-Type: application/json" \
  -d '{"key":"HOME"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/key"

$CURL -X POST -H "Content-Type: application/json" \
  -d '{"keys":["CTRL_LEFT","A"]}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/key_combo"

# ASCII text goes through `input text`. Non-ASCII auto-routes through
# ADBKeyboard when it's the active IME; otherwise returns an error
# with a hint telling you how to install + activate it.
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"text":"hello world"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/type"
```

## Gestures (semantic swipes)

14 named gestures. Coordinates are 0..1 fractions of the current-rotation
screen, translated to native pixels at call time.

```bash
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"gesture":"notifications"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/gesture"
```

Available: `notifications` (top-LEFT for HyperOS/MIUI split shade),
`quick_settings` (top-RIGHT), `shade_center` (stock Android),
`shade_full` (long stock swipe), `close_shade`,
`scroll_up|down|left|right`, `back_edge_left|right`, `home_gesture`,
`recents_gesture`, `screenshot_gesture`.

## UI Automator selectors

```bash
# Dump the current interactive UI tree (filtered from ~500 raw
# nodes down to ~20 actionable ones).
$CURL "$ARENA_BRIDGE_URL/v1/mobile/{serial}/ui"

# Tap by resource-id / text / content-desc / class — survives layout
# reflows that would break pixel-tap paths.
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"id":"com.example:id/login_button"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/tap_by"
```

## Batch executor (v3.84.0)

Run N steps in a single round-trip. Cheaper than N HTTP calls over
Tailscale + auto-audited as one action.

```bash
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"steps":[
    {"type":"key","key":"WAKEUP"},
    {"type":"sleep","duration_ms":200},
    {"type":"key","key":"HOME"},
    {"type":"tap_by","desc":"Поиск"},
    {"type":"sleep","duration_ms":800},
    {"type":"type","text":"weather"},
    {"type":"key","key":"ENTER"}
  ]}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/batch"
```

Step types allowed in batch: `tap`, `swipe`, `scroll`, `key`,
`key_combo`, `type`, `paste`, `gesture`, `shell`, `tap_by`, `sleep`.
Dangerous configuration actions (install, pair, connect) are
intentionally excluded.

Per-step `continue_on_error: true` skips just that step's failure;
top-level `stop_on_error: false` runs every step regardless.

## Helpers (ADBKeyboard for unicode input)

```bash
# 1. Check APK metadata + required consent token (no device needed).
$CURL "$ARENA_BRIDGE_URL/v1/mobile/helpers/status"

# 2. Install (requires the exact consent token from step 1).
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"consent":"yes-install-adbkeyboard-41a8a099"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/helpers/install"

# 3. Activate ADBKeyboard as the current IME.
$CURL -X POST -H "Content-Type: application/json" \
  -d '{}' "$ARENA_BRIDGE_URL/v1/mobile/{serial}/ime/set"

# Now `/type` auto-routes non-ASCII through ADBKeyboard broadcast.
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"text":"привет мир 🌍"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/type"
```

## Wireless ADB

```bash
# 1. On the phone: Settings → Developer options → Wireless debugging
#    → "Pair device with pairing code". Note host, port, and 6-digit code.
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"host":"192.168.1.5","port":38571,"code":"654321"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/pair"

# 2. Use the OTHER port shown under "IP address & Port" (different!).
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"host":"192.168.1.5","port":44121}' \
  "$ARENA_BRIDGE_URL/v1/mobile/connect"

# Disconnect one, or all wireless devices (USB unaffected).
$CURL -X POST -H "Content-Type: application/json" \
  -d '{}' "$ARENA_BRIDGE_URL/v1/mobile/disconnect"
```

## Generic APK install

```bash
# 1. Upload the APK to /tmp/arena-apk-staging/ on the bridge (scp,
#    workspace upload, whatever).

# 2. Prepare: computes SHA-256 + consent token + best-effort package
#    name + apksigner check (if available).
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"apk_path":"my-app.apk"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/apk/prepare"

# 3. Install using the exact consent token from step 2.
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"apk_path":"my-app.apk","consent":"yes-install-abc123ef"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/apk/install"
```

## Diagnostic shell

Restricted allowlist — `getprop`, `dumpsys`, `pm`, `wm`, `settings get`,
etc. Mutating verbs (`settings put`, `pm uninstall`, `svc`) are refused.

```bash
$CURL -X POST -H "Content-Type: application/json" \
  -d '{"command":"getprop ro.product.model"}' \
  "$ARENA_BRIDGE_URL/v1/mobile/{serial}/shell"
```

## CLI shortcut (v3.84.0)

`bin/arena-mobile` is a shell client that reads the same
`ARENA_BRIDGE_URL` / `ARENA_BRIDGE_TOKEN` env pair.

```bash
arena-mobile devices
arena-mobile info 2200ad3b --section overview
arena-mobile screenshot 2200ad3b -o phone.webp
arena-mobile tap 2200ad3b 720 1500
arena-mobile gesture 2200ad3b notifications
arena-mobile batch 2200ad3b @steps.json
arena-mobile pair 192.168.1.5 38571 654321
```

## All 27 endpoints in one screen

```
GET  /v1/mobile/devices
GET  /v1/mobile/{s}/info
GET  /v1/mobile/{s}/screenshot          # ?max_size, quality, format, force_png_source
POST /v1/mobile/{s}/tap                  # {x, y}
POST /v1/mobile/{s}/swipe                # {x1,y1,x2,y2, duration_ms}
POST /v1/mobile/{s}/scroll               # {x, y, vscroll, hscroll}
POST /v1/mobile/{s}/type                 # {text}
POST /v1/mobile/{s}/key                  # {key}
POST /v1/mobile/{s}/key_combo            # {keys: [...]}
POST /v1/mobile/{s}/gesture              # {gesture}
GET  /v1/mobile/{s}/ui                   # ?interactive_only, max_nodes
POST /v1/mobile/{s}/tap_by               # {id | text | desc | class_name | package | index | match}
GET  /v1/mobile/{s}/sensors              # ?events_per_sensor
POST /v1/mobile/{s}/shell                # {command}
GET  /v1/mobile/{s}/packages             # ?filter, include_system, include_disabled
POST /v1/mobile/{s}/batch                # {steps: [...], stop_on_error?}
GET  /v1/mobile/helpers/status
POST /v1/mobile/{s}/helpers/install      # {consent}
GET  /v1/mobile/{s}/ime
POST /v1/mobile/{s}/ime/set
POST /v1/mobile/{s}/ime/reset            # {target?}
POST /v1/mobile/{s}/paste                # {text}
POST /v1/mobile/pair                     # {host, port, code}
POST /v1/mobile/connect                  # {host, port?}
POST /v1/mobile/disconnect               # {host?, port?}
POST /v1/mobile/apk/prepare              # {apk_path}
POST /v1/mobile/{s}/apk/install          # {apk_path, consent}
```
