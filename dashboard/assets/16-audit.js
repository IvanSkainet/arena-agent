// ===== AUDIT (v4.6.0 polish; v4.10.0 live-tail; v4.12.0 ring cap) =====
// State kept module-scope so pagination/filters survive between
// re-renders without re-fetching. Fresh loadAudit() (Reload button
// or auto-refresh tick) refills __auditState.raw.
//
// v4.10.0: adds a live-tail mode backed by /v1/audit/stream?follow=1.
// While live, incoming NDJSON events are pushed onto
// __auditState.raw and the current page re-renders in place. The
// stream is bounded by max_duration on the server (300s); we
// auto-reconnect with since=<last-known-ts> so no event is lost
// across the rollover.
//
// v4.12.0: bounded client-side ring buffer. A long-running live-tail
// session used to grow __auditState.raw unbounded -- a Dashboard
// left open for hours could accumulate tens of thousands of rows in
// memory. The buffer is now capped at __AUDIT_RING_CAP; when it
// overflows we drop the oldest entries and increment
// __auditState.evicted so the meta line can display an "evicted N"
// counter and operators know history was trimmed.
const __AUDIT_RING_CAP = 5000;

const __auditState = {
  raw: [],           // last full fetch from /v1/audit (or growing live)
  page: 0,           // 0-based current page
  autoTimer: null,   // setInterval handle when auto-refresh is on
  lastFetch: null,   // Date of last successful fetch (for meta line)
  // v4.10.0 live-tail state:
  liveController: null,   // AbortController for the fetch() stream
  liveReader: null,       // ReadableStreamDefaultReader we're pulling from
  liveLastTs: null,       // last event ts seen, used for since= on reconnect
  liveEvents: 0,          // running counter of events received live
  liveReconnectTimer: null, // setTimeout for the reconnect back-off
  // v4.12.0 ring buffer:
  evicted: 0,             // rows dropped from the head to honour the cap
};

// Trim __auditState.raw to __AUDIT_RING_CAP entries by dropping the
// oldest events at the head of the array. Returns the number of
// rows dropped so callers can bump __auditState.evicted. Safe to
// call any number of times; a no-op when the buffer is under cap.
function __auditEnforceRingCap() {
  const over = __auditState.raw.length - __AUDIT_RING_CAP;
  if (over <= 0) return 0;
  __auditState.raw.splice(0, over);
  return over;
}

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
  // v4.10.0: live-tail counter -- shown only while an active
  // subscription exists so ordinary polling stays uncluttered.
  if (__auditState.liveController) {
    parts.push("live +" + __auditState.liveEvents);
  }
  // v4.12.0: ring-cap eviction counter. Shown only when > 0 so
  // typical sessions stay uncluttered; a non-zero value means the
  // oldest events have scrolled off (cap = 5000 rows).
  if (__auditState.evicted > 0) {
    parts.push("evicted " + __auditState.evicted);
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
    // Auto-refresh and live-tail do the same job; keep exactly one.
    if (__auditState.liveController) __auditStopLive();
    const liveBox = document.getElementById("auditLive");
    if (liveBox) liveBox.checked = false;
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

// -------- v4.10.0: live-tail via /v1/audit/stream?follow=1 -------------
// Detect ReadableStream support at attach time; older browsers get a
// disabled checkbox rather than a mystery error mid-stream.
function __auditLiveSupported() {
  try {
    // fetch() itself is old news; the streaming reader is the actual
    // requirement.  ``ReadableStream`` may exist without ``getReader``
    // (very old polyfills), so poke at that too.
    return typeof ReadableStream === "function"
      && typeof Response !== "undefined"
      && typeof (new Response(new Blob())).body === "object"
      && typeof (new Response(new Blob())).body.getReader === "function";
  } catch (_e) {
    return false;
  }
}

function __auditLiveSetStatus(kind) {
  // kind: "on" | "err" | "off"
  const dot = document.getElementById("auditLiveDot");
  if (!dot) return;
  dot.classList.remove("on", "err");
  if (kind === "on") dot.classList.add("on");
  else if (kind === "err") dot.classList.add("err");
}

function __auditIngestLiveEvent(ev) {
  // Server-emitted control events (meta / exit / error / raw) are
  // *not* audit rows; skip them from the table view but use their
  // ts if present so a since= reconnect can advance.
  const t = ev && ev.type;
  if (!t) return;
  if (t === "meta" || t === "exit" || t === "error") return;
  if (t === "raw") {
    // Malformed audit line surfaced by the server -- keep it visible
    // so operators notice corruption, but tag it clearly.
    __auditState.raw.push({type: "raw", line: ev.line || ""});
  } else {
    __auditState.raw.push(ev);
  }
  __auditState.liveEvents += 1;
  // v4.12.0: enforce ring cap so a long-running live-tail session
  // can't accumulate tens of thousands of rows in memory. Dropped
  // rows are the oldest ones (head of array); the meta line
  // displays the running "evicted N" counter.
  __auditState.evicted += __auditEnforceRingCap();
  const ts = ev.ts || ev.timestamp;
  if (ts) __auditState.liveLastTs = ts;
  // Re-render only when the audit tab is the one on screen so we
  // don't fight other tabs for CPU.
  const tab = document.getElementById("tab-audit");
  if (tab && tab.classList.contains("active")) {
    __auditRenderPage();
  }
}

// Pump a ReadableStreamDefaultReader, split on '\n' and JSON-parse
// each line. Any parse error is logged to the console but does not
// tear the stream down -- the next line may still be well-formed.
async function __auditConsumeStream(reader) {
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    let chunk;
    try {
      chunk = await reader.read();
    } catch (e) {
      // Abort() surfaces as an error here on some browsers. Bail
      // silently; the caller's finally block handles cleanup.
      break;
    }
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, {stream: true});
    let idx;
    while ((idx = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (!line) continue;
      try {
        __auditIngestLiveEvent(JSON.parse(line));
      } catch (e) {
        console.warn("audit live-tail: bad NDJSON line", e, line);
      }
    }
  }
  // Flush any trailing bytes (usually empty when the server ended
  // cleanly with a newline-terminated exit event).
  buffer += decoder.decode();
  const tail = buffer.trim();
  if (tail) {
    try {
      __auditIngestLiveEvent(JSON.parse(tail));
    } catch (_e) { /* ignore trailing garbage on abort */ }
  }
}

// Open one /v1/audit/stream?follow=1 request. When the server hits
// its max_duration the stream ends cleanly; we schedule a reconnect
// with since=<last-known-ts> so no event is missed across the
// rollover.
async function __auditOpenLiveConnection() {
  const controller = new AbortController();
  __auditState.liveController = controller;
  let base = "/v1/audit/stream?follow=1&lines=0&max_duration=300";
  if (__auditState.liveLastTs) {
    base += "&since=" + encodeURIComponent(__auditState.liveLastTs);
  }
  const token = (window.ARENA_TOKEN || "").trim();
  try {
    const resp = await fetch(base, {
      headers: token ? {"Authorization": "Bearer " + token} : {},
      signal: controller.signal,
    });
    if (!resp.ok || !resp.body) {
      __auditLiveSetStatus("err");
      __auditScheduleLiveReconnect(3000);
      return;
    }
    __auditLiveSetStatus("on");
    __auditState.liveReader = resp.body.getReader();
    await __auditConsumeStream(__auditState.liveReader);
  } catch (e) {
    if (e && e.name === "AbortError") return;   // clean stop
    __auditLiveSetStatus("err");
  } finally {
    __auditState.liveReader = null;
    if (__auditState.liveController === controller) {
      __auditState.liveController = null;
    }
  }
  // If the user still wants live and we ended for any reason other
  // than an abort, reconnect. 250ms is enough to avoid a hot-loop on
  // an immediate error but small enough to feel seamless during a
  // clean max_duration rollover.
  const box = document.getElementById("auditLive");
  if (box && box.checked) {
    __auditScheduleLiveReconnect(250);
  }
}

function __auditScheduleLiveReconnect(delayMs) {
  if (__auditState.liveReconnectTimer) {
    clearTimeout(__auditState.liveReconnectTimer);
  }
  __auditState.liveReconnectTimer = setTimeout(() => {
    __auditState.liveReconnectTimer = null;
    const box = document.getElementById("auditLive");
    if (box && box.checked) __auditOpenLiveConnection();
  }, delayMs);
}

function __auditStopLive() {
  const box = document.getElementById("auditLive");
  if (box) box.checked = false;
  if (__auditState.liveReconnectTimer) {
    clearTimeout(__auditState.liveReconnectTimer);
    __auditState.liveReconnectTimer = null;
  }
  if (__auditState.liveController) {
    try { __auditState.liveController.abort(); } catch (_e) {}
  }
  __auditState.liveController = null;
  __auditState.liveReader = null;
  __auditLiveSetStatus("off");
}

async function __auditToggleLive() {
  const box = document.getElementById("auditLive");
  if (!box) return;
  if (!__auditLiveSupported()) {
    box.checked = false;
    box.disabled = true;
    box.title = "Live-tail needs a browser with ReadableStream (Chrome 43+, Firefox 65+, Safari 10.1+).";
    return;
  }
  if (box.checked) {
    // live-tail wins over auto-refresh: turn polling off.
    const autoBox = document.getElementById("auditAuto");
    if (autoBox && autoBox.checked) {
      autoBox.checked = false;
      __auditToggleAuto();
    }
    // Seed the cursor from the newest row we already have so the
    // first stream doesn't re-emit the last N events already on
    // screen. loadAudit() runs before the toggle in the typical UX
    // flow, so __auditState.raw is usually non-empty.
    if (!__auditState.liveLastTs && __auditState.raw.length > 0) {
      for (let i = __auditState.raw.length - 1; i >= 0; i--) {
        const ts = __auditState.raw[i].ts || __auditState.raw[i].timestamp;
        if (ts) { __auditState.liveLastTs = ts; break; }
      }
    }
    __auditState.liveEvents = 0;
    __auditOpenLiveConnection();
  } else {
    __auditStopLive();
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
    // v4.10.0: live-tail checkbox. Disable on browsers without
    // ReadableStream support so users don't chase a mystery no-op.
    const liveBox = document.getElementById("auditLive");
    if (liveBox) {
      if (!__auditLiveSupported()) {
        liveBox.disabled = true;
        liveBox.title = "Live-tail needs a browser with ReadableStream (Chrome 43+, Firefox 65+, Safari 10.1+).";
      } else {
        liveBox.addEventListener("change", __auditToggleLive);
      }
    }
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
    // v4.12.0: a fresh poll replaces the buffer entirely, so the
    // "evicted" counter resets -- a Reload button click is the
    // operator's explicit "start over" gesture. The cap still
    // applies in case an operator asked for lines=10000+ history.
    __auditState.raw = result.events || [];
    __auditState.evicted = __auditEnforceRingCap();
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
