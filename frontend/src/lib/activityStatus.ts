/* Live Activity indicator state — the ONE mapping from an activity's
 * canonical lifecycle position to its visual row state.
 *
 * The indicator is derived from the backend event type (+ phase where the
 * type alone is ambiguous) and the selected run's canonical lifecycle
 * position — never from row position, never from title text. Rendered rows
 * carry `magi-activity__row--<state>` (and a matching `data-state`) so text
 * and indicator can never disagree:
 *
 *   completed → orange filled dot (the stage was reached and is done)
 *   active    → green pulsing dot (the timeline cursor: newest event of
 *               live work — same live convention as magi-live__dot--on)
 *   pending   → empty outline dot (ahead of the canonical position — a
 *               future stage that must never read as completed)
 *   failed    → strong-coral dot (a canonically failed step)
 *
 * Cumulative lifecycle progression (canonical 8-stage order):
 *   VERIFYING(0) → SAFETY_REVIEW(1) → PREPARING(2) → HANDOFF(3) →
 *   WAITING(4) → APPROVED(5) → EXECUTING(6) → EXECUTED(7)
 *
 * If stage N has been reached, every preceding stage is completed:
 *   - terminal run (canonical action completed/failed/rejected, or the run
 *     itself terminally closed) → EVERY reached row is completed;
 *   - approved live run → rows behind the canonical position are completed,
 *     the newest live row is the active cursor, rows ahead of the canonical
 *     position stay pending (never claimed as completed).
 *
 * Approval is the boundary (see isApprovalGranted): orange ALWAYS means
 * "completed in the approved execution flow". Before the merchant approves
 * (canonical action `requested`/null), every row stays neutral (pending)
 * except the live cursor (active) — preparation must never look like
 * completed execution.
 */

export type ActivityRowState = "completed" | "active" | "pending" | "failed";

/** Canonical 8-stage lifecycle order. Index = progression position. */
export const LIFECYCLE_STAGE_ORDER = [
  "VERIFYING",
  "SAFETY_REVIEW",
  "PREPARING",
  "HANDOFF",
  "WAITING",
  "APPROVED",
  "EXECUTING",
  "EXECUTED",
] as const;

export const STAGE_VERIFYING = 0;
export const STAGE_SAFETY_REVIEW = 1;
export const STAGE_PREPARING = 2;
export const STAGE_HANDOFF = 3;
export const STAGE_WAITING = 4;
export const STAGE_APPROVED = 5;
export const STAGE_EXECUTING = 6;
export const STAGE_EXECUTED = 7;
/** Nothing reached yet (e.g. a freshly queued run). */
export const STAGE_NONE = -1;

/** Backend event types whose canonical meaning is a FAILED step. Only a
 * lifecycle-level failure goes red — a failed tool call the run recovered
 * from keeps its cumulative state so its text never disagrees. */
const FAILED_EVENT_TYPES: ReadonlySet<string> = new Set([
  "action_failed",
  "verification_failed",
]);

/** Canonical action statuses that close the lifecycle (terminal). */
const TERMINAL_ACTION_STATUSES: ReadonlySet<string> = new Set([
  "completed",
  "failed",
  "rejected",
]);

/** Canonical action statuses proving the merchant granted approval: the
 * preparation gate is passed and the approved execution flow is (or was)
 * underway. `requested` (and null) means the merchant has NOT approved —
 * preparation rows must stay neutral, never completed. */
const APPROVAL_GRANTED_STATUSES: ReadonlySet<string> = new Set([
  "approved",
  "executing",
  "completed",
  "failed",
  "rejected",
]);

/** Run statuses that close the run itself (terminal). waiting_approval is
 * deliberately absent: a parked run with an open canonical action is still
 * live work, and a parked run whose action reached completed is terminal
 * via the canonical action status above. */
const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set([
  "completed",
  "failed",
  "blocked",
  "cancelled",
]);

/**
 * Map one backend event to its canonical lifecycle stage index, or null
 * when the event is run-level detail (research, tool calls, phase markers
 * outside the approval gate) rather than a lifecycle transition.
 *
 * Keyed ONLY on (event_type, phase) — never on message/title text.
 * `run_finished` is intentionally unmapped: the parking row ("Run
 * waiting_approval: …") duplicates `awaiting_approval` (deduped read-time
 * by the backend) while a terminal "Run completed: …" row is not a waiting
 * transition, so neither meaning can be assigned from the type alone.
 */
export function lifecycleStageOf(
  eventType: string,
  phase: string | null | undefined,
): number | null {
  switch (eventType) {
    case "verification_passed":
      return STAGE_SAFETY_REVIEW;
    case "action_prepared":
      return STAGE_PREPARING;
    case "handoff_opened":
      return STAGE_HANDOFF;
    case "awaiting_approval":
      return STAGE_WAITING;
    case "action_approved":
      return STAGE_APPROVED;
    case "execution_started":
      return STAGE_EXECUTING;
    case "action_executed":
      return STAGE_EXECUTED;
    case "phase_started":
      if (phase === "verify") return STAGE_VERIFYING;
      if (phase === "prepare") return STAGE_PREPARING;
      return null;
    default:
      return null;
  }
}

/**
 * Canonical lifecycle position reached by the selected run.
 *
 * Source of truth, in order: the canonical agent_actions status overlaid
 * live by the backend (prepStatus) → the run status → the run phase for
 * still-running loops. Never derived from event text.
 */
export function canonicalLifecycleStage(
  canonicalActionState: string | null | undefined,
  runStatus: string | null | undefined,
  runPhase: string | null | undefined,
): number {
  switch (canonicalActionState) {
    case "completed":
    case "failed":
    case "rejected":
      return STAGE_EXECUTED;
    case "executing":
      return STAGE_EXECUTING;
    case "approved":
      return STAGE_APPROVED;
    case "requested":
      return STAGE_WAITING;
    default:
      break;
  }
  switch (runStatus) {
    case "waiting_approval":
      return STAGE_WAITING;
    case "completed":
    case "failed":
    case "blocked":
    case "cancelled":
      return STAGE_EXECUTED;
    case "queued":
      return STAGE_NONE;
    case "running":
      break;
    default:
      return STAGE_NONE;
  }
  switch (runPhase) {
    case "load_context":
    case "observe":
    case "investigate":
      return STAGE_VERIFYING;
    case "verify":
      return STAGE_SAFETY_REVIEW;
    case "plan":
    case "create":
    case "prepare":
      return STAGE_PREPARING;
    case "awaiting_approval":
      return STAGE_WAITING;
    case "complete":
      return STAGE_EXECUTING;
    default:
      return STAGE_NONE;
  }
}

/**
 * Whether the selected run's lifecycle is terminally closed: every
 * displayed stage belonging to it must render completed (except a
 * canonically failed step, which stays failed). Derived from the canonical
 * action status first, the run status second — never from events.
 */
export function isLifecycleTerminal(
  canonicalActionState: string | null | undefined,
  runStatus: string | null | undefined,
): boolean {
  if (
    canonicalActionState &&
    TERMINAL_ACTION_STATUSES.has(canonicalActionState)
  ) {
    return true;
  }
  return !!runStatus && TERMINAL_RUN_STATUSES.has(runStatus);
}

/**
 * Whether the merchant has granted approval for the selected run's
 * canonical action. This is THE boundary between preparation and approved
 * execution: orange always means "completed in the approved execution
 * flow", so without approval no row may render completed. Derived from the
 * canonical agent_actions status only — never from events.
 */
export function isApprovalGranted(
  canonicalActionState: string | null | undefined,
): boolean {
  return (
    !!canonicalActionState &&
    APPROVAL_GRANTED_STATUSES.has(canonicalActionState)
  );
}

export interface ActivityRowContext {
  /** True for the newest row of the newest-first visible feed. */
  isNewest: boolean;
  /** The selected run still has live work (active, or parked with an open
   * canonical action). Derived from the same shouldPollRun/canonical-state
   * helpers that drive polling — never a second state system. */
  runLive: boolean;
  /** Canonical lifecycle position reached by the selected run
   * (see canonicalLifecycleStage). Stages at/below it were reached. */
  currentStage: number;
  /** The selected run's lifecycle is terminally closed
   * (see isLifecycleTerminal): every reached row renders completed. */
  terminal: boolean;
  /** The merchant granted approval for the canonical action
   * (see isApprovalGranted). Orange means "completed in the approved
   * execution flow" — without approval, rows stay neutral (pending) with
   * only the live cursor active. */
  approvalGranted: boolean;
}

/** Rendered indicator class for a row state (what the test asserts on). */
export function activityRowClass(state: ActivityRowState): string {
  return `magi-activity__row--${state}`;
}

export function activityRowState(
  eventType: string,
  phase: string | null | undefined,
  ctx: ActivityRowContext,
): ActivityRowState {
  // A canonically failed step stays failed on live AND terminal runs.
  if (FAILED_EVENT_TYPES.has(eventType)) return "failed";
  // Terminal lifecycle: every reached stage is completed, regardless of
  // row position. This is the completed-run case: EXECUTED reached ⇒
  // VERIFYING … EXECUTING are completed too.
  if (ctx.terminal) return "completed";
  // Approval boundary: before the merchant approves, the agent is only
  // preparing/recommending — nothing may read as completed execution.
  // Preparation rows stay neutral (pending); only the live cursor is
  // active. Orange is reserved for the approved execution flow below.
  if (!ctx.approvalGranted) {
    return ctx.isNewest && ctx.runLive ? "active" : "pending";
  }
  const stage = lifecycleStageOf(eventType, phase);
  // Run-level detail (research, tool calls): the live cursor is active,
  // everything superseded is done.
  if (stage === null) return ctx.isNewest && ctx.runLive ? "active" : "completed";
  // Live cursor: the newest event of live work is happening now.
  if (ctx.isNewest && ctx.runLive) return "active";
  // Ahead of the canonical position: a future stage that exists as a row
  // (stale/duplicate delivery) must never read as completed.
  if (stage > ctx.currentStage) return "pending";
  return "completed";
}
