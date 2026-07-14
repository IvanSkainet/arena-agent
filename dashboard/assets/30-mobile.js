// Dashboard: Mobile Devices card (Android via ADB).
//
// Reads /v1/mobile/* and drives the tap/swipe/type/key/shell/screenshot
// endpoints. Piggybacks on the existing api() helper — never spreads its
// own `headers` key so the default Authorization is preserved.

let _mobileSelectedSerial = null;
let _mobileScreenWidth = 0;
let _mobileScreenHeight = 0;

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

    // If the selected device disappeared, hide the actions card.
    if (_mobileSelectedSerial && !devices.some((d) => d.serial === _mobileSelectedSerial)) {
      _mobileSelectedSerial = null;
      if (selectedCard) selectedCard.style.display = "none";
    }
  } catch (e) {
    console.warn("[mobile] refresh failed:", e);
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

async function selectMobileDevice(serial, label) {
  _mobileSelectedSerial = serial;
  const nameEl = document.getElementById("mobileSelectedName");
  const card = document.getElementById("mobileSelectedCard");
  if (nameEl) nameEl.textContent = (label ? label + " · " : "") + serial;
  if (card) card.style.display = "";
  await mobileLoadInfo();
  await mobileScreenshot();
  refreshMobile();  // refreshes device row Select→✓ Selected label
}

async function mobileLoadInfo() {
  const dump = document.getElementById("mobileInfoDump");
  if (!dump || !_mobileSelectedSerial) return;
  try {
    const r = await api("/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/info");
    dump.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    dump.textContent = "info error: " + (e.message || e);
  }
}

async function mobileScreenshot() {
  if (!_mobileSelectedSerial) return;
  const img = document.getElementById("mobileScreenshotImg");
  const meta = document.getElementById("mobileScreenshotMeta");
  if (!img) return;
  try {
    // Use wire=json + base64 so we get width/height back for click→tap
    // coordinate mapping without an extra HEAD roundtrip. Downscale to
    // keep the payload reasonable — the bridge preserves aspect ratio.
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/screenshot?max_width=480&quality=75&format=jpeg&wire=json"
    );
    if (!r || !r.ok) {
      img.style.display = "none";
      if (meta) meta.textContent = "screenshot failed: " + ((r && (r.error || r.hint)) || "?");
      return;
    }
    _mobileScreenWidth = r.width;
    _mobileScreenHeight = r.height;
    img.src = "data:" + r.mime + ";base64," + r.base64;
    img.style.display = "";
    if (meta) meta.textContent = "shown " + r.width + "×" + r.height
      + " · " + Math.round(r.size_bytes / 1024) + " KB"
      + (r.downscaled ? " (downscaled)" : "");
  } catch (e) {
    if (meta) meta.textContent = "screenshot error: " + (e.message || e);
  }
}

function mobileTapFromImage(event) {
  if (!_mobileSelectedSerial || !_mobileScreenWidth) return;
  const img = event.currentTarget;
  const rect = img.getBoundingClientRect();
  const displayX = event.clientX - rect.left;
  const displayY = event.clientY - rect.top;
  // Scale display coordinates back to native device pixels. Screenshot
  // was downscaled to `_mobileScreenWidth`, but the source Android
  // screen is bigger — we saved the reported "shown" size which is
  // what the downscaler produced, so the ratio between displayed
  // rendered size and reported shown size is 1:1 for width, and we
  // need to walk from `shown` back to the native resolution. We stored
  // the shown size, not the native — so walk through the info endpoint.
  // Simpler: pass the shown coordinate to adb, since the bridge's own
  // screencap targets the real display. Instead, remap:
  //   nativeX = displayX * (nativeW / renderedW)
  // We only know renderedW; nativeW would need a second call. Just
  // scale by the natural display size vs the img's rendered size,
  // then multiply by the ratio nativeW/renderedW=1 (we asked ADB to
  // capture native, then Pillow downscaled to renderedW). So the
  // "displayed pixel" → "native pixel" ratio is nativeW/renderedW.
  // Fetch it from a fresh info call is too slow; instead we ratio
  // against the ORIGINAL display we cached. We only stored
  // `_mobileScreenWidth` = the shown size. As a robust fallback,
  // ask the device once per screenshot for its native size.
  //
  // Practical solution: ratio between the on-screen rendered img and
  // the source PNG's `_mobileScreenWidth` is direct (image is rendered
  // at max 100% of container, so displayed-vs-source is just
  // displayX/img.width). Multiply by (nativeW/shownW) which we don't
  // have, so approximate: nativeW ≈ shownW * (screenSizePhysical / shownW)
  // — but we do have physical size from the info dump. Instead of
  // adding a second network call, keep it simple: send scaled X,Y
  // computed from the displayed pixel ratio to source-shown ratio
  // (which is 1:1 in practice because <img> width == container, and
  // container ≤ 400px, and source is 480px), then let ADB tap slightly
  // off — good enough for a UI proof of life, and the terminal
  // shell/type still work exactly. We'll refine when a native-size
  // field lands in the /info response uniformly.
  const shownX = Math.round(displayX * (_mobileScreenWidth / img.clientWidth));
  const shownY = Math.round(displayY * (_mobileScreenHeight / img.clientHeight));
  // The downscale ratio: native / shown. Read from cached info if we can.
  const info = _mobileCachedInfo || {};
  let nativeRatio = 1;
  if (info.screen_size_physical) {
    const m = /(\d+)x(\d+)/.exec(info.screen_size_physical);
    if (m) {
      const nativeW = parseInt(m[1], 10);
      if (nativeW && _mobileScreenWidth) nativeRatio = nativeW / _mobileScreenWidth;
    }
  }
  const nativeX = Math.round(shownX * nativeRatio);
  const nativeY = Math.round(shownY * nativeRatio);
  _mobileSendTap(nativeX, nativeY);
}

let _mobileCachedInfo = null;

async function mobileLoadInfoCached() {
  if (!_mobileSelectedSerial) return;
  try {
    _mobileCachedInfo = await api("/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/info");
    const dump = document.getElementById("mobileInfoDump");
    if (dump) dump.textContent = JSON.stringify(_mobileCachedInfo, null, 2);
  } catch (e) {
    _mobileCachedInfo = null;
  }
}

async function _mobileSendTap(x, y) {
  if (!_mobileSelectedSerial) return;
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/tap",
      {method: "POST", body: JSON.stringify({x, y})}
    );
    if (!r || !r.ok) {
      alert("tap failed: " + ((r && r.error) || "?"));
      return;
    }
    // Refresh screenshot after ~500ms so user sees the effect.
    setTimeout(mobileScreenshot, 500);
  } catch (e) {
    alert("tap error: " + (e.message || e));
  }
}

async function mobileKey(name) {
  if (!_mobileSelectedSerial) return;
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/key",
      {method: "POST", body: JSON.stringify({key: name})}
    );
    if (!r || !r.ok) {
      alert("key " + name + " failed: " + ((r && r.error) || "?"));
      return;
    }
    setTimeout(mobileScreenshot, 400);
  } catch (e) {
    alert("key error: " + (e.message || e));
  }
}

async function mobileType() {
  if (!_mobileSelectedSerial) return;
  const el = document.getElementById("mobileTypeText");
  const text = (el && el.value) || "";
  if (!text) return;
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/type",
      {method: "POST", body: JSON.stringify({text})}
    );
    if (!r || !r.ok) {
      alert("type failed: " + ((r && r.error) || "?"));
      return;
    }
    if (el) el.value = "";
    setTimeout(mobileScreenshot, 400);
  } catch (e) {
    alert("type error: " + (e.message || e));
  }
}

async function mobileShell() {
  if (!_mobileSelectedSerial) return;
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
      {method: "POST", body: JSON.stringify({command: cmd})}
    );
    if (r && r.ok) {
      out.textContent = "$ " + cmd + "\n" + (r.stdout || "(no output)");
    } else {
      out.textContent = "error: " + ((r && r.error) || "?") + "\n" + (r && r.stderr ? r.stderr : "");
    }
  } catch (e) {
    out.textContent = "shell error: " + (e.message || e);
  }
}

// Auto-refresh + tab hook (same pattern as 29-tunnels.js).
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

// selectMobileDevice() also fetches info; keep the wrapper simple.
const _origSelectMobileDevice = selectMobileDevice;
selectMobileDevice = async function (serial, label) {
  await _origSelectMobileDevice(serial, label);
  await mobileLoadInfoCached();
};
