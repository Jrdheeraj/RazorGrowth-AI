/**
 * Product Agent service layer for the /product-agent workstation.
 *
 * Two kinds of state live here, kept strictly apart:
 *
 * 1. WORKSPACE FACTS — products, orders, units, revenue. Always derived
 *    from the real tenant-isolated backend APIs (GET /api/products,
 *    GET /api/orders, GET /api/analytics/overview, GET /api/growth-radar)
 *    by the pure helpers below. Never hardcoded, never simulated.
 *
 * 2. AGENT-AUTHORED STATE — status headline, insights, recommendations,
 *    recent work, activity, learning, platform connection status. Requested
 *    from GET /api/product-agi/status (planned backend work). While that
 *    endpoint is absent the workstation renders PREVIEW_PRODUCT_AGENT_STATUS,
 *    which the page labels as preview — sample content is never presented as
 *    live backend output, and integrations are never shown as connected.
 */

import { fetchProductAgentStatus } from "./api";
import type {
  CatalogOrder,
  ProductAgentSource,
  ProductAgentStatusResponse,
  ProductResponse,
} from "../types/api";

/* ── Derived product metrics ────────────────────────────────────────────── */

/** Below this stock level a product is reported as a stockout risk. */
export const LOW_STOCK_THRESHOLD = 10;

/** Statuses whose order lines count as real, fulfilled demand. */
const SETTLED_ORDER_STATUSES = new Set([
  "pending",
  "confirmed",
  "paid",
  "shipped",
  "delivered",
]);

/** One comparison half-window for trend maths (15 days each side). */
const HALF_WINDOW_MS = 15 * 24 * 60 * 60 * 1000;

export interface ProductTableRow {
  id: string;
  name: string;
  category: string;
  price: number;
  stock: number;
  units: number;
  revenue: number;
  /** Recent vs prior 15-day unit change; null when there is no baseline. */
  trendPct: number | null;
  hasContent: boolean;
}

export interface CatalogTotals {
  units: number;
  revenue: number;
  unitsDelta: number | null;
  revenueDelta: number | null;
  settledOrders: number;
}

function pct(change: number, base: number): number {
  if (base <= 0) return 0;
  return Math.round((change / base) * 100);
}

function bucketOf(iso: string, now: number): "recent" | "prior" | null {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  if (t > now - HALF_WINDOW_MS) return "recent";
  if (t > now - 2 * HALF_WINDOW_MS) return "prior";
  return null;
}

/**
 * Per-product units, revenue and unit trend, joined to the catalog rows.
 * Cancelled/refunded orders are excluded so the numbers describe demand.
 */
export function productTableRows(
  products: ProductResponse[],
  orders: CatalogOrder[],
): ProductTableRow[] {
  const now = Date.now();
  const agg = new Map<
    string,
    { units: number; revenue: number; recent: number; prior: number }
  >();

  for (const order of orders) {
    if (!SETTLED_ORDER_STATUSES.has(order.status)) continue;
    const bucket = bucketOf(order.created_at, now);
    for (const item of order.items) {
      const row =
        agg.get(item.product_id) ??
        { units: 0, revenue: 0, recent: 0, prior: 0 };
      const line = item.quantity * item.unit_price;
      row.units += item.quantity;
      row.revenue += line;
      if (bucket === "recent") row.recent += item.quantity;
      else if (bucket === "prior") row.prior += item.quantity;
      agg.set(item.product_id, row);
    }
  }

  return products
    .map((p) => {
      const a = agg.get(p.id) ?? { units: 0, revenue: 0, recent: 0, prior: 0 };
      return {
        id: p.id,
        name: p.name,
        category: p.category,
        price: p.price,
        stock: p.stock_quantity,
        units: a.units,
        revenue: a.revenue,
        trendPct: a.prior > 0 ? pct(a.recent - a.prior, a.prior) : null,
        hasContent: Boolean(p.description && p.description.trim().length > 0),
      };
    })
    .sort(
      (a, b) =>
        b.revenue - a.revenue || b.units - a.units || a.name.localeCompare(b.name),
    );
}

/** Catalog-wide units / revenue plus recent-vs-prior deltas from real orders. */
export function catalogTotals(orders: CatalogOrder[]): CatalogTotals {
  const now = Date.now();
  const t: CatalogTotals = {
    units: 0,
    revenue: 0,
    unitsDelta: null,
    revenueDelta: null,
    settledOrders: 0,
  };
  let recentUnits = 0;
  let priorUnits = 0;
  let recentRevenue = 0;
  let priorRevenue = 0;

  for (const order of orders) {
    if (!SETTLED_ORDER_STATUSES.has(order.status)) continue;
    t.settledOrders += 1;
    const bucket = bucketOf(order.created_at, now);
    for (const item of order.items) {
      const line = item.quantity * item.unit_price;
      t.units += item.quantity;
      t.revenue += line;
      if (bucket === "recent") {
        recentUnits += item.quantity;
        recentRevenue += line;
      } else if (bucket === "prior") {
        priorUnits += item.quantity;
        priorRevenue += line;
      }
    }
  }

  t.unitsDelta = priorUnits > 0 ? pct(recentUnits - priorUnits, priorUnits) : null;
  t.revenueDelta =
    priorRevenue > 0 ? pct(recentRevenue - priorRevenue, priorRevenue) : null;
  return t;
}

/* ── Formatting ─────────────────────────────────────────────────────────── */

export function rupees(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

/** Cell delta label: a real percentage when known, "→ live" when merely current. */
export function deltaLabel(v: number | null | undefined, sample = false): string {
  if (sample) return "sample";
  if (v === null || v === undefined || Number.isNaN(v)) return "→ live";
  const r = Math.round(v);
  if (r > 0) return `↑ ${r}%`;
  if (r < 0) return `↓ ${Math.abs(r)}%`;
  return "→ 0%";
}

/* ── Agent-authored state ───────────────────────────────────────────────── */

/**
 * Sample agent state for the workstation, built from the exact
 * ProductAgentStatusResponse contract so a live response drops in unchanged.
 * Timestamps are relative to the call so "Just now" reads honestly.
 */
export function previewProductAgentStatus(): ProductAgentStatusResponse {
  const ago = (minutes: number) =>
    new Date(Date.now() - minutes * 60 * 1000).toISOString();

  return {
    headline:
      "Found 3 product opportunities that could increase revenue by ₹12,450/month.",
    support:
      "I've analyzed your product catalog, sales data, customer behavior, and inventory. Review the insights and approve the recommended actions.",
    status_label: "Working on your products",
    needs_approval: true,
    step_index: 5,
    insights: [
      { id: "top_sellers", icon: "chart", value: "2 best-selling products", detail: "60% of total revenue" },
      { id: "low_stock", icon: "alert", value: "5 products with low inventory", detail: "Risk of stockout in the next 14 days" },
      { id: "thin_content", icon: "doc", value: "4 products need better content", detail: "Missing images, descriptions, or SEO" },
      { id: "cross_sell", icon: "search-check", value: "3 cross-sell opportunities", detail: "Frequently bought together" },
      { id: "opportunities", icon: "git-branch", value: "3 product opportunities", detail: "Combined potential: ₹12,450/month" },
      { id: "pricing", icon: "target", value: "2 pricing opportunities", detail: "Price tiers to review against top sellers" },
    ],
    recommendations: [
      {
        id: "content",
        label: "Optimize product content",
        text: "Improve descriptions, images, and SEO for 4 underperforming products",
        potential: "₹4,200/month",
        confidence: "High confidence",
      },
      {
        id: "cross_sell",
        label: "Create cross-sell bundles",
        text: "Bundle the top 2 products with 3 frequently bought-together items",
        potential: "₹5,600/month",
        confidence: "High confidence",
      },
      {
        id: "pricing",
        label: "Test smarter pricing",
        text: "Run a controlled price test on 2 products with strong demand",
        potential: "₹2,650/month",
        confidence: "Medium confidence",
      },
    ],
    work: [
      { id: "w1", title: "Catalog content audit", state: "completed", meta: "42 products checked · 4 need content" },
      { id: "w2", title: "Inventory risk check", state: "completed", meta: "5 products below reorder level" },
      { id: "w3", title: "Cross-sell analysis", state: "completed", meta: "3 bundle candidates identified" },
      { id: "w4", title: "Product revenue ranking", state: "completed", meta: "Top 2 products = 60% of revenue" },
      { id: "w5", title: "Pricing review", state: "waiting_approval", meta: "Awaiting your approval · nothing runs without it" },
    ],
    activity: [
      { id: "a1", title: "Preparing recommendations", time: ago(0), state: "active" },
      { id: "a2", title: "Checked inventory levels", time: ago(5), state: "completed" },
      { id: "a3", title: "Analyzed product revenue", time: ago(12), state: "completed" },
      { id: "a4", title: "Compared order patterns", time: ago(18), state: "completed" },
      { id: "a5", title: "Read product catalog", time: ago(24), state: "completed" },
    ],
    learning_insight:
      "Cross-sell recommendations show 24% higher conversion when based on real customer purchase history.",
    // Honest by construction: no product-integration API exists yet, so no
    // platform may be reported as connected. The live endpoint can override.
    platforms: [
      { key: "shopify", name: "SHOPIFY", blurb: "Sync products, inventory, and orders", status: "not_connected" },
      { key: "google_merchant", name: "GOOGLE MERCHANT", blurb: "Publish product listings to Google", status: "not_connected" },
      { key: "woocommerce", name: "WOOCOMMERCE", blurb: "Import your WordPress store catalog", status: "not_connected" },
      { key: "razorpay", name: "RAZORPAY", blurb: "Payment and order settlement data", status: "not_connected" },
      { key: "storefront", name: "WEBSITE / STORE", blurb: "Your live storefront as the source of truth", status: "not_connected" },
    ],
  };
}

export interface ProductAgentState {
  source: ProductAgentSource;
  status: ProductAgentStatusResponse;
}

/**
 * Agent-authored state with automatic fallback: live when the backend
 * endpoint answers, labelled preview when it does not exist yet.
 */
export async function fetchProductAgentState(): Promise<ProductAgentState> {
  try {
    const status = await fetchProductAgentStatus();
    if (!status || !Array.isArray(status.insights)) {
      throw new Error("malformed product-agent status");
    }
    return { source: "live", status };
  } catch {
    return { source: "preview", status: previewProductAgentStatus() };
  }
}
