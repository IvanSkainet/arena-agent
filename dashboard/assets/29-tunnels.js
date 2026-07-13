// Dashboard: unified tunnels + ZeroTier controls.
//
// Uses the /v1/tunnels/* facade to display all providers side-by-side plus
// the /v1/zerotier/* endpoints for network membership management. Wraps
// refreshSettings() so a manual refresh of the Settings tab also pulls the
// latest tunnel state — and starts a light auto-refresh loop only while
// the Settings tab is active.

(function () {
  // --- Wrap refreshSettings so the Tunnels card refreshes with the tab. ---
  const _origRefreshSettings = typeof refreshSettings === "function" ? refreshSettings : null;
  window.refreshSettings = async function () {
    if (_origRefreshSettings) {
      try { await _origRefreshSettings.apply(this, arguments); }
      catch (e) { console.warn("[tunnels] refreshSettings pre-hook failed:", e); }
    }
    tunnelsRefresh();
  };

  // --- Auto-refresh loop, only while Settings tab is visible. ---
  let _tunnelsTimer = null;
  function startTunnelsAutoRefresh() {
    stopTunnelsAutoRefresh();
    _tunnelsTimer = setInterval(() => {
      const t = document.getElementById("tab-settings");
      if (!t || !t.classList.contains("active")) { stopTunnelsAutoRefresh(); return; }
      tunnelsRefresh();
    }, 5000);
  }
  function stopTunnelsAutoRefresh() {
    if (_tunnelsTimer) { clearInterval(_tunnelsTimer); _tunnelsTimer = null; }
  }

  // Kick a refresh + start auto-loop as soon as Settings tab becomes active.
  document.addEventListener("click", (ev) => {
    const link = ev.target.closest && ev.target.closest('.sidebar nav a[data-tab="settings"]');
    if (!link) return;
    // refreshSettings() is already called by 01-tab-switching.js; we piggyback
    // on the wrapper above. Just start the auto-refresh loop here.
    setTimeout(startTunnelsAutoRefresh, 200);
  });

  // If the Settings tab is already the active one at page load (dashboard
  // remembers last tab), do the initial refresh + start the loop.
  document.addEventListener("DOMContentLoaded", () => {
    const t = document.getElementById("tab-settings");
    if (t && t.classList.contains("active")) {
      tunnelsRefresh();
      startTunnelsAutoRefresh();
    }
  });

  // If the script itself loaded AFTER DOMContentLoaded (common for the last
  // scripts in the list), run the check immediately as well.
  if (document.readyState !== "loading") {
    const t = document.getElementById("tab-settings");
    if (t && t.classList.contains("active")) {
      tunnelsRefresh();
      startTunnelsAutoRefresh();
    }
  }
})();

// ---------------------------------------------------------------------------
// Main refresh
// ---------------------------------------------------------------------------
async function tunnelsRefresh() {
  try {
    const r = await api("/v1/tunnels/status");
    if (!r || !r.ok) {
      setActiveEndpoint(null);
      return;
    }
    setActiveEndpoint(r.active);

    for (const p of (r.providers || [])) {
      if (p.provider === "tailscale") renderTailscale(p);
      else if (p.provider === "cloudflared") renderCloudflared(p);
      else if (p.provider === "zerotier") renderZerotier(p);
    }
  } catch (e) {
    console.warn("[tunnels] refresh failed:", e);
  }
}

function renderTailscale(p) {
  const label = p.active ? "ACTIVE" : (p.connected ? "connected" : (p.installed ? "installed" : "not installed"));
  const cls = p.active ? "good" : (p.connected ? "info" : "gray");
  setBadge("tsToggleStatus", label, cls);
  setLink("tsUrl", p.public_url);
}

function renderCloudflared(p) {
  let label, cls;
  if (p.active) { label = "ACTIVE"; cls = "good"; }
  else if (p.installed) { label = "installed"; cls = "info"; }
  else { label = "not installed"; cls = "gray"; }
  setBadge("cfToggleStatus", label, cls);
  setLink("cfUrl", p.public_url);
}

function renderZerotier(p) {
  let label, cls;
  if (!p.installed) { label = "NOT INSTALLED"; cls = "gray"; }
  else if (p.active) { label = "ACTIVE"; cls = "good"; }
  else if (p.connected) { label = "connected"; cls = "info"; }
  else { label = "installed"; cls = "gray"; }
  setBadge("ztToggleStatus", label, cls);

  const nodeEl = document.getElementById("ztNodeId");
  if (nodeEl) {
    nodeEl.textContent = p.node_id
      ? `node ${p.node_id} · v${p.version || "?"}`
      : (p.installed ? "not connected" : "");
  }

  setLink("ztUrl", p.public_url);
  renderZtNetworks(p.networks || [], p);
  renderZtOnboarding(p);
}

function setActiveEndpoint(active) {
  const badge = document.getElementById("tunActiveProvider");
  const link = document.getElementById("tunActiveUrl");
  if (!badge || !link) return;
  if (!active || !active.public_url) {
    badge.className = "badge gray";
    badge.textContent = "none";
    link.textContent = "—";
    link.removeAttribute("href");
    return;
  }
  badge.className = "badge good";
  badge.textContent = active.provider;
  link.textContent = active.public_url;
  link.href = active.public_url;
}

function setBadge(id, text, cls) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = "badge " + (cls || "gray");
}

function setLink(id, url) {
  const el = document.getElementById(id);
  if (!el) return;
  if (url) {
    el.href = url;
    el.textContent = url;
    el.style.display = "";
  } else {
    el.style.display = "none";
    el.removeAttribute("href");
  }
}

function renderZtNetworks(networks, provider) {
  const el = document.getElementById("ztNetworksList");
  if (!el) return;
  if (!provider.installed) {
    el.textContent = "(ZeroTier is not installed — see the onboarding tip below)";
    return;
  }
  if (!networks.length) {
    el.textContent = "(no networks joined — paste a network ID below and click Join)";
    return;
  }
  el.textContent = networks.map((n) => {
    const ips = (n.assignedAddresses || []).join(", ") || "no IP";
    const name = (n.name || "(unnamed)").padEnd(24);
    const type = (n.type || "").padEnd(8);
    return `${n.status.padEnd(4)}  ${n.nwid}  ${name}  ${type}  ${ips}`;
  }).join("\n");
}

function renderZtOnboarding(p) {
  const hint = document.getElementById("ztHint");
  if (!hint) return;
  const parts = [];
  if (!p.installed) {
    parts.push(
      "ZeroTier is not installed. Install it, then reload this page:\n"
      + "  Windows: winget install ZeroTier.ZeroTierOne\n"
      + "  macOS:   brew install --cask zerotier-one\n"
      + "  Linux:   sudo pacman -S zerotier-one  (or your distro's equivalent)\n"
      + "Docs: https://www.zerotier.com/download/"
    );
  } else if (!(p.networks || []).length) {
    parts.push(
      "ZeroTier is installed and running. To use it as a backup remote provider:\n"
      + "  1. Create a free network at https://central.zerotier.com (16-char nwid).\n"
      + "     (If you have older networks made before Dec 2025, log in via https://my.zerotier.com — legacy site.)\n"
      + "  2. Paste that nwid into the input above and click Join.\n"
      + "  3. Authorize this node on the ZeroTier Central dashboard.\n"
      + "  4. Once authorized, this Bridge will get a ZT IP and appear as an available provider."
    );
  } else if (p.hint) {
    parts.push(p.hint);
  }
  if (parts.length) {
    hint.style.display = "";
    hint.textContent = parts.join("\n\n");
  } else {
    hint.style.display = "none";
    hint.textContent = "";
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function tunnelsStartAll() {
  try {
    const r = await api("/v1/tunnels/start", {method: "POST"});
    if (r && r.ok && r.active) {
      alert(`Active endpoint: ${r.active.provider} → ${r.active.public_url}`);
    } else {
      alert("No provider became healthy. Check /v1/tunnels/status for details.");
    }
  } catch (e) {
    alert("tunnels/start failed: " + (e.message || e));
  } finally {
    tunnelsRefresh();
  }
}

async function tunnelsStopAll() {
  if (!confirm("Stop ALL tunnels (Tailscale funnel + Cloudflared)? ZeroTier membership is preserved.")) return;
  try {
    await api("/v1/tunnels/stop", {method: "POST"});
  } catch (e) {
    alert("tunnels/stop failed: " + (e.message || e));
  } finally {
    tunnelsRefresh();
  }
}

async function ztNetworkAction(action) {
  const input = document.getElementById("ztNwid");
  const nwid = (input?.value || "").trim();
  if ((action === "join" || action === "leave") && !nwid) {
    alert("Enter a 16-character ZeroTier network ID first.");
    return;
  }
  if (nwid && !/^[0-9a-fA-F]{16}$/.test(nwid)) {
    alert("Network ID must be exactly 16 hex characters (get one at https://central.zerotier.com).");
    return;
  }
  try {
    // NB: DO NOT pass `headers` here — the api() helper spreads opts into
    // `{headers, ...opts}` and any headers key would clobber the default
    // Authorization Bearer header. Pass raw body instead.
    const r = await api(`/v1/zerotier/network/${action}`, {
      method: "POST",
      body: JSON.stringify({network_id: nwid}),
    });
    if (r && r.ok) {
      if (input) input.value = "";
      alert(`ZeroTier ${action} ok`);
    } else {
      alert(`ZeroTier ${action} failed: ${(r && (r.error || r.stderr)) || "unknown"}`);
    }
  } catch (e) {
    alert(`ZeroTier ${action} failed: ${e.message || e}`);
  } finally {
    tunnelsRefresh();
  }
}
