// ===== RELAY TAB (v4.166.0) =====
//
// A mailbox between the operator and the agent, rendered as a chat.
//
// What it deliberately does NOT do: start an agent session. arena.ai has
// no public API and its Terms of Use forbid programmatic access (§5(vi))
// and automated agents against the Service (§5(vii)). So the UI never
// implies someone is listening -- the status line says so explicitly,
// and a message sent to nobody is labelled "queued", not "delivered".
// Lying in the reassuring direction is exactly what bug #66 did.
//
// Backed by the same endpoints as bin/arena-relay, so a message typed
// here is visible in the terminal and vice versa.

let _relayTimer = null;
let _relaySeen = new Set();      // message ids already rendered
let _relayHistory = [];          // {who, body, at}

function _relayEsc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _relayTime(epoch) {
  if (!epoch) return "";
  try { return new Date(epoch * 1000).toLocaleTimeString(); } catch (_) { return ""; }
}

function _relayRender() {
  const log = document.getElementById("relayLog");
  const empty = document.getElementById("relayEmpty");
  if (!log) return;
  if (!_relayHistory.length) {
    if (empty) empty.style.display = "";
    return;
  }
  if (empty) empty.style.display = "none";
  // Keep the scroll pinned to the bottom only when the reader is already
  // there; yanking the view while somebody scrolls back is hostile.
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.querySelectorAll(".rl-msg").forEach((n) => n.remove());
  for (const m of _relayHistory) {
    const div = document.createElement("div");
    div.className = "rl-msg " + m.who;
    const who = m.who === "me" ? "you" : (m.who === "sys" ? "" : (m.sender || "agent"));
    div.innerHTML = (who ? '<span class="rl-meta">' + _relayEsc(who) + " · "
                            + _relayEsc(_relayTime(m.at)) + "</span>" : "")
                    + _relayEsc(m.body);
    log.appendChild(div);
  }
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function _relayPush(who, body, at, sender) {
  _relayHistory.push({who, body, at: at || (Date.now() / 1000), sender});
  if (_relayHistory.length > 300) _relayHistory = _relayHistory.slice(-300);
  _relayRender();
}

async function relayRefresh() {
  try {
    const st = await api("/v1/relay/status");
    const dot = document.getElementById("relayDot");
    const state = document.getElementById("relayPollState");
    const info = document.getElementById("relayQueueInfo");
    const badge = document.getElementById("relayDepthBadge");
    if (dot) dot.className = "rl-dot " + (st.agent_polling ? "on" : "off");
    if (state) {
      // Say plainly whether anyone is there. "Idle" is the honest word
      // when the last poll was minutes ago.
      state.textContent = st.agent_polling
        ? "an agent is listening"
        : (st.last_poll_age_s == null
            ? "no agent has ever polled"
            : "idle (last poll " + Math.round(st.last_poll_age_s) + "s ago)");
    }
    if (info) {
      info.textContent = st.inbox_depth + " waiting · " + st.reply_depth + " unread";
    }
    if (badge) badge.textContent = st.inbox_depth;

    const res = await api("/v1/relay/replies?wait=0");
    for (const r of (res.replies || [])) {
      if (_relaySeen.has(r.id)) continue;
      _relaySeen.add(r.id);
      _relayPush("them", r.body, r.created_at, r.sender);
    }
  } catch (e) {
    const state = document.getElementById("relayPollState");
    if (state) state.textContent = "bridge unreachable";
  }
}

async function relaySend() {
  const input = document.getElementById("relayInput");
  const hint = document.getElementById("relaySendHint");
  const btn = document.getElementById("relaySendBtn");
  if (!input) return;
  const body = (input.value || "").trim();
  if (!body) return;
  if (btn) btn.disabled = true;
  try {
    const res = await api("/v1/relay/send", {
      method: "POST",
      body: JSON.stringify({body, sender: "operator"}),
    });
    if (!res.ok) {
      if (hint) hint.textContent = "not sent: " + (res.error || "unknown error");
      return;
    }
    input.value = "";
    _relayPush("me", body, Date.now() / 1000);
    if (hint) {
      hint.textContent = res.agent_polling
        ? "delivered — an agent is polling"
        : "queued — nobody is polling right now (" + res.inbox_depth
          + " waiting). It will be read when a session starts.";
    }
    relayRefresh();
  } catch (e) {
    if (hint) hint.textContent = "not sent: " + (e.message || "bridge unreachable");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function startRelay() {
  relayRefresh();
  stopRelay();
  _relayTimer = setInterval(() => {
    const auto = document.getElementById("relayAuto");
    if (!auto || auto.checked) relayRefresh();
  }, 4000);
  const input = document.getElementById("relayInput");
  if (input && !input._relayBound) {
    input._relayBound = true;
    input.addEventListener("keydown", (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
        ev.preventDefault();
        relaySend();
      }
    });
  }
}

function stopRelay() {
  if (_relayTimer) { clearInterval(_relayTimer); _relayTimer = null; }
}
