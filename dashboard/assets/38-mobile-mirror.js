// Mobile: live H.264 mirror via MediaSource + WebSocket (v3.84.3).
//
// Backend: /v1/mobile/{s}/mirror streams fragmented MP4 chunks over WS.
// This file wraps a plain <video> with a MediaSource whose SourceBuffer
// gets the chunks appended one-by-one. `__init__` control messages tell
// us to re-create the SourceBuffer (screenrecord segment restart every
// 170s per Android's AVC cap — see arena/mobile/mirror.py).
//
// Depends on globals from 30-mobile.js: _mobileSelectedSerial,
// mobileShowError, mobileClearError.

const _MIRROR_MIME = 'video/mp4; codecs="avc1.640028"';   // H.264 High profile
let _mobileMirrorWs = null;
let _mobileMirrorMediaSource = null;
let _mobileMirrorSourceBuffer = null;
let _mobileMirrorQueue = [];
let _mobileMirrorPendingReset = false;
let _mobileMirrorBytesReceived = 0;
let _mobileMirrorFragments = 0;
let _mobileMirrorStartedAt = 0;
let _mobileMirrorStatsTimer = null;

function _mobileMirrorStatus(msg) {
  const el = document.getElementById("mobileMirrorStatus");
  if (el) el.textContent = msg || "";
}

function _mobileMirrorMeta(msg) {
  const el = document.getElementById("mobileMirrorMeta");
  if (el) el.textContent = msg || "";
}

async function mobileMirrorStart() {
  if (!_mobileSelectedSerial) return;
  if (_mobileMirrorWs) {
    _mobileMirrorStatus("already running");
    return;
  }
  mobileClearError();

  if (!("MediaSource" in window) || !MediaSource.isTypeSupported(_MIRROR_MIME)) {
    mobileShowError("Live mirror not supported",
      "This browser doesn't support MediaSource Extensions for "
      + _MIRROR_MIME + ". Use Chrome, Edge, or Firefox 118+.");
    return;
  }
  const video = document.getElementById("mobileMirrorVideo");
  if (!video) return;

  const size = _val("mobileMirrorSize", "720x1600");
  const bitrate = parseInt(_val("mobileMirrorBitrate", "4000000"), 10);
  _mobileMirrorBytesReceived = 0;
  _mobileMirrorFragments = 0;
  _mobileMirrorStartedAt = performance.now();
  _mobileMirrorQueue = [];
  _mobileMirrorPendingReset = false;

  _mobileMirrorMediaSource = new MediaSource();
  video.src = URL.createObjectURL(_mobileMirrorMediaSource);
  video.style.display = "";
  _mobileMirrorStatus("connecting…");

  await new Promise((res) => {
    _mobileMirrorMediaSource.addEventListener("sourceopen", () => {
      try {
        _mobileMirrorSourceBuffer = _mobileMirrorMediaSource.addSourceBuffer(_MIRROR_MIME);
        _mobileMirrorSourceBuffer.mode = "segments";
        _mobileMirrorSourceBuffer.addEventListener("updateend", _mobileMirrorFlushQueue);
      } catch (e) {
        mobileShowError("MediaSource init failed", e && e.stack || String(e));
      }
      res();
    }, {once: true});
  });

  // Build WS URL. Auth token goes in a query param because browsers
  // don't let you set Authorization on a WebSocket handshake.
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = proto + "//" + location.host
    + "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/mirror"
    + "?size=" + encodeURIComponent(size)
    + "&bit_rate=" + bitrate
    + "&token=" + encodeURIComponent(TOKEN);
  // The bridge's require_auth reads bearer tokens from either the
  // Authorization header OR a `token=` query param, so this works
  // without any handshake tricks. If your bridge doesn't accept
  // ?token= yet, the WS 401s and we surface the error.

  _mobileMirrorWs = new WebSocket(url);
  _mobileMirrorWs.binaryType = "arraybuffer";
  _mobileMirrorWs.onopen = () => {
    _mobileMirrorStatus("streaming");
    if (_mobileMirrorStatsTimer) clearInterval(_mobileMirrorStatsTimer);
    _mobileMirrorStatsTimer = setInterval(_mobileMirrorUpdateMeta, 1000);
  };
  _mobileMirrorWs.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      if (ev.data === "__init__") {
        // New pipeline segment started — the next fMP4 fragment carries
        // a fresh moov box, so we need a fresh SourceBuffer.
        _mobileMirrorPendingReset = true;
      }
      return;
    }
    const chunk = ev.data;
    _mobileMirrorBytesReceived += chunk.byteLength;
    _mobileMirrorFragments += 1;
    _mobileMirrorQueue.push(chunk);
    _mobileMirrorFlushQueue();
  };
  _mobileMirrorWs.onerror = (e) => {
    mobileShowError("Live mirror WS error",
      "WebSocket error — check the browser console for details.");
  };
  _mobileMirrorWs.onclose = (ev) => {
    _mobileMirrorStatus("closed (code " + ev.code + ")");
    _mobileMirrorTeardown();
  };
}

function _mobileMirrorFlushQueue() {
  if (!_mobileMirrorSourceBuffer || _mobileMirrorSourceBuffer.updating) return;
  if (_mobileMirrorPendingReset) {
    // Rebuild the SourceBuffer so a new moov box is accepted cleanly.
    _mobileMirrorPendingReset = false;
    try {
      _mobileMirrorMediaSource.removeSourceBuffer(_mobileMirrorSourceBuffer);
    } catch (_) {}
    try {
      _mobileMirrorSourceBuffer = _mobileMirrorMediaSource.addSourceBuffer(_MIRROR_MIME);
      _mobileMirrorSourceBuffer.mode = "segments";
      _mobileMirrorSourceBuffer.addEventListener("updateend", _mobileMirrorFlushQueue);
    } catch (e) {
      mobileShowError("SourceBuffer reset failed", String(e));
      return;
    }
  }
  if (_mobileMirrorQueue.length === 0) return;
  const chunk = _mobileMirrorQueue.shift();
  try {
    _mobileMirrorSourceBuffer.appendBuffer(chunk);
  } catch (e) {
    // QuotaExceededError = the SourceBuffer is full. Trim the oldest
    // buffered range and retry on the next `updateend`.
    if (e && e.name === "QuotaExceededError") {
      const buffered = _mobileMirrorSourceBuffer.buffered;
      if (buffered.length > 0) {
        const start = buffered.start(0);
        const end = buffered.end(0);
        // Trim the first half of the oldest range.
        try {
          _mobileMirrorSourceBuffer.remove(start, start + (end - start) / 2);
        } catch (_) {}
      }
      _mobileMirrorQueue.unshift(chunk);
    } else {
      console.warn("mirror appendBuffer failed:", e);
    }
  }
}

function _mobileMirrorUpdateMeta() {
  const elapsedMs = performance.now() - _mobileMirrorStartedAt;
  if (elapsedMs <= 0) return;
  const kbps = Math.round((_mobileMirrorBytesReceived * 8) / elapsedMs);
  const fps = (_mobileMirrorFragments * 1000) / elapsedMs;
  _mobileMirrorMeta(
    Math.round(_mobileMirrorBytesReceived / 1024) + " KB · "
    + kbps + " kbps · " + fps.toFixed(1) + " fps"
  );
}

async function mobileMirrorStop() {
  if (!_mobileMirrorWs) {
    _mobileMirrorStatus("not running");
    return;
  }
  try {
    _mobileMirrorWs.close(1000, "user stop");
  } catch (_) {}
  _mobileMirrorTeardown();
  // Also tell the server so it can tear the pipeline down immediately
  // instead of waiting for the "no subscribers" check.
  try {
    await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/mirror/stop",
      {method: "POST", body: JSON.stringify({})}
    );
  } catch (_) {}
}

function _mobileMirrorTeardown() {
  if (_mobileMirrorStatsTimer) {
    clearInterval(_mobileMirrorStatsTimer);
    _mobileMirrorStatsTimer = null;
  }
  _mobileMirrorWs = null;
  _mobileMirrorSourceBuffer = null;
  if (_mobileMirrorMediaSource) {
    try {
      if (_mobileMirrorMediaSource.readyState === "open") {
        _mobileMirrorMediaSource.endOfStream();
      }
    } catch (_) {}
    _mobileMirrorMediaSource = null;
  }
  const video = document.getElementById("mobileMirrorVideo");
  if (video) {
    try { video.pause(); } catch (_) {}
    try { URL.revokeObjectURL(video.src); } catch (_) {}
  }
}

function _val(id, dflt) {
  const el = document.getElementById(id);
  return el ? (el.value || dflt) : dflt;
}
