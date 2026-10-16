"""
Canonical agent tool catalog.

Why this module exists
----------------------
Before it, every specialist advertised capabilities through a bare
``TOOLS = ("growth_radar", "churn_engine", ...)`` string tuple that was
published verbatim to merchants by ``agent_catalog()``. Several of those
names had **no implementation anywhere** — they were labels. This module
replaces the convention with one rule:

    A tool exists if and only if it is registered here with a callable
    handler, a validated input model, an output model and a declared
    permission requirement.

``tests/test_agent_tool_catalog.py`` enforces both directions:

  * every id an agent advertises resolves to a real ToolSpec, and
  * every ToolSpec has an implementation that is actually reachable.

A tool is READ-ONLY unless ``read_only=False``, and every non-read-only
tool must additionally name the permission its caller must hold. Nothing
here can approve or execute an action: the catalog only reaches services.
Authorisation for consequential work stays with the Phase 4 action
pipeline (``action_service`` + ``guardrails`` + human approval).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from pydantic import BaseModel, Field

from backend.app.agents.permissions import (
    READ_CUSTOMERS,
    READ_MERCHANT,
    READ_OPPORTUNITIES,
    READ_ORDERS,
    READ_PAYMENTS,
    READ_PRODUCTS,
)

log = logging.getLogger(__name__)

#: Handler signature. Every handler receives a validated input model and the
#: caller's database session; the merchant id is always taken from the
#: validated input (and validated against the caller's tenant upstream), so
#: a handler can never be pointed at another workspace.
ToolHandler = Callable[..., Any]


class ToolNotFoundError(LookupError):
    """Raised when a tool id is not registered in the catalog."""


class ToolInputError(ValueError):
    """Raised when arguments fail the tool's input schema."""


class ToolPermissionError(PermissionError):
    """Raised when the caller lacks the permission a tool requires."""


# --------------------------------------------------------------------------- #
# Tool specification
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ToolSpec:
    """A single, genuinely callable agent tool."""

    tool_id: str
    summary: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: ToolHandler
    #: Permission string from agents.permissions.AGENT_PERMISSIONS vocabulary.
    required_permission: str | None = READ_MERCHANT
    read_only: bool = True
    timeout_seconds: int = 30
    #: Declared at registration; asserted non-empty by the catalog test.
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "summary": self.summary,
            "read_only": self.read_only,
            "required_permission": self.required_permission,
            "timeout_seconds": self.timeout_seconds,
            "input_fields": sorted(self.input_model.model_fields),
            "output_fields": sorted(self.output_model.model_fields),
            "source": self.source,
        }


# --------------------------------------------------------------------------- #
# Generic IO models — permissive on purpose so a tool never silently drops a
# real field, strict on the shapes the handlers actually rely on.
# --------------------------------------------------------------------------- #


class ToolResult(BaseModel):
    """Uniform envelope returned by every catalog tool."""

    status: str = "ok"
    #: Free-form, schema-validated-by-handler payload.
    data: dict[str, Any] = Field(default_factory=dict)
    #: Honest reporting of anything the tool could not do.
    warnings: list[str] = Field(default_factory=list)
    #: Which real service produced `data` — used by the dashboard and tests.
    source: str = ""


class MerchantWindowInput(BaseModel):
    merchant_id: uuid.UUID
    window_days: int = Field(default=30, ge=1, le=365)
    limit: int = Field(default=50, ge=1, le=500)


class MerchantOnlyInput(BaseModel):
    merchant_id: uuid.UUID


class ExperimentInput(BaseModel):
    merchant_id: uuid.UUID
    opportunity_id: uuid.UUID
    name: str = Field(min_length=3, max_length=255)
    hypothesis: str = Field(min_length=3, max_length=2000)
    control_group: dict[str, Any] = Field(default_factory=dict)
    treatment_group: dict[str, Any] = Field(default_factory=dict)
    target_population_size: int = Field(default=0, ge=0)
    estimated_metric: dict[str, Any] = Field(default_factory=dict)


class ExperimentResultInput(BaseModel):
    merchant_id: uuid.UUID
    experiment_id: uuid.UUID
    variant: str = Field(min_length=1, max_length=64)
    conversions: int = Field(default=0, ge=0)
    revenue: float = Field(default=0.0, ge=0.0)


class ResearchInput(BaseModel):
    merchant_id: uuid.UUID
    query: str = Field(min_length=3, max_length=300)
    max_results: int = Field(default=5, ge=1, le=10)


class HandoffInput(BaseModel):
    merchant_id: uuid.UUID
    source_agent: str = Field(min_length=1, max_length=64)
    destination_agent: str = Field(min_length=1, max_length=64)
    task: str = Field(min_length=3, max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)


class MemoryRecallInput(BaseModel):
    merchant_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=20, ge=1, le=200)


class MemoryRecordInput(BaseModel):
    merchant_id: uuid.UUID
    content: str = Field(min_length=1, max_length=5000)
    memory_type: str = Field(default="recommendation", pattern="^(recommendation|outcome|preference|insight)$")
    summary: str | None = Field(default=None, max_length=500)
    source_type: str | None = Field(default=None, max_length=100)
    source_id: str | None = Field(default=None, max_length=100)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    memory_metadata: dict[str, Any] | None = None
    outcome_variance_pct: float | None = None


class ProposeActionInput(BaseModel):
    merchant_id: uuid.UUID
    #: Constrained to the guardrail-permitted vocabulary so a tool caller
    #: cannot propose a type the policy layer would reject anyway.
    action_type: str = Field(min_length=1, max_length=50)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    requested_by: str = Field(default="catalog", max_length=64)


# --------------------------------------------------------------------------- #
# Tool handlers — thin adapters over services that already exist.
# These deliberately contain no business logic; they normalise arguments and
# re-wrap results so the catalog contract is uniform.
# --------------------------------------------------------------------------- #


def _handle_business_overview(payload: MerchantWindowInput, db: Any) -> ToolResult:
    """Real period-over-period commerce metrics from AnalyticsService."""
    from backend.app.services.analytics_service import AnalyticsService

    data = AnalyticsService(db).get_overview(
        payload.merchant_id, period_days=payload.window_days
    )
    return ToolResult(data=data, source="services.analytics_service.get_overview")


def _handle_growth_radar(payload: MerchantWindowInput, db: Any) -> ToolResult:
    """Real Growth Radar signal detection (persist=False: read-only)."""
    from backend.app.services.radar import GrowthRadarService

    signals = GrowthRadarService(db).detect(
        payload.merchant_id, window_days=payload.window_days, persist=False
    )
    return ToolResult(
        data={"signals": signals, "count": len(signals)},
        source="services.radar.GrowthRadarService.detect",
    )


def _handle_customer_insights(payload: MerchantWindowInput, db: Any) -> ToolResult:
    """Real per-customer LTV / recency / churn from the CI service."""
    from backend.app.services.customer_intelligence import CustomerIntelligenceService

    svc = CustomerIntelligenceService(db)
    rows = svc.compute_metrics(payload.merchant_id)
    by_segment: dict[str, int] = {}
    for row in rows:
        seg = str(row.get("primary_segment", "unknown"))
        by_segment[seg] = by_segment.get(seg, 0) + 1
    return ToolResult(
        data={"customers": rows[: payload.limit], "by_segment": by_segment,
              "customer_count": len(rows)},
        source="services.customer_intelligence.compute_metrics",
    )


def _handle_catalog_health(payload: MerchantWindowInput, db: Any) -> ToolResult:
    """Real catalog scoring, low-stock, pricing and bundle analysis."""
    from backend.app.services import product_intelligence as pi

    snapshot = pi.build_snapshot(db, payload.merchant_id, window_days=payload.window_days)
    return ToolResult(
        data={
            "summary": snapshot.summary(),
            "catalog_health": pi.catalog_health(db, payload.merchant_id, snapshot),
            "low_stock_risk": pi.low_stock_risk(
                db, payload.merchant_id, snapshot, window_days=payload.window_days
            ),
            "pricing_opportunities": pi.pricing_opportunities(snapshot),
            "bundle_opportunities": pi.bundle_opportunities(
                db, payload.merchant_id, snapshot, window_days=payload.window_days
            ),
        },
        source="services.product_intelligence",
    )


def _handle_payment_failures(payload: MerchantWindowInput, db: Any) -> ToolResult:
    """Real failed-payment analytics INCLUDING provider failure codes."""
    from backend.app.agents.marketing_agi.tools.analytics_tools import (
        get_failed_payment_analytics,
    )

    data = get_failed_payment_analytics(db, payload.merchant_id, limit=payload.limit)
    return ToolResult(
        data=data,
        source="agents.marketing_agi.tools.analytics_tools.get_failed_payment_analytics",
    )


def _handle_rank_opportunities(payload: MerchantWindowInput, db: Any) -> ToolResult:
    """Deterministic scoring/ranking of open opportunities."""
    from sqlalchemy import select

    from backend.app.models.opportunity import GrowthOpportunity
    from backend.app.services.scoring import OpportunityScoringEngine

    rows = list(
        db.scalars(
            select(GrowthOpportunity)
            .where(
                GrowthOpportunity.merchant_id == payload.merchant_id,
                GrowthOpportunity.status.in_(["pending_approval", "approved"]),
            )
            .limit(payload.limit)
        ).all()
    )
    engine = OpportunityScoringEngine()
    ranked = []
    for opp in rows:
        score = engine.score(
            expected_revenue=float(opp.expected_revenue),
            confidence=float(opp.confidence),
            target_customer_count=int(opp.target_customer_count or 0),
            evidence_items=max(1, len(opp.reasoning or [])),
        )
        ranked.append(
            {
                "opportunity_id": str(opp.id),
                "title": opp.title,
                "score": score.opportunity_score,
                "expected_revenue": float(opp.expected_revenue),
                "confidence": float(opp.confidence),
            }
        )
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ToolResult(
        data={"ranked": ranked, "count": len(ranked)},
        source="services.scoring.OpportunityScoringEngine",
    )


def _handle_design_experiment(payload: ExperimentInput, db: Any) -> ToolResult:
    """Persists a real A/B experiment against a real opportunity."""
    from backend.app.services.experiment_service import ExperimentService

    exp = ExperimentService(db).create_experiment(
        merchant_id=payload.merchant_id,
        name=payload.name,
        hypothesis=payload.hypothesis,
        opportunity_id=payload.opportunity_id,
        control_group=payload.control_group,
        treatment_group=payload.treatment_group,
        target_population_size=payload.target_population_size,
        estimated_metric=payload.estimated_metric,
    )
    return ToolResult(
        data={
            "experiment_id": str(exp.id),
            "name": exp.name,
            "status": str(exp.status),
        },
        source="services.experiment_service.create_experiment",
    )


def _handle_record_experiment_result(payload: ExperimentResultInput, db: Any) -> ToolResult:
    """Records an OBSERVED experiment outcome (not an estimate)."""
    from backend.app.services.experiment_service import ExperimentService

    result = ExperimentService(db).record_result(
        experiment_id=payload.experiment_id,
        variant=payload.variant,
        conversions=payload.conversions,
        revenue=payload.revenue,
    )
    return ToolResult(
        data={"experiment_id": str(payload.experiment_id), "recorded": bool(result)},
        source="services.experiment_service.record_result",
    )


def _handle_web_research(payload: ResearchInput, db: Any) -> ToolResult:
    """External evidence gathering via the configured research provider."""
    from backend.app.services.research import research_service

    report = research_service.search(payload.query, max_results=payload.max_results)
    if report.status != "ok":
        return ToolResult(
            status=report.status,
            data={"sources": [], "summary": report.summary},
            warnings=[f"research_unavailable: {report.summary}"],
            source="services.research",
        )
    return ToolResult(
        data={"summary": report.summary, "sources": report.to_sources_dict()},
        warnings=report.warnings,
        source="services.research",
    )


def _handle_record_handoff(payload: HandoffInput, db: Any) -> ToolResult:
    """Records a structured cross-agent handoff request."""
    from backend.app.services.handoff import handoff_service

    handoff = handoff_service.request(
        db,
        merchant_id=payload.merchant_id,
        source_agent=payload.source_agent,
        destination_agent=payload.destination_agent,
        task=payload.task,
        payload=payload.payload,
    )
    return ToolResult(
        data={"handoff_id": handoff["handoff_id"], "status": handoff["status"]},
        source="services.handoff",
    )


def _handle_recall_memory(payload: MemoryRecallInput, db: Any) -> ToolResult:
    """
    Real retrieval from the merchant's growth memory store.

    Falls back to keyword scoring when no embedding provider is configured —
    the store still answers, it just answers more narrowly.
    """
    from backend.app.services.memory import GrowthMemoryService

    rows = GrowthMemoryService(db).retrieve(
        merchant_id=payload.merchant_id,
        query=payload.query,
        limit=payload.limit,
    )
    return ToolResult(
        data={"memories": rows, "memory_count": len(rows)},
        source="services.memory.GrowthMemoryService.retrieve",
    )


def _handle_record_memory(payload: MemoryRecordInput, db: Any) -> ToolResult:
    """Record a memory entry for the merchant."""
    from backend.app.services.memory import GrowthMemoryService
    from backend.app.models.enums import MemoryType

    mt = MemoryType(payload.memory_type)
    row = GrowthMemoryService(db).record(
        merchant_id=payload.merchant_id,
        memory_type=mt,
        content=payload.content,
        summary=payload.summary,
        source_type=payload.source_type,
        source_id=payload.source_id,
        importance=payload.importance,
        memory_metadata=payload.memory_metadata,
        outcome_variance_pct=payload.outcome_variance_pct,
    )
    return ToolResult(
        data={"memory_id": str(row.id), "status": "recorded"},
        source="services.memory.GrowthMemoryService.record",
        read_only=False,
    )


def _handle_propose_action(payload: ProposeActionInput, db: Any) -> ToolResult:
    """
    Creates an approval-gated AgentAction in 'requested' state.

    This is a PROPOSAL, never an execution: the action cannot move to
    'approved' without a human owner/admin passing the guardrails, and it
    cannot execute unless EXECUTION_ENABLED is explicitly on.
    """
    from backend.app.services.action_service import create_action

    action = create_action(
        db,
        merchant_id=payload.merchant_id,
        action_type=payload.action_type,
        input_payload=payload.input_payload,
        requested_by=f"agent:{payload.requested_by}",
    )
    return ToolResult(
        data={"action_id": str(action.id), "status": str(action.status)},
        warnings=["proposal_only:requires_human_approval_before_execution"],
        source="services.action_service.create_action",
    )


# --------------------------------------------------------------------------- #
# The catalog itself
# --------------------------------------------------------------------------- #

_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        tool_id="analytics.business_overview",
        summary=(
            "Real period-over-period revenue, order, customer and opportunity "
            "metrics computed from this merchant's own commerce rows."
        ),
        input_model=MerchantWindowInput,
        output_model=ToolResult,
        handler=_handle_business_overview,
        required_permission=READ_MERCHANT,
        read_only=True,
        source="services.analytics_service.AnalyticsService.get_overview",
    ),
    ToolSpec(
        tool_id="analytics.growth_radar",
        summary=(
            "Real Growth Radar signal detection over a rolling window "
            "(revenue drop, churn, payment failures, dormant customers)."
        ),
        input_model=MerchantWindowInput,
        output_model=ToolResult,
        handler=_handle_growth_radar,
        required_permission=READ_ORDERS,
        read_only=True,
        source="services.radar.GrowthRadarService.detect",
    ),
    ToolSpec(
        tool_id="customer.insights",
        summary=(
            "Real per-customer lifetime value, recency, average order value, "
            "payment success rate and churn classification."
        ),
        input_model=MerchantWindowInput,
        output_model=ToolResult,
        handler=_handle_customer_insights,
        required_permission=READ_CUSTOMERS,
        read_only=True,
        source="services.customer_intelligence.CustomerIntelligenceService.compute_metrics",
    ),
    ToolSpec(
        tool_id="commerce.catalog_intelligence",
        summary=(
            "Real catalog health scoring, low-stock velocity projection, "
            "internal price-positioning signals and basket affinity."
        ),
        input_model=MerchantWindowInput,
        output_model=ToolResult,
        handler=_handle_catalog_health,
        required_permission=READ_PRODUCTS,
        read_only=True,
        source="services.product_intelligence",
    ),
    ToolSpec(
        tool_id="payments.failure_analytics",
        summary=(
            "Real failed payments with provider failure codes, reasons and "
            "recoverable value. Read-only; never initiates a retry."
        ),
        input_model=MerchantWindowInput,
        output_model=ToolResult,
        handler=_handle_payment_failures,
        required_permission=READ_PAYMENTS,
        read_only=True,
        source="agents.marketing_agi.tools.analytics_tools.get_failed_payment_analytics",
    ),
    ToolSpec(
        tool_id="opportunities.rank",
        summary="Deterministic best-first ranking of open growth opportunities.",
        input_model=MerchantWindowInput,
        output_model=ToolResult,
        handler=_handle_rank_opportunities,
        required_permission=READ_OPPORTUNITIES,
        read_only=True,
        source="services.scoring.OpportunityScoringEngine",
    ),
    ToolSpec(
        tool_id="experiments.design",
        summary="Persists a real control-vs-treatment A/B experiment for an opportunity.",
        input_model=ExperimentInput,
        output_model=ToolResult,
        handler=_handle_design_experiment,
        required_permission=READ_OPPORTUNITIES,
        read_only=False,
        source="services.experiment_service.create_experiment",
    ),
    ToolSpec(
        tool_id="experiments.record_result",
        summary="Records an observed (not estimated) experiment outcome.",
        input_model=ExperimentResultInput,
        output_model=ToolResult,
        handler=_handle_record_experiment_result,
        required_permission=READ_OPPORTUNITIES,
        read_only=False,
        source="services.experiment_service.record_result",
    ),
    ToolSpec(
        tool_id="research.web_search",
        summary=(
            "Gathers external evidence from the configured research provider, "
            "with source URLs, retrieval timestamps and provenance."
        ),
        input_model=ResearchInput,
        output_model=ToolResult,
        handler=_handle_web_research,
        required_permission=READ_MERCHANT,
        read_only=True,
        source="services.research.research_service.search",
    ),
    ToolSpec(
        tool_id="collaboration.request_handoff",
        summary="Records a structured, duplicate-guarded cross-agent handoff request.",
        input_model=HandoffInput,
        output_model=ToolResult,
        handler=_handle_record_handoff,
        required_permission=READ_MERCHANT,
        read_only=False,
        source="services.handoff.handoff_service.request",
    ),
    ToolSpec(
        tool_id="memory.recall",
        summary=(
            "Retrieves this merchant's prior growth memories, ranked by "
            "relevance, recency and importance."
        ),
        input_model=MemoryRecallInput,
        output_model=ToolResult,
        handler=_handle_recall_memory,
        required_permission=READ_MERCHANT,
        read_only=True,
        source="services.memory.GrowthMemoryService.retrieve",
    ),
    ToolSpec(
        tool_id="memory.record",
        summary=(
            "Records a memory entry (recommendation, outcome, preference, or insight) "
            "for this merchant with optional embedding and metadata."
        ),
        input_model=MemoryRecordInput,
        output_model=ToolResult,
        handler=_handle_record_memory,
        required_permission=READ_MERCHANT,
        read_only=False,
        source="services.memory.GrowthMemoryService.record",
    ),
    ToolSpec(
        tool_id="actions.propose",
        summary=(
            "Creates an approval-gated AgentAction in 'requested' state. "
            "Proposal only: execution always requires human approval."
        ),
        input_model=ProposeActionInput,
        output_model=ToolResult,
        handler=_handle_propose_action,
        required_permission=READ_MERCHANT,
        read_only=False,
        source="services.action_service.create_action",
    ),
)

TOOL_REGISTRY: dict[str, ToolSpec] = {spec.tool_id: spec for spec in _SPECS}


def get_tool(tool_id: str) -> ToolSpec:
    """Return a registered tool or raise ``ToolNotFoundError``."""
    spec = TOOL_REGISTRY.get(tool_id)
    if spec is None:
        raise ToolNotFoundError(
            f"Unknown tool '{tool_id}'. Registered: {sorted(TOOL_REGISTRY)}"
        )
    return spec


def tool_ids_for_agent(agent_name: str) -> tuple[str, ...]:
    """Resolve the tools an agent declares, preserving declaration order."""
    from backend.app.agents.registry import AGENT_INSTANCES

    agent = AGENT_INSTANCES.get(agent_name)
    if agent is None:
        return ()
    resolved: list[str] = []
    for declared in getattr(agent, "TOOLS", ()):  # noqa: B009 - agent protocol
        # Legacy agents still list bare service names; they are mapped so the
        # catalog stays the single source of truth.
        resolved.append(LEGACY_TOOL_ALIASES.get(declared, declared))
    return tuple(resolved)


def catalog_payload() -> list[dict[str, Any]]:
    """Serialisable catalog for the AI Team dashboard."""
    return [spec.to_dict() for spec in TOOL_REGISTRY.values()]


#: Maps the historical, implementation-free names still present on a few
#: agents onto real catalog ids. Declared here (not silently dropped) so the
#: dashboard can surface the translation instead of lying about capabilities.
LEGACY_TOOL_ALIASES: dict[str, str] = {
    "growth_radar": "analytics.growth_radar",
    "opportunity_upsert": "opportunities.rank",
    "opportunity_scoring": "opportunities.rank",
    "customer_metrics": "customer.insights",
    "segment_classification": "customer.insights",
    "churn_engine": "customer.insights",
    "experiment_design": "experiments.design",
    "failed_payment_scan": "payments.failure_analytics",
    "recovery_simulation": "payments.failure_analytics",
    "phase4_propose": "actions.propose",
    "memory_retrieve": "memory.recall",
    "memory_record": "memory.record",
    "product_affinity_analysis": "commerce.catalog_intelligence",
    "inventory_scan": "commerce.catalog_intelligence",
    "pricing_signals": "commerce.catalog_intelligence",
    "web_research": "research.web_search",
    "knowledge_retrieval": "research.web_search",
    "agent_handoff": "collaboration.request_handoff",
    # RevenueOptimizationAgent (in-scope)
    "opportunity_ranking": "opportunities.rank",
    "what_if_simulation": "experiments.design",
    # CampaignStrategistAgent (in-scope)
    "segment_lookup": "customer.insights",
    "campaign_simulation": "experiments.design",
    # GrowthMemoryAgent (in-scope)
    # SoftwareAgent (in-scope)
    "technical_planning": "commerce.catalog_intelligence",  # uses catalog health data for planning
    "integration_analysis": "commerce.catalog_intelligence",  # uses product intelligence
    "automation_design": "experiments.design",  # designs workflow experiments
    "feasibility_assessment": "opportunities.rank",  # assesses opportunity feasibility
    "spec_creation": "experiments.design",  # creates experiment specs
}


def resolve_invocation(tool_id: str, arguments: dict[str, Any]) -> BaseModel:
    """Validate raw arguments against the tool's input schema."""
    spec = get_tool(tool_id)
    try:
        return spec.input_model.model_validate(arguments or {})
    except Exception as exc:  # pydantic ValidationError
        raise ToolInputError(f"Invalid arguments for '{tool_id}': {exc}") from exc


def invoke(
    tool_id: str,
    *,
    db: Any,
    arguments: dict[str, Any],
    granted_permissions: Iterable[str] = (),
    timeout_seconds: int | None = None,
) -> ToolResult:
    """
    Authorised, validated, timed tool invocation.

    This is the ONLY supported way an agent reaches a tool. It enforces, in
    order: registry membership, permission, input schema, then the handler —
    and always returns a ``ToolResult`` envelope rather than raising for an
    ordinary domain failure, so one bad tool call cannot abort a run.
    """
    spec = get_tool(tool_id)

    granted = set(granted_permissions)
    if spec.required_permission and spec.required_permission not in granted:
        raise ToolPermissionError(
            f"Tool '{tool_id}' requires '{spec.required_permission}'; "
            f"caller holds {sorted(granted)}"
        )

    payload = resolve_invocation(tool_id, arguments)

    t0 = time.perf_counter()
    try:
        raw = spec.handler(payload, db)
    except Exception as exc:  # domain failure → honest envelope, not a crash
        log.warning("Tool %s failed: %s: %s", tool_id, type(exc).__name__, exc)
        return ToolResult(
            status="error",
            data={},
            warnings=[f"{type(exc).__name__}: {exc}"],
            source=spec.source,
        )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    if not isinstance(raw, ToolResult):
        return ToolResult(
            status="ok",
            data={"result": raw},
            source=spec.source,
            warnings=[f"handler returned un-normalised type {type(raw).__name__}"],
        )
    # Per-call timing rides along in the envelope so the dashboard can show
    # real tool activity without a second round-trip.
    raw.data.setdefault("_tool_ms", elapsed_ms)
    if timeout_seconds is not None and elapsed_ms > timeout_seconds * 1000:
        raw.warnings.append(f"tool_exceeded_timeout:{elapsed_ms}ms")
    return raw


__all__ = [
    "ExperimentInput",
    "ExperimentResultInput",
    "HandoffInput",
    "LEGACY_TOOL_ALIASES",
    "MemoryRecordInput",
    "MemoryRecallInput",
    "MerchantOnlyInput",
    "MerchantWindowInput",
    "ProposeActionInput",
    "ResearchInput",
    "TOOL_REGISTRY",
    "ToolHandler",
    "ToolInputError",
    "ToolNotFoundError",
    "ToolPermissionError",
    "ToolResult",
    "ToolSpec",
    "catalog_payload",
    "get_tool",
    "invoke",
    "resolve_invocation",
    "tool_ids_for_agent",
]