// Runtime access-profile switch.
//
// The operator's complaint was concrete: "there is no button, and
// without it this is unusable." He was right -- `--profile` was fixed at
// launch, so changing it meant editing a command line and restarting.
// On a phone that means going back into Termux, which is exactly what a
// Dashboard exists to prevent. A safety control nobody can reach does
// not get respected; it gets routed around.
//
// So the button exists, and the safety lives in the interaction instead:
// widening is a two-step consent (same shape as update/apply), narrowing
// is one click, and both are audited server-side.

async function profileRefresh() {
  const badge = document.getElementById("profBadge");
  const meaning = document.getElementById("profMeaning");
  const warn = document.getElementById("profWarn");
  const widen = document.getElementById("profWiden");
  const narrow = document.getElementById("profNarrow");
  if (!badge) return;
  try {
    const r = await api("/v1/admin/profile");
    const full = r.profile === "owner-shell";
    badge.textContent = r.profile;
    badge.className = "badge " + (full ? "warn" : "ok");
    meaning.textContent = (r.meaning && r.meaning[r.profile]) || "";
    if (widen) widen.disabled = full;
    if (narrow) narrow.disabled = !full;
    if (warn) {
      if (r.warning) {
        warn.textContent = "⚠ " + r.warning;
        warn.style.display = "";
      } else {
        warn.style.display = "none";
      }
    }
  } catch (e) {
    badge.textContent = "unavailable";
    badge.className = "badge gray";
    if (meaning) meaning.textContent = String((e && e.message) || e);
  }
}

async function profileWiden() {
  const out = document.getElementById("profResult");
  const say = (t) => { if (out) out.textContent = t; };
  try {
    // Step 1: ask, and get the phrase plus a plain-language description
    // of what is being granted.
    const challenge = await api("/v1/admin/profile", {
      method: "POST",
      body: JSON.stringify({profile: "owner-shell"})
    });
    if (challenge.ok) { await profileRefresh(); say("Already enabled."); return; }
    if (!challenge.consent_required) {
      say("Error: " + (challenge.error || "unexpected response"));
      return;
    }

    const detail = (challenge.what_this_means || "") +
      (challenge.bind && challenge.bind !== "127.0.0.1"
        ? "\n\nThis bridge is bound to " + challenge.bind +
          " — reachable from that network."
        : "");
    if (!confirm("Enable full shell?\n\n" + detail +
                 "\n\nYou can restore restrictions at any time with one click.")) {
      say("Cancelled.");
      return;
    }

    // Step 2: echo the phrase back. The Dashboard does this for the
    // operator -- the confirm dialog above IS the deliberate act. Making
    // a human retype a hash teaches copy-paste, not caution.
    const done = await api("/v1/admin/profile", {
      method: "POST",
      body: JSON.stringify({profile: "owner-shell",
                            consent: challenge.required_consent})
    });
    say(done.ok ? "Full shell enabled." : "Refused: " + (done.error || "?"));
    await profileRefresh();
  } catch (e) {
    say("Failed: " + ((e && e.message) || e));
  }
}

async function profileNarrow() {
  const out = document.getElementById("profResult");
  try {
    const r = await api("/v1/admin/profile", {
      method: "POST",
      body: JSON.stringify({profile: "cautious"})
    });
    if (out) out.textContent = r.ok ? "Restrictions restored."
                                    : ("Failed: " + (r.error || "?"));
    await profileRefresh();
  } catch (e) {
    if (out) out.textContent = "Failed: " + ((e && e.message) || e);
  }
}

if (window.arenaWhenReady) {
  window.arenaWhenReady(profileRefresh);
} else {
  document.addEventListener("DOMContentLoaded", profileRefresh);
}
