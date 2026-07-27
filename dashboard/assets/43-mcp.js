// ===== MCP SERVERS TAB (v4.95.0) =====
//
// Monitor external MCP servers registered in mcp/mcp.json. Data:
//   GET /v1/mcp/servers -> { ok, count, servers: [{name, command,
//                            args, running, tools:[...]}, ...] }
//
// Read-only monitoring ("следить"): shows each server's command,
// running state and (when running) its tool names. The agent drives
// the servers through the mcp.ext_* MCP tools (mcp.add / mcp.ext_tools
// / mcp.ext_call / mcp.ext_stop); this tab just observes.

(function () {
  "use strict";

  var _timer = null;

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderCard(s) {
    var running = !!s.running;
    var badge = running
      ? '<span class="mcp-badge run">running</span>'
      : '<span class="mcp-badge stop">idle</span>';
    var cmd = esc(s.command) + " " + (s.args || []).map(esc).join(" ");
    var tools = (s.tools && s.tools.length)
      ? '<div class="mcp-tools">' +
        s.tools.map(function (t) { return '<span class="tool">' + esc(t) + "</span>"; }).join("") +
        "</div>"
      : '<div class="mcp-row"><span class="mcp-label">tools</span>' +
        '<span class="mcp-val" style="color:var(--text3)">' +
        (running ? "(none reported)" : "connect via mcp.ext_tools to list") + "</span></div>";
    return (
      '<div class="mcp-card">' +
        "<h3>🔗 " + esc(s.name) + badge + "</h3>" +
        '<div class="mcp-row"><span class="mcp-label">command</span><span class="mcp-val">' + cmd.trim() + "</span></div>" +
        tools +
      "</div>"
    );
  }

  // v4.96.0: agent-authored custom tools (the agent growing its own
  // environment via custom.create). Shown next to the external servers.
  function renderCustomCard(c) {
    var risk = c.risk || "medium";
    var badge = '<span class="mcp-badge risk-' + esc(risk) + '">' + esc(risk) + "</span>";
    var params = (c.params && c.params.length)
      ? c.params.map(function (p) { return '<span class="tool">' + esc(p) + "</span>"; }).join("")
      : '<span style="color:var(--text3)">(no params)</span>';
    return (
      '<div class="mcp-card">' +
        "<h3>🧩 " + esc(c.name) + badge + "</h3>" +
        '<div class="mcp-row"><span class="mcp-label">wraps</span><span class="mcp-val">' + esc(c.wraps) + "</span></div>" +
        '<div class="mcp-row"><span class="mcp-label">params</span><span class="mcp-val"><div class="mcp-tools">' + params + "</div></span></div>" +
        (c.description
          ? '<div class="mcp-row"><span class="mcp-label">desc</span><span class="mcp-val">' + esc(c.description) + "</span></div>"
          : "") +
      "</div>"
    );
  }

  function renderCustom(ctools) {
    var grid = document.getElementById("mcpCustomGrid");
    var meta = document.getElementById("mcpCustomMeta");
    if (!grid) return;
    if (meta) {
      meta.textContent = ctools.length
        ? ctools.length + " agent-authored tool(s) — created at runtime via custom.create"
        : "No custom tools yet.";
    }
    grid.innerHTML = ctools.length
      ? ctools.map(renderCustomCard).join("")
      : '<div class="mcp-empty">No agent-authored tools yet. The agent creates one with ' +
        "<code>custom.create</code> (a named wrapper over a built-in tool) and it shows up here.</div>";
  }

  window.loadMcp = async function () {
    var grid = document.getElementById("mcpGrid");
    var meta = document.getElementById("mcpMeta");
    if (!grid) return;
    try {
      var d = await window.api("/v1/mcp/servers");
      if (!d || !d.ok) {
        grid.innerHTML = '<div class="mcp-empty">Failed to load MCP servers: ' +
          esc(d && d.error || "unknown error") + "</div>";
        return;
      }
      var servers = d.servers || [];
      var ctools = d.custom_tools || [];
      var running = servers.filter(function (s) { return s.running; }).length;
      meta.innerHTML =
        '<span class="chip run">' + running + " running</span>" +
        '<span class="chip stop">' + (servers.length - running) + " idle</span>" +
        " · " + servers.length + " registered in mcp/mcp.json";
      grid.innerHTML = servers.length
        ? servers.map(renderCard).join("")
        : '<div class="mcp-empty">No MCP servers registered yet. ' +
          "Add one with the <code>mcp.add</code> tool (or " +
          "<code>marketplace install desktop-commander</code>), then it shows up here.</div>";
      renderCustom(ctools);
    } catch (e) {
      grid.innerHTML = '<div class="mcp-empty">Error: ' + esc(e && e.message || e) + "</div>";
    }
  };

  function startAuto() {
    stopAuto();
    var sel = document.getElementById("mcpInterval");
    var secs = parseInt(sel && sel.value || "15", 10) || 15;
    _timer = setInterval(window.loadMcp, secs * 1000);
  }
  function stopAuto() {
    if (_timer) { clearInterval(_timer); _timer = null; }
  }

  // Wire the auto-refresh checkbox + interval once the tab body exists.
  document.addEventListener("DOMContentLoaded", function () {
    var cb = document.getElementById("mcpAuto");
    var sel = document.getElementById("mcpInterval");
    if (cb) cb.addEventListener("change", function () {
      if (cb.checked) startAuto(); else stopAuto();
    });
    if (sel) sel.addEventListener("change", function () {
      if (cb && cb.checked) startAuto();
    });
  });

  // Stop auto-refresh when leaving the tab (best-effort).
  var _observer = new MutationObserver(function () {
    var tab = document.getElementById("tab-mcp");
    var cb = document.getElementById("mcpAuto");
    if (tab && tab.style.display === "none" && cb && cb.checked) {
      cb.checked = false; stopAuto();
    }
  });
  document.addEventListener("DOMContentLoaded", function () {
    var tab = document.getElementById("tab-mcp");
    if (tab) _observer.observe(tab, { attributes: true, attributeFilter: ["style"] });
  });
})();
