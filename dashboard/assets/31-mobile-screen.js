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

const MOBILE_SCREEN_DEFAULTS = {
  format: "webp",      // webp | jpeg | png
  quality: 82,         // 1..100 (WebP goes to 100, JPEG capped at 95)
  max_width: 720,      // 0 = native resolution, no downscale
  live_hz: 0.67,       // Hz — 0 = off. Default = one frame per 1.5s.
};

function mobileScreenSettingsLoad() {
  try {
    const raw = localStorage.getItem(_MOBILE_LS_KEY);
    if (!raw) return {...MOBILE_SCREEN_DEFAULTS};
    const parsed = JSON.parse(raw);
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
  if (width) width.value = String(s.max_width);
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
    max_width: Number.isFinite(width) ? Math.max(0, Math.min(4096, width)) : 720,
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
async function mobileScreenshot() {
  if (!_mobileSelectedSerial) return;
  if (_mobileScreenshotBusy) return;
  _mobileScreenshotBusy = true;

  const settings = mobileScreenSettingsLoad();
  const img = document.getElementById("mobileScreenshotImg");
  const meta = document.getElementById("mobileScreenshotMeta");
  const loading = document.getElementById("mobileScreenshotLoading");
  if (loading) loading.style.display = "";

  const started = performance.now();
  try {
    const params = new URLSearchParams({
      max_width: String(settings.max_width),
      quality: String(settings.quality),
      format: settings.format,
    });
    const url = BASE
      + "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/screenshot?" + params.toString();
    const resp = await fetch(url, {headers, cache: "no-store"});
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
    const blob = await resp.blob();

    if (_mobileScreenshotBlobUrl) URL.revokeObjectURL(_mobileScreenshotBlobUrl);
    _mobileScreenshotBlobUrl = URL.createObjectURL(blob);
    if (img) {
      img.src = _mobileScreenshotBlobUrl;
      img.style.display = "";
    }
    const elapsed = Math.round(performance.now() - started);
    _mobileLastSnapAt = performance.now();
    if (meta) {
      meta.textContent =
        _mobileShownWidth + "×" + _mobileShownHeight
        + " · " + settings.format + " q" + settings.quality
        + " · " + Math.round(blob.size / 1024) + " KB"
        + " · " + elapsed + " ms";
    }
    _mobileUpdateAgeLabel();
  } catch (e) {
    mobileShowError("Screenshot request failed", e && e.stack || String(e));
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
  const delays = [0, 400, 1200];
  for (const delay of delays) {
    setTimeout(() => {
      if (gen !== _mobileScreenshotGen) return;
      if (!_mobileSelectedSerial) return;
      mobileScreenshot();
    }, delay);
  }
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
  const intervalMs = Math.max(200, Math.round(1000 / settings.live_hz));
  _mobileLiveTimer = setInterval(() => {
    if (!_mobileSelectedSerial) return;
    const tab = document.getElementById("tab-mobile");
    if (!tab || !tab.classList.contains("active")) return;
    if (_mobileScreenshotBusy) return;
    mobileScreenshot();
  }, intervalMs);
}

// Public toggle handler. Called from the checkbox onchange.
function mobileToggleLive() {
  mobileScreenSettingsFromUi();
}
