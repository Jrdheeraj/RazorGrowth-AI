/**
 * AgentDebatePage
 *
 * Frontend-only redesign of the debate detail surface. All rendered content
 * comes from the existing Agent Debate APIs.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  fetchAgentDashboard,
  fetchDebateFindings,
  fetchDebateList,
  fetchDebateMessages,
  fetchDebateRoundStatus,
  startAgentDebate,
  askAgentDebate,
} from "../../../lib/api";
import type {
  AgentDashboardResponse,
  AgentDebateListItem,
  AgentDebateRoundStatus,
  AgentFinding,
  AgentMessage,
} from "../../../types/api";
import "./AgentDebate.css";

const AGENT_LABELS: Record<string, string> = {
  manager: "Growth Manager",
  marketing: "Marketing Expert",
  product: "Product Expert",
  designer: "Design & UX Expert",
  design: "Design & UX Expert",
  software: "Technology Expert",
  technology: "Technology Expert",
};

const AGENT_TONES: Record<string, string> = {
  manager: "green",
  marketing: "warm",
  product: "mist",
  designer: "terracotta",
  design: "terracotta",
  software: "amber",
  technology: "amber",
};

function normalizeKey(value: string | null | undefined) {
  return (value ?? "").toLowerCase().replace(/[^a-z]/g, "");
}

function agentLabel(raw: string | null | undefined) {
  const key = normalizeKey(raw);
  return AGENT_LABELS[key] ?? prettify(raw ?? "AI Expert");
}

function agentInitials(raw: string | null | undefined) {
  const label = agentLabel(raw);
  const words = label.split(/\s+/).filter(Boolean);
  return (words[0]?.[0] ?? "A") + (words[1]?.[0] ?? "");
}

function agentTone(raw: string | null | undefined) {
  return AGENT_TONES[normalizeKey(raw)] ?? "neutral";
}

function prettify(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value: string | null | undefined, options: Intl.DateTimeFormatOptions = {}) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", ...options });
}

function formatTime(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function shortStatus(status: string | null | undefined) {
  const value = status ?? "";
  if (value === "concluded") return "Concluded";
  if (value === "debating" || value === "synthesizing") return "Discussing";
  if (value === "investigating") return "Investigating";
  return prettify(value || "Working");
}

function firstSentence(text: string | null | undefined) {
  if (!text) return "";
  const match = text.trim().match(/^(.+?[.!?])(\s|$)/);
  return match?.[1] ?? text.trim();
}

function remainingText(text: string | null | undefined, first: string) {
  if (!text) return "";
  return text.trim().slice(first.length).trim();
}

function pickRecommendationTitle(dashboard: AgentDashboardResponse, findings: AgentFinding[]) {
  const supporting = findings.find((finding) => finding.supports_recommendation || finding.finding_type === "supporting");
  return supporting?.title || firstSentence(dashboard.recommendation) || firstSentence(dashboard.final_synthesis) || dashboard.objective;
}

function pickRecommendationBody(dashboard: AgentDashboardResponse, title: string) {
  const source = dashboard.recommendation || dashboard.final_synthesis || "";
  const rest = remainingText(source, title);
  return rest || source || "The team has completed its review of the current business data.";
}

function getRound(msg: AgentMessage): number {
  if (!Array.isArray(msg.references)) return 0;
  const first = msg.references[0] as Record<string, unknown> | undefined;
  return typeof first?.round === "number" ? first.round : 0;
}

function parseArray(value: unknown): unknown[] | null {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string") return null;
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function normalizeMessages(raw: AgentMessage[]) {
  return raw.map((message) => ({
    ...message,
    references: parseArray(message.references),
  }));
}

function normalizeFindings(raw: AgentFinding[]) {
  return raw.map((finding) => ({
    ...finding,
    evidence: parseArray(finding.evidence) as Array<Record<string, unknown>> | null,
  }));
}

function sortMessages(messages: AgentMessage[]) {
  return [...messages].sort((a, b) => {
    const aRound = getRound(a);
    const bRound = getRound(b);
    if (aRound !== bRound) return aRound - bRound;
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
  });
}

function checklistItems(dashboard: AgentDashboardResponse, findings: AgentFinding[]) {
  const fromFindings = findings
    .filter((finding) => finding.finding_type === "supporting" || finding.supports_recommendation)
    .map((finding) => finding.description || finding.title)
    .filter(Boolean)
    .slice(0, 4);

  if (fromFindings.length > 0) return fromFindings;

  const synthesis = dashboard.final_synthesis || dashboard.recommendation || "";
  return synthesis
    .split(/(?<=[.!?])\s+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 4);
}

export function AgentDebatePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlDebateId = searchParams.get("id");
  const [debates, setDebates] = useState<AgentDebateListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(urlDebateId);
  const [loadingList, setLoadingList] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [startingDebate, setStartingDebate] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const loadDebates = useCallback(async (preferredSelectedId?: string) => {
    try {
      setLoadingList(true);
      const data = await fetchDebateList();
      const list = data.debates ?? [];
      setDebates(list);
      setListError(null);
      if (preferredSelectedId) setSelectedId(preferredSelectedId);
      else if (!selectedId && list.length > 0) setSelectedId(list[0].id);
      return list;
    } finally {
      setLoadingList(false);
    }
  }, [selectedId]);

  useEffect(() => {
    let cancelled = false;

    async function loadInitialDebates() {
      try {
        const list = await loadDebates();
        if (cancelled) return;
        if (!selectedId && list.length > 0) setSelectedId(list[0].id);
      } catch (error) {
        if (!cancelled) setListError(error instanceof Error ? error.message : "Failed to load debates");
      } finally {
        if (!cancelled) setLoadingList(false);
      }
    }

    loadInitialDebates();
    return () => {
      cancelled = true;
    };
    // Initial load only; URL changes are handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (urlDebateId) setSelectedId(urlDebateId);
  }, [urlDebateId]);

  const selectDebate = useCallback((debateId: string) => {
    setSelectedId(debateId);
    setSearchParams({ id: debateId });
  }, [setSearchParams]);

  const handleStartDebate = useCallback(async () => {
    try {
      setStartingDebate(true);
      setStartError(null);
      const result = await startAgentDebate();
      selectDebate(result.id);
      await loadDebates(result.id);
    } catch (error) {
      setStartError(error instanceof Error ? error.message : "Could not start a new debate");
    } finally {
      setStartingDebate(false);
    }
  }, [loadDebates, selectDebate]);

  return (
    <section id="agent-debate" className="agent-debate-page" aria-labelledby="debate-heading">
      <div className="debate-shell">
        <aside className="debate-sidebar" aria-label="Past discussions">
          <div className="debate-sidebar__title">
            <span className="debate-sidebar__icon" aria-hidden="true">[]</span>
            <h1 id="debate-heading">Agent Debates</h1>
          </div>
          <h2>Past discussions</h2>
          <p>Review how your AI experts analyzed your business.</p>
          <button type="button" className="debate-new-button" onClick={handleStartDebate} disabled={startingDebate}>
            {startingDebate ? "Starting debate..." : "+ Start a new debate"}
          </button>

          {loadingList && <div className="debate-muted">Loading discussions...</div>}
          {listError && <div className="debate-error">Error: {listError}</div>}
          {startError && <div className="debate-error">Error: {startError}</div>}
          {!loadingList && !listError && debates.length === 0 && (
            <div className="debate-empty">No debates yet. Start a new debate to analyze the latest merchant data.</div>
          )}

          <ul className="debate-list">
            {debates.map((debate) => (
              <li key={debate.id}>
                <button
                  type="button"
                  className={`debate-list-item${selectedId === debate.id ? " is-selected" : ""}`}
                  onClick={() => selectDebate(debate.id)}
                >
                  <span className="debate-list-item__mark" aria-hidden="true">[]</span>
                  <span className="debate-list-item__body">
                    <strong>{debate.objective}</strong>
                    <span>
                      <i className={`status-dot status-dot--${debate.status}`} aria-hidden="true" />
                      {shortStatus(debate.status)}
                    </span>
                  </span>
                  <time dateTime={debate.updated_at}>{formatDate(debate.updated_at)}</time>
                </button>
              </li>
            ))}
          </ul>

          <p className="debate-sidebar__note">Each debate brings multiple experts together to discuss your business and find the best opportunities.</p>
        </aside>

        <main className="debate-main">
          {selectedId ? (
            <DebateDetail debateId={selectedId} />
          ) : (
            <div className="debate-placeholder">
              <h2>Select an investigation</h2>
              <p>Choose a past discussion to review the team conversation and final recommendation.</p>
            </div>
          )}
        </main>
      </div>
    </section>
  );
}

function DebateDetail({ debateId }: { debateId: string }) {
  const [dashboard, setDashboard] = useState<AgentDashboardResponse | null>(null);
  const [findings, setFindings] = useState<AgentFinding[]>([]);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [rounds, setRounds] = useState<AgentDebateRoundStatus | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [sendingQuestion, setSendingQuestion] = useState(false);
  const messageListRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottom = useRef(true);

  const load = useCallback(async () => {
    try {
      setError(null);
      const [dash, finds, msgs, rds] = await Promise.all([
        fetchAgentDashboard(debateId),
        fetchDebateFindings(debateId).catch(() => ({ findings: [] as AgentFinding[] })),
        fetchDebateMessages(debateId).catch(() => ({ messages: [] as AgentMessage[] })),
        fetchDebateRoundStatus(debateId).catch(() => null),
      ]);
      setDashboard(dash);
      setFindings(normalizeFindings(finds.findings ?? []));
      setMessages(normalizeMessages(msgs.messages ?? []));
      setRounds(rds);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load debate");
    } finally {
      setLoading(false);
    }
  }, [debateId]);

  useEffect(() => {
    setLoading(true);
    load();
  }, [load]);

  const orderedMessages = useMemo(() => sortMessages(messages), [messages]);
  const isActive = dashboard?.debate_status && !["concluded", "failed"].includes(dashboard.debate_status);

  useEffect(() => {
    if (!isActive) return;
    const interval = window.setInterval(() => {
      load();
    }, 2500);
    return () => window.clearInterval(interval);
  }, [isActive, load]);

  useEffect(() => {
    const list = messageListRef.current;
    if (!list || !shouldStickToBottom.current) return;
    list.scrollTo({ top: list.scrollHeight, behavior: orderedMessages.length > 1 ? "smooth" : "auto" });
  }, [orderedMessages.length, dashboard?.debate_status]);

  const handleMessageScroll = useCallback(() => {
    const list = messageListRef.current;
    if (!list) return;
    const distanceFromBottom = list.scrollHeight - list.scrollTop - list.clientHeight;
    shouldStickToBottom.current = distanceFromBottom < 120;
  }, []);

  const handleQuestion = useCallback(async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || sendingQuestion) return;
    try {
      setSendingQuestion(true);
      await askAgentDebate(debateId, trimmed);
      setQuestion("");
      await load();
    } catch (questionError) {
      setError(questionError instanceof Error ? questionError.message : "Could not send question");
    } finally {
      setSendingQuestion(false);
    }
  }, [debateId, load, question, sendingQuestion]);

  if (loading) {
    return <div className="debate-loading">Loading debate data...</div>;
  }

  if (error || !dashboard) {
    return <div className="debate-error debate-error--panel">{error ?? "No debate data available"}</div>;
  }

  const status = dashboard.debate_status;
  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;
  const completedDate = formatDate(lastMessage?.created_at || undefined) || "";
  const topTitle = pickRecommendationTitle(dashboard, findings);
  const topBody = pickRecommendationBody(dashboard, topTitle);
  const opportunities = findings.filter((finding) => finding.finding_type !== "uncertainty").slice(0, 5);
  const agreedItems = checklistItems(dashboard, findings);
  const hasInsufficientData =
    dashboard.rag_context &&
    dashboard.rag_context.status !== "ready" &&
    !dashboard.rag_context.inference_allowed;

  return (
    <div className="debate-workspace">
      <section className="debate-chat-card" aria-label="Agent discussion">
        <header className="debate-chat-header">
          <div>
            <Link to="/agents" className="debate-back-link">Back to Debates</Link>
            <h2>{dashboard.objective}</h2>
            <p>Our AI experts analyzed your business data and discussed the best opportunities for growth.</p>
          </div>
          <div className="debate-chat-status">
            <span className={`debate-status-pill debate-status-pill--${status}`}>
              <i aria-hidden="true" />
              {shortStatus(status)}
            </span>
            {completedDate && <span>{status === "concluded" ? "Completed" : "Updated"} on {completedDate}</span>}
          </div>
        </header>

        {hasInsufficientData && (
          <div className="debate-data-note">
            <strong>More data needed</strong>
            <span>The team reviewed what is available, but flagged that more history would improve confidence.</span>
          </div>
        )}

        <div
          className="debate-message-list"
          role="log"
          aria-label="Debate messages"
          ref={messageListRef}
          onScroll={handleMessageScroll}
        >
          {orderedMessages.length > 0 ? (
            orderedMessages.map((message) => (
              <article key={message.id} className={`debate-message debate-message--${agentTone(message.from_agent)}`}>
                <div className="debate-avatar" aria-hidden="true">{agentInitials(message.from_agent)}</div>
                <div className="debate-message__content">
                  <div className="debate-message__meta">
                    <strong>{agentLabel(message.from_agent)}</strong>
                    {formatTime(message.created_at) && <time dateTime={message.created_at}>{formatTime(message.created_at)}</time>}
                  </div>
                  <p>{message.content}</p>
                </div>
              </article>
            ))
          ) : (
            <DebateWorkingState dashboard={dashboard} />
          )}
        </div>

        <form className="debate-composer" onSubmit={handleQuestion}>
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask a question about this discussion..."
            aria-label="Ask a question about this discussion"
            disabled={sendingQuestion}
          />
          <button type="submit" aria-label="Send question" disabled={sendingQuestion || !question.trim()}>
            {sendingQuestion ? "Sending..." : "Send"}
          </button>
        </form>

        {showDetails && (
          <div className="debate-detail-drawer" aria-label="Full analysis details">
            <h3>Full analysis details</h3>
            <AnalysisDetails dashboard={dashboard} findings={findings} messages={orderedMessages} rounds={rounds} />
            {rounds && (
              <div className="debate-round-summary">
                <span>Current round: {rounds.current_round}</span>
                <span>Total findings: {rounds.findings_summary?.total ?? findings.length}</span>
              </div>
            )}
            <div className="debate-detail-grid">
              {findings.map((finding) => (
                <div key={finding.id} className="debate-detail-finding">
                  <strong>{agentLabel(finding.agent_specialty)}: {finding.title}</strong>
                  {finding.description && <span>{finding.description}</span>}
                  <EvidenceList evidence={finding.evidence} />
                </div>
              ))}
            </div>
          </div>
        )}
      </section>

      <aside className="debate-result-card" aria-label="Final recommendation">
        <div className="debate-result-heading">
          <span aria-hidden="true">*</span>
          <div>
            <h2>Final Recommendation</h2>
            <p>Based on the discussion, here's what our team recommends.</p>
          </div>
        </div>

        <div className="debate-featured-recommendation">
          <span aria-hidden="true">O</span>
          <div>
            <strong>{topTitle}</strong>
            <p>{topBody}</p>
          </div>
        </div>

        <section className="debate-result-section">
          <h3>Key Opportunities Discussed</h3>
          <div className="debate-opportunity-list">
            {opportunities.length > 0 ? (
              opportunities.map((finding, index) => (
                <article key={finding.id} className="debate-opportunity-card">
                  <span>{index + 1}</span>
                  <div>
                    <strong>{finding.title}</strong>
                    {finding.description && <p>{finding.description}</p>}
                  </div>
                </article>
              ))
            ) : (
              <p className="debate-muted">No opportunities were returned for this debate.</p>
            )}
          </div>
        </section>

        <section className="debate-result-section">
          <h3>What the Team Agreed On</h3>
          <ul className="debate-checklist">
            {agreedItems.length > 0 ? (
              agreedItems.map((item, index) => (
                <li key={`${item}-${index}`}>
                  <span aria-hidden="true" />
                  {item}
                </li>
              ))
            ) : (
              <li className="debate-muted">The team has not recorded shared conclusions yet.</li>
            )}
          </ul>
        </section>

        <div className="debate-result-actions">
          <button type="button" className="debate-primary-action" onClick={() => setShowDetails((value) => !value)}>
            View full analysis details
          </button>
          <button type="button" className="debate-secondary-action" onClick={() => window.location.assign("/debate")}>
            Run a new investigation
          </button>
        </div>
      </aside>
    </div>
  );
}

function DebateWorkingState({ dashboard }: { dashboard: AgentDashboardResponse }) {
  const activeAgents = dashboard.agents.filter((agent) => agent.status !== "completed");
  if (["concluded", "failed"].includes(dashboard.debate_status)) {
    return <div className="debate-empty debate-empty--chat">No messages were recorded for this debate.</div>;
  }

  const agents = activeAgents.length > 0 ? activeAgents : dashboard.agents;
  return (
    <div className="debate-agent-activity" aria-label="Agents are working">
      {agents.slice(0, 5).map((agent) => (
        <article key={agent.specialty} className={`debate-message debate-message--${agentTone(agent.specialty)}`}>
          <div className="debate-avatar" aria-hidden="true">{agentInitials(agent.specialty)}</div>
          <div className="debate-message__content">
            <div className="debate-message__meta">
              <strong>{agentLabel(agent.specialty)}</strong>
            </div>
            <p>{workingCopy(agent.specialty, dashboard.debate_status)}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

function workingCopy(agent: string, status: string) {
  const key = normalizeKey(agent);
  if (key === "manager") return status === "synthesizing" ? "Reviewing the team discussion and preparing the final recommendation..." : "Preparing the investigation and coordinating the specialists...";
  if (key === "marketing") return "Reviewing customer behavior, repeat purchases, and payment recovery opportunities...";
  if (key === "product") return "Analyzing orders, basket value, products, and cross-sell opportunities...";
  if (key === "designer") return "Reviewing the customer experience and checkout messaging opportunities...";
  if (key === "software") return "Checking implementation effort, automation paths, and technical risks...";
  return "Working on this debate...";
}

function AnalysisDetails({
  dashboard,
  findings,
  messages,
  rounds,
}: {
  dashboard: AgentDashboardResponse;
  findings: AgentFinding[];
  messages: AgentMessage[];
  rounds: AgentDebateRoundStatus | null;
}) {
  const facts = dashboard.rag_context?.verified_facts ?? [];
  const supporting = findings.filter((finding) => finding.finding_type === "supporting" || finding.supports_recommendation);
  const concerns = findings.filter((finding) => finding.finding_type === "opposing" || finding.finding_type === "uncertainty");

  return (
    <div className="debate-analysis-copy">
      <p>We looked at your recent Razorpay TEST payments, orders, customers, products, and the growth signals available for this merchant.</p>
      {facts.length > 0 && (
        <section>
          <h4>Evidence reviewed</h4>
          <ul>
            {facts.slice(0, 6).map((fact, index) => (
              <li key={`${fact.fact}-${index}`}>{plainMetric(fact.fact, fact.value)}</li>
            ))}
          </ul>
        </section>
      )}
      {supporting.length > 0 && (
        <section>
          <h4>What the specialists found</h4>
          <ul>
            {supporting.slice(0, 6).map((finding) => (
              <li key={finding.id}>{agentLabel(finding.agent_specialty)} found: {finding.description || finding.title}</li>
            ))}
          </ul>
        </section>
      )}
      {concerns.length > 0 && (
        <section>
          <h4>Concerns and open questions</h4>
          <ul>
            {concerns.slice(0, 5).map((finding) => (
              <li key={finding.id}>{finding.uncertainty_notes || finding.description || finding.title}</li>
            ))}
          </ul>
        </section>
      )}
      {messages.length > 0 && (
        <section>
          <h4>How the team discussed it</h4>
          <p>The team exchanged {messages.length} messages across {rounds?.current_round ?? "multiple"} debate stages before the Growth Manager prepared the recommendation.</p>
        </section>
      )}
      {dashboard.recommendation && (
        <section>
          <h4>What to do next</h4>
          <p>{dashboard.recommendation}</p>
        </section>
      )}
    </div>
  );
}

function plainMetric(fact: string, value: number) {
  const label = fact.replace(/[_-]+/g, " ").toLowerCase();
  if (label.includes("captured") && label.includes("transaction")) return `We reviewed ${value} successful payments.`;
  if (label.includes("successful") && label.includes("payment")) return `${value} payments were successful.`;
  if (label.includes("failed") && label.includes("payment")) return `${value} payments failed.`;
  if (label.includes("customer")) return `${value} customers were included in the analysis.`;
  if (label.includes("order")) return `${value} orders were reviewed.`;
  return `${prettify(fact)}: ${value}`;
}

function EvidenceList({ evidence }: { evidence: Array<Record<string, unknown>> | null }) {
  if (!Array.isArray(evidence) || evidence.length === 0) return null;
  return (
    <ul className="debate-evidence-list">
      {evidence.slice(0, 3).map((item, index) => (
        <li key={index}>{evidenceText(item)}</li>
      ))}
    </ul>
  );
}

function evidenceText(item: Record<string, unknown>) {
  const source = typeof item.source === "string" ? item.source : typeof item.type === "string" ? prettify(item.type) : "Business data";
  const metric = typeof item.metric === "string" ? prettify(item.metric) : "";
  const value = item.value ?? item.catalog_size ?? item.payment_volume ?? item.failed_payments;
  if (metric && value !== undefined) return `${source}: ${metric} was ${String(value)}.`;
  if (value !== undefined) return `${source}: ${String(value)}.`;
  return source;
}
