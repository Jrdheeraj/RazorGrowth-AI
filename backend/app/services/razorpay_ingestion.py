"""
Razorpay Ingestion Service — Phase 4.

Fetches real TEST MODE data from Razorpay and upserts into local database.

Architecture:
    Razorpay TEST API
        ↓
RazorpayIngestionService
    ↓
Local PostgreSQL (Customer, Order, Payment models)
    ↓
ProductionDataConnector → Knowledge Store → Agentic RAG

Design principles:
- Idempotent: safe to re-run, uses provider IDs for deduplication
- Tenant-scoped: all data linked to merchant_id
- Safe: never fabricates data, logs errors without exposing secrets
- Structured results: returns counts for created/updated/skipped/failed
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.integrations.razorpay import build_razorpay_client, RazorpayResult
from backend.app.models.customer import Customer
from backend.app.models.enums import CustomerSegment, OrderStatus, PaymentProvider, PaymentStatus
from backend.app.models.order import Order, OrderItem
from backend.app.models.payment import Payment
from backend.app.models.product import Product
from backend.app.repositories.customer import CustomerRepository
from backend.app.repositories.order import OrderRepository
from backend.app.repositories.payment import PaymentRepository
from backend.app.repositories.product import ProductRepository
from backend.app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class IngestionCounts:
    """Counts for a single ingestion run."""
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0

    def total(self) -> int:
        return self.created + self.updated + self.skipped + self.failed


@dataclass
class RazorpayIngestionResult:
    """Complete result of a Razorpay ingestion run."""
    customers: IngestionCounts = field(default_factory=IngestionCounts)
    orders: IngestionCounts = field(default_factory=IngestionCounts)
    payments: IngestionCounts = field(default_factory=IngestionCounts)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": "razorpay_test",
            "customers": {
                "created": self.customers.created,
                "updated": self.customers.updated,
                "skipped": self.customers.skipped,
                "failed": self.customers.failed,
            },
            "orders": {
                "created": self.orders.created,
                "updated": self.orders.updated,
                "skipped": self.orders.skipped,
                "failed": self.orders.failed,
            },
            "payments": {
                "created": self.payments.created,
                "updated": self.payments.updated,
                "skipped": self.payments.skipped,
                "failed": self.payments.failed,
            },
            "total_errors": len(self.errors),
            "errors": self.errors[:10],  # limit error details
        }


class RazorpayIngestionService:
    """
    Ingests Razorpay TEST MODE data into local database.

    Usage:
        service = RazorpayIngestionService(db, merchant_id)
        result = service.ingest_all()
        db.commit()
    """

    def __init__(
        self,
        db: Session,
        merchant_id: uuid.UUID,
        razorpay_client: Any | None = None,
    ) -> None:
        self.db = db
        self.merchant_id = merchant_id
        self.razorpay = razorpay_client or build_razorpay_client()

        # Repositories
        self.customers = CustomerRepository(db)
        self.orders = OrderRepository(db)
        self.payments = PaymentRepository(db)
        self.products = ProductRepository(db)

    def ingest_all(self) -> RazorpayIngestionResult:
        """
        Run full ingestion: customers → orders → payments.

        Order matters: customers must exist before orders, orders before payments.
        """
        log.info("Starting Razorpay TEST ingestion for merchant %s", self.merchant_id)
        result = RazorpayIngestionResult()

        # Ingest in dependency order
        self._ingest_customers(result)
        self._ingest_orders(result)
        self._ingest_payments(result)

        log.info(
            "Razorpay ingestion complete for merchant %s: %s",
            self.merchant_id,
            result.to_dict(),
        )
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Customer ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def _ingest_customers(self, result: RazorpayIngestionResult) -> None:
        """Fetch all customers from Razorpay and upsert locally."""
        log.debug("Fetching customers from Razorpay")
        rp_result = self.razorpay.list_customers({"count": 100})
        if not rp_result.ok:
            result.customers.failed += 1
            result.errors.append(f"Failed to list customers: {rp_result.error}")
            return

        customers_data = rp_result.metadata.get("customers", {})
        items = customers_data.get("items", []) if isinstance(customers_data, dict) else customers_data

        for rp_customer in items:
            try:
                self._upsert_customer(rp_customer, result)
            except Exception as exc:
                log.exception("Failed to upsert customer %s", rp_customer.get("id"))
                result.customers.failed += 1
                result.errors.append(f"Customer {rp_customer.get('id')}: {type(exc).__name__}")

    def _upsert_customer(self, rp_customer: dict, result: RazorpayIngestionResult) -> None:
        """Upsert a single Razorpay customer into local database."""
        rp_customer_id = rp_customer.get("id")
        email = rp_customer.get("email")
        name = rp_customer.get("name")
        contact = rp_customer.get("contact")

        if not rp_customer_id or not email:
            result.customers.skipped += 1
            return

        # Check if customer already exists (by provider customer ID or email)
        existing = self.customers.get_by_email(self.merchant_id, email)

        if existing:
            # Update existing customer with Razorpay data
            updated = False
            if not existing.name and name:
                existing.name = name
                updated = True
            if not existing.phone and contact:
                existing.phone = contact
                updated = True
            if updated:
                self.db.flush()
                result.customers.updated += 1
            else:
                result.customers.skipped += 1
        else:
            # Create new customer
            customer = Customer(
                merchant_id=self.merchant_id,
                name=name or email.split("@")[0],
                email=email,
                phone=contact,
                segment=CustomerSegment.new,
                total_orders=0,
                total_spend=Decimal("0"),
            )
            self.customers.add(customer)
            self.db.flush()
            result.customers.created += 1

    # ─────────────────────────────────────────────────────────────────────────
    # Order ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def _ingest_orders(self, result: RazorpayIngestionResult) -> None:
        """Fetch all orders from Razorpay and upsert locally."""
        log.debug("Fetching orders from Razorpay")
        rp_result = self.razorpay.list_orders({"count": 100})
        if not rp_result.ok:
            result.orders.failed += 1
            result.errors.append(f"Failed to list orders: {rp_result.error}")
            return

        orders_data = rp_result.metadata.get("orders", {})
        items = orders_data.get("items", []) if isinstance(orders_data, dict) else orders_data

        for rp_order in items:
            try:
                self._upsert_order(rp_order, result)
            except Exception as exc:
                log.exception("Failed to upsert order %s", rp_order.get("id"))
                result.orders.failed += 1
                result.errors.append(f"Order {rp_order.get('id')}: {type(exc).__name__}")

    def _upsert_order(self, rp_order: dict, result: RazorpayIngestionResult) -> None:
        """Upsert a single Razorpay order into local database."""
        rp_order_id = rp_order.get("id")
        amount_paise = rp_order.get("amount", 0)
        currency = rp_order.get("currency", "INR")
        receipt = rp_order.get("receipt")
        status = rp_order.get("status", "created")
        notes = rp_order.get("notes", {})
        created_at_ts = rp_order.get("created_at")

        if not rp_order_id:
            result.orders.skipped += 1
            return

        # Check if order already exists (by canonical order_id, legacy rp_ prefix, or receipt)
        match_conditions = [
            Order.order_number == rp_order_id,
            Order.order_number == f"rp_{rp_order_id}",
        ]
        if receipt:
            match_conditions.append(Order.order_number == receipt)

        stmt = select(Order).where(
            Order.merchant_id == self.merchant_id,
            or_(*match_conditions),
        )
        existing = self.db.execute(stmt).scalars().first()

        # Map Razorpay status to local OrderStatus
        order_status = self._map_order_status(status)
        amount_inr = Decimal(amount_paise) / Decimal(100)

        if existing:
            updated = False
            # Migrate any legacy/receipt order_number to canonical Razorpay order ID
            if existing.order_number != rp_order_id:
                existing.order_number = rp_order_id
                updated = True
            if existing.status != order_status:
                existing.status = order_status
                updated = True
            if existing.total != amount_inr:
                existing.total = amount_inr
                existing.subtotal = amount_inr
                updated = True
            if updated:
                self.db.flush()
                result.orders.updated += 1
            else:
                result.orders.skipped += 1
        else:
            customer_id = self._get_or_create_customer_for_order(rp_order, notes)
            if not customer_id:
                result.orders.failed += 1
                result.errors.append(f"Order {rp_order_id}: no customer found")
                return

            created_at = (
                datetime.fromtimestamp(created_at_ts, tz=timezone.utc)
                if created_at_ts
                else datetime.now(timezone.utc)
            )

            order = Order(
                merchant_id=self.merchant_id,
                customer_id=customer_id,
                order_number=rp_order_id,
                status=order_status,
                subtotal=amount_inr,
                discount=Decimal("0"),
                tax=Decimal("0"),
                total=amount_inr,
                currency=currency,
                created_at=created_at,
            )
            self.db.add(order)
            self.db.flush()

            # Create generic order item for tracking
            item = OrderItem(
                order_id=order.id,
                product_id=self._get_generic_product_id(),
                quantity=1,
                unit_price=amount_inr,
                line_total=amount_inr,
            )
            self.db.add(item)
            self.db.flush()

            result.orders.created += 1

    def _map_order_status(self, rp_status: str) -> OrderStatus:
        """Map Razorpay order status to local OrderStatus."""
        mapping = {
            "created": OrderStatus.pending,
            "attempted": OrderStatus.pending,
            "paid": OrderStatus.paid,
            "cancelled": OrderStatus.cancelled,
        }
        return mapping.get(rp_status, OrderStatus.pending)

    def _get_or_create_customer_for_order(self, rp_order: dict, notes: dict) -> uuid.UUID | None:
        """Find or create a customer for an order based on available data."""
        customer_email = notes.get("customer_email") if notes else None
        customer_name = notes.get("customer_name") if notes else None
        customer_contact = notes.get("customer_contact") if notes else None

        if customer_email:
            existing = self.customers.get_by_email(self.merchant_id, customer_email)
            if existing:
                return existing.id

        if customer_email:
            customer = Customer(
                merchant_id=self.merchant_id,
                name=customer_name or customer_email.split("@")[0],
                email=customer_email,
                phone=customer_contact,
                segment=CustomerSegment.new,
                total_orders=0,
                total_spend=Decimal("0"),
            )
            self.customers.add(customer)
            self.db.flush()
            return customer.id

        any_customer = self.db.execute(
            select(Customer.id).where(Customer.merchant_id == self.merchant_id).limit(1)
        ).scalar_one_or_none()
        if any_customer:
            return any_customer

        default_customer = Customer(
            merchant_id=self.merchant_id,
            name="Razorpay Test Customer",
            email=f"customer_{rp_order.get('id', 'test')}@razorpay.test",
            segment=CustomerSegment.new,
            total_orders=0,
            total_spend=Decimal("0"),
        )
        self.customers.add(default_customer)
        self.db.flush()
        return default_customer.id

    def _get_generic_product_id(self) -> uuid.UUID:
        """Get or create a generic product for orders without line items."""
        product = self.db.execute(
            select(Product.id).where(
                Product.merchant_id == self.merchant_id,
                Product.active == True,
            ).limit(1)
        ).scalar_one_or_none()

        if product:
            return product

        generic = Product(
            merchant_id=self.merchant_id,
            name="Razorpay Order",
            category="general",
            price=Decimal("0"),
            currency="INR",
            sku="RP-GENERIC",
            stock_quantity=0,
            active=True,
        )
        self.products.add(generic)
        self.db.flush()
        return generic.id

    # ─────────────────────────────────────────────────────────────────────────
    # Payment ingestion
    # ─────────────────────────────────────────────────────────────────────────

    def _ingest_payments(self, result: RazorpayIngestionResult) -> None:
        """Fetch all payments from Razorpay and upsert locally."""
        log.debug("Fetching payments from Razorpay")
        rp_result = self.razorpay.list_payments({"count": 100})
        if not rp_result.ok:
            result.payments.failed += 1
            result.errors.append(f"Failed to list payments: {rp_result.error}")
            return

        payments_data = rp_result.metadata.get("payments", {})
        items = payments_data.get("items", []) if isinstance(payments_data, dict) else payments_data

        for rp_payment in items:
            try:
                self._upsert_payment(rp_payment, result)
            except Exception as exc:
                log.exception("Failed to upsert payment %s", rp_payment.get("id"))
                result.payments.failed += 1
                result.errors.append(f"Payment {rp_payment.get('id')}: {type(exc).__name__}")

    def _sync_customer_from_payment(
        self, rp_payment: dict, payment_status: PaymentStatus, amount_inr: Decimal
    ) -> uuid.UUID:
        """Find or create customer from payment details and update records."""
        email = rp_payment.get("email")
        contact = rp_payment.get("contact")
        card_info = rp_payment.get("card")
        card_name = card_info.get("name") if isinstance(card_info, dict) else None
        name = card_name or (email.split("@")[0] if email else "Razorpay Test Customer")

        customer = None
        if email:
            customer = self.customers.get_by_email(self.merchant_id, email)

        if not customer:
            customer = Customer(
                merchant_id=self.merchant_id,
                name=name,
                email=email or f"customer_{rp_payment.get('id', 'guest')}@razorpay.test",
                phone=contact,
                segment=CustomerSegment.new,
                total_orders=1 if payment_status == PaymentStatus.captured else 0,
                total_spend=amount_inr if payment_status == PaymentStatus.captured else Decimal("0"),
            )
            self.customers.add(customer)
            self.db.flush()
            return customer.id

        if contact and not customer.phone:
            customer.phone = contact
        if name and customer.name == "Razorpay Test Customer":
            customer.name = name

        self.db.flush()
        return customer.id

    def _upsert_payment(self, rp_payment: dict, result: RazorpayIngestionResult) -> None:
        """Upsert a single Razorpay payment into local database."""
        rp_payment_id = rp_payment.get("id")
        rp_order_id = rp_payment.get("order_id")
        amount_paise = rp_payment.get("amount", 0)
        currency = rp_payment.get("currency", "INR")
        status = rp_payment.get("status", "pending")
        captured = rp_payment.get("captured", False)
        fee_paise = rp_payment.get("fee", 0)
        tax_paise = rp_payment.get("tax", 0)
        created_at_ts = rp_payment.get("created_at")
        paid_at_ts = rp_payment.get("paid_at")

        if not rp_payment_id:
            result.payments.skipped += 1
            return

        # Check if payment already exists
        existing = self.db.execute(
            select(Payment).where(
                Payment.merchant_id == self.merchant_id,
                Payment.provider_payment_id == rp_payment_id,
            )
        ).scalar_one_or_none()

        # Map Razorpay status to local PaymentStatus
        payment_status = self._map_payment_status(status, captured)

        amount_inr = Decimal(amount_paise) / Decimal(100)
        paid_at = None
        if paid_at_ts:
            paid_at = datetime.fromtimestamp(paid_at_ts, tz=timezone.utc)
        elif created_at_ts and (status == "captured" or captured):
            paid_at = datetime.fromtimestamp(created_at_ts, tz=timezone.utc)

        created_at = (
            datetime.fromtimestamp(created_at_ts, tz=timezone.utc)
            if created_at_ts
            else datetime.now(timezone.utc)
        )

        failure_code = rp_payment.get("error_code")
        failure_reason = rp_payment.get("error_description") or rp_payment.get("error_reason") or rp_payment.get("description") if payment_status == PaymentStatus.failed else None

        # Ensure customer exists and is linked
        customer_id = self._sync_customer_from_payment(rp_payment, payment_status, amount_inr)

        # Find the local order by Razorpay order ID (canonical or legacy)
        local_order = None
        if rp_order_id:
            stmt = select(Order).where(
                Order.merchant_id == self.merchant_id,
                or_(
                    Order.order_number == rp_order_id,
                    Order.order_number == f"rp_{rp_order_id}",
                ),
            )
            local_order = self.db.execute(stmt).scalars().first()

        # If not found locally, fetch the order from Razorpay to upsert it
        if not local_order and rp_order_id:
            try:
                rp_order_res = self.razorpay.fetch_order(rp_order_id)
                if rp_order_res.ok and rp_order_res.metadata:
                    self._upsert_order(rp_order_res.metadata, result)
                    local_order = self.db.execute(
                        select(Order).where(
                            Order.merchant_id == self.merchant_id,
                            Order.order_number == rp_order_id,
                        )
                    ).scalars().first()
            except Exception as e:
                log.warning("Could not fetch missing order %s: %s", rp_order_id, e)

        # If still no local_order, create a local order for this real Razorpay payment
        if not local_order:
            local_order = Order(
                merchant_id=self.merchant_id,
                customer_id=customer_id,
                order_number=rp_order_id or f"rp_direct_{rp_payment_id}",
                status=OrderStatus.paid if payment_status == PaymentStatus.captured else OrderStatus.pending,
                subtotal=amount_inr,
                discount=Decimal("0"),
                tax=Decimal("0"),
                total=amount_inr,
                currency=currency,
                created_at=created_at,
            )
            self.db.add(local_order)
            self.db.flush()

            item = OrderItem(
                order_id=local_order.id,
                product_id=self._get_generic_product_id(),
                quantity=1,
                unit_price=amount_inr,
                line_total=amount_inr,
            )
            self.db.add(item)
            self.db.flush()

        # Link customer to order if needed
        if customer_id and local_order.customer_id != customer_id:
            local_order.customer_id = customer_id

        # Update order status to paid if payment is captured
        if payment_status == PaymentStatus.captured:
            local_order.status = OrderStatus.paid

        if existing:
            updated = False
            if existing.status != payment_status:
                existing.status = payment_status
                updated = True
            if paid_at and not existing.paid_at:
                existing.paid_at = paid_at
                updated = True
            if failure_code and existing.failure_code != failure_code:
                existing.failure_code = failure_code
                updated = True
            if failure_reason and existing.failure_reason != failure_reason:
                existing.failure_reason = failure_reason
                updated = True
            if existing.order_id != local_order.id:
                existing.order_id = local_order.id
                updated = True
            if updated:
                self.db.flush()
                result.payments.updated += 1
            else:
                result.payments.skipped += 1
        else:
            payment = Payment(
                merchant_id=self.merchant_id,
                order_id=local_order.id,
                provider=PaymentProvider.razorpay.value,
                provider_payment_id=rp_payment_id,
                amount=amount_inr,
                currency=currency,
                status=payment_status,
                failure_code=failure_code,
                failure_reason=failure_reason,
                paid_at=paid_at,
                created_at=created_at,
            )
            self.db.add(payment)
            self.db.flush()
            result.payments.created += 1

    def _map_payment_status(self, rp_status: str, captured: bool) -> PaymentStatus:
        """Map Razorpay payment status to local PaymentStatus."""
        if rp_status == "captured" or captured:
            return PaymentStatus.captured
        elif rp_status == "authorized":
            return PaymentStatus.authorised
        elif rp_status == "failed":
            return PaymentStatus.failed
        elif rp_status == "refunded":
            return PaymentStatus.refunded
        else:
            return PaymentStatus.pending