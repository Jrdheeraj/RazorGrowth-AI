"""ProductAGI — the autonomous product-growth employee.

The cycle, exactly as specified:

    OBSERVE            -> UNDERSTAND_CATALOG   read the real catalog + inventory
                       -> ANALYZE_PERFORMANCE  read real demand per product
                       -> FIND_OPPORTUNITIES   deterministic diagnosis
    RESEARCH           -> RESEARCH_ANALYZE     agentic RAG over this workspace
    RECOMMEND          -> PREPARE_RECOMMENDATION  Groq reasons over the above
                       -> SAFETY_CHECK          recommendation-level safety gate
    HUMAN APPROVAL     -> WAITING_APPROVAL      existing agent_actions pipeline
    EXECUTE            -> EXECUTE_MEASURE       only ever a human-approved action
    LEARN              -> LEARN                 measured outcomes, or an honest gap

What this agent is NOT
----------------------
* It is not an LLM wrapper. Every number it reasons over was computed by a
  deterministic MCP tool first; the model is used to interpret, prioritise
  and word.
* It is not a second MCP layer. It uses the shared ``MCPClient``, registry,
  policy, tenant context, cache, retries and observability. Its only new
  surface is the ``product_intelligence`` capability domain.
* It is not an approval system. It CREATES ``agent_actions`` in the
  ``requested`` state through the existing service and then stops. Humans
  approve at ``POST /api/actions/{id}/approve``.
* It has no write tool. ``stage_catalog`` never offers one, the granted
  domains contain no write, and every tool the agent invokes is read-only.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.agents.marketing_agi.limits import LoopLimits
from backend.app.agents.marketing_agi.tools.registry import ToolContext
from backend.app.agents.product_agi import prompts, tools as agent_tools
from backend.app.agents.product_agi.events import EventRecorder
from backend.app.agents.product_agi.rag import ProductResearch
from backend.app.agents.product_agi.schemas import AnalysisResult
from backend.app.agents.product_agi.state import (
    IMPACT_PENDING_REASON,
    IMPACT_UNAVAILABLE_REASON,
    ProductAgentState,
    RunStatus,
    Stage,
)
from backend.app.integrations.mcp import bridge as mcp_bridge
from backend.app.integrations.mcp.client import MCPToolCallRecord
from backend.app.integrations.mcp.observability import MCPLedger
from backend.app.models.agent_action import AgentAction  # noqa: F401
from backend.app.models.enums import AgentActionType
from backend.app.models.product import Product
from backend.app.models.product_agi import (
    ProductAgentFinding,
    ProductAgentRecommendation,
    ProductAgentRun,
)

log = logging.getLogger(__name__)

#: The agent's actor label on the actions it creates. It is an identity
#: string only — it grants nothing and is never treated as an approver.
AGENT_ACTOR = "agent:ProductAGI"

#: Opportunity type used when a recommendation becomes an action. Chosen from
#: the platform's existing ``OpportunityType`` vocabulary so the action
#: executor needs no new capability.
ACTION_OPPORTUNITY_TYPE = "upsell"

#: Recommendation → action type. ``generate_opportunity`` is one of the four
#: pre-existing permitted action types, has a real registered executor, and
#: creates a growth opportunity record. It does NOT mutate the catalog,
#: change a price, or touch any provider.
ACTION_TYPE = AgentActionType.generate_opportunity


class SignalReading(BaseModel):
    """The model's read of the observation stage."""

    observations: list[str] = Field(default_factory=list, max_length=12)
    primary_signal: str = Field(default="", max_length=400)
    open_questions: list[str] = Field(default_factory=list, max_length=4)
    knowledge_gaps: list[str] = Field(default_factory=list, max_length=8)


class SafetyVerdict(BaseModel):
    """The safety gate's structured result."""

    passed: bool = True
    blocked_items: list[str] = Field(default_factory=list, max_length=16)
    notes: str = Field(default="", max_length=600)


class _EarlyComplete(Exception):
    """A stage legitimately finished the run."""


class _BudgetExceeded(Exception):
    """A bounded-resource budget was exhausted."""


class _LLMBudgetExhausted(Exception):
    """This run has spent its LLM call budget.

    Raised by ``_llm_call`` rather than degrading silently, so every call
    site already handles it through the same path as a provider failure:
    the run marks itself degraded and falls back to the deterministic
    pipeline. That keeps the LLM budget a HARD bound on cost instead of a
    declared-but-unenforced number.
    """


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProductAGI:
    """An autonomous product-growth employee."""

    NAME = "ProductAGI"

    def __init__(
        self,
        db: Session,
        merchant_id: uuid.UUID,
        *,
        llm: BaseLLMProvider | None = None,
        embedding_provider: Any = None,
        limits: LoopLimits | None = None,
    ) -> None:
        self._db = db
        self._merchant_id = merchant_id
        self._llm = llm
        self._limits = limits or agent_tools.PRODUCT_AGENT_LIMITS

        self._tool_ctx = ToolContext(
            db=db,
            merchant_id=merchant_id,
            llm=llm,
            embedding_provider=embedding_provider,
        )
        self._mcp_ledger = MCPLedger()
        self._mcp = mcp_bridge.build_client(
            db,
            merchant_id,
            embedding_provider=embedding_provider,
            on_call=self._mcp_ledger.record,
        )
        self._active_state: ProductAgentState | None = None
        self._active_recorder: EventRecorder | None = None
        self._research: ProductResearch | None = None

        self._llm_provider_name: str | None = None
        self._llm_model_name: str | None = None
        if llm is not None:
            try:
                from backend.app.agents.product_agi.llm import llm_identity

                _, self._llm_provider_name, self._llm_model_name = llm_identity()
            except Exception:
                self._llm_provider_name = type(llm).__name__

    # ── LLM wrapper (observability + graceful degradation) ──────────────

    def _llm_call(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        *,
        stage: Stage,
        decision_type: str,
        system: str,
        user: str,
        schema: Any,
        safe_summary: str,
        max_tokens: int = 1600,
    ) -> Any:
        """Invoke Groq with full observability; re-raise on failure.

        On success: records safe metadata (provider, model, latency,
        decision type) and emits a user-safe event. On failure: marks the run
        degraded, emits an honest ``llm_unavailable`` event, and re-raises so
        the caller falls back to the deterministic path instead of
        fabricating reasoning. Never logs prompts, keys or raw responses.
        """
        assert self._llm is not None
        if state.llm_calls >= self._limits.max_llm_calls:
            recorder.emit(
                stage=stage.value,
                event_type="llm_unavailable",
                message=(
                    "LLM call budget for this run is spent "
                    f"({self._limits.max_llm_calls}) — continuing with the "
                    "deterministic pipeline; no reasoning fabricated"
                ),
            )
            state.llm_degraded = True
            state.reasoning_status = "degraded"
            raise _LLMBudgetExhausted(
                f"run exceeded its {self._limits.max_llm_calls} LLM call budget"
            )
        t0 = time.perf_counter()
        try:
            parsed = self._llm.generate_structured(
                system, user, schema, temperature=0.0, max_tokens=max_tokens
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            stats = self._provider_stats()
            state.timing["llm_total_ms"] += latency_ms + stats["retry_delay_ms"]
            state.llm_degraded = True
            state.reasoning_status = "degraded"
            state.llm_decisions.append(
                {
                    "decision_type": decision_type,
                    "provider": self._llm_provider_name,
                    "model": self._llm_model_name,
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": type(exc).__name__,
                    **stats,
                }
            )
            recorder.emit(
                stage=stage.value,
                event_type="llm_unavailable",
                message=(
                    "Groq reasoning unavailable "
                    f"({type(exc).__name__}) — continuing with the "
                    "deterministic pipeline; no reasoning fabricated"
                ),
            )
            raise
        latency_ms = int((time.perf_counter() - t0) * 1000)
        stats = self._provider_stats()
        state.llm_calls += 1
        state.timing["llm_total_ms"] += latency_ms + stats["retry_delay_ms"]
        state.timing["llm_calls"] = state.llm_calls
        state.llm_decisions.append(
            {
                "decision_type": decision_type,
                "provider": self._llm_provider_name,
                "model": self._llm_model_name,
                "latency_ms": latency_ms,
                "success": True,
                **stats,
            }
        )
        recorder.emit(
            stage=stage.value,
            event_type="llm_decision",
            message=safe_summary,
            data={"decision_type": decision_type},
        )
        return parsed

    def _provider_stats(self) -> dict[str, Any]:
        try:
            stats = getattr(self._llm, "last_call_stats", None) or {}
            return {
                "attempts": int(stats.get("attempts", 1)),
                "retries": int(stats.get("retries", 0)),
                "rate_limited": bool(stats.get("rate_limited", False)),
                "retry_delay_ms": int(stats.get("retry_delay_ms", 0)),
            }
        except Exception:
            return {
                "attempts": 1,
                "retries": 0,
                "rate_limited": False,
                "retry_delay_ms": 0,
            }

    # ── MCP helpers ─────────────────────────────────────────────────────

    def _on_mcp_call(self, record: MCPToolCallRecord) -> None:
        """Mirror one MCP invocation into run state and the activity feed."""
        state = self._active_state
        recorder = self._active_recorder
        if state is None or recorder is None:
            return
        row = record.to_dict()
        row["phase"] = state.stage.value
        state.mcp_calls.append(row)
        state.tool_call_count += 1
        state.timing["mcp_calls"] = len(state.mcp_calls)
        state.timing["mcp_total_ms"] = state.timing.get("mcp_total_ms", 0) + int(
            record.duration_ms or 0
        )
        if row.get("cached"):
            state.timing["mcp_cache_hits"] = state.timing.get("mcp_cache_hits", 0) + 1
        if row.get("status") != "success":
            state.timing["mcp_errors"] = state.timing.get("mcp_errors", 0) + 1
        state.timing["mcp_retries"] = state.timing.get("mcp_retries", 0) + int(
            record.retries or 0
        )
        recorder.emit(
            stage=state.stage.value,
            event_type="mcp_tool_call",
            message=f"{record.tool}: {_mcp_summary(row)}",
            data={
                "tool": record.tool,
                "status": record.status,
                "duration_ms": record.duration_ms,
                "cached": bool(record.cached),
                "read_only": bool(record.read_only),
                "domain": record.domain,
                "error_code": record.error_code,
            },
        )

    def _call(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        *,
        stage: Stage,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """One MCP read. Returns the unwrapped data, or None on failure.

        Failures are recorded as an honest gap. They never become a
        plausible-looking default payload.
        """
        from backend.app.integrations.mcp.errors import MCPError

        try:
            return mcp_bridge.mcp_invoke(self._mcp, name, arguments)
        except MCPError as exc:
            state.knowledge_gaps.append(f"{name} failed: {exc.code}")
            state.errors.append(f"{name}: {exc.code}")
            recorder.emit(
                stage=stage.value,
                event_type="tool_failed",
                message=f"{name} failed ({exc.code}) — recorded as a gap",
                data={"tool": name, "error_code": exc.code},
            )
            return None

    # ── persistence ─────────────────────────────────────────────────────

    def _checkpoint(self, run_row: ProductAgentRun, state: ProductAgentState) -> None:
        """Persist progress so other sessions can observe the live run.

        Commit failures are contained (rollback + continue) so a transient DB
        hiccup never kills a run. Also refreshes the cooperative-cancel flag,
        which in-memory state cannot see.
        """
        t0 = time.perf_counter()
        try:
            self._sync_row(run_row, state)
            self._db.commit()
        except Exception:
            log.warning("ProductAgent checkpoint commit failed; continuing", exc_info=True)
            try:
                self._db.rollback()
            except Exception:
                pass
        finally:
            state.timing["db_total_ms"] = state.timing.get("db_total_ms", 0) + int(
                (time.perf_counter() - t0) * 1000
            )
        try:
            fresh = self._db.scalar(
                select(ProductAgentRun.state).where(ProductAgentRun.id == run_row.id)
            )
            if isinstance(fresh, dict) and fresh.get("cancelled"):
                state.cancelled = True
        except Exception:
            pass

    def _sync_row(self, run_row: ProductAgentRun, state: ProductAgentState) -> None:
        run_row.current_stage = state.stage.value
        run_row.status = state.run_status  # type: ignore[attr-defined]
        run_row.products_analyzed = int(state.catalog.get("product_count") or 0)
        run_row.opportunities_found = int(
            state.opportunities_payload.get("opportunity_count") or 0
        )
        run_row.recommendations_created = len(state.recommendations)
        # Refresh the header metrics on every checkpoint so a polling client
        # sees REAL measured progress mid-run instead of nulls until the end.
        # ``window_days`` and the LLM flag are the run's configuration and are
        # carried forward untouched.
        metrics = dict(run_row.metrics or {})
        metrics.setdefault("window_days", state.window_days)
        metrics.setdefault("llm_configured", self._llm is not None)
        metrics.update(_dashboard_metrics(state))
        run_row.metrics = metrics
        run_row.state = state.to_dict()

    # ── public entry point ──────────────────────────────────────────────

    def run(
        self,
        run_row: ProductAgentRun,
        objective: str,
        *,
        analysis_cycle_id: str | None = None,
    ) -> ProductAgentRun:
        """Execute the nine-stage cycle against an existing run row."""
        t_start = time.perf_counter()
        state = ProductAgentState(
            run_id=str(run_row.id),
            merchant_id=str(self._merchant_id),
            objective=objective,
        )
        # The measurement window is a property of the RUN, not of each stage,
        # so the catalog view, the performance view, the deterministic tools
        # and the dashboard all describe the same period.
        configured = (run_row.metrics or {}).get("window_days")
        if isinstance(configured, int) and 1 <= configured <= 365:
            state.window_days = configured
        # Local run status mirrors the persisted row so checkpoints stay honest.
        state.run_status = RunStatus.queued  # type: ignore[attr-defined]

        if analysis_cycle_id:
            run_row.analysis_cycle_id = analysis_cycle_id

        self._mcp.clear_run_state()
        self._mcp.context.run_id = str(run_row.id)
        self._active_state = state
        recorder = EventRecorder(self._db, run_row)
        self._active_recorder = recorder
        # Mirror every MCP invocation into run state + the activity feed.
        # Bound per run so a stray call outside a run writes nothing.
        self._mcp_ledger.bind(self._on_mcp_call)

        if self._llm is not None:
            state.reasoning_status = "reasoning"
            state.reasoning_summary = (
                "Groq reasoning engine engaged — reading live catalog and demand data"
            )
        else:
            state.reasoning_status = "reasoning"
            state.reasoning_summary = (
                "Running the deterministic pipeline (no LLM key configured)"
            )
            state.llm_degraded = True

        self._transition(run_row, RunStatus.running, state, recorder)
        run_row.started_at = utcnow()
        self._db.flush()

        deadline = time.monotonic() + self._limits.run_timeout_seconds
        try:
            self._stage_understand_catalog(state, recorder, run_row)
            self._checkpoint(run_row, state)
            self._stage_analyze_performance(state, recorder, run_row)
            self._checkpoint(run_row, state)
            self._stage_find_opportunities(state, recorder, run_row)
            self._checkpoint(run_row, state)
            self._stage_research(state, recorder, run_row, deadline)
            self._checkpoint(run_row, state)
            analysis = self._stage_prepare_recommendation(state, recorder, run_row)
            self._checkpoint(run_row, state)
            if not self._stage_safety_check(state, recorder, run_row, analysis):
                self._finish(
                    run_row, RunStatus.blocked, state, recorder,
                    reason="safety verification rejected every recommendation",
                )
                return run_row
            self._checkpoint(run_row, state)
            self._stage_prepare_actions(state, recorder, run_row, analysis)
            self._checkpoint(run_row, state)
            self._stage_wait_or_complete(state, recorder, run_row)
        except _EarlyComplete:
            self._sync_row(run_row, state)
            self._db.commit()
            return run_row
        except _BudgetExceeded as exc:
            self._finish(
                run_row, RunStatus.blocked, state, recorder, reason=str(exc)
            )
            return run_row
        except Exception as exc:  # noqa: BLE001 — failure isolation boundary
            log.exception("ProductAgent run %s failed", run_row.id)
            state.errors.append(f"{type(exc).__name__}: {exc}")
            self._finish(
                run_row, RunStatus.failed, state, recorder,
                reason=f"{type(exc).__name__}: {exc}",
            )
            return run_row

        state.timing["total_ms"] = int((time.perf_counter() - t_start) * 1000)
        self._sync_row(run_row, state)
        self._db.commit()
        return run_row

    # ── stage 1: UNDERSTAND_CATALOG ─────────────────────────────────────

    def _stage_understand_catalog(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
    ) -> None:
        t0 = time.perf_counter()
        stage = Stage.understand_catalog
        state.set_stage(stage)
        run_row.current_stage = stage.value
        recorder.emit(
            stage=stage.value,
            event_type="stage_started",
            message="01 — Reading the real product catalog",
        )

        products = self._call(
            state, recorder, stage=stage, name="commerce.list_products", arguments={"limit": 200}
        ) or {}
        inventory = self._call(
            state, recorder, stage=stage, name="commerce.get_inventory",
            arguments={"window_days": state.window_days},
        ) or {}

        product_count = int(products.get("product_count") or 0)
        state.catalog = {
            "product_count": product_count,
            "categories": inventory.get("categories") or [],
            "category_count": inventory.get("category_count"),
            "total_units": inventory.get("total_units"),
            "catalog_value_inr": inventory.get("catalog_value_inr"),
            "in_stock_count": inventory.get("in_stock_count"),
            "out_of_stock_count": inventory.get("out_of_stock_count"),
            "low_stock_count": inventory.get("low_stock_count"),
            "low_stock_threshold": inventory.get("low_stock_threshold"),
            "data_completeness": inventory.get("data_completeness"),
            "products": [
                {
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "price_inr": p.get("price_inr"),
                    "stock_quantity": p.get("stock_quantity"),
                    "has_description": p.get("has_description"),
                }
                for p in (products.get("products") or [])
            ],
        }
        state.add_evidence(
            "commerce.list_products",
            "mcp",
            f"Loaded {product_count} real catalog product(s)",
            tool="commerce.list_products",
        )
        recorder.emit(
            stage=stage.value,
            event_type="catalog_loaded",
            message=f"Loaded {product_count} products from this workspace's catalog",
            data={"product_count": product_count},
        )

        if product_count == 0:
            state.knowledge_gaps.append(
                "This workspace has no products in its catalog"
            )
            recorder.emit(
                stage=stage.value,
                event_type="no_catalog",
                message="Catalog is empty — nothing to analyse honestly",
            )
            run_row.summary = (
                "No products in this workspace's catalog, so no product analysis "
                "is possible. No findings or recommendations were produced."
            )
            run_row.metrics = {
                "product_count": 0,
                "opportunity_count": 0,
                "finding_count": 0,
                "recommendation_count": 0,
            }
            run_row.result = {
                "completed": True,
                "outcome": "empty_catalog",
                "detail": run_row.summary,
            }
            self._finish(
                run_row, RunStatus.completed_no_actions, state, recorder,
                reason="empty catalog: no product analysis is possible",
                advance_stage=False,
            )
            raise _EarlyComplete

        # Name the primary signal (Groq) or derive it deterministically.
        signal = self._read_signal(state, recorder)
        state.catalog["primary_signal"] = signal
        state.timing["analysis_total_ms"] = (
            state.timing.get("analysis_total_ms", 0)
            + int((time.perf_counter() - t0) * 1000)
        )
        recorder.emit(
            stage=stage.value,
            event_type="stage_completed",
            message=f"01 — Catalog understood: {product_count} products, "
            f"{state.catalog.get('category_count')} categories",
            data={"primary_signal": signal},
        )
        state.set_stage(Stage.analyze_performance)

    def _read_signal(self, state: ProductAgentState, recorder: EventRecorder) -> str:
        """Primary product signal: Groq when configured, else deterministic."""
        stage = Stage.understand_catalog
        if self._llm is not None:
            try:
                reading = self._llm_call(
                    state,
                    recorder,
                    stage=stage,
                    decision_type="observe_product_signal",
                    system=prompts.OBSERVE_SYSTEM,
                    user=prompts.observe_user(state.catalog, state.performance),
                    schema=SignalReading,
                    safe_summary="Groq named the primary product signal",
                    max_tokens=800,
                )
                state.knowledge_gaps.extend(reading.knowledge_gaps[:8])
                state.performance.setdefault("observations", [])
                state.performance["observations"] = reading.observations
                state.performance["open_questions"] = reading.open_questions
                if reading.primary_signal:
                    return reading.primary_signal
            except Exception as exc:  # noqa: BLE001
                log.warning("Signal reading failed, using deterministic: %s", exc)

        # Deterministic: the biggest real, explainable signal available.
        low = int(state.catalog.get("low_stock_count") or 0)
        units = state.catalog.get("total_units")
        if low:
            return (
                f"{low} product(s) at or below the configured low-stock "
                f"threshold of {state.catalog.get('low_stock_threshold')}."
            )
        if units:
            return f"{units} units on hand across {state.catalog.get('product_count')} products."
        return "Catalog loaded; no dominant stock signal detected."

    # ── stage 2: ANALYZE_PERFORMANCE ────────────────────────────────────

    def _stage_analyze_performance(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
    ) -> None:
        t0 = time.perf_counter()
        stage = Stage.analyze_performance
        state.set_stage(stage)
        recorder.emit(
            stage=stage.value,
            event_type="stage_started",
            message="02 — Analysing real product performance",
        )

        perf = self._call(
            state, recorder, stage=stage, name="analytics.get_product_performance",
            arguments={"limit": 25, "window_days": state.window_days},
        ) or {}
        orders = self._call(
            state, recorder, stage=stage, name="marketing.analytics.get_orders",
            arguments={"window_days": state.window_days},
        ) or {}

        top = perf.get("top_products") or []
        never_sold = int(perf.get("never_sold_count") or 0)
        state.performance = {
            **state.performance,
            "status": perf.get("status"),
            "window_days": perf.get("window_days"),
            "settled_orders": perf.get("settled_orders"),
            "total_units_sold": perf.get("total_units_sold"),
            "total_revenue_inr": perf.get("total_revenue_inr"),
            "average_order_value_inr": perf.get("average_order_value_inr"),
            "never_sold_count": never_sold,
            "top_products": [
                {
                    "rank": p.get("rank"),
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "units_sold": p.get("units_sold"),
                    "revenue_inr": p.get("revenue_inr"),
                    "revenue_share_pct": p.get("revenue_share_pct"),
                    "status": p.get("status"),
                }
                for p in top
            ],
            "orders_view": {
                "window_days": orders.get("window_days"),
                "order_change_pct": orders.get("order_change_pct"),
                "revenue_change_pct": orders.get("revenue_change_pct"),
                "average_order_value_inr": orders.get("average_order_value_inr"),
                "trend": orders.get("trend"),
            },
        }
        state.add_evidence(
            "analytics.get_product_performance",
            "mcp",
            (
                f"Measured {perf.get('total_units_sold', 0)} unit(s) and INR "
                f"{perf.get('total_revenue_inr', 0)} across "
                f"{perf.get('settled_orders', 0)} settled order(s)"
            ),
            tool="analytics.get_product_performance",
        )
        recorder.emit(
            stage=stage.value,
            event_type="performance_analysed",
            message=(
                f"Analysed product performance: {perf.get('total_units_sold', 0)} "
                f"unit(s), {never_sold} never-sold product(s)"
            ),
            data={
                "settled_orders": perf.get("settled_orders"),
                "total_revenue_inr": perf.get("total_revenue_inr"),
            },
        )
        if never_sold:
            state.knowledge_gaps.append(
                f"{never_sold} product(s) have zero settled demand in the window"
            )
        state.timing["analysis_total_ms"] = (
            state.timing.get("analysis_total_ms", 0)
            + int((time.perf_counter() - t0) * 1000)
        )
        recorder.emit(
            stage=stage.value,
            event_type="stage_completed",
            message="02 — Performance analysis complete",
        )
        state.set_stage(Stage.find_opportunities)

    # ── stage 3: FIND_OPPORTUNITIES ─────────────────────────────────────

    def _stage_find_opportunities(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
    ) -> None:
        t0 = time.perf_counter()
        stage = Stage.find_opportunities
        state.set_stage(stage)
        recorder.emit(
            stage=stage.value,
            event_type="stage_started",
            message="03 — Running deterministic product intelligence",
        )

        payload = self._call(
            state,
            recorder,
            stage=stage,
            name="product_intelligence.get_product_opportunities",
            arguments={"limit": 30, "window_days": state.window_days},
        ) or {}
        state.opportunities_payload = payload
        by_type: dict[str, int] = {}
        for item in payload.get("opportunities") or []:
            key = str(item.get("type") or "other")
            by_type[key] = by_type.get(key, 0) + 1
        health = payload.get("catalog_health") or {}
        state.opportunities = {
            "opportunity_count": payload.get("opportunity_count"),
            "by_type": by_type,
            "catalog_health": {
                "score": health.get("score"),
                "grade": health.get("grade"),
                "status": health.get("status"),
            },
            "unavailable": payload.get("unavailable") or [],
            "items": payload.get("opportunities") or [],
        }
        state.add_evidence(
            "product_intelligence.get_product_opportunities",
            "mcp",
            (
                f"Deterministic intelligence found "
                f"{payload.get('opportunity_count', 0)} opportunity(ies) across "
                f"{len(by_type)} category(ies)"
            ),
            tool="product_intelligence.get_product_opportunities",
        )
        for gap in payload.get("unavailable") or []:
            reason = gap.get("reason")
            if reason:
                state.knowledge_gaps.append(f"{gap.get('signal')}: {reason}")

        self._record_opportunity_findings(state, recorder, payload)
        recorder.emit(
            stage=stage.value,
            event_type="opportunities_found",
            message=f"Found {payload.get('opportunity_count', 0)} deterministic opportunities",
            data={"by_type": by_type},
        )
        state.timing["analysis_total_ms"] = (
            state.timing.get("analysis_total_ms", 0)
            + int((time.perf_counter() - t0) * 1000)
        )
        recorder.emit(
            stage=stage.value,
            event_type="stage_completed",
            message="03 — Opportunity detection complete",
        )
        state.set_stage(Stage.research_analyze)

    def _record_opportunity_findings(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        payload: dict[str, Any],
    ) -> None:
        """Persist one finding row per real opportunity. No invention here."""
        stage = Stage.find_opportunities
        for item in payload.get("opportunities") or []:
            tool = "product_intelligence.get_product_opportunities"
            evidence = [
                {
                    "source": item.get("type") or "product_intelligence",
                    "source_kind": "deterministic",
                    "statement": f"{item.get('title')}: {item.get('detail')}",
                    "tool": tool,
                }
            ]
            state.add_evidence(tool, "deterministic", str(item.get("detail")), tool=tool)
            row = ProductAgentFinding(
                run_id=uuid.UUID(state.run_id),
                merchant_id=self._merchant_id,
                type=str(item.get("type") or "catalog")[:40],
                title=str(item.get("title") or "Product opportunity")[:255],
                description=str(item.get("detail") or "")[:4000],
                severity=str(item.get("severity") or "info")[:20],
                confidence=None,
                evidence=evidence,
                product_ids=item.get("product_ids") or [],
                data={"basis": item.get("basis")},
            )
            self._db.add(row)
            state.findings.append(
                {
                    "id": str(row.id),
                    "type": row.type,
                    "title": row.title,
                    "description": row.description,
                    "severity": row.severity,
                    "evidence": evidence,
                    "basis": item.get("basis"),
                }
            )
        # An honest data-gap finding when nothing was computable.
        if int(payload.get("opportunity_count") or 0) == 0:
            row = ProductAgentFinding(
                run_id=uuid.UUID(state.run_id),
                merchant_id=self._merchant_id,
                type="data_gap",
                title="No product opportunity detected from the available data",
                description=(
                    "Deterministic product intelligence found no stock risk, "
                    "underperformance, content gap, pricing signal or bundle "
                    "candidate in this workspace's real data."
                ),
                severity="info",
                confidence=None,
                evidence=[
                    {
                        "source": "product_intelligence",
                        "source_kind": "deterministic",
                        "statement": (
                            "product_intelligence.get_product_opportunities returned "
                            "zero opportunities"
                        ),
                        "tool": "product_intelligence.get_product_opportunities",
                    }
                ],
                product_ids=[],
                data={"basis": "deterministic_zero_result"},
            )
            self._db.add(row)
            state.findings.append(
                {
                    "id": str(row.id),
                    "type": "data_gap",
                    "title": row.title,
                    "description": row.description,
                    "severity": "info",
                    "evidence": [
                        {
                            "source": "product_intelligence",
                            "source_kind": "deterministic",
                            "statement": (
                                "product_intelligence.get_product_opportunities "
                                "returned zero opportunities"
                            ),
                            "tool": "product_intelligence.get_product_opportunities",
                        }
                    ],
                    "basis": "deterministic_zero_result",
                }
            )
        self._db.flush()
        recorder.emit(
            stage=stage.value,
            event_type="findings_recorded",
            message=f"Recorded {len(state.findings)} evidence-backed finding(s)",
        )

    # ── stage 4: RESEARCH_ANALYZE ───────────────────────────────────────

    def _stage_research(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
        deadline: float,
    ) -> None:
        t0 = time.perf_counter()
        stage = Stage.research_analyze
        state.set_stage(stage)
        recorder.emit(
            stage=stage.value,
            event_type="stage_started",
            message="04 — Researching supporting evidence (agentic RAG)",
        )

        questions = list(state.performance.get("open_questions") or [])
        if not questions and self._llm is not None:
            questions = self._propose_questions(state, recorder)
        if not questions:
            signal = state.catalog.get("primary_signal") or "product performance"
            questions = [f"Why does this signal hold for this catalog: {signal}?"]
        questions = questions[:2]

        self._research = ProductResearch(
            tool_ctx=self._tool_ctx,
            mcp_client=self._mcp,
            llm=self._llm,
            limits=self._limits,
            stage=stage,
        )
        recorder.emit(
            stage=stage.value,
            event_type="rag_started",
            message=f"05 — Retrieving evidence for: {questions[0]}",
        )
        for question in questions:
            self._check_budget(state, deadline)
            state.iterations += 1
            qt0 = time.perf_counter()
            result = self._research.research(question)
            state.timing["rag_total_ms"] = (
                state.timing.get("rag_total_ms", 0)
                + int((time.perf_counter() - qt0) * 1000)
            )
            state.rag_rounds += result.rounds
            state.timing["rag_rounds"] = state.rag_rounds
            state.retrieval_log.append(result.to_dict())
            for statement in result.evidence_statements[:8]:
                state.add_evidence(
                    "agentic_rag", "rag", statement, tool="agentic_rag"
                )
            if result.sufficient:
                recorder.emit(
                    stage=stage.value,
                    event_type="rag_sufficient",
                    message=(
                        f"Evidence sufficient for: {question} "
                        f"({result.rounds} retrieval round(s))"
                    ),
                    data={"rounds": result.rounds},
                )
            else:
                state.knowledge_gaps.extend(result.gaps)
                recorder.emit(
                    stage=stage.value,
                    event_type="rag_insufficient",
                    message=(
                        f"Evidence insufficient for: {question} — gap recorded honestly"
                    ),
                    data={"gaps": result.gaps},
                )
            # Per-question checkpoint so progress is queryable mid-run.
            self._checkpoint(run_row, state)

        state.timing["analysis_total_ms"] = (
            state.timing.get("analysis_total_ms", 0)
            + int((time.perf_counter() - t0) * 1000)
        )
        recorder.emit(
            stage=stage.value,
            event_type="stage_completed",
            message=f"04 — Research complete: {state.rag_rounds} retrieval round(s)",
        )
        state.set_stage(Stage.prepare_recommendation)

    def _propose_questions(
        self, state: ProductAgentState, recorder: EventRecorder
    ) -> list[str]:
        """Let Groq pick retrieval questions; fall back to the signal."""
        from backend.app.agents.product_agi.schemas import ResearchQuestions

        stage = Stage.research_analyze
        try:
            proposed = self._llm_call(
                state,
                recorder,
                stage=stage,
                decision_type="propose_research_questions",
                system=prompts.RESEARCH_QUESTION_SYSTEM,
                user=prompts.research_question_user(
                    str(state.catalog.get("primary_signal") or ""),
                    [p.get("name") for p in state.catalog.get("products") or []],
                ),
                schema=ResearchQuestions,
                safe_summary="Groq proposed retrieval questions",
                max_tokens=500,
            )
            return [q.question for q in proposed.root[:2]]
        except Exception as exc:  # noqa: BLE001
            log.warning("Question proposal failed: %s", exc)
            return []

    # ── stage 5: PREPARE_RECOMMENDATION ─────────────────────────────────

    def _stage_prepare_recommendation(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
    ) -> AnalysisResult | None:
        t0 = time.perf_counter()
        stage = Stage.prepare_recommendation
        state.set_stage(stage)
        recorder.emit(
            stage=stage.value,
            event_type="stage_started",
            message="06 — Preparing evidence-backed recommendations",
        )

        research = {
            "evidence_statements": [e.statement for e in state.evidence if e.source_kind == "rag"][:20],
            "rounds": state.rag_rounds,
            "knowledge_gaps": list(state.knowledge_gaps),
        }
        analysis: AnalysisResult | None = None
        if self._llm is not None:
            try:
                state.reasoning_status = "reasoning"
                analysis = self._llm_call(
                    state,
                    recorder,
                    stage=stage,
                    decision_type="recommend",
                    system=prompts.REASON_SYSTEM,
                    user=prompts.reason_user(
                        catalog=state.catalog,
                        performance=state.performance,
                        opportunities=state.opportunities,
                        research=research,
                    ),
                    schema=AnalysisResult,
                    safe_summary="Groq produced the structured recommendation set",
                    max_tokens=2400,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("Recommendation reasoning failed: %s", exc)
                analysis = None

        if analysis is None:
            analysis = self._deterministic_analysis(state, recorder)
        else:
            state.reasoning_status = "reasoning_complete"
            state.reasoning_summary = analysis.summary[:300]

        state.knowledge_gaps.extend(analysis.knowledge_gaps[:8])
        self._persist_analysis(
            state,
            recorder,
            analysis,
            # Provenance of THIS conclusion, not of the LLM's availability:
            # a degraded run must never be labelled as LLM-reasoned.
            llm_reasoned=analysis is not None and self._llm is not None
            and not state.llm_degraded,
        )
        state.timing["analysis_total_ms"] = (
            state.timing.get("analysis_total_ms", 0)
            + int((time.perf_counter() - t0) * 1000)
        )
        recorder.emit(
            stage=stage.value,
            event_type="recommendations_prepared",
            message=(
                f"06 — Prepared {len(state.recommendations)} recommendation(s), "
                f"{len(analysis.findings)} finding(s)"
            ),
        )
        state.set_stage(Stage.safety_check)
        return analysis

    def _deterministic_analysis(
        self, state: ProductAgentState, recorder: EventRecorder
    ) -> AnalysisResult:
        """Bounded fallback built ONLY from deterministic output.

        Used when no LLM is configured or the provider failed. Every
        recommendation cites a real opportunity item and claims no impact it
        cannot compute — the fallback is honest by construction, and the run
        is marked degraded so the dashboard says so.
        """
        stage = Stage.prepare_recommendation
        from backend.app.agents.product_agi.schemas import (
            Finding,
            Recommendation,
        )

        recommendations: list[Recommendation] = []
        for item in (state.opportunities.get("items") or [])[:4]:
            recommendations.append(
                Recommendation(
                    type=_map_type(str(item.get("type"))),
                    title=str(item.get("title"))[:200],
                    problem=str(item.get("detail"))[:1200],
                    recommendation=(
                        f"Review and act on: {item.get('title')}. "
                        "The Product Agent prepared this for your approval; "
                        "nothing has been changed."
                    )[:1200],
                    why_now=(
                        f"Detected by deterministic analysis on real data "
                        f"({item.get('basis')})."
                    )[:600],
                    confidence=0.5,
                    evidence_refs=[f"{item.get('title')}: {item.get('detail')}"],
                    affected_products=[str(n) for n in (item.get("affected_products") or [])],
                    action_required=True,
                    approval_required=True,
                    risk=(
                        "Derived without LLM reasoning; confirm the numbers "
                        "before acting."
                    ),
                    expected_impact_known=False,
                    expected_impact_text=None,
                )
            )
        summary = (
            f"Analysed {state.catalog.get('product_count', 0)} real product(s) and "
            f"found {state.opportunities.get('opportunity_count', 0)} deterministic "
            "opportunity(ies). Reasoning ran without an LLM, so recommendations are "
            "restatements of measured signals rather than interpreted ones."
        )
        recorder.emit(
            stage=stage.value,
            event_type="deterministic_fallback",
            message=(
                "Produced deterministic recommendations from measured signals "
                "(no LLM reasoning available)"
            ),
        )
        return AnalysisResult(
            findings=[],
            recommendations=recommendations,
            # NOT the state's own gaps: re-adding them here would duplicate
            # every gap the run has already recorded.
            knowledge_gaps=[],
            summary=summary,
            reasoning=(
                "Every item below is a deterministic computation over this "
                "workspace's products and order items. No interpretation was "
                "added because no reasoning engine was available."
            ),
        )

    def _persist_analysis(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        analysis: AnalysisResult,
        *,
        llm_reasoned: bool,
    ) -> None:
        """Write findings + recommendations rows, re-validating product names.

        Every product name the model used is checked against THIS tenant's
        catalog. A name that does not exist is dropped and the recommendation
        records that fact rather than persisting a phantom product.

        ``llm_reasoned`` records WHERE this conclusion came from, so a run
        that fell back to the deterministic pipeline is never stored — or
        displayed — as LLM reasoning.
        """
        valid_names = {
            str(p.get("name"))
            for p in (state.catalog.get("products") or [])
            if p.get("name")
        }
        provenance = "llm_over_deterministic_observations" if llm_reasoned else (
            "deterministic_opportunity"
        )
        source_kind = "llm" if llm_reasoned else "deterministic"
        run_uuid = uuid.UUID(state.run_id)

        for finding in analysis.findings:
            evidence = [
                {
                    "source": source_kind,
                    "source_kind": source_kind,
                    "statement": ref,
                    "tool": None,
                }
                for ref in finding.evidence_refs[:6]
            ]
            row = ProductAgentFinding(
                run_id=run_uuid,
                merchant_id=self._merchant_id,
                type=finding.type[:40],
                title=finding.title[:255],
                description=finding.description[:4000],
                severity=finding.severity[:20],
                confidence=finding.confidence,
                evidence=evidence,
                product_ids=[],
                data={"stage": Stage.prepare_recommendation.value},
            )
            self._db.add(row)
            self._db.flush()  # assigns the PK so the state entry can carry it
            state.findings.append(
                {
                    "id": str(row.id),
                    "type": row.type,
                    "title": row.title,
                    "description": row.description,
                    "severity": row.severity,
                    "confidence": row.confidence,
                    "evidence": evidence,
                }
            )

        for rec in analysis.recommendations:
            evidence = [
                {
                    "source": source_kind,
                    "source_kind": source_kind,
                    "statement": ref,
                    "tool": None,
                }
                for ref in rec.evidence_refs[:8]
            ]
            affected = [n for n in rec.affected_products if n in valid_names]
            unknown = [n for n in rec.affected_products if n not in valid_names]
            expected_impact = (
                {
                    "status": "available",
                    "text": str(rec.expected_impact_text)[:600],
                    "basis": "model_restated_from_supplied_observations",
                }
                if rec.expected_impact_known and rec.expected_impact_text
                else {
                    "status": "unavailable",
                    "text": IMPACT_UNAVAILABLE_REASON,
                    "basis": "no_measurable_impact_in_source_data",
                }
            )
            if unknown:
                state.knowledge_gaps.append(
                    f"Recommendation referenced unknown product(s) and they were "
                    f"dropped: {', '.join(unknown[:3])}"
                )
            row = ProductAgentRecommendation(
                run_id=run_uuid,
                merchant_id=self._merchant_id,
                type=rec.type[:40],
                title=rec.title[:255],
                problem=rec.problem[:4000],
                recommendation=rec.recommendation[:4000],
                why_now=rec.why_now[:2000],
                confidence=round(float(rec.confidence), 4),
                evidence=evidence,
                expected_impact=expected_impact,
                risk=(rec.risk or "")[:2000] or None,
                affected_products=affected,
                basis=provenance,
                action_required=bool(rec.action_required),
                approval_required=bool(rec.approval_required),
                status="proposed",
                data={
                    "unknown_products_dropped": unknown,
                    "llm_degraded": bool(state.llm_degraded),
                    "llm_reasoned": llm_reasoned,
                },
            )
            self._db.add(row)
            self._db.flush()  # assigns the PK so the state entry can carry it
            state.recommendations.append(
                {
                    "id": str(row.id),
                    "type": row.type,
                    "title": row.title,
                    "problem": row.problem,
                    "recommendation": row.recommendation,
                    "why_now": row.why_now,
                    "confidence": row.confidence,
                    "evidence": evidence,
                    "expected_impact": expected_impact,
                    "risk": row.risk,
                    "affected_products": affected,
                    "basis": row.basis,
                    "action_required": row.action_required,
                    "approval_required": row.approval_required,
                }
            )
        self._db.flush()

    # ── stage 6: SAFETY_CHECK ───────────────────────────────────────────

    def _stage_safety_check(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
        analysis: AnalysisResult | None,
    ) -> bool:
        """Recommendation-level safety gate. Runs even with no LLM.

        Deterministic checks first (these are the invariants that must never
        fail), then an optional LLM reviewer for judgement the rules cannot
        express. Any failure blocks the run rather than downgrading quietly.
        """
        stage = Stage.safety_check
        recorder.emit(
            stage=stage.value,
            event_type="stage_started",
            message="07 — Running safety verification on recommendations",
        )
        checks: list[dict[str, Any]] = []
        failures: list[str] = []

        valid_names = {
            str(p.get("name"))
            for p in (state.catalog.get("products") or [])
            if p.get("name")
        }
        for rec in state.recommendations:
            problems: list[str] = []
            if not rec.get("evidence"):
                problems.append("no evidence attached")
            if rec.get("approval_required") is False and rec.get("action_required"):
                problems.append("action required but approval not requested")
            invented = [
                n for n in (rec.get("affected_products") or []) if n not in valid_names
            ]
            if invented:
                problems.append(f"names products outside this catalog: {invented}")
            impact = rec.get("expected_impact") or {}
            if impact.get("status") == "available" and not impact.get("text"):
                problems.append("claims an impact without stating it")
            checks.append(
                {
                    "recommendation_id": rec.get("id"),
                    "passed": not problems,
                    "problems": problems,
                }
            )
            if problems:
                failures.extend(f"{rec.get('title')}: {p}" for p in problems)

        llm_notes: str | None = None
        if self._llm is not None and state.recommendations:
            try:
                verdict = self._llm_call(
                    state,
                    recorder,
                    stage=stage,
                    decision_type="safety_review",
                    system=prompts.SAFETY_SYSTEM,
                    user=prompts.safety_user(state.recommendations),
                    schema=SafetyVerdict,
                    safe_summary="Groq reviewed recommendations for safety",
                    max_tokens=900,
                )
                llm_notes = verdict.notes
                for item in verdict.blocked_items:
                    failures.append(f"LLM safety review: {item}")
            except Exception as exc:  # noqa: BLE001
                log.warning("LLM safety review unavailable: %s", exc)

        passed = not failures
        state.verification = {
            "passed": passed,
            "checked_at": utcnow().isoformat(),
            "recommendation_count": len(state.recommendations),
            "checks": checks,
            "failures": failures,
            "llm_reviewed": bool(state.recommendations and self._llm is not None),
            "llm_notes": llm_notes,
            "invariants": [
                "every recommendation carries evidence",
                "no recommendation names a product outside this catalog",
                "no recommendation claims an unstated impact",
                "any required action requests approval",
                "no recommendation mutates the catalog or executes anything",
            ],
        }
        recorder.emit(
            stage=stage.value,
            event_type="verification_passed" if passed else "verification_failed",
            message=(
                f"07 — Safety verification PASSED across "
                f"{len(state.recommendations)} recommendation(s)"
                if passed
                else f"07 — Safety verification FAILED: {failures[:3]}"
            ),
            data={"passed": passed, "failures": failures},
        )
        return passed

    # ── stage 7: prepare actions / WAITING_APPROVAL ─────────────────────

    def _stage_prepare_actions(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
        analysis: AnalysisResult | None,
    ) -> None:
        """Create approval-gated actions through the EXISTING pipeline.

        Uses ``action_service.create_action``, which validates the payload,
        writes an audit event and leaves the row in ``requested``. The agent
        never approves and never executes. Only recommendations that
        actually require a human get an action.
        """
        stage = Stage.waiting_approval
        state.set_stage(stage)
        recorder.emit(
            stage=stage.value,
            event_type="stage_started",
            message="08 — Preparing actions for human approval",
        )
        from backend.app.services import action_service

        created = 0
        for rec in state.recommendations:
            if not rec.get("action_required"):
                continue
            rec_id = rec.get("id")
            row = self._db.get(ProductAgentRecommendation, uuid.UUID(str(rec_id)))
            if row is None:
                continue
            impact = rec.get("expected_impact") or {}
            # Never invent a rupee figure: expected_revenue stays 0 unless a
            # real, parseable amount was stated in the observations.
            action = action_service.create_action(
                self._db,
                merchant_id=self._merchant_id,
                action_type=ACTION_TYPE,
                input_payload={
                    "opportunity_type": ACTION_OPPORTUNITY_TYPE,
                    "title": str(rec.get("title"))[:255],
                    "description": str(rec.get("recommendation"))[:2000],
                    # Floats, not Decimal: input_payload is stored as JSONB and
                    # a Decimal is not JSON-serializable. The payload schema
                    # coerces them back to Decimal for validation.
                    "confidence": float(min(max(float(rec.get("confidence") or 0), 0), 1)),
                    "expected_revenue": 0.0,
                    "target_customer_count": 0,
                    "reasoning": [
                        f"why_now: {rec.get('why_now')}",
                        f"evidence: {'; '.join(str(e.get('statement')) for e in (rec.get('evidence') or [])[:4])}",
                        f"basis: {rec.get('basis')}",
                    ],
                    "opportunity_key": f"product-{rec.get('id')}",
                    "metadata": {
                        "product_agent_recommendation_id": str(rec.get("id")),
                        "product_agent_run_id": state.run_id,
                        "affected_products": rec.get("affected_products") or [],
                        "expected_impact": impact,
                        "risk": rec.get("risk"),
                        "approval_gated": True,
                    },
                },
                requested_by=AGENT_ACTOR,
            )
            row.action_id = action.id
            row.status = "awaiting_approval"
            row.approval_required = True
            state.prepared_actions.append(
                {
                    "recommendation_id": str(rec.get("id")),
                    "action_id": str(action.id),
                    "action_type": str(
                        getattr(action.action_type, "value", action.action_type)
                    ),
                    "status": str(getattr(action.status, "value", action.status)),
                    "approval_state": "REQUIRED",
                    "executed": False,
                }
            )
            created += 1
        self._db.flush()
        run_row.approval_status = "required" if created else "not_required"
        recorder.emit(
            stage=stage.value,
            event_type="actions_prepared",
            message=(
                f"Prepared {created} approval-gated action(s) via the existing "
                "actions pipeline"
                if created
                else "No action required approval — no action was created"
            ),
            data={"created": created},
        )

    def _stage_wait_or_complete(
        self,
        state: ProductAgentState,
        recorder: EventRecorder,
        run_row: ProductAgentRun,
    ) -> None:
        """Park for approval, or finish honestly with nothing to approve."""
        stage = Stage.waiting_approval
        run_row.current_stage = stage.value

        if state.prepared_actions:
            recorder.emit(
                stage=stage.value,
                event_type="awaiting_approval",
                message=(
                    f"{len(state.prepared_actions)} recommendation(s) now require "
                    "your approval. Nothing has been executed."
                ),
                data={"action_count": len(state.prepared_actions)},
            )
            self._finish(
                run_row, RunStatus.waiting_approval, state, recorder,
                reason=(
                    f"{len(state.prepared_actions)} recommendation(s) await human "
                    "approval via /api/actions"
                ),
            )
        else:
            recorder.emit(
                stage=stage.value,
                event_type="no_actions_required",
                message=(
                    "Analysis complete with nothing requiring approval — "
                    "no action was created and nothing was executed"
                ),
            )
            self._finish(
                run_row, RunStatus.completed_no_actions, state, recorder,
                reason="analysis complete; no recommendation required a human decision",
                advance_stage=False,
            )

    # ── terminal ────────────────────────────────────────────────────────

    def _transition(
        self,
        run_row: ProductAgentRun,
        status: RunStatus,
        state: ProductAgentState,
        recorder: EventRecorder,
    ) -> None:
        run_row.status = status.value
        state.run_status = status  # type: ignore[attr-defined]
        self._db.flush()

    def _finish(
        self,
        run_row: ProductAgentRun,
        status: RunStatus,
        state: ProductAgentState,
        recorder: EventRecorder,
        *,
        reason: str,
        advance_stage: bool = True,
    ) -> None:
        run_row.status = status.value
        state.run_status = status  # type: ignore[attr-defined]
        run_row.completed_at = utcnow()
        run_row.errors = list(state.errors)[:20] or None
        run_row.llm_provider = self._llm_provider_name
        run_row.llm_model = self._llm_model_name
        run_row.approval_status = _approval_label(state)
        # Learning is honest by construction: it can only start once an
        # approved action has actually executed and produced an outcome.
        state.learning_status = (
            "pending_outcomes" if state.prepared_actions else "not_started"
        )
        run_row.summary = run_row.summary or _headline(state)
        run_row.metrics = _dashboard_metrics(state)
        run_row.result = {
            "completed": status
            in (RunStatus.waiting_approval, RunStatus.completed_no_actions),
            "outcome": status.value,
            "detail": reason,
            "recommendation_count": len(state.recommendations),
            "action_count": len(state.prepared_actions),
            "executed_count": 0,
            "llm_degraded": bool(state.llm_degraded),
            "knowledge_gaps": list(state.knowledge_gaps)[:12],
        }
        recorder.emit(
            stage=state.stage.value,
            event_type="run_finished",
            message=f"Run {status.value}: {reason}",
            data={"status": status.value},
        )
        if advance_stage and status is RunStatus.waiting_approval:
            # The run genuinely parks here; LEARN runs when a human acts.
            state.set_stage(Stage.waiting_approval)
        self._sync_row(run_row, state)
        self._db.commit()

    # ── budgets ─────────────────────────────────────────────────────────

    def _check_budget(
        self, state: ProductAgentState, deadline: float
    ) -> None:
        if time.monotonic() > deadline:
            raise _BudgetExceeded(
                f"run exceeded its {self._limits.run_timeout_seconds}s budget"
            )
        if state.tool_call_count >= self._limits.max_tool_calls:
            raise _BudgetExceeded(
                f"run exceeded its {self._limits.max_tool_calls} tool-call budget"
            )


# ── helpers ────────────────────────────────────────────────────────────


def _map_type(raw: str) -> str:
    """Map a deterministic opportunity type onto a recommendation type."""
    mapping = {
        "low_stock": "inventory",
        "underperforming": "merchandising",
        "content_gap": "content",
        "pricing": "pricing",
        "bundle": "bundle",
    }
    return mapping.get(raw, "merchandising")


def _approval_label(state: ProductAgentState) -> str:
    if not state.prepared_actions:
        return "not_required"
    statuses = {
        str(a.get("status")) for a in state.prepared_actions
    }
    if statuses & {"approved"}:
        return "approved"
    if statuses & {"executing"}:
        return "executing"
    if statuses & {"completed"}:
        return "completed"
    if statuses & {"rejected"}:
        return "rejected"
    if statuses & {"failed"}:
        return "failed"
    return "required"


def _headline(state: ProductAgentState) -> str:
    """One honest sentence composed from measured values only."""
    products = state.catalog.get("product_count")
    opps = state.opportunities_payload.get("opportunity_count")
    recs = len(state.recommendations)
    if not products:
        return "No products in this workspace's catalog; no analysis was possible."
    base = (
        f"Analysed {products} product(s) and found {opps or 0} deterministic "
        f"opportunity(ies)."
    )
    if recs:
        base += f" Prepared {recs} evidence-backed recommendation(s)"
        if state.prepared_actions:
            base += (
                f", {len(state.prepared_actions)} of which need your approval. "
                "Nothing has been executed."
            )
        else:
            base += "."
    else:
        base += " No recommendation could be supported by the available data."
    return base


def _dashboard_metrics(state: ProductAgentState) -> dict[str, Any]:
    """Header metrics. Every value is measured, or explicitly None."""
    catalog = state.catalog or {}
    return {
        "window_days": state.window_days,
        "product_count": catalog.get("product_count"),
        "total_units": catalog.get("total_units"),
        "category_count": catalog.get("category_count"),
        "catalog_value_inr": catalog.get("catalog_value_inr"),
        "low_stock_count": catalog.get("low_stock_count"),
        "total_units_sold": state.performance.get("total_units_sold"),
        "total_revenue_inr": state.performance.get("total_revenue_inr"),
        "average_order_value_inr": state.performance.get("average_order_value_inr"),
        "opportunity_count": state.opportunities_payload.get("opportunity_count"),
        "finding_count": len(state.findings),
        "recommendation_count": len(state.recommendations),
        "action_count": len(state.prepared_actions),
        "executed_count": 0,
        "knowledge_gap_count": len(state.knowledge_gaps),
    }


def _mcp_summary(row: dict[str, Any]) -> str:
    if row.get("status") == "denied":
        return f"refused — {row.get('error_code')}"
    if row.get("status") == "error":
        return f"failed — {row.get('error_code')}"
    if row.get("cached"):
        return "served from this run's cache"
    return str(row.get("summary") or "done")


__all__ = [
    "ACTION_OPPORTUNITY_TYPE",
    "ACTION_TYPE",
    "AGENT_ACTOR",
    "ProductAGI",
    "SafetyVerdict",
    "SignalReading",
]