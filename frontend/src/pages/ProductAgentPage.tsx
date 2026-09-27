/**
 * /product-agent — Product Agent workstation (FRONTEND-ONLY Phase 1).
 *
 * A clean implementation built from scratch. No backend calls, no database,
 * no API endpoints, no autonomous execution. All values below are static
 * frontend demo data, typed so real API responses can drop in later:
 *
 *   ProductAgentSnapshot / ProductOpportunity / ProductRecommendation /
 *   ProductActivityItem / ProductChannel / ProductMetric / ProductRow
 *
 * Visual system: same illustrated RazorGrowth world as the Marketing Agent
 * (GlobalEnvironment fixed behind everything) + WindowPanel browser windows.
 * Warm cream paper, thin dark borders, terracotta primary actions, dark
 * green for growth/completion. No glassmorphism, no gradients, no neon.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { WindowPanel } from "../components/WindowPanel";
import { Button, ButtonLink } from "../components/Button";
import { GlobalEnvironment } from "../features/public/Environment/GlobalEnvironment";
import "./ProductAgentPage.css";

/* ── Typed demo-data contracts (backend-ready shapes) ─────────────────── */

export interface ProductMetric {
  value: string;
  label: string;
  delta: string;
}

export interface ProductWorkflowStep {
  top: string;
  bottom: string;
}

export interface ProductInsight {
  icon: UiIconName;
  value: string;
  detail: string;
}

export interface ProductRecommendation {
  index: string;
  title: string;
  text: string;
  potential: string;
  confidence: string;
}

export interface ProductRow {
  name: string;
  initials: string;
  color: string;
  revenue: string;
  units: number;
  trend: string;
  up: boolean;
}

export interface ProductChannel {
  key: string;
  name: string;
  status: "connected" | "not_connected";
  blurb: string;
  meta: string;
  action: "Manage" | "Connect";
}

export interface ProductWorkItem {
  title: string;
  detail: string;
  time: string;
  waiting?: boolean;
}

export interface ProductActivityItem {
  title: string;
  time: string;
  active?: boolean;
}

export interface ProductAgentSnapshot {
  metrics: ProductMetric[];
  insights: ProductInsight[];
  recommendations: ProductRecommendation[];
  channels: ProductChannel[];
  work: ProductWorkItem[];
  activity: ProductActivityItem[];
}

/* ── Static frontend demo data (no API) ───────────────────────────────── */

const WORKFLOW_STEPS: ProductWorkflowStep[] = [
  { top: "Understand", bottom: "catalog" },
  { top: "Analyze", bottom: "performance" },
  { top: "Find", bottom: "opportunities" },
  { top: "Research", bottom: "& analyze" },
  { top: "Prepare", bottom: "recommendation" },
  { top: "Safety", bottom: "check" },
  { top: "Waiting for", bottom: "approval" },
  { top: "Execute", bottom: "& measure" },
];

/** Zero-based index of the current workflow step: 6 = "Waiting for approval". */
const CURRENT_STEP = 6;

const SNAPSHOT: ProductAgentSnapshot = {
  metrics: [
    { value: "42", label: "Total Products", delta: "↑ 18% vs previous period" },
    { value: "96", label: "Total Customers", delta: "↑ 12% vs previous period" },
    { value: "184", label: "Units Sold", delta: "↑ 24% vs previous period" },
    { value: "₹78,420", label: "Product Revenue", delta: "↑ 28% vs previous period" },
  ],
  insights: [
    { icon: "chart", value: "2 best selling products", detail: "60% of total revenue" },
    { icon: "alert", value: "3 underperforming products", detail: "Sales dropped >30%" },
    { icon: "box", value: "5 products with low inventory", detail: "Risk of stockout" },
    { icon: "doc", value: "4 products need better content", detail: "Missing images, descriptions or SEO" },
    { icon: "branch", value: "3 cross-sell opportunities", detail: "Frequently bought together" },
    { icon: "target", value: "2 pricing opportunities", detail: "Potential revenue increase: ₹12,450/month" },
  ],
  recommendations: [
    {
      index: "RECOMMENDATION 1",
      title: "Optimize product content",
      text: "Improve title, description and images for 4 underperforming products.",
      potential: "₹4,800/mo",
      confidence: "82% confidence",
    },
    {
      index: "RECOMMENDATION 2",
      title: "Create product bundle",
      text: "Bundle 2 frequently bought products.",
      potential: "₹5,200/mo",
      confidence: "71% confidence",
    },
    {
      index: "RECOMMENDATION 3",
      title: "Adjust product pricing",
      text: "Increase price for 3 high-demand products with low price sensitivity.",
      potential: "₹2,450/mo",
      confidence: "68% confidence",
    },
  ],
  channels: [
    { key: "shopify", name: "Shopify", status: "connected", blurb: "Catalog synced", meta: "42 products", action: "Manage" },
    { key: "google", name: "Google Merchant", status: "connected", blurb: "Products submitted", meta: "38 active", action: "Manage" },
    { key: "woo", name: "WooCommerce", status: "not_connected", blurb: "Not connected", meta: "Connect to sync products", action: "Connect" },
    { key: "razorpay", name: "Razorpay", status: "connected", blurb: "Sales data available", meta: "Payments linked", action: "Manage" },
    { key: "store", name: "Website / Store", status: "connected", blurb: "Product data available", meta: "Storefront linked", action: "Manage" },
  ],
  work: [
    { title: "Product content analysis", detail: "Analyzed 42 products", time: "Just now" },
    { title: "Found 3 opportunities", detail: "₹12,450/month potential", time: "5 min ago" },
    { title: "Catalog health check", detail: "4 products need attention", time: "12 min ago" },
    { title: "Pricing analysis", detail: "Completed", time: "25 min ago" },
    { title: "Inventory check", detail: "5 low stock products", time: "32 min ago" },
  ],
  activity: [
    { title: "Preparing recommendations", time: "Now", active: true },
    { title: "Analyzed product performance", time: "5 min ago" },
    { title: "Found growth opportunities", time: "8 min ago" },
    { title: "Generated content suggestions", time: "12 min ago" },
    { title: "Analyzed pricing opportunities", time: "18 min ago" },
    { title: "Checked Google Merchant status", time: "25 min ago" },
  ],
};

const TOP_PRODUCTS: ProductRow[] = [
  { name: "Premium Black T-Shirt", initials: "PT", color: "#2a1810", revenue: "₹28,450", units: 62, trend: "↑ +24%", up: true },
  { name: "Classic White Sneakers", initials: "WS", color: "#a94f38", revenue: "₹18,220", units: 38, trend: "↑ +18%", up: true },
  { name: "Leather Wallet", initials: "LW", color: "#3e7d58", revenue: "₹12,980", units: 26, trend: "↑ +12%", up: true },
  { name: "Urban Backpack", initials: "UB", color: "#8a6f5c", revenue: "₹9,450", units: 21, trend: "↓ -8%", up: false },
  { name: "Aviator Sunglasses", initials: "AS", color: "#c85f43", revenue: "₹7,320", units: 18, trend: "↓ -15%", up: false },
];

const UNDERPERFORMING: ProductRow[] = [
  { name: "Urban Backpack", initials: "UB", color: "#8a6f5c", revenue: "₹9,450", units: 21, trend: "↓ -8%", up: false },
  { name: "Aviator Sunglasses", initials: "AS", color: "#c85f43", revenue: "₹7,320", units: 18, trend: "↓ -15%", up: false },
  { name: "Canvas Tote Bag", initials: "CT", color: "#8a6f5c", revenue: "₹4,120", units: 12, trend: "↓ -32%", up: false },
];

const LOW_STOCK: ProductRow[] = [
  { name: "Classic White Sneakers", initials: "WS", color: "#a94f38", revenue: "₹18,220", units: 38, trend: "↑ +18%", up: true },
  { name: "Leather Wallet", initials: "LW", color: "#3e7d58", revenue: "₹12,980", units: 26, trend: "↑ +12%", up: true },
  { name: "Urban Backpack", initials: "UB", color: "#8a6f5c", revenue: "₹9,450", units: 21, trend: "↓ -8%", up: false },
];

const OPPORTUNITY_ROWS: ProductRow[] = [
  { name: "Premium Black T-Shirt", initials: "PT", color: "#2a1810", revenue: "₹28,450", units: 62, trend: "↑ +24%", up: true },
  { name: "Classic White Sneakers", initials: "WS", color: "#a94f38", revenue: "₹18,220", units: 38, trend: "↑ +18%", up: true },
  { name: "Leather Wallet", initials: "LW", color: "#3e7d58", revenue: "₹12,980", units: 26, trend: "↑ +12%", up: true },
];

type PreviewTab = "Top Products" | "Underperforming" | "Low Stock" | "Opportunities";

const PREVIEW_TABS: PreviewTab[] = ["Top Products", "Underperforming", "Low Stock", "Opportunities"];

const PREVIEW_ROWS: Record<PreviewTab, ProductRow[]> = {
  "Top Products": TOP_PRODUCTS,
  Underperforming: UNDERPERFORMING,
  "Low Stock": LOW_STOCK,
  Opportunities: OPPORTUNITY_ROWS,
};

/* ── Dashboard UI icons (one stroke family, no new dependency) ────────── */

type UiIconName =
  | "search"
  | "spark"
  | "alert"
  | "bot"
  | "users"
  | "chart"
  | "target"
  | "clock"
  | "check"
  | "box"
  | "doc"
  | "branch";

function UiIcon({ name, size = 20 }: { name: UiIconName; size?: number }) {
  let body: React.ReactNode;
  switch (name) {
    case "search":
      body = (<><circle cx="9" cy="9" r="5.5" /><line x1="13.2" y1="13.2" x2="17" y2="17" /></>);
      break;
    case "spark":
      body = (<path d="M10 2l1.9 5.6 5.6 1.9-5.6 1.9L10 17l-1.9-5.6L2.5 9.5l5.6-1.9z" fill="currentColor" stroke="none" />);
      break;
    case "alert":
      body = (<><path d="M10 2.5L18 16.5H2z" /><line x1="10" y1="7.5" x2="10" y2="11.5" /><circle cx="10" cy="14" r="0.7" fill="currentColor" stroke="none" /></>);
      break;
    case "bot":
      body = (<><rect x="4" y="7" width="12" height="9" rx="2.5" /><line x1="10" y1="7" x2="10" y2="3.5" /><circle cx="10" cy="2.8" r="1" fill="currentColor" stroke="none" /><circle cx="7.5" cy="11" r="1" fill="currentColor" stroke="none" /><circle cx="12.5" cy="11" r="1" fill="currentColor" stroke="none" /><line x1="7.5" y1="13.8" x2="12.5" y2="13.8" /></>);
      break;
    case "users":
      body = (<><circle cx="7" cy="7" r="3" /><path d="M1.8 16.5c.8-2.8 2.8-4.2 5.2-4.2s4.4 1.4 5.2 4.2" /><circle cx="14.2" cy="8" r="2.3" /><path d="M14.8 12.6c1.9.3 3.2 1.5 3.7 3.6" /></>);
      break;
    case "chart":
      body = (<><line x1="3" y1="3" x2="3" y2="17" /><line x1="3" y1="17" x2="17" y2="17" /><line x1="7.2" y1="12" x2="7.2" y2="15" strokeWidth={2.2} /><line x1="11.2" y1="8.5" x2="11.2" y2="15" strokeWidth={2.2} /><line x1="15.2" y1="5.5" x2="15.2" y2="15" strokeWidth={2.2} /></>);
      break;
    case "target":
      body = (<><circle cx="10" cy="10" r="7" /><circle cx="10" cy="10" r="3.5" /><circle cx="10" cy="10" r="0.8" fill="currentColor" stroke="none" /></>);
      break;
    case "clock":
      body = (<><circle cx="10" cy="10" r="7" /><path d="M10 6.5V10l2.5 1.5" /></>);
      break;
    case "box":
      body = (<><path d="M10 2.5l7 3.5v8l-7 3.5-7-3.5v-8z" /><path d="M3 6l7 3.5L17 6" /><line x1="10" y1="9.5" x2="10" y2="17.5" /></>);
      break;
    case "branch":
      body = (<><line x1="5" y1="2.5" x2="5" y2="12.5" /><circle cx="15" cy="5" r="2.5" /><circle cx="5" cy="15" r="2.5" /><path d="M15 7.5a7.5 7.5 0 0 1-7.5 7.5" /></>);
      break;
    case "doc":
      body = (<><path d="M5 2.5h6.5L15 6v11.5H5z" /><path d="M11.5 2.5V6H15" /><line x1="7.5" y1="10.5" x2="12.5" y2="10.5" /><line x1="7.5" y1="13.5" x2="12.5" y2="13.5" /></>);
      break;
    case "check":
    default:
      body = (<path d="M3.5 10.5l4 4L16.5 5.5" strokeWidth={2.2} />);
      break;
  }
  return (
    <svg
      className="prod-uiicon"
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {body}
    </svg>
  );
}

/* ── Product office illustration (flat RazorGrowth language) ──────────── */

function ProductOfficeArt() {
  return (
    <svg
      className="prod-art"
      viewBox="0 0 520 360"
      role="img"
      aria-label="Illustrated Product Agent workspace analyzing a catalog"
    >
      {/* ground */}
      <rect x="24" y="300" width="472" height="26" fill="#EBD9AE" stroke="#2a1810" strokeWidth="3" />
      {/* main shop block */}
      <rect x="70" y="96" width="330" height="208" fill="#FFF3DF" stroke="#2a1810" strokeWidth="3" />
      {/* sign band */}
      <rect x="70" y="96" width="330" height="40" fill="#21130e" stroke="#2a1810" strokeWidth="3" />
      <text x="235" y="122" textAnchor="middle" fontFamily="'IBM Plex Mono',monospace" fontSize="17" letterSpacing="3" fill="#F7EBD7">
        PRODUCT AGENT
      </text>
      {/* awning */}
      <g stroke="#2a1810" strokeWidth="3">
        <rect x="70" y="136" width="47" height="26" fill="#3E7D58" />
        <rect x="117" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="164" y="136" width="47" height="26" fill="#3E7D58" />
        <rect x="211" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="258" y="136" width="47" height="26" fill="#3E7D58" />
        <rect x="305" y="136" width="47" height="26" fill="#FFF3DF" />
        <rect x="352" y="136" width="48" height="26" fill="#3E7D58" />
      </g>
      {/* left: product shelves */}
      <rect x="96" y="182" width="130" height="102" fill="#F5E6CF" stroke="#2a1810" strokeWidth="3" />
      <line x1="96" y1="210" x2="226" y2="210" stroke="#2a1810" strokeWidth="2.5" />
      <line x1="96" y1="238" x2="226" y2="238" stroke="#2a1810" strokeWidth="2.5" />
      {/* boxes on shelves */}
      <rect x="104" y="188" width="26" height="20" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="134" y="192" width="22" height="16" fill="#7BA57F" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="160" y="186" width="30" height="22" fill="#E8936B" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="104" y="216" width="30" height="20" fill="#70B88A" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="138" y="220" width="24" height="16" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      <rect x="166" y="214" width="28" height="22" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
      {/* robot analyst head */}
      <rect x="106" y="248" width="40" height="28" rx="5" fill="#EBD9AE" stroke="#2a1810" strokeWidth="2.5" />
      <circle cx="118" cy="260" r="3.5" fill="#2a1810" />
      <circle cx="134" cy="260" r="3.5" fill="#2a1810" />
      <rect x="119" y="267" width="13" height="3" fill="#2a1810" />
      {/* right: analytics board */}
      <rect x="242" y="182" width="132" height="122" fill="#F0BC92" stroke="#2a1810" strokeWidth="3" />
      <rect x="252" y="194" width="112" height="64" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      {/* bars */}
      <rect x="262" y="232" width="12" height="18" fill="#3E7D58" />
      <rect x="280" y="222" width="12" height="28" fill="#3E7D58" />
      <rect x="298" y="212" width="12" height="38" fill="#D97757" />
      <rect x="316" y="226" width="12" height="24" fill="#3E7D58" />
      <polyline points="262,228 286,218 304,222 328,206" fill="none" stroke="#2a1810" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="328" cy="206" r="4" fill="#D97757" stroke="#2a1810" strokeWidth="2" />
      {/* price tag */}
      <rect x="252" y="266" width="112" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
      <text x="308" y="284" textAnchor="middle" fontFamily="'IBM Plex Mono',monospace" fontSize="13" letterSpacing="1" fill="#2a1810">₹12,450/mo</text>
      {/* side tree */}
      <rect x="428" y="230" width="16" height="74" fill="#8C7A66" stroke="#2a1810" strokeWidth="3" />
      <circle cx="436" cy="200" r="34" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      <circle cx="414" cy="216" r="18" fill="#7BA57F" stroke="#2a1810" strokeWidth="3" />
      {/* wall tags */}
      <g fontFamily="'IBM Plex Mono',monospace" fontSize="12" letterSpacing="2">
        <rect x="34" y="150" width="86" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="77" y="167" textAnchor="middle" fill="#2a1810">CATALOG</text>
        <rect x="404" y="120" width="102" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="455" y="137" textAnchor="middle" fill="#2a1810">ANALYTICS</text>
        <rect x="404" y="262" width="86" height="26" fill="#D97757" stroke="#2a1810" strokeWidth="2.5" />
        <text x="447" y="279" textAnchor="middle" fill="#21130e">PRICING</text>
        <rect x="34" y="230" width="88" height="26" fill="#FFF3DF" stroke="#2a1810" strokeWidth="2.5" />
        <text x="78" y="247" textAnchor="middle" fill="#2a1810">INVENTORY</text>
      </g>
      {/* sun */}
      <circle cx="466" cy="52" r="24" fill="#E8936B" stroke="#2a1810" strokeWidth="3" />
    </svg>
  );
}

function ChannelGlyph({ channelKey }: { channelKey: string }) {
  const ink = "#2a1810";
  switch (channelKey) {
    case "shopify":
      return (
        <svg className="prod-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Shopify icon">
          <rect x="8" y="8" width="24" height="24" rx="2" fill="#FFF3DF" stroke={ink} strokeWidth="2.8" />
          <path d="M13 15h14l-1.5 9h-11z" fill="none" stroke={ink} strokeWidth="2.4" strokeLinejoin="round" />
          <path d="M15.5 15c0-3 1.2-5 4.5-5 2.6 0 4 1.6 4 3.4" fill="none" stroke="#3E7D58" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case "google":
      return (
        <svg className="prod-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Google Merchant icon">
          <line x1="21.5" y1="7" x2="12" y2="29.5" stroke="#FBBC04" strokeWidth="6.5" strokeLinecap="round" />
          <line x1="21.5" y1="7" x2="29" y2="29.5" stroke="#4285F4" strokeWidth="6.5" strokeLinecap="round" />
          <circle cx="11" cy="30.5" r="4.6" fill="#34A853" />
        </svg>
      );
    case "woo":
      return (
        <svg className="prod-channel__logo" viewBox="0 0 40 40" role="img" aria-label="WooCommerce icon">
          <circle cx="20" cy="20" r="13" fill="none" stroke={ink} strokeWidth="2.8" />
          <path d="M12 14l4 12 4-9 4 9 4-12" fill="none" stroke="#a94f38" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "razorpay":
      return (
        <svg className="prod-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Razorpay icon">
          <rect x="7" y="10" width="26" height="20" rx="2" fill="#0c2451" stroke={ink} strokeWidth="2.8" />
          <path d="M13 15l6 5-6 5" fill="none" stroke="#F7EBD7" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
          <line x1="22" y1="15" x2="27" y2="25" stroke="#70B88A" strokeWidth="2.6" strokeLinecap="round" />
        </svg>
      );
    case "store":
    default:
      return (
        <svg className="prod-channel__logo" viewBox="0 0 40 40" role="img" aria-label="Store icon">
          <path d="M7 15l3-7h20l3 7" fill="none" stroke={ink} strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="9" y="15" width="22" height="16" fill="#FFF3DF" stroke={ink} strokeWidth="2.8" />
          <rect x="17" y="22" width="6" height="9" fill="none" stroke={ink} strokeWidth="2.2" />
        </svg>
      );
  }
}

/* ── Section subcomponents (all presentational, demo data via props) ──── */

function ProductAgentHero() {
  return (
    <WindowPanel title="product.agent" className="prod-hero">
      <div className="prod-hero__inner">
        <div className="prod-hero__copy">
          <p className="prod-eyebrow">PRODUCT AGENT · FRONTEND PREVIEW · DEMO DATA</p>
          <h1 className="prod-hero__title">
            Your autonomous
            <br />
            <span className="prod-hero__accent">product growth employee.</span>
          </h1>
          <p className="prod-hero__sub">
            Analyzes your products, finds growth opportunities, optimizes catalog,
            recommends pricing, and prepares actions — using real business data.
          </p>
        </div>
        <div className="prod-hero__art">
          <ProductOfficeArt />
          <p className="prod-hero__caption">
            <span className="prod-hero__tick" aria-hidden="true" />
            <span>
              Better products
              <br />
              happier customers
              <br />
              higher revenue
            </span>
          </p>
        </div>
      </div>
    </WindowPanel>
  );
}

function AgentStatusCard({ onReview, onDetails }: { onReview: () => void; onDetails: () => void }) {
  return (
    <WindowPanel title="agent.status" className="prod-span-status">
      <div className="prod-status__top">
        <span className="prod-live">
          <UiIcon name="bot" size={22} />
          <span className="prod-live__dot" aria-hidden="true" />
          Working on your products
        </span>
        <span className="prod-status__meta">Frontend preview · demo data</span>
      </div>
      <div className="prod-status__main">
        <div>
          <h2 className="prod-status__headline">
            Found 3 product opportunities
            <br />
            that could increase revenue by
            <br />
            ₹12,450/month.
          </h2>
          <p className="prod-status__support">
            I&apos;ve analyzed your product catalog, sales data, customer behavior
            and inventory. Review the insights and approve the recommended actions.
          </p>
          <div className="prod-status__actions">
            <Button variant="primary" mono onClick={onReview}>
              Review Opportunities →
            </Button>
            <Button variant="secondary" mono onClick={onDetails}>
              View Details
            </Button>
          </div>
        </div>
        <div className="prod-status__check">
          <p className="prod-status__checktitle">
            ANALYSIS
            <br />
            COMPLETE
          </p>
          <ul className="prod-checklist">
            <li className="is-done"><span aria-hidden="true">✓</span> Catalog scanned</li>
            <li className="is-done"><span aria-hidden="true">✓</span> Sales data analyzed</li>
            <li className="is-done"><span aria-hidden="true">✓</span> Opportunities found</li>
            <li className="is-done"><span aria-hidden="true">✓</span> Actions prepared</li>
            <li className="is-now"><span aria-hidden="true">○</span> Waiting for approval</li>
          </ul>
        </div>
      </div>
    </WindowPanel>
  );
}

function BusinessSnapshot({ metrics }: { metrics: ProductMetric[] }) {
  const icons: UiIconName[] = ["box", "users", "chart", "target"];
  return (
    <WindowPanel title="business.snapshot" className="prod-span-snapshot">
      <div className="prod-snap">
        {metrics.map((m, i) => (
          <div key={m.label} className="prod-snap__cell">
            <span className="prod-snap__value">
              <UiIcon name={icons[i % icons.length]} size={18} />
              {m.value}
            </span>
            <span className="prod-snap__label">{m.label}</span>
            <span className="prod-snap__delta">{m.delta}</span>
          </div>
        ))}
      </div>
      <p className="prod-panel__sub">Frontend demo values — live catalog data arrives in a later phase.</p>
    </WindowPanel>
  );
}

function AgentProgress() {
  return (
    <WindowPanel title="agent.progress" className="prod-span-full">
      <ol className="prod-steps" aria-label="Product agent progress">
        {WORKFLOW_STEPS.map((s, i) => (
          <li
            key={`${s.top}-${s.bottom}`}
            className={`prod-steps__step${i < CURRENT_STEP ? " is-done" : ""}${i === CURRENT_STEP ? " is-now" : ""}`}
            aria-current={i === CURRENT_STEP ? "step" : undefined}
          >
            <span className="prod-steps__node" aria-hidden="true">
              {i < CURRENT_STEP ? (
                <svg viewBox="0 0 16 16" width="17" height="17" aria-hidden="true">
                  <path d="M3 8.5l3.5 3.5L13 4.5" fill="none" stroke="#FFF3DF" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                i + 1
              )}
            </span>
            <span className="prod-steps__words">
              <span>{s.top}</span>
              {s.bottom && <span>{s.bottom}</span>}
            </span>
          </li>
        ))}
      </ol>
      <p className="prod-steps__caption">
        Current stage: {WORKFLOW_STEPS[CURRENT_STEP].top} {WORKFLOW_STEPS[CURRENT_STEP].bottom} (frontend preview)
      </p>
    </WindowPanel>
  );
}

function ApprovalRequired({ onReview, onApprove }: { onReview: () => void; onApprove: () => void }) {
  return (
    <div className="prod-span-approval">
      <WindowPanel title="approval.required" className="prod-approval prod-approval--hot">
        <div className="prod-approval__head">
          <span className="prod-approval__icon" aria-hidden="true">
            <UiIcon name="alert" size={15} />
          </span>
          <h2 className="prod-approval__title">Your approval needed</h2>
        </div>
        <p className="prod-approval__campaign">3 product optimization actions are ready.</p>
        <p className="prod-approval__meta">3 opportunities · ₹12,450/month potential impact · Catalog updates</p>
        <p className="prod-approval__note">
          AI investigates. AI recommends. You approve. Nothing executes without your approval.
        </p>
        <div className="prod-approval__actions">
          <Button variant="primary" mono onClick={onReview}>
            Review Actions →
          </Button>
          <Button variant="secondary" mono onClick={onApprove}>
            Approve &amp; Continue
          </Button>
        </div>
      </WindowPanel>
    </div>
  );
}

function ProductInsights({ insights }: { insights: ProductInsight[] }) {
  return (
    <WindowPanel title="what.i.found" className="prod-span-third">
      <div className="prod-sec__head">
        <span className="prod-sec__icon" aria-hidden="true"><UiIcon name="search" size={15} /></span>
        <div>
          <h2 className="prod-sec__title">Top Product Insights</h2>
          <p className="prod-panel__sub">Key findings from your live business data.</p>
        </div>
      </div>
      <ul className="prod-found">
        {insights.map((f) => (
          <li key={f.value} className="prod-found__row">
            <span className="prod-found__icon" aria-hidden="true">
              <UiIcon name={f.icon} size={15} />
            </span>
            <div>
              <p className="prod-found__value">{f.value}</p>
              <p className="prod-found__label">{f.detail}</p>
            </div>
          </li>
        ))}
      </ul>
    </WindowPanel>
  );
}

function ProductRecommendations({
  recommendations,
  onReview,
  onStrategy,
}: {
  recommendations: ProductRecommendation[];
  onReview: () => void;
  onStrategy: () => void;
}) {
  return (
    <WindowPanel title="my.recommendations" className="prod-span-third">
      <span className="prod-badge">High Impact</span>
      <div className="prod-sec__head">
        <span className="prod-sec__icon" aria-hidden="true"><UiIcon name="spark" size={15} /></span>
        <div>
          <h2 className="prod-sec__title">Increase revenue with smarter product strategy</h2>
          <p className="prod-panel__sub">Based on real sales data and customer behavior analysis.</p>
        </div>
      </div>
      <div className="prod-recs">
        {recommendations.map((r) => (
          <div key={r.index} className="prod-rec">
            <span className="prod-rec__label">{r.index}</span>
            <h3 className="prod-rec__title">{r.title}</h3>
            <p className="prod-rec__text">{r.text}</p>
            <div className="prod-rec__meta">
              <span>Potential: <strong>{r.potential}</strong></span>
              <span>Confidence: <strong>{r.confidence}</strong></span>
            </div>
          </div>
        ))}
      </div>
      <div className="prod-sec__actions">
        <Button variant="primary" mono onClick={onReview}>
          Review Opportunities →
        </Button>
        <Button variant="secondary" mono onClick={onStrategy}>
          View Strategy
        </Button>
      </div>
    </WindowPanel>
  );
}

function ProductPreview() {
  const [tab, setTab] = useState<PreviewTab>("Top Products");
  const rows = PREVIEW_ROWS[tab];
  return (
    <WindowPanel title="product.preview" className="prod-span-third prod-span-preview">
      <div className="prod-prev__tabs" role="tablist" aria-label="Product preview tabs">
        {PREVIEW_TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={`prod-prev__tab${tab === t ? " is-active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </div>
      <div className="prod-tablewrap">
        <table className="prod-table">
          <thead>
            <tr>
              <th scope="col">Product</th>
              <th scope="col">Revenue</th>
              <th scope="col">Units</th>
              <th scope="col">Trend</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={`${tab}-${p.name}`}>
                <td>
                  <span className="prod-table__product">
                    <span className="prod-thumb" style={{ background: p.color }} aria-hidden="true">
                      {p.initials}
                    </span>
                    {p.name}
                  </span>
                </td>
                <td>{p.revenue}</td>
                <td>{p.units}</td>
                <td>
                  <span className={p.up ? "prod-trend--up" : "prod-trend--down"}>{p.trend}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="prod-panel__sub">Frontend demo catalog — live products arrive in a later phase.</p>
    </WindowPanel>
  );
}

function ProductChannels({ channels }: { channels: ProductChannel[] }) {
  return (
    <WindowPanel title="product.channels" className="prod-span-full">
      <div className="prod-sec__head">
        <div>
          <h2 className="prod-sec__title">Connected Platforms</h2>
          <p className="prod-panel__sub">Manage your product catalog across all channels.</p>
        </div>
      </div>
      <div className="prod-channels">
        {channels.map((c) => (
          <div key={c.key} className="prod-channel">
            <div className="prod-channel__logozone">
              <ChannelGlyph channelKey={c.key} />
            </div>
            <h3 className="prod-channel__name">{c.name}</h3>
            <span className={`prod-channel__pill${c.status === "connected" ? " is-on" : ""}`}>
              {c.status === "connected" ? "Connected" : "Not connected"}
            </span>
            <p className="prod-channel__blurb">{c.blurb}</p>
            <p className="prod-channel__meta">{c.meta}</p>
            <div className="prod-channel__actions">
              <button type="button" className="prod-stackbtn">
                {c.action}
              </button>
            </div>
          </div>
        ))}
      </div>
      <p className="prod-panel__sub">UI states only — live integrations arrive in a later phase.</p>
    </WindowPanel>
  );
}

function RecentWork({ work }: { work: ProductWorkItem[] }) {
  return (
    <WindowPanel title="recent.work" className="prod-span-half">
      <div className="prod-sec__head prod-sec__head--split">
        <h2 className="prod-sec__title">Recent Activity</h2>
        <span className="prod-panel__sub">Frontend preview</span>
      </div>
      <ul className="prod-work">
        {work.map((w) => (
          <li key={w.title}>
            <div className="prod-work__item">
              <span className="prod-work__icon" aria-hidden="true">
                <UiIcon name={w.waiting ? "clock" : "check"} size={17} />
              </span>
              <span className="prod-work__title">{w.title}</span>
              <span className={`prod-work__state${w.waiting ? " prod-work__state--waiting" : ""}`}>
                {w.waiting ? "Waiting" : "Done"}
              </span>
              <span className="prod-work__meta">{w.detail} · {w.time}</span>
            </div>
          </li>
        ))}
      </ul>
    </WindowPanel>
  );
}

function AgentActivity({ activity }: { activity: ProductActivityItem[] }) {
  return (
    <WindowPanel title="agent.activity" className="prod-span-half">
      <div className="prod-sec__head">
        <span className="prod-live__dot" aria-hidden="true" />
        <h2 className="prod-sec__title">Live activity</h2>
      </div>
      <ol className="prod-activity">
        {activity.map((a) => (
          <li key={a.title} className={`prod-activity__row prod-activity__row--${a.active ? "active" : "completed"}`}>
            <span className="prod-activity__dot" aria-hidden="true" />
            <div>
              <p className="prod-activity__title">{a.title}</p>
              <p className="prod-activity__time">{a.time}</p>
            </div>
          </li>
        ))}
      </ol>
    </WindowPanel>
  );
}

function LearningCard() {
  return (
    <WindowPanel title="what.im.learning" className="prod-span-full">
      <div className="prod-learnempty">
        <div className="prod-learnempty__copy">
          <h2 className="prod-sec__title prod-ico-title">
            <UiIcon name="spark" size={19} />
            What I&apos;m learning
          </h2>
          <p className="prod-learn__insight">
            Cross-sell recommendations show 24% higher conversion when based on real
            customer purchase history.
          </p>
          <p className="prod-learn__insight">
            High-quality product images improve conversion by ~18% for similar stores.
          </p>
        </div>
        <div className="prod-learnempty__visual" aria-hidden="true">
          <span className="prod-learnempty__ring" />
          <p>
            Continuous improvement.
            <br />
            <span>Gets smarter over time.</span>
          </p>
        </div>
      </div>
    </WindowPanel>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────── */

export function ProductAgentPage() {
  const navigate = useNavigate();
  const recommendationsRef = useRef<HTMLDivElement | null>(null);
  const detailsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    document.body.classList.add("prod-hide-site-footer");
    return () => {
      document.body.classList.remove("prod-hide-site-footer");
    };
  }, []);

  const scrollToRecommendations = () => {
    recommendationsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const scrollToDetails = () => {
    detailsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="prod-world">
      <GlobalEnvironment />
      <div className="prod-shell">
        <ProductAgentHero />

        <div className="prod-grid">
          <AgentStatusCard onReview={scrollToRecommendations} onDetails={scrollToDetails} />
          <BusinessSnapshot metrics={SNAPSHOT.metrics} />

          <AgentProgress />
          <ApprovalRequired
            onReview={scrollToRecommendations}
            onApprove={() => navigate("/actions")}
          />

          <div ref={detailsRef} style={{ display: "contents" }} />
          <ProductInsights insights={SNAPSHOT.insights} />
          <div ref={recommendationsRef} style={{ display: "contents" }} />
          <ProductRecommendations
            recommendations={SNAPSHOT.recommendations}
            onReview={scrollToRecommendations}
            onStrategy={scrollToDetails}
          />
          <ProductPreview />

          <ProductChannels channels={SNAPSHOT.channels} />

          <RecentWork work={SNAPSHOT.work} />
          <AgentActivity activity={SNAPSHOT.activity} />

          <LearningCard />
        </div>

        <div className="prod-signoff" aria-label="Product agent footer">
          <span>PRODUCT AGENT · FRONTEND PREVIEW · HUMAN APPROVAL REQUIRED</span>
          <ButtonLink variant="secondary" size="sm" mono to="/agents">
            ← Back to AI Team
          </ButtonLink>
        </div>

        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Button variant="secondary" mono onClick={() => navigate("/marketing-agent")}>
            Open Marketing Agent →
          </Button>
          <Button variant="primary" mono onClick={() => navigate("/actions")}>
            Review &amp; Approve Actions →
          </Button>
        </div>
      </div>
    </div>
  );
}
