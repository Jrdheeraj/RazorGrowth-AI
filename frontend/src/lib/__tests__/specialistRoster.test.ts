/**
 * specialistRoster.test — hand-rolled runner (matches the existing convention
 * in frontend/src/lib/__tests__/*.test.ts, which use `tsc` + `node`, not a
 * test framework).
 *
 * The critical property under test: the roster must never upgrade a missing,
 * unimplemented or failed thing into a healthy-looking one.
 */
import {
  buildRoster,
  groupByCategory,
  phaseForRun,
  toolSummary,
  type RosterSummary,
  type CatalogLike,
  type AgentRunLike,
} from "../specialistRoster.js";

let passed = 0;
let failed = 0;

function ok(name: string, condition: boolean, detail = "") {
  if (condition) {
    passed++;
    console.log(`ok   ${name}`);
  } else {
    failed++;
    console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ""}`);
  }
}

function eq(name: string, actual: unknown, expected: unknown) {
  ok(name, Object.is(actual, expected), `expected ${String(expected)}, got ${String(actual)}`);
}

const tool = (id: string, readOnly = true) => ({
  tool_id: id,
  summary: `${id} summary`,
  read_only: readOnly,
  required_permission: "read_merchant",
  timeout_seconds: 30,
  input_fields: ["merchant_id"],
  output_fields: ["status"],
  source: "services.test",
});

const run = (over: Partial<AgentRunLike> = {}): AgentRunLike => ({
  agent: "A",
  status: "completed",
  ok: true,
  output: {},
  errors: [],
  tools_used: [],
  opportunities_created: 0,
  actions_proposed: 0,
  insights_generated: 0,
  signals_detected: 0,
  experiments_proposed: 0,
  latency_ms: { total: 1, llm: 0, db: 1 },
  llm_configured: false,
  ...over,
});

const catalog: CatalogLike = {
  tool_count: 2,
  agent_count: 2,
  tools: [tool("a.b"), tool("c.d", false)],
  agents: [
    {
      name: "ImplementedAgent",
      description: "Has real tools.",
      category: "domain_specialist",
      permissions: ["read_merchant"],
      tools: ["a.b", "c.d"],
      unimplemented_tools: [],
      tool_details: [tool("a.b"), tool("c.d", false)],
      can_approve: false,
      can_execute: false,
    },
    {
      name: "PartialAgent",
      description: "Declares tools that do not exist.",
      category: "domain_specialist",
      permissions: ["read_merchant"],
      tools: ["a.b"],
      unimplemented_tools: ["phantom_tool", "ghost_tool"],
      tool_details: [tool("a.b")],
      can_approve: false,
      can_execute: false,
    },
  ],
};

/* ── buildRoster ───────────────────────────────────────────────────────── */

let roster: RosterSummary = buildRoster(catalog);
eq("roster counts every agent", roster.totalAgents, 2);
eq("roster reports the catalog tool count", roster.totalTools, 2);
ok("roster is not empty", roster.isEmpty === false);
ok("roster is not an error", roster.isError === false);
eq("exactly one agent is fully implemented", roster.fullyImplementedAgents, 1);
eq("one agent has unimplemented tools", roster.agentsWithUnimplementedTools, 1);
ok("unimplemented names are surfaced, not hidden",
  roster.agents[1].unimplementedTools.length === 2);
ok("unimplemented agent is NOT reported as fully implemented",
  roster.agents[1].fullyImplemented === false);
ok("implemented agent IS reported as fully implemented",
  roster.agents[0].fullyImplemented === true);

/* ── honest empty / error states ───────────────────────────────────────── */

const empty = buildRoster({ ...catalog, agents: [], agent_count: 0 });
ok("no agents => isEmpty", empty.isEmpty === true);
ok("no agents => not an error", empty.isError === false);
eq("no agents => zero total", empty.totalAgents, 0);

const failedLoad = buildRoster(null);
ok("null catalog => isError", failedLoad.isError === true);
ok("null catalog => isEmpty", failedLoad.isEmpty === true);
eq("null catalog => no agents", failedLoad.totalAgents, 0);

/* ── phase derivation never upgrades a failure ─────────────────────────── */

eq("null run => idle", phaseForRun(null), "idle");
eq("ok run with no actions => completed", phaseForRun(run()), "completed");
eq("ok run with proposed actions => approval_required",
  phaseForRun(run({ actions_proposed: 2 })), "approval_required");
eq("failed run => failed", phaseForRun(run({ ok: false, status: "failed" })), "failed");
eq("cancelled run => cancelled", phaseForRun(run({ status: "cancelled" })), "cancelled");
eq("not-ok run => partial", phaseForRun(run({ ok: false })), "partial");

const failedRoster = buildRoster(catalog, { ImplementedAgent: run({ ok: false, status: "failed", errors: ["boom"] }) });
eq("failed agent is counted as failed", failedRoster.failedAgents, 1);
eq("failed agent phase is failed", failedRoster.agents[0].status, "failed");
ok("failed agent shows the real error, not 'Completed'",
  failedRoster.agents[0].statusLabel.indexOf("Completed") === -1,
  failedRoster.agents[0].statusLabel);
ok("approval_required surfaces the action count",
  buildRoster(catalog, { ImplementedAgent: run({ actions_proposed: 3 }) })
    .agents[0].statusLabel.indexOf("3") !== -1);

/* ── grouping + tool summary ───────────────────────────────────────────── */

const grouped = groupByCategory(roster);
eq("all specialists group into specialists", grouped.specialists.length, 2);
eq("no main-team agents present", grouped.main.length, 0);
ok("tool summary reports the count",
  toolSummary(roster.agents[0]).indexOf("2 tool(s)") === 0,
  toolSummary(roster.agents[0]));

const noTools: RosterSummary = buildRoster({
  tool_count: 0,
  agent_count: 1,
  tools: [],
  agents: [
    {
      name: "Bare",
      description: "",
      category: "domain_specialist",
      permissions: [],
      tools: [],
      unimplemented_tools: [],
      tool_details: [],
      can_approve: false,
      can_execute: false,
    },
  ],
});
ok("a tool-less agent does not claim full implementation", noTools.fullyImplementedAgents === 0);
eq("a tool-less agent says so", noTools.agents[0].statusLabel, "No tools registered");
eq("missing description falls back rather than blank",
  noTools.agents[0].description, "No mission recorded.");

const toolLess: RosterSummary = buildRoster({
  tool_count: 0,
  agent_count: 1,
  tools: [],
  agents: [
    {
      name: "Bare",
      description: "",
      category: "domain_specialist",
      permissions: [],
      tools: [],
      unimplemented_tools: [],
      tool_details: [],
      can_approve: false,
      can_execute: false,
    },
  ],
});
ok("agent with no tools is never 'fully implemented'", toolLess.fullyImplementedAgents === 0);
eq("agent with no tools says so", toolLess.agents[0].statusLabel, "No tools registered");
eq("missing description falls back rather than blank",
  toolLess.agents[0].description, "No mission recorded.");

console.log(
  failed === 0
    ? `\nspecialistRoster: ${passed} passed, all checks passed`
    : `\nspecialistRoster: ${failed} check(s) failed`,
);
if (failed > 0) {
  throw new Error(`${failed} specialistRoster check(s) failed`);
}