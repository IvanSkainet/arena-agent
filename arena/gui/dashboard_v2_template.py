"""HTML shell for /gui/v2 dashboard."""
from __future__ import annotations

from arena.gui.dashboard_v2_css import DASHBOARD_V2_CSS
from arena.gui.dashboard_v2_js import DASHBOARD_V2_JS

DASHBOARD_V2_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Arena Bridge Dashboard v2</title>
<style>
{css}
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
{js}
</script>
</body>
</html>"""

DASHBOARD_V2_HTML = DASHBOARD_V2_SHELL.format(css=DASHBOARD_V2_CSS, js=DASHBOARD_V2_JS)
