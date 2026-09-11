"""High-end Agentic RAG for the MarketingAGI.

NOT a "question -> vector search -> answer" pipeline. The agent:

  1. identifies the knowledge requirement
  2. classifies the information type
  3. selects a retrieval strategy (which source answers this best)
  4. retrieves from that source
  5. reranks and evaluates the evidence
  6. checks coverage — identifies knowledge gaps
  7. reformulates the query and retrieves again when coverage is short
  8. cross-checks across independent sources
  9. returns a source-aware evidence set with a sufficiency verdict

When the LLM is configured, strategy selection and sufficiency
judgement are model-driven (structured outputs). Without an LLM the
engine falls back to deterministic heuristics so tests run offline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.agents.marketing_agi.limits import LoopLimits
from backend.app.agents.marketing_agi.tools.registry import ToolContext

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured LLM outputs for the RAG loop
# ---------------------------------------------------------------------------


class RetrievalDecision(BaseModel):
    """The model picks the next retrieval action or declares done."""

    action: str = Field(description="'retrieve' | 'sufficient' | 'insufficient'")
    information_type: str = Field(
        default="unknown",
        description="business | customer | marketing | product | history | unknown",
    )
    tool: str | None = Field(default=None, description="tool to call when retrieving")
    query: str = Field(default="", description="reformulated retrieval query")
    reasoning: str = Field(default="")


class EvidenceSufficiency(BaseModel):
    """The model judges whether the evidence set covers the question."""

    sufficient: bool
    coverage: float = Field(ge=0.0, le=1.0, default=0.0)
    gaps: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="")


@dataclass
class RetrievalOutcome:
    query: str
    tool: str
    information_type: str
    item_count: int
    statements: list[str] = field(default_factory=list)
    latency_ms: int = 0


@dataclass
class AgenticRAGResult:
    question: str
    outcomes: list[RetrievalOutcome] = field(default_factory=list)
    evidence_statements: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    sufficient: bool = False
    rounds: int = 0
    strategy: str = "deterministic"  # or "llm"

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "rounds": self.rounds,
            "strategy": self.strategy,
            "sufficient": self.sufficient,
            "gaps": self.gaps,
            "retrievals": [
                {
                    "query": o.query,
                    "tool": o.tool,
                    "information_type": o.information_type,
                    "item_count": o.item_count,
                    "statements": o.statements[:6],
                    "latency_ms": o.latency_ms,
                }
                for o in self.outcomes
            ],
            "evidence_statements": self.evidence_statements[:24],
        }


# Information-type → best-tool routing table (deterministic fallback and
# LLM guidance). The LLM may propose other registered tools.
TYPE_TOOLS: dict[str, list[str]] = {
    "business": ["get_business_overview", "get_revenue_trend"],
    "customer": ["get_customer_segments", "find_customers", "get_customer_activity_trend"],
    "marketing": ["get_campaign_history", "get_action_history", "get_email_campaign_performance"],
    "product": ["get_product_performance", "get_product_affinities", "get_product_catalog"],
    "history": ["recall_memory", "get_campaign_history", "get_action_history"],
    "knowledge": ["search_knowledge_store"],
    "payments": ["get_failed_payment_analytics"],
    "integrations": ["get_email_campaigns", "get_google_ads_campaigns", "get_meta_campaigns"],
}


def classify_information_type(question: str) -> str:
    """Cheap deterministic classifier (also used as LLM fallback)."""
    q = question.lower()
    rules: list[tuple[str, tuple[str, ...]]] = [
        ("payments", ("payment", "failed", "recover", "retry")),
        ("history", ("tried", "before", "previous", "last time", "memory", "learned")),
        ("marketing", ("campaign", "email", "promotion", "message", "sent")),
        ("product", ("product", "catalog", "cross-sell", "upsell", "basket", "affinity")),
        ("customer", ("customer", "segment", "churn", "inactive", "vip", "audience", "retention")),
        ("business", ("revenue", "order", "aov", "overview", "trend", "growth", "decline")),
    ]
    for info_type, needles in rules:
        if any(n in q for n in needles):
            return info_type
    return "business"


def _rank_evidence(statements: list[str], question: str) -> list[str]:
    """Rerank: statements sharing more question terms rank higher."""
    terms = {t for t in question.lower().split() if len(t) > 3}
    if not terms:
        return statements

    def score(s: str) -> int:
        low = s.lower()
        return sum(1 for t in terms if t in low)

    return sorted(statements, key=score, reverse=True)


def _extract_statements(tool_result: dict[str, Any], tool: str) -> list[str]:
    """Flatten a tool result into factual statements (never invented)."""
    result = tool_result.get("result", tool_result)
    out: list[str] = []

    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)):
                    _walk(v, f"{path}.{k}" if path else k)
                elif v is not None and not isinstance(v, bool):
                    out.append(f"{path}.{k} = {v}" if path else f"{k} = {v}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj[:8]):
                _walk(item, f"{path}[{i}]")

    if isinstance(result, dict):
        _walk(result)
    return out[:40]


class AgenticRAG:
    """Retrieve → evaluate → gap-check → reformulate → cross-check."""

    def __init__(
        self,
        ctx: ToolContext,
        registry,
        llm: BaseLLMProvider | None = None,
        limits: LoopLimits | None = None,
    ) -> None:
        self._ctx = ctx
        self._registry = registry
        self._llm = llm
        self._limits = limits or LoopLimits()
        self._tools = {spec["name"] for spec in registry.catalog()}

    # ── public entry ─────────────────────────────────────────────────────

    def research(self, question: str) -> AgenticRAGResult:
        result = AgenticRAGResult(question=question)
        if self._llm is not None:
            result.strategy = "llm"
            self._research_llm(question, result)
        else:
            self._research_deterministic(question, result)
        return result

    # ── LLM-driven loop ─────────────────────────────────────────────────

    def _research_llm(self, question: str, result: AgenticRAGResult) -> None:
        catalog = self._registry.catalog()
        system = (
            "You are the retrieval strategist of an autonomous marketing agent. "
            "Classify the information need, choose the single best registered tool, "
            "and reformulate the query. Use ONLY tools from the catalog. "
            "Return JSON per the schema."
        )
        user = (
            f"Question: {question}\n\n"
            f"Evidence gathered so far: {result.evidence_statements[:20] or 'none'}\n"
            f"Tool catalog: {catalog}"
        )
        for _ in range(self._limits.max_retrieval_rounds):
            result.rounds += 1
            try:
                decision = self._llm.generate_structured(
                    system, user, RetrievalDecision, temperature=0.0, max_tokens=300
                )
            except Exception as exc:  # model failure -> deterministic fallback
                log.warning("AgenticRAG LLM decision failed: %s", exc)
                self._research_deterministic(question, result)
                return

            if decision.action != "retrieve" or not decision.tool:
                if decision.action == "insufficient":
                    result.sufficient = False
                    result.gaps = [g for g in decision.query.split(";") if g]
                break
            if decision.tool not in self._tools:
                continue  # model hallucinated a tool: skip, never crash

            outcome = self._retrieve(decision.tool, decision.query or question, decision.information_type)
            if outcome is not None:
                result.outcomes.append(outcome)
                result.evidence_statements.extend(
                    _rank_evidence(outcome.statements, question)
                )

            try:
                sufficiency = self._llm.generate_structured(
                    "You judge whether gathered evidence covers the question. Be strict: "
                    "missing data is a gap. Return JSON per the schema.",
                    f"Question: {question}\nEvidence: {result.evidence_statements[:24]}",
                    EvidenceSufficiency,
                    temperature=0.0,
                    max_tokens=300,
                )
                result.gaps = sufficiency.gaps or []
                if sufficiency.sufficient:
                    result.sufficient = True
                    return
            except Exception as exc:
                log.warning("AgenticRAG sufficiency check failed: %s", exc)
                break

            user = (
                f"Question: {question}\n\n"
                f"Known gaps: {result.gaps}\n"
                f"Evidence: {result.evidence_statements[:20]}\n"
                f"Tool catalog: {catalog}"
            )

    # ── deterministic loop (tests + no-LLM environments) ─────────────────

    def _research_deterministic(self, question: str, result: AgenticRAGResult) -> None:
        info_type = classify_information_type(question)
        tools = TYPE_TOOLS.get(info_type, ["get_business_overview"])
        # cross-check: always add a second, independent source
        if len(tools) < 2:
            tools = tools + ["recall_memory"]

        for tool in tools[: self._limits.max_retrieval_rounds]:
            result.rounds += 1
            outcome = self._retrieve(tool, question, info_type)
            if outcome is None:
                continue
            result.outcomes.append(outcome)
            result.evidence_statements.extend(
                _rank_evidence(outcome.statements, question)
            )

        # coverage: enough distinct, non-trivial statements? Statements whose
        # values are zero/empty/none — or that merely echo tool parameters /
        # config — carry no evidence weight. An empty merchant must never be
        # judged "sufficient".
        config_echoes = (
            "criteria.", "window_days", "limit =", "query =", "information_type",
            "inactivity_signal", "data_completeness", "retrieval_method",
        )

        def _substantial(s: str) -> bool:
            if len(s) <= 12:
                return False
            low = s.lower()
            for prefix in config_echoes:
                if low.startswith(prefix):
                    return False
            for token in ("= 0", "= 0.0", "= none", "= null", "= []", "= {}", "= 'none'", "= 'weak'", "no_data"):
                if low.endswith(token):
                    return False
            return True

        substantial = [s for s in result.evidence_statements if _substantial(s)]
        zero_like = [s for s in result.evidence_statements if not _substantial(s)]
        if len(substantial) >= 3:
            result.sufficient = True
        else:
            result.gaps = [
                f"insufficient {info_type} data for: {question}",
                f"{len(zero_like)} of {len(result.evidence_statements)} retrieved facts were empty/zero/config",
            ]

    # ── one retrieval ───────────────────────────────────────────────────

    def _retrieve(self, tool: str, query: str, info_type: str) -> RetrievalOutcome | None:
        params: dict[str, Any] = {}
        if tool in {"search_knowledge_store"}:
            params = {"query": query}
        elif tool == "recall_memory":
            params = {"query": query}
        elif tool == "find_customers":
            params = {"min_orders": 1}
        try:
            call = self._registry.call(self._ctx, tool, params)
        except Exception as exc:
            log.warning("AgenticRAG tool %s failed: %s", tool, exc)
            return None
        statements = _extract_statements(call, tool)
        return RetrievalOutcome(
            query=query,
            tool=tool,
            information_type=info_type,
            item_count=len(statements),
            statements=statements,
            latency_ms=call.get("latency_ms", 0),
        )
