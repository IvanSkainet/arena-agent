/** Arena Unified Bridge — VS Code / VSCodium Extension.
 *
 * Mission Control for your AI bridge: ship status, autopilot, audit trail,
 * MCP tools, capability gaps — all in your IDE sidebar.
 */

import * as vscode from "vscode";
import { BridgeClient } from "./bridge-client";
import { StatusBar } from "./status-bar";
import { ShipStatusProvider } from "./tree-views/ship-status";
import { AutopilotTreeProvider } from "./tree-views/autopilot-tree";
import { GapsTreeProvider } from "./tree-views/gaps-tree";
import { ToolsTreeProvider } from "./tree-views/tools-tree";
import { DashboardPanel } from "./webviews/dashboard";
import { runToolInteractive, startAutopilotFromGoal } from "./commands/run-tool-interactive";

let client: BridgeClient | null = null;
let statusBar: StatusBar;
let dashboard: DashboardPanel;
let shipProvider: ShipStatusProvider;
let autopilotProvider: AutopilotTreeProvider;
let gapsProvider: GapsTreeProvider;
let toolsProvider: ToolsTreeProvider;
let refreshTimer: ReturnType<typeof setInterval> | null = null;

async function connectToBridge(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration("arena");
  let bridgeUrl = config.get<string>("bridgeUrl", "");
  if (!bridgeUrl) {
    bridgeUrl =
      (await vscode.window.showInputBox({
        prompt: "Enter Arena Bridge URL",
        placeHolder: "https://your-bridge-host:port",
      })) ?? "";
    if (!bridgeUrl) { return; }
    await config.update("bridgeUrl", bridgeUrl, vscode.ConfigurationTarget.Global);
  }

  // Try to get token from secret storage first
  let token = await context.secrets.get("arena.bridgeToken");
  if (!token) {
    token =
      (await vscode.window.showInputBox({
        prompt: "Enter Bridge Token (will be stored securely)",
        password: true,
        placeHolder: "Bearer token",
      })) ?? "";
    if (!token) { return; }
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
    vscode.window.showInformationMessage(
      `Connected to Arena Bridge v${ver.version} (${ver.platform})`
    );
    await refreshAll();
    startAutoRefresh();
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    statusBar.updateError("Connection failed");
    vscode.window.showErrorMessage(`Failed to connect: ${msg}`);
    // Clear stored token on auth failure
    if (msg.includes("401") || msg.includes("403")) {
      await context.secrets.delete("arena.bridgeToken");
    }
  }
}

async function refreshAll(): Promise<void> {
  if (!client?.isConnected()) { return; }
  try {
    const preflight = await client.shipPreflight();
    statusBar.updateShipMode(preflight.mode, preflight.ready);
  } catch { /* ignore */ }
  await Promise.all([
    shipProvider.refresh(),
    autopilotProvider.refresh(),
    gapsProvider.refresh(),
    toolsProvider.refresh(),
  ]);
}

function startAutoRefresh(): void {
  stopAutoRefresh();
  const interval = vscode.workspace.getConfiguration("arena").get<number>("refreshInterval", 30);
  if (interval > 0) {
    refreshTimer = setInterval(() => refreshAll().catch(() => {}), interval * 1000);
  }
}

function stopAutoRefresh(): void {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
}

async function takeScreenshot(): Promise<void> {
  if (!client?.isConnected()) {
    vscode.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "Taking screenshot..." },
    async () => {
      try {
        const imgData = await client!.screenshot();
        const panel = vscode.window.createWebviewPanel(
          "arenaScreenshot", "Arena Desktop Screenshot",
          vscode.ViewColumn.One, { enableScripts: true }
        );
        const base64 = imgData.toString("base64");
        panel.webview.html = `<!DOCTYPE html>
<html><head><style>
  body { margin:0; background:#1e1e1e; display:flex; flex-direction:column; align-items:center; min-height:100vh; }
  img { max-width:100%; max-height:90vh; margin-top:16px; border:1px solid #333; }
  .info { color:#808080; font-size:12px; margin:8px; font-family:monospace; }
</style></head><body>
  <img src="data:image/jpeg;base64,${base64}" />
  <div class="info">Captured at ${new Date().toISOString()}</div>
</body></html>`;
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Screenshot failed: ${msg}`);
      }
    }
  );
}

export function activate(context: vscode.ExtensionContext): void {
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
    vscode.window.registerTreeDataProvider("arena.shipStatus", shipProvider),
    vscode.window.registerTreeDataProvider("arena.autopilotRuns", autopilotProvider),
    vscode.window.registerTreeDataProvider("arena.capabilityGaps", gapsProvider),
    vscode.window.registerTreeDataProvider("arena.mcpTools", toolsProvider),
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("arena.connect", () => connectToBridge(context)),
    vscode.commands.registerCommand("arena.disconnect", async () => {
      client?.disconnect();
      await context.secrets.delete("arena.bridgeToken");
      statusBar.updateDisconnected();
      stopAutoRefresh();
      refreshAll();
    }),
    vscode.commands.registerCommand("arena.refreshAll", refreshAll),
    vscode.commands.registerCommand("arena.runTool", (toolName?: string) => {
      if (client) { runToolInteractive(client, toolName); }
    }),
    vscode.commands.registerCommand("arena.screenshot", takeScreenshot),
    vscode.commands.registerCommand("arena.showDashboard", async () => {
      if (!client?.isConnected()) {
        vscode.window.showWarningMessage("Connect to bridge first");
        return;
      }
      await dashboard.show(context);
    }),
    vscode.commands.registerCommand("arena.autopilotStart", () => {
      if (client) { startAutopilotFromGoal(client); }
    }),
  );

  // Auto-connect if URL is saved (token from SecretStorage)
  const bridgeUrl = vscode.workspace.getConfiguration("arena").get<string>("bridgeUrl", "");
  const autoConnect = vscode.workspace.getConfiguration("arena").get<boolean>("autoConnect", true);
  if (autoConnect && bridgeUrl) {
    connectToBridge(context).catch(() => {});
  }
}

export function deactivate(): void {
  stopAutoRefresh();
  client?.disconnect();
}
