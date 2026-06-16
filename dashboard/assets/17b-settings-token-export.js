async function regenToken() {
  if (!confirm("Regenerate the auth token?\n\n" +
               "A new token will be written to token.txt.\n" +
               "Existing sessions continue with the OLD token until the bridge restarts.")) return;
  try {
    const result = await api("/v1/token/regenerate", {method: "POST"});
    if (!result.ok) {
      alert("Error: " + (result.error||"?"));
      return;
    }
    const tok = result.token || "(no token in response)";
    const wantRestart = confirm(
      "✅ New token generated:\n\n" + tok + "\n\n" +
      "Written to:\n" + (result.written_to || []).join("\n") + "\n\n" +
      "Restart the bridge now to activate? (Recommended)\n" +
      "Cancel to keep current session running with old token."
    );
    if (wantRestart) {
      // Persist token in localStorage so the reloaded page can re-auth
      try { localStorage.setItem("arena_token", tok); } catch(_) {}
      bridgeRestart();
    } else {
      alert("Token saved. Restart bridge later via Settings → Restart Bridge.");
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

