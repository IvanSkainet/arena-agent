function workspaceProfileValue() {
  const el = document.getElementById("workspaceProfile");
  return ((el && el.value) || getActiveMemoryProfile() || "default").trim() || "default";
}

async function loadWorkspace() {
  syncMemoryProfileFields(workspaceProfileValue());
  const summary = document.getElementById("workspaceSummary");
  if (!summary) return;
  try {
    const profile = workspaceProfileValue();
    const [memory, tasks, watchers] = await Promise.all([
      api("/v1/memory?profile=" + encodeURIComponent(profile) + "&limit=5"),
      api("/v1/tasks"),
      api("/v1/watch/files"),
    ]);
    const lines = [];
    lines.push("profile=" + profile);
    lines.push("known profiles=" + ((memory.profiles || []).join(", ") || "none"));
    lines.push("memory facts in profile=" + (memory.count || 0));
    lines.push("task queue entries=" + ((tasks.tasks || []).length || 0));
    lines.push("active watchers=" + (watchers.count || 0));
    if (memory.facts && memory.facts.length) {
      lines.push("recent facts:");
      memory.facts.slice(-5).forEach(f => lines.push("- " + f.key + " = " + String(f.value).slice(0, 80)));
    }
    summary.textContent = lines.join("\n");
  } catch (e) {
    summary.textContent = "Error: " + (e.message || "unknown");
  }
  loadWorkspaceWatchers();
}

function _workspaceConstraints() {
  const raw = (document.getElementById("workspaceConstraints").value || "").trim();
  return raw ? raw.split(",").map(x => x.trim()).filter(Boolean) : [];
}

async function runWorkspacePlan() {
  const goal = (document.getElementById("workspaceGoal").value || "").trim();
  if (!goal) return alert("Goal required");
  const box = document.getElementById("workspacePlanResult");
  box.style.display = "block";
  box.textContent = "Planning...";
  try {
    const profile = workspaceProfileValue();
    const result = await api("/v1/plan", {method: "POST", body: JSON.stringify({
      goal,
      context: document.getElementById("workspaceContext").value || "",
      constraints: _workspaceConstraints(),
      max_steps: parseInt(document.getElementById("workspaceMaxSteps").value || "6", 10),
      memory_profile: profile,
    })});
    box.textContent = JSON.stringify(result, null, 2);
    window.ARENA_LAST_PLAN = result;
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function runWorkspaceReact() {
  const goal = (document.getElementById("workspaceGoal").value || "").trim();
  if (!goal) return alert("Goal required");
  const box = document.getElementById("workspaceReactResult");
  box.style.display = "block";
  box.textContent = "Running bounded loop...";
  try {
    const result = await api("/v1/react", {method: "POST", body: JSON.stringify({
      goal,
      context: document.getElementById("workspaceContext").value || "",
      constraints: _workspaceConstraints(),
      max_iterations: parseInt(document.getElementById("workspaceMaxIterations").value || "4", 10),
      memory_profile: workspaceProfileValue(),
      url: document.getElementById("workspaceReactUrl").value || "",
    })});
    box.textContent = JSON.stringify(result, null, 2);
    window.ARENA_LAST_REACT = result;
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function runWorkspaceReflect() {
  const box = document.getElementById("workspaceReflectResult");
  box.style.display = "block";
  box.textContent = "Reflecting...";
  try {
    const run = window.ARENA_LAST_REACT || window.ARENA_LAST_PLAN || {};
    const result = await api("/v1/reflect", {method: "POST", body: JSON.stringify({
      goal: (document.getElementById("workspaceGoal").value || "").trim(),
      run,
      notes: document.getElementById("workspaceNotes").value || "",
      outcome: document.getElementById("workspaceOutcome").value || "",
    })});
    box.textContent = JSON.stringify(result, null, 2);
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function loadWorkspaceWatchers() {
  const box = document.getElementById("workspaceWatchers");
  if (!box) return;
  box.style.display = "block";
  try {
    const result = await api("/v1/watch/files");
    if (!result.watchers || !result.watchers.length) {
      box.textContent = "No active watchers.";
      return;
    }
    box.textContent = JSON.stringify(result.watchers, null, 2);
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function addWorkspaceWatcher() {
  const path = (document.getElementById("watchPath").value || "").trim();
  if (!path) return alert("Watcher path required");
  const patternsRaw = (document.getElementById("watchPatterns").value || "").trim();
  const patterns = patternsRaw ? patternsRaw.split(",").map(x => x.trim()).filter(Boolean) : [];
  try {
    await api("/v1/watch/files", {method: "POST", body: JSON.stringify({
      path,
      recursive: !!document.getElementById("watchRecursive").checked,
      patterns,
      label: document.getElementById("watchLabel").value || "",
    })});
    loadWorkspaceWatchers();
  } catch (e) {
    alert("Error adding watcher: " + (e.message || "unknown"));
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    const stored = localStorage.getItem("arenaMemoryProfile") || "default";
    const workspaceProfile = document.getElementById("workspaceProfile");
    if (workspaceProfile) workspaceProfile.value = stored;
  });
} else {
  const stored = localStorage.getItem("arenaMemoryProfile") || "default";
  const workspaceProfile = document.getElementById("workspaceProfile");
  if (workspaceProfile) workspaceProfile.value = stored;
}
