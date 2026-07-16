// ===== AUDIT (v4.6.0 polish) =====
// State kept module-scope so pagination/filters survive between
// re-renders without re-fetching. Fresh loadAudit() (Reload button
// or auto-refresh tick) refills __auditState.raw.
const __auditState = {
  raw: [],           // last full fetch from /v1/audit
  page: 0,           // 0-based current page
  autoTimer: null,   // setInterval handle when auto-refresh is on
  lastFetch: null,   // Date of last successful fetch (for meta line)
};

// Event-type -> badge category. Keep the mapping tiny; anything
// unknown falls through to 'other'. New event names added by
// future releases will just show up under 'other' until they are
// explicitly categorized here, which is safe (no crash, no
// mislabelling as e.g. 'exec').
function __auditCategory(type) {
  if (!type) return "other";
  const t = String(type);
  if (t === "exec_blocked" || t === "exec_stream_blocked" ||
      t === "exec_script_blocked" || t === "exec_blocked_control" ||
      t === "exec_stream_blocked_control") return "exec-blocked";
  if (t === "exec_timeout" || t === "exec_stream_timeout" ||
      t === "exec_script_timeout") return "exec-timeout";
  if (t.startsWith("exec_stream")) return "exec-stream";
  if (t.startsWith("exec_script")) return "exec-script";
  if (t.startsWith("exec_") || t === "process_killed") return "exec";
  if (t.startsWith("file_")) return "file";
  if (t.startsWith("admin.")) return "admin";
  if (t.endsWith("_tunnel") || t.endsWith("_funnel") ||
      t.startsWith("zerotier") || t.startsWith("tunnels")) return "tunnel";
  if (t.includes("error")) return "error";
  return "other";
}

// Short human-readable detail line. Prefers cmd for exec events,
// path for file events, action for tunnel/admin events, reason
// for blocked events. Slicing to 240 chars so long paths still
// fit into a single row; the full JSON is one click away via
// row-expand.
function __auditDetail(e) {
  if (e.reason) return "reason: " + e.reason;
  if (e.error && typeof e.error === "string") return "error: " + e.error;
  if (e.cmd) {
    const extra = e.interpreter ? " [" + e.interpreter + "]" : "";
    return "cmd" + extra + ": " + String(e.cmd);
  }
  if (e.path) {
    const bytes = (typeof e.bytes === "number") ? "  (" + e.bytes + " B)" : "";
    return "path: " + String(e.path) + bytes;
  }
  if (e.action) {
    const nw = e.network_id ? "  network=" + e.network_id : "";
    return "action: " + String(e.action) + nw;
  }
  if (e.matched) return "matched: " + String(e.matched);
  if (e.target_request_id) return "target: " + e.target_request_id;
  if (e.current) return "current: " + JSON.stringify(e.current).slice(0, 200);
  return "";
}

function __auditExitCell(e) {
  const code = e.exit_code;
  if (code === undefined || code === null) return "<span class='ev-exit-none'>-</span>";
  if (code === 0) return "<span class='ev-exit-ok'>0</span>";
  return "<span class='ev-exit-fail'>" + esc(String(code)) + "</span>";
}

function __auditActor(e) {
  return e.client || e.actor || "-";
}

// ISO-ish timestamps come in like "2026-07-16T14:55:09+00:00".
// Trim to the second and drop the timezone so the column stays
// narrow. Full timestamp is visible in the expand payload.
function __auditTimeCell(ts) {
  if (!ts) return "?";
  const s = String(ts);
  const t = s.replace("T", " ");
  return t.slice(0, 19);
}

// The bridge JSON-encodes events; expanding shows the raw object
// (dedup'd of the fields already visible in the row so we don't
// waste vertical space repeating the timestamp).
function __auditRenderExpanded(e) {
  const skip = new Set(["ts", "timestamp", "type", "client"]);
  const rest = {};
  Object.keys(e).sort().forEach(k => { if (!skip.has(k)) rest[k] = e[k]; });
  try {
    return JSON.stringify(rest, null, 2);
  } catch (_) {
    return String(e);
  }
}

// Client-side filter pass. Filters chain (AND) so an empty box
// = "match anything for this axis". Search is a case-insensitive
// substring across cmd, path, reason, error, matched, actor, and
// request_id -- the fields users actually grep.
function __auditFilter(events) {
  const q = (document.getElementById("auditSearch").value || "").trim().toLowerCase();
  const typeSel = document.getElementById("auditFilter").value || "";
  const exitSel = document.getElementById("auditExit").value || "";
  return events.filter(e => {
    // type filter -- substring so "exec" matches all exec_* variants
    if (typeSel && !(String(e.type || "")).includes(typeSel)) return false;
    // exit filter
    if (exitSel === "ok" && e.exit_code !== 0) return false;
    if (exitSel === "fail") {
      const c = e.exit_code;
      if (c === undefined || c === null || c === 0) return false;
      if (c === -9 || c === -15) return false;  // killed / SIGTERM handled below
    }
    if (exitSel === "killed") {
      const c = e.exit_code;
      const isTimeout = (e.type || "").includes("timeout");
      if (!isTimeout && c !== -9 && c !== -15) return false;
    }
    // search
    if (q) {
      const hay = [
        e.type, e.cmd, e.path, e.reason, e.error, e.matched,
        e.client, e.actor, e.request_id, e.interpreter, e.action,
      ].filter(Boolean).map(x => String(x).toLowerCase()).join(" | ");
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

// Populate the type dropdown from the current fetch so users
// discover event types without reading the source. Preserves the
// current selection across reloads.
function __auditRebuildTypeSelect(events) {
  const sel = document.getElementById("auditFilter");
  const prev = sel.value;
  const seen = new Set();
  events.forEach(e => { if (e.type) seen.add(String(e.type)); });
  // Also keep the coarse categories agents may prefer.
  const groups = ["exec", "exec_script", "exec_stream", "file_", "admin.", "tunnel", "zerotier"];
  const parts = ['<option value="">All types</option>'];
  groups.forEach(g => {
    parts.push('<option value="' + esc(g) + '">' + esc(g) + '*</option>');
  });
  parts.push('<option disabled>-- exact --</option>');
  Array.from(seen).sort().forEach(t => {
    parts.push('<option value="' + esc(t) + '">' + esc(t) + '</option>');
  });
  sel.innerHTML = parts.join("");
  if (prev) sel.value = prev;  // may be gone; that's fine
}

function __auditRenderPage() {
  const tbody = document.getElementById("auditTable");
  const pager = document.getElementById("auditPager");
  const meta = document.getElementById("auditMeta");
  const pageSize = parseInt(document.getElementById("auditPageSize").value, 10) || 100;

  const all = __auditFilter(__auditState.raw);
  // Newest first -- audit.jsonl is append-only, tail() returns in
  // chronological order.
  const rows = all.slice().reverse();
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  if (__auditState.page >= totalPages) __auditState.page = totalPages - 1;
  if (__auditState.page < 0) __auditState.page = 0;
  const start = __auditState.page * pageSize;
  const slice = rows.slice(start, start + pageSize);

  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="audit-empty">No matching audit events. ' +
      (__auditState.raw.length > 0
        ? "Try widening the filters (search / type / exit)."
        : "The bridge audit log is empty.") + '</td></tr>';
    pager.innerHTML = "";
  } else {
    let html = "";
    slice.forEach((e, i) => {
      const cat = __auditCategory(e.type);
      const detail = __auditDetail(e);
      const rid = e.request_id ? String(e.request_id).slice(0, 8) : "-";
      html += '<tr class="audit-row" data-idx="' + (start + i) + '">' +
        '<td class="col-time mono">' + esc(__auditTimeCell(e.ts || e.timestamp)) + '</td>' +
        '<td class="col-type"><span class="ev-badge ' + cat + '">' + esc(String(e.type || "?")) + '</span></td>' +
        '<td class="col-actor mono">' + esc(String(__auditActor(e))) + '</td>' +
        '<td class="col-rid mono" title="' + esc(String(e.request_id || "")) + '">' + esc(rid) + '</td>' +
        '<td class="mono" title="' + esc(String(detail)) + '">' + esc(String(detail).slice(0, 240)) + '</td>' +
        '<td class="col-exit">' + __auditExitCell(e) + '</td>' +
        '</tr>' +
        '<tr class="audit-detail-row"><td colspan="6">' + esc(__auditRenderExpanded(e)) + '</td></tr>';
    });
    tbody.innerHTML = html;

    // Row-expand on click. Attach at tbody level so re-renders don't
    // leak handlers.
    tbody.querySelectorAll("tr.audit-row").forEach(tr => {
      tr.addEventListener("click", () => {
        const next = tr.nextElementSibling;
        if (next && next.classList.contains("audit-detail-row")) {
          next.classList.toggle("open");
        }
      });
    });

    const from = start + 1;
    const to = Math.min(start + slice.length, rows.length);
    pager.innerHTML =
      '<button class="sm" onclick="__auditNav(-1)"' + (__auditState.page === 0 ? " disabled" : "") + '>&laquo; Prev</button>' +
      '<span>' + from + '-' + to + ' of ' + rows.length + '</span>' +
      '<button class="sm" onclick="__auditNav(1)"' + (__auditState.page >= totalPages - 1 ? " disabled" : "") + '>Next &raquo;</button>' +
      '<span style="margin-left:8px">page ' + (__auditState.page + 1) + '/' + totalPages + '</span>';
  }

  const parts = [];
  parts.push(__auditState.raw.length + " fetched");
  parts.push(rows.length + " after filters");
  if (__auditState.lastFetch) {
    parts.push("last fetch " + __auditState.lastFetch.toLocaleTimeString());
  }
  meta.innerHTML = parts.map(esc).join('<span class="sep">|</span>');
}

function __auditNav(delta) {
  __auditState.page += delta;
  __auditRenderPage();
}

// Toggle auto-refresh. 5-second cadence -- enough to feel live but
// well within the bridge's request budget even on Overview.
function __auditToggleAuto() {
  const on = document.getElementById("auditAuto").checked;
  const dot = document.getElementById("auditRefreshDot");
  if (on) {
    dot.classList.add("on");
    if (__auditState.autoTimer) clearInterval(__auditState.autoTimer);
    __auditState.autoTimer = setInterval(loadAudit, 5000);
  } else {
    dot.classList.remove("on");
    if (__auditState.autoTimer) {
      clearInterval(__auditState.autoTimer);
      __auditState.autoTimer = null;
    }
  }
}

async function loadAudit() {
  const n = document.getElementById("auditLines").value || "200";
  const tbody = document.getElementById("auditTable");
  const meta = document.getElementById("auditMeta");
  // First render (before filters wired): install handlers exactly once.
  if (!loadAudit._wired) {
    document.getElementById("auditSearch").addEventListener("input", __auditRenderPage);
    document.getElementById("auditFilter").addEventListener("change", () => { __auditState.page = 0; __auditRenderPage(); });
    document.getElementById("auditExit").addEventListener("change", () => { __auditState.page = 0; __auditRenderPage(); });
    document.getElementById("auditPageSize").addEventListener("change", () => { __auditState.page = 0; __auditRenderPage(); });
    document.getElementById("auditAuto").addEventListener("change", __auditToggleAuto);
    loadAudit._wired = true;
  }
  if (!__auditState.raw.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="audit-empty"><span class="spinner"></span> Loading audit...</td></tr>';
  }
  try {
    const result = await api("/v1/audit?lines=" + encodeURIComponent(n));
    if (!result.ok) {
      tbody.innerHTML = '<tr><td colspan="6" class="audit-empty">Error: ' + esc(result.error || "?") + '</td></tr>';
      return;
    }
    __auditState.raw = result.events || [];
    __auditState.lastFetch = new Date();
    __auditRebuildTypeSelect(__auditState.raw);
    __auditRenderPage();
  } catch (e) {
    tbody.innerHTML = '<tr><td colspan="6" class="audit-empty">Error loading audit: ' + esc(e.message || "Unknown") + '</td></tr>';
    if (meta) meta.textContent = "";
  }
}

async function auditStats() {
  const panel = document.getElementById("auditStatsPanel");
  panel.style.display = "block";
  panel.innerHTML = "<span class='spinner'></span> Computing audit statistics...";
  try {
    const result = await api("/v1/audit?lines=1000");
    if (!result.ok) { panel.innerHTML = "Error: " + esc(result.error||"?"); return; }
    const events = result.events || [];
    const typeCounts = {};
    let minTs = null, maxTs = null;
    events.forEach(e => {
      const t = e.type || "unknown";
      typeCounts[t] = (typeCounts[t]||0) + 1;
      const ts = e.ts || e.timestamp;
      if (ts) {
        const d = new Date(ts);
        if (!minTs || d < minTs) minTs = d;
        if (!maxTs || d > maxTs) maxTs = d;
      }
    });

    panel.innerHTML = "";
    const h3 = document.createElement("h3");
    h3.textContent = "Audit Statistics";
    panel.appendChild(h3);

    const statsGrid = document.createElement("div");
    statsGrid.className = "card-grid-sm";
    const totalCard = document.createElement("div");
    totalCard.className = "card";
    totalCard.innerHTML = "<div class='stat info'>" + events.length + "</div><div class='label'>Total Events</div>";
    statsGrid.appendChild(totalCard);
    panel.appendChild(statsGrid);

    // Type counts
    Object.entries(typeCounts).sort((a,b)=>b[1]-a[1]).forEach(([type, count]) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = "<div class='stat warn'>" + count + "</div><div class='label'>" + esc(type) + "</div>";
      statsGrid.appendChild(card);
    });

    // Time range
    if (minTs && maxTs) {
      const tr = document.createElement("p");
      tr.style.cssText = "font-size:12px;color:var(--text2);margin-top:8px";
      tr.textContent = "Time range: " + minTs.toLocaleString() + " to " + maxTs.toLocaleString();
      panel.appendChild(tr);
    }
  } catch(e) {
    panel.innerHTML = "Error: " + esc(e.message||"Unknown");
  }
}
