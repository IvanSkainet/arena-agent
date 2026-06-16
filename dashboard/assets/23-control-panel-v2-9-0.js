// ===== CONTROL PANEL (v2.9.0) =====
async function refreshControlPanel() {
  try {
    const cs = await api("/v1/control/status");
    if (!cs || !cs.ok) return;
    const state = cs.control || "active";
    const reason = cs.reason || "";

    // Big status
    const icons = {active: "&#9989;", paused: "&#9208;", revoked: "&#128683;"};
    const labels = {active: "ACTIVE", paused: "PAUSED", revoked: "REVOKED"};
    const colors = {active: "ok", paused: "warn", revoked: "fail"};
    document.getElementById("controlBigStatus").innerHTML = icons[state] || "&#10067;";
    document.getElementById("controlBigLabel").textContent = labels[state] || state;
    document.getElementById("controlBigLabel").style.color = state === "active" ? "var(--green)" : state === "paused" ? "var(--yellow)" : "var(--red)";
    document.getElementById("controlBigReason").textContent = reason;

    // Status table
    const badge = document.getElementById("ctrlStatusBadge");
    badge.className = "badge " + colors[state];
    badge.textContent = state;
    document.getElementById("ctrlReason").textContent = reason || "--";
    document.getElementById("ctrlPausedAt").textContent = cs.paused_at ? relTime(cs.paused_at) + " (" + cs.paused_at.slice(11,19) + ")" : "--";
    document.getElementById("ctrlRevokedAt").textContent = cs.revoked_at ? relTime(cs.revoked_at) + " (" + cs.revoked_at.slice(11,19) + ")" : "--";
    document.getElementById("ctrlLastAgent").textContent = cs.last_agent_input_at ? relTime(cs.last_agent_input_at) : "--";
    document.getElementById("ctrlLastUser").textContent = cs.last_user_input_at ? relTime(cs.last_user_input_at) : "--";
    document.getElementById("ctrlSession").textContent = cs.session_id || "--";

    // Button visibility
    document.getElementById("ctrlPauseBtn").style.display = state === "active" ? "inline-block" : "none";
    document.getElementById("ctrlResumeBtn").style.display = state !== "active" ? "inline-block" : "none";
    document.getElementById("ctrlRevokeBtn").style.display = state !== "revoked" ? "inline-block" : "none";

    // Overview card
    const ovState = document.getElementById("overviewControlState");
    if (ovState) { ovState.className = "badge " + colors[state]; ovState.textContent = state; }
    const ovBadge = document.getElementById("overviewControlBadge");
    if (ovBadge) { ovBadge.className = "badge " + colors[state]; ovBadge.textContent = state; }
    const ovPause = document.getElementById("overviewPauseBtn");
    const ovResume = document.getElementById("overviewResumeBtn");
    if (ovPause) ovPause.style.display = state === "active" ? "inline-block" : "none";
    if (ovResume) ovResume.style.display = state !== "active" ? "inline-block" : "none";

    // Also refresh active window
    refreshActiveWindow();
  } catch(e) {}
}

async function controlPause() {
  const reason = prompt("Reason for pausing (optional):", "User paused from dashboard") || "Dashboard pause";
  const r = await api("/v1/control/pause", {method: "POST", body: JSON.stringify({reason})});
  if (r && r.ok) { refreshControlPanel(); }
  else { alert("Pause failed: " + (r ? r.error : "unknown")); }
}

async function controlResume() {
  if (!confirm("Resume agent desktop control?")) return;
  const r = await api("/v1/control/resume", {method: "POST"});
  if (r && r.ok) { refreshControlPanel(); }
  else { alert("Resume failed: " + (r ? r.error : "unknown")); }
}

async function controlRevoke() {
  if (!confirm("REVOKE agent desktop control? This blocks all desktop input until resumed.")) return;
  const r = await api("/v1/control/revoke", {method: "POST", body: JSON.stringify({reason: "User revoked from dashboard"})});
  if (r && r.ok) { refreshControlPanel(); }
  else { alert("Revoke failed: " + (r ? r.error : "unknown")); }
}

async function refreshActiveWindow() {
  try {
    const aw = await api("/v1/desktop/active_window");
    const textEl = document.getElementById("ctrlActiveWinText");
    if (aw && aw.ok && aw.id !== null) {
      const title = aw.title || "(no title)";
      if (textEl) textEl.textContent = `[${aw.backend}] ${title} (id=${aw.id})`;
      document.getElementById("ctrlWinId").textContent = aw.id || "--";
      document.getElementById("ctrlWinTitle").textContent = aw.title || "--";
      document.getElementById("ctrlWinPid").textContent = aw.pid || "--";
      document.getElementById("ctrlWinClass").textContent = aw.class || "--";
      document.getElementById("ctrlWinBackend").textContent = aw.backend || "--";
      // Overview
      const ovWin = document.getElementById("overviewActiveWindow");
      if (ovWin) ovWin.textContent = title;
    } else {
      if (textEl) textEl.textContent = "No active window detected";
      document.getElementById("ctrlWinId").textContent = "--";
      document.getElementById("ctrlWinTitle").textContent = "--";
      document.getElementById("ctrlWinPid").textContent = "--";
      document.getElementById("ctrlWinClass").textContent = "--";
      document.getElementById("ctrlWinBackend").textContent = aw ? aw.backend || "--" : "--";
    }
  } catch(e) {}
}

async function focusByTitle() {
  const title = document.getElementById("ctrlFocusTitle").value.trim();
  if (!title) { alert("Enter a window title"); return; }
  const resEl = document.getElementById("ctrlFocusResult");
  resEl.style.display = "block";
  resEl.textContent = "Focusing...";
  try {
    const r = await api("/v1/desktop/focus", {method: "POST", body: JSON.stringify({title, verify: true, timeout_ms: 1500})});
    resEl.textContent = JSON.stringify(r, null, 2);
    refreshActiveWindow();
  } catch(e) {
    resEl.textContent = "Error: " + e.message;
  }
}

async function testInputGuard() {
  const title = document.getElementById("guardTitleInput").value.trim();
  if (!title) { alert("Enter a required window title"); return; }
  const resEl = document.getElementById("guardTestResult");
  resEl.style.display = "block";
  resEl.textContent = "Testing...";
  try {
    // Test with a safe click at (0,0) with input guard
    const r = await api("/v1/desktop/click", {method: "POST", body: JSON.stringify({x: 0, y: 0, require_active_title: title})});
    if (r.ok) {
      resEl.textContent = "PASS: Input guard allowed (active window matches '" + title + "')";
      resEl.style.color = "var(--green)";
    } else if (r.error && r.error.includes("input_guard")) {
      resEl.textContent = "BLOCKED: Active window does not match '" + title + "'\nActive: " + (r.active_window ? r.active_window.title : "unknown");
      resEl.style.color = "var(--red)";
    } else {
      resEl.textContent = "Result: " + JSON.stringify(r, null, 2);
      resEl.style.color = "var(--text2)";
    }
  } catch(e) {
    resEl.textContent = "Error: " + e.message;
  }
}
