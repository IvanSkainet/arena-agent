async function regenToken() {
  // v4.165.0 (bug #66): this dialog used to promise that a restart was
  // needed before the previous credential stopped working. The opposite
  // is true -- the route swaps the live in-memory token, so the previous
  // one is refused from the next request onward. Telling an operator who
  // is rotating a leaked credential that the leak stays live is the
  // dangerous direction to be wrong in.
  if (!confirm("Regenerate the auth token?\n\n" +
               "A new token will be written to token.txt.\n" +
               "The OLD token stops working IMMEDIATELY — every client " +
               "still using it, including this page, must be updated.")) return;
  try {
    const result = await api("/v1/token/regenerate", {method: "POST"});
    if (!result.ok) {
      alert("Error: " + (result.error||"?"));
      return;
    }
    const tok = result.token || "(no token in response)";
    // The rotation already happened server-side and the previous bearer
    // is already dead, so this page's stored credential is stale RIGHT
    // NOW. Persist the new one before doing anything else -- the earlier
    // code only saved it on the restart branch, so choosing Cancel left
    // the dashboard holding a credential the bridge no longer accepts and
    // every subsequent call 401'd with no explanation.
    let saved = true;
    try { localStorage.setItem("arena_token", tok); } catch(_) { saved = false; }

    const wantRestart = confirm(
      "✅ New token generated and ALREADY ACTIVE:\n\n" + tok + "\n\n" +
      "Written to:\n" + (result.written_to || []).join("\n") + "\n\n" +
      (saved ? "This page has been updated to the new token.\n"
             : "⚠ Could not save the token in this browser — copy it now.\n") +
      "Other clients using the old token are already being refused.\n\n" +
      "Restart the bridge as well? (optional — not needed for the token)"
    );
    if (wantRestart) {
      bridgeRestart();
    } else if (saved) {
      alert("Token rotated and active. This page now uses the new token.");
    } else {
      alert("Token rotated and active, but it could not be stored in this " +
            "browser. Paste it manually or this page will get 401s.");
    }
  } catch(e) {
    alert("Error regenerating token: " + (e.message||"Unknown error"));
  }
}

async function exportConfig() {
  try {
    const result = await api("/v1/config");
    if (!result.ok) { alert("Error: " + (result.error||"?")); return; }
    const blob = new Blob([JSON.stringify(result, null, 2)], {type: "application/json"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "arena-bridge-config.json"; a.click();
    URL.revokeObjectURL(url);
  } catch(e) {
    alert("Error exporting config: " + (e.message||"Unknown error"));
  }
}

// SETTINGS - Beep
async function testBeep(type) {
  try {
    const result = await api("/v1/beep", {method: "POST", body: JSON.stringify({type})});
    if (result.ok) {
      try {
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain); gain.connect(ctx.destination);
        const freqs = {success:880,warning:440,error:330,melody:523,attention:1200};
        osc.frequency.value = freqs[type] || 800;
        gain.gain.value = 0.15;
        osc.start(); osc.stop(ctx.currentTime + 0.2);
      } catch(e) {}
    } else {
      alert("Beep error: " + (result.error||"Unknown"));
    }
  } catch(e) {
    alert("Beep failed: " + (e.message||"Unknown error"));
  }
}

