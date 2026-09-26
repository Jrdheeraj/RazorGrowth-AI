/* Regression test for the Live Activity visual indicator.
 *
 * Guards two production bugs:
 *
 * 1. COMPLETED runs showed only "Campaign executed successfully" with the
 *    completed/orange indicator while earlier lifecycle rows rendered empty.
 * 2. PRE-APPROVAL runs showed orange completed dots on preparation rows
 *    ("Preparing the campaign for your approval", "Campaign safety check
 *    completed", …) — visually implying approved execution had finished
 *    before the merchant ever approved.
 *
 * The rule under test: orange ALWAYS means "completed in the APPROVED
 * execution flow". Approval (canonicalActionState granted) is the boundary
 * between preparation and approved execution. Before approval every row
 * stays neutral (pending) except the live cursor (active).
 *
 * The canonical lifecycle position comes from run/action state
 * (canonicalActionState → run status → run phase), each row maps via
 * (event_type, phase) — never via title text, never via row position.
 *
 * Every check asserts the RENDERED indicator class
 * (`magi-activity__row--<state>`), not just the state string and never the
 * text.
 *
 * Zero-dependency: compiled with the project's own tsc and executed with
 * plain node (`npm run test:activity`). Fails with a non-zero exit code.
 */
import {
  activityRowClass,
  activityRowState,
  canonicalLifecycleStage,
  isApprovalGranted,
  isLifecycleTerminal,
  STAGE_APPROVED,
  STAGE_EXECUTED,
  STAGE_EXECUTING,
  STAGE_WAITING,
  type ActivityRowContext,
} from "../activityStatus.js";

let failures = 0;

function check(name: string, actual: unknown, expected: unknown): void {
  if (actual === expected) {
    console.log(`ok   ${name}`);
  } else {
    failures += 1;
    console.log(`FAIL ${name}: got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)}`);
  }
}

function ctx(over: Partial<ActivityRowContext>): ActivityRowContext {
  return {
    isNewest: false,
    runLive: false,
    currentStage: STAGE_WAITING,
    terminal: false,
    approvalGranted: false,
    ...over,
  };
}

/** The rendered indicator class for one row. */
function cls(
  eventType: string,
  phase: string | null,
  c: Partial<ActivityRowContext>,
): string {
  return activityRowClass(activityRowState(eventType, phase, ctx(c)));
}

// ── Canonical position derivation (state in, stage out — never text) ─────
check(
  "canonicalActionState completed -> EXECUTED",
  canonicalLifecycleStage("completed", "completed", "complete"),
  STAGE_EXECUTED,
);
check(
  "canonicalActionState requested -> WAITING",
  canonicalLifecycleStage("requested", "waiting_approval", "awaiting_approval"),
  STAGE_WAITING,
);
check(
  "canonicalActionState approved -> APPROVED",
  canonicalLifecycleStage("approved", "waiting_approval", "awaiting_approval"),
  STAGE_APPROVED,
);
check(
  "canonicalActionState executing -> EXECUTING",
  canonicalLifecycleStage("executing", "waiting_approval", "awaiting_approval"),
  STAGE_EXECUTING,
);
check(
  "completed action is terminal",
  isLifecycleTerminal("completed", "completed"),
  true,
);
check(
  "requested action is not terminal",
  isLifecycleTerminal("requested", "waiting_approval"),
  false,
);
check(
  "executing action is not terminal",
  isLifecycleTerminal("executing", "waiting_approval"),
  false,
);
check("requested action has no approval", isApprovalGranted("requested"), false);
check("null action has no approval", isApprovalGranted(null), false);
check("approved action has approval", isApprovalGranted("approved"), true);
check("executing action has approval", isApprovalGranted("executing"), true);
check("completed action has approval", isApprovalGranted("completed"), true);
check("rejected action has approval", isApprovalGranted("rejected"), true);

// ── CASE 1: WAITING_FOR_APPROVAL (approval NOT granted) ───────────────────
// The approval boundary: preparation rows stay NEUTRAL (pending) — orange
// must never imply completed execution before the merchant approves. The
// waiting row is the live cursor (active); future stages stay pending.
const WAITING = ctx({ runLive: true, currentStage: STAGE_WAITING });
check(
  "case1: verifying row -> pending class (no orange before approval)",
  cls("phase_started", "verify", { ...WAITING }),
  "magi-activity__row--pending",
);
check(
  "case1: safety-review row -> pending class (no orange before approval)",
  cls("verification_passed", "verify", { ...WAITING }),
  "magi-activity__row--pending",
);
check(
  "case1: preparing row -> pending class (no orange before approval)",
  cls("action_prepared", "prepare", { ...WAITING }),
  "magi-activity__row--pending",
);
check(
  "case1: handoff row -> pending class (no orange before approval)",
  cls("handoff_opened", "prepare", { ...WAITING }),
  "magi-activity__row--pending",
);
check(
  "case1: waiting row (live cursor) -> active class",
  cls("awaiting_approval", "awaiting_approval", { ...WAITING, isNewest: true }),
  "magi-activity__row--active",
);
check(
  "case1: future approved row -> pending class (never completed)",
  cls("action_approved", "execute", { ...WAITING }),
  "magi-activity__row--pending",
);
check(
  "case1: future executed row -> pending class (never completed)",
  cls("action_executed", "complete", { ...WAITING }),
  "magi-activity__row--pending",
);

// ── CASE 2: APPROVED (approval granted — approved execution flow) ─────────
// Everything through APPROVED completed, approval is the live cursor,
// execution stages ahead of position stay pending.
const APPROVED = ctx({
  runLive: true,
  currentStage: STAGE_APPROVED,
  approvalGranted: true,
});
check(
  "case2: waiting row after approval -> completed class",
  cls("awaiting_approval", "awaiting_approval", { ...APPROVED }),
  "magi-activity__row--completed",
);
check(
  "case2: approval row (live cursor) -> active class",
  cls("action_approved", "execute", { ...APPROVED, isNewest: true }),
  "magi-activity__row--active",
);
check(
  "case2: future execution row -> pending class",
  cls("execution_started", "execute", { ...APPROVED }),
  "magi-activity__row--pending",
);
check(
  "case2: future executed row -> pending class",
  cls("action_executed", "complete", { ...APPROVED }),
  "magi-activity__row--pending",
);

// ── CASE 3: EXECUTING ─────────────────────────────────────────────────────
const EXECUTING = ctx({
  runLive: true,
  currentStage: STAGE_EXECUTING,
  approvalGranted: true,
});
check(
  "case3: approved row -> completed class",
  cls("action_approved", "execute", { ...EXECUTING }),
  "magi-activity__row--completed",
);
check(
  "case3: execution row (live cursor) -> active class",
  cls("execution_started", "execute", { ...EXECUTING, isNewest: true }),
  "magi-activity__row--active",
);
check(
  "case3: future executed row -> pending class",
  cls("action_executed", "complete", { ...EXECUTING }),
  "magi-activity__row--pending",
);

// ── CASE 4: COMPLETED — the exact reported bug ────────────────────────────
// Newest-first feed of the real completed run: EVERY reached lifecycle row
// must carry the completed/orange indicator class, regardless of position.
const DONE = ctx({
  runLive: false,
  currentStage: STAGE_EXECUTED,
  terminal: true,
  approvalGranted: true,
});
const completedFeed: Array<[string, string | null]> = [
  ["action_executed", "complete"], // Campaign executed successfully
  ["execution_started", "execute"], // Campaign execution started
  ["action_approved", "execute"], // Campaign approved by you
  ["awaiting_approval", "awaiting_approval"], // Waiting for your approval
  ["handoff_opened", "prepare"], // Creative review requested
  ["action_prepared", "prepare"], // Preparing the campaign for your approval
  ["verification_passed", "verify"], // Campaign safety check completed
  ["phase_started", "verify"], // Checking customers and campaign safety
];
completedFeed.forEach(([t, p], i) => {
  check(
    `case4: completed-run row ${i} (${t}) -> completed class`,
    cls(t, p, { ...DONE, isNewest: i === 0 }),
    "magi-activity__row--completed",
  );
});

// ── Live run detail rows (non-lifecycle events) ───────────────────────────
check(
  "live: newest tool row -> active class",
  cls("tool_used", "investigate", {
    runLive: true,
    currentStage: STAGE_WAITING,
    isNewest: true,
  }),
  "magi-activity__row--active",
);
check(
  "pre-approval: superseded tool row -> pending class (no orange before approval)",
  cls("tool_used", "investigate", {
    runLive: true,
    currentStage: STAGE_WAITING,
  }),
  "magi-activity__row--pending",
);
check(
  "post-approval: superseded tool row -> completed class",
  cls("tool_used", "investigate", {
    runLive: true,
    currentStage: STAGE_EXECUTING,
    approvalGranted: true,
  }),
  "magi-activity__row--completed",
);
check(
  "terminal: superseded tool row -> completed class",
  cls("tool_used", "investigate", { ...DONE }),
  "magi-activity__row--completed",
);

// ── Failure stays failure ─────────────────────────────────────────────────
check(
  "action_failed on live run -> failed class",
  cls("action_failed", "complete", {
    runLive: true,
    currentStage: STAGE_EXECUTING,
    isNewest: true,
  }),
  "magi-activity__row--failed",
);
check(
  "action_failed on terminal run -> failed class",
  cls("action_failed", "complete", { ...DONE, isNewest: true }),
  "magi-activity__row--failed",
);
check(
  "verification_failed -> failed class",
  cls("verification_failed", "verify", { ...DONE }),
  "magi-activity__row--failed",
);
// A failed tool call the run recovered from keeps cumulative state.
check(
  "tool_failed newest of live work -> active class (not failed)",
  cls("tool_failed", "investigate", {
    runLive: true,
    currentStage: STAGE_WAITING,
    isNewest: true,
  }),
  "magi-activity__row--active",
);

// ── Resolved-but-negative steps conclude (never stuck pending) ────────────
check(
  "action_rejected terminal -> completed class",
  cls("action_rejected", "awaiting_approval", { ...DONE, isNewest: true }),
  "magi-activity__row--completed",
);
check(
  "action_reused historical -> completed class",
  cls("action_reused", "execute", { ...DONE }),
  "magi-activity__row--completed",
);

if (failures > 0) {
  throw new Error(`${failures} activityStatus check(s) failed`);
}
console.log("activityStatus: all checks passed");
