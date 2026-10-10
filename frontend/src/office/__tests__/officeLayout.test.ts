/**
 * Command-centre bubble layout + Product Agent status mapping.
 *
 * These cover the two visual defects reported from the AI Command Centre:
 *   1. two speech bubbles ("4 recommendation(s) prepared" and "Blocked")
 *      rendered on top of each other and hid the pixel-art office;
 *   2. a Product Agent that had been approved / was executing / had finished
 *      was labelled FAILED in the office.
 *
 * Run: npm run test:office
 */
import {
  resolveBubblePlacements,
  hasNoOverlap,
  allInsideWorld,
  type BubbleItem,
  type Rect,
} from "../bubbleLayout.js";
import {
  productAgentOfficeSlot,
  marketingAgentOfficeSlot,
} from "../../pages/agentStatusMapping.js";
import type { MarketingAGIRun, ProductAgentRun } from "@/types/api";

/* ── helpers ─────────────────────────────────────────────────────────────── */

let failures = 0;
let passes = 0;

function check(name: string, condition: boolean, detail?: string): void {
  if (condition) {
    passes += 1;
  } else {
    failures += 1;
    console.error(`  FAIL  ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

function eq(name: string, actual: unknown, expected: unknown): void {
  check(name, Object.is(actual, expected), `expected ${String(expected)}, got ${String(actual)}`);
}

function rectsOf(placements: { id: string; rect: Rect | null }[]): Rect[] {
  return placements.filter((p) => p.rect !== null).map((p) => p.rect as Rect);
}

/* ── 1. The reported failure: two bubbles in the same place ──────────────── */

{
  const world = { w: 1600, h: 1200 };
  // Both bubbles anchored at the same spot — the reported overlap.
  const items: BubbleItem[] = [
    {
      id: "ProductAgent",
      base: { x: 700, y: 500, w: 150, h: 40 },
      critical: true,
    },
    {
      id: "MarketingAgent",
      base: { x: 700, y: 500, w: 150, h: 40 },
      critical: false,
    },
  ];
  const out = resolveBubblePlacements(items, world);
  check(
    "two simultaneous messages both get placed",
    out.every((p) => p.rect !== null),
    "one was dropped",
  );
  check("two simultaneous messages do not overlap", hasNoOverlap(rectsOf(out)));
  check("two simultaneous messages stay in the world", allInsideWorld(rectsOf(out), world));
  eq("both ids are reported", out.length, 2);
}

/* ── 2. Long text wrapping / pathological size ───────────────────────────── */

{
  const world = { w: 1200, h: 900 };
  // A very tall bubble (many wrapped lines) next to a normal one.
  const items: BubbleItem[] = [
    { id: "tall", base: { x: 300, y: 300, w: 400, h: 320 }, critical: false },
    { id: "short", base: { x: 320, y: 320, w: 150, h: 40 }, critical: true },
  ];
  const out = resolveBubblePlacements(items, world);
  check("long message does not overlap a neighbour", hasNoOverlap(rectsOf(out)));
  check("long message is never clipped outside the scene", allInsideWorld(rectsOf(out), world));
}

/* ── 3. The whole cast at once (13 agents) ───────────────────────────────── */

{
  const world = { w: 2000, h: 1400 };
  const items: BubbleItem[] = Array.from({ length: 13 }, (_, i) => ({
    id: `agent-${i}`,
    // Cluster several agents around the same tiles, as a busy floor does.
    base: { x: 400 + (i % 3) * 30, y: 600 + Math.floor(i / 3) * 12, w: 150, h: 44 },
    critical: i === 0 || i === 5,
  }));
  const out = resolveBubblePlacements(items, world);
  const rects = rectsOf(out);
  check("13 bubbles produce no overlap", hasNoOverlap(rects), "overlap remained");
  check("13 bubbles stay inside the world", allInsideWorld(rects, world));
  check(
    "crowding drops bubbles instead of stacking them",
    rects.length <= items.length,
  );
}

/* ── 4. Priority: an approval gate survives a crowded floor ──────────────── */

{
  const world = { w: 600, h: 400 };
  // A world just big enough for one bubble: the critical one must win.
  const items: BubbleItem[] = [
    { id: "chatter-1", base: { x: 10, y: 10, w: 150, h: 44 }, critical: false },
    { id: "chatter-2", base: { x: 12, y: 12, w: 150, h: 44 }, critical: false },
    { id: "approval", base: { x: 11, y: 11, w: 150, h: 44 }, critical: true },
  ];
  const out = resolveBubblePlacements(items, world);
  const approval = out.find((p) => p.id === "approval");
  check(
    "an approval gate is placed even when the floor is crowded",
    approval?.rect !== null,
    "the critical bubble was the one dropped",
  );
}

/* ── 5. Determinism + trivial cases ─────────────────────────────────────── */

{
  const items: BubbleItem[] = [
    { id: "a", base: { x: 10, y: 10, w: 100, h: 30 }, critical: false },
    { id: "b", base: { x: 20, y: 20, w: 100, h: 30 }, critical: false },
  ];
  const first = resolveBubblePlacements(items, { w: 800, h: 600 });
  const second = resolveBubblePlacements(items, { w: 800, h: 600 });
  eq(
    "layout is deterministic",
    JSON.stringify(first),
    JSON.stringify(second),
  );

  const empty = resolveBubblePlacements([], { w: 800, h: 600 });
  eq("empty input yields empty output", empty.length, 0);

  const single = resolveBubblePlacements([items[0]], { w: 800, h: 600 });
  check("a lone bubble keeps its natural position", single[0].rect !== null);
  if (single[0].rect) {
    eq("a lone bubble is not moved", single[0].rect.x, 10);
    eq("a lone bubble is not moved (y)", single[0].rect.y, 10);
  }
}

/* ── 6. Bubbles anchored at the map edge stay visible ───────────────────── */

{
  const world = { w: 800, h: 600 };
  const items: BubbleItem[] = [
    // Avatar in the top-left corner — its bubble would poke off-world.
    { id: "corner", base: { x: 0, y: 0, w: 200, h: 60 }, critical: false },
    { id: "corner2", base: { x: 0, y: 0, w: 200, h: 60 }, critical: true },
  ];
  const out = resolveBubblePlacements(items, world);
  check("edge-anchored bubbles stay in the scene", allInsideWorld(rectsOf(out), world));
  check("edge-anchored bubbles do not overlap", hasNoOverlap(rectsOf(out)));
}

/* ── 7. Product Agent status → office status ────────────────────────────── */

{
  const base: ProductAgentRun = {
    id: "r1",
    merchant_id: "m1",
    objective: "Grow the catalog",
    status: "running",
    stage: "understand_catalog",
    metrics: {},
    recommendations_created: 0,
    products_analyzed: 0,
    opportunities_found: 0,
    approval_status: null,
    summary: null,
    errors: [],
    llm_provider: null,
    llm_model: null,
    analysis_cycle_id: null,
    started_at: null,
    completed_at: null,
    duration_seconds: null,
    state: {},
    result: null,
  };

  const cases: Array<[string, string]> = [
    ["approved_awaiting_execution", "AWAITING EXECUTION"],
    ["executing", "EXECUTING"],
    ["completed", "COMPLETED"],
    ["completed_no_actions", "COMPLETED"],
    ["completed_with_failures", "PARTIAL FAILURE"],
    ["blocked", "BLOCKED BY SAFETY"],
    ["failed", "FAILED"],
    ["cancelled", "CANCELLED"],
    ["waiting_approval", "WAITING FOR APPROVAL"],
    ["running", "READING CATALOG"],
    ["queued", "QUEUED"],
  ];

  for (const [status, expectedChip] of cases) {
    const slot = productAgentOfficeSlot({ ...base, status });
    eq(`"${status}" maps to its own chip`, slot.chip, expectedChip);
    check(
      `"${status}" is never shown as FAILED`,
      slot.chip !== "FAILED" || status === "failed",
      `chip was ${slot.chip}`,
    );
  }

  // A partial failure must not read as a plain completion.
  const partial = productAgentOfficeSlot({ ...base, status: "completed_with_failures" });
  check("partial failure is not reported as COMPLETED", partial.chip !== "COMPLETED");

  // A blocked run must surface the backend's own reason.
  const blocked = productAgentOfficeSlot({
    ...base,
    status: "blocked",
    errors: ["recommendation 2 failed safety verification"],
  });
  check(
    "blocked surfaces the real backend reason",
    blocked.monitor.includes("failed safety verification"),
    blocked.monitor,
  );
  check("blocked keeps the blocked word", blocked.monitor.startsWith("Blocked"));

  // A failure must surface the real reason too.
  const failed = productAgentOfficeSlot({
    ...base,
    status: "failed",
    errors: ["groq quota exhausted"],
  });
  check("failure surfaces the real backend reason", failed.monitor.includes("groq quota exhausted"));
}

/* ── 8. Marketing Agent: blocked ≠ failed, and never invents a reason ──── */

{
  const mk = (status: string, errors: string[], objective = "Objective text"): MarketingAGIRun => ({
    id: "mg1",
    merchant_id: "m",
    objective,
    status,
    phase: "complete",
    state: {
      evidence: [],
      tool_calls: [],
      llm_decisions: [],
      retrieval_log: [],
      hypotheses: [],
      observations: [],
      errors,
      reasoning_status: "reasoning",
      llm_degraded: false,
      prepared_action: null,
    } as unknown as MarketingAGIRun["state"],
    llm_provider: "groq",
    iterations: 1,
    tool_call_count: 0,
    analysis_cycle_id: null,
    started_at: null,
    completed_at: null,
    result: null,
    errors,
    llm_model: null,
  } as MarketingAGIRun);

  // The exact reported message: a task objective used as a failure reason.
  const failed = marketingAgentOfficeSlot(mk("failed", [], "Comprehensive commerce analysis and growth optimization"), []);
  check(
    "a failed run never renders the objective as its reason",
    !failed.monitor.includes("Comprehensive commerce analysis"),
    failed.monitor,
  );
  check("a failed run is not labelled BLOCKED", failed.chip !== "BLOCKED", failed.chip);

  const blocked = marketingAgentOfficeSlot(mk("blocked", ["safety policy rejected the campaign"]), []);
  check("a genuinely blocked run stays BLOCKED", blocked.chip === "BLOCKED");
  check(
    "a blocked run shows its real reason",
    blocked.monitor.includes("safety policy rejected the campaign"),
    blocked.monitor,
  );

  const degraded = marketingAgentOfficeSlot(mk("failed", ["boom"], "Obj"), []);
  check("a failure does not claim the LLM is unavailable when it is not", !degraded.sub.includes("LLM unavailable"), degraded.sub);

  const unknown = marketingAgentOfficeSlot(mk("some_future_status", [], "Obj"), []);
  check("an unknown status is not reported as BLOCKED", unknown.chip !== "BLOCKED");
}

/* ── result ──────────────────────────────────────────────────────────────── */

declare const process: { exit(code: number): void };

console.log(`\n  ${passes} passed, ${failures} failed\n`);
if (failures > 0) process.exit(1);