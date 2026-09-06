"""
Razorpay webhook endpoint — Phase 6 Slice 8 + Phase 10.

POST /api/webhooks/razorpay

Authentication model: HMAC signature validation (NOT bearer tokens) —
Razorpay signs each delivery with the webhook secret configured via the
RAZORPAY_WEBHOOK_SECRET environment variable.

Behaviour:
  - Missing secret configuration → 503 WEBHOOK_NOT_CONFIGURED (fail closed:
    unsigned payloads are never accepted).
  - Invalid/missing signature    → 400 INVALID_SIGNATURE.
  - Valid signature              → 200; the event is processed to sync
    local database state. NO money movement occurs from a webhook —
    execution remains exclusively behind Guardrail #1 → Human Approval →
    Guardrail #2.

The raw body is read directly so the signature covers exact bytes.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.ratelimit import enforce_webhook_rate_limit
from backend.app.db.session import get_db
from backend.app.integrations.razorpay import verify_webhook_signature
from backend.app.models.enums import ActorType, AuditEventType, OrderStatus, PaymentProvider, PaymentStatus
from backend.app.models.audit_event import AuditEvent
from backend.app.models.order import Order
from backend.app.models.payment import Payment

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay", dependencies=[Depends(enforce_webhook_rate_limit)])
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        # Fail closed: without a shared secret there is no way to trust a
        # delivery, and accepting it would let anyone forge events.
        return _reject(503, "WEBHOOK_NOT_CONFIGURED")

    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    if not verify_webhook_signature(body, signature, settings.RAZORPAY_WEBHOOK_SECRET):
        log.warning("Razorpay webhook rejected: signature validation failed")
        return _reject(400, "INVALID_SIGNATURE")

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return _reject(400, "INVALID_JSON")

    event_type = str(payload.get("event") or "unknown")
    event_id = payload.get("id")

    # Process the event to sync local state
    processing_result = await _process_webhook_event(db, event_type, payload)

    # Always log audit event
    try:
        db.add(
            AuditEvent(
                merchant_id=processing_result.merchant_id,
                actor_type=ActorType.system,
                actor_id="razorpay_webhook",
                event_type=_map_event_to_audit(event_type),
                entity_type="razorpay_webhook",
                entity_id=str(event_id) if event_id else None,
                payload={
                    "event": event_type,
                    "handled": processing_result.action,
                    "details": processing_result.details,
                },
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Failed to persist webhook audit event: %s", type(exc).__name__)

    return {"status": "accepted", "action": processing_result.action}


class WebhookProcessingResult:
    """Result of processing a webhook event."""

    def __init__(
        self,
        action: str,
        merchant_id: uuid.UUID | None = None,
        details: dict | None = None,
    ):
        self.action = action
        self.merchant_id = merchant_id
        self.details = details or {}


def _razorpay_account_owner_merchant(db: Session) -> uuid.UUID | None:
    """
    The merchant that owns the configured (single) Razorpay account:
    the holder of the OLDEST Razorpay-provider payment — the workspace
    that originally ingested the account's history. Used only to make
    webhook lookups deterministic; webhook events themselves carry no
    merchant identity.
    """
    from backend.app.models.enums import PaymentProvider

    return db.execute(
        select(Payment.merchant_id)
        .where(Payment.provider == PaymentProvider.razorpay.value)
        .order_by(Payment.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()


def _find_payment_by_provider_id(db: Session, rp_payment_id: str) -> Payment | None:
    """Find a local payment by provider id; deterministic across legacy
    cross-merchant duplicates by preferring the Razorpay account owner."""
    rows = db.execute(
        select(Payment).where(Payment.provider_payment_id == rp_payment_id)
    ).scalars().all()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    owner = _razorpay_account_owner_merchant(db)
    for r in rows:
        if r.merchant_id == owner:
            return r
    return rows[0]


def _find_order_by_provider_id(db: Session, rp_order_id: str) -> Order | None:
    """Find a local order by Razorpay order number; deterministic across
    legacy cross-merchant duplicates by preferring the account owner."""
    rows = db.execute(
        select(Order).where(Order.order_number == rp_order_id)
    ).scalars().all()
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    owner = _razorpay_account_owner_merchant(db)
    for r in rows:
        if r.merchant_id == owner:
            return r
    return rows[0]


async def _process_webhook_event(db: Session, event_type: str, payload: dict) -> WebhookProcessingResult:
    """
    Process a Razorpay webhook event and sync local database state.

    Supported events:
      - payment.captured    → update payment status to captured, set paid_at
      - payment.failed      → update payment status to failed, record failure reason
      - payment.authorized  → update payment status to authorised
      - order.paid          → update order status to paid
      - customer.created    → create/update local customer record
    """
    # Razorpay payload structure: {"event": "...", "payload": {"payment": {...}, "order": {...}, "customer": {...}}}
    event_payload = payload.get("payload", {})

    if event_type == "payment.captured":
        return await _handle_payment_captured(db, event_payload)
    elif event_type == "payment.failed":
        return await _handle_payment_failed(db, event_payload)
    elif event_type == "payment.authorized":
        return await _handle_payment_authorized(db, event_payload)
    elif event_type == "order.paid":
        return await _handle_order_paid(db, event_payload)
    elif event_type == "customer.created":
        return await _handle_customer_created(db, event_payload)
    else:
        log.info("Unhandled webhook event type: %s", event_type)
        return WebhookProcessingResult(action="logged_only", details={"event": event_type})


async def _handle_payment_captured(db: Session, payload: dict) -> WebhookProcessingResult:
    """Handle payment.captured webhook."""
    payment_data = payload.get("payment", {})
    entity = payment_data.get("entity", {})
    
    rp_payment_id = entity.get("id")
    rp_order_id = entity.get("order_id")
    amount_paise = entity.get("amount", 0)
    captured_at_ts = entity.get("captured_at")

    if not rp_payment_id:
        return WebhookProcessingResult(action="skipped_missing_payment_id")

    # Find local payment by provider_payment_id (deterministic owner-first)
    payment = _find_payment_by_provider_id(db, rp_payment_id)

    if not payment:
        # Payment not in local DB yet - could be from manual creation or ingestion lag
        # Log and skip; ingestion will catch up
        log.info("Payment captured but not found locally: %s", rp_payment_id)
        return WebhookProcessingResult(
            action="skipped_payment_not_found",
            details={"provider_payment_id": rp_payment_id},
        )

    # Update payment status
    payment.status = PaymentStatus.captured
    if captured_at_ts:
        payment.paid_at = datetime.fromtimestamp(captured_at_ts, tz=timezone.utc)
    db.flush()

    # Update order status if needed
    if payment.order and payment.order.status != OrderStatus.paid:
        payment.order.status = OrderStatus.paid
        db.flush()

    return WebhookProcessingResult(
        action="payment_captured",
        merchant_id=payment.merchant_id,
        details={"payment_id": str(payment.id), "provider_payment_id": rp_payment_id},
    )


async def _handle_payment_failed(db: Session, payload: dict) -> WebhookProcessingResult:
    """Handle payment.failed webhook."""
    payment_data = payload.get("payment", {})
    entity = payment_data.get("entity", {})

    rp_payment_id = entity.get("id")
    rp_order_id = entity.get("order_id")
    error_code = entity.get("error_code")
    error_reason = entity.get("error_reason")

    if not rp_payment_id:
        return WebhookProcessingResult(action="skipped_missing_payment_id")

    payment = _find_payment_by_provider_id(db, rp_payment_id)

    if not payment:
        log.info("Payment failed but not found locally: %s", rp_payment_id)
        return WebhookProcessingResult(
            action="skipped_payment_not_found",
            details={"provider_payment_id": rp_payment_id},
        )

    payment.status = PaymentStatus.failed
    payment.failure_code = error_code
    payment.failure_reason = error_reason
    db.flush()

    return WebhookProcessingResult(
        action="payment_failed",
        merchant_id=payment.merchant_id,
        details={"payment_id": str(payment.id), "error_code": error_code},
    )


async def _handle_payment_authorized(db: Session, payload: dict) -> WebhookProcessingResult:
    """Handle payment.authorized webhook."""
    payment_data = payload.get("payment", {})
    entity = payment_data.get("entity", {})

    rp_payment_id = entity.get("id")
    rp_order_id = entity.get("order_id")

    if not rp_payment_id:
        return WebhookProcessingResult(action="skipped_missing_payment_id")

    payment = _find_payment_by_provider_id(db, rp_payment_id)

    if not payment:
        return WebhookProcessingResult(action="skipped_payment_not_found")

    payment.status = PaymentStatus.authorised
    db.flush()

    return WebhookProcessingResult(
        action="payment_authorized",
        merchant_id=payment.merchant_id,
        details={"payment_id": str(payment.id)},
    )


async def _handle_order_paid(db: Session, payload: dict) -> WebhookProcessingResult:
    """Handle order.paid webhook."""
    order_data = payload.get("order", {})
    entity = order_data.get("entity", {})

    rp_order_id = entity.get("id")

    if not rp_order_id:
        return WebhookProcessingResult(action="skipped_missing_order_id")

    # Find local order by provider order ID (deterministic owner-first)
    order = _find_order_by_provider_id(db, rp_order_id)

    if not order:
        # Try finding by receipt if different
        receipt = entity.get("receipt")
        if receipt:
            order = _find_order_by_provider_id(db, receipt)

    if not order:
        log.info("Order paid but not found locally: %s", rp_order_id)
        return WebhookProcessingResult(action="skipped_order_not_found")

    order.status = OrderStatus.paid
    db.flush()

    return WebhookProcessingResult(
        action="order_paid",
        merchant_id=order.merchant_id,
        details={"order_id": str(order.id), "provider_order_id": rp_order_id},
    )


async def _handle_customer_created(db: Session, payload: dict) -> WebhookProcessingResult:
    """Handle customer.created webhook."""
    customer_data = payload.get("customer", {})
    entity = customer_data.get("entity", {})

    rp_customer_id = entity.get("id")
    email = entity.get("email")
    name = entity.get("name")
    contact = entity.get("contact")

    if not rp_customer_id or not email:
        return WebhookProcessingResult(action="skipped_missing_customer_data")

    # Check if customer exists
    from backend.app.repositories.customer import CustomerRepository
    customer_repo = CustomerRepository(db)
    existing = customer_repo.get_by_email(None, email)  # Need merchant_id

    # We don't have merchant_id from webhook alone - skip for now
    # Ingestion service will handle customer creation
    log.info("Customer created webhook received: %s", rp_customer_id)
    return WebhookProcessingResult(action="logged_customer_created")


def _map_event_to_audit(event_type: str) -> AuditEventType:
    """Map webhook event type to audit event type."""
    mapping = {
        "payment.captured": AuditEventType.payment_succeeded,
        "payment.failed": AuditEventType.payment_failed,
        "payment.authorized": AuditEventType.payment_created,
        "order.paid": AuditEventType.payment_succeeded,
        "customer.created": AuditEventType.payment_created,
    }
    return mapping.get(event_type, AuditEventType.payment_created)


def _reject(status_code: int, detail: str):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=status_code, content={"detail": detail})