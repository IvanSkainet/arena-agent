// Mobile: live H.264 mirror via MediaSource + WebSocket
// (v3.84.3 first cut, v3.84.6 python muxer, v3.84.7 late-subscriber
// seeding, v3.85.1 codec autodetect + hard-reset on MediaSource error).
//
// Backend: /v1/mobile/{s}/mirror streams fragmented MP4 chunks over WS.
// Each chunk is a full moof+mdat pair (one per video frame).
//
// The tricky bit that gave us the "black <video>, InvalidStateError:
// HTMLMediaElement.error is not null" bug in v3.84.7:
//
//   * Android's screenrecord AVC encoder can output any profile the
//     device happens to prefer -- Baseline (66), Main (77), or High
//     (100). It also picks the level based on resolution and bitrate.
//     A hardcoded MSE mime like `avc1.640028` (High @ L4.0) rejects
//     the init segment when the real stream is High @ L4.2 -- MSE
//     puts the <video> into an error state and every subsequent
//     appendBuffer throws InvalidStateError forever.
//
//   * Fix: don't pick the mime until the first init segment lands.
//     Parse the avcC box inside it, read profile/constraint/level,
//     build the canonical `avc1.PPCCLL` string, and only then call
//     addSourceBuffer with the exact codec the browser needs. If
//     MediaSource still rejects the segment, tear the whole pipeline
//     down and reopen with an even wider profile as a fallback.
//
// Depends on globals from 30-mobile.js: _mobileSelectedSerial,
// mobileShowError, mobileClearError, TOKEN.

let _mobileMirrorWs = null;
let _mobileMirrorMediaSource = null;
let _mobileMirrorSourceBuffer = null;
let _mobileMirrorCodec = null;            // "avc1.PPCCLL" once known.
let _mobileMirrorPendingInit = null;      // First ftyp+moov, held until SB opens.
let _mobileMirrorQueue = [];
let _mobileMirrorPendingReset = false;
let _mobileMirrorBytesReceived = 0;
let _mobileMirrorFragments = 0;
let _mobileMirrorStartedAt = 0;
let _mobileMirrorStatsTimer = null;
let _mobileMirrorErrorCount = 0;

function _mobileMirrorStatus(msg) {
  const el = document.getElementById("mobileMirrorStatus");
  if (el) el.textContent = msg || "";
}

function _mobileMirrorMeta(msg) {
  const el = document.getElementById("mobileMirrorMeta");
  if (el) el.textContent = msg || "";
}

// Parse the AVCDecoderConfigurationRecord out of an init segment.
// Returns "avc1.PPCCLL" hex string, or null if we can't find it.
function _mobileMirrorParseCodec(initBytes) {
  try {
    const bytes = new Uint8Array(initBytes);
    // Scan for the ASCII tag "avcC" -- it always sits inside the
    // stsd/avc1 box tree, and never appears in another box's payload
    // in an AVC-only init segment.
    for (let i = 0; i < bytes.length - 8; i++) {
      if (bytes[i] === 0x61 && bytes[i+1] === 0x76
          && bytes[i+2] === 0x63 && bytes[i+3] === 0x43) {
        // avcC body starts at i+4: configuration_version (1 byte),
        // AVCProfileIndication (1), profile_compatibility (1),
        // AVCLevelIndication (1), ...
        const profile = bytes[i+5];
        const compat  = bytes[i+6];
        const level   = bytes[i+7];
        const hex = (n) => n.toString(16).padStart(2, "0");
        return "avc1." + hex(profile) + hex(compat) + hex(level);
      }
    }
  } catch (_) {}
  return null;
}

// MediaSource picks a codec at addSourceBuffer time and never
// negotiates again. If we guessed wrong we must tear the whole thing
// down and rebuild.
function _mobileMirrorOpenSourceBuffer(codec) {
  if (!_mobileMirrorMediaSource
      || _mobileMirrorMediaSource.readyState !== "open") {
    return false;
  }
  const mime = 'video/mp4; codecs="' + codec + '"';
  if (!MediaSource.isTypeSupported(mime)) {
    mobileShowError("Live mirror codec unsupported",
      "This browser can't decode " + mime + ". Try Chrome or Edge.");
    return false;
  }
  try {
    _mobileMirrorSourceBuffer = _mobileMirrorMediaSource.addSourceBuffer(mime);
    _mobileMirrorSourceBuffer.mode = "segments";
    _mobileMirrorSourceBuffer.addEventListener(
      "updateend", _mobileMirrorFlushQueue);
    _mobileMirrorSourceBuffer.addEventListener("error", (e) => {
      console.warn("mirror sourcebuffer error", e);
    });
    _mobileMirrorCodec = codec;
    return true;
  } catch (e) {
    mobileShowError("SourceBuffer init failed", String(e));
    return false;
  }
}

async function mobileMirrorStart() {
  if (!_mobileSelectedSerial) return;
  if (_mobileMirrorWs) {
    _mobileMirrorStatus("already running");
    return;
  }
  mobileClearError();

  if (!("MediaSource" in window)) {
    mobileShowError("Live mirror not supported",
      "This browser doesn't have MediaSource Extensions.");
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
  _mobileMirrorPendingInit = null;
  _mobileMirrorCodec = null;
  _mobileMirrorErrorCount = 0;

  _mobileMirrorMediaSource = new MediaSource();
  video.src = URL.createObjectURL(_mobileMirrorMediaSource);
  video.style.display = "";
  // Autoplay muted so browsers actually start decoding without a click.
  try { video.muted = true; } catch (_) {}
  _mobileMirrorStatus("connecting…");

  // Wait for `sourceopen` -- but do NOT addSourceBuffer yet, we don't
  // know the codec string until the first init segment arrives.
  await new Promise((res) => {
    _mobileMirrorMediaSource.addEventListener("sourceopen", () => {
      // If an init segment already arrived, wire the SourceBuffer now.
      if (_mobileMirrorPendingInit) _mobileMirrorFlushQueue();
      res();
    }, {once: true});
  });

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const url = proto + "//" + location.host
    + "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/mirror"
    + "?size=" + encodeURIComponent(size)
    + "&bit_rate=" + bitrate
    + "&token=" + encodeURIComponent(TOKEN);

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
        // Next binary message is a fresh ftyp+moov. Discard whatever
        // codec/SourceBuffer we had -- the new segment might be a
        // different profile/level and MSE won't renegotiate.
        _mobileMirrorPendingReset = true;
      }
      return;
    }
    const chunk = ev.data;
    _mobileMirrorBytesReceived += chunk.byteLength;
    _mobileMirrorFragments += 1;

    // The first binary message right after `__init__` (or the very
    // first ever) is the init segment. We detect it by looking for
    // the ASCII "ftyp" tag near the start.
    const isInit = _mobileMirrorLooksLikeInit(chunk);
    if (isInit) {
      _mobileMirrorPendingInit = chunk;
      _mobileMirrorPendingReset = true;
    } else {
      _mobileMirrorQueue.push(chunk);
    }
    _mobileMirrorFlushQueue();
  };
  _mobileMirrorWs.onerror = () => {
    mobileShowError("Live mirror WS error",
      "WebSocket error — check the browser console for details.");
  };
  _mobileMirrorWs.onclose = (ev) => {
    _mobileMirrorStatus("closed (code " + ev.code + ")");
    _mobileMirrorTeardown();
  };
}

function _mobileMirrorLooksLikeInit(chunk) {
  if (!chunk || chunk.byteLength < 12) return false;
  const b = new Uint8Array(chunk, 0, 12);
  // Byte 4-7 of an ISOBMFF box is its 4CC tag. First box in an init
  // segment is always "ftyp".
  return b[4] === 0x66 && b[5] === 0x74 && b[6] === 0x79 && b[7] === 0x70;
}

function _mobileMirrorFlushQueue() {
  if (!_mobileMirrorMediaSource
      || _mobileMirrorMediaSource.readyState !== "open") return;

  // Reset requested: tear down the current SourceBuffer so the new
  // init segment can pick its own codec.
  if (_mobileMirrorPendingReset && !_mobileMirrorSourceBufferBusy()) {
    _mobileMirrorPendingReset = false;
    if (_mobileMirrorSourceBuffer) {
      try {
        _mobileMirrorSourceBuffer.removeEventListener(
          "updateend", _mobileMirrorFlushQueue);
      } catch (_) {}
      try {
        _mobileMirrorMediaSource.removeSourceBuffer(_mobileMirrorSourceBuffer);
      } catch (_) {}
      _mobileMirrorSourceBuffer = null;
      _mobileMirrorCodec = null;
    }
  }

  // If we have a pending init segment and no SourceBuffer yet,
  // create the SourceBuffer with the *actual* codec parsed from it.
  if (_mobileMirrorPendingInit && !_mobileMirrorSourceBuffer) {
    const codec = _mobileMirrorParseCodec(_mobileMirrorPendingInit)
                  || "avc1.42E01F";   // safe Baseline fallback
    if (!_mobileMirrorOpenSourceBuffer(codec)) {
      return;
    }
    // Append the init segment itself before draining the queue.
    const init = _mobileMirrorPendingInit;
    _mobileMirrorPendingInit = null;
    try {
      _mobileMirrorSourceBuffer.appendBuffer(init);
    } catch (e) {
      console.warn("mirror init appendBuffer failed:", e);
      _mobileMirrorHandleMediaError();
    }
    return;   // wait for updateend before draining media fragments
  }

  if (!_mobileMirrorSourceBuffer || _mobileMirrorSourceBuffer.updating) {
    return;
  }
  if (_mobileMirrorQueue.length === 0) return;

  const chunk = _mobileMirrorQueue.shift();
  try {
    _mobileMirrorSourceBuffer.appendBuffer(chunk);
  } catch (e) {
    if (e && e.name === "QuotaExceededError") {
      // SourceBuffer full: trim first half of oldest range, retry.
      const buffered = _mobileMirrorSourceBuffer.buffered;
      if (buffered.length > 0) {
        const start = buffered.start(0);
        const end = buffered.end(0);
        try {
          _mobileMirrorSourceBuffer.remove(start, start + (end - start) / 2);
        } catch (_) {}
      }
      _mobileMirrorQueue.unshift(chunk);
    } else if (e && e.name === "InvalidStateError") {
      // MediaSource put the <video> into an error state. Rebuild
      // the whole pipeline; a new init segment will follow on the
      // next screenrecord segment restart (~170s) OR from the
      // late-subscriber seed if we reconnect.
      _mobileMirrorHandleMediaError();
    } else {
      console.warn("mirror appendBuffer failed:", e);
    }
  }
}

function _mobileMirrorSourceBufferBusy() {
  return _mobileMirrorSourceBuffer && _mobileMirrorSourceBuffer.updating;
}

function _mobileMirrorHandleMediaError() {
  _mobileMirrorErrorCount += 1;
  const video = document.getElementById("mobileMirrorVideo");
  const err = video && video.error;
  const errMsg = err ? ("MediaError " + err.code + ": " + (err.message || "")) : "InvalidState";
  console.warn("mirror media error -- reconnecting", errMsg);
  if (_mobileMirrorErrorCount >= 3) {
    _mobileMirrorStatus("giving up after 3 media errors");
    mobileShowError("Live mirror stuck",
      "MediaSource rejected the stream 3 times in a row. Last error: "
      + errMsg + ". Try a different `size` (e.g. 540x1200) or `bit_rate`.");
    mobileMirrorStop();
    return;
  }
  _mobileMirrorStatus("media error, reconnecting…");
  // Full restart: close WS + MediaSource, then reopen. The bridge
  // seeds the next subscriber with the cached init + keyframe (v3.84.7),
  // so playback resumes within a couple of seconds.
  const wasWs = _mobileMirrorWs;
  _mobileMirrorWs = null;   // suppress teardown's ws-close callback
  try { wasWs && wasWs.close(1000, "reset"); } catch (_) {}
  _mobileMirrorTeardown(/*keepErrorCount=*/true);
  setTimeout(() => { mobileMirrorStart(); }, 500);
}

function _mobileMirrorUpdateMeta() {
  const elapsedMs = performance.now() - _mobileMirrorStartedAt;
  if (elapsedMs <= 0) return;
  const kbps = Math.round((_mobileMirrorBytesReceived * 8) / elapsedMs);
  const fps = (_mobileMirrorFragments * 1000) / elapsedMs;
  const codec = _mobileMirrorCodec ? (" · " + _mobileMirrorCodec) : "";
  _mobileMirrorMeta(
    Math.round(_mobileMirrorBytesReceived / 1024) + " KB · "
    + kbps + " kbps · " + fps.toFixed(1) + " fps" + codec
  );
}

async function mobileMirrorStop() {
  if (!_mobileMirrorWs && !_mobileMirrorMediaSource) {
    _mobileMirrorStatus("not running");
    return;
  }
  const wasWs = _mobileMirrorWs;
  _mobileMirrorWs = null;
  try { wasWs && wasWs.close(1000, "user stop"); } catch (_) {}
  _mobileMirrorTeardown();
  try {
    await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/mirror/stop",
      {method: "POST", body: JSON.stringify({})}
    );
  } catch (_) {}
}

function _mobileMirrorTeardown(keepErrorCount) {
  if (_mobileMirrorStatsTimer) {
    clearInterval(_mobileMirrorStatsTimer);
    _mobileMirrorStatsTimer = null;
  }
  _mobileMirrorSourceBuffer = null;
  _mobileMirrorCodec = null;
  _mobileMirrorPendingInit = null;
  _mobileMirrorQueue = [];
  _mobileMirrorPendingReset = false;
  if (!keepErrorCount) _mobileMirrorErrorCount = 0;
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
    try { video.removeAttribute("src"); video.load(); } catch (_) {}
  }
}

function _val(id, dflt) {
  const el = document.getElementById(id);
  return el ? (el.value || dflt) : dflt;
}
