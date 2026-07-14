// Mobile: mouse-wheel + physical-keyboard forwarding (v3.83.3).
//
// The screenshot <img> now emits synthesised mouse-wheel and key events
// to the phone whenever the pointer is over it and the user rolls the
// wheel / presses keys. Previously the only ways to scroll were
// mouse-drag swipes and the semantic gesture buttons — this closes the
// gap and finally makes "just use the phone" feel real over Tailnet.
//
// Depends on globals from 30-mobile.js and 31-mobile-screen.js:
//   _mobileSelectedSerial, _mobileNativeWidth/Height,
//   _mobileShownWidth/Height, api(), mobileShowError(),
//   _fmtBackendError(), _mobileRefreshBurst().

// --- Wheel forwarding ---------------------------------------------------
//
// Browsers emit `wheel` events with `deltaX/deltaY` in pixel units on
// Chrome/Edge and in "line" units on Firefox. Both cases are handled
// by normalising to a small fixed scroll magnitude — the phone doesn't
// need pixel-perfect wheel deltas, it just needs "one notch up" or
// "one notch down" to scroll a list by a chunk.

const _MOBILE_WHEEL_NOTCH_MIN_MS = 60;   // rate limit between broadcast wheel events
let _mobileWheelLastSent = 0;
let _mobileWheelAccumX = 0;
let _mobileWheelAccumY = 0;

function mobileWheelHandler(ev) {
  if (!_mobileSelectedSerial) return;
  if (!_mobileNativeWidth || !_mobileNativeHeight) return;
  ev.preventDefault();

  // deltaMode 0 = pixel, 1 = line, 2 = page. Normalise to a rough
  // "wheel notch" count (1 notch = ~100 px on Chrome, 3 lines on FF).
  const line = ev.deltaMode === 1 ? 1 : (ev.deltaMode === 2 ? 3 : 1 / 100);
  _mobileWheelAccumY += ev.deltaY * line;
  _mobileWheelAccumX += ev.deltaX * line;

  const now = performance.now();
  if (now - _mobileWheelLastSent < _MOBILE_WHEEL_NOTCH_MIN_MS) return;
  _mobileWheelLastSent = now;

  // Round to whole notches (positive = scroll content up = wheel down
  // on the browser). Android `input mouse scroll --axis VSCROLL,N`
  // uses the same sign convention as a real mouse wheel: positive V
  // = wheel-up = content-down. Browsers use the opposite (deltaY > 0
  // means content moves up). Flip the sign so a browser scroll down
  // moves the phone content down too.
  const vNotches = -Math.trunc(_mobileWheelAccumY);
  const hNotches = -Math.trunc(_mobileWheelAccumX);
  if (vNotches === 0 && hNotches === 0) return;
  _mobileWheelAccumY -= -vNotches;
  _mobileWheelAccumX -= -hNotches;

  // Coord under the pointer, translated to native pixels.
  const img = ev.currentTarget;
  const rect = img.getBoundingClientRect();
  const cssX = ev.clientX - rect.left;
  const cssY = ev.clientY - rect.top;
  const shownRatio = _mobileNativeWidth / (_mobileShownWidth || img.clientWidth);
  const nativeX = Math.round(cssX * (img.clientWidth ? _mobileShownWidth / img.clientWidth : 1) * shownRatio);
  const nativeY = Math.round(cssY * (img.clientHeight ? _mobileShownHeight / img.clientHeight : 1) * shownRatio);

  _mobileSendScroll(nativeX, nativeY, vNotches, hNotches);
}

async function _mobileSendScroll(x, y, vscroll, hscroll) {
  mobileClearError();
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/scroll",
      {method: "POST", body: JSON.stringify({x, y, vscroll, hscroll})},
    );
    if (!r || !r.ok) {
      mobileShowError(
        "Scroll (v=" + vscroll + ", h=" + hscroll + ") failed",
        _fmtBackendError("scroll", r),
      );
      return;
    }
    _mobileRefreshBurst();
  } catch (e) {
    mobileShowError("Scroll request failed", e && e.stack || String(e));
  }
}


// --- Physical keyboard forwarding --------------------------------------
//
// When the screenshot area is focused (via tabindex=0 + click), keydown
// events on the browser are translated into `key` or `key_combo` calls
// on the phone. This is opt-in — we don't want ordinary Ctrl+F on the
// Dashboard to teleport to the phone — so the user toggles "kbd" in the
// screen toolbar to enable it.

let _mobileKbdActive = false;

// KeyboardEvent.code → Android KEYCODE name (without the prefix).
const _MOBILE_KEY_MAP = {
  Enter: "ENTER",         NumpadEnter: "ENTER",
  Backspace: "DEL",       Delete: "FORWARD_DEL",
  Tab: "TAB",             Escape: "ESCAPE",       Space: "SPACE",
  ArrowUp: "DPAD_UP",     ArrowDown: "DPAD_DOWN",
  ArrowLeft: "DPAD_LEFT", ArrowRight: "DPAD_RIGHT",
  Home: "MOVE_HOME",      End: "MOVE_END",
  PageUp: "PAGE_UP",      PageDown: "PAGE_DOWN",
  ContextMenu: "MENU",
};
// F1..F12
for (let n = 1; n <= 12; n++) _MOBILE_KEY_MAP["F" + n] = "F" + n;
// Digits 0-9
for (let n = 0; n <= 9; n++) {
  _MOBILE_KEY_MAP["Digit" + n] = String(n);
  _MOBILE_KEY_MAP["Numpad" + n] = String(n);
}
// Letters A-Z
for (let c = 65; c <= 90; c++) {
  _MOBILE_KEY_MAP["Key" + String.fromCharCode(c)] = String.fromCharCode(c);
}

function mobileToggleKeyboard(checkbox) {
  _mobileKbdActive = !!(checkbox && checkbox.checked);
  const label = document.getElementById("mobileKbdStatus");
  if (label) {
    label.textContent = _mobileKbdActive
      ? "keyboard → phone (focus the screen area, then type)"
      : "";
  }
}

function _mobileKbdModifierNames(ev) {
  const mods = [];
  if (ev.ctrlKey || ev.metaKey) mods.push("CTRL_LEFT");
  if (ev.altKey) mods.push("ALT_LEFT");
  if (ev.shiftKey) mods.push("SHIFT_LEFT");
  return mods;
}

async function mobileKeyHandler(ev) {
  if (!_mobileKbdActive) return;
  if (!_mobileSelectedSerial) return;
  // Ignore modifier-only presses (Shift by itself) and repeats.
  if (ev.repeat) return;
  if (["ShiftLeft", "ShiftRight", "ControlLeft", "ControlRight",
       "AltLeft", "AltRight", "MetaLeft", "MetaRight"].includes(ev.code)) {
    return;
  }
  const mapped = _MOBILE_KEY_MAP[ev.code];
  if (!mapped) return;   // unmapped browser key — let it bubble
  ev.preventDefault();
  ev.stopPropagation();

  const mods = _mobileKbdModifierNames(ev);
  mobileClearError();
  try {
    if (mods.length > 0 && mods.length + 1 <= 4) {
      // Ctrl+A, Shift+Alt+Tab, etc. → key_combo
      await api(
        "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/key_combo",
        {method: "POST", body: JSON.stringify({keys: [...mods, mapped]})},
      );
    } else {
      // Single key.
      await api(
        "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/key",
        {method: "POST", body: JSON.stringify({key: mapped})},
      );
    }
    _mobileRefreshBurst();
  } catch (e) {
    mobileShowError("Keyboard forward failed", e && e.stack || String(e));
  }
}

// Focus helper: clicking the screenshot area gives it keyboard focus
// so subsequent keydowns are captured by mobileKeyHandler. Without
// this the first keystroke goes to whatever was previously focused
// (usually the URL bar or a text field elsewhere in the dashboard).
function mobileFocusScreen() {
  const wrap = document.getElementById("mobileScreenshotWrap");
  if (wrap) wrap.focus();
}
