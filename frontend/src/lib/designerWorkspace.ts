/**
 * Pure presentation logic for the Designer Agent dashboard.
 *
 * Extracted from the page component so it can be unit-tested without a DOM,
 * matching the existing `productAgentStatus.ts` / `activityStatus.ts`
 * convention. The page keeps only layout; every decision about what a number
 * MEANS, what an artefact IS, and whether a tool is connected lives here.
 *
 * THE HONESTY RULES THIS MODULE ENFORCES
 * --------------------------------------
 *  1. Real metrics win. A run-derived fallback is used only when the backend's
 *     own count endpoint is unavailable, and the two are never blended.
 *  2. Asset kinds are never collapsed. A brief stays a brief; nothing is
 *     promoted to a "rendered image" that was never generated.
 *  3. A tool is connected only when the backend reported a real connection.
 *     A brand logo is never evidence of one.
 *  4. A failed agent run never wears the pulsing "live right now" glyph.
 *
 * `.js` specifiers on the type-only imports match the convention already used
 * by `src/lib/__tests__/designerAgent.test.ts` and let this module compile
 * under the same standalone `nodenext` invocation the other lib tests use.
 */
import type {
  CreativeBrief,
  DesignAsset,
  DesignAssetKind,
  DesignerActivityEntry,
  DesignerImageGeneration,
  DesignerIntegration,
  DesignerStatusMetric,
} from "../types/api.js";

/* ── Metrics ─────────────────────────────────────────────────────────── */

/** The cell glyph for each backend metric key. */
const METRIC_ICON: Record<string, string> = {
  projects: "folder",
  briefs: "doc",
  awaiting_review: "clipboard",
  approved: "check-circle",
  failed_runs: "alert",
};

/**
 * Cell tone. Only genuinely warning-ish metrics read as warnings, so a healthy
 * workspace is not rendered entirely in alert colours.
 */
const METRIC_TONE: Record<string, string> = {
  projects: "coral",
  briefs: "coral",
  awaiting_review: "amber",
  approved: "green",
  failed_runs: "red",
};

const METRIC_HINT_TONE: Record<string, string> = {
  projects: "ok",
  briefs: "ok",
  awaiting_review: "accent",
  approved: "ok",
  failed_runs: "",
};

export interface DesignerMetricCell {
  key: string;
  value: string;
  label: string;
  hint: string;
  icon: string;
  tone: string;
  hintTone: string;
  /** True when the number came from persisted rows rather than run history. */
  fromRecords: boolean;
}

/**
 * Prefer the backend's real row counts. Only fall back to run-derived metrics
 * when `real` is absent — and mark the cell so the UI can say so, rather than
 * silently presenting two different kinds of number as one.
 */
export function mergeDesignerMetrics(
  real: DesignerStatusMetric[] | null | undefined,
  fallback: Array<{ key: string; value: number | string; label: string; hint: string }>,
): DesignerMetricCell[] {
  const decorate = (
    key: string,
    value: string,
    label: string,
    hint: string,
    fromRecords: boolean,
  ): DesignerMetricCell => ({
    key,
    value,
    label,
    hint,
    icon: METRIC_ICON[key] ?? "doc",
    tone: METRIC_TONE[key] ?? "coral",
    hintTone: METRIC_HINT_TONE[key] ?? "",
    fromRecords,
  });

  if (real && real.length) {
    return real.map((m) => decorate(m.key, String(m.value), m.label, m.hint, true));
  }
  return fallback.map((m) =>
    decorate(m.key, String(m.value), m.label, m.hint, false),
  );
}

/* ── Asset / brief kind ──────────────────────────────────────────────── */

const KIND_ICON: Record<DesignAssetKind, string> = {
  brief: "doc",
  specification: "layout",
  variant: "layers",
  rendered_image: "image",
};

const KIND_LABEL: Record<DesignAssetKind, string> = {
  brief: "Creative brief",
  specification: "Design specification",
  variant: "Creative variant",
  rendered_image: "Rendered image",
};

export function assetKindIcon(kind: DesignAssetKind): string {
  return KIND_ICON[kind] ?? "doc";
}

export function assetKindLabel(kind: DesignAssetKind): string {
  return KIND_LABEL[kind] ?? "Creative brief";
}

/* ── Review status ───────────────────────────────────────────────────── */

/** A review decision is a HUMAN act, so it is always spelled out. */
export function reviewLabel(status: string): string {
  switch (status) {
    case "pending_review":
      return "Awaiting your review";
    case "in_review":
      return "In review";
    case "approved":
      return "Approved";
    case "changes_requested":
      return "Changes requested";
    case "rejected":
      return "Rejected";
    case "draft":
      return "Draft";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "requested":
      return "Proposed";
    default:
      return status.replace(/_/g, " ");
  }
}

/** Pill tone for an output card. Approved reads done, pending reads waiting. */
export function outputPillTone(reviewStatus: string): "ok" | "accent" | "neutral" {
  if (reviewStatus === "approved") return "ok";
  if (reviewStatus === "pending_review" || reviewStatus === "in_review") return "accent";
  return "neutral";
}

/* ── Outputs ─────────────────────────────────────────────────────────── */

export interface DesignerOutputRow {
  id: string;
  title: string;
  kind: DesignAssetKind;
  kindLabel: string;
  icon: string;
  reviewStatus: string;
  reviewText: string;
  pillTone: "ok" | "accent" | "neutral";
  confidence: number | null;
  detail: string;
  recordedAt: number | null;
  projectId: string;
}

/**
 * Merge real assets and real briefs into one newest-first list.
 *
 * Both are shown, and their kinds are kept distinct: a variant asset and the
 * brief it came from are different records, and collapsing them would either
 * duplicate work or hide that the variant exists.
 */
export function buildDesignerOutputs(
  assets: readonly DesignAsset[],
  briefs: readonly CreativeBrief[],
  now: number,
): DesignerOutputRow[] {
  const rows: DesignerOutputRow[] = [];

  for (const a of assets) {
    rows.push({
      id: `asset-${a.id}`,
      title: a.title,
      kind: a.kind,
      kindLabel: assetKindLabel(a.kind),
      icon: assetKindIcon(a.kind),
      reviewStatus: a.review_status,
      reviewText: reviewLabel(a.review_status),
      pillTone: outputPillTone(a.review_status),
      // A variant has no confidence of its own; only a brief does.
      confidence: null,
      detail:
        a.kind === "rendered_image"
          ? "A rendered image asset."
          : `Structured ${assetKindLabel(a.kind).toLowerCase()}, version ${a.version_count}. ${
              a.image_generation?.status === "unavailable"
                ? "Image generation is not configured, so this is text, not an image."
                : ""
            }`.trim(),
      recordedAt: Date.parse(a.created_at) || null,
      projectId: a.project_id,
    });
  }

  for (const b of briefs) {
    rows.push({
      id: `brief-${b.id}`,
      title: b.title,
      kind: "brief",
      kindLabel: assetKindLabel("brief"),
      icon: assetKindIcon("brief"),
      reviewStatus: b.review_status,
      reviewText: reviewLabel(b.review_status),
      pillTone: outputPillTone(b.review_status),
      confidence: b.confidence ?? null,
      detail: b.objective,
      recordedAt: Date.parse(b.created_at) || null,
      projectId: b.project_id,
    });
  }

  /* Newest first. Ties broken by id so the order is stable across polls and a
     record never appears to jump around between refreshes. */
  return rows.sort((x, y) => {
    const d = (y.recordedAt ?? 0) - (x.recordedAt ?? 0);
    return d !== 0 ? d : x.id.localeCompare(y.id);
  });
}

/* ── Tool connections ────────────────────────────────────────────────── */

export interface DesignerToolConnection {
  status: "connected" | "setup_required" | "unsupported" | "unknown";
  pill: string;
  detail: string;
}

/**
 * A tool is `connected` ONLY when the backend reported a real integration
 * record for this workspace. A brand mark proves nothing, and an absent
 * provider list reports `unknown` rather than assuming "not connected".
 */
export function designerToolConnection(
  provider: string,
  integrations: readonly DesignerIntegration[] | null | undefined,
  statusLoaded: boolean,
): DesignerToolConnection {
  if (!statusLoaded || !integrations) {
    return {
      status: "unknown",
      pill: "designer-tool__pill",
      detail: "Connection status unavailable.",
    };
  }
  const found = integrations.find((i) => i.provider === provider);
  if (!found) {
    return {
      status: "unknown",
      pill: "designer-tool__pill",
      detail: "This provider is not reported for your workspace.",
    };
  }
  if (found.status === "connected") {
    return {
      status: "connected",
      pill: "designer-tool__pill--on",
      detail: found.detail,
    };
  }
  if (found.status === "unsupported") {
    return {
      status: "unsupported",
      pill: "designer-tool__pill",
      detail: found.detail,
    };
  }
  return {
    status: "setup_required",
    pill: "designer-tool__pill--setup",
    detail: found.detail,
  };
}

/** True when at least one external tool is genuinely connected. */
export function anyToolConnected(
  integrations: readonly DesignerIntegration[] | null | undefined,
): boolean {
  return Boolean(integrations?.some((i) => i.status === "connected"));
}

/* ── Activity ────────────────────────────────────────────────────────── */

export interface DesignerActivityView {
  icon: string;
  tone: string;
  label: string;
}

/**
 * Icon + tone for a real persisted activity row.
 *
 * A failed run is checked FIRST, so it can never inherit the pulsing "live
 * right now" glyph that an in-flight run legitimately uses.
 */
export function designerActivityView(
  item: DesignerActivityEntry,
): DesignerActivityView {
  if (item.status === "failed") {
    return { icon: "alert", tone: "red", label: "Failed" };
  }
  switch (item.kind) {
    case "run":
      return item.status === "completed"
        ? { icon: "check", tone: "ok", label: "Completed" }
        : { icon: "pulse", tone: "accent", label: "In progress" };
    case "project":
      return { icon: "folder", tone: "ok", label: "Project" };
    case "brief":
      return { icon: "doc", tone: "accent", label: "Creative brief" };
    case "asset":
      return { icon: "image", tone: "neutral", label: "Design asset" };
    case "review":
      return { icon: "clipboard", tone: "accent", label: "Review" };
    default:
      return { icon: "doc", tone: "neutral", label: "Activity" };
  }
}

/**
 * Turn an LLM failure category into a sentence the merchant can act on.
 *
 * Mirrors `describe_llm_failure()` on the backend. The two are kept in step
 * deliberately: the backend decides WHAT happened, the frontend only phrases
 * it, so the two can never disagree about the cause.
 *
 * The important distinction is retry advice. Telling someone to "try again"
 * when their daily quota is spent sends them to fail again for no reason.
 *
 * Deliberately names no credential or environment variable. The frontend
 * bundle must never reference a backend-only provider setting — that is what
 * makes a build-time env var of that name tempting later. Configuration detail
 * belongs in the backend log; the merchant gets the cause and the next step.
 */
export function llmFailureMessage(category: string): string {
  switch (category) {
    case "quota_exhausted":
      return "The AI provider's daily token quota is exhausted. Retrying now will not help - wait for the quota to reset.";
    case "rate_limited":
      return "The AI provider is rate limiting this workspace. Try again in a few seconds.";
    case "auth":
      return "The AI provider rejected this workspace's stored credential. Ask an administrator to check the provider credential.";
    case "model_unavailable":
      return "The configured AI model is unavailable or not entitled for this workspace. Ask an administrator to check the configured model.";
    case "invalid_request":
      return "The AI provider rejected the request as malformed. This is a configuration or model-capability problem, not a quota one.";
    case "timeout":
      return "The AI provider did not respond in time. Try again.";
    case "transient":
      return "The AI provider is temporarily unavailable. Try again shortly.";
    default:
      return "The AI provider returned an unexpected error. Try again.";
  }
}

/** The activity row's secondary line: real detail, or the real status. */
export function designerActivityDetail(item: DesignerActivityEntry): string {
  const detail = item.detail?.trim();
  // The backend reports LLM failures as a stable machine code. Show the
  // merchant what it means and whether retrying helps, not the raw token.
  const llmFailure = detail?.match(
    /^(?:brief_generation_failed|llm_not_configured):([a-z_]+)$/,
  );
  if (llmFailure) {
    return llmFailureMessage(llmFailure[1]);
  }
  if (detail) return detail;
  if (item.status) return reviewLabel(item.status);
  return item.kind.replace(/_/g, " ");
}

/* ── Image-generation UX state ───────────────────────────────────────── */

export type GeneratePhase =
  | "unavailable"        // provider not configured / flag off
  | "no_asset"           // nothing to generate from yet
  | "ready"              // ready to submit
  | "submitting"         // request in flight
  | "success"
  | "failed";

export interface GenerateAvailability {
  phase: GeneratePhase;
  /** Whether the submit control is enabled. */
  canSubmit: boolean;
  /** Short, honest label for the control. */
  label: string;
  /** Sentence shown to the merchant. Never a technical code. */
  message: string;
  tone: "muted" | "ready" | "busy" | "ok" | "bad";
}

/**
 * Decide what the Generate control should say and whether it may be pressed.
 *
 * HONESTY RULES
 * -------------
 *  * `success` is only ever produced from a REAL `completed` response that
 *    carries a stored asset reference. Nothing else may set it.
 *  * A provider that is configured but switched off is `unavailable`, never
 *    "ready" — the button must not look usable when it cannot work.
 *  * While a request is in flight the control is disabled, so a double-click
 *    cannot create two generations.
 *  * Without an asset there is nothing to generate FROM, and the UI says so
 *    rather than inventing one.
 */
export function generateAvailability(input: {
  imageGeneration: DesignerImageGeneration | null | undefined;
  hasAsset: boolean;
  hasPrompt?: boolean;
  submitting: boolean;
  lastResult?: DesignerImageGeneration | null;
}): GenerateAvailability {
  const gen = input.imageGeneration;

  if (input.submitting) {
    return {
      phase: "submitting",
      canSubmit: false,
      label: "Generating…",
      message: "Contacting the image provider. This takes a few seconds.",
      tone: "busy",
    };
  }

  // A failed attempt must be visible, but a retry must still be possible.
  if (
    input.lastResult &&
    input.lastResult.status === "failed" &&
    input.lastResult.reason
  ) {
    return {
      phase: "failed",
      canSubmit: Boolean(gen && gen.status === "available" && input.hasAsset),
      label: "Try again",
      message: input.lastResult.reason,
      tone: "bad",
    };
  }

  if (gen && gen.status === "available") {
    const hasSource = input.hasAsset || Boolean(input.hasPrompt);
    if (!hasSource) {
      return {
        phase: "no_asset",
        canSubmit: false,
        label: "Generate Image",
        message:
          "Image generation needs a design asset or an image description. Run a design request, or enter an image description below.",
        tone: "muted",
      };
    }
    return {
      phase: "ready",
      canSubmit: true,
      label: "Generate Image",
      message: "Renders a real image for the newest design asset using your stored brief.",
      tone: "ready",
    };
  }

  // Not configured. State WHY, using the backend's own reason.
  return {
    phase: "unavailable",
    canSubmit: false,
    label: "Image generation unavailable",
    message:
      gen?.reason ??
      "Image generation is not configured for this workspace.",
    tone: "muted",
  };
}

/** Turn a completed backend response into the success sentence. */
export function generationSuccessMessage(
  result: DesignerImageGeneration,
): string | null {
  if (result.status !== "completed" || !result.rendered_asset_id) return null;
  const dims = result.width && result.height ? `${result.width}×${result.height}` : null;
  return [
    "Image generated and stored",
    dims,
    result.byte_size ? `${Math.round(result.byte_size / 1024)} KB` : null,
    result.model ?? null,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** Map a thrown API error onto an honest, merchant-readable sentence. */
export function generationErrorMessage(e: unknown): string {
  const status = (e as { status?: number })?.status;
  if (status === 401) return "Your session expired. Sign in again to generate images.";
  if (status === 403) return "Your account does not have permission to generate images.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status === 0) return "Could not reach the backend. Check that the API is running.";
  const code = (e as { code?: string })?.code;
  const known: Record<string, string> = {
    PROVIDER_RATE_LIMITED:
      "The image provider is rate limiting this workspace. Try again shortly.",
    PROVIDER_TIMEOUT: "The image provider did not respond in time. Try again.",
    PROVIDER_REJECTED: "The image provider rejected this request.",
    PROVIDER_ERROR: "The image provider returned an error. Try again.",
    IMAGE_TOO_LARGE: "The generated image was larger than this workspace allows.",
  };
  if (code && known[code]) return known[code];
  const msg = (e as Error)?.message;
  return msg && msg.trim() ? msg : "Image generation failed. Try again.";
}

/* ── Status headline ─────────────────────────────────────────────────── */

export interface DesignerStatusCopy {
  headline: string;
  support: string;
}

/**
 * Compose the status panel from REAL state only.
 *
 * `runState` is one of: `none` (no run and no project), `active`, `failed`,
 * `idle`. The agent is never described as active merely because the page
 * loaded — that requires an actual in-flight run.
 */
export function designerStatusCopy(input: {
  registered: boolean;
  agentName: string;
  runState: "none" | "active" | "failed" | "idle";
  modeLabel: string;
  awaitingReview: number;
  latestBrief: { title: string; version: number; reviewStatus: string } | null;
  relative: string;
  runError?: string | null;
}): DesignerStatusCopy {
  const { registered, agentName, runState, modeLabel, awaitingReview, latestBrief, relative } =
    input;

  if (!registered) {
    return {
      headline: "No Designer Agent data is available yet.",
      support: `No agent named "${agentName}" was returned by the backend registry, or the registry could not be read. Until it is, this page shows no runs, metrics or briefs — it will not invent any.`,
    };
  }

  if (runState === "none") {
    return {
      headline: "No design work has run yet.",
      support:
        "Start a design request and the Designer Agent joins the AI Team cycle, researches your brief against real signals and stores its creative concepts for your review.",
    };
  }

  if (runState === "active") {
    return {
      headline: "Your creative work is in progress.",
      support: `The Designer Agent is researching your brief (${modeLabel}). Concepts appear in Latest Design Outputs once stored.`,
    };
  }

  if (runState === "failed") {
    return {
      headline: "The last design run did not finish.",
      support: `Stopped at ${modeLabel}. ${
        input.runError ?? "The run recorded an error."
      }`,
    };
  }

  if (awaitingReview > 0) {
    return {
      headline: `${awaitingReview} brief${awaitingReview === 1 ? "" : "s"} waiting on your review.`,
      support: latestBrief
        ? `Latest brief "${latestBrief.title}" (v${latestBrief.version}) is ${reviewLabel(
            latestBrief.reviewStatus,
          ).toLowerCase()}, stored ${relative}.`
        : "Nothing is executed until you approve it.",
    };
  }

  return {
    headline: "Your creative work is up to date.",
    support: latestBrief
      ? `Latest brief "${latestBrief.title}" (v${latestBrief.version}) is ${reviewLabel(
          latestBrief.reviewStatus,
        ).toLowerCase()}, stored ${relative}.`
      : `Last run ${modeLabel} finished ${relative}.`,
  };
}