from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app.models.customer import Customer
from backend.app.models.enums import (
    Currency,
    CustomerSegment,
    MerchantStatus,
    OrderStatus,
    PaymentProvider,
    PaymentStatus,
)
from backend.app.models.merchant import Merchant
from backend.app.models.order import Order
from backend.app.models.payment import Payment


def _merchant(db_session, label: str) -> Merchant:
    merchant = Merchant(
        name=label,
        slug=f"{label.lower()}-{uuid.uuid4().hex[:8]}",
        email=f"{label.lower()}@analytics.test",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db_session.add(merchant)
    db_session.commit()
    return merchant


def _commerce_rows(db_session, merchant: Merchant, *, payment_status=PaymentStatus.captured):
    customer = Customer(
        merchant_id=merchant.id,
        name="Real Test Customer",
        email=f"customer-{uuid.uuid4().hex[:8]}@analytics.test",
        segment=CustomerSegment.new,
    )
    db_session.add(customer)
    db_session.flush()
    order = Order(
        merchant_id=merchant.id,
        customer_id=customer.id,
        order_number=f"order_TX{uuid.uuid4().hex[:12]}",
        status=OrderStatus.paid if payment_status == PaymentStatus.captured else OrderStatus.pending,
        subtotal=Decimal("100.00"),
        discount=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=Decimal("100.00"),
        currency=Currency.INR,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(order)
    db_session.flush()
    payment = Payment(
        merchant_id=merchant.id,
        order_id=order.id,
        provider=PaymentProvider.razorpay,
        provider_payment_id=f"pay_TX{uuid.uuid4().hex[:12]}",
        amount=Decimal("100.00"),
        currency=Currency.INR,
        status=payment_status,
        paid_at=datetime.now(timezone.utc) if payment_status == PaymentStatus.captured else None,
    )
    db_session.add(payment)
    db_session.commit()
    return customer, order, payment


def test_analytics_endpoints_return_real_scoped_rows(client: TestClient, db_session):
    merchant = _merchant(db_session, "RealData")
    customer, order, payment = _commerce_rows(db_session, merchant)

    overview = client.get(f"/api/analytics/overview?merchant_id={merchant.id}")
    assert overview.status_code == 200
    assert overview.json()["revenue"]["current_period"] == "100.00"

    revenue = client.get(f"/api/analytics/revenue?merchant_id={merchant.id}")
    assert revenue.status_code == 200
    assert revenue.json()["data"][-1]["value"] == "100.00"

    transactions = client.get(f"/api/analytics/transactions?merchant_id={merchant.id}")
    assert transactions.status_code == 200
    row = transactions.json()["transactions"][0]
    assert row["provider_payment_id"] == payment.provider_payment_id
    assert row["order_id"] == str(order.id)
    assert row["order_number"] == order.order_number

    customers = client.get(f"/api/analytics/customers?merchant_id={merchant.id}")
    assert customers.status_code == 200
    assert customers.json()["customers"][0]["id"] == str(customer.id)

    orders = client.get(f"/api/analytics/orders?merchant_id={merchant.id}")
    assert orders.status_code == 200
    assert orders.json()["orders"][0]["order_number"] == order.order_number


def test_analytics_isolates_merchants_and_excludes_failed_revenue(
    client: TestClient, db_session
):
    merchant = _merchant(db_session, "Scoped")
    other = _merchant(db_session, "Other")
    _commerce_rows(db_session, merchant, payment_status=PaymentStatus.failed)
    _, other_order, other_payment = _commerce_rows(db_session, other)

    revenue = client.get(f"/api/analytics/revenue?merchant_id={merchant.id}")
    assert revenue.status_code == 200
    assert revenue.json()["data"] == []

    transactions = client.get(f"/api/analytics/transactions?merchant_id={merchant.id}")
    assert transactions.status_code == 200
    assert transactions.json()["total"] == 1
    assert transactions.json()["transactions"][0]["provider_payment_id"] != other_payment.provider_payment_id
    assert transactions.json()["transactions"][0]["order_id"] != str(other_order.id)


def test_growth_radar_reports_real_metrics_and_insufficient_data(
    client: TestClient, db_session
):
    merchant = _merchant(db_session, "Radar")
    _, order, payment = _commerce_rows(db_session, merchant)

    response = client.get(f"/api/growth/radar?merchant_id={merchant.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == str(merchant.id)
    assert body["metrics"] == {
        "captured_revenue": 100.0,
        "captured_transactions": 1,
        "successful_payments": 1,
        "failed_payments": 0,
        "total_customers": 1,
        "repeat_customers": 0,
        "total_orders": 1,
        "average_order_value": 100.0,
    }
    assert body["data_sufficiency"]["status"] == "insufficient_data"
    assert body["data_sufficiency"]["available"] == 1
    assert body["signals"] == []
    assert payment.provider_payment_id not in body["data_sufficiency"]["message"]
    assert order.order_number.startswith("order_TX")


def test_rag_context_contains_verified_radar_evidence_and_is_tenant_scoped(
    db_session,
):
    from backend.app.services.rag_context import RAGContextService

    merchant = _merchant(db_session, "RagA")
    other = _merchant(db_session, "RagB")
    _commerce_rows(db_session, merchant)
    _commerce_rows(db_session, other)

    result = RAGContextService(db_session).build(
        merchant.id, "revenue growth", window_days=30
    )
    assert result["status"] == "insufficient_data"
    assert result["inference_allowed"] is False
    assert {fact["fact"] for fact in result["verified_facts"]} >= {
        "captured_revenue", "captured_transactions", "total_customers"
    }
    radar_context = [
        item for item in result["retrieved_context"]
        if item["source_type"] == "growth_radar"
    ]
    assert len(radar_context) == 1
    assert radar_context[0]["source_id"] == str(merchant.id)
    assert str(other.id) not in radar_context[0]["content_preview"]
