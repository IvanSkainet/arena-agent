// Dashboard: Mobile Devices card (Android via ADB).
//
// Reads /v1/mobile/* and drives the tap/swipe/type/key/shell/screenshot
// endpoints. Piggybacks on the existing api() helper — never spreads its
// own `headers` key so the default Authorization is preserved.

let _mobileSelectedSerial = null;
let _mobileNativeWidth = 0;      // native device pixels (from /info)
let _mobileNativeHeight = 0;
let _mobileShownWidth = 0;       // downscaled screenshot pixels
let _mobileShownHeight = 0;
let _mobileScreenshotBusy = false;
let _mobileScreenshotBlobUrl = null;
let _mobileInfoCache = null;

// Live-view state. `_mobileLiveOn` mirrors the checkbox, `_mobileLiveTimer`
// holds the polling interval id so we can cancel on tab switch / device
// change. `_mobileScreenshotGen` is a monotonically increasing counter —
// every new user action bumps it, and the adaptive post-action refresh
// series bails as soon as its saved generation is stale (so a rapid tap
// doesn't stack three overlapping screenshot fetches).
let _mobileLiveOn = false;
let _mobileLiveTimer = null;
let _mobileScreenshotGen = 0;
let _mobileLastSnapAt = 0;       // performance.now() at last successful snap
let _mobileAgeTimer = null;      // refreshes the "N s ago" label

// ---------------------------------------------------------------------------
// Error helper — surfaces backend errors inline with a Copy button so the
// user can paste them into a bug report instead of retyping.
// ---------------------------------------------------------------------------
function mobileShowError(title, detail) {
  const box = document.getElementById("mobileErrorBox");
  const titleEl = document.getElementById("mobileErrorTitle");
  const detailEl = document.getElementById("mobileErrorDetail");
  if (!box || !titleEl || !detailEl) {
    // Fallback if the panel isn't in the DOM yet.
    alert(title + "\n\n" + detail);
    return;
  }
  titleEl.textContent = title;
  detailEl.textContent = detail || "(no details)";
  box.style.display = "";
  box.scrollIntoView({behavior: "smooth", block: "nearest"});
}
function mobileClearError() {
  const box = document.getElementById("mobileErrorBox");
  if (box) box.style.display = "none";
}
function mobileCopyError() {
  const titleEl = document.getElementById("mobileErrorTitle");
  const detailEl = document.getElementById("mobileErrorDetail");
  const text = (titleEl?.textContent || "") + "\n\n" + (detailEl?.textContent || "");
  navigator.clipboard.writeText(text).then(
    () => {
      const btn = document.getElementById("mobileErrorCopyBtn");
      if (!btn) return;
      const orig = btn.textContent;
      btn.textContent = "✓ Copied";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    },
    (e) => alert("Copy failed: " + (e.message || e)),
  );
}

// Compose a structured, human-readable error from a bridge response.
function _fmtBackendError(prefix, r) {
  if (!r) return prefix + ": empty response";
  const parts = [];
  if (r.error)       parts.push("error:    " + String(r.error));
  if (r.hint)        parts.push("hint:     " + String(r.hint));
  const stderr = String(r.stderr || "").trim();
  const stdout = String(r.stdout || "").trim();
  if (stderr)        parts.push("stderr:   " + stderr);
  else if (stdout)   parts.push("stdout:   " + stdout);
  if (typeof r.exit_code === "number" && r.exit_code !== 0) {
    parts.push("exit:     " + r.exit_code);
  }
  if (r.action)      parts.push("action:   " + r.action);
  if (r.cli_path)    parts.push("cli_path: " + r.cli_path);
  return parts.length ? parts.join("\n") : (prefix + ": unknown error");
}

// ---------------------------------------------------------------------------
// Devices list
// ---------------------------------------------------------------------------
async function refreshMobile() {
  const headerBadge = document.getElementById("mobileHeaderBadge");
  const adbBadge = document.getElementById("mobileAdbStatus");
  const adbPathEl = document.getElementById("mobileAdbPath");
  const hint = document.getElementById("mobileHint");
  const list = document.getElementById("mobileDevicesList");
  const selectedCard = document.getElementById("mobileSelectedCard");

  try {
    const r = await api("/v1/mobile/devices");

    if (!r || !r.adb_installed) {
      if (headerBadge) { headerBadge.className = "badge gray"; headerBadge.textContent = "adb missing"; }
      if (adbBadge) { adbBadge.className = "badge fail"; adbBadge.textContent = "not installed"; }
      if (adbPathEl) adbPathEl.textContent = "";
      if (list) list.innerHTML = "";
      if (hint) {
        hint.style.display = "";
        hint.textContent = (r && r.hint) || "adb is not installed on the bridge host.";
      }
      if (selectedCard) selectedCard.style.display = "none";
      return;
    }

    if (adbBadge) { adbBadge.className = "badge ok"; adbBadge.textContent = "installed"; }
    if (adbPathEl) adbPathEl.textContent = (r.adb_path || "") + " · v" + (r.adb_version || "?");

    const devices = r.devices || [];
    if (headerBadge) {
      const ready = devices.filter((d) => d.state === "device").length;
      headerBadge.className = ready ? "badge ok" : "badge gray";
      headerBadge.textContent = ready ? (ready + " device" + (ready === 1 ? "" : "s")) : "no devices";
    }

    if (hint) {
      if (r.hint) { hint.style.display = ""; hint.textContent = r.hint; }
      else       { hint.style.display = "none"; hint.textContent = ""; }
    }

    if (list) {
      list.innerHTML = "";
      if (!devices.length) {
        const empty = document.createElement("div");
        empty.style.cssText = "color:#666;font-size:12px";
        empty.textContent = "No devices. Connect a phone via USB and enable USB debugging.";
        list.appendChild(empty);
      } else {
        for (const d of devices) list.appendChild(_mobileDeviceRow(d));
      }
    }

    // If the selected device disappeared, hide the actions card and
    // stop the live-view poll (nothing to poll).
    if (_mobileSelectedSerial && !devices.some((d) => d.serial === _mobileSelectedSerial)) {
      _mobileSelectedSerial = null;
      _mobileInfoCache = null;
      if (selectedCard) selectedCard.style.display = "none";
      if (_mobileLiveTimer) {
        clearInterval(_mobileLiveTimer);
        _mobileLiveTimer = null;
        _mobileLiveOn = false;
        const cb = document.getElementById("mobileLiveToggle");
        if (cb) cb.checked = false;
      }
    }
  } catch (e) {
    console.warn("[mobile] refresh failed:", e);
    mobileShowError("Failed to refresh mobile devices", e && e.stack || String(e));
  }
}

function _mobileDeviceRow(d) {
  const row = document.createElement("div");
  row.className = "row";
  row.style.cssText = "gap:8px;padding:8px;border:1px solid rgba(128,128,128,.2);border-radius:6px;flex-wrap:wrap";

  const badge = document.createElement("span");
  let cls = "gray";
  if (d.state === "device") cls = "ok";
  else if (d.state === "unauthorized") cls = "warn";
  else if (d.state === "offline") cls = "fail";
  badge.className = "badge " + cls;
  badge.textContent = d.state;
  row.appendChild(badge);

  const serial = document.createElement("span");
  serial.className = "mono";
  serial.style.cssText = "font-weight:600;font-size:12px";
  serial.textContent = d.serial;
  row.appendChild(serial);

  if (d.model) {
    const model = document.createElement("span");
    model.style.cssText = "font-size:12px";
    model.textContent = d.model + (d.product ? " (" + d.product + ")" : "");
    row.appendChild(model);
  }
  if (d.usb) {
    const usb = document.createElement("span");
    usb.className = "mono";
    usb.style.cssText = "font-size:11px;color:#666";
    usb.textContent = "usb:" + d.usb;
    row.appendChild(usb);
  }
  if (d.ip) {
    const ip = document.createElement("span");
    ip.className = "mono";
    ip.style.cssText = "font-size:11px;color:#666";
    ip.textContent = d.ip;
    row.appendChild(ip);
  }

  if (d.state === "device") {
    const selectBtn = document.createElement("button");
    selectBtn.textContent = _mobileSelectedSerial === d.serial ? "✓ Selected" : "Select";
    selectBtn.style.marginLeft = "auto";
    selectBtn.onclick = () => selectMobileDevice(d.serial, d.model);
    row.appendChild(selectBtn);
  }
  return row;
}

// ---------------------------------------------------------------------------
// Device selection
// ---------------------------------------------------------------------------
async function selectMobileDevice(serial, label) {
  _mobileSelectedSerial = serial;
  _mobileInfoCache = null;
  _mobileNativeWidth = 0;
  _mobileNativeHeight = 0;
  _mobileLastSnapAt = 0;
  const nameEl = document.getElementById("mobileSelectedName");
  const card = document.getElementById("mobileSelectedCard");
  if (nameEl) nameEl.textContent = (label ? label + " · " : "") + serial;
  if (card) card.style.display = "";
  // Start (or ensure) the 1Hz "N s ago" ticker.
  if (!_mobileAgeTimer) {
    _mobileAgeTimer = setInterval(_mobileUpdateAgeLabel, 1000);
  }
  mobileClearError();
  // Load info first (blocks on physical size for coord scaling), then screenshot.
  await mobileLoadInfo();
  await mobileScreenshot();
  refreshMobile();
}

async function mobileLoadInfo() {
  const dump = document.getElementById("mobileInfoDump");
  if (!_mobileSelectedSerial) return;
  try {
    const r = await api("/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/info");
    _mobileInfoCache = r;
    if (dump) dump.textContent = JSON.stringify(r, null, 2);
    // Cache native screen size for coord scaling.
    const raw = r && (r.screen_size_override || r.screen_size_physical);
    if (raw) {
      const m = /(\d+)x(\d+)/.exec(raw);
      if (m) {
        _mobileNativeWidth = parseInt(m[1], 10);
        _mobileNativeHeight = parseInt(m[2], 10);
      }
    }
  } catch (e) {
    if (dump) dump.textContent = "info error: " + (e && e.message || e);
    mobileShowError("Failed to load device info", e && e.stack || String(e));
  }
}

// ---------------------------------------------------------------------------
// Screenshot — binary blob (no base64 tax), inline loading indicator.
//
// `mobileScreenshot()` fetches one frame. `_mobileRefreshBurst()` is the
// adaptive series called after every action: it snaps at t+0, t+400ms
// and t+1200ms to catch app transition animations (a common failure mode
// on Android — user taps a Google search result, the browser fades to
// black for ~800ms, then paints. A single snap right after the tap
// captures the black frame). The burst is cancelled if the user starts
// another action mid-way (via `_mobileScreenshotGen`).
// ---------------------------------------------------------------------------
async function mobileScreenshot() {
  if (!_mobileSelectedSerial) return;
  if (_mobileScreenshotBusy) return;  // dedup rapid taps
  _mobileScreenshotBusy = true;

  const img = document.getElementById("mobileScreenshotImg");
  const meta = document.getElementById("mobileScreenshotMeta");
  const loading = document.getElementById("mobileScreenshotLoading");
  if (loading) loading.style.display = "";

  const started = performance.now();
  try {
    // Fetch as raw binary — 33% smaller than the JSON+base64 path, and the
    // image element can render straight from a blob URL.
    const url = BASE
      + "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/screenshot?max_width=360&quality=70&format=jpeg";
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

    // Revoke old blob URL to free memory.
    if (_mobileScreenshotBlobUrl) {
      URL.revokeObjectURL(_mobileScreenshotBlobUrl);
    }
    _mobileScreenshotBlobUrl = URL.createObjectURL(blob);
    if (img) {
      img.src = _mobileScreenshotBlobUrl;
      img.style.display = "";
    }
    const elapsed = Math.round(performance.now() - started);
    _mobileLastSnapAt = performance.now();
    if (meta) {
      meta.textContent = _mobileShownWidth + "×" + _mobileShownHeight
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

// Adaptive post-action refresh series. Every burst carries the generation
// counter it was born under; if a newer action bumps the counter, the
// series aborts silently. This gives us smooth updates after taps that
// trigger transition animations (e.g. Google search results screen fades
// in over ~800ms — one snap at t=0 misses the final frame).
function _mobileRefreshBurst() {
  if (!_mobileSelectedSerial) return;
  _mobileScreenshotGen += 1;
  const gen = _mobileScreenshotGen;
  const delays = [0, 400, 1200];
  for (const delay of delays) {
    setTimeout(() => {
      if (gen !== _mobileScreenshotGen) return;   // superseded
      if (!_mobileSelectedSerial) return;
      mobileScreenshot();
    }, delay);
  }
}

// "N s ago" label under the screenshot meta line — updated once a second
// so the user can eyeball how fresh the frame is without checking the
// timestamp column of the meta line manually.
function _mobileUpdateAgeLabel() {
  const el = document.getElementById("mobileScreenshotAge");
  if (!el) return;
  if (!_mobileLastSnapAt) {
    el.textContent = "";
    return;
  }
  const age = Math.round((performance.now() - _mobileLastSnapAt) / 1000);
  el.textContent = age <= 0 ? "just now" : (age + "s ago");
  // Colour cue: fresh = green-ish, stale = grey.
  el.style.color = age <= 2 ? "#2b8a3e" : age <= 10 ? "#666" : "#c92a2a";
}

// Live-view: poll `/screenshot` at a fixed interval. Uses the same busy
// flag as manual refresh so a slow snapshot doesn't stack requests, and
// bails out if we're not on the mobile tab or nothing is selected.
function mobileToggleLive(checkbox) {
  _mobileLiveOn = !!(checkbox && checkbox.checked);
  if (_mobileLiveTimer) {
    clearInterval(_mobileLiveTimer);
    _mobileLiveTimer = null;
  }
  if (!_mobileLiveOn) return;
  _mobileLiveTimer = setInterval(() => {
    if (!_mobileSelectedSerial) return;
    // Only poll while the mobile tab is actually visible — no point
    // burning phone battery + Tailscale bandwidth in the background.
    const tab = document.getElementById("tab-mobile");
    if (!tab || !tab.classList.contains("active")) return;
    if (_mobileScreenshotBusy) return;
    mobileScreenshot();
  }, 1500);
}

// ---------------------------------------------------------------------------
// Tap / key / type / shell — no artificial delays, immediate refresh
// ---------------------------------------------------------------------------
function mobileTapFromImage(event) {
  if (!_mobileSelectedSerial || !_mobileShownWidth) return;
  const img = event.currentTarget;
  const rect = img.getBoundingClientRect();
  const displayX = event.clientX - rect.left;
  const displayY = event.clientY - rect.top;
  // Scale displayed-CSS-pixels → shown-source-pixels → native device pixels.
  const shownX = displayX * (_mobileShownWidth / img.clientWidth);
  const shownY = displayY * (_mobileShownHeight / img.clientHeight);
  const nativeRatio = (_mobileNativeWidth && _mobileShownWidth)
    ? _mobileNativeWidth / _mobileShownWidth : 1;
  const nativeX = Math.round(shownX * nativeRatio);
  const nativeY = Math.round(shownY * nativeRatio);
  _mobileSendTap(nativeX, nativeY);
}

async function _mobileSendTap(x, y) {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/tap",
      {method: "POST", body: JSON.stringify({x, y})},
    );
    if (!r || !r.ok) {
      mobileShowError("Tap failed at (" + x + ", " + y + ")", _fmtBackendError("tap", r));
      return;
    }
    // Adaptive burst: t+0 / t+400 / t+1200 ms. Catches app-transition
    // animations (Chrome/Google black-frame problem) without doubling
    // Tailnet bandwidth for a static screen.
    _mobileRefreshBurst();
  } catch (e) {
    mobileShowError("Tap request failed", e && e.stack || String(e));
  }
}

async function mobileKey(name) {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/key",
      {method: "POST", body: JSON.stringify({key: name})},
    );
    if (!r || !r.ok) {
      mobileShowError("Key " + name + " failed", _fmtBackendError("key", r));
      return;
    }
    _mobileRefreshBurst();
  } catch (e) {
    mobileShowError("Key request failed", e && e.stack || String(e));
  }
}

async function mobileType() {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  const el = document.getElementById("mobileTypeText");
  const text = (el && el.value) || "";
  if (!text) return;
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/type",
      {method: "POST", body: JSON.stringify({text})},
    );
    if (!r || !r.ok) {
      mobileShowError("Type failed", _fmtBackendError("type", r));
      return;
    }
    if (el) el.value = "";
    _mobileRefreshBurst();
  } catch (e) {
    mobileShowError("Type request failed", e && e.stack || String(e));
  }
}

async function mobileShell() {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  const el = document.getElementById("mobileShellCmd");
  const out = document.getElementById("mobileShellOut");
  const cmd = (el && el.value.trim()) || "";
  if (!cmd) return;
  if (!out) return;
  out.style.display = "";
  out.textContent = "…";
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/shell",
      {method: "POST", body: JSON.stringify({command: cmd})},
    );
    if (r && r.ok) {
      out.textContent = "$ " + cmd + "\n" + (r.stdout || "(no output)");
    } else {
      out.textContent = "$ " + cmd + "\n" + _fmtBackendError("shell", r);
    }
  } catch (e) {
    out.textContent = "shell error: " + (e.message || e);
  }
}

// ---------------------------------------------------------------------------
// Auto-refresh + tab hook (same pattern as 29-tunnels.js).
// ---------------------------------------------------------------------------
(function () {
  document.addEventListener("click", (ev) => {
    const link = ev.target.closest && ev.target.closest('.sidebar nav a[data-tab="mobile"]');
    if (!link) return;
    setTimeout(refreshMobile, 100);
  });

  document.addEventListener("DOMContentLoaded", () => {
    const t = document.getElementById("tab-mobile");
    if (t && t.classList.contains("active")) refreshMobile();
  });
  if (document.readyState !== "loading") {
    const t = document.getElementById("tab-mobile");
    if (t && t.classList.contains("active")) refreshMobile();
  }
})();
