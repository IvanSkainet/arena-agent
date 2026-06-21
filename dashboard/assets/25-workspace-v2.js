function workspaceNotesKey() {
  return "workspace.notes";
}

function workspaceLessonPrefix() {
  return "lesson:";
}

async function loadWorkspaceNotes() {
  const profile = workspaceProfileValue();
  const box = document.getElementById("workspaceProfileNotes");
  if (!box) return;
  try {
    const result = await api("/v1/memory?profile=" + encodeURIComponent(profile) + "&q=" + encodeURIComponent(workspaceNotesKey()));
    const facts = result.facts || [];
    const note = facts.find(f => f.key === workspaceNotesKey());
    box.value = note ? (note.value || "") : "";
  } catch (e) {
    box.value = "";
  }
}

async function saveWorkspaceNotes() {
  const profile = workspaceProfileValue();
  const value = (document.getElementById("workspaceProfileNotes").value || "").trim();
  if (!value) {
    return alert("Nothing to save in notes.");
  }
  const result = await api("/v1/memory", {
    method: "POST",
    body: JSON.stringify({profile, key: workspaceNotesKey(), value, tags: ["workspace", "notes"]})
  });
  if (!result.ok) return alert("Error saving notes: " + (result.error || "?"));
  loadWorkspace();
}

function _workspaceLessonKey() {
  return workspaceLessonPrefix() + Date.now();
}

async function loadWorkspaceLessons() {
  const profile = workspaceProfileValue();
  const box = document.getElementById("workspaceLessons");
  if (!box) return;
  try {
    const result = await api("/v1/memory?profile=" + encodeURIComponent(profile));
    const facts = (result.facts || []).filter(f => (f.key || "").startsWith(workspaceLessonPrefix()) || (f.tags || []).includes("lesson"));
    if (!facts.length) {
      box.textContent = "No lessons saved yet.";
      return;
    }
    box.textContent = facts.map(f => {
      const ts = f.timestamp ? relTime(f.timestamp) : "";
      return "- " + (f.value || "") + (ts ? " (" + ts + ")" : "");
    }).join("\n");
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function addWorkspaceLesson() {
  const profile = workspaceProfileValue();
  const input = document.getElementById("workspaceLessonText");
  const value = (input.value || "").trim();
  if (!value) return alert("Lesson text required");
  const result = await api("/v1/memory", {
    method: "POST",
    body: JSON.stringify({profile, key: _workspaceLessonKey(), value, tags: ["lesson", "workspace"]})
  });
  if (!result.ok) return alert("Error saving lesson: " + (result.error || "?"));
  input.value = "";
  loadWorkspaceLessons();
}

async function loadWorkspaceActivity() {
  const box = document.getElementById("workspaceActivity");
  if (!box) return;
  try {
    const result = await api("/v1/audit?lines=40");
    const events = (result.events || []).slice(-12).reverse();
    if (!events.length) {
      box.textContent = "No recent activity.";
      return;
    }
    box.textContent = events.map(ev => {
      const ts = String(ev.ts || ev.timestamp || "").slice(0, 19);
      const type = ev.type || ev.event || "unknown";
      const detail = ev.goal || ev.key || ev.path || ev.cmd || ev.reason || ev.profile || "";
      return `[${ts}] ${type}${detail ? " — " + String(detail).slice(0, 120) : ""}`;
    }).join("\n");
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

function loadWorkspacePanels() {
  loadWorkspaceNotes();
  loadWorkspaceLessons();
  loadWorkspaceActivity();
}
