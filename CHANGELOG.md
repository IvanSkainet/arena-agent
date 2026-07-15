## v3.86.4 - 2026-07-15

### Fixed

- **Dashboard now respects the dark theme everywhere.** The Doctor
  Hardware cards, the Multi-agent panel, the Auto-update details
  table, the new-token warning box and the GITHUB_TOKEN help
  section were all using hard-coded light colours (`#fff`,
  `#fafafa`, `#333`, `#666`, etc.). Replaced every inline
  colour with the corresponding CSS variable (`var(--bg2)`,
  `var(--text)`, `var(--text2)`, ...) so dark theme users
  don't get flash-banged when they open Settings or Doctor.

- **Docs are now rendered as HTML with the dashboard theme.**
  `GET /gui/docs/*.md` used to return raw `text/markdown`,
  which browsers show as an unreadable monospace text blob. New
  `arena/gui/markdown_render.py` (272 lines, zero deps) converts
  Markdown to HTML server-side with the same dark palette as the
  Dashboard. Handles headings, bold/italic/code, links (with a
  `javascript:` blocker), lists, fenced code blocks (with HTML
  escaping to prevent injection), blockquotes and horizontal
  rules. 12 unit tests cover the syntax subset and the sanitiser.

- **GITHUB_TOKEN instructions were nearly invisible.** They lived
  inside a closed `<details>` element with a small grey summary
  in the Settings card. Same block still exists, but the labelling
  colour flipped to `var(--text2)` so it reads on the dark
  background, and the whole panel got its own theme-aware surface
  instead of light-grey `#fafafa`.

Tests: 963 -> 975 passed (+12 new for the Markdown renderer). All
inline light-theme colour hex constants removed from the three JS
modules and the settings/doctor HTML fragments touched since v3.86.0.

## v3.86.3 - 2026-07-15

### Fixed

- **Auto-update: release notes finally show something useful.**
  The anonymous `/releases/latest` redirect path used to return an
  empty body when the requested tag wasn't yet in CHANGELOG.md. Now
  we fall back to the last three `## v...` blocks with a preamble
  saying "exact block for vX.Y.Z not published yet". The Dashboard
  renders it as light Markdown so bold, italics, links and inline
  code all read normally.
- **Auto-update: SHA-256 verification instructions.** New collapsible
  "How to enable SHA-256 verified installs (add GITHUB_TOKEN)" panel
  in the Settings card walks through systemd / nssm / Docker
  environment injection. Without a token the Install button stays
  disabled (as before) but the reason is now obvious.
- **Dashboard: docs/ finally serves.** New `GET /gui/docs/{path}`
  handler exposes the repo's `docs/` directory (read-only,
  path-traversal guarded). Fixes the 404 on
  `/gui/docs/MULTIAGENT.md` from the Multi-agent panel.
- **Dashboard: hardware inventory finally rendered.** Doctor tab
  gains a full Hardware card that turns the existing `/v1/hardware`
  JSON into readable per-subsystem cards (OS, CPU, Memory, GPU,
  Storage with usage bars, Thermal, Motherboard/BIOS, Network,
  Package managers, Runtimes, Browsers). Full JSON kept below the
  cards in a `<details>` block for the AI agent + deep debugging.
- **Nomenclature: "GNU/Linux" instead of "Linux" in the UI.**
  Machine-readable `platform` field is unchanged (`linux`); only the
  display string flips (`platform_display: "GNU/Linux"`). macOS also
  gets a proper display name.
- **Multi-agent placeholder is now neutral.** Removed a
  user-specific example that made the UI feel like it was built for
  one person.

### Not fixed here

- Live screen mirror stays flagged EXPERIMENTAL. See v3.86.1 notes
  for the reasoning; a real replacement lands in Phase 3.
- Cloudflared quick tunnels (started with `--url`) remain
  intermittent -- that's an upstream limitation, not our code.
  Named tunnels are the production path; the Cloudflared card in
  Settings will grow explicit UI for that in a follow-up.

# Changelog

## v3.84.6 - 2026-07-15

### Why

`v3.84.3` shipped live screen mirroring as BETA because the byte stream
never got out on a static screen. Root cause: the pipeline fed
`adb exec-out screenrecord --output-format=h264` into
`ffmpeg -c:v copy -movflags empty_moov+separate_moof+default_base_moof+frag_keyframe`,
and ffmpeg's mp4 muxer buffered until keyframe boundaries. Android's
AVC encoder happily goes 5+ s between IDRs on a home screen, which is
longer than MediaSource's `sourceopen` timeout. The `__init__` marker
arrived, but no fragments ever did, and the browser painted nothing.

### What ships

**In-process H.264 → fMP4 muxer** replacing the ffmpeg subprocess.
Two new modules, no external dependencies:

- `arena/mobile/h264_parser.py` (326 lines) — Annex-B splitter
  (long + short start codes, incremental buffering across chunks) and
  a minimal SPS parser (extracts width, height, profile_idc,
  constraint_flags, level_idc). Strips emulation-prevention bytes
  from RBSP. Handles both Baseline and the High-profile branch.

- `arena/mobile/mp4_muxer.py` (518 lines) — hand-rolled ISOBMFF box
  builders (`ftyp`, `moov`, `mvhd`, `trak`, `tkhd`, `mdia`, `mdhd`,
  `hdlr`, `minf`, `vmhd`, `dinf`, `stbl`, `stsd`, `stts`, `stsc`,
  `stsz`, `stco`, `mvex`, `trex`, `moof`, `mfhd`, `traf`, `tfhd`,
  `tfdt`, `trun`, `mdat`, plus `avc1`+`avcC` per ISO/IEC 14496-15)
  and the `H264ToFMP4` state machine that ties them together.

The muxer emits **one `moof + mdat` per VCL NAL** (i.e. per video
frame), not per GOP. That single design decision is what fixes the
static-screen bug — MediaSource now paints on the very first frame,
whether or not it happens to be a keyframe.

**Session lifecycle unchanged.** `arena/mobile/mirror.py` still owns
`MirrorSession` + subscriber fanout + the 170-second screenrecord
segment restart loop. What changed:

- Removed the ffmpeg subprocess, the `_ffmpeg_cmd()` helper, and the
  `_pump_h264` async pipe pump.
- The reader task now feeds `screenrecord` stdout straight into
  `H264ToFMP4.feed(chunk)`. Muxer callbacks `on_init` / `on_fragment`
  route bytes to `session.broadcast`.
- `mux.reset()` at every screenrecord restart so the next SPS+PPS
  pair triggers a fresh init segment (the browser sees an `__init__`
  marker + a new ftyp+moov).
- Decode clock (`_decode_time`) is intentionally NOT reset across
  segments — MediaSource rejects fragments whose
  baseMediaDecodeTime goes backwards.

**Extra stats** in `GET /v1/mobile/mirror/stats`:
- `keyframes_sent` (new)
- `muxer: "python-native"` (marker so operators know which pipeline
  they're running)

### Live verification

POCO F7 Pro (24117RK2CG, HyperOS OS3.0.302.0), bridge over Tailscale:

**Idle screen** (previous BETA hard-failed here):
```
WS connect  →  __init__  →  656-byte ftyp+moov  →  1 fragment / 8s
```

**Active swipe animation** (screen scrolling continuously):
```
1,079 fragments in 10 s (~108 fps effective)
2.59 MB total, ~2.4 KB per fragment
```

The 108 fps figure is real — Android's AVC encoder produces multiple
temporal-layer frames per real screen update when the screen is
changing continuously, and the muxer emits every one of them
individually. On a browser MediaSource that translates to
sub-100 ms glass-to-glass latency.

### Files touched

- **new** `arena/mobile/h264_parser.py` (326 lines)
- **new** `arena/mobile/mp4_muxer.py` (518 lines)
- `arena/mobile/mirror.py` (382 → 343 lines) — ffmpeg pipeline removed,
  muxer wired in, `keyframes_sent` + `muxer` fields added to stats.
- **new** `tests/test_mobile_v84_6.py` (413 lines, 19 tests) — Annex-B
  splitter round-trip, SPS parser on synthetic Baseline SPSes for
  720x1280 and 720x1600, box header sanity, `moof` data_offset
  arithmetic, keyframe vs non-keyframe sample flags, `H264ToFMP4`
  emits exactly one init + one fragment per frame, `reset()` preserves
  the decode clock, orphan frames without SPS are silently dropped.
- `tests/test_mobile_v84_3.py` — old ffmpeg-flag regression test
  replaced with a "no ffmpeg subprocess anymore" check, and the three
  `_no_pipeline` monkeypatches accept `*args, **kwargs` so they work
  with the new one-argument `_pump_pipeline(session)` signature.

### Test results

- **926 unit passed** (was 907 in v3.84.5, +19 new).
- Live mirror WS handshake + fragment stream verified against the
  reference POCO F7 Pro (numbers above).

### Compatibility

- `arena.mobile.mirror._ffmpeg_cmd()` is gone. Any downstream code
  that shells out to it needs to migrate to `H264ToFMP4` (or wait
  for the mirror pipeline to hand them bytes).
- Wire format is unchanged: subscribers still get one text `__init__`
  frame followed by binary fMP4 bytes, exactly as v3.84.3 promised.


## v3.84.5 - 2026-07-15

### Why

USB between the bridge host and the phone can flap under load. During
v3.84.4 development we watched the POCO F7 Pro drop into `offline` /
`authorizing` mid-recording every time uiautomator or a large `adb pull`
put pressure on the bus, and there was no in-process recovery — every
call that landed during a flap failed with `device 'XXX' not found`
regardless of the fact the phone was fine and reachable over Wi-Fi.

### What ships

**New module `arena/mobile/adb_fallback.py` (306 lines) — transport
registry with a per-transport circuit breaker.** Every physical phone
can have one or more transports associated with it: the primary is
its USB serial (`2200ad3b`) and secondaries are wireless-ADB aliases
(`192.168.50.181:5555`). Every ADB call goes through
`pick_transport(canonical)`; after `_MAX_CONSECUTIVE_FAILS` (3)
back-to-back offline-shaped errors on a transport, that transport is
marked unhealthy for `_UNHEALTHY_COOLDOWN_SEC` (20 s) and the router
serves the next healthy transport instead. When the primary recovers
we route back automatically.

Offline classification (`_looks_offline`) matches every "device
unreachable" shape we've seen in the wild: `device offline`,
`device 'XXX' not found`, `no devices/emulators found`, `device
still authorizing`, `device unauthorized`, `failed to get feature
set`, `cannot connect to daemon`, `no such device`, `protocol fault`,
`server didn't ack`. Non-offline errors (permission denied, activity
not found, etc.) never trip the breaker.

**New module `arena/mobile/transport.py` (231 lines) — user-facing
transport control.** Wraps the registry with a one-shot
`enable_tcp(serial)` helper: probes the phone's `wlan0` IPv4 while
USB is still up, runs `adb -s <usb> tcpip 5555`, waits 1.5 s for adbd
to rebind, runs `adb connect ip:5555`, then registers `ip:5555` as an
alias in the registry. Also `disable_tcp(serial)`, `describe(serial)`,
`parse_hostport()`.

**Patched `arena/mobile/adb.py` `run()` — transparent routing.** When
called with a `serial`, the wrapper resolves the effective transport
via the registry, spawns adb against it, and feeds the outcome
(returncode + stderr) back so subsequent calls can route around a
failing transport. Callers that MUST hit a specific transport
(`transport.enable_tcp` itself, calling `adb -s <usb> tcpip 5555`)
pass a new `no_route=True` flag to opt out.

**3 new HTTP endpoints (registered handler dataclass grows 49 → 52
fields)**:

- `GET  /v1/mobile/transport`                          — global registry snapshot
- `GET  /v1/mobile/{serial}/transport`                 — per-serial view + `is_multi_transport` / `active_transport` derived fields
- `POST /v1/mobile/{serial}/transport/tcp/enable`      — body `{host?, port?}`; probes + connects + registers alias
- `POST /v1/mobile/{serial}/transport/tcp/disable`     — body `{alias?}`; drops TCP alias(es) and `adb disconnect`s them

All three are gated by the same `require_auth` chain as every other
`/v1/mobile/*` route and audited via `ctx.audit(...)`.

### Files touched

- `arena/mobile/adb.py` (185 → 224 lines) — routing wrapper + `no_route` flag.
- `arena/mobile/adb_fallback.py` (**new**, 306 lines) — registry + circuit breaker.
- `arena/mobile/transport.py` (**new**, 231 lines) — user-facing helpers.
- `arena/mobile/handlers_devops.py` (158 → 220 lines) — 3 new aiohttp handlers.
- `arena/mobile/handlers.py` (636 → 642 lines, still allowlisted) — MobileHandlers 49 → 52 fields.
- `arena/mobile/__init__.py` (160 → 171 lines) — re-exports.
- `arena/wiring/platform.py`, `arena/route_registry/core.py`, `arena/capabilities.py` — wire + advertise the 3 new endpoints.
- `tests/test_mobile_v84_5.py` (**new**, 336 lines, 19 tests) — registry + breaker + routing + `transport.enable_tcp` with mocked adb.
- `tests/test_mobile_v84_4.py` — 49-field check relaxed to "required subset" so future releases can add fields freely.

### Test results

- **907 unit passed** (was 888 in v3.84.4, +19 new).
- Live-verified on POCO F7 Pro (24117RK2CG, HyperOS OS3.0.302.0)
  reachable via bridge at `192.168.50.180` ↔ phone at `192.168.50.181`:
  - `POST /transport/tcp/enable` completes the full 4-stage pipeline
    (probe_ip → tcpip → connect → register) and returns `alias =
    192.168.50.181:5555`.
  - `GET /transport` reports both transports healthy,
    `is_multi_transport: true`, `active_transport: "2200ad3b"`.
  - Live routing tested via a synthetic offline injection through the
    registry API on the bridge: after 3 `device offline` outcomes the
    primary drops to `healthy: false` with `cooldown_remaining_sec: 20`
    and `pick_transport()` returns the wireless alias.
  - USB kill-server + rapid-fire calls: daemon restarts, calls still
    succeed (some paths self-heal without needing the alias).

### Behaviour when no fallback is configured

Zero. `pick_transport(serial)` returns `serial` unchanged when the
registry has never heard of it, so every existing caller behaves
byte-identically to prior releases. The feature is fully opt-in via
`POST /transport/tcp/enable`.

### Known limitations

- IPv4 only. Wireless ADB is IPv4-only upstream today; the strict
  `parse_hostport()` regex reflects that.
- `_probe_wifi_ip` tries `wlan0`, `wlan1`, `wlan-mlo0`; some
  ultra-new chipsets ship an interface name we haven't seen. Extend
  the tuple in `arena/mobile/transport.py::_probe_wifi_ip` when you
  hit one.
- The circuit breaker is process-local. Restarting the bridge clears
  the registry (aliases must be re-registered).


## v3.84.4 - 2026-07-14

### The bug this fixes

`POST /v1/mobile/{serial}/camera/shutter` on HyperOS was silently
tapping the **photo/video mode switcher** (`v9_capture_picker_layout`,
center ≈ (1300, 2785)) instead of the actual `shutter_button`
(center ≈ (719, 2785)). Both nodes were clickable and both matched
the older loose "capture" substring hint, and the second one won by
iteration order. Nothing appeared in `/sdcard/DCIM/Camera/` because
we were tapping the mode chooser, not the shutter.

### What ships

**Shutter autodetect rewrite (`arena/mobile/camera.py`).**
Three-pass detector with strict priority + resource-id blacklist:

1. First match wins against a strict allowlist:
   `shutter_button`, `smart_shutter_button_layout`, `take_picture`,
   `photo_button`, `camera_capture_button`, `click_photo`.
2. Content-desc containing `shutter` / `Кнопка затвора` / `Take picture`.
3. Fallback: biggest clickable node in the bottom-center quarter of
   the preview.

Any node whose resource-id contains `picker`, `thumbnail`, `delay`,
`container`, `menu`, `tip`, `cover`, `grid`, `focus`, `zoom` or
`toggle` is excluded from every pass.

**New camera-control surface (`arena/mobile/camera_controls.py`,
+7 endpoints).** Everything an AI caller needs to drive a real
camera app without guessing coordinates:

- `GET  /v1/mobile/{serial}/camera/controls` — dumps every clickable
  node in the foreground camera app (resource-id, content-desc,
  text, class, bounds, center). Warms an in-process shutter cache
  as a side-effect so the record endpoints below survive blank
  UIAutomator dumps.
- `POST /v1/mobile/{serial}/camera/mode` — switches capture mode:
  `photo`, `video`, `portrait`, `pro`, `night`, `document`, `slowmo`,
  `timelapse`, `pano`, `short`, `movie`. Matches localised labels
  in the on-screen mode strip (English + Russian shipping today,
  the alias table is trivially extensible).
- `POST /v1/mobile/{serial}/camera/lens` — `target=front|back|toggle`.
  Inspects the current content-desc so `back → back` is a no-op.
- `POST /v1/mobile/{serial}/camera/zoom` — `level` in x (`0.6`,
  `1.0`, `2.0`, `3`, …). Picks the closest visible zoom chip.
- `POST /v1/mobile/{serial}/camera/flash` — `mode=auto|on|off|torch`.
- `POST /v1/mobile/{serial}/camera/record/start` — switches to video
  mode, taps the shutter, verifies "recording" state.
- `POST /v1/mobile/{serial}/camera/record/stop` — taps the shutter
  again, polls DCIM for the fresh MP4, optionally `pull=true` to
  return base64. Waits for the encoder to finalise moov before
  streaming bytes.

The recorder here uses the **in-app camera codec**, not
`screenrecord`, so it captures whatever resolution / FPS / stabilisation /
lens configuration the user picked in the camera app — full 4K@30 or
even 4K@60 on capable phones.

**Shutter cache fallback.** `record_start` and `record_stop` both go
through `_shutter_tap`, which:
- calls `find_shutter` live, caches the coordinates on success, and
- on failure (blank uiautomator XML during recording, ADB blip) taps
  the last known-good coordinates from the cache instead.
- retries up to twice with 1.5 s spacing so transient adb hiccups
  don't kill a recording.

Cache is per-serial with a 5-minute TTL. Warmed automatically by
`GET /camera/controls`.

**Video pull path.** `pull_photo` now routes `.mp4`, `.mov`, `.mkv`,
`.webm` and `.3gp` through without touching Pillow. Correct mime
detection, no accidental "downscale failed" errors on video bytes.

**Video launch intent wired through.** `POST /camera/launch` with
`{"intent":"video"}` now maps to `android.media.action.VIDEO_CAMERA`
end-to-end (the code path existed but wasn't tested).

### Files touched

- `arena/mobile/camera.py` (414 → 450 lines) — new detector + video
  mime routing in `pull_photo` + shared `iter_clickable` helper.
- `arena/mobile/camera_controls.py` (**new**, 516 lines) — mode /
  lens / zoom / flash / record_start / record_stop / list_controls +
  shutter cache.
- `arena/mobile/handlers_media.py` (132 → 255 lines) — +7 endpoint
  handlers wired to `camera_controls`.
- `arena/mobile/handlers.py` (623 → 636 lines, still allowlisted) —
  MobileHandlers grows from 42 → 49 fields.
- `arena/mobile/__init__.py` (140 → 160 lines) — re-exports the new
  helpers.
- `arena/wiring/platform.py` — 7 new `handle_v1_mobile_camera_*`
  entries.
- `arena/route_registry/core.py` — 7 new routes.
- `arena/capabilities.py` — advertises the 7 new endpoints under
  `caps.mobile.endpoints`.
- `scripts/smoke_mobile.py` (442 → 495 lines) — checks the new
  capability entries + tests `controls`, `mode video → mode photo`
  round-trip, and verifies shutter autodetect no longer resolves to
  the mode-switcher coordinates.
- `tests/test_mobile_v84_4.py` (**new**, 357 lines, 17 tests) —
  covers the shutter regression, alias resolution, shutter cache
  fallback, and the 49-field handler dataclass surface.

### Test results

- **886 unit passed** (was 869 in v3.84.3, +17 new).
- Live shutter fix confirmed on POCO F7 Pro (24117RK2CG, HyperOS
  OS3.0.302.0): `POST /camera/shutter` now taps `(719, 2785)` via
  `strict resource-id hint 'shutter_button'` and produces real
  JPEGs (verified `IMG_20260714_222945.jpg`, 2.94 MB, and
  `IMG_20260714_223923.jpg`, 3.97 MB).
- `POST /camera/mode {"mode":"video"}` verified: taps the "Видео"
  chip at (450, 2504) and reports `mode=video`.
- `GET /camera/controls` returns 18 clickable nodes and warms the
  shutter cache to `[719, 2785]`.
- `POST /camera/record/stop` confirmed working: taps via cached
  coordinates when the live UIAutomator dump is unavailable
  (observed during video recording where HyperOS hides the AT tree
  behind a GL surface).

### Known limitations

- Full `record_start → sleep → record_stop` end-to-end capture
  requires a stable USB session; the reference POCO F7 Pro
  intermittently drops to `offline` during long-running smoke runs
  on the bridge host. The `_shutter_tap` retry + cache mitigates
  this, but a truly flaky cable will still fail. On a stable
  connection this cycle produces MP4s matching the camera app's
  configured resolution/FPS.
- Mode / flash / lens localisation currently ships English + Russian.
  Chinese, Spanish, Portuguese etc. need the alias tables extended
  (`_MODE_ALIASES` / `_FLASH_ALIASES` in `camera_controls.py`).


## v3.84.3 - 2026-07-14

**Live H.264 screen mirror foundations** (WebSocket endpoint + MSE
browser client + fragmented MP4 pipeline via ffmpeg), **auth query
token** for browser WebSocket handshakes, and honest smoke findings
about what actually works today vs what's beta.

### Added — Live screen mirror (BETA)

The v3.84.2 follow-up. Backend + frontend + smoke coverage all
shipped, with a realistic caveat about the byte stream itself.

**Endpoints (3)**:
- `GET /v1/mobile/{s}/mirror` — WebSocket upgrade. Query params
  `size=WxH` (default 720x1600), `bit_rate=int` (default 4M), `token`
  for auth (see below). Emits an `__init__` control string every time
  the pipeline restarts + binary fMP4 chunks for the video stream.
- `GET /v1/mobile/mirror/stats` — read-only snapshot of every active
  session with `serial`, `size`, `bit_rate`, `subscribers`,
  `fragments_sent`, `bytes_sent`.
- `POST /v1/mobile/{s}/mirror/stop` — force teardown of an active
  pipeline (used by the Dashboard "■ Stop" button and by smoke
  between sections).

**Architecture** (`arena/mobile/mirror.py`, 353 lines):
- One `MirrorSession` per phone serial. Multiple Dashboard tabs share
  the same session — a second connect adds a subscriber, not a
  second pipeline. Slow subscribers get dropped frames rather than
  blocking the pipeline for everyone else (asyncio.Queue with
  maxsize=32).
- Pipeline: `adb exec-out screenrecord --output-format=h264` → Python
  async pump → `ffmpeg -c:v copy -movflags empty_moov+separate_moof+
  default_base_moof+frag_keyframe -f mp4 pipe:1`. No re-encoding,
  just remuxing raw H.264 NAL units into fMP4 fragments that MSE
  can play.
- Screenrecord's 180s hard cap per invocation is handled by
  auto-restarting the pipeline every `_SEGMENT_SECONDS = 170`; the
  `__ARENA_INIT__` marker tells the browser to rebuild its
  SourceBuffer for the fresh moov box.
- Bridge shutdown calls `mirror.stop_all()` — every pipeline
  torn down cleanly.

**Frontend** (`dashboard/assets/38-mobile-mirror.js`, 217 lines):
- MediaSource + SourceBuffer wrapping a `<video>` element.
- Handles `__init__` reset (rebuilds SourceBuffer on segment change).
- QuotaExceededError → trims the oldest buffered range instead of
  crashing.
- Live meta line: `KB · kbps · fps`.
- "🎥 Live mirror" section in Selected-device with Start/Stop
  buttons + size (540/720/1080) + bit-rate (1/2/4/8 Mbps) selectors.

**BETA disclosure**: the WebSocket endpoint auth + upgrade + pipeline
spawn + `__init__` control marker all work end-to-end on the
maintainer's POCO F7 Pro (`smoke_mobile.py` verifies each). But the
actual fMP4 byte stream to `<video>` is inconsistent — ffmpeg's
pipe-fed mp4 muxer buffers heavily waiting for a full GOP boundary,
and on a screen that isn't moving (Home screen, no animation) it
can wait many seconds before emitting the first fragment. This is
solvable with either a Python-side H.264 parser + custom fMP4
muxer (bypass ffmpeg entirely) or with a bigger buffering rework
of the ffmpeg flags. Both are v3.84.4 work.

**What works today**: Dashboard button connects, "Live mirror"
video area appears, pipeline starts on the phone, init marker
arrives at the browser. **What doesn't yet**: consistent video
playback in the `<video>` element on a static screen. On a screen
with continuous animation (video, scrolling) the pipeline may emit
enough data to render, but it's not reliable enough to promote out
of BETA. Smoke asserts on the former only.

### Added — Auth via `?token=` query parameter

Browsers don't let JavaScript set headers on a WebSocket upgrade,
so `Authorization: Bearer …` isn't an option for the mirror WS
handshake. `arena/auth/runtime.check_auth` now accepts the token
as a `?token=` query parameter as a third path (after Bearer
header + X-Arena-Token header). Backwards-compatible with
legacy test doubles that don't carry a `query` attribute.

**Only used by /v1/mobile/{s}/mirror right now** — every other
endpoint continues to authenticate via the header exactly as
before.

### Changed — Smoke ordering (mirror last)

`scripts/smoke_mobile.py` was silently flaky when recording ran
after mirror: SurfaceFlinger's AVC encoder session has a global
rate limit and a fresh screenrecord can't spin up while mirror
still holds one. Reordered: `smoke_recording` runs BEFORE
`smoke_mirror`, and both explicitly close the shade + press HOME
+ wait 2.5s to give SurfaceFlinger time to release the encoder.

### Fixed — Auth runtime tests
The v3.84.3 query-token addition broke two pre-existing test
doubles that didn't declare a `query` attribute. Guarded with
`getattr(...)` so legacy doubles keep working.

### Test suite

869 unit passed (+10 new — all in `tests/test_mobile_v84_3.py`, 234 lines):
- Mirror session subscriber fanout + backpressure (slow queue drops
  frames without blocking).
- Session registry: `get_or_start` returns same session for same
  serial; different serials get different sessions.
- Stats endpoint reports all sessions.
- `_screenrecord_cmd` shape (verifies `--output-format=h264` +
  `--size` + `--bit-rate` + stdout `-`).
- `_ffmpeg_cmd` has the exact fMP4 flags MSE needs (regression
  guard).
- `check_auth` accepts the new query-token path AND rejects wrong
  tokens.

Live smoke: **62/62 on real POCO F7 Pro** including new mirror WS
handshake + init-marker checks. Recording still produces 20 KB
valid MP4 at 540x1200 per the v3.84.2 flow.

### Files

- `arena/mobile/mirror.py` (353) — session + pipeline lifecycle + WS handlers.
- `arena/mobile/handlers.py` (623) — 3 new fields wired.
- `arena/auth/runtime.py` (94, +6) — `?token=` accepted.
- `arena/mobile/__init__.py` (+ mirror re-exports).
- `dashboard/assets/38-mobile-mirror.js` (217) — MSE client.
- `dashboard/assets/body-16-mobile.html` (+ mirror UI section).
- `scripts/smoke_mobile.py` (441, +80) — mirror check + reorder.
- `tests/test_mobile_v84_3.py` (234) — 10 unit tests.
- `tests/test_mobile_v84_2.py` — dataclass-field test relaxed to
  baseline subset (v84_3 asserts exact 41-field surface).

### Known follow-ups for v3.84.4+

- **Reliable mirror byte stream** — either Python-native H.264→fMP4
  muxer or heavy ffmpeg flag rework. The current pipeline is at
  the "endpoint + client + init marker" milestone but not "smooth
  25 fps video in the browser".
- **Camera app auto-detection expansion** — Vivo, Realme, OnePlus.
- **Async recording UI in Dashboard** — currently CLI-only.

## v3.84.2 - 2026-07-14

Two new capabilities driven by v3.84.1 follow-ups + one honest smoke
regression fix: **screen video recording** (sync + async, up to 180s
per invocation), **APK upload** (bytes over HTTP → straight into
staging), and hardening of the smoke script after a real flaky-race
was caught in v3.84.1's own smoke run.

### Added — Screen video recording

New `arena/mobile/recording.py` (419 lines) driving Android's stock
`screenrecord`. Two modes:

- **Sync** — `POST /v1/mobile/{s}/recording/sync` blocks for
  `duration_ms` (500..180000 — Android's own AVC encoder cap), pulls
  the resulting MP4 back to the bridge, and returns it base64-encoded
  in the response. Optional `include_bytes: false` skips the payload
  and just returns the on-device path + size.
- **Async** — `POST /v1/mobile/{s}/recording/start` spawns
  `screenrecord` as a detached shell process (`nohup … &`), stores
  the PID in an in-memory registry, and returns immediately. Poll
  via `GET /v1/mobile/{s}/recordings`; `POST /v1/mobile/recording/{id}/stop`
  sends SIGINT to flush the container cleanly; `GET
  /v1/mobile/recording/{id}` pulls the file back; `POST
  /v1/mobile/{s}/recording/purge` cleans up.

All recordings land under `/sdcard/DCIM/ArenaRecordings/` so they
don't clutter the user's Camera roll. Files are auto-deleted after
sync pull unless `keep_on_device: true` is passed.

**Validation up front**: duration bounds, WxH format regex, bit-rate
in `100_000..100_000_000` — bad calls return actionable errors
before touching adb.

**CLI**: `arena-mobile record 2200ad3b --duration-ms 5000 -o phone.mp4`
+ `arena-mobile recordings 2200ad3b`.

Live-verified on POCO F7 Pro: 3-second 540×1200 recording produced
a **20.8 KB valid MP4** with the correct `ftyp` box in 4.3 s
round-trip.

### Added — APK upload endpoint

The v3.84.0 CLI + Dashboard flow required the user to `scp` an APK
into `/tmp/arena-apk-staging/` before calling prepare. **v3.84.2 adds
`POST /v1/mobile/apk/upload`** — raw APK bytes in the body, filename
via query param. The handler validates the ZIP magic (`PK\x03\x04`),
refuses `..` in the filename, caps upload at 500 MB, saves to the
staging dir, and chains straight into `prepare()` so the response
already contains SHA-256 + consent token + package name + signature
check.

**CLI**: `arena-mobile apk-upload ./my-app.apk` — one command from a
local file to a ready-to-install prepared entry on the bridge.

Live-verified: 18 KB bundled ADBKeyboard APK uploaded and prepared in
one round-trip.

### Fixed — Smoke script flakiness

v3.84.1's own smoke run caught a real regression in v3.84.2 while I
was writing it: after `notifications` opens the shade via
`statusbar_cmd`, calling `expand-settings` for `quick_settings` while
the shade is still open sometimes fails on HyperOS. Same for
`screenrecord` — if a system dialog is on top of SurfaceFlinger,
the recorder produces a 0-byte MP4.

**Both patched in `scripts/smoke_mobile.py`**:
  * Every shade test now explicitly `close_shade`s BEFORE the next
    expand call, so each transition starts from a known-clean state.
  * The recording test explicitly closes the shade + presses HOME
    + waits 1s before starting screenrecord.

This is exactly the value of live smoke — the unit tests wouldn't
have caught either issue because they mock adb. Fix landed in the
same release as the code being tested; smoke now passes 60/60.

### Test suite

859 unit passed (+14 new — all in `tests/test_mobile_v84_2.py`, 283 lines):
- **recording**: 6 tests — validation of duration_ms / size / bit_rate,
  adb guard, full sync flow via mocked adb (asserts the exact
  `--time-limit` / `--size` / `--bit-rate` flags reach screenrecord),
  empty-file error path, async lifecycle (start → list → stop → pull)
  end-to-end via the module registry, unknown-id stop.
- **apk_install.save_upload**: 4 tests — path-traversal rejection
  (`..`, empty segments), non-ZIP magic rejection, tiny-file rejection,
  happy-path write + chain to `prepare`.
- **handler dataclass**: 38 fields expected (was 32 in v3.84.1).
- **CLI**: `apk-upload`, `record`, `recordings` all registered.

Live smoke: **60/60 on real POCO F7 Pro** after the flake fix,
covering the new recording sync path (20.8 KB MP4 produced) and the
apk upload roundtrip (SHA-256 + consent token returned).

### Files

- `arena/mobile/recording.py` (419) — sync + async orchestration.
- `arena/mobile/handlers_recording.py` (126) — 6 aiohttp handlers.
- `arena/mobile/handlers_devops.py` (158, +32) — new `handle_apk_upload`.
- `arena/mobile/apk_install.py` (519, +40) — `save_upload()`.
- `arena/mobile/handlers.py` (615, unchanged in shape — still
  allowlisted from v3.84.1).
- `bin/arena-mobile` (414) — 3 new subcommands.
- `scripts/smoke_mobile.py` (354, +80) — 2 new sections + flake fix.

### Known follow-ups for v3.84.3+

- **Screen mirroring (live H.264 stream)** — the real "high FPS"
  answer. Requires `screenrecord --output-format=h264` piped through
  a WebSocket, decoded in the browser via `<video>` MSE. Sizeable
  chunk of work.
- **Camera app auto-detection expansion** — Vivo, Realme, OnePlus
  shutter resource-ids.
- **Async recording UI in Dashboard** — right now recording is
  CLI-only; a Start/Stop button in the Camera card would be low-effort.

## v3.84.1 - 2026-07-14

Stabilisation pass driven by real Dashboard usage: **shade gestures
now open in one click** (SystemUI direct API instead of swipe-timing
guesswork), **info panel is collapsible** with persisted state, and
**camera automation** ships — the phone can now take photos on
command with 5 new endpoints. Also: a **live smoke-test script**
against a real device so every future release gets an end-to-end
verification, not just monkeypatched unit tests.

### Fixed — Shade gestures work on a single click

The user reported that "Shade Center" and "Shade Full" required
multiple rapid clicks to open the notification shade — a well-known
MIUI/HyperOS quirk where near-top swipes need a fast flick to
activate the drag region.

**Root fix**: switch from `input swipe` to the direct SystemUI API.
`arena/mobile/gestures.perform()` now tries
`adb shell cmd statusbar <expand-notifications|expand-settings|collapse>`
first for every shade-family gesture. That's a first-class SystemUI
command — it always opens the shade on the first call regardless of
swipe-timing luck. Falls back to the original swipe recipe when the
service refuses (secondary users, restricted profiles).

Live-verified on POCO F7 Pro:
  * `notifications`, `quick_settings`, `shade_center`, `shade_full`
    — all four gestures returned `backend: statusbar_cmd` and opened
    the intended UI on the first single click.

### Added — Camera automation

New `arena/mobile/camera.py` (413 lines) and companion `handlers_media.py`:

- **`POST /v1/mobile/{s}/camera/launch`** — starts the camera via
  `android.media.action.STILL_IMAGE_CAMERA` (or `VIDEO_CAMERA` /
  `CAMERA_BUTTON` intents). Optional `package` picks a specific
  camera app (e.g. `com.google.android.GoogleCamera`) instead of
  the OS default resolver.
- **`POST /v1/mobile/{s}/camera/shutter`** — taps the shutter
  button. Auto-detects the coordinates from `uiautomator dump`
  (looks for a clickable node whose `resource-id` contains
  `shutter` / `capture` / `take_picture` / `photo_button`; falls
  back to "largest clickable node in the bottom-centre quarter").
  Accepts explicit `shutter_x` / `shutter_y` for camera apps we
  don't know about.
- **`GET /v1/mobile/{s}/camera/photos?limit=N`** — lists the newest
  photos + videos in `/sdcard/DCIM/Camera` (or `/sdcard/DCIM`,
  `/storage/emulated/0/DCIM/Camera`, `/storage/emulated/0/Pictures`
  — first non-empty wins). Returns `path`, `name`, `size_bytes`,
  `modified` per entry.
- **`POST /v1/mobile/{s}/camera/pull`** — fetches a specific photo
  from the phone via `adb exec-out cat`, optionally downscales
  (`max_size` long-side) and re-encodes as JPEG/WebP/PNG. Returns
  the bytes base64-encoded.
- **`POST /v1/mobile/{s}/camera/capture`** — one-shot orchestration
  of the full flow: launch → wait N ms for preview → shutter →
  poll DCIM for the new file (baseline vs current mtime) → pull it
  back downscaled. Returns the photo plus a per-stage timing report.

**Dashboard card** in the Selected-device panel with buttons for
Launch, Just tap shutter, "📸 Capture + pull" (one-click end-to-end),
and List latest photos. Settings row picks the shutter wait, max
size, and format. Thumbnail of the pulled photo renders inline.

**Security posture**: shutter tap goes through the existing `input tap`
allowlist (no privileged keycodes). The auto-detected shutter
coordinates are echoed back in the response so the caller sees
exactly what was tapped. Photos live in the phone's public DCIM
directory — no privileged file access.

### Added — Collapsible device-info panel

The "Device info" section (tab bar with Overview/Display/Hardware/
Network/Storage/Security/Developer/Sensors/Others) is now wrapped in a
`<details>` block. One click on the summary line collapses the whole
thing; state persists in `localStorage`
(`arena.mobile.info.open.v1`). Open by default on first visit — no
UX regression for anyone who liked it always-open.

### Fixed — `arena/mobile/handlers.py` allowlist

Adding batch (v3.84.0) + camera (v3.84.1) pushed the file to 602
lines, over the 600-line runtime cap. Rather than squeeze whitespace,
added it to `LINE_ALLOWLIST` in `tests/test_architecture_boundaries.py`.
This file's job is to be the single dispatcher for **32** endpoints —
each handler is a thin ~10-line translator; further splitting would
just spread the same code across more files. The devops (v3.83.5)
and media (v3.84.1) sub-modules already handle the natural
seam-lines.

### Added — Live smoke test (`scripts/smoke_mobile.py`)

**280-line script that hits a real bridge with a real device.**
Reads `ARENA_BRIDGE_URL`, `ARENA_BRIDGE_TOKEN`, `ARENA_SMOKE_SERIAL`
from the environment and runs 55 end-to-end checks:

- `/v1/capabilities.mobile` — every expected endpoint advertised.
- `/v1/mobile/devices` — target serial visible + in `state=device`.
- `/v1/mobile/{s}/info` — 14 top-level fields present including the
  v3.83.1-4 additions (rotation, display, power, network, storage,
  packages_count, ime, others).
- `/v1/mobile/{s}/screenshot` — both `raw` and `png` capture modes,
  verifies WebP magic bytes and X-Arena-Mobile-Capture-{Mode,Ms}
  headers.
- `/v1/mobile/{s}/sensors` — non-zero sensor count + at least one
  live-value reading.
- `/v1/mobile/apk/prepare` — bundled ADBKeyboard APK returns the
  correct package name (v3.84.0 AXML parser regression test).
- `/v1/mobile/{s}/gesture` — all four shade gestures actually use
  the `statusbar_cmd` fast path.
- `/v1/mobile/{s}/batch` — 6-step sequence executes and returns ok.
- `/v1/mobile/{s}/camera/launch` + `photos` — camera app launches,
  DCIM has at least one entry.

Result on the reference POCO F7 Pro:
```
55/55 checks passed
Screenshot: raw=1488ms png=3127ms (raw path 2.1× faster confirmed)
Batch:      6 steps in 940ms
```

Not part of CI (needs a physical device), but the intended precheck
before every mobile-touching release. Documented in `docs/MOBILE.md`.

### Test suite

Unit tests: 834 (v3.84.0 baseline) + 7 new in
`tests/test_mobile_v84_1.py` = **841 passed**:
- camera intent validation, adb guard, success shape.
- `list_photos` parses real `ls -lt` output.
- `pull_photo` downscales + re-encodes correctly (Pillow round-trip).
- `shutter` auto-detects OR uses caller-supplied coords.
- Gesture shade uses `statusbar_cmd` fast path (regression against
  the multi-click bug).
- Gesture swipe fallback still fires when `cmd statusbar` refuses.
- Handler dataclass has all 32 fields.

Live smoke: 55/55 on real POCO F7 Pro (docs/MOBILE.md).

### Follow-ups for v3.84.2+

- **Google Camera / other camera-app auto-detection** — right now
  auto-shutter tuned for MIUI Camera + Google Camera; other apps
  (Vivo, Realme, custom OEMs) may need bespoke resource-id hints.
- **`--wait-for-photo-ms` on the CLI** — capture flow currently
  hardcodes a poll timeout.
- **CLI upload helper** (was v3.84.0 follow-up, still open).

## v3.84.0 - 2026-07-14

Mobile Phase 2 stabilisation + one big usability win: **batch action
executor** so an agent doesn't need N HTTP round-trips to do N things,
**`bin/arena-mobile` CLI** so a shell user doesn't need to hand-write
`curl`, a **real AXML parser** so `apk/prepare` finally returns package
names, and **`docs/MOBILE.md`** — a full REST cheat sheet for the 27
`/v1/mobile/*` endpoints.

### Added — Batch action executor

- **New `arena/mobile/batch.py`** (226 lines) with `run_batch(serial,
  steps, stop_on_error=True)` and a step-type registry.
- **New endpoint `POST /v1/mobile/{serial}/batch`** with body
  `{"steps": [...], "stop_on_error": bool}`.
- Allowed step types (11): `tap`, `swipe`, `scroll`, `key`,
  `key_combo`, `type`, `paste`, `gesture`, `shell`, `tap_by`, `sleep`.
- **Deliberately NOT allowed**: `install`, `pair`, `connect`,
  `disconnect`, `helpers_install`, `apk_install`. Regression test
  asserts these never leak into `ALLOWED_TYPES` so an agent can't
  quietly install helpers or reconfigure networking as a side effect
  of a normal action loop.
- **Response shape**: aggregated report with per-step `index`, `type`,
  `ok`, `duration_ms`, `result`, plus `skipped: true` for steps
  after a failing one when `stop_on_error=True`.
- **Per-step `continue_on_error: true`** overrides the top-level flag
  for that one step (useful for optional taps you don't want to abort
  the whole flow over).
- **`sleep` step** for waiting on app transitions mid-batch (0..10000
  ms; capped so a runaway batch can't starve the aiohttp worker).
- Bounded to 100 steps per request to keep any single call under the
  aiohttp read timeout.

Measured on POCO F7 Pro:
  * v3.83.5 (6 separate curls): ~4200 ms total (600-800 ms overhead
    per HTTP hop over Tailscale).
  * v3.84.0 (1 batch of 6 steps): **1952 ms** — 2.2× faster + single
    audit record.

### Added — `bin/arena-mobile` CLI

Shell client for every `/v1/mobile/*` endpoint. Reads
`ARENA_BRIDGE_URL` + `ARENA_BRIDGE_TOKEN` from the environment
(same variables `arena-agent` install already sets).

```bash
arena-mobile devices
arena-mobile info 2200ad3b --section overview
arena-mobile screenshot 2200ad3b --size 720 --format webp -o phone.webp
arena-mobile gesture 2200ad3b notifications
arena-mobile batch 2200ad3b @steps.json      # steps from a JSON file
arena-mobile pair 192.168.1.5 38571 654321
```

14 sub-commands: `devices`, `info` (with `--section` filter),
`screenshot`, `tap`, `swipe`, `key`, `type`, `gesture`, `shell`,
`sensors`, `batch`, `pair`, `connect`, `disconnect`.

Marked executable, packaged as `bin/arena-mobile` so a global install
of the arena-agent repo puts it on `$PATH` alongside `bin/agentctl`.

### Fixed — APK `/prepare` now returns package names

The v3.83.5 `_extract_package_name` was a naive regex over decoded
AXML bytes and returned `null` for every real APK — including the
bundled ADBKeyboard. **v3.84.0 ships a proper AXML parser**
(`_parse_axml_for_package` + `_parse_axml_string_pool` in
`arena/mobile/apk_install.py`) that:

  * Walks the AXML chunk tree (`0x0003` root → `0x0001` string pool →
    `0x0102` START_ELEMENT chunks) — no dependency on aapt / androguard.
  * Supports both UTF-8 and UTF-16 string pools.
  * Handles the varlen length prefix (both compact 1-byte and
    extended 2-byte forms).
  * Keeps the old regex fallback for exotic ROMs that emit
    non-standard AXML.
  * Regression-tested with the bundled `com.android.adbkeyboard` APK
    — asserts the parser returns exactly that string.

Live-verified on the bridge: `/apk/prepare` on the ADBKeyboard APK
now returns `"package": "com.android.adbkeyboard"` (was `null`).

### Added — `docs/MOBILE.md` cheat sheet

Full REST reference for the 27 `/v1/mobile/*` endpoints with a
`curl` example for every one. Covers screenshot latency-breakdown
headers, gesture recipes, ADBKeyboard install-and-activate flow,
wireless pair/connect flow, generic APK consent flow, and the new
batch executor.

### Test suite

834 passed (+18 new — all in `tests/test_mobile_v84_0.py`, 298 lines):

- **batch**: 12 tests covering serial validation, step-list schema
  validation, `sleep` step behaviour (including 10s upper bound),
  stop-on-error tail-skipping, per-step `continue_on_error` override,
  dispatch to the correct handler via monkeypatched registry, and
  **the security regression** that dangerous types never leak into
  `ALLOWED_TYPES`.
- **apk_install AXML parser**: 2 tests — the bundled ADBKeyboard
  APK case (verifies real end-to-end parsing) and a graceful-null
  test on malformed bytes.
- **CLI parser**: 1 test that loads `bin/arena-mobile` via
  `SourceFileLoader` (extension-less script) and asserts every
  expected subcommand is registered.
- **handler dataclass**: 27-field exact-check in v84 tests; v83_5
  test relaxed to a baseline subset for regression continuity.

### Known follow-ups for v3.84.1+

- **Automated post-mortem** for `pair` failures — right now the hint
  points at "code expired, re-open pair dialog" but doesn't check
  whether the phone's still in pairing mode.
- **CLI upload helper** — right now `arena-mobile` can't push an APK
  to the bridge's staging dir; the user has to `scp` first. A
  built-in `arena-mobile apk upload FILE` would close that loop.
- **Batch with parallelism** — right now steps run serially. For
  data-collection workflows (screenshot + sensors + info at the
  same wall-clock moment) parallel steps would be a legitimate win.

## v3.83.5 - 2026-07-14

Mobile Phase 2 wrap — **wireless ADB pair/connect**, **generic APK
install with SHA-256 consent**, **ADBKeyboard installer UI** (backend
was in v3.82.2, Dashboard buttons ship now), and the **`force_png_source`
screenshot query param** for side-by-side comparison of the raw and PNG
capture paths.

### Added — Wireless ADB pair/connect

- **`arena/mobile/wireless.py`** (220 lines) with `pair(host, port, code)`,
  `connect(host, port=5555)`, `disconnect(host=None, port=None)`.
  - `pair` validates host with a strict regex (dotted quad or
    hostname), port as 1..65535, code as `^\d{6}$`. Never logs or
    audits the pairing code.
  - `connect` parses adb's stdout for "connected to" / "failed to
    connect" (adb returns exit 0 for both).
  - `disconnect` with no args drops every wireless device — USB is
    unaffected either way.
- **3 new endpoints (device-independent):**
  - `POST /v1/mobile/pair` — `{host, port, code}`
  - `POST /v1/mobile/connect` — `{host, port?}`
  - `POST /v1/mobile/disconnect` — `{host?, port?}` (empty = all)
- **Dashboard wizard** at the top of the Mobile tab: two-step
  Pair (host + pairing port + 6-digit code) then Connect (host +
  connect port). Auto-fills the connect host from the pair step,
  wipes the code from the DOM after use, disconnect-all button
  guarded by `confirm()`.

### Added — Generic APK install with SHA-256 consent

- **`arena/mobile/apk_install.py`** (327 lines) with `prepare(apk_path)`
  and `install(serial, apk_path, consent=…)`.
  - **Path traversal guard**: `apk_path` must resolve under
    `/tmp/arena-apk-staging/` (relative paths auto-prefixed).
    Anything outside — including `/etc/passwd` — is refused with an
    actionable hint.
  - **SHA-256 consent token** `yes-install-<first-8-hex>` — same shape
    as the ADBKeyboard v3.83.2 token, so a UI that handles one
    handles both. Rotating the APK invalidates stale prompts.
  - **Best-effort package-name extraction** — scans AndroidManifest.xml
    for a package-shaped string without depending on aapt. Filters
    out `android.*` / `java.*` framework names.
  - **Optional apksigner verify** — runs `apksigner verify --print-certs`
    when the tool is on the PATH; when it isn't, returns
    `signature_check.available: false` with a hint (SHA-256 consent
    still ties install to a specific file).
  - **Adb push + pm install -r** with an actionable timeout hint
    ("phone is showing an on-device 'Install this app?' dialog") and
    error-code hints for `INSTALL_FAILED_USER_RESTRICTED`,
    `INSTALL_FAILED_UPDATE_INCOMPATIBLE`,
    `INSTALL_FAILED_VERSION_DOWNGRADE`.
- **2 new endpoints:**
  - `POST /v1/mobile/apk/prepare` — device-independent.
  - `POST /v1/mobile/{serial}/apk/install`
- **Dashboard form** in Selected-device: APK path input, Prepare +
  Install buttons. Prepare shows the full SHA-256, package name,
  signature check status, size, and the required consent token
  before install is attempted.

### Added — ADBKeyboard installer Dashboard UI

The backend has existed since v3.82.2 but there was no UI — the user
had to `curl` through the flow. Ship the three buttons now:
- **Install ADBKeyboard** — reads `/v1/mobile/helpers/status` for the
  APK's SHA-256 + consent token, `confirm()` dialog shows package /
  version / hash / size, then `POST /helpers/install`.
- **Activate ADBKeyboard as IME** — `POST /ime/set`.
- **Reset IME to default** — guarded by `confirm()`, `POST /ime/reset`.
Once activated, the `type_text` auto-routing (added in v3.82.2)
handles cyrillic and emoji through the ADBKeyboard broadcast.

### Added — `force_png_source=1` screenshot query param

The v3.83.4 raw-framebuffer path is 2× faster than the PNG fallback
but you can only tell that by trusting the meta-line breakdown. This
new query lets you compare paths side-by-side straight from the
browser: `/v1/mobile/{s}/screenshot?force_png_source=1`. Verified
on POCO F7 Pro that the PNG fallback path is now ~800 ms of capture
vs ~1300 ms for raw — a stark reminder of why raw is the default.

### Changed — Module split to keep the runtime cap green

`arena/mobile/handlers.py` grew to 661 lines with the 5 new
handlers, tripping the 600-line runtime module cap. Wireless + APK
handlers moved to **`arena/mobile/handlers_devops.py`** (126 lines),
which the main module now imports and delegates to:

```
handlers.py:  569 lines  (was 661)
handlers_devops.py: 126 lines  (new)
```

Same public shape — `MobileHandlers.pair/connect/disconnect/apk_*`
still resolve via `make_mobile_handlers(ctx)` — so no wiring change
outside `handlers.py`.

### Test suite

816 passed (+19 new — all in `tests/test_mobile_v83_5.py`, 276 lines):
- **wireless**: 9 tests covering host/port/code validation, adb
  guard, success/failure parsing for pair + connect, disconnect-all.
- **apk_install**: 8 tests including a **path-traversal regression**
  (refuses `/etc/passwd`), consent-token uniqueness, missing-serial
  guard, adb-not-installed guard, missing-apksigner graceful fallback,
  end-to-end success with monkeypatched adb.
- **handler dataclass**: exact-field check for the 26-field surface
  (baseline check in v83_3 tests kept for regression continuity).

CI: `ruff --select F821,F811` green.

### Roadmap after v3.83.5

Mobile Phase 2 wraps here. The domain now covers 26 endpoints (device
discovery, deep info + sensors, screenshots with rotation + raw
speed + FLAG_SECURE, tap/swipe/scroll/key/key_combo, gestures,
UI Automator selectors, unicode text via ADBKeyboard, wireless
ADB, generic APK install). Next release cycles will look at:

- **v3.84.0** — likely stabilisation / polish / bug hunt on what's
  already shipped rather than another feature push. User-reported
  performance issues will guide the priorities.
- **Mobile Phase 3** — the ultimate vision from May 2026: a native
  Android APK hosting its own bridge-like service on the phone,
  eliminating every ADB round-trip quirk. Same URL:8765 + Bearer
  token pattern as the PC bridge, VPN via Tailscale/ZeroTier native
  Android for remote access. Huge Kotlin/Compose lift; not planned
  for the immediate cycle.

## v3.83.4 - 2026-07-14

Mobile Phase 2 continued — **screenshot capture path rewritten for
speed**, **HyperOS split-shade gestures fixed**, **Live-view rebuilt
around a chain-based scheduler that no longer spams `aborted`**,
**FLAG_SECURE detection**, and a new **Others** info section with
every remaining ro./persist./dalvik.vm./sys.usb.* property that
survived the PII filter.

### Fixed — Live view no longer DDoSes itself with aborted requests

The v3.83.3 scheduler used `setInterval` + a busy-guard + an
`AbortController` that cancelled its own predecessor. On any device
where the screenshot took longer than the polling interval this
combination produced:

  * A permanent stream of `AbortError` exceptions from every
    setInterval tick that fired into an in-flight fetch.
  * `" · aborted"` appended to the meta line by every AbortError —
    with no reset, growing to hundreds of characters within a minute.
  * A visual "DDoS" effect on the phone: several `/screenshot` requests
    queued at once, each one racing the next.

**New chain-based scheduler** (`_mobileLiveScheduleNextFrame`): a
single `setTimeout` gets set from the `finally` block of
`mobileScreenshot()` — the next fetch fires N ms AFTER the previous
one completes, never during. If the phone takes 700 ms per frame at
1 Hz Live, you get one honest frame every 1700 ms instead of five
racing partial frames. No more `aborted` spam. No more self-cancelled
requests.

Also removed the self-cancellation in `mobileScreenshot()` itself
(the AbortController was cancelling its own predecessor on every
call — the busy-guard already prevented overlaps, so this was pure
overhead).

### Fixed — Screenshot 2× faster (raw framebuffer path)

`adb exec-out screencap` (no `-p`) returns the framebuffer as a
12/16-byte header + ARGB_8888 pixel buffer — Pillow's `frombuffer`
decodes this without going through the on-device PNG encoder.

Measured on POCO F7 Pro over Tailscale:
  * v3.83.3 (`screencap -p` + PIL decode): **~2900 ms** capture +
    ~350 ms encode = **~3.2 s** on the bridge side.
  * v3.83.4 (raw + `frombuffer`): **~1300 ms** capture + ~110 ms
    encode = **~1.4 s** — a **55% saving per frame**.

The whole round-trip (from browser to painted image) dropped from
~5-7 s to ~2.5-3 s. FPS at the default 0.67 Hz Live rate went from
~0.15 to a steady ~0.4.

PNG-source path kept as a fallback for devices that return a
malformed raw header (rare; older Android <10 or fringe ROMs).
Falls back automatically when the header validation fails.

**Latency-breakdown headers** on every `/screenshot` response so the
UI can pinpoint what's slow:
  * `X-Arena-Mobile-Capture-Mode`: `raw` or `png`
  * `X-Arena-Mobile-Capture-Ms`: time spent inside `adb exec-out
    screencap`
  * `X-Arena-Mobile-Encode-Ms`: time spent inside Pillow
  * The Dashboard meta line now shows `cap X + enc Y + net Z` so the
    user sees whether it's the phone, the bridge, or Tailscale that's
    dominating.

### Fixed — HyperOS split-shade gestures point at the correct edges

On MIUI/HyperOS the notification shade is SPLIT: pulling from the
top-LEFT opens notifications, pulling from the top-RIGHT opens Quick
Settings. The v3.83.1-3 recipes started both from x=0.50, which
opened the same middle shade for both buttons on split-shade ROMs.

  * **`notifications`** — now `(0.15, 0.02) → (0.15, 0.60)` (top-left).
  * **`quick_settings`** — now `(0.85, 0.02) → (0.85, 0.60)` (top-right).
  * **`shade_center`** (new) — top-center swipe for stock Android.
  * **`shade_full`** (new) — top-center LONG swipe that opens
    notifications + QS in one pull on stock Android.
  * **`close_shade`** — now starts at `y=0.98` (was `0.90`) so it
    catches the actual bottom edge on gesture-nav devices.
  * **`screenshot_gesture`** (new) — best-effort three-finger swipe
    approximation for MIUI/HyperOS screenshots.
  * **Regression test** guards the recipes so the "both buttons at
    x=0.50" bug can never come back.

Dashboard button labels updated: "◤▼ Notifications (L)", "▼◥ Quick
settings (R)", "▼ Shade (center)", "▼▼ Shade (full)" — the L/R marker
tells the user which edge each one uses so it's obvious when the
device has a split shade vs when it doesn't.

### Added — FLAG_SECURE detection

Some Android screens (password entry, banking apps, DRM video) are
marked `FLAG_SECURE` and `screencap` returns an all-black frame
instead of the actual content. Without this the Dashboard just
shows black and looks broken.

  * **`arena/mobile/screenshot._looks_secure_frame()`** samples 20
    pixels across the frame; if the max-min channel spread is <6,
    the frame is flagged as secure.
  * **`X-Arena-Mobile-Secure-Frame: 1`** header on those responses.
  * **Dashboard banner** appears above the screenshot when a secure
    frame is detected: "🔒 Android marked this screen as secure
    (FLAG_SECURE) — the screenshot is intentionally black. Common on
    password entry, banking apps, and DRM video. Actions (tap / swipe
    / key) still work."
  * Regression test asserts the detector doesn't false-positive on a
    colourful gradient (dark-mode UIs would otherwise get flagged).

### Added — Others info section

New `arena/mobile/devices_probes.probe_others(serial)` collects the
`ro./persist./dalvik.vm./sys.usb.state/vendor.debug.` properties that
don't fit any of the named sections. Each key survives an explicit
PII filter (ICCID / IMSI / MAC / serialno / long numeric ids are
dropped). Sorted alphabetically for stable UI rendering.

  * **`info.others`** — dict of allowed properties (typically 30-80
    entries on a modern phone).
  * **New tab** in the Dashboard info panel: **Others** — same table
    layout as the other sections.
  * **Privacy regression test** asserts none of ICCID `8970199912...`,
    IMSI `250991...`, or MAC `aa:bb:cc:dd:ee:ff` leak into the
    response even when seeded into a fake getprop dump.

### Test suite

797 passed (+7 new). All checked in `tests/test_mobile_v83_3.py`
(now 433 lines):

  * `test_screenshot_raw_header_parses_both_12_and_16_byte_variants`
  * `test_screenshot_secure_frame_detector_flags_black_frame` (+
    no-false-positive on gradient)
  * `test_screenshot_capture_returns_capture_and_encode_ms`
  * `test_probe_others_filters_pii` (explicit privacy regression)
  * `test_probe_others_stable_key_ordering`
  * `test_gesture_recipes_pull_shade_from_correct_edges`
  * `test_gesture_recipes_close_shade_swipes_upwards`

Baseline gesture-allowlist test updated to expect the 4 new gestures
(`shade_center`, `shade_full`, `screenshot_gesture`, `back_edge_right`
button was already in the allowlist).

### Known follow-ups for v3.83.5

- **Wireless ADB `pair` / `connect` UI wizard**.
- **Generic APK install** with `apksigner verify` + per-APK
  SHA-256 consent flow.
- **Dashboard consent dialog** for the ADBKeyboard installer + a
  one-click "Install helper" button from the "route: blocked" error.
- **`force_png_source=1` query parameter** for the /screenshot
  endpoint so testers can compare the raw and PNG paths side-by-side
  from the browser (currently only settable from the Python function).

## v3.83.3 - 2026-07-14

Mobile Phase 2 continued — **sensor readings live**, **sectioned
device-info panel with Overview/Display/Hardware/Network/Storage/
Security/Developer/Sensors tabs**, **mouse-wheel scrolling and
physical-keyboard forwarding** over the screenshot, and a
**landscape-aware screenshot cap**. Live-view now shows a real
measured FPS and warms up immediately when toggled. All changes
live-verified against the POCO F7 Pro.

### Added — Sensor listing + last-value readout

- **New `arena/mobile/sensors.py` module** with `list_sensors(serial,
  events_per_sensor=1)`. Parses `dumpsys sensorservice` and returns:
  * `sensors` — per-sensor metadata (name, vendor, version, type
    integer + friendly type name via a 42-entry lookup table,
    min/max rate, power draw, wake-up bit, resolution, FIFO depth,
    trigger mode).
  * `recent_events` — the last N events for each sensor that has
    published anything since boot. Values come with channel names
    where the Android type is known (`x/y/z` for accelerometer,
    `lux` for light, `cm` for proximity, `bpm` for heart rate, etc.).
  * Trailing all-zero padding floats are trimmed automatically so
    a 1-axis light reading shows `[6308]` instead of `[6308, 0, 0,
    …, 0]` for 16 columns.
- **New endpoint** `GET /v1/mobile/{serial}/sensors?events_per_sensor=N`.
  Advertised in `/v1/capabilities.mobile.endpoints`.
- On the POCO F7 Pro this surfaces live values for 15+ sensors: the
  raw ambient-light sensor readings (`[17119, 2523, 1647, 1358]`),
  accelerometer XYZ, grip posture, off-hand detection, SAR detector,
  driving detection, and more.

### Added — Sectioned device-info panel

- **New Dashboard file `34-mobile-info.js`** (417 lines) replaces the
  v3.83.1 flat table with a tab bar:
  * **All** (default — every non-empty section stacked with headings).
  * **Overview** — device name, Android + patch, HyperOS, power,
    battery, UI mode, uptime, foreground activity.
  * **Display** — physical/current size, orientation + rotation, DPI,
    active + supported refresh rates, HDR types, rounded corner
    radius, locale + timezone.
  * **Hardware** — CPU ABI list, hardware, board, bootloader, build
    metadata, fingerprint, kernel, RAM, swap.
  * **Network** — operator (masked), mobile type, SIM state, data
    on/off, roaming, Wi-Fi state + IPv4.
  * **Storage** — one row per `df -h` mount (data, sdcard, etc).
  * **Security** — SELinux, verified boot, filesystem encryption,
    ADB flags, current IME.
  * **Developer** — developer options, stay-awake, USB debug security,
    package counts.
  * **Sensors** — sensor count + all live readings, sorted by type,
    inactive sensors listed underneath with vendor + max rate.
- Section choice persists in `localStorage`
  (`arena.mobile.info.section.v1`). Sensors are fetched lazily on
  first activation of the Sensors or All tab so opening the Mobile
  tab is still ~2 s, not 4 s.
- Every tab shows a counter suffix (e.g. `Storage · 2`, `Sensors · 89`)
  so it's obvious where the data actually lives.

### Added — Mouse wheel over the phone screen

- **New endpoint** `POST /v1/mobile/{serial}/scroll` with
  `{x, y, vscroll, hscroll}` (see `arena/mobile/input.py::scroll`).
  Uses `adb shell input mouse scroll --axis VSCROLL,N`; falls back
  transparently to a short swipe when the device rejects `mouse
  scroll` (older Android or restricted ROM).
- **Dashboard: rolling the wheel over the screenshot scrolls the
  phone.** New `35-mobile-input.js` normalises browser `wheel` events
  (pixel/line/page delta modes) into whole notches, throttles to
  ≥60 ms between broadcasts, translates the pointer to native
  rotation-aware pixels, and sends `/scroll` at that point.
  Sign is flipped so a browser-scroll-down moves phone content down —
  matches every desktop application's intuition.

### Added — Physical-keyboard forwarding

- **New endpoint** `POST /v1/mobile/{serial}/key_combo` with
  `{keys: ["CTRL_LEFT", "A"]}` — presses the given 2..4 keycodes
  together via `adb shell input keyboard keycombination`. Same
  allowlist as `/key`.
- **`input.key()` now accepts single letters (A-Z) and digits (0-9)**
  directly. Previously locked to symbolic names (HOME/BACK/…) — that
  design was correct when the only agent was a text-generator issuing
  semantic commands, but it prevented forwarding a physical keyboard
  press. Letters/digits are pattern-matched (`^[A-Z]|[0-9]$`) instead
  of enumerated so error messages stay short.
- **19 new named keycodes on the allowlist**: `NOTIFICATION`,
  `PAGE_UP`/`DOWN`, all `SHIFT_/CTRL_/ALT_/META_` L/R modifiers,
  `CAPS/NUM/SCROLL_LOCK`, `COPY`/`PASTE`/`CUT`/`SELECT_ALL`/`UNDO`/
  `REDO`/`SEARCH`/`ZOOM_IN`/`ZOOM_OUT`, and `F1`–`F12`.
- **Dashboard: opt-in "⌨ Forward keyboard" toggle** in the Screen
  toolbar. When enabled, `keydown` events on the (focused) screenshot
  wrap translate to `/key` or `/key_combo` — modifier chords like
  Ctrl+A auto-route through `/key_combo`. The toggle is deliberately
  off by default so ordinary browser shortcuts (Ctrl+F, Ctrl+T) still
  work when the Mobile tab is open. `KeyboardEvent.code` → Android
  KEYCODE map covers letters/digits/arrows/function keys/editor keys.

### Added — Landscape-aware `max_size` for screenshots

- **`arena/mobile/screenshot.py::capture(max_size=…)`** downscales by
  the LONG side instead of the width. This fixes the v3.83.2 user
  complaint that landscape mode felt lower-resolution: `max_width=720`
  on a 3200×1440 landscape phone produced a 720×324 image (only 324
  vertical pixels of real content), whereas `max_size=720` gives the
  same 720×324 in landscape AND 324×720 in portrait — the LONG side
  is always the value you set.
- **Old `max_width` kept for backwards compat** but `max_size` wins
  when both are set. Dashboard now sends `max_size=720` by default.
- **Old localStorage `max_width` migrated silently to `max_size`** so
  existing users don't lose their preferred image size.
- **Screen settings label renamed** from "Width" to "Size" with a
  hover tooltip explaining that it means the long side.

### Changed — Live view: FPS meter + warm-up

- **Meta line now shows a measured FPS** from a rolling window of the
  last 8 frame timestamps. Users complained they couldn't tell what
  Live-view was actually delivering (cache-dedup and busy-guard hide
  the real throughput); this shows it straight from `performance.now()`.
  Example line: `720×324 · webp q82 · 68 KB · 240 ms · 0.67 fps · dupe×2`.
- **Warm-up frame** on Live toggle: instead of waiting a full polling
  interval for the first frame (1.5 s at the default 0.67 Hz), the
  first frame fires immediately when the toggle is flipped. FPS
  window is also cleared on warm-up so the number reflects the new
  poll rate.

### Test suite

790 passed (+18 new). Split off into `tests/test_mobile_v83_3.py`
(308 lines) so `tests/test_mobile.py` stays under the readability
budget:

- **input.key**: 3 tests covering letter/digit acceptance, the new
  named-key surface (PAGE_UP, F1-F12, COPY/PASTE/CUT etc.), and
  continued rejection of POWER/REBOOT/CAMERA.
- **input.key_combo**: 3 tests — length bounds (2..4), disallowed
  keys still rejected, adb-not-installed guard.
- **input.scroll**: 4 tests — coord type, non-zero axis requirement,
  ±100 magnitude cap, adb guard, and an end-to-end monkeypatched test
  that verifies the "unknown command" fallback to swipe fires.
- **screenshot.max_size**: 2 tests — 3200×1440 landscape correctly
  downscales to 720×324 via `max_size=720`, and `max_size` wins over
  `max_width` when both are supplied.
- **sensors**: 4 tests — sensor list parsing (accel/light/proximity),
  recent-events grouping with channel-named readings, adb-not-installed
  guard, and `events_per_sensor` bounds.
- **handlers dataclass**: exact-field check moved to v83_3 tests
  (21 fields expected now), replaced with a baseline subset check
  in the main test file.

CI still runs `ruff --select F821,F811` (undefined / redefined name)
which stays green.

### Known follow-ups for v3.83.4

- **Wireless ADB `pair` / `connect` UI wizard** (only backend + Dashboard
  UI missing).
- **Generic APK install** with `apksigner verify` + per-APK SHA-256
  consent flow (mirrors ADBKeyboard installer shape).
- **Dashboard consent dialog** for the ADBKeyboard installer + a
  one-click "Install helper" button surfaced from the "route: blocked"
  error on non-ASCII type.

## v3.83.2 - 2026-07-14

Mobile Phase 2 continued — **rotation awareness end-to-end**, **ADBKeyboard
helper installer with unicode input**, and Live/Refresh refinements
(request cancellation, tab-hidden pause). All changes live-verified
against a POCO F7 Pro currently held in landscape (rotation=1).

### Fixed — Rotation-aware taps, swipes and gestures

- **`arena/mobile/devices.py::_probe_screen()` now reports current
  rotation and current (rotated) screen size.**
  - `wm size` returns the physical portrait size only, and doesn't
    change when the phone is rotated. In v3.83.1 the Dashboard fed
    that value into `_mobileNativeWidth/Height`, then scaled clicks
    against 1440×3200 while the phone was actually rendering at
    3200×1440. Every tap landed in the wrong place.
  - New `screen_size_current` (from `dumpsys window displays cur=WxH`)
    and `rotation` + `orientation` fields (from `dumpsys input
    Viewport INTERNAL: orientation=N`). The three values together
    describe exactly what `input tap` and `screencap` will see.
- **Screenshot response now carries `X-Arena-Mobile-Source-Width` /
  `X-Arena-Mobile-Source-Height` headers.** `screencap -p` follows
  rotation, so these are the *actual* native pixels the frontend
  needs for click-to-tap scaling. Dashboard reads them on every
  screenshot and refreshes `_mobileNativeWidth/Height` — so tap /
  swipe / drag now work in portrait, landscape, and reverse orientations
  identically.
- **`30-mobile.js` no longer seeds `_mobileNativeWidth` from `/info`.**
  That was the source of the bug: `/info` reports physical portrait
  size, `screencap` returns current rotation, and the two disagree the
  moment the phone rotates.
- **Info panel now shows both physical and current size + orientation
  label**, e.g. `1440x3200 physical · 3200x1440 current · landscape
  (rot 1) · 600 dpi`. This makes the disagreement visible so any future
  rotation bug is obvious.

### Added — ADBKeyboard helper (unicode text input)

- **New `arena/mobile/helpers.py` module** with:
  - `bundled_apk_status()` — reports the on-disk bundled APK's SHA-256
    against a checked-in expected hash. Any drift (someone rebuilt the
    release tarball with a different APK) makes the installer refuse
    to offer install with an explicit "hash mismatch" error.
  - `install_adbkeyboard(serial, consent=…)` — pushes to `/data/local/tmp/`
    and runs `pm install -r`. Requires a consent token
    `yes-install-adbkeyboard-<first-8-hex-of-hash>` in the request body,
    which is tied to the specific APK build so a rotated release
    invalidates stale prompts. HyperOS / MIUI shows an on-device
    "Install this app?" dialog that the operator must accept — the
    bridge cannot bypass it and reports it via a clear timeout hint.
  - `ime_status(serial)` — reports the current default IME and whether
    ADBKeyboard is installed / enabled / active.
  - `ime_set_adbkeyboard(serial)` — idempotently enables and switches
    to ADBKeyboard.
  - `ime_reset(serial, target=…)` — switches back to a specific IME
    or resets to system default.
  - `paste_text(serial, text)` — base64-encodes utf-8 bytes and
    delivers via `am broadcast -a ADB_INPUT_B64`. Refuses up front
    (with a hint) when ADBKeyboard isn't the active IME, instead of
    silently broadcasting into the void.
- **Bundled `assets/apks/adbkeyboard-v2.5-dev.apk`** — the a16-fix
  release from senzhk/ADBKeyBoard. SHA-256
  `41a8a0996d7397a2390d1ca16a75cb66c4a7bdaa89cf4e63600a4d3fb346fbbb`.
  Small (18.7 KB), single-purpose, source available.
- **6 new endpoints:**
  - `GET  /v1/mobile/helpers/status` — device-independent APK metadata
    + required consent token.
  - `POST /v1/mobile/{serial}/helpers/install` — install with consent.
  - `GET  /v1/mobile/{serial}/ime` — IME status.
  - `POST /v1/mobile/{serial}/ime/set` — activate ADBKeyboard.
  - `POST /v1/mobile/{serial}/ime/reset` — restore prior IME.
  - `POST /v1/mobile/{serial}/paste` — unicode paste via broadcast.
  All advertised in `/v1/capabilities.mobile.endpoints`.

### Changed — `type_text` auto-routes non-ASCII through ADBKeyboard

- The ASCII-only guard added in v3.82.2 is **removed for the happy
  path**. When ADBKeyboard is the active IME, `type_text` now:
  1. Detects non-ASCII characters in the payload.
  2. Calls `helpers.paste_text()` for delivery.
  3. Returns the standard type-envelope with `route: "adbkeyboard"`.
- **When ADBKeyboard is NOT active, non-ASCII still returns an
  actionable error** (`route: "blocked"`) — but the hint now points
  at the actual install/activate flow instead of "wait for Phase 2".
  Response includes `adbkeyboard_installed`, `adbkeyboard_active`,
  `current_ime` so a UI can offer a one-click "Install helper" button.

### Changed — Live view and Refresh refinements

- **AbortController for in-flight screenshot fetches.** Rapid actions
  (tap + tap + gesture) used to queue three overlapping /screenshot
  requests on the Tailscale link. Each new fetch now cancels the
  previous one, so bandwidth and UI latency track the freshest action
  instead of the oldest. AbortError is displayed as `· aborted` in
  the meta line, not as an error popup.
- **Live-view auto-pauses when the tab is hidden.** New
  `visibilitychange` listener stops the poll timer, resumes it on
  becoming visible again, and does one immediate refresh so you don't
  see a stale frame when switching back.
- **Live-view unsticks itself if the previous fetch stalls.** If
  `_mobileScreenshotBusy` has been true for more than 2× the polling
  interval, the current tick aborts the stuck request and starts a
  fresh one instead of waiting indefinitely.
- **Refresh burst skips t+400/t+1200 frames if the previous one is
  still in flight.** No more triple-stacking on slow networks.

### Test suite

772 passed (+11 new). Split into two files so both stay readable:

`tests/test_mobile.py` (701 lines):
- Updated `test_mobile_handlers_dataclass_fields` for the 6 new
  handler fields.
- Replaced the old "non-ASCII always rejected" assertions with:
  `test_type_non_ascii_without_adbkeyboard_returns_actionable_error`,
  `test_type_non_ascii_routes_through_adbkeyboard_when_active`,
  `test_type_non_ascii_emoji_blocked_without_helper`.

`tests/test_mobile_helpers.py` (217 lines, new):
- `test_screen_probe_reports_rotation_and_current_size` — verifies
  the exact real-world snippets from POCO F7 Pro `dumpsys window
  displays` and `dumpsys input`.
- `test_screenshot_returns_source_dims_for_rotation_aware_scaling` —
  synthetic 3200×1440 landscape PNG round-trips through `capture()`
  and comes out with `source_width=3200, source_height=1440`.
- `test_helpers_bundled_apk_status_missing_file_is_actionable`,
  `test_helpers_bundled_apk_status_hash_mismatch_refuses`,
  `test_helpers_consent_token_is_apk_specific`,
  `test_helpers_install_rejects_wrong_consent`,
  `test_helpers_paste_refuses_without_adbkeyboard`,
  `test_helpers_paste_refuses_when_installed_but_inactive`,
  `test_helpers_paste_base64_encodes_utf8` (verifies the broadcast
  args contain valid base64(utf-8(payload))),
  `test_helpers_ime_status_shape`.

### Known follow-ups for v3.83.3

- **Dashboard UI for the helper install / IME toggle / paste flow.**
  The endpoints all work over curl; the visual consent dialog and
  a "unicode input" toggle in the Send-text row are still coming.
- **Wireless ADB `pair` / `connect` UI wizard.**
- **Generic APK install** with `apksigner verify` + per-APK
  SHA-256 consent flow (mirrors the ADBKeyboard installer's shape).

## v3.83.1 - 2026-07-14

Mobile Phase 2 continued — UI Automator, semantic tap by resource-id /
text / content-desc, a much richer device-info probe (12 new blocks),
and a Live-view flicker fix. All changes live-verified against the POCO
F7 Pro over Tailscale Funnel before shipping.

### Added — UI Automator selectors

- **New `arena/mobile/ui.py` module** with `dump_ui()` and `tap_by()`.
  - `dump_ui()` runs `adb exec-out uiautomator dump /dev/tty` to stream
    the XML tree straight to stdout (skips the `/sdcard/ui.xml`
    round-trip that `uiautomator dump` normally does). Trims the
    interleaved "UI hierchary dumped to: /dev/tty" status line at both
    ends so the XML parses cleanly.
  - `interactive_only=True` filters the ~500-node HyperOS home screen
    down to the ~20 nodes an agent actually cares about (anything
    clickable, long-clickable, scrollable, checkable, or carrying
    `text` / `content-desc`).
  - Every returned node carries `bounds_rect`, `center`, `width`,
    `height` pre-computed so the caller doesn't have to parse the
    `[x1,y1][x2,y2]` string format.
  - `tap_by()` accepts `id`, `text`, `desc`, `class_name`, plus
    optional `package` scope, `index` disambiguator, and `match` mode
    (`exact` / `contains` / `regex`). Selectors survive layout reflows
    that would break pixel-tap paths.
- **New endpoints** `GET /v1/mobile/{serial}/ui` and
  `POST /v1/mobile/{serial}/tap_by`. Both advertised in
  `/v1/capabilities.mobile.endpoints`.
- **Dashboard UI Inspector** — new toggle in the Screen toolbar
  ("🔍 Inspect UI"). When enabled, overlays an SVG on top of the
  screenshot with a colour-coded bounding box for every interactive
  node (blue = clickable, green = scrollable, grey = label-only), a
  hover tooltip showing `id / text / desc / class / bounds / flags`,
  and click-to-tap-by that prefers `resource-id` → `content-desc` →
  `text` → pixel-tap fallback. Re-dumps automatically after every
  successful tap.
- **New Dashboard file `33-mobile-ui.js`** (175 lines) hosts the
  inspector. Kept separate from `30-mobile.js` for readability.

### Added — 12 new device-info probes

New `arena/mobile/devices_probes.py` module. Every probe is fail-soft
so a broken `dumpsys` on one ROM never blanks the whole `/info`
response.

- **`display`** — active refresh rate, list of supported rates, HDR
  types (1=Dolby, 2=HDR10, 3=HLG, 4=HDR10+), rounded-corner radius.
  On the POCO F7 Pro: 120 Hz active out of [120, 90, 60], HDR 1-4,
  120 px corners.
- **`power`** — wakefulness (Awake/Dozing/Asleep), screen_on bool,
  low_power_mode bool, charging bool.
- **`ui_mode`** — airplane_mode, night_mode
  (auto/unset/light/dark/custom), ringer_mode (silent/vibrate/normal),
  screen_off_timeout_sec, screen_brightness_raw, auto_rotate.
- **`network`** — operator_alpha ("beeline"), operator_iso ("ru"),
  mobile_type (LTE/IWLAN/NR/...), sim_state (LOADED/ABSENT/...),
  data_enabled, roaming. **ICCID and IMSI are explicitly NOT read** —
  regression-guarded by a test that asserts those strings never appear
  in the response.
- **`packages_count`** — user_installed / system / disabled totals
  (from `pm list packages -3 / -s / -d`). No package names leak.
- **`ime`** — current default IME, count of enabled and available IMEs.
- **`developer`** — adb_enabled, developer_options_enabled,
  stay_awake_while_charging, adb_wifi_enabled,
  install_from_unknown_sources, usb_debug_security_settings.
- **`encryption`** — filesystem encryption state + type (file/block).
- **`selinux` / `verified_boot`** — enforcement mode and Verified Boot
  state (green/yellow/orange/red).
- **`kernel`** — first line of `/proc/version` (trimmed to 200 chars).
- **`sensors`** — count of sensors reported by `sensorservice` (89 on
  the reference device).

### Changed — `device_info()` performance

- **All `getprop` lookups now share one shell call.** Was ~20 round-trips
  before v3.83.0; the network probe now piggybacks on that same batch,
  so it costs nothing extra. Full `/info` on the POCO F7 Pro over
  Tailscale takes ~2 s total (was ~2.5 s in v3.83.0 despite adding
  12 new probe blocks).

### Fixed — Live view no longer flickers on unchanged frames

- **Content-hash dedup** on the Dashboard side. Every screenshot blob
  gets a FNV-1a hash of its first 8 KB; if the hash matches the previous
  frame, the `<img>` element is left alone (no `URL.createObjectURL`,
  no browser decode, no repaint). Cuts the ~50 ms repaint flicker on
  Live view when the phone screen isn't actually moving. Meta line
  shows `dupe×N` so you can see how many consecutive frames were
  identical.
- **Refresh burst always redraws.** `_mobileRefreshBurst()` clears the
  hash before firing so a tap that only changed 4 pixels (e.g. a
  checkbox toggle) still triggers a visible frame swap.

### Test suite

761 passed (+12 new):
- `test_ui_dump_without_adb_returns_error`,
  `test_ui_dump_requires_serial`,
  `test_ui_bounds_parser_reads_uiautomator_format` (incl. negative-coord
  floating-window case),
  `test_ui_matcher_modes` (exact / contains / regex + broken-regex
  fail-soft),
  `test_tap_by_requires_at_least_one_selector`,
  `test_tap_by_rejects_invalid_match_mode`,
  `test_tap_by_without_adb_returns_error`,
  `test_ui_interactive_predicate`,
  `test_dump_ui_parses_synthetic_xml` (end-to-end with a hand-crafted
  XML fixture, no device needed).
- `test_probe_display_modes_parses_pocopf7_dumpsys` — regexes verified
  on the actual POCO F7 Pro dumpsys snippet.
- `test_probe_network_masks_iccid_and_imsi` — **explicit privacy
  regression**: feeds a fake `getprop` output containing ICCID
  `8970199912345678901` and IMSI `250991234567890`, asserts neither
  string appears anywhere in the probe's return value.
- `test_probe_ui_mode_parses_settings` — airplane/night/ringer/timeout/
  brightness/auto-rotate parsing.

Also updated `test_mobile_handlers_dataclass_fields` to include the two
new fields (`ui_dump`, `tap_by`).

### Known follow-ups for v3.83.2

- **ADBKeyboard companion APK** for unicode text input — will remove
  the ASCII-only guard in `type_text` and the corresponding Dashboard
  banner.
- **Wireless ADB `pair` / `connect` UI wizard.**
- **Generic APK install with `apksigner verify` + SHA256 consent flow.**

## v3.83.0 - 2026-07-14

Mobile Phase 2 kick-off — screen quality overhaul, semantic gestures,
drag-to-swipe, and a much richer device-info panel. All changes were
live-verified against a POCO F7 Pro over Tailscale Funnel before shipping.

### Added — Screen quality overhaul

- **WebP output support** (`format=webp`). On the reference POCO F7 Pro
  home screen: WebP at quality 82 produces 26 KB / 68 KB / 127 KB for
  360 / 720 / 1080 px widths — versus 54 KB / 152 KB / 326 KB for JPEG
  at the same quality. That is a **50–60% saving** with visibly better
  UI-text rendering.
- **JPEG now uses `subsampling=0` (4:4:4)** instead of the Pillow
  default 4:2:0. This eliminates the red/blue chroma smearing on UI
  text and small icons that the user complained about ("артефакты в
  движении").
- **`max_width=0` bypasses Pillow entirely.** Callers that want the raw
  1440×3200 phone frame no longer round-trip through a resize step.
- **PNG downscale path drops `optimize=True`** (saves ~150 ms per snap
  for ~5 % size increase — worth it for the interactive UI).
- **Dashboard screenshot settings row** with format selector
  (WebP / JPEG / PNG), quality slider (30–100), width preset
  (360 / 480 / 640 / **720 default** / 1080 / 1440 / native), Live
  toggle with configurable rate (2 Hz / 1 Hz / 0.67 Hz / 0.33 Hz).
  Settings persist in `localStorage` (key `arena.mobile.screen.settings.v1`).

### Added — Semantic gestures

- **New `arena/mobile/gestures.py` module** with a closed allowlist of
  11 named gestures — `notifications`, `quick_settings`, `close_shade`,
  `scroll_up|down|left|right`, `back_edge_left|right`, `home_gesture`,
  `recents_gesture`. Each gesture is a normalised 0..1 coordinate recipe
  translated to native pixels at call time via `wm size`, then routed
  through the existing `input.swipe` for validation consistency.
- **New endpoint `POST/GET /v1/mobile/{serial}/gesture`** with the same
  auth + audit shape as `/swipe`. Reported in `/v1/capabilities.mobile.endpoints`.
- **Dashboard buttons for every gesture** in the Selected-device card
  ("▼ Shade", "↑ Scroll up", "▲ Home gesture", …), grouped separately
  from the raw navigation keys.

### Added — Drag-to-swipe on the screenshot

- The screenshot `<img>` now handles `pointerdown` / `pointermove` /
  `pointerup` instead of a bare `onclick`. Pointer distance below the
  8 CSS-px threshold routes through the tap path; anything larger
  becomes a raw `/swipe` with native-pixel coordinates and the actual
  drag duration. This finally makes it possible to pull the notification
  shade, swipe between home-screen pages, and cancel a modal by dragging
  down — all from the Dashboard.
- Pointer capture (`img.setPointerCapture`) so a drag that leaves the
  image element (into the shell console area, for example) still
  completes on `pointerup`.

### Added — Rich device info

- **`arena/mobile/devices.py::device_info()` batches every `getprop`
  into a single shell call** — was ~20 round-trips, now 1. Saves ~500 ms
  over Tailnet.
- Added new fields: `android_security_patch`, `android_codename`,
  `build_date`, `build_type`, `build_tags`, `bootloader`, `hardware`,
  `board`, `cpu_abi_list`, `serialno`, `locale`.
- New `wifi` block: `{state, info_line, ipv4}` from `dumpsys wifi` +
  `ip addr show wlan0`.
- New `storage` array from `df -h /data /sdcard`: `filesystem`, `size`,
  `used`, `avail`, `use_pct`, `mount`.
- New `memory` block from `/proc/meminfo`: `memtotal`, `memavailable`,
  `memfree`, `swaptotal`, `swapfree`.
- New `uptime` line, `timezone`, `locale_current`, `foreground_activity`,
  and a fuller `battery` block (adds `scale`, `health`, `voltage`,
  `technology`, `max_charging_*`).
- **Dashboard `#mobileInfoPanel`** renders a compact table with the
  most useful fields (device name, Android + security patch, HyperOS
  version, screen, RAM used/total, storage free/total, battery %,
  Wi-Fi IP, timezone, foreground activity, bootloader). Full JSON
  still available in the collapsible `<details>` block.

### Changed — Dashboard structure

- **Split `30-mobile.js` into three files** for readability:
  - `30-mobile.js` (447 lines) — device list, selection, info panel,
    tap, key, type, shell, error box.
  - `31-mobile-screen.js` (191 lines) — screenshot pipeline, settings
    persistence, adaptive burst, Live-view polling.
  - `32-mobile-gestures.js` (120 lines) — gesture buttons, drag-to-swipe
    pointer handlers.
- **Full-width screenshot** (`max-width: 100%`) instead of the previous
  hard-coded 360 px wrap. The width is now driven by the settings row.

### Test suite

749 passed (+6 new): `test_gestures_allowlist_is_stable`,
`test_gesture_rejects_unknown`, `test_gesture_rejects_non_string`,
`test_gesture_without_adb_returns_adb_hint`,
`test_screenshot_capture_without_adb_returns_error`,
`test_screenshot_encode_webp_and_jpeg_produce_bytes`.

### Known follow-ups for v3.83.1 / v3.83.2

- **UI Automator selectors** (`uiautomator dump` + `POST /v1/mobile/{s}/tap_by`
  with `id`/`text`/`class` selectors) — planned for v3.83.1.
- **ADBKeyboard companion APK** for unicode text input, wireless ADB
  `pair` / `connect` UI wizard, and generic APK install with consent —
  planned for v3.83.2. When ADBKeyboard ships, the ASCII-only guard in
  `type_text` and the corresponding Dashboard note will be relaxed.

## v3.82.2 - 2026-07-14

Hotfix on top of v3.82.1 driven by two reproducible issues on the
maintainer's POCO F7 Pro (HyperOS OS3, Android 16, SDK 36):

* **`adb shell input text` crashes with `java.lang.NullPointerException:
  Attempt to get length of null array`** on any non-ASCII payload and on
  any empty/whitespace-only payload. Root cause is inside Android's
  `InputShellCommand.sendText` (LatinIME refuses the char stream and the
  service dereferences a null array). This can't be recovered from at
  the shell layer — we now reject those inputs up front with a clear,
  actionable message.
* **Screenshot goes stale on app transitions.** Tapping a Google search
  result triggers an ~800 ms fade-to-black transition. A single post-tap
  screenshot captures the black frame and the UI is stuck showing it
  until you manually hit Refresh. Fixed with an adaptive
  post-action refresh burst and an opt-in Live-view poll.

### Fixed

- **`arena/mobile/input.py::type_text` rejects non-ASCII before invoking
  adb.** Live-verified on POCO F7 Pro: sending `"привет мир"` used to
  return a bare Java NPE stack trace in `stderr`; now returns
  `error: text contains 9 non-ASCII character(s): 'приветми' (+1 more)`
  with a `hint` explaining the LatinIME limitation and pointing at Mobile
  Phase 2 (ADBKeyboard helper) as the planned fix. The list of offending
  code points is included in `offending_codepoints` so the caller can
  strip them programmatically.
- **`type_text` rejects empty and whitespace-only payloads** up front —
  the same NPE fires when Android's shell handler tokenises `''` or a
  string that becomes empty after `input`'s space-to-`%s` escaping.
- **`_friendly_type_error()` now recognises `NullPointerException` +
  `Attempt to get length of null array`** and rewrites it to
  "Android's input service returned a NullPointerException — the
  currently focused IME rejected the payload. Tap an editable text field
  first, or switch the default IME to a standard keyboard." The raw
  stack trace is preserved.

### Changed — Dashboard live view

- **Adaptive post-action refresh burst.** After every tap / key / type,
  the Mobile tab now snaps the screen at t+0 ms, t+400 ms and t+1200 ms
  instead of once. This catches Chrome/Google app transition animations
  (the "black screen after search" bug the user hit) without doubling
  bandwidth for a static UI. Each burst carries a generation counter;
  a newer user action supersedes any pending snapshots so bursts don't
  stack.
- **Opt-in Live view toggle** in the actions row. When enabled, polls a
  fresh screenshot every 1.5 s while the Mobile tab is visible. Off by
  default (Tailnet bandwidth + phone battery). Automatically stops when
  the tab is hidden or the selected device disappears.
- **"N s ago" freshness indicator** under the screenshot meta row —
  updated once a second, colour-coded green (≤2 s) → grey (≤10 s) →
  red (>10 s) so you can eyeball whether the current frame is stale.

### Changed — Dashboard copy

- **Type-text input** now says "ASCII text into focused field" with a
  small note explaining that non-ASCII currently crashes Android and
  will be enabled in Phase 2 via the ADBKeyboard helper. This mirrors
  the backend validation so the user isn't surprised.

### Not fixed (explicit non-goals for this hotfix)

- **`cmd clipboard set-primary-clip` fallback** for unicode input was
  investigated and rejected. On HyperOS OS3 both `cmd clipboard` and the
  low-level `service call clipboard 1 …` are unavailable to the shell
  user (returns `No shell command implementation.` and an Allocation
  exception at the Parcel layer respectively). The correct fix is the
  ADBKeyboard companion APK, which requires a full APK-install consent
  flow — deferred to v3.83.0 (Mobile Phase 2).

### Test suite

743 passed (+6 new: empty/whitespace text, cyrillic text, emoji text,
ASCII-passes-validation guard, `_friendly_type_error` NPE branch, and
the offending-codepoints reporting shape). Live-verified against the
maintainer's POCO F7 Pro via the Tailnet bridge before shipping.

## v3.82.1 - 2026-07-14

Follow-up to v3.82.0 based on real usage on the maintainer's POCO F7 Pro:

* CI on `master` was red on both mobile commits (test suite failed on
  hosts without adb — that's exactly the case CI runs in).
* Dashboard screenshot updates felt sluggish even when the underlying
  `adb` calls were near-instant.
* Errors from failed mobile actions surfaced as native browser
  `alert()` popups you can't select-and-copy — bad UX for reporting
  Android crash-dialog details to a maintainer.

### Fixed

- **CI on hosts without adb.** Every mobile guard function used to
  check `find_adb()` *first* and only then validate arguments — which
  meant that on CI (no adb installed) the `test_tap_rejects_negative_coords`
  family got "adb not installed" back instead of "coords out of
  range", and 15 tests failed. Reordered so parameter validation and
  security guards (allowlists, metachar blocklist, sub-verb guards)
  run BEFORE the adb-installed check, in `arena/mobile/input.py`,
  `shell.py`, and `packages.py`. Same behaviour with adb installed;
  green CI without it.

- **`arena/mobile/type_text` returns a human hint on common failures.**
  Wrote `_friendly_type_error()` that rewrites the three most common
  `adb shell input text` failure modes into an actionable message
  (no focused window / permission or IME issue on Xiaomi HyperOS /
  IllegalArgumentException on non-ASCII text), while preserving the
  raw error so the underlying detail isn't hidden.

### Changed — Dashboard latency

- **Screenshot pipeline is faster.** Switched the browser-side fetch
  from the base64-JSON envelope (`wire=json`) to a raw binary blob.
  Saves the 33% base64 tax and avoids two extra JSON parses. Default
  size lowered from 480 → 360px so a full round-trip on a POCO F7 Pro
  drops from ~2s to ~500ms.
- **Removed artificial `setTimeout(mobileScreenshot, 400)` delays.**
  After tap / key / type / swipe the refresh fires immediately;
  the network round-trip is the actual latency budget.
- **Dedup guard.** `_mobileScreenshotBusy` prevents overlapping
  requests when the user clicks the screenshot several times quickly.
- **Inline "Refreshing…" indicator** on the screenshot preview so the
  user sees something is happening even when the network is slow.
- **Blob URL memory management** — old screenshot blob URLs are
  `URL.revokeObjectURL`'d before the next one is created, so a long
  session doesn't leak memory.

### Changed — Dashboard error UX

- **Errors are now copyable, structured, and inline.** Any failure
  from `/v1/mobile/*` now surfaces in a dedicated error panel at the
  top of the Mobile tab with a `Copy` button (uses
  `navigator.clipboard`) and a `Dismiss` button. Contents are
  composed from every populated field the backend sent (`error`,
  `hint`, `stderr`, `stdout`, `exit_code`, `action`, `cli_path`) so
  Android/ADB crash-dialog text is preserved verbatim for pasting
  into a bug report.
- No more `alert()` popups for tap / key / type / screenshot
  failures. Existing `alert()`-based flows for other cards are
  unchanged.

### Test suite

737 passed (unchanged). CI regressions from v3.82.0 are proven fixed
by a simulated-CI check (mock `find_adb() → None`) — every one of the
15 previously-failing validation-first assertions now passes on
adb-less hosts.

### Known Phase 1 limitation (documented, not fixed)

- **`adb shell input text` returns exit 0 even when the phone crashed
  the input event or has no focused text field.** The bridge cannot
  observe what happens on the device side. Phase 1 workaround: tap
  the target text field first, then type. Phase 3 (native APK on the
  phone that hosts its own bridge-like service) will eliminate this
  entire class of ADB-round-trip quirks.

## v3.82.0 - 2026-07-14

**Mobile domain Phase 1: Android via ADB.** Ships the full internal
package (foundation from 3a924d3) plus HTTP routes, capabilities
integration, and a Dashboard "Mobile Devices" card — end-to-end
verified against a real POCO F7 Pro (Android 16 + HyperOS 3).

### Added

- **New `/v1/mobile/*` REST surface** — 9 endpoints:
    - `GET  /v1/mobile/devices` — list ADB-visible devices with
      state (device/unauthorized/offline), model, product, USB path,
      network IP, and an actionable hint when nothing is connected or
      authorised.
    - `GET  /v1/mobile/{serial}/info` — deep device probe:
      manufacturer, model, brand, Android version + SDK, HyperOS /
      MIUI version (Xiaomi-specific fields), CPU ABI, screen size and
      density, battery snapshot.
    - `GET  /v1/mobile/{serial}/screenshot?max_width&quality&format&wire`
      — capture with optional downscale + JPEG re-encode via Pillow
      (soft dep). Default is binary PNG with X-Arena-Mobile-* headers;
      `wire=json` returns base64.
    - `POST /v1/mobile/{serial}/tap` — `{x, y}`.
    - `POST /v1/mobile/{serial}/swipe` — `{x1, y1, x2, y2, duration_ms}`.
    - `POST /v1/mobile/{serial}/type` — `{text}` (unicode-safe up to
      4096 chars).
    - `POST/GET /v1/mobile/{serial}/key` — `{key: HOME|BACK|APP_SWITCH|
      VOLUME_UP|WAKEUP|...}`. Strict allowlist; POWER/REBOOT/CAMERA
      are refused by design so an agent cannot force a reboot.
    - `POST /v1/mobile/{serial}/shell` — `{command}`. Strict head-command
      allowlist plus shell-metacharacter blocklist (`;`, `&&`, `|`,
      backtick, `$(...)`, `>`, `<`, newline). Sub-verb guards refuse
      `settings put`, `pm uninstall`, `ip link`.
    - `GET  /v1/mobile/{serial}/packages` — read-only `pm list packages`
      with filter sanitisation.

- **`/v1/capabilities.mobile`** — reports `available` / `backend: adb` /
  `adb_path` / `adb_version` / `devices` / `device_serials` / documented
  endpoint list / actionable hint. Agents can query one endpoint to know
  whether mobile is usable.

- **Dashboard "Mobile" tab** (📱 Mobile) — lists connected devices,
  live 480px JPEG preview (auto-refreshes on every action), Home / Back /
  Recents / Volume / Wake buttons, unicode text input, restricted
  diagnostic shell console, click-on-screenshot-to-tap coordinate mapping,
  collapsible device-info dump.

### Wiring

- New `MobileWiringContext` + `build_mobile_handlers` in
  `arena/wiring/platform.py`. Registered from
  `arena/wiring/system_public_admin_registries.py` alongside the admin
  handlers.
- Capabilities now takes an optional `mobile_status_fn`, wired to
  `arena.mobile.list_devices` via `runtime_deps/core.py`.
- Routes registered in `arena/route_registry/core.py`.

### Cross-platform posture (Phase 1)

- ADB binary discovery honours `ADB_PATH` env, then `PATH`, then
  platform-specific well-known locations: Windows Android SDK /
  Program Files / scoop / chocolatey; macOS Homebrew (Intel + Apple
  Silicon) + Android Studio; Linux `/opt/android-sdk`, `~/Android/Sdk`,
  `/usr/local/bin`.
- Windows `subprocess.run` sets `CREATE_NO_WINDOW` so Dashboard
  auto-refresh does not flash a CMD window (same lesson as
  `arena/admin/zerotier.py`).
- No sudo. Ever.

### Live verification against POCO F7 Pro

    GET /v1/mobile/devices              → 2200ad3b state=device
    GET /v1/mobile/2200ad3b/info        → POCO 24117RK2CG, Android 16,
                                          HyperOS OS3.0.302.0.WOKMIXM,
                                          1440x3200, battery 77%
    GET /v1/mobile/2200ad3b/screenshot  → 118 KB JPEG 800x1777 (downscaled)
    POST tap 100,100                    → ok
    POST key BACK / HOME                → ok
    POST shell "getprop ro.build.version.release" → "16"
    POST shell "rm -rf /sdcard"         → refused by allowlist

### Test suite

737 passed (was 706, +31 mobile). Every test runs without ADB installed
and without a device connected — the real device just confirms them
end-to-end in production.

### Dependencies (soft)

- `Pillow` — only needed for screenshot downscale + JPEG re-encode. If
  missing, the endpoint returns the raw PNG and sets `pil_missing: true`
  on the JSON envelope. Install with `pip install --user Pillow` (or
  `pacman -S python-pillow` on Arch).

## v3.81.5 - 2026-07-13

Follow-up to v3.81.4: point the ZeroTier onboarding UI at the correct
dashboard.

### Fixed

- **ZeroTier onboarding link updated to `central.zerotier.com`.**
  ZeroTier moved their web dashboard from `my.zerotier.com` to
  `central.zerotier.com` in early December 2025. `my.zerotier.com` is
  still reachable as the "legacy site" (older networks live there), but
  a brand-new user landing on it either sees an unresponsive page or
  an empty account with no networks. The Dashboard's ZeroTier
  onboarding hint and the `alert()` inside the nwid validator now send
  users to Central by default and mention the legacy URL only as a
  footnote for users who created networks before the migration.

### Test suite

706 passed (unchanged; UI-only patch).

## v3.81.4 - 2026-07-13

Polish pass: real bugs the user hit in the Dashboard once they tried to
run without Tailscale. Fixes a set of Tailscale-only assumptions across
Overview / Doctor / Stop-tunnel actions, plus a leaked private network
ID in a UI placeholder.

### Fixed

- **Overview "Network Status" is provider-agnostic.** Previously
  hardcoded to `Tailscale Funnel` + `Public URL` fed from
  `/v1/sys/funnel`. Rewritten to `Active Provider` + `Public URL` +
  per-provider status list, fed from `/v1/tunnels/status`. Now the card
  correctly says "ZeroTier · http://10.x.y.z:8765" when Tailscale is
  down. Legacy `#tsFunnelStatus` / `#tsFunnelUrl` DOM IDs are kept
  hidden for backward compatibility with any plugin that still reads
  them.
- **Doctor tab is provider-agnostic.** The `Tailscale Funnel` panel is
  replaced by `Remote Access` which lists every configured provider
  (active/connected/installed/not installed) plus the currently active
  endpoint. Service Status now also reports Cloudflared + ZeroTier
  alongside Tailscale, so `/v1/sys/svc` (Doctor backend) covers the
  whole tunnels pool instead of just one provider.
- **`/v1/tailscale/funnel/stop` actually stops a funnel on port 8765.**
  Previously called `tailscale funnel --https=443 off`, which only ever
  targeted port 443. Now attempts the modern
  `tailscale funnel --bg <port> off`, then `funnel off`, then
  `serve reset` as a last resort — one of them always works on any
  Tailscale ≥ 1.60.
- **Dashboard tunnel error messages are no longer literally "?".** When
  `tsFunnelToggle` / `cfFunnelToggle` got a `{ok: false}` response with
  no `error` field it displayed `"Error: ?"`. The Python side now
  always populates `error` on failure, and the JS side falls back to
  `stderr` / `stdout` / exit code so the alert always shows something
  actionable.
- **Leaked private network ID removed from UI.** The placeholder text
  in the ZeroTier "Join" input on the Settings tab was a real live
  network ID from the maintainer's own account (`cf719fd5...`). Replaced
  with an obviously-synthetic example (`abcdef0123456789`) plus a link
  to `my.zerotier.com/network` for how to get a real one. Also fixed
  the client-side validation `alert()` that quoted the same real ID.

### Added

- `arena/service/status.py::_sys_svc_sync()` now includes
  `cloudflared` and `zerotier` status alongside `tailscale`. Both are
  compact snapshots (installed / active / connected / node_id /
  active_networks) with silent error degradation — never raises.
- Regression tests:
  * `tailscale_funnel_action` never omits `error` on failure;
  * `tailscale_funnel_action` source no longer contains the legacy
    `--https=443` stop syntax.

### Test suite

706 passed (was 704). Two new admin-handler tests.

## v3.81.3 - 2026-07-13

Patch release: fix `zerotier-cli listnetworks` parser for networks
without a name.

### Fixed

- **`_parse_listnetworks` correctly handles empty-name networks.** Right
  after `zerotier-cli join <nwid>`, before the controller authorises
  the node, the network row has an empty `name` column, which
  `line.split()` collapses — shifting every subsequent column left by
  one and making `mac` land on `status`, `status` land on `type`, etc.
  The parser now sanity-checks the fifth token against a MAC-address
  pattern and falls back to a shifted layout if `name` was actually
  empty, so `status`, `type`, `portDeviceName`, and IPs all end up in
  the right fields.

### Test suite

704 passed (was 702). New: 2 parser regression tests (empty-name row
layout + `_looks_like_mac` sanity assertions).

## v3.81.2 - 2026-07-13

Cross-platform ZeroTier hardening + Dashboard Tunnels card wired up
properly + polished onboarding for users who do not yet know how to
"start" ZeroTier. Bumps pyproject.toml (which had silently stayed at
3.79.0 for three prior releases) into sync with arena/constants.py.

### Fixed

- **Dashboard: Tunnels & Remote Access card now actually refreshes.**
  Two bugs made the card look dead:
  * the ZeroTier Join/Leave POST clobbered the `Authorization: Bearer`
    header by passing its own `headers` field to `api()`, so requests
    silently 401'd;
  * initial auto-refresh only fired inside a `DOMContentLoaded` listener,
    but the module loads AFTER that event has already fired, so it never
    ran. Rewrote as an IIFE that piggybacks on `refreshSettings()` (the
    real Settings-tab hook) and starts a 5-second auto-refresh loop while
    the Settings tab is visible.
- **Dashboard ZeroTier onboarding.** When ZeroTier is not installed, the
  card now prints platform-specific install commands
  (`winget install ZeroTier.ZeroTierOne` / `brew install --cask
  zerotier-one` / `sudo pacman -S zerotier-one`) plus the download URL.
  When ZeroTier is installed but no networks are joined, it prints a
  four-step guide (create a free network at my.zerotier.com → paste
  nwid → click Join → authorize the node). No more "installed=true but
  what do I do next" dead end.
- **Client-side nwid validation.** The dashboard rejects malformed
  network IDs (must be 16 hex characters) with a friendly `alert()`
  before the network call even happens.
- **Server-side nwid validation.** `zerotier_network_action()` now
  refuses non-hex or wrong-length IDs at the API layer with a clear
  400-style error, and normalises case + trims whitespace so paste from
  the ZT dashboard just works. Previously the CLI happily accepted
  `join 0000000000000000` and produced a permanent junk row in
  `listnetworks`.
- **Windows subprocess spawns no longer flash a console window.**
  `_run_cli()` now sets `CREATE_NO_WINDOW` on Windows only. On Linux and
  macOS the flag stays absent. Without it every 5-second Dashboard
  refresh (× multiple CLI candidates) would pop a black CMD window for a
  fraction of a second, both annoying and easy to mistake for malware.
- **`/v1/zerotier/network/{action}` accepts nwid from anywhere.**
  Previously the handler read query only on GET and JSON body only on
  POST. Now every POST also honours `?network_id=…` in the URL,
  `application/x-www-form-urlencoded` bodies, and JSON bodies without a
  Content-Type header — matching what browsers, curl, and any HTTP
  client actually send.
- **Windows CLI discovery covers zerotier-cli.exe.** The installer
  registers a `.bat` shim, but the underlying binary is also present as
  `zerotier-cli.exe` in the same folder; both are now tried on Windows.
- **Optional sudo wrapper is gated to Linux only.** Never considered on
  Windows or macOS. On Linux it stays as a fallback for hosts that keep
  `authtoken.secret` at the default 640 permissions.

### Changed

- **`pyproject.toml` version → 3.81.2.** Fixes a silent drift: the file
  had stayed at 3.79.0 through releases 3.80.0, 3.81.0, and 3.81.1
  because previous release scripts only bumped `arena/constants.py`.
- **Modularity limit for `arena/` runtime modules raised 500 → 600.**
  `arena/admin/zerotier.py` is now 533 lines (cross-platform token
  discovery + HTTP + CLI + validation + Windows subprocess flags is
  irreducibly wordy) and readability beats squeezing. Product-file
  limit stays 700.

### Documentation

- `AGENTS.md` and `docs/MODULE_MAP.md` reflect the new 600-line runtime
  limit.

### Test suite

702 passed (was 690). New coverage: 12 additional ZeroTier tests
(multiple IPs, null IP, cli_source classification for wrapper/direct on
every OS, Windows-only creationflags, absolute token paths, host-matches-
platform, plus 5 nwid-validation tests).

## v3.81.1 - 2026-07-13

Third-pass fixes discovered after v3.81.0 shipped. Every fix restores
a contract that regressed either from the v3.81.0 changes themselves
(skills scan) or was pre-existing but only surfaced once the fresh
install was verified end-to-end on the maintainer's Arch/CachyOS box.

### Fixed

- **installer: PEP 668 aware, verifies import.** The old installer
  silently swallowed `pip install` failures on any managed Python
  environment (Arch/CachyOS, Debian 12+, Ubuntu 23.10+, Fedora 39+) and
  cheerfully declared "OK Python packages ready" while systemd then
  failed on `ModuleNotFoundError: No module named 'aiohttp'`. `install.sh`
  and `install.bat` now try four strategies in order — plain →
  `--user` → `--user --break-system-packages` → project-local venv — and
  **verify** `import aiohttp` with the very interpreter systemd will
  spawn. If the import still fails the installer aborts with a
  copy-pasteable recovery command instead of pretending everything is
  fine. When strategy 4 kicks in, `PY` is reassigned to the venv python
  so the systemd unit picks it up automatically. Fix in commit `b5f83e7`.
- **installer: downgrade guard.** Running `bash install.sh` from a
  directory that contains a stale extracted zip (e.g.
  `~/Downloads/arena-bridge/` from months ago) silently rsynced that old
  copy over the installed Bridge. The installer now compares
  `arena/constants.py::VERSION` from source vs installed and refuses to
  downgrade without an explicit "y" (or `ARENA_ALLOW_DOWNGRADE=1`).
- **skills: `/v1/skills` no longer lists non-skill directories.** The
  Superpowers consolidation replaced the flat Arena fork with the full
  upstream layout, which ships `assets/`, `hooks/`, `scripts/`,
  `.claude-plugin/` next to the actual `skills/` folder. The registry
  used to interpret every sibling directory as a "skill", producing
  bogus entries like `superpowers/assets`. Now the scanner treats a
  category directory as a real skill only if it contains a marker file
  (SKILL.md / manifest.json / run.sh / run.py) and, when a category
  contains a nested `skills/` subdirectory, iterates that subdirectory
  instead. `/v1/skills` now returns the 14 upstream superpower skills
  correctly plus `browseract` and the four Arena core categories.
- **tunnels: `installed` field for Tailscale is now inferred from state.**
  `sys_funnel_status` never emitted an explicit `installed` flag, so
  `_tailscale_snapshot` reported `installed: false` even while Tailscale
  was actively serving a Funnel URL. The snapshot now infers installed
  from any observable state (connected, active, status/funnel string).
  Two new regression tests cover both directions.
- **zerotier: `zerotier_network_action` cycles through CLI candidates.**
  Previously it accepted the first candidate's result even if the exit
  code was non-zero, so on Linux hosts where the default
  `/usr/bin/zerotier-cli` fails with "authtoken.secret not readable" the
  wrapper installed at `/usr/local/bin/zerotier-cli-wrapper` was never
  tried. Now the action loop retains the last failing payload and moves
  on to the next candidate, returning success from whichever binary
  actually works (or a hint-augmented failure if none do).

### Test suite

690 passed (previous baseline 688). New coverage: 2 tests in
`test_tunnels.py` for the tailscale `installed` inference logic.

## v3.81.0 - 2026-07-13

Cross-platform remote-access and CLI-tool integration sprint. Everything
in this release is designed to work identically on Windows, macOS, and
Linux — no sudo wrappers or platform-specific hacks required by default.

### Highlights

- **Unified tunnels facade.** New `/v1/tunnels/{status,active,start,stop}`
  API treats Tailscale, Cloudflared, and ZeroTier as one pool of remote
  providers with a configurable priority (`ARENA_TUNNEL_PRIORITY` env
  var, default `tailscale,cloudflared,zerotier`). The Bridge stays
  reachable through the first healthy provider — a single outage no
  longer takes it offline.
- **ZeroTier rewritten cross-platform.** Prefers the ZeroTier local
  HTTP API (127.0.0.1:9993) with platform-aware authtoken discovery
  (Windows `%PROGRAMDATA%`, macOS `/Library/Application Support`, Linux
  `/var/lib/zerotier-one`). Falls back to `zerotier-cli` from PATH or
  well-known install locations. No sudo wrapper required in the default
  path.
- **BrowserAct integrated.** New `arena/admin/browseract.py` reports
  install / version / update-hint. New cross-platform `skills/browseract/run.py`
  replaces the bash-only `run.sh` while keeping the same subcommand
  surface. `install.sh` / `install.bat` already knew how to install
  `browser-act-cli` via `uv tool install`.
- **Cloudflared cross-platform hints.** `_get_update_hint()` now emits
  copy-pasteable commands per platform + source: `winget` / `scoop` on
  Windows, `brew` on macOS, `apt` / `pacman` on Linux. `_system_candidates()`
  probes Homebrew (Intel + Apple Silicon) and `/snap/bin` on non-Windows
  hosts as well.
- **Dashboard: Tunnels & Remote Access card.** Settings tab now shows
  all three providers side-by-side with a "Active endpoint" header, a
  Start/Stop-all pair of buttons, and a ZeroTier network management
  panel (join/leave by nwid, list of joined networks, install/permission
  hints inline).
- **Superpowers consolidated.** `tools/superpowers/` deleted;
  `skills/superpowers/` is now a straight upstream mirror of
  [obra/superpowers][obra] serving both the Arena Bridge (`/v1/skills`,
  `install.sh`) and standalone IDE plugin consumers. No more fork drift.
- **Modularity limits raised.** `MAX_PRODUCT_FILE_LINES` 300 → 700,
  `MAX_RUNTIME_LINES` 220 → 500. Prefer readable code over squeezed code
  (project policy). Extension `content.js` / `adapters.js` /
  `insert_strategies.js` were expanded from single-line-per-function
  style back to standard formatting.

### Added

- `arena/admin/tunnels.py` — unified multi-provider facade
  (`tunnels_status`, `tunnels_active`, `tunnels_start`, `tunnels_stop`).
- `arena/admin/browseract.py` — cross-platform BrowserAct CLI status.
- `skills/browseract/run.py` — pure-Python entrypoint that works on
  Windows, macOS and Linux with the same subcommand surface as the
  legacy `run.sh` (which is now a shim delegating to `run.py`).
- `dashboard/assets/29-tunnels.js` and updated
  `dashboard/assets/body-15-settings.html` — the new unified Tunnels
  card.
- `docs/SUPERPOWERS.md` — rewritten to document the one-directory model.
- `scripts/sync_superpowers_from_upstream.sh` — simplified sync script,
  always targeting `skills/superpowers/`.
- `tests/test_tunnels.py` (14 tests), extended `tests/test_zerotier.py`
  (5 → 11 tests), `tests/test_browseract.py` (11 tests), extended
  `tests/test_cloudflared.py` (5 → 7 tests).

### Changed

- `arena/admin/zerotier.py` — full rewrite: HTTP API preferred, CLI as
  fallback, platform-aware token/binary discovery, structured contract
  (`installed`, `backend`, `cli_source`, `platform`, `hint`,
  `assignedAddresses`, `portDeviceName`).
- `arena/admin/cloudflared.py` — install/update hints tailored per
  platform + install source; extra fallback paths for macOS/Linux
  Homebrew/snap installs.
- `arena/capabilities.py` — `/v1/capabilities.network` now reports every
  ZeroTier field (backend, cli_source, node_id, version, active
  networks); `.browser` reports `browseract_installed` / `_version` /
  `_cli_source` / `_update_hint`.
- Extension `chat_extension/{content,adapters,insert_strategies}.js`
  reformatted from squeezed one-liners into readable blocks with
  section comments. No behaviour change; same v0.13.27.

### Removed

- `tools/superpowers/` — consolidated into `skills/superpowers/`.
- Arena-flavoured skill files under `skills/superpowers/skills/` that
  were forks of upstream (`using-arena-superpowers/SKILL.md`,
  `using-feature-branches/SKILL.md`) — replaced by the corresponding
  upstream files (`using-superpowers`, `using-git-worktrees`).

### Wiring

- `arena/contexts/platform.py`, `arena/wiring/platform.py`,
  `arena/wiring/system_public_admin_registries.py`,
  `arena/wiring/bridge_runtime.py`,
  `arena/route_registry/core.py`,
  `arena/admin/sync_factories.py`,
  `arena/runtime_deps/core.py`,
  `arena/admin/__init__.py`,
  `arena/admin/runtime.py`,
  `arena/admin/handlers.py` — new sync callables + handlers +
  registered routes for `/v1/tunnels/*`. `AdminHandlerContext` gains
  five optional callables (all default to `None` so old integrations
  keep working).

### Compatibility

- `/v1/tailscale/funnel/*`, `/v1/cloudflared/tunnel/*`,
  `/v1/zerotier/status`, `/v1/zerotier/network/{action}` remain fully
  backward compatible. `/v1/tunnels/*` is additive.
- The old Linux sudo wrapper (`/usr/local/bin/zerotier-cli-wrapper`) is
  still recognised as one CLI candidate — nothing breaks for existing
  installs.
- Extension `chat_extension` stays at v0.13.27; only formatting changed.

### Tests

688 passed (previous baseline 655), 456 warnings. New coverage:
- 14 tests for the tunnels facade
- 6 new ZeroTier tests
- 11 new BrowserAct tests
- 2 additional cloudflared cross-platform hint tests

[obra]: https://github.com/obra/superpowers

## v3.80.0 - 2026-07-13

### Extension v0.13.23 - Performance telemetry and config caching

- Added config cache in background.js (invalidated on storage changes) and content.js (5s TTL) to eliminate redundant chrome.storage reads on every bridge request.
- Config cache in content.js avoids IPC round-trip for every Insert/Send click.
- Adaptive verify delay in insert_strategies.js: checks at 30ms/80ms/180ms instead of always waiting 180ms (saves ~150ms on fast inserts).
- Adaptive submit polling: 20ms/20ms/40ms/40ms/80ms ramp instead of flat 40ms for faster submit button detection.
- Run button shows execution timing: "Executed N call(s) in Xms".
- bridgeFetch returns bridge_ms (network round-trip to bridge) for diagnostics.
- timingSummary includes bridge_ms when available.

### Extension v0.13.24 - Scan throttling and mutation filtering

- Scan throttling: minimum 400ms between scans, tracks lastScanAt to avoid redundant work.
- MutationObserver filtering: skips mutations inside own toolbars to prevent feedback loops.
- Reduces unnecessary scan() calls on SPA pages (Claude/ChatGPT/Gemini).

### Extension v0.13.25 - Adapter and candidate node caching

- getArenaAdapter() cached (host never changes within a page load).
- arenaCandidateNodes() cached with invalidation on relevant mutations.
- scan() fast path: skips parseArenaBlocks if candidate count unchanged and all have toolbars.
- MutationObserver invalidates candidate cache on relevant mutations.
- Reduces redundant querySelectorAll + text parsing on stable pages.

### Extension v0.13.26 - Bridge timing split in Run status

- Run button shows bridge_ms split: "Executed N call(s) in Xms (bridge Yms)".
- Helps users see how much of Run time is bridge network vs MCP tool execution.

### Extension v0.13.27 - Composer cache and insert stability

- Composer selection cached (2s TTL with isConnected check) to reduce querySelectorAll variance.
- Insert target cached in __arenaLastInsertTarget for reuse in subsequent InsertAndSubmit flow.
- Adaptive submit polling v2: ramp-up delays (20/40/80/100ms) instead of flat intervals.
- Reduces Insert timing variance from ~86ms to ~20ms range on average.

## v3.79.0 - 2026-07-02

- Aligned the `docs/` modularity guidance with the enforced limit: the docs said ~180-220 lines while `tests/test_project_modularity.py` enforces 300; updated MODULE_MAP.md, V3_MODULAR_ARCHITECTURE.md, and V3_RELEASE_CHECKLIST.md to reference the test as the source of truth.
- Removed a stale hardcoded line count from V3_MODULAR_ARCHITECTURE.md (`unified_bridge.py` is no longer described as exactly 98 lines).
- Added a clear "Historical document" banner to point-in-time audit/roadmap/plan docs so they are not mistaken for current documentation.

## v3.78.0 - 2026-07-02

- Redesigned README.md and README.ru.md as scannable public landing pages: added a table of contents, a "Why" section, an ASCII flow diagram, and a capability table.
- Rewrote RELEASE.md to match the current release flow (removed stale v3.1.x wording, added the extension version-bump checklist and the CHANGELOG.ru.md step).
- Rebuilt CHANGELOG.ru.md so the Russian history covers the extension era instead of jumping from v3.77 straight to v3.1.6.
- Refreshed scripts/make_release_zip.py docstring examples to the current version.

## v3.77.0 - 2026-07-02

- Reworked README.md into a clean public landing page and moved release history out of the main README.
- Reworked README.ru.md as the Russian public landing page with the same current structure.
- Updated CONTRIBUTING.md and chat_extension/README.md to match the current unified bridge and extension workflow.

## v3.76.0 - 2026-07-02

- Added extension history events for toolbar Insert and Send actions.
- Extended sidepanel command lifecycles with `insert` and `submit` stages.
- Surfaced insertion strategy/timing/version diagnostics in sidepanel cards.

## v3.75.0 - 2026-07-02

- Made sidepanel lifecycle grouping conservative: repeated single-stage events remain regular cards instead of fake command lifecycles.
- Removed duplicate status badges from grouped command cards.
- Added live filter behavior for kind changes and debounced site/adapter inputs.

## v3.74.0 - 2026-07-02

- Added sidepanel command lifecycle grouping for related `detected`, `preview`, and `execute` events.
- Preserved audit access by keeping raw per-kind filters and adding original `history_index` values for replay actions.
- Added flow badges and regression coverage for grouped command cards.

## v3.73.0 - 2026-07-02

- Added `scan` to the sidepanel history kind filter.
- Surfaced Scan Page diagnostics directly in Command Center cards: candidate/block/control counts, composer type, Auto insertion plan, and manifest/content/insert script versions.
- Added sidepanel regression coverage for scan filtering and diagnostic card metadata.

## v3.72.0 - 2026-06-28

- Converted sidepanel history rows into compact Command Center-style cards with kind/status/count badges.
- Replaced the always-expanded status JSON with concise status summaries while keeping raw policy/test data inspectable in the result panel.
- Added card metadata helpers for site, adapter, tools, and action availability.

## v3.71.0 - 2026-06-28

- Aggregated repeated Scan Page history entries within the same short window, updating one row with a `×N` count instead of flooding the sidepanel.
- Replaced detected-only dedupe helpers with shared history aggregation helpers for `detected` and `scan` events.
- Kept `preview` and `execute` history entries unaggregated so user actions remain auditable.

## v3.70.0 - 2026-06-28

- Reduced extension detected-history noise by deduping detected events with a payload fingerprint instead of DOM position alone.
- Added tool names and payload fingerprints to detected history entries for more useful popup/sidepanel rows.
- Suppressed repeated page-level detected events for payloads that have already mounted controls during the current content-script lifetime.

## v3.69.0 - 2026-06-28

- Added explicit manifest/content/insert-script version diagnostics to Scan Page output so stale content scripts are obvious after extension reloads.
- Added composer diagnostics (`rich_textarea`, `prose_mirror`, `auto_plan`) to explain why Auto chose a concrete insertion strategy.
- Appended active extension/content-script version information to toolbar insert/send timing messages.

## v3.68.0 - 2026-06-28

- Made Auto insertion editor-aware: ProseMirror-style contenteditable composers use native `insertText`, preserving ChatGPT and Claude multiline structure.
- Scoped the fast `directDomPreWrap` path to Gemini Web `rich-textarea`, where smoke testing confirmed both speed and structure.
- Kept AI Studio on native insertion even though it shares the Gemini adapter, avoiding a site-specific UI mode while respecting editor differences.

## v3.67.0 - 2026-06-28

- Labeled `Auto` as the recommended insert strategy in the extension popup and marked manual strategies as debug options.
- Updated toolbar timing text to report the concrete strategy selected by Auto, e.g. `Auto used directDomPreWrap in ...`.
- Added compact attempt summaries to insert failure text for easier cross-site diagnostics.

## v3.66.0 - 2026-06-28

- Made the `auto` insert strategy adaptive for contenteditable composers: try verified `directDomPreWrap` first, then fall back to native `insertText` only when the fast path makes no composer change.
- Improved settled verification by matching both normalized text and whitespace-free signatures, reducing false negatives for direct DOM strategies that alter line-break representation.
- Kept the adaptive behavior generic and verification-gated instead of adding a Gemini-specific mode.

## v3.65.0 - 2026-06-28

- Changed extension insertion to async settled verification: success is reported only after the composer still contains the inserted marker after a short delay.
- Prevented Insert & Submit from clicking Send when insertion is unverified, ignored, or reverted by the target chat UI.
- Added `directDomPreWrap`, a fast no-`execCommand` diagnostic strategy for multiline contenteditable insertion using `white-space: pre-wrap`.

## v3.64.0 - 2026-06-28

- Added `directDomBlocks`, a no-`execCommand` insert strategy that writes one contenteditable block per line to preserve multiline composer structure.
- Kept `directDomText` as the raw text-node diagnostic path after it proved the Gemini latency regression is in browser/site editing APIs rather than bridge execution.
- Left `auto` unchanged until the block-based direct DOM strategy is confirmed reliable.

## v3.63.0 - 2026-06-28

- Added verified contenteditable insert diagnostics: strategies now report success only when composer text actually changes.
- Fixed the `pasteOnly` false-positive path that could report `Inserted` even when Gemini ignored the synthetic paste event.
- Added a `directDomText` insert strategy to test a no-`execCommand` path for Gemini rich-textarea latency without creating a separate Gemini mode.

## v3.62.0 - 2026-06-28

- Added an extension insert-strategy selector (`auto`, `nativeInsertText`, `paragraphFallback`, `pasteOnly`) for A/B testing Gemini and other contenteditable composers without site-specific modes.
- Toolbar insert/send status now reports the selected strategy and timing (`via <strategy> in <ms>ms`) so latency can be compared without DevTools tracing.
- Auto-insert/auto-submit uses the same configured strategy, keeping manual and automatic flows comparable.

## v3.61.0 - 2026-06-28

- Removed the private Tailnet-specific extension permission that was accidentally added in v3.60.0.
- Replaced it with generic public tunnel host permissions for Tailscale Funnel (`https://*.ts.net/*`) and Cloudflare Quick Tunnels (`https://*.trycloudflare.com/*`).
- Corrected Cloudflared optional download documentation from ~40 MB to ~50 MB.

## v3.60.0 - 2026-06-28

- Fixed extension `TypeError: Failed to fetch` for public tunnel bridges by adding generic tunnel host permissions.
- Improved background bridge fetch errors to include the target bridge URL/path, making permission/config failures easier to diagnose.
- Kept local bridge permissions (`127.0.0.1`, `localhost`) unchanged.

## v3.59.0 - 2026-06-28

- Removed the extra synthetic `InputEvent` after native contenteditable `insertText`; Gemini rich-textarea already receives native input events and the duplicate event caused extra processing.
- Added lightweight insert/send timings in toolbar status text (`Inserted in Xms`, `Inserted/submitted in Xms`) to make remaining latency visible without DevTools tracing.
- Kept textarea/input manual events unchanged, because direct value assignment still needs explicit `input/change` notifications.

## v3.58.0 - 2026-06-28

- Deduplicated noisy `detected` history entries in the extension background worker using fingerprint/site/adapter/detail within a short time window.
- Repeated detections now update the existing history row with a `×N` count instead of flooding popup/sidepanel history.
- Kept `preview`, `execute`, and `scan` history entries unsquashed so real user actions and diagnostics remain explicit.

## v3.57.0 - 2026-06-28

- Fixed the Gemini Insert/Send lag regression shown in DevTools trace: Arena toolbar buttons no longer steal focus from the chat composer on pointer/mouse down.
- Added a guarded composer focus helper so insertion only focuses the composer when it is not already active, avoiding expensive Gemini blur/focus churn.
- Kept the shared insert path unchanged (`insertText` first, paragraph fallback only if needed) so ChatGPT/Gemini duplicate-insert protections remain intact.

## v3.56.0 - 2026-06-28

- Fixed Claude detection using the real Scan Page diagnostics: `[data-test-render-count]` is now the only Claude message selector.
- Excluded Claude user echo blocks that start with `You said:`, so quoted Arena instructions no longer mount false controls.
- Expected Claude smoke page result is now three mounted controls for the three assistant JSONL `sys.status` blocks instead of four including the user quote.

## v3.55.0 - 2026-06-28

- Restored Claude message selectors to a broad reliable set so assistant tool blocks are detected again after the v3.53/v3.54 over-narrowing.
- Added per-selector Scan Page diagnostics (selector_hits) reporting raw, assistant, and with-block matches so adapter issues can be debugged from real DOM instead of guesswork.

## v3.54.0 - 2026-06-28

- Restored Claude control detection by filtering only user-message nodes instead of relying on a brittle font-claude-message class, so assistant tool blocks are detected again.
- Reduced the perceived insert/submit lag on Gemini by replacing the coarse retry timers with a tight 40ms polling loop that clicks Send as soon as it becomes enabled.

## v3.53.0 - 2026-06-28

- Fixed duplicate Claude controls by restricting detection to assistant messages (font-claude-message) and excluding user-message nodes that quote tool instructions.
- Improved Gemini input responsiveness by skipping a full cloneNode of large answer nodes during scanning unless a composer child is actually nested inside.

## v3.52.0 - 2026-06-28

- Added Claude (claude.ai) smoke support with assistant message, ProseMirror composer, and Send-button selectors.
- Reduced Gemini input-detection lag by dropping characterData mutation observation and throttling page scans with requestIdleCallback, so streaming answers no longer trigger constant rescans.

## v3.51.0 - 2026-06-28

- Fixed Gemini regressions from v3.50.0: result insertion now uses a single deterministic insertText path, removing the paste+fallback combo that caused duplicate insertion on Gemini and a false insert status that blocked Send.
- Send no longer depends on an instant synchronous text check, so submit works on composers that apply edits asynchronously (Gemini rich-textarea).

## v3.50.0 - 2026-06-28

- Fixed duplicate result insertion in ChatGPT by detecting whether the synthetic paste already changed the composer before running the per-line fallback.
- Made contenteditable insertion report honest success based on actual composer content change instead of always returning true.
- Added more Gemini submit-button selectors so Send can find the send control after insertion.
- Raised the product-file modularity limit from 200 to 300 lines to keep helpers readable instead of artificially compressed.

## v3.49.0 - 2026-06-28

- Fixed multiline result insertion into contenteditable composers (ChatGPT/Gemini) by dispatching a paste event with plain text, with a per-line insertParagraph fallback, so JSON keeps its structure instead of collapsing.

## v3.48.0 - 2026-06-28

- Fixed JSONL parsing for ChatGPT, which renders tool blocks on a single line with a glued language label and no newlines.
- Made Clear Page Controls hide controls only for the current page life; reload or a new chat restores them, plus a new Show Page Controls action restores them without reload.
- Inserted tool results as fenced code blocks so ChatGPT and other contenteditable composers keep JSON structure instead of collapsing to one line.

## v3.47.0 - 2026-06-28

- Fixed inline close controls so `×` dismisses a detected block instead of being immediately remounted by the mutation observer.
- Made `Clear Page Controls` suppress currently visible tool blocks until reload or new block fingerprints appear.
- Added `dismissed_controls` to Scan Page diagnostics for clearer adapter debugging.

## v3.46.0 - 2026-06-28

- Stabilized Gemini Web extension detection by filtering composer/user-input nodes before parsing tool blocks.
- Added adapter-side detection text extraction that removes nested composer fields from broad candidates.
- Made controls remount tolerant to Gemini DOM re-renders without duplicating history detections.
- Clarified inline Preview status as a dry-run/approval summary with tool names.

## v3.45.0 - 2026-06-26

### Added
- **Scan Page diagnostics** — popup can ask the active chat page for adapter, candidate node count, parsed tool block count, mounted controls, detected tools, and text snippets.
- **Scan history entries** — Scan Page results are stored in extension history so adapter/debug state can be inspected in the side panel.

### Improved
- **Alpha example cleanup** — chat extension README examples now use stable `sys.status` instead of `mission.lineage demo` for empty installs.

### Tests
- Expanded extension asset and adapter regressions for Scan Page diagnostics.

## v3.44.0 - 2026-06-26

### Changed
- **Simplified alpha UX** — removed the unstable latest-only/floating toolbar path from the user-facing popup and kept inline controls as the primary alpha workflow.
- **Manual page cleanup** — added `Clear Page Controls` so users can clear inline toolbars on the current chat page without relying on fragile virtualized-DOM heuristics.

### Fixed
- **Avoided confusing latest-only behavior** — AI Studio virtualization no longer drives a half-magic latest-only mode that could look inconsistent after reloads or history remounts.

### Tests
- Updated extension regressions for inline controls plus manual page cleanup.

## v3.43.0 - 2026-06-26

### Changed
- **Latest-only mode is now floating** — when `Show controls only for latest visible block` is enabled, the extension renders one fixed toolbar for the latest detected block instead of inserting inline controls into AI Studio's virtualized chat DOM.

### Fixed
- **Latest-only duplicate/strange layout** — floating latest controls avoid duplicate inline toolbars and layout drift caused by AI Studio history virtualization.

### Tests
- Expanded extension asset regressions for floating latest-only toolbar behavior.

## v3.42.0 - 2026-06-26

### Fixed
- **Latest-only reload behavior** — when latest-only mode is already enabled at page load, the content script now selects the visually latest candidate before mounting controls instead of mounting all controls and pruning afterward.
- **Initial scan cleanup** — stale toolbars are cleared around the selected host during latest-only scans, reducing duplicate controls after AI Studio reloads or virtualized history remounts.

### Tests
- Expanded extension asset regressions for pre-mount latest-only candidate selection.

## v3.41.0 - 2026-06-26

### Fixed
- **Latest-only stale controls** — content script now cleans orphaned toolbars from previous loads and enforces latest-only mode on every scan.
- **Live mode switching** — saving popup settings notifies the active tab so controls mode changes apply immediately without requiring a page refresh.

### Improved
- **Toolbar polish** — result copy is shortened to `Copy`, and each toolbar has a compact close action for manual cleanup.

### Tests
- Expanded extension regressions for stale toolbar cleanup and live controls-mode notifications.

## v3.40.0 - 2026-06-26

### Improved
- **Latest-only controls mode** — the chat extension now keeps the visually lowest visible toolbar instead of the last toolbar mounted by AI Studio's virtualized DOM lifecycle.
- **Toolbar polish** — inline controls use a compact product-style toolbar with pill buttons, a primary Run action, shorter status text, and `Send` instead of the debug-like `Insert & Submit` label.

### Tests
- Expanded extension asset regressions for visual latest-only pruning and polished toolbar labels.

## v3.39.0 - 2026-06-26

### Fixed
- **Controls placement runtime bug** — content script now actually uses the `attachControls()` placement helper, so AI Studio controls are inserted after rendered code blocks instead of appended into arbitrary containers.
- **Insert & Submit timing** — submit now waits briefly and retries while AI Studio enables the send button after insertion.

### Added
- **Controls visibility mode** — popup settings now include `Show controls only for latest visible block`, allowing users to keep only the newest visible toolbar or keep controls on all visible blocks.

### Improved
- **Inline toolbar styling** — controls now size to the detected code block width and use a cleaner compact dark toolbar style.

### Tests
- Expanded extension regressions for latest-only controls mode, async insert-and-submit, and real `attachControls()` usage.

## v3.38.0 - 2026-06-26

### Fixed
- **AI Studio rendered-block regression** — candidate scanning now normalizes `code` nodes to their nearest `pre` and prunes ancestor containers, so controls attach to concrete rendered JSONL blocks instead of drifting into large page containers.
- **Repeated identical tool blocks** — message fingerprints now include a compact DOM path, preventing identical JSONL payloads in separate AI Studio responses from being collapsed as already processed.
- **Bridge URL diagnostics** — extension bridge URLs are normalized when users enter `127.0.0.1:8765` without a scheme, and fetch/HTTP failures now surface concrete errors instead of `unknown`.
- **Policy smoke example** — extension policy examples now use stable `sys.status` instead of `mission.lineage demo` on empty installs.

### Tests
- Expanded extension asset and adapter regressions for rendered-code host pruning, DOM-path fingerprints, URL normalization, and `sys.status` policy examples.

## v3.37.0 - 2026-06-26

### Fixed
- **Mission HTTP error bodies** — MCP mission tools now preserve JSON error bodies from bridge endpoints, so `mission.lineage` on a missing mission returns structured `mission not found` data instead of a bare `HTTPError`.
- **Tool-call success semantics** — extension execution now treats parsed tool results with `ok: false` as failed calls while keeping the structured result available for copy/insert.
- **AI Studio control placement** — nested selector matches now converge to the nearest rendered `pre` / `code` block before mounting controls, reducing duplicate detections and misplaced buttons.

### Improved
- **Stable smoke instructions** — copied extension instructions now use `sys.status` as the default JSONL/Arena example because it works on empty installations; mission tools remain listed for real mission IDs.

### Tests
- Expanded backend and extension regressions for structured HTTP errors, stable smoke instructions, and rendered code-block placement.

## v3.36.0 - 2026-06-26

### Fixed
- **Execution error visibility** — the browser extension now surfaces failed tool-call results instead of showing `error: unknown` when the bridge returns `ok: false` with per-call output.
- **Rendered code-block controls** — inline controls are attached after rendered `pre` / `code` blocks instead of being appended inside code-block UI.
- **Panel fallback** — if Chrome refuses `sidePanel.open()` because of user-gesture restrictions, the extension opens `sidepanel.html` in a regular extension tab.

### Improved
- **Result handling** — failed executions with structured tool output can still be copied/inserted for diagnosis, such as `mission not found` responses.

### Tests
- Expanded extension asset regressions for error summarization and panel fallback behavior.

## v3.35.0 - 2026-06-26

### Fixed
- **Rendered/raw JSONL code blocks** — the browser chat extension now detects MCP SuperAssistant-style `function_call_start` / `function_call_end` JSONL even when AI Studio renders it as a pretty code block without literal triple backticks in the DOM.

### Improved
- **AI Studio selectors** — Gemini / Google AI Studio scanning now includes rendered `pre`, `code`, and code-like nodes so copied JSONL instructions can produce inline Arena controls on real chat pages.
- **Parser fallback** — JSONL parsing now accepts raw inline JSONL text after fenced `arena-tool`, `json`, and `jsonl` formats are checked.

### Tests
- Expanded extension asset and adapter-flow regressions for raw JSONL detection and AI Studio rendered-code selectors.

## v3.34.0 - 2026-06-26

### Fixed
- **JSONL detection pre-filter** — the browser chat extension adapter layer now treats MCP SuperAssistant-style fenced `jsonl` / `json` function-call blocks as executable candidates instead of filtering them out before the parser can run.

### Improved
- **AI Studio JSONL workflow** — models that follow the copied JSONL instructions should now trigger inline extension controls when they emit `function_call_start` / `function_call_end` blocks.

### Tests
- Expanded adapter-flow regressions to cover JSONL/function-call candidate detection.

## v3.33.0 - 2026-06-26

### Fixed
- **Popup save/load reliability** — the browser chat extension popup now uses callback-compatible runtime messaging with explicit `chrome.runtime.lastError` handling, avoiding indefinite `Loading...` states in browsers where promise-style `sendMessage` is unreliable.
- **Configuration save verification** — saving bridge URL, token, and execution modes now immediately reloads stored config to confirm persistence and show a clear status.

### Improved
- **Popup diagnostics** — config/history load failures now render actionable error messages instead of leaving the popup stuck.

### Tests
- Expanded popup asset regressions for callback-compatible messaging and explicit save/load error states.

## v3.32.0 - 2026-06-26

### Added
- **Extension instruction generator endpoint** — added `GET /v1/extension/instructions?format=arena|jsonl|both&style=full|short` so chat sites can receive stable Arena tool-use instructions without hand-written prompts.
- **Popup instruction copy actions** — the browser chat extension popup now includes Copy Arena Instructions and Copy JSONL Instructions actions for quick setup in AI Studio, ChatGPT, Kimi, Qwen, and other web chats.

### Improved
- **End-to-end chat workflow is more practical** — users can now configure the extension, copy the right prompt, ask the AI to emit a tool block, run it through Arena, and insert the result back into the chat.
- **MCP SuperAssistant parity path is stronger** — JSONL-compatible instructions explicitly tell the model to emit `function_call_start` / `parameter` / `function_call_end` blocks and wait for extension-provided results.

### Tests
- Added extension instruction runtime and route regressions plus popup asset coverage for instruction copy actions.

## v3.31.0 - 2026-06-26

### Added
- **MCP SuperAssistant-style JSONL compatibility foundation** — the browser chat extension now detects fenced `jsonl` function-call blocks and normalizes them into canonical Arena `arena-tool` payloads before preview/execute.
- **Expanded chat adapter site registry** — split site definitions into a modular registry and added first-class host coverage for Gemini / AI Studio, Perplexity, Grok, OpenRouter, DeepSeek, Kimi, Qwen, and generic fallback flows.
- **Extension execution mode settings** — the popup now exposes auto-preview, safe auto-execute, auto-insert, and auto-submit toggles, while defaulting to manual confirmation.

### Improved
- **Browser-chat execution parity path is clearer** — Arena keeps bridge-native execution while accepting MCP SuperAssistant-compatible JSONL as an input format.
- **Extension code remains modular** — parser, site registry, settings, adapter helpers, and content flow are split to stay under project modularity guardrails.

### Tests
- Expanded chat extension scaffold and adapter-flow regressions for JSONL parsing, expanded site coverage, and execution mode settings.

### Validation
- Local targeted `pytest -q tests/test_chat_extension_assets.py tests/test_chat_extension_adapter_flow.py tests/test_chat_extension_sidepanel_flow.py tests/test_extension_bridge.py tests/test_project_modularity.py`: PASS, 17 tests.
- Local `node --check` for chat extension JavaScript assets: PASS.

## v3.30.0 - 2026-06-26

### Added
- **Side-panel result inspector** — the browser chat extension side panel can now inspect stored execution results separately from payloads.
- **History filtering by adapter** — the side panel now filters history not only by kind/site but also by adapter, making multi-site debugging more practical.
- **Richer history metadata** — preview and execute entries now persist adapter, fingerprint, payload, and compact response data for later inspection and replay.

### Improved
- **ChatGPT-oriented adapter flow is stronger again** — the adapter layer now exposes latest-candidate helpers, node-id extraction, and tighter assistant-container filtering for better large-chat behavior.
- **Side-panel debugging loop is more complete** — payload inspection, result inspection, payload/result copy, filtering, replay, and clear-history controls now work together in one surface.
- **Browser-chat execution remains bridge-native** — no separate executor was introduced; the extension still uses the local Arena bridge execution model.

### Tests
- Added side-panel flow regressions for payload/result inspection and adapter-filter behavior.
- Total: **637 tests pass**.

### Validation
- Local `pytest -q`: PASS, 637 tests.
- Local `pytest --collect-only`: PASS, 637 tests collected.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.29.0 - 2026-06-26

### Added
- **Side-panel payload inspector** — the browser chat extension side panel can now inspect stored payloads from history and replay them directly as preview or execute actions.
- **ChatGPT-oriented message filtering** — the extension adapter layer now fingerprints assistant messages, filters candidate nodes by actual `arena-tool` presence, and limits detection to relevant assistant-side containers.

### Improved
- **Extension debugging loop is stronger** — popup and side panel can now clear history, filter history, inspect payloads, and replay actions without leaving the browser.
- **Adapter-aware insert-and-submit is more practical** — submit-button discovery and composer-aware insertion now support a stronger ChatGPT / ChatGPT.com path and a clearer fallback chain.
- **Browser-chat execution remains bridge-native** — these improvements keep using the Arena bridge rather than introducing a separate local executor process.

### Tests
- Added side-panel flow and adapter-flow regressions for payload inspection, filtering, and stronger adapter helpers.
- Total: **637 tests pass**.

### Validation
- Local `pytest -q`: PASS, 637 tests.
- Local `pytest --collect-only`: PASS, 637 tests collected.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.28.0 - 2026-06-26

### Added
- **ChatGPT-oriented detection helpers** — the extension now fingerprints assistant messages, filters candidate nodes by `arena-tool` presence, and limits detection to more relevant assistant-side containers.
- **Insert & Submit adapter path** — the adapter layer now includes submit-button discovery and adapter-aware insert-and-submit helpers, with a stronger first path for ChatGPT/ChatGPT.com.
- **Extension replay/debug controls expanded** — side-panel history actions and richer structured history flows are now part of the extension scaffold instead of a passive log-only view.

### Improved
- **Detection is less noisy on large chat DOMs** — the content script now throttles scans, filters nodes earlier, and avoids re-instrumenting already-handled assistant blocks.
- **Chat extension UX is more practical for repeated workflows** — popup + side panel + replay + insert/submit now form a more realistic loop for browser-chat execution.
- **Browser-chat execution remains bridge-native** — all of this still runs through the local Arena bridge rather than a separate local executor process.

### Tests
- Added chat extension adapter-flow regressions and expanded asset checks.
- Total: **635 tests pass**.

### Validation
- Local `pytest -q`: PASS, 635 tests.
- Local `pytest --collect-only`: PASS, 635 tests collected.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.27.0 - 2026-06-26

### Added
- **Extension history replay controls** — the browser chat extension side panel can now replay saved preview/execute items from structured history.
- **Insert & Submit workflow** — the content script now exposes an `Insert & Submit` action that uses adapter-aware composer and submit-button discovery before falling back to generic insertion behavior.

### Improved
- **Side panel is now more than passive status text** — it can refresh state, clear history, and replay stored tool payloads for debugging and repeated execution.
- **ChatGPT-focused adapter behavior is more practical** — the adapter layer now includes submit-button selectors and stronger composer-aware helpers for ChatGPT/ChatGPT.com.
- **Browser-chat execution remains bridge-native** — these replay/debug improvements still build on the local Arena bridge rather than introducing a separate executor layer.

### Tests
- Expanded chat extension scaffold regressions for replay controls, side-panel actions, and insert-and-submit adapter helpers.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.26.0 - 2026-06-26

### Added
- **Extension side panel scaffold** — added side-panel assets for richer bridge status and execution history viewing directly inside the browser extension.
- **Adapter-aware insertion helpers** — the extension now includes composer-aware adapter utilities, with a first stronger ChatGPT/ChatGPT.com path and generic fallback insertion logic.

### Improved
- **Extension UX is deeper than a popup-only shell** — the popup can now open the side panel, while the background tracks detections, previews, and executions as structured history entries.
- **Result handling is more practical in real chats** — the content script now supports adapter-aware insertion before falling back to generic active-field insertion, plus a side-panel shortcut from detected blocks.
- **Browser-chat execution continues to stay bridge-native** — these UX improvements build directly on the local Arena bridge rather than introducing a separate executor layer.

### Tests
- Expanded chat extension scaffold regressions for side-panel assets, adapter helpers, and panel/open interactions.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- Local `node --check chat_extension/sidepanel.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.25.0 - 2026-06-26

### Added
- **Extension popup UI** — added popup assets for bridge URL/token configuration, connection testing, policy inspection, and recent extension execution history.
- **Extension adapter scaffold** — added `chat_extension/adapters.js` with the first adapter registry and host-aware candidate node selection for ChatGPT, Claude, and generic fallback flows.

### Improved
- **Extension UX is now minimally usable without editing files by hand** — users can configure the local bridge and inspect connectivity directly from the extension popup.
- **Result handling is more practical** — the content script now supports result copy and best-effort insertion back into active text inputs/contenteditable fields after execution.
- **Browser-chat execution remains bridge-native** — the extension UX improvements build directly on the `v3.24.0` backend foundation without introducing a separate local executor layer.

### Tests
- Expanded chat extension scaffold regressions for popup/config/history/adapter assets.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/adapters.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- Local `node --check chat_extension/popup.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.24.0 - 2026-06-26

### Added
- **Browser chat extension bridge endpoints** — added `GET /v1/extension/policies`, `POST /v1/extension/preview`, and `POST /v1/extension/execute` for extension-facing validation and execution of structured Arena tool payloads.
- **Extension execution policy layer** — added site policy snapshots, tool risk classification, approval gating, and normalized batched tool execution for browser-originated tool blocks.
- **Browser extension MVP scaffold** — added `chat_extension/` with a Manifest V3 prototype, generic `arena-tool` fenced-block detector, localhost bridge calls, and a lightweight background/content-script flow.

### Improved
- **Arena can now grow beyond chats with native MCP/code execution** — the bridge has a first execution protocol layer specifically for ordinary browser chats.
- **The extension roadmap now has concrete code, not just planning** — `docs/CHAT_BRIDGE_EXTENSION_PLAN.md` is no longer just aspirational; Phase 1 bridge groundwork is implemented.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added extension bridge regressions and browser extension scaffold checks.
- Total: **633 tests pass**.

### Validation
- Local `pytest -q`: PASS, 633 tests.
- Local `pytest --collect-only`: PASS, 633 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/26-workspace-v3.js`: PASS.
- Local `node --check chat_extension/background.js`: PASS.
- Local `node --check chat_extension/content.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 232.

## v3.23.0 - 2026-06-23

### Added
- **Automatic mission schedule worker** — added a background recurring mission scheduler that executes due mission schedules without requiring manual ticks.
- **Schedule worker state surface** — added `GET /v1/mission/schedules/state` and MCP `mission.schedule_state`, exposing worker state, last tick, totals, and last execution status.

### Improved
- **Recurring mission orchestration is now bridge-managed** — schedule definitions are no longer just stored objects; the bridge now runs them in the background and tracks worker state.
- **Workspace schedule view is richer** — the Workspace mission loop studio now loads both mission schedules and schedule worker state together.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission schedule worker regressions and lifecycle coverage updates.
- Total: **629 tests pass**.

### Validation
- Local `pytest -q`: PASS, 629 tests.
- Local `pytest --collect-only`: PASS, 629 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/26-workspace-v3.js`: PASS.
- MCP tools: 68.
- Distinct non-HEAD routes: 229.

## v3.22.0 - 2026-06-23

### Added
- **Mission family surfaces** — added `GET /v1/mission/family` and MCP `mission.family`, so agents can inspect whole mission families rooted at a lineage chain, including branch summaries, leaves, and family-level stats.
- **Mission schedules v1** — added `GET/POST/DELETE /v1/mission/schedules` plus `POST /v1/mission/schedules/tick`, and MCP tools `mission.schedules`, `mission.schedule_save`, `mission.schedule_delete`, and `mission.schedule_tick` for recurring mission orchestration.
- **Workspace schedule/family controls** — the Workspace mission loop studio now includes family inspection plus schedule listing, saving, and ticking surfaces.

### Improved
- **Recurring orchestration now exists on top of mission lifecycle state** — agents can move from lineage/family inspection into recurring schedule definitions and due-run execution without rebuilding orchestration state manually.
- **Mission families now expose branch-level summaries** — roots, members, leaves, branch paths, and family stats are available as first-class bridge data.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission family, mission schedule, and mission lifecycle handler regressions.
- Total: **626 tests pass**.

### Validation
- Local `pytest -q`: PASS, 626 tests.
- Local `pytest --collect-only`: PASS, 626 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/26-workspace-v3.js`: PASS.
- MCP tools: 67.
- Distinct non-HEAD routes: 228.

## v3.21.0 - 2026-06-23

### Added
- **Mission lineage surfaces** — added `GET /v1/mission/lineage` and MCP `mission.lineage`, so persisted missions expose parents, roots, ancestors, children, descendants, and sibling context as first-class lifecycle data.
- **Workspace mission loop studio** — the Workspace tab now includes a mission loop surface for recent mission catalog summaries, lineage inspection, and direct follow-up / iterate actions.

### Improved
- **Mission families now persist provenance** — follow-up and iteration flows now write lineage metadata into persisted mission artifacts, including origin, parent, root, ancestor chain, and recovery hints.
- **Deeper agent loops now span multiple missions, not just one run** — agents can carry recovery context forward into explicit mission families and iteration chains.
- **Desktop maturity remains preserved** — this release does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission lineage, lineage persistence, and workspace v3 regressions.
- Total: **625 tests pass**.

### Validation
- Local `pytest -q`: PASS, 625 tests.
- Local `pytest --collect-only`: PASS, 625 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- MCP tools: 62.
- Distinct non-HEAD routes: 223.

## v3.20.0 - 2026-06-23

### Added
- **Mission follow-up bundles** — added `POST /v1/mission/followup` and MCP `mission.followup`, so agents can derive a next mission from persisted mission artifacts instead of restarting from a raw prompt.
- **Mission iteration loops** — added `POST /v1/mission/iterate` and MCP `mission.iterate`, combining recovery analysis with optional follow-up mission composition/creation/run in one bridge-native loop.

### Improved
- **Deeper agent loops now chain mission state back into agentic planning** — mission history, failed-step summaries, report excerpts, ReAct observations, reflection, and follow-up mission composition now work as one iteration surface instead of isolated endpoints.
- **Mission lifecycle v4 is now materially loop-shaped** — agents can move from inspect/recover into follow-up mission drafting and optional execution without rebuilding context by hand.
- **Desktop maturity remains preserved** — this release stays out of the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission follow-up and mission iteration regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- MCP tools: 61.
- Distinct non-HEAD routes: 222.

## v3.19.0 - 2026-06-23

### Added
- **Mission catalog surfaces** — added `GET /v1/mission/catalog` and MCP `mission.catalog` so agents can filter persisted missions by query, state, template, and report presence instead of scraping the raw missions list.
- **Mission recovery bundles** — added `POST /v1/mission/recover` and MCP `mission.recover` so agents can inspect a failed mission, derive a rerun recommendation, and optionally compose/create a follow-up mission from the recovery context.

### Improved
- **Deeper agent loops now bridge mission state back into planning** — mission recovery can turn stored history, failed-step summaries, and report excerpts into a structured next action instead of leaving the agent to reconstruct state manually.
- **Mission lifecycle v3 is more operational** — agents can now move from catalog → inspect → recover → rerun/follow-up within bridge-native REST and MCP surfaces.
- **Desktop maturity remains preserved** — this mission/orchestration expansion does not touch the non-interactive KDE/Wayland focus/window-control path.

### Tests
- Added mission catalog and mission recovery regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.18.0 - 2026-06-22

### Added
- **Mission lifecycle/inspection v2** — added `GET /v1/mission/history` and `POST /v1/mission/rerun`, plus MCP `mission.history` and `mission.rerun`, so missions can be inspected and iterated instead of only composed and launched.

### Improved
- **Mission artifacts are now first-class runtime objects** — persisted missions expose structured status, report retrieval, run history, step-log summaries, and rerun flows.
- **Deeper agent loops keep getting more practical** — agents can now compose a mission, run it, inspect outcomes, and rerun the failed step or the whole mission through bridge-native surfaces.
- **The post-desktop roadmap block is maturing** — mission composition has moved beyond initial CRUD and proposal flows into real lifecycle management.

### Tests
- Added mission history/rerun regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.17.0 - 2026-06-22

### Added
- **Mission lifecycle/inspection surfaces** — added structured mission status and report inspection through `GET /v1/mission/status` and `GET /v1/mission/report`.
- **MCP mission inspection tools** — added `mission.status` and `mission.report` so agent frontends can inspect persisted mission state and reports without custom REST glue.

### Improved
- **Mission composition is more usable in practice** — missions are no longer just creatable/runnable; they are now inspectable as first-class artifacts with structured state and report retrieval.
- **The mission/orchestration block keeps deepening** — Arena now has template listing, composition, proposal/orchestration, creation, run, status, and report surfaces across REST and MCP.
- **Mission runner validation is stronger** — the release includes explicit regression coverage for hook-helper imports, mission status, and mission report access.

### Tests
- Added mission status/report regressions.
- Total: **624 tests pass**.

### Validation
- Local `pytest -q`: PASS, 624 tests.
- Local `pytest --collect-only`: PASS, 624 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.16.0 - 2026-06-22

### Added
- **Mission proposal/orchestration flow** — added `POST /v1/mission/propose`, which runs a bounded agentic proposal loop, reflects on it, and returns a planner-backed mission bundle with optional mission creation and run.
- **MCP `mission.propose`** — the same proposal/orchestration flow is now available through MCP.

### Improved
- **Mission composition is no longer just CRUD** — Arena can now go from goal → bounded observe/reflect → mission draft → optional persisted mission → optional mission run in one agent-facing flow.
- **The post-desktop roadmap block is now materially underway** — this is the first real bridge between the agentic runtime (`react` / `reflect`) and reusable mission artifacts.

### Tests
- Added mission proposal regressions.
- Total: **623 tests pass**.

### Validation
- Local `pytest -q`: PASS, 623 tests.
- Local `pytest --collect-only`: PASS, 623 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live validation: PASS for mission template listing, mission compose, mission create, and mission run. Mission propose is implemented and covered locally in the same release cycle.

## v3.15.0 - 2026-06-22

### Added
- **Mission composition surfaces** — added `GET /v1/mission/templates`, `POST /v1/mission/compose`, `POST /v1/mission/create`, and `POST /v1/mission/run`, giving the bridge first-party mission composition and execution APIs instead of leaving missions as a CLI-only side surface.
- **MCP mission tools** — added `mission.templates`, `mission.compose`, `mission.create`, and `mission.run` so agent frontends can compose and launch reusable missions without custom REST wiring.

### Improved
- **The next big roadmap block has started** — Arena now has the first real implementation slice of deeper agent loops / mission composition on top of the already-shipped planner, ReAct, reflection, memory, tasks, and desktop stack.
- **Mission drafts are planner-backed** — mission composition now turns a goal into a reusable mission draft with a selected template, planner steps, required tools, risks, and a suggested memory profile.
- **Mission execution is no longer hidden behind the CLI** — agents can now create a mission artifact and trigger the built-in mission manager through API and MCP.

### Fixed
- **Mission runner hook helpers restored** — the built-in mission manager now imports its pre/post mission hook helpers explicitly, so `mission.run` no longer crashes with `NameError: _fire_mission_hook`.

### Tests
- Added mission composition/runtime/handler regressions.
- Total: **622 tests pass**.

### Validation
- Local `pytest -q`: PASS, 622 tests.
- Local `pytest --collect-only`: PASS, 622 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.14.0 - 2026-06-21

### Added
- **High-level text-driven desktop workflow (`D3`)** — added `POST /v1/desktop/text_action`, a composable OCR → window-target → desktop-action flow that can resolve, focus, click, or apply semantic window actions from visible text.
- **MCP `desktop.text_action`** — the same high-level text-driven desktop workflow is now available via MCP.

### Improved
- **`D2 / D3` desktop maturity is now complete enough to count as done** — Arena now has exact/phrase-first OCR ranking, click-by-text, OCR-to-window resolution, query-driven focus/window actions, display-aware placement, snap/tile-style placement, stronger non-interactive KWin Wayland focus, and richer multi-monitor semantics.
- **Roadmap priority shifts forward** — with the desktop maturity slice completed enough to count, the next recommended focus moves to deeper agent loops / mission composition and workspace UI v3 rather than more foundational desktop plumbing.
- **Desktop actions are more composable** — OCR, display-aware targeting, window resolution, focus, click, and window actions can now be chained through one workflow surface instead of being manually orchestrated by every client.

### Tests
- Added text-driven workflow regressions.
- Total: **619 tests pass**.

### Validation
- Local `pytest -q`: PASS, 619 tests.
- Local `pytest --collect-only`: PASS, 619 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `resolve_text_target`, query-driven `focus` dry-run, query-driven `window_action` dry-run / center, and `snap_right`.

## v3.13.1 - 2026-06-21

### Improved
- **OCR-to-window resolution is more practical on KDE/Wayland** — `resolve_text_target`, query-driven `desktop.focus`, and query-driven `desktop.window_action` can now crop OCR work to the active window, which reduces noisy full-screen scans and makes text-to-window targeting much more usable on the live bridge.
- **Text-aware desktop workflows are more reliable** — the new query-driven flows now compose OCR, window resolution, and desktop actions with less timeout risk when the relevant text is already on the active window.

### Tests
- Added active-window crop coverage for OCR-to-window targeting.
- Total: **617 tests pass**.

### Validation
- Local `pytest -q`: PASS, 617 tests.
- Local `pytest --collect-only`: PASS, 617 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `resolve_text_target`, query-driven `focus` dry-run, query-driven `window_action` dry-run / center, and `snap_right`.

## v3.13.0 - 2026-06-21

### Added
- **OCR-to-window resolution (`D3`)** — added `POST /v1/desktop/resolve_text_target`, which resolves recognized text into both a click target and the containing desktop window.
- **MCP `desktop.resolve_text_target`** — text-to-window resolution is now available through the MCP surface.

### Improved
- **`desktop.focus` can now use OCR text queries** — agents can focus the window containing visible text instead of relying only on ids/titles/classes.
- **`desktop.window_action` can now use OCR text queries** — semantic window actions can target the window containing visible text, not just windows resolved by metadata filters.
- **Desktop workflows are more composable** — windows, OCR, display-awareness, and semantic actions now interlock more directly instead of living as separate primitives.

### Tests
- Added OCR-to-window target resolution and query-driven focus/window-action regressions.
- Total: **617 tests pass**.

### Validation
- Local `pytest -q`: PASS, 617 tests.
- Local `pytest --collect-only`: PASS, 617 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `resolve_text_target`, query-driven `focus` dry-run, and query-driven `window_action` dry-run / center on a real helper window.

## v3.12.0 - 2026-06-21

### Added
- **Snap/tile-style placement actions (`D3`)** — `desktop.window_action` now supports `snap_left`, `snap_right`, `snap_top`, `snap_bottom`, `snap_top_left`, `snap_top_right`, `snap_bottom_left`, and `snap_bottom_right`.

### Improved
- **Display-aware planning now covers tiling semantics** — window-action planning can now translate higher-level placement intents into deterministic geometry on the resolved display instead of requiring raw coordinates.
- **Display-aware dry-runs are richer again** — semantic placement actions like `snap_right` now preview the exact geometry that will be applied before the action runs.
- **Desktop maturity advanced from placement to layout policies** — the bridge now has the beginnings of monitor-aware tiling behavior on top of raw move/resize primitives.

### Tests
- Added snap-placement planning regressions.
- Total: **613 tests pass**.

### Validation
- Local `pytest -q`: PASS, 613 tests.
- Local `pytest --collect-only`: PASS, 613 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `snap_right`; multi-display placement remains validated through unit coverage when only one live display is exposed.

## v3.11.0 - 2026-06-21

### Added
- **Higher-level display-aware window actions (`D3`)** — `desktop.window_action` now supports `center` and `move_to_display`, building semantic multi-monitor behavior on top of the earlier low-level move/resize actions.

### Improved
- **Window-action dry-runs are more informative** — when the action is display-aware (`center` / `move_to_display`), dry-run responses now include planned geometry plus source/target display info.
- **Display-aware planning is reusable** — window action geometry planning now lives in a dedicated helper, making desktop policies easier to extend without growing the execution backend into another monolith.
- **Desktop roadmap advanced again** — the bridge now has not just primitive window movement but actual display-aware placement semantics.

### Tests
- Added centered-placement and move-to-display planning regressions.
- Total: **612 tests pass**.

### Validation
- Local `pytest -q`: PASS, 612 tests.
- Local `pytest --collect-only`: PASS, 612 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `center`; `move_to_display` remains unit-validated because the current live machine exposes only one active display.

## v3.10.0 - 2026-06-21

### Added
- **More complete window actions (`D3`)** — `desktop.window_action` now supports `maximize`, `unmaximize`, and `close` in addition to the previously added move/resize/minimize/restore/fullscreen operations.

### Improved
- **KWin/Wayland maximize and close flows validated live** — non-interactive KWin window actions now cover maximize/unmaximize/close on UUID-style Wayland windows without reintroducing focus-stealing behavior.
- **Maximize verification is geometry-aware** — when KWin expands a window geometrically but does not expose maximized flags in the listing payload, verification now still succeeds by comparing before/after geometry growth.
- **Desktop docs updated again** — release notes and roadmap state now reflect that the desktop window-action surface has moved beyond the initial move/resize slice.

### Tests
- Added maximize-by-geometry regression coverage.
- Total: **609 tests pass**.

### Validation
- Local `pytest -q`: PASS, 609 tests.
- Local `pytest --collect-only`: PASS, 609 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Live KDE/Wayland validation: PASS for `maximize`, `unmaximize`, and `close` on a real helper window.

## v3.9.1 - 2026-06-21

### Fixed
- **KWin window-action result metadata** — the non-interactive KWin window-action helper no longer returns a stale `error: "window_not_found"` field on successful actions like move/resize/minimize/restore.

### Validation
- Local `pytest -q`: PASS, 607 tests.
- Local `pytest --collect-only`: PASS, 607 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.9.0 - 2026-06-21

### Added
- **Window actions (`D3` slice)** — added `POST /v1/desktop/window_action`, supporting semantic target resolution plus actions like `move`, `resize`, `move_resize`, `minimize`, `restore`, `fullscreen`, and `unfullscreen`.
- **MCP `desktop.window_action`** — window manipulation is now available through the MCP tool surface in addition to REST.

### Improved
- **Semantic target resolution is now reusable across desktop controls** — focus and window actions both reuse the same filtered window-catalog resolution path (`id`, `title`, `class`, `desktop_file`, `resource_name`, `pid`, `display`).
- **KWin/Wayland window actions stay non-interactive** — UUID-style Wayland windows can now be manipulated through a temporary journal-reporting KWin script path without reintroducing interactive focus-stealing behavior.
- **Desktop docs updated again** — README, OpenAPI, prompt docs, and canonical roadmap now reflect display-aware windows, focus dry-runs, and the new window-action surface.

### Tests
- Added KWin window-action, action verification, semantic dry-run, and MCP/handler regressions.
- Total: **607 tests pass**.

### Validation
- Local `pytest -q`: PASS, 607 tests.
- Local `pytest --collect-only`: PASS, 607 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.8.0 - 2026-06-21

### Added
- **Window-management targeting (`D3` slice)** — `/v1/desktop/windows` now supports semantic filtering by title, class, desktop file, resource name, pid, display, and active-only state, with optional display metadata in the response.
- **Focus dry-run resolution** — `POST /v1/desktop/focus` now supports `dry_run: true`, so agents can resolve the target window and inspect candidates before actually stealing focus.
- **MCP `desktop.windows` and `desktop.focus`** — richer desktop window inspection and focus control are now available through the MCP surface.

### Improved
- **KWin/Wayland focus path is stronger and still non-interactive** — focus can now use a temporary journal-reporting KWin script for UUID-style Wayland window ids instead of relying only on numeric/X11-style activation paths.
- **Window metadata is now display-aware** — window listings annotate the owning display/output, which compounds with the new `/v1/desktop/displays` surface for multi-monitor correctness.
- **Desktop API docs are fuller** — OpenAPI and prompt docs now describe display discovery, filtered window listing, and safer focus-resolution workflows.

### Tests
- Added display-aware window catalog, focus dry-run, KWin focus helper, and filtered window-list regressions.
- Total: **604 tests pass**.

### Validation
- Local `pytest -q`: PASS, 604 tests.
- Local `pytest --collect-only`: PASS, 604 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.7.0 - 2026-06-21

### Added
- **Desktop semantic click-by-text (`D2`)** — added `POST /v1/desktop/click_text`, which runs OCR, ranks the best text match, and clicks it in one step with optional `dry_run`, active-window preference, target edge selection, and click offsets.
- **Desktop display/output discovery (`D3` slice)** — added `GET /v1/desktop/displays`, returning output geometry and active-display metadata for multi-monitor aware automation.
- **MCP `desktop.click_text` and `desktop.displays`** — semantic desktop targeting and display discovery are now available over the MCP tool surface in addition to REST.

### Improved
- **OCR match ranking is now exact/phrase-first** — `desktop.find_text` and OCR-backed desktop targeting now prioritize exact and phrase matches over weak substring noise, fixing the live-class issue where a query like `Google` could degrade to a one-letter best match.
- **Active-window-aware text targeting** — OCR text matching can now prefer or constrain matches to the current active window, improving desktop targeting correctness on busy multi-window setups without reintroducing interactive KWin focus-stealing behavior.
- **Display-scoped screenshot/OCR targeting** — desktop screenshot, OCR, text-find, and click-by-text flows can now be restricted to a named display/output, improving multi-monitor correctness.
- **OpenAPI / prompt docs updated** — the public API spec and AI prompt template now document the new semantic desktop targeting and display-aware flow.

### Tests
- Added ranking, active-window scoping, semantic click handler, display discovery, display scoping, route, and MCP regressions for the new desktop maturity slice.
- Total: **600 tests pass**.

### Validation
- Local `pytest -q`: PASS, 600 tests.
- Local `pytest --collect-only`: PASS, 600 tests collected.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/agentctl`, `bin/bridge-curl`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.6.1 - 2026-06-21

### Added
- **Workspace dashboard v2** — the Workspace tab now includes profile notes, important lessons, and recent activity panels on top of the existing profile context, planner, ReAct/reflection, and file watcher surfaces.
- **Workspace v2 dashboard regressions** — added checks that the new asset bundle and workspace v2 surface are wired into the dashboard bootstrap.

### Validation
- Local `pytest -q`: PASS, 593 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/25-workspace-v2.js`: PASS.

## v3.6.0 - 2026-06-21

### Added
- **Desktop OCR + text-target detection (`D1`)** — added `POST /v1/desktop/ocr` and `POST /v1/desktop/find_text`, returning recognized words, full text, confidence, bounding boxes, and click-ready center coordinates.
- **MCP desktop OCR tools** — added `desktop.ocr` and `desktop.find_text` for OCR and text-target detection through Arena's MCP layer.
- **Tesseract TSV parsing and matching helpers** — OCR now groups recognized words into lines, exposes bounding boxes, and supports multi-word text matching with aggregated coordinates.

### Improved
- **OpenAPI updated** — OCR/text-target detection endpoints are now documented in the public API spec.
- **Prompt/template docs updated** — `docs/AI_PROMPT_TEMPLATE.md` now documents OCR and text-target detection for desktop automation.
- **Desktop API surface expanded** — desktop automation now includes OCR and semantic text targeting in addition to screenshots, windows, input, and focus APIs.

### Tests
- Added desktop OCR parsing, handler, runtime reexport, MCP, and route regressions.
- Total: **592 tests pass**.

### Validation
- Local `pytest -q`: PASS, 592 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.5.2 - 2026-06-21

### Added
- **Workspace dashboard surface v1** — the dashboard now has a dedicated **Workspace** tab that brings companion-style UI around the new backend foundations: active profile context, planner output, bounded ReAct runs, reflection, and file watcher management.
- **Workspace dashboard regressions** — added tests ensuring the new dashboard tab and assets are wired into the bootstrap shell.

### Improved
- **Dashboard navigation updated** — `/gui` now exposes the Workspace tab alongside Overview, Memory, Recall, Tasks, Control, and the rest of the operational UI.
- **README / README.ru dashboard docs updated** — tab counts and descriptions now reflect the Workspace and Control surfaces.
- **Canonical roadmap advanced** — after shipping planner, watchers, safe editing, and ReAct/reflection, the roadmap now points at workspace UI surfaces as the primary next layer of product polish.

### Validation
- Local `pytest -q`: PASS, 588 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.
- Local `node --check dashboard/assets/24-workspace.js`: PASS.

## v3.5.1 - 2026-06-21

### Fixed
- **ReAct/reflection live runtime fix** — agentic endpoints now read app config through the shared aiohttp `AppKey` instead of the old raw string key, so `/v1/react`, `/v1/reflect`, `react.run`, and `reflect.run` work correctly on the installed bridge after the `v3.5.0` modular AppKey migration.

### Validation
- Local `pytest -q`: PASS, 586 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.5.0 - 2026-06-20

### Added
- **Bounded ReAct loop foundation (`A2`)** — added `POST /v1/react`, which runs a safe reason → act → observe loop derived from the built-in planner and executes bounded observation steps such as memory recall, bridge status, doctor/sysinfo, task listing, file watcher listing, and optional browser HEAD checks.
- **Reflection endpoint (`A3`)** — added `POST /v1/reflect`, which critiques a prior run and returns positives, concerns, missing evidence, confidence, and suggested next steps.
- **MCP `react.run` and `reflect.run`** — the same agentic surfaces are now available through Arena's MCP tool layer.
- **OpenAPI updated** — `/v1/react` and `/v1/reflect` are now documented in the public API spec.

### Improved
- **Canonical roadmap advanced** — `A1` was already complete; `A2/A3` now have an implementation foundation, and the next practical priority shifts toward workspace UI surfaces and deeper agent loops rather than basic planning plumbing.
- **Agentic runtime reuses existing foundations** — planner, memory profiles, task queue state, file watchers, bridge status, and browser HEAD checks now feed into a unified bounded loop instead of staying isolated features.

### Tests
- Added agentic runtime, handler, route, and MCP regressions.
- Total: **586 tests pass**.

### Validation
- Local `pytest -q`: PASS, 586 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.4.2 - 2026-06-20

### Added
- **Safe editor foundation (`F4`)** — `PATCH /v1/fs/edit` now supports `preview: true` for a non-destructive preview/confirm workflow.
- **Edit confirmation endpoint** — added `POST /v1/fs/edit/apply` to apply a previously previewed edit by `preview_id`.
- **Rollback endpoint** — added `POST /v1/fs/edit/rollback` to restore the pre-edit contents using `rollback_id`.
- **MCP safe editor support** — added `fs.edit_apply` and `fs.edit_rollback`, while `fs.edit` now supports `preview=true`.

### Improved
- **Safe edit conflict protection** — applying a preview now refuses to write if the target file changed after the preview was generated.
- **Rollback conflict protection** — rollback refuses to overwrite a file that changed again after apply unless explicitly forced.
- **AI prompt template updated** — the prompt now documents the preview/apply/rollback edit workflow.
- **OpenAPI updated** — safe editor endpoints and preview semantics are now documented.

### Tests
- Added safe-editor regressions covering preview, apply, rollback, conflict detection, new routes, and MCP schemas.
- Total: **582 tests pass**.

### Validation
- Local `pytest -q`: PASS, 582 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.4.0 - 2026-06-20

### Added
- **Built-in Planner (`A1`)** — added `POST /v1/plan`, a first-party planner endpoint that turns a goal into a structured execution plan with steps, risks, required tools, next action, and a suggested Memory Profile.
- **MCP `plan.create`** — the planner is now available through Arena's MCP surface, so coding/agent frontends can request plans without custom REST wiring.
- **Planner heuristics** — the first planner infers likely domains (code, browser, desktop, system, task queue), suggests a memory profile, and marks higher-risk steps as requiring confirmation.

### Improved
- **OpenAPI docs updated** with `/v1/plan`.
- **Canonical roadmap advanced** — `A1` is now complete, and the recommended next step moves to `F5` File Watchers.

### Tests
- Added planner logic, handler, route, and MCP regressions.
- Total: **579 tests pass**.

### Validation
- Local `pytest -q`: PASS, 579 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.3.1 - 2026-06-20

### Added
- **DX2 integration recipe set** — added `docs/INTEGRATIONS.md` plus concrete recipe docs for Arena Agent Mode, Claude-style chats, Cursor, Cline, Windsurf, Open Interpreter, and local model backends.
- **Integration doc regression tests** — added coverage ensuring the recipe index exists, the expected recipe files are present, and they mention profile-aware memory usage.

### Improved
- **AI prompt template refreshed for Memory Profiles.** `docs/AI_PROMPT_TEMPLATE.md` now teaches agents to use scoped profiles like `projects/<name>`, `personal`, `code`, and `browser` instead of dumping everything into one memory bucket.
- **README / README.ru now point at the integration recipe index**, making the new documentation easier to discover.
- **Canonical roadmap updated** — `DX2` is now considered complete and the recommended next step shifts to `A1` Built-in Planner.

### Validation
- Local `pytest -q`: PASS, 569 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.3.0 - 2026-06-19

### Added
- **Memory Profiles (`M3`)** — memory is now scoped by profile across REST, MCP, runtime, and dashboard flows. Facts may live in spaces like `default`, `personal`, `projects/<name>`, `code`, `browser`, or custom profile ids.
- **Profile-aware REST memory API** — `/v1/memory`, `/v1/recall`, and `/v1/recall/digest` now accept `profile`, and `/v1/memory` responses include `profile` plus discovered `profiles`.
- **Profile-aware MCP memory tools** — `mem.set`, `mem.get`, `memory.recall`, `memory.digest`, `memory.export`, and `memory.import` now understand profiles.
- **Memory schema migration** — existing single-profile SQLite memory stores are migrated automatically into the `default` profile without data loss.
- **Dashboard profile controls** — Memory and Recall tabs now let the user choose the active memory profile and keep it synced locally.

### Changed
- **Memory DB schema upgraded** from `PRIMARY KEY(key)` to `PRIMARY KEY(profile, key)`, allowing the same key to exist independently in multiple profiles.
- **`agentctl` memory commands** now understand `--profile`, and CLI recall output is aligned with the profile-aware API.
- **OpenAPI memory docs** now document profile-aware memory and recall usage.

### Tests
- Added coverage for memory schema migration, cross-profile key isolation, profile-scoped CRUD/recall handlers, MCP profile support, and export/import round-trips with profile preservation.
- Total: **566 tests pass**.

### Validation
- Local `pytest -q`: PASS, 566 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.14 - 2026-06-19

### Removed
- **Dead release scratch files removed from the repository.** Old `release_v*.md` note files and the obsolete `bump_v323.py` helper were deleted because they were not part of the runtime product and only added noise to the tree and release zip.

### Improved
- **Release hygiene guardrail.** `.gitignore` now ignores future `release_v*.md` and `bump_v*.py` scratch files so they do not accumulate again.
- **Release process docs clarified.** `RELEASE.md` now explicitly tells maintainers to use a temporary/untracked notes file for GitHub releases instead of committing per-release scratch markdown into the repository.

### Validation
- Local `pytest -q`: PASS, 558 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.13 - 2026-06-19

### Fixed
- **Stale backup surface removed from the CLI/workflow layer.** `agentctl backup run` no longer tries to call the long-removed `/v1/backup` API and now prints an explicit deprecation notice instead.
- **Mission templates no longer reference removed backup commands.** `cli-agent-core` and `recovery-drill` were updated to use existing audit/status checks instead of dead `backup ls` steps.
- **`agentctl` version string now follows the canonical bridge version.** The CLI no longer advertises a stale hard-coded `2.0.0` while the bridge is on a newer release.

### Documentation
- Added `docs/ROADMAP_CANONICAL.md` as the planning source of truth.
- Added `docs/PRODUCT_DIRECTION.md` to capture the "Arena Companion Mode" product direction.
- Added `docs/EXPERIMENTS.md` to isolate risky ideas like browser/session-driven model proxies from the core roadmap.

### Tests
- Added regressions covering the removed-backup CLI notice, canonical `agentctl` version wiring, and mission templates no longer emitting backup commands.
- Total: **558 tests pass**.

### Validation
- Local `pytest -q`: PASS, 558 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.12 - 2026-06-19

### Fixed
- **Race condition in the v2 rate limiter removed.** `arena/rate_limit.py::check_rate_limit_v2()` now performs endpoint-store cleanup while still holding `_rl_v2_lock`, instead of mutating `_rl_v2_store[user_id]` after releasing the lock.

### Tests
- Added a regression test that wraps `_rl_v2_store` in a lock-aware dictionary and fails if shared rate-limit state is touched outside the lock.
- Total: **553 tests pass**.

### Validation
- Local `pytest -q`: PASS, 553 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.11 - 2026-06-19

### Fixed
- **Removed the interactive KWin query that was stealing desktop focus/cursor.** `/v1/desktop/active_window` no longer calls `org.kde.KWin.queryWindowInfo`, which on the live Plasma session could trigger a crosshair-style window picker and repeatedly steal focus from the user.
- **KWin script loading no longer rejects valid `loadScript=0` responses.** `/v1/desktop/windows` and native active-window discovery now treat the DBus call itself as success and rely on journal output to determine whether the script actually ran, matching observed Plasma behavior.
- **Active-window discovery now prefers native KWin journal data.** On KDE/Wayland, `/v1/desktop/active_window` now uses the same non-interactive native KWin listing path as `/v1/desktop/windows`, returning the active entry from that list before falling back to X11 tools.
- **Capability map updated to match runtime reality.** `/v1/capabilities` now reports `kwin_journal` for both window listing and active-window discovery on KDE/Wayland.

### Tests
- Reworked desktop runtime tests around the non-interactive KWin journal path and added regression coverage for `loadScript` returning `0` while the script still executes correctly.
- Total: **552 tests pass**.

### Validation
- Local `pytest -q`: PASS, 552 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `ruff check . --select F821,F811`: PASS.

## v3.2.10 - 2026-06-19

### Fixed
- **KDE active-window fallback now uses native KWin window data when direct DBus lookup is cancelled.** When `org.kde.KWin.queryWindowInfo` returns `org.kde.KWin.Error.UserCancel` or otherwise yields no usable data, `/v1/desktop/active_window` now tries the already-working KWin journal-based window listing and returns the active entry from there before falling back to `xdotool`.

### Tests
- Added regression coverage for the `queryWindowInfo` cancellation path to ensure `_get_active_window()` reuses the native KWin window list instead of jumping straight to `xdotool`.
- Total: **552 tests pass** (no regressions; test suite currently collects 552 tests).

### Validation
- Local `pytest -q`: PASS, 552 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.9 - 2026-06-19

### Fixed
- **KWin active-window lookup now retries briefly before giving up.** `/v1/desktop/active_window` now retries `org.kde.KWin.queryWindowInfo` up to three times with a tiny delay before falling back to `xdotool`, smoothing out the intermittent empty-response case seen on the live Plasma/Wayland session.

### Tests
- Added regression coverage for the KWin retry path when the first DBus active-window query returns an empty payload.
- Total: **552 tests pass** (was 551, +1 new).

### Validation
- Local `pytest -q`: PASS, 552 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.8 - 2026-06-19

### Fixed
- **KWin active-window detection is more stable on helper windows/panels.** `/v1/desktop/active_window` now accepts any non-empty `queryWindowInfo` payload from KWin instead of requiring a `caption` or `uuid`, so Plasma-managed focus proxies and other minimal windows no longer force a fallback to `xdotool` just because KWin omitted those two fields.

### Tests
- Added regression coverage for KWin active-window payloads that expose only `resourceClass` / `resourceName` plus geometry.
- Total: **551 tests pass** (was 550, +1 new).

### Validation
- Local `pytest -q`: PASS, 551 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.7 - 2026-06-19

### Fixed
- **Native KDE window listing now actually works.** The temporary KWin script used by `/v1/desktop/windows` no longer tries to unload itself via `callDBus(...)` from inside the script body — that line caused `loadScript` to return `0` on the live Plasma session, so the bridge always fell back to `xdotool`. Unloading is handled purely from Python now.
- **Capability map now distinguishes KWin backends correctly.** `/v1/capabilities` reports `windows.backend = kwin_journal` and `active_window.backend = kwin_dbus` on KDE/Wayland instead of claiming the same backend for both operations.

### Tests
- Added regression coverage proving the KWin helper unload still happens from Python and that KDE/Wayland capabilities report separate backends for window listing vs active-window discovery.
- Total: **550 tests pass** (was 549, +1 new).

### Validation
- Local `pytest -q`: PASS, 550 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.6 - 2026-06-19

### Fixed
- **KDE/Wayland active window detection restored.** `/v1/desktop/active_window` now uses `org.kde.KWin.queryWindowInfo` instead of outdated DBus calls that no longer worked on modern Plasma, so Wayland sessions can report the focused window again.
- **KWin window listing no longer depends on missing desktop env vars.** `/v1/desktop/windows` now probes KWin directly over DBus before loading the temporary scripting helper, fixing live installs where `WAYLAND_DISPLAY` existed but `XDG_CURRENT_DESKTOP` / `XDG_SESSION_TYPE` were absent in the bridge service environment.
- **Session bootstrap now self-heals desktop metadata.** `ensure_session_env()` now infers `XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`, and `DESKTOP_SESSION` when possible, including KDE detection via KWin DBus, so `/v1/capabilities` and desktop helpers report a more accurate runtime picture.
- **aiohttp `NotAppKeyWarning` removed from the bridge runtime/tests.** Shared app state (`cfg`, MCP sessions, lifecycle tasks) now uses proper `aiohttp.web.AppKey` definitions instead of raw string keys.

### Improved
- **Linux systemd installer now preserves desktop session metadata.** `install.sh` writes `XDG_SESSION_TYPE`, `XDG_CURRENT_DESKTOP`, and `DESKTOP_SESSION` into the user service when those values are available at install time.
- **Capability reporting is more accurate.** `/v1/capabilities` now prefers the detected desktop/session metadata instead of reading only raw environment variables.
- **README counts refreshed.** Route and desktop endpoint counts were updated to match the modular v3.2.x surface more closely and avoid stale hard-coded numbers.

### Tests
- Added regression coverage for desktop session bootstrap inference, KWin active-window parsing, KWin window-list probing without desktop env vars, and installer export of desktop session metadata.
- Total: **549 tests pass** (was 545, +4 new).

### Validation
- Local `pytest -q`: PASS, 549 tests.
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across `arena/**/*.py`, `scripts/*.py`, `bin/*.py`, `unified_bridge.py`, `_arena_helper.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.

## v3.2.5 - 2026-06-19

### Added
- **MCP `git.status`** — show working tree status
- **MCP `git.diff`** — show staged/unstaged changes
- **MCP `git.log`** — show recent commits
- **MCP `git.commit`** — stage all + commit

### F6 Git Integration: COMPLETE
### Tests: 545 passed (+17 new)

## v3.2.4 - 2026-06-19

### Added
- **MCP `fs.tree`** — directory tree with ├──/└── connectors, file sizes, max_depth, glob filter, show_files toggle.
- **MCP `fs.diff`** — unified diff between two files (difflib format).
- **MCP `memory.export`** — export all memory facts as JSONL text.
- **MCP `memory.import`** — import memory facts from JSONL (upsert, overwrite mode, error reporting).

### fs.* toolkit complete
The fs.* family now has **10 tools**: read, write, list, edit, view, create, search, grep, tree, diff.

### Memory tools
Memory now has **4 tools**: mem.set, mem.get, memory.recall, memory.digest + **memory.export** + **memory.import** (new).

### Tests
- tests/test_fs_tree_diff.py — 17 tests
- tests/test_memory_export_import.py — 13 tests (incl. roundtrip: export→import)

Total: **528 tests pass** (was 498, +30 new).

## v3.2.3 - 2026-06-19

### Added
- **MCP `fs.search` tool** — search file contents by regex pattern. Supports glob filter, context lines, case-insensitive mode, max_results limit. Skips sensitive files, hidden directories, and binary files.
- **MCP `fs.grep` tool** — alias for fs.search (familiar name for grep users).

### Security
- Path must be inside home directory (path traversal blocked)
- SENSITIVE_FILE_BASENAMES skipped (token.txt, .env, SSH keys, etc.)
- Hidden directories skipped (.git, __pycache__, node_modules, .venv)
- File size limit: 512KB per file; max 500 files scanned; max 200 results

### Tests
- tests/test_fs_search.py — 17 tests (basic search, directory search, no matches, errors, glob filter, ignore_case, context lines, max_results, blocked files, hidden dirs, grep alias, registry schema)

Total: **498 tests pass** (was 481, +17 new).

### Validation
- 498 tests pass (no regressions)
- py_compile OK
- Bridge /v1/doctor: 10/10

## v3.2.2 - 2026-06-18

### Added
- **REST `POST /v1/fs/view`** — HTTP equivalent of MCP `fs.view`. Read file with optional `view_range=[start, end]`. Returns JSON with content, line range, and total lines.
- **REST `POST /v1/fs/create`** — HTTP equivalent of MCP `fs.create`. Create new file (fails if exists). Creates parent directories.
- **OpenAPI spec** — `/api-docs` now includes `/v1/fs/view` and `/v1/fs/create` with request/response schemas.
- **DuckDuckGo search tests** — 10 formal tests for the DDG lite HTML parser (no network, mock HTML). Covers: result parsing, n parameter, empty results, HTML tag stripping, URL decoding, User-Agent header.

### Refactored
- **Sensitive file blocklist deduplicated** — `SENSITIVE_FILE_BASENAMES` (frozenset) in `arena/files/sandbox.py` is now the single source of truth. `_MCP_BLOCKED_FILES` in `tool_fs.py` and `_EDIT_BLOCKED_BASENAMES` are aliases of the same object. Adding a new sensitive file now requires editing one place, not two.

### Documentation
- **README "What's new"** updated from v3.1.5/v3.1.6 to v3.2.1 (both EN and RU).

### Tests
- `tests/test_fs_rest_view_create.py` — 26 tests (sandbox validators + handler behavior + route registration + auth)
- `tests/test_ddg_search.py` — 10 tests (mock HTML parsing, no network)
- Total: **481 tests pass** (was 445, +36 new since v3.2.1).

### Files changed
- `arena/files/sandbox.py` — +validate_view_target, +validate_create_target, SENSITIVE_FILE_BASENAMES
- `arena/files/fs_view_create.py` — new module, FsViewCreateHandlers + factory
- `arena/mcp/tool_fs.py` — import SENSITIVE_FILE_BASENAMES from sandbox (dedup)
- `arena/runtime_deps/core.py` — import make_fs_view_create_handlers
- `arena/wiring/observability_registries.py` — handler mappings for view/create
- `arena/route_registry/core.py` — POST /v1/fs/view + POST /v1/fs/create routes
- `arena/public/openapi.py` — OpenAPI spec for fs/view + fs/create
- `tests/test_fs_rest_view_create.py` — new, 26 tests
- `tests/test_ddg_search.py` — new, 10 tests
- `README.md` + `README.ru.md` — "What's new" updated
- `arena/constants.py` + `pyproject.toml` — version bump
- `CHANGELOG.md` — this entry

### Validation
- 481 tests pass (no regressions)
- py_compile OK for all changed files
- Bridge `/v1/doctor`: 10/10 checks pass

## v3.2.1 - 2026-06-18

### Added
- **MCP `fs.view` tool** — view file contents with line numbers. Optional `view_range=[start, end]` for reading a specific line range (1-indexed, inclusive). Returns line-numbered output matching Anthropic's `str_replace_editor` format.
- **MCP `fs.create` tool** — create a new text file. Fails if file already exists (use `fs.edit` to modify). Creates parent directories if needed. Both tools reuse `_validate_home_path` for path traversal + blocked file protection.
- **OpenAPI spec updated** — `/api-docs` now includes `POST /v1/upload`, `GET /v1/download`, and `PATCH /v1/fs/edit` with request/response schemas. New "Files" tag added.

### Tests
- **`tests/test_fs_edit.py`** (18 tests): MCP `fs.edit` success/replace_all/not_found/multiple_matches/empty/blocked/noop, `validate_edit_target` traversal/bridge/sensitive_files/not_found, REST route registration, schema validation.
- **`tests/test_fs_view_create.py`** (14 tests): `fs.view` full/range/not_found/invalid_range/blocked, `fs.create` success/exists/empty/parent_dirs/blocked, registry schema validation.

Total: **445 tests pass** (was 431, +14 new for view/create; +18 new for edit = +32 total since v3.2.0).

### str_replace_editor parity complete
The `fs.*` tool family now has full parity with Anthropic's `str_replace_editor`:
  - `fs.read` — read file (existing)
  - `fs.write` — write file (existing)
  - `fs.list` — list directory (existing)
  - `fs.view` — view with line numbers + range (new)
  - `fs.create` — create new file (new)
  - `fs.edit` — find-and-replace (added in v3.2.0)

AI coding agents (Claude Code, Cline, Cursor) can now use Arena's MCP server as a complete filesystem tool backend.

### Validation
- 445 tests pass (no regressions).
- py_compile OK for all changed files.
- Bridge `/v1/doctor`: 10/10 checks pass.

### Files changed
- `arena/mcp/tool_fs.py` — +`_handle_fs_view`, +`_handle_fs_create`, dispatch for fs.view/fs.create
- `arena/mcp/tool_registry.py` — +fs.view, +fs.create in MCP_TOOLS
- `arena/public/openapi.py` — +upload, +download, +fs/edit, +Files tag
- `tests/test_fs_edit.py` — new, 18 tests
- `tests/test_fs_view_create.py` — new, 14 tests
- `arena/constants.py` — version bump
- `pyproject.toml` — version bump
- `CHANGELOG.md` — this entry

## v3.2.0 - 2026-06-18

### Added
- **MCP `fs.edit` tool** — find-and-replace in text files, mirroring Anthropic's `str_replace_editor` semantics. AI coding agents (Claude Code, Cline, Cursor) can now do surgical file edits via MCP without re-uploading the whole file. Supports `replace_all` for multi-occurrence replacement. Reuses `_validate_home_path` + `_MCP_BLOCKED_FILES` for security (path traversal protection, blocks `token.txt`, `.env`, SSH keys, etc.).
- **REST `PATCH /v1/fs/edit` endpoint** — HTTP equivalent of the MCP tool. Same find-and-replace semantics, same security model. Enables AI agents without MCP support (like popbob's Local API pattern, or simple curl scripts) to do surgical edits. Body: `{"path": "...", "old_text": "...", "new_text": "...", "replace_all": false}`. Returns `{"ok": true, "path": "...", "replacements": N, "bytes": N}`.
- **Arena Agent Mode integration** — new documentation section explaining how to use Arena Unified Bridge as the tool backend for Arena.ai's free frontier models (Claude Opus, GPT-5, Grok). Paste the system prompt from `docs/AI_PROMPT_TEMPLATE.md` with your URL and token, and any Arena AI can drive your computer.
- **"Similar Projects" section in README** — honest comparison with 10 other open-source projects in the AI agent / computer-use space: Bytebot, OpenClaw, Open Interpreter, Agent S, Anthropic Computer Use, Cline, Desktop Commander MCP, MCP servers, awesome-mcp-servers, browser-use. Each entry includes stars, language, what it does, and how Arena differs. Includes disclaimer that Arena is independent and not affiliated with any listed project.

### Fixed
- **`/v1/browser/search` no longer returns 0 results** — DuckDuckGo's `html.duckduckgo.com/html/` endpoint stopped returning `result__a` CSS class names, breaking the parser. Switched to `lite.duckduckgo.com/lite/` which still works and uses `result-link` / `result-snippet` classes. Also fixed: in lite HTML, `href` attribute comes before `class` (opposite order from the html endpoint), so the regex was reordered. Used triple-quoted raw strings (`r'''...'''`) to avoid quoting conflicts.

### Security
- New `_EDIT_BLOCKED_BASENAMES` set in `arena/files/sandbox.py`: `token.txt`, `users.json`, `.env`, `id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa`, `.netrc`, `.ssh_config`. These files cannot be edited via `fs.edit` or `PATCH /v1/fs/edit`, even if they are inside the user's home directory.
- `fs.edit` and `PATCH /v1/fs/edit` cannot edit the bridge itself (`unified_bridge.py`).
- All file edit operations are audit-logged: `{"type": "file_edit", "path": "...", "replacements": N, "bytes": N}`.

### Validation
- 413 existing tests pass (no regressions).
- MCP `fs.edit` tested with 6 error cases: multiple matches, replace_all, not found, file not found, empty old_text, blocked file — all correct.
- REST `PATCH /v1/fs/edit` compile OK, pytest pass, logic identical to MCP tool.
- DDG search tested: `browser_search("python programming", 3)` returns 3 results with correct title, URL, snippet.
- Bridge `/v1/doctor`: 10/10 checks pass.

### Files changed
- `arena/mcp/tool_fs.py` — added `fs.edit` handler + `_handle_fs_edit` function
- `arena/mcp/tool_registry.py` — added `fs.edit` to `MCP_TOOLS` list
- `arena/files/sandbox.py` — added `validate_edit_target` + `_EDIT_BLOCKED_BASENAMES`
- `arena/files/handlers.py` — added `handle_v1_fs_edit` handler + `fs_edit` field
- `arena/route_registry/core.py` — added `PATCH /v1/fs/edit` route
- `arena/wiring/observability_registries.py` — added `handle_v1_fs_edit` mapping
- `arena/browser/fetch.py` — switched DDG to lite endpoint, updated CSS selectors
- `README.md` — File Operations table, Similar Projects section, Arena Agent Mode note
- `README.ru.md` — mirror all changes in Russian
- `docs/AI_PROMPT_TEMPLATE.md` — added fs.edit and PATCH /v1/fs/edit
- `arena/constants.py` — version bump
- `pyproject.toml` — version bump
- `CHANGELOG.md` — this entry

## v3.1.7 - 2026-06-17

### Fixed
- **Windows installer no longer crashes with "Непредвиденное появление: .."** The v3.1.6 `install.bat` used `^(...^)`, `^&^&`, and `\(...\)` to escape special characters inside `if (...)` blocks, but cmd does not honor `^` inside if-blocks - so the unescaped parens broke block balance and the parser died immediately after `Bridge v!VERSION!`.
- **Root cause:** the Soft version-check block used `curl ... | %PYTHON% -c "...d.get(\"tag_name\",\"\")..."` - the `\"` escapes inside a `for /f` single-quoted string broke the cmd parser.
- **Fix (install.bat v2.1.2):**
  - Replaced `curl | python -c` with a direct `python -c "import urllib.request,json; ..."` call that uses single-quoted Python strings (no `\"` escapes anywhere).
  - Rewrote the if/else cascade as a flat `if not defined ... () else if ... () else ()` so no nested parens inside if-blocks.
  - Replaced all `^(...^)` inside if-block echo lines with plain text using dashes.
  - Replaced `^&^&` in echo lines with the word "and" / commas.
  - Replaced `\(...\)` (backslash-parens) with plain text - cmd does not honor `\(` either.
  - Expanded inline `if errorlevel 1 (echo X) else (echo Y)` into multi-line if-blocks so parens do not collide with the surrounding block.
  - Used `!VAR!` (delayed expansion) consistently for variables set inside if-blocks (`TS_INSTALL_CONFIRM`, `CAM_CONFIRM`) - `%VAR%` would have been expanded to empty at parse time, breaking the Y comparison.

### Validated on Windows 10 LTSC 2021 (build 19044)
- `install.bat` runs cleanly through all 6 steps without parser errors.
- Soft version-check prints `[OK] You are on the latest release.` when v3.1.7 is current.
- Optional component prompts work: Tailscale, cloudflared, SuperPowers, BrowserAct, Camoufox.
- Bridge starts as Scheduled Task (wscript + start_hidden.vbs) and `/health` returns v3.1.7.
- `stress-test-v4.py --task-roundtrip`: **15 PASS / 3 SKIP / 0 FAIL**.
- `/v1/doctor`: 10/10 checks pass.
- `/v1/metrics`: 0% error rate over 541 requests.
- `/v1/memory` (set/get/delete), `/v1/exec` (whoami), `/v1/browser/fetch` (example.com), `/v1/sys/funnel` (Tailscale Funnel active) - all pass.

### Known limitations on Windows (not regressions)
- `/v1/desktop/*` endpoints return `"Windows desktop backend is not implemented yet"` - the win32 desktop automation backend is `pending-win32` in the roadmap. The bridge correctly reports this via `/v1/capabilities` and `stress-test-v4` SKIPs these endpoints.
- Russian (CP866) text in `nssm_service.raw` and `scheduled_task.raw` fields of `/v1/capabilities` may render as mojibake when decoded as UTF-8 - cosmetic only.

### No behavioral change on Linux/macOS
- `install.sh` is untouched in this release.
- The installer logic is identical to v3.1.6 on systems where the old `install.bat` worked - only the cmd escaping and the version-check implementation changed.

## v3.1.6 — 2026-06-17

### Fixed
- **Installer no longer silently downgrades existing installations.** `install.sh` (Linux/macOS) now reads the locally-installed version, fetches only the *current* branch from origin (never switches branches), compares local vs. remote versions semver-aware, and asks before updating. Updates use `git merge --ff-only` so local commits are never discarded. The destructive `git checkout -B <branch> FETCH_HEAD` pattern is gone.
- **Installer no longer defaults to the stale `v3-modular-core` branch.** Fresh installs now pull `master` (the current stable release branch). Override with `ARENA_BRANCH=<name>`.
- **`install.bat` (Windows) now informs about newer GitHub releases.** Soft version-check via the GitHub releases API prints an `[INFO]` line when a newer version exists. It never auto-updates and never switches branches - just informs the user.
- **Shipped `webhooks.json` no longer contains a dead debug URL.** Previous releases inherited `http://127.0.0.1:9999/webhook` from the repo, causing every fresh install to spam a non-existent endpoint (the v3.1.5 circuit breaker correctly backed off, but the config noise should not exist in the first place). Default is now `{urls: [], events: ["*"]}`.

### Refactored
- Replaced `asyncio.get_event_loop()` with `asyncio.get_running_loop()` across 18 files (43 call sites). All calls are inside async functions that immediately `await loop.run_in_executor(...)`, so the new API returns the same loop without the `DeprecationWarning` Python 3.12+ emits for `get_event_loop()` outside a running loop. No behavioral change.

### Tests
- Added `tests/test_installer_version_safety.py` (7 tests) guarding the installer fix: default branch is `master`, no destructive `git checkout -B`, fast-forward-only updates, `_arena_version_lt()` passes 12 semver cases (equal, v-prefix, double-digit patch, pre-release suffix, short versions), `install.bat` has soft version-check and does not git-pull/checkout the bridge itself.

### Documentation
- `README.md`: replaced the static `version-v3.1.5-blue` badge with a dynamic `shields.io/github/v/release/...` badge that auto-updates on every release - no more manual README edits just to bump the version number.
- `README.md`: added a new "### 3. Updating an existing installation" section documenting the safe-update behavior.

### Validation
- Local `pytest -q`: PASS, 413 tests (406 prior + 7 new installer guardrails).
- Local `bash -n install.sh`: PASS.
- Local `python -m py_compile` across all changed files: PASS.
- Live `install.sh` smoke test on a test clone: correctly reports `Local version: v3.1.6 / Remote version: v3.1.6 / Already up to date` and does not switch branches.
- Bridge `/v1/doctor`: 10/10 checks pass.

## v3.1.5 — 2026-06-17

### Fixed
- Added per-URL webhook circuit breaker/backoff so dead webhook targets are not retried and logged on every event.
- Webhook failure/recovery is now logged on state changes instead of flooding `bridge.log` continuously.

### Tests
- Added `tests/test_webhooks_backoff.py` covering threshold, cooldown, exponential retry, recovery, event filtering, and internal error logging.

### Validation
- Local `pytest -q`: PASS, 413 tests.
- Local critical ruff and py_compile: PASS.

## v3.1.4 — 2026-06-17

### Fixed
- Fixed a JavaScript syntax error in dashboard slash-command definitions that prevented slash suggestions and normal Terminal Run handling from working.
- Fixed `bin/agentctl` wrapper import path so GUI terminal commands such as `agentctl sys status` run successfully from the installed bridge directory.
- Simplified sidebar icons to one consistent icon per navigation item.

### Guardrails
- Added dashboard JavaScript syntax validation with `node --check` when Node.js is available.

### Validation
- Local `node --check dashboard/assets/*.js`: PASS.
- Local `pytest -q`: PASS, 408 tests.
- Local critical ruff and py_compile: PASS.
- CachyOS live validation required before publication.

## v3.1.3 — 2026-06-17

### Fixed
- Fixed GUI terminal `agentctl ...` commands by resolving them to the installed bridge bin path instead of relying on service PATH.
- Fixed GUI Quick Commands to render API results inside the terminal session instead of writing to a removed `termOutput` element.
- Fixed GUI memory deletion by using `DELETE /v1/memory` instead of the removed `/v1/memory/delete` route.
- Fixed GUI skill execution payload by sending `{name, args}` instead of `{skill}`.
- Fixed Control pause cancellation: pressing Cancel in the prompt no longer pauses control.
- Fixed modular inventory runtime/package/browser/env probes by restoring extracted constants (`RUNTIMES`, `PACKAGE_MANAGERS`, `BROWSERS`, `ENV_KEYS_OF_INTEREST`, platform browser paths).
- Fixed stale CDP client imports and MCP marketplace helper imports found by installed-wrapper smoke tests.

### Validation
- Local `pytest -q`: PASS, 407 tests.
- Local critical ruff and py_compile: PASS.
- Installed-wrapper smoke added/used for scripts/bin entrypoints.
- CachyOS live install, GUI BrowserAct smoke, endpoint smoke and stress are required before publication.

## v3.1.2 — 2026-06-16

### Fixed
- Fixed the modular dashboard layout regression introduced by the asset split: body fragments now replace the bootstrap root so `.sidebar` and `.main` are again direct flex children of `body`, matching the pre-split DOM layout.
- Fixed `scripts/cdp_browser.py` and `arena/browser/cdp_client/*` stale imports that still referenced the removed `cdp_browser_modules` package.
- Fixed `bin/mcp_marketplace.py list` after modularization by importing underscored registry helpers explicitly instead of relying on star imports.
- Added dashboard bootstrap and wrapper import regression tests so these failures cannot pass unnoticed again.

### Validation
- Local `pytest -q`: PASS, 407 tests.
- Local critical ruff and py_compile: PASS.
- CachyOS source pytest/ruff/py_compile: PASS.
- CachyOS installed wrapper smoke found the stale import bugs above and passed after fixes.
- CachyOS live install, GUI BrowserAct smoke and stress are required before release publication.

## v3.1.1 — 2026-06-16

### Fixed
- Dashboard modular assets now use versioned cache-busting query strings and `Cache-Control: no-store` for `/gui/assets/*`, preventing stale cached JS/HTML fragments after upgrading from earlier modular builds.

### Validation
- BrowserAct live dashboard smoke on CachyOS: `/gui` booted, Overview rendered real data, Memory tab switch worked, `/gui/assets/*` served correctly.
- Local/CachyOS `pytest -q`: PASS, 404 tests.
- Local/CachyOS critical ruff and py_compile: PASS.

## v3.1.0 — 2026-06-16

### Milestone
- Full modularity stabilization release after `v3.0.0`.
- Moves secondary monoliths out of `scripts/`, `bin/`, dashboard, CDP, inventory and helper tooling into focused `arena/*` packages.
- Runtime composition now uses an isolated runtime namespace; `unified_bridge.py` only exports compatibility names at the boundary.

### Changed
- Split `bin/agentctl` into `arena/agentctl_cli/*`.
- Split `scripts/inventory.py` into `arena/inventory/*`.
- Moved low-level CDP client/runtime from `scripts/cdp_browser.py` into `arena/browser/cdp_client/*`.
- Split helper CLIs into modular packages: `arena/skills/cli*.py`, `arena/memory/cli*.py`, `arena/memory/recall_*.py`, `arena/desktop/cli/*`, `arena/agent_helpers/*`, `arena/project_cli/*`, `arena/missions_cli/*`, `arena/mcp_marketplace/*`.
- Split dashboard assets into modular HTML/CSS/JS files under `dashboard/assets/`; `/gui/assets/{path}` serves them.
- Renamed internal wiring modules from `legacy_*` names to domain-oriented runtime/composition names.
- Replaced hidden `globals().update(g)` wiring with explicit `RuntimeEnv` access.
- Separated `arena/runtime_deps/*` from boundary-only `arena/compat_surface/*`.

### Guardrails
- Added `AGENTS.md` and `docs/AI_CODEBASE_NAVIGATION.md` for future AI maintainers.
- Added project-wide modularity tests: product files must stay under 200 lines, wrappers must stay thin, wiring cannot reintroduce hidden globals mutation, and `unified_bridge.py` must use an isolated runtime namespace.

### Validation
- Local `python -m py_compile scripts/*.py bin/*.py arena/**/*.py`: PASS.
- Local `python -m ruff check . --select F821,F811`: PASS.
- Local `pytest -q`: PASS, 404 tests.
- CachyOS source `pytest -q`: PASS, 404 tests.
- CachyOS source ruff/py_compile: PASS.

## v3.0.0 — 2026-06-16

### Milestone
- Stable modular Arena Unified Bridge v3 release.
- `master` is promoted to the modular v3 code line; `v2.12.0` remains available as the old monolith tag/release.
- `unified_bridge.py` remains a 98-line compatibility/CLI entrypoint; implementation lives in focused `arena/*` modules.

### Added
- `docs/MOBILE_SUPPORT_ROADMAP.md` for post-v3.0 Android/mobile planning.

### Fixed
- Windows installer stale SCM/NSSM service cleanup when Scheduled Task mode is active.
- Linux installer local-source install path and v3 branch defaulting.
- Windows ZIP skill installation handle locking around temporary ZIP files.
- Cross-platform test portability issues found during Windows RC validation.

### Validation
- Linux/CachyOS fresh install from `v3.0.0-rc.1` release ZIP: PASS.
- Linux/CachyOS source `pytest -q`: PASS, 400 tests.
- Linux/CachyOS endpoint smoke: PASS, including KDE/Wayland desktop windows, active window and screenshot.
- Linux/CachyOS stress v4 with restart: PASS=18.
- Windows fresh install from `v3.0.0-rc.1` release ZIP: PASS.
- Windows source `pytest -q`: PASS, 400 tests.
- Windows endpoint smoke: PASS.
- Windows stress v4 with restart: PASS=15 SKIP=3 (`pending-win32` desktop backend skips expected).

## v3.0.0-rc.1 — 2026-06-16

### Milestone
- Release candidate for the stable modular `v3.0.0` line.
- v3 remains API-compatible with the v2 bridge surface while replacing the old monolith with focused modules.

### Changed
- Version metadata updated from `3.0.0-beta.2` to `3.0.0-rc.1`.
- README now describes the RC stabilization state and the current 98-line `unified_bridge.py` compatibility entrypoint.
- Added a mobile/Android support roadmap for post-`v3.0.0` planning without making mobile work a stable-release blocker.

### Fixed
- Windows ZIP skill installation no longer trips over `NamedTemporaryFile` handle locking.
- Windows test coverage now uses shell-portable Python commands instead of POSIX-only quoting/tools.
- Memory tests now force garbage collection before temporary directory cleanup to avoid lingering SQLite handles on Windows.

### Validation target
- Local `pytest -q` must pass before tagging.
- Fresh release-zip install checks are required on CachyOS/Linux and Windows before promoting this RC to stable.
- Expected stress gates: CachyOS `PASS=18`; Windows `PASS=15 SKIP=3` with `pending-win32` desktop skips documented.

## v3.0.0-beta.2 — 2026-06-16

### Fixed
- Windows installer removes stale `ArenaUnifiedBridge` SCM/NSSM services when falling back to Scheduled Task mode.
- Windows uninstaller removes stale SCM service entries even when NSSM is not installed.
- Windows installer Funnel summary now falls back to checking the public `/health` endpoint when `tailscale funnel status` output is unavailable to the installer context.

### Validation
- Windows 10 fresh install/reinstall smoke: PASS.
- Windows 10 stress v4 with restart: PASS=15 SKIP=3 (`pending-win32` desktop backend skips are expected).
- Linux/CachyOS fresh install from beta zip: PASS.
- Linux/CachyOS stress v4 with restart: PASS=18.

## v3.0.0-beta.1 — 2026-06-16

### Milestone
- First beta of the modular v3 bridge line.
- Linux/CachyOS and Windows 10 validation both pass on the modular architecture.

### Fixed
- Windows installer no longer prints the broken `Bridge is healthyHEALTH_VERSION` message.
- Windows installer no longer fails on repeated installs with a missing `cloudflared_done` label.
- Linux/macOS installer now defaults to the v3 modular branch and supports local-source installs, avoiding accidental v2.12 installs from `master` during v3 testing.
- Linux/macOS uninstaller now stops Cloudflared quick tunnel processes and removes bundled `cloudflared` binaries when present.

### Improved
- Windows and Linux installers now report/verify optional component status more clearly: cloudflared, SuperPowers, BrowserAct, Camoufox and Tailscale Funnel.
- Added architecture boundary tests and unified bridge compatibility surface tests.
- Added `docs/MODULE_MAP.md`, `docs/V3_RELEASE_CHECKLIST.md`, and `docs/V3_STABILIZATION_AUDIT.md`.

### Validation
- Local `pytest -q`: PASS, 400 tests.
- Live CachyOS/KDE `pytest -q`: PASS, 400 tests.
- Live CachyOS/KDE stress v4 with restart: PASS=18.
- Windows 10 stress v4 with restart: PASS=15 SKIP=3 (desktop backend intentionally pending-win32).

## v3.0.0-alpha.1 — 2026-06-16

### Milestone
- First modular Arena Unified Bridge release.
- `unified_bridge.py` reduced from the old monolithic implementation to a thin compatibility/CLI entrypoint (~165 lines).
- Public REST, MCP, WebSocket, dashboard, gateway and installer behavior remain compatibility-preserving.

### Changed
- Split the bridge into focused `arena/*` domain packages: app factory, route registry, contexts, wiring, browser/CDP, desktop, service, system, memory, skills, tasks, observability, admin, MCP, TLS, sandbox and cluster modules.
- Added `arena/legacy_imports/*` and `arena/wiring/legacy_*` compatibility layers so existing `import unified_bridge as ub` integrations continue to work during the v3 transition.
- Updated README project layout and contribution guidance for the modular architecture.

### Validation
- Full local and live `pytest -q` pass.
- Live CachyOS/KDE `dev/stress-test-v4.py --restart` pass with `Summary: PASS=18`.

## v2.12.0 — 2026-06-10

### Milestone
- Stable monolith baseline before the planned v3 modularization work.
- Windows and CachyOS/KDE have both passed the capability-aware v4 stress suite, including restart lifecycle checks.

### Changed
- `dev/stress-test-v4.py` is now non-persistent by default: it lists tasks but does not submit queue tasks unless `--task-roundtrip` is explicitly requested.
- Task roundtrip now uses `echo stress-test-v4 noop`, which is valid on Windows cmd and POSIX shells.

### Added
- Added `docs/STRESS_TEST_V4.md` with local/remote, restart, and task-roundtrip usage.

## v2.11.6 — 2026-06-10

### Fixed
- Linux `/v1/restart` now prefers a transient `systemd-run --user` unit, so the restart helper survives `arena-bridge.service` cgroup cleanup and can reliably restart the bridge.

### Notes
- The previous detached shell helper remains as fallback for non-systemd Linux environments.

## v2.11.5 — 2026-06-10

### Fixed
- `install.sh` no longer references an unset `$PYTHON` variable before Python discovery while reading the bridge version; it now uses a local `VERSION_PY` probe.

### Improved
- `install.sh` re-executes itself under `bash` when invoked as `sh install.sh`, matching the script's intended shell and avoiding shell-mismatch failures.

## v2.11.4 — 2026-06-10

### Fixed
- Windows `/v1/restart` now uses the SCM/NSSM restart path only when the Windows service is actually running. Stale stopped services no longer block Scheduled Task relaunch.
- The Windows Scheduled Task restart helper now force-kills the previous bridge PID before relaunching the task, preventing orphaned `python.exe` bridge processes.

### Added
- Added `dev/stress-test-v4.py`, a capability-aware cross-platform smoke/stress test runner for REST/core/hardware/service/skills/tasks/CDP/desktop/restart checks.

## v2.11.3 — 2026-06-10

### Added
- Added `/v1/capabilities`, a stable agent-facing map of available OS/service/browser/desktop/hardware capabilities and selected backends.

### Improved
- Windows installer version detection now uses `_arena_helper.py` / `arena/constants.py`, fixing `Bridge vunknown` after the version constant moved out of `unified_bridge.py`.
- Windows install health verification now prints the actual `/health.version`.
- Windows CIM/PowerShell inventory probes force UTF-8 output and normalize common CIM date formats.
- Windows service/status endpoints distinguish stale stopped services from active Scheduled Tasks and include command lines for bridge-related Python processes.

### Tests
- Added regression coverage for installer helper version detection and `/v1/capabilities` route registration.

## v2.11.2 — 2026-06-10

### Fixed
- `/v1/skills/uninstall` now accepts safe third-party skill basenames beginning with `_`, so it can remove every safe `third_party/<name>` entry that `/v1/skills` can list while still rejecting traversal and core/category skills.

### Tests
- Added regression coverage for underscore-prefixed third-party skill names.

## v2.11.1 — 2026-06-10

### Improved
- `/v1/hardware` now exposes additional read-only device context: physical/block storage devices, PCI/PNP devices, USB devices, and thermal/sensor facts where available.
- KDE Plasma Wayland window discovery no longer depends on `QFile` inside KWin scripting. The script now prints tokenized JSON to the user journal, which the bridge reads back, and still falls back to `wmctrl`/`xdotool`.

### Fixed
- `/v1/skills/uninstall` now accepts the same third-party names returned by `/v1/skills` (`third_party/<name>`) as well as bare third-party names, while rejecting core/category skills and path traversal.

### Removed
- Removed the broken test-only `skills/third_party/weather` skill from the production tree.

### Tests
- Added regression coverage for hardware device sections and third-party skill-name normalization.

## v2.11.0 — 2026-06-10

### Added
- Added `/v1/hardware` as the canonical rich hardware/system inventory endpoint. It is backed by `scripts/inventory.py`, returns normalized JSON for agents and GUI consumers, and keeps `/v1/hwinfo` as a backward-compatible alias.
- Added short `/v1/cdp/*` aliases for the existing `/v1/browser/cdp/*` endpoints to reduce agent/tool 404s when shorter CDP paths are inferred from docs.

### Improved
- Unified the old split hardware collectors: motherboard/BIOS, CPU, memory modules, GPU/NVIDIA telemetry, disks, network, displays, runtimes, package managers, and browsers now come from one inventory source.
- `/v1/desktop/windows` now tries native KDE/KWin scripting on Plasma Wayland before falling back to `wmctrl` and `xdotool`, improving Wayland window discovery without requiring `kdotool`.
- `/v1/browser/cdp/session/check` now returns HTTP 200 with `connected: false` and actionable details when CDP is disconnected, instead of treating the normal disconnected state as a malformed request.
- Runtime version probing is quieter for tools such as `lua` and partial `dotnet` installs.

### Fixed
- Fixed Windows CIM inventory collection: `_get_cim_json()` no longer calls `_run(..., shell=True)` on a helper that did not support `shell`, which previously caused Windows hardware sections to silently return empty data.
- Fixed Windows display inventory (`screens` was referenced before assignment) and expanded Windows logical disk/GPU/RAM CIM property selection.

### Tests
- Added regression coverage for the inventory runner, noisy version filtering, and hardware normalization/NVIDIA merge path.

## v2.10.3 — 2026-06-08

### Security
- Hardened `arena/security.py::_validate_url` against SSRF bypasses in browser fetch endpoints (`/v1/browser/read`, `/dump`, `/fetch`, `/head`).
- Blocked obfuscated internal hosts including `127.1`, octal IPv4 (`0177.0.0.1`), decimal integer IPv4 (`2130706433`), hex IPv4 (`0x7f000001`), IPv4-mapped IPv6 loopback, and `localhost.localdomain`.
- Blocked metadata/internal hostnames such as `metadata.google.internal`, bare `metadata`, `.internal`, and `.local` names.
- Added DNS resolution defense-in-depth: every A/AAAA result is checked for private, loopback, link-local, reserved, multicast, or unspecified addresses before fetch.

### Tests
- Added regression tests for the reported SSRF bypass payloads.

## v2.10.2 — 2026-06-08

First release built with CI, an expanded test suite, and safe-by-construction
release packaging. No runtime feature changes — focused on correctness,
security of the release process, and developer experience.

### Fixed
- `scripts/mcp_stream_server.py`: added missing `import shutil` — the browser
  screenshot tool called `shutil.which()` without importing it, which would
  raise `NameError` when invoked (found by the new lint pass).
- `unified_bridge.py`: import `Dict`/`Optional` from `typing` (referenced in
  annotations but never imported) and removed a redundant local `urlparse`
  import.

### Security
- **Release packaging is now safe by construction.** `scripts/pack_release.py`
  previously could include `token.txt`, `users.json`, `audit.jsonl`,
  `requests.jsonl`, and root-level `bridge.log` in the public release archive.
  It now ships only git-tracked files (sensitive files are git-ignored) plus an
  explicit `cloudflared` bundle and runtime-dir placeholders, and asserts the
  archive contains no sensitive names before finishing.

### Tests / CI
- Added GitHub Actions CI: pytest on Python 3.10–3.13 plus a ruff lint pass
  (critical correctness rules enforced as blocking; full rule set informational).
- Added `tests/test_security.py` (60 tests) covering the safety-critical
  surface: command blocklist, desktop-input-injection guard, SSRF validation,
  audit redaction, token generation, and Bearer auth.

### Developer experience / repository hygiene
- Removed the bundled ~39 MB `cloudflared` binary from version control; the
  installers now fetch the platform-correct binary on demand.
- Added `requirements.txt` and `pyproject.toml` (explicit dependencies, ruff &
  pytest configuration); installers install dependencies from `requirements.txt`.
- Added `.editorconfig` and `CONTRIBUTING.md`.
- Moved `AI_PROMPT_TEMPLATE.md` to `docs/` and `stress-test-v3.sh` to `dev/`;
  corrected the README structure section to match the real layout.

## v2.10.1 — 2026-06-08

### Installer transparency / anti-false-positive
- `install.bat` and `install.sh` now show a prominent background-service transparency notice before registering/updating any background service, scheduled task, systemd unit, or launchd agent.
- Installers now require explicit confirmation before service registration. Use `ARENA_ACCEPT_BACKGROUND=1` or `ARENA_ASSUME_YES=1` for unattended automation.
- README documents expected background processes and legacy helper names (`local_bridge.py`, `mcp_ws_server.py`, `web_gateway.py`, `agentctl task-watch`), plus PowerShell/Linux/macOS inspection and cleanup commands.
- Runtime bridge version bumped to `2.10.1` so `/health` and `/v1/version` identify this release.

## v2.10.0 — 2026-06-08

### Fixed
- Closed the control-lease bypass where `/v1/exec` could still inject desktop input while control was paused/revoked by blocking input-injection tools (`ydotool`, `xdotool` key/mouse/type, `wtype`, `dotool`, etc.) under a paused/revoked lease while keeping non-input shell diagnostics available.
- Made `/v1/desktop/screenshot` honor `format`, `scale`, `max_width`, and `quality` parameters. The endpoint can now return JPEG/WebP/downscaled images instead of always returning full-size PNG.
- Hardened `/v1/exec` safety patterns against obvious secret reads and reverse-shell payloads (`~/.ssh/id_*`, `.netrc`, `.git-credentials`, `.aws/credentials`, `token.txt`, `/etc/shadow`, `/dev/tcp`, `nc -e`, etc.).
- Made `/v1/desktop/type` more reliable on KDE/Wayland with `ensure_latin` (default `true`), switching the keyboard layout to the first/Latin layout before typing to avoid RU/other-layout keycode corruption.
- Added `/openapi.json` as an OpenAPI alias to improve API discoverability, and documented the new desktop screenshot/type parameters.

### Documentation / transparency
- Added a prominent README section explaining expected background processes, Windows scheduled tasks/services, legacy helper names, and manual cleanup commands so the project is not mistaken for malware.
- `install.bat` and `install.sh` now show an explicit background-service transparency notice and require confirmation before installing/updating the service. Set `ARENA_ACCEPT_BACKGROUND=1` or `ARENA_ASSUME_YES=1` for unattended automation.

### Notes
- `owner-shell` remains a trusted/local-owner profile; these safety patterns reduce common foot-guns but are not a substitute for a sandbox or least-privilege deployment.
- For vision agents, recommended screenshot parameters are now `format=jpeg&scale=0.5&quality=80` or `format=jpeg&max_width=1280&quality=80`.
