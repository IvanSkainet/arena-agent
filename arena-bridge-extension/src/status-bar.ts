/** Status bar items for Arena Bridge. */

import * as vscode from "vscode";
import type { BridgeClient } from "./bridge-client";

export class StatusBar {
  private connectionItem: vscode.StatusBarItem;
  private modeItem: vscode.StatusBarItem;

  constructor() {
    this.connectionItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.connectionItem.command = "arena.connect";
    this.connectionItem.tooltip = "Arena Bridge connection";

    this.modeItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 99);
    this.modeItem.command = "arena.showDashboard";
    this.modeItem.tooltip = "Ship mode — click for dashboard";
  }

  show(): void {
    this.connectionItem.show();
  }

  updateDisconnected(): void {
    this.connectionItem.text = "$(plug) Arena: Disconnected";
    this.connectionItem.backgroundColor = undefined;
    this.modeItem.hide();
  }

  updateConnecting(): void {
    this.connectionItem.text = "$(sync~spin) Arena: Connecting...";
    this.modeItem.hide();
  }

  updateConnected(version: string): void {
    this.connectionItem.text = `$(check) Arena v${version}`;
    this.connectionItem.backgroundColor = undefined;
  }

  updateShipMode(mode: string, ready: boolean): void {
    const icons: Record<string, string> = {
      nominal: "$(shield)",
      armed: "$(flame)",
      blocked: "$(error)",
      unknown: "$(question)",
    };
    const colors: Record<string, vscode.ThemeColor | undefined> = {
      nominal: undefined,
      armed: new vscode.ThemeColor("statusBarItem.warningBackground"),
      blocked: new vscode.ThemeColor("statusBarItem.errorBackground"),
    };
    const icon = icons[mode] ?? icons.unknown;
    this.modeItem.text = `${icon} ${mode}${ready ? "" : " (not ready)"}`;
    this.modeItem.backgroundColor = colors[mode];
    this.modeItem.show();
  }

  updateError(msg: string): void {
    this.connectionItem.text = `$(error) Arena: ${msg}`;
    this.connectionItem.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
    this.modeItem.hide();
  }

  dispose(): void {
    this.connectionItem.dispose();
    this.modeItem.dispose();
  }
}
