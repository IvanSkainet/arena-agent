// Mobile: UI Automator inspector overlay (v3.83.1).
//
// Fetches /v1/mobile/{s}/ui, draws an SVG overlay on top of the
// screenshot with a bounding box per interactive node, and lets the
// user click a box to issue /tap_by that selects the same node by its
// resource-id (or text / desc as a fallback). This replaces the
// pixel-perfect drag-and-tap workflow with a semantic one — the tap
// stays valid even if the phone reflows the layout between the dump
// and the click.
//
// Depends on globals from 30-mobile.js and 31-mobile-screen.js:
//   _mobileSelectedSerial, _mobileNativeWidth/Height,
//   _mobileShownWidth/Height, api(), mobileShowError,
//   mobileClearError, _fmtBackendError, _mobileRefreshBurst.

let _mobileInspectorOn = false;
let _mobileInspectorNodes = [];   // last dump nodes
let _mobileInspectorHoverIdx = -1;

// Public entry: called from the toolbar toggle.
async function mobileInspectorToggle(checkbox) {
  _mobileInspectorOn = !!(checkbox && checkbox.checked);
  const overlay = document.getElementById("mobileInspectorOverlay");
  const legend = document.getElementById("mobileInspectorLegend");
  if (overlay) overlay.style.display = _mobileInspectorOn ? "" : "none";
  if (legend) legend.style.display = _mobileInspectorOn ? "" : "none";
  if (_mobileInspectorOn) await mobileInspectorRefresh();
}

async function mobileInspectorRefresh() {
  if (!_mobileSelectedSerial) return;
  mobileClearError();
  const badge = document.getElementById("mobileInspectorStatus");
  if (badge) badge.textContent = "Dumping…";
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/ui?interactive_only=1&max_nodes=200"
    );
    if (!r || !r.ok) {
      mobileShowError("UI dump failed", _fmtBackendError("ui", r));
      if (badge) badge.textContent = "";
      return;
    }
    _mobileInspectorNodes = r.nodes || [];
    // uiautomator's <hierarchy rotation="N"> XML already contains
    // rotation-correct bounds, so screen_bounds here matches the
    // current phone orientation. We prefer it over the screenshot
    // header dims for the SVG viewBox because it comes from the same
    // dump the bounds_rect values came from.
    if (Array.isArray(r.screen_bounds) && r.screen_bounds.length === 2
        && r.screen_bounds[0] > 0 && r.screen_bounds[1] > 0) {
      _mobileNativeWidth = r.screen_bounds[0];
      _mobileNativeHeight = r.screen_bounds[1];
    }
    mobileInspectorRender();
    if (badge) {
      badge.textContent = r.nodes.length + " nodes"
        + (r.truncated ? " (truncated)" : "")
        + " · " + r.duration_ms + " ms";
    }
  } catch (e) {
    mobileShowError("UI dump request failed", e && e.stack || String(e));
    if (badge) badge.textContent = "";
  }
}

function mobileInspectorRender() {
  const svg = document.getElementById("mobileInspectorOverlay");
  const img = document.getElementById("mobileScreenshotImg");
  if (!svg || !img || !_mobileInspectorOn) return;
  if (!_mobileNativeWidth || !_mobileNativeHeight) return;

  // Match the SVG viewBox to the native screen so we can render node
  // bounds unscaled. Actual rendered size is dictated by CSS on the
  // parent <img>.
  svg.setAttribute("viewBox", "0 0 " + _mobileNativeWidth + " " + _mobileNativeHeight);
  svg.innerHTML = "";

  const ns = "http://www.w3.org/2000/svg";
  _mobileInspectorNodes.forEach((n, idx) => {
    if (!n.bounds_rect) return;
    const [x1, y1, x2, y2] = n.bounds_rect;
    const w = Math.max(1, x2 - x1);
    const h = Math.max(1, y2 - y1);
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("x", x1);
    rect.setAttribute("y", y1);
    rect.setAttribute("width", w);
    rect.setAttribute("height", h);
    // Colour: clickable = blue, scrollable = green, label-only = grey.
    let stroke = "#888";
    if (n.clickable === "true" || n["long-clickable"] === "true") stroke = "#1c7ed6";
    else if (n.scrollable === "true") stroke = "#2f9e44";
    rect.setAttribute("stroke", stroke);
    rect.setAttribute("stroke-width", "3");
    rect.setAttribute("fill", "transparent");
    rect.setAttribute("data-idx", String(idx));
    rect.style.cursor = "pointer";
    rect.style.pointerEvents = "auto";
    rect.addEventListener("mouseenter", () => _mobileInspectorHover(idx));
    rect.addEventListener("mouseleave", () => _mobileInspectorHover(-1));
    rect.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      _mobileInspectorTap(idx);
    });
    svg.appendChild(rect);
  });
}

function _mobileInspectorHover(idx) {
  _mobileInspectorHoverIdx = idx;
  const tip = document.getElementById("mobileInspectorTip");
  if (!tip) return;
  if (idx < 0) { tip.style.display = "none"; return; }
  const n = _mobileInspectorNodes[idx];
  if (!n) { tip.style.display = "none"; return; }
  const lines = [];
  if (n["resource-id"]) lines.push("id: " + n["resource-id"]);
  if (n.text) lines.push("text: " + n.text);
  if (n["content-desc"]) lines.push("desc: " + n["content-desc"]);
  if (n.class) lines.push("class: " + n.class);
  lines.push("bounds: " + (n.bounds_rect || []).join(","));
  const flags = [];
  if (n.clickable === "true") flags.push("clickable");
  if (n["long-clickable"] === "true") flags.push("long-clickable");
  if (n.scrollable === "true") flags.push("scrollable");
  if (n.checkable === "true") flags.push("checkable");
  if (n.checked === "true") flags.push("✓checked");
  if (flags.length) lines.push("flags: " + flags.join(", "));
  tip.textContent = lines.join("\n");
  tip.style.display = "";
}

async function _mobileInspectorTap(idx) {
  const n = _mobileInspectorNodes[idx];
  if (!n) return;
  mobileClearError();
  // Prefer resource-id (most stable across layout reflows), fall back
  // to content-desc, then exact text, then package+class+center. We
  // send only ONE selector at a time to avoid over-constraining.
  const selector = {};
  if (n["resource-id"]) selector.id = n["resource-id"];
  else if (n["content-desc"]) selector.desc = n["content-desc"];
  else if (n.text) selector.text = n.text;
  else {
    // No stable selector — fall back to pixel tap by centre.
    const c = n.center;
    if (c && c.length === 2) _mobileSendTap(c[0], c[1]);
    return;
  }
  // If this selector is likely to match many things (e.g. an empty text
  // or a generic id), scope it to the current package so we don't tap
  // some background window's element by accident.
  if (n.package) selector.package = n.package;

  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial) + "/tap_by",
      {method: "POST", body: JSON.stringify(selector)},
    );
    if (!r || !r.ok) {
      mobileShowError(
        "tap_by failed on selector " + JSON.stringify(selector),
        _fmtBackendError("tap_by", r),
      );
      return;
    }
    // Refresh screenshot + re-dump UI so the overlay tracks the new
    // screen. Do the UI re-dump in parallel with the screenshot burst;
    // it's slower (~2s) so it lands after the animation settles.
    _mobileRefreshBurst();
    if (_mobileInspectorOn) setTimeout(mobileInspectorRefresh, 1500);
  } catch (e) {
    mobileShowError("tap_by request failed", e && e.stack || String(e));
  }
}
