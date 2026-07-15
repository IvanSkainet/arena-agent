// ===== Full Inventory =====
// Three view modes:
//   * cards    -- rich HTML cards from 03b-hw-cards.js (same as Doctor)
//   * rendered -- Markdown-to-HTML via renderMarkdown() from 03-helpers.js
//   * raw      -- plain monospace text, ideal for copy/paste
// Default is 'cards' -- gives the operator (and any agent screenshot)
// the same look as the Doctor Hardware tab.
window._invViewMode = "cards";
window._invRawText = "";
window._invRaw = null;   // parsed JSON inventory (used by cards mode)

function _invRenderCurrent() {
  const out = document.getElementById("invOutput");
  if (!out) return;
  const text = window._invRawText || "";
  const inv = window._invRaw || {};

  if (window._invViewMode === "raw") {
    out.textContent = text;
    out.style.whiteSpace = "pre-wrap";
    return;
  }
  if (window._invViewMode === "rendered") {
    // renderMarkdown() from 03-helpers.js. Emits HTML with \n between
    // plain lines instead of <br>, so the container preserves whitespace.
    out.style.whiteSpace = "pre-wrap";
    out.innerHTML = renderMarkdown(text);
    return;
  }
  // 'cards' mode -- same visual language as Doctor Hardware tab.
  // Uses the shared _hwRender* renderers in 03b-hw-cards.js.
  out.style.whiteSpace = "normal";
  if (typeof _hwCard !== "function") {
    // 03b failed to load somehow; fall through to raw text.
    out.textContent = text;
    return;
  }
  const cards = _invBuildCards(inv);
  if (!cards) {
    out.textContent = text || "(no data)";
    return;
  }
  out.innerHTML =
    '<div style="display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(280px,1fr))">'
    + cards + "</div>";
}

// Which sections belong on the Full Inventory card view. Order
// matches the Doctor tab so switching between the two feels
// consistent.
function _invBuildCards(inv) {
  if (!inv || typeof inv !== "object") return "";
  const cards = [];

  // Reuse Doctor renderers. Each is defensive: if the section is
  // missing it returns "". `_hwRender*` are declared in
  // 03b-hw-cards.js, loaded before us.
  const wants = _invWantedSet();
  const push = (name, html) => {
    if (!html) return;
    if (wants && !wants.has(name)) return;
    cards.push(html);
  };

  push("identity",         _hwRenderOS ? _hwRenderOS(inv.os) : "");
  push("boot_time",        _hwRenderBoot ? _hwRenderBoot(inv.boot_time) : "");
  push("cpu",              _hwRenderCPU && _hwRenderCPU(inv.cpu));
  push("memory",           _hwRenderMemory && _hwRenderMemory(inv.memory));
  push("gpu",              _hwRenderGPU && _hwRenderGPU(
                            (inv.gpu && inv.gpu.gpus && inv.gpu.gpus[0]) || null,
                            (inv.gpu && inv.gpu.gpus) || []));
  push("disks",            _hwRenderDisks && _hwRenderDisks(inv.disks));
  push("thermal_detail",   _hwRenderThermal && _hwRenderThermal(inv.thermal, inv.thermal_detail));
  push("fans",             _hwRenderFans && _hwRenderFans(inv.fans));
  push("battery",          _hwRenderBattery && _hwRenderBattery(inv.battery));
  push("disk_smart",       _hwRenderSmart && _hwRenderSmart(inv.disk_smart));
  push("audio",            _hwRenderAudio && _hwRenderAudio(inv.audio));
  push("motherboard",      _hwRenderMotherboard && _hwRenderMotherboard(
                            (inv.motherboard && inv.motherboard.motherboard) || null,
                            (inv.motherboard && inv.motherboard.bios) || null));
  push("network",          _hwRenderNetwork && _hwRenderNetwork(inv.network));
  push("top_processes",    _hwRenderTopProcesses && _hwRenderTopProcesses(inv.top_processes));
  push("listening_ports",  _hwRenderListeningPorts && _hwRenderListeningPorts(inv.listening_ports));
  push("systemd_failed",   _hwRenderSystemdFailed && _hwRenderSystemdFailed(inv.systemd_failed));
  push("containers",       _hwRenderContainers && _hwRenderContainers(inv.containers));
  push("systemd_timers",   _hwRenderSystemdTimers && _hwRenderSystemdTimers(inv.systemd_timers));
  push("network_io",       _hwRenderNetworkIO && _hwRenderNetworkIO(inv.network_io));
  push("updates_available",_hwRenderUpdates && _hwRenderUpdates(inv.updates_available));
  push("logged_users",     _hwRenderLoggedUsers && _hwRenderLoggedUsers(inv.logged_users));
  push("cpu_vulnerabilities", _hwRenderCpuVulns && _hwRenderCpuVulns(inv.cpu_vulnerabilities));
  // v3.88.4 agent context probes
  push("virtualization",   _hwRenderVirt && _hwRenderVirt(inv.virtualization));
  push("time_sync",        _hwRenderTimeSync && _hwRenderTimeSync(inv.time_sync));
  push("firewall_status",  _hwRenderFirewall && _hwRenderFirewall(inv.firewall_status));
  push("dns_resolvers",    _hwRenderDns && _hwRenderDns(inv.dns_resolvers));
  push("env_secret_names", _hwRenderEnvSecrets && _hwRenderEnvSecrets(inv.env_secret_names));
  push("python_venvs",     _hwRenderVenvs && _hwRenderVenvs(inv.python_venvs));
  push("git_repos",        _hwRenderGitRepos && _hwRenderGitRepos(inv.git_repos));
  push("crontab_entries",  _hwRenderCrontab && _hwRenderCrontab(inv.crontab_entries));
  push("dmesg_errors",     _hwRenderKernelErrors && _hwRenderKernelErrors(inv.dmesg_errors));
  push("journal_errors",   _hwRenderJournalErrors && _hwRenderJournalErrors(inv.journal_errors));
  push("services",         _hwRenderServices && _hwRenderServices(inv.services));
  push("kernel_modules",   _hwRenderKernelModules && _hwRenderKernelModules(inv.kernel_modules));
  push("runtimes",         _hwRenderExtra && "");  // covered by _hwRenderExtra below
  push("packages",         "");
  // Package managers / runtimes / browsers -- render once via _hwRenderExtra
  cards.push(_hwRenderExtra ? _hwRenderExtra(inv) : "");

  return cards.filter(Boolean).join("");
}

function _invWantedSet() {
  // If "all" is checked (empty value), return null = show everything.
  const boxes = Array.from(document.querySelectorAll(".inv-sec:checked"));
  if (!boxes.length) return null;
  if (boxes.some(b => b.value === "")) return null;
  return new Set(boxes.map(b => b.value));
}

function toggleInvViewMode() {
  const modes = ["cards", "rendered", "raw"];
  const idx = modes.indexOf(window._invViewMode);
  window._invViewMode = modes[(idx + 1) % modes.length];
  const btn = document.getElementById("invViewModeBtn");
  if (btn) {
    const labels = {cards: "🎨 Cards", rendered: "📖 Rendered", raw: "📝 Raw"};
    btn.textContent = labels[window._invViewMode];
  }
  _invRenderCurrent();
}

function toggleFullInventory() {
  const card = document.getElementById("fullInventoryCard");
  if (!card) return;
  const btn = document.getElementById("invToggleBtn");
  if (card.style.display === "none") {
    card.style.display = "";
    if (btn) btn.textContent = "🙈 Hide Inventory";
    card.scrollIntoView({behavior: "smooth", block: "start"});
    const out = document.getElementById("invOutput");
    if (out && out.textContent.startsWith('Click "Load')) loadFullInventory();
  } else {
    card.style.display = "none";
    if (btn) btn.textContent = "📋 Full Inventory";
  }
}

async function loadFullInventory() {
  const out = document.getElementById("invOutput");
  const status = document.getElementById("invStatus");
  if (!out) return;
  out.textContent = "Loading...";
  if (status) { status.textContent = "loading"; status.className = "badge warn"; }
  const t0 = Date.now();

  const sections = Array.from(document.querySelectorAll(".inv-sec:checked"))
                        .map(c => c.value).filter(v => v);
  const allChecked = Array.from(document.querySelectorAll(".inv-sec:checked"))
                          .some(c => c.value === "");
  let url = "/v1/inventory?format=json&timeout=45";
  if (!allChecked && sections.length === 1) {
    url += "&section=" + encodeURIComponent(sections[0]);
  }

  try {
    const r = await api(url);
    const dt = ((Date.now() - t0) / 1000).toFixed(1);
    if (!r.ok) {
      out.textContent = "Error: " + (r.error || JSON.stringify(r));
      if (status) { status.textContent = "error"; status.className = "badge red"; }
      return;
    }
    const inv = r.inventory || {};
    const text = formatInventoryText(inv, allChecked ? null : sections);
    window._invRawText = text;
    window._invRaw = inv;
    _invRenderCurrent();
    if (status) { status.textContent = `loaded in ${dt}s`; status.className = "badge ok"; }
  } catch (e) {
    out.textContent = "Network error: " + (e.message || e);
    if (status) { status.textContent = "network error"; status.className = "badge red"; }
  }
}
