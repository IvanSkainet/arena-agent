"use strict";
var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toESM = (mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp(target, "default", { value: mod, enumerable: true }) : target,
  mod
));
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/extension.ts
var extension_exports = {};
__export(extension_exports, {
  activate: () => activate,
  deactivate: () => deactivate
});
module.exports = __toCommonJS(extension_exports);
var vscode8 = __toESM(require("vscode"));

// src/bridge-client.ts
var https = __toESM(require("https"));
var http = __toESM(require("http"));
var BridgeClient = class {
  url;
  token;
  connected = false;
  version = null;
  constructor(url, token) {
    this.url = url.replace(/\/+$/, "");
    this.token = token;
  }
  isConnected() {
    return this.connected;
  }
  getVersion() {
    return this.version;
  }
  async connect() {
    const ver = await this.get("/v1/version");
    this.version = ver;
    this.connected = ver.ok;
    return ver;
  }
  disconnect() {
    this.connected = false;
    this.version = null;
  }
  // --- MCP tool call ---
  async callTool(name, args = {}) {
    const payload = {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name, arguments: args }
    };
    const result = await this.post("/mcp", payload);
    const text = result?.result?.content?.[0]?.text ?? "{}";
    try {
      return JSON.parse(text);
    } catch {
      return { text };
    }
  }
  // --- Convenience methods ---
  async shipPreflight() {
    return await this.callTool("ship.preflight");
  }
  async missionControl() {
    return await this.callTool("mission.control_status");
  }
  async autopilotList(limit = 10) {
    return await this.callTool("mission.autopilot_list", { limit });
  }
  async capabilityGaps() {
    return await this.callTool("capability_gap.list", { status: "open" });
  }
  async auditDigest(minutes = 60) {
    return await this.callTool("audit.digest", { minutes });
  }
  async listTools() {
    const payload = {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/list"
    };
    const result = await this.post("/mcp", payload);
    return result?.result?.tools ?? [];
  }
  async screenshot() {
    return this.getRaw("/v1/desktop/screenshot?format=jpeg&scale=0.5&quality=75");
  }
  // --- HTTP helpers ---
  get(path) {
    return this.request("GET", path);
  }
  post(path, body) {
    return this.request("POST", path, body);
  }
  getRaw(path) {
    return new Promise((resolve, reject) => {
      const fullUrl = new URL(this.url + path);
      const mod = fullUrl.protocol === "https:" ? https : http;
      const req = mod.request(
        fullUrl,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${this.token}`
          },
          rejectUnauthorized: false
        },
        (res) => {
          const chunks = [];
          res.on("data", (chunk) => chunks.push(chunk));
          res.on("end", () => resolve(Buffer.concat(chunks)));
        }
      );
      req.on("error", reject);
      req.setTimeout(15e3, () => {
        req.destroy(new Error("timeout"));
      });
      req.end();
    });
  }
  request(method, path, body) {
    return new Promise((resolve, reject) => {
      const fullUrl = new URL(this.url + path);
      const mod = fullUrl.protocol === "https:" ? https : http;
      const data = body ? JSON.stringify(body) : void 0;
      const req = mod.request(
        fullUrl,
        {
          method,
          headers: {
            Authorization: `Bearer ${this.token}`,
            "Content-Type": "application/json",
            ...data ? { "Content-Length": Buffer.byteLength(data).toString() } : {}
          },
          rejectUnauthorized: false
        },
        (res) => {
          const chunks = [];
          res.setEncoding("utf-8");
          res.on("data", (chunk) => chunks.push(chunk));
          res.on("end", () => {
            try {
              resolve(JSON.parse(chunks.join("")));
            } catch {
              reject(new Error(`Invalid JSON from bridge: ${chunks.join("").slice(0, 200)}`));
            }
          });
        }
      );
      req.on("error", reject);
      req.setTimeout(15e3, () => {
        req.destroy(new Error("timeout"));
      });
      if (data) {
        req.write(data);
      }
      req.end();
    });
  }
};

// src/status-bar.ts
var vscode = __toESM(require("vscode"));
var StatusBar = class {
  connectionItem;
  modeItem;
  constructor() {
    this.connectionItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.connectionItem.command = "arena.connect";
    this.connectionItem.tooltip = "Arena Bridge connection";
    this.modeItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
    this.modeItem.command = "arena.showDashboard";
    this.modeItem.tooltip = "Ship mode \u2014 click for dashboard";
  }
  show() {
    this.connectionItem.show();
  }
  updateDisconnected() {
    this.connectionItem.text = "$(plug) Arena: Disconnected";
    this.connectionItem.backgroundColor = void 0;
    this.modeItem.hide();
  }
  updateConnecting() {
    this.connectionItem.text = "$(sync~spin) Arena: Connecting...";
    this.modeItem.hide();
  }
  updateConnected(version) {
    this.connectionItem.text = `$(check) Arena v${version}`;
    this.connectionItem.backgroundColor = void 0;
  }
  updateShipMode(mode, ready) {
    const icons = {
      nominal: "$(shield)",
      armed: "$(flame)",
      blocked: "$(error)",
      unknown: "$(question)"
    };
    const colors = {
      nominal: void 0,
      armed: new vscode.ThemeColor("statusBarItem.warningBackground"),
      blocked: new vscode.ThemeColor("statusBarItem.errorBackground")
    };
    const icon = icons[mode] ?? icons.unknown;
    this.modeItem.text = `${icon} ${mode}${ready ? "" : " (not ready)"}`;
    this.modeItem.backgroundColor = colors[mode];
    this.modeItem.show();
  }
  updateError(msg) {
    this.connectionItem.text = `$(error) Arena: ${msg}`;
    this.connectionItem.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
    this.modeItem.hide();
  }
  dispose() {
    this.connectionItem.dispose();
    this.modeItem.dispose();
  }
};

// src/tree-views/ship-status.ts
var vscode2 = __toESM(require("vscode"));
var ShipStatusProvider = class {
  constructor(client2) {
    this.client = client2;
  }
  _onDidChangeTreeData = new vscode2.EventEmitter();
  onDidChangeTreeData = this._onDidChangeTreeData.event;
  preflight = null;
  async refresh() {
    if (!this.client.isConnected()) {
      this.preflight = null;
    } else {
      try {
        this.preflight = await this.client.shipPreflight();
      } catch {
        this.preflight = null;
      }
    }
    this._onDidChangeTreeData.fire(void 0);
  }
  getTreeItem(element) {
    return element;
  }
  getChildren(element) {
    if (element) {
      return [];
    }
    if (!this.preflight) {
      const item = new vscode2.TreeItem("Not connected");
      item.iconPath = new vscode2.ThemeIcon("plug");
      return [item];
    }
    const items = [];
    items.push(new ShipModeItem(this.preflight.mode, this.preflight.ready));
    if (this.preflight.failed && this.preflight.failed.length > 0) {
      for (const check of this.preflight.failed) {
        items.push(new ShipCheckItem(check));
      }
    }
    return items;
  }
};
var ShipModeItem = class extends vscode2.TreeItem {
  constructor(mode, ready) {
    super(`Mode: ${mode}${ready ? " \u2713" : " (not ready)"}`, vscode2.TreeItemCollapsibleState.None);
    const iconMap = {
      nominal: "shield",
      armed: "flame",
      blocked: "error"
    };
    this.iconPath = new vscode2.ThemeIcon(iconMap[mode] ?? "question");
    this.description = ready ? "ready" : "not ready";
  }
};
var ShipCheckItem = class extends vscode2.TreeItem {
  constructor(check) {
    super(check.name, vscode2.TreeItemCollapsibleState.None);
    this.iconPath = new vscode2.ThemeIcon(check.ok ? "pass" : "error");
    this.description = check.detail ?? check.severity;
  }
};

// src/tree-views/autopilot-tree.ts
var vscode3 = __toESM(require("vscode"));
var AutopilotTreeProvider = class {
  constructor(client2) {
    this.client = client2;
  }
  _onDidChangeTreeData = new vscode3.EventEmitter();
  onDidChangeTreeData = this._onDidChangeTreeData.event;
  runs = [];
  async refresh() {
    if (!this.client.isConnected()) {
      this.runs = [];
    } else {
      try {
        const result = await this.client.autopilotList(10);
        this.runs = result.runs ?? [];
      } catch {
        this.runs = [];
      }
    }
    this._onDidChangeTreeData.fire(void 0);
  }
  getTreeItem(element) {
    return element;
  }
  getChildren() {
    if (!this.runs.length) {
      const item = new vscode3.TreeItem("No autopilot runs");
      item.iconPath = new vscode3.ThemeIcon("history");
      return [item];
    }
    return this.runs.map((r) => new AutopilotRunItem(r));
  }
};
var AutopilotRunItem = class extends vscode3.TreeItem {
  constructor(run) {
    const label = run.goal.length > 50 ? run.goal.slice(0, 47) + "..." : run.goal;
    super(label, vscode3.TreeItemCollapsibleState.None);
    const iconMap = {
      nominal: "pass",
      partial: "warning",
      cancelled: "circle-slash",
      running: "sync~spin",
      error: "error"
    };
    this.iconPath = new vscode3.ThemeIcon(iconMap[run.status] ?? "question");
    this.description = run.status;
    this.tooltip = `${run.goal}
Status: ${run.status}
Outcome: ${run.outcome}
Created: ${run.created_at}`;
  }
};

// src/tree-views/gaps-tree.ts
var vscode4 = __toESM(require("vscode"));
var GapsTreeProvider = class {
  constructor(client2) {
    this.client = client2;
  }
  _onDidChangeTreeData = new vscode4.EventEmitter();
  onDidChangeTreeData = this._onDidChangeTreeData.event;
  gaps = [];
  async refresh() {
    if (!this.client.isConnected()) {
      this.gaps = [];
    } else {
      try {
        const result = await this.client.capabilityGaps();
        this.gaps = result.gaps ?? [];
      } catch {
        this.gaps = [];
      }
    }
    this._onDidChangeTreeData.fire(void 0);
  }
  getTreeItem(element) {
    return element;
  }
  getChildren() {
    if (!this.gaps.length) {
      const item = new vscode4.TreeItem("No open capability gaps");
      item.iconPath = new vscode4.ThemeIcon("check-all");
      return [item];
    }
    return this.gaps.map((g) => new GapItem(g));
  }
};
var GapItem = class extends vscode4.TreeItem {
  constructor(gap) {
    super(gap.title, vscode4.TreeItemCollapsibleState.None);
    const sevIcons = {
      critical: "error",
      high: "warning",
      medium: "info",
      low: "circle-outline"
    };
    this.iconPath = new vscode4.ThemeIcon(sevIcons[gap.severity] ?? "circle-outline");
    this.description = `${gap.severity} \xB7 ${gap.status}`;
    this.tooltip = `${gap.title}
Severity: ${gap.severity}
Status: ${gap.status}
Created: ${gap.created_at}`;
  }
};

// src/tree-views/tools-tree.ts
var vscode5 = __toESM(require("vscode"));
var ToolsTreeProvider = class {
  constructor(client2) {
    this.client = client2;
  }
  _onDidChangeTreeData = new vscode5.EventEmitter();
  onDidChangeTreeData = this._onDidChangeTreeData.event;
  tools = [];
  async refresh() {
    if (!this.client.isConnected()) {
      this.tools = [];
    } else {
      try {
        this.tools = await this.client.listTools();
      } catch {
        this.tools = [];
      }
    }
    this._onDidChangeTreeData.fire(void 0);
  }
  getTreeItem(element) {
    return element;
  }
  getChildren(element) {
    if (!element) {
      const namespaces = /* @__PURE__ */ new Map();
      for (const tool of this.tools) {
        const ns = tool.name.split(".")[0] ?? "other";
        if (!namespaces.has(ns)) {
          namespaces.set(ns, []);
        }
        namespaces.get(ns).push(tool);
      }
      if (namespaces.size === 0) {
        const item = new vscode5.TreeItem("No tools loaded");
        item.iconPath = new vscode5.ThemeIcon("plug");
        return [item];
      }
      return Array.from(namespaces.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([ns, tools]) => new NamespaceItem(ns, tools));
    }
    if (element instanceof NamespaceItem) {
      return element.tools.map((t) => new ToolItem(t));
    }
    return [];
  }
};
var NamespaceItem = class extends vscode5.TreeItem {
  constructor(namespace, tools) {
    super(namespace, vscode5.TreeItemCollapsibleState.Collapsed);
    this.namespace = namespace;
    this.tools = tools;
    this.description = `${tools.length} tools`;
    this.iconPath = new vscode5.ThemeIcon("symbol-namespace");
  }
};
var ToolItem = class extends vscode5.TreeItem {
  constructor(tool) {
    super(tool.name, vscode5.TreeItemCollapsibleState.None);
    this.description = tool.description.slice(0, 80);
    this.tooltip = tool.description;
    this.iconPath = new vscode5.ThemeIcon("symbol-method");
    this.command = {
      command: "arena.runTool",
      title: "Run Tool",
      arguments: [tool.name]
    };
  }
};

// src/webviews/dashboard.ts
var vscode6 = __toESM(require("vscode"));
var DashboardPanel = class {
  constructor(client2) {
    this.client = client2;
  }
  panel = null;
  refreshTimer = null;
  async show(context) {
    if (this.panel) {
      this.panel.reveal();
      await this.refresh();
      return;
    }
    this.panel = vscode6.window.createWebviewPanel(
      "arenaDashboard",
      "Arena Mission Control",
      vscode6.ViewColumn.One,
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
    this.refreshTimer = setInterval(() => this.refresh().catch(() => {
    }), 15e3);
  }
  async refresh() {
    if (!this.panel || !this.client.isConnected()) {
      return;
    }
    let mc = null;
    let audit = null;
    try {
      mc = await this.client.missionControl();
    } catch {
    }
    try {
      audit = await this.client.auditDigest(60);
    } catch {
    }
    if (this.panel) {
      this.panel.webview.html = this.buildHtml(mc, audit);
    }
  }
  buildHtml(mc, audit) {
    const ver = this.client.getVersion();
    const shipMode = mc?.ship?.mode ?? "unknown";
    const shipReady = mc?.ship?.ready ?? false;
    const modeColors = {
      nominal: "#4ec9b0",
      armed: "#dcdcaa",
      blocked: "#f44747",
      unknown: "#808080"
    };
    const modeColor = modeColors[shipMode] ?? modeColors.unknown;
    const runs = mc?.autopilot?.recent_runs ?? [];
    const runsHtml = runs.length === 0 ? "<p class='muted'>No autopilot runs</p>" : runs.map((r) => {
      const statusIcons = {
        nominal: "\u2705",
        partial: "\u26A0\uFE0F",
        cancelled: "\u{1F6AB}",
        running: "\u23F3",
        error: "\u274C"
      };
      const icon = statusIcons[r.status] ?? "\u2753";
      const goal = r.goal.length > 60 ? r.goal.slice(0, 57) + "..." : r.goal;
      return `<div class="run-item"><span class="icon">${icon}</span><span class="goal">${this.esc(goal)}</span><span class="status">${r.status}</span></div>`;
    }).join("");
    const gaps = mc?.capability_gaps?.gaps ?? [];
    const gapsHtml = gaps.length === 0 ? "<p class='muted'>No open capability gaps</p>" : gaps.map((g) => {
      const sevColors = { critical: "#f44747", high: "#ff8c00", medium: "#dcdcaa", low: "#808080" };
      return `<div class="gap-item"><span class="sev" style="color:${sevColors[g.severity] ?? "#808080"}">${g.severity}</span> ${this.esc(g.title)}</div>`;
    }).join("");
    const auditHtml = !audit ? "<p class='muted'>No audit data</p>" : `
      <div class="audit-grid">
        <div class="audit-stat"><span class="num">${audit.total}</span><span class="label">events (${audit.minutes}min)</span></div>
        <div class="audit-stat"><span class="num" style="color:#f44747">${(audit.by_risk?.critical ?? 0) + (audit.by_risk?.high ?? 0)}</span><span class="label">high/critical</span></div>
        <div class="audit-stat"><span class="num" style="color:#ff8c00">${audit.external_count}</span><span class="label">external</span></div>
      </div>
      ${audit.recent_high_risk?.length ? `<div class="high-risk">${audit.recent_high_risk.slice(-5).map(
      (h) => `<div class="risk-item"><span class="risk-badge ${h.risk}">${h.risk}</span> ${this.esc(h.tool)}</div>`
    ).join("")}</div>` : ""}`;
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
  <h1>\u{1F6F8} Arena Mission Control</h1>

  <div class="grid">
    <div class="card">
      <div class="ship-mode" style="color: ${modeColor}">
        ${shipMode.toUpperCase()}
      </div>
      <div class="version">${shipReady ? "Ready" : "Not Ready"} \xB7 v${ver?.version ?? "?"} \xB7 ${ver?.platform ?? "?"}</div>
    </div>

    <div class="card">
      <h2>\u{1F50D} Audit (last hour)</h2>
      ${auditHtml}
    </div>
  </div>

  <div class="info-row">
    <span>\u{1F5A5}\uFE0F ${windowCount} windows</span>
    <span>\u{1F4F1} Mobile: ${mobileOk ? `${deviceCount} devices` : "offline"}</span>
    <span>\u{1F527} ${mc?.autopilot?.total ?? 0} total runs</span>
    <span>\u26A0\uFE0F ${mc?.capability_gaps?.open_count ?? 0} open gaps</span>
  </div>

  <h2>\u{1F680} Recent Autopilot Runs</h2>
  <div class="card">${runsHtml}</div>

  <h2>\u26A1 Capability Gaps</h2>
  <div class="card">${gapsHtml}</div>

  <p class="muted" style="margin-top: 16px; text-align: center; font-size: 11px;">
    Auto-refreshes every 15s \xB7 Arena Bridge Extension v0.1.0
  </p>
</body>
</html>`;
  }
  esc(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  dispose() {
    this.panel?.dispose();
    if (this.refreshTimer) {
      clearInterval(this.refreshTimer);
    }
  }
};

// src/commands/run-tool-interactive.ts
var vscode7 = __toESM(require("vscode"));
async function runToolInteractive(client2, toolName) {
  if (!client2.isConnected()) {
    vscode7.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }
  if (!toolName) {
    const tools = await client2.listTools();
    const items = tools.map((t) => ({
      label: t.name,
      description: t.description.slice(0, 80),
      detail: t.inputSchema.required?.length ? `Required: ${t.inputSchema.required.join(", ")}` : "No required params",
      tool: t
    }));
    const picked = await vscode7.window.showQuickPick(items, {
      placeHolder: "Select MCP tool to run",
      matchOnDescription: true
    });
    if (!picked) {
      return;
    }
    toolName = picked.label;
  }
  let toolDef;
  try {
    const tools = await client2.listTools();
    toolDef = tools.find((t) => t.name === toolName);
  } catch {
  }
  let defaultArgs = "{}";
  if (toolDef?.inputSchema?.properties) {
    const props = toolDef.inputSchema.properties;
    const example = {};
    for (const [key, schema] of Object.entries(props)) {
      const s = schema;
      if (s.default !== void 0) {
        example[key] = s.default;
      } else if (s.type === "string") {
        example[key] = "";
      } else if (s.type === "integer" || s.type === "number") {
        example[key] = 0;
      } else if (s.type === "boolean") {
        example[key] = false;
      }
    }
    const required = new Set(toolDef.inputSchema.required ?? []);
    const filtered = {};
    for (const [k, v] of Object.entries(example)) {
      if (required.has(k) || v !== "" && v !== 0 && v !== false) {
        filtered[k] = v;
      }
    }
    if (Object.keys(filtered).length > 0) {
      defaultArgs = JSON.stringify(filtered, null, 2);
    }
  }
  const argsStr = await vscode7.window.showInputBox({
    prompt: `Arguments for ${toolName} (JSON)`,
    value: defaultArgs,
    placeHolder: '{"key": "value"}',
    validateInput: (value) => {
      if (!value.trim()) {
        return null;
      }
      try {
        JSON.parse(value);
        return null;
      } catch {
        return "Invalid JSON";
      }
    }
  });
  if (argsStr === void 0) {
    return;
  }
  const args = argsStr.trim() ? JSON.parse(argsStr) : {};
  await vscode7.window.withProgress(
    {
      location: vscode7.ProgressLocation.Notification,
      title: `Running ${toolName}...`,
      cancellable: false
    },
    async () => {
      try {
        const result = await client2.callTool(toolName, args);
        const content = JSON.stringify(result, null, 2);
        const doc = await vscode7.workspace.openTextDocument({
          content: `// Result of ${toolName}
// Args: ${JSON.stringify(args)}
${content}`,
          language: "jsonc"
        });
        await vscode7.window.showTextDocument(doc, { preview: true });
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        vscode7.window.showErrorMessage(`${toolName} failed: ${msg}`);
      }
    }
  );
}
async function startAutopilotFromGoal(client2) {
  if (!client2.isConnected()) {
    vscode7.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }
  const goal = await vscode7.window.showInputBox({
    prompt: "Enter autopilot goal (natural language)",
    placeHolder: "check ship status and desktop windows"
  });
  if (!goal) {
    return;
  }
  const mode = await vscode7.window.showQuickPick(
    [
      { label: "Synchronous", description: "Wait for completion", value: "sync" },
      { label: "Async (background)", description: "Returns immediately", value: "async" }
    ],
    { placeHolder: "Execution mode" }
  );
  if (!mode) {
    return;
  }
  await vscode7.window.withProgress(
    {
      location: vscode7.ProgressLocation.Notification,
      title: `Autopilot: ${goal}`,
      cancellable: false
    },
    async () => {
      try {
        const toolName = mode.value === "async" ? "mission.autopilot_start_async" : "mission.autopilot_from_goal";
        const result = await client2.callTool(toolName, { goal });
        const content = JSON.stringify(result, null, 2);
        const doc = await vscode7.workspace.openTextDocument({
          content: `// Autopilot: ${goal}
${content}`,
          language: "jsonc"
        });
        await vscode7.window.showTextDocument(doc, { preview: true });
        const r = result;
        if (r.ok) {
          vscode7.window.showInformationMessage(
            `Autopilot ${r.status}: ${r.outcome ?? "started"}`
          );
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        vscode7.window.showErrorMessage(`Autopilot failed: ${msg}`);
      }
    }
  );
}

// src/extension.ts
var client = null;
var statusBar;
var dashboard;
var shipProvider;
var autopilotProvider;
var gapsProvider;
var toolsProvider;
var refreshTimer = null;
async function connectToBridge(context) {
  const config = vscode8.workspace.getConfiguration("arena");
  let bridgeUrl = config.get("bridgeUrl", "");
  if (!bridgeUrl) {
    bridgeUrl = await vscode8.window.showInputBox({
      prompt: "Enter Arena Bridge URL",
      placeHolder: "https://your-bridge-host:port"
    }) ?? "";
    if (!bridgeUrl) {
      return;
    }
    await config.update("bridgeUrl", bridgeUrl, vscode8.ConfigurationTarget.Global);
  }
  let token = await context.secrets.get("arena.bridgeToken");
  if (!token) {
    token = await vscode8.window.showInputBox({
      prompt: "Enter Bridge Token (will be stored securely)",
      password: true,
      placeHolder: "Bearer token"
    }) ?? "";
    if (!token) {
      return;
    }
    await context.secrets.store("arena.bridgeToken", token);
  }
  statusBar.updateConnecting();
  client = new BridgeClient(bridgeUrl, token);
  shipProvider = new ShipStatusProvider(client);
  autopilotProvider = new AutopilotTreeProvider(client);
  gapsProvider = new GapsTreeProvider(client);
  toolsProvider = new ToolsTreeProvider(client);
  dashboard = new DashboardPanel(client);
  try {
    const ver = await client.connect();
    statusBar.updateConnected(ver.version);
    vscode8.window.showInformationMessage(
      `Connected to Arena Bridge v${ver.version} (${ver.platform})`
    );
    await refreshAll();
    startAutoRefresh();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    statusBar.updateError("Connection failed");
    vscode8.window.showErrorMessage(`Failed to connect: ${msg}`);
    if (msg.includes("401") || msg.includes("403")) {
      await context.secrets.delete("arena.bridgeToken");
    }
  }
}
async function refreshAll() {
  if (!client?.isConnected()) {
    return;
  }
  try {
    const preflight = await client.shipPreflight();
    statusBar.updateShipMode(preflight.mode, preflight.ready);
  } catch {
  }
  await Promise.all([
    shipProvider.refresh(),
    autopilotProvider.refresh(),
    gapsProvider.refresh(),
    toolsProvider.refresh()
  ]);
}
function startAutoRefresh() {
  stopAutoRefresh();
  const interval = vscode8.workspace.getConfiguration("arena").get("refreshInterval", 30);
  if (interval > 0) {
    refreshTimer = setInterval(() => refreshAll().catch(() => {
    }), interval * 1e3);
  }
}
function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}
async function takeScreenshot() {
  if (!client?.isConnected()) {
    vscode8.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }
  await vscode8.window.withProgress(
    { location: vscode8.ProgressLocation.Notification, title: "Taking screenshot..." },
    async () => {
      try {
        const imgData = await client.screenshot();
        const panel = vscode8.window.createWebviewPanel(
          "arenaScreenshot",
          "Arena Desktop Screenshot",
          vscode8.ViewColumn.One,
          { enableScripts: true }
        );
        const base64 = imgData.toString("base64");
        panel.webview.html = `<!DOCTYPE html>
<html><head><style>
  body { margin:0; background:#1e1e1e; display:flex; flex-direction:column; align-items:center; min-height:100vh; }
  img { max-width:100%; max-height:90vh; margin-top:16px; border:1px solid #333; }
  .info { color:#808080; font-size:12px; margin:8px; font-family:monospace; }
</style></head><body>
  <img src="data:image/jpeg;base64,${base64}" />
  <div class="info">Captured at ${(/* @__PURE__ */ new Date()).toISOString()}</div>
</body></html>`;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        vscode8.window.showErrorMessage(`Screenshot failed: ${msg}`);
      }
    }
  );
}
function activate(context) {
  statusBar = new StatusBar();
  statusBar.show();
  statusBar.updateDisconnected();
  context.subscriptions.push(statusBar);
  client = new BridgeClient("", "");
  dashboard = new DashboardPanel(client);
  shipProvider = new ShipStatusProvider(client);
  autopilotProvider = new AutopilotTreeProvider(client);
  gapsProvider = new GapsTreeProvider(client);
  toolsProvider = new ToolsTreeProvider(client);
  context.subscriptions.push(
    vscode8.window.registerTreeDataProvider("arena.shipStatus", shipProvider),
    vscode8.window.registerTreeDataProvider("arena.autopilotRuns", autopilotProvider),
    vscode8.window.registerTreeDataProvider("arena.capabilityGaps", gapsProvider),
    vscode8.window.registerTreeDataProvider("arena.mcpTools", toolsProvider)
  );
  context.subscriptions.push(
    vscode8.commands.registerCommand("arena.connect", () => connectToBridge(context)),
    vscode8.commands.registerCommand("arena.disconnect", async () => {
      client?.disconnect();
      await context.secrets.delete("arena.bridgeToken");
      statusBar.updateDisconnected();
      stopAutoRefresh();
      refreshAll();
    }),
    vscode8.commands.registerCommand("arena.refreshAll", refreshAll),
    vscode8.commands.registerCommand("arena.runTool", (toolName) => {
      if (client) {
        runToolInteractive(client, toolName);
      }
    }),
    vscode8.commands.registerCommand("arena.screenshot", takeScreenshot),
    vscode8.commands.registerCommand("arena.showDashboard", async () => {
      if (!client?.isConnected()) {
        vscode8.window.showWarningMessage("Connect to bridge first");
        return;
      }
      await dashboard.show(context);
    }),
    vscode8.commands.registerCommand("arena.autopilotStart", () => {
      if (client) {
        startAutopilotFromGoal(client);
      }
    })
  );
  const bridgeUrl = vscode8.workspace.getConfiguration("arena").get("bridgeUrl", "");
  const autoConnect = vscode8.workspace.getConfiguration("arena").get("autoConnect", true);
  if (autoConnect && bridgeUrl) {
    connectToBridge(context).catch(() => {
    });
  }
}
function deactivate() {
  stopAutoRefresh();
  client?.disconnect();
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  activate,
  deactivate
});
