/** Interactive tool runner — prompts for JSON arguments. */

import * as vscode from "vscode";
import type { BridgeClient } from "../bridge-client";
import type { McpToolDef } from "../types";

export async function runToolInteractive(client: BridgeClient, toolName?: string): Promise<void> {
  if (!client.isConnected()) {
    vscode.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }

  // If no tool name, show quick pick from all tools
  if (!toolName) {
    const tools = await client.listTools();
    const items = tools.map((t) => ({
      label: t.name,
      description: t.description.slice(0, 80),
      detail: t.inputSchema.required?.length
        ? `Required: ${t.inputSchema.required.join(", ")}`
        : "No required params",
      tool: t,
    }));

    const picked = await vscode.window.showQuickPick(items, {
      placeHolder: "Select MCP tool to run",
      matchOnDescription: true,
    });
    if (!picked) { return; }
    toolName = picked.label;
  }

  // Get tool schema for context
  let toolDef: McpToolDef | undefined;
  try {
    const tools = await client.listTools();
    toolDef = tools.find((t) => t.name === toolName);
  } catch { /* ignore */ }

  // Build default args from schema
  let defaultArgs = "{}";
  if (toolDef?.inputSchema?.properties) {
    const props = toolDef.inputSchema.properties;
    const example: Record<string, unknown> = {};
    for (const [key, schema] of Object.entries(props)) {
      const s = schema as Record<string, unknown>;
      if (s.default !== undefined) {
        example[key] = s.default;
      } else if (s.type === "string") {
        example[key] = "";
      } else if (s.type === "integer" || s.type === "number") {
        example[key] = 0;
      } else if (s.type === "boolean") {
        example[key] = false;
      }
    }
    // Only include required fields + defaults
    const required = new Set(toolDef.inputSchema.required ?? []);
    const filtered: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(example)) {
      if (required.has(k) || v !== "" && v !== 0 && v !== false) {
        filtered[k] = v;
      }
    }
    if (Object.keys(filtered).length > 0) {
      defaultArgs = JSON.stringify(filtered, null, 2);
    }
  }

  // Prompt for arguments
  const argsStr = await vscode.window.showInputBox({
    prompt: `Arguments for ${toolName} (JSON)`,
    value: defaultArgs,
    placeHolder: '{"key": "value"}',
    validateInput: (value) => {
      if (!value.trim()) { return null; } // empty = {}
      try {
        JSON.parse(value);
        return null;
      } catch {
        return "Invalid JSON";
      }
    },
  });
  if (argsStr === undefined) { return; } // cancelled

  const args = argsStr.trim() ? JSON.parse(argsStr) : {};

  // Execute with progress
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Running ${toolName}...`,
      cancellable: false,
    },
    async () => {
      try {
        const result = await client.callTool(toolName!, args);
        const content = JSON.stringify(result, null, 2);
        const doc = await vscode.workspace.openTextDocument({
          content: `// Result of ${toolName}\n// Args: ${JSON.stringify(args)}\n${content}`,
          language: "jsonc",
        });
        await vscode.window.showTextDocument(doc, { preview: true });
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`${toolName} failed: ${msg}`);
      }
    }
  );
}

/** Start autopilot from a goal entered by the user. */
export async function startAutopilotFromGoal(client: BridgeClient): Promise<void> {
  if (!client.isConnected()) {
    vscode.window.showWarningMessage("Not connected to Arena Bridge");
    return;
  }

  const goal = await vscode.window.showInputBox({
    prompt: "Enter autopilot goal (natural language)",
    placeHolder: "check ship status and desktop windows",
  });
  if (!goal) { return; }

  const mode = await vscode.window.showQuickPick(
    [
      { label: "Synchronous", description: "Wait for completion", value: "sync" },
      { label: "Async (background)", description: "Returns immediately", value: "async" },
    ],
    { placeHolder: "Execution mode" }
  );
  if (!mode) { return; }

  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Autopilot: ${goal}`,
      cancellable: false,
    },
    async () => {
      try {
        const toolName = mode.value === "async"
          ? "mission.autopilot_start_async"
          : "mission.autopilot_from_goal";
        const result = await client.callTool(toolName, { goal });
        const content = JSON.stringify(result, null, 2);
        const doc = await vscode.workspace.openTextDocument({
          content: `// Autopilot: ${goal}\n${content}`,
          language: "jsonc",
        });
        await vscode.window.showTextDocument(doc, { preview: true });

        const r = result as Record<string, unknown>;
        if (r.ok) {
          vscode.window.showInformationMessage(
            `Autopilot ${r.status}: ${(r as Record<string, unknown>).outcome ?? "started"}`
          );
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Autopilot failed: ${msg}`);
      }
    }
  );
}
