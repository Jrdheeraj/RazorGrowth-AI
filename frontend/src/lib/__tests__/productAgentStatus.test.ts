/* Regression suite for the Product Agent status model.
 *
 * Guards the reported dashboard contradictions:
 *
 *  1. A run parked at waiting_approval stopped being polled, so approving
 *     an action in another tab left this page frozen forever.
 *  2. Four recommendation rows carried `action_required`, so the panel said
 *     "4 action(s) require approval" while the live state said "No approval
 *     pending" — one screen, two opposite claims.
 *  3. The eight-step tracker took its position from `step_index` alone, so
 *     the approval step stayed active after approval and a failed run could
 *     render every step as complete.
 *  4. A stale mirror made the API answer waiting_approval for a run whose
 *     actions had already executed (§11) — the model must REPORT that, not
 *     hide it.
 *
 * Every check asserts rendered values (labels, classes of state, poll
 * cadence) rather than internal helpers. Zero-dependency: compiled with the
 * project's own tsc and run with plain node (`npm run test:product`).
 */
import {
  RUN_POLL_MS,
  APPROVAL_POLL_MS,
  actionCounts,
  approvalPanelView,
  detectStatusMismatch,
  emptyActionCounts,
  learningText,
  pollIntervalMs,
  progressSteps,
  recommendationState,
  resolveActionCounts,
  resolveViewState,
  shouldPollRun,
  statusCardView,
  workRowView,
  type RecommendationLike,
  type StatusLike,
  type WorkflowStepLike,
} from "../productAgentStatus.js";

let failures = 0;

function check(name: string, actual: unknown, expected: unknown): void {
  if (JSON.stringify(actual) === JSON.stringify(expected)) {
    console.log(`ok   ${name}`);
  } else {
    failures += 1;
    console.log(
      `FAIL ${name}: got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`,
    );
  }
}

const STEPS: WorkflowStepLike[] = [
  { top: "Understand", bottom: "catalog" },
  { top: "Analyze", bottom: "performance" },
  { top: "Find", bottom: "opportunities" },
  { top: "Research", bottom: "& analyze" },
  { top: "Prepare", bottom: "recommendation" },
  { top: "Safety", bottom: "check" },
  { top: "Waiting for", bottom: "approval" },
  { top: "Execute", bottom: "& measure" },
];

function rec(over: Partial<RecommendationLike> = {}): RecommendationLike {
  return {
    action_id: "act-1",
    approval_state: "REQUIRED",
    status: "requested",
    executed: false,
    approval_required: true,
    action_required: true,
    expected_impact: { status: "available", text: "x" },
    ...over,
  };
}

function payload(over: Partial<StatusLike> = {}): StatusLike {
  return {
    has_run: true,
    status: "waiting_approval",
    stage: "waiting_approval",
    step_index: 6,
    status_label: "Waiting for your approval",
    needs_approval: true,
    approval_status: "required",
    headline: "Analysed 4 product(s), found 4 opportunity(ies).",
    support:
      "Analysis complete: 4 products analysed; 4 recommendations prepared. Nothing has been executed — every recommendation waits for your approval.",
    recommendations: [rec(), rec({ action_id: "act-2" }), rec({ action_id: "act-3" }), rec({ action_id: "act-4" })],
    workflow_steps: STEPS,
    metrics: { executed_count: 0 },
    learning_insight: "Learning begins after an approved recommendation is executed and produces a measurable outcome. Nothing has been learned yet.",
    ...over,
  };
}

/* ── 1. Polling cadence: the run must stay live until it is finished ──── */
check("running run polls", shouldPollRun("running"), true);
check("running run polls fast", pollIntervalMs("running"), RUN_POLL_MS);
check("waiting_approval still polls", shouldPollRun("waiting_approval"), true);
check("waiting_approval polls slower", pollIntervalMs("waiting_approval"), APPROVAL_POLL_MS);
check(
  "approved_awaiting_execution still polls (reported bug)",
  shouldPollRun("approved_awaiting_execution"),
  true,
);
check("executing still polls", shouldPollRun("executing"), true);
check("completed stops polling", shouldPollRun("completed"), false);
check("completed_no_actions stops polling", shouldPollRun("completed_no_actions"), false);
check(
  "completed_with_failures stops polling",
  shouldPollRun("completed_with_failures"),
  false,
);
check("failed stops polling", shouldPollRun("failed"), false);
check("blocked stops polling", shouldPollRun("blocked"), false);
check("cancelled stops polling", shouldPollRun("cancelled"), false);
check("no status polls nothing", shouldPollRun(null), false);

/* ── 2. Counts come from live action state, never from the static flag ── */
const pendingCounts = actionCounts(payload().recommendations);
check("4 required actions count as pending", pendingCounts.awaiting_approval, 4);
check("4 required actions count as total", pendingCounts.total, 4);
check("nothing executed in the parked run", pendingCounts.executed, 0);

const flagOnly = actionCounts([
  rec({ action_id: null, approval_state: null, status: "awaiting_approval" }),
  rec({ action_id: null, approval_state: null, status: "proposed" }),
]);
check(
  "a recommendation without an action is not an approval",
  flagOnly.total,
  0,
);
check("static action_required never creates a pending count", flagOnly.awaiting_approval, 0);

const mixed = actionCounts([
  rec({ approval_state: "COMPLETED", status: "completed", executed: true }),
  rec({ action_id: "a2", approval_state: "APPROVED", status: "approved" }),
  rec({ action_id: "a3", approval_state: "EXECUTING", status: "executing" }),
  rec({ action_id: "a4", approval_state: "REJECTED", status: "rejected" }),
  rec({ action_id: "a5", approval_state: "FAILED", status: "failed" }),
]);
check("mixed executed count", mixed.executed, 1);
check("mixed approved count", mixed.approved, 1);
check("mixed executing count", mixed.executing, 1);
check("mixed rejected count", mixed.rejected, 1);
check("mixed failed count", mixed.failed, 1);
check("mixed total", mixed.total, 5);
check(
  "empty counts start at zero",
  emptyActionCounts(),
  { total: 0, awaiting_approval: 0, approved: 0, executing: 0, executed: 0, rejected: 0, failed: 0 },
);

/* ── 3. Approval panel: the two contradictory claims cannot co-exist ──── */
const pendingPanel = approvalPanelView(payload().recommendations, pendingCounts, "waiting_approval");
check("pending panel asks for approval", pendingPanel.title, "Your approval needed");
check("pending panel is hot", pendingPanel.variant, "hot");
check("pending panel is actionable", pendingPanel.actionable, true);
check("pending panel reports the pending count", pendingPanel.pendingCount, 4);

const approvedCounts = actionCounts([
  rec({ approval_state: "APPROVED", status: "approved" }),
  rec({ action_id: "a2", approval_state: "APPROVED", status: "approved" }),
]);
const approvedPanel = approvalPanelView(
  payload({ status: "approved_awaiting_execution", step_index: 7 }).recommendations,
  approvedCounts,
  "approved_awaiting_execution",
);
check("approved panel is not an approval prompt", approvedPanel.title, "Approved — awaiting execution");
check(
  "approved panel never claims no approval while work is outstanding",
  approvedPanel.title !== "No approval pending",
  true,
);
check("approved panel is not an approve prompt", approvedPanel.actionable, false);

const executedCounts = actionCounts([
  rec({ approval_state: "COMPLETED", status: "completed", executed: true }),
  rec({ action_id: "a2", approval_state: "COMPLETED", status: "completed", executed: true }),
]);
const executedPanel = approvalPanelView(
  payload({ status: "completed", step_index: 7 }).recommendations,
  executedCounts,
  "completed",
);
check("executed panel reports execution", executedPanel.title, "All actions executed");
check("executed panel is calm", executedPanel.variant, "calm");
check("executed panel hides the approve prompt", executedPanel.actionable, false);

const rejectedCounts = actionCounts([
  rec({ approval_state: "REJECTED", status: "rejected" }),
  rec({ action_id: "a2", approval_state: "REJECTED", status: "rejected" }),
]);
const rejectedPanel = approvalPanelView(
  payload({ status: "completed" }).recommendations,
  rejectedCounts,
  "completed",
);
check("rejected run reports no approval pending", rejectedPanel.title, "No approval pending");
check("rejected run admits nothing executed", rejectedPanel.line.includes("nothing was executed"), true);

const emptyPanel = approvalPanelView([], actionCounts([]), "completed");
check("no recommendations -> no approval pending", emptyPanel.title, "No approval pending");
check("no recommendations -> honest line", emptyPanel.line, "No recommendation from the last run requires a decision.");

const runningPanel = approvalPanelView(payload().recommendations, pendingCounts, "running");
check(
  "mid-run the panel does not offer an approval that does not exist yet",
  runningPanel.title,
  "Analysis in progress",
);
check("mid-run panel is not actionable", runningPanel.actionable, false);

// The invariant that was broken in production: no positive pending count may
// ever be rendered next to a "No approval pending" title.
const scenarios: Array<[string, StatusLike, string]> = [
  ["parked", payload(), "waiting_approval"],
  ["approved", payload({ status: "approved_awaiting_execution" }), "approved_awaiting_execution"],
  ["executing", payload({ status: "executing" }), "executing"],
  ["completed", payload({ status: "completed" }), "completed"],
  ["failed", payload({ status: "failed" }), "failed"],
];
for (const [name, p, runStatus] of scenarios) {
  const counts = resolveActionCounts(p);
  const panel = approvalPanelView(p.recommendations, counts, runStatus);
  check(
    `invariant ${name}: "No approval pending" implies zero pending`,
    panel.title === "No approval pending" ? panel.pendingCount : 0,
    0,
  );
}

/* ── 4. Eight-step tracker ────────────────────────────────────────────── */
const parked = progressSteps(payload(), pendingCounts);
check("parked: approval step is current", parked.steps[6].state, "now");
check("parked: execution step is ahead", parked.steps[7].state, "ahead");
check("parked: analysis steps are done", parked.steps[0].state, "done");
check("parked: nothing is all-done", parked.allDone, false);
check("parked: approval step is named", parked.steps[6].label, "Waiting for approval");

const approvedProgress = progressSteps(
  payload({ status: "approved_awaiting_execution", step_index: 7 }),
  approvedCounts,
);
check("approved: approval step is finished", approvedProgress.steps[6].state, "done");
check("approved: execution step is current", approvedProgress.steps[7].state, "now");
check("approved: not all done", approvedProgress.allDone, false);

const executingProgress = progressSteps(
  payload({ status: "executing", step_index: 7 }),
  actionCounts([rec({ approval_state: "EXECUTING", status: "executing" })]),
);
check("executing: execution step is current", executingProgress.steps[7].state, "now");

const completedProgress = progressSteps(
  payload({ status: "completed", step_index: 7 }),
  executedCounts,
);
check("completed: every step is done", completedProgress.steps.every((s) => s.state === "done"), true);
check("completed: allDone", completedProgress.allDone, true);
check("completed: active index is past the last step", completedProgress.activeIndex, 8);

const failedProgress = progressSteps(
  payload({ status: "failed", step_index: 4, status_label: "Last run failed" }),
  emptyActionCounts(),
);
check("failed: every step is not done", failedProgress.allDone, false);
check("failed: step before the stop is done", failedProgress.steps[3].state, "done");
check("failed: stopped step is marked", failedProgress.steps[4].stopped, true);
check("failed: steps after the stop are ahead", failedProgress.steps[7].state, "ahead");
check("failed: progress reports the failure", failedProgress.failed, true);

const blockedProgress = progressSteps(
  payload({ status: "blocked", step_index: 6 }),
  emptyActionCounts(),
);
check("blocked: never all done", blockedProgress.allDone, false);
check("blocked: stopped at the approval gate", blockedProgress.steps[6].stopped, true);

const noRunProgress = progressSteps(payload({ has_run: false, status: null, step_index: -1 }), emptyActionCounts());
check("no run: no active step", noRunProgress.activeIndex, -1);
check("no run: all steps ahead", noRunProgress.steps.every((s) => s.state === "ahead"), true);

const rejectedProgress = progressSteps(
  payload({ status: "waiting_approval" }),
  rejectedCounts,
);
check(
  "all-rejected run is not stuck on the approval step",
  rejectedProgress.steps[6].state,
  "done",
);

/* ── 5. Recommendation chips ──────────────────────────────────────────── */
check("required rec is awaiting", recommendationState(rec()).label, "Awaiting approval");
check("required rec tone is pending", recommendationState(rec()).tone, "pending");
check(
  "executed rec is executed",
  recommendationState(rec({ approval_state: "COMPLETED", status: "completed", executed: true })).label,
  "Executed",
);
check(
  "approved rec is not executed",
  recommendationState(rec({ approval_state: "APPROVED", status: "approved" })).label,
  "Approved — not executed",
);
check(
  "rejected rec is rejected",
  recommendationState(rec({ approval_state: "REJECTED", status: "rejected" })).label,
  "Rejected",
);
check(
  "failed rec is failed",
  recommendationState(rec({ approval_state: "FAILED", status: "failed" })).label,
  "Failed",
);
check(
  "rec without a live action state stays awaiting when approval is required",
  recommendationState(rec({ action_id: null, approval_state: null, status: "proposed" })).label,
  "Awaiting approval",
);
check(
  "rec built without approval is informational",
  recommendationState(
    rec({ action_id: null, approval_state: null, status: "proposed", approval_required: false, action_required: false }),
  ).label,
  "No action required",
);

/* ── 6. Status card: one headline per world, no opposite claims ───────── */
const pendingCard = statusCardView(payload(), pendingCounts);
check("parked pill comes from the backend label", pendingCard.pill, "Waiting for your approval");
check("parked indicator is waiting", pendingCard.indicator, "waiting");
check("parked headline mentions the decision", pendingCard.headline.includes("waiting for your approval"), true);
check("parked footer token", pendingCard.footerToken, "WAITING FOR APPROVAL");
check("parked is not terminal", pendingCard.terminal, false);
check("parked keeps polling", pendingCard.live, true);

const executedCard = statusCardView(payload({ status: "completed", step_index: 7 }), executedCounts);
check("completed headline reports execution", executedCard.headline, "All 2 action(s) executed successfully.");
check(
  "completed headline never claims nothing executed",
  executedCard.headline.toLowerCase().includes("nothing has been executed"),
  false,
);
check("completed indicator", executedCard.indicator, "done");
check("completed footer token", executedCard.footerToken, "COMPLETE");
check("completed is terminal", executedCard.terminal, true);

const runningCard = statusCardView(
  payload({
    status: "running",
    stage: "analyze_performance",
    step_index: 1,
    status_label: "Analysing your products",
    support:
      "Analysing 4 product(s) in this workspace. Result counts are finalised when the run finishes.",
  }),
  emptyActionCounts(),
);
check("running indicator", runningCard.indicator, "live");
check("running footer token", runningCard.footerToken, "RUNNING");
check("running headline", runningCard.headline, "Analysing your catalog, demand and inventory.");
check("running support states the analysis is in progress", runningCard.support.startsWith("Analysing"), true);

const finishedWhileRunning = payload({
  status: "running",
  support: "Analysis complete: 4 products analysed.",
});
check(
  "support claiming completion during a run is reported",
  detectStatusMismatch(finishedWhileRunning, resolveActionCounts(finishedWhileRunning)).length > 0,
  true,
);

const failedCard = statusCardView(
  payload({ status: "failed", step_index: 4, status_label: "Last run failed" }),
  emptyActionCounts(),
);
check("failed indicator", failedCard.indicator, "failed");
check("failed footer token", failedCard.footerToken, "STOPPED");
check("failed headline admits the failure", failedCard.headline, "The last run failed before it could finish.");

const staleMirror = payload({
  status: "waiting_approval",
  needs_approval: true,
  approval_status: "required",
  status_label: "Waiting for your approval",
  headline: "Analysed 4 product(s). Nothing has been executed.",
  support: "Completed: 4 products analysed. No action required approval, so no action was created.",
  metrics: { executed_count: 0 },
  recommendations: [
    rec({ approval_state: "COMPLETED", status: "completed", executed: true }),
    rec({ action_id: "a2", approval_state: "COMPLETED", status: "completed", executed: true }),
    rec({ action_id: "a3", approval_state: "COMPLETED", status: "completed", executed: true }),
    rec({ action_id: "a4", approval_state: "COMPLETED", status: "completed", executed: true }),
  ],
});
const staleCounts = resolveActionCounts(staleMirror);
const staleCard = statusCardView(staleMirror, staleCounts);
check(
  "a stale waiting_approval mirror never claims nothing executed",
  staleCard.headline.toLowerCase().includes("nothing has been executed"),
  false,
);
const staleReport = detectStatusMismatch(staleMirror, staleCounts);
check("stale mirror is reported", staleReport.length > 0, true);
check(
  "stale mirror reports the run status field",
  staleReport.some((m) => m.field === "status"),
  true,
);
check(
  "stale mirror reports the approval flag",
  staleReport.some((m) => m.field === "needs_approval"),
  true,
);
check(
  "stale mirror reports the approval status field",
  staleReport.some((m) => m.field === "approval_status"),
  true,
);
check(
  "stale mirror reports the status label",
  staleReport.some((m) => m.field === "status_label"),
  true,
);
check(
  "stale mirror reports the headline claim",
  staleReport.some((m) => m.field === "headline"),
  true,
);
check(
  "stale mirror reports the support claim",
  staleReport.some((m) => m.field === "support"),
  true,
);
check(
  "stale mirror reports the recorded executed metric",
  staleReport.some((m) => m.field === "metrics.executed_count"),
  true,
);

const repairedRun = payload({
  status: "completed",
  step_index: 7,
  needs_approval: false,
  approval_status: "completed",
  status_label: "Completed",
  metrics: { executed_count: 4 },
  recommendations: staleMirror.recommendations,
});
const repairedCard = statusCardView(repairedRun, resolveActionCounts(repairedRun));
check(
  "a repaired run headline reports execution from live actions",
  repairedCard.headline,
  "All 4 action(s) executed successfully.",
);

/* ── 7. A consistent payload reports no contradiction ─────────────────── */
const consistent = payload({
  needs_approval: true,
  approval_status: "required",
  status_label: "Waiting for your approval",
  action_counts: pendingCounts,
  metrics: { executed_count: 0 },
});
check("consistent payload reports nothing", detectStatusMismatch(consistent, resolveActionCounts(consistent)), []);

const serverDisagrees = payload({
  action_counts: { ...pendingCounts, total: 99 },
});
check(
  "a server count that disagrees with the actions is reported",
  detectStatusMismatch(serverDisagrees, resolveActionCounts(serverDisagrees)).some(
    (m) => m.field === "action_counts.total",
  ),
  true,
);
check(
  "no payload -> no report",
  detectStatusMismatch(null, emptyActionCounts()).length,
  0,
);

/* ── 8. View state: a failed refresh never wipes the dashboard ────────── */
check("payload + refresh error stays on screen", resolveViewState({ loading: false, error: "boom", status: payload() }), "stale");
check("no payload + error shows the error state", resolveViewState({ loading: false, error: "boom", status: null }), "error");
check("first load is loading", resolveViewState({ loading: true, error: null, status: null }), "loading");
check("healthy payload is live", resolveViewState({ loading: false, error: null, status: payload() }), "live");

/* ── 9. Run summary rows and learning copy ────────────────────────────── */
check("waiting row", workRowView({ id: "w", state: "waiting_approval", title: "Approval required", meta: "2 action(s)" }).stateLabel, "Waiting");
check("waiting row icon", workRowView({ state: "waiting_approval" }).icon, "clock");
check("approved row", workRowView({ state: "approved" }).stateLabel, "Approved");
check("executed row", workRowView({ state: "completed" }).stateLabel, "Done");
check("failed row", workRowView({ state: "failed" }).stateLabel, "Failed");
check("rejected row", workRowView({ state: "rejected" }).stateLabel, "Rejected");

check(
  "learning copy passes the backend text through",
  learningText(payload({ learning_insight: "3 action(s) approved; 1 executed." }), pendingCounts),
  "3 action(s) approved; 1 executed.",
);
check(
  "learning falls back to the honest empty state",
  learningText(payload({ learning_insight: undefined }), emptyActionCounts()).includes("Learning begins after"),
  true,
);

if (failures > 0) {
  throw new Error(`${failures} productAgentStatus check(s) failed`);
}
console.log("productAgentStatus: all checks passed");
