/**
 * The Product Agent's ONE status model for the /product-agent workstation.
 *
 * The backend read model (GET /api/product-agi/status) is authoritative:
 * its `status`, `stage`, `step_index`, `status_label`, `needs_approval`,
 * `approval_status` and per-recommendation `approval_state` all describe the
 * same persisted run and its canonical `agent_actions` rows. This module is
 * the single place that turns those fields into what the page renders —
 * the status card, the eight-step tracker, the approval panel, every
 * recommendation chip, the run-summary rows, the learning card, the footer
 * token and the polling cadence all read from here, so two sections of the
 * page can never disagree about what the run is doing.
 *
 * Rules it encodes (each one is a production bug that was reported):
 *
 *   1. Counts come from the LIVE action state (`approval_state` / `status`
 *      of linked recommendations), never from `action_required`, which only
 *      says a recommendation was built to need approval.
 *   2. "No approval pending" is impossible while an action is unresolved;
 *      "N action(s) require approval" never appears when the real pending
 *      count is zero.
 *   3. The tracker's approval step (index 6) is active only while an action
 *      is genuinely awaiting a decision; index 7 is active once actions are
 *      approved or executing; every step completes only on a successful
 *      terminal status, and a failed run never marks all steps complete.
 *   4. Polling continues through approval, execution and every intermediate
 *      state, and stops only on a terminal run status.
 *   5. The frontend never invents or repairs state. When the payload
 *      contradicts itself, `detectStatusMismatch` reports it (§11) and the
 *      page shows the report; nothing is silently corrected here.
 *
 * Zero dependencies: structural types only, so it compiles standalone with
 * `tsc` and runs under plain node (`npm run test:product`).
 */

/* ── Status tokens ─────────────────────────────────────────────────────── */

export const RUN_QUEUED = "queued";
export const RUN_RUNNING = "running";
export const RUN_WAITING_APPROVAL = "waiting_approval";
export const RUN_APPROVED = "approved_awaiting_execution";
export const RUN_EXECUTING = "executing";
export const RUN_COMPLETED = "completed";
export const RUN_COMPLETED_NO_ACTIONS = "completed_no_actions";
export const RUN_COMPLETED_WITH_FAILURES = "completed_with_failures";
export const RUN_BLOCKED = "blocked";
export const RUN_FAILED = "failed";
export const RUN_CANCELLED = "cancelled";

/** Finished runs: the API will not change again, so polling stops. */
export const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set([
  RUN_COMPLETED,
  RUN_COMPLETED_NO_ACTIONS,
  RUN_COMPLETED_WITH_FAILURES,
  RUN_BLOCKED,
  RUN_FAILED,
  RUN_CANCELLED,
]);

/** Successful terminal runs — the only case where every step may be done. */
const SUCCESSFUL_RUN_STATUSES: ReadonlySet<string> = new Set([
  RUN_COMPLETED,
  RUN_COMPLETED_NO_ACTIONS,
  RUN_COMPLETED_WITH_FAILURES,
]);

/** Run-level outcomes the run decided itself (crash, block, cancel). */
const STOPPED_RUN_STATUSES: ReadonlySet<string> = new Set([
  RUN_BLOCKED,
  RUN_FAILED,
  RUN_CANCELLED,
]);

/** Fast cadence while the agent is working. */
export const RUN_POLL_MS = 2500;
/** Slower cadence while the run waits for a human decision. */
export const APPROVAL_POLL_MS = 10000;

/** Progress tracker positions (0-based into `workflow_steps`). */
export const STEP_APPROVAL = 6;
export const STEP_EXECUTE = 7;

/* ── Input shapes (structural — this file imports nothing) ─────────────── */

export interface WorkflowStepLike {
  top: string;
  bottom: string;
}

export interface RecommendationLike {
  approval_state?: string | null;
  status?: string | null;
  executed?: boolean;
  action_id?: string | null;
  approval_required?: boolean;
  action_required?: boolean;
  /** `status: "unavailable"` means the impact genuinely could not be computed. */
  expected_impact?: { status?: string; text?: string } | null;
}

export interface WorkItemLike {
  id?: string;
  state?: string;
  title?: string;
  meta?: string;
}

export interface StatusLike {
  has_run?: boolean;
  status?: string | null;
  stage?: string | null;
  step_index?: number;
  status_label?: string;
  needs_approval?: boolean;
  approval_status?: string | null;
  headline?: string;
  support?: string;
  learning_insight?: string;
  recommendations?: readonly RecommendationLike[];
  workflow_steps?: readonly WorkflowStepLike[];
  metrics?: Record<string, number | null> | null;
  action_counts?: Partial<ActionCounts> | null;
}

/* ── Canonical action counts ───────────────────────────────────────────── */

export interface ActionCounts {
  total: number;
  awaiting_approval: number;
  approved: number;
  executing: number;
  executed: number;
  rejected: number;
  failed: number;
}

export function emptyActionCounts(): ActionCounts {
  return {
    total: 0,
    awaiting_approval: 0,
    approved: 0,
    executing: 0,
    executed: 0,
    rejected: 0,
    failed: 0,
  };
}

/**
 * Count one linked recommendation's action. The canonical `approval_state`
 * wins; the live `status` is the fallback. A rec with no action row is not
 * counted at all — it is neither an approval nor an execution — and an
 * unresolved rec counts as awaiting approval, never as approved or done.
 */
function countOne(rec: RecommendationLike, counts: ActionCounts): void {
  if (!rec.action_id) return;
  const byState: Record<string, keyof ActionCounts> = {
    REQUIRED: "awaiting_approval",
    APPROVED: "approved",
    EXECUTING: "executing",
    COMPLETED: "executed",
    FAILED: "failed",
    REJECTED: "rejected",
  };
  const byStatus: Record<string, keyof ActionCounts> = {
    requested: "awaiting_approval",
    awaiting_approval: "awaiting_approval",
    proposed: "awaiting_approval",
    approved: "approved",
    executing: "executing",
    completed: "executed",
    executed: "executed",
    failed: "failed",
    rejected: "rejected",
  };
  const state = rec.approval_state ? byState[rec.approval_state] : undefined;
  const status = rec.status ? byStatus[rec.status] : undefined;
  const bucket: keyof ActionCounts = state ?? status ?? (rec.executed ? "executed" : "awaiting_approval");
  counts[bucket] += 1;
  counts.total += 1;
}

/** Live counts of the run's canonical actions, from the recommendations. */
export function actionCounts(
  recommendations: readonly RecommendationLike[] | undefined | null,
): ActionCounts {
  const counts = emptyActionCounts();
  for (const rec of recommendations ?? []) countOne(rec, counts);
  return counts;
}

/**
 * The counts the panel works from: derived from the recommendations' live
 * action state. The backend's own `action_counts` copy is not trusted here —
 * `detectStatusMismatch` compares the two and reports any disagreement.
 */
export function resolveActionCounts(status: StatusLike | null | undefined): ActionCounts {
  return actionCounts(status?.recommendations);
}

/** True when at least one recommendation is genuinely waiting on the human. */
export function hasPendingDecision(counts: ActionCounts): boolean {
  return counts.awaiting_approval > 0;
}

/* ── Recommendation rendering ──────────────────────────────────────────── */

export type RecommendationStateToken =
  | "awaiting"
  | "approved"
  | "executing"
  | "executed"
  | "failed"
  | "rejected"
  | "no_action";

export interface RecommendationStateView {
  token: RecommendationStateToken;
  label: string;
  /** "pending" waits on the merchant, "positive" ran, "negative" did not. */
  tone: "pending" | "positive" | "negative" | "neutral";
  /** True only while the merchant still has to decide. */
  awaitingDecision: boolean;
}

const RECOMMENDATION_VIEWS: Record<
  RecommendationStateToken,
  { label: string; tone: RecommendationStateView["tone"] }
> = {
  awaiting: { label: "Awaiting approval", tone: "pending" },
  approved: { label: "Approved — not executed", tone: "pending" },
  executing: { label: "Executing", tone: "pending" },
  executed: { label: "Executed", tone: "positive" },
  failed: { label: "Failed", tone: "negative" },
  rejected: { label: "Rejected", tone: "negative" },
  no_action: { label: "No action required", tone: "neutral" },
};

/**
 * One recommendation's honest state. Unresolved means awaiting a decision —
 * a recommendation is never shown as approved or executed on inference.
 */
export function recommendationState(rec: RecommendationLike): RecommendationStateView {
  let token: RecommendationStateToken;
  switch (rec.approval_state) {
    case "COMPLETED":
      token = "executed";
      break;
    case "FAILED":
      token = "failed";
      break;
    case "REJECTED":
      token = "rejected";
      break;
    case "EXECUTING":
      token = "executing";
      break;
    case "APPROVED":
      token = "approved";
      break;
    case "REQUIRED":
      token = "awaiting";
      break;
    default:
      token = recommendationTokenFromStatus(rec);
  }
  const view = RECOMMENDATION_VIEWS[token];
  return {
    token,
    label: view.label,
    tone: view.tone,
    awaitingDecision: token === "awaiting",
  };
}

function recommendationTokenFromStatus(rec: RecommendationLike): RecommendationStateToken {
  if (rec.executed || rec.status === "completed" || rec.status === "executed") {
    return "executed";
  }
  switch (rec.status) {
    case "failed":
      return "failed";
    case "rejected":
      return "rejected";
    case "executing":
      return "executing";
    case "approved":
      return "approved";
    default:
      break;
  }
  // No live action state: a recommendation built to need approval is still
  // an open decision, one built without approval is simply informational.
  return rec.approval_required || rec.action_required ? "awaiting" : "no_action";
}

/** Short label used by the recommendation cards (single source of truth). */
export function approvalLabel(rec: RecommendationLike): string {
  return recommendationState(rec).label;
}

/* ── Status card ───────────────────────────────────────────────────────── */

export type IndicatorToken = "idle" | "live" | "waiting" | "approved" | "done" | "failed";

export interface StatusCardView {
  hasRun: boolean;
  /** Backend `status_label` — the authoritative pill text. */
  pill: string;
  indicator: IndicatorToken;
  /** One honest sentence for the headline; derived, never contradicts support. */
  headline: string;
  /** Backend `support`, or a counts-derived fallback when it is absent. */
  support: string;
  stepIndex: number;
  status: string | null;
  terminal: boolean;
  /** Still changing — the page should keep polling. */
  live: boolean;
  footerToken: string;
}

export function isRunTerminal(status: string | null | undefined): boolean {
  return status != null && TERMINAL_RUN_STATUSES.has(status);
}

/** Poll a run only while its state can still change. */
export function shouldPollRun(status: string | null | undefined): boolean {
  return status != null && !TERMINAL_RUN_STATUSES.has(status);
}

export function pollIntervalMs(status: string | null | undefined): number {
  return status === RUN_WAITING_APPROVAL ? APPROVAL_POLL_MS : RUN_POLL_MS;
}

function indicatorFor(status: string | null, counts: ActionCounts): IndicatorToken {
  if (status == null) return "idle";
  if (STOPPED_RUN_STATUSES.has(status)) return "failed";
  if (SUCCESSFUL_RUN_STATUSES.has(status)) return "done";
  if (status === RUN_WAITING_APPROVAL || counts.awaiting_approval > 0) return "waiting";
  if (status === RUN_APPROVED || status === RUN_EXECUTING) return "approved";
  if (status === RUN_QUEUED || status === RUN_RUNNING) return "live";
  return "idle";
}

function footerTokenFor(status: string | null, counts: ActionCounts): string {
  if (status == null) return "IDLE";
  if (STOPPED_RUN_STATUSES.has(status)) return "STOPPED";
  if (SUCCESSFUL_RUN_STATUSES.has(status)) return "COMPLETE";
  if (status === RUN_WAITING_APPROVAL || counts.awaiting_approval > 0) {
    return "WAITING FOR APPROVAL";
  }
  if (status === RUN_APPROVED || status === RUN_EXECUTING) return "EXECUTING";
  if (status === RUN_QUEUED || status === RUN_RUNNING) return "RUNNING";
  return "IDLE";
}

function headlineFor(status: string, counts: ActionCounts, fallback: string): string {
  const { total, awaiting_approval, approved, executing, executed, rejected, failed } = counts;
  switch (status) {
    case RUN_QUEUED:
      return "Queued — the shared analysis cycle will start this run.";
    case RUN_RUNNING:
      return "Analysing your catalog, demand and inventory.";
    case RUN_WAITING_APPROVAL:
      return awaiting_approval > 0
        ? `${awaiting_approval} of ${total || awaiting_approval} action(s) are waiting for your approval.`
        : "Analysis finished — nothing is waiting for your approval.";
    case RUN_APPROVED:
      return `${approved} action(s) approved and queued for execution. Nothing runs until you approve.`;
    case RUN_EXECUTING:
      return executed > 0
        ? `Executing approved actions — ${executed} of ${total} done so far.`
        : "Executing approved actions through the actions pipeline.";
    case RUN_COMPLETED_NO_ACTIONS:
      return "Analysis complete — no recommendation required an action.";
    case RUN_COMPLETED:
      if (total === 0) return "Analysis complete — no action was required.";
      if (executed >= total) return `All ${executed} action(s) executed successfully.`;
      if (executed > 0) return `${executed} of ${total} action(s) executed.`;
      if (rejected > 0) {
        return `Analysis complete. ${rejected} action(s) rejected — nothing was executed.`;
      }
      return "Analysis complete.";
    case RUN_COMPLETED_WITH_FAILURES:
      return `${executed} of ${total} action(s) executed; ${failed} failed.`;
    case RUN_BLOCKED:
      return "The last run was blocked by the safety review.";
    case RUN_FAILED:
      return "The last run failed before it could finish.";
    case RUN_CANCELLED:
      return "The last run was cancelled.";
    default:
      return fallback || "Run in progress.";
  }
}

function supportFor(status: StatusLike, counts: ActionCounts): string {
  const text = (status.support ?? "").trim();
  if (text) return text;
  const { total, awaiting_approval, approved, executing, executed, rejected, failed } = counts;
  if (total === 0) return "No action was created for this run.";
  const segs: string[] = [];
  if (awaiting_approval) segs.push(`${awaiting_approval} awaiting your approval`);
  if (approved || executing) segs.push(`${approved + executing} approved, not yet executed`);
  if (executed) segs.push(`${executed} executed through the actions pipeline`);
  if (rejected) segs.push(`${rejected} rejected`);
  if (failed) segs.push(`${failed} failed`);
  return `Live action state: ${segs.join("; ")}.`;
}

export function statusCardView(
  status: StatusLike | null | undefined,
  counts: ActionCounts,
): StatusCardView {
  const runStatus = status?.status ?? null;
  const hasRun = runStatus != null && Boolean(status?.has_run);
  return {
    hasRun,
    pill: status?.status_label ?? (hasRun ? "Reading run state" : "No run yet"),
    indicator: indicatorFor(runStatus, counts),
    headline:
      runStatus != null && hasRun
        ? headlineFor(runStatus, counts, status?.status_label ?? "")
        : status?.headline ?? "No Product Agent run yet.",
    support: status ? supportFor(status, counts) : "",
    stepIndex: hasRun ? status?.step_index ?? -1 : -1,
    status: runStatus,
    terminal: isRunTerminal(runStatus),
    live: shouldPollRun(runStatus),
    footerToken: footerTokenFor(runStatus, counts),
  };
}

/* ── Eight-step progress tracker ───────────────────────────────────────── */

export type ProgressStepState = "done" | "now" | "ahead";

export interface ProgressStepView {
  index: number;
  top: string;
  bottom: string;
  label: string;
  state: ProgressStepState;
  /** True for the step where a failed / blocked / cancelled run stopped. */
  stopped: boolean;
}

export interface ProgressView {
  steps: ProgressStepView[];
  /** Step the run is at, or -1 before the first run, or steps.length when
   *  every step is already finished. */
  activeIndex: number;
  allDone: boolean;
  /** A run-level failure: some steps never happened, none may look done. */
  failed: boolean;
  caption: string;
}

/**
 * The tracker's position comes from the canonical action counts first and
 * the backend's `step_index` only as the analysis-phase fallback — so step 6
 * ("Waiting for approval") is active while and only while a decision is
 * outstanding, step 7 covers approved / executing / executed work, and a
 * successful terminal status completes every step.
 */
function activeStepIndex(
  status: StatusLike,
  counts: ActionCounts,
  stepCount: number,
): number {
  const runStatus = status.status ?? null;
  if (runStatus == null) return -1;
  if (SUCCESSFUL_RUN_STATUSES.has(runStatus)) return stepCount;
  if (counts.awaiting_approval > 0) return STEP_APPROVAL;
  if (counts.approved > 0 || counts.executing > 0 || counts.executed > 0) {
    return STEP_EXECUTE;
  }
  if (counts.rejected > 0 || counts.failed > 0) return stepCount;
  const backend = status.step_index ?? -1;
  if (backend >= 0 && backend <= stepCount) return backend;
  return runStatus === RUN_WAITING_APPROVAL ? STEP_APPROVAL : 0;
}

export function progressSteps(
  status: StatusLike | null | undefined,
  counts: ActionCounts,
): ProgressView {
  const source = status ?? null;
  const steps: WorkflowStepLike[] = (source?.workflow_steps ?? []).map((s) => ({
    top: s.top,
    bottom: s.bottom,
  }));
  const runStatus = source?.status ?? null;
  const hasRun = source != null && Boolean(source.has_run) && runStatus != null;
  const failed = runStatus != null && STOPPED_RUN_STATUSES.has(runStatus);
  const allDone = runStatus != null && SUCCESSFUL_RUN_STATUSES.has(runStatus);
  const activeIndex = allDone
    ? steps.length
    : hasRun && source != null
      ? activeStepIndex(source, counts, steps.length)
      : -1;

  const views: ProgressStepView[] = steps.map((s, i) => {
    let state: ProgressStepState = "ahead";
    if (allDone || (activeIndex >= 0 && i < activeIndex)) state = "done";
    else if (i === activeIndex) state = "now";
    return {
      index: i,
      top: s.top,
      bottom: s.bottom,
      label: `${s.top} ${s.bottom}`.trim(),
      state,
      stopped: failed && i === activeIndex,
    };
  });

  return {
    steps: views,
    activeIndex,
    allDone,
    failed,
    caption: progressCaption(source, counts, views, activeIndex),
  };
}

function progressCaption(
  status: StatusLike | null,
  counts: ActionCounts,
  steps: ProgressStepView[],
  activeIndex: number,
): string {
  if (status == null || status.has_run === false) {
    return "No run yet — start a shared analysis to begin.";
  }
  const runStatus = status.status ?? null;
  const current = activeIndex >= 0 && activeIndex < steps.length ? steps[activeIndex] : null;
  const position = current
    ? `Current stage: ${current.label}`
    : steps.length > 0
      ? `All ${steps.length} stages reached`
      : "Run state unavailable";
  const tail = runStatus ? ` · run status: ${runStatus}` : "";
  if (counts.awaiting_approval > 0) {
    return `${position} · ${counts.awaiting_approval} action(s) waiting for your approval${tail}`;
  }
  if (counts.executed > 0) {
    return `${position} · ${counts.executed} action(s) executed${tail}`;
  }
  return `${position}${tail}`;
}

/* ── Approval panel ────────────────────────────────────────────────────── */

export interface ApprovalPanelView {
  /** "hot" = a decision or an execution is outstanding. */
  variant: "hot" | "calm";
  icon: "alert" | "clock" | "check";
  title: string;
  line: string;
  meta: string;
  /** Show the "Review Actions / Open Approvals" buttons. */
  actionable: boolean;
  pendingCount: number;
  total: number;
}

export function approvalPanelView(
  recommendations: readonly RecommendationLike[] | undefined,
  counts: ActionCounts,
  runStatus: string | null = null,
): ApprovalPanelView {
  const total = counts.total || (recommendations?.length ?? 0);
  const pending = counts.awaiting_approval;
  const outstanding = counts.approved + counts.executing;
  const noImpact =
    recommendations?.filter(
      (r) => !r.expected_impact || r.expected_impact.status !== "available",
    ).length ?? 0;
  const impactMeta = `${noImpact} of ${total} have no measurable impact estimate`;

  // While the agent is still analysing, nothing is on the table to decide:
  // a prepared recommendation is not yet an offered approval.
  if (runStatus === RUN_QUEUED || runStatus === RUN_RUNNING) {
    return {
      variant: "calm",
      icon: "clock",
      title: "Analysis in progress",
      line:
        total > 0
          ? `${total} recommendation(s) prepared so far. Approvals open once the run finishes.`
          : "Approvals open once the run finishes preparing recommendations.",
      meta: `${pending} of ${total} action(s) would need your decision · nothing is approvable yet`,
      actionable: false,
      pendingCount: pending,
      total,
    };
  }

  if (pending > 0) {
    return {
      variant: "hot",
      icon: "alert",
      title: "Your approval needed",
      line: `${pending} recommendation(s) are waiting for your decision.`,
      meta: `${pending} of ${total} action(s) awaiting your decision · ${counts.executed} executed · ${impactMeta}`,
      actionable: true,
      pendingCount: pending,
      total,
    };
  }
  if (outstanding > 0) {
    return {
      variant: "hot",
      icon: "clock",
      title: "Approved — awaiting execution",
      line: `${outstanding} action(s) approved by you; execution runs through the actions pipeline.`,
      meta: `${outstanding} approved, not yet executed · ${counts.executed} executed · ${impactMeta}`,
      actionable: false,
      pendingCount: 0,
      total,
    };
  }
  if (counts.executed > 0) {
    return {
      variant: "calm",
      icon: "check",
      title: counts.failed > 0 ? "Executed with failures" : "All actions executed",
      line:
        counts.failed > 0
          ? `${counts.executed} action(s) executed; ${counts.failed} failed during execution.`
          : `${counts.executed} action(s) executed through the actions pipeline. No approval is pending.`,
      meta: `${counts.executed} of ${total} action(s) executed · none awaiting a decision · ${impactMeta}`,
      actionable: false,
      pendingCount: 0,
      total,
    };
  }
  if (counts.rejected > 0) {
    return {
      variant: "calm",
      icon: "check",
      title: "No approval pending",
      line: `${counts.rejected} action(s) were rejected by you, so nothing was executed.`,
      meta: `${counts.rejected} rejected · 0 executed · none awaiting a decision`,
      actionable: false,
      pendingCount: 0,
      total,
    };
  }
  return {
    variant: "calm",
    icon: "check",
    title: "No approval pending",
    line:
      total > 0
        ? `${total} recommendation(s) prepared; none currently need a decision.`
        : "No recommendation from the last run requires a decision.",
    meta: impactMeta,
    actionable: false,
    pendingCount: 0,
    total,
  };
}

/* ── Run summary rows (Recent Work) ────────────────────────────────────── */

export type WorkRowTone = "waiting" | "approved" | "done" | "failed" | "rejected";

export interface WorkRowView {
  id: string;
  title: string;
  meta: string;
  /** Text rendered in the state pill. */
  stateLabel: string;
  tone: WorkRowTone;
  icon: "clock" | "check" | "alert";
}

const WORK_ROWS: Record<WorkRowTone, { stateLabel: string; icon: WorkRowView["icon"] }> = {
  waiting: { stateLabel: "Waiting", icon: "clock" },
  approved: { stateLabel: "Approved", icon: "clock" },
  done: { stateLabel: "Done", icon: "check" },
  failed: { stateLabel: "Failed", icon: "alert" },
  rejected: { stateLabel: "Rejected", icon: "alert" },
};

export function workRowView(item: WorkItemLike): WorkRowView {
  const state = item.state ?? "completed";
  const tone: WorkRowTone =
    state === "waiting_approval"
      ? "waiting"
      : state === "approved"
        ? "approved"
        : state === "failed"
          ? "failed"
          : state === "rejected"
            ? "rejected"
            : "done";
  const meta = WORK_ROWS[tone];
  return {
    id: item.id ?? state,
    title: item.title ?? "",
    meta: item.meta ?? "",
    stateLabel: meta.stateLabel,
    tone,
    icon: meta.icon,
  };
}

/* ── Learning card ─────────────────────────────────────────────────────── */

export const LEARNING_FALLBACK =
  "Learning begins after an approved recommendation is executed and produces a measurable outcome. Nothing has been learned yet.";

export function learningText(status: StatusLike | null | undefined, counts: ActionCounts): string {
  const text = (status?.learning_insight ?? "").trim();
  if (text) return text;
  if (counts.executed > 0) {
    return `${counts.executed} action(s) executed. Outcome measurement has not been recorded yet — execution results live in the per-action audit trail.`;
  }
  return LEARNING_FALLBACK;
}

/* ── View state (what the page renders) ────────────────────────────────── */

export type ViewState = "loading" | "error" | "stale" | "live";

export interface ViewInput {
  loading: boolean;
  error: string | null;
  status: StatusLike | null;
}

/**
 * `stale` = we hold a payload but the last refresh failed. The dashboard
 * stays on screen with the error reported beside it; only a failure with no
 * payload at all replaces the page with the error state.
 */
export function resolveViewState(input: ViewInput): ViewState {
  if (input.status) return input.error ? "stale" : "live";
  if (input.error) return "error";
  if (input.loading) return "loading";
  return "loading";
}

/* ── Self-check: the payload against itself (§11) ──────────────────────── */

export interface StatusMismatch {
  /** Dotted path of the field that disagrees. */
  field: string;
  expected: string;
  found: string;
  message: string;
}

function mismatch(
  field: string,
  expected: string,
  found: string,
  message: string,
): StatusMismatch {
  return { field, expected, found, message };
}

/**
 * Report contradictions inside one payload instead of hiding them: a run
 * status, approval flag, headline, metric and per-action state that describe
 * different worlds. The caller displays the result — it never rewrites the
 * state (the backend owns the fix; see product_action_sync / build_status).
 */
export function detectStatusMismatch(
  status: StatusLike | null | undefined,
  counts: ActionCounts,
): StatusMismatch[] {
  if (!status) return [];
  const out: StatusMismatch[] = [];
  const runStatus = status.status;
  const server = status.action_counts;
  const headline = (status.headline ?? "").toLowerCase();
  const support = (status.support ?? "").toLowerCase();
  const label = (status.status_label ?? "").toLowerCase();

  if (runStatus === RUN_WAITING_APPROVAL && counts.awaiting_approval === 0) {
    out.push(
      mismatch(
        "status",
        "at least 1 action awaiting a decision",
        runStatus,
        "Run reports waiting_approval while no action is awaiting a decision.",
      ),
    );
  }
  if (
    runStatus != null &&
    SUCCESSFUL_RUN_STATUSES.has(runStatus) &&
    counts.awaiting_approval > 0
  ) {
    out.push(
      mismatch(
        "status",
        "waiting_approval",
        runStatus,
        `Run reports ${runStatus} while ${counts.awaiting_approval} action(s) still await a decision.`,
      ),
    );
  }
  if (status.needs_approval !== undefined) {
    const expected = counts.awaiting_approval > 0;
    if (Boolean(status.needs_approval) !== expected) {
      out.push(
        mismatch(
          "needs_approval",
          String(expected),
          String(status.needs_approval),
          `needs_approval disagrees with the ${counts.awaiting_approval} live pending action(s).`,
        ),
      );
    }
  }
  if (
    (status.approval_status ?? "") === "required" &&
    counts.awaiting_approval === 0
  ) {
    out.push(
      mismatch(
        "approval_status",
        "not required",
        String(status.approval_status),
        "approval_status says a decision is required while none is pending.",
      ),
    );
  }
  if (label.includes("waiting for your approval") && counts.awaiting_approval === 0) {
    out.push(
      mismatch(
        "status_label",
        "no waiting-for-approval label",
        String(status.status_label),
        "Status label asks for approval while no action is pending.",
      ),
    );
  }
  if (headline.includes("nothing has been executed") && counts.executed > 0) {
    out.push(
      mismatch(
        "headline",
        `${counts.executed} executed`,
        String(status.headline),
        "Headline claims nothing was executed while actions are executed.",
      ),
    );
  }
  if (support.includes("no action required approval") && counts.total > 0) {
    out.push(
      mismatch(
        "support",
        `${counts.total} linked action(s)`,
        String(status.support),
        "Support text says no action was created while actions are linked.",
      ),
    );
  }
  if (
    (runStatus === RUN_QUEUED || runStatus === RUN_RUNNING) &&
    (support.includes("analysis complete") || support.includes("nothing has been executed"))
  ) {
    out.push(
      mismatch(
        "support",
        "in-progress wording",
        String(status.support),
        "Support text reports a finished analysis while the run is still in progress.",
      ),
    );
  }
  if (server && typeof server.total === "number") {
    const pairs: Array<keyof ActionCounts> = [
      "total",
      "awaiting_approval",
      "approved",
      "executing",
      "executed",
      "rejected",
      "failed",
    ];
    for (const key of pairs) {
      const value = server[key];
      if (typeof value === "number" && value !== counts[key]) {
        out.push(
          mismatch(
            `action_counts.${key}`,
            String(counts[key]),
            String(value),
            `Server action_counts.${key} disagrees with the live recommendation state.`,
          ),
        );
      }
    }
  }
  const executedMetric = status.metrics?.executed_count;
  if (typeof executedMetric === "number" && executedMetric !== counts.executed) {
    out.push(
      mismatch(
        "metrics.executed_count",
        String(counts.executed),
        String(executedMetric),
        "Recorded executed_count disagrees with the executed actions.",
      ),
    );
  }
  for (const rec of status.recommendations ?? []) {
    if (rec.approval_state === "REQUIRED" && rec.executed) {
      out.push(
        mismatch(
          "recommendations.approval_state",
          "not REQUIRED for an executed action",
          "REQUIRED",
          "A recommendation is both executed and still awaiting approval.",
        ),
      );
    }
  }
  return out;
}
