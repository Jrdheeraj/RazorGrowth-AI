"""
Razorpay webhook endpoint — Phase 6 Slice 8.

POST /api/webhooks/razorpay

Authentication model: HMAC signature validation (NOT bearer tokens) —
Razorpay signs each delivery with the webhook secret configured via the
RAZORPAY_WEBHOOK_SECRET environment variable.

Behaviour:
  - Missing secret configuration → 503 WEBHOOK_NOT_CONFIGURED (fail closed:
    unsigned payloads are never accepted).
  - Invalid/missing signature    → 400 INVALID_SIGNATURE.
  - Valid signature              → 200; the raw event is recorded as an
    immutable audit event. NO money movement occurs from a webhook —
    execution remains exclusively behind Guardrail #1 → Human Approval →
    Guardrail #2.

The raw body is read directly so the signature covers exact bytes.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.ratelimit import enforce_webhook_rate_limit
from backend.app.db.session import get_db
from backend.app.integrations.razorpay import verify_webhook_signature
from backend.app.models.enums import ActorType, AuditEventType
from backend.app.models.audit_event import AuditEvent

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

    event_type = "unknown"
    event_id = None
    try:
        import json

        payload = json.loads(body.decode("utf-8"))
        event_type = str(payload.get("event") or "unknown")
        event_id = payload.get("id")
    except Exception:
        payload = {}

    try:
        db.add(
            AuditEvent(
                merchant_id=None,
                actor_type=ActorType.system,
                actor_id="razorpay_webhook",
                event_type=AuditEventType.payment_created,
                entity_type="razorpay_webhook",
                entity_id=str(event_id) if event_id else None,
                payload={
                    "event": event_type,
                    "handled": "logged_only",
                    "note": "Webhooks never trigger money movement",
                },
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        log.warning("Failed to persist webhook audit event: %s", type(exc).__name__)

    return {"status": "accepted", "action": "logged_only"}


def _reject(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})
