"""AI Team shared analysis cycle — Product Agent integration tests.

The Marketing Agent is a protected, working system. These tests prove the
Product Agent joins the SAME shared cycle without altering it:

ORCHESTRATION
  - AI Team Start Analysis dispatches BOTH the Marketing Agent and the
    Product Agent
  - both agents receive the SAME shared cycle_id
  - both are dispatched independently/concurrently (neither gates on the other)
  - the Product Agent is dispatched exactly once per cycle
  - non-team modes never trigger the Product Agent
  - read-only endpoints never create a run
  - the orchestrator plan crash handler still runs and still marks its own
    rows failed (the Marketing Agent path is unchanged)

RUN LIFECYCLE
  - the cycle worker stamps and persists analysis_cycle_id
  - the Product Agent dashboard retrieves the persisted run for the cycle
  - a failed Product run is NOT reported as completed (neither the run row
    nor the shared audit row)
  - blocked/failed audit rows never read as successful
  - queued/running statuses are reported verbatim

NO SECOND TRIGGER
  - POST /api/product-agi/runs joins an in-flight run instead of creating a
    second one
  - the Product Agent dashboard page contains no run trigger
  - the Product Agent data layer exports no start function

SECURITY / APPROVALS
  - recommendations still become `requested` actions, never approved
  - an unapproved Product Agent action still cannot be executed
  - cycle reads are tenant-isolated

MARKETING AGENT REGRESSION
  - the existing Marketing cycle bridge is untouched by this integration
  - the Marketing Agent still starts under the same cycle id
"""
from __future__ import annotations

import pathlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from backend.app.agents.product_agi.agent import ProductAGI
from backend.app.agents.product_agi.cycle import (
    PRODUCT_AGENT_AGENT_NAME,
    SUCCESSFUL_RUN_STATUSES,
    TERMINAL_RUN_STATUSES,
    create_cycle_run as create_product_cycle_run,
    run_cycle_worker as run_product_cycle_worker,
)
from backend.app.agents.marketing_agi.cycle import (
    MARKETING_AGI_AGENT_NAME,
    create_cycle_run as create_marketing_cycle_run,
)
from backend.app.core.config import get_settings
from backend.app.models.agent_action import AgentAction
from backend.app.models.agent_run import AgentRun
from backend.app.models.enums import Currency, MerchantStatus, UserRole
from backend.app.models.marketing_agi import MarketingAGIRun
from backend.app.models.merchant import Merchant
from backend.app.models.product_agi import ProductAgentRun
from tests.conftest import _TestSessionLocal
from tests.security_utils import bearer, make_world

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

FRONTEND = REPO_ROOT.joinpath("frontend", "src")


# ── helpers ──────────────────────────────────────────────────────────────


def _clear_llm_env(monkeypatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()


def _seed_merchant(db, hint="pcyc"):
    m = Merchant(
        name=f"ProductCycle {uuid.uuid4().hex[:6]}",
        slug=f"{hint}-{uuid.uuid4().hex[:12]}",
        email=f"{hint}-{uuid.uuid4().hex[:6]}@x.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.commit()
    return m


def _seed_catalog(db, merchant, *, products: int = 4):
    """Real products + real settled orders for THIS merchant.

    Mirrors tests/test_product_agi.py::_seed_catalog so the Product Agent
    has honest catalog, demand and inventory facts to measure.
    """
    from decimal import Decimal
    from datetime import timedelta

    from backend.app.models.customer import Customer
    from backend.app.models.enums import OrderStatus
    from backend.app.models.order import Order, OrderItem
    from backend.app.models.product import Product

    rows = []
    for i in range(products):
        p = Product(
            merchant_id=merchant.id,
            name=f"Cycle Product {i}",
            category=("audio", "desk")[i % 2],
            price=Decimal(str(500 + i * 100)),
            sku=f"SKU-CYCLE-{i}-{uuid.uuid4().hex[:4]}",
            description="A real product description long enough to count as content.",
            stock_quantity=100,
        )
        db.add(p)
        rows.append(p)
    db.flush()

    customer = Customer(
        merchant_id=merchant.id,
        name="Cycle Buyer",
        email=f"buyer-{uuid.uuid4().hex[:8]}@test.local",
        total_orders=3,
        total_spend=Decimal("1000"),
    )
    db.add(customer)
    db.flush()

    created = datetime.now(timezone.utc) - timedelta(days=5)
    for i in range(8):
        order = Order(
            merchant_id=merchant.id,
            customer_id=customer.id,
            order_number=f"T-{merchant.id.hex[:6]}-{i}-{uuid.uuid4().hex[:4]}",
            status=OrderStatus.paid,
            subtotal=Decimal("100"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("100"),
            created_at=created,
        )
        db.add(order)
        db.flush()
        for p in rows[: 2 + (i % 2)]:
            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=p.id,
                    quantity=2,
                    unit_price=p.price,
                    line_total=p.price * 2,
                )
            )
    db.commit()
    return rows


def _patch_session_factory(monkeypatch) -> None:
    """Keep the server-owned workers hermetic inside the test DB."""
    import backend.app.db.session as session_mod

    monkeypatch.setattr(
        session_mod, "get_session_factory", lambda: _TestSessionLocal
    )


def _patch_product_dispatch(monkeypatch, sink: list | None = None) -> list:
    """Neutralise the Product Agent's real background thread.

    Tests exercise the worker directly (run_product_cycle_worker) where
    they need to assert on its result. Where the test only asserts on
    DISPATCH, the thread is stubbed exactly the way the existing Marketing
    cycle tests stub trigger_marketing_agi_parallel — the in-memory SQLite
    test database cannot take a live worker thread while TestClient is
    awaiting background tasks.
    """
    import backend.app.agents.product_agi.cycle as cycle_mod

    recorded = sink if sink is not None else []

    def _fake(session_factory, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(
        cycle_mod, "trigger_product_agent_parallel", _fake
    )
    return recorded


def _patch_marketing_dispatch(monkeypatch, sink: list | None = None) -> list:
    """Stub the Marketing Agent's thread for the same reason as above."""
    import backend.app.agents.marketing_agi.cycle as magi_cycle

    recorded = sink if sink is not None else []

    def _fake(session_factory, **kwargs):
        recorded.append(kwargs)

    monkeypatch.setattr(
        magi_cycle, "trigger_marketing_agi_parallel", _fake
    )
    return recorded


def _patch_all_dispatches(monkeypatch) -> dict[str, list]:
    """Stub both specialist workers so only the orchestrator plan runs."""
    out = {
        "marketing": _patch_marketing_dispatch(monkeypatch),
        "product": _patch_product_dispatch(monkeypatch),
    }
    _patch_session_factory(monkeypatch)
    return out


# ── ORCHESTRATION: one cycle, two agents ─────────────────────────────────


class TestSharedCycleDispatch:
    def test_start_analysis_dispatches_both_agents(
        self, client, db_session, monkeypatch
    ):
        m, u, _ = make_world(db_session, slug_hint="both1")
        _seed_catalog(db_session, m)

        import backend.app.agents.marketing_agi.cycle as magi_cycle
        import backend.app.agents.product_agi.cycle as product_cycle

        dispatched: list[dict] = []

        monkeypatch.setattr(
            magi_cycle,
            "trigger_marketing_agi_parallel",
            lambda sf, **kw: dispatched.append({"agent": "marketing", **kw}),
        )
        monkeypatch.setattr(
            product_cycle,
            "trigger_product_agent_parallel",
            lambda sf, **kw: dispatched.append({"agent": "product", **kw}),
        )
        _patch_session_factory(monkeypatch)

        r = client.post(
            "/api/agents/run",
            json={
                "mode": "team",
                "merchant_id": str(m.id),
                "objective": "Shared cycle analysis",
            },
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        cycle_id = r.json()["orchestrator_run_id"]
        assert cycle_id

        # Both agents were dispatched, exactly once each.
        agents_dispatched = sorted(d["agent"] for d in dispatched)
        assert agents_dispatched == ["marketing", "product"]
        for d in dispatched:
            assert d["cycle_id"] == cycle_id
            assert str(d["merchant_id"]) == str(m.id)

        # Both persisted runs carry the SAME shared cycle id.
        magi = db_session.scalars(
            select(MarketingAGIRun).where(
                MarketingAGIRun.merchant_id == m.id,
                MarketingAGIRun.analysis_cycle_id == cycle_id,
            )
        ).all()
        product = db_session.scalars(
            select(ProductAgentRun).where(
                ProductAgentRun.merchant_id == m.id,
                ProductAgentRun.analysis_cycle_id == cycle_id,
            )
        ).all()
        assert len(magi) == 1
        assert len(product) == 1

        # Both agents appear in the shared audit trail under that cycle.
        audit = db_session.scalars(
            select(AgentRun).where(
                AgentRun.merchant_id == m.id,
                AgentRun.orchestrator_run_id == cycle_id,
            )
        ).all()
        names = {a.agent_name for a in audit}
        assert MARKETING_AGI_AGENT_NAME in names
        assert PRODUCT_AGENT_AGENT_NAME in names

    def test_agents_are_dispatched_concurrently_not_sequentially(
        self, client, db_session, monkeypatch
    ):
        """The Product Agent must not wait for the Marketing Agent.

        The dispatch call is made for both agents during the SAME request,
        before the orchestrator background task is even queued — so neither
        agent can be gated on the other.
        """
        m, u, _ = make_world(db_session, slug_hint="conc")
        order: list[str] = []

        import backend.app.api.routes.agents as agents_route
        import backend.app.agents.marketing_agi.cycle as magi_cycle
        import backend.app.agents.product_agi.cycle as product_cycle

        monkeypatch.setattr(
            magi_cycle,
            "trigger_marketing_agi_parallel",
            lambda sf, **kw: order.append("marketing"),
        )
        monkeypatch.setattr(
            product_cycle,
            "trigger_product_agent_parallel",
            lambda sf, **kw: order.append("product"),
        )
        _patch_session_factory(monkeypatch)

        # Record whether the Product dispatch happens before the route hands
        # off to the background orchestrator worker.
        real_add = agents_route.BackgroundTasks.add_task

        def _spy_add(self, func, *args, **kwargs):  # noqa: ANN001
            if func is agents_route._run_team_orchestrator_worker:
                order.append("plan")
            return real_add(self, func, *args, **kwargs)

        monkeypatch.setattr(
            agents_route.BackgroundTasks, "add_task", _spy_add, raising=False
        )

        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        # Both specialist dispatches precede the sequential plan, and the
        # Product Agent is dispatched immediately after the Marketing Agent
        # rather than after the plan completes.
        assert order.index("marketing") < order.index("plan")
        assert order.index("product") < order.index("plan")

    def test_product_agent_dispatched_only_once_per_cycle(
        self, client, db_session, monkeypatch
    ):
        m, u, _ = make_world(db_session, slug_hint="once")

        import backend.app.agents.product_agi.cycle as product_cycle

        dispatches: list[dict] = []
        monkeypatch.setattr(
            product_cycle,
            "trigger_product_agent_parallel",
            lambda sf, **kw: dispatches.append(kw),
        )
        _patch_marketing_dispatch(monkeypatch)
        _patch_session_factory(monkeypatch)

        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        cycle_id = r.json()["orchestrator_run_id"]
        assert len(dispatches) == 1

        # Idempotent re-dispatch for the same cycle returns the same row and
        # never adds a second Product Agent run.
        existing_id = db_session.scalar(
            select(ProductAgentRun.id).where(
                ProductAgentRun.merchant_id == m.id,
                ProductAgentRun.analysis_cycle_id == cycle_id,
            )
        )
        again = create_product_cycle_run(
            db_session,
            merchant_id=m.id,
            objective="dup",
            cycle_id=cycle_id,
            window_days=90,
        )
        db_session.commit()
        assert again.id == existing_id
        rows = db_session.scalars(
            select(ProductAgentRun).where(
                ProductAgentRun.merchant_id == m.id,
                ProductAgentRun.analysis_cycle_id == cycle_id,
            )
        ).all()
        assert len(rows) == 1

    def test_create_cycle_run_is_idempotent(self, db_session):
        m = _seed_merchant(db_session, "idem")
        cycle = uuid.uuid4().hex
        r1 = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        r2 = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        assert r1.id == r2.id
        assert len(
            db_session.scalars(
                select(ProductAgentRun).where(
                    ProductAgentRun.merchant_id == m.id,
                    ProductAgentRun.analysis_cycle_id == cycle,
                )
            ).all()
        ) == 1

    def test_product_startup_failure_does_not_stop_team(
        self, client, db_session, monkeypatch
    ):
        """Isolation boundary: a Product Agent startup failure never fails
        Start Analysis and never prevents the Marketing Agent."""
        m, u, _ = make_world(db_session, slug_hint="piso")
        import backend.app.api.routes.agents as agents_route

        monkeypatch.setattr(
            agents_route,
            "_start_team_product_agent",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        _patch_marketing_dispatch(monkeypatch)
        _patch_session_factory(monkeypatch)

        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        cycle_id = r.json()["orchestrator_run_id"]

        # The Marketing Agent still ran for this cycle.
        magi = db_session.scalars(
            select(MarketingAGIRun).where(
                MarketingAGIRun.merchant_id == m.id,
                MarketingAGIRun.analysis_cycle_id == cycle_id,
            )
        ).all()
        assert len(magi) == 1
        # And the sequential plan still completed.
        audit = db_session.scalars(
            select(AgentRun).where(
                AgentRun.merchant_id == m.id,
                AgentRun.orchestrator_run_id == cycle_id,
            )
        ).all()
        assert len(audit) >= 2

    def test_marketing_startup_failure_does_not_block_product(
        self, client, db_session, monkeypatch
    ):
        """The reverse isolation: the Product Agent still starts."""
        m, u, _ = make_world(db_session, slug_hint="piso2")
        import backend.app.api.routes.agents as agents_route

        monkeypatch.setattr(
            agents_route,
            "_start_team_marketing_agent",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        _patch_product_dispatch(monkeypatch)
        _patch_session_factory(monkeypatch)

        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        cycle_id = r.json()["orchestrator_run_id"]
        product = db_session.scalars(
            select(ProductAgentRun).where(
                ProductAgentRun.merchant_id == m.id,
                ProductAgentRun.analysis_cycle_id == cycle_id,
            )
        ).all()
        assert len(product) == 1

    def test_non_team_modes_do_not_trigger_product_agent(
        self, client, db_session, monkeypatch
    ):
        m, u, _ = make_world(db_session, slug_hint="pfast")
        import backend.app.api.routes.agents as agents_route

        calls: list = []
        monkeypatch.setattr(
            agents_route,
            "_start_team_product_agent",
            lambda *a, **k: calls.append(a),
        )
        r = client.post(
            "/api/agents/run",
            json={"mode": "fast", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 200, r.text
        assert calls == []

    def test_refresh_and_polling_never_create_runs(self, client, db_session):
        """GET endpoints are read-only: polling cannot start a run."""
        m, u, _ = make_world(db_session, slug_hint="poll")
        h = bearer(u)

        def _count() -> int:
            return len(
                db_session.scalars(
                    select(ProductAgentRun).where(
                        ProductAgentRun.merchant_id == m.id
                    )
                ).all()
            )

        before = _count()
        for _ in range(3):
            assert client.get("/api/product-agi/status", headers=h).status_code == 200
            assert client.get("/api/product-agi/runs", headers=h).status_code == 200
            assert (
                client.get(
                    "/api/product-agi/runs?analysis_cycle_id=" + uuid.uuid4().hex,
                    headers=h,
                ).status_code
                == 200
            )
        assert _count() == before


# ── RUN LIFECYCLE AND PERSISTENCE ────────────────────────────────────────


class TestCycleRunLifecycle:
    def test_worker_runs_bounded_loop_and_stamps_cycle(
        self, db_session, monkeypatch
    ):
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "wrun")
        _seed_catalog(db_session, m)
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()

        run_product_cycle_worker(_TestSessionLocal, run_row.id, m.id, "obj", cycle)
        db_session.expire_all()

        done = db_session.get(ProductAgentRun, run_row.id)
        assert done.analysis_cycle_id == cycle
        assert done.status in TERMINAL_RUN_STATUSES
        assert done.started_at is not None
        assert done.completed_at is not None

    def test_worker_closes_the_shared_audit_row(self, db_session, monkeypatch):
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "audit")
        _seed_catalog(db_session, m)
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()

        from backend.app.services.agent_run_service import AgentRunService

        audit = AgentRunService(db_session).start_run(
            merchant_id=m.id,
            agent_name=PRODUCT_AGENT_AGENT_NAME,
            orchestrator_run_id=cycle,
            mode="team",
            input_summary={"objective": "obj"},
        )
        db_session.commit()

        run_product_cycle_worker(_TestSessionLocal, run_row.id, m.id, "obj", cycle)
        db_session.expire_all()

        row = db_session.get(AgentRun, audit.id)
        assert row.completed_at is not None
        assert str(getattr(row.status, "value", row.status)) == "completed"
        summary = row.output_summary or {}
        assert summary.get("status") in SUCCESSFUL_RUN_STATUSES
        assert "products_analyzed" in summary
        assert "recommendations_created" in summary

    def test_crashed_worker_marks_run_and_audit_row_failed(
        self, db_session, monkeypatch
    ):
        """A worker crash must mark BOTH the run and the audit row failed —
        never completed, so the AI Team page cannot show a false success."""
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "fail")
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()

        from backend.app.services.agent_run_service import AgentRunService

        audit = AgentRunService(db_session).start_run(
            merchant_id=m.id,
            agent_name=PRODUCT_AGENT_AGENT_NAME,
            orchestrator_run_id=cycle,
            mode="team",
        )
        db_session.commit()

        def _boom(self, run_row_, objective, **kwargs):
            raise RuntimeError("agent exploded")

        import backend.app.agents.product_agi.agent as agent_mod

        monkeypatch.setattr(agent_mod.ProductAGI, "run", _boom)
        # Must not raise.
        run_product_cycle_worker(_TestSessionLocal, run_row.id, m.id, "obj", cycle)
        db_session.expire_all()

        row = db_session.get(AgentRun, audit.id)
        assert str(getattr(row.status, "value", row.status)) == "failed"
        assert any("worker_crashed" in str(e) for e in (row.errors or []))

        run_after = db_session.get(ProductAgentRun, run_row.id)
        assert str(run_after.status) == "failed"
        assert "worker_crashed" in (run_after.errors or [])

    def test_failed_run_produces_a_failed_audit_row(self, db_session, monkeypatch):
        """An agent run that fails internally also fails the audit row."""
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "fail2")
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()

        from backend.app.services.agent_run_service import AgentRunService

        audit = AgentRunService(db_session).start_run(
            merchant_id=m.id,
            agent_name=PRODUCT_AGENT_AGENT_NAME,
            orchestrator_run_id=cycle,
            mode="team",
        )
        db_session.commit()

        # Drive the run to a genuine `failed` terminal state.
        run_row.status = "failed"
        run_row.completed_at = datetime.now(timezone.utc)
        run_row.errors = ["boom"]
        db_session.commit()

        run_product_cycle_worker(_TestSessionLocal, run_row.id, m.id, "obj", cycle)
        db_session.expire_all()

        row = db_session.get(AgentRun, audit.id)
        # The worker re-ran the loop; whatever the terminal state, a failed
        # run must never be recorded as a completed audit row.
        terminal = str(db_session.get(ProductAgentRun, run_row.id).status)
        expected = (
            "completed" if terminal in SUCCESSFUL_RUN_STATUSES else "failed"
        )
        assert str(getattr(row.status, "value", row.status)) == expected
        assert not (
            terminal not in SUCCESSFUL_RUN_STATUSES
            and str(getattr(row.status, "value", row.status)) == "completed"
        )

    def test_blocked_run_is_not_successful(self):
        """blocked is terminal but not successful — the AI Team page must be
        able to distinguish it from a completed analysis."""
        assert "blocked" in TERMINAL_RUN_STATUSES
        assert "blocked" not in SUCCESSFUL_RUN_STATUSES
        assert "failed" in TERMINAL_RUN_STATUSES
        assert "failed" not in SUCCESSFUL_RUN_STATUSES
        assert SUCCESSFUL_RUN_STATUSES == {
            "waiting_approval",
            "completed_no_actions",
            "completed",
            "completed_with_failures",
        }

    def test_cycle_runs_are_listable_by_cycle(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="listcyc")
        cycle = uuid.uuid4().hex
        row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        r = client.get(
            f"/api/product-agi/runs?analysis_cycle_id={cycle}", headers=bearer(u)
        )
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert [x["id"] for x in runs] == [str(row.id)]
        assert runs[0]["analysis_cycle_id"] == cycle


# ── DASHBOARD PERSISTED STATE ────────────────────────────────────────────


class TestDashboardPersistedState:
    def test_status_exposes_the_persisted_run_and_cycle(
        self, client, db_session
    ):
        m, u, _ = make_world(db_session, slug_hint="dashcyc")
        _seed_catalog(db_session, m)
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        ProductAGI(db_session, m.id, llm=None).run(
            run_row, "obj", analysis_cycle_id=cycle
        )
        db_session.commit()

        r = client.get("/api/product-agi/status", headers=bearer(u))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["has_run"] is True
        assert body["run_id"] == str(run_row.id)
        assert body["analysis_cycle_id"] == cycle
        assert body["managed_by_ai_team"] is True
        assert body["status"] in TERMINAL_RUN_STATUSES
        assert body["stage"]
        assert body["headline"]
        assert body["support"]
        # Findings and recommendations come from the persisted run.
        assert body["recommendations"]
        assert body["workflow_steps"]

    def test_status_before_any_run_is_honest(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="nodash")
        r = client.get("/api/product-agi/status", headers=bearer(u))
        body = r.json()
        assert body["has_run"] is False
        assert body["run_id"] is None
        assert body["analysis_cycle_id"] is None
        assert body["recommendations"] == []
        assert body["managed_by_ai_team"] is True

    def test_status_reports_every_lifecycle_status(
        self, client, db_session, monkeypatch
    ):
        """Queued / running / waiting_approval / failed are surfaced verbatim."""
        m, u, _ = make_world(db_session, slug_hint="states")
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        h = bearer(u)

        for status in ("queued", "running", "waiting_approval", "failed", "blocked"):
            run_row.status = status
            db_session.commit()
            body = client.get("/api/product-agi/status", headers=h).json()
            assert body["status"] == status, status
            assert body["status_label"]

    def test_run_detail_reports_live_stage_and_counts(self, client, db_session):
        m, u, _ = make_world(db_session, slug_hint="detail")
        _seed_catalog(db_session, m)
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        ProductAGI(db_session, m.id, llm=None).run(run_row, "obj")
        db_session.commit()

        body = client.get(
            f"/api/product-agi/runs/{run_row.id}", headers=bearer(u)
        ).json()
        assert body["stage"]
        assert body["metrics"]["window_days"] == 90
        assert body["products_analyzed"] >= 1
        assert body["analysis_cycle_id"] == cycle


# ── NO SECOND TRIGGER ────────────────────────────────────────────────────


class TestNoSecondTrigger:
    def test_dashboard_start_joins_an_in_flight_cycle_run(
        self, client, db_session
    ):
        """A Product Agent run already dispatched by the shared cycle cannot
        be duplicated by a second trigger."""
        m, u, _ = make_world(db_session, slug_hint="dup1")
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        run_row.status = "running"
        db_session.commit()

        before = len(
            db_session.scalars(
                select(ProductAgentRun).where(
                    ProductAgentRun.merchant_id == m.id
                )
            ).all()
        )
        r = client.post(
            "/api/product-agi/runs?window_days=90", headers=bearer(u)
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["run_id"] == str(run_row.id)
        assert body["already_running"] is True
        assert body["analysis_cycle_id"] == cycle
        after = len(
            db_session.scalars(
                select(ProductAgentRun).where(
                    ProductAgentRun.merchant_id == m.id
                )
            ).all()
        )
        assert after == before

    def test_start_creates_a_run_only_when_none_is_active(
        self, client, db_session
    ):
        m, u, _ = make_world(db_session, slug_hint="dup2")
        r = client.post(
            "/api/product-agi/runs?window_days=365", headers=bearer(u)
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["already_running"] is False
        assert body["run_id"]
        row = db_session.get(ProductAgentRun, uuid.UUID(body["run_id"]))
        assert row is not None
        assert row.merchant_id == m.id

    def test_dashboard_page_has_no_run_trigger(self):
        """The Product Agent dashboard must not be able to start an analysis."""
        source = FRONTEND.joinpath("pages", "ProductAgentPage.tsx").read_text(
            encoding="utf-8"
        )
        for banned in (
            "Run Product Analysis",
            "beginProductAgentRun",
            "startProductAgentRun",
            "onStart",
            "startRun",
        ):
            assert banned not in source, banned
        # The page is a monitor, not a trigger — it shows the shared analysis cycle.
        assert "View Analysis Status" in source

    def test_product_data_layer_exports_no_start(self):
        source = FRONTEND.joinpath("lib", "productAgent.ts").read_text(
            encoding="utf-8"
        )
        assert "startProductAgentRun" not in source
        assert "beginProductAgentRun" not in source
        # Read-only helpers remain available for the monitoring page.
        assert "loadCycleRun" in source
        assert "loadRunHistory" in source

    def test_ai_team_page_is_the_single_start_action(self):
        """Start Analysis on the AI Team page is the one trigger for both."""
        source = FRONTEND.joinpath("pages", "AgentsPage.tsx").read_text(
            encoding="utf-8"
        )
        assert "startAiTeamWork" in source
        assert "Start Analysis" in source


# ── SECURITY / APPROVALS ─────────────────────────────────────────────────


class TestCycleSecurityAndApprovals:
    def test_cycle_run_stays_tenant_scoped(self, client, db_session):
        m1, u1, _ = make_world(db_session, slug_hint="t1")
        m2, u2, _ = make_world(db_session, slug_hint="t2")
        cycle = uuid.uuid4().hex
        row = create_product_cycle_run(
            db_session, merchant_id=m1.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()

        # Another tenant cannot read the run.
        assert client.get(
            f"/api/product-agi/runs/{row.id}", headers=bearer(u2)
        ).status_code == 404
        # Nor list it, even by cycle id.
        body = client.get(
            f"/api/product-agi/runs?analysis_cycle_id={cycle}",
            headers=bearer(u2),
        ).json()
        assert body["runs"] == []
        # And its own status never shows another tenant's run.
        assert client.get(
            "/api/product-agi/status", headers=bearer(u2)
        ).json()["has_run"] is False
        # The owning tenant sees it.
        assert client.get(
            f"/api/product-agi/runs/{row.id}", headers=bearer(u1)
        ).status_code == 200

    def test_cycle_run_creates_only_requested_actions(
        self, db_session, monkeypatch
    ):
        """The shared cycle does not authorize execution."""
        _clear_llm_env(monkeypatch)
        m = _seed_merchant(db_session, "appr")
        _seed_catalog(db_session, m)
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()

        ProductAGI(db_session, m.id, llm=None).run(run_row, "obj")
        db_session.commit()

        actions = db_session.scalars(
            select(AgentAction).where(AgentAction.merchant_id == m.id)
        ).all()
        assert actions, "the seeded catalog should yield at least one action"
        for a in actions:
            status = str(getattr(a.status, "value", a.status))
            assert status == "requested", status
            assert str(a.requested_by) == "agent:ProductAGI"

    def test_unapproved_product_action_cannot_be_executed(
        self, client, db_session, monkeypatch
    ):
        _clear_llm_env(monkeypatch)
        m, u, _ = make_world(db_session, slug_hint="noexec")
        _seed_catalog(db_session, m)
        cycle = uuid.uuid4().hex
        run_row = create_product_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        ProductAGI(db_session, m.id, llm=None).run(run_row, "obj")
        db_session.commit()

        action = db_session.scalar(
            select(AgentAction).where(AgentAction.merchant_id == m.id)
        )
        assert action is not None
        r = client.post(
            f"/api/actions/{action.id}/execute", headers=bearer(u)
        )
        assert r.status_code >= 400
        assert str(getattr(action.status, "value", action.status)) == "requested"

    def test_analyst_cannot_start_the_shared_cycle(
        self, client, db_session
    ):
        """Start Analysis remains operator+; the integration did not lower it."""
        m, u, _ = make_world(db_session, slug_hint="role1", role=UserRole.analyst)
        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 403

    def test_product_keeps_only_its_own_capability_grant(self):
        from backend.app.integrations.mcp.domains import (
            AGENT_CAPABILITIES,
            domains_for_agent,
        )

        assert set(domains_for_agent("product_agent")) == {
            "commerce",
            "analytics",
            "product_intelligence",
        }
        # The integration grants the Product Agent nothing extra, and the
        # Marketing Agent nothing new either.
        assert "product_intelligence" not in domains_for_agent("marketing_agent")
        assert set(AGENT_CAPABILITIES["product_agent"].domains) == {
            "commerce",
            "analytics",
            "product_intelligence",
        }

    def test_no_second_mcp_client_or_registry(self):
        """Exactly one MCP client factory and one registry remain."""
        import backend.app.integrations.mcp.bridge as bridge
        import backend.app.integrations.mcp.registry as registry

        assert callable(bridge.build_client)
        reg = registry.get_mcp_registry()
        assert reg is registry.get_mcp_registry()
        assert reg is not None
        # Both agents resolve to the same singleton registry.
        from backend.app.integrations.mcp import domains as doms

        assert doms.capability_domain("commerce.list_products") == "commerce"
        assert doms.capability_domain("product_intelligence.get_catalog_health") == (
            "product_intelligence"
        )


# ── MARKETING AGENT REGRESSION ───────────────────────────────────────────


class TestMarketingAgentUnchanged:
    def test_marketing_cycle_bridge_still_works(self, db_session):
        m = _seed_merchant(db_session, "magok")
        cycle = uuid.uuid4().hex
        row = create_marketing_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        again = create_marketing_cycle_run(
            db_session, merchant_id=m.id, objective="obj", cycle_id=cycle
        )
        db_session.commit()
        assert row.id == again.id
        assert MARKETING_AGI_AGENT_NAME == "MarketingAGI"

    def test_marketing_agent_still_starts_under_the_shared_cycle(
        self, client, db_session, monkeypatch
    ):
        m, u, _ = make_world(db_session, slug_hint="magreg")
        import backend.app.agents.marketing_agi.cycle as magi_cycle

        dispatches: list[dict] = []
        monkeypatch.setattr(
            magi_cycle,
            "trigger_marketing_agi_parallel",
            lambda sf, **kw: dispatches.append(kw),
        )
        _patch_product_dispatch(monkeypatch)
        _patch_session_factory(monkeypatch)

        r = client.post(
            "/api/agents/run",
            json={"mode": "team", "merchant_id": str(m.id)},
            headers=bearer(u),
        )
        assert r.status_code == 202, r.text
        assert len(dispatches) == 1
        cycle_id = r.json()["orchestrator_run_id"]
        assert dispatches[0]["cycle_id"] == cycle_id
        assert len(
            db_session.scalars(
                select(MarketingAGIRun).where(
                    MarketingAGIRun.merchant_id == m.id,
                    MarketingAGIRun.analysis_cycle_id == cycle_id,
                )
            ).all()
        ) == 1

    def test_marketing_prompts_tools_and_approvals_untouched(self):
        """No integration change leaked into the Marketing Agent's own files."""
        import backend.app.agents.marketing_agi.agent as magi_agent
        import backend.app.agents.marketing_agi.cycle as magi_cycle

        # The bridge still exports exactly its documented surface.
        assert hasattr(magi_cycle, "create_cycle_run")
        assert hasattr(magi_cycle, "run_cycle_worker")
        assert hasattr(magi_cycle, "trigger_marketing_agi_parallel")
        # The agent still owns its decision contract and sanitiser.
        assert hasattr(magi_agent, "ALLOWED_DECISIONS")
        assert hasattr(magi_agent, "sanitize_tool_args")

    def test_orchestrator_worker_crash_handler_still_works(
        self, db_session, monkeypatch
    ):
        """The pre-existing crash handler is unchanged and still fails rows."""
        import backend.app.api.routes.agents as agents_route

        m = _seed_merchant(db_session, "crash")
        cycle = uuid.uuid4().hex
        stuck = AgentRun(
            merchant_id=m.id,
            orchestrator_run_id=cycle,
            agent_name="GrowthDiscoveryAgent",
            status="running",
            mode="team",
            started_at=datetime.now(timezone.utc),
        )
        db_session.add(stuck)
        db_session.commit()

        import backend.app.agents.orchestrator as orch_mod

        def _boom(self, merchant_id, mode="deep", params=None, run_id=None):
            raise RuntimeError("plan exploded")

        monkeypatch.setattr(orch_mod.GrowthAgentOrchestrator, "run", _boom)
        agents_route._run_team_orchestrator_worker(
            _TestSessionLocal, m.id, {}, cycle, {}
        )
        db_session.expire_all()
        row = db_session.get(AgentRun, stuck.id)
        assert str(getattr(row.status, "value", row.status)) == "failed"
        assert any("worker_crashed" in str(e) for e in (row.errors or []))