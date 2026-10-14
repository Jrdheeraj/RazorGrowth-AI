/**
 * Designer Agent network layer — the ONLY place this feature talks to the API.
 *
 * It calls endpoints that already exist and nothing else:
 *
 *   GET  /api/agents                       → registry entry + declared tools
 *   GET  /api/agents/runs                  → the Designer Agent's real run history
 *   GET  /api/agent-debates                → recent debates (for brief timestamps)
 *   GET  /api/agent-debates/{id}/findings  → its persisted creative briefs
 *
 * No new route is invented and no response is mocked. Each call is isolated:
 * if one endpoint is unavailable its section renders an honest empty state
 * instead of blanking the dashboard.
 */
import { fetchAgentRuns, fetchAgentsMeta, fetchDebateFindings, fetchDebateList } from "./api";
import {
  DESIGNER_DEBATE_SCAN_LIMIT,
  DESIGNER_AGENT_NAME,
  buildDesignerSnapshot,
  type DesignerFindingLike,
  type DesignerRunRowLike,
  type DesignerSnapshot,
} from "./designerAgent";

function toMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

export async function loadDesignerAgentSnapshot(): Promise<DesignerSnapshot> {
  /* Registry — "is this agent even dispatched-able?" */
  let registryEntry: { description?: unknown; tools?: unknown } | null = null;
  try {
    const meta = await fetchAgentsMeta();
    const entry = meta.agents?.find((a) => a.name === DESIGNER_AGENT_NAME);
    if (entry) {
      registryEntry = { description: entry.description, tools: entry.tools };
    }
  } catch {
    // Unreadable registry ⇒ the page reports "Not registered" instead of
    // guessing. It never claims a connected or available state it cannot prove.
  }

  /* Run history — metrics, projects and the activity timeline. */
  let runRows: DesignerRunRowLike[] | null = null;
  try {
    const runsResp = await fetchAgentRuns(200);
    runRows = runsResp.runs as DesignerRunRowLike[];
  } catch {
    // No run history ⇒ every metric reads 0 and every list shows its empty state.
  }

  /* Creative briefs — the Designer Agent's persisted Agent Findings. */
  let debates: Array<{ id: string; objective: string; updatedAt: number | null }> = [];
  let findingsByDebate: Map<string, DesignerFindingLike[]> | null = null;
  try {
    const debatesResp = await fetchDebateList();
    const all = [...(debatesResp.debates ?? [])].sort(
      (a, b) =>
        Date.parse(b.updated_at ?? b.created_at ?? "") -
        Date.parse(a.updated_at ?? a.created_at ?? ""),
    );
    debates = all
      .slice(0, DESIGNER_DEBATE_SCAN_LIMIT)
      .map((d) => ({
        id: d.id,
        objective: d.objective,
        updatedAt: toMs(d.updated_at ?? d.created_at),
      }));

    findingsByDebate = new Map();
    for (const debate of debates) {
      try {
        const resp = await fetchDebateFindings(debate.id);
        findingsByDebate.set(debate.id, resp.findings as DesignerFindingLike[]);
      } catch {
        findingsByDebate.set(debate.id, []);
      }
    }
  } catch {
    // No debate access ⇒ the outputs section renders its empty state.
  }

  return buildDesignerSnapshot({
    registryEntry,
    runRows,
    debates,
    findingsByDebate: findingsByDebate ?? undefined,
  });
}