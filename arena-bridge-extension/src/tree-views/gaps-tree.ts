/** Capability Gaps tree view. */

import * as vscode from "vscode";
import type { BridgeClient } from "../bridge-client";
import type { CapabilityGap } from "../types";

export class GapsTreeProvider implements vscode.TreeDataProvider<GapItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<GapItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  private gaps: CapabilityGap[] = [];

  constructor(private client: BridgeClient) {}

  async refresh(): Promise<void> {
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
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: GapItem): vscode.TreeItem {
    return element;
  }

  getChildren(): GapItem[] {
    if (!this.gaps.length) {
      const item = new vscode.TreeItem("No open capability gaps");
      item.iconPath = new vscode.ThemeIcon("check-all");
      return [item as unknown as GapItem];
    }
    return this.gaps.map((g) => new GapItem(g));
  }
}

class GapItem extends vscode.TreeItem {
  constructor(gap: CapabilityGap) {
    super(gap.title, vscode.TreeItemCollapsibleState.None);
    const sevIcons: Record<string, string> = {
      critical: "error",
      high: "warning",
      medium: "info",
      low: "circle-outline",
    };
    this.iconPath = new vscode.ThemeIcon(sevIcons[gap.severity] ?? "circle-outline");
    this.description = `${gap.severity} · ${gap.status}`;
    this.tooltip = `${gap.title}\nSeverity: ${gap.severity}\nStatus: ${gap.status}\nCreated: ${gap.created_at}`;
  }
}
