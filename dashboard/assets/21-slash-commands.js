// ============================================================
const SLASH_COMMANDS = {
  "/shot":    { cmd: "agentctl browser sd-shot ",          hint: "Screenshot via Chromium" },
  "/dump":    { cmd: "agentctl browser sd-dump ",          hint: "Full DOM via Chromium" },
  "/read":    { cmd: "agentctl browser py-read ",          hint: "Readability extract (urllib)" },
  "/text":    { cmd: "agentctl browser py-dump ",          hint: "Plain text + links (urllib)" },
  "/head":    { cmd: "agentctl browser py-head ",          hint: "HTTP HEAD request" },
  "/search":  { cmd: "agentctl browser py-search ",        hint: "DuckDuckGo search --n 5" },
  "/fetch":   { cmd: "agentctl browser py-fetch ",         hint: "Raw HTTP GET to URL" },
  "/hardware":{ cmd: "curl -s http://127.0.0.1:8765/v1/hardware?include_inventory=0 -H \"Authorization: Bearer $ARENA_TOKEN\"", hint: "Unified hardware inventory" },
  "/hwinfo":  { cmd: "curl -s http://127.0.0.1:8765/v1/hwinfo?include_inventory=0 -H \"Authorization: Bearer $ARENA_TOKEN\"", hint: "Hardware report (compat alias)" },
  "/status":  { cmd: "agentctl sys status",                hint: "Bridge + tunnel + ports overview" },
  "/doctor":  { cmd: "agentctl sys doctor",                hint: "System health checks" },
  "/sysinfo": { cmd: "agentctl sys info",                  hint: "CPU/RAM/Disk summary" },
  "/audit":   { cmd: "agentctl audit tail 50",             hint: "Recent audit log entries" },
  "/facts":   { cmd: "agentctl mem list",                  hint: "List memory facts" },
  "/tasks":   { cmd: "agentctl task ls",                   hint: "List queued/active tasks" },
  "/ip":      { cmd: "agentctl web ip",                    hint: "Show local + public IP" },
  "/dns":     { cmd: "agentctl web dns ",                  hint: "DNS lookup (append host)" },
  "/funnel":  { cmd: "tailscale funnel status",            hint: "Tailscale Funnel status" },
  "/help":    { cmd: "agentctl --help",                    hint: "List agentctl commands" },
};

function expandSlash(input) {
  const trimmed = input.trim();
  for (const [k, v] of Object.entries(SLASH_COMMANDS)) {
    if (trimmed === k || trimmed.startsWith(k + " ")) {
      return v.cmd + trimmed.substring(k.length).trimStart();
    }
  }
  return input;
}

function setupSlashSuggest() {
  const inp = document.getElementById("termCmd");
  const box = document.getElementById("termSuggest");
  if (!inp || !box) return;

  function render() {
    const v = inp.value;
    if (!v.startsWith("/") || v.includes(" ")) {
      box.style.display = "none";
      return;
    }
    const prefix = v.toLowerCase();
    const matches = Object.entries(SLASH_COMMANDS)
      .filter(([k]) => k.startsWith(prefix))
      .slice(0, 8);
    if (!matches.length) {
      box.style.display = "none";
      return;
    }
    box.innerHTML = matches.map(([k, v]) =>
      `<div class="slash-item" style="padding:6px 10px;cursor:pointer;border-bottom:1px solid var(--border)" data-cmd="${k}">
         <b>${k}</b> <span style="color:var(--text2);margin-left:8px">${v.hint}</span>
         <div style="color:var(--text2);font-size:10px;margin-top:2px">${v.cmd.length > 60 ? v.cmd.substring(0,60) + "..." : v.cmd}</div>
       </div>`
    ).join("");
    box.style.display = "block";
    box.querySelectorAll(".slash-item").forEach(el => {
      el.addEventListener("mouseenter", () => el.style.background = "var(--bg3)");
      el.addEventListener("mouseleave", () => el.style.background = "");
      el.addEventListener("click", () => {
        const k = el.dataset.cmd;
        inp.value = k + (SLASH_COMMANDS[k].cmd.endsWith(" ") ? " " : "");
        box.style.display = "none";
        inp.focus();
      });
    });
  }

  inp.addEventListener("input", render);
  inp.addEventListener("focus", render);
  inp.addEventListener("blur", () => setTimeout(() => box.style.display = "none", 200));
  inp.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && box.style.display === "block") {
      const first = box.querySelector(".slash-item");
      if (first) {
        e.preventDefault();
        first.click();
      }
    } else if (e.key === "Escape") {
      box.style.display = "none";
    }
  });
}

// ---------- Hardware Diagnostics ----------
