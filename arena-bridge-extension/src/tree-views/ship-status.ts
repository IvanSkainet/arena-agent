/** Ship Status tree view. */

import * as vscode from "vscode";
import type { BridgeClient } from "../bridge-client";
import type { ShipPreflight, ShipCheck } from "../types";

type TreeItem = ShipModeItem | ShipCheckItem;

export class ShipStatusProvider implements vscode.TreeDataProvider<TreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<TreeItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  private preflight: ShipPreflight | null = null;

  constructor(private client: BridgeClient) {}

  async refresh(): Promise<void> {
    if (!this.client.isConnected()) {
      this.preflight = null;
    } else {
      try {
        this.preflight = await this.client.shipPreflight();
      } catch {
        this.preflight = null;
      }
    }
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: TreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: TreeItem): TreeItem[] {
    if (element) { return []; }
    if (!this.preflight) {
      const item = new vscode.TreeItem("Not connected");
      item.iconPath = new vscode.ThemeIcon("plug");
      return [item as unknown as TreeItem];
    }
    const items: TreeItem[] = [];
    items.push(new ShipModeItem(this.preflight.mode, this.preflight.ready));

    if (this.preflight.failed && this.preflight.failed.length > 0) {
      for (const check of this.preflight.failed) {
        items.push(new ShipCheckItem(check));
      }
    }
    return items;
  }
}

class ShipModeItem extends vscode.TreeItem {
  constructor(mode: string, ready: boolean) {
    super(`Mode: ${mode}${ready ? " ✓" : " (not ready)"}`, vscode.TreeItemCollapsibleState.None);
    const iconMap: Record<string, string> = {
      nominal: "shield",
      armed: "flame",
      blocked: "error",
    };
    this.iconPath = new vscode.ThemeIcon(iconMap[mode] ?? "question");
    this.description = ready ? "ready" : "not ready";
  }
}

class ShipCheckItem extends vscode.TreeItem {
  constructor(check: ShipCheck) {
    super(check.name, vscode.TreeItemCollapsibleState.None);
    this.iconPath = new vscode.ThemeIcon(check.ok ? "pass" : "error");
    this.description = check.detail ?? check.severity;
  }
}
