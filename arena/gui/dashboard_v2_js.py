"""JavaScript for /gui/v2 dashboard."""
from __future__ import annotations

DASHBOARD_V2_JS = r"""const BRIDGE = location.origin;
const TOKEN = new URLSearchParams(location.search).get('token') || '';
let ws = null;
let reconnectDelay = 1000;

function fmt(s) {
  if (s < 60) return s.toFixed(0) + 's';
  if (s < 3600) return (s/60).toFixed(1) + 'm';
  return (s/3600).toFixed(1) + 'h';
}

function fmtMs(ms) {
  if (ms < 1) return (ms*1000).toFixed(0) + 'us';
  if (ms < 1000) return ms.toFixed(1) + 'ms';
  return (ms/1000).toFixed(2) + 's';
}

function setVal(id, val, cls) {
  const el = document.getElementById(id);
  if (el) { el.textContent = val; el.className = 'value' + (cls ? ' ' + cls : ''); }
}

function setBar(id, pct, cls) {
  const el = document.getElementById(id);
  if (el) { el.style.width = Math.min(pct, 100) + '%'; el.className = 'bar ' + (cls || 'blue'); }
}

function addEvent(type, data) {
  const list = document.getElementById('eventsList');
  if (!list) return;
  const div = document.createElement('div');
  div.className = 'event';
  const now = new Date().toLocaleTimeString();
  div.innerHTML = '<span class="time">' + now + '</span> <span class="type">' + type + '</span> ' +
                  (typeof data === 'object' ? JSON.stringify(data).substring(0, 100) : String(data).substring(0, 100));
  list.insertBefore(div, list.firstChild);
  if (list.children.length > 50) list.removeChild(list.lastChild);
}

async function pollMetrics() {
  try {
    const h = TOKEN ? {'Authorization': 'Bearer ' + TOKEN} : {};
    const [metricsR, watchdogR, statusR, alertsR] = await Promise.all([
      fetch(BRIDGE + '/metrics', {headers: h}),
      fetch(BRIDGE + '/v1/watchdog', {headers: h}),
      fetch(BRIDGE + '/v1/status', {headers: h}),
      fetch(BRIDGE + '/v1/alerts', {headers: h})
    ]);
    const mt = await metricsR.text();
    const wd = await watchdogR.json();
    const st = await statusR.json();
    const al = await alertsR.json();

    // Parse Prometheus metrics
    const vals = {};
    mt.split('\n').forEach(line => {
      if (line.startsWith('#') || !line.trim()) return;
      const parts = line.split(' ');
      if (parts.length >= 2) {
        const key = parts[0].replace(/\{.*\}/, '');
        vals[key] = parseFloat(parts[1]);
      }
    });

    setVal('requests', vals.arena_bridge_requests_total || 0);
    setVal('errors', vals.arena_bridge_errors_total || 0,
           vals.arena_bridge_errors_total > 0 ? 'red' : 'green');
    const errRate = vals.arena_bridge_requests_total > 0
      ? (vals.arena_bridge_errors_total / vals.arena_bridge_requests_total * 100).toFixed(2) + '%'
      : '0%';
    setVal('errorRate', errRate, parseFloat(errRate) > 5 ? 'red' : 'green');
    setVal('uptime', fmt(vals.arena_bridge_uptime_seconds || 0), 'blue');
    setVal('memory', (wd.memory_mb || 0).toFixed(1) + ' MB',
           wd.memory_mb > 400 ? 'red' : wd.memory_mb > 200 ? 'yellow' : 'green');
    setBar('memoryBar', wd.memory_mb / (wd.memory_limit_mb || 512) * 100,
           wd.memory_mb > 400 ? 'red' : 'green');
    setVal('cpu', (wd.cpu_percent || 0).toFixed(1) + '%',
           wd.cpu_percent > 80 ? 'red' : wd.cpu_percent > 50 ? 'yellow' : 'green');
    setBar('cpuBar', wd.cpu_percent || 0, wd.cpu_percent > 80 ? 'red' : 'blue');
    setVal('procs', vals.arena_bridge_active_processes || 0);
    setVal('cdpConnected', vals.arena_bridge_cdp_connected ? 'Yes' : 'No',
           vals.arena_bridge_cdp_connected ? 'green' : 'yellow');
    setVal('cdpReconnects', vals.arena_bridge_cdp_reconnect_count || 0,
           vals.arena_bridge_cdp_reconnect_count > 3 ? 'red' : '');
    setVal('subscribers', vals.arena_bridge_event_subscribers || 0);
    setVal('latencyAvg', fmtMs((vals.arena_bridge_request_duration_avg_seconds || 0) * 1000));
    setVal('latencyP50', fmtMs((vals.arena_bridge_request_duration_seconds_quantile_0_5 || 0) * 1000));
    setVal('latencyP95', fmtMs((vals.arena_bridge_request_duration_seconds_quantile_0_95 || 0) * 1000));
    setVal('latencyP99', fmtMs((vals.arena_bridge_request_duration_seconds_quantile_0_99 || 0) * 1000));

    // Alerts
    const alertDiv = document.getElementById('alertsList');
    if (al.ok && al.states) {
      const firing = Object.entries(al.states).filter(([k,v]) => v.status === 'FIRING');
      if (firing.length > 0) {
        alertDiv.innerHTML = firing.map(([k,v]) =>
          '<div class="stat"><span class="label">' + k + '</span>' +
          '<span class="value red">FIRING</span></div>').join('');
      } else {
        alertDiv.innerHTML = '<span class="label">All clear (' +
          Object.keys(al.states).length + ' checks)</span>';
      }
    }

    document.getElementById('version').textContent = 'v' + (st.version || vals.arena_bridge_info_version || '?');
  } catch(e) {
    console.error('poll error:', e);
  }
}

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/v1/events?token=' + TOKEN);
  ws.onopen = () => {
    document.getElementById('wsDot').className = 'ws-dot connected';
    document.getElementById('wsLabel').textContent = 'Live';
    reconnectDelay = 1000;
    addEvent('ws', 'connected');
  };
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type !== 'ping') addEvent(msg.type, msg.data || {});
    } catch(err) {}
  };
  ws.onclose = () => {
    document.getElementById('wsDot').className = 'ws-dot disconnected';
    document.getElementById('wsLabel').textContent = 'Disconnected';
    setTimeout(() => { reconnectDelay = Math.min(reconnectDelay * 2, 30000); connectWS(); }, reconnectDelay);
  };
  ws.onerror = () => { ws.close(); };
}

pollMetrics();
setInterval(pollMetrics, 5000);
connectWS();
"""
