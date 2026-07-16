// ===== TERMINAL: ANSI SGR renderer (v4.15.0) =====
// Convert a raw shell-output string (with ESC[...m sequences)
// into safe HTML: text is escape()'d first, then SGR runs are
// wrapped in <span> elements whose inline styles carry the
// resolved colour + bold/dim/underline attributes.
//
// Scope: SGR ("Select Graphic Rendition") only. Cursor moves,
// clear-screen, save/restore-cursor, private modes -- all
// stripped. Terminal tab is a scrollback pane, not a real TTY;
// letting an app repaint over previous output would be worse
// than not rendering escapes at all.
//
// Supported SGR codes:
//   0             reset
//   1 / 22        bold on / off
//   2             dim on
//   3 / 23        italic on / off
//   4 / 24        underline on / off
//   7 / 27        inverse on / off  (swap fg/bg)
//   30..37        basic foreground
//   40..47        basic background
//   90..97        bright foreground
//   100..107      bright background
//   38;5;N        256-colour foreground
//   48;5;N        256-colour background
//   38;2;R;G;B    truecolour foreground
//   48;2;R;G;B    truecolour background
//   39 / 49       default fg / bg
//
// Anything else (blink, hidden, framed, ...) is accepted
// silently and produces no visual change. The classifier is
// deliberately permissive so an unknown code doesn't dump a
// literal '[47;5;123m' into the output pane.

// Palette. Mirrors the classic xterm defaults (not too bright,
// still legible on the dark #0f0f23 dashboard background). The
// bright colours are the standard "brighter" set, not a
// gratuitous saturation bump.
const __ANSI_BASIC = [
  "#000000", "#cc0000", "#4e9a06", "#c4a000",
  "#3465a4", "#75507b", "#06989a", "#d3d7cf",
];
const __ANSI_BRIGHT = [
  "#555753", "#ef2929", "#8ae234", "#fce94f",
  "#729fcf", "#ad7fa8", "#34e2e2", "#eeeeec",
];

// xterm 256-colour cube. Indexes 0..15 mirror the basic + bright
// palettes; 16..231 form a 6x6x6 cube; 232..255 a 24-step
// grayscale ramp. Rebuilt once at load time.
const __ANSI_XTERM256 = (function () {
  const out = __ANSI_BASIC.concat(__ANSI_BRIGHT);
  const steps = [0, 95, 135, 175, 215, 255];
  for (let r = 0; r < 6; r++) {
    for (let g = 0; g < 6; g++) {
      for (let b = 0; b < 6; b++) {
        out.push("#" +
          steps[r].toString(16).padStart(2, "0") +
          steps[g].toString(16).padStart(2, "0") +
          steps[b].toString(16).padStart(2, "0"));
      }
    }
  }
  for (let i = 0; i < 24; i++) {
    const v = 8 + i * 10;
    const h = v.toString(16).padStart(2, "0");
    out.push("#" + h + h + h);
  }
  return out;
})();

function __ansiEsc(s) {
  // Local esc(): use the same helper the rest of the dashboard
  // exposes as ``esc``. If it's missing (very early boot) fall
  // back to a minimal replacer so a stray call from module scope
  // doesn't throw ReferenceError before 00-core.js has loaded.
  if (typeof esc === "function") return esc(s);
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function __ansiStyleFromState(st) {
  // Build the inline style="" string from a state object. Empty
  // -> return "" so the caller can skip emitting a <span> at all.
  const parts = [];
  let fg = st.fg;
  let bg = st.bg;
  if (st.inverse) { const t = fg; fg = bg; bg = t; }
  if (fg) parts.push("color:" + fg);
  if (bg) parts.push("background:" + bg);
  if (st.bold) parts.push("font-weight:700");
  if (st.dim) parts.push("opacity:0.7");
  if (st.italic) parts.push("font-style:italic");
  if (st.underline) parts.push("text-decoration:underline");
  return parts.join(";");
}

function __ansiApplyCodes(state, codes) {
  // Mutate ``state`` in place for one SGR run. Advances through
  // the ``codes`` array because 38;5;N and 38;2;R;G;B consume
  // multiple slots.
  for (let i = 0; i < codes.length; i++) {
    const c = codes[i];
    if (c === 0 || c === undefined || Number.isNaN(c)) {
      state.fg = null; state.bg = null;
      state.bold = false; state.dim = false;
      state.italic = false; state.underline = false;
      state.inverse = false;
    } else if (c === 1) state.bold = true;
    else if (c === 2) state.dim = true;
    else if (c === 3) state.italic = true;
    else if (c === 4) state.underline = true;
    else if (c === 7) state.inverse = true;
    else if (c === 22) { state.bold = false; state.dim = false; }
    else if (c === 23) state.italic = false;
    else if (c === 24) state.underline = false;
    else if (c === 27) state.inverse = false;
    else if (c >= 30 && c <= 37) state.fg = __ANSI_BASIC[c - 30];
    else if (c === 39) state.fg = null;
    else if (c >= 40 && c <= 47) state.bg = __ANSI_BASIC[c - 40];
    else if (c === 49) state.bg = null;
    else if (c >= 90 && c <= 97) state.fg = __ANSI_BRIGHT[c - 90];
    else if (c >= 100 && c <= 107) state.bg = __ANSI_BRIGHT[c - 100];
    else if (c === 38 || c === 48) {
      const mode = codes[i + 1];
      if (mode === 5) {
        const idx = codes[i + 2];
        i += 2;
        if (idx >= 0 && idx < __ANSI_XTERM256.length) {
          const col = __ANSI_XTERM256[idx];
          if (c === 38) state.fg = col; else state.bg = col;
        }
      } else if (mode === 2) {
        const r = codes[i + 2] | 0;
        const g = codes[i + 3] | 0;
        const b = codes[i + 4] | 0;
        i += 4;
        const col = "#" +
          Math.max(0, Math.min(255, r)).toString(16).padStart(2, "0") +
          Math.max(0, Math.min(255, g)).toString(16).padStart(2, "0") +
          Math.max(0, Math.min(255, b)).toString(16).padStart(2, "0");
        if (c === 38) state.fg = col; else state.bg = col;
      } else {
        // Unknown extended-colour mode -- skip the whole run.
        // Two-arg form (38;m) is malformed but tolerated.
        break;
      }
    }
    // Everything else is ignored.
  }
}

// Public: convert an arbitrary string with embedded ANSI SGR
// escapes into safe HTML. Non-SGR escapes (cursor moves, etc)
// are stripped. Text is always HTML-escape'd first so the caller
// can drop the return value straight into innerHTML.
function __termAnsiToHtml(text) {
  if (text == null || text === "") return "";
  const src = String(text);
  // Regex: ESC[ then any CSI parameter bytes (0x30..0x3f, which
  // covers digits + ';' + '?' + private-mode markers) and any
  // intermediate bytes (0x20..0x2f), up to a final byte
  // 0x40..0x7e. SGR uses only digits+';' -- but we still want
  // to strip private/DEC sequences like ESC[?25l silently, so
  // the regex has to accept them and route to the non-SGR
  // branch by checking the final byte.
  const RE = /\x1b\[([\x30-\x3f]*)([\x20-\x2f]*)([\x40-\x7e])/g;
  let out = "";
  let idx = 0;
  const state = {
    fg: null, bg: null,
    bold: false, dim: false, italic: false,
    underline: false, inverse: false,
  };
  let openSpan = false;

  function _flush(end) {
    if (end <= idx) return;
    const chunk = src.slice(idx, end);
    const style = __ansiStyleFromState(state);
    if (!chunk) return;
    if (style) {
      if (!openSpan) {
        out += '<span style="' + style + '">';
        openSpan = true;
      } else {
        // Style changed: close previous span, open new one.
        out += "</span><span style=\"" + style + '">';
      }
      out += __ansiEsc(chunk);
    } else {
      if (openSpan) { out += "</span>"; openSpan = false; }
      out += __ansiEsc(chunk);
    }
  }

  let m;
  RE.lastIndex = 0;
  while ((m = RE.exec(src)) !== null) {
    _flush(m.index);
    idx = m.index + m[0].length;
    const finalByte = m[3];
    if (finalByte !== "m") {
      // Non-SGR CSI: strip silently. cursor moves, screen
      // clears, DEC private modes (ESC[?25l etc) -- none of
      // those make sense in a scrollback pane.
      continue;
    }
    // SGR must have digits+';' only; if the private-mode marker
    // block is non-empty (starts with '?', '<', '=', '>') this
    // is not a colour code -- skip it silently too.
    const params = m[1];
    if (params && /^[?<=>]/.test(params)) continue;
    // Parse parameter list. Empty means "0" per SGR spec.
    const rawParams = params || "0";
    const codes = rawParams.split(";").map(s => {
      const n = parseInt(s, 10);
      return Number.isNaN(n) ? 0 : n;
    });
    __ansiApplyCodes(state, codes);
    // Recompute open-span state on next _flush call; simplest to
    // close the current span here so the next chunk opens with
    // fresh style.
    if (openSpan) { out += "</span>"; openSpan = false; }
  }
  _flush(src.length);
  if (openSpan) out += "</span>";
  return out;
}

// Also expose a plain "strip" helper for consumers that only want
// the visible text (e.g. copy-to-clipboard should not preserve
// spans). Reuses the same regex.
function __termAnsiStrip(text) {
  if (text == null) return "";
  // Same permissive shape as __termAnsiToHtml's regex: parameter
  // bytes 0x30..0x3f (digits + ';' + '?' + '<=>' private
  // markers) then intermediate bytes 0x20..0x2f then final byte
  // 0x40..0x7e. Covers DEC private modes like ESC[?25l.
  return String(text).replace(
    /\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]/g, ""
  );
}
