// ===== TRANSPORTS TAB =====
//
// Unified control surface for every transport (Tailscale,
// ZeroTier, cloudflared, ngrok). Before this release, controls
// were scattered:
//   - Settings tab: start/stop for TS + CF
//   - Doctor tab: TS diagnostic (read-only)
//   - ZeroTier Central tab: ZT network + member admin
//   - terminal: ngrok curl-only, no UI at all
// Now one place, four cards, one refresh, one auto-refresh,
// one meta line -- same visual language as Audit / Overview /
// Proposals redesigns.
//
// Data sources per transport:
//   /v1/agent/config              -- reachable_count + per-URL list
//   /v1/tailscale/funnel/status   -- TS installed/active/url
//   /v1/cloudflared/tunnel/status -- CF installed/active/url/log
//   /v1/ngrok/tunnel/status       -- NG installed/active/url/log
//   /v1/zerotier/status           -- ZT installed/reachable
//
// Start/stop endpoints per transport:
//   POST /v1/tailscale/funnel/start|stop
//   POST /v1/cloudflared/tunnel/start|stop
//   POST /v1/ngrok/tunnel/start|stop
//   ZT does not have a start/stop verb -- membership is managed
//   through the ZeroTier Central tab; we surface a link there.
//
// Backward compat: this module does NOT redefine any existing
// function from Settings' 17-settings-status.js or 29-tunnels.js.
// Old scripts / operators using tsFunnelToggle() / cfFunnelToggle()
// directly keep working. This is a new surface, not a
// replacement (yet). Settings shows a deprecation notice as of
// v4.37.0; hard removal follows in a later release once we've
// let operators migrate.

(function () {
  "use strict";

  var _timer = null;
  var _lastError = null;
  var _lastRefreshAt = null;
  var _lastDurationMs = null;
  var _lastState = {};  // { transport: { active, url, log, ... } }

  var TRANSPORTS = ["tailscale", "zerotier", "cloudflared", "ngrok"];
  // Transports that have a real autostart marker. ZeroTier
  // absent by design -- membership is long-lived across bridge
  // restarts, so there is nothing to autostart for it.
  var AUTOSTART_TRANSPORTS = ["tailscale", "cloudflared", "ngrok"];

  function _q(id) { return document.getElementById(id); }

  function _fmtTime(d) {
    if (!(d instanceof Date)) return "--:--:--";
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function _escape(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
                    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  function _pulseDot(err) {
    var dot = _q("transportsRefreshDot");
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
    var meta = _q("transportsMeta");
    if (!meta) return;
    var upCount = 0, downCount = 0;
    TRANSPORTS.forEach(function (t) {
      var s = _lastState[t];
      if (!s) return;
      if (s.active) upCount++;
      else downCount++;
    });
    var chips = '<span class="chip up">' + upCount + ' up</span>' +
                '<span class="chip down">' + downCount + ' down</span>';
    var parts = [chips, "last refresh " + _fmtTime(_lastRefreshAt)];
    if (_lastDurationMs !== null) parts.push(_lastDurationMs.toFixed(0) + " ms");
    if (_timer !== null) {
      var sel = _q("transportsInterval");
      parts.push("auto every " + (sel ? sel.value : "15") + "s");
    } else {
      parts.push("manual");
    }
    if (_lastError) parts.push("last error: " + _escape(_lastError));
    meta.innerHTML = parts.map(function (p, i) {
      return (i === 0 ? "" : '<span class="sep">·</span>') + p;
    }).join("");
  }

  function _renderCard(name, snap) {
    var badge = _q("tr-badge-" + name);
    var urlEl = _q("tr-url-" + name);
    var installedEl = _q("tr-installed-" + name);
    var hintEl = _q("tr-hint-" + name);
    var logEl = _q("tr-log-" + name);

    if (!badge || !urlEl || !installedEl) return;

    var active = !!snap.active;
    var installed = ("installed" in snap) ? !!snap.installed : true;
    var url = snap.url || snap.public_url || "";

    // Badge state
    badge.classList.remove("up", "down", "err", "warn");
    if (!installed) {
      badge.classList.add("warn");
      badge.textContent = "not installed";
    } else if (snap.error_code === "needs_authtoken") {
      badge.classList.add("err");
      badge.textContent = "auth needed";
    } else if (active) {
      badge.classList.add("up");
      badge.textContent = "up";
    } else {
      badge.classList.add("down");
      badge.textContent = "down";
    }

    urlEl.textContent = url || "—";
    urlEl.title = url || "";

    installedEl.textContent = installed
      ? (snap.version ? "yes (v" + snap.version + ")" : "yes")
      : "no";

    // Hint / error surface -- only shown when there's something to say.
    if (hintEl) {
      var hintText = "";
      var isErr = false;
      if (!installed && snap.update_hint) {
        hintText = snap.update_hint;
      } else if (snap.hint) {
        hintText = snap.hint;
        isErr = true;
      } else if (snap.error) {
        hintText = snap.error;
        isErr = true;
      }
      if (hintText) {
        hintEl.textContent = hintText;
        hintEl.className = "tr-hint" + (isErr ? " err" : "");
        hintEl.style.display = "";
      } else {
        hintEl.style.display = "none";
      }
    }

    // Log tail -- only for CF + NG which stream stdout.
    if (logEl) {
      var log = snap.log || [];
      if (Array.isArray(log) && log.length > 0) {
        logEl.textContent = log.slice(-6).join("\n");
      } else {
        logEl.textContent = "";
      }
    }
  }

  // v4.38.0: paint the autostart checkbox + env-override pill
  // from the /v1/autostart snapshot. Called from loadTransports
  // once per autostart-capable transport.
  function _renderAutostart(name, state) {
    var box = _q("tr-autostart-" + name);
    var envPill = _q("tr-env-" + name);
    if (!box) return;
    var enabled = !!state.enabled;
    var envOverride = !!state.env_override;
    box.checked = enabled;
    // env-override forces the checkbox on and makes it read-only.
    // The user can't turn autostart off from the UI without
    // unsetting the env var in the service unit.
    box.disabled = envOverride;
    if (envPill) {
      if (envOverride) envPill.classList.add("on");
      else envPill.classList.remove("on");
    }
  }

  async function transportAutostartToggle(name, enabled) {
    var box = _q("tr-autostart-" + name);
    var hintEl = _q("tr-hint-" + name);
    try {
      var d = await window.api("/v1/autostart/" + name, {
        method: "POST",
        body: JSON.stringify({enabled: !!enabled}),
      });
      if (d && d.ok) {
        // Re-render from the fresh state -- picks up env-override
        // situations where the requested change silently didn't
        // stick.
        _renderAutostart(name, (d.state) || {});
        if (d.env_override_warning && hintEl) {
          hintEl.className = "tr-hint";
          hintEl.textContent = d.env_override_warning;
          hintEl.style.display = "";
        }
      } else {
        // Rollback checkbox to what the server thinks is truth.
        if (box) box.checked = !enabled;
        if (hintEl) {
          hintEl.className = "tr-hint err";
          hintEl.textContent = "Autostart toggle failed: " +
            _escape((d && d.error) || "unknown");
          hintEl.style.display = "";
        }
      }
    } catch (e) {
      if (box) box.checked = !enabled;
      if (hintEl) {
        hintEl.className = "tr-hint err";
        hintEl.textContent = "Network error: " + _escape(String(e && e.message || e));
        hintEl.style.display = "";
      }
    }
  }
  window.transportAutostartToggle = transportAutostartToggle;

  async function loadTransports() {
    var t0 = performance.now();
    _pulseDot(false);
    _lastError = null;
    try {
      // Kick off all snapshots in parallel -- each transport has
      // its own /status endpoint. /v1/agent/config gives us the
      // authoritative URL list (which the individual /status
      // endpoints can miss when a URL was set by an out-of-band
      // process).
      var results = await Promise.all([
        window.api("/v1/agent/config"),
        window.api("/v1/tailscale/funnel/status"),
        window.api("/v1/cloudflared/tunnel/status"),
        window.api("/v1/ngrok/tunnel/status"),
        window.api("/v1/zerotier/status"),
        // v4.38.0: unified autostart snapshot.
        window.api("/v1/autostart"),
      ]);
      var cfg = results[0] || {};
      var urlByProv = {};
      (cfg.urls || []).forEach(function (u) {
        urlByProv[u.provider] = u.url;
      });

      var tsRaw = results[1] || {};
      var cfRaw = results[2] || {};
      var ngRaw = results[3] || {};
      var ztRaw = results[4] || {};
      var autoRaw = results[5] || {};
      var autoByTransport = (autoRaw && autoRaw.transports) || {};

      // Tailscale
      var tsSnap = {
        active: !!(tsRaw.active || urlByProv.tailscale),
        installed: tsRaw.installed !== false,
        version: tsRaw.version || null,
        url: tsRaw.url || urlByProv.tailscale || "",
      };

      // cloudflared
      var cfSnap = {
        active: !!cfRaw.active,
        installed: !!cfRaw.installed,
        version: cfRaw.version || null,
        url: cfRaw.url || urlByProv.cloudflared || "",
        log: cfRaw.log || [],
        update_hint: cfRaw.installed ? null : cfRaw.update_hint,
      };

      // ngrok -- has v4.36.0 classified error surface.
      var ngSnap = {
        active: !!ngRaw.active,
        installed: !!ngRaw.installed,
        version: ngRaw.version || null,
        url: ngRaw.url || urlByProv.ngrok || "",
        log: ngRaw.log || [],
        update_hint: ngRaw.installed ? null : ngRaw.update_hint,
      };

      // ZeroTier -- no start/stop, we just show reachable/URL.
      var ztSnap = {
        active: !!(urlByProv.zerotier || (ztRaw.zerotier && ztRaw.zerotier.online)),
        installed: ztRaw.available !== false,
        version: (ztRaw.zerotier && ztRaw.zerotier.version) || null,
        url: urlByProv.zerotier || "",
      };

      _lastState = {
        tailscale: tsSnap,
        zerotier: ztSnap,
        cloudflared: cfSnap,
        ngrok: ngSnap,
      };

      TRANSPORTS.forEach(function (t) { _renderCard(t, _lastState[t]); });
      // v4.38.0: paint per-transport autostart checkbox + env-pill
      // for every transport that has a start/stop verb.
      AUTOSTART_TRANSPORTS.forEach(function (t) {
        _renderAutostart(t, autoByTransport[t] || {});
      });
    } catch (e) {
      _lastError = String(e && e.message || e);
      _pulseDot(true);
    }
    _lastDurationMs = performance.now() - t0;
    _lastRefreshAt = new Date();
    _renderMeta();
  }
  window.loadTransports = loadTransports;

  // ------------------------------------------------------------------
  // start / stop
  // ------------------------------------------------------------------
  var _ROUTE = {
    tailscale:   "/v1/tailscale/funnel/",
    cloudflared: "/v1/cloudflared/tunnel/",
    ngrok:       "/v1/ngrok/tunnel/",
    // ZT deliberately absent -- no start/stop verb.
  };

  async function transportStart(name) {
    var route = _ROUTE[name];
    if (!route) {
      alert(name + " has no start endpoint. Use the ZeroTier tab to " +
            "manage networks.");
      return;
    }
    var hintEl = _q("tr-hint-" + name);
    if (hintEl) {
      hintEl.textContent = "Starting… (ngrok cold start may take up to 45s)";
      hintEl.className = "tr-hint";
      hintEl.style.display = "";
    }
    try {
      // Longer timeout for ngrok / cloudflared because they need
      // to negotiate an edge URL. The api() helper uses fetch's
      // default (no timeout).
      var d = await window.api(route + "start", {method: "POST"});
      if (d && d.ok) {
        // Immediate reload so the badge flips to "up" without the
        // operator having to hit Reload manually.
        await loadTransports();
      } else {
        if (hintEl) {
          hintEl.className = "tr-hint err";
          hintEl.textContent = _escape((d && (d.hint || d.error)) ||
                                       "start failed");
        }
      }
    } catch (e) {
      if (hintEl) {
        hintEl.className = "tr-hint err";
        hintEl.textContent = "Network error: " + _escape(String(e && e.message || e));
      }
    }
  }
  window.transportStart = transportStart;

  async function transportStop(name) {
    var route = _ROUTE[name];
    if (!route) return;
    try {
      await window.api(route + "stop", {method: "POST"});
      await loadTransports();
    } catch (e) {
      var hintEl = _q("tr-hint-" + name);
      if (hintEl) {
        hintEl.className = "tr-hint err";
        hintEl.textContent = "Stop failed: " + _escape(String(e && e.message || e));
        hintEl.style.display = "";
      }
    }
  }
  window.transportStop = transportStop;

  function transportCopyUrl(name) {
    var snap = _lastState[name] || {};
    var url = snap.url;
    if (!url) {
      alert(name + " has no URL to copy.");
      return;
    }
    if (typeof window.copyToClipboard === "function") {
      window.copyToClipboard(url);
    } else {
      // Fallback if the shared helper is missing.
      navigator.clipboard.writeText(url).catch(function () {});
    }
  }
  window.transportCopyUrl = transportCopyUrl;

  async function transportsStartAll() {
    for (var i = 0; i < TRANSPORTS.length; i++) {
      var t = TRANSPORTS[i];
      if (t in _ROUTE) {
        // fire-and-forget so a slow ngrok doesn't block cloudflared
        transportStart(t);
      }
    }
  }
  window.transportsStartAll = transportsStartAll;

  async function transportsStopAll() {
    for (var i = 0; i < TRANSPORTS.length; i++) {
      var t = TRANSPORTS[i];
      if (t in _ROUTE) {
        await transportStop(t);
      }
    }
  }
  window.transportsStopAll = transportsStopAll;

  // ------------------------------------------------------------------
  // auto-refresh timer (mirrors Overview / Proposals toolbars)
  // ------------------------------------------------------------------
  function _rearmTimer() {
    if (_timer !== null) {
      window.clearInterval(_timer);
      _timer = null;
    }
    var box = _q("transportsAuto");
    if (!box || !box.checked) { _renderMeta(); return; }
    var sel = _q("transportsInterval");
    var seconds = sel ? Math.max(1, parseInt(sel.value, 10) || 15) : 15;
    _timer = window.setInterval(function () {
      loadTransports();
    }, seconds * 1000);
    _renderMeta();
  }

  function _wireControls() {
    var box = _q("transportsAuto");
    var sel = _q("transportsInterval");
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

  Object.defineProperty(window, "__transportsTab", {
    value: {
      load: loadTransports,
      start: transportStart,
      stop: transportStop,
      startAll: transportsStartAll,
      stopAll: transportsStopAll,
      rearmTimer: _rearmTimer,
      renderCard: _renderCard,
      renderMeta: _renderMeta,
      getState: function () {
        return {
          lastError: _lastError,
          lastRefreshAt: _lastRefreshAt,
          lastDurationMs: _lastDurationMs,
          hasTimer: _timer !== null,
          transports: _lastState,
        };
      },
    },
    enumerable: false,
    writable: false,
  });
})();
