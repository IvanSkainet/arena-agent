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

let client: BridgeClient | null = null;
let statusBar: StatusBar;
let dashboard: DashboardPanel;
let shipProvider: ShipStatusProvider;
let autopilotProvider: AutopilotTreeProvider;
let gapsProvider: GapsTreeProvider;
let toolsProvider: ToolsTreeProvider;
let refreshTimer: ReturnType<typeof setInterval> | null = null;

async function connectToBridge(): Promise<void> {
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

  // Get token from secret storage or prompt
  const token =
    (await vscode.window.showInputBox({
      prompt: "Enter Bridge Token",
      password: true,
      placeHolder: "Bearer token",
    })) ?? "";
  if (!token) { return; }

  statusBar.updateConnecting();
  client = new BridgeClient(bridgeUrl, token);

  // Update providers with new client
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
    vscode.window.showErrorMessage(`Failed to connect to Arena Bridge: ${msg}`);
  }
}

async function refreshAll(): Promise<void> {
  if (!client?.isConnected()) { return; }
  try {
    const preflight = await client.shipPreflight();
    statusBar.updateShipMode(preflight.mode, preflight.ready);
  } catch {
    // ignore
  }
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
    refreshTimer = setInterval(() => {
      refreshAll().catch(() => {});
    }, interval * 1000);
  }
}

function stopAutoRefresh(): void {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
}

async function runTool(toolName?: string): Promise<void> {
  if (!client?.isConnected()) {
    vscode.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }
  if (!toolName) {
    toolName = await vscode.window.showInputBox({
      prompt: "Enter MCP tool name",
      placeHolder: "ship.status",
    });
  }
  if (!toolName) { return; }

  try {
    const result = await client.callTool(toolName);
    const doc = await vscode.workspace.openTextDocument({
      content: JSON.stringify(result, null, 2),
      language: "json",
    });
    await vscode.window.showTextDocument(doc, { preview: true });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Tool ${toolName} failed: ${msg}`);
  }
}

async function takeScreenshot(): Promise<void> {
  if (!client?.isConnected()) {
    vscode.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }
  try {
    const imgData = await client.screenshot();
    // Create a temp file and open it
    const uri = vscode.Uri.parse(
      `untitled:arena-screenshot-${Date.now()}.jpg`
    );
    // Show raw data in a webview
    const panel = vscode.window.createWebviewPanel(
      "arenaScreenshot",
      "Arena Desktop Screenshot",
      vscode.ViewColumn.One,
      {}
    );
    const base64 = imgData.toString("base64");
    panel.webview.html = `<!DOCTYPE html>
      <html><body style="margin:0;background:#1e1e1e;display:flex;justify-content:center;align-items:center;min-height:100vh">
        <img src="data:image/jpeg;base64,${base64}" style="max-width:100%;max-height:100vh"/>
      </body></html>`;
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    vscode.window.showErrorMessage(`Screenshot failed: ${msg}`);
  }
}

export function activate(context: vscode.ExtensionContext): void {
  // Status bar
  statusBar = new StatusBar();
  statusBar.show();
  statusBar.updateDisconnected();
  context.subscriptions.push(statusBar);

  // Create initial providers (will be replaced on connect)
  client = new BridgeClient("", "");
  dashboard = new DashboardPanel(client);
  shipProvider = new ShipStatusProvider(client);
  autopilotProvider = new AutopilotTreeProvider(client);
  gapsProvider = new GapsTreeProvider(client);
  toolsProvider = new ToolsTreeProvider(client);

  // Register tree views
  context.subscriptions.push(
    vscode.window.registerTreeDataProvider("arena.shipStatus", shipProvider),
    vscode.window.registerTreeDataProvider("arena.autopilotRuns", autopilotProvider),
    vscode.window.registerTreeDataProvider("arena.capabilityGaps", gapsProvider),
    vscode.window.registerTreeDataProvider("arena.mcpTools", toolsProvider),
  );

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand("arena.connect", connectToBridge),
    vscode.commands.registerCommand("arena.disconnect", () => {
      client?.disconnect();
      statusBar.updateDisconnected();
      stopAutoRefresh();
      refreshAll();
    }),
    vscode.commands.registerCommand("arena.refreshAll", refreshAll),
    vscode.commands.registerCommand("arena.runTool", runTool),
    vscode.commands.registerCommand("arena.screenshot", takeScreenshot),
    vscode.commands.registerCommand("arena.showDashboard", async () => {
      if (!client?.isConnected()) {
        vscode.window.showWarningMessage("Connect to bridge first (Arena: Connect to Bridge)");
        return;
      }
      await dashboard.show(context);
    }),
  );

  // Auto-connect
  const autoConnect = vscode.workspace.getConfiguration("arena").get<boolean>("autoConnect", true);
  const bridgeUrl = vscode.workspace.getConfiguration("arena").get<string>("bridgeUrl", "");
  if (autoConnect && bridgeUrl) {
    // Auto-connect is deferred — user still needs to provide token
    // In future: use SecretStorage
  }
}

export function deactivate(): void {
  stopAutoRefresh();
  client?.disconnect();
}
