function _workspaceMissionId() {
  return (document.getElementById("workspaceMissionId").value || "").trim();
}

function _workspaceMissionOptions() {
  return {
    goal: (document.getElementById("workspaceFollowupGoal").value || "").trim(),
    title: (document.getElementById("workspaceFollowupTitle").value || "").trim(),
    create: !!document.getElementById("workspaceMissionCreate").checked,
    run_now: !!document.getElementById("workspaceMissionRun").checked,
    rerun_now: !!document.getElementById("workspaceMissionRerun").checked,
  };
}

function _workspaceMissionLoopBox(id) {
  const box = document.getElementById(id);
  if (box) box.style.display = "block";
  return box;
}

async function loadWorkspaceMissionLoops() {
  const box = _workspaceMissionLoopBox("workspaceMissionCatalog");
  if (!box) return;
  box.textContent = "Loading mission catalog...";
  try {
    const result = await api("/v1/mission/catalog?limit=8");
    const items = result.items || [];
    if (!items.length) {
      box.textContent = "No persisted missions yet.";
      return;
    }
    box.textContent = items.map(item => {
      const lineage = item.parent_mission_id ? ` parent=${item.parent_mission_id} depth=${item.lineage_depth || 0}` : "";
      return `${item.name} [${item.state}] template=${item.template} runs=${item.runs_count || 0} children=${item.child_count || 0}${lineage}`;
    }).join("\n");
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function loadWorkspaceMissionLineage() {
  const missionId = _workspaceMissionId();
  if (!missionId) return alert("Mission id required");
  const box = _workspaceMissionLoopBox("workspaceMissionLineage");
  box.textContent = "Loading mission lineage...";
  try {
    const result = await api("/v1/mission/lineage?name=" + encodeURIComponent(missionId));
    box.textContent = JSON.stringify(result, null, 2);
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function runWorkspaceMissionFollowup() {
  const missionId = _workspaceMissionId();
  if (!missionId) return alert("Mission id required");
  const options = _workspaceMissionOptions();
  const box = _workspaceMissionLoopBox("workspaceMissionLoopResult");
  box.textContent = "Building follow-up mission...";
  try {
    const result = await api("/v1/mission/followup", {
      method: "POST",
      body: JSON.stringify({
        mission_id: missionId,
        goal: options.goal,
        title: options.title,
        notes: document.getElementById("workspaceNotes").value || "",
        memory_profile: workspaceProfileValue(),
        max_steps: parseInt(document.getElementById("workspaceMaxSteps").value || "6", 10),
        max_iterations: parseInt(document.getElementById("workspaceMaxIterations").value || "4", 10),
        create: options.create,
        run_now: options.run_now,
      }),
    });
    box.textContent = JSON.stringify(result, null, 2);
    if (result.followup && result.followup.goal && !options.goal) document.getElementById("workspaceFollowupGoal").value = result.followup.goal;
    loadWorkspaceMissionLoops();
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}

async function runWorkspaceMissionIterate() {
  const missionId = _workspaceMissionId();
  if (!missionId) return alert("Mission id required");
  const options = _workspaceMissionOptions();
  const box = _workspaceMissionLoopBox("workspaceMissionLoopResult");
  box.textContent = "Running mission iteration loop...";
  try {
    const result = await api("/v1/mission/iterate", {
      method: "POST",
      body: JSON.stringify({
        mission_id: missionId,
        notes: document.getElementById("workspaceNotes").value || "",
        memory_profile: workspaceProfileValue(),
        max_steps: parseInt(document.getElementById("workspaceMaxSteps").value || "6", 10),
        max_iterations: parseInt(document.getElementById("workspaceMaxIterations").value || "4", 10),
        rerun_now: options.rerun_now,
        compose_followup: true,
        create_followup: options.create || options.run_now,
        run_followup: options.run_now,
        followup_goal: options.goal,
        followup_title: options.title,
      }),
    });
    box.textContent = JSON.stringify(result, null, 2);
    if (result.followup && result.followup.goal && !options.goal) document.getElementById("workspaceFollowupGoal").value = result.followup.goal;
    loadWorkspaceMissionLoops();
    loadWorkspaceMissionLineage();
  } catch (e) {
    box.textContent = "Error: " + (e.message || "unknown");
  }
}
