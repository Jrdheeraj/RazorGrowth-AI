"""PaymentService."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.app.integrations.razorpay import build_razorpay_client, RazorpayResult
from backend.app.models.customer import Customer
from backend.app.models.enums import CustomerSegment, OrderStatus, PaymentProvider, PaymentStatus
from backend.app.models.order import Order
from backend.app.models.payment import Payment
from backend.app.repositories.customer import CustomerRepository
from backend.app.repositories.payment import PaymentRepository
from backend.app.core.logging import get_logger
from backend.app.core.config import get_settings

log = get_logger(__name__)


class PaymentService:
    def __init__(self, db: Session) -> None:
        self._repo = PaymentRepository(db)
        self._db = db

    def list_payments(
        self,
        merchant_id: uuid.UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Payment]:
        return self._repo.list_by_merchant(
            merchant_id, limit=limit, offset=offset
        )

    def get_payment(self, payment_id: uuid.UUID) -> Payment | None:
        return self._repo.get_by_id(payment_id)

    def get_payment_by_merchant(self, merchant_id: uuid.UUID, payment_id: uuid.UUID) -> Payment | None:
        payment = self._repo.get_by_id(payment_id)
        if payment and payment.merchant_id == merchant_id:
            return payment
        return None

    def create_payment(
        self,
        *,
        merchant_id: uuid.UUID,
        order_id: uuid.UUID,
        provider: str = "synthetic",
        provider_payment_id: str | None = None,
        amount: Decimal,
        currency: str = "INR",
        status: str = "pending",
        failure_code: str | None = None,
        failure_reason: str | None = None,
    ) -> Payment:
        payment = Payment(
            merchant_id=merchant_id,
            order_id=order_id,
            provider=provider,
            provider_payment_id=provider_payment_id,
            amount=amount,
            currency=currency,
            status=status,
            failure_code=failure_code,
            failure_reason=failure_reason,
        )
        self._db.add(payment)
        self._db.flush()
        log.info("Payment created. id=%s merchant=%s order=%s amount=%s", str(payment.id), merchant_id, order_id, amount)
        return payment

    def update_payment(
        self,
        payment_id: uuid.UUID,
        *,
        provider_payment_id: str | None = None,
        status: str | None = None,
        failure_code: str | None = None,
        failure_reason: str | None = None,
    ) -> Payment | None:
        payment = self._repo.get_by_id(payment_id)
        if not payment:
            return None

        if provider_payment_id is not None:
            payment.provider_payment_id = provider_payment_id
        if status is not None:
            payment.status = status
        if failure_code is not None:
            payment.failure_code = failure_code
        if failure_reason is not None:
            payment.failure_reason = failure_reason

        self._db.flush()
        log.info("Payment updated. id=%s", str(payment_id))
        return payment

    def delete_payment(self, payment_id: uuid.UUID) -> bool:
        payment = self._repo.get_by_id(payment_id)
        if not payment:
            return False

        self._repo.delete(payment)
        self._db.flush()
        log.info("Payment deleted. id=%s", str(payment_id))
        return True

    def list_failed_payments(self, merchant_id: uuid.UUID) -> list[Payment]:
        return self._repo.list_failed_by_merchant(merchant_id)

    # ── Checkout / Razorpay TEST integration ────────────────────────────────

    def create_checkout_session(
        self,
        *,
        merchant_id: uuid.UUID,
        amount: Decimal,
        currency: str = "INR",
        description: str | None = None,
        customer_email: str | None = None,
        customer_contact: str | None = None,
        receipt: str | None = None,
        notes: dict | None = None,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a Razorpay TEST checkout session.
        
        Creates a Razorpay order and payment link for TEST MODE checkout.
        Returns the data needed by the frontend to open Razorpay Checkout.
        """
        settings = get_settings()
        
        if not settings.REAL_TEST_INTEGRATION_ENABLED:
            raise ValueError("Real Razorpay TEST integration not enabled")
        
        if not settings.RAZORPAY_ENABLED or not settings.RAZORPAY_TEST_MODE:
            raise ValueError("Razorpay TEST mode not configured")
        
        client = build_razorpay_client()
        
        # Create Razorpay order
        amount_inr = float(amount)
        order_result = client.create_order(
            amount_inr=amount_inr,
            currency=currency,
            receipt=receipt,
            notes=notes,
        )
        
        if not order_result.ok:
            raise ValueError(f"Failed to create Razorpay order: {order_result.error}")
        
        razorpay_order_id = order_result.metadata.get("order_id")
        
        # Create payment link for hosted checkout
        link_result = client.create_payment_link(
            amount_inr=amount_inr,
            currency=currency,
            description=description,
            receipt=receipt,
            notes=notes,
            callback_url=callback_url,
        )
        
        if not link_result.ok:
            raise ValueError(f"Failed to create payment link: {link_result.error}")
        
        payment_link_id = link_result.metadata.get("payment_link_id")
        short_url = link_result.metadata.get("short_url")

        if not customer_email:
            raise ValueError("customer_email is required for checkout persistence")

        customer_repo = CustomerRepository(self._db)
        customer = customer_repo.get_by_email(merchant_id, customer_email)
        if customer is None:
            customer = customer_repo.create(
                merchant_id=merchant_id,
                name=customer_email,
                email=customer_email,
                phone=customer_contact,
                segment=CustomerSegment.new,
            )
            self._db.flush()

        local_order = Order(
            merchant_id=merchant_id,
            customer_id=customer.id,
            order_number=razorpay_order_id,
            status=OrderStatus.pending,
            subtotal=amount,
            discount=Decimal("0.00"),
            tax=Decimal("0.00"),
            total=amount,
            currency=currency,
        )
        self._db.add(local_order)
        self._db.flush()
        
        return {
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_link_id": payment_link_id,
            "short_url": short_url,
            "amount": amount_inr,
            "currency": currency,
            "key_id": settings.RAZORPAY_KEY_ID,
        }

    def verify_payment_signature(
        self,
        razorpay_order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
        merchant_id: uuid.UUID,
    ) -> dict[str, Any]:
        """
        Verify Razorpay payment signature and update local payment record.
        
        The signature is generated by Razorpay using HMAC-SHA256:
        HMAC_SHA256(key_secret, order_id + "|" + payment_id)
        
        If valid, updates/creates the local payment record.
        """
        settings = get_settings()
        secret = settings.RAZORPAY_KEY_SECRET
        
        if not secret:
            log.warning("Cannot verify payment: RAZORPAY_KEY_SECRET not configured")
            return {"verified": False, "payment_id": None}
        
        expected = hmac.new(
            secret.encode("utf-8"),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        
        if not hmac.compare_digest(expected, razorpay_signature.strip().lower()):
            return {"verified": False, "payment_id": None}
        
        # Signature is valid - find or create local payment record
        # First try to find by provider_payment_id
        existing = self._repo.get_by_provider_payment_id(merchant_id, razorpay_payment_id)
        
        if existing:
            # Update existing payment
            existing.status = PaymentStatus.captured
            existing.provider_payment_id = razorpay_payment_id
            if existing.order is not None:
                existing.order.status = OrderStatus.paid
                existing.order.updated_at = datetime.now(timezone.utc)
            self._db.flush()
            log.info("Payment verified and updated. id=%s", str(existing.id))
            return {"verified": True, "payment_id": str(existing.id)}
        
        # Find order by Razorpay order ID (stored in order_number)
        from backend.app.models.order import Order
        from sqlalchemy import select
        
        order = self._db.execute(
            select(Order).where(
                Order.merchant_id == merchant_id,
                Order.order_number == razorpay_order_id,
            )
        ).scalar_one_or_none()
        
        if not order:
            raise ValueError("LOCAL_ORDER_NOT_FOUND")
        
        # Create new payment record
        payment = Payment(
            merchant_id=merchant_id,
            order_id=order.id,
            provider=PaymentProvider.razorpay,
            provider_payment_id=razorpay_payment_id,
            amount=order.total,
            currency=order.currency,
            status=PaymentStatus.captured,
            paid_at=datetime.now(timezone.utc),
        )
        self._db.add(payment)
        order.status = OrderStatus.paid
        order.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        log.info("Payment created from checkout verification. id=%s", str(payment.id))
        return {"verified": True, "payment_id": str(payment.id)}
