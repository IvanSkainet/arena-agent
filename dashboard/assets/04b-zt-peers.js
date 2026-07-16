// ===== OVERVIEW: ZeroTier peers card (v4.7.0) =====
// Consumes /v1/zerotier/peers (v4.4.0+) and renders a small SVG
// donut with a per-category legend + summary + hint. The card is
// hidden when ZeroTier is not installed / not reachable on the
// bridge so hosts without ZT get no broken UI.

// Palette for path_kind slices. Kept in sync with the Audit-tab
// event badge palette so an operator watching both tabs sees the
// same colors mean the same thing. We reference the shared
// dashboard palette via var(--foo) so no hex literals appear
// here (test_no_hardcoded_theme_colors stays green).
const __ZT_KIND_COLOR = {
  direct:   "var(--green)",
  relay:    "var(--orange)",   // relay/planet: mildly bad
  tunneled: "var(--red)",      // TCP fallback: worst
  root:     "var(--purple)",   // PLANET/MOON metadata slice
  none:     "var(--text3)",    // known but unreachable
};

const __ZT_KIND_LABEL = {
  direct:   "direct (P2P UDP)",
  relay:    "relay",
  tunneled: "tunneled (TCP)",
  root:     "PLANET/MOON",
  none:     "unreachable",
};

// Ordering used in the legend + donut slice sequence. Kept stable
// so a peer flipping from ``direct`` back to ``relay`` doesn't
// rearrange the whole chart.
const __ZT_KIND_ORDER = ["direct", "relay", "tunneled", "none", "root"];

function __ztHideCard() {
  const card = document.getElementById("ztPeersCard");
  const header = document.getElementById("ztPeersHeader");
  if (card) card.classList.remove("on");
  if (header) header.style.display = "none";
}

function __ztShowCard() {
  const card = document.getElementById("ztPeersCard");
  const header = document.getElementById("ztPeersHeader");
  if (card) card.classList.add("on");
  if (header) header.style.display = "";
}

// Build the donut as inline SVG arcs. SVG viewBox is 42x42 so the
// numbers below are literal percentages of the circumference
// (2*pi*r = ~100 when r=15.9155). This trick lets us set
// stroke-dasharray = "slice_pct 100-slice_pct" and the visible
// portion equals the fraction. Slices are drawn as concentric
// rotations of the same circle so each stroke-dashoffset shifts
// the start by the cumulative offset.
function __ztRenderDonut(counts, total) {
  const svg = document.getElementById("ztDonut");
  if (!svg) return;
  const cx = 21, cy = 21, r = 15.9155;
  // Background ring so an empty donut isn't invisible.
  const parts = [
    '<circle cx="' + cx + '" cy="' + cy + '" r="' + r +
    '" fill="none" stroke="var(--bg3)" stroke-width="6"></circle>',
  ];
  if (total > 0) {
    let offset = 25;   // start at 12 o'clock (empirical for r=15.9155)
    __ZT_KIND_ORDER.forEach(kind => {
      const n = counts[kind] || 0;
      if (n <= 0) return;
      const pct = (n / total) * 100;
      const gap = 100 - pct;
      parts.push(
        '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '"' +
        ' fill="none" stroke="' + __ZT_KIND_COLOR[kind] + '"' +
        ' stroke-width="6"' +
        ' stroke-dasharray="' + pct.toFixed(3) + ' ' + gap.toFixed(3) + '"' +
        ' stroke-dashoffset="' + offset.toFixed(3) + '"' +
        ' transform="rotate(-90 ' + cx + ' ' + cy + ')"></circle>'
      );
      // stroke-dashoffset counts backwards, so subtract to advance.
      offset = (offset - pct + 100) % 100;
    });
  }
  // Middle text: total peer count.
  parts.push(
    '<text x="' + cx + '" y="' + (cy + 1) +
    '" text-anchor="middle" dominant-baseline="middle"' +
    ' fill="var(--text)" font-size="10" font-weight="600">' +
    total + '</text>' +
    '<text x="' + cx + '" y="' + (cy + 8) +
    '" text-anchor="middle" dominant-baseline="middle"' +
    ' fill="var(--text2)" font-size="4">peers</text>'
  );
  svg.innerHTML = parts.join("");
}

function __ztRenderLegend(counts, total) {
  const el = document.getElementById("ztLegend");
  if (!el) return;
  const items = [];
  __ZT_KIND_ORDER.forEach(kind => {
    const n = counts[kind] || 0;
    if (n <= 0) return;
    const pct = total > 0 ? Math.round((n / total) * 100) : 0;
    items.push(
      '<div><span class="sw" style="background:' + __ZT_KIND_COLOR[kind] +
      '"></span>' + esc(__ZT_KIND_LABEL[kind]) +
      ' <b style="color:var(--text)">' + n + '</b>' +
      ' <span style="color:var(--text3)">(' + pct + '%)</span></div>'
    );
  });
  el.innerHTML = items.join("") ||
    '<div style="color:var(--text3)">No peers reported.</div>';
}

function __ztRenderStats(summary) {
  const el = document.getElementById("ztStats");
  if (!el) return;
  const parts = [];
  if (typeof summary.leaf_total === "number") {
    parts.push('<div class="item">LEAFs: <b>' + summary.leaf_total + '</b></div>');
  }
  if (typeof summary.direct_ratio === "number") {
    parts.push('<div class="item">direct: <b>' +
      Math.round(summary.direct_ratio * 100) + '%</b></div>');
  }
  if (typeof summary.leaf_latency_ms_avg === "number") {
    parts.push('<div class="item">avg latency: <b>' +
      summary.leaf_latency_ms_avg + ' ms</b></div>');
  }
  // v4.5.0 breakdown: only show if there is any relay at all.
  const planet = summary.leaf_relay_planet || 0;
  const tcp    = summary.leaf_relay_tcp_infra || 0;
  if (planet + tcp > 0) {
    parts.push('<div class="item">relay via: <b>' +
      (planet ? planet + ' planet' : "") +
      (planet && tcp ? " + " : "") +
      (tcp ? tcp + ' tcp-infra' : "") + '</b></div>');
  }
  el.innerHTML = parts.join("");
}

function __ztRenderMeta(data) {
  const el = document.getElementById("ztMeta");
  if (!el) return;
  const parts = [];
  if (data.backend) parts.push("backend: " + data.backend);
  if (data.cli_source) parts.push("cli: " + data.cli_source);
  parts.push("updated " + new Date().toLocaleTimeString());
  el.textContent = parts.join(" | ");
}

async function refreshZtPeers() {
  let data = null;
  try {
    data = await api("/v1/zerotier/peers");
  } catch (_e) {
    __ztHideCard();
    return;
  }
  // Endpoint returns {ok:false, installed:false, ...} on hosts
  // without ZT -- hide the card so the tab stays tidy. Also hide
  // when ZT is installed but currently unreadable (no summary
  // to render).
  if (!data || data.installed === false) { __ztHideCard(); return; }
  if (!data.summary || typeof data.summary !== "object") {
    __ztHideCard();
    return;
  }
  __ztShowCard();
  const counts = (data.summary && data.summary.counts) || {};
  const total = Number(data.summary.peer_count) || 0;
  __ztRenderDonut(counts, total);
  __ztRenderLegend(counts, total);
  __ztRenderStats(data.summary);
  __ztRenderMeta(data);
  const hintEl = document.getElementById("ztHint");
  if (hintEl) {
    if (data.hint) {
      hintEl.textContent = data.hint;
      hintEl.style.display = "";
    } else {
      hintEl.style.display = "none";
      hintEl.textContent = "";
    }
  }
}
