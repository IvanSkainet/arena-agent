/** MCP Tools tree view — browse all bridge tools by namespace. */

import * as vscode from "vscode";
import type { BridgeClient } from "../bridge-client";
import type { McpToolDef } from "../types";

type ToolTreeItem = NamespaceItem | ToolItem;

export class ToolsTreeProvider implements vscode.TreeDataProvider<ToolTreeItem> {
  private _onDidChangeTreeData = new vscode.EventEmitter<ToolTreeItem | undefined>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
  private tools: McpToolDef[] = [];

  constructor(private client: BridgeClient) {}

  async refresh(): Promise<void> {
    if (!this.client.isConnected()) {
      this.tools = [];
    } else {
      try {
        this.tools = await this.client.listTools();
      } catch {
        this.tools = [];
      }
    }
    this._onDidChangeTreeData.fire(undefined);
  }

  getTreeItem(element: ToolTreeItem): vscode.TreeItem {
    return element;
  }

  getChildren(element?: ToolTreeItem): ToolTreeItem[] {
    if (!element) {
      // Root: group by namespace
      const namespaces = new Map<string, McpToolDef[]>();
      for (const tool of this.tools) {
        const ns = tool.name.split(".")[0] ?? "other";
        if (!namespaces.has(ns)) { namespaces.set(ns, []); }
        namespaces.get(ns)!.push(tool);
      }
      if (namespaces.size === 0) {
        const item = new vscode.TreeItem("No tools loaded");
        item.iconPath = new vscode.ThemeIcon("plug");
        return [item as unknown as ToolTreeItem];
      }
      return Array.from(namespaces.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([ns, tools]) => new NamespaceItem(ns, tools));
    }
    if (element instanceof NamespaceItem) {
      return element.tools.map((t) => new ToolItem(t));
    }
    return [];
  }
}

class NamespaceItem extends vscode.TreeItem {
  constructor(
    public readonly namespace: string,
    public readonly tools: McpToolDef[],
  ) {
    super(namespace, vscode.TreeItemCollapsibleState.Collapsed);
    this.description = `${tools.length} tools`;
    this.iconPath = new vscode.ThemeIcon("symbol-namespace");
  }
}

class ToolItem extends vscode.TreeItem {
  constructor(tool: McpToolDef) {
    super(tool.name, vscode.TreeItemCollapsibleState.None);
    this.description = tool.description.slice(0, 80);
    this.tooltip = tool.description;
    this.iconPath = new vscode.ThemeIcon("symbol-method");
    this.command = {
      command: "arena.runTool",
      title: "Run Tool",
      arguments: [tool.name],
    };
  }
}
