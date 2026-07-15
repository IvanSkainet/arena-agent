// Mobile: camera automation UI (v3.84.1).
//
// Wraps POST /v1/mobile/{s}/camera/{launch,shutter,pull,capture} and
// GET /v1/mobile/{s}/camera/photos. Depends on globals from 30-mobile.js
// (api, mobileShowError, mobileClearError, _fmtBackendError,
// _mobileSelectedSerial).

function _mobileCamStatus(msg) {
  const el = document.getElementById("mobileCameraStatus");
  if (el) el.textContent = msg;
}

function _mobileCamOpts() {
  return {
    wait_before_shutter_ms: parseInt(
      (document.getElementById("mobileCamWait") || {}).value || "1500", 10),
    max_size: parseInt(
      (document.getElementById("mobileCamSize") || {}).value || "1024", 10),
    format: (document.getElementById("mobileCamFormat") || {}).value || "jpeg",
  };
}

async function mobileCameraLaunch() {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  _mobileCamStatus("Launching camera app…");
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/camera/launch",
      {method: "POST", body: JSON.stringify({intent: "still"})});
    if (!r || !r.ok) {
      mobileShowError("Camera launch failed", _fmtBackendError("launch", r));
      _mobileCamStatus("");
      return;
    }
    _mobileCamStatus("✓ Camera app started. Screenshot the phone to verify.");
  } catch (e) {
    mobileShowError("Camera launch request failed", e && e.stack || String(e));
    _mobileCamStatus("");
  }
}

async function mobileCameraShutter() {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  _mobileCamStatus("Detecting shutter + tapping…");
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/camera/shutter",
      {method: "POST", body: JSON.stringify({})});
    if (!r || !r.ok) {
      mobileShowError("Shutter tap failed", _fmtBackendError("shutter", r));
      _mobileCamStatus("");
      return;
    }
    _mobileCamStatus(
      "✓ Tapped shutter at (" + r.shutter_x + ", " + r.shutter_y + ")\n"
      + "detected via: " + r.detected_via);
  } catch (e) {
    mobileShowError("Shutter request failed", e && e.stack || String(e));
    _mobileCamStatus("");
  }
}

async function mobileCameraCapture() {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  const opts = _mobileCamOpts();
  _mobileCamStatus(
    "Full capture flow: launch → wait "
    + opts.wait_before_shutter_ms + " ms → shutter → pull.");
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/camera/capture",
      {method: "POST", body: JSON.stringify(opts)});
    if (!r || !r.ok) {
      mobileShowError("Camera capture failed", _fmtBackendError("capture", r));
      _mobileCamStatus(
        "capture failed at stage: " + (r && r.stage || "?"));
      return;
    }
    _mobileCamStatus(
      "✓ " + r.source_path + "\n"
      + "  " + r.width + "×" + r.height + " · "
      + Math.round(r.size_bytes / 1024) + " KB · "
      + r.total_duration_ms + " ms · shutter=("
      + r.shutter.x + ", " + r.shutter.y + ")");
    // Render thumbnail from base64.
    const img = document.getElementById("mobileCameraThumb");
    if (img && r.bytes_b64) {
      img.src = "data:" + r.mime + ";base64," + r.bytes_b64;
      img.style.display = "";
    }
  } catch (e) {
    mobileShowError("Capture request failed", e && e.stack || String(e));
    _mobileCamStatus("");
  }
}

async function mobileCameraListPhotos() {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  _mobileCamStatus("Listing DCIM…");
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/camera/photos?limit=10");
    if (!r || !r.ok) {
      mobileShowError("List photos failed", _fmtBackendError("photos", r));
      _mobileCamStatus("");
      return;
    }
    const rows = (r.photos || []).map(
      (p) => "  " + p.modified + "  "
             + String(Math.round(p.size_bytes / 1024)).padStart(7)
             + " KB  " + p.name);
    _mobileCamStatus(
      "✓ " + r.count + " item(s) in DCIM:\n" + rows.join("\n"));
  } catch (e) {
    mobileShowError("List photos request failed", e && e.stack || String(e));
    _mobileCamStatus("");
  }
}


// ---------------------------------------------------------------------------
// Info-panel collapse memory used to live here; it moved to
// 34-mobile-info.js in v3.85.1 so that the ontoggle handler defined
// in body-16-mobile.html is guaranteed to exist by the time the
// browser parses that <details> element (script load order:
// 34 before 37).
