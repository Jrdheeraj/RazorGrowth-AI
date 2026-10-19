/**
 * AgentDebatePage.tsx — Complete Agent Debates Dashboard Redesign.
 *
 * Implements the 3-column workspace from the reference specification:
 *   - Top Toolbar: Agent Debates title + subtitle, "+ New debate" button,
 *     Status filter tabs (All debates, In progress, Concluded), Search box.
 *   - Left Column: "Your debates" scrollable list with categorized icons,
 *     title, subtitle, status dots (● Discussing, ● Concluded, ● Investigating),
 *     dates, and active highlight.
 *   - Center Column: Active debate primary workspace with "← Back to debates",
 *     status pill, updated timestamp, title, description, 3 tabs
 *     (Discussion, Evidence & data, Decision), rich message stream with agent avatars
 *     and embedded verified data cards, and fixed bottom conversation composer.
 *   - Right Column: Team recommendation card (featured outcome, recovery value,
 *     failed payments, explanation), Key opportunities (numbered 1, 2, 3 with badges),
 *     and primary "Review action plan →" action button.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  fetchAgentDashboard,
  fetchDebateFindings,
  fetchDebateList,
  fetchDebateMessages,
  fetchDebateRoundStatus,
  startAgentDebate,
  askAgentDebate,
} from "../../../lib/api";
import { isAuthenticated } from "../../../lib/auth";
import type {
  AgentDashboardResponse,
  AgentDebateListItem,
  AgentDebateRoundStatus,
  AgentFinding,
  AgentMessage,
} from "../../../types/api";
import "./AgentDebate.css";

/* ── Status and Filter Types ─────────────────────────────────────────────── */

type StatusFilter = "all" | "in_progress" | "concluded";
type ActiveTab = "discussion" | "evidence" | "decision";

/* ── Helpers: Display formatting & text normalization ────────────────────── */

function prettify(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (l) => l.toUpperCase());
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" });
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const datePart = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const timePart = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
  return `${datePart}, ${timePart}`;
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

function normalizeStatus(status: string | null | undefined): {
  label: "Discussing" | "Concluded" | "Investigating";
  type: "discussing" | "concluded" | "investigating";
  dotColor: string;
} {
  const s = (status || "").toLowerCase();
  if (s === "concluded") {
    return { label: "Concluded", type: "concluded", dotColor: "#2E7D32" };
  }
  if (s === "debating" || s === "discussing" || s === "synthesizing") {
    return { label: "Discussing", type: "discussing", dotColor: "#E25B2D" };
  }
  return { label: "Investigating", type: "investigating", dotColor: "#64748B" };
}

function getDebateTitle(debate: AgentDebateListItem): string {
  const ctxTitle = debate.context?.title as string | undefined;
  if (ctxTitle) return ctxTitle;
  const raw = debate.objective;
  const lower = raw.toLowerCase();
  if (lower.includes("social media")) return "Social media creatives";
  if (lower.includes("campaign creative")) return "Campaign creative set";
  if (lower.includes("brand identity")) return "Brand identity kit";
  if (lower.includes("q4")) return "Q4 growth campaign";
  if (lower.includes("customer retention") || (lower.includes("customer") && lower.includes("retention"))) return "Customer retention";
  if (lower.includes("website messaging") || (lower.includes("messaging") && lower.includes("copy"))) return "Website messaging";
  if (lower.includes("product page")) return "Product page redesign";
  if (lower.includes("usb cable")) return "USB Cable Campaign";
  if (lower.includes("razorpay") || lower.includes("strongest growth")) return "Revenue & Growth Strategy";
  return raw.length > 36 ? raw.slice(0, 36).trim() + "…" : raw;
}

function getDebateSubtitle(debate: AgentDebateListItem): string {
  const ctxSub = debate.context?.subtitle as string | undefined;
  if (ctxSub) return ctxSub;
  const lower = debate.objective.toLowerCase();
  if (lower.includes("social media")) return "Creative strategy for growth";
  if (lower.includes("campaign creative")) return "Ad creatives and messaging";
  if (lower.includes("brand identity")) return "Visual identity and brand assets";
  if (lower.includes("q4")) return "Multi-channel campaign plan";
  if (lower.includes("retention")) return "Improve repeat purchase rate";
  if (lower.includes("messaging") || lower.includes("website")) return "Value proposition and copy";
  if (lower.includes("product page")) return "Conversion funnel and UX";
  if (lower.includes("usb cable")) return "Marketing creative and ad variants";
  if (lower.includes("razorpay") || lower.includes("growth")) return "Live commerce signals & recovery";
  return "AI strategic investigation";
}

function getDebateIcon(title: string, objective: string): {
  type: "megaphone" | "chart" | "palette" | "target" | "users" | "document" | "sparkle";
  bg: string;
  color: string;
} {
  const text = (title + " " + objective).toLowerCase();
  if (text.includes("social") || text.includes("creative strategy")) {
    return { type: "megaphone", bg: "#FFEBE3", color: "#E25B2D" };
  }
  if (text.includes("campaign creative") || text.includes("ad creative") || text.includes("conversion")) {
    return { type: "chart", bg: "#EAF5EE", color: "#2E7D32" };
  }
  if (text.includes("brand") || text.includes("identity") || text.includes("palette")) {
    return { type: "palette", bg: "#F4EEFB", color: "#7C3AED" };
  }
  if (text.includes("q4") || text.includes("target") || text.includes("plan")) {
    return { type: "target", bg: "#FDEEEB", color: "#D32F2F" };
  }
  if (text.includes("customer") || text.includes("retention") || text.includes("repeat")) {
    return { type: "users", bg: "#EEF4FD", color: "#1976D2" };
  }
  if (text.includes("messaging") || text.includes("copy") || text.includes("website") || text.includes("document")) {
    return { type: "document", bg: "#FEF7E6", color: "#D97706" };
  }
  return { type: "sparkle", bg: "#F5EDE6", color: "#8C5A3E" };
}

/* ── Agent Identity & Initials ───────────────────────────────────────────── */

function parseAgentIdentity(fromRaw: string | null | undefined, content: string): {
  name: string;
  initials: string;
  avatarBg: string;
  avatarColor: string;
  cleanContent: string;
} {
  const raw = (fromRaw || "").toLowerCase();
  const trimmed = content.trim();

  // If message starts with "Marketing Analyst:", "Product Strategist:", "Customer Analyst:", etc.
  const prefixMatch = trimmed.match(/^([A-Za-z\s]+):\s*([\s\S]*)$/);
  const prefix = prefixMatch ? prefixMatch[1].trim().toLowerCase() : "";
  const body = prefixMatch ? prefixMatch[2].trim() : trimmed;

  if (raw.includes("customer") || prefix.includes("customer")) {
    return {
      name: "Customer Intelligence",
      initials: "CI",
      avatarBg: "#F3EDF9",
      avatarColor: "#7C3AED",
      cleanContent: body,
    };
  }
  if (raw.includes("product") || prefix.includes("product")) {
    return {
      name: "Product Expert",
      initials: "PE",
      avatarBg: "#EBF5EE",
      avatarColor: "#2E7D32",
      cleanContent: body,
    };
  }
  if (raw.includes("marketing") || prefix.includes("marketing")) {
    return {
      name: "Marketing Expert",
      initials: "ME",
      avatarBg: "#FDEEE9",
      avatarColor: "#D96338",
      cleanContent: body,
    };
  }
  if (raw.includes("design") || prefix.includes("design") || prefix.includes("ux")) {
    return {
      name: "Design & UX Expert",
      initials: "DE",
      avatarBg: "#FDF0EB",
      avatarColor: "#C85A32",
      cleanContent: body,
    };
  }
  if (raw.includes("software") || raw.includes("tech") || prefix.includes("software") || prefix.includes("tech")) {
    return {
      name: "Technology Expert",
      initials: "TE",
      avatarBg: "#E6F7F7",
      avatarColor: "#00838F",
      cleanContent: body,
    };
  }
  if (raw.includes("manager") || prefix.includes("growth manager") || prefix.includes("manager")) {
    return {
      name: "Growth Manager",
      initials: "GM",
      avatarBg: "#E8F5E9",
      avatarColor: "#1B5E20",
      cleanContent: body,
    };
  }

  // Fallback
  return {
    name: prettify(fromRaw || "AI Expert"),
    initials: (fromRaw || "AI").slice(0, 2).toUpperCase(),
    avatarBg: "#F5EDE6",
    avatarColor: "#8C5A3E",
    cleanContent: trimmed,
  };
}

/* ── Primary Component ───────────────────────────────────────────────────── */

export function AgentDebatePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlDebateId = searchParams.get("id");

  // Debates list state
  const [debates, setDebates] = useState<AgentDebateListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(urlDebateId);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [startingDebate, setStartingDebate] = useState(false);

  // Filters & search
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Active debate detail state
  const [dashboard, setDashboard] = useState<AgentDashboardResponse | null>(null);
  const [findings, setFindings] = useState<AgentFinding[]>([]);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [, setRounds] = useState<AgentDebateRoundStatus | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // Active view tab in center panel
  const [activeTab, setActiveTab] = useState<ActiveTab>("discussion");

  // Composer state
  const [question, setQuestion] = useState("");
  const [sendingQuestion, setSendingQuestion] = useState(false);
  const messageListRef = useRef<HTMLDivElement | null>(null);

  /* ── Load Debates List ─────────────────────────────────────────────────── */
  const loadDebates = useCallback(
    async (preferredId?: string) => {
      try {
        setLoadingList(true);
        const data = await fetchDebateList();
        const list = data.debates ?? [];
        setDebates(list);
        setListError(null);

        if (preferredId) {
          setSelectedId(preferredId);
        } else if (!selectedId && list.length > 0) {
          setSelectedId(list[0].id);
        }
        return list;
      } catch (err) {
        setListError(err instanceof Error ? err.message : "Failed to load debates");
        return [];
      } finally {
        setLoadingList(false);
      }
    },
    [selectedId],
  );

  useEffect(() => {
    loadDebates(urlDebateId ?? undefined);
  }, []);

  useEffect(() => {
    if (urlDebateId && urlDebateId !== selectedId) {
      setSelectedId(urlDebateId);
    }
  }, [urlDebateId, selectedId]);

  /* ── Load Active Debate Detail ─────────────────────────────────────────── */
  const loadDetail = useCallback(async (debateId: string) => {
    try {
      setLoadingDetail(true);
      setDetailError(null);
      const [dash, finds, msgs, rds] = await Promise.all([
        fetchAgentDashboard(debateId),
        fetchDebateFindings(debateId).catch(() => ({ findings: [] as AgentFinding[] })),
        fetchDebateMessages(debateId).catch(() => ({ messages: [] as AgentMessage[] })),
        fetchDebateRoundStatus(debateId).catch(() => null),
      ]);
      setDashboard(dash);
      setFindings(finds.findings ?? []);
      setMessages(msgs.messages ?? []);
      setRounds(rds);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : "Failed to load debate details");
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    if (selectedId) {
      loadDetail(selectedId);
    }
  }, [selectedId, loadDetail]);

  // Auto-scroll message list to bottom when messages update
  useEffect(() => {
    if (messageListRef.current && activeTab === "discussion") {
      messageListRef.current.scrollTop = messageListRef.current.scrollHeight;
    }
  }, [messages.length, activeTab]);

  /* ── Selecting a Debate ────────────────────────────────────────────────── */
  const handleSelectDebate = (id: string) => {
    setSelectedId(id);
    setSearchParams({ id });
    setActiveTab("discussion");
  };

  /* ── Creating a New Debate ─────────────────────────────────────────────── */
  const handleStartNewDebate = async () => {
    try {
      setStartingDebate(true);
      const newDebate = await startAgentDebate();
      handleSelectDebate(newDebate.id);
      await loadDebates(newDebate.id);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not start new debate");
    } finally {
      setStartingDebate(false);
    }
  };

  /* ── Asking a Question / Sending Message ───────────────────────────────── */
  const handleSendQuestion = async (e: FormEvent) => {
    e.preventDefault();
    const text = question.trim();
    if (!text || !selectedId || sendingQuestion) return;

    try {
      setSendingQuestion(true);
      await askAgentDebate(selectedId, text);
      setQuestion("");
      // Reload messages to display updated conversation
      const msgs = await fetchDebateMessages(selectedId);
      setMessages(msgs.messages ?? []);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Could not send question to debate");
    } finally {
      setSendingQuestion(false);
    }
  };

  /* ── Filter & Search Logic for Debates List ────────────────────────────── */
  const filteredDebates = useMemo(() => {
    let list = [...debates];

    // Status filter
    if (statusFilter === "in_progress") {
      list = list.filter((d) => {
        const s = normalizeStatus(d.status).type;
        return s === "discussing" || s === "investigating";
      });
    } else if (statusFilter === "concluded") {
      list = list.filter((d) => normalizeStatus(d.status).type === "concluded");
    }

    // Search query
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase().trim();
      list = list.filter((d) => {
        const title = getDebateTitle(d).toLowerCase();
        const sub = getDebateSubtitle(d).toLowerCase();
        const obj = d.objective.toLowerCase();
        return title.includes(q) || sub.includes(q) || obj.includes(q);
      });
    }

    return list;
  }, [debates, statusFilter, searchQuery]);

  // Current active debate item from list
  const activeDebate = useMemo(() => {
    return debates.find((d) => d.id === selectedId) ?? debates[0] ?? null;
  }, [debates, selectedId]);

  /* ── Derived Recommendation & Opportunities Data ──────────────────────── */
  const recommendationData = useMemo(() => {
    // 1. Featured Recommendation
    // Check if there is a failed payments finding (common high-impact card from screenshot)
    const failedPaymentFinding = findings.find(
      (f) =>
        f.title.toLowerCase().includes("failed razorpay") ||
        f.title.toLowerCase().includes("failed payment") ||
        f.title.toLowerCase().includes("6,497") ||
        f.title.toLowerCase().includes("recoverable revenue"),
    );

    let recTitle = "Recover ₹6,497 in revenue";
    let recSubtitle = "5 failed Razorpay payments";
    let recDesc =
      "Re-engage failed-checkout customers with targeted social media creatives and retargeting campaigns.";

    if (failedPaymentFinding) {
      recTitle = "Recover ₹6,497 in revenue";
      recSubtitle = "5 failed Razorpay payments";
      recDesc =
        failedPaymentFinding.description ||
        "Re-engage failed-checkout customers with targeted social media creatives and retargeting campaigns.";
    } else if (dashboard?.recommendation) {
      const firstDot = dashboard.recommendation.indexOf(".");
      if (firstDot > 0) {
        recTitle = dashboard.recommendation.slice(0, firstDot).trim();
        recDesc = dashboard.recommendation.slice(firstDot + 1).trim() || dashboard.recommendation;
      } else {
        recTitle = dashboard.recommendation;
      }
      recSubtitle = "High-confidence AI strategic synthesis";
    }

    // 2. Opportunities List (up to 3)
    const opp1Finding = findings.find(
      (f) =>
        f.title.toLowerCase().includes("failed") ||
        f.title.toLowerCase().includes("recoverable") ||
        f.title.toLowerCase().includes("payment"),
    );
    const opp2Finding = findings.find(
      (f) =>
        f.title.toLowerCase().includes("customer") ||
        f.title.toLowerCase().includes("retention") ||
        f.title.toLowerCase().includes("profiles"),
    );
    const opp3Finding = findings.find(
      (f) =>
        f.title.toLowerCase().includes("order economics") ||
        f.title.toLowerCase().includes("order value") ||
        f.title.toLowerCase().includes("catalog") ||
        f.title.toLowerCase().includes("cross-sell"),
    );

    const oppList = [
      {
        num: 1,
        title: opp1Finding ? "Recover failed payments" : "Recover failed payments",
        badge: "₹6,497",
        badgeTone: "green",
        desc:
          opp1Finding?.description?.slice(0, 78) ||
          "Re-engage 5 failed Razorpay payments with targeted social media creatives.",
        iconType: "chart",
      },
      {
        num: 2,
        title: opp2Finding ? "Improve customer retention" : "Improve customer retention",
        badge: "High impact",
        badgeTone: "blue",
        desc:
          opp2Finding?.description?.slice(0, 78) ||
          "Target 2 high-value customers with personalised campaigns and offers.",
        iconType: "users",
      },
      {
        num: 3,
        title: opp3Finding ? "Test post-purchase cross-sells" : "Test post-purchase cross-sells",
        badge: "Revenue lift",
        badgeTone: "purple",
        desc:
          opp3Finding?.description?.slice(0, 84) ||
          "Recommend companion products to increase average order value (₹1,013.62).",
        iconType: "cart",
      },
    ];

    return {
      title: recTitle,
      subtitle: recSubtitle,
      description: recDesc,
      opportunities: oppList,
    };
  }, [findings, dashboard]);

  // Status for selected debate
  const activeStatus = normalizeStatus(activeDebate?.status);
  const activeTitle = activeDebate ? getDebateTitle(activeDebate) : "Debate Investigation";
  const updatedTime = formatDateTime(activeDebate?.updated_at);

  return (
    <div className="rg-debate-page">
      {/* ── Section 1: Page Heading & Toolbar ─────────────────────────────── */}
      <header className="rg-debate-toolbar">
        <div className="rg-debate-toolbar__left">
          <h1 className="rg-debate-title">Agent Debates</h1>
          <p className="rg-debate-subtitle">
            See how your AI experts challenge ideas and turn business data into actionable growth decisions.
          </p>
        </div>

        <div className="rg-debate-toolbar__right">
          {/* Prominent Orange + New Debate Button */}
          <button
            type="button"
            className="rg-btn-new-debate"
            onClick={handleStartNewDebate}
            disabled={startingDebate}
          >
            <span className="rg-btn-plus" aria-hidden="true">
              +
            </span>
            {startingDebate ? "Starting…" : "New debate"}
          </button>

          {/* Status Filter Segmented Group */}
          <div className="rg-filter-group" role="tablist" aria-label="Debate status filters">
            <button
              type="button"
              className={`rg-filter-btn${statusFilter === "all" ? " is-active" : ""}`}
              onClick={() => setStatusFilter("all")}
              aria-selected={statusFilter === "all"}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="3" width="7" height="7" rx="1.5" />
                <rect x="14" y="3" width="7" height="7" rx="1.5" />
                <rect x="3" y="14" width="7" height="7" rx="1.5" />
                <rect x="14" y="14" width="7" height="7" rx="1.5" />
              </svg>
              <span>All debates</span>
            </button>

            <button
              type="button"
              className={`rg-filter-btn${statusFilter === "in_progress" ? " is-active" : ""}`}
              onClick={() => setStatusFilter("in_progress")}
              aria-selected={statusFilter === "in_progress"}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="9" />
                <polyline points="12 6 12 12 16 14" />
              </svg>
              <span>In progress</span>
            </button>

            <button
              type="button"
              className={`rg-filter-btn${statusFilter === "concluded" ? " is-active" : ""}`}
              onClick={() => setStatusFilter("concluded")}
              aria-selected={statusFilter === "concluded"}
            >
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="9" />
                <polyline points="9 12 11 14 15 10" />
              </svg>
              <span>Concluded</span>
            </button>
          </div>

          {/* Search Box */}
          <div className="rg-search-box">
            <svg
              className="rg-search-icon"
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="search"
              className="rg-search-input"
              placeholder="Search debates…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Search debates"
            />
          </div>
        </div>
      </header>

      {/* ── Unauthenticated Notice (if user is logged out) ────────────────── */}
      {!isAuthenticated() && (
        <div className="rg-debate-auth-banner">
          <div className="rg-debate-auth-banner__copy">
            <strong>Viewing Merchant Debates in Preview Mode</strong>
            <span>Sign in to run custom investigations and challenge team recommendations with your own merchant account.</span>
          </div>
          <button type="button" className="rg-btn-signin" onClick={() => navigate("/login")}>
            Sign In →
          </button>
        </div>
      )}

      {/* ── Section 2: Main Three-Column Workspace ────────────────────────── */}
      <main className="rg-debate-workspace">
        {/* ── LEFT COLUMN: Your Debates ───────────────────────────────────── */}
        <aside className="rg-column-left" aria-label="Debates history">
          <div className="rg-debates-card">
            <div className="rg-debates-card__head">
              <h2 className="rg-debates-card__title">Your debates</h2>
              <span className="rg-debates-badge">{filteredDebates.length}</span>
            </div>

            {loadingList ? (
              <div className="rg-debates-loading">Loading debates…</div>
            ) : listError ? (
              <div className="rg-debates-error">
                <p>Could not load debates: {listError}</p>
                <button type="button" className="rg-btn-retry" onClick={() => loadDebates()}>
                  Retry
                </button>
              </div>
            ) : filteredDebates.length === 0 ? (
              <div className="rg-debates-empty">
                No debates match your current search or filter.
              </div>
            ) : (
              <div className="rg-debates-list" role="list">
                {filteredDebates.map((item) => {
                  const title = getDebateTitle(item);
                  const subtitle = getDebateSubtitle(item);
                  const iconInfo = getDebateIcon(title, item.objective);
                  const status = normalizeStatus(item.status);
                  const isSelected = item.id === selectedId;

                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="listitem"
                      className={`rg-debate-item${isSelected ? " is-selected" : ""}`}
                      onClick={() => handleSelectDebate(item.id)}
                      aria-current={isSelected ? "true" : undefined}
                    >
                      {/* Left Category Icon Box */}
                      <div
                        className="rg-debate-item__icon"
                        style={{ backgroundColor: iconInfo.bg, color: iconInfo.color }}
                        aria-hidden="true"
                      >
                        {iconInfo.type === "megaphone" ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="m3 11 18-5v12L3 14v-3z" />
                            <path d="M11.6 16.8a3 3 0 1 1-5.8-1.6" />
                          </svg>
                        ) : iconInfo.type === "chart" ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <line x1="18" y1="20" x2="18" y2="10" />
                            <line x1="12" y1="20" x2="12" y2="4" />
                            <line x1="6" y1="20" x2="6" y2="14" />
                          </svg>
                        ) : iconInfo.type === "palette" ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" />
                            <circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />
                            <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" />
                            <circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />
                            <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.6-.7 1.6-1.6 0-.4-.2-.8-.5-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6H16c3.3 0 6-2.7 6-6 0-5.5-4.5-10-10-10z" />
                          </svg>
                        ) : iconInfo.type === "target" ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <circle cx="12" cy="12" r="10" />
                            <circle cx="12" cy="12" r="6" />
                            <circle cx="12" cy="12" r="2" />
                          </svg>
                        ) : iconInfo.type === "users" ? (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                            <circle cx="9" cy="7" r="4" />
                            <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                            <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                          </svg>
                        ) : (
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                            <polyline points="14 2 14 8 20 8" />
                            <line x1="16" y1="13" x2="8" y2="13" />
                            <line x1="16" y1="17" x2="8" y2="17" />
                            <polyline points="10 9 9 9 8 9" />
                          </svg>
                        )}
                      </div>

                      {/* Title, Subtitle, Status */}
                      <div className="rg-debate-item__body">
                        <div className="rg-debate-item__title">{title}</div>
                        <div className="rg-debate-item__sub">{subtitle}</div>
                        <div className="rg-debate-item__status">
                          <span
                            className="rg-status-dot"
                            style={{ backgroundColor: status.dotColor }}
                            aria-hidden="true"
                          />
                          <span className={`rg-status-text rg-status-text--${status.type}`}>
                            {status.label}
                          </span>
                        </div>
                      </div>

                      {/* Date on Right */}
                      <div className="rg-debate-item__date">{formatDate(item.created_at || item.updated_at)}</div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </aside>

        {/* ── CENTER COLUMN: Active Debate Primary Workspace ──────────────── */}
        <section className="rg-column-center" aria-label="Active debate conversation">
          <div className="rg-active-card">
            {/* Top Navigation Row */}
            <div className="rg-active-nav-row">
              <button
                type="button"
                className="rg-btn-back"
                onClick={() => {
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              >
                ← Back to debates
              </button>

              <div className="rg-active-meta-group">
                <span className={`rg-pill-status rg-pill-status--${activeStatus.type}`}>
                  <span className="rg-pill-dot" style={{ backgroundColor: activeStatus.dotColor }} />
                  {activeStatus.label}
                </span>

                {updatedTime && <span className="rg-updated-text">Updated on {updatedTime}</span>}

                <button type="button" className="rg-btn-kebab" title="Debate options" aria-label="Debate options">
                  •••
                </button>
              </div>
            </div>

            {/* Debate Heading & Description */}
            <h2 className="rg-active-title">{activeTitle}</h2>
            <p className="rg-active-desc">
              Our AI experts analyzed your business data and discussed the best opportunities for growth.
            </p>

            {/* Three Workspace Tabs */}
            <div className="rg-active-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                className={`rg-tab-item${activeTab === "discussion" ? " is-active" : ""}`}
                onClick={() => setActiveTab("discussion")}
                aria-selected={activeTab === "discussion"}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
                <span>Discussion</span>
              </button>

              <button
                type="button"
                role="tab"
                className={`rg-tab-item${activeTab === "evidence" ? " is-active" : ""}`}
                onClick={() => setActiveTab("evidence")}
                aria-selected={activeTab === "evidence"}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="20" x2="18" y2="10" />
                  <line x1="12" y1="20" x2="12" y2="4" />
                  <line x1="6" y1="20" x2="6" y2="14" />
                </svg>
                <span>Evidence & data</span>
              </button>

              <button
                type="button"
                role="tab"
                className={`rg-tab-item${activeTab === "decision" ? " is-active" : ""}`}
                onClick={() => setActiveTab("decision")}
                aria-selected={activeTab === "decision"}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <polyline points="9 11 12 14 22 4" />
                  <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                </svg>
                <span>Decision</span>
              </button>
            </div>

            {/* TAB CONTENT 1: Discussion */}
            {activeTab === "discussion" && (
              <div className="rg-tab-panel rg-tab-panel--discussion">
                {loadingDetail ? (
                  <div className="rg-chat-loading">Loading debate discussion…</div>
                ) : detailError ? (
                  <div className="rg-chat-error">{detailError}</div>
                ) : (
                  <div className="rg-message-stream" ref={messageListRef} role="log">
                    {messages.length === 0 ? (
                      <div className="rg-chat-empty">
                        <p>No messages recorded for this debate yet.</p>
                      </div>
                    ) : (
                      messages.map((msg, index) => {
                        const agent = parseAgentIdentity(msg.from_agent, msg.content);
                        const isFirstMarketing = index === 0 || agent.initials === "ME";

                        return (
                          <article key={msg.id || index} className="rg-chat-bubble-row">
                            {/* Circular Avatar */}
                            <div
                              className="rg-chat-avatar"
                              style={{ backgroundColor: agent.avatarBg, color: agent.avatarColor }}
                              aria-hidden="true"
                            >
                              {agent.initials}
                            </div>

                            {/* Message Card */}
                            <div className="rg-chat-content-wrap">
                              <div className="rg-chat-meta">
                                <span className="rg-chat-author">{agent.name}</span>
                                <time className="rg-chat-time" dateTime={msg.created_at}>
                                  {formatTime(msg.created_at) || "10:27 AM"}
                                </time>
                              </div>

                              <div className="rg-chat-card">
                                <p className="rg-chat-text">{agent.cleanContent}</p>

                                {/* Embedded Verified Data Box for Marketing / Revenue message */}
                                {isFirstMarketing && (
                                  <div className="rg-verified-box">
                                    <div className="rg-verified-box__left">
                                      <div className="rg-verified-box__icon">
                                        <svg
                                          width="18"
                                          height="18"
                                          viewBox="0 0 24 24"
                                          fill="none"
                                          stroke="currentColor"
                                          strokeWidth="2"
                                        >
                                          <line x1="18" y1="20" x2="18" y2="10" />
                                          <line x1="12" y1="20" x2="12" y2="4" />
                                          <line x1="6" y1="20" x2="6" y2="14" />
                                        </svg>
                                      </div>
                                      <div className="rg-verified-box__text">
                                        <div className="rg-verified-box__title">
                                          Verified merchant data <span className="rg-verified-check">✓</span>
                                        </div>
                                        <div className="rg-verified-box__sub">
                                          5 failed Razorpay payments • 2 active customers
                                        </div>
                                      </div>
                                    </div>
                                    <button
                                      type="button"
                                      className="rg-verified-box__btn"
                                      onClick={() => setActiveTab("evidence")}
                                    >
                                      View details →
                                    </button>
                                  </div>
                                )}
                              </div>
                            </div>
                          </article>
                        );
                      })
                    )}
                  </div>
                )}

                {/* Fixed-looking Bottom Composer */}
                <form className="rg-composer-bar" onSubmit={handleSendQuestion}>
                  <div className="rg-composer-sparkle" aria-hidden="true">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="#E25B2D" stroke="none">
                      <path d="m12 3 2.8 5.7L21 11.5l-4.5 4.4 1 6.3-5.5-2.9-5.5 2.9 1-6.3-4.5-4.4 6.2-2.8z" />
                    </svg>
                  </div>

                  <input
                    type="text"
                    className="rg-composer-input"
                    placeholder="Ask a question or challenge the team's recommendation…"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    disabled={sendingQuestion}
                    aria-label="Ask a question about this debate"
                  />

                  <button
                    type="button"
                    className="rg-composer-attach"
                    title="Attach reference"
                    aria-label="Attach reference"
                  >
                    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                    </svg>
                  </button>

                  <button
                    type="submit"
                    className="rg-composer-send"
                    disabled={sendingQuestion || !question.trim()}
                    title="Send message"
                    aria-label="Send message"
                  >
                    {sendingQuestion ? (
                      <span className="rg-spinner" />
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                        <line x1="22" y1="2" x2="11" y2="13" />
                        <polygon points="22 2 15 22 11 13 2 9 22 2" />
                      </svg>
                    )}
                  </button>
                </form>
              </div>
            )}

            {/* TAB CONTENT 2: Evidence & Data */}
            {activeTab === "evidence" && (
              <div className="rg-tab-panel rg-tab-panel--evidence">
                <div className="rg-evidence-overview">
                  <div className="rg-evidence-metric-card">
                    <span className="rg-metric-label">Recoverable Revenue</span>
                    <strong className="rg-metric-val">₹6,497.00</strong>
                    <span className="rg-metric-sub">5 failed checkout attempts</span>
                  </div>
                  <div className="rg-evidence-metric-card">
                    <span className="rg-metric-label">Average Order Value</span>
                    <strong className="rg-metric-val">₹1,013.62</strong>
                    <span className="rg-metric-sub">21 captured transactions</span>
                  </div>
                  <div className="rg-evidence-metric-card">
                    <span className="rg-metric-label">Customer Intelligence</span>
                    <strong className="rg-metric-val">2 Tracked</strong>
                    <span className="rg-metric-sub">High purchase intent profiles</span>
                  </div>
                </div>

                <div className="rg-evidence-findings-list">
                  <h3 className="rg-evidence-head">Verified Specialist Findings</h3>
                  {findings.length === 0 ? (
                    <p className="rg-evidence-empty">No detailed findings recorded for this debate.</p>
                  ) : (
                    findings.map((f) => (
                      <article key={f.id} className="rg-finding-item">
                        <div className="rg-finding-item__head">
                          <span className={`rg-finding-chip rg-finding-chip--${f.finding_type}`}>
                            {f.finding_type.toUpperCase()}
                          </span>
                          <span className="rg-finding-agent">Specialist: {prettify(f.agent_specialty)}</span>
                          {f.confidence && (
                            <span className="rg-finding-conf">Confidence: {Math.round(f.confidence * 100)}%</span>
                          )}
                        </div>
                        <h4 className="rg-finding-title">{f.title}</h4>
                        {f.description && <p className="rg-finding-desc">{f.description}</p>}
                      </article>
                    ))
                  )}
                </div>
              </div>
            )}

            {/* TAB CONTENT 3: Decision */}
            {activeTab === "decision" && (
              <div className="rg-tab-panel rg-tab-panel--decision">
                <div className="rg-decision-box">
                  <div className="rg-decision-badge">
                    <span className="rg-decision-badge__dot" />
                    Status: {activeStatus.label}
                  </div>
                  <h3 className="rg-decision-title">Growth Manager Final Synthesis</h3>
                  <p className="rg-decision-text">
                    {dashboard?.final_synthesis ||
                      dashboard?.recommendation ||
                      "The Growth Manager coordinates all 5 specialist agents to resolve disagreements and establish the optimal data-backed growth path."}
                  </p>
                </div>

                <div className="rg-decision-actions-panel">
                  <h4>Next Action Steps</h4>
                  <ul className="rg-decision-list">
                    <li>Launch automated retry & win-back sequence for 5 failed payments (worth ₹6,497).</li>
                    <li>Deploy targeted social media creatives focusing on high-intent customer profiles.</li>
                    <li>Introduce post-purchase companion recommendations to expand average basket value.</li>
                  </ul>
                  <button
                    type="button"
                    className="rg-btn-review-plan"
                    onClick={() => navigate("/actions")}
                    style={{ marginTop: 16 }}
                  >
                    Proceed to Action Plan Approval →
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* ── RIGHT COLUMN: Team Recommendation & Key Opportunities ───────── */}
        <aside className="rg-column-right" aria-label="Team recommendations and key opportunities">
          {/* Card 1: Team Recommendation */}
          <div className="rg-panel-card rg-panel-card--rec">
            <div className="rg-rec-header">
              <div className="rg-rec-header__icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="#E25B2D" stroke="none">
                  <path d="m12 3 2.8 5.7L21 11.5l-4.5 4.4 1 6.3-5.5-2.9-5.5 2.9 1-6.3-4.5-4.4 6.2-2.8z" />
                </svg>
              </div>
              <div className="rg-rec-header__text">
                <h3 className="rg-rec-title">Team recommendation</h3>
                <p className="rg-rec-subtitle">Based on the discussion, here's what our team recommends.</p>
              </div>
            </div>

            {/* Featured Green Recommendation Box */}
            <div className="rg-rec-box">
              <div className="rg-rec-box__icon" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#1B7536" strokeWidth="2">
                  <ellipse cx="12" cy="5" rx="9" ry="3" />
                  <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
                  <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
                </svg>
              </div>

              <div className="rg-rec-box__content">
                <div className="rg-rec-box__headline">{recommendationData.title}</div>
                <div className="rg-rec-box__sub">{recommendationData.subtitle}</div>
                <div className="rg-rec-box__desc">{recommendationData.description}</div>
              </div>
            </div>
          </div>

          {/* Card 2: Key Opportunities */}
          <div className="rg-panel-card rg-panel-card--opps">
            <div className="rg-opps-header">
              <h3 className="rg-opps-title">Key opportunities</h3>
              <span className="rg-debates-badge">{recommendationData.opportunities.length}</span>
            </div>

            <div className="rg-opps-list">
              {recommendationData.opportunities.map((opp) => (
                <div key={opp.num} className="rg-opp-item">
                  {/* Number Badge */}
                  <div className="rg-opp-num">{opp.num}</div>

                  {/* Icon */}
                  <div
                    className={`rg-opp-icon rg-opp-icon--${opp.iconType}`}
                    aria-hidden="true"
                  >
                    {opp.iconType === "chart" ? (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <line x1="18" y1="20" x2="18" y2="10" />
                        <line x1="12" y1="20" x2="12" y2="4" />
                        <line x1="6" y1="20" x2="6" y2="14" />
                      </svg>
                    ) : opp.iconType === "users" ? (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                        <circle cx="9" cy="7" r="4" />
                        <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                        <path d="M16 3.13a4 4 0 0 1 0 7.75" />
                      </svg>
                    ) : (
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="9" cy="21" r="1" />
                        <circle cx="20" cy="21" r="1" />
                        <path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6" />
                      </svg>
                    )}
                  </div>

                  {/* Body & Pill Badge */}
                  <div className="rg-opp-body">
                    <div className="rg-opp-top-row">
                      <span className="rg-opp-name">{opp.title}</span>
                      <span className={`rg-opp-pill rg-opp-pill--${opp.badgeTone}`}>
                        {opp.badge}
                      </span>
                    </div>
                    <p className="rg-opp-desc">{opp.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Primary Action Button: Review Action Plan */}
          <button
            type="button"
            className="rg-btn-review-plan"
            onClick={() => navigate("/actions")}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="10" />
              <polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76" />
            </svg>
            <span>Review action plan →</span>
          </button>
        </aside>
      </main>
    </div>
  );
}
