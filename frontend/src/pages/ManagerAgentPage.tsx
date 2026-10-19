/**
 * /manager-agent — Manager Agent Autonomous Growth Orchestrator Dashboard.
 *
 * Every figure and status on this page comes from the Manager Agent's own
 * backend surface, or is reported as unavailable. There are no fallback
 * counts: a dashboard that invents "28 completed" when the database holds
 * three runs is worse than one that admits it has no data.
 *
 * Endpoints consumed (all added by the Manager coordination router):
 *   POST /api/manager/plan                      validated plan — runs nothing
 *   POST /api/agents/run                        the EXISTING orchestrator
 *   GET  /api/manager/workflows/{id}            real per-agent results
 *   GET  /api/manager/metrics                   real dashboard figures
 *   GET  /api/manager/actions                   pending proposals + origin agent
 *   GET  /agents/catalog                        registered specialists
 *
 * Planning is deliberately separate from execution: the merchant inspects the
 * plan and the selected specialists first, then explicitly starts execution.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { MerchantWorldBackground } from "../features/public/MerchantWorld/MerchantWorldBackground";
import { ManagerHero } from "./manager/ManagerHero";
import { ManagerWorkspaceAndMetrics } from "./manager/ManagerWorkspaceAndMetrics";
import { ManagerRoster } from "./manager/ManagerRoster";
import { ManagerCapabilities } from "./manager/ManagerCapabilities";
import { ManagerLiveExecution } from "./manager/ManagerLiveExecution";
import { ManagerDecisionsAndActivity } from "./manager/ManagerDecisionsAndActivity";
import {
  createManagerPlan,
  fetchManagerActions,
  fetchManagerMetrics,
  fetchManagerRoster,
  fetchManagerWorkflow,
  startAiTeamWork,
  type ManagerMetrics,
  type ManagerPlan,
  type ManagerRoster as ManagerRosterData,
  type ManagerWorkflowReport,
} from "../lib/api";
import { Button } from "../components/Button";
import { PreviewModeBanner } from "../components/PreviewModeBanner";
import { isAuthenticated } from "../lib/auth";
import type {
  ExecutionStepItem,
  ApprovalQueueItem,
  TeamActivityItem,
} from "./manager/types";
import "./ManagerAgentPage.css";

function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "just now";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "recently";
  const mins = Math.max(1, Math.round((Date.now() - t) / 60_000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function formatDuration(ms: number | undefined): string {
  if (!ms || ms <= 0) return "-";
  const totalSec = Math.round(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m === 0) return `${s}s`;
  return `${m}m ${s}s`;
}

/** Map a real backend status onto the dashboard's step vocabulary. */
function stepStatus(
  status: string,
): ExecutionStepItem["status"] {
  switch (status) {
    case "completed":
      return "Completed";
    case "running":
      return "In Progress";
    case "failed":
      return "Failed";
    default:
      return "Pending";
  }
}

const SAMPLE_MANAGER_METRICS: ManagerMetrics = {
  merchant_id: "preview-merchant",
  agents_coordinated: 13,
  tasks_completed: 0,
  awaiting_approval: 0,
  active_workflows: 0,
  total_workflows: 0,
  window_days: 30,
  metrics_available: true,
  unavailable_reasons: [],
};

const SAMPLE_MANAGER_ACTIONS: Array<{
  id: string;
  action_type: string;
  status: string;
  origin_agent: string | null;
  workflow_id: string | null;
  created_at: string;
}> = [];

export function ManagerAgentPage() {
  const [isPreview, setIsPreview] = useState(!isAuthenticated());
  const [isCreating, setIsCreating] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [activeWorkflow, setActiveWorkflow] = useState<string>("Growth Acceleration Plan");

  // Real backend state.
  const [plan, setPlan] = useState<ManagerPlan | null>(null);
  const [workflow, setWorkflow] = useState<ManagerWorkflowReport | null>(null);
  const [metrics, setMetrics] = useState<ManagerMetrics | null>(
    !isAuthenticated() ? SAMPLE_MANAGER_METRICS : null,
  );
  const [roster, setRoster] = useState<ManagerRosterData | null>(null);
  const [pendingActions, setPendingActions] = useState<
    Array<{
      id: string;
      action_type: string;
      status: string;
      origin_agent: string | null;
      workflow_id: string | null;
      created_at: string;
    }>
  >(!isAuthenticated() ? SAMPLE_MANAGER_ACTIONS : []);
  const [loadError, setLoadError] = useState<string | null>(null);

  /* Read-only dashboard load. Every call is independent, so one failing
   * endpoint degrades a single panel instead of blanking the page. */
  const loadDashboard = useCallback(async () => {
    if (!isAuthenticated()) {
      setIsPreview(true);
      setMetrics(SAMPLE_MANAGER_METRICS);
      setPendingActions(SAMPLE_MANAGER_ACTIONS);
      setLoadError(null);
      return;
    }

    const [metricsRes, rosterRes, actionsRes] = await Promise.allSettled([
      fetchManagerMetrics(),
      fetchManagerRoster(),
      fetchManagerActions(),
    ]);

    if (metricsRes.status === "fulfilled") setMetrics(metricsRes.value);
    if (rosterRes.status === "fulfilled") setRoster(rosterRes.value);
    if (actionsRes.status === "fulfilled") {
      setPendingActions(
        actionsRes.value.actions.map((a) => ({
          id: a.id,
          action_type: a.action_type,
          status: a.status,
          origin_agent: a.origin_agent,
          workflow_id: a.workflow_id,
          created_at: a.created_at,
        })),
      );
    }

    const failures = [metricsRes, rosterRes, actionsRes].filter(
      (r) => r.status === "rejected",
    ).length;
    if (failures > 0) {
      if (!isAuthenticated() || failures === 3) {
        setIsPreview(true);
        setMetrics(SAMPLE_MANAGER_METRICS);
        setPendingActions(SAMPLE_MANAGER_ACTIONS);
        setLoadError(null);
      } else {
        setLoadError("Some Manager Agent panels are unavailable.");
      }
    } else {
      setLoadError(null);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await loadDashboard();
      if (cancelled) return;
    })();
    return () => {
      cancelled = true;
    };
  }, [loadDashboard]);

  /**
   * Goal submission: validate locally, ask the Manager for a VALIDATED PLAN,
   * then let the merchant start execution explicitly.
   *
   * No success message is shown until the backend confirms it — the plan
   * response is what sets `plan`, and execution only reports after the
   * orchestrator responds.
   */
  const handleCreatePlan = async (goal: string) => {
    if (!isAuthenticated()) {
      setStatusMessage("Sign in to generate autonomous execution plans with the Manager Agent.");
      return;
    }
    const trimmed = goal.trim();
    if (trimmed.length < 3) {
      setStatusMessage("Describe a growth goal in a few more words before planning.");
      return;
    }

    setIsCreating(true);
    setStatusMessage("Manager Agent is parsing the goal and validating a plan…");
    try {
      // Step 1 — plan only. This runs no agent and creates no action.
      const created = await createManagerPlan({ objective: trimmed, window_days: 30 });
      setPlan(created);
      setActiveWorkflow(created.goal.goal);
      setWorkflow(null);

      if (!created.validation.valid) {
        setStatusMessage(
          `Plan needs changes — ${created.validation.rejections.length} issue(s) rejected. Nothing was executed.`,
        );
        return;
      }
      if (created.tasks.length === 0) {
        setStatusMessage(
          "No specialist matched this goal's capabilities, so no plan was created. Nothing was executed.",
        );
        return;
      }
      setStatusMessage(
        `Plan ready — ${created.tasks.length} task(s) across ${created.selected_agents.length} registered specialist(s). Review, then start execution.`,
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unable to create a growth plan.";
      setStatusMessage(`Coordination error: ${message}`);
    } finally {
      setIsCreating(false);
    }
  };

  /** Step 2 — the merchant explicitly starts execution. */
  const handleStartExecution = async () => {
    if (!isAuthenticated()) {
      setStatusMessage("Sign in to execute growth plans with your AI Team.");
      return;
    }
    if (!plan) return;
    setIsCreating(true);
    setStatusMessage("Dispatching the validated plan to the AI Team workflow…");
    try {
      const res = await startAiTeamWork(plan.goal.goal);
      const workflowId = res.orchestrator_run_id;
      setStatusMessage(`Workflow started (run ${workflowId.slice(0, 8)}…). Reading real results.`);
      await loadDashboard();
      // Fetch the workflow this cycle just produced, so the table and the
      // evaluation show what actually ran.
      const report = await fetchManagerWorkflow(workflowId);
      setWorkflow(report);
      setStatusMessage(
        `Workflow ${report.status} — ${report.totals.agents_executed ?? 0} agent run(s) recorded.`,
      );
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unable to start the workflow.";
      setStatusMessage(`Execution error: ${message}`);
    } finally {
      setIsCreating(false);
    }
  };

  /* ── Execution steps: the workflow's real agent runs ───────────────── */
  const derivedSteps: ExecutionStepItem[] | undefined = useMemo(() => {
    const runs = workflow?.agents_run ?? [];
    if (runs.length === 0) return undefined;
    return runs.map((r, idx) => ({
      num: String(idx + 1),
      step: r.agent.replace(/([A-Z])/g, " $1").trim(),
      specialist: r.agent,
      specialistKey: r.agent,
      // Real task description when the Manager planned it, else the real status.
      task:
        plan?.tasks.find((t) => t.agent_id === r.agent)?.description ??
        (r.errors.length > 0 ? r.errors[0] : `status: ${r.status}`),
      status: stepStatus(r.status),
      duration: formatDuration(r.latency_ms?.total),
    }));
  }, [workflow, plan]);

  /* ── Approval queue: real pending proposals ─────────────────────────── */
  const derivedApprovals: ApprovalQueueItem[] | undefined = useMemo(() => {
    if (pendingActions.length === 0) return undefined;
    return pendingActions.slice(0, 4).map((a) => ({
      id: a.id,
      actionTitle: a.action_type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      actionType: a.action_type,
      agent: a.origin_agent?.replace(/Agent$/, "") ?? "Specialist",
      agentKey: a.origin_agent ?? "unknown",
      createdText: formatRelativeTime(a.created_at),
      status: "Pending" as const,
      actionId: a.id,
    }));
  }, [pendingActions]);

  /* ── Team activity: real agent runs ────────────────────────────────── */
  const derivedActivity: TeamActivityItem[] | undefined = useMemo(() => {
    const runs = workflow?.agents_run ?? [];
    if (runs.length === 0) return undefined;
    return runs.slice(0, 5).map((r) => ({
      id: `${r.agent}-${r.started_at}`,
      time: formatRelativeTime(r.started_at),
      agent: r.agent.replace(/Agent$/, ""),
      agentKey: r.agent,
      activity:
        r.status === "completed"
          ? `Completed ${r.agent.replace(/Agent$/, "")} (${r.actions_proposed} action(s) proposed)`
          : `${r.status}: ${r.agent.replace(/Agent$/, "")}${r.errors[0] ? ` — ${r.errors[0]}` : ""}`,
    }));
  }, [workflow]);

  /* ── Metrics: real counts, or an explicit unavailable state ─────────── */
  const agentsCount = metrics?.agents_coordinated ?? 0;
  const completedTasks = metrics?.tasks_completed ?? 0;
  const awaitingApproval = metrics?.awaiting_approval ?? 0;
  const activeWorkflows = metrics?.active_workflows ?? 0;

  /* ── Hero/roster status overrides, derived from the live registry ────
     Availability is a registry property, not an execution status: an agent
     reads "Available" because it has real registered tools, not because it
     happens to be running right now. Execution state lives in the plan
     table, where each step carries the backend's actual status. */
  const heroStatusOverrides = useMemo(() => {
    const map: Record<string, string> = {};
    for (const entry of roster?.agents ?? []) {
      if (entry.selectable) map[entry.agent_id] = "Available";
    }
    return map;
  }, [roster]);

  const rosterStatusOverrides = useMemo(() => {
    const map: Record<string, string> = {};
    for (const entry of roster?.agents ?? []) {
      map[entry.agent_id] = entry.selectable ? "Available" : "No registered tools";
    }
    return map;
  }, [roster]);

  const workflowAwaitingApproval = useMemo(() => {
    const fromReport = workflow?.report?.actions_awaiting_human_approval;
    return typeof fromReport === "number" ? fromReport : null;
  }, [workflow]);

  return (
    <div className="mgr-world">
      <MerchantWorldBackground />

      <main className="mgr-shell" id="main-content">
        {isPreview && (
          <PreviewModeBanner pageName="Manager Orchestration Command Center" />
        )}
        {/* Section B: Hero Section */}
        <ManagerHero
          onCreatePlan={handleCreatePlan}
          isCreating={isCreating}
          statusMessage={statusMessage}
          agentStatusOverrides={heroStatusOverrides}
        />

        {/* Validated plan inspector — the merchant reviews before executing. */}
        {plan && (
          <section className="mgr-plan" aria-label="Growth plan">
            <header className="mgr-plan__head">
              <span className="meta-label">GROWTH PLAN · {plan.status.toUpperCase()}</span>
              <span className="mgr-plan__id">workflow {plan.workflow_id.slice(0, 8)}</span>
            </header>

            {!plan.validation.valid && (
              <ul className="mgr-plan__rejections">
                {plan.validation.rejections.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            )}

            {plan.goal.blocked_reasons.length > 0 && (
              <p className="mgr-plan__blocked">
                Blocked: {plan.goal.blocked_reasons.join(", ")}
              </p>
            )}

            <table className="mgr-plan__table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Specialist</th>
                  <th>Why selected</th>
                  <th>Approval</th>
                </tr>
              </thead>
              <tbody>
                {plan.tasks.map((t) => (
                  <tr key={t.task_id}>
                    <td>{t.description}</td>
                    <td>
                      <strong>{t.agent_id}</strong>
                    </td>
                    <td>{plan.selection?.find((s) => s.agent_id === t.agent_id)?.reason ?? "—"}</td>
                    <td>{t.approval_required ? "Human approval required" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {plan.tasks.length > 0 && plan.validation.valid && (
              <Button variant="primary" mono disabled={isCreating} onClick={() => void handleStartExecution()}>
                {isCreating ? "STARTING…" : "START EXECUTION"}
              </Button>
            )}

            {workflow && (
              <p className="mgr-plan__result">
                {workflow.evaluation.outcome} ·{" "}
                {workflow.evaluation.completed.length} completed ·{" "}
                {workflow.evaluation.failed.length} failed ·{" "}
                {workflow.evaluation.blocked.length} blocked ·{" "}
                {workflowAwaitingApproval ?? 0} action(s) awaiting human approval
              </p>
            )}
          </section>
        )}

        {loadError && <p className="mgr-error">{loadError}</p>}

        {/* Section C: Growth Workspace & Key Metrics */}
        <ManagerWorkspaceAndMetrics
          agentsCount={agentsCount}
          completedTasksCount={completedTasks}
          awaitingApprovalCount={awaitingApproval}
          activeWorkflowsCount={activeWorkflows}
        />

        {/* Section D: Agent Roster */}
        <ManagerRoster agentStatusOverrides={rosterStatusOverrides} />

        {/* Section E: Manager Capabilities */}
        <ManagerCapabilities />

        {/* Section F: Live Execution Plan & Approval Queue */}
        <ManagerLiveExecution
          steps={derivedSteps}
          pendingActions={derivedApprovals}
          workflowName={activeWorkflow}
        />

        {/* Section G: Recent Decisions & Team Activity */}
        <ManagerDecisionsAndActivity activities={derivedActivity} />
      </main>
    </div>
  );
}
