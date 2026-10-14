/**
 * /designer-agent — Designer Agent workstation.
 *
 * Rebuilt from the saved portrait reference
 * `src/assets/illustrations/Desinger_agent_Design.png`.
 *
 * BACKGROUND — the one intentional deviation from the reference. The
 * reference ships its own illustrated city background; this page instead
 * renders <GlobalEnvironment />, the SAME fixed, scroll-driven illustrated
 * world the Marketing Agent (MarketingAGIPage) and Product Agent
 * (ProductAgentPage) dashboards use. That component owns `.world-env`
 * (`position: fixed; inset: 0`) plus the Sky / Clouds / City / Street /
 * Commerce / MerchantDistrict / Delivery / Foreground layers from
 * `features/public/Environment/`. No background image is imported here and
 * neither sibling page is touched — the Designer Agent simply inherits the
 * same world, sitting behind `.designer-shell` (`position: relative;
 * z-index: 1`) exactly as `.magi-shell` / `.prod-shell` do.
 *
 * TRUTHFULNESS — every number, status, project row, output and activity event
 * comes from real backend records, loaded by `loadDesignerWorkspace()`
 * (lib/designerWorkspaceApi.ts) over `lib/api.ts`:
 *
 *   GET /api/agents/runs               → the agent's real run history
 *   GET /api/designer/status           → registry presence, real capability
 *                                       state, REAL integration connection
 *                                       status, real derived metrics, and the
 *                                       real image-generation availability
 *   GET /api/designer/projects         → real persisted design projects
 *   GET /api/designer/briefs           → real versioned creative briefs
 *   GET /api/designer/assets           → real versioned assets, typed by kind
 *   GET /api/designer/activity         → real persisted events
 *
 * The reference's example figures (28 designs, 6 in review, Figma "Connected",
 * rendered output thumbnails, named projects) are illustration only and are
 * NOT reproduced as facts. Where no backend data exists the panel renders an
 * honest empty / setup-required state. Nothing is faked, no execution is
 * invented, and no external tool is claimed as connected.
 *
 * ASSET TYPES ARE NEVER CONFLATED. The backend has no image-generation
 * provider, so it stores structured briefs and variants — never image bytes.
 * `design_assets.kind` is the honest discriminator (`brief`,
 * `specification`, `variant`, `rendered_image`) and the UI renders a
 * placeholder plate only where it is labelled as one. It never presents a
 * coloured plate as a generated creative.
 *
 * The design request submits to the existing `POST /api/agents/run`
 * (`startInvestigation`) — the same supported endpoint the AI Team uses to
 * dispatch the Designer Agent. It proposes actions; every proposed action
 * still requires human approval in /actions. No new endpoint is invented.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchAgentsMeta,
  fetchRenderedAssetBlob,
  generateDesignerImage,
  startInvestigation,
} from "../lib/api";
import { scrollToSection } from "../lib/scroll";

/* Recognisable brand marks for the external design tools. Local SVG assets
 * under src/assets/brands/, matching the convention already used by the
 * Product Agent dashboard (shopify.svg, razorpay.svg, …) — no new icon or
 * logo dependency is added to the project. */
import figmaLogo from "../assets/brands/figma.svg";
import canvaLogo from "../assets/brands/canva.svg";
import midjourneyLogo from "../assets/brands/midjourney.svg";
import adobeLogo from "../assets/brands/adobe-creative-cloud.svg";
import driveLogo from "../assets/brands/google-drive.svg";
import notionLogo from "../assets/brands/notion.svg";
import { WindowPanel } from "../components/WindowPanel";
import { GlobalEnvironment } from "../features/public/Environment/GlobalEnvironment";
import {
  loadDesignerWorkspace,
  type DesignerWorkspace,
} from "../lib/designerWorkspaceApi";
import type {
  DesignAsset,
  DesignerActivityEntry,
  DesignerImageGeneration,
} from "../types/api";
import {
  buildDesignerOutputs,
  designerActivityDetail,
  designerActivityView,
  designerStatusCopy,
  designerToolConnection,
  generateAvailability,
  generationErrorMessage,
  generationSuccessMessage,
  mergeDesignerMetrics,
  reviewLabel as reviewStatusLabel,
} from "../lib/designerWorkspace";
import {
  DESIGNER_AGENT_NAME,
  designerAvailability,
  designerMetrics,
  designerModeLabel,
  formatTimestamp,
  isDesignerRunActive,
  relativeTime,
  type DesignerRunSummary,
  type DesignerSnapshot,
} from "../lib/designerAgent";
import "./DesignerAgentPage.css";

/* ── Dashboard icons ────────────────────────────────────────────────────
 * ONE consistent stroke family (currentColor, 1.8px, square 20-grid) —
 * the same flat RazorGrowth language the Marketing Agent uses. Inline SVG,
 * no new dependency, no raster images. */

type UiIconName =
  | "search"
  | "bulb"
  | "spark"
  | "send"
  | "image"
  | "clock"
  | "check"
  | "check-circle"
  | "pulse"
  | "alert"
  | "doc"
  | "layers"
  | "folder"
  | "palette"
  | "target"
  | "grid"
  | "wand"
  | "store"
  | "note"
  | "team"
  | "arrow-right"
  | "arrow-up-right"
  | "grid-chart"
  | "flow"
  | "more"
  | "wrench"
  | "flag"
  | "message"
  | "git-branch"
  | "clipboard"
  | "layout";

function UiIcon({ name, size = 18 }: { name: UiIconName; size?: number }) {
  let body: React.ReactNode;
  switch (name) {
    case "search":
      body = (
        <>
          <circle cx="8.5" cy="8.5" r="5.5" />
          <line x1="12.7" y1="12.7" x2="17" y2="17" />
        </>
      );
      break;
    case "bulb":
      body = (
        <>
          <path d="M10 2.5a5.5 5.5 0 0 0-3.2 10c.7.6 1.2 1.3 1.4 2.2h3.6c.2-.9.7-1.6 1.4-2.2A5.5 5.5 0 0 0 10 2.5z" />
          <line x1="8.2" y1="17" x2="11.8" y2="17" />
        </>
      );
      break;
    case "spark":
      body = (
        <path
          d="M10 2l1.9 5.6 5.6 1.9-5.6 1.9L10 17l-1.9-5.6L2.5 9.5l5.6-1.9z"
          fill="currentColor"
          stroke="none"
        />
      );
      break;
    case "send":
      body = (
        <>
          <path d="M18.3 1.7l-5.8 16.6-3.4-7.5-7.5-3.3z" />
          <line x1="18.3" y1="2" x2="9.2" y2="10.8" />
        </>
      );
      break;
    case "image":
      body = (
        <>
          <rect x="2.5" y="4" width="15" height="12" rx="1.5" />
          <circle cx="7" cy="8.5" r="1.4" />
          <path d="M3.5 14.5l4-3.5 3 2.5 2.5-2 3.5 3" />
        </>
      );
      break;
    case "clock":
      body = (
        <>
          <circle cx="10" cy="10" r="7" />
          <path d="M10 6.5V10l2.5 1.5" />
        </>
      );
      break;
    case "check":
      body = <path d="M3.5 10.5l4 4L16.5 5.5" strokeWidth={2.2} />;
      break;
    case "check-circle":
      body = (
        <>
          <circle cx="10" cy="10" r="7" />
          <path d="M7 10.3l2.1 2.1 3.9-4.2" />
        </>
      );
      break;
    case "pulse":
      body = <path d="M2 10h4l2-5 3.5 10 2-5H18" strokeWidth={2} />;
      break;
    case "alert":
      body = (
        <>
          <path d="M10 2.5L18 16.5H2z" />
          <line x1="10" y1="7.5" x2="10" y2="11.5" />
          <circle cx="10" cy="14" r="0.7" fill="currentColor" stroke="none" />
        </>
      );
      break;
    case "doc":
      body = (
        <>
          <path d="M5 2.5h6.5L15 6v11.5H5z" />
          <path d="M11.5 2.5V6H15" />
          <line x1="7.5" y1="10.5" x2="12.5" y2="10.5" />
          <line x1="7.5" y1="13.5" x2="12.5" y2="13.5" />
        </>
      );
      break;
    case "layers":
      body = (
        <>
          <path d="M10 2.5L18 7l-8 4.5L2 7z" />
          <path d="M2 11l8 4.5L18 11" />
        </>
      );
      break;
    case "folder":
      body = (
        <path d="M2.5 5.5h5l2 2.5h8v8.5h-15z" />
      );
      break;
    case "palette":
      body = (
        <>
          <circle cx="10" cy="10" r="7.2" />
          <circle cx="7.4" cy="9" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="10.4" cy="6.6" r="0.9" fill="currentColor" stroke="none" />
          <circle cx="13.4" cy="9.2" r="0.9" fill="currentColor" stroke="none" />
        </>
      );
      break;
    case "target":
      body = (
        <>
          <circle cx="10" cy="10" r="7" />
          <circle cx="10" cy="10" r="3.5" />
          <circle cx="10" cy="10" r="0.8" fill="currentColor" stroke="none" />
        </>
      );
      break;
    case "grid":
      body = (
        <>
          <rect x="2.5" y="2.5" width="6" height="6" />
          <rect x="11.5" y="2.5" width="6" height="6" />
          <rect x="2.5" y="11.5" width="6" height="6" />
          <rect x="11.5" y="11.5" width="6" height="6" />
        </>
      );
      break;
    case "wand":
      body = (
        <>
          <line x1="3" y1="17" x2="13" y2="7" strokeWidth={2.2} />
          <path d="M15 2.5l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9z" fill="currentColor" stroke="none" />
        </>
      );
      break;
    case "store":
      body = (
        <>
          <path d="M3 8.5h14v8h-14z" />
          <path d="M2.5 4.5h15l-1 4h-13z" />
          <path d="M8 16.5v-4.5h4v4.5" />
        </>
      );
      break;
    case "note":
      body = (
        <>
          <rect x="4" y="2.5" width="12" height="15" rx="1.5" />
          <line x1="7" y1="7" x2="13" y2="7" />
          <line x1="7" y1="10.5" x2="13" y2="10.5" />
          <line x1="7" y1="14" x2="10.5" y2="14" />
        </>
      );
      break;
    case "team":
      body = (
        <>
          <circle cx="7" cy="7" r="3" />
          <path d="M1.8 16.5c.8-2.8 2.8-4.2 5.2-4.2s4.4 1.4 5.2 4.2" />
          <circle cx="14.2" cy="8" r="2.3" />
          <path d="M14.8 12.6c1.9.3 3.2 1.5 3.7 3.6" />
        </>
      );
      break;
    case "arrow-right":
      body = <path d="M3.5 10h13M12 5.5l4.5 4.5L12 14.5" />;
      break;
    case "arrow-up-right":
      body = <path d="M6 14L14 6M7.5 6H14v6.5" />;
      break;
    case "grid-chart":
      body = (
        <>
          <line x1="3" y1="3" x2="3" y2="17" />
          <line x1="3" y1="17" x2="17" y2="17" />
          <line x1="7.2" y1="12" x2="7.2" y2="15" strokeWidth={2.2} />
          <line x1="11.2" y1="8.5" x2="11.2" y2="15" strokeWidth={2.2} />
          <line x1="15.2" y1="5.5" x2="15.2" y2="15" strokeWidth={2.2} />
        </>
      );
      break;
    case "flow":
      body = (
        <>
          <circle cx="4" cy="4.5" r="2" />
          <circle cx="16" cy="10" r="2" />
          <circle cx="4" cy="15.5" r="2" />
          <path d="M6 4.5h4a3 3 0 0 1 3 3v0M6 15.5h4a3 3 0 0 0 3-3v0" />
        </>
      );
      break;
    case "wrench":
      body = (
        <path d="M12.6 3.4a4.6 4.6 0 0 0-5.2 6L2.8 14a1.6 1.6 0 0 0 2.3 2.3l4.6-4.6a4.6 4.6 0 0 0 6-5.2l-2.4 2.4-2.2-.5-.5-2.2z" />
      );
      break;
    case "flag":
      body = (
        <>
          <line x1="4.5" y1="2.5" x2="4.5" y2="17.5" />
          <path d="M4.5 3.5h10l-2 3.2 2 3.3h-10" />
        </>
      );
      break;
    case "message":
      body = (
        <path d="M3 3.5h14v10H8.5L5 16.8v-3.3H3z" />
      );
      break;
    case "git-branch":
      body = (
        <>
          <line x1="5" y1="2.5" x2="5" y2="12.5" />
          <circle cx="15" cy="5" r="2.5" />
          <circle cx="5" cy="15" r="2.5" />
          <path d="M15 7.5a7.5 7.5 0 0 1-7.5 7.5" />
        </>
      );
      break;
    case "clipboard":
      body = (
        <>
          <rect x="4.5" y="3.5" width="11" height="14" rx="1.5" />
          <rect x="7.5" y="2" width="5" height="3" rx="0.8" />
          <line x1="7" y1="9" x2="13" y2="9" />
          <line x1="7" y1="12" x2="13" y2="12" />
          <line x1="7" y1="15" x2="11" y2="15" />
        </>
      );
      break;
    case "layout":
      body = (
        <>
          <rect x="2.5" y="2.5" width="15" height="15" rx="1.5" />
          <line x1="2.5" y1="8" x2="17.5" y2="8" />
          <line x1="9.5" y1="8" x2="9.5" y2="17.5" />
        </>
      );
      break;
    case "more":
    default:
      body = (
        <>
          <circle cx="4.5" cy="10" r="1.2" fill="currentColor" stroke="none" />
          <circle cx="10" cy="10" r="1.2" fill="currentColor" stroke="none" />
          <circle cx="15.5" cy="10" r="1.2" fill="currentColor" stroke="none" />
        </>
      );
      break;
  }
  return (
    <svg
      className="designer-uiicon"
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

/* ── Deterministic placeholder palettes ─────────────────────────────────
 * The backend stores no rendered design asset, so output thumbnails and
 * project covers are abstract swatch plates. They are seeded from the REAL
 * record id, so a given brief always looks the same across reloads, and
 * they encode nothing that is not already true. */

const SWATCH_PALETTES: Array<[string, string, string]> = [
  ["#D97757", "#E8936B", "#F0BC92"],
  ["#3E7D58", "#70B88A", "#B7D9C2"],
  ["#7A5BB5", "#A48BD6", "#D6C8F0"],
  ["#B08228", "#E0B04A", "#F2DDA8"],
  ["#3A6EA8", "#5A8DC4", "#B7D2E8"],
  ["#A94F38", "#C85F43", "#E3A491"],
];

function seedOf(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i += 1) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return h;
}

function paletteFor(id: string): [string, string, string] {
  return SWATCH_PALETTES[seedOf(id) % SWATCH_PALETTES.length];
}

/** Abstract art plate for one record — layered, framed shapes so it reads as a
 *  composed design thumbnail. Flat fills only, no fabricated content, seeded
 *  from the real record id so a given brief always looks the same. */
function Swatch({ id, className }: { id: string; className?: string }) {
  const [a, b, c] = paletteFor(id);
  const seed = seedOf(id);
  const r1 = 10 + (seed % 7);
  const r2 = 14 + ((seed >> 3) % 9);
  const dx = (seed >> 6) % 10;
  return (
    <svg
      className={className}
      viewBox="0 0 160 90"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="160" height="90" fill={c} />
      {/* framed artboard */}
      <rect x="14" y="10" width="132" height="70" fill={b} stroke="#2a1810" strokeWidth="2" />
      {/* sun / focal mark */}
      <circle cx={36 + dx} cy={30} r={r1} fill={a} />
      {/* stacked plates */}
      <rect x={44 + dx} y={26} width="60" height="34" fill={a} opacity="0.92" />
      <rect x={58 + dx} y={34} width="76" height="40" fill={b} stroke="#2a1810" strokeWidth="2" />
      <circle cx={118} cy={44} r={r2 / 2} fill={a} />
      {/* baseline rule */}
      <line x1="22" y1="70" x2="72" y2="70" stroke="#2a1810" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* ── Workflow steps (reference: Research → Create → Validate → Deliver) ── */

const WORKFLOW_STEPS = [
  { icon: "search", label: "Research" },
  { icon: "bulb", label: "Create" },
  { icon: "spark", label: "Validate" },
  { icon: "send", label: "Deliver" },
] as const;

/* ── Design capabilities ────────────────────────────────────────────────
 * Static capability DESCRIPTIONS of what the registered Designer Agent
 * declares it can do — product copy, not a metric. The declared tool list
 * itself is rendered separately, straight from the backend registry. */

const CAPABILITIES = [
  {
    icon: "palette",
    tone: "coral",
    title: "Brand & Identity",
    desc: "Logos, color palettes, typography and brand style guides.",
  },
  {
    icon: "image",
    tone: "purple",
    title: "Marketing Creatives",
    desc: "Social media visuals, ads, banners and campaign creative sets.",
  },
  {
    icon: "store",
    tone: "coral",
    title: "Product & UX Design",
    desc: "Product pages, checkout UX, user flows and interface improvements.",
  },
  {
    icon: "layers",
    tone: "blue",
    title: "Design Variations",
    desc: "Multiple creative variants and A/B testing options.",
  },
  {
    icon: "folder",
    tone: "amber",
    title: "Asset Organization",
    desc: "Automatically organize and version your designs.",
  },
  {
    icon: "team",
    tone: "purple",
    title: "AI Team Handoffs",
    desc: "Share assets and insights with marketing, product and engineering agents.",
  },
] as const;

/* ── External design tools shown as UNAVAILABLE ──────────────────────────
 * The reference draws Figma / Canva / Midjourney / Adobe / Drive / Notion
 * with "Connected" pills. This build has no external design-tool
 * integration, so each is listed honestly as not connected, with setup
 * required. Nothing is claimed that the code cannot prove.
 *
 * A displayed brand logo and a connection status are two separate things:
 * the logo identifies the tool the card is about, the pill states the
 * integration's real status. Recognisable brand marks are local SVG assets
 * in src/assets/brands/ (same convention as shopify.svg / razorpay.svg) so
 * no new icon dependency is introduced. */

/* `provider` is the backend's integration key (see
 * `_SUPPORTED_PROVIDERS` in backend/app/api/routes/designer.py), used to match
 * a card against its REAL connection state. The logo is branding only and is
 * never evidence that a connection exists. */
const EXTERNAL_TOOLS = [
  { key: "figma", provider: "figma", label: "Figma", logo: figmaLogo },
  { key: "canva", provider: "canva", label: "Canva", logo: canvaLogo },
  { key: "midjourney", provider: "midjourney", label: "Midjourney", logo: midjourneyLogo },
  {
    key: "adobe",
    provider: "adobe_creative_cloud",
    label: "Adobe Creative Cloud",
    logo: adobeLogo,
  },
  {
    key: "gdrive",
    provider: "google_drive",
    label: "Google Drive",
    logo: driveLogo,
  },
  { key: "notion", provider: "notion", label: "Notion", logo: notionLogo },
] as const;

/** One distinct glyph per built-in registry tool, keyed by the stable backend
 *  tool identifier (never by array position). The registry declares internal
 *  capability names (creative_concept, ux_recommendations, …), not
 *  third-party products, so these stay generic RazorGrowth glyphs rather
 *  than borrowed brand marks. */
function registryToolIcon(tool: string): UiIconName {
  const t = tool.toLowerCase();
  if (t.includes("concept") || t.includes("idea")) return "bulb";
  if (t.includes("messag") || t.includes("copy")) return "message";
  if (t.includes("variant") || t.includes("experiment") || t.includes("split")) return "git-branch";
  if (t.includes("ux")) return "layout";
  if (t.includes("brief") || t.includes("clipboard") || t.includes("file") || t.includes("notebook")) return "clipboard";
  if (t.includes("brand") || t.includes("identity") || t.includes("logo") || t.includes("palette")) return "palette";
  return "spark";
}

function ToolMark({ tool }: { tool: string }) {
  return (
    <span className="designer-tool__logo" aria-hidden="true">
      <UiIcon name={registryToolIcon(tool)} size={20} />
    </span>
  );
}

/** Real brand mark for an external design tool. `alt` is empty on purpose —
 *  the brand name is rendered right beside it, so announcing it twice would
 *  just be noise for a screen reader. */
function BrandMark({ logo }: { logo: string }) {
  return (
    <span className="designer-tool__logo designer-tool__logo--brand">
      <img src={logo} alt="" aria-hidden="true" />
    </span>
  );
}

/* ── Read-model helpers ───────────────────────────────────────────────── */

/** Acronyms the backend registry uses in tool keys. Title-casing every word
 *  would render "ux_recommendations" as "Ux Recommendations", so these are
 *  restored to their conventional casing after the generic title-casing. */
const TOOL_ACRONYMS = new Set(["ux", "ui", "ai", "seo", "cta", "cms", "api"]);

/** Readable tool name for a backend registry tool key. */
function toolLabel(tool: string): string {
  return tool
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase())
    .split(" ")
    .map((w) => (TOOL_ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w))
    .join(" ");
}

/** Glyph for a real asset kind. The backend's `kind` is the honest
 *  discriminator, so the glyph states exactly what the artefact IS — a
 *  structured brief is never drawn as a rendered image. */
function assetKindIcon(kind: DesignAsset["kind"]): UiIconName {
  switch (kind) {
    case "variant":
      return "layers";
    case "specification":
      return "layout";
    case "rendered_image":
      return "image";
    case "brief":
    default:
      return "doc";
  }
}

/** Human label for a stored asset kind. */
function assetKindLabel(kind: DesignAsset["kind"]): string {
  switch (kind) {
    case "variant":
      return "Creative variant";
    case "specification":
      return "Design specification";
    case "rendered_image":
      return "Rendered image";
    case "brief":
    default:
      return "Creative brief";
  }
}

/** Glyph for a real persisted activity row.
 *
 *  A failed agent run must never borrow the pulsing "this is live right now"
 *  glyph, so `failed` is resolved from the row's own real status rather than
 *  from a tone. The decision itself lives in designerWorkspace.ts so it is
 *  unit-tested. */
function activityIcon(item: DesignerActivityEntry): UiIconName {
  return designerActivityView(item).icon as UiIconName;
}

/** Badge tone for a real activity row. A failure reads red, not "live coral". */
function activityBadgeTone(item: DesignerActivityEntry): string {
  return designerActivityView(item).tone;
}

/** Human label for a review status, so the UI never shows a raw enum alone. */
function reviewLabel(status: string): string {
  return reviewStatusLabel(status);
}

/** Human-readable byte size for a stored image. Exact, never rounded up. */
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * One stored image, fetched WITH the bearer token and shown via a temporary
 * object URL.
 *
 * Why not `<img src="/api/...">`: this app authenticates with a Bearer token
 * stored in localStorage and sent as a request HEADER. An image tag cannot set
 * headers, so that approach silently yields a broken image. Fetching the bytes
 * through the shared authenticated client and handing them to the page as a
 * blob is the only thing that actually works — and it keeps the image behind
 * the same auth check as every other endpoint.
 *
 * The object URL is revoked on unmount and whenever the id changes, so long
 * sessions do not leak blobs.
 */
function AuthenticatedImage({
  renderedId,
  alt,
}: {
  renderedId: string;
  alt: string;
}) {
  const [state, setState] = useState<{ url: string | null; error: string | null }>({
    url: null,
    error: null,
  });

  useEffect(() => {
    // Held outside the effect so the cleanup can revoke exactly what was
    // created, including when the fetch resolves after a re-render.
    let objectUrl: string | null = null;
    const controller = new AbortController();

    setState({ url: null, error: null });

    fetchRenderedAssetBlob(renderedId, controller.signal)
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setState({ url: objectUrl, error: null });
      })
      .catch((e: unknown) => {
        if (controller.signal.aborted) return;
        if ((e as Error)?.name === "AbortError") return;
        setState({ url: null, error: generationErrorMessage(e) });
      });

    return () => {
      controller.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
        objectUrl = null;
      }
    };
  }, [renderedId]);

  if (state.error) {
    return (
      <div className="designer-output__thumb designer-output__thumb--error">
        <span className="designer-output__err">
          <UiIcon name="alert" size={18} />
          {state.error}
        </span>
      </div>
    );
  }
  if (!state.url) {
    return (
      <div className="designer-output__thumb designer-output__thumb--loading">
        <span className="designer-loading">Loading image…</span>
      </div>
    );
  }
  return (
    <div className="designer-output__thumb">
      <img className="designer-output__img" src={state.url} alt={alt} />
    </div>
  );
}

/** The four workflow phases the Designer Agent actually records, mapped
 *  from a real run status. No step is ever marked "done" that did not
 *  complete, and a failed run stops the trail where it stopped. */
const DESIGNER_STEPS = [
  "Registered",
  "Research",
  "Create",
  "Review",
  "Approved",
] as const;

function stepIndex(snapshot: DesignerSnapshot): number {
  const latest = snapshot.latest;
  if (!latest) return snapshot.registered ? 0 : -1;
  if (latest.status === "failed") return 2;
  if (isDesignerRunActive(latest.status)) return 2;
  if (latest.status === "completed") return 4;
  return 2;
}

/** Bars for a metric cell: the last few Designer Agent runs as a mini
 *  sparkline. Height is the run's REAL duration and colour is its REAL
 *  outcome, so the chart can never say something the backend did not record.
 *  A run with no recorded latency still gets a floor height so it stays
 *  visible rather than silently disappearing. */
function runSparkline(runs: DesignerRunSummary[]): Array<{ h: number; tone: string }> {
  const recent = runs.slice(0, 5).reverse(); // oldest → newest
  const max = Math.max(1, ...recent.map((r) => r.latencyMs ?? 0));
  return recent.map((r) => ({
    h: r.latencyMs ? Math.max(5, Math.round(((r.latencyMs ?? 0) / max) * 24)) : 5,
    tone:
      r.status === "completed"
        ? "green"
        : isDesignerRunActive(r.status)
          ? "amber"
          : r.status === "failed"
            ? "red"
            : "faint",
  }));
}

/* ── Component ────────────────────────────────────────────────────────── */

export function DesignerAgentPage() {
  const navigate = useNavigate();
  const [snapshot, setSnapshot] = useState<DesignerSnapshot | null>(null);
  /** Real workspace records: projects, briefs, assets, activity, status. */
  const [workspace, setWorkspace] = useState<DesignerWorkspace | null>(null);
  const [loadState, setLoadState] = useState<
    "loading" | "ready" | "login_required" | "no_workspace" | "error"
  >("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [brief, setBrief] = useState("");
  const [dispatching, setDispatching] = useState(false);
  const [dispatchMsg, setDispatchMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [expandedOutput, setExpandedOutput] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    /* Probe the registry directly first. loadDesignerWorkspace() isolates each
     * endpoint, so an auth failure surfaces there as empty data — without this
     * probe a signed-out visitor would be told "this backend does not register a
     * Designer Agent", which is a different (and false) claim.
     * GET /api/agents is an existing endpoint; no backend change. */
    try {
      await fetchAgentsMeta();
    } catch (e) {
      const err = e as { status?: number };
      if (err.status === 401) {
        setLoadState("login_required");
        return;
      }
      if (err.status === 403) {
        setLoadState("no_workspace");
        return;
      }
      // Network / server error on the probe: still try to render whatever
      // the isolated workspace loader can gather.
    }

    try {
      const ws = await loadDesignerWorkspace();
      setSnapshot(ws.snapshot);
      setWorkspace(ws);
      setErrorMsg(ws.error);
      /* Only a TOTAL failure is a page-level error. A partial load still
       * renders: each unavailable section shows its own honest state, which is
       * more useful than hiding real data behind a full-page error. */
      const totalFailure =
        !ws.load.runs && !ws.load.status && !ws.load.projects && !ws.load.briefs;
      setLoadState(totalFailure ? "error" : "ready");
    } catch (e) {
      const err = e as { status?: number; message?: string };
      if (err.status === 401) setLoadState("login_required");
      else if (err.status === 403) setLoadState("no_workspace");
      else {
        setLoadState("error");
        setErrorMsg(err.message ?? "Failed to load the Designer Agent dashboard");
      }
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  /* Refresh run history periodically so an in-flight Designer Agent run
   * becomes visible without a manual reload. Cadence is deliberately slow —
   * this is a read-only board, not a live stream. */
  useEffect(() => {
    if (loadState !== "ready") return;
    const tick = window.setInterval(() => {
      setNow(Date.now());
      void load();
    }, 15000);
    return () => window.clearInterval(tick);
  }, [load, loadState]);

  /* Relative timestamps ("2h ago") must stay current between polls. */
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(id);
  }, []);

  const runs = snapshot?.runs ?? [];

  const availability = useMemo(
    () => designerAvailability(Boolean(snapshot?.registered), runs),
    [snapshot?.registered, runs],
  );

  /* ── Metrics: REAL persisted counts, never a derived guess ────────────
   * `mergeDesignerMetrics` prefers the backend's row counts and only falls back
   * to run history when that endpoint is unavailable, marking the cell so the
   * UI can say which kind of number it is showing. */
  const metrics = useMemo(
    () =>
      mergeDesignerMetrics(workspace?.status?.metrics, designerMetrics(runs, now)),
    [workspace?.status?.metrics, runs, now],
  );

  /* ── Outputs: real stored assets and briefs, typed by honest kind ─────
   * A brief and a variant asset are distinct records with distinct labels. No
   * placeholder is ever dressed up as a generated creative. */
  const outputs = useMemo(
    () => buildDesignerOutputs(workspace?.assets ?? [], workspace?.briefs ?? [], now),
    [workspace?.assets, workspace?.briefs, now],
  );

  /* Real persisted projects. */
  const projects = workspace?.projects ?? [];

  /* Real persisted activity. */
  const activity = workspace?.activity ?? [];

  /* Real image-generation state and real stored images. Both come straight
   * from the backend; nothing here infers availability from the mere presence
   * of a tile. */
  const imageGen = workspace?.imageGeneration ?? null;
  const renderedAssets = useMemo(
    () =>
      (workspace?.renderedAssets ?? []).map((r) => {
        const asset = (workspace?.assets ?? []).find((a) => a.id === r.asset_id);
        return { ...r, asset };
      }),
    [workspace?.renderedAssets, workspace?.assets],
  );

  /* ── Image generation ───────────────────────────────────────────────
   * The panel-level control acts on the newest design asset; each stored
   * image can regenerate its own. Both call the same handler. */
  const [generating, setGenerating] = useState(false);
  const [lastGen, setLastGen] = useState<DesignerImageGeneration | null>(null);
  const [genError, setGenError] = useState<string | null>(null);
  const [imagePrompt, setImagePrompt] = useState("");

  /** Newest asset the agent has actually produced. */
  const newestAssetId = useMemo(() => {
    const list = workspace?.assets ?? [];
    if (!list.length) return null;
    // `assets` arrives newest-first from the backend.
    return list[0].id;
  }, [workspace?.assets]);

  const genAvail = useMemo(
    () =>
      generateAvailability({
        imageGeneration: imageGen,
        hasAsset: Boolean(newestAssetId),
        hasPrompt: imagePrompt.trim().length > 0,
        submitting: generating,
        lastResult: lastGen,
      }),
    [imageGen, newestAssetId, imagePrompt, generating, lastGen],
  );

  /* The single sentence shown under the button. Success is only ever shown
   * after the backend confirmed a persisted image. */
  const genMsg = useMemo(() => {
    if (genError) return genError;
    if (lastGen?.status === "completed") {
      return generationSuccessMessage(lastGen) ?? genAvail.message;
    }
    return genAvail.message;
  }, [genError, lastGen, genAvail.message]);

  const runGeneration = useCallback(
    async (assetId: string | null, prompt?: string) => {
      if ((!assetId && !prompt?.trim()) || generating) return; // no source, never double-submit
      setGenerating(true);
      setGenError(null);
      try {
        const result = await generateDesignerImage(assetId, {
          ...(prompt ? { prompt } : {}),
        });
        setLastGen(result);
        // Refresh from the backend so the panel shows REAL persisted data —
        // never an optimistic tile.
        await load();
        if (result.status !== "completed") {
          setGenError(result.reason ?? "Image generation did not complete.");
        }
      } catch (e) {
        setGenError(generationErrorMessage(e));
      } finally {
        setGenerating(false);
      }
    },
    [generating, load],
  );

  const onGenerate = useCallback(
    (assetId: string | null, prompt?: string) =>
      void runGeneration(assetId, (prompt ?? imagePrompt).trim() || undefined),
    [runGeneration, imagePrompt],
  );

  const onRegenerate = useCallback(
    (assetId: string) => void runGeneration(assetId),
    [runGeneration],
  );

  const step = stepIndex(snapshot ?? { registered: false, latest: null } as DesignerSnapshot);

  const latestRun = runs[0] ?? null;

  /* ── Design request → existing supported endpoint only ──────────────
   * POST /api/agents/run (startInvestigation) dispatches the AI Team
   * workspace cycle, which includes the Designer Agent, and proposes actions
   * for human approval. Nothing is executed automatically.
   *
   * The project is deliberately NOT pre-created here. The Designer Agent
   * creates the project and the brief *inside* the cycle and links them to the
   * cycle's real `orchestrator_run_id`, so a design request never starts a
   * second, parallel AI Team cycle. The cycle id below is the real identifier
   * the merchant can follow. */
  const submitDesignRequest = useCallback(async () => {
    const objective = brief.trim();
    if (!objective) {
      setDispatchMsg({ ok: false, text: "Describe what you want to design first." });
      return;
    }
    if (dispatching) return; // guard against a double-click forking work
    setDispatching(true);
    setDispatchMsg(null);
    try {
      const res = await startInvestigation(objective);
      setDispatchMsg({
        ok: true,
        text: `AI Team cycle ${res.orchestrator_run_id.slice(0, 8)}… started. The Designer Agent researches your brief and stores its concepts on a design project linked to this cycle — nothing is published without your approval.`,
      });
      setBrief("");
      await load();
    } catch (e) {
      const err = e as { status?: number; message?: string };
      setDispatchMsg({
        ok: false,
        text:
          err.status === 401
            ? "Sign in to start a design request."
            : err.status === 403
              ? "No workspace is linked to this account yet."
              : err.message ?? "Could not start the design request.",
      });
    } finally {
      setDispatching(false);
    }
  }, [brief, dispatching, load]);

  /* ── Gate states — honest, never a fake dashboard ──────────────────── */
  if (loadState === "login_required") {
    return (
      <div className="designer-world">
        <GlobalEnvironment />
        <div className="designer-shell">
          <WindowPanel title="designer.agent" className="designer-span-full">
            <div className="window__body">
              <p className="designer-eyebrow">DESIGNER AGENT</p>
              <h1 className="designer-head__title">Sign in to open the Designer Agent</h1>
              <p className="designer-panel__sub">
                This workstation shows your workspace&apos;s real design runs and creative briefs.
              </p>
              <div className="designer-status__actions">
                <button type="button" className="designer-btn designer-btn--primary" onClick={() => navigate("/login")}>
                  Go to sign in
                </button>
              </div>
            </div>
          </WindowPanel>
        </div>
      </div>
    );
  }

  if (loadState === "no_workspace") {
    return (
      <div className="designer-world">
        <GlobalEnvironment />
        <div className="designer-shell">
          <WindowPanel title="designer.agent" className="designer-span-full">
            <div className="window__body">
              <p className="designer-eyebrow">DESIGNER AGENT</p>
              <h1 className="designer-head__title">No workspace linked yet</h1>
              <p className="designer-panel__sub">
                The Designer Agent works inside a merchant workspace. Connect one from your profile to
                see real runs and creative briefs.
              </p>
              <div className="designer-status__actions">
                <button type="button" className="designer-btn designer-btn--primary" onClick={() => navigate("/profile")}>
                  Open profile
                </button>
              </div>
            </div>
          </WindowPanel>
        </div>
      </div>
    );
  }

  if (loadState === "error") {
    return (
      <div className="designer-world">
        <GlobalEnvironment />
        <div className="designer-shell">
          <WindowPanel title="designer.agent" className="designer-span-full">
            <div className="window__body">
              <p className="designer-eyebrow">DESIGNER AGENT</p>
              <h1 className="designer-head__title">Could not load the Designer Agent</h1>
              {errorMsg && <p className="designer-error">{errorMsg}</p>}
              <div className="designer-status__actions">
                <button type="button" className="designer-btn designer-btn--primary" onClick={() => void load()}>
                  Try again
                </button>
              </div>
            </div>
          </WindowPanel>
        </div>
      </div>
    );
  }

  /* ── Render ────────────────────────────────────────────────────────── */

  /* Agent status is the REAL backend state: registry presence from
   * `/api/designer/status`, plus the latest genuine run and the latest stored
   * output. The page never claims the agent is "live" merely because it loaded.
   * The copy itself is built by designerStatusCopy() so the rule is unit-tested. */
  const designerStatus = workspace?.status ?? null;
  const agentRegistered = designerStatus
    ? designerStatus.agent_registered
    : Boolean(snapshot?.registered);

  const latestProject = designerStatus?.latest_project ?? null;
  const latestBrief = designerStatus?.latest_brief ?? null;
  const awaitingReview =
    designerStatus?.metrics.find((m) => m.key === "awaiting_review")?.value ?? 0;

  /* "Active" requires an actual in-flight run. A page load is not activity. */
  const runState: "none" | "active" | "failed" | "idle" =
    latestRun && isDesignerRunActive(latestRun.status)
      ? "active"
      : latestRun && latestRun.status === "failed"
        ? "failed"
        : runs.length === 0 && !latestProject
          ? "none"
          : "idle";

  const statusCopy = designerStatusCopy({
    registered: agentRegistered,
    agentName: DESIGNER_AGENT_NAME,
    runState,
    modeLabel: designerModeLabel(latestRun?.mode ?? ""),
    awaitingReview,
    latestBrief: latestBrief
      ? {
          title: latestBrief.title,
          version: latestBrief.version,
          reviewStatus: latestBrief.review_status,
        }
      : null,
    relative: relativeTime(
      (latestBrief ? Date.parse(latestBrief.created_at) || null : null) ??
        latestRun?.completedAt ??
        latestRun?.startedAt ??
        null,
      now,
    ).toLowerCase(),
    runError: latestRun?.error ?? null,
  });
  const statusHeadline = statusCopy.headline;
  const statusSupport = statusCopy.support;

  /* One shared, real sparkline: the most recent Designer Agent runs. */
  const sparkline = runSparkline(runs);

  return (
    <div className="designer-world">
      {/* The SAME illustrated world the Marketing + Product Agent pages use. */}
      <GlobalEnvironment />

      <div className="designer-shell">
        {/* ══ HERO — copy sits bare on the world; the request is the one window ═ */}
        <div className="designer-hero">
            {/* ── copy column (no card, no border — direct on the world) ── */}
            <div className="designer-hero__copy">
              <p className="designer-eyebrow">
                DESIGNER AGENT · AUTONOMOUS CREATIVE PARTNER
              </p>
              <div className="designer-hero__editorial">
                <h1 className="designer-hero__title">
                  Turn ideas into
                  <br />
                  stunning designs
                  <br />
                  that <span className="designer-hero__accent">grow your business.</span>
                </h1>
              </div>

              {/* Workflow steps */}
              <div className="designer-flow">
                {WORKFLOW_STEPS.map((s, i) => (
                  <div key={s.label} className="designer-flow__item">
                    {i > 0 && (
                      <span className="designer-flow__arrow" aria-hidden="true">
                        <UiIcon name="arrow-right" size={16} />
                      </span>
                    )}
                    <div className="designer-flow__step">
                      <span className="designer-flow__icon">
                        <UiIcon name={s.icon} size={18} />
                      </span>
                      <span className="designer-flow__label">{s.label}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* ── design request window ── */}
            <WindowPanel title="create.with.ai" className="designer-request">
              <div className="designer-request__head">
                <span className="designer-request__avatar" aria-hidden="true">
                  <UiIcon name="spark" size={20} />
                </span>
                <div style={{ minWidth: 0 }}>
                  <h2 className="designer-request__name">Designer Agent</h2>
                  <p className="designer-request__desc">
                    Create brand identities, marketing creatives, product designs and UI/UX
                    experiences for your business automatically.
                  </p>
                </div>
                <button
                  type="button"
                  className="designer-request__how"
                  onClick={() => {
                    if (!scrollToSection("how-it-works")) navigate("/");
                  }}
                >
                  <UiIcon name="bulb" size={13} />
                  How it works
                </button>
              </div>

              <div className="designer-request__statusrow">
                <span
                  className={
                    snapshot?.inFlight
                      ? "designer-request__status"
                      : "designer-request__status designer-request__status--idle"
                  }
                >
                  {snapshot?.inFlight ? "Active" : availability.label}
                </span>
                <p className="designer-request__note">
                  Starts an AI Team analysis cycle. The Designer Agent researches your brief and
                  stores its concepts for your review — nothing is published without your approval.
                </p>
              </div>

              <div className="designer-request__form">
                <div className="designer-request__row">
                  <textarea
                    className="designer-request__textarea"
                    rows={2}
                    placeholder="Describe what you want to design..."
                    value={brief}
                    onChange={(e) => setBrief(e.target.value)}
                    aria-label="Describe what you want to design"
                  />
                  <span className="designer-request__attach" aria-hidden="true">
                    <UiIcon name="image" size={18} />
                  </span>
                  <button
                    type="button"
                    className="designer-request__submit"
                    onClick={() => void submitDesignRequest()}
                    disabled={dispatching || !snapshot?.registered}
                  >
                    {dispatching ? "Starting…" : "Start Design Request"}
                    {!dispatching && <UiIcon name="arrow-right" size={16} />}
                  </button>
                </div>

                {/* Suggestion chips fill the field; they submit nothing. */}
                <div className="designer-request__suggestions">
                  {[
                    "Product page redesign",
                    "Campaign creative set",
                    "Brand identity kit",
                    "Landing page UI",
                    "Social media creatives",
                  ].map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="designer-request__chip"
                      onClick={() => setBrief(s)}
                    >
                      ✦ {s}
                    </button>
                  ))}
                </div>

                {dispatchMsg && (
                  <p
                    className={
                      dispatchMsg.ok
                        ? "designer-request__msg designer-request__msg--ok"
                        : "designer-request__msg designer-request__msg--bad"
                    }
                  >
                    {dispatchMsg.text}
                  </p>
                )}
              </div>
            </WindowPanel>
        </div>

        {/* ══ Loading state (honest, before any data arrives) ════════ */}
        {loadState === "loading" && (
          <WindowPanel title="loading" className="designer-span-full">
            <div className="window__body">
              <p className="designer-loading">Loading your real Designer Agent data…</p>
            </div>
          </WindowPanel>
        )}

        {/* ══ GRID ════════════════════════════════════════════════════ */}
        <div className="designer-grid">
          {/* ── AGENT STATUS ──────────────────────────────────────── */}
          <WindowPanel title="agent.status" className="designer-span-status">
            <div className="designer-status__badge">
              <UiIcon name="spark" size={15} />
              {snapshot?.inFlight ? "TASKS WAITING FOR YOUR REVIEW" : "AGENT STATUS"}
            </div>

            <div className="designer-status__main">
              <div>
                <h2 className="designer-status__headline">{statusHeadline}</h2>
                <p className="designer-status__support">{statusSupport}</p>
                <div className="designer-status__actions">
                  <button
                    type="button"
                    className="designer-btn designer-btn--primary"
                    onClick={() => document.getElementById("designer-projects")?.scrollIntoView({ behavior: "smooth" })}
                  >
                    View progress
                    <UiIcon name="arrow-right" size={14} />
                  </button>
                  <button
                    type="button"
                    className="designer-btn designer-btn--ghost"
                    onClick={() => navigate("/agents")}
                  >
                    View AI Team
                  </button>
                </div>
              </div>

              {/* Workflow trail — real state from the latest run. */}
              <div>
                <ol className="designer-flow" style={{ marginTop: 0, flexDirection: "column", gap: 8 }}>
                  {DESIGNER_STEPS.map((label, i) => (
                    <li
                      key={label}
                      className="designer-activity__row"
                      style={{ gridTemplateColumns: "22px 1fr", padding: "4px 0", gap: 8 }}
                    >
                      <span
                        className={
                          i <= step && step >= 0
                            ? "designer-activity__badge designer-activity__badge--ok"
                            : "designer-activity__badge designer-activity__badge--neutral"
                        }
                        style={{ width: 22, height: 22 }}
                      >
                        <UiIcon name={i <= step && step >= 0 ? "check" : "doc"} size={12} />
                      </span>
                      <span
                        className="designer-output__meta"
                        style={{ fontFamily: "var(--font-display)", fontSize: "0.78rem" }}
                      >
                        {label}
                      </span>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          </WindowPanel>

          {/* ── KEY METRICS ───────────────────────────────────────── */}
          <WindowPanel title="key.metrics" className="designer-span-metrics">
            {workspace?.partial && !workspace.load.status && (
              <p className="designer-empty">
                Real workspace counts are unavailable — showing counts derived from your
                Designer Agent run history instead.
              </p>
            )}
            <div className="designer-metrics">
              {metrics.map((m) => (
                <div key={m.key} className="designer-metric">
                  <div className="designer-metric__top">
                    <span
                      className={`designer-metric__badge designer-metric__badge--${m.tone}`}
                      aria-hidden="true"
                    >
                      <UiIcon name={m.icon as UiIconName} size={17} />
                    </span>
                  </div>
                  <span className="designer-metric__value">{m.value}</span>
                  <span className="designer-metric__label">{m.label}</span>
                  <span
                    className={
                      m.hintTone
                        ? `designer-metric__hint designer-metric__hint--${m.hintTone}`
                        : "designer-metric__hint"
                    }
                  >
                    {m.hint}
                  </span>
                  {/* Real run history: bar height is recorded latency, colour is
                      the recorded outcome. Never decorative. */}
                  {workspace?.load.runs && (
                    <span className="designer-metric__bars" aria-hidden="true">
                      {sparkline.map((b, i) => (
                        <span
                          key={i}
                          className={`designer-metric__bar designer-metric__bar--${b.tone}`}
                          style={{ height: b.h }}
                        />
                      ))}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </WindowPanel>

          {/* ── CONNECTED DESIGN TOOLS ────────────────────────────── */}
          <WindowPanel title="connected.tools" className="designer-span-full">
            <div className="designer-head">
              <div style={{ minWidth: 0 }}>
                <h2 className="designer-head__title designer-ico-title">
                  <UiIcon name="wrench" size={19} />
                  Connected Design Tools
                </h2>
                <p className="designer-panel__sub">
                  {snapshot?.tools.length
                    ? "The Designer Agent's tools as declared by the backend registry."
                    : "Tools the Designer Agent declares in the backend registry."}
                </p>
              </div>
              <details className="designer-disclosure">
                <summary>
                  <UiIcon name="grid" size={14} />
                  Manage Tools
                </summary>
                <div style={{ marginTop: 12 }}>
                  <p className="designer-toolsnote">
                    Built-in tools are the Designer Agent&apos;s own registry capabilities — it
                    works without Figma, Canva or any external account. External cards show
                    each provider&apos;s real connection state, read from your workspace&apos;s
                    integration records, so a logo here never implies a working connection.
                  </p>
                </div>
              </details>
            </div>

            {/* Real registry tools first (these genuinely exist). */}
            {snapshot?.tools.length ? (
              <div className="designer-toolgroup">
                <p className="designer-toolgroup__label">
                  Agent registry tools — available now
                </p>
                <div className="designer-tools">
                  {snapshot.tools.map((tool) => (
                    <div key={tool} className="designer-tool">
                      <ToolMark tool={tool} />
                      <p className="designer-tool__name">{toolLabel(tool)}</p>
                      <span className="designer-tool__pill designer-tool__pill--on">Built in</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="designer-empty">
                The backend registry did not return any tool for {DESIGNER_AGENT_NAME}.
              </p>
            )}

            {/* External design tools — real connection state, from the backend's
                own IntegrationConnection lookup. A provider is only ever shown
                as connected when a connection row exists for this workspace. */}
            <div className="designer-toolgroup">
              <p className="designer-toolgroup__label">
                External design tools —{" "}
                {workspace?.load.status && designerStatus
                  ? designerStatus.integrations.some((i) => i.status === "connected")
                    ? "connection reported by the backend"
                    : "none connected for this workspace"
                  : "connection status unavailable"}
              </p>
              <div className="designer-tools">
                {EXTERNAL_TOOLS.map((tool) => {
                  const conn = designerToolConnection(
                    tool.provider,
                    designerStatus?.integrations,
                    Boolean(workspace?.load.status),
                  );
                  return (
                    <div key={tool.key} className="designer-tool">
                      <BrandMark logo={tool.logo} />
                      <p className="designer-tool__name">{tool.label}</p>
                      <span className={`designer-tool__pill ${conn.pill}`}>
                        {conn.status === "connected"
                          ? "Connected"
                          : conn.status === "unsupported"
                            ? "Not supported"
                            : conn.status === "unknown"
                              ? "Status unknown"
                              : "Setup required"}
                      </span>
                      <span className="designer-tool__meta">{conn.detail}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </WindowPanel>

          {/* ── DESIGN CAPABILITIES ───────────────────────────────── */}
          <WindowPanel title="design.capabilities" className="designer-span-full">
            <div className="designer-head">
              <h2 className="designer-head__title">
                What the Designer Agent can do for your business.
              </h2>
              <button
              type="button"
              className="designer-linkbtn"
              onClick={() => navigate("/agents")}
            >
              View AI Team →
            </button>
          </div>
          <p className="designer-panel__sub">
            Everything you need to create, test and manage designs for your business.
          </p>

          {/* Image generation is reported honestly: this build configures no
              image provider, so the capability is stated as unavailable rather
              than advertised. */}
          {workspace?.load.status && designerStatus && (
            <p className="designer-capnote">
              <UiIcon
                name={designerStatus.image_generation.status === "completed" ? "image" : "alert"}
                size={14}
              />
              Image generation:{" "}
              <strong>{designerStatus.image_generation.status}</strong>
              {designerStatus.image_generation.status !== "completed" &&
                ` — ${designerStatus.image_generation.reason}`}
            </p>
          )}

            <div className="designer-caps">
              {CAPABILITIES.map((c) => (
                <div key={c.title} className="designer-cap">
                  <span
                    className={`designer-cap__icon designer-cap__icon--${c.tone}`}
                    aria-hidden="true"
                  >
                    <UiIcon name={c.icon} size={20} />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <h3 className="designer-cap__title">{c.title}</h3>
                    <p className="designer-cap__desc">{c.desc}</p>
                  </div>
                  <span className="designer-cap__arrow" aria-hidden="true">
                    <UiIcon name="arrow-right" size={15} />
                  </span>
                </div>
              ))}
            </div>
          </WindowPanel>

          {/* ── RECENT DESIGN OUTPUTS ─────────────────────────────── */}
          <WindowPanel title="recent.outputs" className="designer-span-full">
            <div className="designer-head">
              <h2 className="designer-head__title designer-ico-title">
                <UiIcon name="image" size={19} />
                Latest Design Outputs
              </h2>
              <button
                type="button"
                className="designer-linkbtn"
                onClick={() => navigate("/agents")}
              >
                View AI Team →
              </button>
            </div>
            <p className="designer-panel__sub">
              Structured briefs and versioned variants the Designer Agent stored, each labelled with
              its real kind and review state.
            </p>

            {!workspace?.load.briefs && !workspace?.load.assets ? (
              <p className="designer-empty">
                Stored outputs are unavailable right now — this backend did not return your design
                records. Nothing is shown rather than substituted.
              </p>
            ) : outputs.length > 0 ? (
              <div className="designer-outputs">
                {outputs.slice(0, 8).map((o) => {
                  const open = expandedOutput === o.id;
                  return (
                    <div key={o.id} className="designer-output">
                      <button
                        type="button"
                        className="designer-output__thumb"
                        onClick={() => setExpandedOutput(open ? null : o.id)}
                        aria-expanded={open}
                        aria-label={`${open ? "Hide" : "Show"} ${o.title}`}
                      >
                        {/* The plate is a TYPE plate for structured work, never
                            a stand-in for a generated image. */}
                        <Swatch id={o.id} className="designer-output__art" />
                        <span className="designer-output__kindlabel">{o.kindLabel}</span>
                        <span className={`designer-output__pill designer-output__pill--${o.pillTone}`}>
                          <UiIcon
                            name={
                              o.pillTone === "ok" ? "check" : o.pillTone === "accent" ? "alert" : "clock"
                            }
                            size={12}
                          />
                          {o.reviewText}
                        </span>
                      </button>

                      <div className="designer-output__body">
                        <div className="designer-output__row">
                          <h3 className="designer-output__title">
                            <UiIcon name={o.icon as UiIconName} size={14} />
                            {o.title}
                          </h3>
                          <button
                            type="button"
                            className="designer-output__more"
                            aria-label="Toggle output detail"
                            onClick={() => setExpandedOutput(open ? null : o.id)}
                          >
                            <UiIcon name="more" size={16} />
                          </button>
                        </div>
                        <p className="designer-output__meta">
                          {o.kindLabel}
                          {o.confidence !== null
                            ? ` · ${Math.round(o.confidence * 100)}% confidence in the brief`
                            : ""}
                        </p>
                        <p className="designer-output__meta">
                          {o.recordedAt
                            ? `Stored ${formatTimestamp(o.recordedAt)}`
                            : "Stored"}
                        </p>

                        {open && <p className="designer-output__detail">{o.detail}</p>}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="designer-empty">
                No design outputs yet. Start a design request above — the Designer Agent stores its
                creative briefs here once it has real signals to ground them in.
              </p>
            )}
          </WindowPanel>

          {/* ── RENDERED IMAGE OUTPUTS ────────────────────────────── */}
          {/* Only ever shown when a REAL image was validated and stored.
              There is no placeholder tile standing in for a generated
              creative: when nothing is stored, this says so plainly. */}
          <WindowPanel title="rendered.images" className="designer-span-full">
            <div className="designer-head">
              <div style={{ minWidth: 0 }}>
                <h2 className="designer-head__title designer-ico-title">
                  <UiIcon name="image" size={19} />
                  Rendered Images
                </h2>
                <p className="designer-panel__sub">
                  Real images stored for your design assets, each linked to the exact
                  version that produced it.
                </p>
              </div>
              {imageGen?.status === "available" ? (
                <span className="designer-capnote designer-capnote--inline">
                  <UiIcon name="check" size={13} />
                  Image generation ready ({imageGen.provider})
                </span>
              ) : null}
            </div>

            {/* ── Generate action ────────────────────────────────────
                One control for the whole panel, acting on the newest design
                asset. Disabled while a request is in flight so a double-click
                cannot create two generations. */}
            <div className="designer-genbar">
              <input
                type="text"
                className="designer-input"
                value={imagePrompt}
                onChange={(e) => setImagePrompt(e.target.value)}
                placeholder="Describe the image you want to generate (optional if an asset exists)"
                aria-label="Image description"
                disabled={genAvail.phase === "submitting"}
              />
              <button
                type="button"
                className="designer-btn designer-btn--primary"
                onClick={() => void onGenerate(newestAssetId, imagePrompt)}
                disabled={!genAvail.canSubmit}
                aria-busy={genAvail.phase === "submitting"}
              >
                {genAvail.phase === "submitting" ? (
                  <UiIcon name="pulse" size={14} />
                ) : (
                  <UiIcon name="image" size={14} />
                )}
                {genAvail.label}
              </button>
              <p
                className={`designer-genbar__msg designer-genbar__msg--${genAvail.tone}`}
                role={genAvail.phase === "failed" ? "alert" : "status"}
              >
                {genMsg}
              </p>
            </div>

            {!renderedAssets.length ? (
              <p className="designer-empty">
                {genAvail.phase === "unavailable" || genAvail.phase === "no_asset"
                  ? genAvail.message
                  : "No images yet. Use “Generate Image” to render and store a real creative for your newest design asset."}
              </p>
            ) : (
              <div className="designer-outputs">
                {renderedAssets.map((r) => (
                  <div key={r.id} className="designer-output">
                    <AuthenticatedImage renderedId={r.id} alt="A real rendered creative stored for this design asset" />
                    <div className="designer-output__body">
                      <div className="designer-output__row">
                        <h3 className="designer-output__title">
                          <UiIcon name="image" size={14} />
                          {r.asset?.title ?? "Rendered image"}
                        </h3>
                        <button
                          type="button"
                          className="designer-output__more"
                          aria-label={`Regenerate ${r.asset?.title ?? "this image"}`}
                          disabled={genAvail.phase === "submitting" || !genAvail.canSubmit}
                          onClick={() => void onGenerate(r.asset_id)}
                        >
                          <UiIcon name="pulse" size={16} />
                        </button>
                      </div>
                      <p className="designer-output__meta">
                        {r.width}×{r.height} · {r.provider} · {r.model}
                        {r.steps ? ` · ${r.steps} steps` : ""}
                      </p>
                      <p className="designer-output__meta">
                        {formatBytes(r.byte_size)} ·{" "}
                        {relativeTime(Date.parse(r.created_at ?? "") || null, now).toLowerCase()}
                      </p>
                      <p className="designer-output__meta">
                        Version {r.version_id.slice(0, 8)} ·{" "}
                        <button
                          type="button"
                          className="designer-linkbtn designer-linkbtn--inline"
                          onClick={() => void onRegenerate(r.asset_id)}
                          disabled={genAvail.phase === "submitting"}
                        >
                          Regenerate
                        </button>
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </WindowPanel>

          {/* ── ACTIVE DESIGN PROJECTS ────────────────────────────── */}
          <div id="designer-projects" style={{ display: "contents" }}>
            <WindowPanel title="active.projects" className="designer-span-projects">
              <div className="designer-head">
                <h2 className="designer-head__title designer-ico-title">
                  <UiIcon name="target" size={19} />
                  Active Design Projects
                </h2>
                <button type="button" className="designer-linkbtn" onClick={() => navigate("/agents")}>
                  View all projects →
                </button>
              </div>

              {/* Real persisted design projects. The "source" column names the genuine
                provenance of the work — a real AI Team cycle, debate or Growth
                Radar signal — and says "—" when there is none, rather than
                inventing a source. */}
              {!workspace?.load.projects ? (
                <p className="designer-empty">
                  Design projects are unavailable right now — this backend did not return them.
                </p>
              ) : projects.length > 0 ? (
                <div className="designer-tablewrap">
                  <table className="designer-table">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Updated</th>
                        <th aria-label="Row actions" />
                      </tr>
                    </thead>
                    <tbody>
                      {projects.slice(0, 8).map((p) => (
                        <tr key={p.id}>
                          <td>
                            <span className="designer-table__project">
                              <span
                                className="designer-table__chip"
                                style={{ background: paletteFor(p.id)[0] }}
                                aria-hidden="true"
                              />
                              <span className="designer-table__name">
                                <span>{p.title}</span>
                                {/* The real correlation id, shown only when it exists. The
                                    id's own "cycle" prefix is dropped so the
                                    label does not read "Cycle cycle-ab". */}
                                {p.analysis_cycle_id && (
                                  <span className="designer-table__type">
                                    AI Team {p.analysis_cycle_id.replace(/^cycle[-_]?/i, "")}
                                  </span>
                                )}
                                {!p.analysis_cycle_id && p.source_signal_type && (
                                  <span className="designer-table__type">
                                    From signal: {p.source_signal_type.replace(/_/g, " ")}
                                  </span>
                                )}
                              </span>
                            </span>
                          </td>
                          <td className="designer-table__type">
                            {p.project_type.replace(/_/g, " ")}
                          </td>
                          <td>
                            <span
                              className={
                                p.status === "active"
                                  ? "designer-table__state designer-table__state--ok"
                                  : "designer-table__state"
                              }
                            >
                              ● {p.status}
                            </span>
                          </td>
                          <td className="designer-table__when">
                            {p.updated_at
                              ? relativeTime(Date.parse(p.updated_at) || null, now).toLowerCase()
                              : "—"}
                          </td>
                          <td>
                            {/* Opens the REAL AI Team cycle this project belongs
                                to; falls back to the AI Team page when no cycle
                                exists, rather than fabricating an identifier. */}
                            <button
                              type="button"
                              className="designer-output__more"
                              aria-label={`Open ${p.title}`}
                              onClick={() => navigate("/agents")}
                            >
                              <UiIcon name="more" size={16} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="designer-empty">
                  No design projects yet — start a design request to create one.
                </p>
              )}
            </WindowPanel>
          </div>

          {/* ── AGENT ACTIVITY ────────────────────────────────────── */}
          <WindowPanel title="agent.activity" className="designer-span-activity">
            <div className="designer-head">
              <h2 className="designer-head__title designer-ico-title">
                <UiIcon name="pulse" size={19} />
                Recent Activity
              </h2>
              <button type="button" className="designer-linkbtn" onClick={() => navigate("/agents")}>
                View all activity →
              </button>
            </div>

            {/* Genuine persisted events only: real projects, briefs and agent runs with
                their real timestamps. An action that was merely PROPOSED is
                never described as executed. */}
            {!workspace?.load.activity ? (
              <p className="designer-empty">
                Activity is unavailable right now — this backend did not return your Designer
                Agent events.
              </p>
            ) : activity.length > 0 ? (
              <ul className="designer-activity">
                {activity.slice(0, 8).map((item) => (
                  <li key={item.id} className="designer-activity__row">
                    <span
                      className={`designer-activity__badge designer-activity__badge--${activityBadgeTone(item)}`}
                      aria-hidden="true"
                    >
                      <UiIcon name={activityIcon(item)} size={13} />
                    </span>
                    <div style={{ minWidth: 0 }}>
                      <p className="designer-activity__title">{item.title}</p>
                      <p className="designer-activity__detail">
                        {designerActivityDetail(item)}
                      </p>
                    </div>
                    <span className="designer-activity__when">
                      {item.at
                        ? relativeTime(Date.parse(item.at) || null, now).toLowerCase()
                        : "—"}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="designer-empty">
                No activity yet — run the Designer Agent to see its real activity here.
              </p>
            )}
          </WindowPanel>
        </div>

        {/* Compact finishing strip — page content, not site chrome. The shared
         * global SiteFooter still renders below via PublicLayout. */}
        <div className="designer-signoff">
          <span>Designer Agent · autonomous creative partner</span>
          <span>Research → Create → Validate → Deliver</span>
        </div>
      </div>
    </div>
  );
}
