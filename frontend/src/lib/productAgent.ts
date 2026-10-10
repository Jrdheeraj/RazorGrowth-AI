/**
 * Product Agent data layer for the /product-agent workstation.
 *
 * Every value on this page comes from the backend's real read model
 * (GET /api/product-agi/status, /catalog, /platforms and the per-run
 * endpoints). This module does three things and nothing else:
 *
 *   1. fetch the dashboard read model,
 *   2. poll a running run's state so the page stays live,
 *   3. format measured values for display.
 *
 * This page is a MONITOR, not a trigger. The Product Agent is dispatched
 * by the shared AI Team analysis cycle (AI Team → Start Analysis), and
 * every value below is read back from the persisted run. This module
 * therefore exports no "start a run" function at all — see
 * ``agents/product_agi/cycle.py`` for the single dispatch path.
 *
 * It contains NO sample data and NO fallbacks. If the backend cannot be
 * reached the page shows an honest error state — a dashboard that silently
 * falls back to invented numbers would be worse than one that says it
 * cannot reach the agent.
 *
 * Product photography is the one exception: the backend `products` table
 * stores no image column, so the real local photo is resolved from the
 * product's name/SKU through `data/productCatalog` (already used by
 * Checkout). That resolver returns null for a product it genuinely cannot
 * match, and the page then shows "Image unavailable" rather than another
 * product's photo.
 */

import {
  cancelProductAgentRun,
  fetchProductAgentActivity,
  fetchProductAgentFindings,
  fetchProductAgentRecommendations,
  fetchProductAgentRun,
  fetchProductAgentRuns,
  fetchProductAgentStatus,
} from "./api";
import { catalogImageFor } from "../data/productCatalog";
import {
  RUN_POLL_MS,
  approvalLabel,
  isRunTerminal,
} from "./productAgentStatus";
import type {
  ProductAgentActivityResponse,
  ProductAgentFinding,
  ProductAgentProductRow,
  ProductAgentRecommendation,
  ProductAgentRun,
  ProductAgentStatusResponse,
} from "../types/api";

/** Default measurement window. The UI always states the period it shows. */
export const DEFAULT_WINDOW_DAYS = 365;

/**
 * Run statuses that are finished — no further polling needed.
 *
 * The set lives in `productAgentStatus` so the tracker, the footer and the
 * poller share ONE definition. Approval, execution and every intermediate
 * state are NOT terminal: the page must keep refreshing until the run
 * actually reaches a terminal status.
 */
export function isTerminal(status: string | null | undefined): boolean {
  return isRunTerminal(status);
}

/** Poll cadence for a live run (re-exported from the single status model). */
export { RUN_POLL_MS };

/* ── Fetching ──────────────────────────────────────────────────────────── */

export interface ProductAgentLoadState {
  status: ProductAgentStatusResponse | null;
  loading: boolean;
  error: string | null;
  /** True when a run is in flight and the page should keep polling. */
  running: boolean;
}

/**
 * Load the dashboard. One request covers the header, business snapshot,
 * progress stage, insights, recommendations, activity and platforms.
 */
export async function loadProductAgentDashboard(
  windowDays: number = DEFAULT_WINDOW_DAYS,
): Promise<ProductAgentStatusResponse> {
  return fetchProductAgentStatus(windowDays);
}

/**
 * Load the Product Agent run belonging to a shared AI Team analysis cycle.
 *
 * Read-only. Returns null when the cycle produced no Product Agent run for
 * this tenant, so callers can render "not started" rather than inventing
 * state. The dashboard itself uses the /status read model, which already
 * resolves the latest (cycle-linked) run.
 */
export async function loadCycleRun(
  analysisCycleId: string,
): Promise<ProductAgentRun | null> {
  const res = await fetchProductAgentRuns(analysisCycleId);
  return res.runs[0] ?? null;
}

export async function loadRun(runId: string): Promise<ProductAgentRun> {
  return fetchProductAgentRun(runId);
}

export async function loadRunHistory(
  analysisCycleId?: string,
): Promise<ProductAgentRun[]> {
  const res = await fetchProductAgentRuns(analysisCycleId);
  return res.runs;
}

export async function loadFindings(runId: string): Promise<ProductAgentFinding[]> {
  const res = await fetchProductAgentFindings(runId);
  return res.findings;
}

export async function loadRecommendations(
  runId: string,
): Promise<ProductAgentRecommendation[]> {
  const res = await fetchProductAgentRecommendations(runId);
  return res.recommendations;
}

export async function loadActivity(
  runId: string,
  afterSeq = 0,
): Promise<ProductAgentActivityResponse> {
  return fetchProductAgentActivity(runId, afterSeq);
}

export async function cancelRun(runId: string): Promise<ProductAgentRun> {
  return cancelProductAgentRun(runId);
}

/* ── Formatting ────────────────────────────────────────────────────────── */

/** Rendered when the platform reports a value it cannot measure. */
export const UNAVAILABLE = "—";

/** INR amount, or the honest placeholder for a null/unmeasured value. */
export function rupees(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE;
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

export function rupeesExact(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE;
  return `₹${value.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE;
  return value.toLocaleString("en-IN");
}

/** Percent change label; null means there was no baseline to compare with. */
export function delta(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE;
  const r = Math.round(value);
  if (r > 0) return `↑ ${r}%`;
  if (r < 0) return `↓ ${Math.abs(r)}%`;
  return "→ 0%";
}

/** Confidence 0-1 as a whole percentage. */
export function confidence(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return UNAVAILABLE;
  return `${Math.round(value * 100)}%`;
}

/** Impact text: never a number the backend did not compute. */
export function impactText(
  rec: Pick<ProductAgentRecommendation, "expected_impact">,
): string {
  const impact = rec.expected_impact;
  if (!impact || impact.status !== "available" || !impact.text) return UNAVAILABLE;
  return impact.text;
}

/** True when the backend explicitly said an impact is unavailable. */
export function impactUnavailable(
  rec: Pick<ProductAgentRecommendation, "expected_impact">,
): boolean {
  return !rec.expected_impact || rec.expected_impact.status !== "available";
}

/** Short, honest label for a recommendation's approval posture. */
export { approvalLabel };

/** Compact relative timestamp for the activity feed. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return UNAVAILABLE;
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/** Human label for a run duration in seconds. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return UNAVAILABLE;
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

/** Plain-text category label ("desk" -> "Desk"). */
export function categoryLabel(category: string | null | undefined): string {
  if (!category) return "Uncategorised";
  return category.charAt(0).toUpperCase() + category.slice(1);
}

/* ── Business snapshot cells ───────────────────────────────────────────── */

export interface SnapshotCell {
  key: string;
  value: string;
  label: string;
  delta: string;
}

/**
 * The four business-snapshot cells, all derived from the backend's measured
 * catalog summary. When the backend reports `null` the cell shows the
 * unavailable placeholder rather than a fabricated number.
 */
export function snapshotCells(
  status: ProductAgentStatusResponse | null,
): SnapshotCell[] {
  const s = status?.catalog?.summary;
  const metrics = status?.metrics ?? {};
  if (!s) return [];
  return [
    {
      key: "products",
      value: count(s.product_count),
      label: "Total Products",
      delta:
        s.category_count > 0
          ? `Across ${s.category_count} ${s.category_count === 1 ? "category" : "categories"}`
          : "No categories recorded",
    },
    {
      key: "units",
      value: count(s.total_units),
      label: "Units in Stock",
      delta: `${s.in_stock_count} SKU(s) available${
        s.out_of_stock_count ? ` · ${s.out_of_stock_count} out of stock` : ""
      }`,
    },
    {
      key: "categories",
      value: count(s.category_count),
      label: "Categories",
      delta:
        s.categories.length > 0
          ? s.categories.map(categoryLabel).join(" · ")
          : "No categories recorded",
    },
    {
      key: "catalog_value",
      value: rupees(s.catalog_value_inr),
      label: "Catalog Value",
      delta: `Stock value at list price · last ${s.window_days} days of demand data`,
    },
    {
      key: "low_stock",
      value: count(s.low_stock_count),
      label: "Low-Stock Products",
      delta: `At or below ${s.low_stock_threshold} units, or projected to stock out`,
    },
    {
      key: "opportunities",
      value: count(metrics.opportunity_count ?? null),
      label: "Active Opportunities",
      delta:
        metrics.recommendation_count != null
          ? `${metrics.recommendation_count} recommendation(s) prepared`
          : "Deterministic product intelligence",
    },
  ];
}

/* ── Product performance snapshot cells ────────────────────────────────── */

export interface PerfCell {
  key: string;
  value: string;
  label: string;
}

export function performanceCells(
  status: ProductAgentStatusResponse | null,
): PerfCell[] {
  const s = status?.catalog?.summary;
  const health = status?.catalog?.catalog_health;
  const metrics = status?.metrics ?? {};
  if (!s) return [];
  return [
    { key: "catalog", value: `${count(s.product_count)} products`, label: "Catalog" },
    {
      key: "in_stock",
      value: `${s.in_stock_count} products`,
      label: "In stock",
    },
    { key: "units", value: count(s.total_units), label: "Total units" },
    { key: "categories", value: count(s.category_count), label: "Categories" },
    {
      key: "low_stock",
      value: `${s.low_stock_count} flagged`,
      label: "Low stock",
    },
    {
      key: "health",
      value: health?.score != null ? `${health.score}/100` : UNAVAILABLE,
      label: `Catalog health (${health?.grade ?? "unavailable"})`,
    },
    {
      key: "units_sold",
      value: count(metrics.total_units_sold ?? s.total_units_sold),
      label: `Units sold · last ${s.window_days}d`,
    },
    {
      key: "revenue",
      value: rupees(metrics.total_revenue_inr ?? s.total_revenue_inr),
      label: `Revenue · last ${s.window_days}d`,
    },
  ];
}

/* ── Product preview tabs ──────────────────────────────────────────────── */

export type PreviewTab = "Top Products" | "Underperforming" | "Low Stock" | "Opportunities";

export const PREVIEW_TABS: PreviewTab[] = [
  "Top Products",
  "Underperforming",
  "Low Stock",
  "Opportunities",
];

const TAB_SEGMENT: Record<PreviewTab, string> = {
  "Top Products": "top",
  Underperforming: "underperforming",
  "Low Stock": "low_stock",
  Opportunities: "opportunities",
};

export interface PreviewResult {
  rows: ProductAgentProductRow[];
  /** Human explanation shown when the segment is legitimately empty. */
  emptyReason: string;
  /** True when the segment is empty because the backend said data is thin. */
  insufficient: boolean;
}

/**
 * Rows for one preview tab, plus an honest explanation when it is empty.
 * The reason comes from the backend's own segment status, so an
 * "insufficient data" verdict is never rendered as "no problems found".
 */
export function previewRows(
  status: ProductAgentStatusResponse | null,
  tab: PreviewTab,
): PreviewResult {
  const catalog = status?.catalog;
  const segment = TAB_SEGMENT[tab];
  const rows = catalog?.segments?.[segment] ?? [];
  const statusMap = catalog?.segment_status ?? {};

  if (rows.length > 0) return { rows, emptyReason: "", insufficient: false };

  if (tab === "Underperforming") {
    if (statusMap.underperforming !== "available") {
      return {
        rows: [],
        emptyReason: statusMap.underperforming_reason
          ? `Insufficient data — ${statusMap.underperforming_reason}`
          : "Insufficient data to compare product performance yet.",
        insufficient: true,
      };
    }
    return {
      rows: [],
      emptyReason: "No product is below both its category and catalog average.",
      insufficient: false,
    };
  }
  if (tab === "Low Stock") {
    return {
      rows: [],
      emptyReason: `No product is at or below the ${catalog?.summary.low_stock_threshold ?? "—"} unit threshold, or projected to stock out.`,
      insufficient: false,
    };
  }
  if (tab === "Opportunities") {
    if (statusMap.bundles === "insufficient_data" && !rows.length) {
      return { rows: [], emptyReason: "No product opportunity detected.", insufficient: false };
    }
    return { rows: [], emptyReason: "No product opportunity detected.", insufficient: false };
  }
  return {
    rows: [],
    emptyReason: "No product has recorded settled demand in this window.",
    insufficient: true,
  };
}

/** Real photo for a backend product, or null when genuinely unmatched. */
export function productImage(row: Pick<ProductAgentProductRow, "name" | "sku">): string | null {
  return catalogImageFor(row.name, row.sku);
}

/** Two-letter monogram shown behind the photo (and as the fallback). */
export function productInitials(name: string): string {
  const words = name.split(" ").filter(Boolean);
  return ((words[0]?.[0] ?? "") + (words[1]?.[0] ?? "")).toUpperCase();
}

/** Human label for a product performance status token. */
export function statusLabel(status: string | null | undefined): string {
  switch (status) {
    case "strong":
      return "Strong";
    case "steady":
      return "Steady";
    case "underperforming":
      return "Underperforming";
    case "no_demand":
      return "No demand";
    default:
      return "Unavailable";
  }
}