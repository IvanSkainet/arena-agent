// ===== TERMINAL (v1.6.2: persistent shell-like session) =====
const termInput = document.getElementById("termCmd");
let _termHistoryIndex = -1;  // -1 = no nav, 0..n-1 = navigating

termInput.addEventListener("keydown", e => {
  if (e.key === "Enter") {
    _termHistoryIndex = -1;
    runCommand();
  } else if (e.key === "ArrowUp") {
    if (cmdHistory.length === 0) return;
    e.preventDefault();
    _termHistoryIndex = Math.min(_termHistoryIndex + 1, cmdHistory.length - 1);
    termInput.value = cmdHistory[_termHistoryIndex];
    // place cursor at end
    setTimeout(() => termInput.setSelectionRange(termInput.value.length, termInput.value.length), 0);
  } else if (e.key === "ArrowDown") {
    if (_termHistoryIndex <= 0) {
      _termHistoryIndex = -1;
      termInput.value = "";
      return;
    }
    e.preventDefault();
    _termHistoryIndex--;
    termInput.value = cmdHistory[_termHistoryIndex];
  } else if (e.key === "l" && e.ctrlKey) {
    e.preventDefault();
    clearTerminal();
  } else {
    // any other key resets history navigation
    if (e.key.length === 1) _termHistoryIndex = -1;
  }
});

function _termAppendEntry(cmdText, opts) {
  opts = opts || {};
  const sess = document.getElementById("termSession");
  if (!sess) return null;

  const entry = document.createElement("div");
  entry.className = "term-entry";
  entry.style.cssText = "margin-bottom:14px;padding-bottom:10px;border-bottom:1px dashed var(--border)";

  const head = document.createElement("div");
  head.style.cssText = "display:flex;align-items:center;gap:8px;margin-bottom:6px";

  const prompt = document.createElement("span");
  prompt.textContent = "$";
  prompt.style.cssText = "color:var(--green);font-weight:700";
  head.appendChild(prompt);

  const cmdSpan = document.createElement("span");
  cmdSpan.textContent = cmdText;
  cmdSpan.style.cssText = "color:var(--text);font-weight:600;flex:1;word-break:break-all";
  head.appendChild(cmdSpan);

  const meta = document.createElement("span");
  meta.className = "term-meta";
  meta.style.cssText = "color:var(--text2);font-size:11px;white-space:nowrap";
  meta.textContent = "running...";
  head.appendChild(meta);

  const out = document.createElement("pre");
  out.className = "term-out";
  out.style.cssText = "margin:0;padding:0;white-space:pre-wrap;word-break:break-word;color:var(--text)";
  out.textContent = "";

  entry.appendChild(head);
  entry.appendChild(out);
  sess.appendChild(entry);
  sess.scrollTop = sess.scrollHeight;

  return { entry, head, meta, out };
}

function normalizeShellCommand(cmd) {
  const trimmed = String(cmd || "").trim();
  if (/^agentctl(\s|$)/.test(trimmed)) return trimmed.replace(/^agentctl\b/, "$HOME/arena-bridge/bin/agentctl");
  return cmd;
}

// v4.15.0: render output through the ANSI-SGR parser so
// stdout/stderr with ESC[...m colour codes shows up as coloured
// spans instead of literal '\x1b[31m'. Falls back to
// textContent when the string has no escapes so we keep the
// zero-cost path for ordinary commands. Also stashes the raw
// (uncoloured) text on the pre so Copy Output can round-trip
// it without HTML tags.
function _termWriteOut(slot, text) {
  if (!slot || !slot.out) return;
  const raw = String(text == null ? "" : text);
  slot.out._rawText = raw;
  if (raw.indexOf("\x1b[") === -1) {
    slot.out.textContent = raw;
  } else {
    slot.out.innerHTML = __termAnsiToHtml(raw);
  }
}

// v4.13.0: feature-detect ReadableStream support so old browsers
// silently fall back to buffered /v1/exec instead of showing a
// broken stream-mode session. Same probe shape as the audit
// live-tail detector.
function __termStreamSupported() {
  try {
    return typeof ReadableStream === "function"
      && typeof Response !== "undefined"
      && typeof (new Response(new Blob())).body === "object"
      && typeof (new Response(new Blob())).body.getReader === "function";
  } catch (_e) {
    return false;
  }
}

// v4.13.0: run a command via POST /v1/exec/stream (chunked NDJSON,
// v4.3.0 endpoint). Appends stdout/stderr chunks to the slot's
// <pre> as they arrive; the head badge gets a live pulse dot and
// a Kill button that POSTs /v1/kill for the streamed request_id.
async function _runStreamedCommand(c, timeout, slot, t0) {
  const token = (window.ARENA_TOKEN || "").trim();
  const controller = new AbortController();
  let requestId = null;

  // Head: add the live dot + Kill button.
  if (slot && slot.meta) {
    slot.meta.innerHTML = "";
    const dot = document.createElement("span");
    dot.className = "term-stream-dot";
    slot.meta.appendChild(dot);
    const label = document.createElement("span");
    label.textContent = "streaming...";
    slot.meta.appendChild(label);
    const killBtn = document.createElement("button");
    killBtn.className = "term-kill-btn";
    killBtn.textContent = "Kill";
    killBtn.style.marginLeft = "6px";
    killBtn.onclick = async () => {
      killBtn.disabled = true;
      killBtn.textContent = "killing...";
      // Best-effort: /v1/kill needs the request_id; if we haven't
      // seen a start event yet, abort the fetch client-side.
      if (requestId) {
        try {
          await api("/v1/kill", {method: "POST",
                                 body: JSON.stringify({request_id: requestId})});
        } catch (_e) { /* fall through to abort */ }
      }
      try { controller.abort(); } catch (_e) {}
    };
    slot.meta.appendChild(killBtn);
    slot._killBtn = killBtn;
    slot._headLabel = label;
  }

  let stdoutText = "";
  let stderrText = "";
  let exitCode = null;
  let timedOut = false;

  try {
    const resp = await fetch("/v1/exec/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? {"Authorization": "Bearer " + token} : {}),
      },
      body: JSON.stringify({cmd: c, timeout}),
      signal: controller.signal,
    });
    if (!resp.ok || !resp.body) {
      throw new Error("stream HTTP " + resp.status);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      let chunk;
      try { chunk = await reader.read(); }
      catch (_e) { break; }
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, {stream: true});
      let idx;
      while ((idx = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); }
        catch (_e) { continue; }
        const t = ev.type;
        if (t === "meta") {
          requestId = ev.request_id || null;
        } else if (t === "start") {
          if (slot && slot._headLabel) {
            slot._headLabel.textContent = "pid " + (ev.pid || "?");
          }
        } else if (t === "stdout") {
          stdoutText += ev.data || "";
          if (slot) {
            _termWriteOut(slot, stdoutText +
              (stderrText ? "\n--- STDERR ---\n" + stderrText : ""));
            const sess = document.getElementById("termSession");
            if (sess) sess.scrollTop = sess.scrollHeight;
          }
        } else if (t === "stderr") {
          stderrText += ev.data || "";
          if (slot) {
            _termWriteOut(slot, stdoutText +
              (stderrText ? "\n--- STDERR ---\n" + stderrText : ""));
            const sess = document.getElementById("termSession");
            if (sess) sess.scrollTop = sess.scrollHeight;
          }
        } else if (t === "exit") {
          exitCode = (ev.exit_code != null) ? ev.exit_code : null;
          timedOut = !!ev.timed_out;
        }
        // Ignore other control events (error, raw, ...).
      }
    }
  } catch (e) {
    if (e && e.name === "AbortError") {
      // User clicked Kill or nav'd away. Not an error worth
      // surfacing in the output.
    } else {
      stderrText += "\n[stream error: " + (e.message || e) + "]";
    }
  }

  const dur = ((Date.now() - t0) / 1000).toFixed(2);
  document.getElementById("termDuration").textContent = dur + "s";
  overviewMetrics.execs++;

  if (slot) {
    if (!stdoutText && !stderrText) {
      _termWriteOut(slot, "(no output)");
    } else {
      _termWriteOut(slot, stdoutText +
        (stderrText ? "\n--- STDERR ---\n" + stderrText : ""));
    }
    let status = "ok";
    if (timedOut) status = "timeout";
    else if (exitCode == null || exitCode !== 0) status = "fail";
    const color = status === "ok" ? "var(--green)"
                : (status === "timeout" ? "var(--yellow,#fbbf24)"
                                        : "var(--red,#f87171)");
    slot.meta.innerHTML = "";
    const tag = document.createElement("span");
    tag.textContent = "exit " + (exitCode == null ? "?" : exitCode) +
      (timedOut ? " (timeout)" : "");
    tag.style.cssText = "color:" + color + ";font-weight:600";
    slot.meta.appendChild(tag);
    const dt = document.createElement("span");
    dt.textContent = " · " + dur + "s · stream";
    dt.style.color = "var(--text2)";
    slot.meta.appendChild(dt);
  }
}

async function runCommand(cmd) {
  const raw = cmd || termInput.value;
  const c = normalizeShellCommand(raw);
  if (!c.trim()) return;
  termInput.value = "";
  const timeout = parseInt(document.getElementById("termTimeout").value);

  const slot = _termAppendEntry(c);
  const t0 = Date.now();

  // v4.13.0: streaming exec via /v1/exec/stream when the toggle is
  // on. Falls back automatically on browsers without ReadableStream.
  const streamBox = document.getElementById("termStream");
  const wantStream = streamBox && streamBox.checked && __termStreamSupported();
  if (wantStream) {
    try {
      await _runStreamedCommand(c, timeout, slot, t0);
    } finally {
      // Save history (same shape as the buffered branch below).
      if (cmdHistory[0] !== c) {
        cmdHistory.unshift(c);
        if (cmdHistory.length > 50) cmdHistory.length = 50;
        localStorage.setItem("arena_cmd_history", JSON.stringify(cmdHistory));
        renderHistory();
      }
      const sess = document.getElementById("termSession");
      if (sess) sess.scrollTop = sess.scrollHeight;
    }
    return;
  }

  try {
    const result = await api("/v1/exec", {method: "POST", body: JSON.stringify({cmd: c, timeout})});
    const dur = ((Date.now() - t0) / 1000).toFixed(2);
    document.getElementById("termDuration").textContent = dur + "s";
    overviewMetrics.execs++;

    let outText = "";
    let status = "ok";
    let exitCode = result.exit_code != null ? result.exit_code : 0;

    if (result.ok !== undefined) {
      if (result.stdout) outText += result.stdout;
      if (result.stderr) outText += (outText ? "\n--- STDERR ---\n" : "") + result.stderr;
      if (result.timed_out) { outText += "\n[TIMEOUT]"; status = "timeout"; }
      if (!result.ok || exitCode !== 0) status = (status === "ok" ? "fail" : status);
    } else {
      outText = "Error: " + (result.error || "unknown");
      status = "fail";
    }

    if (slot) {
      _termWriteOut(slot, outText || "(no output)");
      const color = status === "ok" ? "var(--green)" : (status === "timeout" ? "var(--yellow,#fbbf24)" : "var(--red,#f87171)");
      slot.meta.innerHTML = "";
      const tag = document.createElement("span");
      tag.textContent = "exit " + exitCode;
      tag.style.cssText = "color:" + color + ";font-weight:600";
      slot.meta.appendChild(tag);
      const dt = document.createElement("span");
      dt.textContent = " · " + dur + "s";
      dt.style.color = "var(--text2)";
      slot.meta.appendChild(dt);
    }
  } catch(e) {
    if (slot) {
      _termWriteOut(slot, "Error executing command: " + (e.message || "Unknown error"));
      slot.meta.innerHTML = '<span style="color:var(--red,#f87171)">network error</span>';
    }
  }

  // Save history (newest first), de-dup latest entry
  if (cmdHistory[0] !== c) {
    cmdHistory.unshift(c);
    if (cmdHistory.length > 50) cmdHistory.length = 50;
    localStorage.setItem("arena_cmd_history", JSON.stringify(cmdHistory));
    renderHistory();
  }
  // auto-scroll on slow apps
  const sess = document.getElementById("termSession");
  if (sess) sess.scrollTop = sess.scrollHeight;
}

function clearTerminal() {
  const sess = document.getElementById("termSession");
  if (sess) sess.innerHTML = '<div style="color:var(--text2);font-style:italic">Session cleared. Ready.</div>';
  document.getElementById("termDuration").textContent = "";
}

function renderHistory() {
  const el = document.getElementById("termHistory");
  if (!el) return;
  el.innerHTML = "";
  cmdHistory.slice(0, 20).forEach((c) => {
    const span = document.createElement("span");
    span.style.cssText = "cursor:pointer;color:var(--purple);display:block;margin-bottom:3px;padding:3px 6px;border-radius:3px";
    span.textContent = c.length > 80 ? c.slice(0,80)+"…" : c;
    span.title = c;
    span.addEventListener("mouseenter", () => span.style.background = "var(--bg3)");
    span.addEventListener("mouseleave", () => span.style.background = "");
    span.addEventListener("click", () => { termInput.value = c; termInput.focus(); });
    el.appendChild(span);
  });
}
renderHistory();

// v4.13.0: gate the stream-mode checkbox on ReadableStream support.
(function _initStreamToggle() {
  const box = document.getElementById("termStream");
  if (!box) return;
  if (!__termStreamSupported()) {
    box.disabled = true;
    box.title = "Stream mode needs a browser with ReadableStream "
      + "(Chrome 43+, Firefox 65+, Safari 10.1+).";
  }
})();

function copyTermOutput() {
  const output = document.getElementById("termSession").innerText;
  copyToClipboard(output);
  const btn = document.querySelector(".copy-btn");
  const orig = btn.textContent;
  btn.textContent = "Copied!";
  setTimeout(() => { btn.textContent = orig; }, 1500);
}

async function apiQuickGet(path) {
  document.querySelectorAll(".sidebar nav a").forEach(x => x.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
  document.querySelector('[data-tab="terminal"]').classList.add("active");
  document.getElementById("tab-terminal").classList.add("active");
  const slot = _termAppendEntry("GET " + path);
  const t0 = Date.now();
  try {
    const result = await api(path);
    const dur = ((Date.now() - t0) / 1000).toFixed(1);
    document.getElementById("termDuration").textContent = dur + "s";
    if (slot) {
      _termWriteOut(slot, JSON.stringify(result, null, 2));
      slot.meta.textContent = "HTTP helper · " + dur + "s";
    }
  } catch(e) {
    if (slot) { _termWriteOut(slot, "Error fetching " + path + ": " + (e.message || "Unknown error")); slot.meta.textContent = "error"; }
  }
  cmdHistory.unshift("GET " + path);
  if (cmdHistory.length > 30) cmdHistory.length = 30;
  localStorage.setItem("arena_cmd_history", JSON.stringify(cmdHistory));
  renderHistory();
}

