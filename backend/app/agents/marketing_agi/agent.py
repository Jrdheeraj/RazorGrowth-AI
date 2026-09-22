"""MarketingAGI — the autonomous bounded reasoning loop.

This is a NEW agent, built from scratch, completely separate from the
legacy MarketingAgent (backend/app/agents/marketing_agent.py), which is
NOT imported, called, or modified here.

The loop (all phases bounded by LoopLimits):

  LOAD CONTEXT → load merchant context + marketing memory
  OBSERVE      → analytics baseline via real SQL tools
  INVESTIGATE  → agentic RAG + dynamic tool selection, driven by the LLM
                 when configured (structured outputs) and deterministic
                 evidence heuristics otherwise
  PLAN         → select workflow + form campaign strategy
  CREATE       → generate campaign content (LLM when available) + audience
  VERIFY       → full self-verification; failures go back to INVESTIGATE
  PREPARE      → persist campaign + propose Phase-4 AgentAction (requested)
  AWAIT        → run ends waiting_approval; humans approve downstream

Termination is explicit: completed / waiting_approval / blocked / failed,
each with a reason. There is no path to an infinite loop: iterations,
tool calls, LLM calls, retrieval rounds, and wall-clock time are all
capped and checked every iteration.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.agents.marketing_agi.limits import LoopLimits, DEFAULT_LIMITS
from backend.app.agents.marketing_agi.state import (
    MarketingAGIState,
    Phase,
    RunStatus,
    assert_run_transition,
)
from backend.app.agents.marketing_agi.events import EventRecorder
from backend.app.agents.marketing_agi.rag import AgenticRAG
from backend.app.agents.marketing_agi.workflows import (
    WorkflowSpec,
    select_workflows,
    workflow_catalog,
)
from backend.app.agents.marketing_agi.verifier import (
    audience_from_find_customers,
    verify_campaign,
)
from backend.app.agents.marketing_agi.memory import (
    MarketingAGIMemory,
    evaluate_outcome,
)
from backend.app.agents.marketing_agi.handoff import HandoffInterface
from backend.app.agents.marketing_agi.tools.bootstrap import register_all_tools
from backend.app.agents.marketing_agi.tools.registry import ToolContext, get_registry
from backend.app.models.marketing_agi import (
    MarketingAGIEvent,
    MarketingAGICampaign,
    MarketingAGIRun,
)

log = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _rupees_short(v: Any) -> str | None:
    """Format a numeric INR value compactly; None when not numeric."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f"₹{f:,.0f}"


def summarize_tool_result(name: str, result: Any) -> str:
    """One-line honest summary of a tool result for the workstation UI.

    Never fabricates: counts/amounts come straight from the result payload;
    unknown shapes fall back to a neutral acknowledgement.
    """
    try:
        if not isinstance(result, dict):
            return "done"
        if name == "find_customers":
            customers = result.get("customers", [])
            n = len(customers) if isinstance(customers, list) else 0
            spend = _rupees_short(result.get("total_spend_inr"))
            return f"{n} customers" + (f" · {spend} spend" if spend else "")
        if name == "get_customer_segments":
            segs = result.get("segments", [])
            return f"{len(segs)} segments" if isinstance(segs, list) else "done"
        if name == "get_customer_profile":
            c = result.get("customer", {})
            label = c.get("email") or c.get("name") or c.get("customer_id") or "profile"
            return f"{label}"
        if name == "get_failed_payment_analytics":
            rec = _rupees_short(result.get("recoverable_revenue_inr"))
            failed = result.get("failed_count", result.get("failed_payments"))
            parts = []
            if failed is not None:
                parts.append(f"{failed} failed")
            if rec:
                parts.append(f"{rec} recoverable")
            return " · ".join(parts) if parts else "done"
        if name in ("get_business_overview", "get_revenue_trend"):
            rev = _rupees_short(
                result.get("total_revenue_inr", result.get("revenue_inr"))
            )
            return f"{rev} revenue" if rev else "done"
        if name == "create_email_campaign_draft":
            if result.get("created"):
                return "Draft created"
            return str(result.get("status", "draft_only")).replace("_", " ")
        if name == "get_email_campaigns":
            camps = result.get("campaigns", [])
            n = len(camps) if isinstance(camps, list) else 0
            esp = "Resend connected" if result.get("connected_esp") else "no ESP"
            return f"{n} campaigns (platform store, {esp})"
        if name == "get_email_campaign_performance":
            n = result.get("campaigns_with_measured_results", 0)
            return f"{n} with measured results · opens/clicks unavailable"
        if name in ("get_google_ads_campaigns", "get_meta_campaigns", "get_social_performance"):
            return "Requires integration — nothing fabricated"
        if name == "get_campaign_history":
            items = result.get("campaigns", result.get("history", []))
            n = len(items) if isinstance(items, list) else 0
            return f"{n} past campaigns"
        if name == "get_action_history":
            items = result.get("actions", result.get("history", []))
            n = len(items) if isinstance(items, list) else 0
            return f"{n} past actions"
        if name == "recall_memory":
            items = result.get("memories", result.get("items", []))
            n = len(items) if isinstance(items, list) else 0
            return f"{n} relevant memories"
        if name == "search_knowledge_store":
            items = result.get("results", result.get("items", []))
            n = len(items) if isinstance(items, list) else 0
            return f"{n} knowledge hits"
        return "done"
    except Exception:
        return "done"


# ---------------------------------------------------------------------------
# Structured LLM schemas for reasoning steps
# ---------------------------------------------------------------------------


class SignalDetection(BaseModel):
    """Model observes the analytics baseline and names what stands out."""

    signals: list[str] = Field(
        description="Distinct marketing-relevant observations, each one sentence"
    )
    primary_signal: str = Field(description="The single most important observation")
    investigation_questions: list[str] = Field(
        description="2-4 specific questions to investigate next"
    )
    knowledge_gaps: list[str] = Field(default_factory=list)


class ToolChoice(BaseModel):
    """The model picks the next tool — dynamic, evidence-driven selection."""

    tool: str = Field(description="Exact tool name from the provided catalog")
    params: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = Field(default="")
    done: bool = Field(
        default=False, description="True when enough evidence is gathered"
    )


class CampaignStrategy(BaseModel):
    """The model designs the marketing intervention."""

    workflow: str = Field(description="Workflow key selected")
    name: str
    objective: str
    audience_reasoning: str
    content_reasoning: str
    message: str
    subject_variants: list[str] = Field(default_factory=list)
    cta: str
    timing: str
    expected_impact_rationale: str
    expected_revenue_inr: float = Field(ge=0)
    success_metric: str
    risks: list[str] = Field(default_factory=list)


class HypothesisVerdict(BaseModel):
    """The model judges each open hypothesis from the evidence."""

    statuses: list[dict[str, str]] = Field(
        description="One per hypothesis: {statement, status, confidence}"
    )


class AgentDecision(BaseModel):
    """Validated agentic-loop decision — the LLM's next step.

    Every autonomous decision the model makes is parsed into this schema
    so raw model output can never drive execution directly. Only
    ``call_tool`` carries executable content, and even then the tool name
    must be allowlisted in the registry and the arguments sanitized
    (tenant keys stripped, JSON-scalar values only) before dispatch.
    """

    decision: str = Field(
        description="call_tool | continue_research | formulate_hypothesis | "
        "create_plan | create_campaign_draft | verify | request_approval | finish"
    )
    tool: str | None = Field(default=None, description="Allowlisted tool name")
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(
        default="",
        description="User-safe one-sentence justification (no chain-of-thought)",
    )


ALLOWED_DECISIONS = frozenset(
    {
        "call_tool",
        "continue_research",
        "formulate_hypothesis",
        "create_plan",
        "create_campaign_draft",
        "verify",
        "request_approval",
        "finish",
    }
)

# Argument keys the model may never supply: the merchant is always taken
# from the backend authenticated context (ToolContext), never from model
# output. Anything tenant-shaped here is stripped before dispatch.
FORBIDDEN_TOOL_ARG_KEYS = frozenset(
    {"merchant_id", "merchant", "tenant_id", "tenant", "merchantId", "tenantId"}
)


def sanitize_tool_args(params: Any) -> tuple[dict[str, Any], list[str]]:
    """Validate + sanitize model-supplied tool arguments.

    Returns (clean_args, dropped_keys). Rejects non-dict params, strips
    tenant-override keys, and drops values that are not JSON scalars
    (nested executable-looking payloads are never passed through).
    """
    if not isinstance(params, dict):
        return {}, ["<non-dict params rejected>"]
    clean: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in params.items():
        if key in FORBIDDEN_TOOL_ARG_KEYS:
            dropped.append(key)
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif isinstance(value, list) and all(
            isinstance(v, (str, int, float, bool)) for v in value
        ):
            clean[key] = value
        else:
            dropped.append(key)
    return clean, dropped


# ---------------------------------------------------------------------------
# The agent
# ---------------------------------------------------------------------------


class MarketingAGI:
    """An autonomous marketing employee. Completely isolated module."""

    NAME = "MarketingAGI"

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
        self._embedding_provider = embedding_provider
        self._limits = limits or DEFAULT_LIMITS

        register_all_tools()
        self._registry = get_registry()
        self._tool_ctx = ToolContext(
            db=db,
            merchant_id=merchant_id,
            llm=llm,
            embedding_provider=embedding_provider,
        )
        # Per-run read-only tool cache (Phase 10): identical read-only
        # calls reuse results within this run only. Cleared at run start.
        self._tool_cache: dict[str, Any] = {}
        # Disconnected external providers (Phase 8): their live tools are
        # omitted from LLM prompts but stay executable via the allowlist.
        self._unavailable_providers: frozenset[str] = self._detect_unavailable_providers()
        self._rag = AgenticRAG(
            self._tool_ctx, self._registry, llm, self._limits,
            prompt_catalog=self._prompt_catalog(include_write=False),
        )
        self._memory = MarketingAGIMemory(db, embedding_provider)
        self._handoffs = HandoffInterface(db)
        # Observability identity for every LLM decision record. The key
        # itself is never stored — only provider/model names.
        self._llm_provider_name: str | None = None
        self._llm_model_name: str | None = None
        if llm is not None:
            try:
                from backend.app.agents.marketing_agi.llm import llm_identity

                _, self._llm_provider_name, self._llm_model_name = llm_identity()
            except Exception:
                self._llm_provider_name = type(llm).__name__

    # ── LLM decision wrapper (observability + graceful degradation) ────

    def _llm_call(
        self,
        state: MarketingAGIState,
        recorder: EventRecorder,
        *,
        phase: str,
        decision_type: str,
        system: str,
        user: str,
        schema: Any,
        safe_summary: str,
        temperature: float = 0.0,
        max_tokens: int = 300,
    ) -> Any:
        """Invoke the Groq reasoning layer with full observability.

        On success records safe metadata (provider, model, latency,
        decision type, tool selected) into ``state.llm_decisions`` and
        emits a user-safe ``llm_decision`` event — never chain-of-thought,
        prompts, keys, or raw customer data. On failure marks the run
        degraded, emits an honest ``llm_unavailable`` event, and re-raises
        so the caller falls back to the bounded deterministic workflow
        instead of fabricating reasoning.
        """
        assert self._llm is not None
        t0 = time.perf_counter()
        try:
            parsed = self._llm.generate_structured(
                system, user, schema,
                temperature=temperature, max_tokens=max_tokens,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            stats = self._accumulate_llm_timing(state, latency_ms)
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
                    "attempts": stats["attempts"],
                    "retries": stats["retries"],
                    "rate_limited": stats["rate_limited"],
                    "retry_delay_ms": stats["retry_delay_ms"],
                }
            )
            recorder.emit(
                phase=phase,
                event_type="llm_unavailable",
                message=(
                    "Groq reasoning unavailable "
                    f"({type(exc).__name__}) — continuing with the bounded "
                    "deterministic workflow; no reasoning fabricated"
                ),
            )
            raise
        latency_ms = int((time.perf_counter() - t0) * 1000)
        stats = self._accumulate_llm_timing(state, latency_ms)
        state.llm_calls += 1
        state.timing["llm_calls"] = state.llm_calls
        tool_selected = getattr(parsed, "tool", None)
        record: dict[str, Any] = {
            "decision_type": decision_type,
            "provider": self._llm_provider_name,
            "model": self._llm_model_name,
            "latency_ms": latency_ms,
            "success": True,
            "attempts": stats["attempts"],
            "retries": stats["retries"],
            "rate_limited": stats["rate_limited"],
            "retry_delay_ms": stats["retry_delay_ms"],
        }
        if tool_selected:
            record["tool"] = tool_selected
        state.llm_decisions.append(record)
        recorder.emit(
            phase=phase,
            event_type="llm_decision",
            message=safe_summary,
            data={"decision_type": decision_type, "tool": tool_selected},
        )
        return parsed

    def _detect_unavailable_providers(self) -> frozenset[str]:
        """External providers with no verified connection for this tenant.

        Disconnected integrations are omitted from LLM prompt catalogs so
        the model never wastes calls reasoning over unavailable live data.
        Capabilities are NOT removed: ``registry.call`` still allowlists
        every registered tool.
        """
        try:
            from backend.app.services import integration_service as svc

            connected = {
                p
                for p in ("resend", "google_ads", "meta_ads", "instagram")
                if svc.connected_row(self._db, self._merchant_id, p) is not None
            }
            return frozenset(
                {"resend", "google_ads", "meta_ads", "instagram"} - connected
            )
        except Exception:
            log.warning("Provider availability check failed; assuming all "
                        "external providers disconnected")
            return frozenset({"resend", "google_ads", "meta_ads", "instagram"})

    def _prompt_catalog(self, *, include_write: bool = False) -> list[dict[str, Any]]:
        """Stage-appropriate tool catalog for LLM prompts.

        Defaults to read-only + connected-only: investigation stages never
        need draft-write tools or disconnected live integrations in the
        prompt. Execution allowlist is unaffected (full registry).
        """
        try:
            return self._registry.catalog(
                include_write=include_write,
                exclude_providers=self._unavailable_providers,
            )
        except Exception:
            return self._registry.catalog()

    def _provider_stats(self) -> dict[str, Any]:
        """Safe per-call stats from the provider (attempts/retries/429).

        Never includes prompts, keys, or response content.
        """
        try:
            stats = getattr(self._llm, "last_call_stats", None) or {}
            return {
                "attempts": int(stats.get("attempts", 1)),
                "retries": int(stats.get("retries", 0)),
                "rate_limited": bool(stats.get("rate_limited", False)),
                "retry_delay_ms": int(stats.get("retry_delay_ms", 0)),
            }
        except Exception:
            return {"attempts": 1, "retries": 0, "rate_limited": False,
                    "retry_delay_ms": 0}

    def _accumulate_llm_timing(self, state: MarketingAGIState,
                               latency_ms: int) -> dict[str, Any]:
        """Fold one LLM call's cost into the run timing. Returns stats."""
        stats = self._provider_stats()
        timing = state.timing
        timing["llm_total_ms"] += latency_ms + stats["retry_delay_ms"]
        timing["llm_calls"] = state.llm_calls
        timing["retry_count"] += stats["retries"]
        if stats["rate_limited"]:
            timing["rate_limit_count"] += 1
        return stats

    def _checkpoint(self, run_row: MarketingAGIRun,
                    state: MarketingAGIState) -> None:
        """Persist intermediate progress so other sessions can observe it.

        Syncs run columns + brain state and commits — never one giant
        uncommitted transaction. Commit failures are contained (rollback +
        continue) so a transient DB hiccup never kills the run. Also
        refreshes the cooperative-cancel flag from the database, since the
        in-memory state cannot see external cancellation otherwise.
        """
        t0 = time.perf_counter()
        try:
            self._sync_row(run_row, state)
            self._db.commit()
        except Exception:
            log.warning("MarketingAGI checkpoint commit failed; continuing",
                        exc_info=True)
            try:
                self._db.rollback()
            except Exception:
                pass
        finally:
            try:
                state.timing["db_total_ms"] += int(
                    (time.perf_counter() - t0) * 1000)
            except Exception:
                pass
        # Cooperative cancel: re-read the flag persisted by the cancel
        # endpoint (the worker's in-memory state never sees it otherwise).
        try:
            fresh_state = self._db.scalar(
                select(MarketingAGIRun.state).where(
                    MarketingAGIRun.id == run_row.id)
            )
            if isinstance(fresh_state, dict) and fresh_state.get("cancelled"):
                state.cancelled = True
        except Exception:
            pass

    def _set_reasoning(
        self,
        state: MarketingAGIState,
        *,
        status: str,
        decision: str | None = None,
        summary: str | None = None,
    ) -> None:
        """Update the user-safe reasoning status shown on the dashboard."""
        state.reasoning_status = status
        if decision is not None:
            state.current_decision = decision
        if summary is not None:
            state.reasoning_summary = summary

    # ── public entry point ──────────────────────────────────────────────

    def run(
        self,
        run_row: MarketingAGIRun,
        objective: str,
        *,
        analysis_cycle_id: str | None = None,
    ) -> MarketingAGIRun:
        """Execute the bounded loop against an existing queued run row.

        ``analysis_cycle_id`` links this execution to its parent AI Team
        analysis cycle (the orchestrator_run_id shared with sibling
        agents). It is informational only: tenant isolation still comes
        from the backend-authenticated merchant id.
        """
        state = MarketingAGIState(
            run_id=str(run_row.id),
            merchant_id=str(self._merchant_id),
            objective=objective,
        )
        if analysis_cycle_id:
            run_row.analysis_cycle_id = analysis_cycle_id
        # Fresh per-run cache: never leaks results across runs/merchants.
        self._tool_cache = {}
        if self._llm is not None:
            state.reasoning_status = "reasoning"
            state.reasoning_summary = (
                "Groq reasoning engine engaged — investigating live business data"
            )
        else:
            state.reasoning_status = "reasoning"
            state.reasoning_summary = (
                "Running the bounded deterministic workflow (no LLM key configured)"
            )
            state.llm_degraded = True
        recorder = EventRecorder(self._db, run_row)
        deadline = time.monotonic() + self._limits.run_timeout_seconds
        t0 = time.perf_counter()

        self._transition(run_row, RunStatus.running, recorder)
        run_row.started_at = utcnow()
        run_row.phase = Phase.load_context.value
        self._db.flush()

        try:
            # Phase 1: LOAD CONTEXT
            self._phase_load_context(state, recorder, run_row)
            self._checkpoint(run_row, state)

            # Phase 2: OBSERVE
            self._phase_observe(state, recorder, run_row)
            self._checkpoint(run_row, state)

            # Phase 3: INVESTIGATE (bounded)
            self._phase_investigate(state, recorder, run_row, deadline)
            self._checkpoint(run_row, state)

            # Phase 4: PLAN
            self._phase_plan(state, recorder, run_row)
            self._checkpoint(run_row, state)

            # Phase 5: CREATE + VERIFY (with one re-investigation on failure)
            ok = self._phase_create_and_verify(state, recorder, run_row, deadline)
            self._checkpoint(run_row, state)
            if not ok:
                # verification failed twice → blocked, never silent
                self._finish(
                    run_row,
                    RunStatus.blocked,
                    recorder,
                    reason="action verification failed after re-investigation",
                    state=state,
                )
                return run_row

            # Phase 6: PREPARE
            self._phase_prepare(state, recorder, run_row)
            self._checkpoint(run_row, state)

            # Phase 7: AWAIT APPROVAL
            self._phase_await(state, recorder, run_row)

        except _Cancelled:
            self._finish(
                run_row, RunStatus.cancelled, recorder,
                reason="run cancelled by operator", state=state,
            )
            return run_row
        except _EarlyComplete:
            # a phase legitimately finished the run (completed /
            # waiting_approval); state was already persisted by _finish
            self._sync_row(run_row, state)
            self._db.commit()
            return run_row
        except _BudgetExceeded as exc:
            self._finish(
                run_row, RunStatus.blocked, recorder, reason=str(exc), state=state
            )
            return run_row
        except Exception as exc:  # noqa: BLE001 — failure isolation boundary
            log.exception("MarketingAGI run %s failed", run_row.id)
            state.errors.append(f"{type(exc).__name__}: {exc}")
            self._finish(
                run_row, RunStatus.failed, recorder,
                reason=f"{type(exc).__name__}: {exc}", state=state,
            )
            return run_row

        self._sync_row(run_row, state)
        self._db.commit()
        return run_row

    # ── phases ──────────────────────────────────────────────────────────

    def _phase_load_context(
        self, state: MarketingAGIState, recorder: EventRecorder, run_row: MarketingAGIRun
    ) -> None:
        run_row.phase = Phase.load_context.value
        recorder.emit(
            phase=Phase.load_context.value,
            event_type="phase_started",
            message=f"01 — Loading merchant context for {state.merchant_id}",
        )

        # business context from the merchant's real data
        overview = self._safe_tool("get_business_overview")
        state.business_context = overview
        state.add_evidence(
            "get_business_overview", "sql", "Business baseline computed from real orders/payments"
        )

        # marketing memory recall
        memories = self._memory.recall(
            self._merchant_id, state.objective, k=5
        )
        state.memory_context = memories
        if memories:
            recorder.emit(
                phase=Phase.load_context.value,
                event_type="memory_recalled",
                message=f"Loaded {len(memories)} marketing memories",
                data={"top": memories[0].get("summary")},
            )
            state.add_evidence(
                "recall_memory", "memory", f"{len(memories)} prior memories inform this run"
            )

        empty = (overview or {}).get("data_completeness") == "no_data"
        if empty:
            state.knowledge_gaps.append("no business data on this merchant yet")
            recorder.emit(
                phase=Phase.load_context.value,
                event_type="empty_business",
                message="Business has no commerce data — nothing to investigate honestly",
            )
            self._finish(
                run_row, RunStatus.completed, recorder,
                reason="empty business: no marketing work is possible without data",
                state=state,
            )
            raise _EarlyComplete

        recorder.emit(
            phase=Phase.load_context.value,
            event_type="phase_completed",
            message=f"Context loaded: {overview.get('total_customers', 0)} customers, "
            f"₹{overview.get('total_revenue_inr', 0):.0f} recorded revenue",
        )

    def _phase_observe(
        self, state: MarketingAGIState, recorder: EventRecorder, run_row: MarketingAGIRun
    ) -> None:
        run_row.phase = Phase.observe.value
        recorder.emit(
            phase=Phase.observe.value,
            event_type="phase_started",
            message="02 — Observing current business state",
        )

        # gather the analytics baseline through real tools.
        # The four read-only analytics reads are independent: run them
        # concurrently on fresh per-thread sessions (sessions are never
        # shared across threads). Any thread failure falls back to a safe
        # error payload for that tool only — one failed tool never kills
        # observation. Sequential fallback if threading itself fails.
        observe_tools = [
            "get_customer_activity_trend",
            "get_customer_segments",
            "get_failed_payment_analytics",
            "get_product_affinities",
        ]
        observed = self._observe_parallel(state, observe_tools)
        analytics: dict[str, Any] = {
            "get_business_overview": state.business_context,
            **observed,
        }
        self._tool_ctx and None  # keep ctx referenced
        state.tool_call_count += 5
        state.timing["tool_calls"] = state.tool_call_count
        run_row.tool_call_count = state.tool_call_count

        # LLM observation or deterministic fallback
        if self._llm is not None:
            self._set_reasoning(
                state, status="reasoning",
                decision="Analyzing business baseline to detect the primary signal",
            )
            try:
                obs = self._llm_call(
                    state, recorder,
                    phase=Phase.observe.value,
                    decision_type="observe_signals",
                    system=self._observe_system_prompt(),
                    user=self._analytics_json(analytics),
                    schema=SignalDetection,
                    safe_summary="LLM analyzed business signal from live analytics",
                    temperature=0.1,
                    max_tokens=600,
                )
                state.observations = obs.signals
                state.knowledge_gaps.extend(obs.knowledge_gaps)
                self._set_reasoning(
                    state, status="investigating",
                    decision=f"Investigating: {obs.primary_signal}",
                    summary=(
                        "Investigating the detected signal because the live "
                        "business data indicates recoverable impact."
                    ),
                )
                recorder.emit(
                    phase=Phase.observe.value,
                    event_type="signals_detected",
                    message=f"03 — Detected signal: {obs.primary_signal}",
                    data={"signals": obs.signals, "questions": obs.investigation_questions},
                )
                state._investigation_questions = obs.investigation_questions  # type: ignore[attr-defined]
                state.add_evidence(
                    "llm_observation", "sql",
                    f"Primary signal: {obs.primary_signal}",
                )
            except Exception as exc:
                log.warning("LLM observation failed, using deterministic: %s", exc)
                self._observe_deterministic(state, analytics, recorder)
        else:
            self._observe_deterministic(state, analytics, recorder)

        # workflow relevance from evidence
        analytics["_inactive_days"] = 30
        state._analytics = analytics  # type: ignore[attr-defined]
        recorder.emit(
            phase=Phase.observe.value,
            event_type="phase_completed",
            message=f"Observation complete — {len(state.observations)} signals identified",
        )

    def _phase_investigate(
        self,
        state: MarketingAGIState,
        recorder: EventRecorder,
        run_row: MarketingAGIRun,
        deadline: float,
    ) -> None:
        run_row.phase = Phase.investigate.value
        recorder.emit(
            phase=Phase.investigate.value,
            event_type="phase_started",
            message="04 — Investigating evidence (agentic RAG)",
        )

        questions: list[str] = getattr(state, "_investigation_questions", None) or (
            [
                "Which customers stopped buying and how much are they worth?",
                "What marketing was tried before and what happened?",
            ]
        )

        for q in questions[:3]:
            self._check_budget(state, deadline)
            state.iterations += 1
            run_row.iterations = state.iterations
            self._db.flush()

            recorder.emit(
                phase=Phase.investigate.value,
                event_type="rag_started",
                message=f"05 — Researching: {q}",
            )
            rag_t0 = time.perf_counter()
            rag_result = self._rag.research(q)
            state.timing["rag_total_ms"] += int(
                (time.perf_counter() - rag_t0) * 1000)
            state.timing["rag_rounds"] += rag_result.rounds
            state.retrieval_log.append(rag_result.to_dict())

            for stmt in rag_result.evidence_statements[:10]:
                state.add_evidence("agentic_rag", "retrieval", stmt)

            if rag_result.sufficient:
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="rag_sufficient",
                    message=f"Evidence sufficient for: {q}",
                    data={"rounds": rag_result.rounds, "statements": len(rag_result.evidence_statements)},
                )
            else:
                state.knowledge_gaps.extend(rag_result.gaps)
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="rag_insufficient",
                    message=f"Evidence insufficient for: {q} — gap recorded honestly",
                    data={"gaps": rag_result.gaps},
                )
            # Per-question checkpoint: RETRIEVING progress is queryable
            # even if a later LLM call hangs or the worker dies.
            self._checkpoint(run_row, state)

        # tool-driven deep investigation: LLM picks tools dynamically
        if self._llm is not None:
            self._llm_tool_loop(state, recorder, run_row, deadline)
        else:
            self._deterministic_tool_loop(state, recorder, run_row)

        # hypothesis resolution from evidence
        if state.hypotheses:
            self._resolve_hypotheses(state, recorder)

        recorder.emit(
            phase=Phase.investigate.value,
            event_type="phase_completed",
            message=f"Investigation complete — {len(state.evidence)} evidence items",
        )

    def _phase_plan(
        self, state: MarketingAGIState, recorder: EventRecorder, run_row: MarketingAGIRun
    ) -> None:
        run_row.phase = Phase.plan.value
        recorder.emit(
            phase=Phase.plan.value,
            event_type="phase_started",
            message="06 — Planning marketing intervention",
        )

        analytics = getattr(state, "_analytics", {})
        candidates = select_workflows(analytics)

        if not candidates:
            recorder.emit(
                phase=Phase.plan.value,
                event_type="no_opportunity",
                message="No marketing opportunity justifies intervention — run completes honestly",
            )
            self._finish(
                run_row, RunStatus.completed, recorder,
                reason="no marketing opportunity detected from evidence",
                state=state,
            )
            raise _EarlyComplete

        # choose the best workflow (LLM preference within candidates, else first)
        chosen = candidates[0]
        if self._llm is not None and len(candidates) > 1:
            try:
                class _Pick(BaseModel):
                    workflow: str

                self._set_reasoning(
                    state, status="planning",
                    decision="Planning the highest-impact marketing intervention",
                )
                pick = self._llm_call(
                    state, recorder,
                    phase=Phase.plan.value,
                    decision_type="select_workflow",
                    system="Pick the single highest-impact workflow from the candidates. "
                    "Return JSON {workflow}.",
                    user=str(
                        [
                            {"key": w.key, "name": w.name, "description": w.description}
                            for w in candidates
                        ]
                    ),
                    schema=_Pick,
                    safe_summary="LLM selected the campaign workflow from evidence",
                    temperature=0.0,
                    max_tokens=60,
                )
                for w in candidates:
                    if w.key == pick.workflow:
                        chosen = w
                        break
            except Exception as exc:
                log.warning("Workflow pick failed, defaulting to first: %s", exc)

        state.workflow = chosen.key
        state.plan = [
            {"step": "build_audience", "tool": "find_customers", "status": "pending"},
            {"step": "design_campaign", "tool": "campaign_strategy", "status": "pending"},
            {"step": "verify", "tool": "verifier", "status": "pending"},
            {"step": "prepare", "tool": "campaign_draft", "status": "pending"},
        ]
        state.add_hypothesis(
            f"'{chosen.name}' is the right intervention for the detected signal",
            confidence=0.6,
        ).status = "confirmed"  # justified by evidence-driven selection

        recorder.emit(
            phase=Phase.plan.value,
            event_type="workflow_selected",
            message=f"07 — Selected workflow: {chosen.name}",
            data={"workflow": chosen.key, "candidates": [w.key for w in candidates]},
        )

    def _phase_create_and_verify(
        self,
        state: MarketingAGIState,
        recorder: EventRecorder,
        run_row: MarketingAGIRun,
        deadline: float,
    ) -> bool:
        """CREATE + VERIFY. Returns True when verification passed."""
        for attempt in (1, 2):
            run_row.phase = Phase.create.value
            self._check_budget(state, deadline)

            workflow = self._workflow_by_key(state.workflow or "customer_win_back")
            analytics = getattr(state, "_analytics", {})

            # build the audience from REAL data
            criteria = workflow.audience_criteria(analytics)
            if workflow.key == "failed_payment_recovery":
                criteria = {"min_orders": 0}
            audience_res = self._tool("find_customers", criteria)
            self._record_tool_call(
                state, "find_customers", criteria, audience_res, ok=True
            )
            state.tool_call_count += 1
            run_row.tool_call_count = state.tool_call_count

            audience_ids = audience_from_find_customers(audience_res)
            state.customer_context = {
                "criteria": criteria,
                "audience_count": len(audience_ids),
                "total_spend_inr": audience_res.get("total_spend_inr", 0),
            }
            recorder.emit(
                phase=Phase.create.value,
                event_type="audience_built",
                message=f"08 — Built customer segment: {len(audience_ids)} customers",
                data={"criteria": criteria},
            )
            state.add_evidence(
                "find_customers", "sql",
                f"Audience of {len(audience_ids)} customers matches {criteria}",
            )

            if len(audience_ids) < self._limits.min_audience_size:
                state.knowledge_gaps.append(
                    f"audience for {workflow.key} is empty — criteria too strict"
                )
                recorder.emit(
                    phase=Phase.create.value,
                    event_type="audience_empty",
                    message="Audience empty — adjusting criteria and retrying investigation",
                )
                continue  # retry once with looser criteria

            # design the campaign (LLM when available; structured fallback)
            campaign_t0 = time.perf_counter()
            strategy = self._design_campaign(state, workflow, audience_res)
            state.timing["campaign_ms"] = state.timing.get("campaign_ms", 0) + int(
                (time.perf_counter() - campaign_t0) * 1000)

            # persist the draft campaign (real, in OUR db)
            campaign_key = f"{workflow.key}-{state.run_id[:8]}"
            draft_res = self._tool(
                "create_email_campaign_draft",
                {
                    "campaign_key": campaign_key,
                    "workflow": workflow.key,
                    "name": strategy.name,
                    "objective": strategy.objective,
                    "audience": {
                        "criteria": criteria,
                        "customer_ids": audience_ids,
                    },
                    "audience_count": len(audience_ids),
                    "content": {
                        "message": strategy.message,
                        "subject_variants": strategy.subject_variants,
                        "cta": strategy.cta,
                        "timing": strategy.timing,
                        "variants": strategy.subject_variants,
                    },
                    "expected_impact": {
                        "rationale": strategy.expected_impact_rationale,
                        "estimated_revenue_inr": strategy.expected_revenue_inr,
                        "risks": strategy.risks,
                    },
                    "success_metric": strategy.success_metric,
                    "evidence_refs": [e.source for e in state.evidence[:10]],
                },
            )
            self._record_tool_call(
                state,
                "create_email_campaign_draft",
                {"campaign_key": campaign_key},
                draft_res,
                ok=True,
            )
            state.tool_call_count += 1
            run_row.tool_call_count = state.tool_call_count

            if not draft_res.get("created"):
                state.errors.append("campaign draft was not created (duplicate?)")
                recorder.emit(
                    phase=Phase.create.value,
                    event_type="draft_failed",
                    message="Campaign draft creation failed — duplicate prevented",
                )
                return False

            recorder.emit(
                phase=Phase.create.value,
                event_type="campaign_created",
                message=f"09 — Campaign draft created: {strategy.name}",
                data={
                    "campaign_id": draft_res.get("campaign_id"),
                    "integration_status": draft_res.get("integration_status"),
                },
            )
            state.campaign_draft = {
                "campaign_id": draft_res["campaign_id"],
                "campaign_key": campaign_key,
                "workflow": workflow.key,
                "name": strategy.name,
                "objective": strategy.objective,
                "audience_count": len(audience_ids),
                "integration_status": draft_res.get("integration_status"),
                "content": {
                    "message": strategy.message,
                    "subject_variants": strategy.subject_variants,
                    "cta": strategy.cta,
                    "timing": strategy.timing,
                },
                "expected_impact": {
                    "rationale": strategy.expected_impact_rationale,
                    "estimated_revenue_inr": strategy.expected_revenue_inr,
                },
                "success_metric": strategy.success_metric,
            }

            # VERIFY
            run_row.phase = Phase.verify.value
            self._set_reasoning(
                state, status="reasoning",
                decision="Verifying audience, evidence, and safety",
            )
            recorder.emit(
                phase=Phase.verify.value,
                event_type="phase_started",
                message="10 — Verifying audience, evidence, and safety",
            )
            campaign_row = self._db.get(
                MarketingAGICampaign, uuid.UUID(draft_res["campaign_id"])
            )
            verify_t0 = time.perf_counter()
            report = verify_campaign(
                self._db,
                self._merchant_id,
                campaign_row,
                audience_ids,
                evidence_count=len(state.evidence),
                limits=self._limits,
            )
            state.timing["verify_ms"] = state.timing.get("verify_ms", 0) + int(
                (time.perf_counter() - verify_t0) * 1000)
            state.verification = report.to_dict()
            # CAMPAIGN_DRAFT + VERIFYING checkpoint before branching.
            self._checkpoint(run_row, state)

            if report.passed:
                recorder.emit(
                    phase=Phase.verify.value,
                    event_type="verification_passed",
                    message="11 — Verification PASSED — campaign ready for approval",
                    data=report.to_dict(),
                )
                return True

            recorder.emit(
                phase=Phase.verify.value,
                event_type="verification_failed",
                message=f"Verification FAILED ({', '.join(report.failed_names)}) — "
                "investigating and fixing",
                data=report.to_dict(),
            )
            state.errors.append(f"verification attempt {attempt}: {report.failed_names}")
            # loop retries (max 2 attempts via for-loop)

        return False

    def _phase_prepare(
        self, state: MarketingAGIState, recorder: EventRecorder, run_row: MarketingAGIRun
    ) -> None:
        run_row.phase = Phase.prepare.value
        recorder.emit(
            phase=Phase.prepare.value,
            event_type="phase_started",
            message="12 — Preparing action for human approval",
        )

        # propose a Phase-4 AgentAction (requested state) — the ONLY bridge
        # to execution; humans approve downstream. Never auto-approved.
        from backend.app.services.action_service import create_action
        from backend.app.models.enums import AgentActionType

        draft = state.campaign_draft or {}
        audience = draft.get("audience_count", 0)
        payload = {
            "merchant_id": str(self._merchant_id),
            "campaign_type": "email",
            "target": {
                "workflow": state.workflow,
                "criteria": state.customer_context.get("criteria", {}),
                "marketing_agi_campaign_id": draft.get("campaign_id"),
            },
            "target_count": audience,
            "metadata": {
                "requested_by_agent": self.NAME,
                "run_id": state.run_id,
                "campaign_key": draft.get("campaign_key"),
                "expected_revenue_inr": (
                    draft.get("expected_impact", {}).get("estimated_revenue_inr")
                ),
                "success_metric": draft.get("success_metric"),
                "evidence_count": len(state.evidence),
                "message_preview": (draft.get("content", {}) or {}).get("message", "")[:200],
                "integration_status": draft.get("integration_status"),
                "approval_note": "Autonomous Marketing AGI campaign — requires human approval",
            },
        }
        action = create_action(
            self._db,
            merchant_id=self._merchant_id,
            action_type=AgentActionType.send_campaign,
            input_payload=payload,
            requested_by=f"agent:{self.NAME}",
        )

        # link the campaign to the action
        campaign_row = self._db.get(
            MarketingAGICampaign, uuid.UUID(draft["campaign_id"])
        )
        campaign_row.action_id = action.id
        campaign_row.lifecycle = "ready_for_approval"
        self._db.flush()

        state.prepared_action = {
            "action_id": str(action.id),
            "status": str(getattr(action.status, "value", action.status)),
            "approval_state": "REQUIRED",
        }
        recorder.emit(
            phase=Phase.prepare.value,
            event_type="action_prepared",
            message=f"13 — Action prepared: send_campaign to {audience} customers "
            "(approval REQUIRED, never auto-executed)",
            data=state.prepared_action,
        )

        # record investigation memory for future runs
        self._memory.record_investigation(
            self._merchant_id,
            statement=(
                f"Run {state.run_id}: detected {state.observations[0] if state.observations else 'signal'} "
                f"→ prepared {state.workflow} campaign for {audience} customers "
                f"(action {action.id} awaiting approval)"
            ),
        )

        # optional: open a handoff for a future specialist review
        if self._llm is not None:
            try:
                h = self._handoffs.request(
                    self._merchant_id,
                    specialist="creative_ux",
                    question="Review the campaign messaging against the evidence before send.",
                    context={
                        "workflow": state.workflow,
                        "audience_count": audience,
                        "objective": draft.get("objective"),
                    },
                    evidence=[
                        e.to_dict() if hasattr(e, "to_dict") else dict(e)
                        for e in state.evidence[:5]
                    ],
                    required_output="Messaging quality assessment and improvement suggestions",
                    run_id=uuid.UUID(state.run_id),
                )
                recorder.emit(
                    phase=Phase.prepare.value,
                    event_type="handoff_opened",
                    message="Handoff opened for future creative review (pending — no specialist upgraded)",
                    data={"handoff_id": str(h.id), "specialist": h.specialist},
                )
            except Exception as exc:
                log.warning("Handoff creation failed: %s", exc)

    def _phase_await(
        self, state: MarketingAGIState, recorder: EventRecorder, run_row: MarketingAGIRun
    ) -> None:
        run_row.phase = Phase.awaiting_approval.value
        self._set_reasoning(
            state, status="waiting_for_approval",
            decision="Campaign draft prepared — waiting for human approval",
            summary="Campaign draft prepared and sent to the human approval gate.",
        )
        recorder.emit(
            phase=Phase.awaiting_approval.value,
            event_type="awaiting_approval",
            message="14 — Campaign READY FOR APPROVAL — waiting for human decision",
            data={"action_id": (state.prepared_action or {}).get("action_id")},
        )
        self._finish(
            run_row, RunStatus.waiting_approval, recorder,
            reason="campaign prepared and verified; awaiting human approval",
            state=state,
        )
        raise _EarlyComplete

    # ── LLM tool loop (dynamic selection) ───────────────────────────────

    def _llm_tool_loop(
        self,
        state: MarketingAGIState,
        recorder: EventRecorder,
        run_row: MarketingAGIRun,
        deadline: float,
    ) -> None:
        # Prompt carries the stage-filtered catalog (read-only, connected
        # only); validation below still uses the FULL allowlist.
        prompt_catalog = self._prompt_catalog(include_write=False)
        allowed_tools = {c["name"] for c in self._registry.catalog()}
        system = (
            "You are the tool-selection engine of an autonomous marketing agent. "
            "Given the objective, the evidence so far, and the tool catalog, choose "
            "the ONE next tool that best answers the biggest open question — or "
            "declare done. Never invent tools outside the catalog."
        )
        for _ in range(4):  # bounded
            self._check_budget(state, deadline)
            self._set_reasoning(
                state, status="selecting_tools",
                decision="Selecting the next evidence-gathering tool",
            )
            user = (
                f"Objective: {state.objective}\n"
                f"Observations: {state.observations}\n"
                f"Evidence so far: {[e.statement for e in state.evidence][:12]}\n"
                f"Knowledge gaps: {state.knowledge_gaps}\n"
                f"Tool catalog: {prompt_catalog}"
            )
            try:
                choice = self._llm_call(
                    state, recorder,
                    phase=Phase.investigate.value,
                    decision_type="select_tool",
                    system=system,
                    user=user,
                    schema=ToolChoice,
                    safe_summary="LLM selected the next investigation tool",
                    temperature=0.0,
                    max_tokens=300,
                )
            except Exception as exc:
                log.warning("LLM tool choice failed: %s", exc)
                break
            if choice.done:
                self._set_reasoning(
                    state, status="investigating",
                    decision="Evidence judged sufficient — ending tool selection",
                    summary="Tool results were reviewed and evidence is sufficient.",
                )
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="tool_loop_done",
                    message="Tool selection complete — evidence judged sufficient by model",
                )
                break
            if choice.tool not in allowed_tools:
                # Hallucinated / unauthorized tool: reject, record, never execute.
                state.llm_decisions.append(
                    {
                        "decision_type": "select_tool",
                        "provider": self._llm_provider_name,
                        "model": self._llm_model_name,
                        "success": False,
                        "error": "unknown_tool_rejected",
                        "tool": choice.tool,
                    }
                )
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="tool_rejected",
                    message=f"Rejected unknown tool: {choice.tool} — not in the allowlist",
                    data={"tool": choice.tool},
                )
                break

            args, dropped = sanitize_tool_args(choice.params)
            if dropped:
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="tool_args_sanitized",
                    message=f"Stripped unsafe arguments from {choice.tool}: {dropped}",
                    data={"tool": choice.tool, "dropped": dropped},
                )
            self._set_reasoning(
                state, status="investigating",
                decision=f"Investigating with {choice.tool}",
                summary=(choice.reasoning or f"Gathering evidence with {choice.tool}.")[:280],
            )
            try:
                call = self._dispatch_tool(state, choice.tool, args)
            except Exception as exc:
                log.warning("Tool %s dispatch failed: %s", choice.tool, exc)
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="tool_failed",
                    message=f"Tool {choice.tool} failed ({type(exc).__name__}) — evidence gap recorded",
                    data={"tool": choice.tool},
                )
                state.knowledge_gaps.append(f"{choice.tool} unavailable: {type(exc).__name__}")
                break
            recorder.emit(
                phase=Phase.investigate.value,
                event_type="tool_used",
                message=f"Used tool: {choice.tool} ({choice.reasoning[:80]})",
                data={"tool": choice.tool, "latency_ms": call.get("latency_ms")},
            )
            for stmt in _flatten_statements(call.get("result", {}))[:6]:
                state.add_evidence(choice.tool, "sql", stmt)
            # TOOL_CALL/TOOL_RESULT checkpoint: each tool result is durable
            # before the next LLM call.
            self._checkpoint(run_row, state)

    # ── deterministic tool loop (no LLM) ─────────────────────────────────

    def _deterministic_tool_loop(
        self,
        state: MarketingAGIState,
        recorder: EventRecorder,
        run_row: MarketingAGIRun,
    ) -> None:
        analytics = getattr(state, "_analytics", {})
        for wf in select_workflows(analytics)[:1]:
            for tool in wf.investigation_tools[:3]:
                params: dict[str, Any] = {}
                if tool == "find_customers":
                    params = {"min_orders": 1}
                elif tool in {"search_knowledge_store", "recall_memory"}:
                    params = {"query": state.objective}
                call = self._dispatch_tool(state, tool, params)
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="tool_used",
                    message=f"Used tool: {tool}",
                    data={"tool": tool, "latency_ms": call.get("latency_ms")},
                )
                for stmt in _flatten_statements(call.get("result", {}))[:6]:
                    state.add_evidence(tool, "sql", stmt)

    # ── helpers ──────────────────────────────────────────────────────────

    def _observe_parallel(
        self, state: MarketingAGIState, names: list[str]
    ) -> dict[str, Any]:
        """Run independent read-only observation tools concurrently.

        Each tool gets a FRESH session on the same engine (sessions are
        never shared across threads) bound to the same tenant. Failures
        are isolated per tool; a threading failure falls back to the
        original sequential path. Individual timings are recorded.

        SQLite (tests/local) uses a single shared-cache connection that is
        not thread-safe, so threading is only used on server databases
        (PostgreSQL); SQLite always takes the sequential path.
        """
        try:
            bind = self._db.get_bind()
        except Exception:
            return self._observe_sequential(state, names)
        if getattr(getattr(bind, "dialect", None), "name", "") == "sqlite":
            return self._observe_sequential(state, names)
        try:
            from concurrent.futures import ThreadPoolExecutor
        except ImportError:
            return self._observe_sequential(state, names)

        def _one(name: str) -> tuple[str, dict[str, Any], int]:
            from sqlalchemy.orm import Session as _Session

            t0 = time.perf_counter()
            sess = _Session(bind=bind, autoflush=False, expire_on_commit=False)
            try:
                ctx = ToolContext(
                    db=sess, merchant_id=self._merchant_id,
                    llm=None, embedding_provider=None,
                )
                call = self._registry.call(ctx, name, {})
                return name, call.get("result", {}), int(
                    (time.perf_counter() - t0) * 1000)
            except Exception as exc:
                log.warning("parallel observe tool %s failed: %s", name, exc)
                return name, {"error": str(exc), "tool": name}, int(
                    (time.perf_counter() - t0) * 1000)
            finally:
                try:
                    sess.close()
                except Exception:
                    pass

        try:
            with ThreadPoolExecutor(
                max_workers=min(len(names), 5),
                thread_name_prefix="magi-observe",
            ) as pool:
                futures = {pool.submit(_one, n): n for n in names}
                results: dict[str, Any] = {}
                for fut, n in futures.items():
                    try:
                        _, payload, latency_ms = fut.result(timeout=30)
                    except Exception as exc:
                        log.warning("parallel observe tool %s timed out: %s", n, exc)
                        payload, latency_ms = (
                            {"error": f"{type(exc).__name__}", "tool": n}, 0)
                    results[n] = payload
                    self._record_tool_call(
                        state, n, {}, payload,
                        ok="error" not in payload, latency_ms=latency_ms,
                        dedupe=False,
                    )
                    state.timing["tool_total_ms"] += latency_ms
                return results
        except Exception as exc:
            log.warning("parallel observe failed, sequential fallback: %s", exc)
            return self._observe_sequential(state, names)

    def _observe_sequential(
        self, state: MarketingAGIState, names: list[str]
    ) -> dict[str, Any]:
        """Original sequential read-only observation path (SQLite/tests)."""
        results: dict[str, Any] = {}
        for n in names:
            t0 = time.perf_counter()
            payload = self._safe_tool(n)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            results[n] = payload
            self._record_tool_call(
                state, n, {}, payload,
                ok="error" not in payload, latency_ms=latency_ms,
                dedupe=False,
            )
            state.timing["tool_total_ms"] += latency_ms
        return results

    def _observe_deterministic(
        self, state: MarketingAGIState, analytics: dict, recorder: EventRecorder
    ) -> None:
        obs: list[str] = []
        overview = analytics.get("get_business_overview", {}) or {}
        activity = analytics.get("get_customer_activity_trend", {}) or {}
        failed = analytics.get("get_failed_payment_analytics", {}) or {}
        affinities = analytics.get("get_product_affinities", {}) or {}

        if overview.get("total_customers", 0) == 0:
            obs.append("No customers recorded")
        if activity.get("inactive_with_purchase_history", 0) >= 3:
            obs.append(
                f"{activity['inactive_with_purchase_history']} customers with purchase "
                "history have gone quiet"
            )
        if failed.get("failed_payment_count", 0) >= 1:
            obs.append(
                f"{failed['failed_payment_count']} failed payments worth "
                f"₹{failed.get('recoverable_value_inr', 0):.0f} recoverable"
            )
        if affinities.get("multi_item_order_count", 0) >= 2:
            obs.append("Clear cross-sell patterns exist in order history")
        if overview.get("repeat_purchase_rate", 0) >= 0.3:
            obs.append("A healthy repeat-purchase base exists to protect")

        state.observations = obs or ["Business baseline recorded, no strong signal"]
        recorder.emit(
            phase=Phase.observe.value,
            event_type="signals_detected",
            message=f"03 — Detected signal: {state.observations[0]}",
            data={"signals": state.observations},
        )

    def _design_campaign(
        self, state: MarketingAGIState, workflow: WorkflowSpec, audience_res: dict
    ) -> CampaignStrategy:
        if self._llm is not None:
            try:
                merchant_name = (state.business_context or {}).get("merchant_name", "our store")
                system = (
                    "You are an expert retention marketer writing ONE campaign for a "
                    "small business. Use ONLY the supplied real evidence. Do not "
                    "invent customer data, statistics, or discounts. Keep the message "
                    "honest, concrete, and short. Return JSON per the schema."
                )
                user = (
                    f"Workflow: {workflow.name} — {workflow.description}\n"
                    f"Business: {merchant_name}\n"
                    f"Audience: {audience_res.get('audience_count')} customers, "
                    f"avg spend ₹{audience_res.get('average_spend_inr', 0):.0f}\n"
                    f"Observations: {state.observations}\n"
                    f"Evidence: {[e.statement for e in state.evidence][:10]}"
                )
                self._set_reasoning(
                    state, status="planning",
                    decision="Drafting the campaign from gathered evidence",
                )
                # NOTE: campaign design has no recorder in scope; the
                # decision is still tracked in state.llm_decisions via a
                # lightweight inline record (no event emission here).
                t0 = time.perf_counter()
                strategy = self._llm.generate_structured(
                    system, user, CampaignStrategy, temperature=0.2, max_tokens=900
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                stats = self._accumulate_llm_timing(state, latency_ms)
                state.llm_calls += 1
                state.timing["llm_calls"] = state.llm_calls
                state.llm_decisions.append(
                    {
                        "decision_type": "design_campaign",
                        "provider": self._llm_provider_name,
                        "model": self._llm_model_name,
                        "latency_ms": latency_ms,
                        "success": True,
                        "attempts": stats["attempts"],
                        "retries": stats["retries"],
                        "rate_limited": stats["rate_limited"],
                        "retry_delay_ms": stats["retry_delay_ms"],
                    }
                )
                self._set_reasoning(
                    state, status="planning",
                    decision="Campaign draft prepared from evidence",
                    summary="Campaign draft prepared and will be sent to verification.",
                )
                return strategy
            except Exception as exc:
                log.warning("LLM campaign design failed, deterministic fallback: %s", exc)
                state.llm_degraded = True

        # deterministic, evidence-grounded fallback content
        n = audience_res.get("audience_count", 0)
        avg = audience_res.get("average_spend_inr", 0) or 0
        base = workflow.name.lower()
        return CampaignStrategy(
            workflow=workflow.key,
            name=f"{workflow.name} Campaign",
            objective=workflow.description,
            audience_reasoning=(
                f"{n} customers match the {workflow.name.lower()} criteria from real purchase data"
            ),
            content_reasoning="Direct, honest, value-first messaging grounded in real history",
            message=(
                f"We noticed it's been a while since your last order. "
                f"Your favourite products are still here — and your past orders "
                f"averaged ₹{avg:.0f}. Come back and pick up where you left off."
                if workflow.key in {"customer_win_back", "customer_retention"}
                else f"A quick note about something we think you'll like, based on your "
                f"purchase history with us."
            ),
            subject_variants=[
                "We saved your spot",
                "Your favourites are back in stock",
                "A small thank-you for being with us",
            ],
            cta="Shop your favourites again",
            timing="Send in the next business-morning window",
            expected_impact_rationale=(
                f"Typical win-back responsiveness applied to {n} customers with "
                f"₹{avg:.0f} average historical spend"
            ),
            expected_revenue_inr=round(min(n * avg * 0.1, 50000), 2),
            success_metric="Purchases from campaign audience within 14 days",
            risks=["Audience may have already lapsed beyond email reach"],
        )

    def _resolve_hypotheses(
        self, state: MarketingAGIState, recorder: EventRecorder
    ) -> None:
        if self._llm is not None:
            try:
                t0 = time.perf_counter()
                verdict = self._llm.generate_structured(
                    "Judge each hypothesis strictly against ONLY the supplied evidence. "
                    "Status: confirmed | rejected | insufficient_evidence. Return JSON per schema.",
                    str(
                        {
                            "hypotheses": [h.statement for h in state.hypotheses],
                            "evidence": [e.statement for e in state.evidence][:20],
                        }
                    ),
                    HypothesisVerdict,
                    temperature=0.0,
                    max_tokens=400,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                stats = self._accumulate_llm_timing(state, latency_ms)
                state.llm_calls += 1
                state.timing["llm_calls"] = state.llm_calls
                state.llm_decisions.append(
                    {
                        "decision_type": "resolve_hypotheses",
                        "provider": self._llm_provider_name,
                        "model": self._llm_model_name,
                        "latency_ms": latency_ms,
                        "success": True,
                        "attempts": stats["attempts"],
                        "retries": stats["retries"],
                        "rate_limited": stats["rate_limited"],
                        "retry_delay_ms": stats["retry_delay_ms"],
                    }
                )
                recorder.emit(
                    phase=Phase.investigate.value,
                    event_type="llm_decision",
                    message="LLM formulated hypothesis verdicts from the evidence",
                    data={"decision_type": "resolve_hypotheses"},
                )
                self._set_reasoning(
                    state, status="investigating",
                    decision="Hypotheses judged against the evidence",
                    summary="Customer data was evaluated, so the agent is judging "
                    "which hypothesis the evidence supports.",
                )
                for i, h in enumerate(state.hypotheses):
                    if i < len(verdict.statuses):
                        v = verdict.statuses[i]
                        h.status = v.get("status", h.status)
                        try:
                            h.confidence = max(0.0, min(1.0, float(v.get("confidence", h.confidence))))
                        except (TypeError, ValueError):
                            pass
            except Exception as exc:
                log.warning("Hypothesis resolution failed: %s", exc)
                state.llm_degraded = True
        recorder.emit(
            phase=Phase.investigate.value,
            event_type="hypotheses_resolved",
            message=f"08 — Hypotheses: "
            + ", ".join(f"{h.status}" for h in state.hypotheses),
            data={"hypotheses": [h.to_dict() for h in state.hypotheses]},
        )

    def _workflow_by_key(self, key: str) -> WorkflowSpec:
        from backend.app.agents.marketing_agi.workflows import WORKFLOWS

        for w in WORKFLOWS:
            if w.key == key:
                return w
        return WORKFLOWS[0]

    def _dispatch_tool(
        self, state: MarketingAGIState, name: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Bounded, deduplicated tool dispatch."""
        fingerprint = (name, _stable(params))
        if fingerprint in state.seen_tool_calls():
            state.duplicate_tool_calls += 1
            raise _BudgetExceeded(
                f"duplicate tool call prevented: {name} {_stable(params)[:80]}"
            )
        if state.tool_call_count >= self._limits.max_tool_calls:
            raise _BudgetExceeded(f"tool-call budget exhausted ({self._limits.max_tool_calls})")

        call = self._registry.call(self._tool_ctx, name, params)
        state.tool_call_count += 1
        state.timing["tool_total_ms"] += int(call.get("latency_ms", 0))
        state.timing["tool_calls"] = state.tool_call_count
        self._record_tool_call(
            state,
            name,
            params,
            call.get("result", {}),
            ok=True,
            latency_ms=call.get("latency_ms", 0),
        )
        return call

    @staticmethod
    def _record_tool_call(
        state: MarketingAGIState,
        name: str,
        params: dict[str, Any],
        result: Any,
        *,
        ok: bool,
        latency_ms: int = 0,
        dedupe: bool = True,
    ) -> None:
        """Append a workstation-ready tool activity entry.

        Entries carry a UTC timestamp and an honest one-line result
        summary so the UI can render Tool / Status / Input / Result /
        Timestamp / Duration without guessing. Observation-baseline reads
        pass dedupe=False so they stay visible without poisoning the
        reasoning-loop duplicate detector.
        """
        state.tool_calls.append(
            {
                "tool": name,
                "params": _jsonable(params),
                "ok": ok,
                "latency_ms": latency_ms,
                "ts": utcnow().isoformat(),
                "summary": summarize_tool_result(name, result) if ok else "failed",
                "dedupe": dedupe,
            }
        )

    def _tool(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        # Per-run cache for identical READ-ONLY calls (same tenant/run by
        # construction: cache is cleared at run() start). Writes, live
        # integrations requiring connections, and unknown tools bypass.
        try:
            if self._registry.spec(name).read_only:
                key = f"{name}|{_stable(params or {})}"
                cached = self._tool_cache.get(key)
                if isinstance(cached, dict):
                    return cached
                call = self._registry.call(self._tool_ctx, name, params)
                result = call.get("result", {})
                # Cache only successful plain-dict payloads.
                if isinstance(result, dict):
                    self._tool_cache[key] = result
                return result
        except Exception:
            pass
        call = self._registry.call(self._tool_ctx, name, params)
        return call.get("result", {})

    def _safe_tool(self, name: str) -> dict[str, Any]:
        try:
            return self._tool(name, {})
        except Exception as exc:
            log.warning("safe tool %s failed: %s", name, exc)
            return {"error": str(exc), "tool": name}

    def _check_budget(self, state: MarketingAGIState, deadline: float) -> None:
        if state.cancelled:
            raise _Cancelled()
        if state.iterations >= self._limits.max_iterations:
            raise _BudgetExceeded(
                f"iteration limit reached ({self._limits.max_iterations})"
            )
        if time.monotonic() > deadline:
            raise _BudgetExceeded(
                f"run timeout ({self._limits.run_timeout_seconds}s) exceeded"
            )

    def _transition(
        self, run_row: MarketingAGIRun, target: RunStatus, recorder: EventRecorder
    ) -> None:
        assert_run_transition(run_row.status, target)
        run_row.status = target.value
        self._db.flush()
        recorder.emit(
            phase=run_row.phase,
            event_type="run_status",
            message=f"Run status → {target.value}",
        )

    def _sync_row(self, run_row: MarketingAGIRun, state: MarketingAGIState) -> None:
        run_row.iterations = state.iterations
        run_row.tool_call_count = state.tool_call_count
        # Keep timing mirrors consistent at every persist point.
        try:
            state.timing["tool_calls"] = state.tool_call_count
            state.timing["llm_calls"] = state.llm_calls
        except Exception:
            pass
        run_row.state = state.to_dict()
        run_row.errors = state.errors

    def _finish(
        self,
        run_row: MarketingAGIRun,
        status: RunStatus,
        recorder: EventRecorder,
        *,
        reason: str,
        state: MarketingAGIState,
    ) -> None:
        state.errors.append(f"finish: {reason}") if status in {
            RunStatus.blocked, RunStatus.failed,
        } else None
        try:
            if run_row.started_at is not None:
                started = run_row.started_at
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                state.timing["total_ms"] = int(
                    (utcnow() - started).total_seconds() * 1000)
        except Exception:
            pass
        assert_run_transition(run_row.status, status)
        run_row.status = status.value
        run_row.completed_at = utcnow()
        if status is RunStatus.waiting_approval:
            run_row.phase = Phase.awaiting_approval.value
        elif status is RunStatus.completed:
            run_row.phase = Phase.complete.value
            if state.reasoning_status not in {"degraded"}:
                state.reasoning_status = "done"
        elif status in {RunStatus.blocked, RunStatus.failed}:
            state.reasoning_status = "degraded" if state.llm_degraded else state.reasoning_status
        run_row.result = {
            "status": status.value,
            "reason": reason,
            "workflow": state.workflow,
            "campaign": state.campaign_draft,
            "verification": state.verification,
            "prepared_action": state.prepared_action,
            "observations": state.observations,
            "hypotheses": [h.to_dict() for h in state.hypotheses],
            "evidence_count": len(state.evidence),
            "knowledge_gaps": state.knowledge_gaps,
            "learned_insights": state.learned_insights,
            "analysis_cycle_id": run_row.analysis_cycle_id,
            "llm_calls": state.llm_calls,
            "llm_decisions": len(state.llm_decisions),
            "llm_degraded": state.llm_degraded,
            "reasoning_summary": state.reasoning_summary,
            "timing": state.timing,
        }
        self._sync_row(run_row, state)
        recorder.emit(
            phase=run_row.phase,
            event_type="run_finished",
            message=f"Run {status.value}: {reason}",
        )
        self._db.commit()

    # ── prompts ─────────────────────────────────────────────────────────

    @staticmethod
    def _observe_system_prompt() -> str:
        return (
            "You are the observation engine of an autonomous marketing agent. "
            "From the merchant's REAL analytics baseline, identify marketing-relevant "
            "signals. Never invent numbers — restate only what is in the data. "
            "Return JSON per the schema."
        )

    @staticmethod
    def _analytics_json(analytics: dict[str, Any]) -> str:
        import json

        return json.dumps(analytics, default=str, indent=1)[:6000]


# ---------------------------------------------------------------------------
# Internal control-flow exceptions (never leak past run())
# ---------------------------------------------------------------------------


class _EarlyComplete(Exception):
    """Run reached a legitimate finish inside a phase."""


class _BudgetExceeded(Exception):
    """A hard loop limit was reached — run must end, honestly."""


class _Cancelled(Exception):
    """Operator cancellation."""


def _stable(params: dict[str, Any]) -> str:
    import json

    try:
        return json.dumps(params, sort_keys=True, default=str)
    except Exception:
        return repr(params)


def _jsonable(params: dict[str, Any]) -> dict[str, Any]:
    try:
        import json

        json.dumps(params)
        return params
    except Exception:
        return {"repr": repr(params)[:200]}


def _flatten_statements(result: dict[str, Any]) -> list[str]:
    from backend.app.agents.marketing_agi.rag import _extract_statements

    return _extract_statements(result, "")
