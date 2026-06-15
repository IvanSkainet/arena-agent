"""HTML templates for built-in GUI dashboards."""
from __future__ import annotations

GUI_LOGIN_HTML = """<!DOCTYPE html>
<html><head><title>Arena Bridge — Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:2.5rem;width:400px;text-align:center}
.card h1{color:#58a6ff;margin-bottom:.25rem;font-size:1.6rem}
.card .sub{color:#8b949e;margin-bottom:1.5rem;font-size:.85rem}
.card input{width:100%;padding:.7rem 1rem;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:.9rem;font-family:monospace;outline:none;margin-bottom:.75rem}
.card input:focus{border-color:#58a6ff;box-shadow:0 0 0 3px rgba(88,166,255,.15)}
.card button{width:100%;padding:.7rem;background:#238636;color:#fff;border:none;border-radius:6px;font-size:.9rem;cursor:pointer;font-weight:600;transition:background .15s}
.card button:hover{background:#2ea043}
.card .err{color:#f85149;font-size:.8rem;margin-top:.5rem;min-height:1.2em}
.card .hint{color:#484f58;font-size:.75rem;margin-top:1.25rem}
</style></head>
<body>
<div class="card">
<h1>Arena Bridge</h1>
<p class="sub">Enter your auth token to access the dashboard</p>
<form id="form" onsubmit="return login()">
<input type="password" id="token" placeholder="Auth token" autofocus autocomplete="off">
<button type="submit">Sign In</button>
<div class="err" id="err"></div>
</form>
<p class="hint">Token is stored in token.txt in the bridge directory</p>
</div>
<script>
var REDIR=location.pathname;
function login(e){
  if(e)e.preventDefault();
  var t=document.getElementById('token').value.trim();
  if(!t){document.getElementById('err').textContent='Please enter a token';return false}
  document.getElementById('err').textContent='';
  document.querySelector('button').textContent='Signing in...';
  fetch('/v1/status',{headers:{'Authorization':'Bearer '+t}}).then(function(r){
    if(r.ok){
      localStorage.setItem('arena_token',t);
      var sep=REDIR.indexOf('?')>-1?'&':'?';
      location.href=REDIR+sep+'token='+encodeURIComponent(t);
    }else{
      document.getElementById('err').textContent='Invalid token';
      document.querySelector('button').textContent='Sign In';
    }
  }).catch(function(){
    document.getElementById('err').textContent='Connection failed';
    document.querySelector('button').textContent='Sign In';
  });
  return false;
}
var saved=localStorage.getItem('arena_token');
if(saved){document.getElementById('token').value=saved;login()}
</script>
</body></html>"""
DASHBOARD_V2_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Arena Bridge Dashboard v2</title>
<style>
:root { --bg: #0d1117; --surface: #161b22; --border: #30363d; --text: #e6edf3;
       --muted: #8b949e; --accent: #58a6ff; --green: #3fb950; --red: #f85149;
       --yellow: #d29922; --orange: #db6d28; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.5; }
.header { background: var(--surface); border-bottom: 1px solid var(--border);
          padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 20px; font-weight: 600; }
.header .version { color: var(--muted); font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        gap: 16px; padding: 24px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        padding: 16px; }
.card h2 { font-size: 14px; font-weight: 600; color: var(--muted); text-transform: uppercase;
           letter-spacing: 0.5px; margin-bottom: 12px; }
.stat { display: flex; justify-content: space-between; align-items: baseline;
        padding: 4px 0; }
.stat .label { color: var(--muted); font-size: 13px; }
.stat .value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.stat .value.green { color: var(--green); }
.stat .value.red { color: var(--red); }
.stat .value.yellow { color: var(--yellow); }
.stat .value.blue { color: var(--accent); }
.bar-container { height: 6px; background: var(--border); border-radius: 3px;
                margin-top: 4px; overflow: hidden; }
.bar { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
.bar.green { background: var(--green); }
.bar.red { background: var(--red); }
.bar.yellow { background: var(--yellow); }
.bar.blue { background: var(--accent); }
.events { max-height: 200px; overflow-y: auto; }
.event { padding: 4px 8px; font-size: 12px; font-family: monospace;
         border-bottom: 1px solid var(--border); }
.event .time { color: var(--muted); }
.event .type { color: var(--accent); }
.footer { text-align: center; padding: 24px; color: var(--muted); font-size: 12px; }
.ws-status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.ws-dot { width: 8px; height: 8px; border-radius: 50%; }
.ws-dot.connected { background: var(--green); }
.ws-dot.disconnected { background: var(--red); }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>Arena Unified Bridge</h1>
    <span class="version" id="version">v---</span>
  </div>
  <div class="ws-status">
    <span class="ws-dot" id="wsDot"></span>
    <span id="wsLabel">Connecting...</span>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Bridge Health</h2>
    <div class="stat"><span class="label">Uptime</span><span class="value blue" id="uptime">--</span></div>
    <div class="stat"><span class="label">Requests</span><span class="value" id="requests">--</span></div>
    <div class="stat"><span class="label">Errors</span><span class="value" id="errors">--</span></div>
    <div class="stat"><span class="label">Error Rate</span><span class="value" id="errorRate">--</span></div>
  </div>

  <div class="card">
    <h2>Resources</h2>
    <div class="stat"><span class="label">Memory</span><span class="value" id="memory">--</span></div>
    <div class="bar-container"><div class="bar green" id="memoryBar" style="width:0%"></div></div>
    <div class="stat"><span class="label">CPU</span><span class="value" id="cpu">--</span></div>
    <div class="bar-container"><div class="bar blue" id="cpuBar" style="width:0%"></div></div>
    <div class="stat"><span class="label">Active Processes</span><span class="value" id="procs">--</span></div>
  </div>

  <div class="card">
    <h2>CDP Browser</h2>
    <div class="stat"><span class="label">Connected</span><span class="value" id="cdpConnected">--</span></div>
    <div class="stat"><span class="label">Reconnects</span><span class="value" id="cdpReconnects">--</span></div>
    <div class="stat"><span class="label">Event Subscribers</span><span class="value" id="subscribers">--</span></div>
  </div>

  <div class="card">
    <h2>Latency</h2>
    <div class="stat"><span class="label">Average</span><span class="value" id="latencyAvg">--</span></div>
    <div class="stat"><span class="label">P50</span><span class="value" id="latencyP50">--</span></div>
    <div class="stat"><span class="label">P95</span><span class="value" id="latencyP95">--</span></div>
    <div class="stat"><span class="label">P99</span><span class="value" id="latencyP99">--</span></div>
  </div>

  <div class="card">
    <h2>Alerts</h2>
    <div id="alertsList"><span class="label">No alerts</span></div>
  </div>

  <div class="card">
    <h2>Live Events</h2>
    <div class="events" id="eventsList"></div>
  </div>
</div>

<div class="footer">Arena Unified Bridge Dashboard v2 &mdash; WebSocket Real-Time</div>

<script>
const BRIDGE = location.origin;
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
    mt.split('\\n').forEach(line => {
      if (line.startsWith('#') || !line.trim()) return;
      const parts = line.split(' ');
      if (parts.length >= 2) {
        const key = parts[0].replace(/\\{.*\\}/, '');
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
</script>
</body>
</html>"""

