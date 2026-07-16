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
// Inner SGR-only renderer. Takes a chunk of text (already OSC-free)
// plus a mutable colour state; returns the HTML. Extracted from
// the v4.15.0 body so v4.18.0 can drive it per OSC-split text
// piece while keeping the state (colours, bold, ...) alive across
// splits.
function _ansiSgrHtml(src, state) {
  if (!src) return "";
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
    if (finalByte !== "m") continue;   // non-SGR CSI: strip
    const params = m[1];
    if (params && /^[?<=>]/.test(params)) continue;   // private-mode
    const rawParams = params || "0";
    const codes = rawParams.split(";").map(s => {
      const n = parseInt(s, 10);
      return Number.isNaN(n) ? 0 : n;
    });
    __ansiApplyCodes(state, codes);
    if (openSpan) { out += "</span>"; openSpan = false; }
  }
  _flush(src.length);
  if (openSpan) out += "</span>";
  return out;
}

function __termAnsiToHtml(text) {
  if (text == null || text === "") return "";
  const src = String(text);
  // v4.18.0: OSC preprocessing splits the source into an ordered
  // list of ("text-run" | "href-open" | "href-close") pieces.
  // Text runs still contain CSI sequences -- SGR state carries
  // across the split so a colour opened before OSC 8 continues
  // after the hyperlink closes.
  const pieces = __oscPreprocess(src);
  const state = {
    fg: null, bg: null,
    bold: false, dim: false, italic: false,
    underline: false, inverse: false,
  };
  let out = "";
  let openHref = false;
  for (const p of pieces) {
    if (p.kind === "text") {
      out += _ansiSgrHtml(p.data, state);
    } else if (p.kind === "href") {
      if (openHref) { out += "</a>"; openHref = false; }
      if (p.data) {
        // Escape the URL for the href attribute. __ansiEsc handles
        // & < > " so a URL like ``https://example.com/?a=1&b="x"``
        // becomes safe attribute content.
        out += '<a href="' + __ansiEsc(p.data) +
               '" target="_blank" rel="noreferrer noopener">';
        openHref = true;
      }
      // else: OSC 8 close with empty URL -- already handled above.
    }
  }
  if (openHref) out += "</a>";
  return out;
}

// Also expose a plain "strip" helper for consumers that only want
// the visible text (e.g. copy-to-clipboard should not preserve
// spans). Reuses the same regex.
function __termAnsiStrip(text) {
  if (text == null) return "";
  // First drop every OSC (ESC ] ... BEL / ESC \) then every CSI.
  // Both regex shapes match the parser used by __termAnsiToHtml so
  // strip() output equals "what __termAnsiToHtml would render"
  // minus the HTML wrappers.
  return String(text)
    .replace(/\x1b\][\s\S]*?(?:\x07|\x1b\\)/g, "")
    .replace(/\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]/g, "");
}

// --------------------------------------------------------------------------
// v4.18.0: OSC (Operating System Command) preprocessor.
//
// OSC syntax:  ESC ] Ps ; Pt ST
//   ST is either BEL (0x07) or ESC \ (0x1b 0x5c).
//   Ps is a decimal parameter selector; Pt is the payload.
//
// We handle exactly two flavours because they are the only OSCs a
// scrollback pane can meaningfully react to:
//
//   OSC 8 ; params ; URL   -- open hyperlink (URL is the anchor
//                             target; anchor CLOSES on the next
//                             OSC 8 with an empty URL).
//   OSC 0/1/2 ; TITLE      -- set window / icon / tab title.
//                             We have no title bar; drop silently.
//
// Everything else (progress reports, iTerm2 shell integration,
// finalTerm markers, Kitty images...) is silently stripped. The
// Terminal tab is a scrollback pane, not a real terminal; adding
// more OSC handlers here would be scope creep.
//
// URL sanitisation: OSC 8 URLs are attacker-controlled bytes from
// stdout. We normalise the scheme to lower-case and reject any
// scheme in _UNSAFE_SCHEMES so a shell that prints
//   ESC]8;;javascript:alert(1) ESC\ ...text... ESC]8;; ESC\
// does not become a live XSS on click. When a URL is rejected the
// text still renders, just without the anchor wrap.
const _UNSAFE_SCHEMES = ["javascript:", "data:", "vbscript:", "file:"];

function __oscSafeUrl(raw) {
  if (raw == null) return null;
  const url = String(raw).trim();
  if (!url) return null;
  const lower = url.toLowerCase();
  for (const bad of _UNSAFE_SCHEMES) {
    if (lower.startsWith(bad)) return null;
  }
  // Guard against control characters that could smuggle out of the
  // href attribute later. Real URLs don't contain raw whitespace or
  // \x00-\x1f bytes.
  if (/[\x00-\x1f\s"'<>`]/.test(url)) return null;
  return url;
}

// Split the input into an ordered list of pieces:
//   {kind: "text",  data: string}       -- raw text between OSCs
//   {kind: "href",  data: string|null}  -- OSC 8 with URL (null = close)
// Non-hyperlink OSCs are dropped from the output entirely.
function __oscPreprocess(src) {
  const OSC_RE = /\x1b\](\d+);?([\s\S]*?)(?:\x07|\x1b\\)/g;
  const pieces = [];
  let last = 0;
  let m;
  OSC_RE.lastIndex = 0;
  while ((m = OSC_RE.exec(src)) !== null) {
    if (m.index > last) {
      pieces.push({kind: "text", data: src.slice(last, m.index)});
    }
    last = m.index + m[0].length;
    const ps = parseInt(m[1], 10);
    const pt = m[2] || "";
    if (ps === 8) {
      // OSC 8 payload: "params;URL". Params usually empty (`;`) or
      // `id=foo`; we don't consume them but must split correctly.
      const sep = pt.indexOf(";");
      const url = sep >= 0 ? pt.slice(sep + 1) : pt;
      const safe = __oscSafeUrl(url);
      pieces.push({kind: "href", data: safe});   // safe may be null (=close)
    }
    // Titles (0, 1, 2), progress reports (9), iTerm/finalTerm/kitty
    // -- silently dropped.
  }
  if (last < src.length) {
    pieces.push({kind: "text", data: src.slice(last)});
  }
  return pieces;
}

