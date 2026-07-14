// Mobile: screenshot pipeline v2 (v3.83.0).
//
// Splits the screenshot / gesture handling out of 30-mobile.js so each
// concern is easy to read. Depends on globals defined in 30-mobile.js:
//   _mobileSelectedSerial, _mobileNativeWidth/Height,
//   _mobileShownWidth/Height, _mobileScreenshotBusy,
//   _mobileScreenshotBlobUrl, _mobileScreenshotGen, _mobileLastSnapAt,
//   mobileShowError(), _fmtBackendError().

// --- Screenshot settings (persisted in localStorage) --------------------
const _MOBILE_LS_KEY = "arena.mobile.screen.settings.v1";

// Screen settings persist in localStorage under this shape. v3.83.3
// renamed `max_width` → `max_size` (long side) so landscape orientation
// no longer collapses to a tiny image — see arena/mobile/screenshot.py
// docstring. Old settings are migrated silently below.
const MOBILE_SCREEN_DEFAULTS = {
  format: "webp",      // webp | jpeg | png
  quality: 82,         // 1..100 (WebP goes to 100, JPEG capped at 95)
  max_size: 720,       // 0 = native resolution, no downscale
  live_hz: 0.67,       // Hz — 0 = off. Default = one frame per 1.5s.
};

function mobileScreenSettingsLoad() {
  try {
    const raw = localStorage.getItem(_MOBILE_LS_KEY);
    if (!raw) return {...MOBILE_SCREEN_DEFAULTS};
    const parsed = JSON.parse(raw);
    // Migrate old key: v3.83.2 stored `max_width`, v3.83.3 uses
    // `max_size` (long side). Silently promote so existing users
    // don't lose their preferred image size.
    if (parsed.max_width && !parsed.max_size) {
      parsed.max_size = parsed.max_width;
      delete parsed.max_width;
    }
    return {...MOBILE_SCREEN_DEFAULTS, ...parsed};
  } catch (_) {
    return {...MOBILE_SCREEN_DEFAULTS};
  }
}

function mobileScreenSettingsSave(patch) {
  const merged = {...mobileScreenSettingsLoad(), ...(patch || {})};
  try { localStorage.setItem(_MOBILE_LS_KEY, JSON.stringify(merged)); }
  catch (_) { /* private-mode / quota — non-fatal */ }
  return merged;
}

// Populate the settings row inputs from the saved values. Called after
// the tab HTML mounts so we don't fight the browser's own restore.
function mobileScreenSettingsMount() {
  const s = mobileScreenSettingsLoad();
  const fmt = document.getElementById("mobileFormat");
  const qual = document.getElementById("mobileQuality");
  const qualLabel = document.getElementById("mobileQualityValue");
  const width = document.getElementById("mobileWidth");
  const live = document.getElementById("mobileLiveToggle");
  const rate = document.getElementById("mobileLiveRate");
  if (fmt) fmt.value = s.format;
  if (qual) qual.value = String(s.quality);
  if (qualLabel) qualLabel.textContent = String(s.quality);
  if (width) width.value = String(s.max_size);
  if (rate) rate.value = String(s.live_hz);
  if (live) live.checked = s.live_hz > 0;
}

// Called from every input's onchange handler.
function mobileScreenSettingsFromUi() {
  const fmt = (document.getElementById("mobileFormat") || {}).value || "webp";
  const qual = parseInt((document.getElementById("mobileQuality") || {}).value, 10);
  const width = parseInt((document.getElementById("mobileWidth") || {}).value, 10);
  const rate = parseFloat((document.getElementById("mobileLiveRate") || {}).value);
  const live = !!(document.getElementById("mobileLiveToggle") || {}).checked;
  const patch = {
    format: ["webp", "jpeg", "png"].includes(fmt) ? fmt : "webp",
    quality: Number.isFinite(qual) ? Math.max(1, Math.min(100, qual)) : 82,
    max_size: Number.isFinite(width) ? Math.max(0, Math.min(4096, width)) : 720,
    live_hz: (live && Number.isFinite(rate)) ? Math.max(0, Math.min(5, rate)) : 0,
  };
  mobileScreenSettingsSave(patch);
  const qualLabel = document.getElementById("mobileQualityValue");
  if (qualLabel) qualLabel.textContent = String(patch.quality);
  // Restart live poll with the new rate.
  mobileLiveApply();
  // Refresh once immediately so the user sees the effect of the setting.
  mobileScreenshot();
  return patch;
}

// --- Screenshot fetch --------------------------------------------------
//
// Content-hash dedup: identical frames don't replace the <img> src, which
// eliminates the ~50ms decode/repaint flicker in Live view when the phone
// screen isn't actually changing. We compute a fast 64-bit FNV-1a hash
// over the first 8 KB of the blob — that catches every real difference
// on a phone UI (WebP encoder is deterministic given identical input).

let _mobileLastHash = null;
let _mobileConsecutiveDupes = 0;
// Rolling window of the last N frame-end timestamps so the meta line
// can show a real measured FPS. Users complained they couldn't tell
// what Live-view was actually delivering — cache + tap-guard hide the
// actual throughput. This is that number, straight from performance.now().
const _mobileFrameStamps = [];
const _MOBILE_FPS_WINDOW = 8;

// Abort controller for the in-flight screenshot fetch. When the user
// takes another action (device switch, tab hidden), we call this to
// cancel the in-flight /screenshot request. Note: unlike v3.83.3 we
// do NOT auto-abort our own predecessor from mobileScreenshot() —
// the busy-guard ensures only one is in flight at a time, and
// self-cancellation was producing a permanent AbortError stream.
// (Live-view state — _mobileLivePendingTimeout, _mobileLivePausedByHidden —
// lives lower in this file with the chain-based scheduler.)
let _mobileFetchController = null;

async function _mobileBlobHash(blob) {
  // Fast path: use a small prefix. For 720×1600 WebP the compressed
  // stream diverges within the first few hundred bytes for any real
  // pixel change, so 8 KB is overkill.
  const size = Math.min(blob.size, 8192);
  const buf = await blob.slice(0, size).arrayBuffer();
  const view = new Uint8Array(buf);
  let h = 0xcbf29ce484222325n;
  const p = 0x100000001b3n;
  for (let i = 0; i < view.length; i++) {
    h = BigInt.asUintN(64, (h ^ BigInt(view[i])) * p);
  }
  return h.toString(16) + ":" + blob.size;
}

async function mobileScreenshot() {
  if (!_mobileSelectedSerial) return;
  if (_mobileScreenshotBusy) return;
  _mobileScreenshotBusy = true;

  const settings = mobileScreenSettingsLoad();
  const img = document.getElementById("mobileScreenshotImg");
  const meta = document.getElementById("mobileScreenshotMeta");
  const loading = document.getElementById("mobileScreenshotLoading");
  if (loading) loading.style.display = "";

  // Fresh AbortController per fetch so the caller can cancel this
  // specific request (device switch, tab hidden) without racing
  // against a future fetch. We do NOT cancel our own previous fetch
  // here — the busy-guard above already ensures only one is in flight
  // at a time. The v3.83.3 code cancelled its own predecessor via
  // this controller, which combined with setInterval-based Live-view
  // produced a permanent stream of AbortErrors.
  _mobileFetchController = new AbortController();
  const controller = _mobileFetchController;

  const started = performance.now();
  try {
    const params = new URLSearchParams({
      max_size: String(settings.max_size),
      quality: String(settings.quality),
      format: settings.format,
    });
    const url = BASE
      + "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/screenshot?" + params.toString();
    const resp = await fetch(url, {headers, cache: "no-store", signal: controller.signal});
    if (!resp.ok) {
      let msg = "HTTP " + resp.status;
      try {
        const body = await resp.text();
        try {
          const j = JSON.parse(body);
          msg = _fmtBackendError("screenshot failed", j);
        } catch (_) {
          if (body) msg += "\n" + body.slice(0, 400);
        }
      } catch (_) {}
      if (meta) meta.textContent = "screenshot failed";
      mobileShowError("Screenshot failed", msg);
      return;
    }
    _mobileShownWidth = parseInt(resp.headers.get("X-Arena-Mobile-Width") || "0", 10);
    _mobileShownHeight = parseInt(resp.headers.get("X-Arena-Mobile-Height") || "0", 10);
    const srcW = parseInt(resp.headers.get("X-Arena-Mobile-Source-Width") || "0", 10);
    const srcH = parseInt(resp.headers.get("X-Arena-Mobile-Source-Height") || "0", 10);
    if (srcW > 0 && srcH > 0) {
      _mobileNativeWidth = srcW;
      _mobileNativeHeight = srcH;
    }
    // v3.83.4: latency breakdown from the bridge so the meta line
    // shows where time is actually spent (capture on device vs
    // encode on bridge). Also expose the capture-mode ("raw"/"png")
    // so it's obvious when the fast path is engaged.
    const captureMs = parseInt(resp.headers.get("X-Arena-Mobile-Capture-Ms") || "0", 10);
    const encodeMs  = parseInt(resp.headers.get("X-Arena-Mobile-Encode-Ms")  || "0", 10);
    const captureMode = resp.headers.get("X-Arena-Mobile-Capture-Mode") || "";
    const secureFrame = resp.headers.get("X-Arena-Mobile-Secure-Frame") === "1";
    const blob = await resp.blob();

    // Content-hash dedup: identical blob → keep the current <img>.
    // This is what stops the Live-view flicker.
    const hash = await _mobileBlobHash(blob);
    const isDupe = (hash === _mobileLastHash);
    if (isDupe) {
      _mobileConsecutiveDupes += 1;
    } else {
      _mobileConsecutiveDupes = 0;
      _mobileLastHash = hash;
      if (_mobileScreenshotBlobUrl) URL.revokeObjectURL(_mobileScreenshotBlobUrl);
      _mobileScreenshotBlobUrl = URL.createObjectURL(blob);
      if (img) {
        img.src = _mobileScreenshotBlobUrl;
        img.style.display = "";
      }
    }

    const elapsed = Math.round(performance.now() - started);
    _mobileLastSnapAt = performance.now();
    // Track FPS from the last N frames. Aborted / duped frames still
    // count because they were real network round-trips.
    _mobileFrameStamps.push(_mobileLastSnapAt);
    if (_mobileFrameStamps.length > _MOBILE_FPS_WINDOW) _mobileFrameStamps.shift();
    let fpsLabel = "";
    if (_mobileFrameStamps.length >= 2) {
      const span = _mobileFrameStamps[_mobileFrameStamps.length - 1]
                 - _mobileFrameStamps[0];
      if (span > 0) {
        const fps = ((_mobileFrameStamps.length - 1) * 1000) / span;
        fpsLabel = " · " + fps.toFixed(fps < 3 ? 2 : 1) + " fps";
      }
    }
    if (meta) {
      const dupeTag = isDupe
        ? " · dupe" + (_mobileConsecutiveDupes > 1 ? "×" + _mobileConsecutiveDupes : "")
        : "";
      // Breakdown: elapsed = full round-trip; capture+encode = server
      // side; network = elapsed - capture - encode. This lets the user
      // see whether it's the phone, the bridge, or Tailscale that's slow.
      const network = Math.max(0, elapsed - captureMs - encodeMs);
      const breakdown = (captureMs || encodeMs)
        ? " (cap " + captureMs + " + enc " + encodeMs + " + net " + network + ")"
        : "";
      const modeTag = captureMode ? " · " + captureMode : "";
      meta.textContent =
        _mobileShownWidth + "×" + _mobileShownHeight
        + " · " + settings.format + " q" + settings.quality + modeTag
        + " · " + Math.round(blob.size / 1024) + " KB"
        + " · " + elapsed + " ms" + breakdown
        + fpsLabel + dupeTag;
    }
    // Secure-screen banner — surface once, don't spam. FLAG_SECURE
    // screens (password entry, banking apps) return a black frame
    // that would otherwise look like a Live-view crash.
    const secureBanner = document.getElementById("mobileSecureBanner");
    if (secureBanner) {
      secureBanner.style.display = secureFrame ? "" : "none";
    }
    _mobileUpdateAgeLabel();
  } catch (e) {
    // AbortError = intentional cancel from a follow-up action, not an
    // error we want to surface to the user. Log to console only; the
    // previous version appended " · aborted" to the meta line every
    // time and never reset it, which grew into hundreds of characters
    // during long Live sessions.
    if (!(e && e.name === "AbortError")) {
      mobileShowError("Screenshot request failed", e && e.stack || String(e));
    }
  } finally {
    if (loading) loading.style.display = "none";
    _mobileScreenshotBusy = false;
    // Live-view chain: schedule the next frame from the finally block
    // instead of via setInterval. This means "next fetch fires N ms
    // AFTER the previous one completes", not "every N ms regardless".
    // Result: no more request pile-up on slow devices, no more spurious
    // AbortErrors from setInterval firing into an in-flight fetch.
    _mobileLiveScheduleNextFrame();
  }
}

// --- Adaptive burst + Live polling -------------------------------------
function _mobileRefreshBurst() {
  if (!_mobileSelectedSerial) return;
  _mobileScreenshotGen += 1;
  const gen = _mobileScreenshotGen;
  // Force at least one visible frame update after a user action: the
  // very first snap in the burst clears the dedup hash so an
  // "identical" frame after a tap that didn't visibly change anything
  // (e.g. tapping a checkbox that only changed 4 pixels) still redraws.
  _mobileLastHash = null;
  const delays = [0, 400, 1200];
  for (const delay of delays) {
    setTimeout(() => {
      if (gen !== _mobileScreenshotGen) return;
      if (!_mobileSelectedSerial) return;
      // Skip if a later burst frame is still fetching — no point
      // stacking three in-flight requests.
      if (delay > 0 && _mobileScreenshotBusy) return;
      mobileScreenshot();
    }, delay);
  }
}

// Pause the Live-view poll when the tab is hidden (background tab, other
// window). Resume automatically when it becomes visible again. This
// stops the poll from burning Tailscale bandwidth + phone battery for
// no visible benefit.
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      // Cancel any pending Live-chain tick so we don't burn Tailnet
      // bandwidth while the user is in another tab.
      _mobileLiveClear();
      _mobileLivePausedByHidden = true;
    } else if (_mobileLivePausedByHidden) {
      _mobileLivePausedByHidden = false;
      // Restart the Live chain — mobileLiveApply also fires an
      // immediate first frame so the user sees fresh content on return.
      if (typeof mobileLiveApply === "function") mobileLiveApply();
    }
  });
}

function _mobileUpdateAgeLabel() {
  const el = document.getElementById("mobileScreenshotAge");
  if (!el) return;
  if (!_mobileLastSnapAt) { el.textContent = ""; return; }
  const age = Math.round((performance.now() - _mobileLastSnapAt) / 1000);
  el.textContent = age <= 0 ? "just now" : (age + "s ago");
  el.style.color = age <= 2 ? "#2b8a3e" : age <= 10 ? "#666" : "#c92a2a";
}

// Chain-based Live view (v3.83.4).
//
// The v3.83.3 implementation used setInterval + a busy-guard + an
// AbortController. On a slow connection this meant:
//   * setInterval fires every N ms regardless of whether the previous
//     fetch finished
//   * busy-guard skips most ticks (they log " · aborted" appended to
//     the meta line, which never got reset and grew forever)
//   * the surviving tick would abort the in-flight fetch mid-decode,
//     producing a real AbortError every cycle
//
// The new model: a single pending timeout that only gets scheduled
// AFTER a frame completes. Live rate becomes "wait N ms between frames"
// instead of "fire N ms after the previous fire". If the phone takes
// 700 ms per frame at 1 Hz, we produce ~1 frame/1700 ms — honest — and
// never queue a second request while the first is running.
let _mobileLivePendingTimeout = null;
let _mobileLivePausedByHidden = false;   // set by visibilitychange

function _mobileLiveClear() {
  if (_mobileLivePendingTimeout !== null) {
    clearTimeout(_mobileLivePendingTimeout);
    _mobileLivePendingTimeout = null;
  }
}

function _mobileLiveScheduleNextFrame() {
  _mobileLiveClear();
  const settings = mobileScreenSettingsLoad();
  if (!(settings.live_hz > 0)) return;              // Live off
  if (!_mobileSelectedSerial) return;               // no device
  if (typeof document !== "undefined" && document.hidden) {
    _mobileLivePausedByHidden = true;
    return;
  }
  const tab = document.getElementById("tab-mobile");
  if (!tab || !tab.classList.contains("active")) return;
  const intervalMs = Math.max(200, Math.round(1000 / settings.live_hz));
  _mobileLivePendingTimeout = setTimeout(() => {
    _mobileLivePendingTimeout = null;
    if (!_mobileScreenshotBusy) mobileScreenshot();
    else _mobileLiveScheduleNextFrame();  // recheck on the next tick
  }, intervalMs);
}

// Public entry point: enable/disable/rate change. Warms up with an
// immediate first frame.
function mobileLiveApply() {
  _mobileLiveClear();
  const settings = mobileScreenSettingsLoad();
  if (!(settings.live_hz > 0)) return;
  if (typeof document !== "undefined" && document.hidden) {
    _mobileLivePausedByHidden = true;
    return;
  }
  if (_mobileSelectedSerial && !_mobileScreenshotBusy) {
    _mobileFrameStamps.length = 0;
    mobileScreenshot();  // finally block will schedule the next
  } else {
    _mobileLiveScheduleNextFrame();
  }
}

// Compat shim for other files that still call the setInterval-based
// clearer. The name is kept so external references (e.g. selectMobileDevice
// resetting Live on device change) don't need to be updated.
let _mobileLiveTimer = null;  // unused now, kept for reference

// Public toggle handler. Called from the checkbox onchange.
function mobileToggleLive() {
  mobileScreenSettingsFromUi();
}
