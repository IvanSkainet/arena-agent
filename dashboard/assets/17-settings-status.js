// ===== SETTINGS =====

// Extra work to run whenever the Settings tab is shown. Two modules used to
// reassign `refreshSettings` itself (`const orig = refreshSettings;
// refreshSettings = async () => { await orig(); ... }`), which worked but only
// by luck: it depends on every caller resolving the name at call time rather
// than holding a reference, and a third patch written in the same style would
// silently swallow the second. A list is what the code actually meant.
const _settingsRefreshHooks = [];

/** Register extra work for the Settings tab. Failures never block the rest. */
function registerSettingsRefreshHook(fn) {
  if (typeof fn === "function") _settingsRefreshHooks.push(fn);
}

async function refreshSettings() {
  // Service mode badge
  try {
    const si = await api("/v1/service/info");
    const el = document.getElementById("setServiceMode");
    if (el && si && si.ok) {
      const mode = si.running_as || "unknown";
      const labels = {
        "nssm-service":   ["NSSM Windows Service", "ok"],
        "scheduled-task": ["Windows Scheduled Task", "warn"],
        "systemd-user":   ["systemd-user (Linux)", "ok"],
        "launchd":        ["launchd (macOS)", "ok"],
        // v4.168.1: Android. The bridge used to report "unknown" on
        // every phone because it fell into the Linux branch and asked
        // systemd, which Termux does not have. The hook-only state is
        // called out separately on purpose: a boot script with no
        // Termux:Boot app looks exactly like working autostart until
        // the phone reboots and the bridge does not come back.
        "termux-boot":           ["Termux:Boot (autostart)", "ok"],
        "termux-boot-hook-only": ["Hook installed, Termux:Boot missing", "warn"],
        "manual":                ["Manual / unmanaged", "warn"],
        "unknown":               ["Manual / unmanaged", "warn"],
      };
      const [label, kind] = labels[mode] || [mode, "gray"];
      el.className = "badge " + kind;
      el.textContent = label + (si.pid ? "  (PID " + si.pid + ")" : "");
      el.title = JSON.stringify(si, null, 2);

      // Say what to do about it, where the operator is already looking.
      const note = si.termux_boot && si.termux_boot.note;
      let hint = document.getElementById("setServiceHint");
      if (note) {
        if (!hint) {
          hint = document.createElement("p");
          hint.id = "setServiceHint";
          hint.className = "st-hint";
          hint.style.cssText = "margin:4px 0 0 0;font-size:12px";
          el.parentElement.parentElement.appendChild(hint);
        }
        hint.textContent = note;
      } else if (hint) {
        hint.remove();
      }
    }
  } catch (e) { /* ignore */ }

  try {
    const health = await api("/health");
    if (health.ok !== undefined && health.uptime_seconds !== undefined) {
      document.getElementById("setUptime").textContent = formatUptime(health.uptime_seconds);
    }
    // Env info
    const sysinfo = await api("/v1/sysinfo");
    if (sysinfo.ok) {
      const envParts = [];
      if (sysinfo.python_version) envParts.push("Python: " + sysinfo.python_version);
      if (sysinfo.platform) envParts.push("Platform: " + sysinfo.platform);
      if (sysinfo.os_build) envParts.push("OS: " + sysinfo.os_build);
      if (sysinfo.cpu_threads) envParts.push("CPU Threads: " + sysinfo.cpu_threads);
      if (sysinfo.mem_total_mb) envParts.push("RAM: " + (sysinfo.mem_total_mb/1024).toFixed(1) + " GB");
      if (sysinfo.disk_free_gb) envParts.push("Disk Free: " + sysinfo.disk_free_gb + " GB");
      if (sysinfo.architecture) envParts.push("Arch: " + sysinfo.architecture);
      document.getElementById("envInfo").textContent = envParts.join("\n");
    }
    // Metrics
    document.getElementById("setRequests").textContent = overviewMetrics.requests;
    document.getElementById("setErrors").textContent = overviewMetrics.errors;
    // Tunnel status per-transport now lives on the Transports tab; this
    // block used to query /v1/tailscale/funnel/status and
    // /v1/cloudflared/tunnel/status to paint tsToggleStatus / cfToggleStatus
    // badges, but the Settings card was reduced to a "Go to Transports tab"
    // link so those DOM ids no longer exist. See dashboard/assets/20-transports.js.
    // Webhooks
    const wh = await api("/v1/webhooks");
    if (wh && wh.ok && wh.webhooks) {
      document.getElementById("setWebhookUrls").value = (wh.webhooks.urls || []).join("\n");
      document.getElementById("setWebhookEvents").value = (wh.webhooks.events || []).join(", ");
    }
  } catch(e) {
    // Silent fail
  }

  // Run registered extras last, each isolated: one failing hook must not
  // stop the others or the base refresh that already succeeded.
  for (const hook of _settingsRefreshHooks) {
    try {
      await hook();
    } catch (e) {
      console.warn("[settings] refresh hook failed", e);
    }
  }
}

async function saveWebhooks() {
  const urlsRaw = document.getElementById("setWebhookUrls").value;
  const eventsRaw = document.getElementById("setWebhookEvents").value;
  
  const urls = urlsRaw.split("\n").map(s => s.trim()).filter(s => s.startsWith("http"));
  const events = eventsRaw.split(",").map(s => s.trim()).filter(s => s.length > 0);
  
  if (events.length === 0) events.push("*");
  
  try {
    const res = await api("/v1/webhooks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls, events })
    });
    if (res.ok) {
      alert("Webhooks saved successfully.");
      refreshSettings();
    } else {
      alert("Error saving webhooks: " + res.error);
    }
  } catch (e) {
    alert("Error: " + e.message);
  }
}

// _humanTunnelError removed along with the tsFunnelToggle / cfFunnelToggle
// callers that were its only consumers. The Transports tab surfaces its own
// per-transport hint text via the tr-hint slot in each card.

// tsFunnelToggle / cfFunnelToggle removed in the Settings-migration cleanup.
// Their functionality now lives on the Transports tab as transportStart('tailscale') /
// transportStart('cloudflared') in dashboard/assets/20-transports.js.
// If a bookmarked script still calls the old names it will get a ReferenceError;
// operators should open the Transports tab and use the per-transport Start/Stop
// buttons there. Removed here rather than shimmed because keeping named
// stubs would silently pretend to work and hide the migration from users.

// ===== v4.97.0: YOLO mode (auto-approve everything) =====
// The ack token is read from the server (/v1/control/yolo) so it can never
// drift from arena.autonomy.YOLO_ACK_TOKEN. Enabling also requires the
// operator to tick the liability checkbox AND confirm.
let _yoloAck = "I_ACCEPT_FULL_RESPONSIBILITY";

async function yoloRefresh() {
  try {
    const st = await api("/v1/control/yolo");
    if (!st || !st.ok) return;
    if (st.ack_token) _yoloAck = st.ack_token;
    const on = !!st.yolo;
    const badge = document.getElementById("yoloBadge");
    if (badge) { badge.className = "badge " + (on ? "fail" : "ok"); badge.textContent = on ? "ON" : "OFF"; }
    const en = document.getElementById("yoloEnableBtn");
    const di = document.getElementById("yoloDisableBtn");
    if (en) en.style.display = on ? "none" : "inline-block";
    if (di) di.style.display = on ? "inline-block" : "none";
    const ack = document.getElementById("yoloAckCheck");
    if (ack) ack.checked = false;  // never pre-tick the liability box
    const txt = document.getElementById("yoloStateText");
    if (txt) {
      txt.textContent = on
        ? ("Enabled" + (st.enabled_at ? " at " + String(st.enabled_at).slice(11, 19) : "") + (st.enabled_by ? " by " + st.enabled_by : ""))
        : "Disabled (safe default; not persisted across restarts).";
    }
  } catch (e) { /* settings tab may render before endpoint is reachable */ }
}

async function yoloSet(enable) {
  if (enable) {
    const ack = document.getElementById("yoloAckCheck");
    if (!ack || !ack.checked) { alert("Tick the responsibility checkbox first."); return; }
    if (!confirm("Enable YOLO? The agent will run EVERY tool with NO " +
                 "confirmation until you disable it or the bridge restarts. " +
                 "Nobody is responsible for what it does.")) return;
  }
  const body = enable
    ? {enabled: true, ack: _yoloAck, by: "dashboard"}
    : {enabled: false, by: "dashboard"};
  const r = await api("/v1/control/yolo", {method: "POST", body: JSON.stringify(body)});
  if (r && r.ok) { await yoloRefresh(); }
  else { alert((enable ? "Enable" : "Disable") + " failed: " +
               ((r && (r.error || r.message)) || "unknown")); }
}

// Refresh YOLO state every time the Settings tab opens.
registerSettingsRefreshHook(() => yoloRefresh());

// ===== EXECUTION POSTURE ("cubes") for code.run (v4.102.0) =====
// The risk scoring below MIRRORS arena/autonomy/posture.py risk_level(); it is
// for live UI feedback only -- the SERVER re-validates and enforces the ack on
// Apply, so a client mis-compute can never bypass safety.
let _postureMeta = null;
const _POSTURE_AXES = ["sandbox", "network", "privilege", "filesystem", "runtime"];

function _postureRisk(p) {
  let s = 0;
  if (p.sandbox === "off") s += 3;
  if (p.privilege === "elevated") s += 2;
  if (p.network === "open") s += 2;
  if (p.filesystem === "open") s += 2; else if (p.filesystem === "home-rw") s += 1;
  if (p.runtime === "any") s += 1;
  return s >= 5 ? "critical" : s >= 3 ? "high" : s >= 1 ? "medium" : "low";
}
function _postureReadUI() {
  const p = {};
  _POSTURE_AXES.forEach(function (a) {
    const el = document.getElementById("posture_" + a);
    if (el) p[a] = el.value;
  });
  return p;
}
function _postureExposes(p) {
  const e = [];
  if (p.sandbox === "off") e.push("NO sandbox &mdash; code runs on this host with your privileges");
  if (p.network === "open") e.push("network OPEN (egress unrestricted)");
  if (p.privilege === "elevated") e.push("ELEVATED privileges");
  if (p.filesystem === "open" || p.filesystem === "home-rw") e.push("filesystem writes NOT confined");
  if (p.runtime === "any") e.push("any interpreter allowed");
  return e;
}
function posturePreview() {
  const p = _postureReadUI();
  const risk = _postureRisk(p);
  const b = document.getElementById("postureRiskBadge");
  if (b) { b.className = "badge " + (risk === "low" ? "ok" : risk === "medium" ? "warn" : "fail"); b.textContent = risk; }
  const need = (risk === "high" || risk === "critical") && _postureMeta && _postureMeta.ack_phrases
    ? _postureMeta.ack_phrases[risk] : null;
  const exposes = _postureExposes(p);
  const warn = document.getElementById("postureWarn");
  if (warn) {
    if (exposes.length) {
      warn.style.display = "block";
      document.getElementById("postureWarnTitle").textContent = "Risky posture (" + risk + ") exposes:";
      document.getElementById("postureWarnBody").innerHTML = exposes.map(function (x) { return "&bull; " + x; }).join("<br>");
    } else { warn.style.display = "none"; }
  }
  const ackRow = document.getElementById("postureAckRow");
  if (ackRow) {
    if (need) {
      ackRow.style.display = "flex";
      ackRow.dataset.need = need;
      document.getElementById("postureAckLabel").textContent =
        "This posture is " + risk + ". Tick to confirm you accept it (server will also require the ack phrase).";
      document.getElementById("postureAckCheck").checked = false;
    } else { ackRow.style.display = "none"; ackRow.dataset.need = ""; }
  }
}
function posturePreset(name) {
  if (!_postureMeta || !_postureMeta.presets || !_postureMeta.presets[name]) return;
  const pr = _postureMeta.presets[name];
  _POSTURE_AXES.forEach(function (a) {
    const el = document.getElementById("posture_" + a);
    if (el && pr[a] != null) el.value = pr[a];
  });
  posturePreview();
}
async function postureRefresh() {
  try {
    const st = await api("/v1/autonomy/posture");
    if (!st || !st.axes) return;  // axes is what we render; don't depend on 'ok'
    _postureMeta = {axes: st.axes, ack_phrases: st.ack_phrases, presets: st.presets};
    const cur = st.posture || {};
    const box = document.getElementById("postureAxes");
    if (!box) return;
    box.innerHTML = _POSTURE_AXES.map(function (a) {
      const vals = (st.axes && st.axes[a]) || [];
      const opts = vals.map(function (v) {
        return '<option value="' + v + '"' + (cur[a] === v ? " selected" : "") + ">" + v + "</option>";
      }).join("");
      return '<div class="row"><span style="width:96px;font-size:12px;color:var(--text2)">' + a +
             '</span><select id="posture_' + a + '" onchange="posturePreview()" style="max-width:240px">' +
             opts + "</select></div>";
    }).join("");
    const st2 = document.getElementById("postureStateText");
    if (st2) st2.textContent = "saved risk " + st.risk + " (" +
      _POSTURE_AXES.map(function (a) { return a + "=" + cur[a]; }).join(", ") + ")";
    posturePreview();
  } catch (e) { /* settings tab may render before endpoint is reachable */ }
}
async function postureApply() {
  const p = _postureReadUI();
  const risk = _postureRisk(p);
  const need = (risk === "high" || risk === "critical") && _postureMeta && _postureMeta.ack_phrases
    ? _postureMeta.ack_phrases[risk] : null;
  let ack = null;
  if (need) {
    const cb = document.getElementById("postureAckCheck");
    if (!cb || !cb.checked) { alert("Tick the confirmation checkbox for this " + risk + " posture."); return; }
    if (!confirm("Apply a " + risk + " execution posture?" +
                 (p.sandbox === "off" ? " Code will run UNFENCED on this host." : ""))) return;
    ack = need;
  }
  // keep runtimes/resources the UI does not edit in this slice
  const st = await api("/v1/autonomy/posture");
  const base = (st && st.posture) || {};
  const merged = Object.assign({}, base, p);
  const r = await api("/v1/autonomy/posture",
    {method: "POST", body: JSON.stringify({posture: merged, ack: ack})});
  if (r && r.ok) { await postureRefresh(); }
  else { alert("Apply failed: " + ((r && (r.error || r.message)) || "unknown") +
               (r && r.required_ack ? " (ack: " + r.required_ack + ")" : "")); }
}

registerSettingsRefreshHook(() => postureRefresh());
