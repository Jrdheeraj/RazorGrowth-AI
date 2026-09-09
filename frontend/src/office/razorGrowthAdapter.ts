import type { OfficeAgent } from "./OfficeFloor";

// Map RazorGrowth's 13 specialist agents to distinct Office characters.
// ManagerAgent is the god (Michael, seated at desk-ceo). Others cycle through the cast.
const RG_TO_OFFICE_CHARACTER: Record<string, string> = {
  ManagerAgent: "michael",
  GrowthMemoryAgent: "jim",
  GrowthDiscoveryAgent: "pam",
  CustomerIntelligenceAgent: "dwight",
  RevenueOptimizationAgent: "kevin",
  PaymentRecoveryAgent: "angela",
  MarketingAgent: "oscar",
  ProductAgent: "stanley",
  CampaignStrategistAgent: "phyllis",
  DesignerAgent: "andy",
  SoftwareAgent: "kelly",
  ExperimentAgent: "ryan",
  OpportunityPrioritizationAgent: "toby",
  // fallbacks for any future agent
  GrowthRadarAgent: "creed",
  CustomerSuccessAgent: "meredith",
};

const ACCENT_CYCLE = ["coral", "mint", "sky", "lemon", "lilac", "peach"] as const;

export type RazorAgentLiveStatus =
  | "IDLE"
  | "WAITING"
  | "WORKING"
  | "THINKING"
  | "TOOL_CALL"
  | "ANALYZING"
  | "COMMUNICATING"
  | "COMPLETED"
  | "BLOCKED"
  | "ERROR"
  | "NEEDS_APPROVAL";

export function mapLiveStatus(s: RazorAgentLiveStatus): OfficeAgent["status"] {
  switch (s) {
    case "WORKING":
    case "TOOL_CALL":
    case "ANALYZING":
    case "COMMUNICATING":
      return "working";
    case "THINKING":
      return "thinking";
    case "COMPLETED":
      return "success";
    case "BLOCKED":
    case "NEEDS_APPROVAL":
    case "ERROR":
      return "blocked";
    case "WAITING":
      return "waiting";
    case "IDLE":
    default:
      return "idle";
  }
}

export function toOfficeCharacter(razorKey: string): string {
  return RG_TO_OFFICE_CHARACTER[razorKey] ?? "jim";
}

export function accentForIndex(i: number): string {
  return ACCENT_CYCLE[i % ACCENT_CYCLE.length];
}

/**
 * Build OfficeAgent list from RazorGrowth live data.
 * Call this inside AgentsPage after deriving agent statuses.
 */
export function buildOfficeAgents(
  order: string[],
  getLive: (key: string, idx: number) => { status: RazorAgentLiveStatus; action: string },
): OfficeAgent[] {
  return order.map((key, idx) => {
    const live = getLive(key, idx);
    return {
      id: key,
      name: key.replace(/Agent$/, ""),
      character: toOfficeCharacter(key),
      status: mapLiveStatus(live.status),
      action: live.action,
      accent: accentForIndex(idx + (key === "ManagerAgent" ? 3 : 0)),
      isGod: key === "ManagerAgent",
      carrying: live.status === "TOOL_CALL" ? "Bash" : undefined,
    };
  });
}
