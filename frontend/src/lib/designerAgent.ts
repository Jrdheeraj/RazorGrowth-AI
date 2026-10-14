/**
 * Designer Agent read model — frontend only.
 *
 * The backend has NO `/api/designer-*` surface: the Designer Agent is one of the
 * thirteen registered specialists (`GET /api/agents`), it is dispatched by the
 * shared AI Team cycle (`POST /api/agents/run`) and it persists its creative
 * briefs as Agent Findings inside an Agent Debate
 * (`GET /api/agent-debates/{id}/findings`, `agent_specialty = "designer"`).
 *
 * This module maps THOSE existing records into the dashboard's read model. It
 * invents no API, mocks nothing and hardcodes no business number: every value it
 * returns is either derived from a real backend record or an explicit `null`
 * that the UI renders as an honest empty state.
 *
 * Deliberately import-free (the network layer lives in `designerAgentApi.ts`)
 * so the whole mapping is unit-testable with plain `tsc` + `node`, matching the
 * convention used by `activityStatus.ts` and `productAgentStatus.ts`.
 * The two input shapes below are structurally satisfied by the backend
 * contracts `AgentRunRow` and `AgentFinding` in `types/api.ts`.
 */

/** Registry key of the specialist (matches backend/app/agents/registry.py). */
export const DESIGNER_AGENT_NAME = "DesignerAgent";

/** Debate `agent_specialty` used by the Designer Agent's persisted findings. */
export const DESIGNER_SPECIALTY = "designer";

/** Run statuses that mean "the agent is mid-flight right now". */
const ACTIVE_STATUSES = new Set(["queued", "running", "pending"]);

export type DesignerTone = "ok" | "accent" | "neutral";

/* ── Backend record shapes (structural, not imported) ──────────────────── */

export interface DesignerRunRowLike {
  id: string;
  agent_name: string;
  status: string;
  mode: string;
  orchestrator_run_id: string | null;
  started_at: string;
  completed_at: string | null;
  total_latency_ms: number;
  opportunities_created: number;
  actions_proposed: number;
  tools_used: unknown;
  errors: string[] | null;
}

export type DesignerFindingType = "supporting" | "opposing" | "neutral" | "uncertainty";

export interface DesignerFindingLike {
  id: string;
  agent_specialty: string;
  finding_type: DesignerFindingType;
  title: string;
  description: string | null;
  confidence: number;
  uncertainty_notes: string | null;
  supports_recommendation: boolean | null;
}

/* ── Normalized records ────────────────────────────────────────────────── */

export interface DesignerRunSummary {
  id: string;
  status: string;
  mode: string;
  cycleId: string | null;
  startedAt: number | null;
  completedAt: number | null;
  latencyMs: number | null;
  tools: string[];
  opportunities: number;
  actionsProposed: number;
  error: string | null;
}

export interface DesignerFindingSummary {
  id: string;
  title: string;
  description: string | null;
  findingType: DesignerFindingType;
  confidence: number;
  uncertainty: string | null;
  supportsRecommendation: boolean | null;
  debateId: string | null;
  debateObjective: string | null;
  /** Parent debate timestamp — findings carry no timestamp of their own. */
  recordedAt: number | null;
}

export interface DesignerMetric {
  key: string;
  label: string;
  value: string;
  /** Real, derived detail. Never a made-up delta. */
  hint: string;
  tone: DesignerTone;
}

export interface DesignerActivityItem {
  id: string;
  title: string;
  detail: string;
  at: number | null;
  tone: DesignerTone;
  kind: "run" | "brief";
}

export interface DesignerProjectRow {
  id: string;
  project: string;
  type: string;
  status: string;
  statusTone: DesignerTone;
  updatedAt: number | null;
  tools: string[];
  error: string | null;
}

export interface DesignerOutput {
  id: string;
  title: string;
  kind: string;
  body: string;
  reviewLabel: string;
  reviewTone: DesignerTone;
  confidence: number | null;
  source: string;
}

export interface DesignerSnapshot {
  /** The Designer Agent is present in the backend registry. */
  registered: boolean;
  registryDescription: string | null;
  /** The agent's real MCP tool names, straight from the registry. */
  tools: string[];
  runs: DesignerRunSummary[];
  latest: DesignerRunSummary | null;
  findings: DesignerFindingSummary[];
  /** Set when at least one Designer Agent run is queued or running. */
  inFlight: boolean;
}

/* ── Small helpers ─────────────────────────────────────────────────────── */

function toMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : t;
}

function toTools(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((t): t is string => typeof t === "string" && t.length > 0);
}

function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  return id.length > 8 ? `${id.slice(0, 8)}…` : id;
}

/** "Cycle a1b2c3d4" — the table already prints the full run id separately. */
export function designerCycleLabel(cycleId: string | null): string {
  if (!cycleId) return "Standalone run";
  return `Cycle ${shortId(cycleId)}`;
}

export function designerModeLabel(mode: string): string {
  switch (mode) {
    case "growth_team": return "AI Growth Team debate";
    case "team": return "AI Team workspace";
    case "deep": return "Deep analysis";
    case "fast": return "Fast analysis";
    case "": return "Analysis";
    default: return mode.replace(/_/g, " ");
  }
}

export function relativeTime(at: number | null, now: number): string {
  if (at === null) return "Unknown time";
  const seconds = Math.round((now - at) / 1000);
  if (seconds < 45) return "Just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} d ago`;
  return new Date(at).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export function formatTimestamp(at: number | null): string {
  if (at === null) return "—";
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/* ── Mapping: agent runs ───────────────────────────────────────────────── */

export function designerRunsFromRows(rows: DesignerRunRowLike[] | null | undefined): DesignerRunSummary[] {
  if (!Array.isArray(rows)) return [];
  return rows
    .filter((r) => r && r.agent_name === DESIGNER_AGENT_NAME)
    .map<DesignerRunSummary>((r) => ({
      id: String(r.id),
      status: String(r.status ?? "unknown"),
      mode: String(r.mode ?? ""),
      cycleId: r.orchestrator_run_id ?? null,
      startedAt: toMs(r.started_at),
      completedAt: toMs(r.completed_at),
      latencyMs: typeof r.total_latency_ms === "number" && r.total_latency_ms > 0 ? r.total_latency_ms : null,
      tools: toTools(r.tools_used),
      opportunities: typeof r.opportunities_created === "number" ? r.opportunities_created : 0,
      actionsProposed: typeof r.actions_proposed === "number" ? r.actions_proposed : 0,
      error: Array.isArray(r.errors) && r.errors.length > 0 ? String(r.errors[0]) : null,
    }))
    .sort((a, b) => (b.startedAt ?? 0) - (a.startedAt ?? 0));
}

/* ── Mapping: persisted creative briefs (Agent Findings) ───────────────── */

export function designerFindingsFrom(
  findings: DesignerFindingLike[] | null | undefined,
  debateId: string | null,
  debateObjective: string | null,
  recordedAt: number | null,
): DesignerFindingSummary[] {
  if (!Array.isArray(findings)) return [];
  return findings
    .filter((f) => f && f.agent_specialty === DESIGNER_SPECIALTY)
    .map<DesignerFindingSummary>((f) => ({
      id: String(f.id),
      title: String(f.title ?? "Untitled creative brief"),
      description: f.description ?? null,
      findingType: (f.finding_type ?? "neutral") as DesignerFindingType,
      confidence: typeof f.confidence === "number" ? f.confidence : 0,
      uncertainty: f.uncertainty_notes ?? null,
      supportsRecommendation:
        typeof f.supports_recommendation === "boolean" ? f.supports_recommendation : null,
      debateId,
      debateObjective,
      recordedAt,
    }));
}

/** Classify a real Designer Agent finding into one of the agent's own tools. */
export function designerOutputKind(finding: DesignerFindingSummary): string {
  const haystack = `${finding.title} ${finding.description ?? ""}`.toLowerCase();
  if (haystack.includes("ux") || haystack.includes("checkout") || haystack.includes("friction") || haystack.includes("experience")) {
    return "UX recommendation";
  }
  if (haystack.includes("messaging") || haystack.includes("trust badge") || haystack.includes("copy")) {
    return "Messaging strategy";
  }
  if (haystack.includes("variant") || haystack.includes("experiment") || haystack.includes("a/b")) {
    return "Experiment variants";
  }
  if (haystack.includes("creative") || haystack.includes("concept") || haystack.includes("visual")) {
    return "Creative concept";
  }
  return "Design finding";
}

function reviewLabel(finding: DesignerFindingSummary): { label: string; tone: DesignerTone } {
  switch (finding.findingType) {
    case "supporting":
      return { label: "Supports plan", tone: "ok" };
    case "opposing":
      return { label: "Challenges plan", tone: "accent" };
    case "uncertainty":
      return { label: "Open question", tone: "neutral" };
    default:
      return { label: "Neutral note", tone: "neutral" };
  }
}

export function designerOutputs(findings: DesignerFindingSummary[]): DesignerOutput[] {
  return findings.map<DesignerOutput>((f) => {
    const review = reviewLabel(f);
    const source = f.debateObjective
      ? `AI Team debate · ${f.debateObjective.slice(0, 72)}${f.debateObjective.length > 72 ? "…" : ""}`
      : "AI Team debate";
    return {
      id: f.id,
      title: f.title,
      kind: designerOutputKind(f),
      body: (f.description ?? "No written brief was stored for this finding.").slice(0, 240),
      reviewLabel: review.label,
      reviewTone: review.tone,
      confidence: typeof f.confidence === "number" ? f.confidence : null,
      source,
    };
  });
}

/* ── Availability (agent presence) vs. execution state vs. review ───────── */

export interface DesignerAvailability {
  label: string;
  tone: DesignerTone;
  detail: string;
}

/** Availability = "can the backend dispatch this agent right now?" */
export function designerAvailability(
  registered: boolean,
  runs: DesignerRunSummary[],
): DesignerAvailability {
  if (!registered) {
    return {
      label: "Not registered",
      tone: "neutral",
      detail: "The Designer Agent is not in this backend's agent registry.",
    };
  }
  const latest = runs[0] ?? null;
  if (latest && ACTIVE_STATUSES.has(latest.status)) {
    return { label: "Working now", tone: "accent", detail: "An AI Team cycle is running the Designer Agent right now." };
  }
  return {
    label: "Available",
    tone: "ok",
    detail: latest
      ? `Registered and ready — last run ${relativeTime(latest.completedAt ?? latest.startedAt, Date.now()).toLowerCase()}.`
      : "Registered and ready to be dispatched by an AI Team cycle.",
  };
}

/* ── Metrics row ───────────────────────────────────────────────────────── */

export function designerMetrics(runs: DesignerRunSummary[], now: number): DesignerMetric[] {
  const weekAgo = now - 7 * 24 * 60 * 60 * 1000;
  const total = runs.length;
  const completed = runs.filter((r) => r.status === "completed").length;
  const failed = runs.filter((r) => r.status === "failed").length;
  const running = runs.filter((r) => ACTIVE_STATUSES.has(r.status)).length;
  const last7 = runs.filter((r) => (r.startedAt ?? 0) >= weekAgo).length;
  const latest = runs[0] ?? null;
  // The failure hint must describe an actual failed run, not simply the newest
  // one — otherwise a failed run from last month reports "no failure".
  const latestFailure = runs.find((r) => r.status === "failed" && r.error) ?? null;

  const completedRuns = runs.filter((r) => r.status === "completed" && r.latencyMs !== null);
  const avgLatency =
    completedRuns.length > 0
      ? Math.round(completedRuns.reduce((sum, r) => sum + (r.latencyMs ?? 0), 0) / completedRuns.length)
      : null;

  return [
    {
      key: "runs",
      label: "Designer Agent runs",
      value: String(total),
      hint: total === 0 ? "No runs recorded yet" : `${last7} in the last 7 days`,
      tone: "neutral",
    },
    {
      key: "completed",
      label: "Completed",
      value: String(completed),
      hint: avgLatency !== null ? `Avg ${avgLatency.toLocaleString("en-IN")} ms per run` : "No completed run to measure yet",
      tone: "ok",
    },
    {
      key: "active",
      label: "Running now",
      value: String(running),
      hint: latest
        ? `Latest: ${designerModeLabel(latest.mode)} · ${relativeTime(latest.startedAt, now).toLowerCase()}`
        : "Idle — no Designer Agent run in flight",
      tone: running > 0 ? "accent" : "neutral",
    },
    {
      key: "failed",
      label: "Failed",
      value: String(failed),
      hint: latestFailure?.error
        ? `Last error: ${latestFailure.error.slice(0, 64)}`
        : failed > 0
          ? `${failed} run${failed === 1 ? "" : "s"} failed without a stored error`
          : "No failed Designer Agent run recorded",
      tone: failed > 0 ? "accent" : "neutral",
    },
  ];
}

/* ── Projects table ────────────────────────────────────────────────────── */

function projectTone(status: string): DesignerTone {
  if (status === "completed") return "ok";
  if (status === "failed") return "accent";
  if (ACTIVE_STATUSES.has(status)) return "accent";
  return "neutral";
}

function projectStatusLabel(status: string): string {
  if (ACTIVE_STATUSES.has(status)) return "In progress";
  if (status === "completed") return "Completed";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Cancelled";
  return status ? status.charAt(0).toUpperCase() + status.slice(1) : "Unknown";
}

export function designerProjectRows(runs: DesignerRunSummary[]): DesignerProjectRow[] {
  return runs.map<DesignerProjectRow>((r) => ({
    id: r.id,
    project: designerCycleLabel(r.cycleId),
    type: designerModeLabel(r.mode),
    status: projectStatusLabel(r.status),
    statusTone: projectTone(r.status),
    updatedAt: r.completedAt ?? r.startedAt,
    tools: r.tools,
    error: r.error,
  }));
}

/* ── Activity timeline ─────────────────────────────────────────────────── */

export function designerActivity(
  runs: DesignerRunSummary[],
  findings: DesignerFindingSummary[],
): DesignerActivityItem[] {
  const items: DesignerActivityItem[] = [];

  for (const r of runs) {
    const active = ACTIVE_STATUSES.has(r.status);
    const failed = r.status === "failed";
    items.push({
      id: `run-${r.id}`,
      title: `Designer Agent run ${projectStatusLabel(r.status).toLowerCase()}`,
      detail: [
        designerModeLabel(r.mode),
        r.latencyMs !== null ? `${r.latencyMs.toLocaleString("en-IN")} ms` : null,
        r.tools.length > 0 ? `${r.tools.length} tool${r.tools.length === 1 ? "" : "s"}` : null,
        r.error ? `error: ${r.error.slice(0, 80)}` : null,
      ]
        .filter(Boolean)
        .join(" · "),
      at: r.completedAt ?? r.startedAt,
      tone: failed ? "accent" : active ? "accent" : "ok",
      kind: "run",
    });
  }

  for (const f of findings) {
    items.push({
      id: `brief-${f.id}`,
      title: f.title,
      detail: [
        designerOutputKind(f),
        f.confidence > 0 ? `${Math.round(f.confidence * 100)}% confidence` : null,
        f.debateObjective ? `debate: ${f.debateObjective.slice(0, 60)}` : null,
      ]
        .filter(Boolean)
        .join(" · "),
      at: f.recordedAt,
      tone: f.findingType === "uncertainty" ? "neutral" : "ok",
      kind: "brief",
    });
  }

  return items.sort((a, b) => (b.at ?? 0) - (a.at ?? 0));
}

/* ── AI Team card copy (one honest sentence, never a placeholder) ──────── */

export function designerCardFinding(
  runs: DesignerRunSummary[],
  findings: DesignerFindingSummary[],
): string {
  const brief = findings[0];
  if (brief) {
    return `${brief.title} — ${designerOutputKind(brief).toLowerCase()} recorded for human review; nothing is published or executed automatically.`;
  }
  const latest = runs[0] ?? null;
  if (!latest) {
    return "No Designer Agent run yet — Start Analysis on this page dispatches the Designer Agent with the rest of the AI Team.";
  }
  const base = `${designerModeLabel(latest.mode)} · ${projectStatusLabel(latest.status).toLowerCase()}`;
  if (ACTIVE_STATUSES.has(latest.status)) return `Design work in flight — ${base}.`;
  if (latest.status === "failed") return `${base} — run failed: ${latest.error ?? "the run did not complete"}.`;
  if (latest.status === "completed") {
    return `${base} — ${latest.opportunities} opportunit${latest.opportunities === 1 ? "y" : "ies"} and ${latest.actionsProposed} proposed action${latest.actionsProposed === 1 ? "" : "s"} awaiting human approval.`;
  }
  return `${base}.`;
}

export function designerCardSupport(
  runs: DesignerRunSummary[],
  findings: DesignerFindingSummary[],
): string {
  const parts: string[] = [`${runs.length} run${runs.length === 1 ? "" : "s"} recorded`];
  parts.push(`${findings.length} creative brief${findings.length === 1 ? "" : "s"} on file`);
  const latest = runs[0];
  if (latest?.tools.length) parts.push(`tools: ${latest.tools.slice(0, 3).join(", ")}`);
  return parts.join(" · ");
}

/* ── Snapshot assembly helper (kept pure so it stays testable) ─────────── */

/** How many recent debates are inspected for persisted creative briefs. */
export const DESIGNER_DEBATE_SCAN_LIMIT = 3;

/** True when a run status means the agent is mid-flight right now. */
export function isDesignerRunActive(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

/** Build the dashboard read model from already-fetched backend payloads. */
export function buildDesignerSnapshot(input: {
  registryEntry?: { description?: unknown; tools?: unknown } | null;
  runRows?: DesignerRunRowLike[] | null;
  debates?: Array<{ id: string; objective: string; updatedAt: number | null }> | null;
  findingsByDebate?: Map<string, DesignerFindingLike[]>;
}): DesignerSnapshot {
  const entry = input.registryEntry ?? null;
  const runs = designerRunsFromRows(input.runRows);
  const findings: DesignerFindingSummary[] = [];
  for (const debate of (input.debates ?? []).slice(0, DESIGNER_DEBATE_SCAN_LIMIT)) {
    findings.push(
      ...designerFindingsFrom(
        input.findingsByDebate?.get(debate.id) ?? null,
        debate.id,
        debate.objective,
        debate.updatedAt,
      ),
    );
  }
  return {
    registered: Boolean(entry),
    registryDescription: typeof entry?.description === "string" ? entry.description : null,
    tools: Array.isArray(entry?.tools)
      ? entry.tools.filter((t): t is string => typeof t === "string")
      : [],
    runs,
    latest: runs[0] ?? null,
    findings,
    inFlight: runs.some((r) => ACTIVE_STATUSES.has(r.status)),
  };
}

/** Empty read model — used before the first load and when auth is missing. */
export const EMPTY_DESIGNER_SNAPSHOT: DesignerSnapshot = buildDesignerSnapshot({});