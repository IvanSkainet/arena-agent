// ===== LIVE CHARTS (v3.95.0) =====
//
// Streams host metrics (CPU/RAM/Swap/Net/Disk/GPU) from the
// /v1/live-metrics/stream WebSocket and renders each series as a
// rolling sparkline in the Live tab.
//
// No external chart library -- the sparkline is a tiny Canvas 2D
// path renderer (~40 LOC) so the Dashboard preview works even
// inside the sandboxed iframe that blocks CDNs.
//
// Buffer size = 120 samples, so at 1Hz you see the last 2 minutes.

(function () {
  const BUFFER_SIZE = 120;
  const CHART_HEIGHT = 60;

  // Named color per metric so the same series always renders in
  // the same accent (helps at-a-glance recognition across the
  // grid of ~6 canvases).
  //
  // Values are resolved from CSS custom properties on the fly so
  // the palette follows any future theme swap. Falls back to the
  // hardcoded literal when the property is missing (e.g. running
  // the JS outside the Dashboard for a smoke test).
  function _cssColor(varName, fallback) {
    try {
      const v = getComputedStyle(document.documentElement)
                  .getPropertyValue(varName).trim();
      return v || fallback;
    } catch (_e) { return fallback; }
  }
  const COLORS = {
    get cpu()     { return _cssColor("--live-cpu",     "#4ade80"); },
    get memory()  { return _cssColor("--live-mem",     "#60a5fa"); },
    get swap()    { return _cssColor("--live-swap",    "#a78bfa"); },
    get net_rx()  { return _cssColor("--live-net-rx",  "#22d3ee"); },
    get net_tx()  { return _cssColor("--live-net-tx",  "#f59e0b"); },
    get disk_rd() { return _cssColor("--live-disk-rd", "#f472b6"); },
    get disk_wr() { return _cssColor("--live-disk-wr", "#f87171"); },
    get gpu()     { return _cssColor("--live-gpu",     "#84cc16"); },
    get gpu_mem() { return _cssColor("--live-gpu-mem", "#eab308"); },
  };

  // Ring buffers keyed by series name.
  const buffers = new Map();

  function pushSample(name, value) {
    let buf = buffers.get(name);
    if (!buf) {
      buf = new Array(BUFFER_SIZE).fill(null);
      buffers.set(name, buf);
    }
    buf.push(value);
    if (buf.length > BUFFER_SIZE) buf.shift();
    return buf;
  }

  function drawSparkline(canvas, buf, color, opts) {
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || canvas.width || 300;
    const cssH = canvas.clientHeight || canvas.height || CHART_HEIGHT;
    if (canvas.width !== Math.floor(cssW * dpr)) {
      canvas.width = Math.floor(cssW * dpr);
      canvas.height = Math.floor(cssH * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    // Background grid: two horizontal rules at 33/66% of the
    // sparkline height. Subtle so the data line remains dominant.
    ctx.strokeStyle = "rgba(148,163,184,0.15)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, Math.floor(cssH * 0.33) + 0.5);
    ctx.lineTo(cssW, Math.floor(cssH * 0.33) + 0.5);
    ctx.moveTo(0, Math.floor(cssH * 0.66) + 0.5);
    ctx.lineTo(cssW, Math.floor(cssH * 0.66) + 0.5);
    ctx.stroke();

    const nonNull = buf.filter(v => v !== null && !isNaN(v));
    if (!nonNull.length) return;
    // Percent-typed series get a fixed 0..100 range; throughput
    // series auto-scale to peak-in-buffer with a 5% headroom.
    let vmin, vmax;
    if (opts && opts.fixed_range) {
      vmin = opts.fixed_range[0];
      vmax = opts.fixed_range[1];
    } else {
      vmin = 0;
      vmax = Math.max(1, ...nonNull) * 1.05;
    }

    const stepX = cssW / (BUFFER_SIZE - 1);
    ctx.strokeStyle = color;
    ctx.fillStyle = color + "22";
    ctx.lineWidth = 1.5;

    // Filled area under the line.
    ctx.beginPath();
    let firstDrawn = false;
    for (let i = 0; i < buf.length; i++) {
      const v = buf[i];
      if (v === null || isNaN(v)) continue;
      const x = i * stepX;
      const y = cssH - ((v - vmin) / (vmax - vmin)) * cssH;
      if (!firstDrawn) {
        ctx.moveTo(x, cssH);
        ctx.lineTo(x, y);
        firstDrawn = true;
      } else {
        ctx.lineTo(x, y);
      }
    }
    if (firstDrawn) {
      ctx.lineTo((buf.length - 1) * stepX, cssH);
      ctx.closePath();
      ctx.fill();
    }

    // Stroke the top edge.
    ctx.beginPath();
    firstDrawn = false;
    for (let i = 0; i < buf.length; i++) {
      const v = buf[i];
      if (v === null || isNaN(v)) continue;
      const x = i * stepX;
      const y = cssH - ((v - vmin) / (vmax - vmin)) * cssH;
      if (!firstDrawn) { ctx.moveTo(x, y); firstDrawn = true; }
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  function humanBytes(n) {
    if (n === null || n === undefined || isNaN(n)) return "--";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    let v = Math.max(0, Number(n));
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    return v.toFixed(v >= 100 ? 0 : v >= 10 ? 1 : 2) + " " + units[i];
  }

  function humanRate(n) { return humanBytes(n) + "/s"; }

  function renderSnapshot(snap) {
    if (!snap || !snap.ok) return;

    // ---- CPU ----
    const cpu = snap.cpu || {};
    const cpuVal = cpu.available ? cpu.percent : null;
    const cpuBuf = pushSample("cpu", cpuVal);
    drawSparkline(document.getElementById("liveCpuChart"), cpuBuf,
                  COLORS.cpu, {fixed_range: [0, 100]});
    _setText("liveCpuValue", cpu.available ? cpu.percent.toFixed(1) + "%" : "--");
    _setText("liveCpuMeta",
             cpu.available
               ? (cpu.count_logical + " threads · load " +
                  (cpu.load_avg_1m == null ? "?" : cpu.load_avg_1m.toFixed(2)))
               : (cpu.reason || "unavailable"));

    // Per-core mini bars.
    const perCore = cpu.per_core || [];
    const perCoreBox = document.getElementById("liveCpuPerCore");
    if (perCoreBox) {
      if (!perCore.length) {
        perCoreBox.style.display = "none";
      } else {
        perCoreBox.style.display = "";
        perCoreBox.innerHTML = perCore.map((p, i) =>
          '<div class="livecore"><span class="livecore-label">' + i + '</span>' +
          '<div class="livecore-bar"><div class="livecore-fill" ' +
            'style="width:' + Math.min(100, p) + '%;background:var(--live-cpu)"></div></div>' +
          '<span class="livecore-val">' + p.toFixed(0) + '%</span></div>'
        ).join("");
      }
    }

    // ---- Memory ----
    const mem = snap.memory || {};
    const memVal = mem.available ? mem.percent : null;
    drawSparkline(document.getElementById("liveMemChart"),
                  pushSample("memory", memVal), COLORS.memory,
                  {fixed_range: [0, 100]});
    _setText("liveMemValue", mem.available ? mem.percent.toFixed(1) + "%" : "--");
    _setText("liveMemMeta",
             mem.available
               ? (humanBytes(mem.used_bytes) + " / " + humanBytes(mem.total_bytes))
               : (mem.reason || "unavailable"));

    // ---- Swap ----
    const sw = snap.swap || {};
    const swVal = sw.available ? sw.percent : null;
    drawSparkline(document.getElementById("liveSwapChart"),
                  pushSample("swap", swVal), COLORS.swap,
                  {fixed_range: [0, 100]});
    _setText("liveSwapValue", sw.available ? sw.percent.toFixed(1) + "%" : "--");
    _setText("liveSwapMeta",
             sw.available && sw.total_bytes > 0
               ? (humanBytes(sw.used_bytes) + " / " + humanBytes(sw.total_bytes))
               : (sw.available ? "no swap configured" : (sw.reason || "unavailable")));

    // ---- Network ----
    const net = snap.net || {};
    const rxVal = net.available ? net.bytes_recv_per_sec : null;
    const txVal = net.available ? net.bytes_sent_per_sec : null;
    drawSparkline(document.getElementById("liveNetRxChart"),
                  pushSample("net_rx", rxVal), COLORS.net_rx, null);
    drawSparkline(document.getElementById("liveNetTxChart"),
                  pushSample("net_tx", txVal), COLORS.net_tx, null);
    _setText("liveNetRxValue", net.available ? humanRate(net.bytes_recv_per_sec) : "--");
    _setText("liveNetTxValue", net.available ? humanRate(net.bytes_sent_per_sec) : "--");
    _setText("liveNetMeta",
             net.available
               ? ("Total: ↓ " + humanBytes(net.bytes_recv_total) +
                  " · ↑ " + humanBytes(net.bytes_sent_total))
               : (net.reason || "unavailable"));

    // ---- Disk ----
    const disk = snap.disk || {};
    const rdVal = disk.available ? disk.read_bytes_per_sec : null;
    const wrVal = disk.available ? disk.write_bytes_per_sec : null;
    drawSparkline(document.getElementById("liveDiskRdChart"),
                  pushSample("disk_rd", rdVal), COLORS.disk_rd, null);
    drawSparkline(document.getElementById("liveDiskWrChart"),
                  pushSample("disk_wr", wrVal), COLORS.disk_wr, null);
    _setText("liveDiskRdValue", disk.available ? humanRate(disk.read_bytes_per_sec) : "--");
    _setText("liveDiskWrValue", disk.available ? humanRate(disk.write_bytes_per_sec) : "--");
    _setText("liveDiskMeta",
             disk.available
               ? ("Total read " + humanBytes(disk.read_bytes_total) +
                  " · written " + humanBytes(disk.write_bytes_total))
               : (disk.reason || "unavailable"));

    // ---- GPU ----
    const gpu = snap.gpu || {};
    const gpuBox = document.getElementById("liveGpuBox");
    if (!gpuBox) return;
    if (!gpu.available) {
      gpuBox.innerHTML = '<div class="card"><div class="stat">--</div>' +
                         '<div class="label">GPU (' +
                         esc(gpu.backend || "none") + ')</div></div>';
      return;
    }
    const devices = gpu.devices || [];
    gpuBox.innerHTML = devices.map((d, idx) => {
      const utilBuf = pushSample("gpu" + idx, d.gpu_util_percent);
      const memBuf = pushSample("gpu_mem" + idx,
        d.mem_total_bytes ? (d.mem_used_bytes / d.mem_total_bytes * 100) : 0);
      return (
        '<div class="live-card">' +
          '<div class="live-header">' +
            '<span class="live-label">GPU ' + idx + ' · ' + esc(d.name) + '</span>' +
            '<span class="live-value" style="color:var(--live-gpu)">' +
              d.gpu_util_percent + '%</span>' +
          '</div>' +
          '<canvas class="live-canvas" id="liveGpuUtilChart' + idx +
                  '" height="' + CHART_HEIGHT + '"></canvas>' +
          '<div class="live-meta">Memory: ' + humanBytes(d.mem_used_bytes) +
            ' / ' + humanBytes(d.mem_total_bytes) +
            ' · ' + d.temperature_c + '°C</div>' +
          '<canvas class="live-canvas" id="liveGpuMemChart' + idx +
                  '" height="' + CHART_HEIGHT + '"></canvas>' +
        '</div>'
      );
    }).join("");
    // Draw after DOM update.
    devices.forEach((d, idx) => {
      drawSparkline(document.getElementById("liveGpuUtilChart" + idx),
                    buffers.get("gpu" + idx), COLORS.gpu,
                    {fixed_range: [0, 100]});
      drawSparkline(document.getElementById("liveGpuMemChart" + idx),
                    buffers.get("gpu_mem" + idx), COLORS.gpu_mem,
                    {fixed_range: [0, 100]});
    });
  }

  function _setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  // ------- WebSocket lifecycle -------

  let ws = null;
  let pollTimer = null;
  let statusEl = null;

  function _updateStatus(state, extra) {
    if (!statusEl) statusEl = document.getElementById("liveStatus");
    if (!statusEl) return;
    // Match on the CSS variable so theme swaps affect the dot too.
    const map = {
      connecting: {cssVar: "--live-net-tx",  text: "connecting…"},
      connected:  {cssVar: "--live-cpu",     text: "streaming (WebSocket)"},
      polling:    {cssVar: "--live-mem",     text: "polling (1Hz HTTP fallback)"},
      error:      {cssVar: "--live-disk-wr", text: "error"},
      stopped:    {cssVar: "--live-text-muted", text: "stopped"},
    };
    const s = map[state] || {cssVar: "--live-text-muted", text: state};
    statusEl.innerHTML = '<span class="live-dot" style="background:var(' +
                         s.cssVar + ')"></span> ' + s.text +
                         (extra ? " — " + esc(extra) : "");
  }

  function _wsUrl() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + window.location.host + "/v1/live-metrics/stream";
  }

  async function _pollOnce() {
    try {
      const r = await apiGet("/v1/live-metrics");
      if (r && r.ok) renderSnapshot(r);
    } catch (e) {
      _updateStatus("error", String(e));
    }
  }

  function _startPollFallback() {
    _updateStatus("polling");
    if (pollTimer) clearInterval(pollTimer);
    _pollOnce();
    pollTimer = setInterval(_pollOnce, 1000);
  }

  function _stopPollFallback() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  window.startLiveCharts = function () {
    _updateStatus("connecting");
    // Server-side WebSocket auth: we can't set an Authorization
    // header on WebSocket from the browser, so pass the token via
    // subprotocol negotiation would be ideal -- but our
    // require_auth accepts ?token=... query as a documented
    // fallback. Confirm with tests before shipping.
    let url = _wsUrl();
    if (window.ARENA_TOKEN) {
      url += "?token=" + encodeURIComponent(window.ARENA_TOKEN);
    }
    try {
      ws = new WebSocket(url);
    } catch (e) {
      _startPollFallback();
      return;
    }
    ws.onopen = function () { _updateStatus("connected"); };
    ws.onmessage = function (ev) {
      try { renderSnapshot(JSON.parse(ev.data)); }
      catch (_e) { /* ignore malformed frame */ }
    };
    ws.onerror = function () { /* onclose handles fallback */ };
    ws.onclose = function () {
      // If we never got a message, the server likely refused the
      // WebSocket upgrade (auth). Fall back to polling.
      if (buffers.size === 0) {
        _startPollFallback();
      } else {
        _updateStatus("stopped");
      }
    };
  };

  window.stopLiveCharts = function () {
    _updateStatus("stopped");
    if (ws) { try { ws.close(); } catch (_) {} ws = null; }
    _stopPollFallback();
  };
})();
