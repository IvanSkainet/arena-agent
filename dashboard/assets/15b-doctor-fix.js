async function doctorFix() {
  if (!confirm("Auto-fix common issues?")) return;
  const doctorEl = document.getElementById("doctorResults");
  doctorEl.innerHTML = "<span class='spinner'></span> Running auto-fix...";
  try {
    const result = await api("/v1/doctor/fix", {method: "POST"});
    if (!result.ok) { doctorEl.innerHTML = "<div class='card'>Error: " + esc(result.error||"?") + "</div>"; return; }
    doctorEl.innerHTML = "";
    const card = document.createElement("div");
    card.className = "card";
    const pre = document.createElement("pre");
    pre.className = "mono";
    pre.style.whiteSpace = "pre-wrap";
    pre.textContent = JSON.stringify(result, null, 2);
    card.appendChild(pre);
    doctorEl.appendChild(card);
    // Re-run diagnostics after fix
    setTimeout(runDoctor, 2000);
  } catch(e) {
    doctorEl.innerHTML = "<div class='card'>Fix error: " + esc(e.message||"Unknown") + "</div>";
  }
}

