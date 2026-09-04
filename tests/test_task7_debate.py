from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from backend.app.agents.orchestrator import GrowthAgentOrchestrator
from backend.app.models.agent_debate import AgentDebate, AgentFinding, AgentTask
from backend.app.models.customer import Customer
from backend.app.models.enums import (
    Currency,
    CustomerSegment,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
    DebateStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.order import Order
from backend.app.models.payment import Payment


def _merchant(db, name: str) -> Merchant:
    merchant = Merchant(
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        email=f"{name.lower()}@task7.test",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(merchant)
    db.commit()
    return merchant


def _captured_commerce(db, merchant: Merchant, count: int) -> None:
    now = datetime.now(timezone.utc)
    for index in range(count):
        customer = Customer(
            merchant_id=merchant.id,
            name=f"Customer {index}",
            email=f"customer-{index}-{uuid.uuid4().hex[:6]}@task7.test",
            segment=CustomerSegment.new,
            total_orders=1,
            total_spend=Decimal("100.00"),
        )
        db.add(customer)
        db.flush()
        order = Order(
            merchant_id=merchant.id,
            customer_id=customer.id,
            order_number=f"order_TX{uuid.uuid4().hex[:12]}",
            status=OrderStatus.paid,
            subtotal=Decimal("100.00"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("100.00"),
            currency=Currency.INR,
            created_at=now - timedelta(minutes=index),
        )
        db.add(order)
        db.flush()
        db.add(Payment(
            merchant_id=merchant.id,
            order_id=order.id,
            provider=PaymentProvider.razorpay,
            provider_payment_id=f"pay_TX{uuid.uuid4().hex[:12]}",
            amount=Decimal("100.00"),
            currency=Currency.INR,
            status=PaymentStatus.captured,
            paid_at=now - timedelta(minutes=index),
        ))
    db.commit()


def test_growth_team_persists_rag_context_and_concludes_insufficient_evidence(db_session):
    merchant = _merchant(db_session, "Task7Thin")
    _captured_commerce(db_session, merchant, 1)

    summary = GrowthAgentOrchestrator(db_session).run(
        merchant.id,
        mode="growth_team",
        params={"objective": "Find revenue growth opportunities", "window_days": 30},
    )

    debates = list(db_session.scalars(
        select(AgentDebate).where(AgentDebate.merchant_id == merchant.id)
    ).all())
    assert len(debates) == 1
    debate = debates[0]
    assert debate.context["rag_context"]["status"] == "insufficient_data"
    assert debate.status == DebateStatus.concluded
    assert "INSUFFICIENT EVIDENCE" in (debate.final_synthesis or "")
    assert summary.status == "completed"
    assert all(
        agent["output"]["evidence_context"]["merchant_id"] == str(merchant.id)
        for agent in summary.agents_run
    )
    assert all(
        agent["output"].get("recommendation") is None
        for agent in summary.agents_run
        if agent["agent"] != "ManagerAgent"
    )
    assert db_session.scalars(
        select(AgentFinding).where(AgentFinding.merchant_id == merchant.id)
    ).first() is None


def test_growth_team_uses_real_rag_evidence_for_sufficient_debate(db_session):
    merchant = _merchant(db_session, "Task7Ready")
    _captured_commerce(db_session, merchant, 3)

    summary = GrowthAgentOrchestrator(db_session).run(
        merchant.id,
        mode="growth_team",
        params={"objective": "Find revenue growth opportunities", "window_days": 30},
    )

    debate = db_session.scalar(
        select(AgentDebate).where(AgentDebate.merchant_id == merchant.id)
    )
    assert debate is not None
    assert debate.context["rag_context"]["status"] == "ready"
    assert debate.context["rag_context"]["data_sufficiency"]["available"] == 3
    tasks = list(db_session.scalars(
        select(AgentTask).where(AgentTask.debate_id == debate.id)
    ).all())
    assert tasks
    assert all(task.input_data["objective"] == "Find revenue growth opportunities" for task in tasks)
    assert summary.status == "completed"
