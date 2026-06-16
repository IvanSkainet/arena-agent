// ===== TASKS =====
function startTaskRefresh() {
  stopTaskRefresh();
  taskRefreshTimer = setInterval(loadTasks, 10000);
}
function stopTaskRefresh() {
  if (taskRefreshTimer) { clearInterval(taskRefreshTimer); taskRefreshTimer = null; }
}

function showTaskSubmit() {
  document.getElementById("taskSubmitPanel").style.display = "block";
  document.getElementById("taskCmd").focus();
}

async function loadTasks() {
  const tbody = document.getElementById("tasksTable");
  try {
    const result = await api("/v1/tasks");
    if (!result.ok) { tbody.innerHTML = "<tr><td colspan='5'>Error: " + esc(result.error||"?") + "</td></tr>"; return; }
    const tasks = result.tasks || [];
    // Update stats
    const counts = {inbox:0, running:0, done:0, failed:0};
    tasks.forEach(t => { if (counts[t.state] !== undefined) counts[t.state]++; });
    document.getElementById("taskInbox").textContent = counts.inbox;
    document.getElementById("taskRunning").textContent = counts.running;
    document.getElementById("taskDone").textContent = counts.done;
    document.getElementById("taskFailed").textContent = counts.failed;
    document.getElementById("taskCountBadge").textContent = tasks.length;

    if (!tasks.length) { tbody.innerHTML = "<tr><td colspan='5'>No tasks</td></tr>"; return; }
    tbody.innerHTML = "";
    tasks.forEach(t => {
      const tr = document.createElement("tr");
      const stateColors = {inbox:"gray",running:"warn",done:"ok",failed:"fail"};
      const stateClass = stateColors[t.state] || "gray";
      tr.innerHTML = "<td class='mono'>" + esc(t.id || "").slice(0,8) + "</td><td class='mono' style='max-width:300px;overflow:hidden;text-overflow:ellipsis'>" + esc(t.cmd || "") + "</td><td><span class='badge " + stateClass + "'>" + esc(t.state || "?") + "</span></td><td class='mono'>" + esc(relTime(t.started_at || t.created_at)) + "</td><td class='mono'>" + esc(t.duration ? t.duration + "s" : "--") + "</td>";
      tbody.appendChild(tr);
    });
  } catch(e) {
    tbody.innerHTML = "<tr><td colspan='5'>Error loading tasks: " + esc(e.message||"Unknown") + "</td></tr>";
  }
}

async function submitTask() {
  const cmd = document.getElementById("taskCmd").value.trim();
  const timeout = parseInt(document.getElementById("taskTimeout").value) || 30;
  const cwd = document.getElementById("taskCwd").value.trim();
  if (!cmd) return alert("Command required");
  try {
    const body = {cmd, timeout};
    if (cwd) body.cwd = cwd;
    const result = await api("/v1/tasks", {method: "POST", body: JSON.stringify(body)});
    if (result.ok) {
      document.getElementById("taskSubmitPanel").style.display = "none";
      document.getElementById("taskCmd").value = "";
      document.getElementById("taskCwd").value = "";
      loadTasks();
    } else {
      alert("Error: " + (result.error||"?"));
    }
  } catch(e) {
    alert("Error submitting task: " + (e.message||"Unknown error"));
  }
}

async function cleanTasks() {
  try {
    const result = await api("/v1/tasks/clean", {method: "POST"});
    if (result.ok) loadTasks();
    else alert("Error: " + (result.error||"?"));
  } catch(e) {
    alert("Error cleaning tasks: " + (e.message||"Unknown error"));
  }
}

