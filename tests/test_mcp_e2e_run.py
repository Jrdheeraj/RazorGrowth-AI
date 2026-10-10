"""End-to-end Marketing Agent run through the MCP tool connectivity layer.

This is the acceptance proof for the migration: ONE real run of the
autonomous Marketing Agent must

    observe business data
      → use MCP tools
      → retrieve evidence (agentic RAG)
      → reason (Groq when configured, bounded deterministic loop otherwise)
      → identify an opportunity
      → prepare an action
      → verify it
      → request human approval
      → wait for approval

Nothing is stubbed inside the agent: the tools are the real platform tools,
the data is a real seeded commerce history, the verification and the
approval row are real rows. Only the LLM is optionally absent — and when
absent the agent says so rather than fabricating reasoning.

Run it with a real key to exercise Groq:

    LLM_PROVIDER=groq GROQ_API_KEY=... python -m tests.test_mcp_e2e_run
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

# Test-environment defaults, mirroring tests/conftest.py.
os.environ.setdefault("AUTH_MODE", "optional")
os.environ.setdefault(
    "AUTH_SECRET_KEY", "test-only-secret-key-do-not-use-in-production"
)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ["RAZORPAY_ENABLED"] = "false"
os.environ["RAZORPAY_TEST_MODE"] = "false"
os.environ["REAL_TEST_INTEGRATION_ENABLED"] = "false"
os.environ["RAZORPAY_WEBHOOK_SECRET"] = ""

from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.app.db.base import Base  # noqa: E402
import backend.app.models  # noqa: F401,E402  (register every table)
from backend.app.models.customer import Customer  # noqa: E402
from backend.app.models.enums import (  # noqa: E402
    AgentActionStatus,
    Currency,
    CustomerSegment,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.merchant import Merchant  # noqa: E402
from backend.app.models.order import Order  # noqa: E402
from backend.app.models.payment import Payment  # noqa: E402
from backend.app.models.agent_action import AgentAction  # noqa: E402
from backend.app.models.marketing_agi import MarketingAGIEvent  # noqa: E402


def build_engine():
    """Build an in-memory engine with the suite's JSONB → JSON swap.

    Reuses the exact helper the pytest suite uses, so this run sees the
    same schema it does — no bespoke test-only database.
    """
    from tests.conftest import _make_test_engine

    return _make_test_engine()


# ── seeded commerce history ────────────────────────────────────────────


def seed_world(db, slug: str = "e2e") -> Merchant:
    """A real merchant with the signal the agent should act on.

    Six customers with real captured orders who have all gone quiet (no
    orders in the last 45 days) plus a couple of failed payments — i.e.
    genuine, in-the-database reasons to run a win-back / recovery
    campaign.
    """
    slug = f"{slug}-{uuid.uuid4().hex[:8]}"
    merchant = Merchant(
        name="E2E Retail",
        slug=slug,
        email=f"owner@{slug}.test",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(merchant)
    db.flush()

    now = datetime.now(timezone.utc)
    for i in range(6):
        customer = Customer(
            merchant_id=merchant.id,
            name=f"Customer {i}",
            email=f"c{i}@{slug}.test",
            segment=CustomerSegment.new,
            total_orders=2,
            total_spend=Decimal("5000") + Decimal(500 * i),
        )
        db.add(customer)
        db.flush()
        # Two real captured orders each, 75 and 70 days ago — well outside
        # the 45-day win-back window, so these customers read as inactive.
        for j, days_ago in enumerate((75, 70)):
            _order(db, merchant, customer, i, j, days_ago, captured=True)

    # Two genuinely failed payments => real recoverable value.
    for i in range(3):
        customer = db.scalar(
            select(Customer).where(
                Customer.merchant_id == merchant.id,
                Customer.name == f"Customer {i}",
            )
        )
        _order(db, merchant, customer, i, 99, 5, captured=False)

    db.commit()
    return merchant


def _order(
    db, merchant, customer, i: int, j: int, days_ago: int, *, captured: bool
):
    """One real order + payment row, exactly as ingestion would write it."""
    now = datetime.now(timezone.utc)
    total = Decimal("2500") + Decimal(250 * i) + Decimal(100 * j)
    order = Order(
        merchant_id=merchant.id,
        customer_id=customer.id,
        order_number=f"E2E-{i}-{j}",
        status=OrderStatus.paid if captured else OrderStatus.pending,
        subtotal=total,
        discount=Decimal("0"),
        tax=Decimal("0"),
        total=total,
        currency=Currency.INR,
        created_at=now - timedelta(days=days_ago),
    )
    db.add(order)
    db.flush()
    payment = Payment(
        merchant_id=merchant.id,
        order_id=order.id,
        provider=PaymentProvider.synthetic,
        amount=total,
        currency=Currency.INR,
        status=PaymentStatus.captured if captured else PaymentStatus.failed,
        failure_code=None if captured else "BAD_CARD",
        created_at=now - timedelta(days=days_ago),
    )
    db.add(payment)
    db.flush()
    return order, payment


# ── the run ─────────────────────────────────────────────────────────────


def run_agent_cycle(verbose: bool = True) -> dict:
    """Execute one full autonomous MarketingAGI run and report the truth."""
    from backend.app.agents.marketing_agi.agent import MarketingAGI
    from backend.app.agents.marketing_agi.llm import llm_identity
    from backend.app.agents.marketing_agi.limits import LoopLimits
    from backend.app.models.marketing_agi import MarketingAGIRun
    from backend.app.integrations.mcp import bridge as mcp_bridge
    from backend.app.integrations.mcp.policy import allowlists
    from backend.app.integrations.mcp.registry import get_mcp_registry

    engine = build_engine()
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()

    merchant = seed_world(db)
    objective = "Find and prepare the highest-impact marketing work for this business"

    llm = None
    configured, provider, model = llm_identity()
    if configured:
        try:
            from backend.app.agents.marketing_agi.llm import build_marketing_llm

            llm = build_marketing_llm()
        except Exception as exc:  # pragma: no cover - key problems
            print(f"! Groq setup failed ({type(exc).__name__}) — running the "
                  "bounded deterministic loop instead")
    run_row = MarketingAGIRun(
        merchant_id=merchant.id,
        objective=objective,
        status="queued",
        phase="load_context",
    )
    db.add(run_row)
    db.commit()

    agent = MarketingAGI(db, merchant.id, llm=llm, limits=LoopLimits())
    run_row = agent.run(run_row, objective)
    db.refresh(run_row)

    state = run_row.state or {}
    events = list(
        db.scalars(
            select(MarketingAGIEvent)
            .where(MarketingAGIEvent.run_id == run_row.id)
            .order_by(MarketingAGIEvent.seq)
        ).all()
    )
    actions = list(
        db.scalars(
            select(AgentAction).where(AgentAction.merchant_id == merchant.id)
        ).all()
    )
    mcp_rows = state.get("mcp_calls", [])
    sets = allowlists()
    report = {
        "merchant": str(merchant.id),
        "run_id": str(run_row.id),
        "llm_configured": configured,
        "llm_provider": provider,
        "llm_model": model,
        "llm_used": llm is not None,
        "status": run_row.status,
        "phase": run_row.phase,
        "iterations": run_row.iterations,
        "mcp_calls": len(mcp_rows),
        "mcp_tools_registered": len(get_mcp_registry().names()),
        "mcp_read_tools": len(sets["read"]),
        "mcp_write_tools": len(sets["write"]),
        "mcp_servers": sorted({s.server for s in get_mcp_registry().all_specs()}),
        "mcp_providers_used": sorted({r["provider"] for r in mcp_rows}),
        "mcp_succeeded": sum(1 for r in mcp_rows if r["status"] == "success"),
        "mcp_refused": sum(1 for r in mcp_rows if r["status"] == "denied"),
        "mcp_failed": sum(1 for r in mcp_rows if r["status"] == "error"),
        "mcp_cached": sum(1 for r in mcp_rows if r.get("cached")),
        "mcp_evidence_count": len(state.get("evidence", [])),
        "rag_rounds": len(state.get("retrieval_log", [])),
        "observations": len(state.get("observations", [])),
        "workflow": state.get("workflow"),
        "campaign": (state.get("campaign_draft") or {}).get("name"),
        "audience_count": (state.get("campaign_draft") or {}).get("audience_count"),
        "verification_passed": (state.get("verification") or {}).get("passed"),
        "verification_failed": (state.get("verification") or {}).get("failed"),
        "prepared_action": state.get("prepared_action"),
        "action_statuses": [str(getattr(a.status, "value", a.status)) for a in actions],
        "action_approved_by": [a.approved_by for a in actions],
        "knowledge_gaps": state.get("knowledge_gaps", []),
        "llm_calls": state.get("llm_calls", 0),
        "llm_decisions": len(state.get("llm_decisions", [])),
        "llm_degraded": state.get("llm_degraded", False),
        "timing": state.get("timing", {}),
        "event_types": [e.event_type for e in events],
        "mcp_event_types": sum(
            1 for e in events if e.event_type == "mcp_tool_call"
        ),
        "errors": run_row.errors or [],
    }

    if verbose:
        _print_report(report, mcp_rows, events)
    return report


def _print_report(report: dict, mcp_rows: list[dict], events: list) -> None:
    bar = "=" * 74
    print(bar)
    print("RAZORGROWTH AI — MARKETING AGENT END-TO-END RUN (over MCP)")
    print(bar)
    print(f"merchant          : {report['merchant']}")
    print(f"run              : {report['run_id']}")
    print(f"reasoning engine : {report['llm_provider']} / {report['llm_model']} "
          f"(configured={report['llm_configured']}, used={report['llm_used']})")
    print(f"LLM calls        : {report['llm_calls']} "
          f"({report['llm_decisions']} decisions, degraded={report['llm_degraded']})")
    print(bar)
    print(f"status           : {report['status']}  (phase {report['phase']}, "
          f"{report['iterations']} iterations)")
    print(f"MCP layer        : {report['mcp_calls']} calls · "
          f"{report['mcp_tools_registered']} tools registered "
          f"({report['mcp_read_tools']} read / {report['mcp_write_tools']} write)")
    print(f"MCP servers      : {', '.join(report['mcp_servers'])}")
    print(f"MCP providers    : {', '.join(report['mcp_providers_used'])}")
    print(f"MCP outcomes     : {report['mcp_succeeded']} success · "
          f"{report['mcp_refused']} refused · {report['mcp_failed']} failed · "
          f"{report['mcp_cached']} cached")
    print(bar)
    print("MCP TOOL CALLS")
    for row in mcp_rows:
        outcome = row["status"].upper()
        extra = ""
        if row.get("error_code"):
            extra = f" · {row['error_code']}"
        if row.get("cached"):
            extra += " · cached"
        print(f"  {row['tool']:<45} {outcome:<8} {row['duration_ms']:>5}ms{extra}")
    print(bar)
    print(f"observations     : {report['observations']}")
    print(f"evidence items   : {report['mcp_evidence_count']}")
    print(f"RAG rounds       : {report['rag_rounds']}")
    print(f"workflow chosen  : {report['workflow']}")
    print(f"campaign         : {report['campaign']} "
          f"(audience {report['audience_count']})")
    print(f"verification     : passed={report['verification_passed']} "
          f"failed={report['verification_failed']}")
    print(f"prepared action  : {report['prepared_action']}")
    print(f"action statuses  : {report['action_statuses']}")
    print(f"approved by      : {report['action_approved_by']}  "
          "(must be all-None — the agent never self-approves)")
    print(f"mcp_tool_call events in live activity : {report['mcp_event_types']}")
    if report["knowledge_gaps"]:
        print(f"knowledge gaps   : {report['knowledge_gaps'][:5]}")
    if report["errors"]:
        print(f"errors           : {report['errors']}")
    print(bar)


def assert_acceptance(report: dict) -> None:
    """Fail loudly unless every acceptance criterion actually held."""
    problems = []
    if report["status"] != "waiting_approval":
        problems.append(f"status={report['status']} (expected waiting_approval)")
    if report["mcp_calls"] == 0:
        problems.append("no MCP tool calls were made")
    if report["mcp_failed"] or report["mcp_refused"]:
        problems.append(
            f"MCP failures/refusals during the run: "
            f"{report['mcp_failed']} failed / {report['mcp_refused']} refused"
        )
    if not report["observations"]:
        problems.append("no observations were made")
    if report["mcp_evidence_count"] == 0:
        problems.append("no evidence was gathered")
    if not report["rag_rounds"]:
        problems.append("the agentic RAG loop did not run")
    if not report["workflow"]:
        problems.append("no workflow was selected")
    if not report["campaign"]:
        problems.append("no campaign was prepared")
    if report["verification_passed"] is not True:
        problems.append(f"verification failed: {report['verification_failed']}")
    if not report["prepared_action"]:
        problems.append("no action was prepared")
    if report["action_statuses"] != ["requested"]:
        problems.append(
            f"action statuses {report['action_statuses']} (expected ['requested'])"
        )
    if any(report["action_approved_by"]):
        problems.append("an action was self-approved — approval boundary breached")
    if report["mcp_event_types"] == 0:
        problems.append("MCP calls are not visible in the activity stream")
    if problems:
        raise SystemExit(
            "END-TO-END ACCEPTANCE FAILED:\n  - " + "\n  - ".join(problems)
        )
    print("\nEND-TO-END ACCEPTANCE PASSED: the agent observed, used MCP tools,")
    print("gathered evidence, reasoned, identified an opportunity, prepared an")
    print("action, verified it, and is now waiting for human approval.")


if __name__ == "__main__":
    report = run_agent_cycle()
    assert_acceptance(report)
    sys.exit(0)