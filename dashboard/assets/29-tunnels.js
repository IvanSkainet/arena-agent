// Dashboard: unified tunnels + ZeroTier controls.
//
// Uses the /v1/tunnels/* facade to display all providers at once and
// /v1/zerotier/* endpoints for network membership management.

async function tunnelsRefresh() {
  try {
    const r = await api("/v1/tunnels/status");
    if (!r || !r.ok) {
      setActiveEndpoint(null);
      return;
    }
    // Active endpoint header.
    setActiveEndpoint(r.active);

    // Per-provider rows.
    for (const p of (r.providers || [])) {
      if (p.provider === "tailscale") {
        setBadge("tsToggleStatus", p.active ? "ACTIVE" : (p.connected ? "connected" : "off"), p.active ? "good" : (p.connected ? "info" : "gray"));
        setLink("tsUrl", p.public_url);
      } else if (p.provider === "cloudflared") {
        const label = p.active ? "ACTIVE" : (p.installed ? "installed" : "not installed");
        setBadge("cfToggleStatus", label, p.active ? "good" : (p.installed ? "info" : "gray"));
        setLink("cfUrl", p.public_url);
      } else if (p.provider === "zerotier") {
        let label = "off";
        let cls = "gray";
        if (p.installed && p.active) { label = "ACTIVE"; cls = "good"; }
        else if (p.installed && p.connected) { label = "connected"; cls = "info"; }
        else if (p.installed) { label = "installed"; cls = "gray"; }
        else { label = "not installed"; cls = "gray"; }
        setBadge("ztToggleStatus", label, cls);
        const nodeEl = document.getElementById("ztNodeId");
        if (nodeEl) nodeEl.textContent = p.node_id ? `node ${p.node_id} · v${p.version || "?"}` : "";
        setLink("ztUrl", p.public_url);
        renderZtNetworks(p.networks || []);
        renderZtHint(p);
      }
    }
  } catch (e) {
    console.warn("[tunnels] refresh failed:", e);
  }
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

function renderZtNetworks(networks) {
  const el = document.getElementById("ztNetworksList");
  if (!el) return;
  if (!networks.length) {
    el.textContent = "(no networks joined)";
    return;
  }
  el.textContent = networks.map((n) => {
    const ips = (n.assignedAddresses || []).join(", ") || "no IP";
    return `${n.status.padEnd(4)}  ${n.nwid}  ${(n.name || "(unnamed)").padEnd(24)}  ${(n.type || "").padEnd(8)}  ${ips}`;
  }).join("\n");
}

function renderZtHint(zt) {
  const hint = document.getElementById("ztHint");
  if (!hint) return;
  if (!zt.installed) {
    hint.style.display = "";
    hint.textContent = "ZeroTier is not installed. See https://www.zerotier.com/download/";
  } else if (zt.hint) {
    hint.style.display = "";
    hint.textContent = zt.hint;
  } else {
    hint.style.display = "none";
    hint.textContent = "";
  }
}

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
    alert("Enter a ZeroTier network ID first.");
    return;
  }
  try {
    const r = await api(`/v1/zerotier/network/${action}`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({network_id: nwid}),
    });
    if (r && r.ok) {
      if (input) input.value = "";
      alert(`ZeroTier ${action} ok`);
    } else {
      alert(`ZeroTier ${action} failed: ${r?.error || "unknown"}`);
    }
  } catch (e) {
    alert(`ZeroTier ${action} failed: ${e.message || e}`);
  } finally {
    tunnelsRefresh();
  }
}

// Auto-refresh whenever the Settings tab becomes active.
document.addEventListener("DOMContentLoaded", () => {
  const settingsTab = document.querySelector('[data-tab="tab-settings"]');
  if (settingsTab) {
    settingsTab.addEventListener("click", () => setTimeout(tunnelsRefresh, 100));
  }
  // Initial pull.
  setTimeout(tunnelsRefresh, 500);
});
