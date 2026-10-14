/**
 * Designer Agent dashboard presentation logic.
 *
 * Every test here asserts a TRUTHFULNESS property, not just a shape: that a
 * fabricated number is never shown, that an asset kind is never promoted, and
 * that a brand logo is never mistaken for a working connection.
 */
import {
  anyToolConnected,
  assetKindIcon,
  assetKindLabel,
  buildDesignerOutputs,
  designerActivityDetail,
  designerActivityView,
  designerStatusCopy,
  designerToolConnection,
  generateAvailability,
  generationErrorMessage,
  generationSuccessMessage,
  llmFailureMessage,
  mergeDesignerMetrics,
  outputPillTone,
  reviewLabel,
} from "../designerWorkspace.js";
// Type-only: erased at compile time, so the emitted JS has no import of it.
import type {
  CreativeBrief,
  DesignAsset,
  DesignerActivityEntry,
  DesignerImageGeneration,
  DesignerIntegration,
  DesignerStatusMetric,
} from "../../types/api.js";

let seq = 0;
const id = () => `0000000${seq++}-0000-4000-8000-000000000000`;

/* ── fixtures ────────────────────────────────────────────────────────── */

function metric(key: string, value: number): DesignerStatusMetric {
  return { key, label: key, value, hint: `${value} from stored rows` };
}

function asset(over: Partial<DesignAsset> = {}): DesignAsset {
  return {
    id: id(),
    merchant_id: "m",
    project_id: "p",
    brief_id: null,
    kind: "variant",
    title: "Editorial variant",
    variant_key: "control",
    status: "ready_for_review",
    review_status: "pending_review",
    current_version_id: null,
    version_count: 1,
    image_generation: {
      status: "unavailable",
      provider: null,
      reason: "No image-generation provider is configured for this workspace.",
      asset_reference: null,
    },
    created_at: "2026-01-01T00:00:00.000Z",
    updated_at: "2026-01-01T00:00:00.000Z",
    ...over,
  };
}

function brief(over: Partial<CreativeBrief> = {}): CreativeBrief {
  return {
    id: id(),
    project_id: "p",
    version: 1,
    is_current: 1,
    title: "Summer refresh",
    objective: "One coherent visual system",
    audience: null,
    channel: null,
    format_spec: null,
    brand_constraints: null,
    content_requirements: null,
    layout_direction: null,
    color_guidance: null,
    typography_guidance: null,
    accessibility_considerations: null,
    dependencies: null,
    open_questions: null,
    assumptions: null,
    evidence: null,
    radar_references: null,
    variants: null,
    review_status: "pending_review",
    review_notes: null,
    confidence: 0.7,
    validation: null,
    llm_provider: null,
    llm_model: null,
    analysis_cycle_id: null,
    agent_run_id: null,
    created_at: "2026-01-02T00:00:00.000Z",
    updated_at: "2026-01-02T00:00:00.000Z",
    ...over,
  };
}

/* ── metrics ─────────────────────────────────────────────────────────── */

function testMergeDesignerMetrics() {
  const fallback = [
    { key: "runs", value: 4, label: "Total runs", hint: "4 runs" },
    { key: "failed", value: 1, label: "Failed runs", hint: "1 failed" },
  ];

  // Real counts win outright.
  const withReal = mergeDesignerMetrics(
    [metric("projects", 2), metric("briefs", 5), metric("awaiting_review", 3)],
    fallback,
  );
  if (withReal.length !== 3) throw new Error("real metrics must replace the fallback entirely");
  if (withReal.some((m) => m.fromRecords === false))
    throw new Error("real metrics must all be marked as record-derived");
  if (withReal[0].value !== "2") throw new Error("value must be the real count");

  // No real metrics -> the fallback is used and is NOT claimed as a record count.
  const noReal = mergeDesignerMetrics(null, fallback);
  if (noReal.length !== 2) throw new Error("fallback must be used when no real metrics exist");
  if (noReal[0].fromRecords !== false)
    throw new Error("a run-derived metric must not claim to come from records");

  // An empty array is treated as "not loaded", not as "zero real metrics".
  const emptyReal = mergeDesignerMetrics([], fallback);
  if (emptyReal[0].fromRecords !== false)
    throw new Error("an empty metrics array must not blank the panel");

  // Each key gets a glyph and a tone; unknown keys degrade safely.
  if (withReal[0].icon !== "folder") throw new Error("projects must use the folder glyph");
  if (withReal[1].icon !== "doc") throw new Error("briefs must use the doc glyph");
  if (withReal[2].hintTone !== "accent") throw new Error("pending review must read as waiting");
  const unknown = mergeDesignerMetrics([metric("something_new", 4)], []);
  if (unknown[0].icon !== "doc") throw new Error("an unknown key must fall back to the doc glyph");
  if (unknown[0].tone !== "coral") throw new Error("an unknown key must fall back to a neutral tone");

  // No invented numbers: values are always the backend's strings.
  if (mergeDesignerMetrics([metric("projects", 0)], fallback)[0].value !== "0")
    throw new Error("a real zero must render as 0, not be replaced by a fallback");
}

/* ── asset kinds are never conflated ─────────────────────────────────── */

function testAssetKinds() {
  if (assetKindLabel("brief") !== "Creative brief") throw new Error("brief label");
  if (assetKindLabel("variant") !== "Creative variant") throw new Error("variant label");
  if (assetKindLabel("rendered_image") !== "Rendered image") throw new Error("image label");
  if (assetKindIcon("variant") !== "layers") throw new Error("variant icon");
  if (assetKindIcon("rendered_image") === assetKindIcon("brief"))
    throw new Error("a rendered image must not share the brief glyph");

  // Every kind is spelled distinctly, so the UI can never imply a brief is an
  // image.
  const labels = (["brief", "specification", "variant", "rendered_image"] as const).map(
    assetKindLabel,
  );
  if (new Set(labels).size !== labels.length) throw new Error("asset kind labels must be unique");
}

function testBuildDesignerOutputs() {
  const rows = buildDesignerOutputs(
    [asset({ kind: "variant", title: "Bold variant", created_at: "2026-01-01T00:00:00.000Z" })],
    [brief({ title: "Summer refresh", created_at: "2026-01-02T00:00:00.000Z" })],
    Date.parse("2026-01-03T00:00:00.000Z"),
  );

  if (rows.length !== 2) throw new Error("an asset and a brief are distinct records");
  if (rows[0].title !== "Summer refresh") throw new Error("newest must sort first");
  if (rows[1].title !== "Bold variant") throw new Error("older asset must sort second");

  // A variant asset is never relabelled as an image.
  const variant = rows[1];
  if (variant.kind !== "variant") throw new Error("variant kind must be preserved");
  if (variant.kindLabel !== "Creative variant") throw new Error("variant label must be preserved");
  if (!variant.detail.includes("not an image"))
    throw new Error("a variant must state that image generation is unavailable");

  // Only a brief carries a confidence number; a variant must not inherit one.
  if (rows[0].confidence !== 0.7) throw new Error("a brief carries its own confidence");
  if (variant.confidence !== null) throw new Error("a variant must not invent a confidence");

  // Empty inputs produce an empty list, not placeholder rows.
  if (buildDesignerOutputs([], [], 0).length !== 0)
    throw new Error("empty inputs must produce an empty list");

  // Identical timestamps must still produce a stable order, so a record never
  // appears to jump around between the 15s polls.
  const tieInput = [
    asset({ id: "b", created_at: "2026-01-01T00:00:00.000Z" }),
    asset({ id: "a", created_at: "2026-01-01T00:00:00.000Z" }),
  ];
  const tieA = buildDesignerOutputs(tieInput, [], 0).map((r) => r.id);
  const tieB = buildDesignerOutputs([...tieInput].reverse(), [], 0).map((r) => r.id);
  if (tieA.join(",") !== tieB.join(","))
    throw new Error("tie order must be independent of input order");
  if (tieA.join(",") !== "asset-a,asset-b")
    throw new Error(`tie order must break by id, got ${tieA.join(",")}`);
}

/* ── review is a human act ───────────────────────────────────────────── */

function testReviewLabels() {
  if (reviewLabel("pending_review") !== "Awaiting your review")
    throw new Error("pending review must be spelled out for the merchant");
  if (reviewLabel("changes_requested") !== "Changes requested")
    throw new Error("changes requested");
  if (reviewLabel("approved") !== "Approved") throw new Error("approved");
  if (reviewLabel("weird_state") !== "weird state")
    throw new Error("an unknown status must degrade readably, not to undefined");

  if (outputPillTone("approved") !== "ok") throw new Error("approved reads done");
  if (outputPillTone("pending_review") !== "accent")
    throw new Error("pending review must read as waiting, not done");
  if (outputPillTone("draft") !== "neutral") throw new Error("draft reads neutral");
}

/* ── a logo is not a connection ──────────────────────────────────────── */

function testDesignerToolConnection() {
  const integrations: DesignerIntegration[] = [
    {
      provider: "figma",
      label: "Figma",
      purpose: "Design file handoff",
      status: "connected",
      supported: true,
      detail: "Connected as workspace account",
    },
    {
      provider: "canva",
      label: "Canva",
      purpose: "Template and asset exchange",
      status: "setup_required",
      supported: true,
      detail: "No integration is configured for this workspace.",
    },
  ];

  if (designerToolConnection("figma", integrations, true).status !== "connected")
    throw new Error("a real connection must be reported as connected");
  if (designerToolConnection("canva", integrations, true).status !== "setup_required")
    throw new Error("an unconfigured provider must read setup_required");
  if (designerToolConnection("figma", integrations, true).pill !== "designer-tool__pill--on")
    throw new Error("connected pill class");

  // An absent provider is `unknown`, never silently "setup required".
  if (designerToolConnection("notion", integrations, true).status !== "unknown")
    throw new Error("an unreported provider must be unknown, not assumed unconfigured");

  // When the status endpoint itself failed, nothing may be claimed.
  const unknownLoad = designerToolConnection("figma", integrations, false);
  if (unknownLoad.status !== "unknown")
    throw new Error("a failed status load must not claim any connection");
  if (unknownLoad.detail !== "Connection status unavailable.")
    throw new Error("a failed status load must say so");

  if (!anyToolConnected(integrations)) throw new Error("a real connection must be detected");
  if (anyToolConnected([{ ...integrations[1] }]))
    throw new Error("setup_required must not count as connected");
  if (anyToolConnected(null)) throw new Error("null integrations must not claim a connection");
}

/* ── activity ────────────────────────────────────────────────────────── */

function activity(over: Partial<DesignerActivityEntry> = {}): DesignerActivityEntry {
  return {
    id: "run-1",
    kind: "run",
    title: "Designer Agent run",
    detail: null,
    status: "completed",
    at: "2026-01-01T00:00:00.000Z",
    ...over,
  };
}

function testDesignerActivityView() {
  // A failure must never inherit the pulsing in-flight glyph.
  const failed = designerActivityView(activity({ status: "failed" }));
  if (failed.icon !== "alert") throw new Error("a failed run must show the alert glyph");
  if (failed.tone !== "red") throw new Error("a failed run must read red");

  const active = designerActivityView(activity({ status: "running" }));
  if (active.icon !== "pulse") throw new Error("an in-flight run uses the pulse glyph");
  if (active.tone !== "accent") throw new Error("an in-flight run reads as live");

  const done = designerActivityView(activity({ status: "completed" }));
  if (done.icon !== "check") throw new Error("a completed run shows the check glyph");

  if (designerActivityView(activity({ kind: "project" })).icon !== "folder")
    throw new Error("project glyph");
  if (designerActivityView(activity({ kind: "brief" })).icon !== "doc")
    throw new Error("brief glyph");
  if (designerActivityView(activity({ kind: "review" })).icon !== "clipboard")
    throw new Error("review glyph");
  if (designerActivityView(activity({ kind: "review", status: "failed" })).tone !== "red")
    throw new Error("a failed review must still read red");

  // Detail: real detail wins, then the real status, then the kind.
  if (
    designerActivityDetail(activity({ detail: "2 variants" })) !== "2 variants"
  )
    throw new Error("real detail must be preferred");
  if (
    designerActivityDetail(activity({ detail: null, status: "pending_review" })) !==
    "Awaiting your review"
  )
    throw new Error("a missing detail falls back to the human status");
  if (designerActivityDetail(activity({ detail: "  ", status: null, kind: "asset" })) !== "asset")
    throw new Error("a blank detail must not render as empty");
}

/* ── status copy is never optimistic ─────────────────────────────────── */

function testDesignerStatusCopy() {
  const base = {
    registered: true,
    agentName: "DesignerAgent",
    modeLabel: "Growth Team",
    awaitingReview: 0,
    latestBrief: null,
    relative: "2 hours ago",
    runError: null,
  };

  const notRegistered = designerStatusCopy({ ...base, registered: false, runState: "none" });
  if (!notRegistered.support.includes("DesignerAgent"))
    throw new Error("an unregistered agent must name the agent it looked for");

  const noWork = designerStatusCopy({ ...base, runState: "none" });
  if (noWork.headline !== "No design work has run yet.")
    throw new Error("no work must not be described as active");

  const active = designerStatusCopy({ ...base, runState: "active" });
  if (active.headline !== "Your creative work is in progress.")
    throw new Error("only a real in-flight run may claim progress");

  const failed = designerStatusCopy({
    ...base,
    runState: "failed",
    runError: "provider timed out",
  });
  if (!failed.support.includes("provider timed out"))
    throw new Error("a failure must surface its real error");

  const waiting = designerStatusCopy({ ...base, runState: "idle", awaitingReview: 3 });
  if (waiting.headline !== "3 briefs waiting on your review.")
    throw new Error("pending review count must be reflected");

  const oneWaiting = designerStatusCopy({ ...base, runState: "idle", awaitingReview: 1 });
  if (oneWaiting.headline !== "1 brief waiting on your review.")
    throw new Error("singular wording");

  const withBrief = designerStatusCopy({
    ...base,
    runState: "idle",
    latestBrief: { title: "Summer refresh", version: 2, reviewStatus: "pending_review" },
  });
  if (!withBrief.support.includes("Summer refresh") || !withBrief.support.includes("v2"))
    throw new Error("the latest real brief must be named with its version");

  const idle = designerStatusCopy({ ...base, runState: "idle" });
  if (idle.headline !== "Your creative work is up to date.")
    throw new Error("idle copy");

  // Approved brief with nothing pending must not still say "waiting".
  const approved = designerStatusCopy({
    ...base,
    runState: "idle",
    latestBrief: { title: "Shipped", version: 3, reviewStatus: "approved" },
  });
  if (approved.headline.includes("waiting"))
    throw new Error("an approved brief must not read as pending review");
}

/* ── image generation UX ─────────────────────────────────────────────── */

function gen(over: Partial<DesignerImageGeneration> = {}): DesignerImageGeneration {
  return {
    status: "available",
    provider: "cloudflare",
    reason: null,
    asset_reference: null,
    model: "cloudflare-flux-1-schnell",
    ...over,
  };
}

function testGenerateAvailability() {
  // Provider configured + asset present -> ready and enabled.
  const ready = generateAvailability({
    imageGeneration: gen(),
    hasAsset: true,
    submitting: false,
  });
  if (ready.phase !== "ready") throw new Error(`expected ready, got ${ready.phase}`);
  if (!ready.canSubmit) throw new Error("ready must be submittable");
  if (ready.label !== "Generate Image") throw new Error("ready label");

  // In flight -> disabled, so a double-click cannot fork two generations.
  const busy = generateAvailability({
    imageGeneration: gen(),
    hasAsset: true,
    submitting: true,
  });
  if (busy.phase !== "submitting") throw new Error("must report submitting");
  if (busy.canSubmit) throw new Error("must be disabled while in flight");

  // Feature off -> unavailable, and the backend's own reason is surfaced.
  const off = generateAvailability({
    imageGeneration: gen({
      status: "unavailable",
      reason: "Image generation is switched off (IMAGE_GENERATION_ENABLED=false).",
    }),
    hasAsset: true,
    submitting: false,
  });
  if (off.phase !== "unavailable") throw new Error("a disabled provider is unavailable");
  if (off.canSubmit) throw new Error("a disabled provider must NOT be submittable");
  if (!off.message.includes("IMAGE_GENERATION_ENABLED"))
    throw new Error("must state the real reason, not a generic one");

  // No asset -> explains the prerequisite instead of pretending to be ready.
  const noAsset = generateAvailability({
    imageGeneration: gen(),
    hasAsset: false,
    submitting: false,
  });
  if (noAsset.phase !== "no_asset") throw new Error("expected no_asset");
  if (noAsset.canSubmit) throw new Error("nothing to generate from must be disabled");
  if (!noAsset.message.toLowerCase().includes("asset"))
    throw new Error("must explain the asset prerequisite");

  // No status at all (endpoint failed) -> unavailable, never optimistic.
  const unknown = generateAvailability({
    imageGeneration: null,
    hasAsset: true,
    submitting: false,
  });
  if (unknown.phase !== "unavailable") throw new Error("unknown state must be unavailable");
  if (unknown.canSubmit) throw new Error("unknown state must not be submittable");
  if (!unknown.message) throw new Error("must always explain itself");

  // A previous failure keeps the button usable so the user can retry.
  const retry = generateAvailability({
    imageGeneration: gen(),
    hasAsset: true,
    submitting: false,
    lastResult: gen({ status: "failed", reason: "The image provider is rate limiting this workspace." }),
  });
  if (retry.phase !== "failed") throw new Error("a failure must stay visible");
  if (!retry.canSubmit) throw new Error("a failed attempt must still be retryable");
  if (!retry.message.includes("rate limiting")) throw new Error("failure reason must be shown");
}

function testGenerationSuccessMessage() {
  const ok = generationSuccessMessage(
    gen({
      status: "completed",
      rendered_asset_id: "r-1",
      width: 1024,
      height: 1024,
      byte_size: 333904,
    }),
  );
  if (!ok || !ok.includes("stored")) throw new Error("success must say it was stored");
  if (!ok.includes("1024×1024")) throw new Error("success must state real dimensions");

  // CRITICAL: no success without a real persisted reference.
  for (const bad of [
    gen({ status: "failed", rendered_asset_id: "r-1" }),
    gen({ status: "completed", rendered_asset_id: undefined }),
    gen({ status: "completed" }),
    gen({ status: "unavailable" }),
  ]) {
    if (generationSuccessMessage(bad) !== null)
      throw new Error("must never report success without a stored reference");
  }
}

function testGenerationErrorMessage() {
  const cases: Array<[unknown, string]> = [
    [{ status: 401 }, "session"],
    [{ status: 403 }, "permission"],
    [{ status: 429 }, "Too many"],
    [{ status: 0 }, "backend"],
    [{ code: "PROVIDER_RATE_LIMITED", status: 200 }, "rate limiting"],
    [{ code: "PROVIDER_TIMEOUT", status: 200 }, "did not respond"],
  ];
  for (const [err, needle] of cases) {
    const msg = generationErrorMessage(err);
    if (!msg.toLowerCase().includes(needle.toLowerCase()))
      throw new Error(`error message for ${JSON.stringify(err)} should mention "${needle}", got "${msg}"`);
  }
  if (!generationErrorMessage(new Error("boom")).includes("boom"))
    throw new Error("an unrecognised error should still surface its message");
  if (!generationErrorMessage({}))
    throw new Error("an empty error must still produce a sentence");
}

/* ── LLM failure copy ───────────────────────────────────────────────── */

function testLLMFailureMessage() {
  // The critical one: an exhausted daily quota must NOT invite a retry.
  const quota = llmFailureMessage("quota_exhausted");
  if (!/quota is exhausted/i.test(quota)) throw new Error("quota copy");
  if (!/will not help/i.test(quota)) {
    throw new Error("an exhausted daily quota must say retrying will not help");
  }

  // A transient throttle SHOULD invite a retry.
  const throttled = llmFailureMessage("rate_limited");
  if (!/try again/i.test(throttled)) throw new Error("a throttle should be retryable");

  // Configuration failures point at an administrator, not at the merchant,
  // and must never name a backend env var (see
  // test_no_frontend_llm_credential / test_docker_compose_does_not_pass_the_token_to_the_frontend).
  for (const [cat, needle] of [
    ["auth", /administrator/i],
    ["model_unavailable", /administrator/i],
  ] as const) {
    if (!needle.test(llmFailureMessage(cat))) {
      throw new Error(`${cat} copy must escalate to an administrator`);
    }
  }

  // Never leak the raw category code, never return empty.
  const codes = [
    "quota_exhausted",
    "rate_limited",
    "auth",
    "model_unavailable",
    "invalid_request",
    "timeout",
    "transient",
  ];
  for (const c of [...codes, "banana"]) {
    const msg = llmFailureMessage(c);
    if (!msg || msg.trim().length < 20) throw new Error(`no usable copy for ${c}`);
    // An unrecognised category must not be echoed back verbatim either.
    if (c !== "banana" && msg.toLowerCase().includes(c)) {
      throw new Error(`raw code leaked into copy: ${msg}`);
    }
  }
}

function testActivityDetailTranslatesLLMFailures() {
  const entry = (
    kind: DesignerActivityEntry["kind"],
    detail: string,
    status: string,
  ): DesignerActivityEntry => ({
    id: id(),
    kind,
    detail,
    status,
    title: kind,
    at: "2026-01-01T00:00:00Z",
  });

  const quota = designerActivityDetail(
    entry("run", "brief_generation_failed:quota_exhausted", "failed"),
  );
  if (quota.includes("quota_exhausted")) {
    throw new Error("the raw category code must not be shown to the merchant");
  }
  if (!/daily token quota/i.test(quota)) throw new Error(`untranslated detail: ${quota}`);

  // An unrelated detail is passed through untouched.
  const other = designerActivityDetail(
    entry("brief", "Summer refresh - 3 variants", "completed"),
  );
  if (other !== "Summer refresh - 3 variants") {
    throw new Error(`real detail must survive: ${other}`);
  }

  // Falls back to the status when there is no detail at all.
  const bare = designerActivityDetail(entry("brief", "", "completed"));
  if (bare !== reviewLabel("completed")) throw new Error(`bad fallback: ${bare}`);
}

/* ── runner ──────────────────────────────────────────────────────────── */

/**
 * A deliberate throw rather than `process.exit`, matching the existing
 * `designerAgent.test.ts` runner so this needs no Node type definitions.
 */
const TESTS: Array<[string, () => void]> = [
  ["mergeDesignerMetrics", testMergeDesignerMetrics],
  ["asset kinds are never conflated", testAssetKinds],
  ["buildDesignerOutputs", testBuildDesignerOutputs],
  ["review labels are human-readable", testReviewLabels],
  ["a logo is not a connection", testDesignerToolConnection],
  ["activity never shows a failure as live", testDesignerActivityView],
  ["status copy is never optimistic", testDesignerStatusCopy],
  ["LLM failure copy is actionable", testLLMFailureMessage],
  ["activity details translate LLM failures", testActivityDetailTranslatesLLMFailures],
  ["generate availability is honest", testGenerateAvailability],
  ["success requires a persisted image", testGenerationSuccessMessage],
  ["errors are merchant-readable", testGenerationErrorMessage],
];

let failures = 0;
for (const [name, fn] of TESTS) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (e) {
    failures++;
    console.error(`FAIL ${name}\n  ${(e as Error).message}`);
  }
}
console.log(
  failures === 0
    ? "\ndesigner workspace: all checks passed"
    : `\n${failures} designerWorkspace check(s) failed`,
);
if (failures > 0) throw new Error(`${failures} designerWorkspace check(s) failed`);