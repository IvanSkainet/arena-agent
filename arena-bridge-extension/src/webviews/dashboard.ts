/** Mission Control Dashboard webview panel. */

import * as vscode from "vscode";
import type { BridgeClient } from "../bridge-client";
import type { MissionControlStatus, AuditDigest } from "../types";

export class DashboardPanel {
  private panel: vscode.WebviewPanel | null = null;
  private refreshTimer: ReturnType<typeof setInterval> | null = null;

  constructor(private client: BridgeClient) {}

  async show(context: vscode.ExtensionContext): Promise<void> {
    if (this.panel) {
      this.panel.reveal();
      await this.refresh();
      return;
    }

    this.panel = vscode.window.createWebviewPanel(
      "arenaDashboard",
      "Arena Mission Control",
      vscode.ViewColumn.One,
      { enableScripts: true, retainContextWhenHidden: true }
    );

    this.panel.onDidDispose(() => {
      this.panel = null;
      if (this.refreshTimer) {
        clearInterval(this.refreshTimer);
        this.refreshTimer = null;
      }
    });

    await this.refresh();

    // Auto-refresh every 15s
    this.refreshTimer = setInterval(() => this.refresh().catch(() => {}), 15000);
  }

  async refresh(): Promise<void> {
    if (!this.panel || !this.client.isConnected()) { return; }

    let mc: MissionControlStatus | null = null;
    let audit: AuditDigest | null = null;

    try {
      mc = await this.client.missionControl();
    } catch { /* ignore */ }

    try {
      audit = await this.client.auditDigest(60);
    } catch { /* ignore */ }

    if (this.panel) {
      this.panel.webview.html = this.buildHtml(mc, audit);
    }
  }

  private buildHtml(mc: MissionControlStatus | null, audit: AuditDigest | null): string {
    const ver = this.client.getVersion();

    // Ship section
    const shipMode = mc?.ship?.mode ?? "unknown";
    const shipReady = mc?.ship?.ready ?? false;
    const modeColors: Record<string, string> = {
      nominal: "#4ec9b0", armed: "#dcdcaa", blocked: "#f44747", unknown: "#808080"
    };
    const modeColor = modeColors[shipMode] ?? modeColors.unknown;

    // Autopilot
    const runs = mc?.autopilot?.recent_runs ?? [];
    const runsHtml = runs.length === 0
      ? "<p class='muted'>No autopilot runs</p>"
      : runs.map(r => {
          const statusIcons: Record<string, string> = {
            nominal: "✅", partial: "⚠️", cancelled: "🚫", running: "⏳", error: "❌"
          };
          const icon = statusIcons[r.status] ?? "❓";
          const goal = r.goal.length > 60 ? r.goal.slice(0, 57) + "..." : r.goal;
          return `<div class="run-item"><span class="icon">${icon}</span><span class="goal">${this.esc(goal)}</span><span class="status">${r.status}</span></div>`;
        }).join("");

    // Gaps
    const gaps = mc?.capability_gaps?.gaps ?? [];
    const gapsHtml = gaps.length === 0
      ? "<p class='muted'>No open capability gaps</p>"
      : gaps.map(g => {
          const sevColors: Record<string, string> = { critical: "#f44747", high: "#ff8c00", medium: "#dcdcaa", low: "#808080" };
          return `<div class="gap-item"><span class="sev" style="color:${sevColors[g.severity] ?? '#808080'}">${g.severity}</span> ${this.esc(g.title)}</div>`;
        }).join("");

    // Audit
    const auditHtml = !audit ? "<p class='muted'>No audit data</p>" : `
      <div class="audit-grid">
        <div class="audit-stat"><span class="num">${audit.total}</span><span class="label">events (${audit.minutes}min)</span></div>
        <div class="audit-stat"><span class="num" style="color:#f44747">${(audit.by_risk?.critical ?? 0) + (audit.by_risk?.high ?? 0)}</span><span class="label">high/critical</span></div>
        <div class="audit-stat"><span class="num" style="color:#ff8c00">${audit.external_count}</span><span class="label">external</span></div>
      </div>
      ${audit.recent_high_risk?.length ? `<div class="high-risk">${audit.recent_high_risk.slice(-5).map(h =>
        `<div class="risk-item"><span class="risk-badge ${h.risk}">${h.risk}</span> ${this.esc(h.tool)}</div>`
      ).join("")}</div>` : ""}`;

    // Desktop + Mobile
    const windowCount = mc?.desktop?.window_count ?? 0;
    const mobileOk = mc?.mobile?.ok ?? false;
    const deviceCount = mc?.mobile?.device_count ?? 0;

    return `<!DOCTYPE html>
<html>
<head>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: var(--vscode-font-family, 'Segoe UI', sans-serif); color: #ccc; background: #1e1e1e; padding: 16px; }
  h1 { font-size: 18px; color: #e0e0e0; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
  h2 { font-size: 14px; color: #808080; text-transform: uppercase; letter-spacing: 1px; margin: 20px 0 8px; border-bottom: 1px solid #333; padding-bottom: 4px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .card { background: #252526; border-radius: 6px; padding: 12px; border: 1px solid #333; }
  .ship-mode { font-size: 28px; font-weight: bold; text-align: center; padding: 16px; border-radius: 8px; background: #2d2d2d; }
  .version { font-size: 12px; color: #808080; text-align: center; margin-top: 4px; }
  .run-item { display: flex; gap: 8px; padding: 4px 0; border-bottom: 1px solid #2d2d2d; align-items: center; }
  .run-item .icon { flex-shrink: 0; }
  .run-item .goal { flex: 1; font-size: 13px; }
  .run-item .status { font-size: 11px; color: #808080; }
  .gap-item { padding: 4px 0; font-size: 13px; border-bottom: 1px solid #2d2d2d; }
  .gap-item .sev { font-weight: bold; font-size: 11px; text-transform: uppercase; }
  .muted { color: #555; font-size: 13px; }
  .audit-grid { display: flex; gap: 16px; }
  .audit-stat { text-align: center; flex: 1; }
  .audit-stat .num { display: block; font-size: 24px; font-weight: bold; }
  .audit-stat .label { font-size: 11px; color: #808080; }
  .high-risk { margin-top: 8px; }
  .risk-item { font-size: 12px; padding: 2px 0; }
  .risk-badge { font-size: 10px; padding: 1px 4px; border-radius: 3px; font-weight: bold; }
  .risk-badge.critical { background: #f44747; color: #fff; }
  .risk-badge.high { background: #ff8c00; color: #fff; }
  .info-row { display: flex; gap: 16px; margin-top: 8px; font-size: 13px; }
  .info-row span { background: #2d2d2d; padding: 4px 8px; border-radius: 4px; }
</style>
</head>
<body>
  <h1>🛸 Arena Mission Control</h1>

  <div class="grid">
    <div class="card">
      <div class="ship-mode" style="color: ${modeColor}">
        ${shipMode.toUpperCase()}
      </div>
      <div class="version">${shipReady ? "Ready" : "Not Ready"} · v${ver?.version ?? "?"} · ${ver?.platform ?? "?"}</div>
    </div>

    <div class="card">
      <h2>🔍 Audit (last hour)</h2>
      ${auditHtml}
    </div>
  </div>

  <div class="info-row">
    <span>🖥️ ${windowCount} windows</span>
    <span>📱 Mobile: ${mobileOk ? `${deviceCount} devices` : "offline"}</span>
    <span>🔧 ${mc?.autopilot?.total ?? 0} total runs</span>
    <span>⚠️ ${mc?.capability_gaps?.open_count ?? 0} open gaps</span>
  </div>

  <h2>🚀 Recent Autopilot Runs</h2>
  <div class="card">${runsHtml}</div>

  <h2>⚡ Capability Gaps</h2>
  <div class="card">${gapsHtml}</div>

  <p class="muted" style="margin-top: 16px; text-align: center; font-size: 11px;">
    Auto-refreshes every 15s · Arena Bridge Extension v0.1.0
  </p>
</body>
</html>`;
  }

  private esc(s: string): string {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  dispose(): void {
    this.panel?.dispose();
    if (this.refreshTimer) { clearInterval(this.refreshTimer); }
  }
}
