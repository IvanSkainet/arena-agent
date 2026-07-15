// Doctor tab: hardware inventory loader. All card renderers live
// in 03b-hw-cards.js so both the Doctor tab and the Full Inventory
// card (22-full-inventory-loader.js) can share the same visuals.
async function doctorLoadHardware() {
  const target = _hwEl("hwCards");
  const rawEl = _hwEl("hwRawJson");
  const timeEl = _hwEl("hwGeneratedAt");
  if (target) target.innerHTML = '<div style="color:var(--text3);font-size:12px">Loading hardware inventory…</div>';
  try {
    const r = await api("/v1/hardware");
    if (!r || r.ok !== true) {
      target.innerHTML = '<div style="color:var(--red)">Hardware fetch failed: ' + _hwEsc((r && r.error) || "unknown") + '</div>';
      return;
    }
    const hw = r.hardware || {};
    if (timeEl && hw.generated_at) {
      timeEl.textContent = "collected " + new Date(hw.generated_at).toLocaleString();
    }
    const cards = [
      _hwRenderOS(hw.os),
      _hwRenderBoot(hw.boot_time),
      _hwRenderCPU(hw.cpu),
      _hwRenderMemory(hw.memory),
      _hwRenderGPU(hw.gpu, hw.gpus),
      _hwRenderDisks(hw.disks),
      _hwRenderThermal(hw.thermal, hw.thermal_detail),
      _hwRenderFans(hw.fans),
      _hwRenderBattery(hw.battery),
      _hwRenderSmart(hw.disk_smart),
      _hwRenderAudio(hw.audio),
      _hwRenderMotherboard(hw.motherboard, hw.bios),
      _hwRenderNetwork(hw.network),
      _hwRenderTopProcesses(hw.top_processes),
      _hwRenderListeningPorts(hw.listening_ports),
      _hwRenderSystemdFailed(hw.systemd_failed),
      _hwRenderServices(hw.services),
      _hwRenderExtra(hw),
    ].filter(Boolean);
    if (!cards.length) {
      target.innerHTML = '<div style="color:var(--warning-text)">Backend returned empty hardware payload.</div>';
    } else {
      target.innerHTML = cards.join("");
    }
    if (rawEl) rawEl.textContent = JSON.stringify(r, null, 2);
  } catch (e) {
    target.innerHTML = '<div style="color:var(--red)">Hardware fetch failed: ' + _hwEsc(e && e.message || e) + '</div>';
  }
}

// Auto-run once when the Doctor tab first becomes visible so the
// operator doesn't have to hit Refresh every load. We watch the tab
// switcher for a change; 01-tab-switching.js fires custom events on
// activation, but as a safety net we ALSO fire on the very first
// tick after DOMContentLoaded if #tab-doctor is currently visible.
(function () {
  let ran = false;
  function _once() {
    if (ran) return;
    const t = document.getElementById("tab-doctor");
    if (t && t.style.display !== "none") {
      ran = true;
      try { doctorLoadHardware(); } catch (_) {}
    }
  }
  document.addEventListener("click", (ev) => {
    if (!ev || !ev.target) return;
    const target = ev.target.closest && ev.target.closest('[onclick*="doctor" i], [onclick*="Doctor" i], .tab-btn');
    if (target) setTimeout(_once, 50);
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setTimeout(_once, 500), {once: true});
  } else {
    setTimeout(_once, 500);
  }
})();
