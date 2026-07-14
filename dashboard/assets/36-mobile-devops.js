// Mobile: devops UI (v3.83.5).
//
// Wireless ADB pair/connect/disconnect wizard, ADBKeyboard installer
// with SHA-256 consent, and a generic APK-install form. Lives in its
// own file so 30-mobile.js stays focused on the per-device controls.
//
// Depends on globals from 30-mobile.js:
//   api(), mobileShowError(), mobileClearError(), _fmtBackendError().

// ---------------------------------------------------------------------------
// Wireless ADB
// ---------------------------------------------------------------------------

async function mobileWirelessPair() {
  const host = _mobileWlValue("mobileWlPairHost");
  const port = parseInt(_mobileWlValue("mobileWlPairPort"), 10);
  const code = _mobileWlValue("mobileWlPairCode");
  if (!host || !port || !code) {
    mobileShowError("Missing pairing fields",
      "Fill in host, port and the 6-digit pairing code shown on the phone.");
    return;
  }
  _mobileWlStatus("Pairing…");
  mobileClearError();
  try {
    const r = await api("/v1/mobile/pair",
      {method: "POST", body: JSON.stringify({host, port, code})});
    if (!r || !r.ok) {
      mobileShowError("Pair failed", _fmtBackendError("pair", r));
      _mobileWlStatus("");
      return;
    }
    _mobileWlStatus("✓ Paired. Now enter the CONNECT port (different from pair port).");
    // Auto-fill the connect host so the user only has to type the connect
    // port and click Connect.
    const connectHost = document.getElementById("mobileWlConnectHost");
    if (connectHost && !connectHost.value) connectHost.value = host;
    const connectPort = document.getElementById("mobileWlConnectPort");
    if (connectPort) connectPort.focus();
    // Wipe the pairing code from the DOM — it's single-use and short-lived.
    const codeEl = document.getElementById("mobileWlPairCode");
    if (codeEl) codeEl.value = "";
  } catch (e) {
    mobileShowError("Pair request failed", e && e.stack || String(e));
    _mobileWlStatus("");
  }
}

async function mobileWirelessConnect() {
  const host = _mobileWlValue("mobileWlConnectHost");
  const port = parseInt(_mobileWlValue("mobileWlConnectPort"), 10);
  if (!host || !port) {
    mobileShowError("Missing connect fields",
      "Fill in host and port (the 'IP address & Port' shown on the phone).");
    return;
  }
  _mobileWlStatus("Connecting…");
  mobileClearError();
  try {
    const r = await api("/v1/mobile/connect",
      {method: "POST", body: JSON.stringify({host, port})});
    if (!r || !r.ok) {
      mobileShowError("Connect failed", _fmtBackendError("connect", r));
      _mobileWlStatus("");
      return;
    }
    _mobileWlStatus("✓ Connected: " + r.serial + " — refreshing device list…");
    setTimeout(refreshMobile, 500);
  } catch (e) {
    mobileShowError("Connect request failed", e && e.stack || String(e));
    _mobileWlStatus("");
  }
}

async function mobileWirelessDisconnectAll() {
  if (!confirm("Disconnect ALL wireless ADB devices? USB devices are unaffected."))
    return;
  mobileClearError();
  try {
    const r = await api("/v1/mobile/disconnect",
      {method: "POST", body: JSON.stringify({})});
    if (!r || !r.ok) {
      mobileShowError("Disconnect failed", _fmtBackendError("disconnect", r));
      return;
    }
    _mobileWlStatus("✓ Disconnected: " + (r.stdout || "(no wireless devices)"));
    setTimeout(refreshMobile, 500);
  } catch (e) {
    mobileShowError("Disconnect request failed", e && e.stack || String(e));
  }
}

function _mobileWlValue(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : "";
}

function _mobileWlStatus(msg) {
  const el = document.getElementById("mobileWlStatus");
  if (el) el.textContent = msg;
}


// ---------------------------------------------------------------------------
// ADBKeyboard installer (from v3.83.2 backend, UI new in v3.83.5)
// ---------------------------------------------------------------------------
//
// Two-step consent flow:
//   1. GET /v1/mobile/helpers/status — returns SHA-256 + required
//      consent token. UI shows both so the user knows exactly what
//      APK is about to be installed.
//   2. POST /v1/mobile/{serial}/helpers/install with that token.

async function mobileHelperInstall() {
  const serial = _mobileSelectedSerial;
  if (!serial) {
    mobileShowError("No device selected",
      "Pick a device first, then install the ADBKeyboard helper.");
    return;
  }
  mobileClearError();
  _mobileHelperStatus("Fetching APK metadata…");
  let status;
  try {
    status = await api("/v1/mobile/helpers/status");
  } catch (e) {
    mobileShowError("helpers/status failed", e && e.stack || String(e));
    return;
  }
  if (!status || !status.ok) {
    mobileShowError("Bundled ADBKeyboard not shippable",
      _fmtBackendError("helpers/status", status));
    return;
  }
  const consent = status.required_consent;
  const msg = "Install ADBKeyboard helper on this device?\n\n"
    + "Package: " + (status.package || "com.android.adbkeyboard") + "\n"
    + "Version: " + (status.version || "?") + "\n"
    + "SHA-256: " + (status.sha256 || "?") + "\n"
    + "Size: " + Math.round((status.size_bytes || 0) / 1024) + " KB\n\n"
    + "Enables non-ASCII (cyrillic, emoji) input via ADB_INPUT_B64 broadcast. "
    + "You'll need to accept an on-device 'Install this app?' dialog on the phone.";
  if (!confirm(msg)) {
    _mobileHelperStatus("");
    return;
  }
  _mobileHelperStatus("Pushing APK + waiting for on-device dialog…");
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(serial) + "/helpers/install",
      {method: "POST", body: JSON.stringify({consent})});
    if (!r || !r.ok) {
      mobileShowError("ADBKeyboard install failed", _fmtBackendError("install", r));
      _mobileHelperStatus("");
      return;
    }
    _mobileHelperStatus("✓ Installed. Click 'Activate ADBKeyboard' to switch IME.");
  } catch (e) {
    mobileShowError("Install request failed", e && e.stack || String(e));
    _mobileHelperStatus("");
  }
}

async function mobileHelperActivate() {
  const serial = _mobileSelectedSerial;
  if (!serial) return;
  mobileClearError();
  _mobileHelperStatus("Switching IME to ADBKeyboard…");
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(serial) + "/ime/set",
      {method: "POST", body: JSON.stringify({})});
    if (!r || !r.ok) {
      mobileShowError("ime/set failed", _fmtBackendError("ime_set", r));
      _mobileHelperStatus("");
      return;
    }
    _mobileHelperStatus("✓ ADBKeyboard is now the active IME. Non-ASCII typing works.");
  } catch (e) {
    mobileShowError("ime/set request failed", e && e.stack || String(e));
    _mobileHelperStatus("");
  }
}

async function mobileHelperReset() {
  const serial = _mobileSelectedSerial;
  if (!serial) return;
  if (!confirm("Reset the IME back to the system default? "
             + "ADBKeyboard stays installed but stops being active.")) return;
  mobileClearError();
  _mobileHelperStatus("Resetting IME…");
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(serial) + "/ime/reset",
      {method: "POST", body: JSON.stringify({})});
    if (!r || !r.ok) {
      mobileShowError("ime/reset failed", _fmtBackendError("ime_reset", r));
      _mobileHelperStatus("");
      return;
    }
    _mobileHelperStatus("✓ IME reset.");
  } catch (e) {
    mobileShowError("ime/reset request failed", e && e.stack || String(e));
    _mobileHelperStatus("");
  }
}

function _mobileHelperStatus(msg) {
  const el = document.getElementById("mobileHelperStatus");
  if (el) el.textContent = msg;
}


// ---------------------------------------------------------------------------
// Generic APK install — path-based (bridge staging directory).
// ---------------------------------------------------------------------------

async function mobileApkPrepare() {
  const path = _mobileWlValue("mobileApkPath");
  if (!path) {
    mobileShowError("Missing APK path",
      "Enter the path of an APK under the bridge's /tmp/arena-apk-staging directory.");
    return;
  }
  mobileClearError();
  const status = document.getElementById("mobileApkStatus");
  if (status) status.textContent = "Reading APK + computing SHA-256…";
  try {
    const r = await api("/v1/mobile/apk/prepare",
      {method: "POST", body: JSON.stringify({apk_path: path})});
    if (!r || !r.ok) {
      mobileShowError("APK prepare failed", _fmtBackendError("apk/prepare", r));
      if (status) status.textContent = "";
      return;
    }
    // Stash the sha + consent + package on a hidden field so the
    // Install button reads it back without a second round-trip.
    const sha = document.getElementById("mobileApkSha");
    if (sha) sha.value = r.sha256 || "";
    const consent = document.getElementById("mobileApkConsent");
    if (consent) consent.value = r.required_consent || "";
    if (status) {
      const sig = r.signature_check || {};
      const sigLine = sig.available === false ? "apksigner not installed on bridge"
                    : sig.verified === true ? "✓ signature verified"
                    : sig.verified === false ? "✗ signature INVALID: " + (sig.hint || "")
                    : "signature check skipped";
      status.textContent =
        "Package: " + (r.package || "(unknown)") + "\n"
        + "SHA-256: " + r.sha256 + "\n"
        + "Size: " + Math.round(r.size_bytes / 1024) + " KB\n"
        + "Signature: " + sigLine + "\n"
        + "Consent token: " + r.required_consent + "\n\n"
        + "Click 'Install' to push + `pm install -r` on the selected device. "
        + "You'll need to accept an on-device dialog on the phone.";
    }
  } catch (e) {
    mobileShowError("APK prepare request failed", e && e.stack || String(e));
    if (status) status.textContent = "";
  }
}

async function mobileApkInstall() {
  const serial = _mobileSelectedSerial;
  if (!serial) {
    mobileShowError("No device selected",
      "Pick a device first, then install the APK.");
    return;
  }
  const path = _mobileWlValue("mobileApkPath");
  const consent = _mobileWlValue("mobileApkConsent");
  if (!path || !consent) {
    mobileShowError("Prepare first",
      "Click 'Prepare' to compute the SHA-256 and get a consent token, then Install.");
    return;
  }
  mobileClearError();
  const status = document.getElementById("mobileApkStatus");
  if (status) status.textContent += "\n\nInstalling — waiting for on-device dialog…";
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(serial) + "/apk/install",
      {method: "POST", body: JSON.stringify({apk_path: path, consent})});
    if (!r || !r.ok) {
      mobileShowError("APK install failed", _fmtBackendError("apk/install", r));
      return;
    }
    if (status) status.textContent += "\n✓ Success.";
  } catch (e) {
    mobileShowError("APK install request failed", e && e.stack || String(e));
  }
}
