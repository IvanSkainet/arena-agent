/** Autopilot Runs tree view. */

import * as vscode from "vscode";
import type { BridgeClient } from "../bridge-client";
import type { AutopilotRun } from "../types";

export class AutopilotTreeProvider implements vscode.TreeDataProvider<AutopilotRunItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<AutopilotRunItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  private runs: AutopilotRun[] = [];

  constructor(private client: BridgeClient) {}

  async refresh(): Promise<void> {
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
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: AutopilotRunItem): vscode.TreeItem {
    return element;
  }

  getChildren(): AutopilotRunItem[] {
    if (!this.runs.length) {
      const item = new vscode.TreeItem("No autopilot runs");
      item.iconPath = new vscode.ThemeIcon("history");
      return [item as unknown as AutopilotRunItem];
    }
    return this.runs.map((r) => new AutopilotRunItem(r));
  }
}

class AutopilotRunItem extends vscode.TreeItem {
  constructor(run: AutopilotRun) {
    const label = run.goal.length > 50 ? run.goal.slice(0, 47) + "..." : run.goal;
    super(label, vscode.TreeItemCollapsibleState.None);

    const iconMap: Record<string, string> = {
      nominal: "pass",
      partial: "warning",
      cancelled: "circle-slash",
      running: "sync~spin",
      error: "error",
    };
    this.iconPath = new vscode.ThemeIcon(iconMap[run.status] ?? "question");
    this.description = run.status;
    this.tooltip = `${run.goal}\nStatus: ${run.status}\nOutcome: ${run.outcome}\nCreated: ${run.created_at}`;
  }
}
