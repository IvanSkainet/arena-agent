"""CSS for /gui/v2 dashboard."""
from __future__ import annotations

DASHBOARD_V2_CSS = """:root { --bg: #0d1117; --surface: #161b22; --border: #30363d; --text: #e6edf3;
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
"""
