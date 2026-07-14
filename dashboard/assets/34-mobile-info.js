// Mobile: sectioned device-info panel (v3.83.3).
//
// The v3.83.1 info panel dumped every field into one long two-column
// table. That was fine for glancing at the device but hard to skim
// when looking for one specific thing (e.g. "what's the battery
// temperature?"). This module rebuilds the panel as a small tab bar:
//   All (default) · Overview · Display · Hardware · Network ·
//   Storage · Security · Developer · Sensors
//
// Depends on globals from 30-mobile.js:
//   _mobileSelectedSerial, _mobileInfoCache, api(),
//   mobileShowError(), _fmtBackendError().

const MOBILE_INFO_SECTIONS = [
  {id: "all",       label: "All"},
  {id: "overview",  label: "Overview"},
  {id: "display",   label: "Display"},
  {id: "hardware",  label: "Hardware"},
  {id: "network",   label: "Network"},
  {id: "storage",   label: "Storage"},
  {id: "security",  label: "Security"},
  {id: "developer", label: "Developer"},
  {id: "sensors",   label: "Sensors"},
  {id: "others",    label: "Others"},
];

const _MOBILE_INFO_LS_KEY = "arena.mobile.info.section.v1";
let _mobileSensorsCache = null;
let _mobileSensorsLoading = false;

function _mobileInfoActiveSection() {
  try {
    const raw = localStorage.getItem(_MOBILE_INFO_LS_KEY);
    if (raw && MOBILE_INFO_SECTIONS.some((s) => s.id === raw)) return raw;
  } catch (_) {}
  return "all";
}

function _mobileInfoSaveSection(id) {
  try { localStorage.setItem(_MOBILE_INFO_LS_KEY, id); } catch (_) {}
}

// Public: switch section from a tab click.
function mobileInfoShowSection(id) {
  if (!MOBILE_INFO_SECTIONS.some((s) => s.id === id)) return;
  _mobileInfoSaveSection(id);
  mobileRenderInfoPanel();
  // Sensors are fetched lazily — the /sensors endpoint is heavier
  // (~500ms for `dumpsys sensorservice` parsing) so don't run it
  // unless the user actually opened that tab.
  if ((id === "sensors" || id === "all") && !_mobileSensorsCache && !_mobileSensorsLoading) {
    _mobileLoadSensors();
  }
}

async function _mobileLoadSensors() {
  if (!_mobileSelectedSerial) return;
  _mobileSensorsLoading = true;
  try {
    const r = await api(
      "/v1/mobile/" + encodeURIComponent(_mobileSelectedSerial)
      + "/sensors?events_per_sensor=1"
    );
    _mobileSensorsCache = r;
    mobileRenderInfoPanel();
  } catch (e) {
    console.warn("[mobile] sensors load failed:", e);
    _mobileSensorsCache = {ok: false, error: String(e && e.message || e)};
    mobileRenderInfoPanel();
  } finally {
    _mobileSensorsLoading = false;
  }
}

// Called when the user selects a different device — dumps the cached
// sensors so the new one gets its own fetch.
function mobileInfoResetCache() {
  _mobileSensorsCache = null;
  _mobileSensorsLoading = false;
}

// Full replacement for the v3.83.1 mobileRenderInfoPanel — reads the
// same _mobileInfoCache but rearranges the fields into sections.
function mobileRenderInfoPanel() {
  const el = document.getElementById("mobileInfoPanel");
  if (!el || !_mobileInfoCache) return;
  const i = _mobileInfoCache;
  const active = _mobileInfoActiveSection();

  // Build sections as arrays of [label, value] pairs so an "all" view
  // can concat + render them under section headings.
  const sections = {
    overview:  _mobileInfoSectionOverview(i),
    display:   _mobileInfoSectionDisplay(i),
    hardware:  _mobileInfoSectionHardware(i),
    network:   _mobileInfoSectionNetwork(i),
    storage:   _mobileInfoSectionStorage(i),
    security:  _mobileInfoSectionSecurity(i),
    developer: _mobileInfoSectionDeveloper(i),
    sensors:   _mobileInfoSectionSensors(_mobileSensorsCache),
    others:    _mobileInfoSectionOthers(i),
  };

  el.innerHTML = "";
  el.appendChild(_mobileInfoTabBar(active, sections));

  if (active === "all") {
    // Render every non-empty section with a heading, in a stable order.
    for (const s of MOBILE_INFO_SECTIONS) {
      if (s.id === "all") continue;
      const rows = sections[s.id];
      if (!rows || rows.length === 0) continue;
      el.appendChild(_mobileInfoSectionHeader(s.label));
      el.appendChild(_mobileInfoTable(rows));
    }
  } else {
    const rows = sections[active] || [];
    if (rows.length === 0) {
      const empty = document.createElement("div");
      empty.style.cssText = "padding:8px;color:#888;font-size:12px";
      empty.textContent = active === "sensors" && _mobileSensorsLoading
        ? "Loading sensor data (~1-2 s)…"
        : "No data for this section on this device.";
      el.appendChild(empty);
    } else {
      el.appendChild(_mobileInfoTable(rows));
    }
  }
}

function _mobileInfoTabBar(activeId, sections) {
  const bar = document.createElement("div");
  bar.style.cssText = "display:flex;flex-wrap:wrap;gap:2px;padding:6px 6px 8px 6px;border-bottom:1px solid rgba(128,128,128,.15);margin-bottom:6px";
  for (const s of MOBILE_INFO_SECTIONS) {
    const btn = document.createElement("button");
    btn.className = "sm";
    btn.style.cssText =
      "font-size:11px;padding:2px 8px;border-radius:4px;cursor:pointer;"
      + (s.id === activeId
        ? "background:#1c7ed6;color:#fff;border:1px solid #1c7ed6;"
        : "background:transparent;color:inherit;border:1px solid rgba(128,128,128,.3);");
    // Add a tiny counter suffix for non-empty sections so it's obvious
    // where the data actually is.
    const count = (sections[s.id] || []).length;
    btn.textContent = count > 0 && s.id !== "all"
      ? `${s.label} · ${count}`
      : s.label;
    btn.onclick = () => mobileInfoShowSection(s.id);
    bar.appendChild(btn);
  }
  return bar;
}

function _mobileInfoSectionHeader(label) {
  const h = document.createElement("div");
  h.style.cssText = "margin:8px 4px 2px 4px;font-size:11px;font-weight:600;color:#666;text-transform:uppercase;letter-spacing:0.5px";
  h.textContent = label;
  return h;
}

function _mobileInfoTable(rows) {
  const table = document.createElement("table");
  table.style.cssText = "width:100%;border-collapse:collapse;font-size:12px";
  for (const [k, v] of rows) {
    if (v === null || v === undefined || v === "") continue;
    const tr = document.createElement("tr");
    const tdK = document.createElement("td");
    tdK.style.cssText = "padding:3px 8px 3px 4px;color:#666;white-space:nowrap;vertical-align:top;width:120px";
    tdK.textContent = k;
    const tdV = document.createElement("td");
    tdV.style.cssText = "padding:3px 4px;word-break:break-word";
    tdV.className = "mono";
    tdV.textContent = String(v);
    tr.appendChild(tdK); tr.appendChild(tdV);
    table.appendChild(tr);
  }
  return table;
}

// ---------------------------------------------------------------------------
// Section builders. Each returns an array of [label, value] pairs.
// Values are omitted when the underlying probe returned nothing.
// ---------------------------------------------------------------------------

function _pair(label, value) {
  return (value === null || value === undefined || value === "")
    ? null : [label, value];
}
function _list(...pairs) {
  return pairs.filter(Boolean);
}

function _mobileInfoSectionOverview(i) {
  const name = [i.brand, i.manufacturer, i.model].filter(Boolean).join(" · ");
  const android = (i.android_version ? "Android " + i.android_version : "")
    + (i.android_sdk ? " · SDK " + i.android_sdk : "")
    + (i.android_security_patch ? " · patch " + i.android_security_patch : "");
  const power = i.power ? [
    typeof i.power.screen_on === "boolean" ? (i.power.screen_on ? "screen on" : "screen OFF") : null,
    i.power.wakefulness,
    i.power.charging === true ? "charging" : null,
    i.power.low_power_mode === true ? "low power" : null,
  ].filter(Boolean).join(" · ") : null;
  const battery = _mobileFormatBattery(i.battery);
  const uiMode = i.ui_mode ? [
    i.ui_mode.night_mode ? "theme: " + i.ui_mode.night_mode : null,
    typeof i.ui_mode.airplane_mode === "boolean" ? "airplane: " + (i.ui_mode.airplane_mode ? "on" : "off") : null,
    i.ui_mode.ringer_mode ? "ringer: " + i.ui_mode.ringer_mode : null,
    i.ui_mode.screen_off_timeout_sec ? "timeout: " + i.ui_mode.screen_off_timeout_sec + "s" : null,
    typeof i.ui_mode.auto_rotate === "boolean" ? "auto-rotate: " + (i.ui_mode.auto_rotate ? "on" : "off") : null,
  ].filter(Boolean).join(" · ") : null;
  return _list(
    _pair("Device", name),
    _pair("Codename", i.device),
    _pair("Android", android),
    _pair("HyperOS", i.hyperos_version || i.miui_version),
    _pair("Power", power),
    _pair("Battery", battery),
    _pair("UI mode", uiMode),
    _pair("Uptime", i.uptime),
    _pair("Foreground", i.foreground_activity),
  );
}

function _mobileInfoSectionDisplay(i) {
  const screen = [
    i.screen_size_physical ? i.screen_size_physical + " physical" : null,
    (i.screen_size_current && i.screen_size_current !== i.screen_size_physical)
      ? i.screen_size_current + " current" : null,
    i.orientation
      ? i.orientation + (typeof i.rotation === "number" ? " (rot " + i.rotation + ")" : "")
      : null,
    (i.density_override || i.density_physical)
      ? (i.density_override || i.density_physical) + " dpi" : null,
  ].filter(Boolean).join(" · ");
  const d = i.display || {};
  const refresh = [
    d.active_refresh_rate ? d.active_refresh_rate + " Hz" : null,
    Array.isArray(d.supported_refresh_rates)
      ? "(" + d.supported_refresh_rates.join("/") + " Hz)" : null,
  ].filter(Boolean).join(" ");
  return _list(
    _pair("Screen", screen),
    _pair("Refresh rate", refresh),
    _pair("HDR types", Array.isArray(d.hdr_types) ? d.hdr_types.join(",") : null),
    _pair("Rounded corner", d.rounded_corner_radius_px
      ? d.rounded_corner_radius_px + " px" : null),
    _pair("Locale", (i.locale_current || i.locale || "")
      + (i.timezone ? " · " + i.timezone : "")),
  );
}

function _mobileInfoSectionHardware(i) {
  return _list(
    _pair("CPU ABI", i.cpu_abi),
    _pair("CPU ABI list", i.cpu_abi_list),
    _pair("Hardware", i.hardware),
    _pair("Board", i.board),
    _pair("Bootloader", i.bootloader),
    _pair("Serial (getprop)", i.serialno),
    _pair("Build ID", i.build_id),
    _pair("Build date", i.build_date),
    _pair("Build type", i.build_type),
    _pair("Build tags", i.build_tags),
    _pair("Fingerprint", i.fingerprint),
    _pair("Kernel",
      i.kernel && i.kernel.length > 140 ? i.kernel.slice(0, 137) + "…" : i.kernel),
    _pair("RAM", i.memory && i.memory.memtotal
      ? (i.memory.memavailable
        ? i.memory.memavailable + " avail / " + i.memory.memtotal
        : i.memory.memtotal)
      : null),
    _pair("Swap", i.memory && i.memory.swaptotal
      ? (i.memory.swapfree
        ? i.memory.swapfree + " free / " + i.memory.swaptotal
        : i.memory.swaptotal)
      : null),
  );
}

function _mobileInfoSectionNetwork(i) {
  const n = i.network || {};
  const oper = [
    n.operator_alpha,
    n.operator_iso ? "(" + n.operator_iso + ")" : null,
  ].filter(Boolean).join(" ");
  return _list(
    _pair("Operator", oper || null),
    _pair("Mobile type", n.mobile_type),
    _pair("SIM state", n.sim_state),
    _pair("Mobile data", typeof n.data_enabled === "boolean"
      ? (n.data_enabled ? "enabled" : "disabled") : null),
    _pair("Roaming", n.roaming === true ? "yes" : null),
    _pair("Wi-Fi state", i.wifi && i.wifi.state),
    _pair("Wi-Fi IPv4", i.wifi && i.wifi.ipv4),
    _pair("Wi-Fi info", i.wifi && i.wifi.info_line
      ? (i.wifi.info_line.length > 200 ? i.wifi.info_line.slice(0, 197) + "…" : i.wifi.info_line)
      : null),
  );
}

function _mobileInfoSectionStorage(i) {
  const rows = [];
  if (Array.isArray(i.storage) && i.storage.length) {
    for (const s of i.storage) {
      rows.push([s.mount || s.filesystem, (s.avail || "?") + " free / " + (s.size || "?")
        + " (" + (s.use_pct || "?") + " used, fs " + (s.filesystem || "?") + ")"]);
    }
  }
  return rows;
}

function _mobileInfoSectionSecurity(i) {
  const dev = i.developer || {};
  return _list(
    _pair("SELinux", i.selinux),
    _pair("Verified boot", i.verified_boot),
    _pair("FS encryption", i.encryption
      ? (i.encryption.state || "?") + (i.encryption.type ? " (" + i.encryption.type + ")" : "")
      : null),
    _pair("ADB enabled", dev.adb_enabled === true ? "yes" : (dev.adb_enabled === false ? "no" : null)),
    _pair("ADB over Wi-Fi", dev.adb_wifi_enabled === true ? "yes" : (dev.adb_wifi_enabled === false ? "no" : null)),
    _pair("Unknown sources", dev.install_from_unknown_sources === true ? "yes" : (dev.install_from_unknown_sources === false ? "no" : null)),
    _pair("Keyboard IME", i.ime && i.ime.current),
    _pair("Keyboards enabled", i.ime && i.ime.enabled_count !== undefined
      ? i.ime.enabled_count + " / " + (i.ime.available_count || "?") : null),
  );
}

function _mobileInfoSectionDeveloper(i) {
  const dev = i.developer || {};
  return _list(
    _pair("Developer options", dev.developer_options_enabled === true ? "on" : null),
    _pair("Stay awake charging", dev.stay_awake_while_charging),
    _pair("USB debug security", dev.usb_debug_security_settings),
    _pair("User apps", i.packages_count && i.packages_count.user_installed),
    _pair("System apps", i.packages_count && i.packages_count.system),
    _pair("Disabled apps", i.packages_count && i.packages_count.disabled),
  );
}

function _mobileInfoSectionSensors(sensorsResp) {
  if (!sensorsResp) {
    return []; // triggers "loading…" placeholder in the outer render
  }
  if (!sensorsResp.ok) {
    return [["Error", sensorsResp.error || "sensor probe failed"]];
  }
  const rows = [];
  const count = sensorsResp.sensor_count || (sensorsResp.sensors || []).length;
  rows.push(["Sensor count", String(count)]);

  // Group and prefer live readings from `recent_events`. Show only
  // sensors that actually reported values, sorted by type.
  const recent = sensorsResp.recent_events || {};
  const named_readings = [];
  for (const [name, entry] of Object.entries(recent)) {
    const last = (entry.events || [])[entry.events.length - 1];
    if (!last) continue;
    let display;
    if (last.named && Object.keys(last.named).length) {
      display = Object.entries(last.named)
        .map(([k, v]) => `${k}=${_fmtNum(v)}`).join(", ");
    } else {
      display = last.values.map(_fmtNum).join(", ");
    }
    named_readings.push([
      (entry.type || "?") + " · " + name,
      display + "  @" + (last.wall || "?"),
    ]);
  }
  named_readings.sort();
  for (const r of named_readings) rows.push(r);

  // Also list all sensors, even ones without recent events, so the
  // count is accountable.
  const seen_names = new Set(Object.keys(recent).map((k) => k.toLowerCase()));
  const inactive = [];
  for (const s of (sensorsResp.sensors || [])) {
    if (seen_names.has((s.name || "").toLowerCase())) continue;
    inactive.push([
      (s.type || "?") + " · " + s.name,
      "no recent events"
        + (s.vendor ? " · " + s.vendor : "")
        + (s.max_rate_hz ? " · max " + s.max_rate_hz + " Hz" : ""),
    ]);
  }
  inactive.sort();
  for (const r of inactive.slice(0, 60)) rows.push(r);
  if (inactive.length > 60) {
    rows.push(["…", "+" + (inactive.length - 60) + " more sensors without live values"]);
  }
  return rows;
}

function _fmtNum(v) {
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(Math.abs(v) < 10 ? 3 : 1);
}

function _mobileFormatBattery(b) {
  if (!b) return null;
  const parts = [];
  if (b.level && b.scale) {
    parts.push(Math.round(100 * parseInt(b.level, 10) / parseInt(b.scale, 10)) + "%");
  } else if (b.level) parts.push(b.level + "%");
  if (b.temperature) {
    const t = parseInt(b.temperature, 10);
    if (!Number.isNaN(t)) parts.push((t / 10).toFixed(1) + "°C");
  }
  if (b.voltage) parts.push(b.voltage + " mV");
  if (b.health) parts.push("health: " + b.health);
  if (b.technology) parts.push(b.technology);
  if (b.ac_powered === "true") parts.push("AC");
  else if (b.usb_powered === "true") parts.push("USB");
  else if (b.wireless_powered === "true") parts.push("wireless");
  return parts.join(" · ");
}


// Others: catch-all for the raw ro./persist./dalvik.vm./sys.usb.*
// properties that survived the PII filter on the bridge side. Rendered
// as a sorted table so the same device produces the same order across
// refreshes.
function _mobileInfoSectionOthers(i) {
  if (!i.others || typeof i.others !== "object") return [];
  const rows = [];
  for (const key of Object.keys(i.others)) {
    rows.push([key, i.others[key]]);
  }
  return rows;
}
