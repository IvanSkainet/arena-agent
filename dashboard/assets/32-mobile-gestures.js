// Mobile: gesture buttons + drag-to-swipe on the screenshot (v3.83.0).
//
// Depends on globals from 30-mobile.js and 31-mobile-screen.js.

// --- Named gesture buttons --------------------------------------------
async function mobileGesture(name) {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/gesture",
      {method: "POST", body: JSON.stringify({gesture: name})},
    );
    if (!r || !r.ok) {
      mobileShowError("Gesture " + name + " failed", _fmtBackendError("gesture", r));
      return;
    }
    _mobileRefreshBurst();
  } catch (e) {
    mobileShowError("Gesture request failed", e && e.stack || String(e));
  }
}

// --- Drag-to-swipe on the screenshot -----------------------------------
//
// Threshold in CSS px below which the pointer-up is treated as a plain
// tap (routed through the existing pixel-tap path). Above the threshold
// we translate to native pixel coords and issue a raw /swipe.
const _MOBILE_DRAG_THRESHOLD_PX = 8;

let _mobileDrag = null;   // {x, y, t, moved}

function _mobileImgToNative(img, cssX, cssY) {
  if (!_mobileShownWidth || !_mobileShownHeight) return null;
  const shownX = cssX * (_mobileShownWidth / img.clientWidth);
  const shownY = cssY * (_mobileShownHeight / img.clientHeight);
  const ratio = (_mobileNativeWidth && _mobileShownWidth)
    ? _mobileNativeWidth / _mobileShownWidth : 1;
  return {
    x: Math.round(shownX * ratio),
    y: Math.round(shownY * ratio),
  };
}

function mobilePointerDown(ev) {
  if (!_mobileSelectedSerial) return;
  const img = ev.currentTarget;
  const rect = img.getBoundingClientRect();
  _mobileDrag = {
    startX: ev.clientX - rect.left,
    startY: ev.clientY - rect.top,
    started: performance.now(),
    moved: false,
    img: img,
  };
  // Capture the pointer so pointerup fires on us even if user drags off
  // the image (into the shell console panel, for instance).
  try { img.setPointerCapture(ev.pointerId); } catch (_) {}
}

function mobilePointerMove(ev) {
  if (!_mobileDrag) return;
  const rect = _mobileDrag.img.getBoundingClientRect();
  const dx = (ev.clientX - rect.left) - _mobileDrag.startX;
  const dy = (ev.clientY - rect.top) - _mobileDrag.startY;
  if (Math.abs(dx) > _MOBILE_DRAG_THRESHOLD_PX
      || Math.abs(dy) > _MOBILE_DRAG_THRESHOLD_PX) {
    _mobileDrag.moved = true;
  }
}

async function mobilePointerUp(ev) {
  if (!_mobileDrag) return;
  const drag = _mobileDrag;
  _mobileDrag = null;
  const img = drag.img;
  const rect = img.getBoundingClientRect();
  const endX = ev.clientX - rect.left;
  const endY = ev.clientY - rect.top;
  const durationMs = Math.max(80, Math.round(performance.now() - drag.started));

  if (!drag.moved) {
    // Plain tap — reuse the tap path so audit records are consistent.
    const p = _mobileImgToNative(img, endX, endY);
    if (p) _mobileSendTap(p.x, p.y);
    return;
  }
  const from = _mobileImgToNative(img, drag.startX, drag.startY);
  const to = _mobileImgToNative(img, endX, endY);
  if (!from || !to) return;

  mobileClearError();
  try {
    // Cap duration so a very slow drag doesn't hang the request timeout.
    const dur = Math.min(3000, durationMs);
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/swipe",
      {method: "POST", body: JSON.stringify({
        x1: from.x, y1: from.y, x2: to.x, y2: to.y, duration_ms: dur,
      })},
    );
    if (!r || !r.ok) {
      mobileShowError(
        "Swipe (" + from.x + "," + from.y + ") → (" + to.x + "," + to.y + ") failed",
        _fmtBackendError("swipe", r),
      );
      return;
    }
    _mobileRefreshBurst();
  } catch (e) {
    mobileShowError("Swipe request failed", e && e.stack || String(e));
  }
}

// Called when the mouse leaves the image mid-drag on browsers that
// don't support pointer capture. Treat as a completed drag ending at
// the last known position.
function mobilePointerCancel() {
  _mobileDrag = null;
}
