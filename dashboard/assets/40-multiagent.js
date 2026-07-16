// Multi-agent session controls (v3.86.1).
//
// Backend: POST/GET/DELETE /v1/agents (v3.86.0). All calls require
// the MASTER token, which is what the Dashboard already uses.
//
// UX shape:
//   * The freshly-created token is shown ONCE in a bright warning
//     box with a Copy button. It disappears on the next Refresh.
//     (Backend deliberately omits the token from list/get responses.)
//   * The active-agent table refreshes on load, on any create/revoke,
//     and every 30 s in the background so an operator watching
//     multiple agents sees fresh request counts.
//   * Copy button falls back to a text prompt() on browsers that
//     don't expose navigator.clipboard (older Safari, HTTP contexts).

let _agentsList = [];
let _agentsRefreshTimer = null;
let _agentsLastNewToken = null;

function _agentsEl(id) { return document.getElementById(id); }

function _agentsStatus(msg, level) {
  const el = _agentsEl("agentsStatus");
  if (!el) return;
  el.textContent = msg || "";
  const colours = {info: "#333", ok: "#0a0", warn: "#a80", err: "#a00"};
  el.style.color = colours[level || "info"];
}

function _agentsBadge(count) {
  const el = _agentsEl("agentsBadge");
  if (!el) return;
  el.textContent = count + (count === 1 ? " active" : " active");
  el.style.display = "inline-block";
  el.style.background = count > 0 ? "#2b8a3e" : "#868e96";
}

function _agentsFormatAgo(epoch) {
  if (!epoch || epoch <= 0) return "never";
  const s = Math.round(Date.now() / 1000 - epoch);
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.round(s / 60) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  return Math.round(s / 86400) + "d ago";
}

function _agentsRenderTable() {
  const body = _agentsEl("agentsTableBody");
  if (!body) return;
  if (!_agentsList.length) {
    body.innerHTML = '<tr><td colspan="5" style="padding:8px;text-align:center;color:var(--text2)">No agents yet — press Create.</td></tr>';
    return;
  }
  const rows = _agentsList.map((a) => {
    const id = a.agent_id || "?";
    const label = a.label || "?";
    const reqs = a.request_count || 0;
    const seen = _agentsFormatAgo(a.last_seen_at);
    return '<tr>'
      + '<td style="padding:4px"><code style="font-size:11px">' + _htmlEscape(id) + '</code></td>'
      + '<td style="padding:4px">' + _htmlEscape(label) + '</td>'
      + '<td style="padding:4px;text-align:right;font-variant-numeric:tabular-nums">' + reqs + '</td>'
      + '<td style="padding:4px;color:var(--text2);font-size:11px">' + seen + '</td>'
      + '<td style="padding:4px;text-align:right">'
      + '<button class="sm" onclick="agentsRevoke(\'' + _jsEscape(id) + '\')" style="color:var(--red)">Revoke</button>'
      + '</td>'
      + '</tr>';
  });
  body.innerHTML = rows.join("");
  _agentsBadge(_agentsList.length);
}

// v3.91.0: _htmlEscape is now an alias for esc() from 03-helpers.js.

function _jsEscape(s) {
  return String(s || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

async function agentsRefresh() {
  try {
    const r = await api("/v1/agents");
    if (r && r.ok) {
      _agentsList = r.agents || [];
      _agentsRenderTable();
      _agentsStatus(r.count + " active agent" + (r.count === 1 ? "" : "s") + ".", "info");
    } else {
      _agentsStatus("List failed: " + (r && r.error || "unknown"), "err");
    }
  } catch (e) {
    _agentsStatus("List failed: " + (e && e.message || e), "err");
  }
}

async function agentsCreate() {
  const labelEl = _agentsEl("agentsCreateLabel");
  const label = labelEl && labelEl.value ? labelEl.value.trim() : "";
  if (!label) {
    _agentsStatus("Please enter a label first (e.g. 'laptop-agent').", "warn");
    if (labelEl) labelEl.focus();
    return;
  }
  _agentsStatus("Creating agent…");
  try {
    const r = await api("/v1/agents",
      {method: "POST", body: JSON.stringify({label: label})});
    if (r && r.ok && r.agent && r.agent.token) {
      _agentsLastNewToken = r.agent.token;
      const box = _agentsEl("agentsNewTokenBox");
      _agentsEl("agentsNewToken").textContent = r.agent.token;
      _agentsEl("agentsNewId").textContent = r.agent.agent_id;
      if (box) box.style.display = "";
      _agentsStatus("Created agent '" + r.agent.label + "'. Copy the token now — it will NOT be shown again.", "ok");
      if (labelEl) labelEl.value = "";
      await agentsRefresh();
    } else {
      _agentsStatus("Create failed: " + (r && r.error || "unknown"), "err");
    }
  } catch (e) {
    _agentsStatus("Create failed: " + (e && e.message || e), "err");
  }
}

async function agentsRevoke(agentId) {
  if (!agentId) return;
  const rec = _agentsList.find((a) => a.agent_id === agentId);
  const label = rec ? rec.label : agentId;
  if (!confirm("Revoke agent '" + label + "'?\n\n"
               + "The agent's bearer token will stop working immediately.\n"
               + "Anyone using it will get 401 on their next request.")) {
    return;
  }
  try {
    const r = await api("/v1/agents/" + encodeURIComponent(agentId),
      {method: "DELETE"});
    if (r && r.ok) {
      _agentsStatus("Revoked agent '" + label + "'.", "ok");
      // Clear the "new token" box if it was showing this agent.
      const nid = _agentsEl("agentsNewId");
      if (nid && nid.textContent === agentId) {
        _agentsEl("agentsNewTokenBox").style.display = "none";
        _agentsLastNewToken = null;
      }
      await agentsRefresh();
    } else {
      _agentsStatus("Revoke failed: " + (r && r.error || "unknown"), "err");
    }
  } catch (e) {
    _agentsStatus("Revoke failed: " + (e && e.message || e), "err");
  }
}

async function agentsCopyNewToken() {
  if (!_agentsLastNewToken) return;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(_agentsLastNewToken);
      _agentsStatus("Token copied to clipboard.", "ok");
      return;
    }
  } catch (_) {}
  // Fallback: prompt() so the user can Ctrl+C manually.
  prompt("Copy the token with Ctrl+C:", _agentsLastNewToken);
}

// Auto-load on Dashboard boot + refresh every 30 s.
(function () {
  function _init() {
    setTimeout(() => {
      try { agentsRefresh(); } catch (_) {}
    }, 2500);
    if (_agentsRefreshTimer) clearInterval(_agentsRefreshTimer);
    _agentsRefreshTimer = setInterval(() => {
      try { agentsRefresh(); } catch (_) {}
    }, 30000);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _init, {once: true});
  } else {
    _init();
  }
})();
