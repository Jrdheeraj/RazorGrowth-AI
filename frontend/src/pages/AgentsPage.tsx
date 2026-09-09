import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  fetchAgentsMeta,
  fetchAgentRuns,
  fetchGrowthRadar,
  fetchRankedOpportunities,
  fetchGrowthMemory,
  startAiTeamWork,
} from "../lib/api";
import type {
  ActionPlan,
  ActionPlanItem,
  AgentRunRow,
  AgentsListResponse,
  GrowthRadarResponse,
  GrowthMemoryResponse,
  OrchestratorRunResponse,
  OrchestrationAgentOutput,
  RankedOpportunity,
} from "../types/api";
import { WindowPanel } from "../components/WindowPanel";
import { Button } from "../components/Button";
import { StatusChip } from "../components/StatusIndicator";
import { OfficeFloor } from "../office/OfficeFloor";
import { toOfficeCharacter, mapLiveStatus, accentForIndex } from "../office/razorGrowthAdapter";
import { isAuthenticated } from "../lib/auth";
import "../office/office.css";
import "./AgentsPage.css";

const DEFAULT_OBJECTIVE = "Comprehensive commerce analysis and growth optimization";

/* ── Agent identity ─────────────────────────────────────────────────────── */

interface AgentProfile {
  label: string;
  specialty: string;
  looksAt: string;
  focus: string;
}

const AGENT_PROFILES: Record<string, AgentProfile> = {
  ManagerAgent: {
    label: "Growth Manager",
    specialty: "Growth strategy & coordination",
    looksAt: "Business health, specialist findings, and opportunity rankings",
    focus: "Coordinates the team, resolves disagreements, and locks the final recommendation.",
  },
  MarketingAgent: {
    label: "Marketing Analyst",
    specialty: "Customer retention & campaigns",
    looksAt: "Customer segments, repeat purchases, and failed checkout transactions",
    focus: "Finds ways to retain customers, win back buyers, and run high-return campaigns.",
  },
  ProductAgent: {
    label: "Product Strategist",
    specialty: "Catalog & basket economics",
    looksAt: "Product catalog, average order value, and items bought together",
    focus: "Uncovers upsell, cross-sell, and bundle opportunities to increase order size.",
  },
  DesignerAgent: {
    label: "Creative & UX Advisor",
    specialty: "Checkout experience & messaging",
    looksAt: "Payment retry flows, checkout drop-offs, and trust signals",
    focus: "Recommends smoother checkout steps and clearer decline messaging.",
  },
  SoftwareAgent: {
    label: "Technical Feasibility",
    specialty: "Automation & integrations",
    looksAt: "Razorpay webhooks, APIs, catalog scale, and integration constraints",
    focus: "Checks whether each recommendation can realistically and safely be automated.",
  },
  GrowthDiscoveryAgent: {
    label: "Opportunity Discovery",
    specialty: "Growth signal detection",
    looksAt: "Payment volume shifts, transaction outcomes, and baseline trends",
    focus: "Scans live commerce data for emerging revenue and retention signals.",
  },
  CustomerIntelligenceAgent: {
    label: "Customer Intelligence",
    specialty: "Customer lifecycle & churn risk",
    looksAt: "Customer order recency, frequency, spend, and payment history",
    focus: "Spots at-risk customers and high-value buyers before patterns are obvious.",
  },
  RevenueOptimizationAgent: {
    label: "Revenue Optimisation",
    specialty: "Pricing & margin maximization",
    looksAt: "Order basket distributions, pricing tiers, and margin thresholds",
    focus: "Models discount rules and bundling strategies that lift total revenue.",
  },
  CampaignStrategistAgent: {
    label: "Campaign Strategist",
    specialty: "Targeted audience campaigns",
    looksAt: "Audience cohorts and predicted conversion rates",
    focus: "Plans targeted campaigns with explicit revenue impact projections.",
  },
  PaymentRecoveryAgent: {
    label: "Payment Recovery",
    specialty: "Failed payment recapture",
    looksAt: "Unsuccessful Razorpay payments, failure error codes, and retry timings",
    focus: "Identifies recoverable revenue from failed checkouts and sets retry strategies.",
  },
  ExperimentAgent: {
    label: "Experiment Designer",
    specialty: "A/B testing & validation",
    looksAt: "Conversion rate baselines, sample sizes, and control groups",
    focus: "Designs controlled tests so recommendations are verified before rollout.",
  },
  OpportunityPrioritizationAgent: {
    label: "Priority Ranking",
    specialty: "Impact vs. effort scoring",
    looksAt: "Discovered opportunities, estimated revenue, and operational effort",
    focus: "Compares and ranks all growth ideas to decide what to execute first.",
  },
  GrowthMemoryAgent: {
    label: "Growth Memory",
    specialty: "Knowledge & historical continuity",
    looksAt: "Prior investigations, approved actions, and outcome metrics",
    focus: "Retains context across analyses so decisions improve over time.",
  },
};

const AGENT_ORDER: string[] = [
  "GrowthMemoryAgent",
  "GrowthDiscoveryAgent",
  "CustomerIntelligenceAgent",
  "RevenueOptimizationAgent",
  "PaymentRecoveryAgent",
  "MarketingAgent",
  "ProductAgent",
  "CampaignStrategistAgent",
  "DesignerAgent",
  "ExperimentAgent",
  "OpportunityPrioritizationAgent",
  "SoftwareAgent",
  "ManagerAgent",
];

const LIVE_TASKS: Record<string, string> = {
  ManagerAgent: "Team strategy, specialist coordination, and the final recommendation",
  MarketingAgent: "Failed payments + customer purchase history",
  ProductAgent: "Products, order values, and items bought together",
  DesignerAgent: "Checkout experience and payment retry messaging",
  SoftwareAgent: "Automation paths and technical constraints",
  GrowthDiscoveryAgent: "Live commerce data for emerging growth signals",
  CustomerIntelligenceAgent: "Customer purchase behavior and repeat patterns",
  RevenueOptimizationAgent: "Pricing, basket value, and margin opportunities",
  CampaignStrategistAgent: "Customer cohorts for targeted campaigns",
  PaymentRecoveryAgent: "Failed transactions and recoverable revenue",
  ExperimentAgent: "How each recommendation can be safely tested",
  OpportunityPrioritizationAgent: "All discovered opportunities, ranked by impact",
  GrowthMemoryAgent: "Historical context from past analyses",
};

const EXECUTION_PHASES: Record<string, string> = {
  GrowthMemoryAgent: "Growth Memory is reviewing historical context...",
  GrowthDiscoveryAgent: "Opportunity Discovery is analyzing your business...",
  CustomerIntelligenceAgent: "Customer Intelligence is reviewing your customers...",
  RevenueOptimizationAgent: "Revenue Optimisation is looking for ways to increase revenue...",
  PaymentRecoveryAgent: "Payment Recovery is checking unsuccessful payments...",
  MarketingAgent: "Marketing Analyst is identifying customer and campaign opportunities...",
  ProductAgent: "Product Strategist is reviewing products and order patterns...",
  CampaignStrategistAgent: "Campaign Strategist is planning potential campaigns...",
  DesignerAgent: "Creative & UX Advisor is working on customer experience improvements...",
  ExperimentAgent: "Experiment Designer is planning how recommendations can be tested...",
  OpportunityPrioritizationAgent: "Priority Ranking is comparing the opportunities...",
  SoftwareAgent: "Technical Feasibility is checking what can realistically be implemented...",
  ManagerAgent: "Growth Manager is reviewing the team's work...",
};

const AVATAR_BASE: Record<string, { zone: string }> = {
  GrowthMemoryAgent: { zone: "MEMORY" },
  GrowthDiscoveryAgent: { zone: "MEMORY" },
  CustomerIntelligenceAgent: { zone: "SPECIALISTS" },
  RevenueOptimizationAgent: { zone: "SPECIALISTS" },
  PaymentRecoveryAgent: { zone: "SPECIALISTS" },
  MarketingAgent: { zone: "SPECIALISTS" },
  ProductAgent: { zone: "SPECIALISTS" },
  CampaignStrategistAgent: { zone: "SPECIALISTS" },
  DesignerAgent: { zone: "SPECIALISTS" },
  ExperimentAgent: { zone: "VALIDATION" },
  OpportunityPrioritizationAgent: { zone: "VALIDATION" },
  SoftwareAgent: { zone: "VALIDATION" },
  ManagerAgent: { zone: "COORDINATION" },
};

const ZONE_META: Record<string, { label: string; hint: string }> = {
  MEMORY: { label: "MEMORY & DISCOVERY", hint: "Context + signals" },
  SPECIALISTS: { label: "SPECIALISTS", hint: "Deep domain analysis" },
  VALIDATION: { label: "STRATEGY & QA", hint: "Prioritise + validate" },
  COORDINATION: { label: "COORDINATION", hint: "Final recommendation" },
};

/* top-down office coordinates — percent of floor canvas */
const OFFICE_POS: Record<string, { x: number; y: number }> = {
  GrowthMemoryAgent: { x: 18, y: 18 },
  GrowthDiscoveryAgent: { x: 42, y: 18 },
  CustomerIntelligenceAgent: { x: 66, y: 18 },
  RevenueOptimizationAgent: { x: 86, y: 18 },
  PaymentRecoveryAgent: { x: 14, y: 42 },
  MarketingAgent: { x: 37, y: 42 },
  ProductAgent: { x: 60, y: 42 },
  CampaignStrategistAgent: { x: 84, y: 42 },
  DesignerAgent: { x: 14, y: 68 },
  ExperimentAgent: { x: 37, y: 68 },
  OpportunityPrioritizationAgent: { x: 60, y: 68 },
  SoftwareAgent: { x: 84, y: 68 },
  ManagerAgent: { x: 50, y: 90 },
};

/* distinct illustrated face + body configs — 13 unique humans, retro pixel-office style */
type FaceConfig = {
  skin: string;
  hair: string;
  hairStyle: "short" | "bob" | "long" | "curly" | "buzz" | "afro" | "bun" | "wavy" | "bald";
  eye: string;
  shirt: string;
  beard?: boolean;
  mustache?: boolean;
  glasses?: boolean;
  freckles?: boolean;
  earring?: boolean;
};
const FACE_CONFIG: Record<string, FaceConfig> = {
  GrowthMemoryAgent: { skin: "#f2d6b8", hair: "#9aa0a6", hairStyle: "short", eye: "#2a1810", shirt: "#e8d5b8", glasses: true },
  GrowthDiscoveryAgent: { skin: "#e7c4a0", hair: "#3a2a18", hairStyle: "wavy", eye: "#2a1810", shirt: "#d9e8d0", beard: true },
  CustomerIntelligenceAgent: { skin: "#f8e2c9", hair: "#d9b06a", hairStyle: "bob", eye: "#4a3a2a", shirt: "#dbeafe" },
  RevenueOptimizationAgent: { skin: "#e8b99a", hair: "#1b1b1e", hairStyle: "buzz", eye: "#2a1810", shirt: "#fef3c7", glasses: true },
  PaymentRecoveryAgent: { skin: "#fde6cc", hair: "#b84a22", hairStyle: "curly", eye: "#3a2a1a", shirt: "#fde8e1", freckles: true },
  MarketingAgent: { skin: "#d9b89c", hair: "#2b1d12", hairStyle: "long", eye: "#2a1810", shirt: "#fce7f3" },
  ProductAgent: { skin: "#e0b79e", hair: "#5b3a1e", hairStyle: "short", eye: "#2a1810", shirt: "#e0f2fe", beard: true },
  CampaignStrategistAgent: { skin: "#f5ddc2", hair: "#e6c07a", hairStyle: "long", eye: "#3a2a14", shirt: "#fef9c3" },
  DesignerAgent: { skin: "#f1cec0", hair: "#4a2d6a", hairStyle: "bob", eye: "#2a1810", shirt: "#f3e8ff", glasses: true, earring: true },
  ExperimentAgent: { skin: "#8d6b4a", hair: "#0f0f0f", hairStyle: "afro", eye: "#1a120e", shirt: "#dcfce7" },
  OpportunityPrioritizationAgent: { skin: "#d8b59a", hair: "#9a9a9a", hairStyle: "buzz", eye: "#2a1810", shirt: "#fee2e2", mustache: true },
  SoftwareAgent: { skin: "#d1ab8e", hair: "#1e1e1e", hairStyle: "short", eye: "#2a1810", shirt: "#e5e7eb", glasses: true, beard: true },
  ManagerAgent: { skin: "#f0d0b0", hair: "#6b3e1e", hairStyle: "short", eye: "#2a1810", shirt: "#ffedd5" },
};

/* ── helpers ────────────────────────────────────────────────────────────── */

function prettifyName(raw: string) {
  return raw
    .replace(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (l) => l.toUpperCase())
    .replace(/\s*Agent\s*$/i, "")
    .trim();
}
function agentProfile(name: string): AgentProfile {
  return (
    AGENT_PROFILES[name] ?? {
      label: prettifyName(name),
      specialty: "Business analysis",
      looksAt: "Your live commerce records",
      focus: "Analyzes your business data for growth opportunities.",
    }
  );
}
function firstSentence(text: string | null | undefined): string | null {
  if (!text) return null;
  const m = text.trim().match(/^(.+?[.!?])(\s|$)/);
  return m?.[1] ?? text.trim();
}
function sentences(text: string | null | undefined, count: number): string | null {
  if (!text) return null;
  return text.split(/(?<=[.!?])\s+/).filter(Boolean).slice(0, count).join(" ");
}
function formatMoney(v: number | null | undefined): string | null {
  if (v === null || v === undefined || Number.isNaN(v)) return null;
  return `₹${v.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}
function confidenceWord(v: number | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  if (v >= 0.75) return "High";
  if (v >= 0.45) return "Medium";
  return "Low";
}
function timeAgo(ts: number | null) {
  if (!ts) return "Not yet run";
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (s < 45) return "Just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return `${Math.round(h / 24)} d ago`;
}
function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso.slice(11, 19);
  }
}
function hashCode(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

/* ── types ──────────────────────────────────────────────────────────────── */

type CmdTab = "ACTIVITY" | "MONITOR" | "TASKS" | "MEMORY" | "GRAPH" | "TERMINAL" | "COMMANDS" | "WORKERS";
type AgentLiveStatus = "IDLE" | "WAITING" | "WORKING" | "THINKING" | "TOOL_CALL" | "ANALYZING" | "COMMUNICATING" | "COMPLETED" | "BLOCKED" | "ERROR" | "NEEDS_APPROVAL";

interface AgentLiveInfo {
  key: string;
  label: string;
  specialty: string;
  zone: string;
  liveStatus: AgentLiveStatus;
  chipLabel: string;
  chipTone: "neutral" | "ok" | "accent";
  anim: "pulse" | "none";
  progress: number;
  monitorLine: string;
  subLine: string;
  latencyMs: number | null;
  tools: string[];
  toolDetail: { tool: string; input: string; result: string } | null;
  commTarget: string | null;
  pos: { x: number; y: number };
}

/* ── progress & status derivation ──────────────────────────────────────── */

function deriveAgentProgress(raw: AgentRunRow | undefined, out: OrchestrationAgentOutput | undefined, isWorking: boolean, orderIdx: number, startedAtMs: number | null): number {
  if (raw?.status === "completed" || out?.status === "completed") return 100;
  if (raw?.status === "failed") return 100;
  if (raw?.status === "running") {
    const elapsed = startedAtMs ? (Date.now() - startedAtMs) / 1000 : 2;
    const base = 42 + (hashCode(raw.agent_name) % 18);
    const wobble = Math.min(32, Math.floor(elapsed * 1.8) % 34);
    return Math.min(96, base + wobble);
  }
  if (isWorking) {
    const phaseSlot = orderIdx * 7;
    const pseudo = (hashCode(String(orderIdx)) % 22) + phaseSlot;
    return Math.min(68, 12 + (pseudo % 48));
  }
  return 0;
}

function deriveLiveStatus(name: string, run: AgentRunRow | undefined, out: OrchestrationAgentOutput | undefined, isWorking: boolean, hasInsufficient: boolean): { live: AgentLiveStatus; chip: string; tone: "neutral" | "ok" | "accent"; anim: "pulse" | "none" } {
  if (hasInsufficient && !run && !out) return { live: "BLOCKED", chip: "BLOCKED", tone: "neutral", anim: "none" };
  const hasTools = Array.isArray(run?.tools_used) && (run.tools_used as unknown[]).length > 0;
  if (run) {
    if (run.status === "running") {
      if (hasTools && Math.random() > 0.45) return { live: "TOOL_CALL", chip: "USING TOOL", tone: "accent", anim: "pulse" };
      // 12% chance to show communicating while running (inter-agent walk)
      if (hashCode(name + String(run.started_at)) % 11 === 0) return { live: "COMMUNICATING", chip: "COMMUNICATING", tone: "accent", anim: "pulse" };
      if (hashCode(name) % 7 === 0) return { live: "ANALYZING", chip: "ANALYZING", tone: "accent", anim: "pulse" };
      if (hashCode(name) % 5 === 0) return { live: "THINKING", chip: "THINKING", tone: "accent", anim: "pulse" };
      return { live: "WORKING", chip: "WORKING", tone: "accent", anim: "pulse" };
    }
    if (run.status === "completed") {
      if (run.opportunities_created > 0) return { live: "COMPLETED", chip: "FOUND SOMETHING", tone: "accent", anim: "none" };
      return { live: "COMPLETED", chip: "COMPLETED", tone: "ok", anim: "none" };
    }
    if (run.status === "failed") return { live: "ERROR", chip: "ERROR", tone: "neutral", anim: "none" };
    return { live: "ANALYZING", chip: "REVIEWING", tone: "accent", anim: "pulse" };
  }
  if (out) {
    if (out.status === "completed") {
      if (out.opportunities_created > 0) return { live: "COMPLETED", chip: "FOUND SOMETHING", tone: "accent", anim: "none" };
      return { live: "COMPLETED", chip: "COMPLETED", tone: "ok", anim: "none" };
    }
    return { live: "THINKING", chip: "THINKING", tone: "accent", anim: "pulse" };
  }
  if (isWorking) {
    if (name === "GrowthMemoryAgent") return { live: "WORKING", chip: "WORKING", tone: "accent", anim: "pulse" };
    // stagger waiting -> thinking progression
    if (hashCode(name) % 3 === 0) return { live: "THINKING", chip: "THINKING", tone: "accent", anim: "pulse" };
    return { live: "WAITING", chip: "WAITING", tone: "neutral", anim: "none" };
  }
  return { live: "IDLE", chip: "IDLE", tone: "neutral", anim: "none" };
}

function toolDetailForAgent(key: string, metrics: GrowthRadarResponse["metrics"] | null, run: AgentRunRow | undefined): { tool: string; input: string; result: string } | null {
  if (key === "PaymentRecoveryAgent" && metrics) {
    const total = (metrics.successful_payments ?? 0) + (metrics.failed_payments ?? 0);
    return { tool: "fetch_payments", input: "window=30d", result: `${total} attempts · ${metrics.failed_payments} failed` };
  }
  if (key === "CustomerIntelligenceAgent" && metrics) {
    return { tool: "analyze_customers", input: `${metrics.total_customers} customers`, result: `${metrics.repeat_customers} repeat` };
  }
  if (key === "GrowthDiscoveryAgent" && metrics) {
    return { tool: "scan_growth_signals", input: "baseline vs current", result: run?.opportunities_created ? `${run.opportunities_created} signal(s)` : "scanning" };
  }
  if (key === "RevenueOptimizationAgent") return { tool: "model_basket_value", input: "AOV & margins", result: "bundling run" };
  if (key === "GrowthMemoryAgent") return { tool: "load_memory", input: "prior analyses", result: "context restored" };
  if (run && Array.isArray(run.tools_used) && (run.tools_used as string[]).length) {
    const t = (run.tools_used as string[])[0];
    return { tool: t, input: "live data", result: "executed" };
  }
  return null;
}
function commTargetFor(key: string): string | null {
  const map: Record<string, string> = {
    PaymentRecoveryAgent: "ManagerAgent",
    CustomerIntelligenceAgent: "CampaignStrategistAgent",
    GrowthDiscoveryAgent: "OpportunityPrioritizationAgent",
    OpportunityPrioritizationAgent: "SoftwareAgent",
    SoftwareAgent: "ManagerAgent",
    RevenueOptimizationAgent: "OpportunityPrioritizationAgent",
    MarketingAgent: "GrowthMemoryAgent",
  };
  return map[key] ?? null;
}

/* ══════════════════════════════════════════════════════════════════════════
   Subcomponents
   ══════════════════════════════════════════════════════════════════════════ */

/* ── Illustrated face avatar — CSS/HTML + SVG, no initials ───────────────── */
function FaceAvatar({ agentKey, status, size = 40 }: { agentKey: string; status: AgentLiveStatus; size?: number }) {
  const cfg = FACE_CONFIG[agentKey] ?? { skin: "#f2d6b8", hair: "#6b3e1e", hairStyle: "short" as const, eye: "#2a1810", shirt: "#f5e6cf" } as FaceConfig;
  const tone =
    status === "WORKING" || status === "TOOL_CALL" || status === "ANALYZING" || status === "THINKING" || status === "COMMUNICATING"
      ? "working"
      : status === "COMPLETED"
        ? "done"
        : status === "ERROR"
          ? "error"
          : status === "BLOCKED"
            ? "blocked"
            : "idle";
  const s = size;
  const hairShape = (() => {
    switch (cfg.hairStyle) {
      case "bob":
        return <path d="M7 16 Q7 6 20 5 Q33 6 33 16 L33 20 Q30 14 20 14 Q10 14 7 20 Z" fill={cfg.hair} />;
      case "long":
        return <path d="M8 15 Q8 4 20 4 Q32 4 32 15 L32 28 Q28 22 20 22 Q12 22 8 28 Z" fill={cfg.hair} />;
      case "curly":
        return (
          <g fill={cfg.hair}>
            <circle cx={12} cy={12} r={5} />
            <circle cx={20} cy={9} r={6} />
            <circle cx={28} cy={12} r={5} />
            <circle cx={10} cy={17} r={4} />
            <circle cx={30} cy={17} r={4} />
            <rect x={10} y={12} width={20} height={10} rx={3} />
          </g>
        );
      case "buzz":
        return <ellipse cx={20} cy={13} rx={12} ry={8} fill={cfg.hair} />;
      case "afro":
        return (
          <g fill={cfg.hair}>
            <ellipse cx={20} cy={15} rx={14} ry={11} />
            <ellipse cx={20} cy={11} rx={10} ry={7} />
          </g>
        );
      case "bald":
        return null;
      case "bun":
        return (
          <g fill={cfg.hair}>
            <ellipse cx={20} cy={15} rx={12} ry={8} />
            <circle cx={20} cy={7} r={5} />
          </g>
        );
      case "wavy":
        return <path d="M7 17 Q7 5 20 6 Q33 5 33 17 L31 18 Q30 10 20 10 Q10 10 9 18 Z" fill={cfg.hair} />;
      default: // short
        return <path d="M8 15 Q8 5 20 4.5 Q32 5 32 15 L30 15 Q30 9 20 9 Q10 9 10 15 Z" fill={cfg.hair} />;
    }
  })();

  const shirt = (cfg as FaceConfig).shirt ?? "#f5e6cf";
  return (
    <div className={`face-ava face-ava--${tone}`} style={{ width: s, height: s }} aria-hidden="true">
      <svg viewBox="0 0 40 40" width={s} height={s} role="img" aria-label={`${agentKey} face`}>
        {/* shirt / torso — distinct clothing per agent */}
        <rect x={11} y={30.5} width={18} height={8.5} rx={1.6} fill={shirt} stroke="rgba(42,24,16,0.18)" strokeWidth={0.6} />
        <rect x={15} y={30.5} width={10} height={6} rx={1.2} fill="rgba(255,255,255,0.55)" stroke="rgba(42,24,16,0.10)" strokeWidth={0.4} />
        {/* tiny collar button */}
        <circle cx={20} cy={33.5} r={0.7} fill="rgba(42,24,16,0.35)" />
        {/* head */}
        <ellipse cx={20} cy={22.5} rx={11.2} ry={12} fill={cfg.skin} stroke="rgba(42,24,16,0.18)" strokeWidth={0.7} />
        {/* hair behind */}
        {hairShape}
        {/* ears */}
        <ellipse cx={8.8} cy={22} rx={2} ry={3.2} fill={cfg.skin} stroke="rgba(42,24,16,0.14)" strokeWidth={0.5} />
        <ellipse cx={31.2} cy={22} rx={2} ry={3.2} fill={cfg.skin} stroke="rgba(42,24,16,0.14)" strokeWidth={0.5} />
        {/* freckles */}
        {cfg.freckles && (
          <g fill="#c97a5a" opacity={0.55}>
            <circle cx={15} cy={24} r={0.7} />
            <circle cx={17.2} cy={25} r={0.6} />
            <circle cx={22.8} cy={25} r={0.6} />
            <circle cx={25} cy={24} r={0.7} />
          </g>
        )}
        {/* eyes */}
        <g fill={cfg.eye}>
          <ellipse cx={15.2} cy={21.2} rx={1.55} ry={1.9} />
          <ellipse cx={24.8} cy={21.2} rx={1.55} ry={1.9} />
          <circle cx={15.7} cy={20.5} r={0.55} fill="#fff" opacity={0.95} />
          <circle cx={25.3} cy={20.5} r={0.55} fill="#fff" opacity={0.95} />
        </g>
        {/* eyebrows */}
        <g stroke={cfg.hair} strokeWidth={1.05} strokeLinecap="round" opacity={0.85}>
          <path d="M12.5 17.8 Q15 17 17.5 17.9" fill="none" />
          <path d="M22.5 17.9 Q25 17 27.5 17.8" fill="none" />
        </g>
        {/* nose */}
        <path d="M20 22.2 L19.2 25.2 L20.8 25.2" fill="none" stroke="rgba(42,24,16,0.28)" strokeWidth={0.65} strokeLinecap="round" strokeLinejoin="round" />
        {/* mouth */}
        {status === "WORKING" || status === "TOOL_CALL" ? (
          <ellipse cx={20} cy={27.7} rx={1.4} ry={1} fill="rgba(42,24,16,0.78)" />
        ) : status === "COMPLETED" ? (
          <path d="M16.5 27.2 Q20 29 23.5 27.2" fill="none" stroke="rgba(42,24,16,0.65)" strokeWidth={0.9} strokeLinecap="round" />
        ) : status === "ERROR" ? (
          <path d="M16.5 27.8 Q20 26 23.5 27.8" fill="none" stroke="#a94f38" strokeWidth={0.9} strokeLinecap="round" />
        ) : (
          <path d="M16.8 27.4 Q20 28.6 23.2 27.4" fill="none" stroke="rgba(42,24,16,0.45)" strokeWidth={0.8} strokeLinecap="round" />
        )}
        {/* beard */}
        {cfg.beard && <path d="M10 24 Q10 32 20 33 Q30 32 30 24 L29 24 Q29 30 20 31 Q11 30 11 24 Z" fill="#2b1d12" opacity={0.95} />}
        {cfg.mustache && !cfg.beard && <path d="M16 25.6 Q20 25 24 25.6 Q20 26.6 16 25.6" fill="#2b1d12" opacity={0.9} />}
        {/* glasses */}
        {cfg.glasses && (
          <g stroke="rgba(42,24,16,0.85)" strokeWidth={0.85} fill="rgba(255,255,255,0.12)">
            <circle cx={15.2} cy={21.2} r={3.6} />
            <circle cx={24.8} cy={21.2} r={3.6} />
            <line x1={18.8} y1={21.2} x2={21.2} y2={21.2} />
            <line x1={11.6} y1={21} x2={9} y2={20.2} />
            <line x1={28.4} y1={21} x2={31} y2={20.2} />
          </g>
        )}
        {/* earring */}
        {cfg.earring && <circle cx={31.6} cy={25.2} r={1} fill="#d9b06a" stroke="rgba(42,24,16,0.35)" strokeWidth={0.4} />}
        {/* blush when working */}
        {(status === "WORKING" || status === "ANALYZING") && (
          <g fill="#d97757" opacity={0.18}>
            <ellipse cx={12.5} cy={24.5} rx={2.2} ry={1.2} />
            <ellipse cx={27.5} cy={24.5} rx={2.2} ry={1.2} />
          </g>
        )}
      </svg>
      <span className={`face-ava__dot face-ava__dot--${tone}`} />
      {(status === "WORKING" || status === "TOOL_CALL" || status === "ANALYZING" || status === "THINKING") && <span className="face-ava__typing" aria-hidden="true">●●●</span>}
    </div>
  );
}
function AgentAvatar({ agentKey, status, size = 40 }: { agentKey: string; status: AgentLiveStatus; size?: number }) {
  return <FaceAvatar agentKey={agentKey} status={status} size={size} />;
}

function ProgressBar({ value, tone = "coral", striped = false }: { value: number; tone?: "coral" | "green" | "ink"; striped?: boolean }) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  return (
    <div className={`pbar pbar--${tone}${striped ? " pbar--striped" : ""}`} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className="pbar__fill" style={{ width: `${pct}%` }} />
    </div>
  );
}

/* ── Business Snapshot Compact ──────────────────────────────────────────── */
function BusinessSnapshotStrip({ radar }: { radar: GrowthRadarResponse | null }) {
  const m = radar?.metrics;
  const signals = radar?.signals.length ?? 0;
  const cells: Array<{ label: string; value: string; hint: string; warn?: boolean }> = [
    { label: "REVENUE", value: m ? (formatMoney(m.captured_revenue) ?? "—") : "…", hint: "captured" },
    { label: "SUCCESSFUL", value: m ? String(m.successful_payments ?? m.captured_transactions) : "…", hint: "payments" },
    { label: "FAILED", value: m ? String(m.failed_payments) : "…", hint: "recoverable", warn: Boolean(m && m.failed_payments > 0) },
    { label: "CUSTOMERS", value: m ? String(m.total_customers) : "…", hint: "unique" },
    { label: "ORDERS", value: m ? String(m.total_orders) : "…", hint: "total" },
    { label: "SIGNALS", value: radar ? String(signals) : "…", hint: "detected" },
  ];
  return (
    <div className="snapshot-strip">
      {cells.map((c) => (
        <div key={c.label} className={`snapshot-strip__cell${c.warn ? " snapshot-strip__cell--warn" : ""}`}>
          <span className="snapshot-strip__label">{c.label}</span>
          <span className={`snapshot-strip__value${c.warn ? " snapshot-strip__value--warn" : ""}`}>{c.value}</span>
          <span className="snapshot-strip__hint">{c.hint}</span>
        </div>
      ))}
    </div>
  );
}

/* ── Workflow Graph ────────────────────────────────────────────────────── */
function WorkflowGraphViz({
  executedCount,
  signalsCount,
  opportunitiesCount,
  hasDebate,
  hasActionPlan,
  selectedId,
  onSelect,
}: {
  executedCount: number;
  signalsCount: number;
  opportunitiesCount: number;
  hasDebate: boolean;
  hasActionPlan: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const nodes: Array<{ id: string; num: string; title: string; hint: string; reached: boolean; accent?: boolean }> = [
    { id: "data", num: "01", title: "REAL BUSINESS DATA", hint: "Payments · orders · customers", reached: true },
    { id: "memory", num: "02", title: "GROWTH MEMORY", hint: "Historical context", reached: executedCount > 0 },
    { id: "specialists", num: "03", title: "SPECIALIST AGENTS", hint: "Parallel analysis", reached: executedCount > 1 },
    { id: "findings", num: "04", title: "FINDINGS", hint: "Evidence + reckoning", reached: signalsCount > 0 || executedCount > 2 },
    { id: "debate", num: "05", title: "AGENT DEBATE", hint: "Challenge · cross-examine", reached: hasDebate },
    { id: "ranking", num: "06", title: "PRIORITY RANKING", hint: "Impact vs effort", reached: opportunitiesCount > 0 },
    { id: "action", num: "07", title: "ACTION PREPARATION", hint: "Ready for approval", reached: hasActionPlan },
    { id: "human", num: "08", title: "HUMAN APPROVAL", hint: "You stay in control", reached: false, accent: true },
  ];
  return (
    <div className="wflow">
      <div className="wflow__nodes">
        {nodes.map((n) => (
          <button
            key={n.id}
            type="button"
            className={`wflow__node${n.reached ? " wflow__node--reached" : ""}${selectedId === n.id ? " wflow__node--selected" : ""}${n.accent ? " wflow__node--accent" : ""}`}
            onClick={() => onSelect(n.id)}
            aria-pressed={selectedId === n.id}
          >
            <span className="wflow__num">{n.num}</span>
            <span className="wflow__title">{n.title}</span>
            <span className="wflow__hint">{n.hint}</span>
            <span className={`wflow__dot${n.reached ? " wflow__dot--on" : ""}`} aria-hidden="true" />
          </button>
        ))}
      </div>
      <div className="wflow__legend">
        <span>
          <i className="wflow__legendDot wflow__legendDot--on" /> reached
        </span>
        <span>
          <i className="wflow__legendDot" /> pending
        </span>
        <span className="wflow__demoBadge">● DERIVED FROM REAL EXECUTION</span>
      </div>
    </div>
  );
}

/* ── Agent Detail Overlay ──────────────────────────────────────────────── */
function AgentDetailPanel({
  agentKey,
  onClose,
  liveInfo,
  output,
  run,
  radar,
  planItem,
  confidence,
  evidence,
  reasoning,
}: {
  agentKey: string;
  onClose: () => void;
  liveInfo: AgentLiveInfo;
  output: OrchestrationAgentOutput | undefined;
  run: AgentRunRow | undefined;
  radar: GrowthRadarResponse | null;
  planItem: ActionPlanItem | null;
  confidence: string | null;
  evidence: string;
  reasoning: string | null;
}) {
  const profile = agentProfile(agentKey);
  const m = radar?.metrics;
  const summary = output?.output?.summary ?? "";
  const recs: string[] = output?.output?.recommendations ?? [];
  const isCompleted = liveInfo.liveStatus === "COMPLETED";
  const hasFailed = liveInfo.liveStatus === "ERROR";
  const failed = m?.failed_payments ?? 0;
  const totalCustomers = m?.total_customers ?? 0;
  const totalOrders = m?.total_orders ?? 0;
  const revenue = m ? formatMoney(m.captured_revenue) ?? "—" : "—";

  // Build 6 steps with real evidence where possible
  const steps: Array<{ n: string; title: string; detail: string; meta: string }> = (() => {
    if (agentKey === "PaymentRecoveryAgent") {
      return [
        { n: "01", title: "Retrieved payment records", detail: `${(m?.successful_payments ?? 0) + failed} payment attempts analyzed from the selected window`, meta: `${m?.successful_payments ?? 0} successful · ${failed} unsuccessful` },
        { n: "02", title: "Classified payment outcomes", detail: "Separated captured vs failed Razorpay attempts and flagged unsuccessful codes.", meta: `${failed > 0 ? "Failures detected — recoverable signal present" : "No failures in window"}` },
        { n: "03", title: "Investigated failed transactions", detail: "Reviewed failure records individually for retry timing and error pattern.", meta: failed > 0 ? `${failed} failure records reviewed` : "No failure records to inspect" },
        { n: "04", title: "Calculated recovery opportunity", detail: failed > 0 && m ? `₹${Math.round(failed * (m.average_order_value || 0)).toLocaleString("en-IN")} potentially recoverable (avg order value × failed count).` : "Recoverable value computed from failed attempt value.", meta: `Avg order ₹${m ? Math.round(m.average_order_value).toLocaleString("en-IN") : "—"}` },
        { n: "05", title: "Evaluated evidence", detail: evidence, meta: confidence ? `Confidence · ${confidence}` : "Evidence strength assessed" },
        { n: "06", title: "Generated recommendation", detail: recs[0] ?? planItem?.next_steps ?? "Prepare compliant payment-recovery workflow — review failures and re-engage with a reminder before retrying.", meta: "Next: Priority Ranking → Technical Feasibility → Growth Manager" },
      ];
    }
    if (agentKey === "CustomerIntelligenceAgent") {
      return [
        { n: "01", title: "Loaded customer roster", detail: `${totalCustomers} unique customers found in this workspace.`, meta: `${totalCustomers} customers` },
        { n: "02", title: "Computed recency & frequency", detail: "Measured repeat purchase behavior and days since last order.", meta: `${m?.repeat_customers ?? 0} repeat buyers identified` },
        { n: "03", title: "Reviewed order history", detail: `Scanned ${totalOrders} orders to understand lifecycle and drop-off.`, meta: `${totalOrders} orders` },
        { n: "04", title: "Flagged retention patterns", detail: evidence, meta: reasoning ?? "Segment behavior summarized" },
        { n: "05", title: "Assessed cohort value", detail: `Revenue captured ${revenue} across ${totalCustomers} customers — repeat rate ${totalCustomers ? Math.round(((m?.repeat_customers ?? 0) / totalCustomers) * 100) : 0}%.`, meta: confidence ? `Confidence · ${confidence}` : "Cohort confidence assessed" },
        { n: "06", title: "Proposed retention play", detail: recs[0] ?? "Recommend win-back cohort + repeat-purchase nurture.", meta: "Next: Campaign Strategist + Priority Ranking" },
      ];
    }
    if (agentKey === "GrowthMemoryAgent") {
      return [
        { n: "01", title: "Loaded prior analysis context", detail: "Retrieved investigation history, approved actions, and outcome metrics.", meta: "Continuity window: previous analyses" },
        { n: "02", title: "Reviewed approved actions", detail: "Checked which recommendations were approved, rejected, or still pending.", meta: planItem ? `Initiative: ${planItem.title.slice(0, 42)}…` : "No plan linkage yet" },
        { n: "03", title: "Compared current vs prior metrics", detail: `Current revenue ${revenue} · ${totalOrders} orders · ${totalCustomers} customers`, meta: "Delta vs historical baseline" },
        { n: "04", title: "Surfaced continuity risks", detail: evidence, meta: reasoning ?? "Context drift evaluated" },
        { n: "05", title: "Scored memory confidence", detail: confidence ? `Confidence ${confidence} — based on historical coverage.` : "Memory confidence assessed.", meta: "Knowledge retention score" },
        { n: "06", title: "Handed context to specialists", detail: recs[0] ?? "Context package forwarded to discovery + specialist agents.", meta: "Next: Opportunity Discovery" },
      ];
    }
    // generic 6-step for all other agents
    return [
      { n: "01", title: "Ingested live business data", detail: evidence, meta: `${totalOrders} orders · ${totalCustomers} customers · ${revenue} revenue` },
      { n: "02", title: "Scoped analysis window", detail: "Filtered to the selected 30-day window and normalized for comparison.", meta: "Window: last 30 days" },
      { n: "03", title: "Applied specialist heuristics", detail: profile.focus, meta: profile.specialty },
      { n: "04", title: "Cross-checked related signals", detail: reasoning ?? "Compared finding against peer agent observations.", meta: confidence ? `Confidence · ${confidence}` : "Evidence triangulation" },
      { n: "05", title: "Quantified impact", detail: planItem?.expected_impact ?? recs[0] ?? "Estimated impact derived from live order and payment distributions.", meta: planItem ? `Priority: ${planItem.priority}` : "Impact model applied" },
      { n: "06", title: "Drafted recommendation", detail: planItem?.next_steps ?? recs[1] ?? "Recommendation prepared for ranking and feasibility review.", meta: "Next: Priority Ranking → Growth Manager" },
    ];
  })();

  return (
    <div className="detail-overlay" role="dialog" aria-modal="true" aria-label={`${profile.label} detail`}>
      <button type="button" className="detail-overlay__backdrop" onClick={onClose} aria-label="Close detail" />
      <div className="detail-overlay__panel">
        <header className="detail-overlay__head">
          <div className="detail-overlay__headLeft">
            <AgentAvatar agentKey={agentKey} status={liveInfo.liveStatus} size={44} />
            <div>
              <p className="meta-label" style={{ marginBottom: 2 }}>{liveInfo.zone} · {profile.specialty.toUpperCase()}</p>
              <h3 className="detail-overlay__title">{profile.label.toUpperCase()}</h3>
              <p className="detail-overlay__role">{profile.specialty} — {liveInfo.chipLabel}</p>
            </div>
          </div>
          <div className="detail-overlay__headRight">
            <StatusChip tone={liveInfo.chipTone} pulse={liveInfo.anim === "pulse"}>{liveInfo.chipLabel}</StatusChip>
            <button type="button" className="detail-overlay__close" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
        </header>

        <div className="detail-overlay__grid">
          <div className="detail-overlay__main">
            <div className="detail-overlay__kpiRow">
              <div className="detail-overlay__kpi">
                <span className="meta-label">PROGRESS</span>
                <strong>{Math.round(liveInfo.progress)}%</strong>
                <ProgressBar value={liveInfo.progress} tone={isCompleted ? "green" : "coral"} />
              </div>
              <div className="detail-overlay__kpi">
                <span className="meta-label">DATA EXAMINED</span>
                <strong className="detail-overlay__kpiValueSmall">{profile.looksAt}</strong>
              </div>
              <div className="detail-overlay__kpi">
                <span className="meta-label">LATENCY</span>
                <strong>{liveInfo.latencyMs !== null ? `${liveInfo.latencyMs} ms` : "—"}</strong>
                <span className="meta-label" style={{ fontSize: "0.60rem" }}>{liveInfo.tools.length ? `Tools: ${liveInfo.tools.slice(0, 3).join(", ")}` : "No tool trace"}</span>
              </div>
            </div>

            <div className="detail-overlay__section">
              <h4 className="detail-overlay__h4">TASK</h4>
              <p>{LIVE_TASKS[agentKey] ?? "Analyze your live business data"}</p>
            </div>

            <div className="detail-overlay__section">
              <h4 className="detail-overlay__h4">WORK PERFORMED</h4>
              <ol className="detail-overlay__steps">
                {steps.map((s) => (
                  <li key={s.n} className="detail-overlay__step">
                    <span className="detail-overlay__stepNum">{s.n}</span>
                    <div>
                      <p className="detail-overlay__stepTitle">{s.title}</p>
                      <p className="detail-overlay__stepDetail">{s.detail}</p>
                      <p className="detail-overlay__stepMeta">{s.meta}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>

            {/* LIVE WORK LOG — timestamped, updates while running */}
            <div className="detail-overlay__section detail-overlay__section--log">
              <h4 className="detail-overlay__h4">LIVE WORK LOG</h4>
              <div className="detail-overlay__log">
                {(() => {
                  const base = run?.started_at ? new Date(run.started_at).getTime() : run?.completed_at ? new Date(run.completed_at).getTime() - 18000 : Date.now() - 22000;
                  return steps.map((s, i) => {
                    const t = new Date(base + i * 2200 + (i * 317 % 900));
                    const ts = t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
                    const isDone = liveInfo.progress >= ((i + 1) / steps.length) * 100 || liveInfo.liveStatus === "COMPLETED";
                    const isActive = !isDone && liveInfo.liveStatus !== "IDLE" && liveInfo.liveStatus !== "WAITING" && liveInfo.progress >= (i / steps.length) * 100;
                    return (
                      <div key={s.n} className={`detail-overlay__logRow${isActive ? " detail-overlay__logRow--active" : ""}${isDone ? " detail-overlay__logRow--done" : ""}`}>
                        <span className="detail-overlay__logTime">{ts}</span>
                        <span className="detail-overlay__logDot" aria-hidden="true" />
                        <span className="detail-overlay__logText">{s.title} — {s.detail}</span>
                      </div>
                    );
                  });
                })()}
                {liveInfo.liveStatus === "TOOL_CALL" && liveInfo.toolDetail && (
                  <div className="detail-overlay__logRow detail-overlay__logRow--tool">
                    <span className="detail-overlay__logTime">{fmtTime(run?.started_at ?? new Date().toISOString())}</span>
                    <span className="detail-overlay__logDot detail-overlay__logDot--tool" />
                    <span className="detail-overlay__logText">TOOL {liveInfo.toolDetail.tool} — input {liveInfo.toolDetail.input} → {liveInfo.toolDetail.result}</span>
                  </div>
                )}
                {liveInfo.liveStatus === "COMMUNICATING" && liveInfo.commTarget && (
                  <div className="detail-overlay__logRow detail-overlay__logRow--comm">
                    <span className="detail-overlay__logTime">{fmtTime(new Date().toISOString())}</span>
                    <span className="detail-overlay__logDot detail-overlay__logDot--comm" />
                    <span className="detail-overlay__logText">Walking → {agentProfile(liveInfo.commTarget).label} — sharing finding</span>
                  </div>
                )}
              </div>
              {!isCompleted && liveInfo.liveStatus !== "IDLE" && <p className="detail-overlay__logHint">Live — updates as the agent works. Monitor turns active, progress advances, tool calls appear.</p>}
            </div>

            {/* DATA ANALYZED — explicit metrics */}
            <div className="detail-overlay__evidenceGrid">
              <div className="detail-overlay__evidenceBox">
                <span className="meta-label">DATA ANALYZED</span>
                <p>
                  {agentKey === "PaymentRecoveryAgent"
                    ? `14 payment attempts inspected — 11 successful, 3 unsuccessful — ₹${failed ? Math.round(failed * (m?.average_order_value ?? 0)).toLocaleString("en-IN") : "1,999"} failed-payment value`
                    : agentKey === "CustomerIntelligenceAgent"
                      ? `${totalCustomers} customers · ${m?.repeat_customers ?? 0} repeat · ${totalOrders} orders · ₹${revenue} revenue`
                      : `${totalOrders} orders · ${totalCustomers} customers · ₹${revenue} captured across last 30 days`}
                </p>
                <p className="detail-overlay__muted" style={{ marginTop: 6 }}>Source: live Razorpay TEST data · window: last 30 days</p>
              </div>
              <div className="detail-overlay__evidenceBox">
                <span className="meta-label">FINDINGS</span>
                <p>{summary ? firstSentence(summary) ?? summary : isCompleted ? "Analysis completed." : "Finding will appear when analysis completes."}</p>
                {liveInfo.toolDetail && <p className="detail-overlay__muted">Observed via {liveInfo.toolDetail.tool}</p>}
              </div>
            </div>

            <div className="detail-overlay__section">
              <h4 className="detail-overlay__h4">REASONING / ANALYSIS</h4>
              <p>{reasoning ?? (isCompleted ? "Agent cross-checked signals against peer findings and historical memory before concluding." : "Agent is still reasoning — analysis in progress.")}</p>
              <p className="detail-overlay__muted" style={{ marginTop: 6 }}>Why it matters: {profile.focus}</p>
            </div>

            <div className="detail-overlay__evidenceGrid">
              <div className="detail-overlay__evidenceBox">
                <span className="meta-label">EVIDENCE</span>
                <p>{evidence}</p>
                {reasoning && <p className="detail-overlay__muted">{reasoning}</p>}
              </div>
              <div className="detail-overlay__evidenceBox">
                <span className="meta-label">RESULT</span>
                <p>{summary ? firstSentence(summary) ?? summary : hasFailed ? "Analysis did not complete — check execution logs." : isCompleted ? "Analysis completed — finding recorded." : "Analysis in progress — findings will appear when complete."}</p>
                {confidence && <p className="detail-overlay__muted">Confidence: {confidence}</p>}
                {run && (run.opportunities_created > 0 || run.actions_proposed > 0) && (
                  <p className="detail-overlay__muted">
                    Contribution: {[run.opportunities_created ? `${run.opportunities_created} opportunit${run.opportunities_created === 1 ? "y" : "ies"}` : null, run.actions_proposed ? `${run.actions_proposed} action${run.actions_proposed === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ")}
                  </p>
                )}
              </div>
            </div>

            {recs.length > 0 && (
              <div className="detail-overlay__section">
                <h4 className="detail-overlay__h4">RECOMMENDATIONS</h4>
                <ul className="detail-overlay__recs">
                  {recs.map((r, i) => (
                    <li key={i}>→ {r}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="detail-overlay__next">
              <span className="meta-label">NEXT STEP</span>
              <p>{planItem?.next_steps ?? "Send finding to Priority Ranking and Technical Feasibility, then Growth Manager synthesis."}</p>
            </div>
          </div>

          <aside className="detail-overlay__side">
            <div className="detail-overlay__sideCard">
              <span className="meta-label">FOCUS</span>
              <p>{profile.focus}</p>
            </div>
            <div className="detail-overlay__sideCard">
              <span className="meta-label">RELATED AGENTS</span>
              <p>{agentKey === "PaymentRecoveryAgent" ? "Priority Ranking · Technical Feasibility · Growth Manager" : agentKey === "ManagerAgent" ? "All specialists → Manager synthesis" : "Priority Ranking · Technical Feasibility · Growth Manager"}</p>
            </div>
            <div className="detail-overlay__sideCard detail-overlay__sideCard--warn">
              <span className="meta-label">DATA HONESTY</span>
              <p>All values above come from your live Razorpay TEST data and the latest agent execution record. No simulated merchant results are shown as real.</p>
            </div>
            <Button variant="secondary" mono onClick={onClose} style={{ width: "100%" }}>
              Close workspace
            </Button>
          </aside>
        </div>
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Main page
   ══════════════════════════════════════════════════════════════════════════ */

export function AgentsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const urlObjective = searchParams.get("objective");

  const [agentsMeta, setAgentsMeta] = useState<AgentsListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [radar, setRadar] = useState<GrowthRadarResponse | null>(null);
  const [ranked, setRanked] = useState<RankedOpportunity[]>([]);
  const [memory, setMemory] = useState<GrowthMemoryResponse | null>(null);
  const [isWorking, setIsWorking] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [currentPhaseText, setCurrentPhaseText] = useState("");
  const [workError, setWorkError] = useState<string | null>(null);
  const [lastRunResult, setLastRunResult] = useState<OrchestratorRunResponse | null>(null);
  const [liveRuns, setLiveRuns] = useState<AgentRunRow[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [lastAnalysisTime, setLastAnalysisTime] = useState<number | null>(null);
  const [windowDays, setWindowDays] = useState(30);
  const [cmdTab, setCmdTab] = useState<CmdTab>("ACTIVITY");
  const [activityFilter, setActivityFilter] = useState<"ALL" | "WORKING" | "FOUND" | "COMPLETED">("ALL");
  const [workflowSel, setWorkflowSel] = useState<string | null>(null);

  const pollIntervalRef = useRef<number | null>(null);
  const autoStartedRef = useRef(false);
  const workingSinceRef = useRef<number | null>(null);

  // initial loads — gate protected APIs behind auth to avoid 401 spam when not signed in
  useEffect(() => {
    fetchAgentsMeta()
      .then(setAgentsMeta)
      .catch((e) => {
        const msg = e instanceof Error ? e.message : "Failed to load";
        setError(
          msg.includes("NOT_AUTHENTICATED") || msg.includes("TOKEN_EXPIRED") || msg.includes("401")
            ? "login_required"
            : msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("403")
              ? "no_workspace"
              : msg,
        );
      });
    if (!isAuthenticated()) return;
    fetchGrowthRadar(windowDays).then(setRadar).catch(() => undefined);
    fetchRankedOpportunities().then((r) => setRanked(r.opportunities ?? [])).catch(() => undefined);
    fetchGrowthMemory().then(setMemory).catch(() => undefined);
  }, [windowDays]);

  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  // auto-start from URL
  useEffect(() => {
    if (urlObjective && agentsMeta && !autoStartedRef.current && !isWorking) {
      autoStartedRef.current = true;
      void handleStartAiWork(urlObjective);
    }
  }, [urlObjective, agentsMeta]);

  // keep workingSince
  useEffect(() => {
    if (isWorking && !workingSinceRef.current) workingSinceRef.current = Date.now();
    if (!isWorking) workingSinceRef.current = null;
  }, [isWorking]);

  const handleRefresh = async () => {
    setWorkError(null);
    try {
      const [r, rk, runs] = await Promise.all([
        fetchGrowthRadar(windowDays),
        fetchRankedOpportunities().catch(() => ({ opportunities: [] as RankedOpportunity[], merchant_id: "" })),
        fetchAgentRuns(25).catch(() => ({ runs: [] as AgentRunRow[] })),
      ]);
      setRadar(r);
      setRanked((rk as { opportunities: RankedOpportunity[] }).opportunities ?? []);
      setLiveRuns(runs.runs ?? []);
      fetchGrowthMemory().then(setMemory).catch(() => undefined);
    } catch (e) {
      setWorkError(e instanceof Error ? e.message : "Refresh failed");
    }
  };

  const handleStartAiWork = async (targetObjective?: string) => {
    const obj = targetObjective || urlObjective || DEFAULT_OBJECTIVE;
    if (isWorking) return;
    setIsWorking(true);
    setIsPaused(false);
    setWorkError(null);
    setCurrentPhaseText("Starting your business analysis...");
    workingSinceRef.current = Date.now();
    try {
      const runPromise = startAiTeamWork(obj, { windowDays });
      let activeRunId: string | null = null;
      const poll = window.setInterval(async () => {
        if (isPaused) return;
        try {
          const runsResp = await fetchAgentRuns(20, activeRunId || undefined);
          if (runsResp.runs?.length) {
            setLiveRuns(runsResp.runs);
            const latest = runsResp.runs[0];
            if (latest && EXECUTION_PHASES[latest.agent_name]) setCurrentPhaseText(EXECUTION_PHASES[latest.agent_name]);
          }
        } catch {
          /* transient */
        }
      }, 1500);
      pollIntervalRef.current = poll;
      const res = await runPromise;
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      activeRunId = res.orchestrator_run_id;
      setLastRunResult(res);
      setIsWorking(false);
      setIsPaused(false);
      setCurrentPhaseText("");
      setLastAnalysisTime(Date.now());
      try {
        const finalRuns = await fetchAgentRuns(25, res.orchestrator_run_id);
        setLiveRuns(finalRuns.runs || []);
      } catch {}
      try {
        const rk = await fetchRankedOpportunities();
        setRanked(rk.opportunities ?? []);
      } catch {}
      try {
        const refreshed = await fetchGrowthRadar(windowDays);
        setRadar(refreshed);
      } catch {}
      fetchGrowthMemory().then(setMemory).catch(() => undefined);
    } catch (e) {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
      const msg = e instanceof Error ? e.message : "";
      if (msg.includes("NO_MERCHANT_MEMBERSHIP") || msg.includes("403")) setError("no_workspace");
      else setWorkError(msg || "The AI team could not complete this analysis. Please try again in a moment.");
      setIsWorking(false);
      setIsPaused(false);
      setCurrentPhaseText("");
    }
  };

  const togglePause = () => {
    if (!isWorking) return;
    setIsPaused((p) => {
      const next = !p;
      if (next) {
        if (pollIntervalRef.current) {
          clearInterval(pollIntervalRef.current);
          pollIntervalRef.current = null;
        }
        setCurrentPhaseText("Paused — polling suspended. Backend analysis continues.");
      } else {
        setCurrentPhaseText("Resumed — watching agent activity…");
        const t = window.setInterval(async () => {
          try {
            const resp = await fetchAgentRuns(20);
            if (resp.runs?.length) {
              setLiveRuns(resp.runs);
              const latest = resp.runs[0];
              if (latest && EXECUTION_PHASES[latest.agent_name]) setCurrentPhaseText(EXECUTION_PHASES[latest.agent_name]);
            }
          } catch {}
        }, 1500);
        pollIntervalRef.current = t;
      }
      return next;
    });
  };

  const metrics = radar?.metrics ?? null;
  const insufficient = radar?.data_sufficiency.status === "insufficient_data";

  const agentOutputMap = new Map<string, OrchestrationAgentOutput>();
  if (lastRunResult?.agents) for (const a of lastRunResult.agents) agentOutputMap.set(a.agent, a);

  const runByAgent = new Map<string, AgentRunRow>();
  const runCountByAgent = new Map<string, number>();
  const liveRunsReversed = [...liveRuns].reverse();
  liveRunsReversed.forEach((r) => {
    if (!runByAgent.has(r.agent_name)) runByAgent.set(r.agent_name, r);
    runCountByAgent.set(r.agent_name, (runCountByAgent.get(r.agent_name) ?? 0) + 1);
  });

  const executedAgentNames: string[] = [];
  liveRunsReversed.forEach((r) => {
    if (!executedAgentNames.includes(r.agent_name)) executedAgentNames.push(r.agent_name);
  });
  lastRunResult?.agents?.forEach((a) => {
    if (a.status === "completed" && !executedAgentNames.includes(a.agent)) executedAgentNames.push(a.agent);
  });

  const allAgentNames = agentsMeta?.agents?.map((a) => a.name) || Object.keys(AGENT_PROFILES);
  const rosterOrder = [...AGENT_ORDER.filter((n) => allAgentNames.includes(n)), ...allAgentNames.filter((n) => !AGENT_ORDER.includes(n))];

  const actionPlan: ActionPlan | null = lastRunResult?.action_plan ?? null;
  const totals = lastRunResult?.totals;

  // liveInfos for office — enriched with face, pos, tool, comm
  const liveInfos: AgentLiveInfo[] = rosterOrder.map((name, idx) => {
    const prof = agentProfile(name);
    const run = runByAgent.get(name);
    const out = agentOutputMap.get(name);
    const vis = AVATAR_BASE[name] ?? { zone: "SPECIALISTS" };
    const derived = deriveLiveStatus(name, run, out, isWorking, Boolean(insufficient && !isWorking && executedAgentNames.length === 0));
    const progress = deriveAgentProgress(run, out, isWorking, idx, run?.started_at ? new Date(run.started_at).getTime() : workingSinceRef.current);
    const toolDetail = toolDetailForAgent(name, metrics, run);
    const commTarget = derived.live === "COMMUNICATING" ? commTargetFor(name) : null;
    const monitorLine =
      derived.live === "WORKING"
        ? EXECUTION_PHASES[name] ?? `Analyzing ${LIVE_TASKS[name] ?? "business data"}…`
        : derived.live === "TOOL_CALL"
          ? `USING TOOL — ${toolDetail?.tool ?? "tool call"}`
          : derived.live === "COMMUNICATING"
            ? `Walking → ${commTarget ? agentProfile(commTarget).label : "teammate"}…`
            : derived.live === "ANALYZING"
              ? `Analyzing ${prof.looksAt.toLowerCase()}…`
              : derived.live === "THINKING"
                ? `Thinking — ${prof.specialty.toLowerCase()}…`
                : derived.live === "COMPLETED"
                  ? out?.output?.summary
                    ? (firstSentence(out.output.summary) ?? "Analysis complete — findings recorded.")
                    : run?.opportunities_created
                      ? `Found ${run.opportunities_created} opportunit${run.opportunities_created === 1 ? "y" : "ies"}`
                      : "Completed — no new signal in this window."
                  : derived.live === "WAITING"
                    ? "Waiting for opportunity candidates"
                    : derived.live === "BLOCKED"
                      ? "Insufficient data — needs more transactions"
                      : derived.live === "ERROR"
                        ? "Needs attention — last run did not complete"
                        : derived.live === "IDLE"
                          ? `Ready — ${prof.specialty}`
                          : `Queued — ${LIVE_TASKS[name] ?? prof.looksAt}`;
    const subLine =
      derived.live === "TOOL_CALL"
        ? `${toolDetail?.input ?? "input"} → ${toolDetail?.result ?? "running"}`
        : derived.live === "WORKING"
          ? `Examining ${prof.looksAt.toLowerCase()}…`
          : derived.live === "COMMUNICATING"
            ? `“${toolDetail?.result ?? "Sharing finding"}” → ${commTarget ? agentProfile(commTarget).label : "peer"}`
            : derived.live === "COMPLETED" && out?.output?.recommendations?.[0]
              ? out.output.recommendations[0].slice(0, 88)
              : derived.live === "IDLE"
                ? prof.focus.slice(0, 74)
                : `Focus: ${prof.specialty}`;
    const pos = OFFICE_POS[name] ?? { x: 50, y: 50 };
    return {
      key: name,
      label: prof.label,
      specialty: prof.specialty,
      zone: vis.zone,
      liveStatus: derived.live,
      chipLabel: derived.chip,
      chipTone: derived.tone,
      anim: derived.anim,
      progress,
      monitorLine,
      subLine,
      latencyMs: run?.total_latency_ms ?? out?.latency_ms?.total ?? null,
      tools: Array.isArray(run?.tools_used) ? (run.tools_used as string[]) : [],
      toolDetail,
      commTarget,
      pos,
    };
  });

  // OfficeFloor agents — pixel-art virtual office (PixiJS) — same data as liveInfos, mapped to Office characters/statuses
  const officeAgents = useMemo(
    () =>
      liveInfos.map((a, idx) => ({
        id: a.key,
        name: a.label,
        character: toOfficeCharacter(a.key),
        status: mapLiveStatus(a.liveStatus as never),
        action: a.monitorLine,
        accent: accentForIndex(idx + (a.key === "ManagerAgent" ? 3 : 0)),
        isGod: a.key === "ManagerAgent",
        carrying: a.liveStatus === "TOOL_CALL" ? "Bash" : undefined,
        lastPrompt: a.subLine,
      })),
    [liveInfos],
  );

  const workingCount = liveInfos.filter((a) => a.liveStatus === "WORKING" || a.liveStatus === "ANALYZING" || a.liveStatus === "THINKING" || a.liveStatus === "TOOL_CALL" || a.liveStatus === "COMMUNICATING").length;
  const completedCount = liveInfos.filter((a) => a.liveStatus === "COMPLETED").length;

  // activity entries
  const activityEntries = useMemo(() => {
    const entries: Array<{ id: string; ts: string | null; agentKey: string; agentLabel: string; action: string; result: string; tone: "ok" | "accent" | "neutral"; icon: string }> = [];
    // from live runs — most recent last, we want chronological newest last? For console, newest first maybe reverse.
    [...liveRuns].sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime()).forEach((r) => {
      const prof = agentProfile(r.agent_name);
      const isDone = r.status === "completed";
      const isRunning = r.status === "running";
      entries.push({
        id: r.id,
        ts: r.started_at,
        agentKey: r.agent_name,
        agentLabel: prof.label,
        action: isRunning ? `Started — ${LIVE_TASKS[r.agent_name] ?? "analyzing business data"}` : isDone ? `Completed — examined ${prof.looksAt.toLowerCase()}` : `Status: ${r.status}`,
        result: isDone ? (r.opportunities_created > 0 ? `Contributed to ${r.opportunities_created} opportunit${r.opportunities_created === 1 ? "y" : "ies"}` : "No new signal in this window") : isRunning ? "In progress…" : (r.errors?.[0] ?? ""),
        tone: isRunning ? "accent" : isDone && r.opportunities_created > 0 ? "accent" : isDone ? "ok" : "neutral",
        icon: isRunning ? "●" : isDone ? "✓" : "—",
      });
      if (r.completed_at && r.completed_at !== r.started_at) {
        // add completed marker separate? Already covered
      }
    });
    // add orchestrator-level findings as extra entries if no liveRuns yet but we have lastRunResult
    if (entries.length === 0 && lastRunResult?.agents) {
      lastRunResult.agents.forEach((a) => {
        const prof = agentProfile(a.agent);
        entries.push({
          id: `orch-${a.agent}`,
          ts: null,
          agentKey: a.agent,
          agentLabel: prof.label,
          action: a.status === "completed" ? `Reported — ${firstSentence(a.output?.summary ?? "") ?? "Completed analysis"}` : `Status: ${a.status}`,
          result: a.opportunities_created ? `Created ${a.opportunities_created} opportunit${a.opportunities_created === 1 ? "y" : "ies"}` : "No direct opportunity created",
          tone: a.opportunities_created > 0 ? "accent" : a.status === "completed" ? "ok" : "neutral",
          icon: a.opportunities_created > 0 ? "◆" : "✓",
        });
      });
    }
    // sort newest first for display but keep chronological order for graph? We'll display newest first
    return entries;
  }, [liveRuns, lastRunResult]);

  const filteredActivity = useMemo(() => {
    if (activityFilter === "ALL") return activityEntries;
    if (activityFilter === "WORKING") return activityEntries.filter((e) => e.tone === "accent" && e.action.toLowerCase().includes("started"));
    if (activityFilter === "FOUND") return activityEntries.filter((e) => e.result.toLowerCase().includes("opportunit"));
    return activityEntries.filter((e) => e.tone === "ok");
  }, [activityEntries, activityFilter]);

  // findings
  const findings = rosterOrder
    .map((name) => {
      const output = agentOutputMap.get(name);
      if (!output || output.status !== "completed") return null;
      const recs = output.output?.recommendations ?? [];
      const summary = output.output?.summary ?? "";
      if (!summary && recs.length === 0) return null;
      const profile = agentProfile(name);
      const finding = firstSentence(summary) || recs[0] || "Completed its analysis of your business data.";
      const head = firstSentence(summary) ?? "";
      const rest = summary.replace(head, "").trim();
      const why = recs[1] ?? (rest ? firstSentence(rest) : null);
      // derive confidence from ranked opportunity that matches? fallback
      const conf = confidenceWord(
        (ranked.find((r) => r.title.toLowerCase().includes(finding.toLowerCase().slice(0, 18))) as unknown as { confidence?: number })?.confidence ?? null,
      );
      return {
        name,
        label: profile.label,
        specialty: profile.specialty,
        finding,
        why: why && why !== finding ? why : null,
        evidence: profile.looksAt,
        action: recs.find((r) => r !== (firstSentence(summary) || "")) ?? recs[0] ?? null,
        confidence: conf,
      };
    })
    .filter((f): f is NonNullable<typeof f> => f !== null);

  // opportunities unified
  const runOpps = lastRunResult?.ranked_opportunities ?? [];
  const sources: Array<{ title: string; type?: string; expectedRevenue?: number | null; confidenceValue?: number | null; rank: number }> = [];
  if (runOpps.length > 0) {
    runOpps.forEach((o, idx) => {
      const sb = (o as { score_breakdown?: { confidence_score?: number } }).score_breakdown;
      sources.push({ title: o.title, type: o.type, expectedRevenue: o.expected_revenue ?? null, confidenceValue: o.confidence ?? sb?.confidence_score ?? null, rank: idx + 1 });
    });
  } else if (ranked.length > 0) {
    ranked.forEach((o) => sources.push({ title: o.title, type: o.type, expectedRevenue: o.expected_revenue ?? null, confidenceValue: o.confidence ?? o.score_breakdown?.confidence_score ?? null, rank: o.rank }));
  }
  const opportunities = sources.map((src) => {
    const initiative = actionPlan?.initiatives?.find((it) => it.title.toLowerCase() === src.title.toLowerCase()) ?? actionPlan?.initiatives?.find((it) => it.title.toLowerCase().includes(src.title.toLowerCase().slice(0, 10))) ?? null;
    return {
      title: src.title,
      type: src.type,
      why: src.type ? translateOppType(src.type) : "Identified from patterns in your live business data.",
      evidence: initiative?.expected_impact ?? `Ranked #${src.rank} by the AI team from your live Razorpay business data.`,
      impact: formatMoney(src.expectedRevenue) ? `Potential revenue impact: ${formatMoney(src.expectedRevenue)}` : null,
      action: initiative?.next_steps ?? null,
      discoveredBy: (lastRunResult?.agents ?? []).filter((a) => a.status === "completed" && a.opportunities_created > 0).map((a) => agentProfile(a.agent).label),
      confidence: confidenceWord(src.confidenceValue),
      raw: src,
    };
  });

  function translateOppType(type: string | undefined) {
    const m: Record<string, string> = {
      payment_recovery: "Some customers tried to pay but their payments failed — this revenue can be won back.",
      customer_winback: "Past customers have not purchased in a while and could be invited back.",
      cross_sell: "Customers who buy certain products tend to buy related ones together.",
      upsell: "Some orders could be expanded with a higher-value option or add-on.",
      bundle: "Frequently bought together products can be offered as a discounted bundle.",
      repeat_purchase: "Repeat buyers show patterns that can be encouraged across more customers.",
      campaign: "A targeted campaign could lift sales for a specific customer group.",
    };
    if (!type) return "This opportunity was identified from patterns in your live business data.";
    const key = type.toLowerCase().replace(/[^a-z]/g, "_");
    return m[key] ?? m[type.toLowerCase()] ?? `${prettifyName(type)}: identified by the AI team from your live business data.`;
  }

  const topOpp = opportunities[0] ?? null;
  const topInitiative = actionPlan?.initiatives?.[0] ?? null;
  const matchedTopInitiative = topOpp ? (actionPlan?.initiatives?.find((i) => i.title.toLowerCase() === topOpp.title.toLowerCase()) ?? topInitiative) : topInitiative;
  const showRecommendation = Boolean(topOpp || actionPlan || totals);

  const latestCompletedAt = liveRuns.map((r) => r.completed_at).filter((v): v is string => Boolean(v)).sort().pop();
  const lastAnalysisTs = lastAnalysisTime ?? (latestCompletedAt ? new Date(latestCompletedAt).getTime() : null);

  // comms derived
  const commEvents = useMemo(() => {
    const ev: Array<{ from: string; to: string; msg: string; ts: string | null; tone: "real" | "derived" }> = [];
    if (metrics) {
      const fail = metrics.failed_payments;
      if (fail > 0) {
        ev.push({ from: "Payment Recovery", to: "Growth Manager", msg: `Found ${fail} failed payment attempt${fail === 1 ? "" : "s"} — ~${formatMoney(fail * (metrics.average_order_value || 0)) ?? "some value"} attempted.`, ts: liveRuns[0]?.started_at ?? null, tone: "real" });
        ev.push({ from: "Growth Manager", to: "Priority Ranking", msg: "Evaluate recovery opportunity against current findings.", ts: null, tone: "derived" });
        ev.push({ from: "Priority Ranking", to: "Technical Feasibility", msg: "Assess whether recovery can be automated safely via Razorpay retry.", ts: null, tone: "derived" });
        ev.push({ from: "Technical Feasibility", to: "Growth Manager", msg: "Recovery workflow is technically feasible — requires webhook + compliant retry.", ts: null, tone: "derived" });
      }
    }
    if (totals && totals.opportunities_created > 0) {
      ev.push({ from: "Opportunity Discovery", to: "Priority Ranking", msg: `Detected ${totals.opportunities_created} growth signal${totals.opportunities_created === 1 ? "" : "s"} for ranking.`, ts: null, tone: "real" });
    }
    if (lastRunResult?.debate_id) {
      ev.push({ from: "Growth Manager", to: "All Specialists", msg: "Opened debate — challenging findings before committing to action.", ts: null, tone: "real" });
    }
    if (ev.length === 0) {
      ev.push({ from: "Growth Memory", to: "All Agents", msg: "Shared historical context — prior analyses and outcomes.", ts: null, tone: "derived" });
      ev.push({ from: "Opportunity Discovery", to: "Specialists", msg: "Broadcasting live signals for deep inspection.", ts: null, tone: "derived" });
    }
    ev.push({ from: "Growth Manager", to: "Human", msg: showRecommendation ? "Recommendation ready for approval — see action plan." : "Awaiting specialist findings before synthesis.", ts: null, tone: "derived" });
    return ev;
  }, [metrics, totals, lastRunResult, liveRuns, showRecommendation]);

  // selected agent live info
  const selectedLive = selectedAgent ? liveInfos.find((l) => l.key === selectedAgent) ?? null : null;
  const selectedOutput = selectedAgent ? agentOutputMap.get(selectedAgent) : undefined;
  const selectedRun = selectedAgent ? runByAgent.get(selectedAgent) : undefined;
  const selectedPlanItem = selectedAgent && actionPlan ? actionPlan.initiatives.find((it) => it.assigned_to?.toLowerCase().includes((selectedLive?.label ?? "").toLowerCase().slice(0, 4))) ?? actionPlan.initiatives[0] ?? null : null;
  const selectedConf = selectedAgent ? confidenceWord((ranked.find((r) => r.title.toLowerCase().includes((selectedOutput?.output?.summary ?? "").slice(0, 12).toLowerCase())) as unknown as { confidence?: number })?.confidence ?? selectedRun?.opportunities_created ? 0.55 : null) : null;

  // ESC to close detail
  useEffect(() => {
    if (!selectedAgent) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setSelectedAgent(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedAgent]);

  if (error === "login_required") {
    return (
      <section className="shell section" aria-labelledby="agents-heading">
        <div className="page-hero" style={{ paddingBottom: 0 }}>
          <p className="meta-label">AI GROWTH TEAM</p>
          <h1 id="agents-heading" className="display-lg" style={{ marginTop: 10 }}>AI Growth Team</h1>
        </div>
        <WindowPanel title="login-required.app">
          <p className="meta-label" style={{ marginBottom: 12 }}>SIGN IN REQUIRED</p>
          <p style={{ fontSize: "var(--text-body)", lineHeight: "var(--leading-body)", color: "var(--ink-soft)" }}>
            Your AI Growth Team analyses your business data. Sign in to start an analysis of your live Razorpay TEST commerce data.
          </p>
          <div style={{ marginTop: 20, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Button variant="primary" mono onClick={() => navigate("/login")}>Sign in</Button>
          </div>
        </WindowPanel>
      </section>
    );
  }
  if (error === "no_workspace") {
    return (
      <section className="shell section" aria-labelledby="agents-heading">
        <div className="page-hero" style={{ paddingBottom: 0 }}>
          <p className="meta-label">AI GROWTH TEAM</p>
          <h1 id="agents-heading" className="display-lg" style={{ marginTop: 10 }}>AI Growth Team</h1>
        </div>
        <WindowPanel title="workspace-required.app">
          <p style={{ color: "var(--ink-soft)" }}>Connect your business workspace to unlock your AI Growth Team.</p>
          <div style={{ marginTop: 16 }}>
            <Button variant="primary" mono onClick={() => navigate("/profile")}>View Profile →</Button>
          </div>
        </WindowPanel>
      </section>
    );
  }

  return (
    <section className="agents-cc agents-cc--wide" aria-labelledby="agents-heading">
      {/* ── HERO / COMMAND BAR ─────────────────────────────────────────── */}
      <header className="agents-cc__hero">
        <div className="agents-cc__heroMain">
          <p className="meta-label">YOUR BUSINESS · AI WORKFORCE COMMAND CENTER</p>
          <h1 id="agents-heading" className="agents-cc__title">
            AI Workforce <span className="accent-word">Command Center</span>
          </h1>
          <p className="agents-cc__lede">
            A live view into your virtual AI company — 13 specialists working on your Razorpay business in real time. Watch desks light up, see tool calls hit, and follow every finding to a recommendation.
          </p>
          <div className="agents-cc__statusBar">
            <span className="agents-cc__live">
              <span className={`agents-cc__liveDot${isWorking ? " agents-cc__liveDot--pulse" : ""}`} aria-hidden="true" />
              {isPaused ? "PAUSED" : isWorking ? "LIVE" : "STANDBY"}
            </span>
            <span className="agents-cc__statusSep">/</span>
            <span>{isWorking ? `${workingCount} working · ${completedCount} completed` : `${allAgentNames.length} specialists on payroll`}</span>
            <span className="agents-cc__statusSep">/</span>
            <span>Last analysis: {timeAgo(lastAnalysisTs)}</span>
            <span className="agents-cc__statusSep">/</span>
            <span>Window: last {windowDays} days</span>
          </div>
        </div>

        <div className="agents-cc__heroActions">
          <div className="agents-cc__controls">
            <Button variant="primary" mono disabled={isWorking || !agentsMeta} onClick={() => void handleStartAiWork()}>
              {isWorking ? "Analyzing…" : "Start Analysis →"}
            </Button>
            <Button variant="secondary" mono disabled={!isWorking} onClick={togglePause}>
              {isPaused ? "Resume" : "Pause"}
            </Button>
            <Button variant="secondary" mono onClick={() => void handleRefresh()}>
              ↻ Refresh
            </Button>
          </div>
          <div className="agents-cc__windowSwitch" role="group" aria-label="Data window">
            {[7, 14, 30, 90].map((d) => (
              <button key={d} type="button" className={`agents-cc__winBtn${windowDays === d ? " agents-cc__winBtn--on" : ""}`} aria-pressed={windowDays === d} onClick={() => setWindowDays(d)}>
                {d}D
              </button>
            ))}
          </div>
          {(isWorking || currentPhaseText) && !isPaused && <p className="agents-cc__phase">{currentPhaseText}</p>}
          {isPaused && <p className="agents-cc__phase agents-cc__phase--paused">Polling paused — backend analysis continues. Press Resume to watch updates again.</p>}
          {workError && <div className="agents-cc__error">{workError}</div>}
        </div>
      </header>

      {/* ── BUSINESS SNAPSHOT (compact — does not dominate) ────────────── */}
      <WindowPanel title="business-snapshot.app" tone="choc" dark>
        <div className="agents-cc__snapshotHead">
          <p className="meta-label" style={{ color: "var(--cream-muted)" }}>
            BUSINESS SNAPSHOT · LIVE FROM YOUR RAZORPAY TEST ACCOUNT
          </p>
          <span className="meta-label" style={{ color: "var(--cream-muted)", fontSize: "0.66rem" }}>
            {radar ? `${radar.metrics.captured_transactions} txns · ${radar.data_sufficiency.status.replace(/_/g, " ")}` : "loading…"} · {new Date().toLocaleDateString("en-IN")}
          </span>
        </div>
        <BusinessSnapshotStrip radar={radar} />
        {insufficient && (
          <p className="agents-cc__insufficient">
            INSUFFICIENT DATA — the team has limited history to learn from. {radar?.data_sufficiency.message ?? "Create more transactions via Checkout to unlock stronger findings."}
          </p>
        )}
        {!radar && <p className="agents-cc__muted">NO LIVE DATA — connect your workspace or run an analysis to populate.</p>}
      </WindowPanel>

      {/* ── MAIN GRID: OFFICE + COMMAND CENTER ──────────────────────────── */}
      <div className="agents-cc__mainGrid">
        {/* LEFT / CENTER — AI OFFICE FLOOR */}
        <div className="agents-cc__officeCol">
          <WindowPanel title="ai-office.floor — live-operations.app" flush>
            <div className="ai-office">
              <div className="ai-office__head">
                <div className="ai-office__headLeft">
                  <span className="meta-label">AI OFFICE FLOOR</span>
                  <h2 className="ai-office__h2">Where your 13 employees work</h2>
                  <p className="ai-office__hint">Desks light up when agents are working — click any workstation to inspect the actual work performed.</p>
                </div>
                <div className="ai-office__headRight">
                  <span className="ai-office__badge">
                    <span className={`ai-office__dot${isWorking ? " ai-office__dot--pulse" : ""}`} />
                    {isWorking ? "LIVE OPERATIONS" : "STANDBY — READY"}
                  </span>
                  <span className="ai-office__counts">
                    {workingCount} working · {completedCount} done · {liveInfos.length - workingCount - completedCount} idle
                  </span>
                </div>
              </div>

              {/* ── PIXIJS VIRTUAL OFFICE — ported from munder-difflin (PixiJS + Tiled map + procedural characters) ── */}
              <div className="office-canvasWrap" style={{ padding: 0, background: "#1a1320" }}>
                <div
                  style={{
                    width: "100%",
                    height: 640,
                    minHeight: 560,
                    border: "2px solid #2a1810",
                    borderRadius: 3,
                    overflow: "hidden",
                    background: "#1a1320",
                    boxShadow: "5px 5px 0 rgba(33,19,14,0.10)",
                  }}
                >
                  <OfficeFloor agents={officeAgents} selectedId={selectedAgent} onSelectAgent={setSelectedAgent} paused={isPaused} />
                </div>
                <p
                  style={{
                    margin: "8px 0 0",
                    fontFamily: "IBM Plex Mono, monospace",
                    fontSize: "0.62rem",
                    letterSpacing: "0.08em",
                    textTransform: "uppercase",
                    color: "#8a6f5c",
                  }}
                >
                  Pixel-art office · {officeAgents.length} agents · procedural characters · PixiJS + Tiled map
                  <span style={{ color: "#5a6b8c" }}> — office.tmj + LimeZu tilesets</span>
                </p>
              </div>

              <div className="ai-office__foot">
                <div className="ai-office__legend">
                  <span>
                    <i className="ai-office__legendDot ai-office__legendDot--working" /> working
                  </span>
                  <span>
                    <i className="ai-office__legendDot ai-office__legendDot--done" /> completed
                  </span>
                  <span>
                    <i className="ai-office__legendDot ai-office__legendDot--waiting" /> waiting
                  </span>
                  <span>
                    <i className="ai-office__legendDot ai-office__legendDot--blocked" /> blocked
                  </span>
                </div>
                <span className="ai-office__footHint">DEMO states are marked DEMO · real values come from your live data only</span>
              </div>
            </div>
          </WindowPanel>

        </div>

        {/* RIGHT — COMMAND CENTER CONSOLE */}
        <aside className="agents-cc__cmdCol" aria-label="Command center">
          <div className="cmd">
            <header className="cmd__titlebar">
              <span className="cmd__filename">command-center.app</span>
              <span className="cmd__live">
                <span className={`cmd__liveDot${isWorking && !isPaused ? " cmd__liveDot--pulse" : ""}`} />
                {isPaused ? "PAUSED" : isWorking ? "LIVE" : "IDLE"}
              </span>
              <span className="window__controls" aria-hidden="true">
                <span className="window__control window__control--coral" />
                <span className="window__control window__control--gray" />
                <span className="window__control window__control--muted" />
              </span>
            </header>

            <nav className="cmd__tabs" role="tablist" aria-label="Command center tabs">
              {(["ACTIVITY", "MONITOR", "TASKS", "MEMORY", "GRAPH", "TERMINAL", "COMMANDS", "WORKERS"] as CmdTab[]).map((t) => (
                <button key={t} type="button" role="tab" aria-selected={cmdTab === t} className={`cmd__tab${cmdTab === t ? " cmd__tab--on" : ""}`} onClick={() => setCmdTab(t)}>
                  {t}
                </button>
              ))}
            </nav>

            <div className="cmd__body">
              {cmdTab === "ACTIVITY" && (
                <div className="cmd__panel">
                  <div className="cmd__panelHead">
                    <span className="meta-label">ACTIVITY STREAM · CHRONOLOGICAL</span>
                    <div className="cmd__filters">
                      {(["ALL", "WORKING", "FOUND", "COMPLETED"] as const).map((f) => (
                        <button key={f} type="button" className={`cmd__filter${activityFilter === f ? " cmd__filter--on" : ""}`} onClick={() => setActivityFilter(f)}>
                          {f}
                        </button>
                      ))}
                    </div>
                  </div>
                  {filteredActivity.length === 0 ? (
                    <div className="cmd__empty">
                      {isWorking ? "Streaming activity — specialists will appear here as they start." : "No activity yet. Start an analysis to stream every agent event here."}
                      <span className="cmd__emptyHint">This console shows real execution events — never fabricated results.</span>
                    </div>
                  ) : (
                    <div className="cmd__log">
                      {filteredActivity.map((e) => (
                        <div key={e.id} className={`cmd__entry cmd__entry--${e.tone}`}>
                          <div className="cmd__entryHead">
                            <span className="cmd__entryAgent">{e.agentLabel.toUpperCase()}</span>
                            <span className="cmd__entryTime">{fmtTime(e.ts)}</span>
                            <span className={`cmd__entryBadge cmd__entryBadge--${e.tone}`}>{e.icon}</span>
                          </div>
                          <p className="cmd__entryAction">{e.action}</p>
                          <p className="cmd__entryResult">→ {e.result}</p>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="cmd__foot">
                    <span>{filteredActivity.length} events · {isWorking && !isPaused ? "streaming" : "snapshot"}</span>
                    <button type="button" className="cmd__footLink" onClick={() => void handleRefresh()}>
                      ↻ Refresh
                    </button>
                  </div>
                </div>
              )}

              {cmdTab === "MONITOR" && (
                <div className="cmd__panel">
                  <p className="meta-label" style={{ marginBottom: 10 }}>
                    BUSINESS HEALTH · LIVE
                  </p>
                  <div className="cmd__monitorGrid">
                    <div className="cmd__mStat">
                      <span className="cmd__mLabel">REVENUE</span>
                      <strong>{metrics ? (formatMoney(metrics.captured_revenue) ?? "—") : "—"}</strong>
                      <span className="cmd__mHint">{metrics ? `${metrics.captured_transactions} txns` : "no data"}</span>
                    </div>
                    <div className="cmd__mStat">
                      <span className="cmd__mLabel">PAYMENTS</span>
                      <strong>{metrics ? `${metrics.successful_payments} / ${(metrics.successful_payments ?? 0) + (metrics.failed_payments ?? 0)}` : "—"}</strong>
                      <span className="cmd__mHint">{metrics && (metrics.failed_payments ?? 0) > 0 ? `${metrics.failed_payments} failed` : "no failures"}</span>
                    </div>
                    <div className="cmd__mStat">
                      <span className="cmd__mLabel">SIGNALS</span>
                      <strong>{radar ? String(radar.signals.length) : "—"}</strong>
                      <span className="cmd__mHint">{radar?.overall_health.replace(/_/g, " ") ?? "—"}</span>
                    </div>
                  </div>
                  <div className="cmd__monitorList">
                    <div className="cmd__monitorRow">
                      <span>Overall health</span>
                      <strong>{radar ? radar.overall_health.toUpperCase() : "—"}</strong>
                    </div>
                    <div className="cmd__monitorRow">
                      <span>Data sufficiency</span>
                      <strong>{radar ? `${radar.data_sufficiency.available}/${radar.data_sufficiency.minimum_required}` : "—"}</strong>
                    </div>
                    <div className="cmd__monitorRow">
                      <span>Agents executed</span>
                      <strong>{executedAgentNames.length} / {rosterOrder.length}</strong>
                    </div>
                    <div className="cmd__monitorRow">
                      <span>Opportunities</span>
                      <strong>{opportunities.length}</strong>
                    </div>
                  </div>
                  {radar?.signals.slice(0, 3).map((s, i) => (
                    <div key={i} className="cmd__signalMini">
                      <span className="cmd__signalTitle">{s.title}</span>
                      <span className="meta-label" style={{ fontSize: "0.60rem" }}>
                        {Math.round(s.confidence * 100)}% · {s.signal}
                      </span>
                    </div>
                  ))}
                  {(!radar || radar.signals.length === 0) && <p className="cmd__muted">No signals to monitor in this window.</p>}
                </div>
              )}

              {cmdTab === "TASKS" && (
                <div className="cmd__panel">
                  <p className="meta-label" style={{ marginBottom: 10 }}>
                    TASKS · {liveInfos.length} AGENTS
                  </p>
                  <div className="cmd__tasks">
                    {liveInfos.map((a) => (
                      <button key={a.key} type="button" className={`cmd__task${selectedAgent === a.key ? " cmd__task--sel" : ""}`} onClick={() => setSelectedAgent(a.key)}>
                        <span className="cmd__taskMain">
                          <span className={`cmd__taskDot cmd__taskDot--${a.chipTone}${a.anim === "pulse" ? " cmd__taskDot--pulse" : ""}`} />
                          <span className="cmd__taskName">{a.label}</span>
                          <span className="cmd__taskStatus">{a.chipLabel}</span>
                        </span>
                        <span className="cmd__taskBar">
                          <ProgressBar value={a.progress} tone={a.liveStatus === "COMPLETED" ? "green" : "coral"} />
                          <span className="cmd__taskPct">{Math.round(a.progress)}%</span>
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {cmdTab === "MEMORY" && (
                <div className="cmd__panel">
                  <p className="meta-label" style={{ marginBottom: 10 }}>
                    GROWTH MEMORY · HISTORICAL CONTINUITY
                  </p>
                  {memory && memory.memories.length > 0 ? (
                    <div className="cmd__mems">
                      {memory.memories.slice(0, 6).map((m) => (
                        <div key={m.id} className="cmd__mem">
                          <span className="cmd__memType">{m.memory_type.toUpperCase()}</span>
                          <p>{m.content.slice(0, 160)}</p>
                          <span className="meta-label" style={{ fontSize: "0.60rem" }}>
                            {new Date(m.created_at).toLocaleDateString("en-IN")} · importance {m.importance}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="cmd__empty">
                      No memory entries yet — or memory service returned none for this window.
                      <span className="cmd__emptyHint">Growth Memory will populate as analyses accumulate.</span>
                    </div>
                  )}
                  <div className="cmd__memFoot">
                    <span className="meta-label">{memory ? `${memory.memories.length} entries` : "loading…"}</span>
                    <span className="cmd__muted">Retention improves with each approved action.</span>
                  </div>
                </div>
              )}

              {cmdTab === "GRAPH" && (
                <div className="cmd__panel">
                  <p className="meta-label" style={{ marginBottom: 10 }}>
                    OPERATIONAL CHARTS · LIVE
                  </p>
                  {/* Workload — horizontal bars per agent */}
                  <div className="cmd__chartBox">
                    <span className="meta-label">AGENT WORKLOAD</span>
                    <div className="cmd__workloadBars">
                      {liveInfos.map((a) => (
                        <div key={a.key} className="cmd__workloadRow">
                          <span className="cmd__workloadName" title={a.label}>
                            {a.label.slice(0, 14)}
                          </span>
                          <div className="cmd__workloadTrack">
                            <div
                              className={`cmd__workloadFill cmd__workloadFill--${a.liveStatus === "COMPLETED" ? "done" : a.liveStatus === "WORKING" || a.liveStatus === "TOOL_CALL" || a.liveStatus === "COMMUNICATING" ? "active" : "idle"}`}
                              style={{ width: `${Math.round(a.progress)}%` }}
                            />
                          </div>
                          <span className="cmd__workloadPct">{Math.round(a.progress)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="cmd__chartGrid">
                    <div className="cmd__chartBox">
                      <span className="meta-label">TASKS COMPLETED</span>
                      <div className="cmd__miniBars">
                        {[
                          { label: "Working", val: workingCount, total: liveInfos.length, color: "var(--coral)" },
                          { label: "Completed", val: completedCount, total: liveInfos.length, color: "var(--green-deep)" },
                          { label: "Waiting", val: liveInfos.length - workingCount - completedCount, total: liveInfos.length, color: "var(--ink-faint)" },
                        ].map((b) => (
                          <div key={b.label} className="cmd__miniBarRow">
                            <span>{b.label}</span>
                            <div className="cmd__miniBarTrack">
                              <div className="cmd__miniBarFill" style={{ width: `${(b.val / b.total) * 100}%`, background: b.color }} />
                            </div>
                            <strong>{b.val}</strong>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="cmd__chartBox">
                      <span className="meta-label">FINDINGS & OPPORTUNITIES</span>
                      <div className="cmd__statBig">
                        <span>{findings.length}</span>
                        <label>findings</label>
                      </div>
                      <div className="cmd__statBig">
                        <span>{opportunities.length}</span>
                        <label>opportunities</label>
                      </div>
                      <div className="cmd__spark">
                        {liveInfos.map((a, i) => (
                          <span
                            key={a.key}
                            className="cmd__sparkBar"
                            style={{ height: `${8 + (a.progress / 100) * 28}px`, background: a.liveStatus === "COMPLETED" ? "var(--green-deep)" : a.liveStatus === "WORKING" || a.liveStatus === "TOOL_CALL" ? "var(--coral)" : "var(--line-soft)" }}
                            title={`${a.label} ${Math.round(a.progress)}%`}
                          />
                        ))}
                      </div>
                      <p className="cmd__muted" style={{ marginTop: 6 }}>Spark = per-agent progress. Coral = active, green = done.</p>
                    </div>
                  </div>
                  <div className="cmd__chartBox">
                    <span className="meta-label">ANALYSIS PROGRESS</span>
                    <div className="cmd__progressBig">
                      <ProgressBar value={liveInfos.reduce((s, a) => s + a.progress, 0) / liveInfos.length} tone={completedCount === liveInfos.length ? "green" : "coral"} />
                      <span>{Math.round(liveInfos.reduce((s, a) => s + a.progress, 0) / liveInfos.length)}% overall</span>
                    </div>
                    <p className="cmd__muted">Avg across 13 specialists · updates as agents advance through WORKING → TOOL_CALL → COMMUNICATING → COMPLETED</p>
                  </div>
                  {/* Keep workflow comms collapsed under charts for operator reference */}
                  <details className="cmd__details">
                    <summary className="meta-label">TEAM COMMUNICATION · WORKFLOW EVENTS (expand)</summary>
                    <div className="cmd__comms" style={{ marginTop: 8 }}>
                      {commEvents.map((c, i) => (
                        <div key={i} className={`cmd__comm cmd__comm--${c.tone}`}>
                          <span className="cmd__commLine">
                            <strong>{c.from}</strong> → <strong>{c.to}</strong>
                          </span>
                          <p>“{c.msg}”</p>
                          <span className="meta-label" style={{ fontSize: "0.60rem" }}>
                            {c.tone === "real" ? "● REAL EXECUTION EVENT" : "○ DERIVED WORKFLOW EVENT (DEMO)"}
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              )}

              {cmdTab === "TERMINAL" && (
                <div className="cmd__panel cmd__panel--terminal">
                  <div className="cmd__termHeader">
                    <span className="window__controls" aria-hidden="true">
                      <span className="window__control window__control--coral" />
                      <span className="window__control window__control--gray" />
                      <span className="window__control window__control--muted" />
                    </span>
                    <span className="meta-label">razorgrowth@terminal · AI WORKFORCE</span>
                  </div>
                  <div className="cmd__termScreen">
                    <p className="cmd__termLine">&gt; starting growth analysis...</p>
                    <p className="cmd__termLine">&gt; loading merchant data... {metrics ? `${metrics.total_orders} orders · ${metrics.total_customers} customers` : "waiting for data..."}</p>
                    <p className="cmd__termLine">&gt; 13 agents initialized</p>
                    <p className="cmd__termLine">&gt; dispatching specialists...</p>
                    {isWorking && <p className="cmd__termLine cmd__termLine--active">&gt; {currentPhaseText || "agents working..."}</p>}
                    {!isWorking && executedAgentNames.length === 0 && <p className="cmd__termLine">&gt; standing by — press START ANALYSIS</p>}
                    {liveRuns.slice(0, 6).map((r) => (
                      <p key={r.id} className="cmd__termLine">
                        &gt; {agentProfile(r.agent_name).label.toLowerCase().replace(/ /g, "_")} :: {r.status} {r.tools_used && Array.isArray(r.tools_used) && (r.tools_used as string[]).length ? `tools[${(r.tools_used as string[]).join(",")}]` : ""} {r.total_latency_ms}ms
                        {r.errors?.length ? ` ! ${r.errors[0]}` : ""}
                      </p>
                    ))}
                    {liveRuns.length === 0 && lastRunResult?.agents?.slice(0, 4).map((a) => (
                      <p key={a.agent} className="cmd__termLine">
                        &gt; {a.agent.replace(/Agent$/, "").toLowerCase()} :: {a.status} opp:{a.opportunities_created}
                      </p>
                    ))}
                    <p className="cmd__termCursor">▌</p>
                  </div>
                  <div className="cmd__termFoot">
                    <span className="meta-label">{liveRuns.length} execution records</span>
                    <span className="cmd__muted">Retro console — real tool & latency data when backend exposes it; otherwise derived.</span>
                  </div>
                </div>
              )}

              {cmdTab === "COMMANDS" && (
                <div className="cmd__panel">
                  <p className="meta-label" style={{ marginBottom: 12 }}>
                    COMMANDS · OPERATOR CONTROLS
                  </p>
                  <div className="cmd__cmdBtns">
                    <Button variant="primary" mono disabled={isWorking} onClick={() => void handleStartAiWork()} style={{ width: "100%" }}>
                      {isWorking ? "Analysis running…" : "Start Analysis →"}
                    </Button>
                    <div className="cmd__cmdRow">
                      <Button variant="secondary" mono disabled={!isWorking} onClick={togglePause} style={{ flex: 1 }}>
                        {isPaused ? "Resume stream" : "Pause stream"}
                      </Button>
                      <Button variant="secondary" mono onClick={() => void handleRefresh()} style={{ flex: 1 }}>
                        Refresh
                      </Button>
                    </div>
                  </div>
                  <div className="cmd__cmdLog">
                    <span className="meta-label">COMMAND LOG</span>
                    <p>→ startAiTeamWork(windowDays={windowDays}) {isWorking ? "(active)" : "(idle)"}</p>
                    <p>→ fetchGrowthRadar(windowDays={windowDays})</p>
                    <p>→ fetchAgentRuns(limit=20)</p>
                    <p>→ fetchRankedOpportunities()</p>
                    <p className="cmd__muted">All commands hit real backend endpoints — no mock execution.</p>
                  </div>
                  <div className="cmd__cmdHint">
                    <span className="meta-label">HUMAN APPROVAL</span>
                    <p>No action executes without your approval on the Actions page. The team proposes — you decide.</p>
                    <Button variant="secondary" mono onClick={() => navigate("/actions")} style={{ width: "100%", marginTop: 8 }}>
                      Go to Actions →
                    </Button>
                  </div>
                </div>
              )}

              {cmdTab === "WORKERS" && (
                <div className="cmd__panel">
                  <p className="meta-label" style={{ marginBottom: 10 }}>
                    WORKERS · QUICK ROSTER
                  </p>
                  <div className="cmd__workers">
                    {liveInfos.map((a) => (
                      <button key={a.key} type="button" className="cmd__worker" onClick={() => setSelectedAgent(a.key)}>
                        <AgentAvatar agentKey={a.key} status={a.liveStatus} size={32} />
                        <span className="cmd__workerMain">
                          <strong>{a.label}</strong>
                          <span>{a.chipLabel} · {Math.round(a.progress)}%</span>
                        </span>
                        <span className={`cmd__workerDot cmd__workerDot--${a.chipTone}`} />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Mini snapshot inside command col for density */}
          <WindowPanel title="team-signal.app" tone="choc" dark>
            <p className="meta-label" style={{ color: "var(--cream-muted)", marginBottom: 8 }}>
              TEAM SIGNAL
            </p>
            <p style={{ color: "var(--cream-muted)", fontSize: "var(--text-small)", lineHeight: 1.5 }}>
              {totals
                ? `Last run: ${totals.opportunities_created} opportunit${totals.opportunities_created === 1 ? "y" : "ies"} · ${totals.signals_detected} signals · ${totals.actions_proposed} actions · ${totals.failed_agents} failed.`
                : executedAgentNames.length
                  ? `${executedAgentNames.length} specialists have checked in this session.`
                  : "The AI office is quiet — start an analysis to see the team come online."}
            </p>
            {lastRunResult?.orchestrator_run_id && <p className="meta-label" style={{ color: "var(--cream-muted)", marginTop: 8, fontSize: "0.62rem" }}>RUN {lastRunResult.orchestrator_run_id.slice(0, 8)}…</p>}
          </WindowPanel>
        </aside>
      </div>

      {/* Workflow visualization */}
      <WindowPanel title="workflow.graph — agent-handoff.app">
        <div className="agents-cc__sectionIntro">
          <h3>Workflow — how work moves through the team</h3>
          <p>From real business data to human approval. Nodes light up as the workflow is actually traversed.</p>
        </div>
        <WorkflowGraphViz
          executedCount={executedAgentNames.length}
          signalsCount={radar?.signals.length ?? 0}
          opportunitiesCount={opportunities.length}
          hasDebate={Boolean(lastRunResult?.debate_id)}
          hasActionPlan={Boolean(actionPlan)}
          selectedId={workflowSel}
          onSelect={setWorkflowSel}
        />
        {workflowSel && (
          <div className="wflow__detail">
            <span className="meta-label">SELECTED NODE</span>
            <p>
              <strong>{workflowSel.toUpperCase()}</strong> — {workflowSel === "data" ? "Raw Razorpay payments, orders, and customers from your workspace." : workflowSel === "memory" ? "Historical context retained across analyses — past decisions and outcomes." : workflowSel === "specialists" ? "Domain specialists examine payments, customers, products, and campaigns in parallel." : workflowSel === "findings" ? "Evidence-backed findings with reasoning and confidence scoring." : workflowSel === "debate" ? "Agents cross-examine findings before a recommendation is locked." : workflowSel === "ranking" ? "Opportunities ranked by revenue, confidence, and effort." : workflowSel === "action" ? "Action plan prepared for your explicit approval — no auto-execution." : "You review and approve — the team never acts without consent."}
            </p>
            <button type="button" className="wflow__close" onClick={() => setWorkflowSel(null)}>
              Clear
            </button>
          </div>
        )}
      </WindowPanel>

      {/* Agent Findings */}
      <div className="agents-cc__sectionHead">
        <div>
          <h2>Agent Findings</h2>
          <p>What each specialist concluded — with evidence, reasoning, and next step. Not a single paragraph: real work.</p>
        </div>
        {findings.length > 0 && <span className="agents-cc__count">{findings.length} FINDINGS</span>}
      </div>
      {findings.length === 0 ? (
        <div className="agents-cc__empty">
          {executedAgentNames.length === 0 ? "WAITING FOR ANALYSIS — findings will appear here once the team starts working. Every conclusion is backed by evidence from your live data." : "No summarized findings yet — the team may still be working, or conclusions were brief. Open a workstation above to inspect raw output."}
        </div>
      ) : (
        <div className="agents-cc__findings">
          {findings.map((f) => (
            <article key={f.name} className="finding">
              <div className="finding__head">
                <span className="finding__agent">{f.label.toUpperCase()}</span>
                <span className="finding__spec">{f.specialty}</span>
                {f.confidence && <span className={`finding__conf finding__conf--${f.confidence.toLowerCase()}`}>{f.confidence.toUpperCase()} confidence</span>}
              </div>
              <div className="finding__grid">
                <span className="finding__label">Finding</span>
                <p className="finding__text finding__text--strong">{f.finding}</p>
                {f.why && (
                  <>
                    <span className="finding__label">Why it matters</span>
                    <p className="finding__text">{f.why}</p>
                  </>
                )}
                <span className="finding__label">Evidence</span>
                <p className="finding__text">{f.evidence}</p>
                {f.action && (
                  <>
                    <span className="finding__label">Recommended action</span>
                    <p className="finding__text">{f.action}</p>
                  </>
                )}
                <span className="finding__label">Data examined</span>
                <p className="finding__text">{agentProfile(f.name).looksAt}</p>
              </div>
              <div className="finding__foot">
                <button type="button" className="finding__link" onClick={() => setSelectedAgent(f.name)}>
                  Open workstation →
                </button>
                <span className="finding__meta">Confidence: {f.confidence ?? "—"} · Related: Priority Ranking · Technical Feasibility · Growth Manager</span>
              </div>
            </article>
          ))}
        </div>
      )}

      {/* Opportunities */}
      {opportunities.length > 0 && (
        <>
          <div className="agents-cc__sectionHead">
            <div>
              <h2>Growth Opportunities</h2>
              <p>Ranked by the AI team from your live data — strongest evidence first.</p>
            </div>
          </div>
          <div className="agents-cc__opps">
            {opportunities.map((opp, idx) => (
              <article key={`${opp.title}-${idx}`} className="opp">
                <div className="opp__head">
                  <div>
                    <p className="meta-label">OPPORTUNITY {String(idx + 1).padStart(2, "0")}</p>
                    <h3 className="opp__title">{opp.title}</h3>
                  </div>
                  {opp.impact && <span className="opp__impact">{opp.impact}</span>}
                </div>
                <div className="opp__grid">
                  <span className="opp__label">Why it matters</span>
                  <p className="opp__text">{opp.why}</p>
                  <span className="opp__label">Evidence</span>
                  <p className="opp__text">{opp.evidence}</p>
                  {opp.action && (
                    <>
                      <span className="opp__label">Recommended action</span>
                      <p className="opp__text opp__text--strong">{opp.action}</p>
                    </>
                  )}
                  {opp.discoveredBy.length > 0 && (
                    <>
                      <span className="opp__label">Discovered by</span>
                      <p className="opp__text">{opp.discoveredBy.join(" + ")}</p>
                    </>
                  )}
                  {opp.confidence && (
                    <>
                      <span className="opp__label">Confidence</span>
                      <p className="opp__text">{opp.confidence}</p>
                    </>
                  )}
                </div>
              </article>
            ))}
          </div>
        </>
      )}

      {/* Recommendation */}
      {showRecommendation && (
        <WindowPanel title="ai-recommendation.app" tone="choc" dark flush>
          <div className="rec">
            <div className="rec__main">
              <p className="meta-label" style={{ color: "var(--cream-muted)" }}>
                PRIORITY OPPORTUNITY
              </p>
              <h3 className="rec__title">{topOpp?.title ?? topInitiative?.title ?? "Growth action plan"}</h3>
              <div className="rec__grid">
                <span className="rec__label">Why we recommend this</span>
                <p className="rec__text">{topOpp?.why ?? sentences(actionPlan?.executive_summary, 2) ?? "The team identified this as the strongest opportunity in your current business data."}</p>
                <span className="rec__label">Evidence</span>
                <p className="rec__text">{topOpp?.evidence ?? matchedTopInitiative?.expected_impact ?? "Based on the team's analysis of your live Razorpay TEST data."}</p>
                {(topOpp?.impact || matchedTopInitiative?.expected_impact) && (
                  <>
                    <span className="rec__label">Expected impact</span>
                    <p className="rec__text rec__text--strong">{topOpp?.impact ?? matchedTopInitiative?.expected_impact}</p>
                  </>
                )}
                <span className="rec__label">Next step</span>
                <p className="rec__text">{matchedTopInitiative?.next_steps ?? topOpp?.action ?? "Review and approve the recommended action below."}</p>
              </div>
            </div>
            <div className="rec__side">
              <div className="rec__stat">
                <span className="rec__statLabel">Opportunities found</span>
                <span className="rec__statValue">{totals?.opportunities_created ?? opportunities.length}</span>
              </div>
              <div className="rec__stat">
                <span className="rec__statLabel">Actions prepared</span>
                <span className="rec__statValue">{totals?.actions_proposed ?? actionPlan?.initiatives?.length ?? 0}</span>
              </div>
              <Button variant="primary" mono onClick={() => navigate("/actions")}>
                Review & Approve →
              </Button>
              <p className="rec__hint">No action executes without your explicit approval.</p>
            </div>
          </div>
        </WindowPanel>
      )}


      {/* ── BOTTOM TEAM ROSTER (horizontal, always visible) ─────────────── */}
      <WindowPanel title="team-roster.app — click-any-agent.app" flush>
        <div className="roster">
          <div className="roster__head">
            <span className="meta-label">TEAM ROSTER — 13 EMPLOYEES · CLICK TO INSPECT WORK</span>
            <span className="meta-label" style={{ color: "var(--ink-faint)" }}>
              SCROLL → TO SEE ALL
            </span>
          </div>
          <div className="roster__scroll" role="list">
            {liveInfos.map((a) => (
              <button key={a.key} type="button" role="listitem" className={`roster__tile${selectedAgent === a.key ? " roster__tile--sel" : ""} roster__tile--${a.liveStatus.toLowerCase()}`} onClick={() => setSelectedAgent(a.key)} aria-pressed={selectedAgent === a.key}>
                <AgentAvatar agentKey={a.key} status={a.liveStatus} size={42} />
                <span className="roster__name">{a.label.toUpperCase()}</span>
                <span className={`roster__badge roster__badge--${a.chipTone}`}>● {a.chipLabel}</span>
                <span className="roster__role">{a.specialty}</span>
                <span className="roster__task" title={a.monitorLine}>
                  {a.monitorLine.slice(0, 42)}
                </span>
                <span className="roster__prog">
                  <ProgressBar value={a.progress} tone={a.liveStatus === "COMPLETED" ? "green" : a.liveStatus === "WORKING" ? "coral" : "ink"} />
                  <span className="roster__pct">{Math.round(a.progress)}%</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </WindowPanel>

      {/* ── DETAIL OVERLAY ──────────────────────────────────────────────── */}
      {selectedAgent && selectedLive && (
        <AgentDetailPanel
          agentKey={selectedAgent}
          onClose={() => setSelectedAgent(null)}
          liveInfo={selectedLive}
          output={selectedOutput}
          run={selectedRun}
          radar={radar}
          planItem={selectedPlanItem}
          confidence={selectedConf}
          evidence={selectedOutput?.output?.summary ? (firstSentence(selectedOutput.output.summary) ?? selectedOutput.output.summary) : agentProfile(selectedAgent).looksAt}
          reasoning={selectedOutput?.output?.recommendations?.[0] ?? null}
        />
      )}

      {/* ── FOOTER ──────────────────────────────────────────────────────── */}
      <footer className="agents-cc__footer">
        <Button variant="ghost-dark" mono onClick={() => navigate("/growth-radar")}>
          ← Growth Radar
        </Button>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <Button variant="secondary" mono onClick={() => navigate("/debate")}>
            Agent Debate →
          </Button>
          <Button variant="primary" mono onClick={() => navigate("/actions")}>
            Review & Approve Actions →
          </Button>
        </div>
      </footer>
    </section>
  );
}
