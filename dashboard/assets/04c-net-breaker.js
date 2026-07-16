// ===== OVERVIEW: circuit breaker indicators (v4.11.0) =====
// Consumes the ``breaker`` field of /v1/tunnels/probe (v4.8.0) and
// renders one small badge per keyed provider inside the Network
// Status card:
//   * blue "ok N"          -- closed, no consecutive failures
//   * yellow "warn N"      -- closed but N > 0 consecutive failures
//                             (predictive: probe is trending bad)
//   * red "cooldown 45s"   -- open, N seconds remaining
//
// Tooltip on every badge exposes the ``last_error`` string so the
// operator can see WHY it's tripping without a debug endpoint.
//
// The row is hidden entirely when there are no records so hosts
// without any tunnel activity keep a tidy Overview.
//
// Fail-soft: any api() error hides the row rather than showing
// stale numbers. The v4.7.0 ZT peers card does the same thing --
// same design pattern.

function __netBreakerHide() {
  const row = document.getElementById("netBreakerRow");
  if (row) row.classList.remove("on");
}

function __netBreakerShow() {
  const row = document.getElementById("netBreakerRow");
  if (row) row.classList.add("on");
}

// The key format we build in tunnels_probe is
// "{provider}|{host}:{port}"; split just enough to render a
// friendly label like "cloudflared @foo.trycloudflare.com:443".
function __netBreakerLabel(key) {
  const bar = key.indexOf("|");
  if (bar < 0) return key;
  const provider = key.slice(0, bar);
  const hostport = key.slice(bar + 1);
  return provider + " @" + hostport;
}

function __netBreakerRender(snapshot) {
  const listEl = document.getElementById("netBreakerList");
  if (!listEl) return;
  const keys = Object.keys(snapshot || {});
  if (keys.length === 0) { __netBreakerHide(); return; }
  keys.sort();

  const parts = [];
  keys.forEach(k => {
    const rec = snapshot[k] || {};
    const state = rec.state || "closed";
    const fails = rec.consecutive_failures || 0;
    const lastErr = rec.last_error || "";
    const label = __netBreakerLabel(k);
    let cls = "ok";
    let text = "ok";
    if (state === "open") {
      cls = "open";
      const cd = typeof rec.cools_down_in_sec === "number"
        ? Math.round(rec.cools_down_in_sec)
        : "?";
      text = "cooldown " + cd + "s";
    } else if (fails > 0) {
      cls = "warn";
      text = "warn " + fails + "/3";
    }
    // Tooltip text: last error + fail count so it's self-diagnosing.
    // We assemble the title via a real attribute (not innerHTML) so a
    // last_error containing HTML-ish characters can't slip a tag in.
    const item = document.createElement("span");
    item.className = "item " + cls;
    const tips = [];
    tips.push(label);
    tips.push("state: " + state);
    tips.push("consecutive failures: " + fails);
    if (lastErr) tips.push("last error: " + lastErr);
    if (state === "open" && typeof rec.cools_down_in_sec === "number") {
      tips.push("cools down in: " + rec.cools_down_in_sec + "s");
    }
    item.title = tips.join("\n");
    // Compact per-badge text: shorten label to "provider (Ns)" or
    // "provider (warn)" so the row doesn't wrap on mobile. Full
    // detail lives in the tooltip.
    const short = label.split(" @")[0];  // just the provider name
    item.textContent = short + ": " + text;
    parts.push(item);
  });

  listEl.innerHTML = "";
  parts.forEach(p => listEl.appendChild(p));
  __netBreakerShow();
}

async function refreshNetBreaker() {
  let data = null;
  try {
    data = await api("/v1/tunnels/probe");
  } catch (_e) {
    __netBreakerHide();
    return;
  }
  if (!data || data.ok === false) { __netBreakerHide(); return; }
  const snap = data.breaker;
  if (!snap || typeof snap !== "object") { __netBreakerHide(); return; }
  __netBreakerRender(snap);
}
