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
  // v4.60.0: swap 🪝 (Emoji 14.0, missing on Windows 10 LTSC 2021 base Segoe UI Emoji) -> 🎣 (Emoji 3.0, universal).
  {name: "hooks",     icon: "🎣", label: "Hooks",     onShow: () => loadHooks()},
  {name: "agents",    icon: "🤖", label: "Agents",    onShow: () => loadAgents()},
  {name: "control",   icon: "🛡️", label: "Control",   onShow: () => refreshControlPanel()},
  {name: "mobile",    icon: "📱", label: "Mobile",    onShow: () => refreshMobile()},
  {name: "live",      icon: "📈", label: "Live",
                                    onShow: () => startLiveCharts(),
                                    onHide: () => stopLiveCharts()},
  {name: "zerotier",  icon: "🌐", label: "ZeroTier", onShow: () => refreshZerotierCentral()},
  {name: "doctor",    icon: "🏥", label: "Doctor",    onShow: () => runDoctor()},
  {name: "audit",     icon: "📜", label: "Audit",     onShow: () => loadAudit()},
  {name: "transports",icon: "🔌", label: "Transports",onShow: () => loadTransports()},
  // v4.95.0: external MCP servers monitor.
  {name: "mcp",       icon: "🔗", label: "MCP",       onShow: () => loadMcp()},
  {name: "proposals", icon: "📝", label: "Proposals", onShow: () => loadProposals()},
  // v4.166.0: operator <-> agent mailbox. onHide stops the poll timer so a
  // background tab does not keep hitting the bridge every 4s.
  // 24-relay.js may not have loaded yet when this tab is clicked -- the
  // dispatcher would then swallow a ReferenceError into console.warn and
  // the poll timer would silently never start. Observed: clicking 2.0s
  // after boot left the timer null, 2.5s set it. Retry briefly instead of
  // racing, and give up loudly rather than pretending it worked.
  {name: "relay",     icon: "✉️", label: "Relay",
                                    onShow: () => window.arenaWhenReady(
                                      "startRelay", () => startRelay()),
                                    onHide: () => {
                                      if (typeof stopRelay === "function") stopRelay();
                                    }},
  {name: "settings",  icon: "⚙️", label: "Settings",  onShow: () => refreshSettings()},
];


// Call `fn` once `name` exists in global scope. Scripts are injected
// dynamically with retry (see index.html), so a tab can be clicked before
// its module has arrived. Polls briefly, then reports rather than failing
// silently -- a dead tab with a clean console is the worst outcome.
window.arenaWhenReady = function (name, fn, tries) {
  tries = tries == null ? 40 : tries;   // 40 x 50ms = 2s
  if (typeof window[name] === "function") { fn(); return; }
  if (tries <= 0) {
    console.warn("[arena] " + name + " never loaded; tab will not refresh");
    return;
  }
  setTimeout(() => window.arenaWhenReady(name, fn, tries - 1), 50);
};

// Public helper -- lookup by name.
window.arenaTabByName = function(name) {
  return window.ARENA_TABS.find(t => t.name === name) || null;
};
