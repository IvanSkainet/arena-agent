// ===== ZEROTIER CENTRAL (v3.96.0) =====
//
// Full management surface for https://api.zerotier.com/api/v1/.
// The Central API token is server-side (env ZEROTIER_CENTRAL_TOKEN
// or ~/.zerotier-central-token) — this UI never sees or transmits
// it directly; it just proxies through Bridge endpoints under
// /v1/zerotier/central/*.

(function () {
  let selectedNetworkId = null;

  window.refreshZerotierCentral = async function () {
    await Promise.all([_loadStatus(), _loadNetworks()]);
  };

  async function _loadStatus() {
    const el = document.getElementById("ztcStatus");
    if (!el) return;
    el.innerHTML = '<span class="muted">checking token…</span>';
    try {
      const r = await api("/v1/zerotier/central/status");
      if (r.ok) {
        el.innerHTML =
          '<span class="badge ok">Central OK</span> ' +
          '<span class="muted">token: ' + esc(r.token_source || "?") + '</span>';
      } else if (r.central === false) {
        el.innerHTML =
          '<span class="badge warn">Token missing</span> ' +
          '<span class="muted">' + esc(r.hint || r.reason || "") + '</span>';
      } else {
        el.innerHTML =
          '<span class="badge fail">Central error</span> ' +
          '<span class="muted">' + esc(r.error || "unknown") + '</span>';
      }
    } catch (e) {
      el.innerHTML = '<span class="badge fail">Network error</span> ' + esc(String(e));
    }
  }

  async function _loadNetworks() {
    const box = document.getElementById("ztcNetworks");
    if (!box) return;
    box.innerHTML = '<span class="muted">loading…</span>';
    try {
      const r = await api("/v1/zerotier/central/networks");
      if (!r.ok) {
        box.innerHTML = '<div class="error-box"><div class="error-title">' +
                        esc(r.error || "failed") + '</div></div>';
        return;
      }
      if (!r.networks.length) {
        box.innerHTML = '<div class="muted">No networks yet. Use "Create network" above.</div>';
        return;
      }
      const rows = r.networks.map(n =>
        '<tr data-nwid="' + esc(n.id) + '" class="ztc-net-row" ' +
             'style="cursor:pointer">' +
          '<td class="mono">' + esc(n.id) + '</td>' +
          '<td>' + esc(n.name || "(unnamed)") + '</td>' +
          '<td>' + (n.private
            ? '<span class="badge info">private</span>'
            : '<span class="badge warn">public</span>') + '</td>' +
          '<td class="mono">' + esc(String(n.authorized_count)) +
            ' / ' + esc(String(n.member_count)) + '</td>' +
          '<td>' + esc((n.ip_pools[0] || {}).ipRangeStart || "-") +
            ' – ' + esc((n.ip_pools[0] || {}).ipRangeEnd || "-") + '</td>' +
          '<td><button class="danger ztc-net-delete" ' +
                    'data-nwid="' + esc(n.id) + '" ' +
                    'data-name="' + esc(n.name || "") + '">Delete</button></td>' +
        '</tr>'
      ).join("");
      box.innerHTML =
        '<table style="width:100%">' +
        '<thead><tr>' +
          '<th>Network ID</th><th>Name</th><th>Visibility</th>' +
          '<th>Auth / total</th><th>IP pool</th><th></th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody></table>';

      // Row-click → members panel. Delegated to survive re-renders.
      box.querySelectorAll(".ztc-net-row").forEach(tr => {
        tr.addEventListener("click", (ev) => {
          if (ev.target && ev.target.matches("button")) return;
          _selectNetwork(tr.getAttribute("data-nwid"));
        });
      });
      box.querySelectorAll(".ztc-net-delete").forEach(btn => {
        btn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          const nwid = btn.getAttribute("data-nwid");
          const name = btn.getAttribute("data-name") || nwid;
          _deleteNetwork(nwid, name);
        });
      });
    } catch (e) {
      box.innerHTML = '<div class="error-box"><div class="error-title">' +
                      esc(String(e)) + '</div></div>';
    }
  }

  async function _selectNetwork(nwid) {
    selectedNetworkId = nwid;
    const panel = document.getElementById("ztcMembersPanel");
    const title = document.getElementById("ztcMembersTitle");
    const box = document.getElementById("ztcMembers");
    if (!panel || !box) return;
    panel.style.display = "";
    title.textContent = nwid;
    box.innerHTML = '<span class="muted">loading members…</span>';
    try {
      const r = await api("/v1/zerotier/central/networks/" + encodeURIComponent(nwid) + "/members");
      if (!r.ok) {
        box.innerHTML = '<div class="error-box"><div class="error-title">' +
                        esc(r.error || "failed") + '</div></div>';
        return;
      }
      if (!r.members.length) {
        box.innerHTML = '<div class="muted">No members have joined yet.</div>';
        return;
      }
      const rows = r.members.map(m => {
        const authBadge = m.authorized
          ? '<span class="badge ok">authorized</span>'
          : '<span class="badge warn">pending</span>';
        const online = m.last_online
          ? _shortAgo(Date.now() - m.last_online)
          : "never";
        const authBtn = m.authorized
          ? '<button class="warning ztc-mem-auth" ' +
                'data-node="' + esc(m.node_id) + '" data-authorize="false">Deauthorize</button>'
          : '<button class="success ztc-mem-auth" ' +
                'data-node="' + esc(m.node_id) + '" data-authorize="true">Approve</button>';
        return (
          '<tr>' +
            '<td class="mono">' + esc(m.node_id || "") + '</td>' +
            '<td>' + esc(m.name || "") + '</td>' +
            '<td>' + authBadge + '</td>' +
            '<td class="mono">' + esc((m.ip_assignments || []).join(", ") || "-") + '</td>' +
            '<td class="mono">' + esc(m.physical_address || "-") + '</td>' +
            '<td class="muted">' + esc(m.client_version || "-") + '</td>' +
            '<td class="muted">' + esc(online) + '</td>' +
            '<td>' + authBtn +
              ' <button class="danger ztc-mem-delete" ' +
                    'data-node="' + esc(m.node_id) + '">Remove</button></td>' +
          '</tr>'
        );
      }).join("");
      box.innerHTML =
        '<table style="width:100%">' +
        '<thead><tr>' +
          '<th>Node ID</th><th>Name</th><th>Auth</th>' +
          '<th>IPs</th><th>Physical</th><th>Version</th>' +
          '<th>Last online</th><th></th>' +
        '</tr></thead>' +
        '<tbody>' + rows + '</tbody></table>';

      box.querySelectorAll(".ztc-mem-auth").forEach(btn => {
        btn.addEventListener("click", () =>
          _setMemberAuth(nwid, btn.getAttribute("data-node"),
                         btn.getAttribute("data-authorize") === "true"));
      });
      box.querySelectorAll(".ztc-mem-delete").forEach(btn => {
        btn.addEventListener("click", () =>
          _deleteMember(nwid, btn.getAttribute("data-node")));
      });
    } catch (e) {
      box.innerHTML = '<div class="error-box"><div class="error-title">' +
                      esc(String(e)) + '</div></div>';
    }
  }

  function _shortAgo(ms) {
    if (!ms || ms < 0) return "?";
    const s = Math.floor(ms / 1000);
    if (s < 60) return s + "s ago";
    const m = Math.floor(s / 60);
    if (m < 60) return m + "m ago";
    const h = Math.floor(m / 60);
    if (h < 24) return h + "h ago";
    const d = Math.floor(h / 24);
    return d + "d ago";
  }

  window.ztcCreateNetwork = async function () {
    const nameInput = document.getElementById("ztcNewName");
    if (!nameInput) return;
    const name = (nameInput.value || "").trim();
    if (!name) { alert("Enter a network name."); return; }
    try {
      const r = await api("/v1/zerotier/central/networks", {method:"POST", body: JSON.stringify({name: name})});
      if (r.ok) {
        nameInput.value = "";
        await _loadNetworks();
      } else {
        alert("Create failed: " + (r.error || "unknown"));
      }
    } catch (e) {
      alert("Create failed: " + String(e));
    }
  };

  async function _deleteNetwork(nwid, name) {
    if (!confirm("Delete network " + (name || nwid) + " permanently?\n" +
                 "This is unrecoverable — every joined member will disconnect.")) {
      return;
    }
    try {
      const r = await api(
        "/v1/zerotier/central/networks/" + encodeURIComponent(nwid),
        {method: "DELETE"}
      );
      if (r.ok) {
        if (selectedNetworkId === nwid) {
          const panel = document.getElementById("ztcMembersPanel");
          if (panel) panel.style.display = "none";
          selectedNetworkId = null;
        }
        await _loadNetworks();
      } else {
        alert("Delete failed: " + (r.error || "unknown"));
      }
    } catch (e) {
      alert("Delete failed: " + String(e));
    }
  }

  async function _setMemberAuth(nwid, nodeId, authorized) {
    try {
      const r = await api("/v1/zerotier/central/networks/" + encodeURIComponent(nwid) +
        "/members/" + encodeURIComponent(nodeId), {method:"POST", body: JSON.stringify({authorized: !!authorized})});
      if (r.ok) {
        await _selectNetwork(nwid);
      } else {
        alert("Update failed: " + (r.error || "unknown"));
      }
    } catch (e) {
      alert("Update failed: " + String(e));
    }
  }

  async function _deleteMember(nwid, nodeId) {
    if (!confirm("Remove member " + nodeId + " from this network?\n" +
                 "They can re-join later; use Deauthorize instead to block.")) {
      return;
    }
    try {
      const r = await api(
        "/v1/zerotier/central/networks/" + encodeURIComponent(nwid) +
        "/members/" + encodeURIComponent(nodeId),
        {method: "DELETE"}
      );
      if (r.ok) {
        await _selectNetwork(nwid);
      } else {
        alert("Remove failed: " + (r.error || "unknown"));
      }
    } catch (e) {
      alert("Remove failed: " + String(e));
    }
  }
})();
