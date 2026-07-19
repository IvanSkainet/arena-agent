// Auto-update Dashboard controls (v3.85.4 polished UI).
//
// Talks to the four v3.85.0 endpoints and renders their output in a
// human-friendly way rather than dumping JSON at the user.
//
//   GET  /v1/admin/update/status
//   POST /v1/admin/update/check
//   POST /v1/admin/update/apply
//   POST /v1/admin/update/restart
//
// UX contract:
//   * The "Check" button is always safe (no side effects).
//   * The "Install" button is a two-click confirm: first click asks
//     the server for a consent token, second click echoes it back.
//     Disabled unless the release has a SHA-256 digest we can verify.
//   * The "Restart" button is a plain restart -- gated by confirm().
//   * On first Dashboard load we run a background check() once so the
//     "Update available" badge in the corner of the Auto-update card
//     shows up without the user having to open Settings first.

let _adminUpdateLatest = null;
let _adminUpdateInFlight = false;
let _adminUpdateSpinnerTimer = null;

function _adminUpdateStartSpinner(baseMsg) {
  _adminUpdateStopSpinner();
  let dots = 0;
  _adminUpdateStatus(baseMsg, "info");
  _adminUpdateSpinnerTimer = setInterval(() => {
    dots = (dots + 1) % 4;
    _adminUpdateStatus(baseMsg + " " + ".".repeat(dots).padEnd(3), "info");
  }, 400);
}

function _adminUpdateStopSpinner() {
  if (_adminUpdateSpinnerTimer) {
    clearInterval(_adminUpdateSpinnerTimer);
    _adminUpdateSpinnerTimer = null;
  }
}

// ---- DOM helpers -----------------------------------------------------------

function _adminUpdateEl(id) { return document.getElementById(id); }

function _adminUpdateStatus(msg, level) {
  const el = _adminUpdateEl("adminUpdateStatus");
  if (!el) return;
  el.textContent = msg || "";
  const colours = {info: "#333", ok: "#0a0", warn: "#a80", err: "#a00"};
  el.style.color = colours[level || "info"];
}

function _adminUpdateSetInstallEnabled(on, tooltip) {
  const btn = _adminUpdateEl("adminUpdateInstallBtn");
  if (!btn) return;
  btn.disabled = !on;
  if (tooltip) btn.title = tooltip;
  else btn.removeAttribute("title");
}

function _adminUpdateBadge(text, level) {
  const el = _adminUpdateEl("adminUpdateBadge");
  if (!el) return;
  el.textContent = text || "";
  el.style.display = text ? "inline-block" : "none";
  const colours = {ok: "#2b8a3e", warn: "#c9740c", err: "#c92a2a",
                   info: "#3a7bd5"};
  el.style.background = colours[level || "info"];
}

function _adminUpdateFormatSize(bytes) {
  if (!bytes || bytes <= 0) return "unknown size";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " KB";
  return (bytes / (1024 * 1024)).toFixed(2) + " MB";
}

// v3.91.0: _htmlEscape is now an alias for esc() from 03-helpers.js.

function _adminUpdateShortSha(sha) {
  // "sha256:abcdef1234...ff00" style, so operators can eyeball
  // whether two runs referenced the same asset without reading
  // 64 hex chars.
  if (!sha) return "not published";
  const clean = String(sha).replace(/^sha256:/i, "");
  if (clean.length < 20) return sha;
  return "sha256:" + clean.slice(0, 8) + "…" + clean.slice(-6)
    + " (" + clean.length + " chars)";
}

function _adminUpdateFormatDate(iso) {
  if (!iso) return "unknown";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch (_) { return iso; }
}

// ---- Rendering -------------------------------------------------------------

function _adminUpdateRenderStatus(status, check) {
  const cur = status && status.current;
  const latest = check && check.latest;
  const parts = [];
  parts.push('<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">');
  parts.push('<div><strong>Installed:</strong> v' + (cur || "?") + '</div>');
  if (latest) {
    parts.push('<div><strong>Available:</strong> v' + latest + '</div>');
  }
  parts.push('</div>');
  parts.push('<table class="mono" style="font-size:11px;color:var(--text);border-collapse:collapse;width:100%">');
  const rows = [
    ["Repository",   check && check.repo || (status && status.repo) || "?"],
    ["Install root", status && status.install_root || "?"],
    ["Platform",     (status && (status.platform_display || status.platform)) || "?"],
    ["Source",       check && check.source || "not yet checked"],
    ["Published",    check && _adminUpdateFormatDate(check.published_at)],
    ["Asset",        check && check.asset_name || "?"],
    ["Asset size",   check && _adminUpdateFormatSize(check.asset_size_bytes)],
    ["Asset SHA-256",
      check && check.asset_digest
        ? '<span title="' + _htmlEscape(check.asset_digest) + '">' + _htmlEscape(_adminUpdateShortSha(check.asset_digest)) + '</span>'
        : "not published (add GITHUB_TOKEN to enable verified installs)"],
    ["Release URL",  check && check.release_url
                     ? '<a href="' + check.release_url + '" target="_blank" rel="noopener">' + check.release_url + '</a>'
                     : "-"],
  ];
  for (const [k, v] of rows) {
    if (v == null || v === "" || v === "unknown") continue;
    parts.push('<tr><td style="padding:2px 8px 2px 0;color:var(--text2);vertical-align:top;white-space:nowrap">' + k + '</td>'
             + '<td style="padding:2px 0;word-break:break-all">' + v + '</td></tr>');
  }
  parts.push('</table>');
  const el = _adminUpdateEl("adminUpdateDetails");
  if (el) el.innerHTML = parts.join("");
}

function _adminUpdateRenderReleaseBody(body) {
  const el = _adminUpdateEl("adminUpdateReleaseBody");
  if (!el) return;
  if (!body || !body.trim()) {
    el.style.display = "none";
    el.innerHTML = "";
    return;
  }
  // Shared renderer from 03-helpers.js -- supports the same Markdown
  // subset the server-side markdown_render.py handles.
  el.innerHTML = renderMarkdown(body);
  el.style.display = "";
}

// ---- Actions ---------------------------------------------------------------

async function adminUpdateCheck() {
  if (_adminUpdateInFlight) return;
  _adminUpdateInFlight = true;
  _adminUpdateStatus("Checking GitHub…");
  _adminUpdateSetInstallEnabled(false);
  _adminUpdateRenderReleaseBody("");
  try {
    const status = await api("/v1/admin/update/status");
    const check  = await api("/v1/admin/update/check",
                             {method: "POST", body: "{}"});
    _adminUpdateRenderStatus(status, check);
    if (!check || check.ok !== true) {
      const err = (check && (check.error || check.hint)) || "check failed";
      _adminUpdateStatus("Check failed: " + err, "err");
      _adminUpdateBadge("check failed", "err");
      return;
    }
    _adminUpdateLatest = check;
    _adminUpdateRenderReleaseBody(check.body || "");
    if (check.needs_update) {
      _adminUpdateStatus(
        "Update available: v" + status.current + " → v" + check.latest,
        "ok");
      _adminUpdateBadge("update v" + check.latest, "warn");
      if (check.asset_digest) {
        _adminUpdateSetInstallEnabled(true,
          "Download + verify + install " + check.asset_name);
      } else {
        // v4.50.2: without a token GitHub does not publish SHA-256.
        // Install is still allowed if the operator explicitly accepts
        // the risk in a confirm dialog -- this unblocks the Windows
        // path where paying the GITHUB_TOKEN price is unreasonable.
        _adminUpdateSetInstallEnabled(true,
          "Install without SHA-256 verification.\n"
          + "GitHub does not publish a digest on the anonymous /releases/latest "
          + "redirect path. You'll get an explicit confirm dialog before the "
          + "install starts. For verified installs, paste a GitHub token in the "
          + "'GitHub token for verified installs' box below.");
      }
    } else {
      _adminUpdateStatus(
        "You're on the latest version (v" + status.current + ").",
        "ok");
      _adminUpdateBadge("up to date", "ok");
    }
  } catch (e) {
    _adminUpdateStatus("Check failed: " + (e && e.message || e), "err");
    _adminUpdateBadge("error", "err");
  } finally {
    _adminUpdateInFlight = false;
  }
}

async function adminUpdateInstall() {
  if (_adminUpdateInFlight) return;
  if (!_adminUpdateLatest || !_adminUpdateLatest.needs_update) {
    _adminUpdateStatus("Nothing to install. Press Check first.", "warn");
    return;
  }
  const rel = _adminUpdateLatest;
  const size = _adminUpdateFormatSize(rel.asset_size_bytes);
  const unverified = !rel.asset_digest;
  const proceed = unverified ? confirm(
      "⚠ Install v" + rel.latest + " WITHOUT SHA-256 verification?\n\n"
      + "Asset : " + rel.asset_name + "  (" + size + ")\n"
      + "SHA-256: not published (needs a GitHub token to fetch)\n\n"
      + "Because you have no GitHub token configured, GitHub cannot\n"
      + "give us the release's SHA-256 digest. The bridge will still\n"
      + "download the release from github.com (SSRF-guarded, 512 MB cap),\n"
      + "compute the SHA-256 for the audit log, and install atomically --\n"
      + "but it will NOT verify that digest against a published value.\n\n"
      + "This is safe if you trust GitHub's HTTPS. For a verified install\n"
      + "cancel here and paste a token in the box below the Auto-update card,\n"
      + "then Check again.\n\n"
      + "Continue with UNVERIFIED install?"
    ) : confirm(
      "Install v" + rel.latest + "?\n\n"
      + "Asset : " + rel.asset_name + "  (" + size + ")\n"
      + "SHA-256: " + rel.asset_digest + "\n\n"
      + "The bridge will download the release from GitHub, verify\n"
      + "SHA-256, atomically replace the source tree, and restart.\n"
      + "Your config and bridge home are untouched.\n\n"
      + "This takes ~10 seconds and briefly disconnects this Dashboard."
    );
  if (!proceed) {
    _adminUpdateStatus("Install cancelled.", "warn");
    return;
  }
  _adminUpdateInFlight = true;
  _adminUpdateSetInstallEnabled(false);
  _adminUpdateStartSpinner(unverified
    ? "Requesting consent token (unverified path)"
    : "Requesting consent token");
  const body = {
    tag: rel.latest_tag,
    asset_url: rel.asset_url,
    asset_name: rel.asset_name,
    restart: true,
  };
  if (unverified) {
    body.accept_no_verification = true;
  } else {
    body.expected_sha256 = rel.asset_digest;
  }
  try {
    const step1 = await api("/v1/admin/update/apply",
                            {method: "POST", body: JSON.stringify(body)});
    if (step1 && step1.consent_required && step1.required_consent) {
      _adminUpdateStartSpinner(
        "Downloading + verifying + installing (consent = "
        + step1.required_consent + ")");
      body.consent = step1.required_consent;
      const step2 = await api("/v1/admin/update/apply",
                              {method: "POST", body: JSON.stringify(body)});
      _adminUpdateStopSpinner();
      if (step2 && step2.ok) {
        const swapped = (step2.swapped || []).join(", ");
        const restartHint = step2.restart === "scheduled"
          ? "Bridge is restarting — reload this page in ~3 s."
          : "Restart pending: relaunch the service to activate.";
        _adminUpdateStatus(
          "Installed v" + step2.applied_version + ".\n"
          + "Swapped: " + (swapped || "(windows deferred install)") + "\n"
          + restartHint,
          "ok");
        _adminUpdateBadge("installing v" + step2.applied_version, "info");
        // Auto-refresh the page after the bridge should be back up.
        setTimeout(() => { location.reload(); }, 5000);
      } else {
        const err = (step2 && (step2.error || JSON.stringify(step2))) || "unknown error";
        _adminUpdateStatus("Install failed: " + err, "err");
        _adminUpdateSetInstallEnabled(true);
      }
    } else if (step1 && step1.ok) {
      _adminUpdateStopSpinner();
      _adminUpdateStatus("Installed v" + step1.applied_version + ".", "ok");
    } else {
      _adminUpdateStopSpinner();
      const err = (step1 && (step1.error || JSON.stringify(step1))) || "no response";
      _adminUpdateStatus("Install failed: " + err, "err");
      _adminUpdateSetInstallEnabled(true);
    }
  } catch (e) {
    _adminUpdateStopSpinner();
    _adminUpdateStatus("Install failed: " + (e && e.message || e), "err");
    _adminUpdateSetInstallEnabled(true);
  } finally {
    _adminUpdateStopSpinner();
    _adminUpdateInFlight = false;
  }
}

async function adminUpdateRestart() {
  if (!confirm("Restart the bridge now?\n\n"
               + "On systemd / launchd the service comes back automatically.\n"
               + "On Windows a service supervisor (nssm) must relaunch it.")) {
    return;
  }
  _adminUpdateStatus("Restart requested…");
  try {
    const r = await api("/v1/admin/update/restart",
                        {method: "POST", body: "{}"});
    if (r && r.ok) {
      _adminUpdateStatus(
        "Restart " + (r.restart || "scheduled")
        + " — reload this page in ~3 s.", "ok");
      setTimeout(() => { location.reload(); }, 5000);
    } else {
      _adminUpdateStatus(
        "Restart failed: " + (r && (r.error || r.hint) || "unknown"), "err");
    }
  } catch (e) {
    _adminUpdateStatus("Restart failed: " + (e && e.message || e), "err");
  }
}

// ---- Auto-check on Dashboard boot -----------------------------------------
// Fire ONCE, ~2 s after boot, so the badge shows the update state
// without the user needing to open Settings.
(function () {
  function _autoOnce() {
    setTimeout(() => {
      try { adminUpdateCheck(); } catch (_) {}
    }, 2000);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _autoOnce, {once: true});
  } else {
    _autoOnce();
  }
})();

// ---------------------------------------------------------------------------
// v4.50.0: GitHub token UI (Settings tab).
// ---------------------------------------------------------------------------
async function adminUpdateTokenSave() {
  const inp = document.getElementById("adminUpdateTokenInput");
  const out = document.getElementById("adminUpdateTokenResult");
  if (!inp || !out) return;
  const raw = String(inp.value || "").trim();
  if (!raw) { out.textContent = "Paste a token first."; out.style.color = "var(--yellow)"; return; }
  out.textContent = "Saving…"; out.style.color = "var(--text2)";
  try {
    const data = await api("/v1/admin/update/token-set", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: raw}),
    });
    if (data && data.ok) {
      out.textContent = "Token saved (source: " + (data.source || "file") + "). Install button will unlock on next Check.";
      out.style.color = "var(--green)";
      inp.value = "";
      // Refresh status so the header chip flips to 'token active'.
      if (typeof adminUpdateCheck === "function") adminUpdateCheck();
    } else {
      out.textContent = "Save failed: " + (data && data.error || "unknown error");
      out.style.color = "var(--red)";
    }
  } catch (e) {
    out.textContent = "Save failed: " + (e && e.message || e);
    out.style.color = "var(--red)";
  } finally {
    _adminUpdateRefreshTokenStatus();
  }
}

async function adminUpdateTokenClear() {
  const out = document.getElementById("adminUpdateTokenResult");
  if (!out) return;
  if (!confirm("Clear the saved GitHub token from this machine?\n\nEnv vars (GITHUB_TOKEN / GH_TOKEN) are not touched.")) return;
  out.textContent = "Clearing…"; out.style.color = "var(--text2)";
  try {
    const data = await api("/v1/admin/update/token-clear", {method: "POST"});
    if (data && data.ok) {
      out.textContent = data.removed ? "Token file removed." : "No token file was present.";
      out.style.color = "var(--green)";
    } else {
      out.textContent = "Clear failed: " + (data && data.error || "unknown error");
      out.style.color = "var(--red)";
    }
  } catch (e) {
    out.textContent = "Clear failed: " + (e && e.message || e);
    out.style.color = "var(--red)";
  } finally {
    _adminUpdateRefreshTokenStatus();
  }
}

async function _adminUpdateRefreshTokenStatus() {
  const el = document.getElementById("adminUpdateTokenStatus");
  if (!el) return;
  try {
    const data = await api("/v1/admin/update/status");
    const src = data && data.github_token_source || "none";
    if (src === "env") {
      el.innerHTML = "<span style='color:var(--green)'>● Token active</span> (from GITHUB_TOKEN / GH_TOKEN env var). Env values take precedence over the saved file.";
    } else if (src === "file") {
      el.innerHTML = "<span style='color:var(--green)'>● Token active</span> (from saved file on this machine). Install button will use authenticated + SHA-256 verified path.";
    } else {
      el.innerHTML = "<span style='color:var(--yellow)'>○ No token configured.</span> Auto-Update falls back to the anonymous /releases/latest redirect — Install stays disabled because GitHub doesn't publish SHA-256 there. Paste a token below to unlock.";
    }
  } catch (e) {
    el.textContent = "Token status: unavailable (" + (e && e.message || e) + ")";
  }
}

// Refresh once per Settings-tab activation. arenaTabByName().onShow already
// fires refreshSettings(); attach ourselves to run right after that.
document.addEventListener("DOMContentLoaded", () => {
  // First paint after the shell renders. Deliberately fire-and-forget.
  setTimeout(() => { try { _adminUpdateRefreshTokenStatus(); } catch (_e) {} }, 400);
});
