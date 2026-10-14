/**
 * Designer Agent read-model tests — zero dependency, no backend, no browser.
 * Run with `npm run test:designer`.
 *
 * These lock the truthfulness rules: no fabricated metric, no invented status,
 * no output that is not backed by a real Designer Agent record.
 */
import {
  DESIGNER_AGENT_NAME,
  buildDesignerSnapshot,
  designerActivity,
  designerAvailability,
  designerCardFinding,
  designerCardSupport,
  designerFindingsFrom,
  designerMetrics,
  designerOutputs,
  designerProjectRows,
  designerRunsFromRows,
  isDesignerRunActive,
  relativeTime,
  type DesignerFindingLike,
  type DesignerRunRowLike,
} from "../designerAgent.js";

let failures = 0;

function ok(name: string, cond: boolean, detail = "") {
  if (cond) {
    console.log(`ok   ${name}`);
  } else {
    failures += 1;
    console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ""}`);
  }
}

function eq(name: string, actual: unknown, expected: unknown) {
  ok(name, Object.is(actual, expected), `expected ${String(expected)}, got ${String(actual)}`);
}

const NOW = Date.parse("2026-03-10T12:00:00Z");

function run(over: Partial<DesignerRunRowLike> = {}): DesignerRunRowLike {
  return {
    id: "11111111-2222-3333-4444-555555555555",
    agent_name: DESIGNER_AGENT_NAME,
    status: "completed",
    mode: "team",
    orchestrator_run_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    started_at: "2026-03-10T11:00:00Z",
    completed_at: "2026-03-10T11:00:12Z",
    total_latency_ms: 4200,
    opportunities_created: 2,
    actions_proposed: 1,
    tools_used: ["creative_concept", "ux_recommendations"],
    errors: null,
    ...over,
  };
}

/* ── Only the Designer Agent's own runs are used ───────────────────────── */

{
  const rows = [
    run(),
    run({ agent_name: "MarketingAgent", id: "other-1" }),
    run({ agent_name: "ProductAgent", id: "other-2" }),
    run({ id: "designer-2", status: "running", completed_at: null, started_at: "2026-03-10T11:50:00Z" }),
  ];
  const runs = designerRunsFromRows(rows);
  eq("filters to the Designer Agent only", runs.length, 2);
  eq("newest run first", runs[0].id, "designer-2");
  eq("running status preserved", runs[0].status, "running");
  eq("tool trace normalised", runs[1].tools.join(","), "creative_concept,ux_recommendations");
}

{
  eq("no rows → no runs", designerRunsFromRows(null).length, 0);
  eq("empty rows → no runs", designerRunsFromRows([]).length, 0);
}

/* ── Availability is separate from execution state ─────────────────────── */

{
  const notRegistered = designerAvailability(false, []);
  eq("unregistered agent is not 'available'", notRegistered.label, "Not registered");

  const idle = designerAvailability(true, designerRunsFromRows([run()]));
  eq("registered + idle = available", idle.label, "Available");
  eq("available tone is success", idle.tone, "ok");

  const working = designerAvailability(
    true,
    designerRunsFromRows([run({ status: "running", completed_at: null })]),
  );
  eq("in-flight run reads as working", working.label, "Working now");
  eq("in-flight tone is accent", working.tone, "accent");

  const failed = designerAvailability(true, designerRunsFromRows([run({ status: "failed" })]));
  eq("a failed run does not mean unavailable", failed.label, "Available");
}

/* ── Metrics come only from real runs ──────────────────────────────────── */

{
  const runs = designerRunsFromRows([
    run({ id: "a", started_at: "2026-03-09T10:00:00Z", completed_at: "2026-03-09T10:00:10Z" }),
    run({ id: "b", started_at: "2026-03-01T10:00:00Z", completed_at: "2026-03-01T10:00:10Z" }),
    run({ id: "c", status: "failed", started_at: "2026-02-01T10:00:00Z", errors: ["boom"] }),
  ]);
  const m = designerMetrics(runs, NOW);
  eq("metric count", m.length, 4);
  eq("total runs", m[0].value, "3");
  eq("completed runs", m[1].value, "2");
  eq("running now", m[2].value, "0");
  eq("failed runs", m[3].value, "1");
  ok("7-day hint is derived from timestamps", m[0].hint.includes("1 in the last 7 days"), m[0].hint);
  ok("failure hint surfaces the real error", m[3].hint.includes("boom"), m[3].hint);
}

{
  const m = designerMetrics([], NOW);
  ok("no runs → zero, never a placeholder number", m.every((x) => x.value === "0"), JSON.stringify(m));
  eq("no runs → honest hint", m[0].hint, "No runs recorded yet");
  eq("no runs → no fake latency", m[1].hint, "No completed run to measure yet");
}

/* ── Findings must belong to the designer specialty ────────────────────── */

function finding(over: Partial<DesignerFindingLike> = {}): DesignerFindingLike {
  return {
    id: "f-1",
    agent_specialty: "designer",
    finding_type: "supporting",
    title: "Checkout Journey & Friction Reduction for Payment Failures",
    description: "Streamlined recovery UX for failed payments.",
    confidence: 0.85,
    uncertainty_notes: null,
    supports_recommendation: true,
    ...over,
  };
}

{
  const findings = designerFindingsFrom(
    [finding(), finding({ id: "f-2", agent_specialty: "marketing" })],
    "debate-1",
    "Reduce checkout drop-off",
    NOW,
  );
  eq("only designer findings are mapped", findings.length, 1);
  eq("parent debate carried through", findings[0].debateObjective, "Reduce checkout drop-off");
  eq("parent debate timestamp used", findings[0].recordedAt, NOW);
}

{
  const outputs = designerOutputs(designerFindingsFrom([finding()], "d", "Objective", NOW));
  eq("one output per designer finding", outputs.length, 1);
  eq("UX findings classified as UX recommendations", outputs[0].kind, "UX recommendation");
  eq("supporting finding review state", outputs[0].reviewLabel, "Supports plan");
  ok("output body is never empty filler", outputs[0].body.length > 0);
}

{
  const outputs = designerOutputs(
    designerFindingsFrom([finding({ finding_type: "uncertainty", id: "f-3" })], "d", "Obj", NOW),
  );
  eq("uncertainty is its own review state", outputs[0].reviewLabel, "Open question");
}

{
  eq("no findings → no outputs", designerOutputs([]).length, 0);
}

/* ── Projects mirror real run records ──────────────────────────────────── */

{
  const rows = designerProjectRows(designerRunsFromRows([run({ status: "running", completed_at: null })]));
  eq("one project row per run", rows.length, 1);
  eq("running reads as in progress", rows[0].status, "In progress");
  ok("project row names the real AI Team cycle", /^Cycle [0-9a-f]{8}/.test(rows[0].project), rows[0].project);
  eq("no runs → no projects", designerProjectRows([]).length, 0);
}

/* ── Activity is built from real records only ──────────────────────────── */

{
  const runs = designerRunsFromRows([run()]);
  const findings = designerFindingsFrom([finding()], "d", "Objective", NOW);
  const items = designerActivity(runs, findings);
  eq("run + brief produce two activity rows", items.length, 2);
  ok("every item carries a kind", items.every((i) => i.kind === "run" || i.kind === "brief"));
  ok("no empty detail strings", items.every((i) => i.detail.length > 0));
  eq("no records → no activity", designerActivity([], []).length, 0);
}

/* ── AI Team card copy never fabricates ────────────────────────────────── */

{
  const nothing = designerCardFinding([], []);
  ok("no run → invites a real analysis", nothing.includes("No Designer Agent run yet"), nothing);

  const noFindings = designerCardFinding(designerRunsFromRows([run()]), []);
  ok("completed run reports its real counts", noFindings.includes("2 opportunities"), noFindings);

  const withBrief = designerCardFinding([], designerFindingsFrom([finding()], "d", "Obj", NOW));
  ok("a real brief is quoted", withBrief.includes("Checkout Journey"), withBrief);
  ok("brief copy states it needs human review", withBrief.includes("human review"), withBrief);

  eq("no records at all → honest support line", designerCardSupport([], []), "0 runs recorded · 0 creative briefs on file");
}

/* ── Relative time ─────────────────────────────────────────────────────── */

ok("just now", relativeTime(NOW - 5_000, NOW) === "Just now");
ok("minutes", relativeTime(NOW - 5 * 60_000, NOW) === "5 min ago");
ok("hours", relativeTime(NOW - 3 * 3_600_000, NOW) === "3 h ago");
ok("days", relativeTime(NOW - 2 * 86_400_000, NOW) === "2 d ago");
ok("unknown timestamp is stated, never faked", relativeTime(null, NOW) === "Unknown time");

/* ── Snapshot assembly ─────────────────────────────────────────────────── */

{
  eq("in-flight statuses are recognised", [isDesignerRunActive("queued"), isDesignerRunActive("running"), isDesignerRunActive("completed")].join(","), "true,true,false");
}

{
  const empty = buildDesignerSnapshot({});
  eq("empty snapshot is not registered", empty.registered, false);
  eq("empty snapshot has no runs", empty.runs.length, 0);
  eq("empty snapshot is not in flight", empty.inFlight, false);
}

{
  const snap = buildDesignerSnapshot({
    registryEntry: { description: "Creative specialist.", tools: ["creative_concept", "messaging_strategy"] },
    runRows: [run({ status: "running", completed_at: null })],
    debates: [{ id: "d1", objective: "Reduce drop-off", updatedAt: NOW }],
    findingsByDebate: new Map([["d1", [finding()]]]),
  });
  eq("registry entry read", snap.registered, true);
  eq("declared tools read", snap.tools.length, 2);
  eq("run in flight detected", snap.inFlight, true);
  eq("brief mapped", snap.findings.length, 1);
  eq("latest run exposed", snap.latest?.id, run().id);
}

{
  const capped = buildDesignerSnapshot({
    debates: [1, 2, 3, 4, 5].map((n) => ({ id: `d${n}`, objective: `O${n}`, updatedAt: NOW })),
    findingsByDebate: new Map([["d1", [finding({ id: "a" })]]]),
  });
  eq("only the newest debates are scanned", capped.findings.length, 1);
}

console.log(failures === 0 ? "\ndesigner agent: all checks passed" : `\n${failures} check(s) failed`);
if (failures > 0) {
  throw new Error(`${failures} designerAgent check(s) failed`);
}