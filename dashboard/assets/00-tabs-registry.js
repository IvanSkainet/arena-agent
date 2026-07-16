// ===== TABS REGISTRY (v3.90.0) =====
//
// Single source of truth for every Dashboard tab. Adding a new tab
// = adding ONE entry below + shipping the corresponding body-XX.html
// / JS asset. Historically this data was duplicated across THREE
// places:
//     1. body-00-shell.html   -- <a data-tab="X">📊 Label</a> nav items
//     2. 01-tab-switching.js  -- if (tabName === "X") loadX();
//     3. dashboard/index.html -- 'body-XX-name.html' + 'YY-name.js'
//        entries in ARENA_DASHBOARD_SCRIPTS / bodyParts arrays.
//
// The nav bar in body-00-shell.html is now auto-built from this
// list at boot. Loader dispatch (01-tab-switching.js) reads from it.
// The body/script asset arrays in index.html stay as-is for now --
// dynamic <script> loading with retry needs the flat list -- but a
// guard test asserts every TABS entry has a matching body file.
//
// Order below = visual order in the sidebar.
window.ARENA_TABS = [
  {name: "overview",  icon: "📊", label: "Overview",  onShow: () => refreshOverview()},
  {name: "workspace", icon: "🧭", label: "Workspace", onShow: () => loadWorkspace()},
  {name: "terminal",  icon: "💻", label: "Terminal"},
  {name: "memory",    icon: "🧠", label: "Memory",    onShow: () => loadMemory()},
  {name: "recall",    icon: "🔍", label: "Recall"},
  {name: "missions",  icon: "⭐", label: "Missions",  onShow: () => loadMissions()},
  {name: "browser",   icon: "🌐", label: "Browser"},
  {name: "reports",   icon: "📁", label: "Reports",   onShow: () => loadReports()},
  {name: "tasks",     icon: "📋", label: "Tasks",
                                    onShow: () => { loadTasks(); startTaskRefresh(); },
                                    onHide: () => stopTaskRefresh()},
  {name: "skills",    icon: "🧩", label: "Skills",    onShow: () => loadSkills()},
  {name: "hooks",     icon: "🪝", label: "Hooks",     onShow: () => loadHooks()},
  {name: "agents",    icon: "🤖", label: "Agents",    onShow: () => loadAgents()},
  {name: "control",   icon: "🛡️", label: "Control",   onShow: () => refreshControlPanel()},
  {name: "mobile",    icon: "📱", label: "Mobile",    onShow: () => refreshMobile()},
  {name: "live",      icon: "📈", label: "Live",
                                    onShow: () => startLiveCharts(),
                                    onHide: () => stopLiveCharts()},
  {name: "doctor",    icon: "🏥", label: "Doctor",    onShow: () => runDoctor()},
  {name: "audit",     icon: "📜", label: "Audit",     onShow: () => loadAudit()},
  {name: "settings",  icon: "⚙️", label: "Settings",  onShow: () => refreshSettings()},
];

// Public helper -- lookup by name.
window.arenaTabByName = function(name) {
  return window.ARENA_TABS.find(t => t.name === name) || null;
};
