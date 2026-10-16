/**
 * specialistRoster â€” registry-driven view model for the AI Team dashboard.
 *
 * Every value here is derived from what the backend actually reports. The
 * module deliberately refuses to invent anything:
 *
 *   * an agent with no catalogued tools shows "no tools registered", not a
 *     fabricated capability list;
 *   * a tool name the registry could not resolve is surfaced in
 *     `unimplementedTools` so the merchant sees the gap instead of a lie;
 *   * a run that is missing, failed or degraded is reported with its real
 *     status â€” never upgraded to "healthy".
 *
 * It is a pure transform (no React, no fetch) so it can be unit tested the
 * same way the rest of frontend/src/lib is tested.
 *
 * Types are declared locally and structurally, exactly like
 * `designerAgent.ts` does, so this module can be compiled and tested in
 * isolation without dragging in `api.ts` (which uses extensionless imports
 * that `tsc --module nodenext` cannot resolve on its own).
 */

/** Mirrors AgentToolSpec in api.ts. */
export interface ToolSpecLike {
  tool_id: string;
  summary: string;
  read_only: boolean;
  required_permission: string | null;
  timeout_seconds: number;
  input_fields: string[];
  output_fields: string[];
  source: string;
}

/** Mirrors AgentCatalogEntryLike in api.ts. */
export interface AgentCatalogEntryLike {
  name: string;
  description: string;
  category: string;
  permissions: string[];
  tools: string[];
  unimplemented_tools: string[];
  tool_details: ToolSpecLike[];
  can_approve: boolean;
  can_execute: boolean;
}

/** Mirrors AgentRunLike in api.ts. */
export interface AgentRunLike {
  agent: string;
  status: string;
  ok: boolean;
  output: Record<string, unknown>;
  errors: string[];
  tools_used: string[];
  opportunities_created: number;
  actions_proposed: number;
  insights_generated: number;
  signals_detected: number;
  experiments_proposed: number;
  latency_ms: { total: number; llm: number; db: number };
  llm_configured: boolean;
}

export interface CatalogLike {
  tools: ToolSpecLike[];
  tool_count: number;
  agents: AgentCatalogEntryLike[];
  agent_count: number;
}

export type RunPhase =
  | "idle"
  | "running"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "approval_required";

export interface ToolView {
  id: string;
  summary: string;
  readOnly: boolean;
  permission: string;
  source: string;
}

export interface RosterAgent {
  name: string;
  description: string;
  category: "main_growth_team" | "domain_specialist";
  permissions: string[];
  tools: ToolView[];
  unimplementedTools: string[];
  hasUnimplementedTools: boolean;
  /** True only when every advertised tool resolves to a real implementation. */
  fullyImplemented: boolean;
  canApprove: boolean;
  canExecute: boolean;
  status: RunPhase;
  lastRun: AgentRunLike | null;
  /** Human-readable one-liner describing the agent's CURRENT real state. */
  statusLabel: string;
}

export interface RosterSummary {
  agents: RosterAgent[];
  totalAgents: number;
  totalTools: number;
  fullyImplementedAgents: number;
  agentsWithUnimplementedTools: number;
  runningAgents: number;
  failedAgents: number;
  /** True when the backend reported no agents at all. */
  isEmpty: boolean;
  /** True when the backend responded but we could not build a roster. */
  isError: boolean;
}

const READ_ONLY_LABEL = "read-only";

export function toToolView(spec: ToolSpecLike): ToolView {
  return {
    id: spec.tool_id,
    summary: spec.summary || "No description provided.",
    readOnly: spec.read_only,
    permission: spec.required_permission ?? "none",
    source: spec.source || "unregistered",
  };
}

/**
 * Derive a run phase from a real run response.
 * `approval_required` is derived from actual proposed actions, not assumed.
 */
export function phaseForRun(run: AgentRunLike | null): RunPhase {
  if (!run) return "idle";
  if (run.status === "cancelled") return "cancelled";
  if (run.status === "failed" || run.status === "failed".toLowerCase()) return "failed";
  if (run.ok) return run.actions_proposed > 0 ? "approval_required" : "completed";
  return "partial";
}

export function statusLabelFor(agent: Omit<RosterAgent, "statusLabel">): string {
  switch (agent.status) {
    case "running":
      return "Runningâ€¦";
    case "completed":
      return "Completed";
    case "partial":
      return `Completed with warnings (${agent.lastRun?.errors.length ?? 0})`;
    case "failed":
      return agent.lastRun?.errors?.[0] || "Failed";
    case "cancelled":
      return "Cancelled";
    case "approval_required":
      return `${agent.lastRun?.actions_proposed ?? 0} action(s) awaiting approval`;
    default:
      return agent.tools.length === 0
        ? "No tools registered"
        : "Idle â€” not run yet";
  }
}

export function buildRoster(
  catalog: CatalogLike | null,
  runs: Record<string, AgentRunLike | null> = {},
): RosterSummary {
  if (!catalog || !Array.isArray(catalog.agents)) {
    return {
      agents: [],
      totalAgents: 0,
      totalTools: 0,
      fullyImplementedAgents: 0,
      agentsWithUnimplementedTools: 0,
      runningAgents: 0,
      failedAgents: 0,
      isEmpty: true,
      isError: true,
    };
  }

  const agents: RosterAgent[] = catalog.agents.map((entry: AgentCatalogEntryLike) => {
    const tools = (entry.tool_details ?? []).map(toToolView);
    const unimplemented = entry.unimplemented_tools ?? [];
    const run = runs[entry.name] ?? null;
    const base = {
      name: entry.name,
      description: entry.description || "No mission recorded.",
      category:
        entry.category === "main_growth_team"
          ? ("main_growth_team" as const)
          : ("domain_specialist" as const),
      permissions: entry.permissions ?? [],
      tools,
      unimplementedTools: unimplemented,
      hasUnimplementedTools: unimplemented.length > 0,
      // "Fully implemented" means every advertised tool resolves â€” it never
      // means "the agent is powerful".
      fullyImplemented: tools.length > 0 && unimplemented.length === 0,
      canApprove: entry.can_approve === true,
      canExecute: entry.can_execute === true,
      status: phaseForRun(run),
      lastRun: run,
    };
    return { ...base, statusLabel: statusLabelFor(base) };
  });

  return {
    agents,
    totalAgents: agents.length,
    totalTools: catalog.tool_count ?? 0,
    fullyImplementedAgents: agents.filter((a) => a.fullyImplemented).length,
    agentsWithUnimplementedTools: agents.filter((a) => a.hasUnimplementedTools).length,
    runningAgents: agents.filter((a) => a.status === "running").length,
    failedAgents: agents.filter((a) => a.status === "failed").length,
    isEmpty: agents.length === 0,
    isError: false,
  };
}

export function groupByCategory(roster: RosterSummary): {
  main: RosterAgent[];
  specialists: RosterAgent[];
} {
  return {
    main: roster.agents.filter((a) => a.category === "main_growth_team"),
    specialists: roster.agents.filter((a) => a.category === "domain_specialist"),
  };
}

export function toolSummary(agent: RosterAgent): string {
  if (agent.tools.length === 0) return "No tools registered";
  const readOnly = agent.tools.filter((t) => t.readOnly).length;
  return `${agent.tools.length} tool(s) Â· ${readOnly} ${READ_ONLY_LABEL}`;
}

