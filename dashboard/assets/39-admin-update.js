// Auto-update Dashboard controls (v3.85.1).
//
// Talks to the four v3.85.0 endpoints:
//   GET  /v1/admin/update/status          current version + install root
//   POST /v1/admin/update/check           GitHub round-trip
//   POST /v1/admin/update/apply           download + install
//   POST /v1/admin/update/restart         manual restart (POSIX re-execs;
//                                         Windows relies on a service supervisor)
//
// The two-step consent flow is exactly the same as
// /v1/mobile/{s}/apk/install from v3.83.5: the first apply call
// returns `consent_required: true` with the token the user must
// echo back on the second call. This module handles both roundtrips
// automatically after a single Install click, but only after the
// user confirms in a plain browser confirm() dialog so a stray
// click on a shared laptop can't upgrade the bridge.
//
// Depends on globals from 02-api-helper.js: api(). Nothing else.

let _adminUpdateLatest = null;   // last successful /check response
let _adminUpdateInFlight = false;

function _adminUpdateStatus(msg, colour) {
  const el = document.getElementById("adminUpdateStatus");
  if (!el) return;
  el.textContent = msg || "";
  el.style.color = colour || "#333";
}

function _adminUpdateSetInstallEnabled(on) {
  const btn = document.getElementById("adminUpdateInstallBtn");
  if (btn) btn.disabled = !on;
}

function _adminUpdateShowReleaseBody(body) {
  const el = document.getElementById("adminUpdateReleaseBody");
  if (!el) return;
  if (body && body.trim()) {
    el.textContent = body;
    el.style.display = "";
  } else {
    el.style.display = "none";
    el.textContent = "";
  }
}

async function adminUpdateCheck() {
  if (_adminUpdateInFlight) return;
  _adminUpdateInFlight = true;
  _adminUpdateStatus("Checking GitHub…");
  _adminUpdateSetInstallEnabled(false);
  _adminUpdateShowReleaseBody("");
  try {
    const status = await api("/v1/admin/update/status");
    const check = await api("/v1/admin/update/check",
                            {method: "POST", body: "{}"});
    if (!check || check.ok !== true) {
      const err = (check && (check.error || check.hint)) || "check failed";
      _adminUpdateStatus("Check failed: " + err, "#a00");
      return;
    }
    _adminUpdateLatest = check;
    _adminUpdateShowReleaseBody(check.body || "");
    if (check.needs_update) {
      const size = check.asset_size_bytes
        ? (Math.round(check.asset_size_bytes / 1024) + " KB")
        : "unknown size";
      _adminUpdateStatus(
        "Update available: " + status.current + "  →  " + check.latest
        + "\nAsset: " + (check.asset_name || "(unknown)")
        + "  · " + size
        + "\nPublished: " + (check.published_at || "?")
        + "\nSHA-256: " + (check.asset_digest || "(GitHub did not publish one)")
        + "\nRelease: " + (check.release_url || ""),
        "#0a0");
      // Only enable Install if GitHub gave us a sha256 -- without one
      // apply_update refuses to install.
      _adminUpdateSetInstallEnabled(!!check.asset_digest);
      if (!check.asset_digest) {
        _adminUpdateStatus(
          "Update available but GitHub didn't publish a sha256 digest\n"
          + "for this asset. Install is disabled to keep verification\n"
          + "mandatory. Re-run the release with `gh release create`\n"
          + "against a newer gh CLI (v2.60+) which attaches digests\n"
          + "automatically.",
          "#a80");
      }
    } else {
      _adminUpdateStatus(
        "Already on the latest version (" + status.current + ").",
        "#080");
    }
  } catch (e) {
    _adminUpdateStatus("Check failed: " + (e && e.message || e), "#a00");
  } finally {
    _adminUpdateInFlight = false;
  }
}

async function adminUpdateInstall() {
  if (_adminUpdateInFlight) return;
  if (!_adminUpdateLatest || !_adminUpdateLatest.needs_update) {
    _adminUpdateStatus("Nothing to install. Press Check first.", "#a80");
    return;
  }
  const rel = _adminUpdateLatest;
  const size = rel.asset_size_bytes
    ? (Math.round(rel.asset_size_bytes / 1024) + " KB")
    : "unknown";
  const proceed = confirm(
    "Install " + rel.latest + " (" + rel.asset_name + ", " + size + ")?\n\n"
    + "The bridge will download the release from GitHub, verify\n"
    + "SHA-256, atomically replace the source tree, and re-exec\n"
    + "itself. Your config and bridge home are not touched.\n\n"
    + "This takes ~10 seconds and briefly disconnects this Dashboard."
  );
  if (!proceed) {
    _adminUpdateStatus("Install cancelled.", "#a80");
    return;
  }
  _adminUpdateInFlight = true;
  _adminUpdateSetInstallEnabled(false);
  _adminUpdateStatus("Downloading " + rel.asset_name + "…");
  const body = {
    tag: rel.latest_tag,
    asset_url: rel.asset_url,
    asset_name: rel.asset_name,
    expected_sha256: rel.asset_digest,
    restart: true,
  };
  try {
    // Step 1: server returns consent_required + the token we need.
    const step1 = await api("/v1/admin/update/apply",
                            {method: "POST", body: JSON.stringify(body)});
    if (step1 && step1.consent_required && step1.required_consent) {
      _adminUpdateStatus(
        "Verifying + installing… (consent: " + step1.required_consent + ")");
      body.consent = step1.required_consent;
      const step2 = await api("/v1/admin/update/apply",
                              {method: "POST", body: JSON.stringify(body)});
      if (step2 && step2.ok) {
        _adminUpdateStatus(
          "Installed " + step2.applied_version + "!\n"
          + "Swapped: " + ((step2.swapped || []).join(", ") || "(windows deferred install)")
          + "\n" + (step2.restart === "scheduled"
                    ? "Bridge is restarting (systemd) — reload this page in ~3 s."
                    : "Restart pending: relaunch the service to activate."),
          "#0a0");
      } else {
        const err = (step2 && (step2.error || JSON.stringify(step2))) || "unknown error";
        _adminUpdateStatus("Install failed: " + err, "#a00");
        _adminUpdateSetInstallEnabled(true);
      }
    } else if (step1 && step1.ok) {
      // Some old server versions might do a one-shot install. Handle
      // that too even though v3.85.0 always uses two-step.
      _adminUpdateStatus("Installed " + step1.applied_version + ".", "#0a0");
    } else {
      const err = (step1 && (step1.error || JSON.stringify(step1))) || "no response";
      _adminUpdateStatus("Install failed: " + err, "#a00");
      _adminUpdateSetInstallEnabled(true);
    }
  } catch (e) {
    _adminUpdateStatus("Install failed: " + (e && e.message || e), "#a00");
    _adminUpdateSetInstallEnabled(true);
  } finally {
    _adminUpdateInFlight = false;
  }
}

async function adminUpdateRestart() {
  if (!confirm("Restart the bridge now?\n\n"
               + "On systemd / launchd the service will come back up automatically.\n"
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
        + " — reload this page in ~3 s.", "#0a0");
    } else {
      _adminUpdateStatus(
        "Restart failed: " + (r && (r.error || r.hint) || "unknown"), "#a00");
    }
  } catch (e) {
    _adminUpdateStatus("Restart failed: " + (e && e.message || e), "#a00");
  }
}
