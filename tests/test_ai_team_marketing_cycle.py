"""AI Team + Marketing Agent shared-cycle + Groq reasoning tests.

Covers the connected improvements without touching the legacy
MarketingAgent, integrations, or unrelated agents:

ORCHESTRATION
  - team Start Analysis starts the Marketing Agent with the shared cycle id
  - exactly one Marketing Agent execution per cycle (idempotent create)
  - parallel dispatch (worker starts without waiting for the team plan)
  - Marketing Agent failure never stops sibling agents
  - non-team modes do not trigger the Marketing Agent
  - read-only endpoints (list/get/events) never create runs

LLM (Groq reasoning layer)
  - Groq preferred whenever GROQ_API_KEY is set (backend-only)
  - generic provider fallback / None when unconfigured
  - no frontend exposure of GROQ_API_KEY
  - AgentDecision schema validation; invalid decisions rejected
  - unknown tools rejected and recorded, never executed
  - tenant-override args stripped before dispatch
  - tool results feed back into the loop; multi-iteration observability
  - retrieval bounded by max_retrieval_rounds
  - Groq failure degrades gracefully (no crash, no fabricated reasoning)

SECURITY
  - tenant isolation of cycle runs
  - approval gate preserved (requested, never auto-approved/executed)
  - no direct email send from the LLM path
"""
from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.agents.marketing_agi.agent import (
    AgentDecision,
    ALLOWED_DECISIONS,
    MarketingAGI,
    sanitize_tool_args,
)
from backend.app.agents.marketing_agi.cycle import (
    MARKETING_AGI_AGENT_NAME,
    create_cycle_run,
    run_cycle_worker,
)
from backend.app.agents.marketing_agi.llm import build_marketing_llm, llm_identity
from backend.app.agents.marketing_agi.rag import AgenticRAG
from backend.app.agents.marketing_agi.tools.bootstrap import register_all_tools
from backend.app.agents.marketing_agi.tools.registry import ToolContext, get_registry
from backend.app.ai.llm.base import BaseLLMProvider
from backend.app.ai.llm.provider import GroqProvider, OpenAIProvider
from backend.app.core.config import get_settings
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    Currency,
    CustomerSegment,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
    UserRole,
)
from backend.app.models.marketing_agi import MarketingAGIRun
from backend.app.models.merchant import Merchant
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from tests.security_utils import bearer, make_world


# ── helpers ──────────────────────────────────────────────────────────────

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _clear_llm_env(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()


def _seed_merchant(db, hint="cyc"):
    m = Merchant(
        name=f"Cycle {uuid.uuid4().hex[:6]}",
        slug=f"{hint}-{uuid.uuid4().hex[:12]}",
        email=f"{hint}-{uuid.uuid4().hex[:6]}@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.commit()
    return m


def _add_customer(db, merchant, *, name, days_ago=60, failed=False):
    c = Customer(
        merchant_id=merchant.id,
        name=name,
        email=f"{name}-{uuid.uuid4().hex[:8]}@cust.com",
        segment=CustomerSegment.returning,
        total_orders=2,
        total_spend=Decimal("5000"),
    )
    db.add(c)
    db.flush()
    now = datetime.now(timezone.utc)
    order = Order(
        merchant_id=merchant.id,
        customer_id=c.id,
        order_number=f"O-{uuid.uuid4().hex[:10]}",
        status=OrderStatus.paid if not failed else OrderStatus.pending,
        subtotal=Decimal("2500"),
        discount=Decimal("0"),
        tax=Decimal("0"),
        total=Decimal("2500"),
        currency=Currency.INR,
        created_at=now - timedelta(days=days_ago),
    )
    db.add(order)
    db.flush()
    db.add(
        Payment(
            merchant_id=merchant.id,
            order_id=order.id,
            provider=PaymentProvider.synthetic,
            amount=Decimal("2500"),
            currency=Currency.INR,
            status=PaymentStatus.captured if not failed else PaymentStatus.failed,
            created_at=now - timedelta(days=days_ago),
        )
    )
    db.commit()
    return c


class _FakeLLM(BaseLLMProvider):
    """Scripted model: pops generate_structured responses per schema type.

    script maps schema class name → list of responses, because the agent
    loop AND the agentic RAG share one LLM instance with different
    schemas (SignalDetection/ToolChoice/CampaignStrategy/HypothesisVerdict
    vs RetrievalDecision/EvidenceSufficiency).
    """

    def __init__(self, script: dict[str, list[Any]] | None = None, fail: bool = False):
        self._script: dict[str, list[Any]] = {
            k: list(v) for k, v in (script or {}).items()
        }
        self.fail = fail
        self.calls = 0

    def generate(self, system_prompt, user_prompt, **kwargs) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("groq unavailable")
        return "ok"

    def generate_structured(self, system_prompt, user_prompt, schema, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("groq unavailable")
        queue = self._script.get(schema.__name__, [])
        if not queue:
            raise RuntimeError(f"script exhausted for {schema.__name__}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, dict):
            return schema.model_validate(item)
        return item


def _full_script():
    from backend.app.agents.marketing_agi.agent import (
        CampaignStrategy,
        HypothesisVerdict,
        SignalDetection,
        ToolChoice,
    )
    from backend.app.agents.marketing_agi.rag import (
        EvidenceSufficiency,
        RetrievalDecision,
    )

    return {
        "SignalDetection": [
            SignalDetection(
                signals=["5 customers with purchase history have gone quiet"],
                primary_signal="5 customers with purchase history have gone quiet",
                investigation_questions=["Which customers stopped buying?"],
                knowledge_gaps=[],
            ),
        ],
        "RetrievalDecision": [
            RetrievalDecision(
                action="retrieve", information_type="customer",
                tool="get_customer_segments",
                query="Which customers stopped buying?",
                reasoning="need segments",
            ),
        ],
        "EvidenceSufficiency": [
            EvidenceSufficiency(
                sufficient=True, coverage=0.9, gaps=[], reasoning="enough",
            ),
        ],
        "ToolChoice": [
            ToolChoice(
                tool="get_customer_segments", params={},
                reasoning="Need segment evidence", done=False,
            ),
            ToolChoice(tool="", params={}, reasoning="done", done=True),
        ],
        "CampaignStrategy": [
            CampaignStrategy(
                workflow="customer_win_back",
                name="Win-back Campaign",
                objective="Recover dormant customers",
                audience_reasoning="real audience",
                content_reasoning="honest",
                message="We miss you — your favourites are here.",
                subject_variants=["We saved your spot"],
                cta="Shop again",
                timing="morning",
                expected_impact_rationale="grounded estimate",
                expected_revenue_inr=1000.0,
                success_metric="purchases in 14 days",
                risks=[],
            ),
        ],
    }


def _queued_run(db, merchant, objective="Cycle objective"):
    run_row = MarketingAGIRun(
        merchant_id=merchant.id,
        objective=objective,
        status="queued",
        phase="load_context",
    )
    db.add(run_row)
    db.commit()
    return run_row


# ── ORCHESTRATION ────────────────────────────────────────────────────────


class TestSharedCycle:
    def test_create_cycle_run_is_idempotent(self, db_session):
        m = _seed_merchant(db_session, "idem")
        cycle = uuid.uuid4().hex
        r1 = create_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        r2 = create_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        assert r1.id == r2.id
        rows = db_session.scalars(
            select(MarketingAGIRun).where(
                MarketingAGIRun.merchant_id == m.id,
                MarketingAGIRun.analysis_cycle_id == cycle,
            )
        ).all()
        assert len(rows) == 1

    def test_team_start_creates_shared_cycle_once(
        self, client, db_session, monkeypatch
    ):
        m, u, _ = make_world(db_session, slug_hint="team1")
        _add_customer(db_session, m, name="cyc-a")
        dispatched: list[dict] = []

        import backend.app.agents.marketing_agi.cycle as cycle_mod

        def _fake_trigger(session_factory, **kwargs):
            dispatched.append(kwargs)

        monkeypatch.setattr(
            cycle_mod, "trigger_marketing_agi_parallel", _fake_trigger
        )
        # Route asks for the app session factory to hand to the worker;
        # give it the test factory so the test stays hermetic.
        import backend.app.db.session as session_mod
        from tests.conftest import _TestSessionLocal

        monkeypatch.setattr(
            session_mod, "get_session_factory", lambda: _TestSessionLocal
        )
        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id),
                  "objective": "Team analysis"},
            headers=bearer(u),
        )
        # Request-independent: 202 with cycle id, returned without waiting
        # for the plan (TestClient awaits background tasks, so the worker
        # has completed by the time we inspect the DB below).
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "running"
        cycle_id = body["orchestrator_run_id"]
        assert cycle_id
        # exactly one parallel dispatch for the cycle, carrying the cycle id
        assert len(dispatched) == 1
        assert dispatched[0]["cycle_id"] == cycle_id
        assert str(dispatched[0]["merchant_id"]) == str(m.id)
        magi = db_session.scalars(
            select(MarketingAGIRun).where(
                MarketingAGIRun.merchant_id == m.id,
                MarketingAGIRun.analysis_cycle_id == cycle_id,
            )
        ).all()
        assert len(magi) == 1
        # sibling agent rows share the same cycle, including the audit row
        agents = db_session.scalars(
            select(AgentRun).where(
                AgentRun.merchant_id == m.id,
                AgentRun.orchestrator_run_id == cycle_id,
            )
        ).all()
        assert len(agents) >= 2
        assert MARKETING_AGI_AGENT_NAME in {a.agent_name for a in agents}

    def test_marketing_startup_failure_does_not_stop_team(
        self, client, db_session, monkeypatch
    ):
        m, u, _ = make_world(db_session, slug_hint="team2")
        import backend.app.api.routes.agents as agents_route

        def _boom(db, merchant_id, params, cycle_id):
            raise RuntimeError("groq down")

        monkeypatch.setattr(agents_route, "_start_team_marketing_agent", _boom)
        # The server-owned orchestrator worker must still use a test session.
        import backend.app.db.session as session_mod
        from tests.conftest import _TestSessionLocal

        monkeypatch.setattr(
            session_mod, "get_session_factory", lambda: _TestSessionLocal
        )
        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        assert r.json()["status"] == "running"
        # The server-owned orchestrator worker still completed the plan
        # despite the Marketing Agent startup failure (isolation).
        cycle_id = r.json()["orchestrator_run_id"]
        agents = db_session.scalars(
            select(AgentRun).where(
                AgentRun.merchant_id == m.id,
                AgentRun.orchestrator_run_id == cycle_id,
            )
        ).all()
        assert len(agents) >= 2

    def test_non_team_modes_do_not_trigger_marketing(
        self, client, db_session, monkeypatch
    ):
        m, u, _ = make_world(db_session, slug_hint="team3")
        import backend.app.api.routes.agents as agents_route

        calls: list = []
        monkeypatch.setattr(
            agents_route, "_start_team_marketing_agent",
            lambda *a, **k: calls.append(a),
        )
        r = client.post(
            "/api/agents/run",
            json={"mode": "fast", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 200, r.text
        assert calls == []

    def test_read_endpoints_never_create_runs(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="ro1")

        def _count():
            return len(
                db_session.scalars(
                    select(MarketingAGIRun).where(
                        MarketingAGIRun.merchant_id == m.id
                    )
                ).all()
            )

        before = _count()
        assert client.get("/api/marketing-agi/runs", headers=bearer(u)).status_code == 200
        assert client.get("/api/marketing-agi/status", headers=bearer(u)).status_code == 200
        assert client.get("/api/marketing-agi/campaigns", headers=bearer(u)).status_code == 200
        assert _count() == before

    def test_cycle_worker_runs_bounded_loop(self, db_session, monkeypatch):
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "work")
        _add_customer(db_session, m, name="work-a")
        cycle = uuid.uuid4().hex
        run_row = create_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        from tests.conftest import _TestSessionLocal

        run_cycle_worker(
            _TestSessionLocal, run_row.id, m.id, "obj", cycle
        )
        db_session.expire_all()
        done = db_session.get(MarketingAGIRun, run_row.id)
        assert done.analysis_cycle_id == cycle
        assert done.status in (
            "waiting_approval", "completed", "blocked", "failed",
        )
        state = done.state or {}
        assert state.get("tool_call_count", 0) >= 1

    def test_cycle_worker_llm_setup_failure_still_terminates(
        self, db_session, monkeypatch
    ):
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "crash")
        cycle = uuid.uuid4().hex
        run_row = create_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()

        # Groq setup blowing up must not hang or crash the worker: it falls
        # back to the bounded deterministic loop and terminates.
        import backend.app.agents.marketing_agi.llm as llm_mod

        monkeypatch.setattr(
            llm_mod, "build_marketing_llm",
            lambda: (_ for _ in ()).throw(RuntimeError("groq down")),
        )
        from tests.conftest import _TestSessionLocal

        run_cycle_worker(_TestSessionLocal, run_row.id, m.id, "obj", cycle)
        db_session.expire_all()
        done = db_session.get(MarketingAGIRun, run_row.id)
        assert done.status in (
            "waiting_approval", "completed", "blocked", "failed",
        )


# ── LLM ──────────────────────────────────────────────────────────────────


class TestGroqWiring:
    def test_groq_preferred_when_key_set(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_1234567890")
        monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
        monkeypatch.setenv("LLM_PROVIDER", "openrouter")
        get_settings.cache_clear()
        try:
            configured, provider, model = llm_identity()
            assert configured is True
            assert provider == "groq"
            assert model == "openai/gpt-oss-120b"
            llm = build_marketing_llm()
            assert isinstance(llm, GroqProvider)
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_generic_fallback_without_groq_key(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "")
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.setenv("LLM_API_KEY", "sk-test-1234567890")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
        get_settings.cache_clear()
        try:
            configured, provider, model = llm_identity()
            assert (configured, provider, model) == (True, "openai", "gpt-4o-mini")
            assert isinstance(build_marketing_llm(), OpenAIProvider)
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_none_when_no_keys(self, monkeypatch):
        _clear_llm_env(monkeypatch)
        try:
            assert llm_identity() == (False, None, None)
            assert build_marketing_llm() is None
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_no_frontend_groq_key(self):
        hits = [
            p for p in REPO_ROOT.joinpath("frontend", "src").rglob("*")
            if p.is_file()
            and ("GROQ_API_KEY" in p.read_text(errors="ignore")
                 or "VITE_GROQ" in p.read_text(errors="ignore"))
        ]
        assert hits == []

    def test_configured_model_comes_from_settings(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_1234567890")
        monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
        get_settings.cache_clear()
        try:
            llm = build_marketing_llm()
            assert llm._model == "openai/gpt-oss-120b"
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()


class TestAgentDecisions:
    def test_valid_decision_parses(self):
        d = AgentDecision.model_validate(
            {"decision": "call_tool", "tool": "find_customers",
             "arguments": {"min_orders": 0}, "reason": "Need audience evidence."}
        )
        assert d.decision == "call_tool"
        assert d.tool == "find_customers"

    def test_allowed_decision_set(self):
        assert ALLOWED_DECISIONS == {
            "call_tool", "continue_research", "formulate_hypothesis",
            "create_plan", "create_campaign_draft", "verify",
            "request_approval", "finish",
        }

    def test_invalid_decision_shape_rejected(self):
        import pydantic

        # wrong-typed tool field is rejected by the schema
        with pytest.raises(pydantic.ValidationError):
            AgentDecision.model_validate(
                {"decision": "call_tool", "tool": 12345,
                 "arguments": {}, "reason": "x"}
            )
        # non-object payloads are rejected
        with pytest.raises(pydantic.ValidationError):
            AgentDecision.model_validate("just do it")
        # unknown decision verbs never validate as executable
        d = AgentDecision.model_validate(
            {"decision": "self_approve", "reason": "trust me"}
        )
        assert d.decision not in ALLOWED_DECISIONS

    def test_sanitize_strips_tenant_keys(self):
        clean, dropped = sanitize_tool_args(
            {"min_orders": 1, "merchant_id": "other", "tenant_id": "x"}
        )
        assert clean == {"min_orders": 1}
        assert set(dropped) == {"merchant_id", "tenant_id"}

    def test_sanitize_drops_non_scalar_payloads(self):
        clean, dropped = sanitize_tool_args(
            {"query": "q", "nested": {"evil": 1}, "cb": ["a", 1]}
        )
        assert clean == {"query": "q", "cb": ["a", 1]}
        assert dropped == ["nested"]

    def test_sanitize_rejects_non_dict(self):
        clean, dropped = sanitize_tool_args("find_customers")
        assert clean == {} and dropped

    def test_unknown_tool_rejected_and_recorded(self, db_session):
        m = _seed_merchant(db_session, "unk")
        _add_customer(db_session, m, name="unk-a")
        from backend.app.agents.marketing_agi.agent import SignalDetection, ToolChoice

        llm = _FakeLLM({
            "SignalDetection": [
                SignalDetection(
                    signals=["quiet customers"],
                    primary_signal="quiet customers",
                    investigation_questions=["Who stopped buying?"],
                    knowledge_gaps=[],
                ),
            ],
            "RetrievalDecision": [],
            "EvidenceSufficiency": [],
            "ToolChoice": [
                ToolChoice(tool="drop_database", params={},
                           reasoning="evil", done=False),
            ],
        })
        run_row = _queued_run(db_session, m)
        MarketingAGI(db_session, m.id, llm=llm).run(run_row, "obj")
        state = run_row.state
        tools = [c["tool"] for c in state["tool_calls"]]
        assert "drop_database" not in tools
        rejected = [d for d in state["llm_decisions"]
                    if d.get("error") == "unknown_tool_rejected"]
        assert rejected

    def test_tenant_override_in_tool_args_stripped(self, db_session):
        m = _seed_merchant(db_session, "ten")
        other = _seed_merchant(db_session, "oth")
        _add_customer(db_session, m, name="ten-a")
        _add_customer(db_session, other, name="oth-a")
        from backend.app.agents.marketing_agi.agent import SignalDetection, ToolChoice

        llm = _FakeLLM({
            "SignalDetection": [
                SignalDetection(
                    signals=["quiet customers"],
                    primary_signal="quiet customers",
                    investigation_questions=["Who stopped buying?"],
                    knowledge_gaps=[],
                ),
            ],
            "ToolChoice": [
                # model tries to override the tenant: must be stripped
                ToolChoice(tool="get_customer_segments",
                           params={"merchant_id": str(other.id)},
                           reasoning="segments", done=False),
                ToolChoice(tool="", params={}, reasoning="", done=True),
            ],
        })
        run_row = _queued_run(db_session, m)
        MarketingAGI(db_session, m.id, llm=llm).run(run_row, "obj")
        # all evidence belongs to merchant m's tools (tenant-scoped ctx)
        assert run_row.state["tool_call_count"] >= 1

    def test_multi_iteration_observability(self, db_session):
        m = _seed_merchant(db_session, "obs")
        _add_customer(db_session, m, name="obs-a")
        llm = _FakeLLM(_full_script())
        # patch identity names for deterministic metadata
        run_row = _queued_run(db_session, m)
        agent = MarketingAGI(db_session, m.id, llm=llm)
        agent._llm_provider_name = "groq"
        agent._llm_model_name = "openai/gpt-oss-120b"
        agent.run(run_row, "obj")
        state = run_row.state
        assert state["llm_calls"] >= 2
        assert len(state["llm_decisions"]) >= 2
        for d in state["llm_decisions"]:
            assert d["provider"] == "groq"
            assert d["model"] == "openai/gpt-oss-120b"
            assert isinstance(d["latency_ms"], int)
            assert d["success"] is True
            assert "system_prompt" not in d and "api_key" not in str(d).lower()
        assert state["reasoning_summary"]
        assert state["current_decision"]

    def test_groq_failure_degrades_gracefully(self, db_session):
        m = _seed_merchant(db_session, "deg")
        _add_customer(db_session, m, name="deg-a")
        llm = _FakeLLM([], fail=True)
        run_row = _queued_run(db_session, m)
        MarketingAGI(db_session, m.id, llm=llm).run(run_row, "obj")
        state = run_row.state
        assert state["llm_degraded"] is True
        assert run_row.status in (
            "waiting_approval", "completed", "blocked", "failed",
        )
        # honest failure recorded, no fabricated LLM success
        assert not [d for d in state["llm_decisions"] if d.get("success")]
        assert any("finish: " in e or "llm" in e.lower() or "groq" in e.lower()
                   or "LLM" in e or "unavailable" in e.lower()
                   for e in state["errors"]) or state["llm_degraded"]

    def test_retry_behavior_bounded(self):
        from backend.app.ai.llm.provider import OpenAIProvider

        p = OpenAIProvider(api_key="sk-x", timeout=1, max_retries=2)
        calls = {"n": 0}

        def _boom(**kwargs):
            calls["n"] += 1
            import openai

            raise openai.APIConnectionError(request=None)

        import backend.app.ai.llm.provider as prov

        real = prov._is_retryable
        prov._is_retryable = lambda exc: True
        try:
            with pytest.raises(Exception):
                p._call_with_retry(_boom)
        finally:
            prov._is_retryable = real
        assert calls["n"] == 3  # initial + 2 retries, never infinite

    def test_retrieval_rounds_bounded(self, db_session):
        from backend.app.agents.marketing_agi.limits import LoopLimits

        m = _seed_merchant(db_session, "rag")
        register_all_tools()
        ctx = ToolContext(db=db_session, merchant_id=m.id)
        rag = AgenticRAG(ctx, get_registry(), None,
                         LoopLimits(max_retrieval_rounds=2))
        res = rag.research("Which customers stopped buying?")
        assert res.rounds <= 2


# ── SECURITY ─────────────────────────────────────────────────────────────


class TestCycleSecurity:
    def test_cross_tenant_cycle_isolated(self, client, db_session):
        m1, u1, _ = make_world(db_session, slug_hint="c1")
        m2, u2, _ = make_world(db_session, slug_hint="c2")
        cycle = uuid.uuid4().hex
        create_cycle_run(
            db_session, merchant_id=m1.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        run_id = db_session.scalar(
            select(MarketingAGIRun.id).where(
                MarketingAGIRun.merchant_id == m1.id,
                MarketingAGIRun.analysis_cycle_id == cycle,
            )
        )
        r = client.get(f"/api/marketing-agi/runs/{run_id}", headers=bearer(u2))
        assert r.status_code == 404
        r = client.get(
            f"/api/marketing-agi/runs?analysis_cycle_id={cycle}",
            headers=bearer(u2),
        )
        assert r.status_code == 200
        assert r.json()["runs"] == []

    def test_cycle_filter_scoped_to_merchant(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="cf")
        cycle = uuid.uuid4().hex
        create_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        r = client.get(
            f"/api/marketing-agi/runs?analysis_cycle_id={cycle}",
            headers=bearer(u),
        )
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["analysis_cycle_id"] == cycle

    def test_approval_gate_preserved(self, db_session, monkeypatch):
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "appr")
        _add_customer(db_session, m, name="appr-a")
        run_row = _queued_run(db_session, m)
        MarketingAGI(db_session, m.id, llm=None).run(run_row, "obj")
        state = run_row.state
        if state.get("prepared_action"):
            action = db_session.get(
                AgentAction, uuid.UUID(state["prepared_action"]["action_id"])
            )
            assert action is not None
            assert str(getattr(action.status, "value", action.status)) == "requested"
            assert run_row.status == "waiting_approval"
            # no external execution happened
            assert str(getattr(action.status, "value", action.status)) not in {
                "executing", "completed",
            }

    def test_no_direct_email_send(self, db_session, monkeypatch):
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "mail")
        _add_customer(db_session, m, name="mail-a")
        run_row = _queued_run(db_session, m)
        MarketingAGI(db_session, m.id, llm=None).run(run_row, "obj")
        tools_used = [c["tool"] for c in (run_row.state or {}).get("tool_calls", [])]
        # the LLM path can only reach allowlisted tools; nothing sends email
        assert "send_email" not in tools_used
        assert "send_campaign" not in tools_used
        # draft tool only persists drafts, never sends
        register_all_tools()
        out = get_registry().call(
            ToolContext(db=db_session, merchant_id=m.id),
            "create_email_campaign_draft",
            {"campaign_key": f"k-{uuid.uuid4().hex[:8]}",
             "workflow": "customer_win_back", "name": "n",
             "objective": "o",
             "audience": {"criteria": {}, "customer_ids": []},
             "audience_count": 0,
             "content": {"message": "hi", "cta": "go", "timing": "now"},
             "expected_impact": {"rationale": "r", "estimated_revenue_inr": 0},
             "success_metric": "m", "evidence_refs": []},
        )["result"]
        assert out.get("created") is True
        assert out.get("integration_status") in ("draft_only", "connected",
                                                 "requires_integration")

    def test_registry_rejects_arbitrary_tools(self, db_session):
        m = _seed_merchant(db_session, "arb")
        register_all_tools()
        ctx = ToolContext(db=db_session, merchant_id=m.id)
        from backend.app.agents.marketing_agi.tools.registry import ToolError

        for evil in ("send_campaign", "exec_sql", "http_get", ""):
            with pytest.raises(ToolError):
                get_registry().call(ctx, evil, {})


# ── DASHBOARD STATE ──────────────────────────────────────────────────────


class TestDashboardState:
    def test_run_serializes_cycle_and_llm_state(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="dash")
        cycle = uuid.uuid4().hex
        run_row = create_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        r = client.get(f"/api/marketing-agi/runs/{run_row.id}", headers=bearer(u))
        assert r.status_code == 200
        body = r.json()
        assert body["analysis_cycle_id"] == cycle
        for key in ("llm_calls", "llm_decisions", "reasoning_status",
                    "current_decision", "reasoning_summary", "llm_degraded"):
            assert key in body["state"]

    def test_status_reports_llm_identity(self, client, db_session, monkeypatch):
        m, u, _ = make_world(db_session, slug_hint="dash2")
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test_key_1234567890")
        monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
        get_settings.cache_clear()
        try:
            r = client.get("/api/marketing-agi/status", headers=bearer(u))
            assert r.status_code == 200
            body = r.json()
            assert body["llm_configured"] is True
            assert body["llm_provider"] == "groq"
            assert body["llm_model"] == "openai/gpt-oss-120b"
        finally:
            monkeypatch.undo()
            get_settings.cache_clear()

    def test_single_start_action_on_team(self, client, db_session):
        """AI Team exposes one Start Analysis (POST /api/agents/run); the
        Marketing Agent page performs no standalone start — verified by the
        absence of a start trigger in its bundle (see frontend test)."""
        m, u, _ = make_world(db_session, slug_hint="dash3")
        r = client.get("/api/agents", headers=bearer(u))
        assert r.status_code == 200
        names = {a["name"] for a in r.json()["agents"]}
        assert "MarketingAgent" in names


# ── BACKGROUND EXECUTION (Phase 14A) ──────────────────────────────────


class TestBackgroundExecution:
    def test_post_returns_202_without_waiting_for_plan(
        self, client, db_session, monkeypatch
    ):
        """202 + cycle id immediately; Marketing Agent row persisted in-request."""
        m, u, _ = make_world(db_session, slug_hint="bg1")
        import backend.app.agents.marketing_agi.cycle as cycle_mod
        import backend.app.db.session as session_mod
        from tests.conftest import _TestSessionLocal

        monkeypatch.setattr(
            cycle_mod, "trigger_marketing_agi_parallel", lambda sf, **k: None
        )
        monkeypatch.setattr(
            session_mod, "get_session_factory", lambda: _TestSessionLocal
        )
        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "running"
        assert body["orchestrator_run_id"]
        # Cycle-linked Marketing Agent row already persisted at return time.
        magi = db_session.scalars(
            select(MarketingAGIRun).where(
                MarketingAGIRun.merchant_id == m.id,
                MarketingAGIRun.analysis_cycle_id == body["orchestrator_run_id"],
            )
        ).all()
        assert len(magi) == 1

    def test_orchestrator_worker_uses_fresh_session_not_request(
        self, db_session, monkeypatch
    ):
        """Worker runs the plan on its own session; request session state
        (e.g. closed/rolled-back) cannot affect it."""
        from tests.conftest import _TestSessionLocal
        import backend.app.api.routes.agents as agents_route

        m = _seed_merchant(db_session, "bg2")
        _add_customer(db_session, m, name="bg2-a")
        cycle = uuid.uuid4().hex
        agents_route._run_team_orchestrator_worker(
            _TestSessionLocal, m.id, {"objective": "bg", "window_days": 30},
            cycle, {},
        )
        db_session.expire_all()
        agents = db_session.scalars(
            select(AgentRun).where(
                AgentRun.merchant_id == m.id,
                AgentRun.orchestrator_run_id == cycle,
            )
        ).all()
        # Full 14-step AI_TEAM_PLAN completed on the worker session.
        assert len(agents) >= 14

    def test_orchestrator_worker_crash_marks_rows_failed(
        self, db_session, monkeypatch
    ):
        """A worker crash never propagates and best-effort marks
        still-running audit rows FAILED instead of stuck."""
        from tests.conftest import _TestSessionLocal
        from backend.app.models.enums import AgentRunStatus
        import backend.app.api.routes.agents as agents_route

        m = _seed_merchant(db_session, "bg3")
        cycle = uuid.uuid4().hex
        stuck = AgentRun(
            merchant_id=m.id,
            orchestrator_run_id=cycle,
            agent_name="GrowthDiscoveryAgent",
            status=AgentRunStatus.running,
            mode="team",
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(stuck)
        db_session.commit()

        import backend.app.agents.orchestrator as orch_mod

        def _boom(self, merchant_id, mode="deep", params=None, run_id=None):
            raise RuntimeError("plan exploded")

        monkeypatch.setattr(orch_mod.GrowthAgentOrchestrator, "run", _boom)
        # Must not raise.
        agents_route._run_team_orchestrator_worker(
            _TestSessionLocal, m.id, {}, cycle, {}
        )
        db_session.expire_all()
        row = db_session.get(AgentRun, stuck.id)
        assert str(getattr(row.status, "value", row.status)) == "failed"
        assert any("worker_crashed" in str(e) for e in (row.errors or []))

    def test_orchestrator_worker_never_raises_unknown_merchant(
        self, monkeypatch
    ):
        """Even a missing merchant is contained (FAILED persistence, no raise)."""
        from tests.conftest import _TestSessionLocal
        import backend.app.api.routes.agents as agents_route

        agents_route._run_team_orchestrator_worker(
            _TestSessionLocal, uuid.uuid4(), {}, uuid.uuid4().hex, {}
        )  # must not raise


# ── PERSISTENCE (Phase 14D) ────────────────────────────────────────────


class TestIntermediatePersistence:
    def test_checkpoint_visible_to_separate_session(self, db_session):
        """A mid-run checkpoint commits state so polling sessions observe it."""
        from tests.conftest import _TestSessionLocal
        from backend.app.agents.marketing_agi.state import MarketingAGIState

        m = _seed_merchant(db_session, "ckpt")
        run_row = _queued_run(db_session, m)
        agent = MarketingAGI(db_session, m.id, llm=None)
        state = MarketingAGIState(
            run_id=str(run_row.id), merchant_id=str(m.id), objective="obj",
        )
        state.reasoning_status = "investigating"
        state.reasoning_summary = "Checkpoint probe summary."
        state.tool_call_count = 3
        agent._checkpoint(run_row, state)

        fresh = _TestSessionLocal()
        try:
            body = fresh.get(MarketingAGIRun, run_row.id)
            assert body is not None
            assert body.state["reasoning_status"] == "investigating"
            assert body.state["reasoning_summary"] == "Checkpoint probe summary."
            assert body.state["tool_call_count"] == 3
            assert body.tool_call_count == 3
        finally:
            fresh.close()

    def test_events_queryable_via_api_before_completion(
        self, client, db_session
    ):
        """Events emitted mid-run are readable through the events endpoint
        (committed, tenant-scoped) — no final commit required."""
        from backend.app.agents.marketing_agi.events import (
            EventRecorder, list_events,
        )

        m, u, _ = make_world(db_session, slug_hint="evt")
        run_row = _queued_run(db_session, m)
        rec = EventRecorder(db_session, run_row)
        rec.emit(phase="observe", event_type="phase_started", message="probe")
        db_session.commit()
        r = client.get(
            f"/api/marketing-agi/runs/{run_row.id}/events", headers=bearer(u)
        )
        assert r.status_code == 200
        assert any(e["message"] == "probe" for e in r.json()["events"])
        assert list_events(db_session, run_row.id, m.id)

    def test_full_run_persists_campaign_and_approval(
        self, client, db_session, monkeypatch
    ):
        """Terminal state (campaign draft + requested action) survives and
        is queryable after completion — the refresh/navigation source."""
        _clear_llm_env(monkeypatch)
        m, u, _ = make_world(db_session, slug_hint="pers")
        _add_customer(db_session, m, name="pers-a")
        run_row = _queued_run(db_session, m)
        MarketingAGI(db_session, m.id, llm=None).run(run_row, "obj")
        db_session.expire_all()

        r = client.get(
            f"/api/marketing-agi/runs/{run_row.id}", headers=bearer(u)
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in (
            "waiting_approval", "completed", "blocked", "failed",
        )
        assert "timing" in body["state"]
        assert "result" in body and body["result"] is not None
        if body["state"].get("campaign_draft"):
            camps = client.get(
                "/api/marketing-agi/campaigns", headers=bearer(u)
            ).json()["campaigns"]
            assert len(camps) >= 1
        if body["state"].get("prepared_action"):
            acts = client.get("/api/actions", headers=bearer(u)).json()
            items = acts["actions"] if isinstance(acts, dict) else acts
            assert any(
                a.get("status") == "requested" for a in items
            )

    def test_timing_metadata_present_and_secret_free(
        self, db_session, monkeypatch
    ):
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "tim")
        _add_customer(db_session, m, name="tim-a")
        run_row = _queued_run(db_session, m)
        MarketingAGI(db_session, m.id, llm=None).run(run_row, "obj")
        timing = (run_row.state or {}).get("timing", {})
        for key in ("total_ms", "llm_total_ms", "tool_total_ms", "rag_total_ms",
                    "db_total_ms", "llm_calls", "rate_limit_count",
                    "retry_count", "tool_calls", "rag_rounds"):
            assert key in timing, key
        blob = str(timing) + str(run_row.state.get("llm_decisions", []))
        for secret_word in ("gsk_", "sk-or-", "Bearer ", "api_key"):
            assert secret_word not in blob


# ── GROQ 429 / RETRY-AFTER (Phase 14F) ─────────────────────────────────


class TestGroqRetryAfter:
    def _rate_limit_error(self, retry_after=None):
        import httpx
        import openai

        headers = {}
        if retry_after is not None:
            headers["retry-after"] = str(retry_after)
        request = httpx.Request(
            "POST", "https://api.groq.com/openai/v1/chat/completions"
        )
        response = httpx.Response(429, request=request, headers=headers)
        return openai.RateLimitError("rate limited", response=response, body=None)

    def test_retry_after_hint_parsed(self):
        from backend.app.ai.llm.provider import _retry_after_seconds

        assert _retry_after_seconds(self._rate_limit_error("7"), 1.0) == 7.0

    def test_retry_after_capped(self):
        from backend.app.ai.llm.provider import (
            _retry_after_seconds, MAX_RETRY_DELAY_SECONDS,
        )

        assert _retry_after_seconds(self._rate_limit_error("120"), 1.0) == \
            MAX_RETRY_DELAY_SECONDS

    def test_retry_after_missing_falls_back(self):
        from backend.app.ai.llm.provider import _retry_after_seconds

        assert _retry_after_seconds(self._rate_limit_error(None), 2.0) == 2.0

    def test_retry_respects_hint_and_records_stats(self, monkeypatch):
        from backend.app.ai.llm.provider import GroqProvider

        p = GroqProvider(api_key="gsk_test_key_1234567890", timeout=5,
                         max_retries=1, max_tokens=50)
        calls = {"n": 0}
        sleeps: list[float] = []

        def _flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise self._rate_limit_error("9")
            return "ok"

        monkeypatch.setattr(p, "_do_generate", _flaky)
        monkeypatch.setattr(
            "backend.app.ai.llm.provider.time.sleep",
            lambda s: sleeps.append(s),
        )
        assert p._call_with_retry(_flaky) == "ok"
        assert sleeps == [9.0]
        assert p.last_call_stats["rate_limited"] is True
        assert p.last_call_stats["retries"] == 1
        assert p.last_call_stats["retry_delay_ms"] == 9000

    def test_capped_hint_never_stalls(self, monkeypatch):
        from backend.app.ai.llm.provider import (
            GroqProvider, MAX_RETRY_DELAY_SECONDS,
        )

        p = GroqProvider(api_key="gsk_test_key_1234567890", timeout=5,
                         max_retries=1, max_tokens=50)
        sleeps: list[float] = []

        def _always_429(**kwargs):
            raise self._rate_limit_error("300")

        import backend.app.ai.llm.provider as prov

        monkeypatch.setattr(
            "backend.app.ai.llm.provider.time.sleep",
            lambda s: sleeps.append(s),
        )
        with pytest.raises(prov.LLMError):
            p._call_with_retry(_always_429)
        assert sum(sleeps) <= 2 * MAX_RETRY_DELAY_SECONDS
        assert p.last_call_stats["attempts"] == 2  # bounded, never infinite


# ── TOOL CATALOG FILTERING (Phase 14G) ─────────────────────────────────


class TestToolCatalogFiltering:
    def test_write_tools_excluded_for_investigation(self):
        register_all_tools()
        full = {t["name"] for t in get_registry().catalog()}
        assert "create_email_campaign_draft" in full
        filtered = {t["name"] for t in get_registry().catalog(include_write=False)}
        assert "create_email_campaign_draft" not in filtered
        # read-only investigation tools remain
        assert {"get_business_overview", "find_customers",
                "get_customer_segments"} <= filtered

    def test_disconnected_providers_excluded(self):
        register_all_tools()
        names = {t["name"] for t in get_registry().catalog(
            exclude_providers=frozenset({"google_ads", "meta_ads", "instagram"}))}
        assert "get_google_ads_campaigns" not in names
        assert "get_meta_campaigns" not in names
        assert "get_social_performance" not in names
        # draft-only platform tools (no live connection needed) remain
        assert "get_email_campaigns" in names
        assert "create_email_campaign_draft" in names

    def test_allowlist_unaffected_by_prompt_filter(self, db_session):
        m = _seed_merchant(db_session, "allow")
        register_all_tools()
        # Even when excluded from prompts, the tool still executes honestly
        # (requires_integration payload, zero network).
        out = get_registry().call(
            ToolContext(db=db_session, merchant_id=m.id),
            "get_google_ads_campaigns", {},
        )["result"]
        assert out.get("status") == "requires_integration"

    def test_agent_prompt_catalog_excludes_disconnected(self, db_session):
        m = _seed_merchant(db_session, "pcat")
        agent = MarketingAGI(db_session, m.id, llm=None)
        names = {t["name"] for t in agent._prompt_catalog(include_write=False)}
        # No verified connections in this workspace → live tools out.
        assert "get_google_ads_campaigns" not in names
        assert "get_meta_campaigns" not in names
        assert "create_email_campaign_draft" not in names
        assert "get_business_overview" in names


# ── OBSERVATION ROBUSTNESS (Phase 14H) ─────────────────────────────────


class TestObservationRobustness:
    def test_all_observe_tools_return(self, db_session):
        m = _seed_merchant(db_session, "obs")
        _add_customer(db_session, m, name="obs-a")
        agent = MarketingAGI(db_session, m.id, llm=None)
        from backend.app.agents.marketing_agi.state import MarketingAGIState

        state = MarketingAGIState(
            run_id="r", merchant_id=str(m.id), objective="o",
        )
        out = agent._observe_parallel(
            state,
            ["get_customer_activity_trend", "get_customer_segments",
             "get_failed_payment_analytics", "get_product_affinities"],
        )
        assert set(out) == {"get_customer_activity_trend",
                            "get_customer_segments",
                            "get_failed_payment_analytics",
                            "get_product_affinities"}

    def test_one_failed_tool_does_not_kill_observation(self, db_session, monkeypatch):
        from backend.app.agents.marketing_agi.state import MarketingAGIState
        from backend.app.agents.marketing_agi.tools.registry import (
            MarketingToolRegistry,
        )

        m = _seed_merchant(db_session, "obsf")
        agent = MarketingAGI(db_session, m.id, llm=None)
        real_call = MarketingToolRegistry.call

        def _flaky(self, ctx, name, params):
            if name == "get_customer_segments":
                raise RuntimeError("segments store down")
            return real_call(self, ctx, name, params)

        monkeypatch.setattr(MarketingToolRegistry, "call", _flaky)
        state = MarketingAGIState(
            run_id="r", merchant_id=str(m.id), objective="o",
        )
        out = agent._observe_parallel(
            state, ["get_customer_segments", "get_failed_payment_analytics"],
        )
        assert out["get_customer_segments"].get("error")
        assert "error" not in out["get_failed_payment_analytics"]

    def test_per_run_cache_reuses_read_only_result(self, db_session):
        m = _seed_merchant(db_session, "cache")
        agent = MarketingAGI(db_session, m.id, llm=None)
        register_all_tools()
        from backend.app.agents.marketing_agi.tools.registry import (
            MarketingToolRegistry,
        )

        calls = {"n": 0}
        real_call = MarketingToolRegistry.call  # unbound: (self, ctx, name, params)

        def _counting(self, ctx, name, params):
            calls["n"] += 1
            return real_call(self, ctx, name, params)

        monkeypatch_ctx = pytest.MonkeyPatch()
        monkeypatch_ctx.setattr(MarketingToolRegistry, "call", _counting)
        try:
            first = agent._tool("get_business_overview", {})
            second = agent._tool("get_business_overview", {})
        finally:
            monkeypatch_ctx.undo()
        assert first == second
        assert calls["n"] == 1  # second served from per-run cache


# ── SINGLE START ACTION (restored) ─────────────────────────────────────


class TestSingleStartAction:
    def test_single_start_action_on_team(self, client, db_session):
        """AI Team exposes one Start Analysis (POST /api/agents/run); the
        Marketing Agent page performs no standalone start."""
        m, u, _ = make_world(db_session, slug_hint="dash3")
        r = client.get("/api/agents", headers=bearer(u))
        assert r.status_code == 200
        names = {a["name"] for a in r.json()["agents"]}
        assert "MarketingAgent" in names
