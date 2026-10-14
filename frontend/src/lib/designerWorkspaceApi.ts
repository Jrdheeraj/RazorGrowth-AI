/**
 * Designer Agent workspace loader — the page's single data entry point.
 *
 * This module contains NO fetch logic. Every call goes through `api.ts`'s
 * private `request<T>()`, so auth, base URL, 401 token-drop and error
 * normalisation are exactly the platform's, not a second implementation.
 *
 * TWO DATA SOURCES, DELIBERATELY BOTH KEPT
 * -----------------------------------------
 * `snapshot`  derives from `agent_runs` — the agent's genuine execution
 *             record, including real latency and real failure status. This is
 *             still the authoritative view of "did the agent actually run".
 * `workspace` comes from the new `/api/designer/*` endpoints — real projects,
 *             briefs, versioned assets and derived metrics.
 *
 * Neither can substitute for the other: a run row says work happened but not
 * what was produced, and a brief says what was produced but not whether the
 * run succeeded.
 *
 * HONESTY CONTRACT
 * ----------------
 * Every section is loaded independently. A failing endpoint yields an empty
 * array plus a `false` in `load`, so the dashboard renders an honest
 * "unavailable" state for that section instead of an empty-looking success or
 * a silently blank page. Nothing here ever synthesises a project, a brief, a
 * metric or a connected tool.
 */
import {
  fetchAgentRuns,
  fetchDesignerActivity,
  fetchDesignerAssets,
  fetchDesignerBriefs,
  fetchDesignerImageGeneration,
  fetchDesignerProjects,
  fetchDesignerStatus,
  fetchRenderedAssets,
} from "./api";
import {
  DESIGNER_AGENT_NAME,
  buildDesignerSnapshot,
  type DesignerRunRowLike,
  type DesignerSnapshot,
} from "./designerAgent";
import type {
  CreativeBrief,
  DesignAsset,
  DesignProject,
  DesignerActivityEntry,
  DesignerImageGeneration,
  DesignerStatus,
  RenderedAsset,
} from "../types/api";

/** Per-section availability, so the UI can distinguish "empty" from "broken". */
export interface DesignerLoadState {
  runs: boolean;
  status: boolean;
  projects: boolean;
  briefs: boolean;
  assets: boolean;
  activity: boolean;
  images: boolean;
}

export interface DesignerWorkspace {
  /** Agent execution history (real run rows + debate findings). */
  snapshot: DesignerSnapshot;
  /** Real workspace state, or null when the endpoint was unavailable. */
  status: DesignerStatus | null;
  projects: DesignProject[];
  briefs: CreativeBrief[];
  assets: DesignAsset[];
  activity: DesignerActivityEntry[];
  /** Real provider availability. Null when the endpoint was unavailable. */
  imageGeneration: DesignerImageGeneration | null;
  /** Real stored images, newest first. Empty when none exist. */
  renderedAssets: RenderedAsset[];
  /** Bytes stored today per workspace — shown so the quota is visible. */
  imageUsageToday: { images: number; bytes: number } | null;
  load: DesignerLoadState;
  /** True when at least one section failed to load. */
  partial: boolean;
  /** The first real error message, for a retry affordance. */
  error: string | null;
}

/**
 * Load the whole Designer workspace.
 *
 * Never rejects: a total failure resolves to a workspace with everything empty,
 * `partial: true` and a message, which the page renders as an honest error
 * state rather than an empty dashboard.
 */
export async function loadDesignerWorkspace(): Promise<DesignerWorkspace> {
  const load: DesignerLoadState = {
    runs: false,
    status: false,
    projects: false,
    briefs: false,
    assets: false,
    activity: false,
    images: false,
  };

  let status: DesignerStatus | null = null;
  let projects: DesignProject[] = [];
  let briefs: CreativeBrief[] = [];
  let assets: DesignAsset[] = [];
  let activity: DesignerActivityEntry[] = [];
  let imageGeneration: DesignerImageGeneration | null = null;
  let renderedAssets: RenderedAsset[] = [];
  let imageUsageToday: { images: number; bytes: number } | null = null;
  let error: string | null = null;

  // ── 1. The agent's real run history ──────────────────────────────────
  let snapshot = buildDesignerSnapshot({});
  try {
    const runsResp = await fetchAgentRuns(200);
    load.runs = true;
    snapshot = buildDesignerSnapshot({
      registryEntry: null,
      runRows: (runsResp.runs ?? []).filter(
        (r) => r.agent_name === DESIGNER_AGENT_NAME,
      ) as DesignerRunRowLike[],
    });
  } catch (e) {
    error ??= describeError(e);
  }

  // ── 2. Registry status, capabilities, integrations, metrics ──────────
  try {
    status = await fetchDesignerStatus();
    load.status = true;
  } catch (e) {
    error ??= describeError(e);
  }

  // ── 3. Projects ─────────────────────────────────────────────────────
  try {
    projects = (await fetchDesignerProjects({ limit: 50 })).projects ?? [];
    load.projects = true;
  } catch (e) {
    error ??= describeError(e);
  }

  // ── 4. Briefs (newest first, so "current" work leads) ────────────────
  try {
    briefs = (await fetchDesignerBriefs({ limit: 50 })).briefs ?? [];
    load.briefs = true;
  } catch (e) {
    error ??= describeError(e);
  }

  // ── 5. Versioned assets ─────────────────────────────────────────────
  try {
    assets = (await fetchDesignerAssets({ limit: 50 })).assets ?? [];
    load.assets = true;
  } catch (e) {
    error ??= describeError(e);
  }

  // ── 6. Genuine persisted activity ────────────────────────────────────
  try {
    activity = (await fetchDesignerActivity(20)).items ?? [];
    load.activity = true;
  } catch (e) {
    error ??= describeError(e);
  }

  // ── 7. Real image-generation state and real stored images ───────────
  // Both are loaded independently. A failure here says "unavailable" rather
  // than implying an image exists or that the provider is ready.
  try {
    imageGeneration = await fetchDesignerImageGeneration();
    load.images = true;
  } catch (e) {
    error ??= describeError(e);
  }
  try {
    const rendered = await fetchRenderedAssets({ limit: 50 });
    renderedAssets = rendered.assets ?? [];
    imageUsageToday = rendered.usage_today ?? null;
    load.images = true;
  } catch (e) {
    error ??= describeError(e);
  }

  // The registry facts come from `/api/designer/status`, which reads the LIVE
  // agent registry server-side. That is authoritative for registration and for
  // the declared tool list, and it replaces the run-row-derived snapshot for
  // both. Without this the page would render the agent as "not registered" and
  // keep the request form disabled even though the agent IS registered.
  if (status) {
    snapshot = {
      ...snapshot,
      registered: status.agent_registered,
      registryDescription: status.agent_description ?? snapshot.registryDescription,
      tools: status.capabilities.length
        ? status.capabilities.map((c) => c.key)
        : snapshot.tools,
    };
  }

  const partial = Object.values(load).some((ok) => !ok);
  return {
    snapshot,
    status,
    projects,
    briefs,
    assets,
    activity,
    imageGeneration,
    renderedAssets,
    imageUsageToday,
    load,
    partial,
    error,
  };
}

/** Turn a thrown ApiError into a short, honest, user-facing message. */
function describeError(e: unknown): string {
  const status = (e as { status?: number })?.status;
  if (status === 401) return "Sign in to load your Designer Agent workspace.";
  if (status === 403) return "Your account has no workspace access yet.";
  if (status === 0) return "The backend is unreachable. Check that the API is running.";
  const message = (e as Error)?.message;
  return message && message.trim() ? message : "Failed to load the Designer workspace.";
}