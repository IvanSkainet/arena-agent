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
// takes another action (tap, key, gesture), we call this to cancel
// the previous /screenshot request instead of letting two overlapping
// fetches race. Tailscale round-trip for a 720px WebP is ~200-400ms,
// so a rapid triple-tap without this would queue 3 stale frames and
// display them one after another.
let _mobileFetchController = null;

// True while the visibility hook has paused Live-view polling because
// the tab is hidden. Resumed on `visibilitychange` -> visible.
let _mobileLivePausedByHidden = false;

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

  // Cancel any previous in-flight fetch so a rapid action series
  // doesn't stack pending frames on the Tailscale link.
  if (_mobileFetchController) {
    try { _mobileFetchController.abort(); } catch (_) {}
  }
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
    // Rotation-aware native size — the frontend uses this (not the
    // /info physical size) to translate CSS clicks back to phone
    // coordinates. `screencap` follows rotation, so landscape gives
    // us 3200x1440 here even though /info reports 1440x3200. Falls
    // back to shown size if the bridge is older than v3.83.2.
    const srcW = parseInt(resp.headers.get("X-Arena-Mobile-Source-Width") || "0", 10);
    const srcH = parseInt(resp.headers.get("X-Arena-Mobile-Source-Height") || "0", 10);
    if (srcW > 0 && srcH > 0) {
      _mobileNativeWidth = srcW;
      _mobileNativeHeight = srcH;
    }
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
      meta.textContent =
        _mobileShownWidth + "×" + _mobileShownHeight
        + " · " + settings.format + " q" + settings.quality
        + " · " + Math.round(blob.size / 1024) + " KB"
        + " · " + elapsed + " ms" + fpsLabel + dupeTag;
    }
    _mobileUpdateAgeLabel();
  } catch (e) {
    // AbortError = intentional cancel from a follow-up action, not an
    // error we want to surface to the user.
    if (e && e.name === "AbortError") {
      // Meta line: hint that we skipped one frame on purpose.
      if (meta && meta.textContent) meta.textContent += " · aborted";
    } else {
      mobileShowError("Screenshot request failed", e && e.stack || String(e));
    }
  } finally {
    if (loading) loading.style.display = "none";
    _mobileScreenshotBusy = false;
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
      if (_mobileLiveTimer) {
        clearInterval(_mobileLiveTimer);
        _mobileLiveTimer = null;
        _mobileLivePausedByHidden = true;
      }
    } else if (_mobileLivePausedByHidden) {
      _mobileLivePausedByHidden = false;
      // Re-apply the current settings (starts the timer if Live is on).
      if (typeof mobileLiveApply === "function") mobileLiveApply();
      // And do one immediate refresh so the user sees a current frame.
      if (_mobileSelectedSerial) mobileScreenshot();
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

// Applies the current Live-view rate: stops any existing poll, starts
// a new one if enabled. Called from settings changes and tab-switch.
function mobileLiveApply() {
  const settings = mobileScreenSettingsLoad();
  if (_mobileLiveTimer) {
    clearInterval(_mobileLiveTimer);
    _mobileLiveTimer = null;
  }
  if (!(settings.live_hz > 0)) return;
  if (typeof document !== "undefined" && document.hidden) {
    // Don't start polling into a hidden tab — visibilitychange will
    // re-apply once we become visible again.
    _mobileLivePausedByHidden = true;
    return;
  }
  const intervalMs = Math.max(200, Math.round(1000 / settings.live_hz));
  // Warm-up: fire the first frame right away instead of waiting a full
  // interval — a 1.5s Live rate should not delay the first paint by
  // 1.5s when the toggle just got flipped.
  if (_mobileSelectedSerial && !_mobileScreenshotBusy) {
    _mobileFrameStamps.length = 0;
    mobileScreenshot();
  }
  _mobileLiveTimer = setInterval(() => {
    if (!_mobileSelectedSerial) return;
    const tab = document.getElementById("tab-mobile");
    if (!tab || !tab.classList.contains("active")) return;
    // Skip only if the network round-trip is genuinely slower than the
    // polling interval. If it's been more than 2× the interval since
    // the last successful snap, the previous fetch is probably stuck —
    // abort it so this tick can make progress.
    if (_mobileScreenshotBusy) {
      const stall = performance.now() - _mobileLastSnapAt;
      if (stall > intervalMs * 2 && _mobileFetchController) {
        try { _mobileFetchController.abort(); } catch (_) {}
        _mobileScreenshotBusy = false;
      } else {
        return;
      }
    }
    mobileScreenshot();
  }, intervalMs);
}

// Public toggle handler. Called from the checkbox onchange.
function mobileToggleLive() {
  mobileScreenSettingsFromUi();
}
