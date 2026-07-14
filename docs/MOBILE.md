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

## All 52 endpoints in one screen (v3.84.5)

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
POST /v1/mobile/apk/upload               # raw APK bytes
# Camera (v3.84.1 + v3.84.4).
POST /v1/mobile/{s}/camera/launch        # {intent?, package?}   intent: still|video|generic
POST /v1/mobile/{s}/camera/shutter       # {shutter_x?, shutter_y?}
GET  /v1/mobile/{s}/camera/photos        # ?limit
POST /v1/mobile/{s}/camera/pull          # {path, max_size?, format?, quality?}
POST /v1/mobile/{s}/camera/capture       # end-to-end: launch -> shutter -> pull
GET  /v1/mobile/{s}/camera/controls      # (v3.84.4) all clickable UI nodes in camera app
POST /v1/mobile/{s}/camera/mode          # (v3.84.4) {mode}   photo|video|portrait|pro|night|document|slowmo|timelapse|pano|short|movie
POST /v1/mobile/{s}/camera/lens          # (v3.84.4) {target}  front|back|toggle
POST /v1/mobile/{s}/camera/zoom          # (v3.84.4) {level}   0.6 | 1.0 | 2.0 | 3 | ...
POST /v1/mobile/{s}/camera/flash         # (v3.84.4) {mode}    auto|on|off|torch
POST /v1/mobile/{s}/camera/record/start  # (v3.84.4) starts in-app video recording
POST /v1/mobile/{s}/camera/record/stop   # (v3.84.4) {pull?, max_size?}  stops + optionally returns bytes
# Screen recording via screenrecord (v3.84.2, independent of camera app).
POST /v1/mobile/{s}/recording/sync       # sync capture
POST /v1/mobile/{s}/recording/start
POST /v1/mobile/recording/{rec_id}/stop
GET  /v1/mobile/{s}/recordings
GET  /v1/mobile/recording/{rec_id}
POST /v1/mobile/{s}/recording/purge
# Live H.264 mirror (v3.84.3 BETA).
GET  /v1/mobile/{s}/mirror               # WebSocket + ?token= auth
GET  /v1/mobile/mirror/stats
POST /v1/mobile/{s}/mirror/stop
# Transport fallback (v3.84.5).
GET  /v1/mobile/transport                # global registry snapshot
GET  /v1/mobile/{s}/transport            # per-serial view
POST /v1/mobile/{s}/transport/tcp/enable # {host?, port?}  probe wlan0 + adb tcpip + adb connect + register alias
POST /v1/mobile/{s}/transport/tcp/disable# {alias?}         drop alias + adb disconnect
```

## Transport fallback (v3.84.5)

USB flaps happen. When they do, every ADB call in-flight returns
`device 'XXX' not found` and there's nothing an API caller can do
about it. The transport fallback registers a wireless-ADB address for
the same phone and transparently routes calls to it once the USB
side trips a per-transport circuit breaker.

### Enable it once

```bash
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{}' \
  "$BRIDGE/v1/mobile/$S/transport/tcp/enable" | jq
```

Response walks the four stages so you can see what happened even on
failure:

```json
{
  "ok": true,
  "alias": "192.168.50.181:5555",
  "stages": [
    {"stage": "probe_ip", "wifi_ip": "192.168.50.181"},
    {"stage": "tcpip", "returncode": 0, "stdout": "restarting in TCP mode port: 5555"},
    {"stage": "connect", "ok": true, "output": "connected to 192.168.50.181:5555"},
    {"stage": "register", "alias": "192.168.50.181:5555"}
  ]
}
```

### Watch the health

```bash
curl -sSf -H "Authorization: Bearer $TOK" \
  "$BRIDGE/v1/mobile/$S/transport" | jq
```

Each transport reports `healthy`, `consecutive_fails`,
`cooldown_remaining_sec`, `total_calls`, `total_fails`, `last_error`.
The device object also carries `is_multi_transport` (true when at
least one alias is registered) and `active_transport` (the address
that will be used for the next call).

### How the breaker fires

Three back-to-back offline-shaped errors on a single transport
(`device offline`, `device 'XXX' not found`, `no devices/emulators
found`, `device unauthorized`, `failed to get feature set`, etc.)
mark it unhealthy for 20 s. During cooldown the router serves the
next healthy transport. A successful call resets the counter
immediately.

Non-offline errors (permission denied, activity not found, invalid
key event...) never trip the breaker — they're app-level failures,
not transport failures.

### Drop it

```bash
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{}' \
  "$BRIDGE/v1/mobile/$S/transport/tcp/disable"
```

Drops every TCP alias and runs `adb disconnect` on each one. The
USB primary is untouched.

## Camera control cookbook (v3.84.4)

The camera control surface deliberately drives the **stock camera
app** (via UIAutomator taps) rather than talking to the raw Camera2
HAL. That means you get whatever the phone's photo/video pipeline
already knows how to do — HDR, night mode, portrait bokeh, 4K@60,
telephoto lens selection, etc. — without re-implementing any of it.

### Introspect what's on screen

```bash
# First: what modes / lenses / zoom chips are visible right now?
curl -sSf -H "Authorization: Bearer $TOK" \
  "$BRIDGE/v1/mobile/$S/camera/controls" | jq
```

Response includes every clickable node with `resource_id`,
`content_desc`, `text`, `bounds`, `center`. Also side-effects a warm
shutter-cache entry so subsequent record calls survive UIAutomator
outages.

### Take a photo end-to-end

```bash
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{}' \
  "$BRIDGE/v1/mobile/$S/camera/launch"

# ... optionally: switch lens, set zoom, set flash, switch mode ...
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{"target":"back"}' \
  "$BRIDGE/v1/mobile/$S/camera/lens"

curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{"level":"2.0"}' \
  "$BRIDGE/v1/mobile/$S/camera/zoom"

curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{"mode":"off"}' \
  "$BRIDGE/v1/mobile/$S/camera/flash"

curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{}' \
  "$BRIDGE/v1/mobile/$S/camera/shutter"

# Pull the newest photo back to the bridge (JPEG downscaled to 1024px):
curl -sSf -H "Authorization: Bearer $TOK" \
  "$BRIDGE/v1/mobile/$S/camera/photos?limit=1" | jq
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"path":"/sdcard/DCIM/Camera/IMG_....jpg","max_size":1024}' \
  "$BRIDGE/v1/mobile/$S/camera/pull" | jq -r '.bytes_b64' | base64 -d > photo.jpg
```

### Record a video end-to-end

```bash
# Launch the camera app + warm the shutter cache.
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{}' \
  "$BRIDGE/v1/mobile/$S/camera/launch"
sleep 3
curl -sSf -H "Authorization: Bearer $TOK" \
  "$BRIDGE/v1/mobile/$S/camera/controls" > /dev/null

# Start recording (switches to video mode + presses shutter).
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" -d '{}' \
  "$BRIDGE/v1/mobile/$S/camera/record/start"

sleep 10   # record for 10 seconds

# Stop + return the MP4 as base64 in the response.
curl -sSf -X POST -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"pull":true,"wait_for_file_ms":25000}' \
  "$BRIDGE/v1/mobile/$S/camera/record/stop" \
  | jq -r '.bytes_b64' | base64 -d > clip.mp4
```

`record_stop` polls DCIM for a fresh MP4, then waits for the file
size to stabilise before reading bytes (encoders take ~1 s to finish
finalising `moov` after you press stop).

### Localisation

`switch_mode` and `set_flash` match a table of English + Russian
labels. To add another language, extend `_MODE_ALIASES` /
`_FLASH_ALIASES` in `arena/mobile/camera_controls.py` with the
strings that appear in your camera app.
```
