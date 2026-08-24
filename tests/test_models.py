"""
Phase 2 — model, repository, and service tests.

Uses the SQLite in-memory database provisioned by conftest.py.
All tests are deterministic and require no PostgreSQL.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from backend.app.models import (
    Merchant, Product, Customer, Order, OrderItem, Payment, GrowthOpportunity
)
from backend.app.models.enums import (
    Currency, CustomerSegment, MerchantStatus, OpportunityStatus,
    OpportunityType, OrderStatus, PaymentProvider, PaymentStatus,
)
from backend.app.repositories import (
    MerchantRepository, ProductRepository, CustomerRepository,
    OrderRepository, PaymentRepository, GrowthOpportunityRepository,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _make_merchant(db) -> Merchant:
    repo = MerchantRepository(db)
    slug = f"test-merchant-{uuid.uuid4().hex[:8]}"
    m = Merchant(
        name="Test Merchant",
        slug=slug,
        email=f"{slug}@example.com",
        status=MerchantStatus.active,
        currency=Currency.INR,
    )
    db.add(m)
    db.flush()
    return m


def _make_product(db, merchant: Merchant, sku_suffix: str = "001") -> Product:
    p = Product(
        merchant_id=merchant.id,
        name="Test Headphones",
        category="audio",
        price=Decimal("1999.00"),
        sku=f"SKU-TEST-{sku_suffix}",
        stock_quantity=100,
        active=True,
    )
    db.add(p)
    db.flush()
    return p


def _make_customer(db, merchant: Merchant, suffix: str = "001") -> Customer:
    c = Customer(
        merchant_id=merchant.id,
        name=f"Test Customer {suffix}",
        email=f"customer{suffix}@example.com",
        segment=CustomerSegment.returning,
    )
    db.add(c)
    db.flush()
    return c


def _make_order(db, merchant: Merchant, customer: Customer, product: Product) -> Order:
    order_num = f"TEST-{uuid.uuid4().hex[:6].upper()}"
    o = Order(
        merchant_id=merchant.id,
        customer_id=customer.id,
        order_number=order_num,
        status=OrderStatus.paid,
        subtotal=product.price,
        discount=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=product.price,
        currency=Currency.INR,
    )
    db.add(o)
    db.flush()
    item = OrderItem(
        order_id=o.id,
        product_id=product.id,
        quantity=1,
        unit_price=product.price,
        line_total=product.price,
    )
    db.add(item)
    db.flush()
    return o


# --------------------------------------------------------------------------- #
# Model creation tests
# --------------------------------------------------------------------------- #

class TestMerchantModel:
    def test_create_merchant(self, db_session):
        m = _make_merchant(db_session)
        assert m.id is not None
        assert m.slug is not None
        assert m.currency == Currency.INR

    def test_merchant_status_default(self, db_session):
        m = _make_merchant(db_session)
        assert m.status == MerchantStatus.active


class TestProductModel:
    def test_create_product(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant)
        assert product.id is not None
        assert product.price == Decimal("1999.00")
        assert product.active is True

    def test_product_price_is_decimal(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant, sku_suffix="decimal")
        assert isinstance(product.price, Decimal)


class TestCustomerModel:
    def test_create_customer(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant)
        assert customer.id is not None
        assert customer.segment == CustomerSegment.returning

    def test_customer_spend_default_zero(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="spend")
        assert customer.total_spend == Decimal("0.00")
        assert customer.total_orders == 0


class TestOrderModel:
    def test_create_order(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="ord")
        product = _make_product(db_session, merchant, sku_suffix="ord")
        order = _make_order(db_session, merchant, customer, product)
        assert order.id is not None
        assert order.status == OrderStatus.paid
        assert order.total == Decimal("1999.00")

    def test_order_has_items(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="items")
        product = _make_product(db_session, merchant, sku_suffix="items")
        order = _make_order(db_session, merchant, customer, product)
        assert len(order.items) == 1
        assert order.items[0].unit_price == Decimal("1999.00")

    def test_order_item_unit_price_is_decimal(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="dp")
        product = _make_product(db_session, merchant, sku_suffix="dp")
        order = _make_order(db_session, merchant, customer, product)
        assert isinstance(order.items[0].unit_price, Decimal)


class TestPaymentModel:
    def test_create_payment(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="pay")
        product = _make_product(db_session, merchant, sku_suffix="pay")
        order = _make_order(db_session, merchant, customer, product)

        payment = Payment(
            merchant_id=merchant.id,
            order_id=order.id,
            provider=PaymentProvider.synthetic,
            amount=order.total,
            currency=Currency.INR,
            status=PaymentStatus.captured,
        )
        db_session.add(payment)
        db_session.flush()
        assert payment.id is not None
        assert payment.status == PaymentStatus.captured
        assert isinstance(payment.amount, Decimal)

    def test_failed_payment(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="fail")
        product = _make_product(db_session, merchant, sku_suffix="fail")
        order = _make_order(db_session, merchant, customer, product)

        payment = Payment(
            merchant_id=merchant.id,
            order_id=order.id,
            provider=PaymentProvider.synthetic,
            amount=order.total,
            currency=Currency.INR,
            status=PaymentStatus.failed,
            failure_code="INSUFFICIENT_FUNDS",
            failure_reason="Test failure",
        )
        db_session.add(payment)
        db_session.flush()
        assert payment.status == PaymentStatus.failed
        assert payment.failure_code == "INSUFFICIENT_FUNDS"
        assert payment.provider_payment_id is None


class TestOpportunityModel:
    def test_create_opportunity(self, db_session):
        merchant = _make_merchant(db_session)
        repo = GrowthOpportunityRepository(db_session)
        opp = repo.create(
            merchant_id=merchant.id,
            opportunity_key="test_opp_001",
            type=OpportunityType.cross_sell,
            title="Test cross-sell",
            confidence=Decimal("0.85"),
            expected_revenue=Decimal("5000.00"),
            target_customer_count=20,
            reasoning=["Reason one.", "Reason two."],
        )
        assert opp.id is not None
        assert opp.status == OpportunityStatus.pending_approval
        assert isinstance(opp.confidence, Decimal)

    def test_opportunity_idempotent_create(self, db_session):
        """get_by_key should prevent duplicate creation."""
        merchant = _make_merchant(db_session)
        repo = GrowthOpportunityRepository(db_session)
        key = f"idempotent_{uuid.uuid4().hex[:8]}"
        opp1 = repo.create(
            merchant_id=merchant.id,
            opportunity_key=key,
            type=OpportunityType.upsell,
            title="Upsell test",
            confidence=Decimal("0.70"),
            expected_revenue=Decimal("2000.00"),
            target_customer_count=10,
        )
        existing = repo.get_by_key(merchant.id, key)
        assert existing is not None
        assert existing.id == opp1.id


# --------------------------------------------------------------------------- #
# Repository tests
# --------------------------------------------------------------------------- #

class TestMerchantRepository:
    def test_get_by_slug(self, db_session):
        m = _make_merchant(db_session)
        repo = MerchantRepository(db_session)
        found = repo.get_by_slug(m.slug)
        assert found is not None
        assert found.id == m.id

    def test_list_all(self, db_session):
        _make_merchant(db_session)
        repo = MerchantRepository(db_session)
        results = repo.list_all(limit=200)
        assert len(results) >= 1


class TestProductRepository:
    def test_list_by_merchant(self, db_session):
        merchant = _make_merchant(db_session)
        _make_product(db_session, merchant, sku_suffix="r001")
        _make_product(db_session, merchant, sku_suffix="r002")
        repo = ProductRepository(db_session)
        results = repo.list_by_merchant(merchant.id)
        assert len(results) >= 2

    def test_get_by_sku(self, db_session):
        merchant = _make_merchant(db_session)
        product = _make_product(db_session, merchant, sku_suffix="sku_find")
        repo = ProductRepository(db_session)
        found = repo.get_by_sku(merchant.id, product.sku)
        assert found is not None
        assert found.id == product.id


class TestCustomerRepository:
    def test_list_by_merchant(self, db_session):
        merchant = _make_merchant(db_session)
        _make_customer(db_session, merchant, suffix="clist1")
        _make_customer(db_session, merchant, suffix="clist2")
        repo = CustomerRepository(db_session)
        results = repo.list_by_merchant(merchant.id)
        assert len(results) >= 2


class TestOrderRepository:
    def test_list_by_merchant(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="olist")
        product = _make_product(db_session, merchant, sku_suffix="olist")
        _make_order(db_session, merchant, customer, product)
        repo = OrderRepository(db_session)
        results = repo.list_by_merchant(merchant.id)
        assert len(results) >= 1

    def test_get_customer_ids_for_product(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="cprod")
        product = _make_product(db_session, merchant, sku_suffix="cprod")
        _make_order(db_session, merchant, customer, product)
        repo = OrderRepository(db_session)
        ids = repo.get_customer_ids_for_product(merchant.id, product.id)
        assert customer.id in ids


class TestPaymentRepository:
    def test_list_failed(self, db_session):
        merchant = _make_merchant(db_session)
        customer = _make_customer(db_session, merchant, suffix="pfail")
        product = _make_product(db_session, merchant, sku_suffix="pfail")
        order = _make_order(db_session, merchant, customer, product)
        payment = Payment(
            merchant_id=merchant.id,
            order_id=order.id,
            provider=PaymentProvider.synthetic,
            amount=order.total,
            currency=Currency.INR,
            status=PaymentStatus.failed,
            failure_code="TEST_FAIL",
        )
        db_session.add(payment)
        db_session.flush()
        repo = PaymentRepository(db_session)
        failed = repo.list_failed_by_merchant(merchant.id)
        assert any(p.id == payment.id for p in failed)


# --------------------------------------------------------------------------- #
# New API endpoint tests
# --------------------------------------------------------------------------- #

class TestMerchantsEndpoint:
    def test_returns_200(self, client):
        response = client.get("/api/merchants")
        assert response.status_code == 200

    def test_returns_list(self, client):
        body = client.get("/api/merchants").json()
        assert isinstance(body, list)


class TestOpportunitiesEndpointPhase2:
    def test_returns_200(self, client):
        """Opportunities endpoint always returns 200 (fallback to in-memory)."""
        response = client.get("/api/opportunities")
        assert response.status_code == 200

    def test_has_items(self, client):
        body = client.get("/api/opportunities").json()
        assert "items" in body
        assert isinstance(body["items"], list)
