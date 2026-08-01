/** Shared types for the Arena Bridge extension. */

export interface BridgeVersion {
  ok: boolean;
  version: string;
  service: string;
  python: string;
  platform: string;
}

export interface ShipPreflight {
  ok: boolean;
  ready: boolean;
  mode: string;
  armed: boolean;
  failed: ShipCheck[];
}

export interface ShipCheck {
  name: string;
  ok: boolean;
  severity: string;
  detail?: string;
}

export interface AutopilotRun {
  run_id: string;
  goal: string;
  status: string;
  outcome: string;
  created_at: string;
  finished_at?: string;
  scenario: string;
  step_count?: number;
}

export interface CapabilityGap {
  id: string;
  title: string;
  severity: string;
  status: string;
  created_at: string;
  updated_at: string;
  scenario?: string;
}

export interface MissionControlStatus {
  ok: boolean;
  timestamp: string;
  ship: {
    mode: string;
    ready: boolean;
    failed_checks: ShipCheck[];
  };
  autopilot: {
    recent_runs: AutopilotRun[];
    total: number;
  };
  capability_gaps: {
    open_count: number;
    gaps: CapabilityGap[];
  };
  scenarios: {
    recent_records: unknown[];
  };
  desktop: {
    window_count: number;
  };
  mobile: {
    ok: boolean;
    device_count: number;
  };
}

export interface McpToolDef {
  name: string;
  description: string;
  inputSchema: {
    type: string;
    properties: Record<string, unknown>;
    required?: string[];
  };
}

export interface AuditDigest {
  ok: boolean;
  total: number;
  minutes: number;
  by_risk: Record<string, number>;
  by_category: Record<string, number>;
  external_count: number;
  recent_high_risk: Array<{
    ts: string;
    tool: string;
    risk: string;
    category: string;
    external: boolean;
  }>;
}
