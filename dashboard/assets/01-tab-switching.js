// ===== TAB SWITCHING =====
document.querySelectorAll(".sidebar nav a").forEach(a => {
  a.addEventListener("click", () => {
    document.querySelectorAll(".sidebar nav a").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    a.classList.add("active");
    const tabName = a.dataset.tab;
    activeTab = tabName;
    document.getElementById("tab-" + tabName).classList.add("active");
    // Load data on tab switch
    if (tabName === "overview") refreshOverview();
    if (tabName === "workspace") loadWorkspace();
    if (tabName === "memory") loadMemory();
    if (tabName === "missions") loadMissions();
    if (tabName === "reports") loadReports();
    if (tabName === "tasks") { loadTasks(); startTaskRefresh(); }
    else { stopTaskRefresh(); }
    if (tabName === "skills") loadSkills();
    if (tabName === "hooks") loadHooks();
    if (tabName === "agents") loadAgents();
    if (tabName === "audit") loadAudit();
    if (tabName === "settings") refreshSettings();
    if (tabName === "mobile") refreshMobile();
    if (tabName === "doctor") runDoctor();
    if (tabName === "control") refreshControlPanel();
  });
});

