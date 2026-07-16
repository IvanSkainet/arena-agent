// ===== PROPOSALS TAB =====
//
// UI over the agent-driven change proposal endpoints:
//     GET  /v1/admin/proposal/list
//     GET  /v1/admin/proposal/status?id=<full_id>
//     POST /v1/admin/proposal/submit  {title, rationale, diff}
//
// The endpoints themselves have been shipping since v4.19.0 (with
// bugfixes in v4.20.0). Until now they were curl-only -- this
// module is the first UI on top so operators can browse the
// proposal ledger without leaving the dashboard.
//
// Design choices:
//   * Fetches through window.api() so bearer auth is uniform.
//   * Auto-refresh toolbar matches the Audit + Overview pattern
//     established in the redesign arc.
//   * Row-click expands a detail row underneath (same pattern the
//     Audit tab uses) showing rationale + tests_tail + copy
//     buttons for branch / request_id.
//   * Submit form is collapsible so the table stays the primary
//     surface. Result banner reports ok/error inline.
//
// Fail-soft rules identical to other tabs: any fetch error keeps
// the last-known state on screen; toolbar meta line reports the
// error so users know why nothing is moving.

(function () {
  "use strict";

  var _timer = null;
  var _lastError = null;
  var _lastRefreshAt = null;
  var _lastDurationMs = null;
  var _lastProposals = [];

  function _q(id) { return document.getElementById(id); }

  function _fmtTime(d) {
    if (!(d instanceof Date)) return "--:--:--";
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function _fmtAge(iso) {
    if (!iso) return "--";
    var t = Date.parse(iso);
    if (!isFinite(t)) return "--";
    var sec = Math.max(0, (Date.now() - t) / 1000);
    if (sec < 60) return sec.toFixed(0) + "s";
    if (sec < 3600) return (sec / 60).toFixed(0) + "m";
    if (sec < 86400) return (sec / 3600).toFixed(1) + "h";
    return (sec / 86400).toFixed(1) + "d";
  }

  function _short(id) {
    return (typeof id === "string") ? id.slice(0, 8) : "";
  }

  function _escape(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function _pulseDot(err) {
    var dot = _q("proposalsRefreshDot");
    if (!dot) return;
    dot.classList.remove("on", "err");
    void dot.offsetWidth;
    dot.classList.add(err ? "err" : "on");
    if (_timer === null) {
      window.setTimeout(function () {
        if (dot) dot.classList.remove("on", "err");
      }, 1500);
    }
  }

  function _renderMeta() {
    var meta = _q("proposalsMeta");
    if (!meta) return;
    var counts = { passed: 0, failed: 0, pending: 0, running: 0, other: 0 };
    _lastProposals.forEach(function (p) {
      var st = (p.state || "").toLowerCase();
      if (counts.hasOwnProperty(st)) counts[st]++;
      else counts.other++;
    });
    var chips = "";
    ["passed", "failed", "pending", "running"].forEach(function (k) {
      if (counts[k] > 0) {
        chips += '<span class="chip ' + k + '">' + counts[k] + " " + k + "</span>";
      }
    });
    var parts = [];
    parts.push("Total " + _lastProposals.length);
    if (chips) parts.push(chips);
    parts.push("last refresh " + _fmtTime(_lastRefreshAt));
    if (_lastDurationMs !== null) parts.push(_lastDurationMs.toFixed(0) + " ms");
    if (_timer !== null) {
      var sel = _q("proposalsInterval");
      var iv = sel ? sel.value : "15";
      parts.push("auto every " + iv + "s");
    } else {
      parts.push("manual");
    }
    if (_lastError) parts.push("last error: " + _escape(_lastError));
    meta.innerHTML = parts.map(function (p, i) {
      return (i === 0 ? "" : '<span class="sep">·</span>') + p;
    }).join("");
  }

  function _renderTable(proposals) {
    var tbody = _q("proposalsTbody");
    if (!tbody) return;
    tbody.innerHTML = "";
    if (!proposals || proposals.length === 0) {
      var tr = document.createElement("tr");
      var td = document.createElement("td");
      td.colSpan = 6;
      td.className = "pr-empty";
      td.textContent = "No proposals yet. Submit one with the ➕ New button above.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    // Newest first: JSONL ledger is append-only; the list endpoint
    // already returns newest-first (verified by the v4.20.0 dogfood)
    // so we preserve order.
    proposals.forEach(function (p, idx) {
      var mainRow = document.createElement("tr");
      mainRow.className = "pr-row";
      mainRow.dataset.rid = p.request_id || "";

      var state = String(p.state || "?").toLowerCase();
      var badgeCls = "st-badge " + (
        ["passed","failed","pending","running","rejected","applied"].indexOf(state) >= 0
          ? state : "other"
      );
      mainRow.innerHTML =
        '<td><code>' + _escape(_short(p.request_id)) + '</code></td>' +
        '<td>' + _escape(p.title || "(no title)") + '</td>' +
        '<td><span class="' + badgeCls + '">' + _escape(state) + '</span></td>' +
        '<td><code>' + _escape(p.branch || "--") + '</code></td>' +
        '<td>' + _escape(_fmtAge(p.updated_at_iso || p.submitted_at_iso)) + '</td>' +
        '<td>' +
          '<button class="sm" onclick="event.stopPropagation();copyToClipboard(\'' +
            _escape(p.request_id || "") + '\')">Copy ID</button>' +
        '</td>';

      var detailRow = document.createElement("tr");
      detailRow.className = "pr-detail-row";
      var detailTd = document.createElement("td");
      detailTd.colSpan = 6;
      detailTd.innerHTML = _renderDetail(p);
      detailRow.appendChild(detailTd);

      mainRow.addEventListener("click", function () {
        detailRow.classList.toggle("open");
      });

      tbody.appendChild(mainRow);
      tbody.appendChild(detailRow);
    });
  }

  function _renderDetail(p) {
    var rationale = p.rationale || "(no rationale)";
    var testsTail = p.tests_tail || "(no test output captured yet)";
    var reason = p.reason || null;
    var pushUrl = p.push_url || null;
    var sha = p.diff_sha256 || "--";
    var diffBytes = (typeof p.diff_bytes === "number") ? p.diff_bytes : 0;

    var html = "";
    html += '<div class="pr-detail-block"><h4>Metadata</h4>' +
      '<div style="font-size:11px;color:var(--text2)">' +
      'request_id <code>' + _escape(p.request_id || "") + '</code>' +
      ' · client <code>' + _escape(p.client || "") + '</code>' +
      ' · diff ' + diffBytes + ' bytes · sha256 <code>' + _escape(sha.slice(0, 12)) + '…</code>' +
      ' · exit_code ' + _escape(p.exit_code === undefined ? "--" : p.exit_code) +
      '</div></div>';

    html += '<div class="pr-detail-block"><h4>Rationale</h4>' +
      '<div class="pr-body">' + _escape(rationale) + '</div></div>';

    if (reason) {
      html += '<div class="pr-detail-block"><h4>State reason</h4>' +
        '<div class="pr-body">' + _escape(reason) + '</div></div>';
    }

    html += '<div class="pr-detail-block"><h4>Test output tail</h4>' +
      '<div class="pr-body">' + _escape(testsTail) + '</div></div>';

    var actions = '';
    if (pushUrl) {
      actions += '<a href="' + _escape(pushUrl) +
        '" target="_blank" rel="noreferrer"><button class="info sm">↗ Open push URL</button></a>';
    }
    actions += '<button class="sm" onclick="copyToClipboard(\'' +
      _escape(p.branch || "") + '\')">Copy branch</button>';
    actions += '<button class="sm" onclick="copyToClipboard(\'' +
      _escape(p.request_id || "") + '\')">Copy full ID</button>';
    html += '<div class="pr-detail-actions">' + actions + '</div>';

    return html;
  }

  async function loadProposals() {
    var t0 = performance.now();
    _pulseDot(false);
    try {
      var d = await window.api("/v1/admin/proposal/list");
      _lastProposals = Array.isArray(d && d.proposals) ? d.proposals : [];
      _lastError = null;
      _renderTable(_lastProposals);
    } catch (e) {
      _lastError = String(e && e.message || e);
      _pulseDot(true);
    }
    _lastDurationMs = performance.now() - t0;
    _lastRefreshAt = new Date();
    _renderMeta();
  }
  window.loadProposals = loadProposals;

  // ------------------------------------------------------------------
  // submit form
  // ------------------------------------------------------------------
  function toggleProposalForm() {
    var form = _q("proposalsForm");
    if (!form) return;
    form.classList.toggle("on");
  }
  window.toggleProposalForm = toggleProposalForm;

  async function submitProposal() {
    var titleEl = _q("prTitle");
    var ratEl = _q("prRationale");
    var diffEl = _q("prDiff");
    var resEl = _q("prFormResult");
    var btn = _q("prSubmitBtn");
    if (!titleEl || !ratEl || !diffEl || !resEl) return;

    var body = {
      title: (titleEl.value || "").trim(),
      rationale: (ratEl.value || "").trim(),
      diff: diffEl.value || "",
    };
    if (!body.title) {
      resEl.className = "pr-form-result err";
      resEl.textContent = "Title required.";
      return;
    }
    if (!body.diff.trim()) {
      resEl.className = "pr-form-result err";
      resEl.textContent = "Diff cannot be empty.";
      return;
    }
    if (btn) btn.disabled = true;
    resEl.className = "pr-form-result";
    resEl.textContent = "Submitting…";
    try {
      var d = await window.api("/v1/admin/proposal/submit", {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (d && d.ok) {
        resEl.className = "pr-form-result ok";
        resEl.textContent = "Submitted -- request_id " +
          (d.request_id || (d.proposal && d.proposal.request_id) || "?") +
          " -- reload to watch its state transition.";
        titleEl.value = "";
        ratEl.value = "";
        diffEl.value = "";
        // Auto-reload so the new row appears immediately.
        loadProposals();
      } else {
        resEl.className = "pr-form-result err";
        resEl.textContent = "Bridge rejected proposal: " +
          _escape((d && (d.error || d.reason)) || "unknown reason");
      }
    } catch (e) {
      resEl.className = "pr-form-result err";
      resEl.textContent = "Network / submit failed: " + _escape(String(e && e.message || e));
    } finally {
      if (btn) btn.disabled = false;
    }
  }
  window.submitProposal = submitProposal;

  // ------------------------------------------------------------------
  // auto-refresh timer (mirrors Overview toolbar)
  // ------------------------------------------------------------------
  function _rearmTimer() {
    if (_timer !== null) {
      window.clearInterval(_timer);
      _timer = null;
    }
    var box = _q("proposalsAuto");
    if (!box || !box.checked) { _renderMeta(); return; }
    var sel = _q("proposalsInterval");
    var seconds = sel ? Math.max(1, parseInt(sel.value, 10) || 15) : 15;
    _timer = window.setInterval(function () {
      loadProposals();
    }, seconds * 1000);
    _renderMeta();
  }

  function _wireControls() {
    var box = _q("proposalsAuto");
    var sel = _q("proposalsInterval");
    if (box) box.addEventListener("change", _rearmTimer);
    if (sel) sel.addEventListener("change", _rearmTimer);
  }

  function _init() {
    _wireControls();
    _renderMeta();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", _init);
  } else {
    _init();
  }

  Object.defineProperty(window, "__proposalsTab", {
    value: {
      load: loadProposals,
      submit: submitProposal,
      toggleForm: toggleProposalForm,
      rearmTimer: _rearmTimer,
      renderTable: _renderTable,
      renderMeta: _renderMeta,
      getState: function () {
        return {
          lastError: _lastError,
          lastRefreshAt: _lastRefreshAt,
          lastDurationMs: _lastDurationMs,
          hasTimer: _timer !== null,
          proposals: _lastProposals,
        };
      },
    },
    enumerable: false,
    writable: false,
  });
})();
