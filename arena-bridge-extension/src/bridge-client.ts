/** HTTP client for the Arena Unified Bridge. */

import * as https from "https";
import * as http from "http";
import type {
  BridgeVersion,
  ShipPreflight,
  AutopilotRun,
  CapabilityGap,
  MissionControlStatus,
  McpToolDef,
  AuditDigest,
} from "./types";

export class BridgeClient {
  private url: string;
  private token: string;
  private connected = false;
  private version: BridgeVersion | null = null;

  constructor(url: string, token: string) {
    this.url = url.replace(/\/+$/, "");
    this.token = token;
  }

  isConnected(): boolean {
    return this.connected;
  }

  getVersion(): BridgeVersion | null {
    return this.version;
  }

  async connect(): Promise<BridgeVersion> {
    const ver = await this.get<BridgeVersion>("/v1/version");
    this.version = ver;
    this.connected = ver.ok;
    return ver;
  }

  disconnect(): void {
    this.connected = false;
    this.version = null;
  }

  // --- MCP tool call ---
  async callTool(name: string, args: Record<string, unknown> = {}): Promise<unknown> {
    const payload = {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name, arguments: args },
    };
    const result = await this.post<{ result?: { content?: Array<{ text?: string }> } }>("/mcp", payload);
    const text = result?.result?.content?.[0]?.text ?? "{}";
    try {
      return JSON.parse(text);
    } catch {
      return { text };
    }
  }

  // --- Convenience methods ---
  async shipPreflight(): Promise<ShipPreflight> {
    return (await this.callTool("ship.preflight")) as ShipPreflight;
  }

  async missionControl(): Promise<MissionControlStatus> {
    return (await this.callTool("mission.control_status")) as MissionControlStatus;
  }

  async autopilotList(limit = 10): Promise<{ runs: AutopilotRun[] }> {
    return (await this.callTool("mission.autopilot_list", { limit })) as { runs: AutopilotRun[] };
  }

  async capabilityGaps(): Promise<{ gaps: CapabilityGap[] }> {
    return (await this.callTool("capability_gap.list", { status: "open" })) as { gaps: CapabilityGap[] };
  }

  async auditDigest(minutes = 60): Promise<AuditDigest> {
    return (await this.callTool("audit.digest", { minutes })) as AuditDigest;
  }

  async listTools(): Promise<McpToolDef[]> {
    const payload = {
      jsonrpc: "2.0",
      id: 1,
      method: "tools/list",
    };
    const result = await this.post<{ result?: { tools?: McpToolDef[] } }>("/mcp", payload);
    return result?.result?.tools ?? [];
  }

  async screenshot(): Promise<Buffer> {
    return this.getRaw("/v1/desktop/screenshot?format=jpeg&scale=0.5&quality=75");
  }

  // --- HTTP helpers ---
  private get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  private post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  private getRaw(path: string): Promise<Buffer> {
    return new Promise((resolve, reject) => {
      const fullUrl = new URL(this.url + path);
      const mod = fullUrl.protocol === "https:" ? https : http;
      const req = mod.request(
        fullUrl,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${this.token}`,
          },
          rejectUnauthorized: false,
        },
        (res) => {
          const chunks: Buffer[] = [];
          res.on("data", (chunk: Buffer) => chunks.push(chunk));
          res.on("end", () => resolve(Buffer.concat(chunks)));
        }
      );
      req.on("error", reject);
      req.setTimeout(15000, () => {
        req.destroy(new Error("timeout"));
      });
      req.end();
    });
  }

  private request<T>(method: string, path: string, body?: unknown): Promise<T> {
    return new Promise((resolve, reject) => {
      const fullUrl = new URL(this.url + path);
      const mod = fullUrl.protocol === "https:" ? https : http;
      const data = body ? JSON.stringify(body) : undefined;
      const req = mod.request(
        fullUrl,
        {
          method,
          headers: {
            Authorization: `Bearer ${this.token}`,
            "Content-Type": "application/json",
            ...(data ? { "Content-Length": Buffer.byteLength(data).toString() } : {}),
          },
          rejectUnauthorized: false,
        },
        (res) => {
          const chunks: string[] = [];
          res.setEncoding("utf-8");
          res.on("data", (chunk: string) => chunks.push(chunk));
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
      req.setTimeout(15000, () => {
        req.destroy(new Error("timeout"));
      });
      if (data) {
        req.write(data);
      }
      req.end();
    });
  }
}
